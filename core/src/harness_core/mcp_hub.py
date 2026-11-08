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
    "projeto desta pasta; lembrete para avisar o Pedro no celular numa hora marcada. Ferramentas "
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
        tools = self._builtin()
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
        except (ToolError, VaultError, ConnectorError, SlackError, McpError, KeyError, ValueError) as exc:
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
