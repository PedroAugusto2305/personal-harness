// Formatos que o núcleo (core/src/harness_core) devolve e publica.

export type Provider = "claude" | "codex";
export type SessionKind = Provider | "shell";
export type SessionStatus = "starting" | "running" | "working" | "waiting" | "exited";

export interface RateWindow {
  used_pct: number;
  resets_at: number | null;
}

export type RateLimits = Partial<Record<"five_hour" | "seven_day", RateWindow>>;

export interface Statusline {
  model: string | null;
  cwd: string | null;
  context: { used_pct: number | null; size: number | null; used_tokens: number | null };
  cost_usd: number | null;
  rate_limits: RateLimits;
  transcript?: string | null;
  /** Id da conversa no Claude (para continuar depois de sair). */
  session_id?: string | null;
}

export interface Session {
  id: string;
  kind: SessionKind;
  title: string;
  cwd: string;
  created_at: number;
  account: string | null;
  tag: string | null;
  agent: string | null;
  ports: number[];
  status: SessionStatus;
  statusline: Statusline | null;
  exit_code: number | null;
  pid: number | null;
}

export interface Account {
  id: string;
  name: string;
  dir: string | null;
  active: boolean;
}

export type Accounts = Record<Provider, { active: string; accounts: Account[] }>;

/** Limites do plano de uma conta. O Codex informa também o plano. */
export type AccountLimits = RateLimits & { plan?: string; updated_at?: number };

/** Uso por provedor e por conta (id da conta → limites). */
export type Usage = Record<Provider, Record<string, AccountLimits>>;

export interface VoiceStatus {
  model: string;
  state: "idle" | "loading" | "ready" | "error";
  error: string | null;
}

export interface Project {
  id: string;
  name: string;
  path: string;
}

export interface Worktree {
  path: string;
  head: string | null;
  branch: string | null;
  detached: boolean;
  locked: boolean;
  prunable: boolean;
  main: boolean;
  changes: number;
  ahead: number;
  behind: number;
  missing: boolean;
}

export interface GitFile {
  path: string;
  orig: string | null;
  x: string;
  y: string;
  staged: boolean;
  unstaged: boolean;
  untracked: boolean;
  conflict: boolean;
}

export interface GitStatus {
  branch: string | null;
  head: string | null;
  upstream: string | null;
  ahead: number;
  behind: number;
  files: GitFile[];
  /** v0.9.6: operação em andamento (merge, rebase…) e o último commit (subiu = já está no upstream). */
  operacao?: "merge" | "rebase" | "cherry-pick" | "revert" | null;
  ultimo_commit?: { sha: string; assunto: string; subiu: boolean } | null;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  cli: Provider;
  model: string;
  account: string;
  folder: string;
  color: string;
  origin: string;
  prompt: string;
  sprite: boolean;
  updated_at: number;
  /** Contas de conector liberadas pela central: "" = todas; "nenhum" = nenhuma; senão ids separados por vírgula. */
  connectors: string;
  pain: string;
}

export interface SpriteJob {
  id: string;
  prompt: string;
  base: string | null;
  status: "running" | "done" | "error";
  error: string | null;
  note: string;
  created_at: number;
  finished_at: number | null;
}

export type AgentDraft = Pick<Agent, "name" | "description" | "pain" | "cli" | "model" | "account" | "folder" | "color" | "connectors" | "prompt">;

export interface TextFile {
  path: string;
  size: number;
  binary: boolean;
  truncated: boolean;
  text: string;
  mime: string;
  /** v0.9.7: sha256 do arquivo inteiro (o editor só grava se ninguém mudou desde que abriu). */
  hash?: string;
  mtime?: number;
}

/** Nota numa linha do diff, que vai em lote para o agente. */
export interface ReviewNote {
  id: string;
  file: string;
  line: number;
  side: "old" | "new";
  code: string;
  text: string;
}

