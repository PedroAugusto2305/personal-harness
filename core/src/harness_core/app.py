"""API local do núcleo: sessões, terminais por WebSocket, eventos, contas, cota, voz e hooks."""

from __future__ import annotations

import asyncio
import hashlib
import os
import json
from datetime import datetime
import secrets
import shutil
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
from .accounts import PROVIDERS, AccountStore, UnknownAccount, slugify
from .activity import ActivityLog
from .agent_draft import DraftError, draft_agent
from .agents import Agent, AgentError, AgentStore, allowed_connectors
from .capture import interpret
from .study import DAILY_BEFORE, StudyLog
from .study_map import SESSION_TYPES, TUTOR, StudyError, StudyMap
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
from .system import Awake, list_skills, mac_notify, notifier, process_table, set_notifier, tree_usage, wants_awake
from .prefs import PrefsError
from . import barra, ghostty, github, system, themes, updates
from . import app_themes, barra_lateral
from .commands import CommandError, CommandStore, Keymap, UnknownCommand
from .transcript import context_breakdown, last_messages
from .kanban_auto import AutoError, AutoItem, AutoQueue, auto_prompt
from .kanban import Kanban
from .clickup_rest import ClickupBoard, ClickupError
from .vault import Vault, VaultError, link_target, split_frontmatter, write_atomic
from .sprites import SpriteStudio, model_image
from .attachments import MAX_ATTACHMENT_BYTES, save_attachment
from .config import DEFAULT_PORT as metis_profiles_port, Settings, load_settings
from .connectors import CATALOG, ConnectorError, ConnectorStore, tool_mode
from .keychain import Keychain
from .keychain import Vault as SecretVault
from .mcp_hub import Context, Hub, ToolError
from . import chrome_cookies
from . import mcp_configs, mcp_registry  # v0.9.8 parte 3: conectores
from . import automation_ai, automation_templates, n8n_import  # v0.9.8 parte 4: automação por frase, n8n e estratégias
from . import graphify_tools, skills_manager  # v0.9.8 parte 5: grafo do código e Skills
from . import backup as metis_backup, profiles as metis_profiles  # v0.9.8 parte 5: perfis e backup
from .keychain import service_for as keychain_service
from .browser_bridge import BrowserAnswer, BrowserBridge, BrowserHistory, BrowserProfiles, HistoryVisit, ImportBody, ProfileBody, ProfileError
from .slack import MANIFEST, SlackError
from .model_usage import ModelUsage
from .projects import ProjectError, ProjectStore, clone_repo, create_repo, default_parent, find_repos
from .relay import install_cli_shim, install_relay
from .routines import DAYS, Routine, RoutineError, RoutineStore, decide, next_slot, slot_on
from .routines import PREFIX as ROUTINE_PREFIX, RoutineFlows
from .sessions import CommandError as LaunchError
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
#: Prévia do agente já lida pelo /hooks/event (numa thread), guardada no payload do Stop.
PREVIEW_KEY = "_previa_metis"


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
    #: v0.9.8: modelo e esforço só desta sessão e o pedido que já entra no agente.
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:/-]{1,80}$")
    effort: str | None = Field(default=None, pattern="^(low|medium|high|xhigh)$")
    prompt: str | None = Field(default=None, max_length=8000)


class DraftAgent(BaseModel):
    """Agente ainda não salvo, para "testar antes de salvar"."""

    name: str = Field(min_length=1, max_length=60)
    cli: str = Field(default="claude", pattern="^(claude|codex|outra)$")
    model: str = ""
    folder: str = ""
    prompt: str = ""
    args: str = Field(default="", max_length=2000)
    env: str = Field(default="", max_length=8000)
    command: str = Field(default="", max_length=2000)


