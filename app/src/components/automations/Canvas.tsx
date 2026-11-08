// O canvas das Automações: grade de pontinhos que anda e escala junto, blocos de 84 px com a faixa
// na cor do tipo, ligações curvas com "+" nas saídas livres, contagem de itens depois de rodar,
// notas como callouts do Obsidian. Arrastar o fundo move, ⌘ + rolar dá zoom; arrastar da saída de
// um bloco até outro liga os dois.

import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { ICON, Icon } from "../../icons";
import type { CoreClient } from "../../lib/core";
import { KIND_COLOR } from "../../lib/format";
import type { Agent, AutoCatalog, AutoEdge, AutoFlow, AutoStepRun } from "../../types";
import {
  type AddCtx,
  AW,
  type Change,
  type CNode,
  type Ramo,
  KIND,
  OFF,
  P,
  S,
  STEP_LABEL,
  isPlain,
  itemsLabel,
  itemsOf,
  moveNode,
  nodeW,
  nodesOf,
  outputsOf,
  stepSub,
  toolElem,
  toolTitle,
  TRIGGER,
} from "./model";
import { ElemMark, Glyph } from "./parts";

export interface CanvasApi {
  /** O meio da tela, em coordenadas do desenho (onde entra um passo ou uma nota solta). */
  center: () => { x: number; y: number };
}

interface Props {
  flow: AutoFlow;
  editing: boolean;
  steps: Record<string, AutoStepRun>;
  catalog: AutoCatalog | null;
  agents: Agent[];
  client: CoreClient | null;
  selectedId: string | null;
  /** Muda quando o desenho deve ser enquadrado de novo (outra automação, outra execução). */
  fitKey: string;
  apiRef: { current: CanvasApi | null };
  onSelect: (id: string | null) => void;
  onOpen: (id: string) => void;
  onEdit: (change: Change) => void;
  onAdd: (ctx: AddCtx) => void;
  onLink: (de: string, para: string, ramo?: Ramo) => void;
  onTestStep: (id: string) => void;
  onToggleOff: (id: string) => void;
  onRemove: (id: string) => void;
  children?: ReactNode;
}

interface Drag {
  kind: "node" | "note" | "pan" | "link";
  id?: string;
  ramo?: Ramo;
  sx: number;
  sy: number;
  ox: number;
  oy: number;
  moved: boolean;
}

const clamp = (min: number, max: number, v: number) => Math.max(min, Math.min(max, v));

function bez(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = Math.max(40, Math.abs(b.x - a.x) / 2);
  return {
    d: `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x - 3},${b.y}`,
    mid: { x: (a.x + 3 * (a.x + dx) + 3 * (b.x - dx) + b.x) / 8, y: (a.y + 3 * a.y + 3 * b.y + b.y) / 8 },
  };
}

const portIn = (n: CNode) => ({ x: n.x, y: n.y + S / 2 });
const portOut = (n: CNode, ramo?: Ramo) => ({
  x: n.x + nodeW(n.kind),
  y: n.y + (n.kind === "condicao" && ramo ? (ramo === "sim" ? S * 0.3 : S * 0.7) : S / 2),
});

/** Modelo, ferramentas e saída do agente, pendurados embaixo do bloco. */
function agentParts(n: CNode) {
  const step = n.step!;
  const tools = step.ferramentas ?? [];
  const shown = tools.slice(0, 2);
  return {
    cy: n.y + S + 84,
    ports: [
      { key: "modelo", label: "Modelo", x: n.x + AW * 0.15 },
      { key: "ferramentas", label: "Ferramentas", x: n.x + AW * 0.5 },
      { key: "saida", label: "Saída", x: n.x + AW * 0.85 },
    ],
    model: { x: n.x + AW * 0.15, cli: step.cli ?? "claude", level: step.modelo || "padrão" },
    tools: shown.length
      ? shown.map((name, i) => ({ x: n.x + AW * 0.5 + (i - (shown.length - 1) / 2) * 58, name }))
      : [{ x: n.x + AW * 0.5, name: "" }],
    more: tools.length - shown.length,
    out: { x: n.x + AW * 0.85, fields: Object.keys(step.saida ?? {}) },
  };
}