export type CoreEvent =
  | { type: "hello"; version?: string; sessions: Session[]; usage: Usage; accounts: Accounts; projects: Project[]; agents: Agent[] }
  | { type: "prefs"; prefs: Prefs }
  | { type: "comandos" }
  | { type: "atualizacao"; nova: string; versao: string }
  | { type: "atalhos" }
  | { type: "awake"; ativo: boolean }
  | { type: "session.created"; session: Session }
  | { type: "session.closed"; id: string }
  | { type: "session.status"; id: string; status: SessionStatus; exit_code?: number | null }
  | { type: "session.statusline"; id: string; statusline: Statusline }
  | { type: "session.hook"; id: string; name: string; message?: string | null }
  | { type: "usage"; usage: Usage }
  | { type: "accounts"; accounts: Accounts }
  | { type: "projects"; projects: Project[] }
  | { type: "worktrees"; project: string }
  | { type: "agents"; agents: Agent[] }
  | { type: "ports"; ports: Record<string, number[]> }
  | { type: "open-web"; url: string; cwd: string | null }
  | { type: "brain.changed"; project: string }
  | { type: "connectors"; accounts: ConnectorAccount[] }
  | { type: "approval"; approval: Approval }
  | { type: "approval.done"; id: string }
  | { type: "activity"; item: ActivityItem }
  | { type: "connector.error"; account: string; error: string }
  | { type: "routines"; routines: Routine[] }
  | { type: "routine.run"; routine: Routine; run: RoutineRun; session?: string }
  | { type: "study"; summary: StudySummary }
  | { type: "suggestions"; created?: number[]; decided?: number }
  | { type: "brain.session"; session: string }
  | { type: "brain.error"; error: string }
  | { type: "automation.run"; run: number; automation: string; status: AutoRunStatus; mode: AutoMode; error?: string }
  | { type: "automation.step"; run: number; automation?: string | null; step: string; status?: AutoStepStatus; itens?: number; erro?: string; nota?: string; sessao?: string }
  | { type: "automation.published"; automation: string; versao: number }
  | { type: "automation.error"; automation: string; error: string };

export type Connection = "connecting" | "online" | "offline";

export type ThemeName = "dracula" | "grafite" | "claro";

export type View = "term" | "agents" | "settings" | "brain" | "kanban" | "connectors" | "today" | "study" | "automations" | "boards";

// --- Rotinas e Hoje (v0.7) ---------------------------------------------------------------

export interface Routine {
  id: string;
  name: string;
  agent: string;
  cli: "claude" | "codex";
  folder: string;
  /** 0 = segunda … 6 = domingo */
  days: number[];
  time: string;
  /** minutos depois da hora em que ainda roda se o Mac estava dormindo */
  catchup: number;
  notify: boolean;
  active: boolean;
  prompt: string;
  created: number;
  updated_at: number;
  next?: string | null;
}

export type RoutineDraft = Pick<Routine, "name" | "agent" | "cli" | "folder" | "days" | "time" | "catchup" | "notify" | "active" | "prompt">;

export interface RoutineRun {
  id: number;
  routine: string;
  slot: number;
  ts: number;
  status: string;
  session: string;
  detail: string;
}

export interface StudySummary {
  today: number;
  floor: number;
  week: { day: string; minutes: number }[];
  week_total: number;
  streak: number;
  rest_day: boolean;
  risk: boolean;
  recent: { id: number; started: number; ended: number; minutes: number; subject: string; day: string }[];
}

export interface AgentDraftSuggestion {
  name: string;
  description: string;
  pain: string;
  cli: "claude" | "codex";
  color: string;
  folder: string;
  prompt: string;
  sprite: string;
}

export interface TodayData {
  now: string;
  weekday: string;
  slots: { routine: Routine; slot: string; run: RoutineRun | null }[];
  manual: RoutineRun[];
  doing: (KanbanTask & { project: string })[];
  approvals: Approval[];
  study: StudySummary;
}

// --- Conectores, aprovação e Atividade (v0.6) ------------------------------------------------

export interface ConnectorAccount {
  id: string;
  kind: "slack" | "clickup";
  service: string;
  name: string;
  created: number;
  meta: Record<string, string | number>;
  approve_writes: boolean;
  reminders: boolean;
}

export interface ConnectorCatalog {
  [kind: string]: { name: string; auth: "token" | "oauth"; description: string; url?: string };
}

export interface Approval {
  id: string;
  session: string;
  who: string;
  tool: string;
  account: string;
  summary: string;
  args: Record<string, unknown>;
  created: number;
}

