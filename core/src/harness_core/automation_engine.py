"""Motor das automações (v0.9.0): roda o desenho passo a passo e guarda cada execução.

- Camadas pelo caminho mais longo a partir do gatilho; o que está na mesma camada roda junto.
- Um passo roda se alguma ligação que chega nele está viva (a origem deu ok e, se for
  condição, o ramo bate); senão fica "pulado".
- Teste roda o RASCUNHO com ensaio: ferramenta que fala com outras pessoas não é chamada, o
  que ela faria vai para a DM do Pedro; dados fixados num passo substituem a chamada; esperar
  vira 3 segundos. Produção roda só a PUBLICADA.
- Ferramenta chama a central de MCP direto (sem agente e sem cota), com a aprovação e o log
  da Atividade de sempre. Agente abre um terminal interativo de verdade (claude ou codex, pelo
  plano), com MCP só com as ferramentas liberadas e a `saida`, por onde o resultado volta e é
  conferido contra o formato combinado (até 2 pedidos de correção; depois, erro).
- Erro nunca calado: execução vermelha, evento para a tela e, em produção, DM no Slack.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from .agents import Agent, AgentError, AgentStore
from .automations import (
    TRIGGER_ID,
    AutomationError,
    AutomationStore,
    check_output,
    validate,
    count_items,
    downstream,
    evaluate_rule,
    layers,
    make_scope,
    render,
)
from .brain_index import BrainIndex
from .kanban import Kanban
from .mcp_hub import Context, Hub
from .routines import decide
from .vault import Vault, VaultError

AGENT_SLOTS = 2  # no Mac Intel, no máximo 2 agentes de automação ao mesmo tempo
DEFAULT_AGENT_MINUTES = 20
MAX_NUDGES = 2
KEEP_RUNS = 200
DAILY_SECTION = "🛠️ Registro de trabalho"
DAILY_BEFORE = ("## 🧠 Aprendi hoje", "## 🌙 Noite")

OUTPUT_HELP = {"texto": "texto", "numero": "número", "lista": "lista", "objeto": "objeto", "sim/nao": "true ou false"}


class StepError(RuntimeError):
    pass


class StepRefused(RuntimeError):
    pass


@dataclass
class RunState:
    id: int
    automation: str
    flow: dict
    mode: str
    task: asyncio.Task | None = None
    sessions: set[str] = field(default_factory=set)


@dataclass
class Waiter:
    run: int
    step: str
    shape: dict
    future: asyncio.Future
    attempts: int = 0
    nudges: int = 0


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


class Engine:
    def __init__(
        self,
        home: Path,
        store: AutomationStore,
        hub: Hub,
        manager,
        brain: BrainIndex,
        kanban: Kanban,
        vault: Vault,
        agents: AgentStore,
        notify: Callable[[str], str] = lambda _text: "sem Slack",
        publish: Callable[[dict], None] = lambda _event: None,
    ) -> None:
        self.db = home / "automacoes.db"
        self.store = store
        self.hub = hub
        self.manager = manager
        self.brain = brain
        self.kanban = kanban
        self.vault = vault
        self.agents = agents
        self.notify = notify
        self.publish = publish
        self.runs: dict[int, RunState] = {}
        self.waiters: dict[str, Waiter] = {}
        self._slots: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        hub.output_handler = self.receive_output
        home.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(
                """
                create table if not exists runs(id integer primary key, automation text, mode text, origem text, versao text,
                    status text, started real, ended real, error text, nota text, flow text);
                create index if not exists runs_automation on runs(automation, id);
                create table if not exists steps(run integer, step text, status text, started real, ended real,
                    entrada text, saida text, itens integer, erro text, nota text, sessao text, primary key(run, step));
                create table if not exists estado(automation text primary key, ativa integer default 0, ultima_hora real, desde real);
                """
            )
            if "sessao" not in {r[1] for r in con.execute("pragma table_info(steps)")}:
                con.execute("alter table steps add column sessao text")
            # O núcleo caiu no meio de uma execução: ela não volta, fica registrada como interrompida.
            con.execute("update runs set status = 'interrompida', ended = coalesce(ended, ?) where status in ('rodando', 'esperando')", (time.time(),))

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    # --- estado da automação (ativa, última hora tratada) -----------------------------------

    def state(self, automation_id: str) -> dict:
        with self._connect() as con:
            row = con.execute("select * from estado where automation = ?", (automation_id,)).fetchone()
        return dict(row) if row else {"automation": automation_id, "ativa": 0, "ultima_hora": None, "desde": None}

    def set_active(self, automation_id: str, active: bool) -> dict:
        if active and self.store.published(automation_id) is None:
            raise AutomationError("publique a automação antes de ativar: o motor só roda a publicada")
        now = time.time()
        with self._connect() as con:
            con.execute(
                "insert into estado(automation, ativa, desde) values (?, ?, ?) "
                "on conflict(automation) do update set ativa = excluded.ativa, desde = case when excluded.ativa = 1 then excluded.desde else estado.desde end",
                (automation_id, int(active), now),
            )
        return self.state(automation_id)

    # --- leitura das execuções ----------------------------------------------------------------

    def run(self, run_id: int) -> dict:
        with self._connect() as con:
            row = con.execute("select * from runs where id = ?", (run_id,)).fetchone()
            steps = con.execute("select * from steps where run = ?", (run_id,)).fetchall()
        if row is None:
            raise AutomationError("execução não encontrada")
        item = dict(row)
        item["flow"] = _load(item["flow"])
        item["steps"] = {
            s["step"]: {**dict(s), "entrada": _load(s["entrada"]), "saida": _load(s["saida"])} for s in steps
        }
        return item

    def list_runs(self, automation_id: str, limit: int = 50) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "select id, automation, mode, origem, versao, status, started, ended, error, nota from runs where automation = ? order by id desc limit ?",
                (automation_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def last_run(self, automation_id: str) -> dict | None:
        runs = self.list_runs(automation_id, 1)
        return runs[0] if runs else None

    # --- gravação ---------------------------------------------------------------------------------

    def _new_run(self, automation_id: str, flow: dict, mode: str, origem: str, versao: str) -> int:
        with self._connect() as con:
            run_id = con.execute(
                "insert into runs(automation, mode, origem, versao, status, started, flow) values (?,?,?,?,?,?,?)",
                (automation_id, mode, origem, versao, "rodando", time.time(), _json(flow)),
            ).lastrowid
            # Só as últimas KEEP_RUNS execuções de cada automação ficam guardadas.
            old = [r[0] for r in con.execute("select id from runs where automation = ? order by id desc limit -1 offset ?", (automation_id, KEEP_RUNS))]
            for rid in old:
                con.execute("delete from steps where run = ?", (rid,))
                con.execute("delete from runs where id = ?", (rid,))
        return run_id

    def _save_step(self, run_id: int, step_id: str, **values: Any) -> None:
        cols = {"status", "started", "ended", "entrada", "saida", "itens", "erro", "nota", "sessao"}
        data = {k: (_json(v) if k in ("entrada", "saida") else v) for k, v in values.items() if k in cols}
        with self._connect() as con:
            con.execute("insert or ignore into steps(run, step) values (?, ?)", (run_id, step_id))
            if data:
                con.execute(f"update steps set {', '.join(f'{k} = ?' for k in data)} where run = ? and step = ?", (*data.values(), run_id, step_id))
        state = self.runs.get(run_id)
        self.publish({"type": "automation.step", "run": run_id, "automation": state.automation if state else None, "step": step_id,
                      **{k: values[k] for k in ("status", "itens", "erro", "nota", "sessao") if k in values}})  # fmt: skip

    def _finish(self, state: RunState, status: str, error: str = "", note: str = "") -> None:
        with self._connect() as con:
            con.execute("update runs set status = ?, ended = ?, error = ?, nota = ? where id = ?", (status, time.time(), error, note, state.id))
        self.runs.pop(state.id, None)
        self.publish({"type": "automation.run", "run": state.id, "automation": state.automation, "status": status, "mode": state.mode, "error": error})
        if status == "erro" and state.mode == "producao":
            self.notify(f"⚠️ A automação {state.flow['nome']} falhou: {error[:300]}. Na MÊTIS, Automações → Execuções tem Pedir conserto.")

    # --- partida ---------------------------------------------------------------------------------

    async def start(self, automation_id: str, mode: str = "teste", origem: str = "manual", desde: str | None = None,
                    base_run: int | None = None, only: str | None = None) -> int:  # fmt: skip
        """Começa uma execução em segundo plano e devolve o número dela."""
        self._loop = asyncio.get_running_loop()
        if self._slots is None:
            self._slots = asyncio.Semaphore(AGENT_SLOTS)
        if mode == "producao":
            flow = self.store.published(automation_id)
            if flow is None:
                raise AutomationError("a automação ainda não foi publicada")
            versions = self.store.versions(automation_id)
            versao = f"v{versions[0]['number']}" if versions else "publicada"
        else:
            flow, versao = self.store.draft(automation_id), "rascunho"
        flow = validate(flow, strict=True)  # o rascunho pode ter passo pela metade; para rodar, não
        ids = {s["id"] for s in flow["passos"]}
        for target in (desde, only):
            if target is not None and target not in ids:
                raise AutomationError(f"passo não encontrado: {target}")
        prefill: dict[str, dict] = {}
        if desde is not None or only is not None:
            source = self.run(base_run) if base_run else self._latest_with_outputs(automation_id)
            if source is None:
                raise AutomationError("rode a automação uma vez antes: o passo precisa das entradas guardadas")
            keep = (set(ids) | {TRIGGER_ID}) - (downstream(flow, desde) if desde else {only})
            prefill = {sid: data for sid, data in source["steps"].items() if sid in keep}
        run_id = self._new_run(automation_id, flow, mode, origem, versao)
        state = RunState(run_id, automation_id, flow, mode)
        self.runs[run_id] = state
        targets = downstream(flow, desde) if desde else ({only} if only else set(ids))
        state.task = asyncio.create_task(self._execute(state, prefill, targets, origem))
        self.publish({"type": "automation.run", "run": run_id, "automation": automation_id, "status": "rodando", "mode": mode})
        return run_id

    def _latest_with_outputs(self, automation_id: str) -> dict | None:
        for item in self.list_runs(automation_id, 10):
            full = self.run(item["id"])
            if any(s.get("status") == "ok" for s in full["steps"].values()):
                return full
        return None

    async def cancel(self, run_id: int) -> bool:
        state = self.runs.get(run_id)
        if state is None or state.task is None:
            return False
        state.task.cancel()
        return True

    # --- execução ----------------------------------------------------------------------------------

    async def _execute(self, state: RunState, prefill: dict[str, dict], targets: set[str], origem: str) -> None:
        flow = state.flow
        now = datetime.now().astimezone()
        outputs: dict[str, Any] = {}
        status: dict[str, str] = {}
        trigger_out = {"hoje": now.date().isoformat(), "agora": now.isoformat(timespec="minutes"), "origem": origem, "modo": state.mode}
        for sid, data in prefill.items():
            outputs[sid], status[sid] = data.get("saida"), data.get("status") or "ok"
            self._save_step(state.id, sid, status=status[sid], saida=outputs[sid], entrada=data.get("entrada"),
                            itens=data.get("itens") or 0, nota="guardado da execução anterior", started=data.get("started"), ended=data.get("ended"))  # fmt: skip
        if TRIGGER_ID not in status:
            outputs[TRIGGER_ID], status[TRIGGER_ID] = trigger_out, "ok"
            self._save_step(state.id, TRIGGER_ID, status="ok", saida=trigger_out, itens=1, started=time.time(), ended=time.time())
        steps = {s["id"]: s for s in flow["passos"]}
        refused = False
        try:
            for layer in layers(flow)[1:]:
                batch = []
                for sid in layer:
                    if sid not in targets or sid not in steps:
                        continue
                    live = self._live_inputs(flow, sid, status, outputs)
                    if live is None and len(targets) > 1:
                        status[sid] = "pulado"
                        self._save_step(state.id, sid, status="pulado", nota="nenhum caminho chegou aqui")
                        continue
                    batch.append((steps[sid], live or {}))
                if not batch:
                    continue
                results = await asyncio.gather(*(self._run_step(state, step, inputs, outputs) for step, inputs in batch))
                for (step, _inputs), (result_status, value) in zip(batch, results):
                    status[step["id"]] = result_status
                    if result_status == "ok":
                        outputs[step["id"]] = value
                errors = [step for (step, _), (st, _) in zip(batch, results) if st == "erro"]
                if errors:
                    first = errors[0]
                    raise StepError(f"{first['titulo']}: {self._step_error(state.id, first['id'])}")
                refused = refused or any(st == "recusado" for st, _ in results)
        except asyncio.CancelledError:
            self._close_sessions(state, keep=True)
            self._finish(state, "cancelada", note="parada por você")
            return
        except StepError as exc:
            self._finish(state, "erro", error=str(exc))
            return
        except Exception as exc:  # nunca calado: o motor marca erro e segue vivo
            self._finish(state, "erro", error=f"erro interno do motor: {exc}")
            return
        for sid in targets:
            if sid in steps and sid not in status:
                self._save_step(state.id, sid, status="pulado", nota="não está ligado ao gatilho")
        self._finish(state, "recusada" if refused else "ok", note="parou numa aprovação recusada" if refused else "")

    def _step_error(self, run_id: int, step_id: str) -> str:
        with self._connect() as con:
            row = con.execute("select erro from steps where run = ? and step = ?", (run_id, step_id)).fetchone()
        return (row["erro"] if row else "") or "erro"

    @staticmethod
    def _live_inputs(flow: dict, sid: str, status: dict[str, str], outputs: dict[str, Any]) -> Any:
        """A entrada do passo (a saída de quem chega vivo nele), ou None se nenhum caminho chegou."""
        titles = {TRIGGER_ID: "gatilho"} | {s["id"]: s["titulo"] for s in flow["passos"]}
        live = []
        for e in flow["ligacoes"]:
            if e["para"] != sid or status.get(e["de"]) != "ok":
                continue
            value = outputs.get(e["de"])
            if e.get("ramo") and not (isinstance(value, dict) and value.get("ramo") == e["ramo"]):
                continue
            live.append(e["de"])
        if not live:
            return None
        if len(live) == 1:
            return outputs.get(live[0])
        return {titles[s]: outputs.get(s) for s in live}

    async def _run_step(self, state: RunState, step: dict, inputs: Any, outputs: dict[str, Any]) -> tuple[str, Any]:
        sid = step["id"]
        started = time.time()
        self._save_step(state.id, sid, status="rodando", entrada=inputs, started=started, erro=None, nota=None)
        scope = make_scope(state.flow, outputs, entrada=inputs)
        note = ""
        try:
            if step.get("desligado"):
                value, note = inputs, "desligado: os dados passaram direto"
            elif state.mode == "teste" and step.get("fixado") is not None:
                value, note = step["fixado"], "dados fixados (teste)"
            else:
                value, note = await self._dispatch(state, step, scope, inputs)
        except StepRefused as exc:
            self._save_step(state.id, sid, status="recusado", ended=time.time(), nota=str(exc))
            return "recusado", None
        except asyncio.CancelledError:
            self._save_step(state.id, sid, status="erro", ended=time.time(), erro="parada por você")
            raise
        except (StepError, AutomationError, VaultError, AgentError, OSError, ValueError, KeyError) as exc:
            self._save_step(state.id, sid, status="erro", ended=time.time(), erro=str(exc) or exc.__class__.__name__)
            return "erro", None
        self._save_step(state.id, sid, status="ok", ended=time.time(), saida=value, itens=count_items(value), nota=note or None)
        return "ok", value

    async def _dispatch(self, state: RunState, step: dict, scope: dict, inputs: Any) -> tuple[Any, str]:
        kind = step["tipo"]
        if kind == "ferramenta":
            return await self._tool(state, step, scope)
        if kind == "agente":
            return await self._agent(state, step, scope)
        if kind == "condicao":
            result = evaluate_rule(str(step["regra"]), scope)
            return {"resultado": result, "ramo": "sim" if result else "não", "entrada": inputs}, f"ramo {'sim' if result else 'não'}"
        if kind == "aprovacao":
            message = str(render(step.get("mensagem") or f"Seguir com a automação {state.flow['nome']}?", scope))
            minutes = float(step.get("prazo_min") or 60)
            self._save_step(state.id, step["id"], status="esperando", nota="esperando você")
            verdict = await self.hub.ask(f"automacao-{state.id}", f"⚙️ {state.flow['nome']}", "aprovação", state.flow["nome"], message[:600], {}, minutes * 60)
            if verdict != "aprovado":
                raise StepRefused("recusada por você" if verdict == "recusado" else f"sem resposta em {minutes:g} min")
            return inputs, "aprovado por você"
        if kind == "brain":
            return await asyncio.to_thread(self._brain, state, step, scope)
        if kind == "esperar":
            seconds = float(step["minutos"]) * 60
            if state.mode == "teste":
                await asyncio.sleep(min(seconds, 3))
                return inputs, f"teste: esperou {min(seconds, 3):g} s no lugar de {step['minutos']:g} min"
            await asyncio.sleep(seconds)
            return inputs, f"esperou {step['minutos']:g} min"
        raise StepError(f"tipo de passo desconhecido: {kind}")

    # --- ferramenta ---------------------------------------------------------------------------------

    async def _tool(self, state: RunState, step: dict, scope: dict) -> tuple[Any, str]:
        name = str(step["ferramenta"])
        args = render(step.get("argumentos") or {}, scope)
        if not isinstance(args, dict):
            raise StepError("os argumentos da ferramenta precisam ser um objeto")
        ctx = Context(session=f"automacao-{state.id}", who=f"⚙️ {state.flow['nome']}", cwd=None, allowed=None)
        tool = await asyncio.to_thread(self.hub.find_tool, ctx, name)
        if tool is None:
            raise StepError(f"a ferramenta {name} não existe ou a conta dela foi desligada em Conectores")
        if state.mode == "teste" and tool.write:
            sent = await asyncio.to_thread(self.notify, f"🧪 Ensaio de {state.flow['nome']} · {step['titulo']}: ia chamar {name} com {_json(args)[:900]}")
            return {"ensaio": True, "ferramenta": name, "argumentos": args}, f"ensaio: não chamou ({sent or 'foi para a sua DM'})"
        account = next((a for a in self.hub.connectors.list() if a.id == tool.account), None)
        if tool.write and (account.approve_writes if account else True):
            self._save_step(state.id, step["id"], status="esperando", nota="esperando sua aprovação")
        payload = await self.hub.call(ctx, name, args)
        texts = [c.get("text", "") for c in payload.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]
        text = "\n".join(texts).strip()
        if payload.get("isError"):
            raise StepError(text or "a ferramenta devolveu erro")
        if payload.get("structuredContent") is not None:
            return payload["structuredContent"], ""
        try:
            parsed = json.loads(text)
            return parsed, ""
        except ValueError:
            return {"texto": text}, ""

    # --- Brain ----------------------------------------------------------------------------------------

    def _brain(self, state: RunState, step: dict, scope: dict) -> tuple[Any, str]:
        action = step["acao"]
        get = lambda key: str(render(step.get(key) or "", scope) or "").strip()  # noqa: E731
        if action == "buscar":
            tipo = [t for t in get("tipos").split(",") if t]
            return self.brain.search(get("termos"), tipo or None, get("projeto") or None, int(step.get("limite") or 10)), ""
        if action == "ler":
            note = self.brain.note(title=get("nota"))
            return {k: note[k] for k in ("title", "path", "tipo", "projeto", "status", "data", "resumo", "meta", "body")}, ""
        if action == "precedentes":
            project, terms = get("projeto"), get("termos")
            context = terms or (self.brain.project_context(project) if project else "")
            return self.brain.precedents(project or None, context, int(step.get("limite") or 6), free_text=bool(terms), wait=20.0), ""
        if action == "tarefas":
            return [t for t in self.kanban.tasks(get("projeto")) if t["state"] != "concluida"], ""
        if action == "diario":
            now = datetime.now().astimezone()
            line = f"- {now:%H:%M} · ⚙️ {state.flow['nome']} · {get('texto')}"
            if state.mode == "teste":
                return {"ensaio": True, "linha": line}, "ensaio: a linha não foi gravada"
            path = self.vault.append_daily(now.date().isoformat(), DAILY_SECTION, line, DAILY_BEFORE)
            return {"linha": line, "nota": self.vault.rel(path)}, ""
        raise StepError(f"ação do Brain desconhecida: {action}")

    # --- agente ----------------------------------------------------------------------------------------

    def _agent_prompt(self, state: RunState, step: dict, scope: dict) -> str:
        request = str(render(step["pedido"], scope))
        shape = step.get("saida") or {}
        lines = [f"[Automação da MÊTIS · {state.flow['nome']} · passo \"{step['titulo']}\"{' · TESTE EM ENSAIO' if state.mode == 'teste' else ''}]", "", request, ""]
        if shape:
            fields = ", ".join(f"{k} ({OUTPUT_HELP[v]})" for k, v in shape.items())
            lines.append(f"Quando terminar, chame a ferramenta `saida` do servidor MCP metis com dados = um objeto JSON com: {fields}.")
        else:
            lines.append("Quando terminar, chame a ferramenta `saida` do servidor MCP metis com dados = um objeto JSON com o resultado.")
        lines.append("Não termine sem chamar `saida`. Use só as ferramentas liberadas para este passo.")
        if state.mode == "teste":
            lines.append("Isto é um teste: não mande nada para outras pessoas.")
        return "\n".join(lines)

    async def _agent(self, state: RunState, step: dict, scope: dict) -> tuple[Any, str]:
        assert self._slots is not None
        prompt = self._agent_prompt(state, step, scope)
        async with self._slots:
            if step.get("agente"):
                agent = self.agents.get(str(step["agente"]))
                if step.get("modelo"):
                    agent = Agent(**{**agent.to_dict(), "model": str(step["modelo"])})
            else:
                agent = Agent(id="automacao", name=f"⚙️ {step['titulo']}"[:60], cli=str(step.get("cli") or "claude"), model=str(step.get("modelo") or ""))
            # As ferramentas da central (já filtradas para o passo) não pedem licença no Claude:
            # no modo manual, a pergunta travaria o passo à espera de alguém no terminal.
            extra = ["--allowedTools", "mcp__metis"] if agent.cli == "claude" else None
            session = self.manager.create(agent.cli, str(Path(step["pasta"]).expanduser()) if step.get("pasta") else None,
                                          title=f"Automação · {state.flow['nome']}", tag="automacao", agent=agent, prompt=prompt,
                                          extra_args=extra)  # fmt: skip
            self.hub.session_tools[session.id] = {str(t) for t in step.get("ferramentas") or []}
            state.sessions.add(session.id)
            loop = asyncio.get_running_loop()
            waiter = Waiter(state.id, step["id"], dict(step.get("saida") or {}), loop.create_future())
            self.waiters[session.id] = waiter
            self._save_step(state.id, step["id"], status="rodando", nota=f"terminal «{session.title}»", sessao=session.id)
            minutes = float(step.get("tempo_limite_min") or DEFAULT_AGENT_MINUTES)
            started = time.time()
            try:
                data = await asyncio.wait_for(waiter.future, minutes * 60)
            except asyncio.TimeoutError as exc:
                raise StepError(f"o agente não devolveu a saída em {minutes:g} min (o terminal «{session.title}» ficou aberto)") from exc
            finally:
                self.waiters.pop(session.id, None)
            took = time.time() - started
            line = getattr(self.manager.get(session.id), "statusline", None) or {}
            context = (line.get("context") or {}).get("used_tokens")
            note = f"terminal «{session.title}» · {took / 60:.1f} min" + (f" · contexto {context / 1000:.0f} mil tokens" if context else "")
            if step.get("onde") != "visivel":
                loop.call_later(5, lambda: asyncio.ensure_future(self.manager.close(session.id)))
            return data, note

    def receive_output(self, session_id: str, data: Any) -> str:
        """A ferramenta `saida` da central: confere o formato e acorda o passo que espera."""
        waiter = self.waiters.get(session_id)
        if waiter is None or waiter.future.done():
            raise StepError("esta sessão não tem passo de automação esperando saída")
        problems = check_output(data, waiter.shape)
        loop = self._loop
        assert loop is not None
        if problems:
            waiter.attempts += 1
            if waiter.attempts > MAX_NUDGES:
                loop.call_soon_threadsafe(self._fail, waiter, f"saída fora do formato depois de {MAX_NUDGES} pedidos de correção: {'; '.join(problems)}")
                return "A MÊTIS marcou este passo como erro: a saída continuou fora do formato. Pode encerrar."
            return "Saída fora do formato combinado: " + "; ".join(problems) + ". Chame `saida` de novo com todos os campos."
        loop.call_soon_threadsafe(self._resolve, waiter, data)
        return "Recebido pela MÊTIS. O passo terminou; pode encerrar."

    @staticmethod
    def _resolve(waiter: Waiter, data: Any) -> None:
        if not waiter.future.done():
            waiter.future.set_result(data)

    @staticmethod
    def _fail(waiter: Waiter, message: str) -> None:
        if not waiter.future.done():
            waiter.future.set_exception(StepError(message))

    def on_stop(self, session_id: str) -> None:
        """O agente terminou o turno sem chamar `saida`: pede de novo no mesmo terminal (até 2 vezes)."""
        waiter = self.waiters.get(session_id)
        session = self.manager.get(session_id)
        if waiter is None or waiter.future.done() or session is None:
            return
        waiter.nudges += 1
        if waiter.nudges > MAX_NUDGES:
            self._fail(waiter, "o agente terminou sem chamar a ferramenta saida")
            return
        fields = ", ".join(f"{k} ({OUTPUT_HELP[v]})" for k, v in waiter.shape.items()) or "o resultado"
        text = f"Falta devolver o resultado à MÊTIS: chame a ferramenta `saida` (MCP metis) com dados = {{{fields}}}."
        session.pty.write(b"\x1b[200~" + text.encode() + b"\x1b[201~")
        loop = self._loop or asyncio.get_event_loop()
        loop.call_later(0.2, lambda: session.pty.write(b"\r"))

    def _close_sessions(self, state: RunState, keep: bool) -> None:
        for sid in list(state.sessions):
            waiter = self.waiters.pop(sid, None)
            if waiter is not None and not waiter.future.done():
                waiter.future.cancel()

    # --- agendador ---------------------------------------------------------------------------------

    async def tick(self, now: datetime | None = None) -> list[int]:
        """Chamado pelo agendador do núcleo: roda as automações ativas e agendadas na hora (ou recupera)."""
        now = now or datetime.now().astimezone()
        started = []
        for automation_id in self.store.ids():
            st = self.state(automation_id)
            if not st["ativa"]:
                continue
            try:
                flow = self.store.published(automation_id)
            except AutomationError:
                continue
            if flow is None or flow["gatilho"]["tipo"] != "agendado":
                continue
            trigger = flow["gatilho"]
            rule = SimpleNamespace(days=trigger["dias"], time=trigger["hora"], catchup=int(trigger.get("recupera_min") or 60), active=True, created=st["desde"] or 0)
            last = datetime.fromtimestamp(st["ultima_hora"]).astimezone() if st["ultima_hora"] else None
            verdict = decide(rule, now, last)
            if verdict is None:
                continue
            action, slot = verdict
            with self._connect() as con:
                con.execute("update estado set ultima_hora = ? where automation = ?", (slot.timestamp(), automation_id))
            if action == "pular":
                run_id = self._new_run(automation_id, flow, "producao", "agendado", "publicada")
                with self._connect() as con:
                    con.execute("update runs set status = 'pulada', ended = ?, nota = ? where id = ?", (time.time(), f"o Mac estava dormindo às {slot:%H:%M}", run_id))
                self.publish({"type": "automation.run", "run": run_id, "automation": automation_id, "status": "pulada", "mode": "producao"})
                continue
            try:
                started.append(await self.start(automation_id, "producao", "agendado" if action == "rodar" else "recuperada"))
            except AutomationError as exc:
                self.publish({"type": "automation.error", "automation": automation_id, "error": str(exc)})
        return started
