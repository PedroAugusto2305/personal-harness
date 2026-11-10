import type {
  ActivityItem,
  Approval,
  BoardProject,
  ConnectorAccount,
  ConnectorCatalog,
  AgentDraftSuggestion,
  Routine,
  RoutineDraft,
  StudySummary,
  RoutineRun,
  TodayData,
  BrainGraphData,
  BrainHit,
  BrainNote,
  AutoCatalog,
  AutoDetail,
  AutoFlow,
  AutoRun,
  AutoRunSummary,
  AutoSummary,
  BoardFile,
  BoardSummary,
  HistoryItem,
  PermissionMode,
  Prefs,
  ProjectScripts,
  Resources,
  SkillInfo,
  BrainPlace,
  CanvasDoc,
  ContextWindow,
  SessionGlance,
  SemanticStatus,
  SessionMap,
  Suggestion,
  KanbanTask,
  Stage,
  TaskState,
  Accounts,
  Account,
  Agent,
  AgentDraft,
  GitStatus,
  Project,
  Provider,
  Session,
  SessionKind,
  SpriteJob,
  TextFile,
  Usage,
  VoiceStatus,
  Worktree,
  GhosttyInfo,
  SavedCommand,
  TerminalTheme,
  VersionInfo,
  AppTheme,
  AppThemeSource,
  BrowserProfile,
  CookieSource,
  HistoryEntry,
  ImportedCookie,
  RefBranch,
  RefCommit,
  SidebarState,
  WorktreeMode,
  BackupCheck,
  MetisProfile,
  ProfilesState,
  StudyConcept,
  StudyMap,
  StudyPlan,
  StudySessionKind,
  CodeGraph,
  FailedCheck,
  SkillTarget,
  AutoProposal,
  AutoStrategy,
  AgentEvent,
  AgentPanelItem,
  ClickupBoard,
  ClickupList,
  ClickupTask,
  CliMcp,
  ConnectionTest,
  RegistryServer,
  ChangedFile,
  ConflictBlock,
  ConflictChoice,
  DiffMode,
  GitConfig,
  GitRefs,
  GithubIssue,
  GithubPr,
  GithubState,
  PullRequest,
  NoteText,
  NoteTitle,
  BarCommand,
  SessionContext,
  ThemeEntry,
 ConnectorTool, ToolMode, BoardTask, AutoQueueView, AutoItem, AutoSettings, VaultNode, ModelUsageReport } from "../types";

export interface CoreInfo {
  url: string;
  token: string;
  managed?: boolean;
}

export const inTauri = () => "__TAURI_INTERNALS__" in window;

/**
 * Onde está o núcleo. No app, o Tauri informa. No navegador (desenvolvimento), vale o
 * que vier no endereço (#url=…&token=…) ou nas variáveis VITE_*.
 */
export async function getCoreInfo(): Promise<CoreInfo> {
  if (inTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<CoreInfo>("core_info");
  }
  const hash = new URLSearchParams(window.location.hash.slice(1));
  return {
    url: hash.get("url") ?? import.meta.env.VITE_HARNESS_URL ?? "http://127.0.0.1:47830",
    token: hash.get("token") ?? import.meta.env.VITE_HARNESS_TOKEN ?? "",
  };
}

/** Reinicia o núcleo (versão nova do código): fecha os terminais e sobe outro. Só na janela do app. */
/** v0.9.8: troca de perfil. O núcleo já gravou o perfil novo; o app desliga este e sobe o outro. */
export async function switchProfile(): Promise<boolean> {
  if (!inTauri()) return false;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("profile_switch");
  return true;
}

export async function restartCore(): Promise<boolean> {
  if (!inTauri()) return false;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("core_restart");
  return true;
}

/** Número no ícone do Dock (avisos não lidos); 0 tira. Só na janela do app. */
export async function setDockBadge(count: number): Promise<void> {
  if (!inTauri()) return;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().setBadgeCount(count > 0 ? count : undefined);
  } catch {
    // sem permissão ou fora do macOS: o sino da janela basta
  }
}

/** v0.9.9: aviso nativo do macOS, com o ícone da MÊTIS. */
export interface NativeNotice {
  titulo: string;
  texto: string;
  subtitulo?: string;
  som: boolean;
  /** Para onde o clique leva: "sessao:<id>", "aprovacao:<id>", "automacao:<id>" ou "". */
  alvo: string;
  /** Avisos do mesmo grupo (a mesma sessão) ficam juntos na Central. */
  grupo?: string;
}

/** Manda pela Central de Notificações. Devolve o motivo quando não deu (fora do app, sem permissão). */
export async function nativeNotify(aviso: NativeNotice): Promise<string | null> {
  if (!inTauri()) return "fora do app";
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("notify_native", { aviso });
    return null;
  } catch (cause) {
    return cause instanceof Error ? cause.message : String(cause);
  }
}

/** "ativo", "negado", "pendente" ou "fora do app". */
export async function nativeNotifyStatus(): Promise<string> {
  if (!inTauri()) return "fora do app";
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<string>("notify_status");
  } catch {
    return "fora do app";
  }
}

/** O executável do app num .app ("" no desenvolvimento): o núcleo avisa por ele com a janela fechada. */
export async function appExecutable(): Promise<string> {
  if (!inTauri()) return "";
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<string>("app_exe");
  } catch {
    return "";
  }
}

/** O alvo do clique que abriu o app (e esquece): a janela ainda não ouvia quando ele chegou. */
export async function takePendingNotice(): Promise<string | null> {
  if (!inTauri()) return null;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return (await invoke<string | null>("notify_pending")) ?? null;
  } catch {
    return null;
  }
}

/** Clique num aviso nativo: o alvo que ele levava. */
export async function onNativeNoticeClick(handler: (target: string) => void): Promise<() => void> {
  if (!inTauri()) return () => undefined;
  const { listen } = await import("@tauri-apps/api/event");
  return listen<string>("metis-aviso", (event) => handler(event.payload));
}

export class CoreError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export interface NewSessionOptions {
  account?: string;
  title?: string;
  tag?: string;
  agent?: string;
  cols?: number;
  rows?: number;
  /** Agente ainda não salvo ("testar antes de salvar"). */
  draft?: { name: string; cli: "claude" | "codex"; model: string; folder: string; prompt: string };
  /** Retomar uma conversa do histórico (`claude --resume <id>`, `codex resume <id>`). */
  resume?: string;
  /** Modo de permissão só desta sessão; sem ele vale o dos Ajustes. */
  permissao?: PermissionMode;
  /** v0.9.9: o pedido que já entra no agente, e modelo e esforço só desta sessão. */
  prompt?: string;
  model?: string;
  effort?: "low" | "medium" | "high" | "xhigh";
}

export class CoreClient {
  constructor(readonly info: CoreInfo) {}

