"""Registro das sessões, status dos agentes e eventos para a interface."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .claude_settings import claude_argv
from .config import Settings
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

KINDS = ("claude", "shell")


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
            "status": self.status,
            "statusline": self.statusline,
            "exit_code": self.exit_code,
            "pid": self.pty.pid,
        }


@dataclass
class Usage:
    """Uso do plano por provedor. Os limites são da conta, não da sessão."""

    claude: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"claude": self.claude}


def child_env(settings: Settings, session_id: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(BLOCKED_ENV_PREFIXES) and key not in BLOCKED_ENV_KEYS
    }
    env.update(
        {
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "LANG": env.get("LANG") or "pt_BR.UTF-8",
            "HARNESS_SESSION_ID": session_id,
            "HARNESS_CORE_URL": settings.url,
            "HARNESS_TOKEN": settings.token,
        }
    )
    return env


def resolve_argv(kind: str, settings: Settings) -> list[str]:
    if kind == "claude":
        executable = shutil.which("claude")
        if not executable:
            raise ExecutableNotFound("claude não encontrado no PATH")
        return claude_argv(executable, settings.relay_path)
    if kind == "shell":
        return [os.environ.get("SHELL") or "/bin/zsh", "-l"]
    raise UnknownKind(kind)


class SessionManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions: dict[str, Session] = {}
        self.events = EventBus()
        self.usage = Usage()

    def list(self) -> list[dict]:
        return [s.to_dict() for s in sorted(self.sessions.values(), key=lambda s: s.created_at)]

    def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def create(self, kind: str, cwd: str | None = None, cols: int = 120, rows: int = 32, title: str | None = None) -> Session:
        if kind not in KINDS:
            raise UnknownKind(kind)
        session_id = uuid.uuid4().hex[:8]
        workdir = str(Path(cwd or Path.home()).expanduser())
        argv = resolve_argv(kind, self.settings)
        pty = PtySession(
            argv=argv,
            cwd=workdir,
            env=child_env(self.settings, session_id),
            cols=cols,
            rows=rows,
            on_exit=lambda code: self._on_exit(session_id, code),
        )
        session = Session(
            id=session_id,
            kind=kind,
            title=title or ("Claude" if kind == "claude" else Path(argv[0]).name),
            cwd=workdir,
            created_at=time.time(),
            pty=pty,
            status="starting" if kind == "claude" else "running",
        )
        self.sessions[session_id] = session
        pty.start()
        self.events.publish({"type": "session.created", "session": session.to_dict()})
        return session

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
            self.usage.claude = {**parsed["rate_limits"], "updated_at": time.time()}
            self.events.publish({"type": "usage", "usage": self.usage.to_dict()})
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
