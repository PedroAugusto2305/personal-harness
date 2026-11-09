"""Registro das sessões, contas, status dos agentes e eventos para a interface."""

from __future__ import annotations

import asyncio
import json
import re
import os
import shutil
import sys
import time
import tomllib
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from .accounts import PROVIDERS, AccountStore
from .agents import Agent, AgentError, agent_args, parse_env, split_args
from .claude_settings import claude_argv, mcp_args
from .codex_usage import read_codex_limits
from .config import Settings
from .ports import ports_by_session
from .pty_session import PtySession
from .prefs import Prefs, codex_trust_args, permission_args, trust_claude_folder
from .model_usage import load_plan_usage, save_plan_usage
from .statusline import parse_statusline

# Variáveis que não podem vazar para os agentes. As do Orca fariam os hooks dele
# reportarem as sessões do Harness. As do Claude Code são marcadores da sessão que
# abriu o núcleo: marcam sessão aninhada (desliga o histórico) e uma delas é token.
# Configuração do usuário (CLAUDE_CONFIG_DIR, ANTHROPIC_*, CLAUDE_CODE_USE_*) passa.
BLOCKED_ENV_PREFIXES = ("ORCA_", "HARNESS_")
BLOCKED_ENV_KEYS = {
    "CLAUDECODE",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_PLUGIN_DIRS",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_SSE_PORT",
}

# Hook do Claude Code → status do agente na interface.
HOOK_STATUS = {
    "SessionStart": "waiting",
    "UserPromptSubmit": "working",
    "Stop": "waiting",
    "Notification": "waiting",
}

# Hook → atenção (v0.9.8, painel de agentes): o que o agente espera de você.
HOOK_ATTENTION = {
    "Stop": "terminou",
    "Notification": "pergunta",
    "UserPromptSubmit": None,
    "SessionStart": None,
}
#: O "estou esperando sua resposta" que o Claude manda depois de um minuto parado não é pergunta.
IDLE_NOTICE = "claude is waiting for your input"

KINDS = ("claude", "codex", "shell")
CODEX_POLL_SECONDS = 180
PORTS_POLL_SECONDS = 4


class UnknownKind(ValueError):
    pass


class ExecutableNotFound(RuntimeError):
    pass


class CommandError(ValueError):
    """Linha de comando de uma CLI "outra" (ou argumentos do agente) que não dá para rodar."""


#: Etiquetas de sessão que nunca hibernam: o motor das automações e as rotinas esperam por elas.
NO_HIBERNATE_TAGS = ("automacao", "rotina")
EFFORTS = ("low", "medium", "high", "xhigh")


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[@-Z\\\]^_=>78]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class EventBus:
    """Eventos para a janela. Pode ser chamado de uma thread (ferramenta do MCP, varredura do
    Brain): aí o evento entra na fila pelo loop dono dela."""

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue[dict], asyncio.AbstractEventLoop | None] = {}
        #: v0.9.8: quem dentro do núcleo quer saber de cada evento (gatilhos das automações).
        self._listeners: list[Callable[[dict], None]] = []

    def listen(self, fn: Callable[[dict], None]) -> None:
        """Chama fn(evento) a cada publish, na thread de quem publica. fn não pode travar."""
        self._listeners.append(fn)

    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._subscribers[queue] = loop
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.pop(queue, None)

    @property
    def listeners(self) -> int:
        """Quantas janelas estão ligadas agora (0 = a MÊTIS está fechada e o núcleo segue sozinho)."""
        return len(self._subscribers)

    def publish(self, event: dict) -> None:
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        for queue, loop in list(self._subscribers.items()):
            if loop is not None and loop is not current:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            else:
                queue.put_nowait(event)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - quem escuta nunca derruba quem publica
                pass


