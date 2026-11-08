import { useMemo } from "react";
import type { CoreClient } from "../lib/core";
import type { Agent } from "../types";

/** Hash simples e estável do nome, para o desenho padrão não mudar entre aberturas. */
function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function darken(hex: string, factor = 0.68): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const part = (shift: number) => Math.round(((n >> shift) & 255) * factor);
  return `rgb(${part(16)}, ${part(8)}, ${part(0)})`;
}

// Busto 16 × 16, de frente. Letras viram cores na paleta abaixo.
const BUST = [
  "................",
  "................",
  "......oooo......",
  ".....ohhhho.....",
  "....ohhhhhho....",
  "....ohssssho....",
  "....oseSSeso....",
  "....osssssso....",
  "....ossmmsso....",
  ".....osssso.....",
  "......oSSo......",
  "..oowwwwwwwwoo..",
  ".owwwwwwwwwwwwo.",
  ".owwwWwwwwWwwwo.",
  "owwwwWwwwwWwwwwo",
  "owwwwWwwwwWwwwwo",
];

type Patch = [row: number, col: number, code: string][];
const span = (row: number, from: number, to: number, code: string): Patch =>
  Array.from({ length: to - from + 1 }, (_, i) => [row, from + i, code] as [number, number, string]);

// Manto (clâmide) no ombro, preso por uma fíbula de ouro, e a faixa da toga na cor do agente.
const CLOAK: Patch = [
  [11, 4, "c"], [11, 5, "g"], [11, 6, "c"],
  ...span(12, 2, 5, "c"), [12, 6, "C"],
  [13, 1, "c"], [13, 2, "C"], [13, 5, "c"], [13, 6, "c"], [13, 7, "C"],
  [14, 1, "c"], [14, 2, "C"], [14, 7, "c"], [14, 8, "c"], [14, 9, "C"],
  [15, 1, "c"], [15, 2, "C"], [15, 9, "c"], [15, 10, "c"], [15, 11, "C"],
];

const HEADGEAR: Record<string, Patch> = {
  // Coroa de louros dourada.
  louros: [
    [2, 6, "G"], [2, 9, "G"], [3, 5, "g"], [3, 10, "g"],
    [4, 4, "g"], [4, 5, "G"], [4, 10, "G"], [4, 11, "g"], [5, 4, "g"], [5, 11, "g"],
  ],
  // Elmo coríntio de bronze, com crista na cor do agente.
  elmo: [
    ...span(0, 6, 9, "c"), [1, 5, "c"], ...span(1, 6, 9, "c"), [1, 10, "C"],
    ...span(2, 6, 9, "b"), ...span(3, 5, 10, "b"), [3, 5, "B"], ...span(4, 5, 10, "b"), [4, 5, "B"],
    [5, 5, "b"], [5, 10, "b"], [5, 7, "B"], [5, 8, "B"],
    [6, 5, "b"], [6, 10, "b"], [6, 7, "B"], [6, 8, "B"],
    [7, 5, "b"], [7, 10, "b"], [8, 5, "B"], [8, 10, "B"],
  ],
  // Diadema de ouro com uma pedra na cor do agente.
  diadema: [...span(4, 5, 10, "g"), [4, 7, "c"], [4, 8, "c"]],
  // Véu de vestal na cor do agente.
  veu: [
    ...span(2, 6, 9, "c"), ...span(3, 5, 10, "c"), ...span(4, 5, 10, "c"), [4, 5, "C"], [4, 10, "C"],
    [5, 5, "c"], [5, 10, "c"], [6, 4, "c"], [6, 11, "c"], [7, 4, "c"], [7, 11, "c"],
    [8, 4, "C"], [8, 11, "C"], [9, 4, "c"], [9, 11, "c"], [10, 4, "c"], [10, 5, "C"], [10, 10, "C"], [10, 11, "c"],
  ],
  // Só o cabelo: o filósofo.
  nada: [],
};

