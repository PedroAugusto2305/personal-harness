import type {
  Accounts,
  Account,
  Agent,
  AgentDraft,
  GitStatus,
  Project,
  Provider,
  Session,
  SessionKind,
  TextFile,
  Usage,
  VoiceStatus,
  Worktree,
} from "../types";

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

  removeProject(id: string): Promise<void> {
    return this.request("DELETE", `/projects/${encodeURIComponent(id)}`);
  }

  worktrees(projectId: string): Promise<Worktree[]> {
    return this.request("GET", `/projects/${encodeURIComponent(projectId)}/worktrees`);
  }

  createWorktree(projectId: string, name: string, copyEnv: boolean, base?: string): Promise<{ path: string; branch: string; copied: string[] }> {
    return this.request("POST", `/projects/${encodeURIComponent(projectId)}/worktrees`, { name, copy_env: copyEnv, base: base || null });
  }

  deleteWorktree(projectId: string, path: string, force = false): Promise<{ branch_deleted: boolean; branch_kept: string | null; branch: string | null }> {
    const query = new URLSearchParams({ path, force: String(force) });
    return this.request("DELETE", `/projects/${encodeURIComponent(projectId)}/worktrees?${query}`);
  }

  // --- git da revisão

  gitStatus(path: string): Promise<GitStatus> {
    return this.request("GET", `/git/status?${new URLSearchParams({ path })}`);
  }

  async gitDiff(path: string, file: string, mode: "head" | "staged" | "worktree", untracked: boolean): Promise<string> {
    const query = new URLSearchParams({ path, file, mode, untracked: String(untracked) });
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

  commit(path: string, message: string): Promise<unknown> {
    return this.request("POST", "/git/commit", { path, message });
  }

  push(path: string): Promise<unknown> {
    return this.request("POST", "/git/push", { path });
  }

  pull(path: string): Promise<unknown> {
    return this.request("POST", "/git/pull", { path });
  }

  // --- arquivos

  files(root: string): Promise<{ root: string; files: string[] }> {
    return this.request("GET", `/fs/files?${new URLSearchParams({ root })}`);
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

  spriteUrl(id: string, version: number): string {
    return `${this.info.url}/agents/${encodeURIComponent(id)}/sprite?${new URLSearchParams({ token: this.info.token, v: String(version) })}`;
  }

  importMaestri(): Promise<{ imported: string[] }> {
    return this.request("POST", "/agents/import/maestri");
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

export async function windowAction(action: "close" | "minimize" | "toggleMaximize"): Promise<void> {
  if (!inTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow()[action]();
}
