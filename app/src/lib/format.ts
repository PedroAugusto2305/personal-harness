import type { SessionStatus } from "../types";

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