export interface ActivityItem {
  id: number;
  ts: number;
  session: string;
  who: string;
  tool: string;
  account: string;
  args: Record<string, unknown> | string;
  status: string;
  detail: string;
  ms: number;
}

// --- Brain e kanban (v0.5) ---------------------------------------------------------

export type NoteType = "decisao" | "incidente" | "aprendizado" | "entrega" | "projeto" | string;

export interface BrainHit {
  path: string;
  title: string;
  tipo: NoteType;
  projeto: string;
  status: string;
  data: string;
  resumo: string;
  /** Trecho com \x02 … \x03 em volta das palavras achadas. */
  snippet?: string;
  terms?: string[];
  /** Como o precedente foi achado (v0.8): "significado", "palavra" ou os dois. */
  via?: string[];
  /** Quanto se destaca da média, em desvios-padrão (busca por significado). */
  z?: number;
}

export interface BrainNote extends BrainHit {
  meta: Record<string, string>;
  body: string;
  backlinks: BrainHit[];
}

export type Stage = "" | "ideia" | "planejando" | "construindo" | "em-producao" | "pausado";
export type TaskState = "pendente" | "em-andamento" | "em-teste" | "concluida";

export interface BoardProject {
  name: string;
  path: string;
  stage: Stage;
  status: string;
  area: string;
  deadline: string;
  started: string;
  updated: string;
  directory: string;
  tasks: Record<TaskState, number>;
  next: string[];
  records: { decisoes: number; incidentes: number; entregas: number; aprendizados: number };
  proposals: number;
}

export interface KanbanTask {
  id: string;
  text: string;
  state: TaskState;
  line: number;
  subtasks_done: number;
  subtasks_total: number;
  cancelled: boolean;
  done_on: string;
}

export interface GraphNodeData {
  path: string;
  title: string;
  tipo: NoteType;
  projeto: string;
  status: string;
  data: string;
  /** Nuvem da área do projeto: carreira, trabalho, clientes, pessoal, brain ou semarea. */
  group: string;
  degree: number;
}

export interface BrainGraphData {
  nodes: GraphNodeData[];
  edges: [number, number][];
  groups: { key: string; label: string; count: number }[];
}

export interface BrainPlace {
  project: BoardProject | null;
  tasks?: KanbanTask[];
  precedents?: BrainHit[];
}

// --- Brain vivo (v0.8) -----------------------------------------------------------------------

export interface Suggestion {
  id: number;
  created: number;
  source_path: string;
  source_title: string;
  source_tipo: NoteType;
  source_project: string;
  target_project: string;
  title: string;
  resumo: string;
  motivo: string;
  matches: { title: string; path: string; tipo: NoteType; z: number }[];
  z: number;
  status: "pendente" | "aceita" | "recusada";
  decided: number | null;
  note: string | null;
}

export interface SemanticStatus {
  model: { state: "ausente" | "baixando" | "carregando" | "pronto" | "parado" | "erro"; model: string; url: string; error: string; disk_mb: number; loads: number };
  index: { notes: number; vectors: number };
  suggestions: {
    counts: Record<string, number>;
    judged_today: number;
    daily_max: number;
    watching_since: string | null;
    last_scan: { at?: number; new?: number; candidates?: number; judged?: number; created?: number[]; errors?: string[] };
    judge: boolean;
  };
}

export interface SessionMapNode {
  path: string;
  title: string;
  tipo: NoteType;
  projeto: string;
  status: string;
  via: string[];
}

export interface SessionMap {
  project: string | null;
  nodes: SessionMapNode[];
  edges: [number, number][];
}

export interface ContextWindow {
  available: boolean;
  reason?: string;
  used?: number;
  size?: number;
  pct?: number | null;
  free?: number;
  categories?: { key: string; label: string; tokens: number; pct: number }[];
  top?: { label: string; category: string; tokens: number; times: number }[];
  compacted?: boolean;
  estimated?: boolean;
  updated?: number;
}

// --- Automações (v0.9.0) ---------------------------------------------------------------------