@dataclass
class Session:
    id: str
    kind: str
    title: str
    cwd: str
    created_at: float
    pty: PtySession
    account: str | None = None
    tag: str | None = None
    agent: str | None = None
    ports: list[int] = field(default_factory=list)
    status: str = "starting"
    statusline: dict | None = None
    exit_code: int | None = None
    #: v0.9.8: parada (SIGSTOP) depois de muito tempo esperando; qualquer escrita acorda.
    hibernando: bool = False
    #: v0.9.8: "pergunta" (Notification), "terminou" (Stop) ou None; e desde quando está assim.
    atencao: str | None = None
    status_desde: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "account": self.account,
            "tag": self.tag,
            "agent": self.agent,
            "ports": self.ports,
            "status": self.status,
            "statusline": self.statusline,
            "exit_code": self.exit_code,
            "pid": self.pty.pid,
            "hibernando": self.hibernando,
            "atencao": self.atencao,
            "status_desde": self.status_desde,
        }


@dataclass
class Usage:
    """Uso do plano por provedor e por conta. Os limites são da conta, não da sessão."""

    claude: dict[str, dict] = field(default_factory=dict)
    codex: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"claude": self.claude, "codex": self.codex}


def _venv_bin() -> str | None:
    """Pasta bin do ambiente virtual do núcleo (o `uv run` a põe na frente do PATH)."""
    return str(Path(sys.prefix) / "bin") if sys.prefix != sys.base_prefix else None


def clean_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(BLOCKED_ENV_PREFIXES) and key not in BLOCKED_ENV_KEYS
    }
    # Sem isso, `python3` e `pip` nos terminais seriam os do núcleo, não os do usuário.
    venv_bin = _venv_bin()
    if venv_bin and "PATH" in env:
        env["PATH"] = os.pathsep.join(p for p in env["PATH"].split(os.pathsep) if p and p != venv_bin)
    if env.get("VIRTUAL_ENV") == sys.prefix:
        del env["VIRTUAL_ENV"]
    return env


