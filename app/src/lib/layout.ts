/**
 * Divisão da tela em árvore (v0.9.3): cada worktree guarda a sua.
 *
 * A tela de uma worktree é uma árvore de painéis: a folha mostra uma aba (ou fica vazia,
 * com os botões de abrir), e o nó de divisão parte o espaço em dois, lado a lado ("row")
 * ou um em cima do outro ("col"), na proporção `ratio`. Os terminais continuam todos
 * montados; a árvore só diz onde cada um aparece. Tudo aqui é puro, para testar e para o
 * React comparar por referência.
 */

export type PaneNode = PaneLeaf | PaneSplit;

export interface PaneLeaf {
  t: "leaf";
  id: string;
  /** Chave da aba (id da sessão ou "doc:…"); null = painel vazio. */
  tab: string | null;
}

export interface PaneSplit {
  t: "split";
  id: string;
  /** "row": lado a lado; "col": um em cima do outro. */
  dir: "row" | "col";
  /** Fração do primeiro filho (0.12 a 0.88). */
  ratio: number;
  a: PaneNode;
  b: PaneNode;
}

export interface Layout {
  root: PaneNode;
  /** Folha em foco. */
  focus: string;
}

/** Posição em frações do espaço dos painéis (0 a 1). */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type Side = "left" | "right" | "top" | "bottom";
export type Direction = Side;

export const MIN_RATIO = 0.12;
export const MAX_RATIO = 0.88;

let counter = 0;
export const newId = () => `p${Date.now().toString(36)}${(counter++).toString(36)}`;

export const leaf = (tab: string | null): PaneLeaf => ({ t: "leaf", id: newId(), tab });

export function single(tab: string | null): Layout {
  const node = leaf(tab);
  return { root: node, focus: node.id };
}

export function leaves(node: PaneNode): PaneLeaf[] {
  return node.t === "leaf" ? [node] : [...leaves(node.a), ...leaves(node.b)];
}

export function findLeaf(node: PaneNode, id: string): PaneLeaf | null {
  return leaves(node).find((l) => l.id === id) ?? null;
}

export function leafWithTab(node: PaneNode, tab: string): PaneLeaf | null {
  return leaves(node).find((l) => l.tab === tab) ?? null;
}

/** Abas que aparecem na árvore. */
export function visibleTabs(node: PaneNode): string[] {
  return leaves(node)
    .map((l) => l.tab)
    .filter((t): t is string => !!t);
}

function mapLeaves(node: PaneNode, fn: (l: PaneLeaf) => PaneNode): PaneNode {
  if (node.t === "leaf") return fn(node);
  const a = mapLeaves(node.a, fn);
  const b = mapLeaves(node.b, fn);
  return a === node.a && b === node.b ? node : { ...node, a, b };
}

/** Põe a aba na folha; se ela já aparece em outra folha, as duas trocam (a aba nunca aparece duas vezes). */
export function setTab(node: PaneNode, leafId: string, tab: string | null): PaneNode {
  const target = findLeaf(node, leafId);
  if (!target || target.tab === tab) return node;
  const other = tab ? leafWithTab(node, tab) : null;
  return mapLeaves(node, (l) => {
    if (l.id === leafId) return { ...l, tab };
    if (other && l.id === other.id) return { ...l, tab: target.tab };
    return l;
  });
}

/** Troca a aba `from` por `to` onde ela estiver (agente reiniciado nasce no mesmo lugar). */
export function replaceTab(node: PaneNode, from: string, to: string): PaneNode {
  return mapLeaves(node, (l) => (l.tab === from ? { ...l, tab: to } : l));
}

/**
 * Parte a folha em duas: a nova vai para o lado pedido, com a aba dada.
 * Devolve a árvore e o id da folha nova.
 */
export function splitLeaf(node: PaneNode, leafId: string, side: Side, tab: string | null): { root: PaneNode; created: string } {
  const fresh = leaf(tab);
  // Uma aba aparece num lugar só: se ela já está em outra folha, aquela fica vazia.
  const base = tab ? mapLeaves(node, (l) => (l.tab === tab ? { ...l, tab: null } : l)) : node;
  const root = mapLeaves(base, (l) => {
    if (l.id !== leafId) return l;
    const dir = side === "left" || side === "right" ? "row" : "col";
    const first = side === "left" || side === "top";
    return { t: "split", id: newId(), dir, ratio: 0.5, a: first ? fresh : l, b: first ? l : fresh };
  });
  return { root: root === base ? node : root, created: fresh.id };
}

/** Tira a folha; a irmã ocupa o lugar do pai. Com uma folha só, devolve null. */
export function removeLeaf(node: PaneNode, leafId: string): PaneNode | null {
  if (node.t === "leaf") return node.id === leafId ? null : node;
  const a = removeLeaf(node.a, leafId);
  const b = removeLeaf(node.b, leafId);
  if (!a) return b;
  if (!b) return a;
  return a === node.a && b === node.b ? node : { ...node, a, b };
}

export function setRatio(node: PaneNode, splitId: string, ratio: number): PaneNode {
  if (node.t === "leaf") return node;
  if (node.id === splitId) {
    const next = Math.min(MAX_RATIO, Math.max(MIN_RATIO, ratio));
    return next === node.ratio ? node : { ...node, ratio: next };
  }
  const a = setRatio(node.a, splitId, ratio);
  const b = setRatio(node.b, splitId, ratio);
  return a === node.a && b === node.b ? node : { ...node, a, b };
}

