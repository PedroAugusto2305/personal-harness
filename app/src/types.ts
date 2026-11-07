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

export type CoreEvent =
  | { type: "hello"; sessions: Session[]; usage: Usage; accounts: Accounts }
  | { type: "session.created"; session: Session }
  | { type: "session.closed"; id: string }
  | { type: "session.status"; id: string; status: SessionStatus }
  | { type: "session.statusline"; id: string; statusline: Statusline }
  | { type: "session.hook"; id: string; name: string }
  | { type: "usage"; usage: Usage }
  | { type: "accounts"; accounts: Accounts };

export type Connection = "connecting" | "online" | "offline";

export type ThemeName = "dracula" | "grafite" | "claro";

export type View = "term" | "settings";