const BEARD: Record<string, Patch> = {
  nenhuma: [],
  curta: [[8, 5, "h"], [8, 10, "h"], ...span(9, 6, 9, "h")],
  longa: [[8, 5, "h"], [8, 10, "h"], ...span(9, 6, 9, "h"), ...span(10, 6, 9, "h"), ...span(11, 6, 9, "H"), [12, 7, "H"], [12, 8, "H"]],
};

const SKINS = ["#f1c7a1", "#e2a979", "#c88956", "#8f5b3c"];
const HAIRS = ["#2b1d14", "#5a3a22", "#a8743c", "#cfc9bf"];

/** A sprite padrão: um busto greco-romano desenhado a partir do nome, na cor do agente. */
export function GreekBust({ seed, color, size = 32 }: { seed: string; color: string; size?: number }) {
  const cells = useMemo(() => {
    const bits = hash(seed);
    const gear = Object.keys(HEADGEAR)[bits % 5];
    const skin = SKINS[(bits >>> 3) % SKINS.length];
    const hairColor = HAIRS[(bits >>> 6) % HAIRS.length];
    const beardKey = gear === "veu" ? "nenhuma" : gear === "elmo" ? (["nenhuma", "curta"] as const)[(bits >>> 9) % 2] : (["nenhuma", "curta", "longa"] as const)[(bits >>> 9) % 3];
    const palette: Record<string, string> = {
      o: "#1c1828",
      e: "#1c1828",
      s: skin,
      S: darken(skin, 0.86),
      m: darken(skin, 0.62),
      h: hairColor,
      H: darken(hairColor, 0.8),
      w: "#ece6d8",
      W: "#c9c0ad",
      c: color,
      C: darken(color),
      g: "#e2b44c",
      G: "#a87b2c",
      b: "#c58a42",
      B: "#8a5a28",
    };
    const grid = BUST.map((row) => row.split(""));
    for (const [r, c, code] of [...CLOAK, ...BEARD[beardKey], ...HEADGEAR[gear]]) grid[r][c] = code;
    const out: { x: number; y: number; fill: string }[] = [];
    grid.forEach((row, y) => row.forEach((code, x) => code !== "." && out.push({ x, y, fill: palette[code] })));
    return out;
  }, [seed, color]);

  return (
    <svg className="pixel" width={size} height={size} viewBox="0 0 16 16" shapeRendering="crispEdges" aria-hidden="true">
      {cells.map((cell) => (
        <rect key={`${cell.x}-${cell.y}`} x={cell.x} y={cell.y} width="1.02" height="1.02" fill={cell.fill} />
      ))}
    </svg>
  );
}

/** Mantido para quem ainda importa o nome antigo. */
export const PixelAvatar = GreekBust;

/** Estados animados do DESIGN.md: código por cima da sprite parada, o personagem nunca muda de cara. */
export type SpriteState = "idle" | "working" | "waiting" | "sleeping" | "done" | "error";

export function spriteState(session: { status: string; exit_code: number | null }): SpriteState {
  if (session.status === "working") return "working";
  if (session.status === "waiting") return "waiting";
  if (session.status === "exited") return session.exit_code ? "error" : "done";
  return "idle";
}

export function AgentSprite({ agent, client, size = 32, state }: { agent: Agent; client: CoreClient | null; size?: number; state?: SpriteState }) {
  const figure = <AgentFigure agent={agent} client={client} size={size} />;
  if (!state) return figure;
  return (
    <span className="sprite-anim" data-state={state} style={{ ["--s" as string]: `${size}px` }} title={STATE_TITLE[state]}>
      {figure}
    </span>
  );
}

const STATE_TITLE: Record<SpriteState, string> = {
  idle: "parado",
  working: "trabalhando",
  waiting: "esperando você",
  sleeping: "dormindo",
  done: "concluiu",
  error: "erro",
};

function AgentFigure({ agent, client, size }: { agent: Agent; client: CoreClient | null; size: number }) {
  if (agent.sprite && client) {
    return (
      <img
        className="pixel sprite-img"
        src={client.spriteUrl(agent.id, agent.updated_at)}
        width={size}
        height={size}
        alt=""
        draggable={false}
      />
    );
  }
  return <GreekBust seed={agent.id + agent.name} color={agent.color} size={size} />;
}
