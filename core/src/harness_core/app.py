"""API local do núcleo: sessões, terminais por WebSocket, eventos, contas, cota, voz e hooks."""

from __future__ import annotations

import asyncio
import os
import json
from datetime import datetime
import secrets
import subprocess
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from . import files as fs
from . import gitops
from .accounts import PROVIDERS, AccountStore, UnknownAccount
from .activity import ActivityLog
from .agent_draft import DraftError, draft_agent
from .agents import Agent, AgentError, AgentStore, allowed_connectors
from .capture import interpret
from .study import DAILY_BEFORE, StudyLog
from .boards import BoardConflict, BoardError, BoardStore
from .brain_index import BrainIndex
from .automation_engine import Engine
from .automations import AutomationError, AutomationStore, blank, connectors_used, validate
from .brain_tools import BrainTools
from .claude_print import ClaudePrintError, ask_json
from .semantic import Embedder
from .suggestions import SuggestionError, Suggestions, render_pending
from .history import codex_rollout_for
from .history import list_sessions as history_sessions
from .system import Awake, list_skills, mac_notify, process_table, tree_usage, wants_awake
from .prefs import PrefsError
from .transcript import context_breakdown, last_messages
from .kanban import Kanban
from .vault import Vault, VaultError
from .sprites import SpriteStudio
from .attachments import MAX_ATTACHMENT_BYTES, save_attachment
from .config import Settings, load_settings
from .connectors import CATALOG, ConnectorError, ConnectorStore
from .keychain import Keychain
from .keychain import Vault as SecretVault
from .mcp_hub import Context, Hub, ToolError
from .slack import MANIFEST, SlackError
from .projects import ProjectError, ProjectStore
from .relay import install_cli_shim, install_relay
from .routines import DAYS, Routine, RoutineError, RoutineStore, decide, next_slot, slot_on
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
    #: Retomar uma conversa (`claude --resume <id>`, `codex resume <id>`).
    resume: str | None = Field(default=None, pattern="^[A-Za-z0-9-]{8,80}$")
    #: Modo de permissão só desta sessão (padrao, manual, auto, yolo).
    permissao: str | None = Field(default=None, pattern="^(padrao|manual|auto|yolo)$")
    cwd: str | None = None
    cols: int = Field(default=120, ge=20, le=500)
    rows: int = Field(default=32, ge=5, le=300)
    title: str | None = None
    account: str | None = None
    tag: str | None = Field(default=None, pattern="^[a-z]{1,20}$")
    agent: str | None = None
    draft: DraftAgent | None = None


class DraftAgent(BaseModel):
    """Agente ainda não salvo, para "testar antes de salvar"."""

    name: str = Field(min_length=1, max_length=60)
    cli: str = Field(default="claude", pattern="^(claude|codex)$")
    model: str = ""
    folder: str = ""
    prompt: str = ""


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
    pain: str = ""
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


class RoutineBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    agent: str = ""
    cli: str = Field(default="claude", pattern="^(claude|codex)$")
    folder: str = ""
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    time: str = Field(min_length=1, max_length=8)
    catchup: int = Field(default=60, ge=0, le=7 * 24 * 60)
    notify: bool = True
    active: bool = True
    prompt: str = Field(min_length=1, max_length=8000)


class CaptureBody(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)


class StudyBlock(BaseModel):
    minutos: float = Field(gt=0, le=240)
    assunto: str = Field(default="", max_length=200)


class DraftRequest(BaseModel):
    descricao: str = Field(min_length=1, max_length=2000)


class Decision(BaseModel):
    aprovar: bool


class TitlesBody(BaseModel):
    titles: list[str] = Field(default_factory=list, max_length=2000)


class MacNotice(BaseModel):
    titulo: str = Field(min_length=1, max_length=120)
    texto: str = Field(default="", max_length=240)


class ScriptsBody(BaseModel):
    setup: str | None = Field(default=None, max_length=4000)
    arquivar: str | None = Field(default=None, max_length=4000)


class RestartBody(BaseModel):
    continuar: bool = False


class HandOffBody(BaseModel):
    para: str | None = Field(default=None, pattern="^(claude|codex)$")
    nota: str = Field(default="", max_length=2000)


class NewBoard(BaseModel):
    projeto: str = Field(min_length=1)
    nome: str = Field(min_length=1, max_length=120)


class SaveBoard(BaseModel):
    path: str = Field(min_length=1)
    canvas: dict
    base: float = 0


class LinkNote(BaseModel):
    sessao: str = Field(min_length=1)
    nota: str = Field(min_length=1)


class SessionMessage(BaseModel):
    texto: str = Field(min_length=1, max_length=20000)


