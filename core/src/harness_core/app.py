"""API local do núcleo: sessões, terminais por WebSocket, eventos, contas, cota, voz e hooks."""

from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from . import files as fs
from . import gitops
from .accounts import PROVIDERS, AccountStore, UnknownAccount
from .activity import ActivityLog
from .agents import AgentError, AgentStore, allowed_connectors
from .brain_index import BrainIndex
from .kanban import Kanban
from .vault import Vault, VaultError
from .sprites import SpriteStudio
from .attachments import MAX_ATTACHMENT_BYTES, save_attachment
from .config import Settings, load_settings
from .connectors import CATALOG, ConnectorError, ConnectorStore
from .keychain import Keychain
from .keychain import Vault as SecretVault
from .mcp_hub import Hub, ToolError
from .slack import MANIFEST, SlackError
from .projects import ProjectError, ProjectStore
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
    agent: str | None = None


class NewAccount(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class NewProject(BaseModel):
    path: str = Field(min_length=1)
    name: str | None = None


class NewWorktree(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base: str | None = None
    copy_env: bool = True


class GitFiles(BaseModel):
    path: str
    files: list[str] = Field(default_factory=list)


class GitCommit(BaseModel):
    path: str
    message: str = Field(min_length=1)


class GitPath(BaseModel):
    path: str


class AgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""
    cli: str = Field(default="claude", pattern="^(claude|codex)$")
    model: str = ""
    account: str = ""
    folder: str = ""
    color: str = "#82a0ff"
    connectors: str = ""
    prompt: str = ""


class SpriteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    name: str = ""
    description: str = ""
    color: str = "#82a0ff"
    base: str | None = None


class SpriteChoice(BaseModel):
    job: str = Field(pattern="^[a-z0-9]{1,32}$")


class OpenTarget(BaseModel):
    url: str | None = None
    reveal: str | None = None


class WebTab(BaseModel):
    url: str = ""
    cwd: str | None = None


class StageBody(BaseModel):
    stage: str = Field(default="", pattern="^(|ideia|planejando|construindo|em-producao|pausado)$")


class TaskBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    state: str = Field(default="pendente", pattern="^(pendente|em-andamento|em-teste|concluida)$")


class TaskMove(BaseModel):
    state: str = Field(pattern="^(pendente|em-andamento|em-teste|concluida)$")


class NotePath(BaseModel):
    path: str = Field(min_length=4)


class SlackConnect(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    token: str = Field(min_length=5, max_length=300)
    email: str = Field(min_length=3, max_length=200)


class OAuthConnect(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class ConnectorPatch(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    approve_writes: bool | None = None
    reminders: bool | None = None


class ReminderBody(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    quando: str = Field(min_length=1, max_length=100)
    conta: str = ""


class Decision(BaseModel):
    aprovar: bool


class TitlesBody(BaseModel):
    titles: list[str] = Field(default_factory=list, max_length=2000)


def create_app(
    settings: Settings | None = None,
    accounts: AccountStore | None = None,
    transcriber: Transcriber | None = None,
    poll_codex: bool = True,
    poll_ports: bool = True,
    keychain: SecretVault | None = None,
    http=None,
) -> FastAPI:
    settings = settings or load_settings()
    manager = SessionManager(settings, accounts)
    voice = transcriber or Transcriber(settings.home)
    projects = ProjectStore(settings.home)
    agents = AgentStore(settings.home)

    def codex_env() -> tuple[str | None, dict[str, str]]:
        import shutil

        from .sessions import clean_env

        account = manager.accounts.active("codex")
        return shutil.which("codex"), {**clean_env(), **manager.accounts.env("codex", account)}

    studio = SpriteStudio(settings.home, codex_env)
    vault = Vault(settings.brain)
    brain = BrainIndex(vault, settings.home / "brain.db")
    kanban = Kanban(vault)
    connectors = ConnectorStore(settings.home, keychain or Keychain(), http)
    activity = ActivityLog(settings.home / "atividade.db")

    def session_info(session_id: str) -> dict | None:
        session = manager.get(session_id)
        if session is None:
            return None
        agent = None
        if session.agent:
            try:
                agent = agents.get(session.agent)
            except AgentError:
                agent = None
        return {"who": agent.name if agent else session.title, "cwd": session.cwd, "allowed": allowed_connectors(agent)}

    hub = Hub(
        connectors=connectors,
        brain=brain,
        kanban=kanban,
        vault=vault,
        activity=activity,
        publish=manager.events.publish,
        session_info=session_info,
        on_brain_change=lambda project: manager.events.publish({"type": "brain.changed", "project": project}),
    )
    manager.mcp_token = hub.register
    manager.mcp_forget = hub.forget

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        install_relay(settings.relay_path)
        install_cli_shim(settings.relay_path.parent, settings.home)
        # Primeiro índice do Brain em segundo plano: a janela abre sem esperar por ele.
        asyncio.get_running_loop().run_in_executor(None, lambda: brain.refresh(max_age=0))
        pollers = []
        if poll_codex:
            pollers.append(asyncio.create_task(manager.poll_codex_usage()))
        if poll_ports:
            pollers.append(asyncio.create_task(manager.poll_ports()))
        yield
        for poller in pollers:
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

    def require_token_or_query(x_harness_token: str | None = Header(default=None), token: str | None = None) -> None:
        """Imagens e PDFs entram por <img src> e <iframe>, que não mandam cabeçalho."""
        if not (valid(x_harness_token) or valid(token)):
            raise HTTPException(status_code=401, detail="token inválido")

    def fail(exc: Exception, status: int = 400) -> HTTPException:
        code = getattr(exc, "code", None)
        return HTTPException(status_code=409 if code == 409 else status, detail=str(exc))

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
            agent = agents.get(body.agent) if body.agent else None
            session = manager.create(body.kind, body.cwd, body.cols, body.rows, body.title, body.account, body.tag, agent)
        except AgentError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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

    # --- projetos e worktrees -----------------------------------------------

    def projects_changed() -> None:
        manager.events.publish({"type": "projects", "projects": projects.list()})

    def project_path(project_id: str) -> str:
        try:
            return projects.get(project_id).path
        except ProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects", dependencies=[Depends(require_token)])
    def list_projects() -> list[dict]:
        return projects.list()

    @app.post("/projects", dependencies=[Depends(require_token)], status_code=201)
    def add_project(body: NewProject) -> dict:
        try:
            project = projects.add(body.path, body.name)
        except ProjectError as exc:
            raise fail(exc) from exc
        projects_changed()
        return project.__dict__

    @app.delete("/projects/{project_id}", dependencies=[Depends(require_token)], status_code=204)
    def remove_project(project_id: str) -> None:
        try:
            projects.remove(project_id)
        except ProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        projects_changed()

    @app.get("/projects/{project_id}/worktrees", dependencies=[Depends(require_token)])
    async def project_worktrees(project_id: str) -> list[dict]:
        repo = project_path(project_id)
        try:
            items = await gitops.list_worktrees(repo)
        except gitops.GitError as exc:
            raise fail(exc) from exc

        async def summary(item: dict) -> dict:
            try:
                info = await gitops.status(item["path"])
                return {**item, "changes": len(info["files"]), "ahead": info["ahead"], "behind": info["behind"], "missing": False}
            except (gitops.GitError, FileNotFoundError, NotADirectoryError):
                return {**item, "changes": 0, "ahead": 0, "behind": 0, "missing": True}

        return list(await asyncio.gather(*(summary(i) for i in items)))

    @app.post("/projects/{project_id}/worktrees", dependencies=[Depends(require_token)], status_code=201)
    async def new_worktree(project_id: str, body: NewWorktree) -> dict:
        try:
            created = await gitops.create_worktree(project_path(project_id), settings.worktrees, body.name, body.base, body.copy_env)
        except gitops.GitError as exc:
            raise fail(exc) from exc
        manager.events.publish({"type": "worktrees", "project": project_id})
        return created

    @app.delete("/projects/{project_id}/worktrees", dependencies=[Depends(require_token)])
    async def delete_worktree(project_id: str, path: str = Query(...), force: bool = False) -> dict:
        busy = [s.title for s in manager.sessions.values() if s.status != "exited" and _within(s.cwd, path)]
        if busy and not force:
            raise HTTPException(status_code=409, detail=f"feche antes os terminais desta worktree: {', '.join(busy)}")
        try:
            result = await gitops.remove_worktree(project_path(project_id), path, force)
        except gitops.GitError as exc:
            raise fail(exc) from exc
        manager.events.publish({"type": "worktrees", "project": project_id})
        return result

    # --- git da revisão ----------------------------------------------------

    @app.get("/git/status", dependencies=[Depends(require_token)])
    async def git_status(path: str) -> dict:
        try:
            return await gitops.status(path)
        except (gitops.GitError, FileNotFoundError, NotADirectoryError) as exc:
            raise fail(exc) from exc

    @app.get("/git/diff", dependencies=[Depends(require_token)], response_class=PlainTextResponse)
    async def git_diff(path: str, file: str, mode: str = Query(default="head", pattern="^(head|staged|worktree)$"), untracked: bool = False) -> str:
        try:
            fs.inside(path, file)
            return await gitops.diff(path, file, mode, untracked)
        except (gitops.GitError, fs.FileError) as exc:
            raise fail(exc) from exc

    async def git_action(action, *args) -> dict:
        try:
            result = await action(*args)
        except (gitops.GitError, FileNotFoundError) as exc:
            raise fail(exc) from exc
        return {"ok": True, "result": result if isinstance(result, str) else None}

    @app.post("/git/stage", dependencies=[Depends(require_token)])
    async def git_stage(body: GitFiles) -> dict:
        return await git_action(gitops.stage, body.path, body.files)

    @app.post("/git/unstage", dependencies=[Depends(require_token)])
    async def git_unstage(body: GitFiles) -> dict:
        return await git_action(gitops.unstage, body.path, body.files)

    @app.post("/git/commit", dependencies=[Depends(require_token)])
    async def git_commit(body: GitCommit) -> dict:
        return await git_action(gitops.commit, body.path, body.message)

    @app.post("/git/push", dependencies=[Depends(require_token)])
    async def git_push(body: GitPath) -> dict:
        return await git_action(gitops.push, body.path)

    @app.post("/git/pull", dependencies=[Depends(require_token)])
    async def git_pull(body: GitPath) -> dict:
        return await git_action(gitops.pull, body.path)

    # --- arquivos ----------------------------------------------------------

    @app.get("/fs/files", dependencies=[Depends(require_token)])
    async def fs_files(root: str) -> dict:
        try:
            fs.inside(root, ".")
            return {"root": root, "files": await gitops.list_files(root)}
        except (gitops.GitError, fs.FileError) as exc:
            raise fail(exc) from exc

    @app.get("/fs/text", dependencies=[Depends(require_token)])
    def fs_text(root: str, path: str) -> dict:
        try:
            return fs.read_text(root, path)
        except fs.FileError as exc:
            raise fail(exc, 404) from exc

    @app.get("/fs/raw", dependencies=[Depends(require_token_or_query)])
    def fs_raw(root: str, path: str) -> FileResponse:
        try:
            target = fs.inside(root, path)
        except fs.FileError as exc:
            raise fail(exc, 404) from exc
        if not target.is_file():
            raise HTTPException(status_code=404, detail="arquivo não encontrado")
        return FileResponse(target, media_type=fs.media_type(target), headers={"Cache-Control": "no-store"})

    @app.post("/open", dependencies=[Depends(require_token)], status_code=204)
    def open_target(body: OpenTarget) -> None:
        try:
            if body.url:
                fs.open_url(body.url)
            elif body.reveal:
                fs.reveal(body.reveal)
        except fs.FileError as exc:
            raise fail(exc) from exc

    @app.post("/ui/web", dependencies=[Depends(require_token)], status_code=204)
    def open_web_tab(body: WebTab) -> None:
        """Pede à janela uma aba do navegador da MÊTIS (usado pelo `metis web`)."""
        url = body.url.strip()
        if url and not url.startswith(("http://", "https://", "about:blank")):
            raise HTTPException(status_code=400, detail="só abro http, https ou about:blank")
        manager.events.publish({"type": "open-web", "url": url, "cwd": body.cwd})

    # --- Brain e kanban -------------------------------------------------------

    def brain_fail(exc: Exception) -> HTTPException:
        missing = "não encontrad" in str(exc)
        return HTTPException(status_code=404 if missing else 400, detail=str(exc))

    def brain_changed(project: str) -> None:
        manager.events.publish({"type": "brain.changed", "project": project})

    def cwd_of(session: str | None, cwd: str | None) -> str | None:
        found = manager.get(session) if session else None
        return found.cwd if found else cwd

    @app.get("/brain/status", dependencies=[Depends(require_token)])
    def brain_status() -> dict:
        return brain.status()

    @app.get("/brain/search", dependencies=[Depends(require_token)])
    def brain_search(q: str = "", tipo: str = "", projeto: str = "", limit: int = Query(default=40, ge=1, le=200)) -> list[dict]:
        tipos = [x for x in tipo.split(",") if x]
        return brain.search(q, tipos or None, projeto or None, limit)

    @app.get("/brain/graph", dependencies=[Depends(require_token)])
    def brain_graph() -> dict:
        return brain.graph()

    @app.get("/brain/note", dependencies=[Depends(require_token)])
    def brain_note(path: str = "", title: str = "") -> dict:
        try:
            return brain.note(path or None, title or None)
        except VaultError as exc:
            raise brain_fail(exc) from exc

    @app.post("/brain/known", dependencies=[Depends(require_token)])
    def brain_known(body: TitlesBody) -> list[str]:
        return brain.known_titles(body.titles)

    @app.post("/brain/obsidian", dependencies=[Depends(require_token)], status_code=204)
    def brain_obsidian(body: NotePath) -> None:
        """Abre a nota no Obsidian. Só notas de dentro do vault; o endereço é montado aqui."""
        import subprocess
        from urllib.parse import quote, urlencode

        try:
            vault.resolve(body.path)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        url = "obsidian://open?" + urlencode({"vault": vault.root.name, "file": body.path[: -len(".md")]}, quote_via=quote)
        subprocess.run(["open", url], check=False, timeout=10)

    @app.get("/brain/place", dependencies=[Depends(require_token)])
    def brain_place(cwd: str = "", session: str = "") -> dict:
        """O projeto do Brain de uma pasta (ou da pasta de uma sessão), com tarefas e precedentes."""
        folder = cwd_of(session or None, cwd or None)
        note = vault.project_for_dir(folder) if folder else None
        if note is None:
            return {"project": None}
        board = next((p for p in kanban.projects() if p["name"] == note.name), None)
        return {
            "project": board,
            "tasks": kanban.tasks(note.name),
            "precedents": brain.precedents(note.name, brain.project_context(note.name), 6),
        }

    @app.get("/brain/precedents", dependencies=[Depends(require_token)])
    def brain_precedents(project: str = "", q: str = "", cwd: str = "", limit: int = Query(default=8, ge=1, le=30)) -> list[dict]:
        if not project and cwd:
            note = vault.project_for_dir(cwd)
            project = note.name if note else ""
        try:
            context = q or (brain.project_context(project) if project else "")
        except VaultError as exc:
            raise brain_fail(exc) from exc
        return brain.precedents(project or None, context, limit)

    @app.get("/brain/session-context", dependencies=[Depends(require_token)], response_class=PlainTextResponse)
    def brain_session_context(session: str = "", cwd: str = "") -> str:
        """Texto do hook SessionStart: o Claude Code junta ao contexto o que sair aqui."""
        folder = cwd_of(session or None, cwd or None)
        try:
            return brain.session_context(folder) if folder else ""
        except (VaultError, OSError):
            return ""

    @app.get("/brain/projects", dependencies=[Depends(require_token)])
    def brain_projects() -> list[dict]:
        return kanban.projects()

    @app.put("/brain/projects/{name}/stage", dependencies=[Depends(require_token)])
    def brain_stage(name: str, body: StageBody) -> dict:
        try:
            project = kanban.set_stage(name, body.stage)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        brain_changed(name)
        return project

    @app.get("/brain/projects/{name}/tasks", dependencies=[Depends(require_token)])
    def brain_tasks(name: str) -> list[dict]:
        try:
            return kanban.tasks(name)
        except VaultError as exc:
            raise brain_fail(exc) from exc

    @app.post("/brain/projects/{name}/tasks", dependencies=[Depends(require_token)], status_code=201)
    def brain_add_task(name: str, body: TaskBody) -> dict:
        try:
            task = kanban.add(name, body.text, body.state)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        brain_changed(name)
        return task

    @app.put("/brain/projects/{name}/tasks/{task_id}", dependencies=[Depends(require_token)])
    def brain_move_task(name: str, task_id: str, body: TaskMove) -> dict:
        try:
            task = kanban.move(name, task_id, body.state)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        brain_changed(name)
        return task

    # --- central de MCP (uma por sessão de agente, pelo token dela) ------------------

    @app.post("/mcp")
    async def mcp_endpoint(request: Request, authorization: str | None = Header(default=None)) -> Response:
        token = authorization.split(" ", 1)[1].strip() if authorization and authorization.lower().startswith("bearer ") else None
        if hub.context(token) is None:
            return JSONResponse({"error": "token da sessão inválido"}, status_code=401)
        try:
            body = json.loads(await request.body() or b"null")
        except json.JSONDecodeError:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}}, status_code=400)
        reply = await hub.handle_body(token, body)
        return Response(status_code=202) if reply is None else JSONResponse(reply)

    @app.get("/mcp")
    def mcp_stream() -> Response:
        return Response(status_code=405)  # sem fluxo de eventos: toda resposta vem na própria chamada

    @app.delete("/mcp")
    def mcp_close() -> Response:
        return Response(status_code=200)

    # --- conectores, lembretes, atividade e aprovações --------------------------------

    def connectors_changed() -> None:
        manager.events.publish({"type": "connectors", "accounts": [a.to_dict() for a in connectors.list()]})

    @app.get("/conectores", dependencies=[Depends(require_token)])
    def list_connectors() -> dict:
        return {"catalog": CATALOG, "accounts": [a.to_dict() for a in connectors.list()]}

    @app.post("/conectores/slack", dependencies=[Depends(require_token)], status_code=201)
    def connect_slack(body: SlackConnect) -> dict:
        try:
            account = connectors.add_slack(body.name, body.token, body.email)
        except ConnectorError as exc:
            raise fail(exc) from exc
        connectors_changed()
        return account.to_dict()

    @app.get("/conectores/slack/manifesto", dependencies=[Depends(require_token)], response_class=PlainTextResponse)
    def slack_manifest() -> str:
        return MANIFEST

    @app.post("/conectores/oauth/{kind}", dependencies=[Depends(require_token)])
    def connect_oauth(kind: str, body: OAuthConnect) -> dict:
        try:
            url = connectors.start_oauth(kind, body.name, f"{settings.url}/conectores/oauth/retorno")
        except ConnectorError as exc:
            raise fail(exc) from exc
        return {"url": url}

    @app.get("/conectores/oauth/retorno", response_class=HTMLResponse)
    def oauth_return(state: str = "", code: str = "", error: str = "", error_description: str = "") -> HTMLResponse:
        """O navegador volta aqui depois do login (sem token da MÊTIS: quem prova é o state)."""
        if error or not code:
            return HTMLResponse(_page("Login não concluído", error_description or error or "o serviço não devolveu o código"), status_code=400)
        try:
            account = connectors.finish_oauth(state, code)
        except ConnectorError as exc:
            return HTMLResponse(_page("Login não concluído", str(exc)), status_code=400)
        connectors_changed()
        return HTMLResponse(_page(f"{account.name} conectado", "Pode fechar esta aba e voltar para a MÊTIS."))

    @app.patch("/conectores/{account_id}", dependencies=[Depends(require_token)])
    def patch_connector(account_id: str, body: ConnectorPatch) -> dict:
        try:
            account = connectors.update(account_id, **body.model_dump())
        except ConnectorError as exc:
            raise fail(exc, 404) from exc
        connectors_changed()
        return account.to_dict()

    @app.delete("/conectores/{account_id}", dependencies=[Depends(require_token)], status_code=204)
    def delete_connector(account_id: str) -> None:
        try:
            connectors.remove(account_id)
        except ConnectorError as exc:
            raise fail(exc, 404) from exc
        connectors_changed()

    @app.post("/conectores/{account_id}/teste", dependencies=[Depends(require_token)])
    def test_connector(account_id: str) -> dict:
        try:
            account = connectors.get(account_id)
            if account.kind == "slack":
                account, slack = connectors.slack(account_id)
                slack.send(account.meta["dm"], "✅ Teste da MÊTIS: se isto tocou no celular, os avisos estão funcionando.")
                return {"message": f"Mensagem de teste enviada na sua DM em {account.name}."}
            tools = connectors.mcp(account_id).tools()
            return {"message": f"{account.name} respondeu com {len(tools)} ferramentas."}
        except (ConnectorError, SlackError, RuntimeError, OSError) as exc:
            raise fail(exc) from exc

    @app.post("/lembretes", dependencies=[Depends(require_token)], status_code=201)
    def create_reminder(body: ReminderBody) -> dict:
        account = body.conta or next((a.id for a in connectors.list() if a.reminders), "")
        if not account:
            raise HTTPException(status_code=400, detail="nenhuma conta do Slack conectada para lembretes; conecte uma em Conectores")
        try:
            return {"message": hub.remind(account, body.texto, body.quando)}
        except (ToolError, ConnectorError, SlackError) as exc:
            raise fail(exc) from exc

    @app.get("/atividade", dependencies=[Depends(require_token)])
    def list_activity(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict]:
        return activity.recent(limit)

    @app.get("/aprovacoes", dependencies=[Depends(require_token)])
    def list_approvals() -> list[dict]:
        return [p.to_dict() for p in hub.pending.values()]

    @app.post("/aprovacoes/{approval_id}", dependencies=[Depends(require_token)], status_code=204)
    def decide_approval(approval_id: str, body: Decision) -> None:
        if not hub.decide(approval_id, body.aprovar):
            raise HTTPException(status_code=404, detail="aprovação não encontrada ou já respondida")

    # --- agentes em arquivo --------------------------------------------------

    def agents_changed() -> None:
        manager.events.publish({"type": "agents", "agents": agents.list()})

    @app.get("/agents", dependencies=[Depends(require_token)])
    def list_agents() -> list[dict]:
        return agents.list()

    @app.post("/agents", dependencies=[Depends(require_token)], status_code=201)
    def create_agent(body: AgentBody) -> dict:
        try:
            agent = agents.save(body.model_dump())
        except AgentError as exc:
            raise fail(exc) from exc
        agents_changed()
        return agent.to_dict()

    @app.put("/agents/{agent_id}", dependencies=[Depends(require_token)])
    def update_agent(agent_id: str, body: AgentBody) -> dict:
        try:
            agents.get(agent_id)
            agent = agents.save(body.model_dump(), agent_id)
        except AgentError as exc:
            raise fail(exc, 404) from exc
        agents_changed()
        return agent.to_dict()

    @app.delete("/agents/{agent_id}", dependencies=[Depends(require_token)], status_code=204)
    def delete_agent(agent_id: str) -> None:
        try:
            agents.delete(agent_id)
        except AgentError as exc:
            raise fail(exc, 404) from exc
        agents_changed()

    @app.post("/agents/{agent_id}/sprite", dependencies=[Depends(require_token)], status_code=204)
    async def set_sprite(agent_id: str, request: Request) -> None:
        try:
            agents.set_sprite(agent_id, await request.body())
        except AgentError as exc:
            raise fail(exc) from exc
        agents_changed()

    @app.delete("/agents/{agent_id}/sprite", dependencies=[Depends(require_token)], status_code=204)
    def clear_sprite(agent_id: str) -> None:
        try:
            agents.clear_sprite(agent_id)
        except AgentError as exc:
            raise fail(exc, 404) from exc
        agents_changed()

    @app.get("/agents/{agent_id}/sprite", dependencies=[Depends(require_token_or_query)])
    def get_sprite(agent_id: str) -> FileResponse:
        try:
            path = agents.sprite_path(agent_id)
        except AgentError as exc:
            raise fail(exc, 404) from exc
        if path is None:
            raise HTTPException(status_code=404, detail="agente sem sprite")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    # --- sprites por prompt (Codex + pixelização) ---------------------------------

    def sprite_changed(job) -> None:
        manager.events.publish({"type": "sprite.job", "job": job.to_dict()})

    @app.post("/sprites/jobs", dependencies=[Depends(require_token)], status_code=202)
    async def start_sprite(body: SpriteRequest) -> dict:
        try:
            job = studio.start(body.prompt, body.name, body.description, body.color, body.base, sprite_changed)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="rascunho anterior não encontrado") from exc
        return job.to_dict()

    @app.get("/sprites/jobs/{job_id}", dependencies=[Depends(require_token)])
    def sprite_job(job_id: str) -> dict:
        job = studio.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="trabalho desconhecido")
        return job.to_dict()

    @app.get("/sprites/jobs/{job_id}/image", dependencies=[Depends(require_token_or_query)])
    def sprite_job_image(job_id: str) -> FileResponse:
        try:
            path = studio.image(job_id)
        except KeyError:
            path = None
        if path is None:
            raise HTTPException(status_code=404, detail="sprite ainda não pronta")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/agents/{agent_id}/sprite/from-job", dependencies=[Depends(require_token)], status_code=204)
    def sprite_from_job(agent_id: str, body: SpriteChoice) -> None:
        path = studio.image(body.job)
        if path is None:
            raise HTTPException(status_code=404, detail="sprite ainda não pronta")
        try:
            agents.set_sprite(agent_id, path.read_bytes())
        except AgentError as exc:
            raise fail(exc, 404) from exc
        agents_changed()

    @app.post("/agents/import/maestri", dependencies=[Depends(require_token)])
    def import_maestri(roles: str = Query(default="~/Documents/Brain/.maestri/roles")) -> dict:
        folder = __import__("pathlib").Path(roles).expanduser()
        if not folder.is_dir():
            raise HTTPException(status_code=404, detail=f"pasta de papéis não encontrada: {roles}")
        imported = agents.import_maestri(folder)
        if imported:
            agents_changed()
        return {"imported": [a.name for a in imported]}

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
                    "projects": projects.list(),
                    "agents": agents.list(),
                }
            )
            while True:
                await websocket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            manager.events.unsubscribe(queue)

    return app


def _page(title: str, text: str) -> str:
    import html

    return (
        "<!doctype html><meta charset='utf-8'><title>MÊTIS</title>"
        "<body style='font:15px -apple-system,system-ui;background:#1c1c1f;color:#e8e8ee;display:grid;place-items:center;height:100vh;margin:0'>"
        f"<div style='max-width:420px;text-align:center'><h2>{html.escape(title)}</h2><p style='color:#a6a6b0'>{html.escape(text)}</p></div>"
    )


def _within(child: str, parent: str) -> bool:
    import os

    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent.rstrip("/") + "/")


async def _json(request: Request) -> dict:
    try:
        data = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
