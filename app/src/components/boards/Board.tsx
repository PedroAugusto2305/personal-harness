// O quadro: grade de pontinhos que anda e escala junto (como nas Automações), cartões que se
// arrastam e mudam de tamanho pelo canto, ligações curvas entre os lados com rótulo no meio.
// Arrastar o fundo move, rolar move, ⌘ + rolar dá zoom; arrastar do pontinho do lado de um cartão
// até outro liga os dois; soltar uma nota do Brain em cima de uma sessão vira contexto.

import { useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent as ReactPointerEvent } from "react";
import { ICON, Icon } from "../../icons";
import {
  CANVAS_COLORS,
  type Point,
  type Rect,
  anchor,
  boundsOf,
  cardKind,
  colorOf,
  contextEdges,
  curve,
  edgeGeometry,
  inside,
  isNote,
  nearestSide,
  sessionMetaOf,
  taskMetaOf,
} from "../../lib/canvas";
import type { Agent, BrainHit, CanvasDoc, CanvasNode, CanvasSide, KanbanTask, Session } from "../../types";
import { Card, type CardCtx, type CardHandlers } from "./Cards";

export type Selection = { kind: "node" | "edge"; id: string } | null;

export interface BoardApi {
  /** O meio da tela, em coordenadas do quadro (onde entra um cartão novo). */
  center: () => Point;
  centerOn: (id: string) => void;
  fit: () => void;
}

interface Props {
  doc: CanvasDoc;
  notas: Record<string, BrainHit | null>;
  sessions: Session[];
  agents: Agent[];
  tasks: KanbanTask[] | null;
  selection: Selection;
  editingId: string | null;
  /** O quadro aberto: guarda o zoom e a posição de cada um enquanto o app está aberto. */
  viewKey: string;
  /** Muda quando o quadro deve ser enquadrado (ou voltar à posição lembrada). */
  fitKey: string;
  apiRef: { current: BoardApi | null };
  ctx: CardCtx;
  onSelect: (selection: Selection) => void;
  onEditing: (id: string | null) => void;
  onEdit: (change: (doc: CanvasDoc) => CanvasDoc) => void;
  onConnect: (from: string, fromSide: CanvasSide, to: string, toSide: CanvasSide) => void;
  onDropOnSession: (noteId: string, sessionNodeId: string) => void;
  onRemove: () => void;
  onDropExternal: (data: { url?: string; text?: string }, at: Point) => void;
}

interface Drag {
  kind: "move" | "resize" | "pan" | "link";
  node?: CanvasNode;
  side?: CanvasSide;
  sx: number;
  sy: number;
  ox: number;
  oy: number;
  /** Cartões dentro do grupo arrastado: vão junto, como no Obsidian. */
  members?: { id: string; x: number; y: number }[];
  moved: boolean;
}

const clamp = (min: number, max: number, v: number) => Math.max(min, Math.min(max, v));
const MIN_Z = 0.2;
const MAX_Z = 2;
const PAD = 400;
const FIT = "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5";

const views = new Map<string, { zoom: number; pan: Point }>();

function moveNodes(doc: CanvasDoc, positions: { id: string; x: number; y: number }[]): CanvasDoc {
  const at = new Map(positions.map((p) => [p.id, p]));
  return { ...doc, nodes: doc.nodes.map((n) => (at.has(n.id) ? { ...n, x: at.get(n.id)!.x, y: at.get(n.id)!.y } : n)) };
}

const within = (p: Point, r: Rect) => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height;

/** Dá para rolar este elemento nessa direção? Então a rolagem é dele, não do quadro. */
function canScroll(el: HTMLElement, dy: number): boolean {
  if (el.scrollHeight <= el.clientHeight + 1) return false;
  return dy < 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1;
}