export type AutoStepType = "ferramenta" | "agente" | "condicao" | "aprovacao" | "brain" | "esperar";
export type AutoOutputType = "texto" | "numero" | "lista" | "objeto" | "sim/nao";
export type AutoMode = "teste" | "producao";
export type AutoRunStatus = "rodando" | "ok" | "erro" | "recusada" | "cancelada" | "pulada" | "interrompida";
export type AutoStepStatus = "rodando" | "ok" | "erro" | "pulado" | "recusado" | "esperando";

export interface AutoTrigger {
  tipo: "manual" | "agendado";
  /** 0 = segunda … 6 = domingo */
  dias?: number[];
  hora?: string;
  recupera_min?: number;
  x?: number;
  y?: number;
}

export interface AutoStep {
  id: string;
  tipo: AutoStepType;
  titulo: string;
  x?: number;
  y?: number;
  /** Desligado: os dados passam direto, sem rodar. */
  desligado?: boolean;
  /** Dados fixados: no teste, substituem a chamada. */
  fixado?: unknown;
  // ferramenta
  ferramenta?: string;
  argumentos?: Record<string, unknown>;
  // agente
  agente?: string;
  cli?: "claude" | "codex";
  modelo?: string;
  onde?: "segundo-plano" | "visivel";
  ferramentas?: string[];
  pedido?: string;
  saida?: Record<string, AutoOutputType>;
  pasta?: string;
  tempo_limite_min?: number;
  // condição
  regra?: string;
  // aprovação
  mensagem?: string;
  prazo_min?: number;
  // Brain
  acao?: "buscar" | "ler" | "precedentes" | "tarefas" | "diario";
  /** Título da nota que o "ler" abre. */
  nota?: string;
  termos?: string;
  tipos?: string;
  projeto?: string;
  texto?: string;
  limite?: number;
  // esperar
  minutos?: number;
}

export interface AutoEdge {
  de: string;
  para: string;
  ramo?: "sim" | "não";
}

export interface AutoNote {
  id: string;
  titulo: string;
  texto: string;
  x: number;
  y: number;
  w?: number;
}

export interface AutoFlow {
  nome: string;
  descricao: string;
  gatilho: AutoTrigger;
  passos: AutoStep[];
  ligacoes: AutoEdge[];
  notas: AutoNote[];
}

export interface AutoRunSummary {
  id: number;
  automation: string;
  mode: AutoMode;
  origem: string;
  versao: string;
  status: AutoRunStatus;
  started: number;
  ended: number | null;
  error: string | null;
  nota: string | null;
}

export interface AutoStepRun {
  status: AutoStepStatus;
  started: number | null;
  ended: number | null;
  entrada: unknown;
  saida: unknown;
  itens: number | null;
  erro: string | null;
  nota: string | null;
  /** Terminal do passo de agente (dá para abrir enquanto ele trabalha). */
  sessao?: string | null;
}

export interface AutoRun extends AutoRunSummary {
  flow: AutoFlow;
  steps: Record<string, AutoStepRun>;
}

export interface AutoSummary {
  id: string;
  nome: string;
  descricao?: string;
  gatilho?: AutoTrigger;
  ativa: boolean;
  /** Número da versão publicada (null = nunca publicada). */
  publicada: number | null;
  /** O rascunho tem mudanças que a publicada não tem. */
  mudou?: boolean;
  conectores: string[];
  ultima?: AutoRunSummary | null;
  /** Quando o rascunho mudou no disco (segundos): a tela relê se outro mudou o arquivo. */
  alterado?: number;
  /** O YAML não abre (editado à mão com erro). */
  erro?: string;
}

export interface AutoVersion {
  hash: string;
  when: number;
  message: string;
  number: number;
}

export interface AutoDetail extends AutoSummary {
  rascunho: AutoFlow;
  publicada_desenho: AutoFlow | null;
  versoes: AutoVersion[];
  diferenca: string;
  arquivo: string;
}

export interface AutoCatalog {
  ferramentas: { nome: string; descricao: string; conta: string; conta_nome: string; pessoas: boolean; esquema: Record<string, unknown> }[];
  agentes: { id: string; nome: string; cli: "claude" | "codex"; cor: string; descricao: string }[];
}

// --- Quadros (v0.9.1): .canvas do Obsidian (JSON Canvas 1.0) na pasta do projeto no Brain ---------

