/**
 * Atalhos remapeáveis (v0.9.3).
 *
 * Cada ação tem um padrão; o que o Pedro muda fica em ~/.harness/atalhos.json (só as
 * sobrescritas, legível à mão: {"dividir.baixo": "Meta+Shift+KeyD"}; "" desliga).
 * O atalho é guardado pela tecla física (KeyboardEvent.code) com os modificadores na ordem
 * Meta, Ctrl, Alt, Shift: o ⌥ do Mac troca o caractere (⌥D vira "∂") e o ⇧ troca a
 * pontuação, mas o code não muda. No teclado Brasileiro – Pro os colchetes e a crase
 * ficam onde estão no americano, então os rótulos abaixo batem com o que está impresso.
 */

export interface ActionDef {
  id: string;
  label: string;
  group: string;
  combo: string;
}

export const ACTIONS: ActionDef[] = [
  { id: "paleta", group: "Geral", label: "Salto rápido: abas e ações", combo: "Meta+KeyK" },
  { id: "pular", group: "Geral", label: "Pular para: recentes, worktrees e telas", combo: "Meta+KeyJ" },
  { id: "comandos", group: "Geral", label: "Comandos salvos", combo: "Meta+Shift+KeyK" },
  { id: "arquivo", group: "Geral", label: "Abrir arquivo da worktree", combo: "Meta+KeyP" },
  { id: "ajustes", group: "Geral", label: "Ajustes", combo: "Meta+Comma" },
  { id: "painel", group: "Geral", label: "Painel da worktree", combo: "Meta+Shift+KeyB" },
  { id: "flutuante", group: "Geral", label: "Terminal flutuante", combo: "Ctrl+Backquote" },
  { id: "barra", group: "Terminal", label: "Ir para a barra de entrada (no navegador, o endereço)", combo: "Meta+KeyL" },
  { id: "ditar", group: "Terminal", label: "Ditar / parar", combo: "Meta+Shift+KeyM" },
  { id: "buscar", group: "Terminal", label: "Buscar no terminal", combo: "Meta+KeyF" },
  { id: "dividir.direita", group: "Divisão", label: "Dividir à direita", combo: "Meta+KeyD" },
  { id: "dividir.baixo", group: "Divisão", label: "Dividir para baixo", combo: "Meta+Shift+KeyD" },
  { id: "dividir.fechar", group: "Divisão", label: "Tirar o painel da divisão", combo: "Meta+Shift+KeyW" },
  { id: "dividir.juntar", group: "Divisão", label: "Juntar tudo num painel", combo: "" },
  { id: "foco.esquerda", group: "Divisão", label: "Painel à esquerda", combo: "Meta+Alt+ArrowLeft" },
  { id: "foco.direita", group: "Divisão", label: "Painel à direita", combo: "Meta+Alt+ArrowRight" },
  { id: "foco.cima", group: "Divisão", label: "Painel de cima", combo: "Meta+Alt+ArrowUp" },
  { id: "foco.baixo", group: "Divisão", label: "Painel de baixo", combo: "Meta+Alt+ArrowDown" },
  { id: "web.recarregar", group: "Navegador", label: "Recarregar a página", combo: "Meta+KeyR" },
  { id: "web.voltar", group: "Navegador", label: "Voltar", combo: "Meta+BracketLeft" },
  { id: "web.avancar", group: "Navegador", label: "Avançar", combo: "Meta+BracketRight" },
];

/** Atalhos que não mudam: listados na tela, mas fora do arquivo. */
export const FIXED: [string, string][] = [
  ["⌘1 … ⌘9", "Ir para a aba"],
  ["Esc", "Fechar a busca, a paleta ou a gravação"],
  ["⌥Espaço", "Captura rápida, de qualquer app"],
];

/** Do macOS: não dá para tomar (o sistema ou o menu do app pegam antes). */
const RESERVED = new Set(["Meta+KeyQ", "Meta+KeyH", "Meta+KeyM", "Meta+KeyC", "Meta+KeyV", "Meta+KeyX", "Meta+KeyA", "Meta+KeyZ", "Meta+Shift+KeyZ", "Meta+KeyW", "Meta+Tab", "Meta+Space", "Ctrl+Meta+KeyF", "Meta+Alt+KeyH"]);

const MODIFIER_CODES = new Set(["MetaLeft", "MetaRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight", "ShiftLeft", "ShiftRight", "CapsLock", "Fn"]);

interface KeyLike {
  code: string;
  key?: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}

