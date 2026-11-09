import type { Provider, SessionKind, SessionStatus } from "../types";

export const STATUS_LABEL: Record<SessionStatus, string> = {
  starting: "iniciando",
  running: "rodando",
  working: "trabalhando",
  waiting: "esperando você",
  exited: "encerrada",
};

export const STATUS_COLOR: Record<SessionStatus, string> = {
  starting: "var(--fnt)",
  running: "var(--acc)",
  working: "var(--run)",
  waiting: "var(--wait)",
  exited: "var(--fnt)",
};

/** 76200 → "76,2k"; 1000000 → "1M". */
export function tokens(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1_000_000_000) return `${trim(value / 1_000_000_000)}B`;
  if (value >= 1_000_000) return `${trim(value / 1_000_000)}M`;
  if (value >= 1_000) return `${trim(value / 1_000)}k`;
  return String(value);
}

function trim(value: number): string {
  return value.toFixed(1).replace(/\.0$/, "").replace(".", ",");
}

export function pct(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value)}%`;
}

/** Tempo até zerar a janela de uso: "2h48m", "4d6h", "12m". */
export function resetIn(epochSeconds: number | null | undefined, now = Date.now()): string {
  if (!epochSeconds) return "";
  const minutes = Math.max(0, Math.round((epochSeconds * 1000 - now) / 60000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) return `${days}d${hours}h`;
  if (hours > 0) return `${hours}h${String(mins).padStart(2, "0")}m`;
  return `${mins}m`;
}

/** /Users/pedro/orca/projects/x → ~/orca/projects/x */
export function shortPath(path: string): string {
  return path.replace(/^\/Users\/[^/]+/, "~");
}

export function money(value: number | null | undefined): string {
  if (value == null) return "";
  return `US$ ${value.toFixed(2).replace(".", ",")}`;
}

export const KIND_LABEL: Record<SessionKind, string> = { claude: "Claude Code", codex: "Codex", shell: "Shell" };
export const KIND_GLYPH: Record<SessionKind, string> = { claude: "✻", codex: "◇", shell: ">_" };
export const KIND_COLOR: Record<SessionKind, string> = { claude: "#d97757", codex: "var(--acct)", shell: "var(--mut)" };
export const PROVIDERS: Provider[] = ["claude", "codex"];

/** 83 s → "1:23". */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Sem acento e em minúsculas, para a busca do salto rápido. */
export function fold(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

/** Quanto tempo faz, curto: "agora", "há 5 min", "há 3 h", "ontem", "há 4 dias", "12/03". */
export function ago(epochMs: number, now = Date.now()): string {
  const minutes = Math.floor((now - epochMs) / 60000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "ontem";
  if (days < 7) return `há ${days} dias`;
  const date = new Date(epochMs);
  const dm = `${String(date.getDate()).padStart(2, "0")}/${String(date.getMonth() + 1).padStart(2, "0")}`;
  return date.getFullYear() === new Date(now).getFullYear() ? dm : `${dm}/${date.getFullYear()}`;
}

/** 1536 → "1,5 GB"; 230 → "230 MB". */
export function megabytes(mb: number): string {
  return mb >= 1024 ? `${trim(mb / 1024)} GB` : `${Math.round(mb)} MB`;
}
