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

export type AgentDraft = Pick<Agent, "name" | "description" | "cli" | "model" | "account" | "folder" | "color" | "prompt">;

export interface TextFile {
  path: string;
  size: number;
  binary: boolean;
  truncated: boolean;
  text: string;
  mime: string;
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
  | { type: "hello"; sessions: Session[]; usage: Usage; accounts: Accounts; projects: Project[]; agents: Agent[] }
  | { type: "session.created"; session: Session }
  | { type: "session.closed"; id: string }
  | { type: "session.status"; id: string; status: SessionStatus }
  | { type: "session.statusline"; id: string; statusline: Statusline }
  | { type: "session.hook"; id: string; name: string }
  | { type: "usage"; usage: Usage }
  | { type: "accounts"; accounts: Accounts }
  | { type: "projects"; projects: Project[] }
  | { type: "worktrees"; project: string }
  | { type: "agents"; agents: Agent[] }
  | { type: "ports"; ports: Record<string, number[]> }
  | { type: "open-web"; url: string; cwd: string | null }
  | { type: "brain.changed"; project: string };

export type Connection = "connecting" | "online" | "offline";

export type ThemeName = "dracula" | "grafite" | "claro";

export type View = "term" | "agents" | "settings" | "brain" | "kanban";

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

export interface BrainPlace {
  project: BoardProject | null;
  tasks?: KanbanTask[];
  precedents?: BrainHit[];
}