/** "Meta+Shift+KeyD" de um evento; null para tecla de modificador sozinha. */
export function comboOf(event: KeyLike): string | null {
  if (!event.code || MODIFIER_CODES.has(event.code)) return null;
  const parts: string[] = [];
  if (event.metaKey) parts.push("Meta");
  if (event.ctrlKey) parts.push("Ctrl");
  if (event.altKey) parts.push("Alt");
  if (event.shiftKey) parts.push("Shift");
  parts.push(event.code);
  return parts.join("+");
}

const CODE_LABEL: Record<string, string> = {
  Comma: ",",
  Period: ".",
  Slash: "/",
  Backslash: "\\",
  Semicolon: ";",
  Quote: "'",
  Backquote: "`",
  BracketLeft: "[",
  BracketRight: "]",
  Minus: "-",
  Equal: "=",
  IntlBackslash: "§",
  ArrowLeft: "←",
  ArrowRight: "→",
  ArrowUp: "↑",
  ArrowDown: "↓",
  Space: "Espaço",
  Enter: "↵",
  Escape: "Esc",
  Tab: "⇥",
  Backspace: "⌫",
  Delete: "⌦",
  PageUp: "PgUp",
  PageDown: "PgDn",
  Home: "Home",
  End: "End",
};

/** "Meta+Shift+KeyD" → "⌘⇧D" (na ordem do Mac: ⌃⌥⇧⌘). */
export function formatCombo(combo: string): string {
  if (!combo) return "—";
  const parts = combo.split("+");
  const code = parts.pop() ?? "";
  const mods = new Set(parts);
  const key = /^Key[A-Z]$/.test(code)
    ? code.slice(3)
    : /^Digit\d$/.test(code)
      ? code.slice(5)
      : /^Numpad\d$/.test(code)
        ? code.slice(6)
        : (CODE_LABEL[code] ?? code);
  return `${mods.has("Ctrl") ? "⌃" : ""}${mods.has("Alt") ? "⌥" : ""}${mods.has("Shift") ? "⇧" : ""}${mods.has("Meta") ? "⌘" : ""}${key}`;
}

export type Overrides = Record<string, string>;

/** Atalho em vigor de cada ação: o padrão com as sobrescritas do arquivo por cima. */
export function effective(overrides: Overrides): Record<string, string> {
  return Object.fromEntries(ACTIONS.map((a) => [a.id, a.id in overrides ? overrides[a.id] : a.combo]));
}

/** Atalho → ação (só os ligados). Se dois apontam para o mesmo, vale o primeiro da lista. */
export function bindings(overrides: Overrides): Map<string, string> {
  const map = new Map<string, string>();
  for (const [id, combo] of Object.entries(effective(overrides))) if (combo && !map.has(combo)) map.set(combo, id);
  return map;
}

/** Por que o atalho não serve (ou null): sem modificador, reservado do macOS ou ⌘ e número. */
export function comboProblem(combo: string): string | null {
  const parts = combo.split("+");
  const code = parts[parts.length - 1];
  const mods = parts.slice(0, -1);
  const free = /^F\d{1,2}$/.test(code);
  if (!mods.length && !free) return "Use pelo menos um modificador (⌘, ⌃ ou ⌥), ou uma tecla F.";
  if (mods.length === 1 && mods[0] === "Shift" && !free) return "Só ⇧ escreve letra maiúscula: junte ⌘, ⌃ ou ⌥.";
  if (RESERVED.has(combo)) return `${formatCombo(combo)} é do macOS ou do menu do app.`;
  if (mods.length === 1 && mods[0] === "Meta" && /^Digit[1-9]$/.test(code)) return "⌘1 a ⌘9 são das abas.";
  return null;
}

/** As sobrescritas que mudam algo (igual ao padrão não vai para o arquivo). */
export function compact(overrides: Overrides): Overrides {
  const defaults = Object.fromEntries(ACTIONS.map((a) => [a.id, a.combo]));
  return Object.fromEntries(Object.entries(overrides).filter(([id, combo]) => id in defaults && defaults[id] !== combo));
}

/** Rótulo do atalho de uma ação, para dicas ("⌘D"); vazio se desligado. */
export function hintFor(overrides: Overrides, id: string): string {
  const combo = effective(overrides)[id];
  return combo ? formatCombo(combo) : "";
}

/** Ajustes → Atalhos gravando uma tecla: os atalhos da janela param enquanto isso. */
export const recorder = { active: false };
