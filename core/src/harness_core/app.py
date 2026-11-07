"""API local do núcleo: sessões, terminais por WebSocket, eventos e recepção dos hooks."""

from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings, load_settings
from .relay import install_relay
from .sessions import ExecutableNotFound, SessionManager, UnknownKind
from .statusline import render_statusline

ALLOWED_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]


class NewSession(BaseModel):
    kind: str = Field(pattern="^(claude|shell)$")
    cwd: str | None = None
    cols: int = Field(default=120, ge=20, le=500)
    rows: int = Field(default=32, ge=5, le=300)
    title: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    manager = SessionManager(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        install_relay(settings.relay_path)
        yield
        await manager.close_all()

    app = FastAPI(title="Harness core", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def valid(token: str | None) -> bool:
        return bool(token) and secrets.compare_digest(token, settings.token)

    def require_token(x_harness_token: str | None = Header(default=None)) -> None:
        if not valid(x_harness_token):
            raise HTTPException(status_code=401, detail="token inválido")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/sessions", dependencies=[Depends(require_token)])
    def list_sessions() -> list[dict]:
        return manager.list()

    @app.post("/sessions", dependencies=[Depends(require_token)], status_code=201)
    async def create_session(body: NewSession) -> dict:
        # async de propósito: o PTY é lido pelo loop do asyncio, então precisa nascer nele.
        try:
            session = manager.create(body.kind, body.cwd, body.cols, body.rows, body.title)
        except UnknownKind as exc:
            raise HTTPException(status_code=400, detail=f"tipo desconhecido: {exc}") from exc
        except ExecutableNotFound as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise HTTPException(status_code=400, detail=f"pasta inválida: {body.cwd}") from exc
        return session.to_dict()

    @app.delete("/sessions/{session_id}", dependencies=[Depends(require_token)], status_code=204)
    async def close_session(session_id: str) -> None:
        if not await manager.close(session_id):
            raise HTTPException(status_code=404, detail="sessão não encontrada")

    @app.get("/usage", dependencies=[Depends(require_token)])
    def usage() -> dict:
        return manager.usage.to_dict()

    @app.post("/hooks/statusline", dependencies=[Depends(require_token)], response_class=PlainTextResponse)
    async def hook_statusline(request: Request, session: str = Query(...)) -> str:
        payload = await _json(request)
        parsed = manager.record_statusline(session, payload)
        return render_statusline(parsed) if parsed else ""

    @app.post("/hooks/event", dependencies=[Depends(require_token)], status_code=204)
    async def hook_event(request: Request, session: str = Query(...), name: str = Query(...)) -> None:
        await _json(request)
        manager.record_hook(session, name)

    @app.websocket("/sessions/{session_id}/pty")
    async def pty_socket(websocket: WebSocket, session_id: str, token: str | None = None) -> None:
        if not valid(token):
            await websocket.close(code=4401)
            return
        session = manager.get(session_id)
        if session is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        backlog, queue = session.pty.subscribe()

        async def pump_out() -> None:
            if backlog:
                await websocket.send_bytes(backlog)
            while True:
                chunk = await queue.get()
                if chunk is None:
                    await websocket.send_text(json.dumps({"type": "exit", "code": session.pty.exit_code}))
                    return
                await websocket.send_bytes(chunk)

        async def pump_in() -> None:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)
                if data.get("type") == "input":
                    session.pty.write(str(data.get("data", "")).encode("utf-8"))
                elif data.get("type") == "resize":
                    session.pty.resize(int(data["cols"]), int(data["rows"]))

        tasks = [asyncio.create_task(pump_out()), asyncio.create_task(pump_in())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                if not task.cancelled():
                    task.exception()  # desconexão do cliente é o fim normal; não é erro
        finally:
            session.pty.unsubscribe(queue)
            try:
                await websocket.close()
            except RuntimeError:
                pass

    @app.websocket("/events")
    async def events_socket(websocket: WebSocket, token: str | None = None) -> None:
        if not valid(token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        queue = manager.events.subscribe()
        try:
            await websocket.send_json({"type": "hello", "sessions": manager.list(), "usage": manager.usage.to_dict()})
            while True:
                await websocket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            manager.events.unsubscribe(queue)

    return app


async def _json(request: Request) -> dict:
    try:
        data = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