  wsUrl(path: string): string {
    const base = this.info.url.replace(/^http/, "ws");
    const glue = path.includes("?") ? "&" : "?";
    return `${base}${path}${glue}token=${encodeURIComponent(this.info.token)}`;
  }

  async waitUntilHealthy(timeoutMs = 30000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const response = await fetch(`${this.info.url}/health`);
        if (response.ok) return;
      } catch {
        // núcleo ainda subindo
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    throw new CoreError("o núcleo não respondeu", 0);
  }

  private async send<T>(method: string, path: string, body?: BodyInit, type = "application/json"): Promise<T> {
    const response = await fetch(`${this.info.url}${path}`, {
      method,
      headers: { "Content-Type": type, "X-Harness-Token": this.info.token },
      body,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const data = await response.json();
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? detail);
      } catch {
        // resposta sem JSON
      }
      throw new CoreError(String(detail), response.status);
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  private request<T>(method: string, path: string, body?: unknown): Promise<T> {
    return this.send(method, path, body === undefined ? undefined : JSON.stringify(body));
  }

  // --- sessões

  listSessions(): Promise<Session[]> {
    return this.request("GET", "/sessions");
  }

  createSession(kind: SessionKind, cwd: string, options: NewSessionOptions = {}): Promise<Session> {
    const { cols = 120, rows = 32, ...rest } = options;
    return this.request("POST", "/sessions", { kind, cwd, cols, rows, ...rest });
  }

  closeSession(id: string): Promise<void> {
    return this.request("DELETE", `/sessions/${id}`);
  }

  // --- contas e uso

  accounts(): Promise<Accounts> {
    return this.request("GET", "/accounts");
  }

  addAccount(provider: Provider, name: string): Promise<Account> {
    return this.request("POST", `/accounts/${provider}`, { name });
  }

  activateAccount(provider: Provider, id: string): Promise<Account> {
    return this.request("POST", `/accounts/${provider}/${encodeURIComponent(id)}/activate`);
  }

  refreshUsage(): Promise<Usage> {
    return this.request("POST", "/usage/refresh");
  }

  // --- voz e anexos

  voiceStatus(): Promise<VoiceStatus> {
    return this.request("GET", "/voice");
  }

  prepareVoice(): Promise<VoiceStatus> {
    return this.request("POST", "/voice/prepare");
  }

  async transcribe(wav: Blob, language = "pt"): Promise<string> {
    const answer = await this.send<{ text: string }>("POST", `/voice/transcribe?language=${language}`, wav, "audio/wav");
    return answer.text;
  }

  // --- projetos e worktrees

  projects(): Promise<Project[]> {
    return this.request("GET", "/projects");
  }

  addProject(path: string): Promise<Project> {
    return this.request("POST", "/projects", { path });
  }

  /** v0.9.9: repositórios no Mac que ainda não são projetos, e onde clonar ou criar. */
  projectSuggestions(): Promise<{ repositorios: { path: string; name: string; atualizado: number }[]; pasta_padrao: string }> {
    return this.request("GET", "/projects/sugestoes");
  }

  cloneProject(url: string, pasta = ""): Promise<Project> {
    return this.request("POST", "/projects/clone", { url, pasta });
  }

  createProject(nome: string, pasta = ""): Promise<Project> {
    return this.request("POST", "/projects/criar", { nome, pasta });
  }

  removeProject(id: string): Promise<void> {
    return this.request("DELETE", `/projects/${encodeURIComponent(id)}`);
  }

  worktrees(projectId: string): Promise<Worktree[]> {
    return this.request("GET", `/projects/${encodeURIComponent(projectId)}/worktrees`);
  }

  /** `setup`: id do terminal onde o script de setup do projeto roda (v0.9.2); `setup_erro` se ele não abriu. */
  createWorktree(
    projectId: string,
    name: string,
    copyEnv: boolean,
    base?: string,
    modo: WorktreeMode = "nova",
  ): Promise<{ path: string; branch: string; copied: string[]; setup?: string; setup_erro?: string }> {
    return this.request("POST", `/projects/${encodeURIComponent(projectId)}/worktrees`, { name, copy_env: copyEnv, base: base || null, modo });
  }

  /** Branches e commits para criar a worktree a partir deles (v0.9.8). */
  refs(projectId: string, q = ""): Promise<{ branches: RefBranch[]; commits: RefCommit[] }> {
    return this.request("GET", `/projects/${encodeURIComponent(projectId)}/refs?q=${encodeURIComponent(q)}`);
  }

  deleteWorktree(projectId: string, path: string, force = false): Promise<{ branch_deleted: boolean; branch_kept: string | null; branch: string | null }> {
    const query = new URLSearchParams({ path, force: String(force) });
    return this.request("DELETE", `/projects/${encodeURIComponent(projectId)}/worktrees?${query}`);
  }

  // --- git da revisão

  gitStatus(path: string): Promise<GitStatus> {
    return this.request("GET", `/git/status?${new URLSearchParams({ path })}`);
  }

  async gitDiff(path: string, file: string, mode: DiffMode, untracked: boolean, ref = ""): Promise<string> {
    const query = new URLSearchParams({ path, file, mode, untracked: String(untracked), ...(mode === "ref" ? { ref } : {}) });
    const response = await fetch(`${this.info.url}/git/diff?${query}`, { headers: { "X-Harness-Token": this.info.token } });
    if (!response.ok) throw new CoreError((await response.json().catch(() => ({}))).detail ?? response.statusText, response.status);
    return response.text();
  }

  stage(path: string, files: string[]): Promise<unknown> {
    return this.request("POST", "/git/stage", { path, files });
  }

  unstage(path: string, files: string[]): Promise<unknown> {
    return this.request("POST", "/git/unstage", { path, files });
  }

  commit(path: string, message: string, amend = false): Promise<unknown> {
    return this.request("POST", "/git/commit", { path, message, amend });
  }

  push(path: string, force = false): Promise<unknown> {
    return this.request("POST", "/git/push", { path, force });
  }

  // --- git e GitHub (v0.9.6)

  gitRefs(path: string): Promise<GitRefs> {
    return this.request("GET", `/git/refs?${new URLSearchParams({ path })}`);
  }

  gitChanged(path: string, ref: string): Promise<{ ref: string; base: string; files: ChangedFile[] }> {
    return this.request("GET", `/git/changed?${new URLSearchParams({ path, ref })}`);
  }

  /** Aplica um patch: no índice (cached) para marcar e desmarcar trechos; na árvore (reverse) para descartar. */
  gitApply(path: string, patch: string, cached: boolean, reverse: boolean): Promise<unknown> {
    return this.request("POST", "/git/apply", { path, patch, cached, reverse });
  }

  gitDiscard(path: string, files: string[]): Promise<{ ok: boolean; lixeira: string[] }> {
    return this.request("POST", "/git/discard", { path, files });
  }

  gitFetch(path: string): Promise<unknown> {
    return this.request("POST", "/git/fetch", { path });
  }

  gitSync(path: string): Promise<{ feito: "push" | "pull" | "sync" | "nada"; saida: string }> {
    return this.request("POST", "/git/sync", { path });
  }

  gitOperation(path: string, acao: "abortar" | "continuar"): Promise<unknown> {
    return this.request("POST", "/git/operacao", { path, acao });
  }

  gitConflict(path: string, file: string): Promise<{ blocos: ConflictBlock[]; texto: string }> {
    return this.request("GET", `/git/conflito?${new URLSearchParams({ path, file })}`);
  }

  resolveConflict(path: string, file: string, escolhas: ConflictChoice[]): Promise<{ resolvido: boolean }> {
    return this.request("POST", "/git/conflito", { path, file, escolhas });
  }

  resolveConflictSide(path: string, file: string, lado: "nosso" | "deles"): Promise<{ resolvido: boolean }> {
    return this.request("POST", "/git/conflito", { path, file, lado });
  }

  /** O arquivo como estava numa ref (para o diff de imagem), com o token no endereço. */
  gitBlobUrl(path: string, file: string, ref = "HEAD"): string {
    return `${this.info.url}/git/blob?${new URLSearchParams({ path, file, ref, token: this.info.token })}`;
  }

  gitConfig(): Promise<GitConfig> {
    return this.request("GET", "/git/config");
  }

  saveGitConfig(assinar: boolean): Promise<GitConfig> {
    return this.request("PUT", "/git/config", { assinar });
  }

  github(path: string): Promise<GithubState> {
    return this.request("GET", `/github/estado?${new URLSearchParams({ path })}`);
  }

  createPr(path: string, titulo: string, corpo: string, base: string, rascunho: boolean): Promise<PullRequest> {
    return this.request("POST", "/github/pr", { path, titulo, corpo, base, rascunho });
  }

  mergePr(path: string, numero: number, metodo: "rebase" | "squash" | "merge"): Promise<PullRequest | { ok: boolean }> {
    return this.request("POST", "/github/pr/juntar", { path, numero, metodo });
  }

  readyPr(path: string, numero: number): Promise<PullRequest | { ok: boolean }> {
    return this.request("POST", "/github/pr/pronto", { path, numero });
  }

  githubItems(path: string): Promise<{ gh?: boolean; issues: GithubIssue[]; prs: GithubPr[] }> {
    return this.request("GET", `/github/itens?${new URLSearchParams({ path })}`);
  }

  editors(): Promise<{ id: string; nome: string }[]> {
    return this.request("GET", "/sistema/editores");
  }

  openIn(editor: string, path: string): Promise<unknown> {
    return this.request("POST", "/sistema/abrir-em", { editor, path });
  }

  pull(path: string): Promise<unknown> {
    return this.request("POST", "/git/pull", { path });
  }

  // --- arquivos

  files(root: string): Promise<{ root: string; files: string[] }> {
    return this.request("GET", `/fs/files?${new URLSearchParams({ root })}`);
  }

  /** Grava o arquivo só se ele ainda tem o hash de quando foi aberto (409 se mudou no disco). */
  writeText(root: string, path: string, text: string, hash: string): Promise<{ hash: string; mtime: number; size: number }> {
    return this.request("PUT", "/fs/text", { root, path, text, hash });
  }

  brainNoteText(path: string): Promise<NoteText> {
    return this.request("GET", `/brain/note/texto?${new URLSearchParams({ path })}`);
  }

  /** Grava a nota inteira (com o frontmatter) só se ninguém a mudou desde que abriu (409: o Obsidian salvou). */
  saveBrainNote(path: string, texto: string, hash: string): Promise<{ hash: string; alterado: number }> {
    return this.request("PUT", "/brain/note/texto", { path, texto, hash });
  }

  brainTitles(q: string, limite = 20): Promise<NoteTitle[]> {
    return this.request("GET", `/brain/titulos?${new URLSearchParams({ q, limite: String(limite) })}`);
  }

  readText(root: string, path: string): Promise<TextFile> {
    return this.request("GET", `/fs/text?${new URLSearchParams({ root, path })}`);
  }

  /** Para <img>, <iframe>, <audio> e <video>, que não mandam cabeçalho. */
  rawUrl(root: string, path: string): string {
    return `${this.info.url}/fs/raw?${new URLSearchParams({ root, path, token: this.info.token })}`;
  }

  open(target: { url?: string; reveal?: string }): Promise<void> {
    return this.request("POST", "/open", target);
  }

  // --- agentes

  agents(): Promise<Agent[]> {
    return this.request("GET", "/agents");
  }

  createAgent(draft: AgentDraft): Promise<Agent> {
    return this.request("POST", "/agents", draft);
  }

  updateAgent(id: string, draft: AgentDraft): Promise<Agent> {
    return this.request("PUT", `/agents/${encodeURIComponent(id)}`, draft);
  }

  deleteAgent(id: string): Promise<void> {
    return this.request("DELETE", `/agents/${encodeURIComponent(id)}`);
  }

  setSprite(id: string, png: Blob): Promise<void> {
    return this.send("POST", `/agents/${encodeURIComponent(id)}/sprite`, png, "image/png");
  }

  clearSprite(id: string): Promise<void> {
    return this.request("DELETE", `/agents/${encodeURIComponent(id)}/sprite`);
  }

  /** A sprite parada; com `anim`, a tira do movimento parado (quadros lado a lado). */
  spriteUrl(id: string, version: number, anim = false): string {
    const query = new URLSearchParams({ token: this.info.token, v: String(version), ...(anim ? { anim: "1" } : {}) });
    return `${this.info.url}/agents/${encodeURIComponent(id)}/sprite?${query}`;
  }

  // --- sprites por prompt

  startSprite(request: { prompt: string; name: string; description: string; color: string; base?: string | null }): Promise<SpriteJob> {
    return this.request("POST", "/sprites/jobs", request);
  }

  spriteJob(id: string): Promise<SpriteJob> {
    return this.request("GET", `/sprites/jobs/${encodeURIComponent(id)}`);
  }

  /** v0.9.9: a imagem modelo que toda sprite segue. */
  spriteModelUrl(): string {
    return `${this.info.url}/sprites/modelo?${new URLSearchParams({ token: this.info.token })}`;
  }

  spriteJobUrl(id: string, anim = false): string {
    return `${this.info.url}/sprites/jobs/${encodeURIComponent(id)}/image?${new URLSearchParams({ token: this.info.token, ...(anim ? { anim: "1" } : {}) })}`;
  }

  useSpriteJob(agentId: string, job: string): Promise<void> {
    return this.request("POST", `/agents/${encodeURIComponent(agentId)}/sprite/from-job`, { job });
  }

  importMaestri(): Promise<{ imported: string[] }> {
    return this.request("POST", "/agents/import/maestri");
  }

  // --- Brain e kanban ---------------------------------------------------------

  brainSearch(q: string, options: { tipo?: string[]; projeto?: string; limit?: number } = {}): Promise<BrainHit[]> {
    const query = new URLSearchParams({ q, tipo: (options.tipo ?? []).join(","), projeto: options.projeto ?? "", limit: String(options.limit ?? 40) });
    return this.request("GET", `/brain/search?${query}`);
  }

  brainNote(target: { path?: string; title?: string }): Promise<BrainNote> {
    return this.request("GET", `/brain/note?${new URLSearchParams({ path: target.path ?? "", title: target.title ?? "" })}`);
  }

  brainStatus(): Promise<{ vault: string; available: boolean; total: number; types: Record<string, number> }> {
    return this.request("GET", "/brain/status");
  }

  openInObsidian(path: string): Promise<void> {
    return this.request("POST", "/brain/obsidian", { path });
  }

  brainGraph(): Promise<BrainGraphData> {
    return this.request("GET", "/brain/graph");
  }

  brainKnown(titles: string[]): Promise<string[]> {
    return this.request("POST", "/brain/known", { titles });
  }

  // --- Sessões, agentes e sistema (v0.9.2) ---------------------------------------------

  prefs(): Promise<Prefs> {
    return this.request("GET", "/ajustes");
  }

  /** Muda só as chaves dadas (avisos é mesclado). */
  savePrefs(changes: Partial<Prefs> | { avisos: Partial<Prefs["avisos"]> }): Promise<Prefs> {
    return this.request("PUT", "/ajustes", changes);
  }

  /** Conversas do Claude e do Codex no disco, mais novas primeiro (todas as contas). */
  history(q = "", cwd = "", limit = 80): Promise<HistoryItem[]> {
    return this.request("GET", `/historico?${new URLSearchParams({ q, cwd, limit: String(limit) })}`);
  }

  /** Reinicia o agente na mesma pasta e conta; `continuar` retoma a conversa (409 se não achar). */
  restartSession(id: string, continuar: boolean): Promise<Session> {
    return this.request("POST", `/sessions/${encodeURIComponent(id)}/reiniciar`, { continuar });
  }

  /** Passa o trabalho para a outra CLI (Claude ↔ Codex) com o transcript e as últimas mensagens. */
  handOff(id: string, para?: "claude" | "codex", nota = ""): Promise<Session> {
    return this.request("POST", `/sessions/${encodeURIComponent(id)}/passar`, { para: para ?? null, nota });
  }

  resources(): Promise<Resources> {
    return this.request("GET", "/recursos");
  }

  skills(cwd = ""): Promise<SkillInfo[]> {
    return this.request("GET", `/skills?${new URLSearchParams({ cwd })}`);
  }

  projectScripts(projectId: string): Promise<ProjectScripts> {
    return this.request("GET", `/projects/${encodeURIComponent(projectId)}/scripts`);
  }

  setProjectScripts(projectId: string, scripts: Partial<ProjectScripts>): Promise<ProjectScripts> {
    return this.request("PUT", `/projects/${encodeURIComponent(projectId)}/scripts`, scripts);
  }

  /** Aviso do macOS pela mão do núcleo (para quando a janela está aberta mas sem foco). */
  notifyMac(titulo: string, texto = ""): Promise<void> {
    return this.request("POST", "/avisos/mac", { titulo, texto });
  }

  /** v0.9.9: tokens e custo equivalente em API por modelo, dia e projeto (1 a 90 dias). */
  modelUsage(dias: number): Promise<ModelUsageReport> {
    return this.request("GET", `/uso/modelos?dias=${dias}`);
  }

  /** v0.9.9: o executável do app, para o núcleo avisar com o ícone da MÊTIS com a janela fechada. */
  setNotifier(exe: string): Promise<void> {
    return this.request("PUT", "/avisos/app", { exe });
  }

  /** Desliga o núcleo de vez (fecha os terminais). A janela não faz isso sozinha ao fechar. */
  shutdown(): Promise<{ fechando: number }> {
    return this.request("POST", "/desligar");
  }

  // --- Quadros (v0.9.1) -------------------------------------------------------------

  boards(): Promise<BoardSummary[]> {
    return this.request("GET", "/quadros");
  }

  createBoard(projeto: string, nome: string): Promise<BoardSummary> {
    return this.request("POST", "/quadros", { projeto, nome });
  }

  board(path: string): Promise<BoardFile> {
    return this.request("GET", `/quadros/abrir?${new URLSearchParams({ path })}`);
  }

  /** Salva o .canvas. `base` = o `alterado` que a tela conhece: 409 se o Obsidian salvou depois. */
  saveBoard(path: string, canvas: CanvasDoc, base: number): Promise<{ alterado: number; notas: BoardFile["notas"] }> {
    return this.request("PUT", "/quadros/salvar", { path, canvas, base });
  }

  /** Liga uma nota do Brain a uma sessão: a sessão recebe o pedido de ler a nota (vira contexto). */
  linkNoteToSession(sessao: string, nota: string): Promise<{ mensagem: string }> {
    return this.request("POST", "/quadros/ligar", { sessao, nota });
  }

  sessionGlance(sessionId: string): Promise<SessionGlance> {
    return this.request("GET", `/sessions/${encodeURIComponent(sessionId)}/resumo`);
  }

  /** Manda uma mensagem para a sessão (colagem + Enter no terminal dela). */
  sendToSession(sessionId: string, texto: string): Promise<void> {
    return this.request("POST", `/sessions/${encodeURIComponent(sessionId)}/mensagem`, { texto });
  }

  // --- Automações (v0.9.0) ---------------------------------------------------------

  automations(): Promise<AutoSummary[]> {
    return this.request("GET", "/automacoes");
  }

  automation(id: string): Promise<AutoDetail> {
    return this.request("GET", `/automacoes/${encodeURIComponent(id)}`);
  }

  automationCatalog(): Promise<AutoCatalog> {
    return this.request("GET", "/automacoes/catalogo");
  }

  createAutomation(nome: string, desenho?: AutoFlow): Promise<AutoSummary> {
    return this.request("POST", "/automacoes", { nome, desenho: desenho ?? null });
  }

  /** v0.9.8: o Claude monta (ou ajusta) a automação a partir de uma frase; nada é salvo. */
  proposeAutomation(descricao: string, atual?: AutoFlow): Promise<AutoProposal> {
    return this.request("POST", "/automacoes/proposta", { descricao, atual: atual ?? null });
  }

  writeCode(descricao: string, linguagem: "python" | "javascript", entrada_exemplo?: unknown): Promise<{ codigo: string }> {
    return this.request("POST", "/automacoes/codigo/escrever", { descricao, linguagem, entrada_exemplo: entrada_exemplo ?? null });
  }

  importN8n(body: { fluxo: unknown } | { conta: string; workflow_id: string }): Promise<AutoProposal> {
    return this.request("POST", "/automacoes/importar-n8n", body);
  }

  n8nFlows(conta: string): Promise<{ fluxos: { id: string; nome: string; ativo: boolean }[] }> {
    return this.request("GET", `/automacoes/n8n/fluxos?conta=${encodeURIComponent(conta)}`);
  }

  strategies(): Promise<{ estrategias: AutoStrategy[] }> {
    return this.request("GET", "/automacoes/estrategias");
  }

  createFromStrategy(id: string, parametros: Record<string, string | number>): Promise<{ id: string }> {
    return this.request("POST", `/automacoes/estrategias/${encodeURIComponent(id)}`, { parametros });
  }

  saveAutomation(id: string, desenho: AutoFlow): Promise<AutoSummary> {
    return this.request("PUT", `/automacoes/${encodeURIComponent(id)}`, { desenho });
  }

  archiveAutomation(id: string): Promise<void> {
    return this.request("DELETE", `/automacoes/${encodeURIComponent(id)}`);
  }

  /** Publica o rascunho, ou uma versão antiga (hash do commit) de novo. */
  publishAutomation(id: string, versao = ""): Promise<AutoSummary> {
    return this.request("POST", `/automacoes/${encodeURIComponent(id)}/publicar`, { versao });
  }

  setAutomationActive(id: string, ativa: boolean): Promise<AutoSummary> {
    return this.request("PUT", `/automacoes/${encodeURIComponent(id)}/ativa`, { ativa });
  }

  /** Testa o rascunho com ensaio: inteiro, a partir de um passo (desde) ou só um passo (passo). */
  testAutomation(id: string, options: { desde?: string; passo?: string; execucao?: number } = {}): Promise<{ execucao: number }> {
    return this.request("POST", `/automacoes/${encodeURIComponent(id)}/testar`, { desde: options.desde ?? "", passo: options.passo ?? "", execucao: options.execucao ?? 0 });
  }

  /** Roda a publicada agora, de verdade. */
  runAutomation(id: string): Promise<{ execucao: number }> {
    return this.request("POST", `/automacoes/${encodeURIComponent(id)}/rodar`);
  }

  automationRuns(id: string, limit = 50): Promise<AutoRunSummary[]> {
    return this.request("GET", `/automacoes/${encodeURIComponent(id)}/execucoes?limit=${limit}`);
  }

  automationRun(runId: number): Promise<AutoRun> {
    return this.request("GET", `/execucoes/${runId}`);
  }

  rerunFrom(runId: number, desde: string): Promise<{ execucao: number }> {
    return this.request("POST", `/execucoes/${runId}/reexecutar`, { desde });
  }

  stopRun(runId: number): Promise<void> {
    return this.request("POST", `/execucoes/${runId}/parar`);
  }

  /** Abre um Claude com o rascunho e o log do erro; a correção vai só para o rascunho. */
  askFix(runId: number): Promise<{ session: string; title: string }> {
    return this.request("POST", `/execucoes/${runId}/conserto`);
  }

  // --- Brain vivo (v0.8) ---------------------------------------------------------

  brainSemantic(): Promise<SemanticStatus> {
    return this.request("GET", "/brain/semantica");
  }

  brainSemanticDownload(): Promise<SemanticStatus["model"]> {
    return this.request("POST", "/brain/semantica/baixar");
  }

  suggestions(options: { project?: string; status?: string; note?: string } = {}): Promise<Suggestion[]> {
    const query = new URLSearchParams({ project: options.project ?? "", status: options.status ?? "pendente", nota: options.note ?? "" });
    return this.request("GET", `/brain/sugestoes?${query}`);
  }

  acceptSuggestion(id: number, titulo: string, resumo: string): Promise<Suggestion & { output: string }> {
    return this.request("POST", `/brain/sugestoes/${id}/aceitar`, { titulo, resumo });
  }

  rejectSuggestion(id: number): Promise<Suggestion> {
    return this.request("POST", `/brain/sugestoes/${id}/recusar`);
  }

  scanSuggestions(): Promise<SemanticStatus["suggestions"]["last_scan"] & { skipped?: string; baseline?: number }> {
    return this.request("POST", "/brain/sugestoes/varrer");
  }

  sessionMap(sessionId: string): Promise<SessionMap> {
    return this.request("GET", `/brain/sessao/${encodeURIComponent(sessionId)}`);
  }

  contextWindow(sessionId: string): Promise<ContextWindow> {
    return this.request("GET", `/sessions/${encodeURIComponent(sessionId)}/contexto`);
  }

  brainPlace(cwd: string): Promise<BrainPlace> {
    return this.request("GET", `/brain/place?${new URLSearchParams({ cwd })}`);
  }

  boardProjects(): Promise<BoardProject[]> {
    return this.request("GET", "/brain/projects");
  }

  setStage(project: string, stage: Stage): Promise<BoardProject> {
    return this.request("PUT", `/brain/projects/${encodeURIComponent(project)}/stage`, { stage });
  }

  tasks(project: string): Promise<KanbanTask[]> {
    return this.request("GET", `/brain/projects/${encodeURIComponent(project)}/tasks`);
  }

  addTask(project: string, text: string, state: TaskState = "pendente"): Promise<KanbanTask> {
    return this.request("POST", `/brain/projects/${encodeURIComponent(project)}/tasks`, { text, state });
  }

  /** v0.9.8: rótulos e subtarefas (caminhos conferidos com o núcleo). */
  setTaskLabels(project: string, id: string, rotulos: string[]): Promise<KanbanTask> {
    return this.request("PUT", `/brain/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(id)}/rotulos`, { rotulos });
  }

  addSubtask(project: string, id: string, texto: string): Promise<KanbanTask> {
    return this.request("POST", `/brain/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(id)}/subtarefas`, { texto });
  }

  setSubtask(project: string, id: string, indice: number, feita: boolean): Promise<KanbanTask> {
    return this.request("PUT", `/brain/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(id)}/subtarefas/${indice}`, { feita });
  }

  moveTask(project: string, id: string, state: TaskState): Promise<KanbanTask> {
    return this.request("PUT", `/brain/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(id)}`, { state });
  }

  // --- conectores, lembretes, aprovações ---------------------------------------

  connectors(): Promise<{ catalog: ConnectorCatalog; accounts: ConnectorAccount[] }> {
    return this.request("GET", "/conectores");
  }

  connectSlack(name: string, token: string, email: string): Promise<ConnectorAccount> {
    return this.request("POST", "/conectores/slack", { name, token, email });
  }

  async slackManifest(): Promise<string> {
    const response = await fetch(`${this.info.url}/conectores/slack/manifesto`, { headers: { "X-Harness-Token": this.info.token } });
    return response.text();
  }

  startOAuth(kind: string, name: string): Promise<{ url: string }> {
    return this.request("POST", `/conectores/oauth/${encodeURIComponent(kind)}`, { name });
  }

  /** v0.9.9: as pastas e notas do vault. */
  brainTree(): Promise<VaultNode[]> {
    return this.request("GET", "/brain/arvore");
  }

  /** v0.9.9: as tarefas de todos os projetos do Brain. */
  allTasks(): Promise<BoardTask[]> {
    return this.request("GET", "/kanban/tarefas");
  }

  /** v0.9.9: a fila da coluna Auto. */
  autoQueue(): Promise<AutoQueueView> {
    return this.request("GET", "/kanban/auto");
  }

  autoEnqueue(projeto: string, tarefa: string, settings: AutoSettings): Promise<AutoItem> {
    return this.request("POST", "/kanban/auto", { projeto, tarefa, ...settings });
  }

  autoCancel(id: string): Promise<AutoItem> {
    return this.request("DELETE", `/kanban/auto/${encodeURIComponent(id)}`);
  }

  autoClear(): Promise<void> {
    return this.request("DELETE", "/kanban/auto");
  }

  autoLimit(limite: number): Promise<AutoQueueView> {
    return this.request("PUT", "/kanban/auto/limite", { limite });
  }

  /** v0.9.9: as ferramentas de uma conta, com o modo de cada uma. */
  connectorTools(id: string): Promise<{ ferramentas: ConnectorTool[] }> {
    return this.request("GET", `/conectores/${encodeURIComponent(id)}/ferramentas`);
  }

  patchConnector(
    id: string,
    changes: { name?: string; approve_writes?: boolean; reminders?: boolean; tool_modes?: Record<string, ToolMode | "padrao"> },
  ): Promise<ConnectorAccount> {
    return this.request("PATCH", `/conectores/${encodeURIComponent(id)}`, changes);
  }

  deleteConnector(id: string): Promise<void> {
    return this.request("DELETE", `/conectores/${encodeURIComponent(id)}`);
  }

  testConnector(id: string): Promise<{ message: string }> {
    return this.request("POST", `/conectores/${encodeURIComponent(id)}/teste`);
  }

  remind(texto: string, quando: string, conta = ""): Promise<{ message: string }> {
    return this.request("POST", "/lembretes", { texto, quando, conta });
  }

  activity(limit = 150): Promise<ActivityItem[]> {
    return this.request("GET", `/atividade?limit=${limit}`);
  }

  approvals(): Promise<Approval[]> {
    return this.request("GET", "/aprovacoes");
  }

  decide(id: string, aprovar: boolean): Promise<void> {
    return this.request("POST", `/aprovacoes/${encodeURIComponent(id)}`, { aprovar });
  }

  // --- captura, estudo e agente por descrição ----------------------------------------

  capture(texto: string): Promise<{ acao: string; mensagem: string }> {
    return this.request("POST", "/captura", { texto });
  }

  study(): Promise<StudySummary> {
    return this.request("GET", "/estudo");
  }

  // v0.9.8: Estudo completo
  studyMap(): Promise<StudyMap> {
    return this.request("GET", "/estudo/mapa");
  }

  studyPlan(): Promise<StudyPlan> {
    return this.request("GET", "/estudo/plano");
  }

  addConcept(nome: string, relacionados: string[] = [], resumo = ""): Promise<StudyConcept> {
    return this.request("POST", "/estudo/conceitos", { nome, relacionados, resumo: resumo || null });
  }

  patchConcept(titulo: string, changes: { dominio?: number; semana?: string | number | null }): Promise<StudyConcept> {
    return this.request("PATCH", "/estudo/conceitos", { titulo, ...changes });
  }

  studySession(tipo: StudySessionKind, conceito?: string): Promise<Session> {
    return this.request("POST", "/estudo/sessao", { tipo, conceito: conceito ?? null });
  }

  // v0.9.8: perfis e backup
  profiles(): Promise<ProfilesState> {
    return this.request("GET", "/perfis");
  }

  createProfile(nome: string, copiar: boolean, vault?: string): Promise<MetisProfile> {
    return this.request("POST", "/perfis", { nome, copiar, vault: vault || null });
  }

  patchProfile(id: string, changes: { nome?: string; vault?: string | null }): Promise<MetisProfile> {
    return this.request("PATCH", `/perfis/${encodeURIComponent(id)}`, changes);
  }

  deleteProfile(id: string): Promise<void> {
    return this.request("DELETE", `/perfis/${encodeURIComponent(id)}`);
  }

  activateProfile(id: string): Promise<{ id: string; pasta: string; porta: number; vault: string | null }> {
    return this.request("POST", `/perfis/${encodeURIComponent(id)}/ativar`);
  }

  backupContents(): Promise<{ itens: { caminho: string; tamanho: number; tipo: string }[]; fora: string[] }> {
    return this.request("GET", "/backup");
  }

  exportBackup(): Promise<{ arquivo: string; tamanho: number }> {
    return this.request("POST", "/backup/exportar", {});
  }

  checkBackup(arquivo: string): Promise<BackupCheck> {
    return this.request("POST", "/backup/conferir", { arquivo });
  }

  importBackup(arquivo: string): Promise<{ restaurados: string[]; backup_anterior: string; reiniciar: boolean }> {
    return this.request("POST", "/backup/importar", { arquivo });
  }

  studyBlock(minutos: number, assunto: string): Promise<{ line: string; note: string }> {
    return this.request("POST", "/estudo/blocos", { minutos, assunto });
  }

  draftAgent(descricao: string): Promise<AgentDraftSuggestion> {
    return this.request("POST", "/agents/rascunho", { descricao });
  }

  // --- rotinas e Hoje ------------------------------------------------------------

  routines(): Promise<{ routines: Routine[]; runs: RoutineRun[] }> {
    return this.request("GET", "/rotinas");
  }

  saveRoutine(draft: RoutineDraft, id?: string): Promise<Routine> {
    return id ? this.request("PUT", `/rotinas/${encodeURIComponent(id)}`, draft) : this.request("POST", "/rotinas", draft);
  }

  deleteRoutine(id: string): Promise<void> {
    return this.request("DELETE", `/rotinas/${encodeURIComponent(id)}`);
  }

  runRoutine(id: string): Promise<RoutineRun> {
    return this.request("POST", `/rotinas/${encodeURIComponent(id)}/rodar`);
  }

  today(): Promise<TodayData> {
    return this.request("GET", "/hoje");
  }

  // --- terminal e navegação (v0.9.3) ------------------------------------------------

  async commands(): Promise<SavedCommand[]> {
    return (await this.request<{ comandos: SavedCommand[] }>("GET", "/comandos")).comandos;
  }

  saveCommand(item: Omit<SavedCommand, "id">, id?: string): Promise<SavedCommand> {
    return id ? this.request("PUT", `/comandos/${encodeURIComponent(id)}`, item) : this.request("POST", "/comandos", item);
  }

  deleteCommand(id: string): Promise<void> {
    return this.request("DELETE", `/comandos/${encodeURIComponent(id)}`);
  }

  /** Só os atalhos mudados (o resto é o padrão da tela), e o arquivo onde ficam. */
  keymap(): Promise<{ atalhos: Record<string, string>; arquivo: string }> {
    return this.request("GET", "/atalhos");
  }

  saveKeymap(atalhos: Record<string, string>): Promise<{ atalhos: Record<string, string>; arquivo: string }> {
    return this.request("PUT", "/atalhos", { atalhos });
  }

  ghostty(): Promise<GhosttyInfo> {
    return this.request("GET", "/ghostty");
  }

  ghosttyTheme(nome: string): Promise<TerminalTheme> {
    return this.request("GET", `/ghostty/tema?${new URLSearchParams({ nome })}`);
  }

  readGhosttyTheme(texto: string, nome?: string): Promise<TerminalTheme> {
    return this.request("POST", "/ghostty/ler", nome ? { texto, nome } : { texto });
  }

  /** A versão em uso e a nova, se houver; `buscar` traz as tags do GitHub antes (alguns segundos). */
  systemVersion(buscar = false): Promise<VersionInfo> {
    return this.request("GET", `/sistema/versao${buscar ? "?buscar=true" : ""}`);
  }

  /** Abre um terminal que instala a versão (a mais nova, sem versão) e devolve a sessão dele. */
  systemUpdate(versao?: string): Promise<Session> {
    return this.request("POST", "/sistema/atualizar", versao ? { versao } : {});
  }

  // --- agentes e terminal (v0.9.8)

  sessionBar(id: string): Promise<{ comandos: BarCommand[] }> {
    return this.request("GET", `/sessions/${encodeURIComponent(id)}/barra`);
  }

  sessionContext(id: string): Promise<SessionContext> {
    return this.request("GET", `/sessions/${encodeURIComponent(id)}/contexto`);
  }

  /** Acorda o agente hibernado (SIGCONT). */
  wakeSession(id: string): Promise<Session> {
    return this.request("POST", `/sessions/${encodeURIComponent(id)}/acordar`);
  }

  themes(): Promise<{ temas: ThemeEntry[] }> {
    return this.request("GET", "/temas");
  }

  theme(nome: string, formato: string): Promise<TerminalTheme & { formato: string }> {
    return this.request("GET", `/temas/tema?${new URLSearchParams({ nome, formato })}`);
  }

  /** Lê um tema colado (Ghostty, Kitty ou Warp: o formato é detectado). */
  readTheme(texto: string, nome?: string): Promise<TerminalTheme & { formato: string }> {
    return this.request("POST", "/temas/ler", nome ? { texto, nome } : { texto });
  }

  metisSkill(): Promise<{ texto: string; instalada: { claude: boolean; codex: boolean } }> {
    return this.request("GET", "/skills/metis");
  }

  installMetisSkill(destino: "claude" | "codex" | "ambos"): Promise<{ texto: string; instalada: { claude: boolean; codex: boolean } }> {
    return this.request("POST", "/skills/metis", { destino });
  }

  // --- navegador e tela (v0.9.8, parte 2) ---

  browserAnswer(id: string, ok: boolean, resultado: unknown, erro: string | null = null): Promise<void> {
    return this.request("POST", `/navegador/resposta/${encodeURIComponent(id)}`, { ok, resultado, erro });
  }

  webHistory(q = "", limite = 20): Promise<{ itens: HistoryEntry[] }> {
    return this.request("GET", `/navegador/historico?q=${encodeURIComponent(q)}&limite=${limite}`);
  }

  addWebHistory(url: string, titulo: string | null): Promise<void> {
    return this.request("POST", "/navegador/historico", { url, titulo: titulo ?? "" });
  }

  clearWebHistory(): Promise<void> {
    return this.request("DELETE", "/navegador/historico");
  }

  browserProfiles(): Promise<{ perfis: BrowserProfile[] }> {
    return this.request("GET", "/navegador/perfis");
  }

  createBrowserProfile(nome: string): Promise<BrowserProfile> {
    return this.request("POST", "/navegador/perfis", { nome });
  }

  renameBrowserProfile(id: string, nome: string): Promise<BrowserProfile> {
    return this.request("PATCH", `/navegador/perfis/${encodeURIComponent(id)}`, { nome });
  }

  deleteBrowserProfile(id: string): Promise<void> {
    return this.request("DELETE", `/navegador/perfis/${encodeURIComponent(id)}`);
  }

  cookieSources(): Promise<{ fontes: CookieSource[] }> {
    return this.request("GET", "/navegador/importar");
  }

  readCookies(fonte: string, dominios?: string[]): Promise<{ cookies: ImportedCookie[]; ignorados: number }> {
    return this.request("POST", "/navegador/importar", { fonte, dominios: dominios?.length ? dominios : null });
  }

  sidebar(): Promise<SidebarState> {
    return this.request("GET", "/barra");
  }

  patchSidebar(change: { fixar: { caminho: string; fixo: boolean } } | { nome: { caminho: string; nome: string } } | { cor: { projeto: string; cor: string } }): Promise<SidebarState> {
    return this.request("PATCH", "/barra", change);
  }

  renameSession(id: string, titulo: string): Promise<Session> {
    return this.request("PATCH", `/sessions/${encodeURIComponent(id)}`, { titulo });
  }

  appThemes(): Promise<{ temas: AppTheme[] }> {
    return this.request("GET", "/temas-app");
  }

  deleteAppTheme(id: string): Promise<void> {
    return this.request("DELETE", `/temas-app/${encodeURIComponent(id)}`);
  }

  promptAppTheme(descricao: string): Promise<AppTheme> {
    return this.request("POST", "/temas-app/prompt", { descricao });
  }

  appThemeSources(): Promise<{ fontes: AppThemeSource[] }> {
    return this.request("GET", "/temas-app/importar");
  }

  importAppTheme(id: string): Promise<AppTheme> {
    return this.request("POST", "/temas-app/importar", { id });
  }

  // --- conectores, kanban, painel e Atividade (v0.9.8, parte 3) ---

  connectGithub(nome: string, token = ""): Promise<ConnectorAccount> {
    return this.request("POST", "/conectores/github", { nome, token: token || null });
  }

  googleClient(): Promise<{ configurado: boolean; client_id_fim: string }> {
    return this.request("GET", "/conectores/google/cliente");
  }

  saveGoogleClient(client_id: string, client_secret: string): Promise<{ configurado: boolean; client_id_fim: string }> {
    return this.request("PUT", "/conectores/google/cliente", { client_id, client_secret });
  }

  startGoogle(nome: string): Promise<{ url: string }> {
    return this.request("POST", "/conectores/google/iniciar", { nome });
  }

  /** MCP próprio: http (nenhuma, token ou oauth → {url}) ou stdio. */
  addMcp(body: {
    nome: string;
    transporte: "http" | "stdio";
    url?: string;
    auth?: "nenhuma" | "token" | "oauth";
    token?: string;
    comando?: string;
    env?: string;
    pasta?: string;
  }): Promise<ConnectorAccount | { url: string }> {
    return this.request("POST", "/conectores/mcp", body);
  }

  mcpRegistry(q: string): Promise<{ servidores: RegistryServer[] }> {
    return this.request("GET", `/conectores/catalogo-mcp?q=${encodeURIComponent(q)}`);
  }

  checkConnector(id: string): Promise<ConnectionTest> {
    return this.request("POST", `/conectores/${encodeURIComponent(id)}/testar`);
  }

  cliMcps(): Promise<{ claude: CliMcp[]; codex: CliMcp[] }> {
    return this.request("GET", "/mcps-cli");
  }

  copyCliMcp(de: "claude" | "codex", para: "claude" | "codex", nome: string): Promise<{ claude: CliMcp[]; codex: CliMcp[]; avisos?: string[] }> {
    return this.request("POST", "/mcps-cli/copiar", { de, para, nome });
  }

  clickupLists(conta: string): Promise<{ listas: ClickupList[] }> {
    return this.request("GET", `/clickup/${encodeURIComponent(conta)}/listas`);
  }

  clickupApiToken(conta: string): Promise<{ tem: boolean }> {
    return this.request("GET", `/clickup/${encodeURIComponent(conta)}/token-api`);
  }

  saveClickupApiToken(conta: string, token: string): Promise<{ tem: boolean } | void> {
    return this.request("PUT", `/clickup/${encodeURIComponent(conta)}/token-api`, { token });
  }

  clickupBoard(projeto: string): Promise<ClickupBoard> {
    return this.request("GET", `/kanban/${encodeURIComponent(projeto)}/clickup`);
  }

  linkClickup(projeto: string, conta: string, lista: string, nome: string): Promise<unknown> {
    return this.request("PUT", `/kanban/${encodeURIComponent(projeto)}/clickup`, { conta, lista, nome });
  }

  unlinkClickup(projeto: string): Promise<void> {
    return this.request("DELETE", `/kanban/${encodeURIComponent(projeto)}/clickup`);
  }

  setClickupStatus(conta: string, id: string, status: string): Promise<ClickupTask> {
    return this.request("PATCH", `/clickup/${encodeURIComponent(conta)}/tarefas/${encodeURIComponent(id)}`, { status });
  }

  agentsPanel(): Promise<{ agentes: AgentPanelItem[] }> {
    return this.request("GET", "/agentes/painel");
  }

  agentEvents(limite = 100, sessao = ""): Promise<{ eventos: AgentEvent[] }> {
    return this.request("GET", `/atividade/eventos?limite=${limite}&sessao=${encodeURIComponent(sessao)}`);
  }

  // --- código e Skills (v0.9.8, parte 5) ---

  failedChecks(root: string): Promise<{ pr: number | null; checks: FailedCheck[] }> {
    return this.request("GET", `/github/checks-falhos?root=${encodeURIComponent(root)}`);
  }

  failedChecksRequest(root: string): Promise<{ pedido: string }> {
    return this.request("POST", "/github/checks-falhos/pedido", { root });
  }

  reviewPr(root: string, cli: "claude" | "codex"): Promise<Session> {
    return this.request("POST", "/github/revisao", { root, cli });
  }

  codeGraph(root: string): Promise<CodeGraph> {
    return this.request("GET", `/codigo/grafo?root=${encodeURIComponent(root)}`);
  }

  updateCodeGraph(root: string): Promise<void> {
    return this.request("POST", "/codigo/grafo/atualizar", { root });
  }

  installSkill(origem: string, destino: SkillTarget, root?: string, substituir = false): Promise<{ instaladas: string[]; ignoradas: { nome: string; motivo: string }[] }> {
    return this.request("POST", "/skills/instalar", { origem, destino, root: root || null, substituir });
  }

  updateSkill(nome: string, destino: SkillTarget, root?: string): Promise<{ nome: string; commit: string; antes: string | null }> {
    return this.request("POST", `/skills/${encodeURIComponent(nome)}/atualizar`, { destino, root: root || null });
  }

  exportSkill(nome: string, destino: SkillTarget, root?: string): Promise<{ arquivo: string }> {
    return this.request("POST", `/skills/${encodeURIComponent(nome)}/exportar`, { destino, root: root || null });
  }

  copySkill(nome: string, de: SkillTarget, para: SkillTarget, root?: string): Promise<{ pasta: string }> {
    return this.request("POST", `/skills/${encodeURIComponent(nome)}/copiar`, { de, para, root: root || null });
  }

  deleteSkill(nome: string, destino: SkillTarget, root?: string): Promise<{ lixeira: string }> {
    const query = new URLSearchParams({ destino, root: root || "" });
    return this.request("DELETE", `/skills/${encodeURIComponent(nome)}?${query}`);
  }

  async upload(file: Blob, name: string): Promise<string> {
    const answer = await this.send<{ path: string }>(
      "POST",
      `/attachments?name=${encodeURIComponent(name)}`,
      file,
      "application/octet-stream",
    );
    return answer.path;
  }
}

/** Acompanha a tela cheia da janela (pelo botão verde, ⌃⌘F ou Visualizar → Tela cheia): o
 * macOS esconde os botões da janela nela, e a barra de título devolve o espaço deles.
 *
 * Não há evento de tela cheia: o estado é perguntado depois que a janela para de mudar de
 * tamanho. A pergunta espera 250 ms do último resize (arrastar a borda não vira uma chamada
 * por quadro) e se repete 700 ms depois, porque o macOS só marca a saída da tela cheia no fim
 * da animação, depois do último resize. Resposta atrasada de uma pergunta antiga é ignorada. */
export async function watchFullscreen(onChange: (full: boolean) => void): Promise<() => void> {
  if (!inTauri()) return () => {};
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const win = getCurrentWindow();
  let asked = 0;
  const timers: number[] = [];
  const ask = () => {
    const mine = ++asked;
    void win.isFullscreen().then((full) => mine === asked && onChange(full), () => {});
  };
  const settle = () => {
    timers.splice(0).forEach((timer) => window.clearTimeout(timer));
    timers.push(window.setTimeout(ask, 250), window.setTimeout(ask, 950));
  };
  ask();
  const unlisten = await win.onResized(settle);
  return () => {
    unlisten();
    timers.splice(0).forEach((timer) => window.clearTimeout(timer));
  };
}
