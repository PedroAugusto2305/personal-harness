// Aparência da MÊTIS (v0.9.8, parte 2): temas feitos por prompt ou importados do VS Code e
// do Obsidian, fontes, densidade e zoom. Tudo isso é da tela: fica no armazenamento dela,
// como o tema; os temas novos moram no núcleo (~/.harness/temas) porque é ele que os gera.
import { appZoom } from "./browser";
import { APP_COLOR_KEYS, type AppTheme, type ThemeName } from "../types";

export const BUILTIN_THEMES: ThemeName[] = ["dracula", "grafite", "claro"];
const BUILTIN_LABEL: Record<string, string> = { dracula: "Drácula azul", grafite: "Grafite", claro: "Claro" };

/** Temas do núcleo conhecidos agora (o App atualiza quando a lista chega ou muda). */
let customs: AppTheme[] = [];
export function setCustomThemes(list: AppTheme[]): void {
  customs = list;
}
export function customThemes(): AppTheme[] {
  return customs;
}

export const themeKey = (theme: AppTheme): ThemeName => `tema:${theme.id}`;
export function customOf(theme: ThemeName): AppTheme | null {
  return theme.startsWith("tema:") ? (customs.find((t) => t.id === theme.slice(5)) ?? null) : null;
}

export function themeLabel(theme: ThemeName): string {
  return BUILTIN_LABEL[theme] ?? customOf(theme)?.nome ?? "Tema apagado";
}

/** Claro ou escuro: decide as cores ANSI do terminal e o tema do editor. */
export function themeIsLight(theme: ThemeName): boolean {
  if (theme === "claro") return true;
  return customOf(theme)?.base === "claro";
}

function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/**
 * Põe o tema na raiz. Os três da MÊTIS são blocos do CSS; o feito por prompt ou importado
 * entra por cima do Drácula (ou do Claro), cor por cor, então o que ele não define (as
 * nuvens do grafo do Brain) vem do tema de base.
 */
export function applyTheme(theme: ThemeName): void {
  const root = document.documentElement;
  const custom = customOf(theme);
  for (const key of APP_COLOR_KEYS) root.style.removeProperty(`--${key}`);
  root.style.removeProperty("--soft");
  if (!custom) {
    root.dataset.theme = BUILTIN_LABEL[theme] ? theme : "dracula";
    return;
  }
  root.dataset.theme = custom.base === "claro" ? "claro" : "dracula";
  for (const key of APP_COLOR_KEYS) {
    const value = custom.cores[key];
    if (value) root.style.setProperty(`--${key}`, value);
  }
  const rgb = hexToRgb(custom.cores.acc);
  if (rgb) root.style.setProperty("--soft", `rgba(${rgb.join(", ")}, ${custom.base === "claro" ? 0.14 : 0.16})`);
}

// --- fontes, densidade e zoom -------------------------------------------------------------

export type Density = "compacta" | "normal" | "confortavel";

export interface Appearance {
  /** Fonte da interface (valor de font-family). */
  ui: string;
  /** Fonte mono: terminal, editores, código. */
  mono: string;
  /** Tamanho da letra do terminal, em px. */
  termSize: number;
  density: Density;
  /** Zoom da janela inteira (1 = 100%). */
  zoom: number;
}

export const DEFAULT_APPEARANCE: Appearance = {
  ui: "Inter",
  mono: "Fira Code",
  termSize: 13,
  density: "normal",
  zoom: 1,
};

/** Fontes oferecidas. As que vêm com a MÊTIS sempre existem; as outras só se o Mac tiver. */
export const UI_FONTS: { nome: string; valor: string; embutida?: boolean }[] = [
  { nome: "Inter (padrão)", valor: "Inter", embutida: true },
  { nome: "SF Pro (a do macOS)", valor: "-apple-system", embutida: true },
  { nome: "Helvetica Neue", valor: "Helvetica Neue" },
  { nome: "Avenir Next", valor: "Avenir Next" },
  { nome: "IBM Plex Sans", valor: "IBM Plex Sans" },
];

export const MONO_FONTS: { nome: string; valor: string; embutida?: boolean }[] = [
  { nome: "Fira Code (padrão)", valor: "Fira Code", embutida: true },
  { nome: "SF Mono", valor: "SF Mono" },
  { nome: "Menlo", valor: "Menlo", embutida: true },
  { nome: "Monaco", valor: "Monaco" },
  { nome: "JetBrains Mono", valor: "JetBrains Mono" },
  { nome: "Cascadia Code", valor: "Cascadia Code" },
  { nome: "Source Code Pro", valor: "Source Code Pro" },
  { nome: "IBM Plex Mono", valor: "IBM Plex Mono" },
  { nome: "Hack", valor: "Hack" },
];

/** A fonte existe neste Mac? (mede um texto com ela e com as fontes de reserva). */
export function fontInstalled(name: string): boolean {
  if (name === "-apple-system") return true;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  const sample = "mmmmmmmmmmlli1WQ@#{}";
  return ["monospace", "serif", "sans-serif"].some((fallback) => {
    ctx.font = `32px ${fallback}`;
    const base = ctx.measureText(sample).width;
    ctx.font = `32px "${name}", ${fallback}`;
    return ctx.measureText(sample).width !== base;
  });
}

const quoted = (name: string) => (name.startsWith("-") ? name : `"${name}"`);
export const uiFamily = (a: Appearance) => `${quoted(a.ui)}, Inter, system-ui, sans-serif`;
export const monoFamily = (a: Appearance) => `${quoted(a.mono)}, "Fira Code", ui-monospace, monospace`;

export function loadAppearance(): Appearance {
  try {
    const raw = localStorage.getItem("harness.aparencia");
    const value = raw ? (JSON.parse(raw) as Partial<Appearance>) : {};
    return { ...DEFAULT_APPEARANCE, ...value };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function saveAppearance(value: Appearance): void {
  try {
    localStorage.setItem("harness.aparencia", JSON.stringify(value));
  } catch {
    // sem armazenamento: vale até fechar
  }
}

/** Fontes e densidade na raiz; o zoom vai para a janela (o WebKit escala tudo, inclusive o navegador). */
export function applyAppearance(value: Appearance, native: boolean): void {
  const root = document.documentElement;
  root.style.setProperty("--ui-font", uiFamily(value));
  root.style.setProperty("--mono", monoFamily(value));
  root.dataset.density = value.density;
  if (native) void appZoom.set(value.zoom).catch(() => undefined);
  else root.style.setProperty("zoom", String(value.zoom));
}

export const ZOOM_STEPS = [0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.5];
export function nextZoom(current: number, direction: 1 | -1): number {
  if (direction > 0) return ZOOM_STEPS.find((z) => z > current + 0.001) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1];
  return [...ZOOM_STEPS].reverse().find((z) => z < current - 0.001) ?? ZOOM_STEPS[0];
}
