"""API local do núcleo: sessões, terminais por WebSocket, eventos, contas, cota, voz e hooks."""

from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from .accounts import PROVIDERS, AccountStore, UnknownAccount
from .attachments import MAX_ATTACHMENT_BYTES, save_attachment
from .config import Settings, load_settings
from .relay import install_cli_shim, install_relay
from .sessions import ExecutableNotFound, SessionManager, UnknownKind
from .statusline import render_statusline
from .voice import AudioFormatError, Transcriber

ALLOWED_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]
MAX_AUDIO_BYTES = 20 * 1024 * 1024  # ~10 min de WAV 16 kHz mono


class NewSession(BaseModel):
    kind: str = Field(pattern="^(claude|codex|shell)$")
    cwd: str | None = None
    cols: int = Field(default=120, ge=20, le=500)
    rows: int = Field(default=32, ge=5, le=300)
    title: str | None = None
    account: str | None = None
    tag: str | None = Field(default=None, pattern="^[a-z]{1,20}$")


class NewAccount(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def create_app(
    settings: Settings | None = None,
    accounts: AccountStore | None = None,
    transcriber: Transcriber | None = None,
    poll_codex: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    manager = SessionManager(settings, accounts)
    voice = transcriber or Transcriber(settings.home)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        install_relay(settings.relay_path)
        install_cli_shim(settings.relay_path.parent, settings.home)
        poller = asyncio.create_task(manager.poll_codex_usage()) if poll_codex else None
        yield
        if poller:
            poller.cancel()
            with suppress(asyncio.CancelledError):
                await poller
        await manager.close_all()

    app = FastAPI(title="Harness core", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.manager = manager
    app.state.voice = voice
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])

    def valid(token: str | None) -> bool:
        return bool(token) and secrets.compare_digest(token, settings.token)

    def require_token(x_harness_token: str | None = Header(default=None)) -> None:
        if not valid(x_harness_token):
            raise HTTPException(status_code=401, detail="token inválido")

    def check_provider(provider: str) -> None:
        if provider not in PROVIDERS:
            raise HTTPException(status_code=404, detail=f"provedor desconhecido: {provider}")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    # --- sessões -----------------------------------------------------------

    @app.get("/sessions", dependencies=[Depends(require_token)])
    def list_sessions() -> list[dict]:
        return manager.list()

    @app.post("/sessions", dependencies=[Depends(require_token)], status_code=201)
    async def create_session(body: NewSession) -> dict:
        # async de propósito: o PTY é lido pelo loop do asyncio, então precisa nascer nele.
        try:
            session = manager.create(body.kind, body.cwd, body.cols, body.rows, body.title, body.account, body.tag)
        except UnknownKind as exc:
            raise HTTPException(status_code=400, detail=f"tipo desconhecido: {exc}") from exc
        except UnknownAccount as exc:
            raise HTTPException(status_code=404, detail=f"conta desconhecida: {exc}") from exc
        except ExecutableNotFound as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise HTTPException(status_code=400, detail=f"pasta inválida: {body.cwd}") from exc
        return session.to_dict()

    @app.delete("/sessions/{session_id}", dependencies=[Depends(require_token)], status_code=204)
    async def close_session(session_id: str) -> None:
        if not await manager.close(session_id):
            raise HTTPException(status_code=404, detail="sessão não encontrada")

    # --- contas e cota -----------------------------------------------------

    @app.get("/accounts", dependencies=[Depends(require_token)])
    def list_accounts() -> dict:
        return manager.accounts.list()

    @app.post("/accounts/{provider}", dependencies=[Depends(require_token)], status_code=201)
    def add_account(provider: str, body: NewAccount) -> dict:
        check_provider(provider)
        account = manager.accounts.add(provider, body.name)
        manager.accounts_changed()
        return account.to_dict(active=False)

    @app.post("/accounts/{provider}/{account_id}/activate", dependencies=[Depends(require_token)])
    async def activate_account(provider: str, account_id: str) -> dict:
        check_provider(provider)
        try:
            account = manager.accounts.activate(provider, account_id)
        except UnknownAccount as exc:
            raise HTTPException(status_code=404, detail=f"conta desconhecida: {exc}") from exc
        manager.accounts_changed()
        if provider == "codex":
            asyncio.create_task(manager.refresh_codex_usage())
        return account.to_dict(active=True)

    @app.post("/accounts/reload", dependencies=[Depends(require_token)], status_code=204)
    def reload_accounts() -> None:
        """Chamado pelo comando `harness` depois de mudar as contas pelo terminal."""
        manager.accounts_changed()

    @app.get("/usage", dependencies=[Depends(require_token)])
    def usage() -> dict:
        return manager.usage.to_dict()

    @app.post("/usage/refresh", dependencies=[Depends(require_token)])
    async def refresh_usage() -> dict:
        await manager.refresh_codex_usage()
        return manager.usage.to_dict()

    # --- voz ---------------------------------------------------------------

    @app.get("/voice", dependencies=[Depends(require_token)])
    def voice_status() -> dict:
        return voice.status()

    @app.post("/voice/prepare", dependencies=[Depends(require_token)], status_code=202)
    async def voice_prepare() -> dict:
        if voice.state not in ("ready", "loading"):
            task = asyncio.create_task(voice.prepare())
            task.add_done_callback(lambda t: t.exception())  # o erro fica em voice.status()
        return voice.status()

    @app.post("/voice/transcribe", dependencies=[Depends(require_token)])
    async def voice_transcribe(request: Request, language: str = Query(default="pt", pattern="^[a-z]{2}$")) -> dict:
        audio = await request.body()
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="áudio grande demais")
        try:
            text = await voice.transcribe(audio, language)
        except AudioFormatError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"voz indisponível: {exc}") from exc
        return {"text": text}

    # --- anexos -------------------------------------------------------------

    @app.post("/attachments", dependencies=[Depends(require_token)], status_code=201)
    async def upload_attachment(request: Request, name: str = Query(min_length=1, max_length=255)) -> dict:
        data = await request.body()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="anexo grande demais (máximo 50 MB)")
        return {"path": str(save_attachment(settings.home, name, data))}

    # --- hooks do Claude Code ----------------------------------------------

    @app.post("/hooks/statusline", dependencies=[Depends(require_token)], response_class=PlainTextResponse)
    async def hook_statusline(request: Request, session: str = Query(...)) -> str:
        payload = await _json(request)
        parsed = manager.record_statusline(session, payload)
        return render_statusline(parsed) if parsed else ""

    @app.post("/hooks/event", dependencies=[Depends(require_token)], status_code=204)
    async def hook_event(request: Request, session: str = Query(...), name: str = Query(...)) -> None:
        await _json(request)
        manager.record_hook(session, name)

    # --- WebSockets --------------------------------------------------------

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
                data = json.loads(await websocket.receive_text())
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
            with suppress(RuntimeError):
                await websocket.close()

    @app.websocket("/events")
    async def events_socket(websocket: WebSocket, token: str | None = None) -> None:
        if not valid(token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        queue = manager.events.subscribe()
        try:
            await websocket.send_json(
                {
                    "type": "hello",
                    "sessions": manager.list(),
                    "usage": manager.usage.to_dict(),
                    "accounts": manager.accounts.list(),
                }
            )
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
