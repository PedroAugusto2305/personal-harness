// Quadros (v0.9.1): o .canvas do Obsidian (JSON Canvas 1.0, jsoncanvas.org) visto pela MÊTIS.
// Os cartões da MÊTIS (sessão, tarefa) são nós "text": Markdown legível no Obsidian e, no fim,
// um comentário `%%metis {...}%%` (o Obsidian esconde) com o BoardCardMeta em JSON.

import type { BoardCardMeta, CanvasDoc, CanvasEdge, CanvasNode, CanvasSide, KanbanTask, TaskState } from "../types";
import { KIND_GLYPH, shortPath } from "./format";

const MARK = "%%metis";

/** Separa o texto do cartão do `%%metis {...}%%` do fim. Sem marca (ou com JSON torto) é nota solta. */
export function parseMeta(text: string | undefined): { meta: BoardCardMeta | null; body: string } {
  const source = text ?? "";
  const at = source.lastIndexOf(MARK);
  if (at < 0) return { meta: null, body: source };
  const tail = source.slice(at + MARK.length).trim();
  if (!tail.endsWith("%%")) return { meta: null, body: source };
  try {
    const value = JSON.parse(tail.slice(0, -2).trim()) as BoardCardMeta;
    if (value && (value.tipo === "sessao" || value.tipo === "tarefa")) return { meta: value, body: source.slice(0, at).trimEnd() };
  } catch {
    // comentário que não é nosso: o texto fica como está
  }
  return { meta: null, body: source };
}

export function withMeta(body: string, meta: BoardCardMeta): string {
  return `${body.trimEnd()}\n\n${MARK} ${JSON.stringify(meta)}%%`;
}

/** Id de 16 caracteres hexadecimais, como os que o Obsidian gera. */
export function newId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

// --- cores --------------------------------------------------------------------------------------

/** As seis cores prontas do Obsidian ("1" vermelho … "6" roxo), puxadas para os tokens do tema. */
export const CANVAS_COLORS: { key: string; label: string; value: string }[] = [
  { key: "1", label: "vermelho", value: "var(--err)" },
  { key: "2", label: "laranja", value: "color-mix(in srgb, var(--err) 55%, var(--g-carreira))" },
  { key: "3", label: "amarelo", value: "var(--g-carreira)" },
  { key: "4", label: "verde", value: "var(--g-brain)" },
  { key: "5", label: "ciano", value: "var(--run)" },
  { key: "6", label: "roxo", value: "var(--wait)" },
];

export function colorOf(color: string | undefined): string | undefined {
  if (!color) return undefined;
  const preset = CANVAS_COLORS.find((c) => c.key === color);
  if (preset) return preset.value;
  return /^#[0-9a-f]{3,8}$/i.test(color) ? color : undefined;
}

// --- tipos de cartão ------------------------------------------------------------------------------

export type CardKind = "nota" | "anexo" | "sessao" | "tarefa" | "link" | "sticky" | "grupo";

export type SessionMeta = Extract<BoardCardMeta, { tipo: "sessao" }>;
export type TaskMeta = Extract<BoardCardMeta, { tipo: "tarefa" }>;

export function cardKind(node: CanvasNode): CardKind {
  if (node.type === "group") return "grupo";
  if (node.type === "link") return "link";
  if (node.type === "file") return (node.file ?? "").toLowerCase().endsWith(".md") ? "nota" : "anexo";
  const { meta } = parseMeta(node.text);
  if (meta?.tipo === "sessao") return "sessao";
  if (meta?.tipo === "tarefa") return "tarefa";
  return "sticky";
}

export function sessionMetaOf(node: CanvasNode | undefined): SessionMeta | null {
  if (!node || node.type !== "text") return null;
  const { meta } = parseMeta(node.text);
  return meta?.tipo === "sessao" ? meta : null;
}

export function taskMetaOf(node: CanvasNode | undefined): TaskMeta | null {
  if (!node || node.type !== "text") return null;
  const { meta } = parseMeta(node.text);
  return meta?.tipo === "tarefa" ? meta : null;
}

export const isNote = (node: CanvasNode | undefined) => !!node && node.type === "file" && (node.file ?? "").toLowerCase().endsWith(".md");

