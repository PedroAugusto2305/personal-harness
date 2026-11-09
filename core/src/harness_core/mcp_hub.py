"""Central de MCP da MÊTIS: um servidor MCP só, por HTTP, para cada terminal de agente.

Cada sessão do Claude ou do Codex recebe um token próprio (por `--mcp-config` no Claude e
por `bearer_token_env_var` no Codex). Pelo token a central sabe a sessão, a pasta (o projeto
do Brain) e o agente, e entrega só as ferramentas liberadas para ele:

- do Brain e do kanban (brain_buscar, brain_ler, brain_precedentes, brain_conflitos,
  brain_sugestoes, tarefas, tarefa_mover, tarefa_nova) e o lembrete;
- de cada conta de conector, com o id da conta na frente (slack-pessoal__lembrete,
  clickup-seller-pro__<ferramenta do ClickUp>).

Escrita que envolve outras pessoas (mensagem num canal, criar ou mudar algo no ClickUp)
espera a aprovação do Pedro na tela. Tudo vai para a Atividade.
Protocolo escrito à mão (JSON-RPC por HTTP com resposta JSON): é o pedaço que a central
precisa, sem depender do SDK.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import __version__
from .activity import ActivityLog
from .brain_index import BrainIndex
from .brain_tools import DESCRIPTIONS, BrainTools
from .browser_bridge import BridgeError, BrowserBridge, normalize_url
from .connectors import ConnectorError, ConnectorStore
from .kanban import Kanban
from .mcp_client import McpError
from .slack import SlackError
from .vault import Vault, VaultError
from .when import WhenError, parse_when

PROTOCOL = "2025-06-18"
APPROVAL_TIMEOUT = 10 * 60
UPSTREAM_TTL = 10 * 60
MAX_NAME = 52  # o Claude mostra mcp__metis__<nome>, e o total não pode passar de 64

INSTRUCTIONS = (
    "Central da MÊTIS, o ambiente pessoal do Pedro. Use brain_precedentes e brain_buscar para ver o que "
    "outros projetos já decidiram, e brain_conflitos ANTES de registrar uma decisão (acha repetição e "
    "contradição no próprio projeto); tarefas e tarefa_mover para o kanban do "
    "projeto desta pasta; lembrete para avisar o Pedro no celular numa hora marcada. As navegador_* agem "
    "no navegador da MÊTIS, na aba da worktree desta pasta: rode navegador_ler antes de agir e use as refs "
    "[eN] que ele mostra em clicar e digitar. Ferramentas "
    "com nome de conta na frente (slack-…, clickup-…) agem nessas contas; as que escrevem para "
    "outras pessoas esperam a aprovação do Pedro."
)


class ToolError(RuntimeError):
    pass


@dataclass
class Context:
    session: str
    who: str
    cwd: str | None
    allowed: set[str] | None  # contas de conector liberadas; None = todas


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[[dict, Context], Any]
    account: str = ""
    write: bool = False
    summary: Callable[[dict], str] | None = None

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema}


@dataclass
class Pending:
    id: str
    session: str
    who: str
    tool: str
    account: str
    summary: str
    args: dict
    created: float
    future: asyncio.Future = field(repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session": self.session,
            "who": self.who,
            "tool": self.tool,
            "account": self.account,
            "summary": self.summary,
            "args": self.args,
            "created": self.created,
        }


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _text(value: str) -> dict:
    return {"content": [{"type": "text", "text": value}]}


class Hub:
    def __init__(
        self,
        *,
        connectors: ConnectorStore,
        brain: BrainIndex,
        kanban: Kanban,
        vault: Vault,
        activity: ActivityLog,
        publish: Callable[[dict], None],
        session_info: Callable[[str], dict | None],
        on_brain_change: Callable[[str], None] = lambda _project: None,
        brain_tools: BrainTools | None = None,
        browser: BrowserBridge | None = None,
    ) -> None:
        self.connectors = connectors
        self.brain = brain
        self.kanban = kanban
        self.vault = vault
        self.activity = activity
        self.publish = publish
        self.session_info = session_info
        self.on_brain_change = on_brain_change
        self.brain_tools = brain_tools or BrainTools(brain)
        self.browser = browser
        # Notas do Brain que cada sessão viu pelas ferramentas (mini-mapa): sessão → caminho → nota.
        self.session_notes: dict[str, dict[str, dict]] = {}
        # Passo de agente de uma automação (v0.9): só as ferramentas liberadas no passo, mais a
        # `saida`, por onde o agente devolve o resultado ao motor.
        self.session_tools: dict[str, set[str]] = {}
        self.output_handler: Callable[[str, Any], str] | None = None
        self.tokens: dict[str, str] = {}
        self.pending: dict[str, Pending] = {}
        self._upstream: dict[str, tuple[float, list[dict]]] = {}

    # --- sessões ------------------------------------------------------------------

    def register(self, session_id: str) -> str:
        token = secrets.token_urlsafe(24)
        self.tokens[token] = session_id
        return token

    def forget(self, session_id: str) -> None:
        self.tokens = {t: s for t, s in self.tokens.items() if s != session_id}
        self.session_notes.pop(session_id, None)
        self.session_tools.pop(session_id, None)

    def touch(self, session_id: str, notes: list[dict], via: str) -> None:
        """Guarda as notas que a sessão viu, para o mini-mapa, e avisa a tela."""
        seen = self.session_notes.setdefault(session_id, {})
        added = False
        for note in notes[:12]:
            path = note.get("path")
            if not path:
                continue
            if path not in seen:
                added = True
            entry = seen.setdefault(path, {k: note.get(k, "") for k in ("path", "title", "tipo", "projeto", "status")} | {"via": []})
            if via not in entry["via"]:
                entry["via"].append(via)
        if added:
            self.publish({"type": "brain.session", "session": session_id})

    def context(self, token: str | None) -> Context | None:
        session = self.tokens.get(token or "")
        if session is None:
            return None
        info = self.session_info(session) or {}
        return Context(session=session, who=info.get("who") or session, cwd=info.get("cwd"), allowed=info.get("allowed"))

    # --- ferramentas -----------------------------------------------------------------

    def _project(self, ctx: Context, args: dict) -> str:
        name = str(args.get("projeto") or "").strip()
        if name:
            return name
        note = self.vault.project_for_dir(ctx.cwd) if ctx.cwd else None
        if note is None:
            raise ToolError("esta pasta não é de um projeto do Brain; diga o projeto (campo projeto)")
        return note.name

    def _builtin(self) -> list[Tool]:
        def buscar(args: dict, ctx: Context) -> str:
            text, notes = self.brain_tools.buscar(str(args.get("termos", "")), str(args.get("tipo") or ""), str(args.get("projeto") or ""))
            self.touch(ctx.session, notes[:5], "busca")
            return text

        def ler(args: dict, ctx: Context) -> str:
            text, notes = self.brain_tools.ler(str(args.get("titulo", "")))
            self.touch(ctx.session, notes, "leitura")
            return text

        def precedentes(args: dict, ctx: Context) -> str:
            try:
                project = self._project(ctx, args)
            except ToolError:
                project = ""
            text, notes = self.brain_tools.precedentes(project, str(args.get("termos") or ""))
            self.touch(ctx.session, notes, "precedente")
            return text

        def conflitos(args: dict, ctx: Context) -> str:
            try:
                project = self._project(ctx, args)
            except ToolError:
                project = ""
            text, notes = self.brain_tools.conflitos(str(args.get("decisao", "")), project)
            self.touch(ctx.session, notes, "conflito")
            return text

        def sugestoes(args: dict, ctx: Context) -> str:
            text, notes = self.brain_tools.sugestoes(self._project(ctx, args))
            self.touch(ctx.session, notes, "sugestão")
            return text

        def tarefas(args: dict, ctx: Context) -> str:
            project = self._project(ctx, args)
            items = [t for t in self.kanban.tasks(project) if args.get("todas") or t["state"] != "concluida"]
            if not items:
                return f"Nenhuma tarefa aberta em {project}."
            return f"Próximas ações de {project}:\n" + "\n".join(f"- [{t['state']}] {t['id']}: {t['text']}" for t in items)

        def mover(args: dict, ctx: Context) -> str:
            project = self._project(ctx, args)
            task = self.kanban.move(project, str(args["id"]), str(args["estado"]))
            self.on_brain_change(project)
            return f"{task['id']} agora está em {task['state']}: {task['text']}"

        def nova(args: dict, ctx: Context) -> str:
            project = self._project(ctx, args)
            task = self.kanban.add(project, str(args["texto"]), str(args.get("estado") or "pendente"))
            self.on_brain_change(project)
            return f"Tarefa {task['id']} criada em {project} ({task['state']})."

        def lembrete(args: dict, ctx: Context) -> str:
            account = str(args.get("conta") or "") or next((a.id for a in self.connectors.list() if a.reminders), "")
            if not account:
                raise ToolError("nenhuma conta do Slack conectada para lembretes; conecte uma em Conectores")
            if ctx.allowed is not None and account not in ctx.allowed:
                raise ToolError(f"este agente não tem acesso à conta {account}")
            return self.remind(account, str(args["texto"]), str(args["quando"]))

        estado = {"type": "string", "enum": ["pendente", "em-andamento", "em-teste", "concluida"]}
        projeto = {"type": "string", "description": "Nome do projeto no Brain. Vazio: o projeto desta pasta."}
        return [
            Tool("brain_buscar", DESCRIPTIONS["brain_buscar"],
                 _schema({"termos": {"type": "string"}, "tipo": {"type": "string", "description": "decisao, incidente, aprendizado, entrega, projeto (vírgula para vários)"}, "projeto": {"type": "string"}}, ["termos"]), buscar),
            Tool("brain_ler", DESCRIPTIONS["brain_ler"], _schema({"titulo": {"type": "string"}}, ["titulo"]), ler),
            Tool("brain_precedentes", DESCRIPTIONS["brain_precedentes"],
                 _schema({"termos": {"type": "string", "description": "Uma frase sobre o assunto. Vazio: o momento do projeto."}, "projeto": projeto}, []), precedentes),
            Tool("brain_conflitos", DESCRIPTIONS["brain_conflitos"],
                 _schema({"decisao": {"type": "string", "description": "A decisão numa frase afirmada."}, "projeto": projeto}, ["decisao"]), conflitos),
            Tool("brain_sugestoes", DESCRIPTIONS["brain_sugestoes"], _schema({"projeto": projeto}, []), sugestoes),
            Tool("tarefas", "Próximas ações (kanban) do projeto desta pasta, com o id de cada uma.",
                 _schema({"projeto": projeto, "todas": {"type": "boolean", "description": "inclui as concluídas"}}, []), tarefas),
            Tool("tarefa_mover", "Move uma tarefa do kanban: pendente, em-andamento, em-teste ou concluida. Mova a sua tarefa para em-teste quando terminar.",
                 _schema({"id": {"type": "string"}, "estado": estado, "projeto": projeto}, ["id", "estado"]), mover),
            Tool("tarefa_nova", "Acrescenta uma tarefa às Próximas ações do projeto.",
                 _schema({"texto": {"type": "string"}, "estado": estado, "projeto": projeto}, ["texto"]), nova),
            Tool("lembrete", "Agenda um lembrete para o Pedro: o bot da MÊTIS manda a mensagem na DM do Slack na hora marcada, e o iPhone toca mesmo com o Mac dormindo.",
                 _schema({"texto": {"type": "string"}, "quando": {"type": "string", "description": "ISO 8601 com fuso, ou em português: 'sexta 9h', 'amanhã 14:30', 'em 20 min'"}, "conta": {"type": "string", "description": "id da conta do Slack; vazio = a conta de lembretes"}}, ["texto", "quando"]), lembrete),
        ]

    def _browser_tools(self) -> list[Tool]:
        """O navegador da MÊTIS (v0.9.8): o pedido vai à janela, que age no WebKit da aba."""
        bridge = self.browser
        if bridge is None:
            return []

        def ask(ctx: Context, action: str, args: dict, timeout: float = 30, keep: tuple[str, ...] = ()) -> Any:
            clean = {k: v for k, v in args.items() if k in keep or (v is not None and v != "")}
            return bridge.request(ctx.session, ctx.who, ctx.cwd, action, clean, timeout)

        def page(result: Any) -> str:
            data = result if isinstance(result, dict) else {}
            return f"{data.get('titulo') or 'sem título'} ({data.get('url') or 'sem endereço'})"

        def header(result: Any) -> str:
            data = result if isinstance(result, dict) else {}
            return f"Aba {data.get('aba') or '?'} · {data.get('titulo') or 'sem título'} · {data.get('url') or 'sem endereço'}"

        def target(args: dict, *, text: bool = False) -> dict:
            ref = str(args.get("ref") or "").strip().strip("[]").strip()
            selector = str(args.get("seletor") or "").strip()
            label = str(args.get("texto") or "").strip() if text else ""
            if not (ref or selector or label):
                need = "ref, seletor ou texto" if text else "ref ou seletor"
                raise ToolError(f"diga em qual elemento: {need} (rode navegador_ler para ver as refs [eN])")
            found = {"ref": ref, "seletor": selector}
            if text:
                found["texto"] = label
            return found

        def done(result: Any) -> str:
            data = result if isinstance(result, dict) else {}
            return f"feito: {data.get('feito') or 'ok'}; página: {page(data)}"

        def pretty(value: Any) -> str:
            return json.dumps(value, ensure_ascii=False, indent=2, default=str)

        def abrir(args: dict, ctx: Context) -> str:
            try:
                url = normalize_url(str(args.get("url") or ""))
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            result = ask(ctx, "abrir", {"url": url, "nova_aba": bool(args.get("nova_aba")), "aba": args.get("aba")})
            data = result if isinstance(result, dict) else {}
            return f"Aberto na aba {data.get('aba') or '?'}: {page(data)}"

        def abas(_args: dict, ctx: Context) -> str:
            result = ask(ctx, "abas", {})
            if not result:
                return "Nenhuma aba de navegador nesta worktree. Use navegador_abrir."
            lines = []
            for tab in result if isinstance(result, list) else []:
                mark = " (ativa)" if tab.get("ativa") else ""
                profile = f" [{tab.get('perfil')}]" if tab.get("perfil") else ""
                lines.append(f"- {tab.get('aba')}{mark}{profile}: {tab.get('titulo') or 'sem título'} — {tab.get('url') or ''}")
            return "\n".join(lines) or pretty(result)

        def ler(args: dict, ctx: Context) -> str:
            result = ask(ctx, "ler", {"aba": args.get("aba")})
            data = result if isinstance(result, dict) else {}
            return f"{header(data)}\n\n{data.get('texto') or '(página sem texto)'}"

        def clicar(args: dict, ctx: Context) -> str:
            return done(ask(ctx, "clicar", {**target(args, text=True), "aba": args.get("aba")}))

        def digitar(args: dict, ctx: Context) -> str:
            if "texto" not in args or args.get("texto") is None:
                raise ToolError("diga o texto")
            body = {**target(args), "texto": str(args["texto"]), "enviar": bool(args.get("enviar", False)),
                    "limpar": bool(args.get("limpar", True)), "aba": args.get("aba")}
            return done(ask(ctx, "digitar", body, keep=("texto",)))

        def tecla(args: dict, ctx: Context) -> str:
            key = str(args.get("tecla") or "").strip()
            if not key:
                raise ToolError("diga a tecla (Enter, Escape, Tab, ArrowDown…)")
            return done(ask(ctx, "tecla", {"tecla": key, "aba": args.get("aba")}))

        def escolher(args: dict, ctx: Context) -> str:
            if args.get("valor") is None:
                raise ToolError("diga o valor a escolher")
            return done(ask(ctx, "escolher", {**target(args), "valor": str(args["valor"]), "aba": args.get("aba")}))

        def passar(args: dict, ctx: Context) -> str:
            return done(ask(ctx, "passar", {**target(args), "aba": args.get("aba")}))

        def rolar(args: dict, ctx: Context) -> str:
            direction = str(args.get("direcao") or "baixo")
            if direction not in ("baixo", "cima"):
                raise ToolError("direcao é baixo ou cima")
            body: dict = {"direcao": direction, "aba": args.get("aba")}
            if args.get("pixels") is not None:
                try:
                    body["pixels"] = int(args["pixels"])
                except (TypeError, ValueError) as exc:
                    raise ToolError("pixels é um número inteiro") from exc
            ref = str(args.get("ref") or "").strip().strip("[]").strip()
            body.update({"ref": ref, "seletor": str(args.get("seletor") or "").strip()})
            return done(ask(ctx, "rolar", body))

        def ir(args: dict, ctx: Context) -> str:
            action = str(args.get("acao") or "")
            if action not in ("voltar", "avancar", "recarregar"):
                raise ToolError("acao é voltar, avancar ou recarregar")
            return done(ask(ctx, "ir", {"acao": action, "aba": args.get("aba")}))

        def esperar(args: dict, ctx: Context) -> str:
            try:
                seconds = max(1, min(30, int(args.get("segundos") or 5)))
            except (TypeError, ValueError) as exc:
                raise ToolError("segundos é um número de 1 a 30") from exc
            body = {"texto": str(args.get("texto") or "").strip(), "seletor": str(args.get("seletor") or "").strip(),
                    "segundos": seconds, "aba": args.get("aba")}
            result = ask(ctx, "esperar", body, timeout=seconds + 10)
            data = result if isinstance(result, dict) else {}
            if data.get("achou"):
                return f"achou; página: {page(data)}"
            return f"não apareceu em {seconds} s; página: {page(data)}"

        def foto(args: dict, ctx: Context) -> dict:
            result = ask(ctx, "foto", {"aba": args.get("aba")})
            data = result if isinstance(result, dict) else {}
            if not data.get("base64"):
                raise ToolError("a janela não devolveu a imagem")
            return {"content": [{"type": "text", "text": header(data)},
                                {"type": "image", "data": data["base64"], "mimeType": data.get("mime") or "image/png"}]}

        def console(args: dict, ctx: Context) -> str:
            result = ask(ctx, "console", {"limpar": bool(args.get("limpar", False)), "aba": args.get("aba")})
            data = result if isinstance(result, dict) else {}
            entries = data.get("entradas") or []
            return pretty(entries) if entries else f"Console vazio na aba {data.get('aba') or '?'}."

        def rede(args: dict, ctx: Context) -> str:
            result = ask(ctx, "rede", {"filtro": str(args.get("filtro") or "").strip(), "aba": args.get("aba")})
            data = result if isinstance(result, dict) else {}
            requests = data.get("pedidos") or []
            return pretty(requests) if requests else f"Nenhum pedido registrado na aba {data.get('aba') or '?'}."

        def js(args: dict, ctx: Context) -> str:
            code = str(args.get("codigo") or "").strip()
            if not code:
                raise ToolError("diga o código (uma expressão JavaScript)")
            result = ask(ctx, "js", {"codigo": code, "aba": args.get("aba")})
            data = result if isinstance(result, dict) else {}
            return pretty(data.get("valor"))

        def fechar(args: dict, ctx: Context) -> str:
            tab = str(args.get("aba") or "").strip()
            if not tab:
                raise ToolError("diga a aba (navegador_abas lista as abertas)")
            result = ask(ctx, "fechar", {"aba": tab})
            data = result if isinstance(result, dict) else {}
            return f"Aba {data.get('aba') or tab} fechada."

        aba = {"type": "string", "description": "Aba (de navegador_abas). Vazio: a aba de navegador mais recente desta worktree."}
        ref = {"type": "string", "description": "Ref do elemento no navegador_ler, como e12."}
        seletor = {"type": "string", "description": "Seletor CSS, se não houver ref."}
        return [
            Tool("navegador_abrir", "Abre um endereço no navegador da MÊTIS, na aba desta worktree (ou numa aba nova). Aceita localhost:3000, :3000 e exemplo.com.",
                 _schema({"url": {"type": "string"}, "nova_aba": {"type": "boolean", "description": "abre numa aba nova em vez de usar a atual"}, "aba": aba}, ["url"]), abrir),
            Tool("navegador_abas", "Lista as abas de navegador desta worktree, com a ativa e o perfil.", _schema({}, []), abas),
            Tool("navegador_ler", "Lê a página: título, endereço e os elementos visíveis em texto, com refs como [e12] para usar em navegador_clicar e navegador_digitar. Rode antes de agir.",
                 _schema({"aba": aba}, []), ler),
            Tool("navegador_clicar", "Clica num elemento (ref do navegador_ler, seletor ou o texto visível). O Pedro vê o cursor do agente.",
                 _schema({"ref": ref, "seletor": seletor, "texto": {"type": "string", "description": "Texto visível do elemento, se não houver ref."}, "aba": aba}, []), clicar),
            Tool("navegador_digitar", "Digita num campo (ref ou seletor). limpar apaga o que havia; enviar aperta Enter no fim.",
                 _schema({"texto": {"type": "string"}, "ref": ref, "seletor": seletor, "enviar": {"type": "boolean"}, "limpar": {"type": "boolean"}, "aba": aba}, ["texto"]), digitar),
            Tool("navegador_tecla", "Aperta uma tecla na página: Enter, Escape, Tab, ArrowDown, ArrowUp, Backspace…",
                 _schema({"tecla": {"type": "string"}, "aba": aba}, ["tecla"]), tecla),
            Tool("navegador_escolher", "Escolhe uma opção numa lista (select), pelo valor ou pelo texto da opção.",
                 _schema({"valor": {"type": "string"}, "ref": ref, "seletor": seletor, "aba": aba}, ["valor"]), escolher),
            Tool("navegador_passar", "Passa o mouse sobre um elemento (abre menus de hover).", _schema({"ref": ref, "seletor": seletor, "aba": aba}, []), passar),
            Tool("navegador_rolar", "Rola a página para baixo ou para cima, ou até um elemento (ref ou seletor).",
                 _schema({"direcao": {"type": "string", "enum": ["baixo", "cima"]}, "pixels": {"type": "integer"}, "ref": ref, "seletor": seletor, "aba": aba}, []), rolar),
            Tool("navegador_ir", "Volta, avança ou recarrega a página.",
                 _schema({"acao": {"type": "string", "enum": ["voltar", "avancar", "recarregar"]}, "aba": aba}, ["acao"]), ir),
            Tool("navegador_esperar", "Espera um texto ou um seletor aparecer na página (até 30 s).",
                 _schema({"texto": {"type": "string"}, "seletor": seletor, "segundos": {"type": "integer", "minimum": 1, "maximum": 30}, "aba": aba}, []), esperar),
            Tool("navegador_foto", "Tira uma foto da parte visível da página.", _schema({"aba": aba}, []), foto),
            Tool("navegador_console", "Mensagens do console da página (erros, avisos, logs), as mais recentes.",
                 _schema({"limpar": {"type": "boolean", "description": "apaga as mensagens depois de ler"}, "aba": aba}, []), console),
            Tool("navegador_rede", "Pedidos de rede da página (fetch e XHR): método, endereço, status e tempo.",
                 _schema({"filtro": {"type": "string", "description": "parte do endereço"}, "aba": aba}, []), rede),
            Tool("navegador_js", "Roda uma expressão JavaScript na página e devolve o valor (em JSON).",
                 _schema({"codigo": {"type": "string"}, "aba": aba}, ["codigo"]), js),
            Tool("navegador_fechar", "Fecha uma aba de navegador.", _schema({"aba": {"type": "string"}}, ["aba"]), fechar),
        ]

    def remind(self, account_id: str, text: str, when_text: str) -> str:
        try:
            when = parse_when(when_text)
        except WhenError as exc:
            raise ToolError(str(exc)) from exc
        account, slack = self.connectors.slack(account_id)
        slack.schedule(account.meta["dm"], f"⏰ {text}", when)
        return f"Lembrete agendado em {account.name} para {when:%d/%m/%Y %H:%M}: {text}"

    def _slack_tools(self, account) -> list[Tool]:
        def para_mim(args: dict, _ctx: Context) -> str:
            acc, slack = self.connectors.slack(account.id)
            slack.send(acc.meta["dm"], str(args["texto"]))
            return f"Mensagem enviada na sua DM em {acc.name}."

        def lembrete(args: dict, _ctx: Context) -> str:
            return self.remind(account.id, str(args["texto"]), str(args["quando"]))

        def canal(args: dict, _ctx: Context) -> str:
            acc, slack = self.connectors.slack(account.id)
            sent = slack.send(str(args["canal"]), str(args["texto"]))
            return f"Mensagem enviada em {sent['channel']} ({acc.name})."

        prefix = f"[{account.name}] "
        return [
            Tool(f"{account.id}__mensagem_para_mim", prefix + "Manda uma mensagem do bot da MÊTIS na DM do Pedro (avisa no celular agora).",
                 _schema({"texto": {"type": "string"}}, ["texto"]), para_mim, account.id),
            Tool(f"{account.id}__lembrete", prefix + "Agenda uma mensagem do bot na DM do Pedro para a hora marcada.",
                 _schema({"texto": {"type": "string"}, "quando": {"type": "string"}}, ["texto", "quando"]), lembrete, account.id),
            Tool(f"{account.id}__mensagem_no_canal", prefix + "Manda mensagem num canal ou para outra pessoa (id do canal ou #nome; o bot precisa estar no canal). Pede aprovação do Pedro.",
                 _schema({"canal": {"type": "string"}, "texto": {"type": "string"}}, ["canal", "texto"]), canal, account.id, write=True,
                 summary=lambda a: f"mandar em {a.get('canal')}: “{str(a.get('texto', ''))[:300]}”"),
        ]

    def _upstream_tools(self, account) -> list[Tool]:
        cached = self._upstream.get(account.id)
        if cached and time.time() - cached[0] < UPSTREAM_TTL:
            remote = cached[1]
        else:
            try:
                remote = self.connectors.mcp(account.id).tools()
            except (McpError, ConnectorError, OSError) as exc:
                self.publish({"type": "connector.error", "account": account.id, "error": str(exc)})
                return []
            self._upstream[account.id] = (time.time(), remote)
        tools = []
        for item in remote:
            upstream = item.get("name", "")
            name = f"{account.id}__{upstream}"[:MAX_NAME]
            read_only = bool((item.get("annotations") or {}).get("readOnlyHint"))

            def run(args: dict, _ctx: Context, upstream: str = upstream) -> dict:
                return self.connectors.mcp(account.id).call(upstream, args)

            tools.append(
                Tool(name, f"[{account.name}] {item.get('description', '')}".strip(), item.get("inputSchema") or _schema({}, []), run, account.id,
                     write=not read_only, summary=lambda a, upstream=upstream: f"{upstream} {json.dumps(a, ensure_ascii=False)[:300]}")
            )
        return tools

    def _output_tool(self) -> Tool:
        def saida(args: dict, ctx: Context) -> str:
            if self.output_handler is None:
                raise ToolError("nenhuma automação esperando a saída desta sessão")
            return self.output_handler(ctx.session, args.get("dados"))

        return Tool(
            "saida",
            "Devolve o resultado deste passo de automação à MÊTIS. Chame UMA vez, no fim, com o JSON no formato combinado no pedido (campo dados). Se faltar campo, a MÊTIS diz o que corrigir.",
            _schema({"dados": {"type": "object", "description": "O resultado no formato combinado."}}, ["dados"]),
            saida,
        )

    def tools_for(self, ctx: Context) -> list[Tool]:
        tools = self._builtin() + self._browser_tools()
        for account in self.connectors.list():
            if ctx.allowed is not None and account.id not in ctx.allowed:
                continue
            tools += self._slack_tools(account) if account.kind == "slack" else self._upstream_tools(account)
        allowed = self.session_tools.get(ctx.session)
        if allowed is not None:
            tools = [t for t in tools if t.name in allowed] + [self._output_tool()]
        return tools

    def find_tool(self, ctx: Context, name: str) -> Tool | None:
        return next((t for t in self.tools_for(ctx) if t.name == name), None)

    # --- aprovação -----------------------------------------------------------------

    def decide(self, approval_id: str, approve: bool) -> bool:
        pending = self.pending.get(approval_id)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result(approve)
        return True

    async def _ask(self, ctx: Context, tool: Tool, args: dict) -> str:
        """Espera o Pedro: 'aprovado', 'recusado' ou 'expirou'."""
        account = next((a for a in self.connectors.list() if a.id == tool.account), None)
        summary = tool.summary(args) if tool.summary else json.dumps(args, ensure_ascii=False)[:300]
        return await self.ask(ctx.session, ctx.who, tool.name, account.name if account else tool.account, summary, args)

    async def ask(self, session: str, who: str, tool: str, account: str, summary: str, args: dict, timeout: float = APPROVAL_TIMEOUT) -> str:
        """Pedido de aprovação na tela (o mesmo cartão da central): 'aprovado', 'recusado' ou 'expirou'."""
        loop = asyncio.get_running_loop()
        pending = Pending(
            id=secrets.token_hex(6),
            session=session,
            who=who,
            tool=tool,
            account=account,
            summary=summary,
            args=args,
            created=time.time(),
            future=loop.create_future(),
        )
        self.pending[pending.id] = pending
        self.publish({"type": "approval", "approval": pending.to_dict()})
        try:
            return "aprovado" if await asyncio.wait_for(pending.future, timeout) else "recusado"
        except asyncio.TimeoutError:
            return "expirou"
        finally:
            self.pending.pop(pending.id, None)
            self.publish({"type": "approval.done", "id": pending.id})

    # --- protocolo -------------------------------------------------------------------

    async def call(self, ctx: Context, name: str, args: dict) -> dict:
        tools = await asyncio.to_thread(self.tools_for, ctx)
        tool = next((t for t in tools if t.name == name), None)
        if tool is None:
            return {**_text(f"ferramenta desconhecida ou não liberada para este agente: {name}"), "isError": True}
        account = next((a for a in self.connectors.list() if a.id == tool.account), None)
        needs = tool.write and (account.approve_writes if account else True)
        started = time.time()
        call_id = self.activity.start(ctx.session, ctx.who, name, tool.account, args, "aguardando você" if needs else "rodando")
        self.publish({"type": "activity", "item": self.activity.get(call_id)})
        if needs:
            verdict = await self._ask(ctx, tool, args)
            if verdict != "aprovado":
                self.activity.finish(call_id, verdict, "", started)
                self.publish({"type": "activity", "item": self.activity.get(call_id)})
                message = "O Pedro recusou esta ação." if verdict == "recusado" else "Sem resposta do Pedro em 10 minutos; a ação não foi feita."
                return {**_text(message), "isError": True}
        try:
            result = await asyncio.to_thread(tool.run, args, ctx)
            status, detail = "ok", ""
            payload = result if isinstance(result, dict) and "content" in result else _text(str(result))
            if payload.get("isError"):
                status = "erro"
        except (ToolError, BridgeError, VaultError, ConnectorError, SlackError, McpError, KeyError, ValueError) as exc:
            status, detail = "erro", str(exc)
            payload = {**_text(f"Erro: {exc}"), "isError": True}
        texts = [c.get("text", "") for c in payload.get("content", []) if isinstance(c, dict)]
        self.activity.finish(call_id, status, detail or " ".join(texts)[:400], started)
        self.publish({"type": "activity", "item": self.activity.get(call_id)})
        return payload

    async def handle(self, token: str | None, message: dict) -> dict | None:
        """Uma mensagem JSON-RPC. Notificações não têm resposta."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "mensagem JSON-RPC inválida"}}
        method, mid = message.get("method"), message.get("id")
        if mid is None:
            return None
        ctx = self.context(token)
        if ctx is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": "token da sessão inválido"}}
        params = message.get("params") or {}
        try:
            if method == "initialize":
                version = params.get("protocolVersion") or PROTOCOL
                result = {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "metis", "title": "MÊTIS", "version": __version__},
                    "instructions": INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                tools = await asyncio.to_thread(self.tools_for, ctx)
                result = {"tools": [t.spec() for t in tools]}
            elif method == "tools/call":
                result = await self.call(ctx, str(params.get("name", "")), params.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"método desconhecido: {method}"}}
        except Exception as exc:  # erro inesperado vira erro JSON-RPC, nunca derruba a central
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    async def handle_body(self, token: str | None, body: Any) -> Any:
        if isinstance(body, list):
            replies = [r for r in [await self.handle(token, m) for m in body] if r is not None]
            return replies or None
        return await self.handle(token, body)
