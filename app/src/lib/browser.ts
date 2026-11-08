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

export const browser = {
  available: inTauri,
  open: (label: string, url: string, rect: Rect, incognito = false) => call("browser_open", { label, url, incognito, ...rect }),
  bounds: (label: string, rect: Rect) => call("browser_bounds", { label, ...rect }),
  visible: (label: string, visible: boolean) => call("browser_visible", { label, visible }),
  navigate: (label: string, url: string) => call("browser_navigate", { label, url }),
  go: (label: string, action: "back" | "forward" | "reload" | "stop" | "devtools" | "focus") => call("browser_go", { label, action }),
  design: (label: string, on: boolean) => call("browser_design", { label, on }),
  close: (label: string) => call("browser_close", { label }),
};

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