/** Texto do cartão de sessão: legível no Obsidian, com o meta escondido no fim. */
export function sessionText(meta: SessionMeta): string {
  return withMeta(`${KIND_GLYPH[meta.kind]} **${meta.titulo}** · \`${shortPath(meta.cwd)}\`\n\nSessão da MÊTIS: abre no app.`, meta);
}

export function taskText(meta: TaskMeta, task: KanbanTask): string {
  const box = task.state === "concluida" ? "[x]" : "[ ]";
  return withMeta(`**Tarefa** · ${meta.projeto}\n\n- ${box} ${task.text}\n\nTarefa do kanban da MÊTIS.`, meta);
}

export const TASK_STATE: Record<TaskState, { label: string; color: string }> = {
  pendente: { label: "pendente", color: "var(--fnt)" },
  "em-andamento": { label: "em andamento", color: "var(--run)" },
  "em-teste": { label: "em teste", color: "var(--wait)" },
  concluida: { label: "concluída", color: "var(--acc)" },
};

/** Tamanho de cada cartão novo. */
export const CARD_SIZE: Record<CardKind, { width: number; height: number }> = {
  nota: { width: 340, height: 220 },
  anexo: { width: 280, height: 110 },
  sessao: { width: 420, height: 330 },
  tarefa: { width: 280, height: 150 },
  link: { width: 380, height: 136 },
  sticky: { width: 280, height: 150 },
  grupo: { width: 560, height: 380 },
};

// --- links --------------------------------------------------------------------------------------

export function linkInfo(url: string): { host: string; path: string; local: boolean; clickup: boolean } {
  try {
    const parsed = new URL(url);
    const host = parsed.host;
    const path = `${parsed.pathname === "/" ? "" : parsed.pathname}${parsed.search}${parsed.hash}`;
    const local = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1";
    const clickup = /(^|\.)clickup\.com$/i.test(parsed.hostname) || /(^|\.)cu\.page$/i.test(parsed.hostname);
    return { host, path, local, clickup };
  } catch {
    return { host: url, path: "", local: false, clickup: false };
  }
}

/** O que o Pedro digitou → endereço com esquema (localhost vira http, o resto https). */
export function normalizeUrl(input: string): string {
  const text = input.trim();
  if (!text) return "";
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(text) || /^about:/i.test(text)) return text;
  if (/^(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(text)) return `http://${text}`;
  return `https://${text}`;
}

export const looksLikeUrl = (text: string) => /^(https?:\/\/|localhost(:\d+)?(\/|$)|127\.0\.0\.1)/i.test(text.trim()) && !/\s/.test(text.trim());

// --- geometria ------------------------------------------------------------------------------------

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

const NORMAL: Record<CanvasSide, Point> = { top: { x: 0, y: -1 }, right: { x: 1, y: 0 }, bottom: { x: 0, y: 1 }, left: { x: -1, y: 0 } };

export function anchor(r: Rect, side: CanvasSide): Point {
  if (side === "top") return { x: r.x + r.width / 2, y: r.y };
  if (side === "bottom") return { x: r.x + r.width / 2, y: r.y + r.height };
  if (side === "left") return { x: r.x, y: r.y + r.height / 2 };
  return { x: r.x + r.width, y: r.y + r.height / 2 };
}

/** Os lados que se olham, quando a ligação não diz quais. */
export function bestSides(a: Rect, b: Rect): [CanvasSide, CanvasSide] {
  const dx = b.x + b.width / 2 - (a.x + a.width / 2);
  const dy = b.y + b.height / 2 - (a.y + a.height / 2);
  if (Math.abs(dx) / (a.width + b.width) >= Math.abs(dy) / (a.height + b.height)) return dx >= 0 ? ["right", "left"] : ["left", "right"];
  return dy >= 0 ? ["bottom", "top"] : ["top", "bottom"];
}

/** O lado do cartão mais perto de um ponto (onde a ligação arrastada foi solta). */
export function nearestSide(r: Rect, p: Point): CanvasSide {
  const d: [CanvasSide, number][] = [
    ["top", Math.abs(p.y - r.y)],
    ["bottom", Math.abs(p.y - (r.y + r.height))],
    ["left", Math.abs(p.x - r.x)],
    ["right", Math.abs(p.x - (r.x + r.width))],
  ];
  return d.sort((m, n) => m[1] - n[1])[0][0];
}