export function Board(props: Props) {
  const { doc, selection, editingId } = props;
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Point>({ x: 80, y: 80 });
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [link, setLink] = useState<{ from: string; side: CanvasSide; x: number; y: number; target: string | null } | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const dropRef = useRef<string | null>(null);
  const lastClick = useRef<{ id: string; t: number } | null>(null);
  const shown = useRef<string | null>(null);
  const view = useRef({ zoom, pan });
  view.current = { zoom, pan };
  const live = useRef(props);
  live.current = props;

  const byId = useMemo(() => new Map(doc.nodes.map((n) => [n.id, n])), [doc.nodes]);
  const ctxEdges = useMemo(() => new Set(contextEdges(doc).map((e) => e.id)), [doc]);
  const sessionsById = useMemo(() => new Map(props.sessions.map((s) => [s.id, s])), [props.sessions]);
  const agentsById = useMemo(() => new Map(props.agents.map((a) => [a.id, a])), [props.agents]);

  const toWorld = (clientX: number, clientY: number): Point => {
    const box = viewport.current?.getBoundingClientRect();
    const { zoom: z, pan: p } = view.current;
    return { x: (clientX - (box?.left ?? 0) - p.x) / z, y: (clientY - (box?.top ?? 0) - p.y) / z };
  };

  const fit = () => {
    const el = viewport.current;
    if (!el || !el.clientWidth) return;
    const w = el.clientWidth;
    const h = el.clientHeight;
    const b = boundsOf(live.current.doc.nodes);
    if (!b) {
      setZoom(1);
      setPan({ x: Math.round(w / 2), y: Math.round(h / 2) });
      return;
    }
    const z = clamp(MIN_Z, 1, Math.min((w - 120) / Math.max(1, b.width), (h - 120) / Math.max(1, b.height)));
    setZoom(z);
    setPan({ x: (w - b.width * z) / 2 - b.x * z, y: (h - b.height * z) / 2 - b.y * z });
  };
  const fitRef = useRef(fit);
  fitRef.current = fit;

  props.apiRef.current = {
    center: () => {
      const el = viewport.current;
      const { zoom: z, pan: p } = view.current;
      return el ? { x: Math.round((el.clientWidth / 2 - p.x) / z), y: Math.round((el.clientHeight / 2 - p.y) / z) } : { x: 0, y: 0 };
    },
    centerOn: (id) => {
      const el = viewport.current;
      const n = live.current.doc.nodes.find((x) => x.id === id);
      if (!el || !n) return;
      const z = clamp(MIN_Z, MAX_Z, Math.min(Math.max(view.current.zoom, 0.6), (el.clientWidth - 80) / n.width, (el.clientHeight - 80) / n.height));
      setZoom(z);
      setPan({ x: el.clientWidth / 2 - (n.x + n.width / 2) * z, y: el.clientHeight / 2 - (n.y + n.height / 2) * z });
    },
    fit: () => fitRef.current(),
  };

  // Quadro aberto: volta para onde estava (se já foi aberto) ou enquadra tudo.
  useEffect(() => {
    shown.current = null;
    const key = props.viewKey;
    const frame = window.requestAnimationFrame(() => {
      const saved = views.get(key);
      if (saved) {
        setZoom(saved.zoom);
        setPan(saved.pan);
      } else fitRef.current();
      shown.current = key;
    });
    return () => window.cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.fitKey]);

  useEffect(() => {
    if (shown.current === props.viewKey) views.set(props.viewKey, { zoom, pan });
  }, [zoom, pan, props.viewKey]);

  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    observer.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    // Rolar anda; ⌘ + rolar (ou pinça no trackpad) dá zoom em volta do ponteiro. Dentro de um
    // cartão que rola (as linhas da sessão, uma nota longa), a rolagem fica com ele.
    const onWheel = (event: WheelEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest(".bd-overlay")) return;
      const zooming = event.ctrlKey || event.metaKey;
      if (!zooming) {
        const scroller = target?.closest<HTMLElement>(".bd-scroll, textarea");
        if (scroller && canScroll(scroller, event.deltaY)) return;
      }
      event.preventDefault();
      const { zoom: z, pan: p } = view.current;
      if (zooming) {
        const next = clamp(MIN_Z, MAX_Z, z * Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.002)));
        const box = el.getBoundingClientRect();
        const cx = event.clientX - box.left;
        const cy = event.clientY - box.top;
        setPan({ x: cx - ((cx - p.x) / z) * next, y: cy - ((cy - p.y) / z) * next });
        setZoom(next);
      } else {
        setPan({ x: p.x - event.deltaX, y: p.y - event.deltaY });
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      observer.disconnect();
      el.removeEventListener("wheel", onWheel);
    };
  }, []);

  const zoomBy = (factor: number) => {
    const next = clamp(MIN_Z, MAX_Z, zoom * factor);
    const cx = size.w / 2;
    const cy = size.h / 2;
    setPan({ x: cx - ((cx - pan.x) / zoom) * next, y: cy - ((cy - pan.y) / zoom) * next });
    setZoom(next);
  };

  // --- arrastar cartões, cantos, ligações e o fundo ----------------------------------------------

  const targetAt = (clientX: number, clientY: number) =>
    document.elementFromPoint(clientX, clientY)?.closest<HTMLElement>("[data-card-id]")?.dataset.cardId ?? null;

  const onCardDown = (event: ReactPointerEvent, node: CanvasNode) => {
    // Botões, campos e links do cartão funcionam normalmente; não viram arrasto do quadro.
    if ((event.target as HTMLElement).closest("button, input, textarea, select, a")) return event.stopPropagation();
    if (event.button !== 0) return;
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    const members =
      node.type === "group"
        ? live.current.doc.nodes.filter((n) => n.id !== node.id && inside(n, node)).map((n) => ({ id: n.id, x: n.x, y: n.y }))
        : undefined;
    drag.current = { kind: "move", node, sx: event.clientX, sy: event.clientY, ox: node.x, oy: node.y, members, moved: false };
    const sel = live.current.selection;
    if (!(sel?.kind === "node" && sel.id === node.id)) props.onSelect({ kind: "node", id: node.id });
    if (live.current.editingId && live.current.editingId !== node.id) props.onEditing(null);
  };

  const onHandleDown = (event: ReactPointerEvent, node: CanvasNode, side: CanvasSide) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { kind: "link", node, side, sx: event.clientX, sy: event.clientY, ox: 0, oy: 0, moved: false };
  };

  const onResizeDown = (event: ReactPointerEvent, node: CanvasNode) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { kind: "resize", node, sx: event.clientX, sy: event.clientY, ox: node.width, oy: node.height, moved: false };
  };

  const handlers = useRef({ down: onCardDown, handle: onHandleDown, resize: onResizeDown });
  handlers.current = { down: onCardDown, handle: onHandleDown, resize: onResizeDown };
  const on = useMemo<CardHandlers>(
    () => ({
      down: (event, node) => handlers.current.down(event, node),
      handle: (event, node, side) => handlers.current.handle(event, node, side),
      resize: (event, node) => handlers.current.resize(event, node),
    }),
    [],
  );

  const onViewportDown = (event: ReactPointerEvent) => {
    if (event.button !== 0 && event.button !== 1) return;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { kind: "pan", sx: event.clientX, sy: event.clientY, ox: pan.x, oy: pan.y, moved: false };
  };

  const setDrop = (id: string | null) => {
    if (dropRef.current === id) return;
    dropRef.current = id;
    setDropTarget(id);
  };

  const onMove = (event: ReactPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = event.clientX - d.sx;
    const dy = event.clientY - d.sy;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true;
    const z = view.current.zoom;
    if (d.kind === "pan") {
      setPan({ x: d.ox + dx, y: d.oy + dy });
    } else if (d.kind === "move" && d.node) {
      const mx = Math.round(dx / z);
      const my = Math.round(dy / z);
      const id = d.node.id;
      props.onEdit((current) =>
        moveNodes(current, [{ id, x: d.ox + mx, y: d.oy + my }, ...(d.members ?? []).map((m) => ({ id: m.id, x: m.x + mx, y: m.y + my }))]),
      );
      if (isNote(d.node)) {
        const p = toWorld(event.clientX, event.clientY);
        const over = live.current.doc.nodes.find((n) => n.id !== id && within(p, n) && !!sessionMetaOf(n));
        setDrop(over?.id ?? null);
      }
    } else if (d.kind === "resize" && d.node) {
      const id = d.node.id;
      const group = d.node.type === "group";
      const width = Math.max(group ? 160 : 140, Math.round(d.ox + dx / z));
      const height = Math.max(group ? 100 : 70, Math.round(d.oy + dy / z));
      props.onEdit((current) => ({ ...current, nodes: current.nodes.map((n) => (n.id === id ? { ...n, width, height } : n)) }));
    } else if (d.kind === "link" && d.node && d.side) {
      const p = toWorld(event.clientX, event.clientY);
      const t = targetAt(event.clientX, event.clientY);
      setLink({ from: d.node.id, side: d.side, x: p.x, y: p.y, target: t && t !== d.node.id ? t : null });
    }
  };

  const onUp = (event: ReactPointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.kind === "link" && d.node && d.side) {
      setLink(null);
      if (!d.moved) return;
      const target = targetAt(event.clientX, event.clientY);
      const node = target ? live.current.doc.nodes.find((n) => n.id === target) : undefined;
      if (node && node.id !== d.node.id) props.onConnect(d.node.id, d.side, node.id, nearestSide(node, toWorld(event.clientX, event.clientY)));
      return;
    }
    if (d.kind === "move" && d.node) {
      const drop = dropRef.current;
      setDrop(null);
      if (d.moved && drop && isNote(d.node)) {
        // A nota volta para onde estava e fica ligada à sessão.
        props.onEdit((current) => moveNodes(current, [{ id: d.node!.id, x: d.ox, y: d.oy }]));
        props.onDropOnSession(d.node.id, drop);
        return;
      }
      if (!d.moved) {
        const now = Date.now();
        const twice = lastClick.current?.id === d.node.id && now - lastClick.current.t < 400;
        lastClick.current = { id: d.node.id, t: now };
        const kind = cardKind(d.node);
        if (twice && (kind === "sticky" || kind === "grupo")) props.onEditing(d.node.id);
      }
      return;
    }
    if (d.kind === "pan" && !d.moved) props.onSelect(null);
  };

  const onCancel = () => {
    drag.current = null;
    setLink(null);
    setDrop(null);
  };

  // --- soltar texto ou endereço vindo de fora -------------------------------------------------------

  const onDragOver = (event: DragEvent) => {
    const types = Array.from(event.dataTransfer.types);
    if (types.includes("Files") || !(types.includes("text/uri-list") || types.includes("text/plain"))) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };

  const onDrop = (event: DragEvent) => {
    const types = Array.from(event.dataTransfer.types);
    if (types.includes("Files")) return;
    event.preventDefault();
    event.stopPropagation();
    const uri = event.dataTransfer
      .getData("text/uri-list")
      .split(/\r?\n/)
      .find((line) => line.trim() && !line.startsWith("#"));
    const text = event.dataTransfer.getData("text/plain");
    if (uri || text.trim()) props.onDropExternal(uri ? { url: uri.trim() } : { text }, toWorld(event.clientX, event.clientY));
  };

  // --- desenho ----------------------------------------------------------------------------------------

  const geometry = useMemo(
    () =>
      doc.edges.flatMap((e) => {
        const a = byId.get(e.fromNode);
        const b = byId.get(e.toNode);
        return a && b ? [{ edge: e, ...edgeGeometry(e, a, b) }] : [];
      }),
    [doc.edges, byId],
  );

  const box = useMemo(() => {
    const b = boundsOf(doc.nodes) ?? { x: 0, y: 0, width: 0, height: 0 };
    return { x: b.x - PAD, y: b.y - PAD, width: b.width + PAD * 2, height: b.height + PAD * 2 };
  }, [doc.nodes]);

  const markers = useMemo(() => {
    const list = [
      { id: "def", fill: "var(--fnt)" },
      { id: "ctx", fill: "var(--acc)" },
      { id: "sel", fill: "var(--acct)" },
      ...CANVAS_COLORS.map((c) => ({ id: c.key, fill: c.value })),
    ];
    for (const e of doc.edges) {
      if (e.color && /^#[0-9a-f]{3,8}$/i.test(e.color) && !list.some((m) => m.id === e.color!.slice(1))) list.push({ id: e.color.slice(1), fill: e.color });
    }
    return list;
  }, [doc.edges]);

  const markerOf = (color: string | undefined, isCtx: boolean, selected: boolean) => {
    if (selected) return "sel";
    if (color && colorOf(color)) return color.startsWith("#") ? color.slice(1) : color;
    return isCtx ? "ctx" : "def";
  };

  const area = { x: -pan.x / zoom, y: -pan.y / zoom, w: size.w / zoom, h: size.h / zoom };
  const isVisible = (n: CanvasNode) => n.x < area.x + area.w && n.x + n.width > area.x && n.y < area.y + area.h && n.y + n.height > area.y;
  const tasksLoaded = props.tasks !== null;
  const lifted = dropTarget ? drag.current?.node?.id : undefined;

  const renderCard = (n: CanvasNode) => {
    const kind = cardKind(n);
    const meta = kind === "sessao" ? sessionMetaOf(n) : null;
    const session = meta ? sessionsById.get(meta.sessao) ?? null : undefined;
    const agentId = session?.agent ?? meta?.agente ?? "";
    const taskMeta = kind === "tarefa" ? taskMetaOf(n) : null;
    return (
      <Card
        key={n.id}
        node={n}
        kind={kind}
        ctx={props.ctx}
        on={on}
        selected={selection?.kind === "node" && selection.id === n.id}
        editing={editingId === n.id}
        dropTarget={dropTarget === n.id}
        lifted={!!dropTarget && lifted === n.id}
        linkTarget={link?.target === n.id}
        visible={kind === "sessao" ? isVisible(n) : true}
        hit={kind === "nota" ? (n.file && n.file in props.notas ? props.notas[n.file] : undefined) : undefined}
        session={session}
        agent={agentId ? agentsById.get(agentId) ?? null : null}
        task={taskMeta ? props.tasks?.find((t) => t.id === taskMeta.id) ?? null : undefined}
        tasksLoaded={tasksLoaded}
      />
    );
  };

  const selNode = selection?.kind === "node" ? byId.get(selection.id) : undefined;
  const selEdge = selection?.kind === "edge" ? geometry.find((g) => g.edge.id === selection.id) : undefined;
  const selKind = selNode ? cardKind(selNode) : null;
  const linkFrom = link ? byId.get(link.from) : undefined;
  const stop = (event: ReactPointerEvent) => event.stopPropagation();

  const setColor = (color: string | undefined) => {
    if (!selNode) return;
    const id = selNode.id;
    props.onEdit((current) => ({ ...current, nodes: current.nodes.map((n) => (n.id === id ? { ...n, color } : n)) }));
  };

  const setEdgeLabel = (label: string) => {
    if (!selEdge) return;
    const id = selEdge.edge.id;
    props.onEdit((current) => ({ ...current, edges: current.edges.map((e) => (e.id === id ? { ...e, label: label || undefined } : e)) }));
  };

  const selectEdge = (event: ReactPointerEvent, id: string) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    props.onSelect({ kind: "edge", id });
  };

  return (
    <div
      ref={viewport}
      className="bd-viewport"
      data-linking={link ? "true" : undefined}
      style={{ backgroundPosition: `${pan.x}px ${pan.y}px`, backgroundSize: `${20 * zoom}px ${20 * zoom}px` }}
      onPointerDown={onViewportDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onCancel}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <div className="bd-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, ["--inv" as string]: 1 / zoom }}>
        {doc.nodes.filter((n) => n.type === "group").map(renderCard)}

        <svg className="bd-edges" width={box.width} height={box.height} style={{ left: box.x, top: box.y }} aria-hidden="true">
          <defs>
            {markers.map((m) => (
              <marker key={m.id} id={`bd-arr-${m.id}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="13" markerHeight="13" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" style={{ fill: m.fill }} />
              </marker>
            ))}
          </defs>
          <g transform={`translate(${-box.x},${-box.y})`}>
            {geometry.map(({ edge, d }) => {
              const isCtx = ctxEdges.has(edge.id);
              const selected = selection?.kind === "edge" && selection.id === edge.id;
              const marker = `url(#bd-arr-${markerOf(edge.color, isCtx, selected)})`;
              const stroke = selected ? "var(--acct)" : colorOf(edge.color) ?? (isCtx ? "var(--acc)" : "var(--fnt)");
              return (
                <g key={edge.id} className="bd-edge" data-selected={selected ? "true" : undefined}>
                  <path
                    className="bd-line"
                    d={d}
                    style={{ stroke }}
                    markerEnd={edge.toEnd === "none" ? undefined : marker}
                    markerStart={edge.fromEnd === "arrow" ? marker : undefined}
                  />
                  <path className="bd-hit" d={d} onPointerDown={(event) => selectEdge(event, edge.id)} />
                </g>
              );
            })}
            {link && linkFrom && (
              <path
                className="bd-line bd-draft"
                d={curve(anchor(linkFrom, link.side), link.side, { x: link.x, y: link.y }, null).d}
                markerEnd="url(#bd-arr-ctx)"
              />
            )}
          </g>
        </svg>

        {geometry.map(({ edge, mid }) =>
          edge.label && !(selection?.kind === "edge" && selection.id === edge.id) ? (
            <span
              key={`lbl-${edge.id}`}
              className="bd-edge-label"
              data-ctx={ctxEdges.has(edge.id) ? "true" : undefined}
              style={{ left: mid.x, top: mid.y }}
              onPointerDown={(event) => selectEdge(event, edge.id)}
            >
              {edge.label}
            </span>
          ) : null,
        )}

        {doc.nodes.filter((n) => n.type !== "group").map(renderCard)}
      </div>

      {selNode && editingId !== selNode.id && (
        <div
          className="bd-cardbar bd-overlay"
          style={{ left: Math.max(8, selNode.x * zoom + pan.x), top: Math.max(8, selNode.y * zoom + pan.y - 40) }}
          onPointerDown={stop}
        >
          <button type="button" className="bd-swatch" data-none="true" title="Sem cor" aria-label="Sem cor" aria-pressed={!selNode.color} onClick={() => setColor(undefined)} />
          {CANVAS_COLORS.map((c) => (
            <button
              key={c.key}
              type="button"
              className="bd-swatch"
              style={{ ["--sw" as string]: c.value }}
              title={`Cor: ${c.label}`}
              aria-label={`Cor: ${c.label}`}
              aria-pressed={selNode.color === c.key}
              onClick={() => setColor(c.key)}
            />
          ))}
          {(selKind === "sticky" || selKind === "grupo") && (
            <>
              <span className="bd-sep" />
              <button type="button" className="bd-barbtn" onClick={() => props.onEditing(selNode.id)}>
                {selKind === "grupo" ? "Renomear" : "Editar"}
              </button>
            </>
          )}
          <span className="bd-sep" />
          <button type="button" className="bd-barbtn" title="Tirar do quadro (Delete)" aria-label="Tirar do quadro" onClick={props.onRemove}>
            <Icon d={ICON.trash} size={13} strokeWidth={2} />
          </button>
        </div>
      )}

      {selEdge && (
        <div className="bd-edgebar bd-overlay" style={{ left: selEdge.mid.x * zoom + pan.x, top: selEdge.mid.y * zoom + pan.y }} onPointerDown={stop}>
          <input
            value={selEdge.edge.label ?? ""}
            placeholder="Rótulo"
            aria-label="Rótulo da ligação"
            onChange={(event) => setEdgeLabel(event.target.value)}
            onKeyDown={(event) => (event.key === "Enter" || event.key === "Escape") && props.onSelect(null)}
          />
          <button type="button" className="bd-barbtn" title="Tirar a ligação (Delete)" aria-label="Tirar a ligação" onClick={props.onRemove}>
            <Icon d={ICON.trash} size={13} strokeWidth={2} />
          </button>
        </div>
      )}

      <div className="bd-zoom bd-overlay" role="toolbar" aria-label="Zoom" onPointerDown={stop}>
        <button type="button" onClick={() => zoomBy(1.2)} aria-label="Aproximar" title="Aproximar (⌘ + rolar)">
          <Icon d={ICON.plus} size={14} strokeWidth={2} />
        </button>
        <button type="button" onClick={() => zoomBy(1 / 1.2)} aria-label="Afastar" title="Afastar">
          <Icon d={ICON.minus} size={14} strokeWidth={2} />
        </button>
        <button type="button" onClick={fit} aria-label="Enquadrar tudo" title="Enquadrar tudo">
          <Icon d={FIT} size={14} strokeWidth={2} />
        </button>
        <span className="mono">{Math.round(zoom * 100)}%</span>
      </div>

      {doc.nodes.length === 0 && (
        <div className="bd-hint-empty">
          <b>Quadro vazio</b>
          <span>Use “Adicionar” para pôr notas do Brain, sessões, tarefas, links e notas suas. Tudo fica no .canvas do projeto e abre no Obsidian.</span>
        </div>
      )}
    </div>
  );
}
