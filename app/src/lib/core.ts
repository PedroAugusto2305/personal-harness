import type { Session, SessionKind, Usage } from "../types";

export interface CoreInfo {
  url: string;
  token: string;
  managed?: boolean;
}

const inTauri = () => "__TAURI_INTERNALS__" in window;

/** Onde está o núcleo: no app, o Tauri informa; no navegador, as variáveis VITE_*. */
export async function getCoreInfo(): Promise<CoreInfo> {
  if (inTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<CoreInfo>("core_info");
  }
  return {
    url: import.meta.env.VITE_HARNESS_URL ?? "http://127.0.0.1:47830",
    token: import.meta.env.VITE_HARNESS_TOKEN ?? "",
  };
}

export class CoreError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
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

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.info.url}${path}`, {
      method,
      headers: { "Content-Type": "application/json", "X-Harness-Token": this.info.token },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        detail = (await response.json()).detail ?? detail;
      } catch {
        // resposta sem JSON
      }
      throw new CoreError(String(detail), response.status);
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  listSessions(): Promise<Session[]> {
    return this.request("GET", "/sessions");
  }

  usage(): Promise<Usage> {
    return this.request("GET", "/usage");
  }

  createSession(kind: SessionKind, cwd: string, cols: number, rows: number): Promise<Session> {
    return this.request("POST", "/sessions", { kind, cwd, cols, rows });
  }

  closeSession(id: string): Promise<void> {
    return this.request("DELETE", `/sessions/${id}`);
  }
}

export async function windowAction(action: "close" | "minimize" | "toggleMaximize"): Promise<void> {
  if (!inTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow()[action]();
}