/** Curva entre dois lados, saindo e chegando na perpendicular, e o ponto do meio (para o rótulo). */
export function curve(a: Point, sa: CanvasSide, b: Point, sb: CanvasSide | null): { d: string; mid: Point } {
  const k = Math.max(36, Math.min(180, Math.hypot(b.x - a.x, b.y - a.y) * 0.4));
  const c1 = { x: a.x + NORMAL[sa].x * k, y: a.y + NORMAL[sa].y * k };
  const c2 = sb ? { x: b.x + NORMAL[sb].x * k, y: b.y + NORMAL[sb].y * k } : b;
  return {
    d: `M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${b.x},${b.y}`,
    mid: { x: (a.x + 3 * c1.x + 3 * c2.x + b.x) / 8, y: (a.y + 3 * c1.y + 3 * c2.y + b.y) / 8 },
  };
}

export function edgeGeometry(edge: CanvasEdge, from: Rect, to: Rect) {
  const [fs, ts] = bestSides(from, to);
  const fromSide = edge.fromSide ?? fs;
  const toSide = edge.toSide ?? ts;
  return curve(anchor(from, fromSide), fromSide, anchor(to, toSide), toSide);
}

const GAP = 24;

/** Um lugar livre perto de (cx, cy) para um cartão w × h: anda em anéis até não encostar em ninguém. */
export function placeFree(nodes: CanvasNode[], cx: number, cy: number, w: number, h: number, isGroup = false): Point {
  const obstacles = nodes.filter((n) => isGroup || n.type !== "group");
  const free = (x: number, y: number) =>
    !obstacles.some((n) => x < n.x + n.width + GAP && x + w + GAP > n.x && y < n.y + n.height + GAP && y + h + GAP > n.y);
  const x0 = Math.round(cx - w / 2);
  const y0 = Math.round(cy - h / 2);
  if (free(x0, y0)) return { x: x0, y: y0 };
  const step = 40;
  for (let ring = 1; ring <= 60; ring++) {
    const spots: Point[] = [];
    for (let i = -ring; i <= ring; i++) {
      spots.push({ x: i, y: -ring }, { x: i, y: ring });
      if (i > -ring && i < ring) spots.push({ x: -ring, y: i }, { x: ring, y: i });
    }
    spots.sort((p, q) => Math.hypot(p.x, p.y * 1.4) - Math.hypot(q.x, q.y * 1.4));
    for (const s of spots) {
      const x = x0 + s.x * step;
      const y = y0 + s.y * step;
      if (free(x, y)) return { x, y };
    }
  }
  const right = Math.max(0, ...obstacles.map((n) => n.x + n.width));
  return { x: right + GAP * 2, y: y0 };
}

export function boundsOf(nodes: Rect[]): Rect | null {
  if (!nodes.length) return null;
  const minX = Math.min(...nodes.map((n) => n.x));
  const minY = Math.min(...nodes.map((n) => n.y));
  const maxX = Math.max(...nodes.map((n) => n.x + n.width));
  const maxY = Math.max(...nodes.map((n) => n.y + n.height));
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

export const inside = (inner: Rect, outer: Rect) =>
  inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.width <= outer.x + outer.width && inner.y + inner.height <= outer.y + outer.height;

/** Ligações nota do Brain ↔ sessão: os "precedentes ligados" do rodapé. */
export function contextEdges(doc: CanvasDoc): CanvasEdge[] {
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  return doc.edges.filter((e) => {
    const a = byId.get(e.fromNode);
    const b = byId.get(e.toNode);
    // Só conta o que virou contexto de fato: Claude ou Codex (no shell a ligação é só desenho).
    const session = sessionMetaOf(isNote(a) ? b : a);
    return (isNote(a) || isNote(b)) && !!session && session.kind !== "shell";
  });
}

/** "01-PROJETOS/Alfa/decisoes/X.md" → "Alfa / decisoes". */
export function notePlace(path: string, projeto?: string): string {
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "01-PROJETOS") parts.shift();
  parts.pop();
  return parts.length ? parts.join(" / ") : projeto || "Brain";
}

export const fileName = (path: string) => (path.split("/").pop() ?? path).replace(/\.md$/i, "");
