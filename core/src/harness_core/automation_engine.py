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
- v0.9.8: passo de código (Python ou JavaScript local), gatilhos de evento da MÊTIS e de
  sondagem de conector, troca de CLI quando a cota de 5 h passa de 80% e agente sem saída
  combinada (termina no fim do turno, com a última mensagem). As rotinas da v0.7 rodam aqui.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from .agents import Agent, AgentError, AgentStore
from .automations import (
    ALL_TOOLS,
    EVENTS,
    TRIGGER_ID,
    AutomationError,
    _walk,
    fold,
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
QUOTA_LIMIT = 80.0  # % da janela de 5 h a partir do qual o passo de agente troca de CLI
CLI_NAME = {"claude": "Claude", "codex": "Codex"}
EVENT_DEBOUNCE = 30.0  # a mesma automação não dispara de novo pelo mesmo evento em 30 s
#: O que identifica "o mesmo evento" para o intervalo acima.
EVENT_KEYS = {
    "brain.nota": ("caminho",),
    "tarefa.moveu": ("projeto", "id", "para"),
    "agente.terminou": ("sessao",),
    "agente.errou": ("sessao",),
    "worktree.criada": ("caminho",),
    "captura": ("texto",),
}
POLL_KEEP = 2000  # itens vistos guardados por automação de sondagem
CODE_LOG_LINES = 5


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
        self._recent: dict[tuple, float] = {}
        self._lock = threading.Lock()
        self._tasks: set[asyncio.Future] = set()
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
                create table if not exists sondagem_itens(automation text, chave text, ts real, primary key(automation, chave));
                """
            )
            if "sessao" not in {r[1] for r in con.execute("pragma table_info(steps)")}:
                con.execute("alter table steps add column sessao text")
            # v0.9.8: a hora marcada da execução (rotinas) e o estado da sondagem.
            if "slot" not in {r[1] for r in con.execute("pragma table_info(runs)")}:
                con.execute("alter table runs add column slot real")
            columns = {r[1] for r in con.execute("pragma table_info(estado)")}
            if "ultima_sondagem" not in columns:
                con.execute("alter table estado add column ultima_sondagem real")
            if "sondagem_base" not in columns:
                con.execute("alter table estado add column sondagem_base integer default 0")
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
        item = dict(row) if row else {"automation": automation_id, "ativa": 0, "ultima_hora": None, "desde": None, "ultima_sondagem": None, "sondagem_base": 0}
        item["proxima_sondagem"] = None
        if item.get("ativa"):
            try:
                published = self.store.published(automation_id)
            except AutomationError:
                published = None
            trigger = (published or {}).get("gatilho") or {}
            if trigger.get("tipo") == "sondagem":
                item["proxima_sondagem"] = (item.get("ultima_sondagem") or time.time()) + int(trigger.get("cada_min") or 15) * 60
        return item

    def import_state(self, automation_id: str, active: bool, desde: float | None, ultima_hora: float | None) -> dict:
        """Estado vindo de outro lugar (a rotina migrada): ativa, desde quando e a última hora tratada."""
        with self._connect() as con:
            con.execute(
                "insert into estado(automation, ativa, desde, ultima_hora) values (?, ?, ?, ?) "
                "on conflict(automation) do update set ativa = excluded.ativa, desde = excluded.desde, ultima_hora = excluded.ultima_hora",
                (automation_id, int(active), desde, ultima_hora),
            )
        return self.state(automation_id)

    def set_active(self, automation_id: str, active: bool) -> dict:
        published = self.store.published(automation_id) if active else None
        if active and published is None:
            raise AutomationError("publique a automação antes de ativar: o motor só roda a publicada")
        if published is not None:
            self.check_trigger(published)
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

    def _new_run(self, automation_id: str, flow: dict, mode: str, origem: str, versao: str, slot: float | None = None) -> int:
        with self._connect() as con:
            run_id = con.execute(
                "insert into runs(automation, mode, origem, versao, status, started, flow, slot) values (?,?,?,?,?,?,?,?)",
                (automation_id, mode, origem, versao, "rodando", time.time(), _json(flow), slot),
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
                    base_run: int | None = None, only: str | None = None, entrada: dict | None = None,
                    slot: float | None = None) -> int:  # fmt: skip
        """Começa uma execução em segundo plano e devolve o número dela. `entrada` (evento,
        sondagem) entra na saída do gatilho; `slot` é a hora marcada (agendado)."""
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
        run_id = self._new_run(automation_id, flow, mode, origem, versao, slot)
        state = RunState(run_id, automation_id, flow, mode)
        self.runs[run_id] = state
        targets = downstream(flow, desde) if desde else ({only} if only else set(ids))
        state.task = asyncio.create_task(self._execute(state, prefill, targets, origem, entrada or {}))
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

    async def _execute(self, state: RunState, prefill: dict[str, dict], targets: set[str], origem: str, entrada: dict | None = None) -> None:
        flow = state.flow
        now = datetime.now().astimezone()
        outputs: dict[str, Any] = {}
        status: dict[str, str] = {}
        trigger_out = {**(entrada or {}), "hoje": now.date().isoformat(), "agora": now.isoformat(timespec="minutes"), "origem": origem, "modo": state.mode}
        if state.mode == "producao" and flow["gatilho"].get("aviso"):
            # Rotina (ou automação agendada) que avisa: a DM no Slack sai quando ela começa.
            routine = any(s.get("etiqueta") == "rotina" for s in flow["passos"])
            when = f" das {now:%H:%M}" if origem in ("agendado", "recuperada") else ""
            text = (f"🔔 A rotina {flow['nome']}{when} abriu na MÊTIS. Abra o terminal dela no Mac." if routine
                    else f"⚙️ A automação {flow['nome']} começou na MÊTIS{when}.")  # fmt: skip
            await asyncio.to_thread(self.notify, text)
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
            elif step["tipo"] == "codigo":
                titles = {TRIGGER_ID: "gatilho"} | {s["id"]: s["titulo"] for s in state.flow["passos"]}
                passos = {titles.get(k, k): v for k, v in outputs.items()}
                value, note = await asyncio.to_thread(self._code, step, inputs, passos)
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

    # --- código ---------------------------------------------------------------------------------------

    def _code(self, step: dict, inputs: Any, passos: dict) -> tuple[Any, str]:
        """Python ou JavaScript local: recebe `entrada` e `passos`, devolve em `saida`. Roda numa
        pasta temporária, com env mínimo e o tempo limite do passo; os prints viram o log."""
        language = step.get("linguagem") or "python"
        limit = int(step.get("tempo_limite_s") or 30)
        mark = f"<<<METIS-SAIDA-{secrets.token_hex(6)}>>>"
        code = str(step.get("codigo") or "")
        if language == "javascript":
            node = shutil.which("node")
            if not node:
                raise StepError("o Node não está instalado neste Mac (brew install node): o passo em JavaScript não roda")
            source = (
                "const __dados = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
                "let entrada = __dados.entrada, passos = __dados.passos, saida = null;\n"
                "(async () => {\n" + code + "\n})().then(\n"
                f"  () => {{ process.stdout.write('\\n{mark}' + JSON.stringify(saida === undefined ? null : saida) + '\\n'); }},\n"
                "  (erro) => { console.error(erro && erro.stack ? erro.stack : String(erro)); process.exit(1); }\n);\n"
            )
            name, argv = "passo.cjs", [node, "passo.cjs"]
        else:
            source = (
                "import json as __json, sys as __sys\n"
                "__dados = __json.load(__sys.stdin)\n"
                "entrada, passos, saida = __dados['entrada'], __dados['passos'], None\n"
                + code + "\n"
                f"print('\\n{mark}' + __json.dumps(saida, ensure_ascii=False, default=str))\n"
            )
            name, argv = "passo.py", [sys.executable, "-I", "passo.py"]
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", "PYTHONIOENCODING": "utf-8"}
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="metis-codigo-") as folder:
            (Path(folder) / name).write_text(source, encoding="utf-8")
            try:
                done = subprocess.run(argv, cwd=folder, input=_json({"entrada": inputs, "passos": passos}), capture_output=True,
                                      text=True, timeout=limit, env=env)  # fmt: skip
            except subprocess.TimeoutExpired as exc:
                raise StepError(f"o código passou de {limit} s e foi parado") from exc
        if done.returncode != 0:
            raise StepError((done.stderr or done.stdout).strip()[-600:] or f"o código saiu com o código {done.returncode}")
        value, found, log = None, False, []
        for line in done.stdout.splitlines():
            if line.startswith(mark):
                value, found = _load(line[len(mark):]), True
            elif line.strip():
                log.append(line.rstrip())
        if not found:
            raise StepError("o código terminou sem devolver a saída (o processo foi encerrado no meio?)")
        tail = [*log, *[l for l in done.stderr.splitlines() if l.strip()]][-CODE_LOG_LINES:]
        note = " · ".join(tail)[:400] if tail else f"{language} em {time.time() - started:.1f} s"
        return value, note

    # --- ferramenta ---------------------------------------------------------------------------------

    async def _call_tool(self, ctx: Context, name: str, args: dict, read_only: bool = False) -> Any:
        """Chama uma ferramenta da central e devolve o resultado (o JSON, o estruturado ou {texto})."""
        tool = await asyncio.to_thread(self.hub.find_tool, ctx, name)
        if tool is None:
            raise StepError(f"a ferramenta {name} não existe ou a conta dela foi desligada em Conectores")
        if read_only and tool.writes(args):
            raise StepError(f"a ferramenta {name} escreve (fala com outras pessoas ou muda algo): a sondagem só usa leitura")
        payload = await self.hub.call(ctx, name, args)
        texts = [c.get("text", "") for c in payload.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]
        text = "\n".join(texts).strip()
        if payload.get("isError"):
            raise StepError(text or "a ferramenta devolveu erro")
        if payload.get("structuredContent") is not None:
            return payload["structuredContent"]
        try:
            return json.loads(text)
        except ValueError:
            return {"texto": text}

    async def _tool(self, state: RunState, step: dict, scope: dict) -> tuple[Any, str]:
        name = str(step["ferramenta"])
        args = render(step.get("argumentos") or {}, scope)
        if not isinstance(args, dict):
            raise StepError("os argumentos da ferramenta precisam ser um objeto")
        ctx = Context(session=f"automacao-{state.id}", who=f"⚙️ {state.flow['nome']}", cwd=None, allowed=None)
        tool = await asyncio.to_thread(self.hub.find_tool, ctx, name)
        if tool is None:
            raise StepError(f"a ferramenta {name} não existe ou a conta dela foi desligada em Conectores")
        if state.mode == "teste" and tool.writes(args):
            sent = await asyncio.to_thread(self.notify, f"🧪 Ensaio de {state.flow['nome']} · {step['titulo']}: ia chamar {name} com {_json(args)[:900]}")
            return {"ensaio": True, "ferramenta": name, "argumentos": args}, f"ensaio: não chamou ({sent or 'foi para a sua DM'})"
        account = next((a for a in self.hub.connectors.list() if a.id == tool.account), None)
        if tool.writes(args) and (account.approve_writes if account else True):
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
        if not shape:
            # Sem saída combinada (as rotinas): o pedido vai como está e o passo termina no fim
            # do turno, com a última mensagem do agente.
            return request + ("\n\n(Teste de automação: não mande nada para outras pessoas.)" if state.mode == "teste" else "")
        lines = [f"[Automação da MÊTIS · {state.flow['nome']} · passo \"{step['titulo']}\"{' · TESTE EM ENSAIO' if state.mode == 'teste' else ''}]", "", request, ""]
        fields = ", ".join(f"{k} ({OUTPUT_HELP[v]})" for k, v in shape.items())
        lines.append(f"Quando terminar, chame a ferramenta `saida` do servidor MCP metis com dados = um objeto JSON com: {fields}.")
        lines.append("Não termine sem chamar `saida`. Use só as ferramentas liberadas para este passo.")
        if state.mode == "teste":
            lines.append("Isto é um teste: não mande nada para outras pessoas.")
        return "\n".join(lines)

    def _five_hour(self, cli: str) -> float | None:
        """Quanto da janela de 5 h a conta ativa da CLI já usou (None = sem dado ainda)."""
        try:
            account = self.manager.accounts.active(cli).id
            limits = getattr(self.manager.usage, cli, {}).get(account) or {}
        except Exception:  # noqa: BLE001 - sem uso conhecido, não troca
            return None
        value = (limits.get("five_hour") or {}).get("used_pct")
        return float(value) if isinstance(value, (int, float)) else None

    def _quota_switch(self, cli: str) -> tuple[str, str]:
        """(cli que roda, nota): troca quando esta passou de 80% da janela de 5 h e a outra não."""
        other = "codex" if cli == "claude" else "claude"
        mine, theirs = self._five_hour(cli), self._five_hour(other)
        if mine is not None and mine >= QUOTA_LIMIT and (theirs is None or theirs < QUOTA_LIMIT):
            return other, f"rodou no {CLI_NAME[other]}: {CLI_NAME[cli]} a {mine:.0f}% da janela de 5 h"
        return cli, ""

    async def _agent(self, state: RunState, step: dict, scope: dict) -> tuple[Any, str]:
        assert self._slots is not None
        prompt = self._agent_prompt(state, step, scope)
        routine = step.get("etiqueta") == "rotina"
        async with self._slots:
            if step.get("agente"):
                agent = self.agents.get(str(step["agente"]))
                if step.get("modelo"):
                    agent = Agent(**{**agent.to_dict(), "model": str(step["modelo"])})
            elif routine:
                agent = None  # rotina sem agente da galeria: o terminal leva o nome dela
            else:
                agent = Agent(id="automacao", name=f"⚙️ {step['titulo']}"[:60], cli=str(step.get("cli") or "claude"), model=str(step.get("modelo") or ""))
            cli = agent.cli if agent else str(step.get("cli") or "claude")
            switch_note = ""
            if step.get("troca_cota", True) and cli in CLI_NAME:
                used, switch_note = self._quota_switch(cli)
                if used != cli:
                    cli = used
                    if agent is not None:  # o agente da galeria mantém nome e papel; o modelo é da outra CLI
                        agent = Agent(**{**agent.to_dict(), "cli": cli, "model": ""})
            tools = step.get("ferramentas")
            restricted = not (isinstance(tools, list) and ALL_TOOLS in tools)
            kwargs: dict[str, Any] = {
                "title": (None if agent and routine else state.flow["nome"]) if routine else f"Automação · {state.flow['nome']}",
                "tag": "rotina" if routine else "automacao",
                "agent": agent,
                "prompt": prompt,
            }
            # As ferramentas da central (já filtradas para o passo) não pedem licença no Claude:
            # no modo manual, a pergunta travaria o passo à espera de alguém no terminal.
            if restricted and cli == "claude":
                kwargs["extra_args"] = ["--allowedTools", "mcp__metis"]
            folder = str(Path(step["pasta"]).expanduser()) if step.get("pasta") else None
            session = self.manager.create(cli, folder, **kwargs)
            if restricted:
                self.hub.session_tools[session.id] = {str(t) for t in tools or []}
            state.sessions.add(session.id)
            loop = asyncio.get_running_loop()
            waiter = Waiter(state.id, step["id"], dict(step.get("saida") or {}), loop.create_future())
            self.waiters[session.id] = waiter
            note_open = f"terminal «{session.title}»" + (f" · {switch_note}" if switch_note else "")
            self._save_step(state.id, step["id"], status="rodando", nota=note_open, sessao=session.id)
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
            if switch_note:
                note += f" · {switch_note}"
            if switch_note and isinstance(data, dict):
                data = {**data, "cli_usado": cli}
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

    def on_stop(self, session_id: str, texto: str | None = None) -> None:
        """O agente terminou o turno. Sem saída combinada, o passo termina aqui com a última
        mensagem; com saída, e sem ter chamado `saida`, pede de novo no mesmo terminal (até 2 vezes)."""
        waiter = self.waiters.get(session_id)
        if waiter is None or waiter.future.done():
            return
        if not waiter.shape:
            loop = self._loop
            data = {"texto": (texto or "").strip()}
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(self._resolve, waiter, data)
            else:
                self._resolve(waiter, data)
            return
        session = self.manager.get(session_id)
        if session is None:
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
        """Chamado pelo agendador do núcleo: roda as automações ativas e agendadas na hora (ou
        recupera) e faz as sondagens que venceram."""
        now = now or datetime.now().astimezone()
        self._loop = self._loop or asyncio.get_running_loop()
        started = []
        for automation_id in self.store.ids():
            st = self.state(automation_id)
            if not st["ativa"]:
                continue
            try:
                flow = self.store.published(automation_id)
            except AutomationError:
                continue
            if flow is None:
                continue
            if flow["gatilho"]["tipo"] == "sondagem":
                run_id = await self._poll(automation_id, flow, st, now.timestamp())
                if run_id is not None:
                    started.append(run_id)
                continue
            if flow["gatilho"]["tipo"] != "agendado":
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
                run_id = self._new_run(automation_id, flow, "producao", "agendado", "publicada", slot.timestamp())
                with self._connect() as con:
                    con.execute("update runs set status = 'pulada', ended = ?, nota = ? where id = ?", (time.time(), f"o Mac estava dormindo às {slot:%H:%M}", run_id))
                self.publish({"type": "automation.run", "run": run_id, "automation": automation_id, "status": "pulada", "mode": "producao"})
                continue
            try:
                started.append(await self.start(automation_id, "producao", "agendado" if action == "rodar" else "recuperada", slot=slot.timestamp()))
            except AutomationError as exc:
                self.publish({"type": "automation.error", "automation": automation_id, "error": str(exc)})
        return started

    # --- sondagem ----------------------------------------------------------------------------------

    @staticmethod
    def _first_list(value: Any, path: str) -> list | None:
        """A lista de itens no resultado: no caminho dado, ou a primeira lista que aparecer."""
        if path:
            found = _walk(value, path)
            return found if isinstance(found, list) else None
        todo = [value]
        while todo:
            item = todo.pop(0)
            if isinstance(item, list):
                return item
            if isinstance(item, dict):
                todo.extend(item.values())
        return None

    @staticmethod
    def _item_key(item: Any, field: str) -> str:
        if field and isinstance(item, dict) and item.get(field) not in (None, ""):
            return str(item[field])
        return hashlib.sha1(json.dumps(item, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    def check_trigger(self, flow: dict) -> None:
        """Gatilho de sondagem: a ferramenta precisa existir e só ler (nada que fale com pessoas)."""
        trigger = flow.get("gatilho") or {}
        if trigger.get("tipo") != "sondagem":
            return
        name = str(trigger.get("ferramenta") or "")
        ctx = Context(session="sondagem", who="sondagem", cwd=None, allowed=None)
        tool = self.hub.find_tool(ctx, name)
        if tool is None:
            raise AutomationError(f"a ferramenta {name} da sondagem não existe ou a conta dela foi desligada em Conectores")
        if tool.write:
            raise AutomationError(f"a ferramenta {name} escreve (fala com outras pessoas ou muda algo): a sondagem só usa ferramentas de leitura")

    async def _poll(self, automation_id: str, flow: dict, st: dict, now: float) -> int | None:
        """Uma sondagem vencida: lê a lista, anota os itens e dispara com os novos (a primeira só anota)."""
        trigger = flow["gatilho"]
        if now - float(st.get("ultima_sondagem") or 0) < int(trigger.get("cada_min") or 15) * 60:
            return None
        with self._connect() as con:
            con.execute("update estado set ultima_sondagem = ? where automation = ?", (now, automation_id))
        ctx = Context(session=f"sondagem-{automation_id}", who=f"⚙️ {flow['nome']}", cwd=None, allowed=None)
        try:
            args = render(trigger.get("argumentos") or {}, make_scope(flow, {}))
            result = await self._call_tool(ctx, str(trigger["ferramenta"]), args if isinstance(args, dict) else {}, read_only=True)
        except (StepError, AutomationError, ValueError, KeyError, OSError) as exc:
            self.publish({"type": "automation.error", "automation": automation_id, "error": f"sondagem: {exc}"})
            return None
        items = self._first_list(result, str(trigger.get("caminho") or ""))
        if items is None:
            self.publish({"type": "automation.error", "automation": automation_id, "error": "sondagem: o resultado não tem uma lista de itens (confira o caminho)"})
            return None
        keyed: dict[str, Any] = {}
        for item in items:
            keyed.setdefault(self._item_key(item, str(trigger.get("chave") or "")), item)
        with self._connect() as con:
            seen = {r[0] for r in con.execute("select chave from sondagem_itens where automation = ?", (automation_id,))}
            fresh = [(k, v) for k, v in keyed.items() if k not in seen]
            con.executemany("insert or ignore into sondagem_itens(automation, chave, ts) values (?, ?, ?)", [(automation_id, k, now) for k, _ in fresh])
            con.execute(
                "delete from sondagem_itens where automation = ? and chave not in "
                "(select chave from sondagem_itens where automation = ? order by ts desc limit ?)",
                (automation_id, automation_id, POLL_KEEP),
            )
            first = not st.get("sondagem_base")
            if first:
                con.execute("update estado set sondagem_base = 1 where automation = ?", (automation_id,))
        if first or not fresh:
            return None
        try:
            return await self.start(automation_id, "producao", "sondagem", entrada={"novos": [v for _, v in fresh]})
        except AutomationError as exc:
            self.publish({"type": "automation.error", "automation": automation_id, "error": str(exc)})
            return None

    # --- eventos da MÊTIS ---------------------------------------------------------------------------

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """O loop do núcleo: eventos que chegam de outras threads disparam nele."""
        self._loop = loop

    def owns(self, session_id: str) -> bool:
        """A sessão é de um passo de automação (não dispara agente.terminou: seria um laço)."""
        return session_id in self.waiters or any(session_id in st.sessions for st in self.runs.values())

    def listens(self, name: str) -> bool:
        """Alguma automação ativa e publicada espera este evento?"""
        for automation_id in self.store.ids():
            if not self.state(automation_id)["ativa"]:
                continue
            try:
                flow = self.store.published(automation_id)
            except AutomationError:
                continue
            if flow and flow["gatilho"]["tipo"] == "evento" and flow["gatilho"].get("evento") == name:
                return True
        return False

    def fire_event(self, name: str, payload: dict) -> None:
        """Um evento da MÊTIS aconteceu. Pode vir de qualquer thread; dispara no loop do núcleo."""
        if name not in EVENTS:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        coro = self.on_event(name, dict(payload))
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            task = loop.create_task(coro)
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    async def on_event(self, name: str, payload: dict) -> list[int]:
        """As automações ativas com gatilho neste evento (e o filtro batendo) rodam em produção."""
        started: list[int] = []
        for automation_id in self.store.ids():
            if not self.state(automation_id)["ativa"]:
                continue
            try:
                flow = self.store.published(automation_id)
            except AutomationError:
                continue
            trigger = (flow or {}).get("gatilho") or {}
            if trigger.get("tipo") != "evento" or trigger.get("evento") != name:
                continue
            rule = trigger.get("filtro") or {}
            if any(fold(str(payload.get(k, ""))) != fold(str(v)) for k, v in rule.items()):
                continue
            key = (automation_id, name, "|".join(str(payload.get(k, "")) for k in EVENT_KEYS.get(name, ())))
            now = time.monotonic()
            with self._lock:
                self._recent = {k: t for k, t in self._recent.items() if now - t < EVENT_DEBOUNCE}
                if key in self._recent:
                    continue
                self._recent[key] = now
            try:
                started.append(await self.start(automation_id, "producao", "evento", entrada={"evento": name, **payload}))
            except AutomationError as exc:
                self.publish({"type": "automation.error", "automation": automation_id, "error": str(exc)})
        return started

    def on_bus_event(self, event: dict) -> None:
        """Ouve o barramento do núcleo: agente (Claude ou Codex) que saiu com erro é o agente.errou."""
        if event.get("type") != "session.status" or event.get("status") != "exited":
            return
        code = event.get("exit_code")
        if code in (None, 0):
            return
        session = self.manager.get(str(event.get("id")))
        if session is None or getattr(session, "kind", "") not in ("claude", "codex") or self.owns(session.id):
            return
        self.fire_event("agente.errou", {"sessao": session.id, "titulo": session.title, "cli": session.kind, "cwd": session.cwd, "codigo": code})

    async def shutdown(self) -> None:
        """O núcleo vai desligar: as execuções em andamento param (voltam como interrompidas)."""
        for state in list(self.runs.values()):
            if state.task is not None and not state.task.done():
                state.task.cancel()
        for state in list(self.runs.values()):
            if state.task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(state.task), 2)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):  # noqa: BLE001
                    pass

    # --- execuções das rotinas (v0.9.8) -------------------------------------------------------------

    def runs_with_prefix(self, prefix: str, limit: int = 60, since: float = 0) -> list[dict]:
        """Execuções das automações cujo id começa com o prefixo, com a sessão do primeiro agente."""
        with self._connect() as con:
            rows = con.execute(
                "select r.id, r.automation, r.mode, r.origem, r.status, r.started, r.ended, r.error, r.nota, r.slot, "
                "(select s.sessao from steps s where s.run = r.id and s.sessao is not null limit 1) as sessao "
                "from runs r where r.automation like ? and r.started >= ? order by r.id desc limit ?",
                (prefix.replace("%", "") + "%", since, limit),
            ).fetchall()
        return [dict(r) for r in rows]