export type CanvasSide = "top" | "right" | "bottom" | "left";

/** Nó do JSON Canvas (jsoncanvas.org). Cartões da MÊTIS (sessão, tarefa) são nós "text" com um
 *  comentário `%%metis {...}%%` no fim: o Obsidian esconde o comentário e guarda o texto ao salvar. */
export interface CanvasNode {
  id: string;
  type: "text" | "file" | "link" | "group";
  x: number;
  y: number;
  width: number;
  height: number;
  /** "1" a "6" (cores do Obsidian) ou "#rrggbb". */
  color?: string;
  text?: string;
  /** Caminho da nota dentro do vault (nó "file"), ex.: "01-PROJETOS/Alfa/decisoes/X.md". */
  file?: string;
  subpath?: string;
  url?: string;
  label?: string;
  background?: string;
  backgroundStyle?: "cover" | "ratio" | "repeat";
}

export interface CanvasEdge {
  id: string;
  fromNode: string;
  fromSide?: CanvasSide;
  fromEnd?: "none" | "arrow";
  toNode: string;
  toSide?: CanvasSide;
  toEnd?: "none" | "arrow";
  color?: string;
  label?: string;
}

export interface CanvasDoc {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

/** O que a MÊTIS guarda no `%%metis {...}%%` de um nó "text". */
export type BoardCardMeta =
  | { tipo: "sessao"; sessao: string; titulo: string; kind: SessionKind; cwd: string; agente?: string }
  | { tipo: "tarefa"; projeto: string; id: string };

export interface BoardSummary {
  /** Caminho do .canvas dentro do vault. */
  path: string;
  nome: string;
  projeto: string | null;
  itens: number;
  /** mtime do arquivo (segundos): muda quando o Obsidian salva. */
  alterado: number;
}

export interface BoardFile extends BoardSummary {
  canvas: CanvasDoc;
  /** Para cada nó "file": a nota do Brain (título, tipo, projeto, status, resumo) ou null se não existe. */
  notas: Record<string, BrainHit | null>;
}

export interface SessionGlance {
  id: string;
  title: string;
  kind: SessionKind;
  status: SessionStatus;
  cwd: string;
  agent: string | null;
  context_pct: number | null;
  /** Última troca da conversa (Claude, pelo transcript): quem falou e o texto. */
  ultimas: { role: "voce" | "agente"; text: string }[];
  /** Fim do terminal sem cores (Codex, shell, ou Claude sem transcript ainda). */
  linhas: string[];
}

// --- Sessões, agentes e sistema (v0.9.2) ------------------------------------------------------

export type PermissionMode = "padrao" | "manual" | "auto" | "yolo";

export interface Prefs {
  permissao_claude: PermissionMode;
  permissao_codex: PermissionMode;
  /** As pastas dos projetos e das worktrees da MÊTIS entram como confiáveis na CLI. */
  confiar_pastas: boolean;
  manter_acordado: "nunca" | "agente" | "sempre";
  avisos: { terminou: boolean; espera: boolean; aprovacao: boolean; erro: boolean; som: boolean; volume: number; silencio: boolean };
  /** v0.9.6: receitas do que o agente da worktree faz no git, e o editor externo. */
  receita_commit?: string;
  receita_commit_marcado?: string;
  receita_pr?: string;
  agente_git?: "claude" | "codex";
  editor_externo?: string;
}

export interface HistoryItem {
  cli: "claude" | "codex";
  id: string;
  cwd: string;
  titulo: string;
  primeiro: string;
  /** Nome da conta (ou "padrão"). */
  conta: string;
  /** Id da conta na MÊTIS ("padrao" quando é a pasta de sempre, sem conta cadastrada). */
  conta_id?: string;
  inicio: string;
  /** mtime do arquivo (segundos). */
  atualizado: number;
  tamanho: number;
  arquivo: string;
}

export interface Resources {
  nucleo: { mb: number; cpu: number; com_sessoes_mb: number };
  sessoes: { id: string; title: string; kind: SessionKind; status: SessionStatus; cwd: string; mb: number; cpu: number; processos: number; comandos: string[] }[];
  modelo: SemanticStatus["model"];
  acordado: { modo: Prefs["manter_acordado"]; ativo: boolean };
  /** Janelas da MÊTIS ligadas ao núcleo agora. */
  janelas: number;
}

export interface SkillInfo {
  nome: string;
  descricao: string;
  origem: "usuário" | "projeto";
  pasta: string;
  arquivo: string;
}

export interface ProjectScripts {
  /** Roda num terminal à vista na worktree nova. */
  setup: string;
  /** Roda antes de apagar a worktree (até 2 min); se falhar, não apaga sem forçar. */
  arquivar: string;
}

// --- Terminal e navegação (v0.9.3) -----------------------------------------------------

/** Comando ou prompt salvo, global (projeto null) ou de um projeto (o caminho do repositório). */
export interface SavedCommand {
  id: string;
  nome: string;
  texto: string;
  /** "comando" roda no shell; "prompt" vai para a barra de entrada do agente. */
  tipo: "comando" | "prompt";
  projeto: string | null;
}

/** Cores de um tema de terminal, no formato do xterm (ITheme). */
export interface TerminalColors {
  background?: string;
  foreground?: string;
  cursor?: string;
  cursorAccent?: string;
  selectionBackground?: string;
  selectionForeground?: string;
  black?: string;
  red?: string;
  green?: string;
  yellow?: string;
  blue?: string;
  magenta?: string;
  cyan?: string;
  white?: string;
  brightBlack?: string;
  brightRed?: string;
  brightGreen?: string;
  brightYellow?: string;
  brightBlue?: string;
  brightMagenta?: string;
  brightCyan?: string;
  brightWhite?: string;
}

export interface TerminalTheme {
  nome: string;
  cores: TerminalColors;
}

export interface GhosttyInfo {
  config: { arquivo: string; tema: string | null; cores_proprias: boolean } | null;
  temas: { nome: string; origem: "metis" | "ghostty" | "usuario" }[];
}

// --- Uso diário (v0.9.4) ---------------------------------------------------------------

/** A versão em uso: a instalada (cópia de uma tag em ~/.harness/versoes) ou a de desenvolvimento. */
export interface VersionInfo {
  versao: string;
  instalada: boolean;
  tag: string | null;
  pasta: string;
  repositorio: string | null;
  ultima: string | null;
  /** Versão mais nova que a instalada, se houver. */
  nova: string | null;
}

// --- Git e GitHub (v0.9.6) --------------------------------------------------------------

export type DiffMode = "head" | "staged" | "worktree" | "ref";

export interface GitRefs {
  branches: string[];
  remotos: string[];
  tags: string[];
  padrao: string;
  atual: string | null;
}

export interface ChangedFile {
  path: string;
  status: string;
  orig: string | null;
}

export interface ConflictBlock {
  indice: number;
  nosso: string;
  deles: string;
  base: string | null;
  rotulo_nosso: string;
  rotulo_deles: string;
}

export type ConflictChoice = "nosso" | "deles" | "ambos" | "base";

export interface ChecksSummary {
  ok: number;
  falhou: number;
  pendente: number;
}

export interface PullRequest {
  numero: number;
  titulo: string;
  url: string;
  estado: "OPEN" | "MERGED" | "CLOSED";
  rascunho: boolean;
  base: string;
  cabeca: string;
  checks: ChecksSummary;
  revisao: string | null;
  mesclavel: "MERGEABLE" | "CONFLICTING" | "UNKNOWN" | string;
}

export interface GithubState {
  gh: boolean;
  repo: string | null;
  pr: PullRequest | null;
}

export interface GithubIssue {
  numero: number;
  titulo: string;
  url: string;
  rotulos: string[];
  autor: string;
  atualizado: string;
}

export interface GithubPr {
  numero: number;
  titulo: string;
  url: string;
  rascunho: boolean;
  cabeca: string;
  autor: string;
  checks: ChecksSummary;
}

export interface GitConfig {
  assinar: boolean;
  formato: string;
  tem_chave: boolean;
  nome: string;
  email: string;
}

// --- Editores (v0.9.7) ------------------------------------------------------------------

export interface NoteText {
  path: string;
  texto: string;
  hash: string;
  alterado: number;
}

export interface NoteTitle {
  titulo: string;
  tipo: string;
  projeto: string;
  path: string;
}
