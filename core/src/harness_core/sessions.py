"""Registro das sessões, contas, status dos agentes e eventos para a interface."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .accounts import PROVIDERS, AccountStore
from .agents import Agent, agent_args
from .claude_settings import claude_argv
from .codex_usage import read_codex_limits
from .config import Settings
from .ports import ports_by_session
from .pty_session import PtySession
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

KINDS = ("claude", "codex", "shell")
CODEX_POLL_SECONDS = 180
PORTS_POLL_SECONDS = 4


class UnknownKind(ValueError):
    pass


class ExecutableNotFound(RuntimeError):
    pass


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()

    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        for queue in list(self._subscribers):
            queue.put_nowait(event)


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
        self.usage = Usage()

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
    ) -> Session:
        if agent is not None:
            kind = agent.cli
            cwd = cwd or agent.folder or None
            title = title or agent.name
            account_id = account_id or agent.account or None
        if kind not in KINDS:
            raise UnknownKind(kind)
        session_id = uuid.uuid4().hex[:8]
        workdir = str(Path(cwd or Path.home()).expanduser())
        argv = resolve_argv(kind, self.settings)
        if agent is not None:
            argv = argv + agent_args(agent)
        env, account = self.session_env(kind, session_id, account_id)
        pty = PtySession(
            argv=argv,
            cwd=workdir,
            env=env,
            cols=cols,
            rows=rows,
            on_exit=lambda code: self._on_exit(session_id, code),
        )
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
        return session

    def _unique_title(self, base: str) -> str:
        """Claude, Claude 2, Claude 3…: abas e a barra de entrada precisam distinguir."""
        taken = {s.title for s in self.sessions.values()}
        title, n = base, 2
        while title in taken:
            title, n = f"{base} {n}", n + 1
        return title

    async def close(self, session_id: str) -> bool:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return False
        await session.pty.terminate()
        self.events.publish({"type": "session.closed", "id": session_id})
        return True

    async def close_all(self) -> None:
        for session_id in list(self.sessions):
            await self.close(session_id)

    def _set_status(self, session: Session, status: str) -> None:
        if session.status == status:
            return
        session.status = status
        self.events.publish({"type": "session.status", "id": session.id, "status": status})

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
            self.usage.claude[account] = {**parsed["rate_limits"], "updated_at": time.time()}
            self._publish_usage()
        return parsed

    def record_hook(self, session_id: str, name: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            return False
        status = HOOK_STATUS.get(name)
        if status:
            self._set_status(session, status)
        self.events.publish({"type": "session.hook", "id": session_id, "name": name})
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