def child_env(settings: Settings, session_id: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = clean_env()
    env.update(extra or {})
    env.update(
        {
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "LANG": env.get("LANG") or "pt_BR.UTF-8",
            # No fim, para nunca passar na frente de um comando do usuário.
            "PATH": f"{env.get('PATH') or '/usr/bin:/bin'}:{settings.relay_path.parent}",
            "HARNESS_SESSION_ID": session_id,
            "HARNESS_CORE_URL": settings.url,
            "HARNESS_TOKEN": settings.token,
        }
    )
    return env


def codex_notify_args(relay: Path, config_file: Path) -> list[str]:
    """Aviso do Codex (v0.9.4): ele não tem hooks, mas chama o programa do `notify` ao fim
    de cada turno, com um JSON no último argumento. A sessão passa a chamar o relay da MÊTIS,
    que avisa o núcleo e em seguida chama o `notify` que já estava no config.toml da conta
    (o do Computer Use do Codex, por exemplo), para não desligar o que o Pedro já usa."""
    try:
        with config_file.open("rb") as handle:
            current = tomllib.load(handle).get("notify")
    except (OSError, tomllib.TOMLDecodeError):
        current = None
    chained = [str(x) for x in current] if isinstance(current, list) and all(isinstance(x, str) for x in current) else []
    # Lista de strings em JSON é um array válido em TOML.
    return ["-c", "notify=" + json.dumps([str(relay), "codex", *chained], ensure_ascii=False)]


def resolve_argv(kind: str, settings: Settings) -> list[str]:
    if kind in ("claude", "codex"):
        executable = shutil.which(kind)
        if not executable:
            raise ExecutableNotFound(f"{kind} não encontrado no PATH")
        return claude_argv(executable, settings.relay_path) if kind == "claude" else [executable]
    if kind == "shell":
        return [os.environ.get("SHELL") or "/bin/zsh", "-l"]
    raise UnknownKind(kind)


class SessionManager:
    def __init__(self, settings: Settings, accounts: AccountStore | None = None) -> None:
        self.settings = settings
        self.accounts = accounts or AccountStore(settings.home)
        self.sessions: dict[str, Session] = {}
        self.events = EventBus()
        # v0.9.9: o último limite visto do Claude volta depois de reiniciar (só vem da statusline).
        self.usage = Usage(claude=load_plan_usage(settings.home))
        # Central de MCP: dá um token por sessão de agente e esquece ao fechar (ligada pelo app).
        self.mcp_token: Callable[[str], str] | None = None
        self.mcp_forget: Callable[[str], None] | None = None
        # Ajustes (v0.9.2): modo de permissão e pastas confiáveis (ligados pelo app).
        self.prefs = Prefs(settings.home)
        self.trusted_roots: Callable[[], list[str]] = lambda: [str(settings.worktrees)]
        # Mudança de estado de uma sessão (antes, depois) e hook recebido (nome, mensagem).
        self.on_status: Callable[[Session, str, str], None] | None = None
        self.on_hook: Callable[[Session, str, str | None], None] | None = None
        #: v0.9.8: a Atividade dos agentes ("inicio", "hook", "saiu", "hibernou", "acordou").
        self.on_activity: Callable[[Session, str, dict], None] | None = None

    # --- sessões -----------------------------------------------------------

    def list(self) -> list[dict]:
        return [s.to_dict() for s in sorted(self.sessions.values(), key=lambda s: s.created_at)]

    def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def session_env(self, kind: str, session_id: str, account_id: str | None) -> tuple[dict[str, str], str | None]:
        """Ambiente do processo e a conta usada (só Claude e Codex têm conta)."""
        if kind not in PROVIDERS:
            return child_env(self.settings, session_id), None
        account = self.accounts.get(kind, account_id) if account_id else self.accounts.active(kind)
        return child_env(self.settings, session_id, self.accounts.env(kind, account)), account.id

    def create(
        self,
        kind: str,
        cwd: str | None = None,
        cols: int = 120,
        rows: int = 32,
        title: str | None = None,
        account_id: str | None = None,
        tag: str | None = None,
        agent: Agent | None = None,
        prompt: str | None = None,
        resume: str | None = None,
        permission: str | None = None,
        extra_args: list[str] | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> Session:
        if agent is not None:
            kind = agent.cli
            cwd = cwd or agent.folder or None
            title = title or agent.name
            account_id = account_id or agent.account or None
            if model and kind in PROVIDERS:
                agent = replace(agent, model=model)  # o modelo do pedido vence o do agente
        if kind != "outra" and kind not in KINDS:
            raise UnknownKind(kind)
        session_id = uuid.uuid4().hex[:8]
        workdir = str(Path(cwd or Path.home()).expanduser())
        try:
            agent_env = parse_env(agent.env) if agent is not None else {}
            if kind == "outra":
                # v0.9.8: qualquer CLI de agente, num terminal comum (sem a central de MCP).
                argv = split_args(agent.command if agent else "", "o comando") + split_args(agent.args if agent else "")
                if not argv:
                    raise CommandError("o agente não tem a linha de comando da CLI")
                found = shutil.which(argv[0])
                if not found:
                    raise CommandError(f"não achei {argv[0]} no PATH")
                argv[0] = found
                kind = "shell"
            else:
                argv = resolve_argv(kind, self.settings)
                if agent is not None:
                    argv = argv + agent_args(agent)
        except AgentError as exc:
            raise CommandError(str(exc)) from exc
        if model and kind in PROVIDERS and (agent is None or not agent.model):
            argv = argv + (["--model", model] if kind == "claude" else ["-m", model])
        if effort and kind == "codex":
            if effort not in EFFORTS:
                raise CommandError(f"esforço inválido: {effort}")
            argv = argv + ["-c", f'model_reasoning_effort="{effort}"']
        env, account = self.session_env(kind, session_id, account_id)
        env.update(agent_env)
        if kind in PROVIDERS:
            prefs = self.prefs.get()
            argv = argv + permission_args(kind, permission or prefs[f"permissao_{kind}"])
            if prefs["confiar_pastas"] and self._trusted(workdir):
                if kind == "claude":
                    folder = env.get("CLAUDE_CONFIG_DIR")
                    trust_claude_folder(Path(folder) / ".claude.json" if folder else self.settings.claude_json, workdir)
                else:
                    argv = argv + codex_trust_args(workdir)
            if kind == "codex":
                codex_home = Path(env["CODEX_HOME"]) if env.get("CODEX_HOME") else Path.home() / ".codex"
                argv = argv + codex_notify_args(self.settings.relay_path, codex_home / "config.toml")
            if extra_args:
                argv = argv + list(extra_args)
            if resume:
                # Retomar: no Claude é --resume <id>; no Codex, o subcomando `codex resume <id>`.
                argv = argv + ["--resume", resume] if kind == "claude" else [argv[0], "resume", resume, *argv[1:]]
        if kind in ("claude", "codex") and self.mcp_token is not None:
            token = self.mcp_token(session_id)
            argv = argv + mcp_args(kind, self.settings.url, token)
            env["METIS_MCP_TOKEN"] = token
        if prompt and kind in ("claude", "codex") and not resume:
            # Primeira mensagem da sessão interativa (rotinas). Vai logo depois do executável:
            # no Claude, o --mcp-config aceita vários valores e engoliria o que viesse depois.
            argv = [argv[0], prompt, *argv[1:]]
        pty = PtySession(
            argv=argv,
            cwd=workdir,
            env=env,
            cols=cols,
            rows=rows,
            on_exit=lambda code: self._on_exit(session_id, code),
        )
        pty.on_wake = lambda: self._woke(session_id)
        default_title = {"claude": "Claude", "codex": "Codex"}.get(kind, Path(argv[0]).name)
        session = Session(
            id=session_id,
            kind=kind,
            title=self._unique_title(title or default_title),
            cwd=workdir,
            created_at=time.time(),
            pty=pty,
            account=account,
            tag=tag,
            agent=agent.id if agent else None,
            status="starting" if kind == "claude" else "running",
        )
        self.sessions[session_id] = session
        pty.start()
        self.events.publish({"type": "session.created", "session": session.to_dict()})
        self._activity(session, "inicio")
        return session

    def _activity(self, session: Session, kind: str, data: dict | None = None) -> None:
        if self.on_activity is None:
            return
        try:
            self.on_activity(session, kind, data or {})
        except Exception:  # a Atividade nunca derruba a sessão
            pass

    def _trusted(self, folder: str) -> bool:
        """Pasta de um projeto da MÊTIS ou de uma worktree dele: entra como confiável na CLI."""
        target = Path(folder).resolve()
        for root in self.trusted_roots():
            try:
                target.relative_to(Path(root).expanduser().resolve())
                return True
            except ValueError:
                continue
        return False

    def _unique_title(self, base: str) -> str:
        """Claude, Claude 2, Claude 3…: abas e a barra de entrada precisam distinguir."""
        taken = {s.title for s in self.sessions.values()}
        title, n = base, 2
        while title in taken:
            title, n = f"{base} {n}", n + 1
        return title

    def send_text(self, session_id: str, text: str, paste: bool = True) -> bool:
        """Mensagem para a sessão como se viesse da barra de baixo: colagem e, logo depois, Enter.

        `paste=False` digita o texto puro, linha a linha: é o caso de um shell que acabou de
        nascer e ainda não ligou o modo de colagem (as marcas apareceriam como lixo na tela).

        Pode vir de uma rota síncrona (thread): a escrita vai pelo loop dono do terminal, que é
        quem pode registrar a espera de escrita do PTY."""
        session = self.sessions.get(session_id)
        loop = session.pty._loop if session is not None else None
        if session is None or not session.pty.alive or loop is None or loop.is_closed():
            return False
        clean = text.replace("\x1b", "")
        if paste:
            payload = b"\x1b[200~" + clean.encode("utf-8") + b"\x1b[201~"
        else:
            payload = "\r".join(clean.splitlines()).encode("utf-8")

        def enter() -> None:
            if session.pty.alive:
                session.pty.write(b"\r")

        def paste() -> None:
            session.pty.write(payload)
            loop.call_later(0.15, enter)

        loop.call_soon_threadsafe(paste)
        return True

    def tail_lines(self, session_id: str, count: int = 8) -> list[str]:
        """O fim do terminal sem cores nem comandos de tela (aproximado: a TUI redesenha a tela)."""
        session = self.sessions.get(session_id)
        if session is None:
            return []
        raw = bytes(session.pty._buffer[-24000:]).decode("utf-8", errors="replace")
        text = ANSI_RE.sub("", raw)
        lines = []
        for line in text.replace("\r\n", "\n").split("\n"):
            line = line.rsplit("\r", 1)[-1].rstrip()
            if line.strip() and not set(line.strip()) <= set("─━═-_│ "):
                lines.append(line[:200])
        return lines[-count:]

    async def close(self, session_id: str) -> bool:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return False
        if session.hibernando:
            session.pty.resume()  # acorda antes de terminar
            session.hibernando = False
        await session.pty.terminate()
        if self.mcp_forget is not None:
            self.mcp_forget(session_id)
        self.events.publish({"type": "session.closed", "id": session_id})
        return True

    async def close_all(self) -> None:
        for session_id in list(self.sessions):
            await self.close(session_id)

    # --- hibernação (v0.9.8) -------------------------------------------------

    def hibernate_idle(self, now: float | None = None) -> list[str]:
        """Para (SIGSTOP) os agentes que esperam há mais de hibernar_min minutos sem saída nem
        entrada. Fora: automações e rotinas, que o núcleo espera. Devolve os ids parados."""
        minutes = int(self.prefs.get().get("hibernar_min") or 0)
        if minutes <= 0:
            return []
        now = time.time() if now is None else now
        stopped: list[str] = []
        for session in list(self.sessions.values()):
            if (
                session.kind in PROVIDERS
                and session.pty.alive
                and session.status == "waiting"
                and not session.hibernando
                and session.tag not in NO_HIBERNATE_TAGS
                and now - session.pty.last_activity >= minutes * 60
                and session.pty.pause()
            ):
                session.hibernando = True
                self.events.publish({"type": "session.hibernate", "id": session.id, "hibernando": True})
                self._activity(session, "hibernou")
                stopped.append(session.id)
        return stopped

    def wake(self, session_id: str) -> Session | None:
        """Acorda um agente que hibernava (a tela pede ao focar o terminal)."""
        session = self.sessions.get(session_id)
        if session is None:
            return None
        if session.hibernando:
            session.pty.resume()
            self._woke(session_id)
        return session

    def _woke(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None or not session.hibernando:
            return
        session.hibernando = False
        self.events.publish({"type": "session.hibernate", "id": session_id, "hibernando": False})
        self._activity(session, "acordou")

    def _set_status(self, session: Session, status: str) -> None:
        if session.status == status:
            return
        before, session.status = session.status, status
        session.status_desde = time.time()
        if status == "working":
            session.atencao = None  # voltou a trabalhar: não espera mais nada de você
        event: dict[str, Any] = {"type": "session.status", "id": session.id, "status": status, "atencao": session.atencao, "status_desde": session.status_desde}
        if status == "exited":
            event["exit_code"] = session.exit_code  # a faixa do agente que saiu mostra o código
        self.events.publish(event)
        if self.on_status is not None:
            self.on_status(session, before, status)
        if status == "exited":
            self._activity(session, "saiu")

    def _on_exit(self, session_id: str, code: int | None) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        session.exit_code = code
        self._set_status(session, "exited")

    # --- telemetria do Claude Code -----------------------------------------

    def record_statusline(self, session_id: str, payload: dict) -> dict | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        parsed = parse_statusline(payload)
        session.statusline = parsed
        if session.status == "starting":
            self._set_status(session, "waiting")
        self.events.publish({"type": "session.statusline", "id": session_id, "statusline": parsed})
        # Só o Claude Code manda statusline; os limites são da conta, não da sessão.
        if parsed["rate_limits"]:
            account = session.account or self.accounts.active("claude").id
            before = {k: v for k, v in (self.usage.claude.get(account) or {}).items() if k != "updated_at"}
            self.usage.claude[account] = {**parsed["rate_limits"], "updated_at": time.time()}
            # A statusline chega a cada resposta: o arquivo só é regravado quando o limite muda.
            if before != parsed["rate_limits"]:
                save_plan_usage(self.settings.home, self.usage.claude)
            self._publish_usage()
        return parsed

    def note_input(self, session_id: str, data: str) -> None:
        """Enter num Codex parado é um turno novo: ele não tem o UserPromptSubmit do Claude."""
        session = self.sessions.get(session_id)
        if session is not None and session.kind == "codex" and "\r" in data and session.status in ("waiting", "running") and session.pty.alive:
            self._set_status(session, "working")

    def record_hook(self, session_id: str, name: str, payload: dict | None = None) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            return False
        message = (payload or {}).get("message") if isinstance((payload or {}).get("message"), str) else None
        changed = False
        idle = name == "Notification" and (message or "").lower().startswith(IDLE_NOTICE)
        if name in HOOK_ATTENTION and not idle and session.atencao != HOOK_ATTENTION[name]:
            session.atencao = HOOK_ATTENTION[name]
            changed = True
        status = HOOK_STATUS.get(name)
        if status and status != session.status:
            self._set_status(session, status)  # o evento já leva a atenção nova
        elif changed:
            session.status_desde = time.time()
            self.events.publish(
                {"type": "session.status", "id": session.id, "status": session.status, "atencao": session.atencao, "status_desde": session.status_desde}
            )
        self.events.publish({"type": "session.hook", "id": session_id, "name": name, "message": message, "atencao": session.atencao})
        self._activity(session, "hook", {"name": name, "message": message, "payload": payload or {}, "idle": idle})
        if self.on_hook is not None:
            self.on_hook(session, name, message)
        return True

    def forget(self, session_id: str) -> bool:
        """Tira da lista uma sessão que já saiu (reiniciar no lugar dela, com o mesmo nome)."""
        session = self.sessions.get(session_id)
        if session is None or session.pty.alive:
            return False
        self.sessions.pop(session_id, None)
        if self.mcp_forget is not None:
            self.mcp_forget(session_id)
        self.events.publish({"type": "session.closed", "id": session_id})
        return True

    # --- contas e cota -----------------------------------------------------

    def accounts_changed(self) -> None:
        self.events.publish({"type": "accounts", "accounts": self.accounts.list()})

    def _publish_usage(self) -> None:
        self.events.publish({"type": "usage", "usage": self.usage.to_dict()})

    async def refresh_codex_usage(self) -> dict | None:
        executable = shutil.which("codex")
        if not executable:
            return None
        account = self.accounts.active("codex")
        env = {**clean_env(), **self.accounts.env("codex", account)}
        limits = await read_codex_limits(executable, env)
        if limits is not None:
            self.usage.codex[account.id] = {**limits, "updated_at": time.time()}
            self._publish_usage()
        return limits

    # --- portas ---------------------------------------------------------------

    def refresh_ports(self) -> bool:
        roots = {s.id: s.pty.pid for s in self.sessions.values() if s.pty.pid and s.status != "exited"}
        found = ports_by_session(roots)
        changed = False
        for session in self.sessions.values():
            ports = found.get(session.id, [])
            if ports != session.ports:
                session.ports = ports
                changed = True
        if changed:
            self.events.publish({"type": "ports", "ports": {s.id: s.ports for s in self.sessions.values()}})
        return changed

    async def poll_ports(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(PORTS_POLL_SECONDS)
            if not self.sessions:
                continue
            try:
                await loop.run_in_executor(None, self.refresh_ports)
            except Exception:  # lsof ou ps falharam: tenta de novo na próxima volta
                pass

    async def poll_codex_usage(self) -> None:
        while True:
            try:
                await self.refresh_codex_usage()
            except Exception:  # a cota nunca derruba o núcleo
                pass
            await asyncio.sleep(CODEX_POLL_SECONDS)