class NewAccount(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class NewProject(BaseModel):
    path: str = Field(min_length=1)
    name: str | None = None


class CloneProject(BaseModel):
    url: str = Field(min_length=3, max_length=500)
    pasta: str = Field(default="", max_length=1000)


class CreateProject(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    pasta: str = Field(default="", max_length=1000)


class NewWorktree(BaseModel):
    # v0.9.8: o nome pode ficar vazio no modo "branch" (a pasta vem do nome do branch).
    name: str = Field(default="", max_length=80)
    base: str | None = None
    copy_env: bool = True
    modo: str = "nova"


class GitFiles(BaseModel):
    path: str
    files: list[str] = Field(default_factory=list)


class GitCommit(BaseModel):
    path: str
    message: str = Field(default="", max_length=20000)
    amend: bool = False


class GitPath(BaseModel):
    path: str


class GitPush(BaseModel):
    path: str
    force: bool = False


class GitApply(BaseModel):
    path: str
    patch: str = Field(min_length=1, max_length=5_000_000)
    cached: bool = True
    reverse: bool = False


class GitOperation(BaseModel):
    path: str
    acao: str = Field(pattern="^(abortar|continuar)$")


class GitConflict(BaseModel):
    path: str
    file: str
    escolhas: list[str] | None = None
    lado: str | None = Field(default=None, pattern="^(nosso|deles)$")


class PrCreate(BaseModel):
    path: str
    titulo: str = Field(min_length=1, max_length=256)
    corpo: str = Field(default="", max_length=60000)
    base: str = Field(min_length=1, max_length=200)
    rascunho: bool = False


class PrNumber(BaseModel):
    path: str
    numero: int = Field(ge=1)
    metodo: str = Field(default="rebase", pattern="^(rebase|squash|merge)$")


class GitSigning(BaseModel):
    assinar: bool


class OpenIn(BaseModel):
    editor: str = Field(min_length=1, max_length=40)
    path: str


class AgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""
    pain: str = ""
    cli: str = Field(default="claude", pattern="^(claude|codex|outra)$")
    model: str = ""
    account: str = ""
    folder: str = ""
    color: str = "#82a0ff"
    connectors: str = ""
    prompt: str = ""
    #: v0.9.8: argumentos extras (como no terminal), variáveis (CHAVE=valor por linha) e a
    #: linha de comando de uma CLI "outra".
    args: str = Field(default="", max_length=2000)
    env: str = Field(default="", max_length=8000)
    command: str = Field(default="", max_length=2000)


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
    #: v0.9.8: rótulos e subtarefas já na criação (opcionais).
    rotulos: list[str] = Field(default_factory=list, max_length=20)
    subtarefas: list[str] = Field(default_factory=list, max_length=50)


class TaskLabels(BaseModel):
    rotulos: list[str] = Field(default_factory=list, max_length=20)


class NewSubtask(BaseModel):
    texto: str = Field(min_length=1, max_length=1000)


class MarkSubtask(BaseModel):
    feita: bool = True


class ClickupToken(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ClickupLink(BaseModel):
    conta: str = Field(min_length=1, max_length=80)
    lista: str = Field(min_length=1, max_length=40)
    nome: str = Field(default="", max_length=200)


class ClickupStatus(BaseModel):
    status: str = Field(min_length=1, max_length=100)


class TaskMove(BaseModel):
    state: str = Field(pattern="^(pendente|em-andamento|em-teste|concluida)$")


class AutoEnqueue(BaseModel):
    """v0.9.9: tarefa na coluna Auto do kanban."""

    projeto: str = Field(min_length=1, max_length=200)
    tarefa: str = Field(min_length=1, max_length=80)
    cli: str = Field(default="claude", pattern="^(claude|codex)$")
    agente: str = Field(default="", max_length=80)
    modelo: str = Field(default="", pattern=r"^[A-Za-z0-9._:/-]{0,80}$")
    esforco: str = Field(default="", pattern="^(|low|medium|high|xhigh)$")
    permissao: str = Field(default="auto", pattern="^(padrao|manual|auto|yolo)$")
    onde: str = Field(default="worktree", pattern="^(worktree|pasta)$")


class AutoLimit(BaseModel):
    limite: int = Field(ge=1, le=4)


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
    #: v0.9.9: {ferramenta: "livre" | "aprovacao" | "desligada" | "padrao"}
    tool_modes: dict[str, str] | None = Field(default=None, max_length=400)


# v0.9.8 parte 3: corpos das rotas novas de conectores
class GithubConnect(BaseModel):
    nome: str = Field(default="", max_length=40)
    #: Vazio ou null: usa o login do gh (a tela da v0.9.8 mandava null com o campo vazio).
    token: str | None = Field(default="", max_length=400)

class GoogleClient(BaseModel):
    client_id: str = Field(max_length=300)
    client_secret: str = Field(max_length=300)

class GoogleStart(BaseModel):
    nome: str = Field(default="", max_length=40)

class McpConnect(BaseModel):
    nome: str = Field(default="", max_length=40)
    transporte: str = "http"
    url: str = Field(default="", max_length=2000)
    auth: str = "nenhuma"
    token: str = Field(default="", max_length=4000)
    comando: str = Field(default="", max_length=2000)
    env: str = Field(default="", max_length=20000)
    pasta: str = Field(default="", max_length=1000)

class McpCopy(BaseModel):
    de: str
    para: str
    nome: str = Field(max_length=200)


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


# v0.9.8: Estudo completo (o mapa de conceitos, o plano e as sessões com o Sócrates).
class NewConcept(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    resumo: str = Field(default="", max_length=4000)
    relacionados: list[str] = Field(default_factory=list, max_length=40)
    semana: int | None = Field(default=None, ge=0, le=200)


class ConceptPatch(BaseModel):
    titulo: str = Field(min_length=1, max_length=120)
    dominio: int | None = Field(default=None, ge=0, le=4)
    semana: int | None = Field(default=None, ge=0, le=200)


class StudySessionBody(BaseModel):
    tipo: str
    conceito: str | None = Field(default=None, max_length=120)


class DraftRequest(BaseModel):
    descricao: str = Field(min_length=1, max_length=2000)


class Decision(BaseModel):
    aprovar: bool


class FsWrite(BaseModel):
    root: str
    path: str = Field(min_length=1)
    text: str
    hash: str = Field(min_length=64, max_length=64)


class NoteText(BaseModel):
    path: str = Field(min_length=4)
    texto: str
    hash: str = Field(min_length=64, max_length=64)


class TitlesBody(BaseModel):
    titles: list[str] = Field(default_factory=list, max_length=2000)


class MacNotice(BaseModel):
    titulo: str = Field(min_length=1, max_length=120)
    texto: str = Field(default="", max_length=240)


class AppNotifier(BaseModel):
    exe: str = Field(default="", max_length=1024)


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


# v0.9.8 parte 4: automação por frase, código escrito pelo Claude, n8n e estratégias.
class ProposalBody(BaseModel):
    descricao: str = Field(default="", max_length=4000)
    atual: dict | None = None


class CodeWriteBody(BaseModel):
    descricao: str = Field(default="", max_length=4000)
    linguagem: str = "python"
    entrada_exemplo: object | None = None


class N8nImportBody(BaseModel):
    fluxo: object | None = None
    conta: str | None = None
    workflow_id: str | None = None


class StrategyBody(BaseModel):
    parametros: dict = Field(default_factory=dict)


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


class ThemeText(BaseModel):
    texto: str = Field(max_length=ghostty.MAX_BYTES)
    nome: str | None = Field(default=None, max_length=120)
    formato: str | None = Field(default=None, pattern="^(ghostty|kitty|warp)$")


class SkillInstall(BaseModel):
    destino: str = Field(pattern="^(claude|codex|ambos)$")


# --- v0.9.8 parte 5: checks, revisão de PR, grafo do código e Skills ---------------------------

SKILL_WHERE = "^(claude|codex|projeto)$"


class RootBody(BaseModel):
    root: str = Field(min_length=1)


class ReviewBody(BaseModel):
    root: str = Field(min_length=1)
    cli: str = Field(default="claude", pattern="^(claude|codex)$")
    numero: int | None = Field(default=None, ge=1)


class SkillAdd(BaseModel):
    origem: str = Field(min_length=1, max_length=2000)
    destino: str = Field(pattern=SKILL_WHERE)
    root: str | None = None
    substituir: bool = False


class SkillWhere(BaseModel):
    destino: str = Field(pattern=SKILL_WHERE)
    root: str | None = None


class SkillCopy(BaseModel):
    de: str = Field(pattern=SKILL_WHERE)
    para: str = Field(pattern=SKILL_WHERE)
    root: str | None = None


class GhosttyText(BaseModel):
    texto: str = Field(max_length=ghostty.MAX_BYTES)
    nome: str | None = Field(default=None, max_length=120)


class AcceptBody(BaseModel):
    titulo: str = Field(default="", max_length=200)
    resumo: str = Field(default="", max_length=1200)


class MetisProfileBody(BaseModel):
    """Perfil novo da MÊTIS (v0.9.8): pasta de dados própria; `copiar` leva a configuração atual."""

    nome: str = Field(min_length=1, max_length=40)
    vault: str | None = Field(default=None, max_length=1000)
    copiar: bool = False


class MetisProfilePatch(BaseModel):
    nome: str | None = Field(default=None, max_length=40)
    #: Texto vazio tira o Brain próprio (volta ao padrão).
    vault: str | None = Field(default=None, max_length=1000)


class BackupExportBody(BaseModel):
    destino: str | None = Field(default=None, max_length=1000)


class BackupFileBody(BaseModel):
    arquivo: str = Field(min_length=1, max_length=1000)


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
    commands = CommandStore(settings.home)
    keymap = Keymap(settings.home)

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
    connectors = ConnectorStore(settings.home, keychain or Keychain(keychain_service(settings.profile)), http)
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
        browser=BrowserBridge(manager.events),
    )
    browser_history = BrowserHistory(settings.home / "navegador.db")
    browser_profiles = BrowserProfiles(settings.home, publish=manager.events.publish)
    manager.mcp_token = hub.register
    manager.mcp_forget = hub.forget
    routines = RoutineStore(settings.home)
    study = StudyLog(settings.home, vault)
    study_map = StudyMap(vault, project=lambda: manager.prefs.get()["estudo_projeto"])
    hub.study_map = study_map  # ferramentas estudo_* da central (v0.9.8)

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
        target = f"sessao:{session.id}"
        if kind == "espera" and notices["espera"]:
            mac_notify(f"{session.title} espera você", message or Path(session.cwd).name, notices["som"], target, session.id)
        elif kind == "terminou" and notices["terminou"]:
            mac_notify(f"{session.title} terminou", Path(session.cwd).name, notices["som"], target, session.id)

    manager.on_hook = on_hook
    automations = AutomationStore(settings.home)
    engine = Engine(settings.home, automations, hub, manager, brain, kanban, vault, agents, notify=dm_pedro, publish=lambda event: manager.events.publish(event))
    # v0.9.8: as rotinas viram automações (uma vez) e os eventos da MÊTIS disparam automações.
    routine_flows = RoutineFlows(automations, engine, routines)
    try:
        routine_flows.migrate()
    except Exception:  # noqa: BLE001 - a migração nunca impede o núcleo de subir
        pass
    kanban.on_move = lambda info: engine.fire_event("tarefa.moveu", info)
    brain.on_note = lambda info: engine.fire_event("brain.nota", info)
    manager.events.listen(engine.on_bus_event)

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
        except (AgentError, LaunchError, UnknownKind, ExecutableNotFound, OSError) as exc:
            # LaunchError: linha de comando que não roda (CLI "outra" fora do PATH, argumentos ruins).
            # Sem ela aqui, o erro subia pelo agendador e a task dele morria.
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
                if routine.migrated:  # virou automação: quem roda é o motor (nada de execução dupla)
                    continue
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
            working = sum(1 for s in manager.sessions.values() if s.status == "working" and not s.hibernando)
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

    async def hibernate_watch() -> None:
        """A cada 30 s: agente parado esperando há mais que o combinado em Ajustes é pausado
        (SIGSTOP); qualquer tecla, o Acordar ou fechar a sessão o acorda (v0.9.8)."""
        while True:
            await asyncio.sleep(30)
            try:
                manager.hibernate_idle()
            except Exception as exc:  # noqa: BLE001 - hibernar nunca derruba o núcleo
                manager.events.publish({"type": "session.error", "error": f"hibernar: {exc}"})

    update_state: dict = {"info": None, "avisada": None}

    async def update_watch() -> None:
        """A cada 6 h (e logo ao subir), a MÊTIS instalada procura uma versão nova no repositório
        e avisa uma vez por versão. Sem rede, só fica para a próxima rodada."""
        await asyncio.sleep(20)
        while True:
            try:
                info = await asyncio.to_thread(updates.check, settings.home, True)
                update_state["info"] = info
                if info["nova"] and info["nova"] != update_state["avisada"]:
                    update_state["avisada"] = info["nova"]
                    manager.events.publish({"type": "atualizacao", "nova": info["nova"], "versao": info["versao"]})
            except Exception:  # noqa: BLE001 - a busca de versão nunca derruba o núcleo
                pass
            await asyncio.sleep(6 * 3600)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        install_relay(settings.relay_path)
        install_cli_shim(settings.relay_path.parent, settings.home, settings.profile)
        engine.bind(asyncio.get_running_loop())  # eventos de outras threads disparam automações neste loop
        app.state.auto.bind(asyncio.get_running_loop())  # v0.9.9: a fila Auto do kanban roda neste loop
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
            pollers.append(asyncio.create_task(update_watch()))
            pollers.append(asyncio.create_task(hibernate_watch()))
        yield
        for poller in pollers:
            poller.cancel()
            with suppress(asyncio.CancelledError):
                await poller
        await engine.shutdown()
        await manager.close_all()
        connectors.close()  # os MCPs por stdio não ficam órfãos
        awake.stop()

    app = FastAPI(title="Harness core", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.manager = manager
    app.state.brain = brain
    app.state.suggestions = suggestions
    app.state.hub = hub
    app.state.study_map = study_map
    app.state.embedder = embedder
    app.state.engine = engine
    app.state.cli_homes = None  # None = ~/.claude e ~/.codex; os testes apontam para pastas temporárias
    app.state.model_usage = ModelUsage(manager.accounts.list, projects.list, settings.worktrees, lambda: app.state.cli_homes)
    app.state.skills_downloads = None  # v0.9.8: None = ~/Downloads (exportar skill); os testes trocam
    app.state.skills_trash = None  # None = ~/.Trash (tirar skill)
    app.state.chrome_support = None  # None = ~/Library/Application Support (cookies do Chrome); os testes trocam
    app.state.chrome_password = None  # None = o Keychain pelo `security`; os testes trocam
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

    # --- v0.9.4: versão instalada e atualização -------------------------------------------

    @app.get("/sistema/versao", dependencies=[Depends(require_token)])
    async def system_version(buscar: bool = False) -> dict:
        """A versão em uso, se é a instalada ou a de desenvolvimento, e a nova, se houver.
        `buscar` traz as tags do GitHub antes (alguns segundos); sem ele, só o repositório local."""
        info = await asyncio.to_thread(updates.check, settings.home, buscar)
        update_state["info"] = info
        return info

    @app.post("/sistema/atualizar", dependencies=[Depends(require_token)])
    async def system_update(body: dict) -> dict:
        """Abre um terminal à vista que roda o instalar.sh da versão pedida (a mais nova, sem versão).
        O núcleo em uso segue até o Pedro reiniciá-lo; a janela nova oferece isso."""
        info = await asyncio.to_thread(updates.check, settings.home, False)
        if not info["repositorio"]:
            raise HTTPException(status_code=409, detail="não achei o repositório da MÊTIS para buscar a versão nova")
        tag = str(body.get("versao") or info["ultima"] or "")
        if tag not in await asyncio.to_thread(updates.tags, info["repositorio"]):
            raise HTTPException(status_code=400, detail=f"versão não encontrada no repositório: {tag or '(nenhuma)'}")
        session = manager.create("shell", info["repositorio"], title=f"Atualizar a MÊTIS · {tag}")
        manager.send_text(session.id, updates.update_command(info["repositorio"], tag), paste=False)
        return session.to_dict()

    # --- perfis e backup (v0.9.8, parte 5) -----------------------------------------------

    profile_registry = metis_profiles.ProfileRegistry(metis_profiles_port)

    def metis_profile_fail(exc: metis_profiles.ProfileError) -> HTTPException:
        return HTTPException(status_code=exc.code, detail=str(exc))

    @app.get("/perfis", dependencies=[Depends(require_token)])
    def list_profiles() -> dict:
        """Os perfis (pastas de dados com núcleo próprio), o ativo e o deste núcleo."""
        state = profile_registry.state()
        return {"ativo": state["ativo"], "atual": settings.profile, "perfis": state["perfis"], "travado": settings.locked}

    @app.post("/perfis", dependencies=[Depends(require_token)], status_code=201)
    def create_profile(body: MetisProfileBody) -> dict:
        try:
            profile = profile_registry.create(body.nome, body.vault)
        except metis_profiles.ProfileError as exc:
            raise metis_profile_fail(exc) from exc
        if body.copiar:
            # A configuração do perfil atual, sem segredo nenhum (o mesmo zip do backup).
            metis_backup.copy_config(settings.home, profile.folder, settings.profile)
        manager.events.publish({"type": "perfis"})
        return profile.to_dict()

    @app.patch("/perfis/{profile_id}", dependencies=[Depends(require_token)])
    def patch_profile(profile_id: str, body: MetisProfilePatch) -> dict:
        try:
            profile = profile_registry.update(
                profile_id,
                nome=body.nome,
                vault=body.vault if body.vault else None,
                clear_vault=body.vault is not None and not body.vault.strip(),
            )
        except metis_profiles.ProfileError as exc:
            raise metis_profile_fail(exc) from exc
        manager.events.publish({"type": "perfis"})
        return profile.to_dict()

    @app.delete("/perfis/{profile_id}", dependencies=[Depends(require_token)], status_code=204)
    def delete_profile(profile_id: str) -> None:
        if profile_id == settings.profile:
            raise HTTPException(status_code=400, detail="este é o perfil deste núcleo: troque para outro antes de apagar")
        try:
            profile_registry.delete(profile_id)
        except metis_profiles.ProfileError as exc:
            raise metis_profile_fail(exc) from exc
        manager.events.publish({"type": "perfis"})

    @app.post("/perfis/{profile_id}/ativar", dependencies=[Depends(require_token)])
    def activate_profile(profile_id: str) -> dict:
        """Grava o perfil ativo; o app desliga este núcleo e sobe o do outro perfil."""
        if settings.locked:
            raise HTTPException(status_code=409, detail="esta MÊTIS roda com a pasta imposta pelo ambiente (desenvolvimento): troque de perfil na MÊTIS instalada")
        try:
            profile = profile_registry.activate(profile_id)
        except metis_profiles.ProfileError as exc:
            raise metis_profile_fail(exc) from exc
        manager.events.publish({"type": "perfis"})
        return {"id": profile.id, "pasta": str(profile.folder), "porta": profile.porta, "vault": str(profile.brain) if profile.brain else None}

    def backup_fail(exc: Exception) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    @app.get("/backup", dependencies=[Depends(require_token)])
    def backup_listing() -> dict:
        """O que iria no zip agora, e o que fica fora (com o motivo)."""
        return metis_backup.listing(settings.home)

    @app.post("/backup/exportar", dependencies=[Depends(require_token)])
    async def backup_export(body: BackupExportBody) -> dict:
        folder = Path(body.destino).expanduser() if body.destino else None
        return await asyncio.to_thread(metis_backup.export, settings.home, settings.profile, folder)

    @app.post("/backup/conferir", dependencies=[Depends(require_token)])
    async def backup_check(body: BackupFileBody) -> dict:
        try:
            return await asyncio.to_thread(metis_backup.check, settings.home, Path(body.arquivo).expanduser())
        except metis_backup.BackupError as exc:
            raise backup_fail(exc) from exc

    @app.post("/backup/importar", dependencies=[Depends(require_token)])
    async def backup_import(body: BackupFileBody) -> dict:
        try:
            result = await asyncio.to_thread(metis_backup.restore, settings.home, settings.profile, Path(body.arquivo).expanduser())
        except metis_backup.BackupError as exc:
            raise backup_fail(exc) from exc
        manager.events.publish({"type": "backup.importado"})
        return result

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
                agent = Agent(id="rascunho", name=d.name, cli=d.cli, model=d.model, folder=d.folder, prompt=d.prompt,
                              args=d.args, env=d.env, command=d.command)  # fmt: skip
            session = manager.create(body.kind, body.cwd, body.cols, body.rows, body.title, body.account, body.tag, agent,
                                     resume=body.resume, permission=body.permissao, prompt=body.prompt or None,
                                     model=body.model, effort=body.effort)  # fmt: skip
        except LaunchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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

    def codex_rollout_of(session) -> dict | None:
        """A conversa do Codex deste terminal: pelo thread-id do notify; antes do primeiro fim de
        turno, a mais recente da pasta que nenhum outro terminal aberto já sabe que é dele."""
        others = {s.conversa for s in manager.sessions.values() if s.id != session.id and s.conversa}
        return codex_rollout_for(manager.accounts.list(), session.cwd, session.created_at - 5, app.state.cli_homes,
                                 conversation=session.conversa, skip=others)  # fmt: skip

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
                found = await asyncio.to_thread(codex_rollout_of, old)
                resume = found["id"] if found else None
            if not resume:
                raise HTTPException(status_code=409, detail="não achei a conversa desta sessão para continuar; reinicie do zero")
        if old.pty.alive:
            await manager.close(session_id)
        else:
            manager.forget(session_id)  # já saiu: sai da lista para a nova nascer com o mesmo nome
        try:
            session = reopen(old, resume=resume)
        except (LaunchError, UnknownKind, ExecutableNotFound, UnknownAccount, OSError) as exc:
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
            found = await asyncio.to_thread(codex_rollout_of, old)
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
        except (LaunchError, UnknownKind, ExecutableNotFound, UnknownAccount, OSError) as exc:
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
        """Skills do usuário (Claude de cada conta e Codex) e do projeto da pasta, com o destino
        (claude, codex ou projeto) e de onde vieram, quando instaladas pela MÊTIS (v0.9.8)."""
        dirs = [cli_home("claude") / "skills", cli_home("codex") / "skills"]
        for provider, entry in manager.accounts.list().items():
            for account in entry["accounts"]:
                if account.get("dir"):
                    dirs.append(Path(account["dir"]).expanduser() / "skills")
        where = {"claude": dirs[0], "codex": dirs[1]}
        if cwd:
            where["projeto"] = Path(cwd).expanduser() / ".claude" / "skills"
        return skills_manager.annotate(list_skills(dirs, cwd or None), where)

    def cli_home(provider: str, account_id: str | None = None) -> Path:
        """A pasta da CLI de uma conta (CLAUDE_CONFIG_DIR/CODEX_HOME dela) ou a padrão."""
        if account_id:
            try:
                account = manager.accounts.get(provider, account_id)
            except UnknownAccount:
                account = None
            if account is not None and account.dir:
                return Path(account.dir).expanduser()
        defaults = app.state.cli_homes or {}
        if provider in defaults:
            return Path(defaults[provider])
        if provider == "codex" and os.environ.get("CODEX_HOME"):
            return Path(os.environ["CODEX_HOME"]).expanduser()
        return Path.home() / f".{provider}"

    def skill_homes() -> dict[str, list[Path]]:
        """Para cada CLI: a pasta padrão e as das contas com pasta própria."""
        homes: dict[str, list[Path]] = {}
        listed = manager.accounts.list()
        for provider in ("claude", "codex"):
            found = [cli_home(provider)]
            for account in (listed.get(provider) or {}).get("accounts", []):
                folder = account.get("dir")
                if folder and Path(folder).expanduser() not in found:
                    found.append(Path(folder).expanduser())
            homes[provider] = found
        return homes

    @app.get("/skills/metis", dependencies=[Depends(require_token)])
    def metis_skill() -> dict:
        """A skill que ensina o agente a usar a MÊTIS e se ela já está instalada (v0.9.8)."""
        return barra.skill_state(skill_homes())

    @app.post("/skills/metis", dependencies=[Depends(require_token)])
    def install_metis_skill(body: SkillInstall) -> dict:
        try:
            return barra.install_skill(skill_homes(), body.destino)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"não consegui gravar a skill: {exc}") from exc

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

    @app.put("/avisos/app", dependencies=[Depends(require_token)])
    def set_app_notifier(body: AppNotifier) -> dict:
        """A janela informa o executável do app (v0.9.9): com a janela fechada, o aviso sai por ele."""
        return {"ok": set_notifier(body.exe), "exe": notifier()}

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

    # --- v0.9.3: comandos salvos, atalhos e temas do Ghostty ------------------------------

    @app.get("/comandos", dependencies=[Depends(require_token)])
    def list_commands() -> dict:
        return {"comandos": commands.list()}

    @app.post("/comandos", dependencies=[Depends(require_token)])
    def add_command(body: dict) -> dict:
        try:
            item = commands.add(body)
        except CommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        manager.events.publish({"type": "comandos"})
        return item

    @app.put("/comandos/{command_id}", dependencies=[Depends(require_token)])
    def update_command(command_id: str, body: dict) -> dict:
        try:
            item = commands.update(command_id, body)
        except CommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except UnknownCommand as exc:
            raise HTTPException(status_code=404, detail="comando não encontrado") from exc
        manager.events.publish({"type": "comandos"})
        return item

    @app.delete("/comandos/{command_id}", dependencies=[Depends(require_token)])
    def delete_command(command_id: str) -> dict:
        try:
            commands.delete(command_id)
        except UnknownCommand as exc:
            raise HTTPException(status_code=404, detail="comando não encontrado") from exc
        manager.events.publish({"type": "comandos"})
        return {"ok": True}

    @app.get("/atalhos", dependencies=[Depends(require_token)])
    def get_keymap() -> dict:
        return keymap.get()

    @app.put("/atalhos", dependencies=[Depends(require_token)])
    def put_keymap(body: dict) -> dict:
        try:
            data = keymap.set(body.get("atalhos"))
        except CommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        manager.events.publish({"type": "atalhos"})
        return data

    @app.get("/ghostty", dependencies=[Depends(require_token)])
    def ghostty_themes() -> dict:
        return {"config": ghostty.config_info(), "temas": ghostty.list_themes()}

    @app.get("/ghostty/tema", dependencies=[Depends(require_token)])
    def ghostty_theme(nome: str) -> dict:
        try:
            return {"nome": nome, "cores": ghostty.load_theme(nome)}
        except ghostty.ThemeNotFound as exc:
            raise HTTPException(status_code=404, detail=f"tema não encontrado: {nome}") from exc
        except ghostty.GhosttyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ghostty/ler", dependencies=[Depends(require_token)])
    def ghostty_read(body: GhosttyText) -> dict:
        try:
            colors = ghostty.parse_theme(body.texto)
        except ghostty.GhosttyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"nome": (body.nome or "").strip() or "Tema colado", "cores": colors}

    # --- temas de outros terminais (v0.9.8): Ghostty, Kitty e Warp ----------------------

    @app.get("/temas", dependencies=[Depends(require_token)])
    def terminal_themes() -> dict:
        return {"temas": themes.list_all()}

    @app.get("/temas/tema", dependencies=[Depends(require_token)])
    def terminal_theme(nome: str, formato: str = Query(default="ghostty", pattern="^(ghostty|kitty|warp)$")) -> dict:
        try:
            return {"nome": nome, "formato": formato, "cores": themes.load(nome, formato)}
        except ghostty.ThemeNotFound as exc:
            raise HTTPException(status_code=404, detail=f"tema não encontrado: {nome}") from exc
        except ghostty.GhosttyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/temas/ler", dependencies=[Depends(require_token)])
    def terminal_theme_read(body: ThemeText) -> dict:
        """Tema colado de qualquer dos três: o formato é descoberto pelo texto."""
        try:
            fmt, colors = themes.parse(body.texto, body.formato)
        except ghostty.GhosttyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"nome": (body.nome or "").strip() or "Tema colado", "formato": fmt, "cores": colors}

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

    @app.get("/uso/modelos", dependencies=[Depends(require_token)])
    async def model_usage_report(dias: int = Query(30, ge=1, le=90)) -> dict:
        """v0.9.9: tokens e custo equivalente em API por modelo, dia e projeto, dos registros das CLIs."""
        return await asyncio.to_thread(app.state.model_usage.report, dias)

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

    # v0.9.9: o diálogo "Adicionar projeto" (repositórios do Mac, clonar, criar), no jeito do Orca.
    @app.get("/projects/sugestoes", dependencies=[Depends(require_token)])
    async def project_suggestions() -> dict:
        known = projects.list()
        found = await asyncio.to_thread(find_repos, known, settings.worktrees)
        return {"repositorios": found, "pasta_padrao": str(default_parent(known))}

    @app.post("/projects/clone", dependencies=[Depends(require_token)], status_code=201)
    async def clone_project(body: CloneProject) -> dict:
        parent = Path(body.pasta).expanduser() if body.pasta.strip() else default_parent(projects.list())
        try:
            path = await asyncio.to_thread(clone_repo, body.url, parent)
            project = projects.add(str(path))
        except ProjectError as exc:
            raise fail(exc) from exc
        projects_changed()
        return project.__dict__

    @app.post("/projects/criar", dependencies=[Depends(require_token)], status_code=201)
    async def create_project(body: CreateProject) -> dict:
        parent = Path(body.pasta).expanduser() if body.pasta.strip() else default_parent(projects.list())
        try:
            path = await asyncio.to_thread(create_repo, body.nome, parent)
            project = projects.add(str(path), body.nome.strip())
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

    def worktree_created(project_id: str, created: dict, name: str) -> dict:
        """Depois de criar uma worktree (pela barra lateral ou pela coluna Auto): avisa a janela,
        dispara o evento `worktree.criada` das automações e roda o script de setup do projeto."""
        manager.events.publish({"type": "worktrees", "project": project_id})
        engine.fire_event("worktree.criada", {"projeto": projects.get(project_id).name, "caminho": created["path"], "branch": created.get("branch") or ""})
        script = projects.scripts(project_id).get("setup")
        if script:
            # O setup roda num terminal à vista na worktree nova: dá para acompanhar e corrigir.
            try:
                setup = manager.create("shell", created["path"], title=f"Setup · {created.get('branch') or name}")
                manager.send_text(setup.id, script, paste=False)
                created = {**created, "setup": setup.id}
            except (UnknownKind, ExecutableNotFound, OSError) as exc:
                created = {**created, "setup_erro": str(exc)}
        return created

    @app.post("/projects/{project_id}/worktrees", dependencies=[Depends(require_token)], status_code=201)
    async def new_worktree(project_id: str, body: NewWorktree) -> dict:
        try:
            created = await gitops.create_worktree(project_path(project_id), settings.worktrees, body.name, body.base, body.copy_env, body.modo)
        except gitops.GitError as exc:
            raise fail(exc) from exc
        return worktree_created(project_id, created, body.name)

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
    async def git_diff(
        path: str, file: str, mode: str = Query(default="head", pattern="^(head|staged|worktree|ref)$"), untracked: bool = False, ref: str = ""
    ) -> str:
        try:
            fs.inside(path, file)
            return await gitops.diff(path, file, mode, untracked, ref=ref or None)
        except (gitops.GitError, fs.FileError) as exc:
            raise fail(exc) from exc

    # --- v0.9.6: git e GitHub -----------------------------------------------------------

    @app.get("/git/refs", dependencies=[Depends(require_token)])
    async def git_refs(path: str) -> dict:
        try:
            return await gitops.refs(path)
        except (gitops.GitError, FileNotFoundError, NotADirectoryError) as exc:
            raise fail(exc) from exc

    @app.get("/git/changed", dependencies=[Depends(require_token)])
    async def git_changed(path: str, ref: str) -> dict:
        try:
            return await gitops.changed(path, ref)
        except (gitops.GitError, FileNotFoundError, NotADirectoryError) as exc:
            raise fail(exc) from exc

    @app.post("/git/apply", dependencies=[Depends(require_token)])
    async def git_apply(body: GitApply) -> dict:
        try:
            await gitops.apply_patch(body.path, body.patch, body.cached, body.reverse)
        except (gitops.GitError, FileNotFoundError) as exc:
            raise fail(exc) from exc
        return {"ok": True}

    @app.post("/git/discard", dependencies=[Depends(require_token)])
    async def git_discard(body: GitFiles) -> dict:
        try:
            moved = await gitops.discard(body.path, body.files)
        except (gitops.GitError, fs.FileError, FileNotFoundError, OSError) as exc:
            raise fail(exc) from exc
        return {"ok": True, "lixeira": moved}

    @app.post("/git/fetch", dependencies=[Depends(require_token)])
    async def git_fetch(body: GitPath) -> dict:
        return await git_action(gitops.fetch, body.path)

    @app.post("/git/sync", dependencies=[Depends(require_token)])
    async def git_sync(body: GitPath) -> dict:
        try:
            return await gitops.sync(body.path)
        except (gitops.GitError, FileNotFoundError) as exc:
            raise fail(exc) from exc

    @app.post("/git/operacao", dependencies=[Depends(require_token)])
    async def git_operation(body: GitOperation) -> dict:
        return await git_action(gitops.finish_operation, body.path, body.acao)

    @app.get("/git/conflito", dependencies=[Depends(require_token)])
    async def git_conflict(path: str, file: str) -> dict:
        try:
            return await gitops.conflict(path, file)
        except (gitops.GitError, fs.FileError, FileNotFoundError, IsADirectoryError) as exc:
            raise fail(exc) from exc

    @app.post("/git/conflito", dependencies=[Depends(require_token)])
    async def git_resolve(body: GitConflict) -> dict:
        if body.lado is None and body.escolhas is None:
            raise HTTPException(status_code=400, detail="diga as escolhas de cada conflito ou o lado do arquivo inteiro")
        try:
            done = await gitops.resolve(body.path, body.file, choices=body.escolhas, side=body.lado)
        except (gitops.GitError, fs.FileError, FileNotFoundError) as exc:
            raise fail(exc) from exc
        return {"resolvido": done}

    @app.get("/git/blob", dependencies=[Depends(require_token_or_query)])
    async def git_blob(path: str, file: str, ref: str = "HEAD") -> Response:
        try:
            data = await gitops.blob(path, file, ref)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (gitops.GitError, fs.FileError) as exc:
            raise fail(exc) from exc
        return Response(content=data, media_type=fs.media_type(Path(file)), headers={"Cache-Control": "no-store"})

    @app.get("/git/config", dependencies=[Depends(require_token)])
    async def git_config() -> dict:
        return await gitops.global_config()

    @app.put("/git/config", dependencies=[Depends(require_token)])
    async def git_config_set(body: GitSigning) -> dict:
        try:
            return await gitops.set_signing(body.assinar)
        except gitops.GitError as exc:
            raise fail(exc) from exc

    @app.get("/github/estado", dependencies=[Depends(require_token)])
    async def github_state(path: str) -> dict:
        return await asyncio.to_thread(github.state, path)

    @app.get("/github/itens", dependencies=[Depends(require_token)])
    async def github_items(path: str) -> dict:
        return await asyncio.to_thread(github.items, path)

    @app.post("/github/pr", dependencies=[Depends(require_token)])
    async def github_create(body: PrCreate) -> dict:
        try:
            gitops.check_ref(body.base)
            info = await gitops.status(body.path)
            if not info["upstream"] or info["ahead"] > 0:
                await gitops.push(body.path)  # o gh não cria PR de branch que não subiu
            return await asyncio.to_thread(github.create_pr, body.path, body.titulo, body.corpo, body.base, body.rascunho)
        except (gitops.GitError, github.GithubError, FileNotFoundError) as exc:
            raise fail(exc) from exc

    @app.post("/github/pr/juntar", dependencies=[Depends(require_token)])
    async def github_merge(body: PrNumber) -> dict:
        try:
            return await asyncio.to_thread(github.merge_pr, body.path, body.numero, body.metodo)
        except github.GithubError as exc:
            raise fail(exc) from exc

    @app.post("/github/pr/pronto", dependencies=[Depends(require_token)])
    async def github_ready(body: PrNumber) -> dict:
        try:
            return await asyncio.to_thread(github.mark_ready, body.path, body.numero)
        except github.GithubError as exc:
            raise fail(exc) from exc

    @app.get("/sistema/editores", dependencies=[Depends(require_token)])
    def system_editors() -> list[dict]:
        return system.list_editors()

    @app.post("/sistema/abrir-em", dependencies=[Depends(require_token)], status_code=204)
    def system_open_in(body: OpenIn) -> None:
        try:
            system.open_in(body.editor, body.path)
        except (ValueError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        return await git_action(gitops.commit, body.path, body.message, body.amend)

    @app.post("/git/push", dependencies=[Depends(require_token)])
    async def git_push(body: GitPush) -> dict:
        return await git_action(gitops.push, body.path, body.force)

    @app.post("/git/pull", dependencies=[Depends(require_token)])
    async def git_pull(body: GitPath) -> dict:
        return await git_action(gitops.pull, body.path)

    # --- v0.9.8 parte 5: checks falhos, revisão de PR, grafo do código e Skills -------------

    @app.get("/github/checks-falhos", dependencies=[Depends(require_token)])
    async def github_failed_checks(root: str) -> dict:
        return await asyncio.to_thread(github.failed_checks, root)

    @app.post("/github/checks-falhos/pedido", dependencies=[Depends(require_token)])
    async def github_checks_request(body: RootBody) -> dict:
        try:
            return {"pedido": await asyncio.to_thread(github.checks_request, body.root)}
        except github.GithubError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/github/revisao", dependencies=[Depends(require_token)])
    async def github_review(body: ReviewBody) -> dict:
        """Revisão do PR por um agente que só lê: plano no Claude, sandbox só de leitura no Codex."""
        try:
            numero, prompt = await asyncio.to_thread(github.review_request, body.root, body.numero)
        except github.GithubError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        readonly = ["--permission-mode", "plan"] if body.cli == "claude" else ["--sandbox", "read-only"]
        try:
            # permission="padrao": o modo dos ajustes (até yolo) não entra; vale só o de leitura.
            session = manager.create(body.cli, body.root, title=f"Revisão do PR #{numero}", prompt=prompt, permission="padrao", extra_args=readonly)
        except ExecutableNotFound as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc
        except (LaunchError, UnknownKind) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise HTTPException(status_code=400, detail=f"pasta inválida: {body.root}") from exc
        return session.to_dict()

    @app.get("/codigo/grafo", dependencies=[Depends(require_token)])
    def code_graph(root: str) -> dict:
        return graphify_tools.state(root)

    @app.post("/codigo/grafo/atualizar", dependencies=[Depends(require_token)], status_code=202)
    def code_graph_update(body: RootBody) -> dict:
        """`graphify update` em segundo plano (sem IA); avisa a tela pelo evento codigo.grafo."""
        if not Path(body.root).expanduser().is_dir():
            raise HTTPException(status_code=400, detail=f"pasta inválida: {body.root}")

        def work() -> None:
            try:
                detail = graphify_tools.update(body.root)
                event = {"type": "codigo.grafo", "root": body.root, "status": "ok", "detalhe": detail[-400:]}
            except graphify_tools.GraphifyError as exc:
                event = {"type": "codigo.grafo", "root": body.root, "status": "erro", "detalhe": str(exc)}
            manager.events.publish(event)

        threading.Thread(target=work, name="graphify-update", daemon=True).start()
        return {"ok": True}

    def skills_dir(destino: str, root: str | None) -> Path:
        """A pasta skills do destino: a da conta ativa do Claude ou do Codex, ou a do projeto."""
        if destino in ("claude", "codex"):
            return cli_home(destino) / "skills"
        if not root or not Path(root).expanduser().is_dir():
            raise HTTPException(status_code=400, detail="diga a pasta do projeto (root) para o destino projeto")
        return Path(root).expanduser() / ".claude" / "skills"

    def skill_fail(exc: Exception) -> HTTPException:
        status = 409 if isinstance(exc, skills_manager.SkillConflict) else 404 if isinstance(exc, skills_manager.SkillMissing) else 400
        return HTTPException(status_code=status, detail=str(exc))

    @app.post("/skills/instalar", dependencies=[Depends(require_token)])
    async def skills_install(body: SkillAdd) -> dict:
        target = skills_dir(body.destino, body.root)
        try:
            return await asyncio.to_thread(skills_manager.install, body.origem, target, body.substituir)
        except skills_manager.SkillError as exc:
            raise skill_fail(exc) from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="o git demorou demais para clonar") from exc

    @app.post("/skills/{nome}/atualizar", dependencies=[Depends(require_token)])
    async def skills_update(nome: str, body: SkillWhere) -> dict:
        try:
            return await asyncio.to_thread(skills_manager.update, nome, skills_dir(body.destino, body.root))
        except skills_manager.SkillError as exc:
            raise skill_fail(exc) from exc

    @app.post("/skills/{nome}/exportar", dependencies=[Depends(require_token)])
    def skills_export(nome: str, body: SkillWhere) -> dict:
        try:
            return {"arquivo": str(skills_manager.export(nome, skills_dir(body.destino, body.root), app.state.skills_downloads))}
        except skills_manager.SkillError as exc:
            raise skill_fail(exc) from exc

    @app.post("/skills/{nome}/copiar", dependencies=[Depends(require_token)])
    def skills_copy(nome: str, body: SkillCopy) -> dict:
        if body.de == body.para:
            raise HTTPException(status_code=400, detail="a origem e o destino são o mesmo")
        try:
            target = skills_manager.copy(nome, skills_dir(body.de, body.root), skills_dir(body.para, body.root))
        except skills_manager.SkillError as exc:
            raise skill_fail(exc) from exc
        return {"pasta": str(target)}

    @app.delete("/skills/{nome}", dependencies=[Depends(require_token)])
    def skills_remove(nome: str, destino: str, root: str | None = None) -> dict:
        if destino not in ("claude", "codex", "projeto"):
            raise HTTPException(status_code=400, detail="destino é claude, codex ou projeto")
        try:
            return {"lixeira": str(skills_manager.trash(nome, skills_dir(destino, root), app.state.skills_trash))}
        except skills_manager.SkillError as exc:
            raise skill_fail(exc) from exc

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

    @app.put("/fs/text", dependencies=[Depends(require_token)])
    def fs_write(body: FsWrite) -> dict:
        """Salvar do editor (v0.9.7): só se o arquivo ainda for o que o editor abriu (hash)."""
        try:
            return fs.write_text(body.root, body.path, body.text, body.hash)
        except fs.FileConflict as exc:
            raise HTTPException(status_code=409, detail={"mensagem": str(exc), "hash": exc.hash}) from exc
        except fs.TooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except (fs.FileError, OSError) as exc:
            raise fail(exc) from exc

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

    # --- navegador da MÊTIS (v0.9.8): resposta da janela, histórico, perfis, cookies -------------

    @app.post("/navegador/resposta/{request_id}", dependencies=[Depends(require_token)], status_code=204)
    def browser_answer(request_id: str, body: BrowserAnswer) -> None:
        """A janela devolve o que o agente pediu pelo MCP (navegador_ler, navegador_clicar…)."""
        if hub.browser is None or not hub.browser.resolve(request_id, body.ok, body.resultado, body.erro):
            raise HTTPException(status_code=404, detail="pedido do navegador não encontrado (expirou?)")

    @app.post("/navegador/historico", dependencies=[Depends(require_token)], status_code=204)
    def browser_visit(body: HistoryVisit) -> None:
        browser_history.visit(body.url, body.titulo)

    @app.get("/navegador/historico", dependencies=[Depends(require_token)])
    def browser_history_list(q: str = "", limite: int = Query(20, ge=1, le=100)) -> dict:
        return {"itens": browser_history.search(q, limite)}

    @app.delete("/navegador/historico", dependencies=[Depends(require_token)], status_code=204)
    def browser_history_clear() -> None:
        browser_history.clear()

    def profile_fail(exc: ProfileError) -> HTTPException:
        return HTTPException(status_code=exc.status, detail=str(exc))

    @app.get("/navegador/perfis", dependencies=[Depends(require_token)])
    def browser_profiles_list() -> dict:
        return {"perfis": browser_profiles.list()}

    @app.post("/navegador/perfis", dependencies=[Depends(require_token)])
    def browser_profile_new(body: ProfileBody) -> dict:
        try:
            return browser_profiles.create(body.nome)
        except ProfileError as exc:
            raise profile_fail(exc) from exc

    @app.patch("/navegador/perfis/{profile_id}", dependencies=[Depends(require_token)])
    def browser_profile_rename(profile_id: str, body: ProfileBody) -> dict:
        try:
            return browser_profiles.rename(profile_id, body.nome)
        except ProfileError as exc:
            raise profile_fail(exc) from exc

    @app.delete("/navegador/perfis/{profile_id}", dependencies=[Depends(require_token)], status_code=204)
    def browser_profile_delete(profile_id: str) -> None:
        try:
            browser_profiles.delete(profile_id)
        except ProfileError as exc:
            raise profile_fail(exc) from exc

    @app.get("/navegador/importar", dependencies=[Depends(require_token)])
    async def browser_import_sources() -> dict:
        """Perfis do Chrome, Brave, Edge, Arc e Chromium com cookies para importar."""
        return {"fontes": await asyncio.to_thread(chrome_cookies.list_sources, app.state.chrome_support)}

    @app.post("/navegador/importar", dependencies=[Depends(require_token)])
    async def browser_import(body: ImportBody) -> dict:
        """Os cookies decifrados (a senha vem do Keychain, com licença do Pedro). Nunca vão para log."""
        try:
            return await asyncio.to_thread(
                chrome_cookies.read_cookies, body.fonte, body.dominios, app.state.chrome_support, app.state.chrome_password
            )
        except chrome_cookies.ChromeCookieError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    # --- v0.9.7: editor de notas ----------------------------------------------------------

    @app.get("/brain/note/texto", dependencies=[Depends(require_token)])
    def brain_note_text(path: str) -> dict:
        """A nota inteira, com o frontmatter, e o hash que o editor manda de volta ao salvar."""
        try:
            target = vault.resolve(path)
            data = target.read_bytes()
        except (VaultError, OSError) as exc:
            raise brain_fail(exc) from exc
        return {
            "path": vault.rel(target),
            "texto": data.decode("utf-8", "replace"),
            # v1.0.0: nota fora de UTF-8 abre só para leitura (gravar estragaria os acentos).
            "utf8": fs.is_utf8(data),
            "hash": hashlib.sha256(data).hexdigest(),
            "alterado": target.stat().st_mtime,
        }

    @app.put("/brain/note/texto", dependencies=[Depends(require_token)])
    def brain_note_save(body: NoteText) -> dict:
        """Salva a nota só se ela ainda for a que o editor abriu: se o Obsidian gravou depois,
        recusa (409) com o hash de agora. Nunca grava nota vazia, nota fora de UTF-8 nem cria nota."""
        if not body.texto.strip():
            raise HTTPException(status_code=400, detail="o Brain nunca apaga: nota vazia não é gravada")
        try:
            target = vault.resolve(body.path)
            on_disk = target.read_bytes()
        except (VaultError, OSError) as exc:
            raise brain_fail(exc) from exc
        if not fs.is_utf8(on_disk):
            raise HTTPException(status_code=400, detail="a nota não está em UTF-8: a MÊTIS não grava por cima para não estragar os acentos.")
        current = hashlib.sha256(on_disk).hexdigest()
        if current != body.hash:
            raise HTTPException(status_code=409, detail={"mensagem": "a nota mudou (no Obsidian?) desde que foi aberta", "hash": current})
        write_atomic(target, body.texto)
        brain.refresh(max_age=0)  # uma nota mudou: o resto do vault só é conferido pelo mtime
        meta, _body = split_frontmatter(body.texto)
        project = target.stem if meta.get("tipo") == "projeto" else link_target(meta.get("projeto", ""))
        brain_changed(project)
        return {"hash": hashlib.sha256(body.texto.encode("utf-8")).hexdigest(), "alterado": target.stat().st_mtime}

    @app.get("/brain/arvore", dependencies=[Depends(require_token)])
    def brain_tree() -> list[dict]:
        """v0.9.9: a árvore de pastas e notas do vault (Brain e Estudo)."""
        return vault.tree()

    @app.get("/brain/titulos", dependencies=[Depends(require_token)])
    def brain_titles(q: str = "", limite: int = Query(default=20, ge=1, le=50)) -> list[dict]:
        """Títulos para o autocompletar de [[ no editor de notas."""
        return brain.titles(q, limite)

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
    async def session_context_window(session_id: str) -> dict:
        """Janela de contexto do Claude (o que ocupa o contexto, lido do transcript). O Inspector
        chama a cada resposta: a conversa da sessão fica em /conversa, que só o ⋯ e a espiada pedem."""
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        line = session.statusline or {}
        transcript = line.get("transcript")
        if not transcript:
            return {"available": False, "reason": "o Claude ainda não mandou a statusline desta sessão"}
        return await asyncio.to_thread(context_breakdown, transcript, line.get("context") or {})

    @app.get("/sessions/{session_id}/conversa", dependencies=[Depends(require_token)])
    async def session_conversation(session_id: str) -> dict:
        """A conversa da sessão (v0.9.8): cli, id_conversa, transcript, cwd e texto (Claude e Codex)."""
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        return await conversation_of(session)

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

    @app.get("/kanban/tarefas", dependencies=[Depends(require_token)])
    def all_tasks() -> list[dict]:
        """v0.9.9: as tarefas de todos os projetos do Brain, com o projeto e o número de cada uma."""
        out: list[dict] = []
        for project in kanban.projects():
            try:
                tasks = kanban.tasks(project["name"])
            except VaultError:
                continue
            for n, task in enumerate(tasks, start=1):
                out.append({**task, "projeto": project["name"], "n": n})
        return out

    # --- coluna Auto (v0.9.9) ---

    def project_directory(name: str) -> str:
        project = next((p for p in kanban.projects() if p["name"] == name), None)
        if project is None:
            raise AutoError(f"projeto não encontrado no Brain: {name}")
        folder = str(project.get("directory") or "").strip()
        if not folder:
            raise AutoError(f"a nota de {name} não tem diretorio: no frontmatter (a pasta do código)")
        path = Path(folder).expanduser()
        if not path.is_dir():
            raise AutoError(f"a pasta do projeto não existe: {folder}")
        return str(path)

    async def auto_start(item: AutoItem) -> tuple[str, str]:
        # Antes de mexer no git: o agente existe e a CLI está instalada (senão sobrava uma worktree sem uso).
        agent = None
        if item.agente:
            try:
                agent = agents.get(item.agente)
            except AgentError as exc:
                raise AutoError(f"o agente {item.agente} não existe mais: escolha outro no Rodar sozinha") from exc
        kind = agent.cli if agent is not None and agent.cli in ("claude", "codex") else item.cli
        if not shutil.which(kind):
            raise AutoError(f"o {kind} não está instalado (comando {kind} não encontrado)")
        cwd = await asyncio.to_thread(project_directory, item.projeto)
        created = None
        project = None
        if item.onde == "worktree":
            try:
                project = projects.add(cwd)
                projects_changed()
                # O id do item no nome: rodar a mesma tarefa de novo não bate na pasta da vez anterior.
                name = f"auto-{(slugify(item.texto)[:32].strip('-') or item.tarefa)}-{item.id[:4]}"
                created = await gitops.create_worktree(project.path, settings.worktrees, name, None, True, "nova")
            except (ProjectError, gitops.GitError) as exc:
                raise AutoError(f"não deu para criar a worktree: {exc}") from exc
            created = worktree_created(project.id, created, name)
            cwd = created["path"]
        try:
            session = manager.create(kind, cwd, title=f"Auto · {item.texto[:40]}", agent=agent, permission=item.permissao,
                                     prompt=auto_prompt(item), model=item.modelo or None, effort=item.esforco or None)  # fmt: skip
        except Exception as exc:
            # O agente não abriu: a worktree que acabou de nascer sai junto (branch sem commit nenhum).
            if created is not None and project is not None:
                try:
                    await gitops.remove_worktree(project.path, created["path"], force=True)
                    manager.events.publish({"type": "worktrees", "project": project.id})
                except gitops.GitError:
                    pass
            raise AutoError(f"o agente não abriu: {exc}") from exc
        return session.id, cwd

    def auto_move(projeto: str, tarefa: str, state: str) -> None:
        kanban.move(projeto, tarefa, state)
        brain_changed(projeto)

    auto = AutoQueue(settings.home / "kanban-auto.json", start=auto_start, move=auto_move, publish=manager.events.publish)
    auto.update_task_ids(kanban.current_ids)  # fila gravada antes da v1.0, com o id que contava os rótulos
    manager.events.listen(auto.on_bus_event)
    app.state.auto = auto

    @app.get("/kanban/auto", dependencies=[Depends(require_token)])
    def auto_view() -> dict:
        return auto.view()

    @app.post("/kanban/auto", dependencies=[Depends(require_token)], status_code=201)
    def auto_enqueue(body: AutoEnqueue) -> dict:
        try:
            task = next((t for t in kanban.tasks(body.projeto) if t["id"] == body.tarefa), None)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        if task is None:
            raise HTTPException(status_code=404, detail="tarefa não encontrada (a nota mudou?)")
        if body.agente:
            try:
                agents.get(body.agente)
            except AgentError as exc:
                raise HTTPException(status_code=400, detail=f"o agente {body.agente} não existe mais") from exc
        try:
            item = auto.enqueue(body.projeto, body.tarefa, task.get("texto") or task["text"], cli=body.cli, agente=body.agente, modelo=body.modelo,
                                esforco=body.esforco, permissao=body.permissao, onde=body.onde)  # fmt: skip
        except AutoError as exc:
            raise fail(exc) from exc
        return item.to_dict()

    @app.delete("/kanban/auto/{item_id}", dependencies=[Depends(require_token)])
    def auto_cancel(item_id: str) -> dict:
        try:
            return auto.cancel(item_id).to_dict()
        except AutoError as exc:
            raise fail(exc) from exc

    @app.delete("/kanban/auto", dependencies=[Depends(require_token)], status_code=204)
    def auto_clear() -> None:
        auto.clear_done()

    @app.put("/kanban/auto/limite", dependencies=[Depends(require_token)])
    def auto_limit(body: AutoLimit) -> dict:
        try:
            auto.set_limit(body.limite)
        except AutoError as exc:
            raise fail(exc) from exc
        return auto.view()

    @app.get("/brain/projects/{name}/tasks", dependencies=[Depends(require_token)])
    def brain_tasks(name: str) -> list[dict]:
        try:
            return kanban.tasks(name)
        except VaultError as exc:
            raise brain_fail(exc) from exc

    @app.post("/brain/projects/{name}/tasks", dependencies=[Depends(require_token)], status_code=201)
    def brain_add_task(name: str, body: TaskBody) -> dict:
        try:
            task = kanban.add(name, body.text, body.state, labels=body.rotulos, subtasks=body.subtarefas)
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

    # --- v0.9.8 parte 3: rótulos, subtarefas, ClickUp no kanban, painel e eventos dos agentes ---

    @app.put("/brain/projects/{name}/tasks/{task_id}/rotulos", dependencies=[Depends(require_token)])
    def brain_task_labels(name: str, task_id: str, body: TaskLabels) -> dict:
        try:
            task = kanban.set_labels(name, task_id, body.rotulos)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        brain_changed(name)
        return task

    @app.post("/brain/projects/{name}/tasks/{task_id}/subtarefas", dependencies=[Depends(require_token)], status_code=201)
    def brain_add_subtask(name: str, task_id: str, body: NewSubtask) -> dict:
        try:
            task = kanban.add_subtask(name, task_id, body.texto)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        brain_changed(name)
        return task

    @app.put("/brain/projects/{name}/tasks/{task_id}/subtarefas/{index}", dependencies=[Depends(require_token)])
    def brain_mark_subtask(name: str, task_id: str, index: int, body: MarkSubtask) -> dict:
        try:
            task = kanban.mark_subtask(name, task_id, index, body.feita)
        except VaultError as exc:
            raise brain_fail(exc) from exc
        brain_changed(name)
        return task

    @app.get("/brain/projects/{name}/rotulos", dependencies=[Depends(require_token)])
    def brain_labels(name: str) -> dict:
        try:
            return {"rotulos": kanban.labels(name)}
        except VaultError as exc:
            raise brain_fail(exc) from exc

    clickup = ClickupBoard(settings.home, connectors)

    def clickup_fail(exc: Exception) -> HTTPException:
        if isinstance(exc, ClickupError):
            return HTTPException(status_code=exc.status, detail=str(exc))
        return HTTPException(status_code=404 if "desconhecida" in str(exc) else 400, detail=str(exc))

    @app.get("/clickup/{conta}/token-api", dependencies=[Depends(require_token)])
    def clickup_token_state(conta: str) -> dict:
        try:
            return {"tem": clickup.has_personal(conta)}
        except (ClickupError, ConnectorError) as exc:
            raise clickup_fail(exc) from exc

    @app.put("/clickup/{conta}/token-api", dependencies=[Depends(require_token)], status_code=204)
    async def clickup_token_set(conta: str, body: ClickupToken) -> None:
        try:
            await asyncio.to_thread(clickup.set_personal, conta, body.token)
        except ClickupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ConnectorError as exc:
            raise clickup_fail(exc) from exc

    @app.delete("/clickup/{conta}/token-api", dependencies=[Depends(require_token)], status_code=204)
    def clickup_token_drop(conta: str) -> None:
        try:
            clickup.drop_personal(conta)
        except (ClickupError, ConnectorError) as exc:
            raise clickup_fail(exc) from exc

    @app.get("/clickup/{conta}/listas", dependencies=[Depends(require_token)])
    async def clickup_lists(conta: str) -> dict:
        try:
            return {"listas": await asyncio.to_thread(clickup.lists, conta)}
        except (ClickupError, ConnectorError) as exc:
            raise clickup_fail(exc) from exc

    @app.patch("/clickup/{conta}/tarefas/{task_id}", dependencies=[Depends(require_token)])
    async def clickup_task_status(conta: str, task_id: str, body: ClickupStatus) -> dict:
        try:
            return await asyncio.to_thread(clickup.set_status, conta, task_id, body.status)
        except (ClickupError, ConnectorError) as exc:
            raise clickup_fail(exc) from exc

    @app.get("/kanban/{projeto}/clickup", dependencies=[Depends(require_token)])
    async def kanban_clickup(projeto: str) -> dict:
        try:
            return await asyncio.to_thread(clickup.board, projeto)
        except (ClickupError, ConnectorError) as exc:
            raise clickup_fail(exc) from exc

    @app.put("/kanban/{projeto}/clickup", dependencies=[Depends(require_token)])
    def kanban_clickup_link(projeto: str, body: ClickupLink) -> dict:
        try:
            return clickup.set_link(projeto, body.conta, body.lista, body.nome)
        except (ClickupError, ConnectorError) as exc:
            raise clickup_fail(exc) from exc

    @app.delete("/kanban/{projeto}/clickup", dependencies=[Depends(require_token)], status_code=204)
    def kanban_clickup_unlink(projeto: str) -> None:
        clickup.drop_link(projeto)

    #: v1.0: o rollout do Codex de cada sessão (achado uma vez, sem varrer as pastas a cada 4 s)
    #: e a prévia de cada transcript pela data e pelo tamanho (só relê quando ele muda). O rollout
    #: só fica guardado depois que a conversa da sessão é conhecida (o thread-id do notify), junto
    #: com ela: antes disso, o palpite pela pasta pode mudar.
    codex_rollouts: dict[str, tuple[str, str]] = {}
    previews: dict[str, tuple[tuple[int, int], str]] = {}

    def last_agent_text(session, payload: dict | None = None) -> str:
        """A última mensagem do agente, até 280 caracteres (prévia do painel e da Atividade)."""
        payload = payload or {}
        if isinstance(payload.get(PREVIEW_KEY), str):
            return payload[PREVIEW_KEY]  # já lida numa thread pelo /hooks/event
        for key in ("last_assistant_message", "last-assistant-message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())[:280]
        transcript = payload.get("transcript_path") if isinstance(payload.get("transcript_path"), str) else None
        try:
            if not transcript and session.kind == "claude":
                transcript = (session.statusline or {}).get("transcript")
            if not transcript and session.kind == "codex":
                cached_rollout = codex_rollouts.get(session.id)
                if cached_rollout and cached_rollout[0] == session.conversa and os.path.exists(cached_rollout[1]):
                    transcript = cached_rollout[1]
                else:
                    found = codex_rollout_of(session)
                    transcript = found["arquivo"] if found else None
                    if transcript and session.conversa:
                        codex_rollouts[session.id] = (session.conversa, transcript)
            if not transcript:
                return ""
            stat = os.stat(os.path.expanduser(transcript))
            key = (stat.st_mtime_ns, stat.st_size)
            cached = previews.get(transcript)
            if cached is not None and cached[0] == key:
                return cached[1]
            text = next((m["text"][:280] for m in reversed(last_messages(transcript, 6, 600)) if m["role"] == "agente"), "")
            previews[transcript] = (key, text)
            return text
        except Exception:  # transcript ilegível: sem prévia
            return ""

    EVENT_TITLE = {"inicio": "começou", "terminou": "terminou o turno", "pergunta": "precisa de você", "hibernou": "hibernou", "acordou": "acordou"}

    def on_activity(session, kind: str, data: dict) -> None:
        """O que acontece com cada agente vira evento da Atividade (e aparece na hora na tela)."""
        if session.kind not in ("claude", "codex"):
            return
        preview = ""
        if kind == "hook":
            name = data.get("name")
            if name == "Stop":
                kind, preview = "terminou", last_agent_text(session, data.get("payload"))
            elif name == "Notification" and not data.get("idle"):
                kind, preview = "pergunta", data.get("message") or ""
            else:
                return
        title = EVENT_TITLE.get(kind, kind)
        if kind == "saiu":
            title = f"saiu com o código {session.exit_code}" if session.exit_code is not None else "saiu"
        item = activity.event(session.id, session.title, kind, title, preview)
        manager.events.publish({"type": "activity.event", "item": item})

    manager.on_activity = on_activity

    @app.get("/atividade/eventos", dependencies=[Depends(require_token)])
    def activity_events(limite: int = Query(default=100, ge=1, le=1000), sessao: str = "") -> dict:
        return {"eventos": activity.events(limite, sessao)}

    def board_column(session) -> str:
        if session.status == "exited" or session.hibernando:
            return "parado"
        if session.atencao == "pergunta":
            return "precisa"
        if session.status == "working":
            return "trabalhando"
        if session.atencao == "terminou":
            return "feito"
        return "parado"

    @app.get("/agentes/painel", dependencies=[Depends(require_token)])
    async def agents_board() -> dict:
        """Painel de agentes (v0.9.8): cada Claude e Codex aberto, na coluna do que espera de você."""
        now = time.time()
        out = []
        agents = [s for s in list(manager.sessions.values()) if s.kind in ("claude", "codex")]
        # As prévias ao mesmo tempo, cada uma numa thread (antes, uma depois da outra).
        texts = await asyncio.gather(*(asyncio.to_thread(last_agent_text, s) for s in agents))
        for session, preview in zip(agents, texts):
            line = session.statusline or {}
            out.append(
                {
                    "id": session.id,
                    "titulo": session.title,
                    "cli": session.kind,
                    "agente": session.agent,
                    "cwd": session.cwd,
                    "coluna": board_column(session),
                    "desde": session.status_desde,
                    "previa": preview,
                    "custo_usd": line.get("cost_usd") if session.kind == "claude" else None,
                    "duracao_s": round(now - session.created_at),
                    "tag": session.tag,
                }
            )
        return {"agentes": out}

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
            # Modo de ferramenta inválido é pedido errado (400); conta que não existe, 404.
            raise fail(exc, 400 if "modo de ferramenta" in str(exc) else 404) from exc
        connectors_changed()
        return account.to_dict()

    @app.delete("/conectores/{account_id}", dependencies=[Depends(require_token)], status_code=204)
    def delete_connector(account_id: str) -> None:
        try:
            connectors.remove(account_id)
        except ConnectorError as exc:
            raise fail(exc, 404) from exc
        connectors_changed()

    @app.get("/conectores/{account_id}/ferramentas", dependencies=[Depends(require_token)])
    def connector_tools(account_id: str) -> dict:
        """v0.9.9: as ferramentas da conta, com o modo de cada uma (livre, aprovação, desligada)."""
        try:
            account = connectors.get(account_id)
            tools = hub.account_tools(account)
        except (ConnectorError, RuntimeError, OSError) as exc:
            raise fail(exc) from exc
        return {
            "ferramentas": [
                {"nome": t.name, "descricao": t.description[:300], "escrita": bool(t.write), "modo": tool_mode(account, t.name, t.write), "escolhido": t.name in (account.tool_modes or {})}
                for t in tools
            ]
        }

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

    # --- conectores da v0.9.8 (parte 3): GitHub, Google, MCP próprio, catálogo, testar, CLIs ---

    registry = mcp_registry.McpRegistry(connectors.http)
    app.state.connectors = connectors
    app.state.mcp_cli_runner = None  # None = as CLIs de verdade; os testes trocam

    @app.post("/conectores/github", dependencies=[Depends(require_token)], status_code=201)
    def connect_github(body: GithubConnect) -> dict:
        try:
            account = connectors.add_github(body.nome, body.token or "")
        except ConnectorError as exc:
            raise fail(exc) from exc
        connectors_changed()
        return account.to_dict()

    @app.get("/conectores/google/cliente", dependencies=[Depends(require_token)])
    def google_client() -> dict:
        return connectors.google_client_status()

    @app.put("/conectores/google/cliente", dependencies=[Depends(require_token)])
    def set_google_client(body: GoogleClient) -> dict:
        try:
            return connectors.set_google_client(body.client_id, body.client_secret)
        except ConnectorError as exc:
            raise fail(exc) from exc

    @app.post("/conectores/google/iniciar", dependencies=[Depends(require_token)])
    def start_google(body: GoogleStart) -> dict:
        try:
            return {"url": connectors.start_google(body.nome, f"{settings.url}/conectores/oauth/retorno")}
        except ConnectorError as exc:
            raise fail(exc) from exc

    @app.post("/conectores/mcp", dependencies=[Depends(require_token)])
    def connect_mcp(body: McpConnect) -> JSONResponse:
        """MCP próprio: por endereço (sem login, token ou OAuth) ou por comando (stdio)."""
        try:
            if body.transporte == "stdio":
                created = connectors.add_mcp_stdio(body.nome, body.comando, body.env, body.pasta)
            elif body.transporte == "http":
                created = connectors.add_mcp_http(body.nome, body.url, body.auth, body.token, f"{settings.url}/conectores/oauth/retorno")
            else:
                raise ConnectorError("transporte: http ou stdio")
        except ConnectorError as exc:
            raise fail(exc) from exc
        if isinstance(created, str):  # OAuth: a página de login abre no navegador
            return JSONResponse({"url": created})
        connectors_changed()
        return JSONResponse(created.to_dict(), status_code=201)

    @app.get("/conectores/catalogo-mcp", dependencies=[Depends(require_token)])
    def mcp_catalog(q: str = Query(default="", max_length=200)) -> dict:
        try:
            return {"servidores": registry.search(q)}
        except mcp_registry.RegistryError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/conectores/{account_id}/testar", dependencies=[Depends(require_token)])
    def try_connector(account_id: str) -> dict:
        return connectors.test(account_id)

    def cli_places() -> mcp_configs.Places:
        claude = manager.accounts.active("claude")
        codex = manager.accounts.active("codex")
        claude_json = Path(claude.dir).expanduser() / ".claude.json" if claude.dir else settings.claude_json
        return mcp_configs.Places(
            claude_json=claude_json,
            codex_config=cli_home("codex", codex.id) / "config.toml",
            claude_env={"CLAUDE_CONFIG_DIR": str(Path(claude.dir).expanduser())} if claude.dir else {},
            codex_env={"CODEX_HOME": str(cli_home("codex", codex.id))} if codex.dir or app.state.cli_homes else {},
        )

    @app.get("/mcps-cli", dependencies=[Depends(require_token)])
    def cli_mcps() -> dict:
        return mcp_configs.listing(cli_places())

    @app.post("/mcps-cli/copiar", dependencies=[Depends(require_token)])
    def copy_cli_mcp(body: McpCopy) -> dict:
        try:
            return mcp_configs.copy(cli_places(), body.de, body.para, body.nome, app.state.mcp_cli_runner)
        except mcp_configs.McpConfigError as exc:
            raise HTTPException(status_code=exc.code, detail=str(exc)) from exc

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

    @app.post("/sessions/{session_id}/acordar", dependencies=[Depends(require_token)])
    def wake_session(session_id: str) -> dict:
        """Acorda o agente que hibernava (SIGCONT); se não hibernava, só devolve a sessão."""
        session = manager.wake(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        return session.to_dict()

    @app.get("/sessions/{session_id}/barra", dependencies=[Depends(require_token)])
    def session_slash_commands(session_id: str) -> dict:
        """O que oferecer ao digitar "/" na barra de baixo desta sessão (v0.9.8)."""
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        if session.kind not in ("claude", "codex"):
            return {"comandos": []}
        home = cli_home(session.kind, session.account)
        return {"comandos": barra.slash_commands(session.kind, home, session.cwd)}

    async def conversation_of(session) -> dict:
        """A conversa da sessão para levar a outro lugar (v0.9.8): id, transcript e as últimas 20 mensagens."""
        conversation, transcript = None, None
        if session.kind == "claude":
            line = session.statusline or {}
            conversation, transcript = line.get("session_id"), line.get("transcript")
        elif session.kind == "codex":
            found = await asyncio.to_thread(codex_rollout_of, session)
            if found:
                conversation, transcript = found["id"] or None, found["arquivo"]
        recent = await asyncio.to_thread(last_messages, transcript, 20, 2000) if transcript else []
        text = "\n\n".join(f"{'você' if m['role'] == 'voce' else 'agente'}: {m['text']}" for m in recent)
        return {"cli": session.kind, "id_conversa": conversation, "transcript": transcript, "cwd": session.cwd, "texto": text}

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

    # --- v0.9.8 parte 4: automação por frase, código pelo Claude, n8n e estratégias ---------------
    # Antes de /automacoes/{automation_id}: senão "estrategias" e "proposta" viram um id.

    def automation_ask(prompt: str) -> dict:
        """Pedido pontual ao Claude (Sonnet, pelo plano, sem ferramentas); os testes trocam app.state.automation_ask."""
        override = getattr(app.state, "automation_ask", None)
        if override is not None:
            return override(prompt)
        return ask_json(prompt, claude_env(), settings.home / "automacoes-ia", model="sonnet", bare=True)

    async def automation_tools() -> list[dict]:
        catalog = await automation_catalog()
        return catalog["ferramentas"]

    @app.post("/automacoes/proposta", dependencies=[Depends(require_token)])
    async def automation_proposal(body: ProposalBody) -> dict:
        """Criar ou ajustar por frase: devolve a proposta conferida; nada é salvo (quem aplica é o Pedro)."""
        catalog = await automation_catalog()
        try:
            return await asyncio.to_thread(automation_ai.propose, body.descricao, body.atual, catalog["ferramentas"], catalog["agentes"], automation_ask)
        except automation_ai.ProposalInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (ClaudePrintError, automation_ai.ProposalError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/automacoes/codigo/escrever", dependencies=[Depends(require_token)])
    async def automation_write_code(body: CodeWriteBody) -> dict:
        try:
            return await asyncio.to_thread(automation_ai.write_code, body.descricao, body.linguagem, body.entrada_exemplo, automation_ask)
        except automation_ai.ProposalInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (ClaudePrintError, automation_ai.ProposalError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def n8n_client(account_id: str):
        try:
            return connectors.mcp(account_id)
        except ConnectorError as exc:
            raise HTTPException(status_code=404 if "desconhecida" in str(exc) else 400, detail=str(exc)) from exc

    @app.get("/automacoes/n8n/fluxos", dependencies=[Depends(require_token)])
    async def n8n_workflows(conta: str = Query(...)) -> dict:
        client = n8n_client(conta)
        try:
            return {"fluxos": await asyncio.to_thread(n8n_import.list_from_account, client)}
        except n8n_import.ImportError_ as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - erro do MCP de fora vira mensagem, nunca 500
            raise HTTPException(status_code=502, detail=f"o n8n não respondeu: {exc}") from exc

    @app.post("/automacoes/importar-n8n", dependencies=[Depends(require_token)])
    async def import_n8n(body: N8nImportBody) -> dict:
        """Workflow do n8n (o JSON exportado, ou pela conta do MCP do n8n) → proposta, com o que revisar."""
        workflow = body.fluxo
        if workflow is None:
            if not body.conta or not body.workflow_id:
                raise HTTPException(status_code=400, detail="mande o JSON do workflow (fluxo) ou a conta e o workflow_id")
            client = n8n_client(body.conta)
            try:
                workflow = await asyncio.to_thread(n8n_import.fetch_from_account, client, body.workflow_id)
            except n8n_import.ImportError_ as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"o n8n não respondeu: {exc}") from exc
        tools = await automation_tools()
        kinds = {a.id: a.kind for a in connectors.list()}
        try:
            return await asyncio.to_thread(n8n_import.translate, workflow, tools, kinds)
        except n8n_import.ImportError_ as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/automacoes/estrategias", dependencies=[Depends(require_token)])
    def automation_strategies() -> dict:
        return {"estrategias": automation_templates.catalog()}

    @app.post("/automacoes/estrategias/{strategy_id}", dependencies=[Depends(require_token)], status_code=201)
    def create_from_strategy(strategy_id: str, body: StrategyBody) -> dict:
        """A estratégia vira um rascunho de automação (gatilho manual), para o Pedro ajustar e publicar."""
        try:
            flow = automation_templates.build(strategy_id, body.parametros)
            automation_id = automations.create(flow["nome"], flow)
        except automation_templates.StrategyError as exc:
            raise HTTPException(status_code=404 if "desconhecida" in str(exc) else 400, detail=str(exc)) from exc
        except AutomationError as exc:
            raise automation_fail(exc) from exc
        return {"id": automation_id}

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
            # Sondagem só com ferramenta que lê: conferido antes de a versão valer.
            import yaml

            engine.check_trigger(validate(yaml.safe_load(content) if content else automations.draft(automation_id), strict=True))
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
        manager.events.publish({"type": "routines", "routines": [routine_view(r, now) for r in routine_flows.list()]})

    def routine_events(event: dict) -> None:
        """Execução de uma rotina-<id> vira o aviso de rotina de sempre na tela (abriu, pulou, erro)."""
        kind, automation_id = event.get("type"), str(event.get("automation") or "")
        if kind not in ("automation.step", "automation.run") or not automation_id.startswith(ROUTINE_PREFIX):
            return
        if kind == "automation.step" and not event.get("sessao"):
            return
        if kind == "automation.run" and event.get("status") not in ("erro", "pulada"):
            return
        row = next((r for r in engine.runs_with_prefix(automation_id, 5) if r["id"] == event.get("run")), None)
        routine = routine_flows.routine(automation_id)
        if row is None or routine is None:
            return
        manager.events.publish({"type": "routine.run", "routine": routine.to_dict(), "run": routine_flows.run_view(row), "session": row.get("sessao") or None})

    manager.events.listen(routine_events)

    async def run_routine_flow(routine_id: str) -> dict:
        """Rodar agora uma rotina-automação: a execução começa e a resposta sai quando o terminal nasce."""
        automation_id = routine_flows.automation_id(routine_id)
        try:
            run_id = await engine.start(automation_id, "producao", "manual")
        except AutomationError as exc:
            return {"id": 0, "routine": routine_id, "slot": 0, "ts": time.time(), "status": "erro", "session": "", "detail": str(exc)}
        row = None
        for _ in range(100):  # até 10 s: o terminal nasce no primeiro passo
            row = next((r for r in engine.runs_with_prefix(automation_id, 5) if r["id"] == run_id), None)
            if row is not None and (row["sessao"] or row["status"] != "rodando"):
                break
            await asyncio.sleep(0.1)
        assert row is not None
        return routine_flows.run_view(row)

    @app.get("/rotinas", dependencies=[Depends(require_token)])
    def list_routines() -> dict:
        now = datetime.now().astimezone()
        return {"routines": [routine_view(r, now) for r in routine_flows.list()], "runs": routine_flows.runs(60)}

    @app.post("/rotinas", dependencies=[Depends(require_token)], status_code=201)
    def create_routine(body: RoutineBody) -> dict:
        try:
            routine = routine_flows.save(body.model_dump())
        except (RoutineError, AutomationError) as exc:
            raise fail(exc) from exc
        routines_changed()
        return routine_view(routine, datetime.now().astimezone())

    @app.put("/rotinas/{routine_id}", dependencies=[Depends(require_token)])
    def update_routine(routine_id: str, body: RoutineBody) -> dict:
        try:
            routine_flows.get(routine_id)
            if routine_flows.is_flow(routine_id):
                routine = routine_flows.save(body.model_dump(), routine_id)
            else:  # rotina antiga que não migrou (arquivo que não abria): segue no .md
                routine = routines.save(body.model_dump(), routine_id)
        except (RoutineError, AutomationError) as exc:
            raise fail(exc, 404) from exc
        routines_changed()
        return routine_view(routine, datetime.now().astimezone())

    @app.delete("/rotinas/{routine_id}", dependencies=[Depends(require_token)], status_code=204)
    def delete_routine(routine_id: str) -> None:
        try:
            routine_flows.get(routine_id)
            routine_flows.delete(routine_id)
        except (RoutineError, AutomationError) as exc:
            raise fail(exc, 404) from exc
        routines_changed()

    @app.post("/rotinas/{routine_id}/rodar", dependencies=[Depends(require_token)])
    async def run_routine_now(routine_id: str) -> dict:
        try:
            routine = routine_flows.get(routine_id)
        except RoutineError as exc:
            raise fail(exc, 404) from exc
        if routine_flows.is_flow(routine_id):
            return await run_routine_flow(routine_id)
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
        engine.fire_event("captura", {"texto": body.texto})
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
        # v0.9.8: quantos conceitos vencem hoje e a semana do cronograma.
        return {**study.summary(), "vencidos": study_map.due_count(), "semana_atual": study_map.current()}

    @app.post("/estudo/blocos", dependencies=[Depends(require_token)], status_code=201)
    def study_block(body: StudyBlock) -> dict:
        block = study.add(body.minutos, body.assunto)
        manager.events.publish({"type": "study", "summary": study.summary()})
        return block

    # --- Estudo completo (v0.9.8): mapa, plano, conceitos e sessões com o Sócrates ---

    def study_fail(exc: Exception) -> HTTPException:
        text = str(exc)
        status = 404 if "não encontrado" in text or "não está no Brain" in text else 409 if "já existe" in text else 400
        return HTTPException(status_code=status, detail=text)

    @app.get("/estudo/mapa", dependencies=[Depends(require_token)])
    def study_map_route() -> dict:
        try:
            return study_map.map()
        except (StudyError, OSError) as exc:
            raise study_fail(exc) from exc

    @app.get("/estudo/plano", dependencies=[Depends(require_token)])
    def study_plan() -> dict:
        try:
            return study_map.plan()
        except (StudyError, OSError) as exc:
            raise study_fail(exc) from exc

    @app.post("/estudo/conceitos", dependencies=[Depends(require_token)], status_code=201)
    def study_new_concept(body: NewConcept) -> dict:
        try:
            concept = study_map.create(body.nome, body.resumo, body.relacionados, body.semana)
        except (StudyError, OSError) as exc:
            raise study_fail(exc) from exc
        manager.events.publish({"type": "estudo.mudou"})
        return concept.to_dict()

    @app.patch("/estudo/conceitos", dependencies=[Depends(require_token)])
    def study_patch_concept(body: ConceptPatch) -> dict:
        week = body.semana if "semana" in body.model_fields_set else "keep"
        try:
            concept = study_map.update(body.titulo, body.dominio, week)
        except (StudyError, OSError) as exc:
            raise study_fail(exc) from exc
        manager.events.publish({"type": "estudo.mudou"})
        return concept.to_dict()

    @app.post("/estudo/sessao", dependencies=[Depends(require_token)], status_code=201)
    async def study_session(body: StudySessionBody) -> dict:
        # async de propósito: o PTY nasce no loop do asyncio, como em POST /sessions.
        if body.tipo not in SESSION_TYPES:
            raise HTTPException(status_code=400, detail=f"tipo de sessão é {', '.join(SESSION_TYPES)}")
        try:
            agent = agents.get(TUTOR)
        except AgentError as exc:
            raise HTTPException(status_code=400, detail="o Sócrates (agente socrates) não está na galeria de agentes: crie ou importe ele primeiro") from exc
        try:
            prompt = study_map.session_prompt(body.tipo, (body.conceito or "").strip() or None)
            cwd = study_map.session_cwd(body.tipo)
        except (StudyError, OSError) as exc:
            raise study_fail(exc) from exc
        label = {"medir": "medir o que sei", "aprender": f"aprender {body.conceito}" if body.conceito else "aprender",
                 "praticar": "praticar", "revisar": "revisar"}[body.tipo]  # fmt: skip
        try:
            session = manager.create(agent.cli, cwd, title=f"Estudo · {label}"[:60], tag="estudo", agent=agent, prompt=prompt)
        except (LaunchError, UnknownKind, ExecutableNotFound) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise HTTPException(status_code=400, detail=f"pasta inválida para a sessão: {exc}") from exc
        return session.to_dict()

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
        runs_today = routine_flows.runs(200, start.timestamp())
        slots = []
        for routine in routine_flows.list():
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
        except AgentError as exc:
            raise fail(exc, 404) from exc
        try:
            agent = agents.save(body.model_dump(), agent_id)
        except AgentError as exc:
            raise fail(exc) from exc
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
    def get_sprite(agent_id: str, anim: bool = False) -> FileResponse:
        """A sprite parada; com `anim=1`, a tira do movimento parado (v0.9.9)."""
        try:
            path = agents.sprite_path(agent_id, anim)
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

    @app.get("/sprites/modelo", dependencies=[Depends(require_token_or_query)])
    def sprite_model() -> FileResponse:
        """v0.9.9: o modelo que toda sprite segue (o do Pedro, ou o que ele pôs em agentes/sprites/modelo.png)."""
        return FileResponse(model_image(settings.home), media_type="image/png")

    @app.get("/sprites/jobs/{job_id}/image", dependencies=[Depends(require_token_or_query)])
    def sprite_job_image(job_id: str, anim: bool = False) -> FileResponse:
        try:
            path = studio.image(job_id, anim)
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
        strip = studio.image(body.job, anim=True)
        try:
            agents.set_sprite(agent_id, path.read_bytes(), strip.read_bytes() if strip else None)
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

    hook_order: dict[str, asyncio.Lock] = {}

    @app.post("/hooks/event", dependencies=[Depends(require_token)], status_code=204)
    async def hook_event(request: Request, session: str = Query(...), name: str = Query(...)) -> None:
        payload = await _json(request)
        # Um hook por vez em cada sessão, na ordem de chegada: o Stop espera a prévia numa
        # thread, e um hook que chegue nesse meio tempo não passa na frente dele.
        async with hook_order.setdefault(session, asyncio.Lock()):
            await record_hook_event(session, name, payload)

    async def record_hook_event(session: str, name: str, payload) -> None:
        if name == "Stop" and (live := manager.get(session)) is not None and live.kind in ("claude", "codex"):
            # A prévia (transcript e, no Codex, a busca do rollout) é lida uma vez, numa thread,
            # antes de registrar o hook: o loop não trava e os eventos saem na mesma ordem. A
            # Atividade, a automação e o gatilho usam a mesma, pela chave PREVIEW_KEY.
            base = payload if isinstance(payload, dict) else {}
            payload = {**base, PREVIEW_KEY: await asyncio.to_thread(last_agent_text, live, base)}
        manager.record_hook(session, name, payload if isinstance(payload, dict) else None)
        if name == "Stop":
            data = payload if isinstance(payload, dict) else None
            live = manager.get(session)
            waiter = engine.waiters.get(session)
            ours = engine.owns(session)
            # Passo de automação: sem saída combinada termina aqui (com a última mensagem); com
            # saída e sem ter chamado `saida`, a MÊTIS pede de novo.
            engine.on_stop(session, last_agent_text(live, data) if waiter is not None and not waiter.shape and live is not None else None)
            # v0.9.8: gatilho agente.terminou (nunca para as sessões das próprias automações: seria um laço).
            if live is not None and live.kind in ("claude", "codex") and not ours and engine.listens("agente.terminou"):
                engine.fire_event(
                    "agente.terminou",
                    {"sessao": live.id, "titulo": live.title, "cli": live.kind, "cwd": live.cwd, "previa": last_agent_text(live, data)},
                )

    # --- v0.9.8 parte 2: barra lateral, renomear terminal, refs e temas da tela ------------

    sidebar = barra_lateral.SidebarStore(settings.home)
    app_theme_store = app_themes.ThemeStore(settings.home)

    @app.get("/barra", dependencies=[Depends(require_token)])
    def sidebar_state() -> dict:
        return sidebar.state()

    @app.patch("/barra", dependencies=[Depends(require_token)])
    def sidebar_patch(body: dict) -> dict:
        """Uma ação por vez: fixar, nome (apelido da worktree) ou cor (do projeto)."""
        try:
            state = sidebar.patch(body)
        except barra_lateral.BarraError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        manager.events.publish({"type": "barra", "barra": state})
        return state

    @app.patch("/sessions/{session_id}", dependencies=[Depends(require_token)])
    def rename_session(session_id: str, body: dict) -> dict:
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        title = body.get("titulo")
        title = " ".join(title.split()) if isinstance(title, str) else ""
        if not 1 <= len(title) <= 80:
            raise HTTPException(status_code=400, detail="o título precisa ter de 1 a 80 caracteres")
        session.title = title
        manager.events.publish({"type": "session.renamed", "id": session_id, "title": title})
        return session.to_dict()

    @app.get("/projects/{project_id}/refs", dependencies=[Depends(require_token)])
    async def project_refs(project_id: str, q: str = "") -> dict:
        """Branches e commits para abrir uma worktree a partir deles."""
        try:
            return await gitops.list_refs(project_path(project_id), q)
        except gitops.GitError as exc:
            raise fail(exc) from exc

    def app_themes_changed() -> None:
        manager.events.publish({"type": "temas-app"})

    @app.get("/temas-app", dependencies=[Depends(require_token)])
    def list_app_themes() -> dict:
        return {"temas": app_theme_store.list()}

    @app.delete("/temas-app/{theme_id}", dependencies=[Depends(require_token)], status_code=204)
    def delete_app_theme(theme_id: str) -> None:
        if not app_theme_store.delete(theme_id):
            raise HTTPException(status_code=404, detail="tema não encontrado")
        app_themes_changed()

    @app.post("/temas-app/prompt", dependencies=[Depends(require_token)], status_code=201)
    async def app_theme_from_prompt(body: dict) -> dict:
        """Tema a partir de uma frase: o Claude (pelo plano, sem ferramentas) escolhe as cores e a MÊTIS confere o contraste."""

        def ask(prompt: str) -> dict:
            return ask_json(prompt, claude_env(), settings.home / "temas-prompt", model="sonnet", bare=True)

        try:
            theme = await asyncio.to_thread(app_themes.from_prompt, body.get("descricao"), ask)
        except app_themes.ThemeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (ClaudePrintError, app_themes.ThemeGenError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        saved = app_theme_store.save(theme)
        app_themes_changed()
        return saved

    @app.get("/temas-app/importar", dependencies=[Depends(require_token)])
    async def app_theme_sources() -> dict:
        """Temas do VS Code (e do Cursor) e do Obsidian que dá para trazer."""
        return {"fontes": await asyncio.to_thread(app_themes.list_sources)}

    @app.post("/temas-app/importar", dependencies=[Depends(require_token)], status_code=201)
    async def import_app_theme(body: dict) -> dict:
        try:
            theme = await asyncio.to_thread(app_themes.import_source, body.get("id"))
        except app_themes.SourceNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (app_themes.ThemeError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved = app_theme_store.save(theme)
        app_themes_changed()
        return saved

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
                    text = str(data.get("data", ""))
                    session.pty.write(text.encode("utf-8"))
                    manager.note_input(session.id, text)
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
