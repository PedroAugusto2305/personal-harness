// Ponte com o navegador nativo (src-tauri/src/browser.rs). Fora do Tauri não há
// navegador embutido; a aba cai num iframe simples, sem modo de design.
import { inTauri } from "./core";

export interface BrowserState {
  label: string;
  url: string | null;
  title: string | null;
  loading: boolean | null;
}

export interface DesignPick {
  url: string;
  title: string;
  selector: string;
  element: string;
  text: string;
  html: string;
  styles: string[];
  size: string;
  position: string;
  source: { file: string | null; line: string | number | null; components: string[]; approx?: boolean };
}

export interface ForwardedKey {
  key: string;
  code: string;
  meta: boolean;
  shift: boolean;
  ctrl: boolean;
  alt: boolean;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

async function call<T = void>(command: string, args: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(command, args);
}

/** Zoom da janela da MÊTIS (v0.9.8): a página nativa é posicionada em pontos da janela, e o
 *  retângulo medido no DOM vem em pixels CSS, que o zoom aumenta ou diminui. */
let zoom = 1;
export const appZoom = {
  get: () => zoom,
  async set(factor: number) {
    zoom = Math.min(1.6, Math.max(0.7, Math.round(factor * 100) / 100));
    if (inTauri()) await call("app_zoom", { factor: zoom });
    return zoom;
  },
};
const scaled = (r: Rect): Rect =>
  zoom === 1 ? r : { x: Math.round(r.x * zoom), y: Math.round(r.y * zoom), width: Math.round(r.width * zoom), height: Math.round(r.height * zoom) };

/** Aparelhos da emulação (v0.9.8): tamanho da tela em pontos e o user agent. */
export interface Device {
  id: string;
  nome: string;
  w: number;
  h: number;
  ua: string | null;
}

const IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
export const DEVICES: Device[] = [
  { id: "", nome: "Tela inteira", w: 0, h: 0, ua: null },
  { id: "iphone", nome: "iPhone 15", w: 393, h: 852, ua: IPHONE_UA },
  { id: "iphone-se", nome: "iPhone SE", w: 375, h: 667, ua: IPHONE_UA },
  {
    id: "android",
    nome: "Android (Pixel 8)",
    w: 412,
    h: 915,
    ua: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
  },
  { id: "ipad", nome: "iPad Air", w: 820, h: 1180, ua: "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1" },
  { id: "notebook", nome: "Notebook 1280 × 800", w: 1280, h: 800, ua: null },
];

export interface OpenOptions {
  incognito?: boolean;
  /** Identificador (32 hex) do cofre do perfil; vazio = Padrão. */
  profile?: string | null;
  userAgent?: string | null;
}

export const browser = {
  available: inTauri,
  open: (label: string, url: string, rect: Rect, options: OpenOptions = {}) =>
    call("browser_open", {
      label,
      url,
      incognito: !!options.incognito,
      profile: options.profile || null,
      userAgent: options.userAgent || null,
      ...scaled(rect),
    }),
  bounds: (label: string, rect: Rect) => call("browser_bounds", { label, ...scaled(rect) }),
  visible: (label: string, visible: boolean) => call("browser_visible", { label, visible }),
  navigate: (label: string, url: string) => call("browser_navigate", { label, url }),
  go: (label: string, action: "back" | "forward" | "reload" | "stop" | "devtools" | "focus") => call("browser_go", { label, action }),
  design: (label: string, on: boolean) => call("browser_design", { label, on }),
  close: (label: string) => call("browser_close", { label }),
  /** Roda um script e devolve o valor em JSON (cru, como o WebKit serializou). */
  eval: (label: string, script: string) => call<string>("browser_eval", { label, script }),
  photo: (label: string) => call<string>("browser_photo", { label }),
  userAgent: (label: string, agent: string | null) => call("browser_user_agent", { label, agent }),
  pageZoom: (label: string, factor: number) => call("browser_zoom", { label, factor }),
  removeProfile: (profile: string) => call("browser_remove_profile", { profile }),
  importCookies: (profile: string | null, cookies: unknown[]) => call<number>("browser_import_cookies", { profile, cookies }),
};

const sleep = (ms: number) => new Promise((done) => window.setTimeout(done, ms));

/** Resposta de window.__metis.agent / result, já desembrulhada. */
interface AgentReply {
  ok?: boolean;
  v?: unknown;
  e?: string;
  perdido?: boolean;
  pendente?: string;
}

async function agentEval(label: string, script: string): Promise<AgentReply | null> {
  const raw = await browser.eval(label, script);
  let value: unknown = raw;
  // O WebKit devolve o valor em JSON; o script devolve um texto JSON: dois níveis.
  for (let i = 0; i < 2 && typeof value === "string"; i++) {
    try {
      value = JSON.parse(value);
    } catch {
      break;
    }
  }
  return value && typeof value === "object" ? (value as AgentReply) : null;
}

export class AgentPageError extends Error {}

/**
 * Uma ação do agente dentro da página (v0.9.8): ler, clicar, digitar… O cursor anda antes
 * das ações de mouse, então a resposta pode vir pendente e é buscada em seguida. Se a página
 * trocou no meio (um clique que navegou), a ação conta como feita.
 */
export async function agentAction(label: string, action: string, args: Record<string, unknown>, timeoutMs = 15000): Promise<unknown> {
  const call = `window.__metis && window.__metis.agent ? window.__metis.agent(${JSON.stringify(action)}, ${JSON.stringify(args)}) : null`;
  const reply: AgentReply | null = await agentEval(label, call);
  if (!reply) throw new AgentPageError("a página ainda não está pronta (carregando ou em branco)");
  return follow(label, reply, timeoutMs);
}

/**
 * navegador_js (v1.0). O código vai dentro de uma função no próprio script do evaluateJavaScript,
 * que o CSP da página não bloqueia (o eval de dentro da página dá EvalError em sites sem
 * 'unsafe-eval', como o GitHub e os apps do Google). Se não for uma expressão (vários comandos),
 * o script nem compila, nada roda, e o pedido cai no eval da página, como antes.
 */
export async function agentJs(label: string, code: string, timeoutMs = 15000): Promise<unknown> {
  const expression = code.trim().replace(/[\s;]+$/, "");
  const script = `window.__metis && window.__metis.value ? window.__metis.value(function () { return (${expression}\n); }) : null`;
  const reply: AgentReply | null = await agentEval(label, script).catch(() => null);
  if (reply) return follow(label, reply, timeoutMs);
  return agentAction(label, "js", { codigo: code }, timeoutMs);
}

/** Segue a resposta da página até o fim (a ação pendente é buscada por __metis.result). */
async function follow(label: string, first: AgentReply, timeoutMs: number): Promise<unknown> {
  let reply = first;
  const started = Date.now();
  while (reply.pendente) {
    if (Date.now() - started > timeoutMs) throw new AgentPageError("a página não terminou a ação a tempo");
    await sleep(120);
    const id: string = reply.pendente;
    const next: AgentReply | null = await agentEval(label, `window.__metis && window.__metis.result ? window.__metis.result(${JSON.stringify(id)}) : null`).catch(() => null);
    // Sem __metis (página nova nascendo) ou resposta perdida: o clique levou a outra página.
    if (!next) return "feito; a página mudou";
    reply = next;
  }
  if (!reply.ok) {
    if (reply.perdido) return "feito; a página mudou";
    throw new AgentPageError(reply.e || "a página recusou a ação");
  }
  return reply.v;
}

/** Abre no navegador do Mac. */
export async function openExternal(url: string): Promise<void> {
  if (inTauri()) await call("open_external", { url });
  else window.open(url, "_blank", "noopener");
}

/** Assina um evento vindo do lado nativo; devolve a função para cancelar. */
export async function onBrowserEvent<T>(name: string, handler: (payload: T) => void): Promise<() => void> {
  if (!inTauri()) return () => undefined;
  const { listen } = await import("@tauri-apps/api/event");
  return listen<T>(name, (event) => handler(event.payload));
}

/** "localhost:3000" → http://…; "exemplo.com" → https://…; frase → busca. */
export function normalizeUrl(input: string): string {
  const text = input.trim();
  if (!text) return "about:blank";
  if (/^(https?|file|about):/i.test(text)) return text;
  if (/^(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:\d+)?(\/.*)?$/i.test(text) || /^[\w.-]+\.local(:\d+)?(\/.*)?$/i.test(text)) {
    return `http://${text}`;
  }
  if (/^:\d+(\/.*)?$/.test(text)) return `http://localhost${text}`;
  if (!/\s/.test(text) && /^[\w-]+(\.[\w-]+)+(:\d+)?(\/.*)?$/.test(text)) return `https://${text}`;
  return `https://www.google.com/search?q=${encodeURIComponent(text)}`;
}

/** Texto que vai para a barra de entrada do agente quando você escolhe um elemento. */
export function describePick(pick: DesignPick, root: string | null): string {
  const where = pick.url.replace(/^https?:\/\//, "");
  const lines = [`No navegador (${where}), este elemento:`];
  if (pick.source.components.length) lines.push(`- componente: ${pick.source.components.join(" ‹ ")}`);
  if (pick.source.file) {
    let file = String(pick.source.file);
    if (root && file.startsWith(root)) file = file.slice(root.length).replace(/^\//, "");
    const line = pick.source.line ? (pick.source.approx ? ` (perto da linha ${pick.source.line})` : `:${pick.source.line}`) : "";
    lines.push(`- arquivo: ${file}${line}`);
  }
  lines.push(`- seletor: ${pick.selector}`);
  if (pick.text) lines.push(`- texto: "${pick.text.slice(0, 160)}"`);
  lines.push(`- tamanho: ${pick.size} em (${pick.position})`);
  if (pick.styles.length) lines.push(`- estilo: ${pick.styles.join("; ")}`);
  lines.push("- HTML:", "```html", pick.html, "```");
  lines.push("O que mudar: ");
  return lines.join("\n");
}