export function Canvas(props: Props) {
  const { flow, editing, steps, catalog, agents, client, selectedId } = props;
  const [zoom, setZoom] = useState(0.9);
  const [pan, setPan] = useState({ x: 60, y: 60 });
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const [link, setLink] = useState<{ from: string; ramo?: Ramo; x: number; y: number } | null>(null);
  const [editingNote, setEditingNote] = useState<string | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const lastClick = useRef<{ id: string; t: number } | null>(null);
  const hoverTimer = useRef<number | null>(null);
  const view = useRef({ zoom, pan });
  view.current = { zoom, pan };

  const nodes = nodesOf(flow);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const latest = useRef({ nodes, notes: flow.notas });
  latest.current = { nodes, notes: flow.notas };

  const toWorld = (clientX: number, clientY: number) => {
    const box = canvas.current?.getBoundingClientRect();
    const { zoom: z, pan: p } = view.current;
    return { x: (clientX - (box?.left ?? 0) - p.x) / z, y: (clientY - (box?.top ?? 0) - p.y) / z };
  };

  props.apiRef.current = {
    center: () => {
      const box = canvas.current?.getBoundingClientRect();
      const { zoom: z, pan: p } = view.current;
      return box ? { x: Math.round((box.width / 2 - p.x) / z), y: Math.round((box.height / 2 - p.y) / z) } : { x: 200, y: 200 };
    },
  };

  /** Enquadra o desenho, deixando espaço embaixo para a barra de testar. */
  const fit = () => {
    const box = canvas.current?.getBoundingClientRect();
    if (!box || !box.width) return;
    const { nodes: ns, notes } = latest.current;
    const xs = [...ns.map((n) => n.x), ...notes.map((n) => n.x)];
    const ys = [...ns.map((n) => n.y), ...notes.map((n) => n.y)];
    const minX = Math.min(...xs) - 30;
    const minY = Math.min(...ys) - 50;
    const maxX = Math.max(...ns.map((n) => n.x + nodeW(n.kind) + 70), ...notes.map((n) => n.x + (n.w ?? 240)));
    const maxY = Math.max(...ns.map((n) => n.y + S + (n.kind === "agente" ? 150 : 60)), ...notes.map((n) => n.y + 130));
    const scale = clamp(0.5, 1.1, Math.min((box.width - 80) / (maxX - minX), (box.height - 150) / (maxY - minY)));
    setZoom(scale);
    setPan({
      x: (box.width - (maxX - minX) * scale) / 2 - minX * scale,
      y: (box.height - 90 - (maxY - minY) * scale) / 2 - minY * scale,
    });
  };
  const fitRef = useRef(fit);
  fitRef.current = fit;

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => fitRef.current());
    return () => window.cancelAnimationFrame(frame);
  }, [props.fitKey]);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    let last = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (Math.abs(el.clientWidth - last) > 40) {
        last = el.clientWidth;
        fitRef.current();
      }
    });
    observer.observe(el);
    // Rolar anda; ⌘ + rolar (ou pinça no trackpad) dá zoom em volta do ponteiro.
    const onWheel = (event: WheelEvent) => {
      if ((event.target as HTMLElement | null)?.closest(".af-overlay")) return;
      event.preventDefault();
      const { zoom: z, pan: p } = view.current;
      if (event.ctrlKey || event.metaKey) {
        const next = clamp(0.4, 1.6, z * Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.002)));
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

  useEffect(() => {
    if (!editing) setEditingNote(null);
  }, [editing]);

  const zoomBy = (factor: number) => {
    const box = canvas.current?.getBoundingClientRect();
    const next = clamp(0.4, 1.6, zoom * factor);
    if (box) {
      const cx = box.width / 2;
      const cy = box.height / 2;
      setPan({ x: cx - ((cx - pan.x) / zoom) * next, y: cy - ((cy - pan.y) / zoom) * next });
    }
    setZoom(next);
  };

  // --- arrastar passos, notas, ligações e o canvas -----------------------------------------------

  const onItemDown = (event: ReactPointerEvent, kind: "node" | "note", item: { id: string; x: number; y: number }) => {
    // Botões dentro do bloco (testar, desligar, tirar, o × da nota) não podem virar arrasto do canvas,
    // senão a captura do ponteiro engole o clique.
    if ((event.target as HTMLElement).closest("button, input, textarea")) return event.stopPropagation();
    if (event.button !== 0 || (event.target as HTMLElement).closest(".af-port")) return;
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { kind, id: item.id, sx: event.clientX, sy: event.clientY, ox: item.x, oy: item.y, moved: false };
  };

  const onPortDown = (event: ReactPointerEvent, n: CNode, ramo?: Ramo) => {
    if (!editing || event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { kind: "link", id: n.id, ramo, sx: event.clientX, sy: event.clientY, ox: 0, oy: 0, moved: false };
  };

  const onCanvasDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { kind: "pan", sx: event.clientX, sy: event.clientY, ox: pan.x, oy: pan.y, moved: false };
  };

  const onMove = (event: ReactPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = event.clientX - d.sx;
    const dy = event.clientY - d.sy;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true;
    if (d.kind === "pan") setPan({ x: d.ox + dx, y: d.oy + dy });
    else if (d.kind === "link") setLink({ from: d.id!, ramo: d.ramo, ...toWorld(event.clientX, event.clientY) });
    else if (!editing) return;
    else if (d.kind === "node") props.onEdit((f) => moveNode(f, d.id!, Math.round(d.ox + dx / zoom), Math.round(d.oy + dy / zoom)));
    else if (d.kind === "note")
      props.onEdit((f) => ({
        ...f,
        notas: f.notas.map((k) => (k.id === d.id ? { ...k, x: Math.round(d.ox + dx / zoom), y: Math.round(d.oy + dy / zoom) } : k)),
      }));
  };

  const onUp = (event: ReactPointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.kind === "link") {
      setLink(null);
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>("[data-node-id]")?.dataset.nodeId;
      if (d.moved && target && target !== d.id) props.onLink(d.id!, target, d.ramo);
      return;
    }
    if (d.moved) return;
    if ((d.kind === "node" || d.kind === "note") && d.id) {
      const now = Date.now();
      const twice = lastClick.current?.id === d.id && now - lastClick.current.t < 380;
      lastClick.current = { id: d.id, t: now };
      if (d.kind === "node") {
        props.onSelect(d.id);
        if (twice) props.onOpen(d.id);
      } else if (twice && editing) setEditingNote(d.id);
    } else if (d.kind === "pan") {
      props.onSelect(null);
    }
  };

  const keepEdge = (key: string | null) => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
    if (key) setHoverEdge(key);
  };
  const dropEdge = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => setHoverEdge(null), 220);
  };

  const removeEdge = (edge: AutoEdge) => {
    props.onEdit((f) => ({ ...f, ligacoes: f.ligacoes.filter((e) => !(e.de === edge.de && e.para === edge.para && e.ramo === edge.ramo)) }));
    setHoverEdge(null);
  };

  // --- estado das ligações depois de rodar ------------------------------------------------------------

  const edgeOk = (e: AutoEdge) => {
    const from = steps[e.de];
    const to = steps[e.para];
    if (from?.status !== "ok" || !to || to.status === "pulado" || to.status === "recusado") return false;
    return !e.ramo || (isPlain(from.saida) && from.saida.ramo === e.ramo);
  };

  /** Saídas sem ligação ganham o "+" na ponta, para emendar o próximo passo. */
  const stubs = editing
    ? nodes.flatMap((n) =>
        outputsOf(n.kind)
          .filter((ramo) => !flow.ligacoes.some((e) => e.de === n.id && (n.kind !== "condicao" || e.ramo === ramo)))
          .map((ramo) => ({ node: n, ramo, p: portOut(n, ramo) })),
      )
    : [];

  // --- desenho ----------------------------------------------------------------------------------------

  const renderNode = (n: CNode) => {
    const step = n.step;
    const st = steps[n.id]?.status;
    const w = nodeW(n.kind);
    const color = n.kind === "agente" ? KIND_COLOR[step?.cli ?? "claude"] : KIND[n.kind].color;
    const tool = step?.ferramenta ? catalog?.ferramentas.find((t) => t.nome === step.ferramenta) : undefined;
    const missing = n.kind === "ferramenta" && !!catalog && !!step?.ferramenta && !tool;
    const pinned = step?.fixado !== undefined && step?.fixado !== null;
    const agent = step?.agente ? agents.find((a) => a.id === step.agente) : undefined;
    const parts = n.kind === "agente" && step ? agentParts(n) : null;
    const sub = step ? stepSub(step) : flow.gatilho.tipo;
    const style = { left: n.x, top: n.y, width: w, height: S, ["--k" as string]: color } as CSSProperties;
    return (
      <div key={n.id} className="af-nwrap" data-off={step?.desligado ? "true" : undefined}>
        <div
          className="af-n"
          data-node-id={n.id}
          data-kind={n.kind}
          data-status={st}
          data-selected={selectedId === n.id ? "true" : undefined}
          data-warn={missing ? "true" : undefined}
          style={style}
          title={st ? `${n.title}: ${STEP_LABEL[st]}` : undefined}
          onPointerDown={(event) => onItemDown(event, "node", n)}
        >
          {parts && step ? (
            <div className="af-n-agent">
              <span className="af-n-avatar">
                <Glyph kind={n.kind} step={step} agents={agents} client={client} size={32} />
              </span>
              <span className="af-n-text">
                <b>{n.title}</b>
                <span className="mono">{agent ? agent.name : step.cli === "codex" ? "Codex" : "Claude Code"}</span>
                <span className="af-cost mono">{step.onde === "visivel" ? "numa aba visível" : "em segundo plano"}</span>
              </span>
            </div>
          ) : (
            <span className="af-n-glyph">
              <Glyph kind={n.kind} step={step} agents={agents} client={client} size={32} />
            </span>
          )}
          {n.kind === "gatilho" && (
            <span className="af-bolt" title="Gatilho">
              <Icon d={P.bolt} size={11} strokeWidth={2} />
            </span>
          )}
          {tool?.pessoas && (
            <span className="af-lock" title="Fala com outras pessoas: pede aprovação, e no teste vira ensaio">
              <Icon d={P.lock} size={10} strokeWidth={2.2} />
            </span>
          )}
          {st && st !== "pulado" && (
            <span className="af-st" data-step={st} title={STEP_LABEL[st]}>
              {st === "rodando" ? (
                <span className="af-spin" />
              ) : st === "ok" ? (
                <Icon d={ICON.check} size={11} strokeWidth={3} />
              ) : st === "erro" ? (
                "!"
              ) : st === "esperando" ? (
                "‖"
              ) : (
                "✕"
              )}
            </span>
          )}
          {pinned && (
            <span className="af-pinned" title="Dados fixados: no teste, substituem a chamada">
              <Icon d={P.pin} size={10} strokeWidth={2} />
            </span>
          )}
          {n.kind !== "gatilho" && <span className="af-port in" />}
          {n.kind === "condicao" ? (
            <>
              <span className="af-port out" style={{ top: S * 0.3 }} onPointerDown={(event) => onPortDown(event, n, "sim")} />
              <span className="af-port out" style={{ top: S * 0.7 }} onPointerDown={(event) => onPortDown(event, n, "não")} />
              <span className="af-branch mono" style={{ top: S * 0.3 }}>
                sim
              </span>
              <span className="af-branch mono" data-no="true" style={{ top: S * 0.7 }}>
                não
              </span>
            </>
          ) : (
            <span className="af-port out" onPointerDown={(event) => onPortDown(event, n)} />
          )}
          {editing && n.kind !== "gatilho" && (
            <div className="af-n-tools">
              <button type="button" title="Testar só este passo" onClick={() => props.onTestStep(n.id)}>
                <Icon d={P.play} size={10} strokeWidth={2.2} />
              </button>
              <button
                type="button"
                title={step?.desligado ? "Ligar o passo" : "Desligar o passo (os dados passam direto)"}
                onClick={() => props.onToggleOff(n.id)}
              >
                <Icon d={P.power} size={11} strokeWidth={2.2} />
              </button>
              <button type="button" title="Tirar o passo" onClick={() => props.onRemove(n.id)}>
                <Icon d={ICON.trash} size={11} strokeWidth={2} />
              </button>
            </div>
          )}
        </div>
        {!parts && (
          <div className="af-n-label" style={{ left: n.x + w / 2 - 85, top: n.y + S + 8 }}>
            <b>{n.title}</b>
            <span className="mono">{sub}</span>
            {missing && <span className="af-warn mono">⚠ ferramenta não encontrada</span>}
          </div>
        )}
        {parts && (
          <>
            {parts.ports.map((p) => (
              <span key={p.key} className="af-sub-port" style={{ left: p.x - 5, top: n.y + S - 5 }} />
            ))}
            {parts.ports.map((p) => (
              <span key={`${p.key}-l`} className="af-sub-label mono" style={{ left: p.x - 40, top: n.y + S + 12 }}>
                {p.label}
              </span>
            ))}
            <button
              type="button"
              className="af-sub"
              style={{ left: parts.model.x - 18, top: parts.cy - 18 }}
              title={`Modelo: ${parts.model.level}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => props.onOpen(n.id)}
            >
              <span className="af-cli" style={{ color: KIND_COLOR[parts.model.cli] }}>
                {parts.model.cli === "codex" ? "◇" : "✻"}
              </span>
            </button>
            <span className="af-sub-name mono" style={{ left: parts.model.x - 36, top: parts.cy + 23 }}>
              {parts.model.cli} · {parts.model.level}
            </span>
            {parts.tools.map((t, i) => (
              <div key={`${t.name}-${t.x}`}>
                <button
                  type="button"
                  className="af-sub"
                  data-empty={!t.name ? "true" : undefined}
                  style={{ left: t.x - 18, top: parts.cy - 18 }}
                  title={t.name ? `${toolTitle(t.name)} (${t.name})` : "Nenhuma ferramenta liberada"}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => props.onOpen(n.id)}
                >
                  {t.name ? <ElemMark elem={toolElem(t.name)} size={14} /> : "+"}
                </button>
                <span className="af-sub-name mono" style={{ left: t.x - 36, top: parts.cy + 23 }}>
                  {t.name ? toolTitle(t.name).toLowerCase() : "nenhuma"}
                  {parts.more > 0 && i === parts.tools.length - 1 && <i>+{parts.more}</i>}
                </span>
              </div>
            ))}
            <button
              type="button"
              className="af-sub"
              data-empty={!parts.out.fields.length ? "true" : undefined}
              style={{ left: parts.out.x - 18, top: parts.cy - 18 }}
              title={parts.out.fields.length ? `Saída combinada: ${parts.out.fields.join(", ")}` : "Saída livre"}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => props.onOpen(n.id)}
            >
              <span className="mono af-brace">{parts.out.fields.length ? "{ }" : "+"}</span>
            </button>
            <span className="af-sub-name mono" style={{ left: parts.out.x - 36, top: parts.cy + 23 }}>
              {parts.out.fields.length ? `${parts.out.fields.length} ${parts.out.fields.length === 1 ? "campo" : "campos"}` : "livre"}
            </span>
          </>
        )}
      </div>
    );
  };

  const linkFrom = link ? byId.get(link.from) : undefined;

  return (
    <div
      ref={canvas}
      className="af-canvas"
      data-mode={editing ? "editor" : "runs"}
      data-linking={link ? "true" : undefined}
      style={{ backgroundPosition: `${pan.x}px ${pan.y}px`, backgroundSize: `${20 * zoom}px ${20 * zoom}px` }}
      onPointerDown={onCanvasDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={() => ((drag.current = null), setLink(null))}
    >
      <div className="af-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}>
        <svg className="af-edges" width={OFF * 2} height={OFF * 2} style={{ left: -OFF, top: -OFF }} aria-hidden="true">
          <defs>
            <marker id="af-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" className="af-arr" />
            </marker>
            <marker id="af-arr-ok" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" className="af-arr-ok" />
            </marker>
            <marker id="af-arr-acc" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" className="af-arr-acc" />
            </marker>
          </defs>
          <g transform={`translate(${OFF},${OFF})`}>
            {nodes
              .filter((n) => n.kind === "agente" && n.step)
              .flatMap((n) => {
                const parts = agentParts(n);
                const targets = [parts.model.x, ...parts.tools.map((t) => t.x), parts.out.x];
                const sources = [parts.ports[0].x, ...parts.tools.map(() => parts.ports[1].x), parts.ports[2].x];
                return targets.map((tx, i) => (
                  <path
                    key={`${n.id}-sub-${i}`}
                    className="af-subline"
                    d={`M${sources[i]},${n.y + S + 4} C${sources[i]},${n.y + S + 46} ${tx},${parts.cy - 50} ${tx},${parts.cy - 19}`}
                  />
                ));
              })}
            {flow.ligacoes.map((e) => {
              const a = byId.get(e.de);
              const b = byId.get(e.para);
              if (!a || !b) return null;
              const { d } = bez(portOut(a, e.ramo), portIn(b));
              const key = `${e.de}>${e.para}>${e.ramo ?? ""}`;
              const ok = edgeOk(e);
              return (
                <g key={key} className="af-edge" data-branch={e.ramo} data-state={ok ? "ok" : undefined} data-hover={hoverEdge === key ? "true" : undefined}>
                  <path d={d} markerEnd={`url(#${ok ? "af-arr-ok" : "af-arr"})`} />
                  {editing && <path className="af-hit" d={d} onPointerEnter={() => keepEdge(key)} onPointerLeave={dropEdge} />}
                </g>
              );
            })}
            {stubs.map(({ node, ramo, p }) => (
              <path key={`${node.id}-stub-${ramo ?? ""}`} className="af-stubline" d={`M${p.x},${p.y} L${p.x + 34},${p.y}`} />
            ))}
            {link && linkFrom && (
              <g className="af-edge" data-draft="true">
                <path d={bez(portOut(linkFrom, link.ramo), { x: link.x, y: link.y }).d} markerEnd="url(#af-arr-acc)" />
              </g>
            )}
          </g>
        </svg>

        {flow.notas.map((k) =>
          editingNote === k.id ? (
            <div
              key={k.id}
              className="af-sticky"
              data-editing="true"
              style={{ left: k.x, top: k.y, width: k.w ?? 240 }}
              onPointerDown={(event) => event.stopPropagation()}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setEditingNote(null);
              }}
            >
              <input
                className="af-sticky-title"
                value={k.titulo}
                placeholder="Título"
                aria-label="Título da nota"
                onChange={(event) => props.onEdit((f) => ({ ...f, notas: f.notas.map((x) => (x.id === k.id ? { ...x, titulo: event.target.value } : x)) }))}
                onKeyDown={(event) => event.key === "Escape" && setEditingNote(null)}
              />
              <textarea
                autoFocus
                value={k.texto}
                rows={Math.max(3, k.texto.split("\n").length + 1)}
                placeholder="O porquê do fluxo, para você daqui a três meses."
                aria-label="Texto da nota"
                onChange={(event) => props.onEdit((f) => ({ ...f, notas: f.notas.map((x) => (x.id === k.id ? { ...x, texto: event.target.value } : x)) }))}
                onKeyDown={(event) => event.key === "Escape" && setEditingNote(null)}
              />
            </div>
          ) : (
            <div
              key={k.id}
              className="af-sticky"
              style={{ left: k.x, top: k.y, width: k.w ?? 240 }}
              title={editing ? "Dois cliques para editar" : undefined}
              onPointerDown={(event) => onItemDown(event, "note", k)}
            >
              <span className="af-caps">{k.titulo || "Nota"}</span>
              {k.texto && <p>{k.texto}</p>}
              {editing && (
                <button
                  type="button"
                  className="af-sticky-x"
                  title="Tirar a nota"
                  onClick={() => props.onEdit((f) => ({ ...f, notas: f.notas.filter((x) => x.id !== k.id) }))}
                >
                  <Icon d={ICON.close} size={10} strokeWidth={2} />
                </button>
              )}
            </div>
          ),
        )}

        {nodes.map(renderNode)}

        {flow.ligacoes.map((e) => {
          const a = byId.get(e.de);
          const b = byId.get(e.para);
          if (!a || !b) return null;
          const key = `${e.de}>${e.para}>${e.ramo ?? ""}`;
          const { mid } = bez(portOut(a, e.ramo), portIn(b));
          const lit = edgeOk(e);
          return (
            <div key={`lbl-${key}`}>
              {lit && (
                <span className="af-edge-count mono" style={{ left: mid.x, top: mid.y }}>
                  {itemsLabel(itemsOf(steps[e.de]))}
                </span>
              )}
              {editing && hoverEdge === key && (
                <span
                  className="af-edge-tools"
                  style={{ left: mid.x, top: mid.y }}
                  onPointerEnter={() => keepEdge(null)}
                  onPointerLeave={dropEdge}
                  onPointerDown={(event) => event.stopPropagation()}
                >
                  <button type="button" title="Pôr um passo aqui no meio" onClick={() => props.onAdd({ between: e })}>
                    <Icon d={ICON.plus} size={12} strokeWidth={2.2} />
                  </button>
                  <button type="button" title="Tirar a ligação" onClick={() => removeEdge(e)}>
                    <Icon d={ICON.trash} size={11} strokeWidth={2} />
                  </button>
                </span>
              )}
            </div>
          );
        })}

        {stubs.map(({ node, ramo, p }) => (
          <button
            key={`${node.id}-plus-${ramo ?? ""}`}
            type="button"
            className="af-stub"
            style={{ left: p.x + 34, top: p.y - 11 }}
            title={ramo ? `Próximo passo no ramo ${ramo}` : node.id === TRIGGER ? "Primeiro passo" : "Próximo passo"}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => props.onAdd({ after: node.id, ramo })}
          >
            <Icon d={ICON.plus} size={12} strokeWidth={2.2} />
          </button>
        ))}
      </div>

      {props.children}

      <div className="af-zoom af-overlay" onPointerDown={(event) => event.stopPropagation()}>
        <button type="button" onClick={fit} aria-label="Enquadrar" title="Enquadrar">
          <Icon d={P.fit} size={13} strokeWidth={2} />
        </button>
        <button type="button" onClick={() => zoomBy(1.15)} aria-label="Aproximar" title="Aproximar (⌘ + rolar)">
          <Icon d={ICON.plus} size={13} strokeWidth={2} />
        </button>
        <button type="button" onClick={() => zoomBy(1 / 1.15)} aria-label="Afastar" title="Afastar">
          <Icon d={ICON.minus} size={13} strokeWidth={2} />
        </button>
        <span className="mono">{Math.round(zoom * 100)}%</span>
      </div>
    </div>
  );
}