class NewAutomation(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    desenho: dict | None = None


class AutomationBody(BaseModel):
    desenho: dict


class PublishBody(BaseModel):
    versao: str = ""


class ActiveBody(BaseModel):
    ativa: bool


class TestBody(BaseModel):
    desde: str = ""
    passo: str = ""
    execucao: int = 0


class RerunBody(BaseModel):
    desde: str = Field(min_length=1)


class EmbedBody(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)


class AcceptBody(BaseModel):
    titulo: str = Field(default="", max_length=200)
    resumo: str = Field(default="", max_length=1200)


def create_app(
    settings: Settings | None = None,
    accounts: AccountStore | None = None,
    transcriber: Transcriber | None = None,
    poll_codex: bool = True,
    poll_ports: bool = True,
    keychain: SecretVault | None = None,
    http=None,
    run_scheduler: bool = True,
    embedder: Embedder | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    manager = SessionManager(settings, accounts)
    voice = transcriber or Transcriber(settings.home)
    projects = ProjectStore(settings.home)
    # Pastas confiáveis para a CLI: os repositórios cadastrados e as worktrees da MÊTIS.
    manager.trusted_roots = lambda: [p["path"] for p in projects.list()] + [str(settings.worktrees)]
    agents = AgentStore(settings.home)

    def codex_env() -> tuple[str | None, dict[str, str]]:
        import shutil

        from .sessions import clean_env

        account = manager.accounts.active("codex")
        return shutil.which("codex"), {**clean_env(), **manager.accounts.env("codex", account)}

    studio = SpriteStudio(settings.home, codex_env)
    vault = Vault(settings.brain)
    # Busca por significado: o modelo só carrega no núcleo, sob demanda (semantic.py).
    embedder = embedder or Embedder(settings.home / "modelos")
    brain = BrainIndex(vault, settings.home / "brain.db", encode=embedder.encode)

    def claude_env() -> dict[str, str]:
        from .sessions import clean_env

        # BRAIN_REGISTRAR=off: o pedido pontual não dispara os hooks de registro do Brain.
        return {**clean_env(), **manager.accounts.env("claude", manager.accounts.active("claude")), "BRAIN_REGISTRAR": "off"}

    def judge(prompt: str) -> dict:
        """O juiz das sugestões: Haiku pelo plano, sem ferramentas; uma segunda tentativa se o JSON quebrar."""
        try:
            return ask_json(prompt, claude_env(), settings.home / "juiz", model="haiku", bare=True)
        except ClaudePrintError as exc:
            if "JSON" not in str(exc):
                raise
            return ask_json(prompt, claude_env(), settings.home / "juiz", model="haiku", bare=True)

    suggestions = Suggestions(settings.home, brain, vault, judge=judge, publish=lambda event: manager.events.publish(event))
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
        brain_tools=BrainTools(brain, pending=lambda project: suggestions.list(project)),
    )
    manager.mcp_token = hub.register
    manager.mcp_forget = hub.forget
    routines = RoutineStore(settings.home)
    study = StudyLog(settings.home, vault)

    def dm_pedro(text: str) -> str:
        """Mensagem do bot na DM do Pedro (conta de lembretes). Devolve o que deu errado, se deu."""
        account = next((a for a in connectors.list() if a.reminders), None)
        if account is None:
            return "sem conta do Slack para avisar"
        try:
            _, slack = connectors.slack(account.id)
            slack.send(account.meta["dm"], text)
        except (ConnectorError, SlackError, OSError, KeyError) as exc:
            return f"Slack falhou: {exc}"
        return ""

    boards = BoardStore(vault, brain)
    awake = Awake()

    def hook_notice(name: str, message: str | None) -> str | None:
        """Qual aviso o hook pede: Stop = terminou; Notification = espera você, menos o "estou
        esperando sua resposta" que o Claude manda depois de um minuto parado (já avisou no Stop)."""
        if name == "Stop":
            return "terminou"
        if name == "Notification" and not (message or "").lower().startswith("claude is waiting for your input"):
            return "espera"
        return None

    def on_hook(session, name: str, message: str | None) -> None:
        """Sem janela aberta, o núcleo mesmo avisa no macOS quando o agente termina ou espera você."""
        if manager.events.listeners or session.kind not in ("claude", "codex"):
            return
        kind = hook_notice(name, message)
        notices = manager.prefs.get()["avisos"]
        if kind is None or notices["silencio"]:
            return
        if kind == "espera" and notices["espera"]:
            mac_notify(f"{session.title} espera você", message or Path(session.cwd).name, notices["som"])
        elif kind == "terminou" and notices["terminou"]:
            mac_notify(f"{session.title} terminou", Path(session.cwd).name, notices["som"])

    manager.on_hook = on_hook
    automations = AutomationStore(settings.home)
    engine = Engine(settings.home, automations, hub, manager, brain, kanban, vault, agents, notify=dm_pedro, publish=lambda event: manager.events.publish(event))

    def notify_routine(routine: Routine, who: str, slot) -> str:
        """Aviso no Slack (conta de lembretes) de que a rotina abriu. Devolve o que deu errado, se deu."""
        account = next((a for a in connectors.list() if a.reminders), None)
        if account is None:
            return "sem conta do Slack para avisar"
        try:
            _, slack = connectors.slack(account.id)
            when = f" das {slot:%H:%M}" if slot else ""
            slack.send(account.meta["dm"], f"🔔 {who} te chamou na MÊTIS: {routine.name}{when}. Abra o terminal dela no Mac.")
        except (ConnectorError, SlackError, OSError, KeyError) as exc:
            return f"aviso no Slack falhou: {exc}"
        return ""

    async def run_routine(routine: Routine, slot, status: str) -> dict:
        """Abre o terminal da rotina (no loop: o PTY nasce nele) e avisa no Slack."""
        try:
            agent = agents.get(routine.agent) if routine.agent else None
            session = manager.create(
                agent.cli if agent else routine.cli,
                routine.folder or None,
                title=None if agent else routine.name,
                tag="rotina",
                agent=agent,
                prompt=routine.prompt,
            )
        except (AgentError, UnknownKind, ExecutableNotFound, OSError) as exc:
            run = routines.record(routine.id, slot, "erro", detail=str(exc))
            manager.events.publish({"type": "routine.run", "routine": routine.to_dict(), "run": run})
            return run
        problem = await asyncio.to_thread(notify_routine, routine, session.title, slot) if routine.notify else ""
        run = routines.record(routine.id, slot, status, session.id, problem)
        manager.events.publish({"type": "routine.run", "routine": routine.to_dict(), "run": run, "session": session.id})
        return run

    async def scheduler() -> None:
        """A cada 20 s: rotina na hora roda; atrasada (Mac dormindo) recupera na janela ou pula."""
        await asyncio.sleep(3)
        while True:
            now = datetime.now().astimezone()
            for routine in routines.list():
                try:
                    verdict = decide(routine, now, routines.last_handled(routine.id))
                except RoutineError:
                    continue
                if verdict is None:
                    continue
                action, slot = verdict
                if action == "pular":
                    run = routines.record(routine.id, slot, "pulou", detail=f"o Mac estava dormindo às {slot:%H:%M}")
                    manager.events.publish({"type": "routine.run", "routine": routine.to_dict(), "run": run})
                else:
                    await run_routine(routine, slot, "rodou" if action == "rodar" else "recuperada")
            try:
                await engine.tick(now)
            except Exception as exc:  # o agendador das rotinas nunca para por causa de uma automação
                manager.events.publish({"type": "automation.error", "automation": "", "error": str(exc)})
            working = sum(1 for s in manager.sessions.values() if s.status == "working")
            if awake.apply(wants_awake(manager.prefs.get()["manter_acordado"], working, len(engine.runs))):
                manager.events.publish({"type": "awake", "ativo": awake.active})
            await asyncio.sleep(20)

    async def brain_worker() -> None:
        """A cada 2 min: vetores das notas novas, sugestões dos registros novos e o modelo parado sai da memória."""
        await asyncio.sleep(8)
        while True:
            try:
                await asyncio.to_thread(brain.sync_vectors, 60.0)
                await asyncio.to_thread(suggestions.scan)
            except Exception as exc:  # o Brain nunca derruba o núcleo
                manager.events.publish({"type": "brain.error", "error": str(exc)})
            embedder.tick()
            await asyncio.sleep(120)

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
        if run_scheduler:
            pollers.append(asyncio.create_task(scheduler()))
            pollers.append(asyncio.create_task(brain_worker()))
        yield
        for poller in pollers:
            poller.cancel()
            with suppress(asyncio.CancelledError):
                await poller
        await manager.close_all()
        awake.stop()

    app = FastAPI(title="Harness core", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.manager = manager
    app.state.brain = brain
    app.state.suggestions = suggestions
    app.state.hub = hub
    app.state.embedder = embedder
    app.state.engine = engine
    app.state.cli_homes = None  # None = ~/.claude e ~/.codex; os testes apontam para pastas temporárias
    app.state.automations = automations
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

    @app.post("/desligar", dependencies=[Depends(require_token)], status_code=202)
    async def shutdown() -> dict:
        """Desliga a MÊTIS de vez: fecha os terminais e sai (a janela não derruba o núcleo sozinha)."""
        import signal

        open_sessions = len(manager.list())

        def stop() -> None:
            os.kill(os.getpid(), signal.SIGTERM)  # o uvicorn fecha as sessões direito

            def force() -> None:
                time.sleep(10)
                os._exit(0)  # o encerramento travou: sai assim mesmo, quem pediu quer o núcleo fora

            threading.Thread(target=force, name="desligar-a-forca", daemon=True).start()

        asyncio.get_running_loop().call_later(0.3, stop)
        return {"fechando": open_sessions}

    # --- sessões -----------------------------------------------------------

    @app.get("/sessions", dependencies=[Depends(require_token)])
    def list_sessions() -> list[dict]:
        return manager.list()

    @app.post("/sessions", dependencies=[Depends(require_token)], status_code=201)
    async def create_session(body: NewSession) -> dict:
        # async de propósito: o PTY é lido pelo loop do asyncio, então precisa nascer nele.
        try:
            agent = agents.get(body.agent) if body.agent else None
            if body.draft is not None:
                d = body.draft
                agent = Agent(id="rascunho", name=d.name, cli=d.cli, model=d.model, folder=d.folder, prompt=d.prompt)
            session = manager.create(body.kind, body.cwd, body.cols, body.rows, body.title, body.account, body.tag, agent,
                                     resume=body.resume, permission=body.permissao)  # fmt: skip
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

    def reopen(old, *, kind: str | None = None, resume: str | None = None, prompt: str | None = None):
        """Sessão nova no lugar de outra: mesma pasta, conta, agente e etiqueta."""
        agent = None
        if old.agent:
            try:
                agent = agents.get(old.agent)
            except AgentError:
                agent = None
        if kind and agent is not None and agent.cli != kind:
            agent = None  # passar o trabalho para a outra CLI: o agente é de uma CLI só
        same_kind = (kind or old.kind) == old.kind
        return manager.create(kind or old.kind, old.cwd, title=None if agent else (old.title if same_kind else None),
                              account_id=old.account if same_kind else None, tag=old.tag, agent=agent, resume=resume, prompt=prompt)  # fmt: skip

    @app.post("/sessions/{session_id}/reiniciar", dependencies=[Depends(require_token)], status_code=201)
    async def restart_session(session_id: str, body: RestartBody) -> dict:
        """Reinicia o agente que saiu (ou trava): mesma pasta e conta; `continuar` retoma a conversa do Claude."""
        old = manager.get(session_id)
        if old is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        resume = None
        if body.continuar:
            if old.kind == "claude":
                resume = (old.statusline or {}).get("session_id")
            elif old.kind == "codex":
                found = await asyncio.to_thread(codex_rollout_for, manager.accounts.list(), old.cwd, old.created_at - 5, app.state.cli_homes)
                resume = found["id"] if found else None
            if not resume:
                raise HTTPException(status_code=409, detail="não achei a conversa desta sessão para continuar; reinicie do zero")
        if old.pty.alive:
            await manager.close(session_id)
        else:
            manager.forget(session_id)  # já saiu: sai da lista para a nova nascer com o mesmo nome
        try:
            session = reopen(old, resume=resume)
        except (UnknownKind, ExecutableNotFound, UnknownAccount, OSError) as exc:
            raise fail(exc) from exc
        return session.to_dict()

    @app.post("/sessions/{session_id}/passar", dependencies=[Depends(require_token)], status_code=201)
    async def hand_off(session_id: str, body: HandOffBody) -> dict:
        """Passa o trabalho para a outra CLI: sessão nova na mesma pasta, com o transcript e as últimas mensagens."""
        old = manager.get(session_id)
        if old is None or old.kind not in ("claude", "codex"):
            raise HTTPException(status_code=404, detail="só sessões do Claude ou do Codex passam o trabalho")
        target = body.para or ("codex" if old.kind == "claude" else "claude")
        transcript = (old.statusline or {}).get("transcript") if old.kind == "claude" else None
        if old.kind == "codex":
            found = await asyncio.to_thread(codex_rollout_for, manager.accounts.list(), old.cwd, old.created_at - 5, app.state.cli_homes)
            transcript = found["arquivo"] if found else None
        recent = last_messages(transcript, 6) if transcript and old.kind == "claude" else []
        names = {"claude": "Claude", "codex": "Codex"}
        lines = [f"Continue o trabalho que estava com o {names[old.kind]} nesta mesma pasta ({old.cwd})."]
        if transcript:
            lines.append(f"O registro completo da conversa está em {transcript} (JSONL): leia o fim dele para saber o que foi pedido e feito.")
        if recent:
            lines.append("Últimas mensagens:")
            lines += [f"- {'Pedro' if m['role'] == 'voce' else names[old.kind]}: {m['text']}" for m in recent]
        lines.append("Confira o estado do repositório (git status e git diff) antes de seguir, diga em duas linhas onde o trabalho parou e continue de onde parou.")
        if body.nota:
            lines.append(f"Recado do Pedro: {body.nota}")
        try:
            session = reopen(old, kind=target, prompt="\n".join(lines))
        except (UnknownKind, ExecutableNotFound, UnknownAccount, OSError) as exc:
            raise fail(exc) from exc
        return session.to_dict()

    # --- histórico de sessões e ajustes (v0.9.2) ---------------------------------------

    @app.get("/historico", dependencies=[Depends(require_token)])
    async def session_history(q: str = "", cwd: str = "", limit: int = Query(default=60, ge=1, le=300)) -> list[dict]:
        return await asyncio.to_thread(history_sessions, manager.accounts.list(), q, limit, cwd, app.state.cli_homes)

    @app.get("/recursos", dependencies=[Depends(require_token)])
    def resources() -> dict:
        """Memória e CPU do núcleo e de cada sessão (com os processos filhos), o modelo e o Mac acordado."""
        table = process_table()
        core = tree_usage({pid: row for pid, row in table.items()}, os.getpid())
        own = table.get(os.getpid(), (0, 0.0, 0.0, ""))
        sessions = []
        for session in manager.sessions.values():
            pid = session.pty.pid
            usage = tree_usage(table, pid) if pid else {"mb": 0, "cpu": 0.0, "processos": 0, "comandos": []}
            sessions.append({"id": session.id, "title": session.title, "kind": session.kind, "status": session.status, "cwd": session.cwd, **usage})
        sessions.sort(key=lambda item: -item["mb"])
        return {
            "nucleo": {"mb": round(own[1]), "cpu": own[2], "com_sessoes_mb": core["mb"]},
            "sessoes": sessions,
            "modelo": embedder.status(),
            "acordado": {"modo": manager.prefs.get()["manter_acordado"], "ativo": awake.active},
            "janelas": manager.events.listeners,
        }

    @app.get("/skills", dependencies=[Depends(require_token)])
    def skills(cwd: str = "") -> list[dict]:
        """Skills do usuário (Claude de cada conta e Codex) e do projeto da pasta."""
        dirs = [Path.home() / ".claude" / "skills", Path.home() / ".codex" / "skills"]
        for provider, entry in manager.accounts.list().items():
            for account in entry["accounts"]:
                if account.get("dir"):
                    dirs.append(Path(account["dir"]).expanduser() / "skills")
        return list_skills(dirs, cwd or None)

    @app.get("/projects/{project_id}/scripts", dependencies=[Depends(require_token)])
    def project_scripts(project_id: str) -> dict:
        try:
            return projects.scripts(project_id)
        except ProjectError as exc:
            raise fail(exc, 404) from exc

    @app.put("/projects/{project_id}/scripts", dependencies=[Depends(require_token)])
    def set_project_scripts(project_id: str, body: ScriptsBody) -> dict:
        try:
            return projects.set_scripts(project_id, body.setup, body.arquivar)
        except ProjectError as exc:
            raise fail(exc, 404) from exc

    @app.post("/avisos/mac", dependencies=[Depends(require_token)], status_code=204)
    def notify_mac(body: MacNotice) -> None:
        """Aviso do macOS pedido pela janela (aberta, mas sem foco). Respeita o silêncio dos Ajustes."""
        notices = manager.prefs.get()["avisos"]
        if not notices["silencio"]:
            mac_notify(body.titulo, body.texto, notices["som"])

    @app.get("/ajustes", dependencies=[Depends(require_token)])
    def get_prefs() -> dict:
        return manager.prefs.get()

    @app.put("/ajustes", dependencies=[Depends(require_token)])
    def put_prefs(body: dict) -> dict:
        try:
            data = manager.prefs.update(body)
        except (PrefsError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        manager.events.publish({"type": "prefs", "prefs": data})
        return data

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
        script = projects.scripts(project_id).get("setup")
        if script:
            # O setup roda num terminal à vista na worktree nova: dá para acompanhar e corrigir.
            try:
                setup = manager.create("shell", created["path"], title=f"Setup · {created.get('branch') or body.name}")
                manager.send_text(setup.id, script, paste=False)
                created = {**created, "setup": setup.id}
            except (UnknownKind, ExecutableNotFound, OSError) as exc:
                created = {**created, "setup_erro": str(exc)}
        return created

    @app.delete("/projects/{project_id}/worktrees", dependencies=[Depends(require_token)])
    async def delete_worktree(project_id: str, path: str = Query(...), force: bool = False) -> dict:
        busy = [s.title for s in manager.sessions.values() if s.status != "exited" and _within(s.cwd, path)]
        if busy and not force:
            raise HTTPException(status_code=409, detail=f"feche antes os terminais desta worktree: {', '.join(busy)}")
        archive_note = ""
        try:
            script = projects.scripts(project_id).get("arquivar") if Path(path).is_dir() else ""
        except ProjectError:
            script = ""
        if script:
            # Antes de apagar: o script de arquivamento roda na worktree (até 2 min).
            done = await asyncio.to_thread(
                lambda: subprocess.run(["/bin/zsh", "-lc", script], cwd=path, capture_output=True, text=True, timeout=120)
            )
            if done.returncode != 0 and not force:
                raise HTTPException(status_code=409, detail=f"o script de arquivamento falhou: {(done.stderr or done.stdout).strip()[-400:]}")
            archive_note = (done.stdout or "").strip()[-400:]
        try:
            result = await gitops.remove_worktree(project_path(project_id), path, force)
        except gitops.GitError as exc:
            raise fail(exc) from exc
        manager.events.publish({"type": "worktrees", "project": project_id})
        return {**result, **({"arquivamento": archive_note} if archive_note else {})}

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
        """Abre a nota (ou um quadro .canvas) no Obsidian. Só arquivo de dentro do vault; o endereço é montado aqui."""
        import subprocess
        from urllib.parse import quote, urlencode

        if body.path.endswith(".canvas"):
            try:
                boards.read(body.path)  # confere que o quadro existe e mora num projeto do vault
            except BoardError as exc:
                raise board_fail(exc) from exc
            target = body.path  # arquivo que não é .md vai com a extensão no endereço do Obsidian
        else:
            try:
                vault.resolve(body.path)
            except VaultError as exc:
                raise brain_fail(exc) from exc
            target = body.path[: -len(".md")]
        url = "obsidian://open?" + urlencode({"vault": vault.root.name, "file": target}, quote_via=quote)
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
        return brain.precedents(project or None, context, limit, free_text=bool(q), wait=20.0 if q else 0.0)

    @app.get("/brain/session-context", dependencies=[Depends(require_token)], response_class=PlainTextResponse)
    def brain_session_context(session: str = "", cwd: str = "") -> str:
        """Texto do hook SessionStart: o Claude Code junta ao contexto o que sair aqui."""
        folder = cwd_of(session or None, cwd or None)
        try:
            project, found = brain.session_precedents(folder) if folder else (None, [])
        except (VaultError, OSError):
            return ""
        if not project:
            return ""
        if session:
            hub.touch(session, found, "início")
        pending = render_pending(suggestions.list(project))
        extra = ([f"Sugestões de precedente esperando o Pedro em [[{project}]] (ele aceita ou recusa na MÊTIS; brain_sugestoes mostra todas):", *pending] if pending else [])
        return brain.render_context(project, found, extra)

    # --- Brain vivo (v0.8): significado, conflitos, sugestões, mini-mapa ------------------

    @app.get("/brain/semantica", dependencies=[Depends(require_token)])
    def brain_semantic() -> dict:
        return {"model": embedder.status(), "index": brain.vector_status(), "suggestions": suggestions.status()}

    @app.post("/brain/semantica/baixar", dependencies=[Depends(require_token)], status_code=202)
    def brain_semantic_download() -> dict:
        embedder.download()
        return embedder.status()

    @app.post("/brain/embed", dependencies=[Depends(require_token)])
    def brain_embed(body: EmbedBody) -> dict:
        """Vetores para o MCP de fora (que não carrega o modelo)."""
        vectors = embedder.encode(body.texts, 20.0)
        if vectors is None:
            raise HTTPException(status_code=503, detail=embedder.status()["error"] or "o modelo de significado não está pronto")
        return {"vectors": [[round(float(x), 5) for x in v] for v in vectors]}

    @app.get("/brain/conflitos", dependencies=[Depends(require_token)])
    def brain_conflicts(q: str = Query(min_length=3), project: str = "", cwd: str = "") -> dict:
        if not project and cwd:
            note = vault.project_for_dir(cwd)
            project = note.name if note else ""
        return brain.conflicts(q, project or None)

    @app.get("/brain/sugestoes", dependencies=[Depends(require_token)])
    def brain_suggestions(project: str = "", status: str = "pendente", nota: str = "") -> list[dict]:
        if nota:
            return suggestions.for_note(nota)
        return suggestions.list(project or None, status or None)

    @app.post("/brain/sugestoes/varrer", dependencies=[Depends(require_token)])
    async def brain_suggestions_scan() -> dict:
        return await asyncio.to_thread(suggestions.scan)

    @app.post("/brain/sugestoes/{suggestion_id}/aceitar", dependencies=[Depends(require_token)])
    def brain_suggestion_accept(suggestion_id: int, body: AcceptBody) -> dict:
        try:
            item = suggestions.accept(suggestion_id, body.titulo or None, body.resumo or None)
        except SuggestionError as exc:
            raise fail(exc) from exc
        brain_changed(item["target_project"])
        return item

    @app.post("/brain/sugestoes/{suggestion_id}/recusar", dependencies=[Depends(require_token)])
    def brain_suggestion_reject(suggestion_id: int) -> dict:
        try:
            return suggestions.reject(suggestion_id)
        except SuggestionError as exc:
            raise fail(exc) from exc

    @app.get("/brain/sessao/{session_id}", dependencies=[Depends(require_token)])
    def brain_session_map(session_id: str) -> dict:
        """Mini-mapa: o projeto da sessão e as notas do Brain que ela viu (início, leituras, buscas)."""
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        note = vault.project_for_dir(session.cwd) if session.cwd else None
        nodes = list(hub.session_notes.get(session_id, {}).values())
        if note is not None:
            # Registros deste projeto feitos depois do início da sessão: o que ela deixou no Brain.
            for item in brain.records_since(note.name, session.created_at):
                if item["path"] not in {n["path"] for n in nodes}:
                    nodes.append({**item, "via": ["registro"]})
        return {"project": note.name if note else None, "nodes": nodes[:40], "edges": brain.edges_among([n["path"] for n in nodes[:40]])}

    @app.get("/sessions/{session_id}/contexto", dependencies=[Depends(require_token)])
    def session_context_window(session_id: str) -> dict:
        """Janela de contexto do Claude: o que ocupa o contexto da sessão, lido do transcript."""
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        line = session.statusline or {}
        transcript = line.get("transcript")
        if not transcript:
            return {"available": False, "reason": "o Claude ainda não mandou a statusline desta sessão"}
        return context_breakdown(transcript, line.get("context") or {})

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

    # --- quadros (v0.9.1): .canvas do Obsidian na pasta do projeto ------------------------

    def board_fail(exc: Exception) -> HTTPException:
        status = 409 if isinstance(exc, BoardConflict) else 404 if "não encontrad" in str(exc) else 400
        return HTTPException(status_code=status, detail=str(exc))

    @app.get("/quadros", dependencies=[Depends(require_token)])
    def list_boards() -> list[dict]:
        return boards.list()

    @app.post("/quadros", dependencies=[Depends(require_token)], status_code=201)
    def create_board(body: NewBoard) -> dict:
        try:
            return boards.create(body.projeto, body.nome)
        except BoardError as exc:
            raise board_fail(exc) from exc

    @app.get("/quadros/abrir", dependencies=[Depends(require_token)])
    def open_board(path: str = Query(min_length=1)) -> dict:
        try:
            return boards.read(path)
        except BoardError as exc:
            raise board_fail(exc) from exc

    @app.put("/quadros/salvar", dependencies=[Depends(require_token)])
    def save_board(body: SaveBoard) -> dict:
        try:
            return boards.save(body.path, body.canvas, body.base)
        except BoardError as exc:
            raise board_fail(exc) from exc

    @app.post("/quadros/ligar", dependencies=[Depends(require_token)])
    def link_note(body: LinkNote) -> dict:
        """Nota do Brain ligada a uma sessão no quadro: a sessão recebe o pedido de ler (vira contexto)."""
        session = manager.get(body.sessao)
        if session is None:
            raise HTTPException(status_code=404, detail="essa sessão não está aberta")
        if session.kind not in ("claude", "codex"):
            # No shell, o pedido viraria um comando digitado.
            raise HTTPException(status_code=400, detail="a nota vira contexto só numa sessão do Claude ou do Codex")
        try:
            note = brain.note(path=body.nota)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        full = settings.brain / note["path"]
        text = (
            f"Nota do Brain ligada a esta sessão no quadro da MÊTIS: «{note['title']}» ({full}). "
            f"Leia (brain_ler \"{note['title']}\" no MCP metis, ou o arquivo) e leve em conta no que está fazendo; responda só com o que muda para você."
        )
        if not manager.send_text(body.sessao, text):
            raise HTTPException(status_code=404, detail="essa sessão não está aberta")
        hub.touch(body.sessao, [note], "quadro")
        return {"mensagem": text}

    @app.get("/sessions/{session_id}/resumo", dependencies=[Depends(require_token)])
    def session_glance(session_id: str) -> dict:
        """O cartão da sessão no quadro: estado, contexto, as últimas mensagens e o fim do terminal."""
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        line = session.statusline or {}
        transcript = line.get("transcript")
        recent = last_messages(transcript, 2) if transcript else []
        return {
            "id": session.id,
            "title": session.title,
            "kind": session.kind,
            "status": session.status,
            "cwd": session.cwd,
            "agent": session.agent,
            "context_pct": (line.get("context") or {}).get("used_pct"),
            "ultimas": recent,
            "linhas": [] if recent else manager.tail_lines(session_id, 8),
        }

    @app.post("/sessions/{session_id}/mensagem", dependencies=[Depends(require_token)], status_code=204)
    def session_message(session_id: str, body: SessionMessage) -> None:
        if not manager.send_text(session_id, body.texto):
            raise HTTPException(status_code=404, detail="essa sessão não está aberta")

    # --- automações (v0.9.0) ---------------------------------------------------------

    def automation_fail(exc: Exception) -> HTTPException:
        message = str(exc)
        return HTTPException(status_code=404 if "não encontrada" in message else 400, detail=message)

    def automation_summary(automation_id: str) -> dict:
        draft = automations.draft(automation_id)
        published = automations.published(automation_id)
        st = engine.state(automation_id)
        versions = automations.versions(automation_id)
        return {
            "id": automation_id,
            "nome": draft["nome"],
            "descricao": draft["descricao"],
            "gatilho": (published or draft)["gatilho"],
            "ativa": bool(st["ativa"]),
            "publicada": versions[0]["number"] if versions else None,
            "mudou": published is not None and published != draft,
            "conectores": connectors_used(draft),
            "ultima": engine.last_run(automation_id),
            "alterado": automations.mtime(automation_id),
        }

    @app.get("/automacoes", dependencies=[Depends(require_token)])
    def list_automations() -> list[dict]:
        items = []
        for automation_id in automations.ids():
            try:
                items.append(automation_summary(automation_id))
            except AutomationError as exc:
                items.append({"id": automation_id, "nome": automation_id, "erro": str(exc), "ativa": False, "conectores": []})
        return items

    @app.post("/automacoes", dependencies=[Depends(require_token)], status_code=201)
    def create_automation(body: NewAutomation) -> dict:
        try:
            automation_id = automations.create(body.nome, body.desenho or blank(body.nome))
        except AutomationError as exc:
            raise automation_fail(exc) from exc
        return automation_summary(automation_id)

    @app.get("/automacoes/catalogo", dependencies=[Depends(require_token)])
    async def automation_catalog() -> dict:
        """O que dá para pôr num passo: ferramentas da central (com quem fala com outras pessoas), agentes e o Brain."""
        ctx = Context(session="catalogo", who="catálogo", cwd=None, allowed=None)
        tools = await asyncio.to_thread(hub.tools_for, ctx)
        names = {a.id: a.name for a in connectors.list()}
        return {
            "ferramentas": [
                {"nome": t.name, "descricao": t.description, "conta": t.account, "conta_nome": names.get(t.account, "MÊTIS"), "pessoas": t.write, "esquema": t.schema}
                for t in tools
            ],
            "agentes": [{"id": a["id"], "nome": a["name"], "cli": a["cli"], "cor": a["color"], "descricao": a["description"]} for a in agents.list()],
        }

    @app.get("/automacoes/{automation_id}", dependencies=[Depends(require_token)])
    def get_automation(automation_id: str) -> dict:
        try:
            return {
                **automation_summary(automation_id),
                "rascunho": automations.draft(automation_id),
                "publicada_desenho": automations.published(automation_id),
                "versoes": automations.versions(automation_id),
                "diferenca": automations.diff(automation_id),
                "arquivo": str(automations.path(automation_id)),
            }
        except AutomationError as exc:
            raise automation_fail(exc) from exc

    @app.put("/automacoes/{automation_id}", dependencies=[Depends(require_token)])
    def save_automation(automation_id: str, body: AutomationBody) -> dict:
        try:
            automations.save(automation_id, body.desenho)
            return automation_summary(automation_id)
        except AutomationError as exc:
            raise automation_fail(exc) from exc

    @app.delete("/automacoes/{automation_id}", dependencies=[Depends(require_token)], status_code=204)
    def archive_automation(automation_id: str) -> None:
        try:
            engine.set_active(automation_id, False)
            automations.archive(automation_id)
        except AutomationError as exc:
            raise automation_fail(exc) from exc

    @app.post("/automacoes/{automation_id}/publicar", dependencies=[Depends(require_token)])
    def publish_automation(automation_id: str, body: PublishBody) -> dict:
        try:
            content = automations.version_content(automation_id, body.versao) if body.versao else None
            number = automations.publish(automation_id, content)
        except AutomationError as exc:
            raise automation_fail(exc) from exc
        manager.events.publish({"type": "automation.published", "automation": automation_id, "versao": number})
        return automation_summary(automation_id)

    @app.put("/automacoes/{automation_id}/ativa", dependencies=[Depends(require_token)])
    def toggle_automation(automation_id: str, body: ActiveBody) -> dict:
        try:
            engine.set_active(automation_id, body.ativa)
        except AutomationError as exc:
            raise automation_fail(exc) from exc
        return automation_summary(automation_id)

    @app.post("/automacoes/{automation_id}/testar", dependencies=[Depends(require_token)], status_code=202)
    async def test_automation(automation_id: str, body: TestBody) -> dict:
        """Roda o RASCUNHO com ensaio (inteiro, a partir de um passo, ou um passo só)."""
        try:
            run_id = await engine.start(automation_id, "teste", "teste", desde=body.desde or None, base_run=body.execucao or None, only=body.passo or None)
        except AutomationError as exc:
            raise automation_fail(exc) from exc
        return {"execucao": run_id}

    @app.post("/automacoes/{automation_id}/rodar", dependencies=[Depends(require_token)], status_code=202)
    async def run_automation(automation_id: str) -> dict:
        """Roda a PUBLICADA agora, de verdade (`metis rodar`)."""
        try:
            run_id = await engine.start(automation_id, "producao", "manual")
        except AutomationError as exc:
            raise automation_fail(exc) from exc
        return {"execucao": run_id}

    @app.get("/automacoes/{automation_id}/execucoes", dependencies=[Depends(require_token)])
    def automation_runs(automation_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
        return engine.list_runs(automation_id, limit)

    @app.get("/execucoes/{run_id}", dependencies=[Depends(require_token)])
    def get_run(run_id: int) -> dict:
        try:
            return engine.run(run_id)
        except AutomationError as exc:
            raise automation_fail(exc) from exc

    @app.post("/execucoes/{run_id}/reexecutar", dependencies=[Depends(require_token)], status_code=202)
    async def rerun_from(run_id: int, body: RerunBody) -> dict:
        """Reexecutar daqui: as entradas guardadas valem, e só o passo e o que vem depois rodam de novo."""
        try:
            base = engine.run(run_id)
            new_id = await engine.start(base["automation"], base["mode"], "reexecução", desde=body.desde, base_run=run_id)
        except AutomationError as exc:
            raise automation_fail(exc) from exc
        return {"execucao": new_id}

    @app.post("/execucoes/{run_id}/parar", dependencies=[Depends(require_token)], status_code=204)
    async def stop_run(run_id: int) -> None:
        if not await engine.cancel(run_id):
            raise HTTPException(status_code=404, detail="essa execução não está rodando")

    @app.post("/execucoes/{run_id}/conserto", dependencies=[Depends(require_token)], status_code=201)
    def ask_fix(run_id: int) -> dict:
        """Pedir conserto: um Claude com o rascunho e o log; a correção vai só para o rascunho."""
        try:
            run = engine.run(run_id)
            path = automations.path(run["automation"])
        except AutomationError as exc:
            raise automation_fail(exc) from exc
        failed = [f"- {sid}: {st.get('erro')}" for sid, st in run["steps"].items() if st.get("status") == "erro"]
        prompt = (
            f"A automação da MÊTIS \"{run['flow']['nome']}\" falhou na execução #{run_id} ({run['mode']}).\n"
            f"Erro: {run.get('error')}\n" + "\n".join(failed) + "\n\n"
            f"O rascunho dela é o arquivo {path}. Leia o arquivo e o erro, explique em duas linhas a causa e corrija "
            "SÓ o rascunho (nunca a pasta publicadas/). Mantenha o formato YAML e os ids dos passos. "
            "Depois diga ao Pedro para conferir na tela de Automações, testar e publicar."
        )
        try:
            session = manager.create("claude", str(automations.dir), title=f"Conserto · {run['flow']['nome']}", tag="automacao", prompt=prompt)
        except (UnknownKind, ExecutableNotFound, OSError) as exc:
            raise fail(exc) from exc
        return {"session": session.id, "title": session.title}

    # --- rotinas e Hoje -------------------------------------------------------------

    def routine_view(routine: Routine, now: datetime) -> dict:
        nxt = next_slot(routine, now)
        return {**routine.to_dict(), "next": nxt.isoformat() if nxt else None}

    def routines_changed() -> None:
        now = datetime.now().astimezone()
        manager.events.publish({"type": "routines", "routines": [routine_view(r, now) for r in routines.list()]})

    @app.get("/rotinas", dependencies=[Depends(require_token)])
    def list_routines() -> dict:
        now = datetime.now().astimezone()
        return {"routines": [routine_view(r, now) for r in routines.list()], "runs": routines.runs(60)}

    @app.post("/rotinas", dependencies=[Depends(require_token)], status_code=201)
    def create_routine(body: RoutineBody) -> dict:
        try:
            routine = routines.save(body.model_dump())
        except RoutineError as exc:
            raise fail(exc) from exc
        routines_changed()
        return routine_view(routine, datetime.now().astimezone())

    @app.put("/rotinas/{routine_id}", dependencies=[Depends(require_token)])
    def update_routine(routine_id: str, body: RoutineBody) -> dict:
        try:
            routines.get(routine_id)
            routine = routines.save(body.model_dump(), routine_id)
        except RoutineError as exc:
            raise fail(exc, 404) from exc
        routines_changed()
        return routine_view(routine, datetime.now().astimezone())

    @app.delete("/rotinas/{routine_id}", dependencies=[Depends(require_token)], status_code=204)
    def delete_routine(routine_id: str) -> None:
        try:
            routines.delete(routine_id)
        except RoutineError as exc:
            raise fail(exc, 404) from exc
        routines_changed()

    @app.post("/rotinas/{routine_id}/rodar", dependencies=[Depends(require_token)])
    async def run_routine_now(routine_id: str) -> dict:
        try:
            routine = routines.get(routine_id)
        except RoutineError as exc:
            raise fail(exc, 404) from exc
        return await run_routine(routine, None, "manual")

    # --- captura rápida, concierge e estudo -------------------------------------------

    def reminder_account() -> str:
        return next((a.id for a in connectors.list() if a.reminders), "")

    async def to_concierge(text: str) -> str:
        """Manda ao Hermes: no terminal dele, se já estiver aberto; senão abre um com o pedido."""
        live = next((s for s in manager.sessions.values() if s.agent == "hermes" and s.status != "exited"), None)
        if live is not None:
            live.pty.write(text.replace("\n", " ").encode("utf-8"))
            await asyncio.sleep(0.15)
            live.pty.write(b"\r")
            return f"Mandei para o {live.title}, no terminal dele."
        try:
            hermes = agents.get("hermes")
        except AgentError:
            hermes = None
        session = manager.create("claude", None, title=None if hermes else "Concierge", tag="concierge", agent=hermes, prompt=text)
        return f"{session.title} abriu na MÊTIS com o seu pedido."

    @app.post("/captura", dependencies=[Depends(require_token)])
    async def capture(body: CaptureBody) -> dict:
        names = [p.name for p in vault.projects()] if vault.available else []
        try:
            item = interpret(body.texto, names)
        except ValueError as exc:
            raise fail(exc) from exc
        today_str = datetime.now().astimezone().date().isoformat()
        try:
            if item.kind == "lembrete" and reminder_account():
                message = await asyncio.to_thread(hub.remind, reminder_account(), item.text, item.when.isoformat())
            elif item.kind == "tarefa" and item.project:
                task = await asyncio.to_thread(kanban.add, item.project, item.text)
                manager.events.publish({"type": "brain.changed", "project": item.project})
                message = f"Tarefa {task['id']} nas Próximas ações de {item.project}."
            elif item.kind in ("tarefa", "nota"):
                line = f"- [ ] {item.text}" if item.kind == "tarefa" else f"- {item.text}"
                await asyncio.to_thread(vault.append_daily, today_str, "📥 Capturas do dia", line, DAILY_BEFORE)
                message = f"{'Tarefa' if item.kind == 'tarefa' else 'Nota'} nas Capturas do dia ({today_str})."
            else:
                # Lembrete sem Slack conectado também vai para o Hermes, que avisa o que falta.
                message = await to_concierge(body.texto)
                item.kind = "concierge"
        except (ToolError, ConnectorError, SlackError, VaultError, OSError) as exc:
            raise fail(exc) from exc
        return {"acao": item.kind, "mensagem": message}

    @app.get("/estudo", dependencies=[Depends(require_token)])
    def study_summary() -> dict:
        return study.summary()

    @app.post("/estudo/blocos", dependencies=[Depends(require_token)], status_code=201)
    def study_block(body: StudyBlock) -> dict:
        block = study.add(body.minutos, body.assunto)
        manager.events.publish({"type": "study", "summary": study.summary()})
        return block

    @app.post("/agents/rascunho", dependencies=[Depends(require_token)])
    def agent_draft(body: DraftRequest) -> dict:
        from .sessions import clean_env

        env = {**clean_env(), **manager.accounts.env("claude", manager.accounts.active("claude"))}
        try:
            return draft_agent(body.descricao, [a["name"] for a in agents.list()], env)
        except DraftError as exc:
            raise fail(exc) from exc

    @app.get("/hoje", dependencies=[Depends(require_token)])
    def today() -> dict:
        """O dia num lugar só: rotinas de hoje, tarefas em andamento, aprovações e lembretes."""
        now = datetime.now().astimezone()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        runs_today = routines.runs(200, start.timestamp())
        slots = []
        for routine in routines.list():
            slot = slot_on(routine, now) if routine.active else None
            if slot is None:
                continue
            run = next((r for r in runs_today if r["routine"] == routine.id and abs(r["slot"] - slot.timestamp()) < 1), None)
            slots.append({"routine": routine_view(routine, now), "slot": slot.isoformat(), "run": run})
        manual = [r for r in runs_today if not r["slot"]]
        doing = []
        for project in kanban.projects():
            if not (project["tasks"]["em-andamento"] or project["tasks"]["em-teste"]):
                continue
            for task in kanban.tasks(project["name"]):
                if task["state"] in ("em-andamento", "em-teste"):
                    doing.append({"project": project["name"], **task})
        return {
            "now": now.isoformat(),
            "weekday": DAYS[now.weekday()],
            "slots": sorted(slots, key=lambda s: s["slot"]),
            "manual": manual,
            "doing": doing,
            "approvals": [p.to_dict() for p in hub.pending.values()],
            "study": study.summary(now),
        }

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
        payload = await _json(request)
        manager.record_hook(session, name, payload if isinstance(payload, dict) else None)
        if name == "Stop":
            engine.on_stop(session)  # passo de automação que terminou o turno sem devolver a saída

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
            with suppress(RuntimeError, WebSocketDisconnect):  # o cliente já fechou: nada a fechar
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
                    "version": __version__,
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