/**
 * Tira da árvore as abas que não existem mais. Com mais de uma folha, a folha da aba
 * fechada sai (a irmã cresce); a última folha fica, com a aba de reserva ou vazia.
 */
export function prune(layout: Layout, exists: (tab: string) => boolean, fallback: () => string | null): Layout {
  let root: PaneNode | null = layout.root;
  for (const l of leaves(layout.root)) {
    if (l.tab === null || exists(l.tab)) continue;
    const without: PaneNode | null = root ? removeLeaf(root, l.id) : null;
    root = without ?? { ...l, tab: null };
  }
  if (!root) return single(fallback());
  const all = leaves(root);
  if (all.length === 1 && all[0].tab === null) {
    const tab = fallback();
    if (tab) root = { ...all[0], tab };
  }
  if (root === layout.root) return layout;
  const focus = findLeaf(root, layout.focus) ? layout.focus : leaves(root)[0].id;
  return { root, focus };
}

/** Onde cada folha fica, e onde ficam as divisórias (para arrastar). */
export function measure(node: PaneNode, box: Rect = { x: 0, y: 0, w: 1, h: 1 }) {
  const rects = new Map<string, Rect>();
  const dividers: { id: string; dir: "row" | "col"; box: Rect; ratio: number }[] = [];
  const walk = (n: PaneNode, r: Rect) => {
    if (n.t === "leaf") {
      rects.set(n.id, r);
      return;
    }
    dividers.push({ id: n.id, dir: n.dir, box: r, ratio: n.ratio });
    if (n.dir === "row") {
      const wa = r.w * n.ratio;
      walk(n.a, { x: r.x, y: r.y, w: wa, h: r.h });
      walk(n.b, { x: r.x + wa, y: r.y, w: r.w - wa, h: r.h });
    } else {
      const ha = r.h * n.ratio;
      walk(n.a, { x: r.x, y: r.y, w: r.w, h: ha });
      walk(n.b, { x: r.x, y: r.y + ha, w: r.w, h: r.h - ha });
    }
  };
  walk(node, box);
  return { rects, dividers };
}

const EPS = 1e-6;

/** O painel vizinho na direção pedida (o que mais encosta no atual), para ⌘⌥ e as setas. */
export function neighbor(node: PaneNode, leafId: string, dir: Direction): string | null {
  const { rects } = measure(node);
  const cur = rects.get(leafId);
  if (!cur) return null;
  let best: { id: string; gap: number; overlap: number } | null = null;
  for (const [id, r] of rects) {
    if (id === leafId) continue;
    let gap: number;
    let overlap: number;
    if (dir === "left" || dir === "right") {
      gap = dir === "right" ? r.x - (cur.x + cur.w) : cur.x - (r.x + r.w);
      overlap = Math.min(cur.y + cur.h, r.y + r.h) - Math.max(cur.y, r.y);
    } else {
      gap = dir === "bottom" ? r.y - (cur.y + cur.h) : cur.y - (r.y + r.h);
      overlap = Math.min(cur.x + cur.w, r.x + r.w) - Math.max(cur.x, r.x);
    }
    if (gap < -EPS || overlap <= EPS) continue;
    if (!best || gap < best.gap - EPS || (Math.abs(gap - best.gap) <= EPS && overlap > best.overlap)) best = { id, gap, overlap };
  }
  return best?.id ?? null;
}

/** Parte de um painel sob o ponteiro ao arrastar uma aba: uma borda (dividir) ou o meio (trocar). */
export function dropZone(r: { left: number; top: number; width: number; height: number }, x: number, y: number): Side | "center" {
  const fx = (x - r.left) / r.width;
  const fy = (y - r.top) / r.height;
  const edge = 0.25;
  const near = [
    { side: "left" as const, d: fx },
    { side: "right" as const, d: 1 - fx },
    { side: "top" as const, d: fy },
    { side: "bottom" as const, d: 1 - fy },
  ].sort((p, q) => p.d - q.d)[0];
  return near.d < edge ? near.side : "center";
}

/** Confere o que veio do armazenamento: árvore malformada vira null (a worktree volta ao padrão). */
export function parseLayout(value: unknown): Layout | null {
  const node = (v: unknown, depth: number): PaneNode | null => {
    if (!v || typeof v !== "object" || depth > 12) return null;
    const o = v as Record<string, unknown>;
    if (typeof o.id !== "string") return null;
    if (o.t === "leaf") return { t: "leaf", id: o.id, tab: typeof o.tab === "string" ? o.tab : null };
    if (o.t !== "split" || (o.dir !== "row" && o.dir !== "col") || typeof o.ratio !== "number") return null;
    const a = node(o.a, depth + 1);
    const b = node(o.b, depth + 1);
    if (!a || !b) return null;
    return { t: "split", id: o.id, dir: o.dir, ratio: Math.min(MAX_RATIO, Math.max(MIN_RATIO, o.ratio)), a, b };
  };
  if (!value || typeof value !== "object") return null;
  const o = value as Record<string, unknown>;
  const root = node(o.root, 0);
  if (!root) return null;
  const focus = typeof o.focus === "string" && findLeaf(root, o.focus) ? o.focus : leaves(root)[0].id;
  return { root, focus };
}
