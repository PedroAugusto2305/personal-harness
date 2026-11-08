import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationNodeDatum } from "d3-force";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CoreClient } from "../lib/core";
import { TYPE_ICON, TYPE_LABEL } from "../lib/obsidian";
import type { BrainGraphData, GraphNodeData } from "../types";

interface Props {
  client: CoreClient | null;
  tick: number;
  /** Notas achadas pela busca: o resto apaga. */
  highlight: Set<string> | null;
  /** Última nota aberta: ganha um anel. */
  current: string | null;
  onOpen: (path: string) => void;
}

interface Node extends GraphNodeData, SimulationNodeDatum {
  i: number;
  r: number;
  x: number;
  y: number;
}

const FILTERS: { key: string; label: string; tipos: string[] }[] = [
  { key: "projeto", label: "Projetos", tipos: ["projeto"] },
  { key: "decisao", label: "Decisões", tipos: ["decisao"] },
  { key: "incidente", label: "Incidentes", tipos: ["incidente"] },
  { key: "aprendizado", label: "Aprendizados", tipos: ["aprendizado"] },
  { key: "entrega", label: "Entregas", tipos: ["entrega"] },
  { key: "conhecimento", label: "Conhecimento", tipos: ["permanente", "literatura", "moc"] },
  { key: "diario", label: "Diário", tipos: ["daily"] },
  { key: "outras", label: "Outras", tipos: [] },
];
const CATEGORY = new Map(FILTERS.flatMap((f) => f.tipos.map((t) => [t, f.key] as const)));
const categoryOf = (tipo: string) => CATEGORY.get(tipo) ?? "outras";

const GROUP_VAR: Record<string, string> = {
  carreira: "--g-carreira",
  trabalho: "--g-trabalho",
  clientes: "--g-clientes",
  pessoal: "--g-pessoal",
  brain: "--g-brain",
  semarea: "--g-semarea",
};

/** Layout calculado uma vez por conjunto de notas; voltar ao grafo não recalcula. */
let layoutCache: { signature: string; xy: Float64Array } | null = null;

function layout(nodes: Node[], edges: [number, number][]): void {
  const signature = `${nodes.length}:${edges.length}:${nodes[0]?.path}:${nodes[nodes.length - 1]?.path}`;
  if (layoutCache?.signature === signature) {
    nodes.forEach((n, i) => {
      n.x = layoutCache!.xy[i * 2];
      n.y = layoutCache!.xy[i * 2 + 1];
    });
    return;
  }
  // Cada área é uma nuvem num círculo; dentro dela, cada projeto puxa as notas para o próprio centro.
  const groups = [...new Set(nodes.map((n) => n.group))];
  const groupCenter = new Map(
    groups.map((g, i) => {
      const angle = (i / groups.length) * Math.PI * 2 - Math.PI / 2;
      return [g, { x: Math.cos(angle) * 620, y: Math.sin(angle) * 460 }] as const;
    }),
  );
  const projectsOf = new Map<string, string[]>();
  for (const n of nodes) {
    const list = projectsOf.get(n.group) ?? [];
    if (n.projeto && !list.includes(n.projeto)) list.push(n.projeto);
    projectsOf.set(n.group, list);
  }
  const center = new Map<string, { x: number; y: number }>();
  for (const [group, projects] of projectsOf) {
    const base = groupCenter.get(group)!;
    projects.forEach((p, i) => {
      const angle = (i / Math.max(1, projects.length)) * Math.PI * 2;
      const radius = projects.length > 1 ? 110 + projects.length * 14 : 0;
      center.set(`${group}:${p}`, { x: base.x + Math.cos(angle) * radius, y: base.y + Math.sin(angle) * radius });
    });
  }
  const target = (n: Node) => center.get(`${n.group}:${n.projeto}`) ?? groupCenter.get(n.group)!;
  let seed = 7;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5) * 80;
  for (const n of nodes) {
    const t = target(n);
    n.x = t.x + rand();
    n.y = t.y + rand();
  }
  const links = edges.map(([a, b]) => ({ source: a, target: b, same: nodes[a].projeto === nodes[b].projeto }));
  const sim = forceSimulation<Node>(nodes)
    .force(
      "link",
      forceLink<Node, (typeof links)[number]>(links)
        .distance((l) => (l.same ? 24 : 70))
        .strength((l) => (l.same ? 0.22 : 0.015)),
    )
    .force("charge", forceManyBody<Node>().strength(-22).distanceMax(220))
    .force("x", forceX<Node>((n) => target(n).x).strength(0.07))
    .force("y", forceY<Node>((n) => target(n).y).strength(0.07))
    .force("collide", forceCollide<Node>((n) => n.r + 1.5))
    .stop();
  for (let i = 0; i < 280; i += 1) sim.tick();
  const xy = new Float64Array(nodes.length * 2);
  nodes.forEach((n, i) => {
    xy[i * 2] = n.x;
    xy[i * 2 + 1] = n.y;
  });
  layoutCache = { signature, xy };
}

export function BrainGraph({ client, tick, highlight, current, onOpen }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [data, setData] = useState<{ nodes: Node[]; edges: [number, number][]; groups: BrainGraphData["groups"] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [hiddenGroups, setHiddenGroups] = useState<Set<string>>(new Set());
  const [cross, setCross] = useState(true);
  const [orphans, setOrphans] = useState(true);
  const [hover, setHover] = useState<{ node: Node; x: number; y: number } | null>(null);
  const view = useRef({ k: 1, x: 0, y: 0 });
  const size = useRef({ w: 0, h: 0 });
  const fitted = useRef(false);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const [, redraw] = useState(0);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .brainGraph()
      .then((graph) => {
        if (!alive) return;
        const nodes: Node[] = graph.nodes.map((n, i) => ({ ...n, i, r: n.tipo === "projeto" ? 7 : 2.6 + Math.min(5, Math.sqrt(n.degree) * 0.75), x: 0, y: 0 }));
        // Calcula numa folga do navegador, para a tela aparecer antes.
        window.setTimeout(() => {
          if (!alive) return;
          layout(nodes, graph.edges);
          setData({ nodes, edges: graph.edges, groups: graph.groups });
        }, 20);
      })
      .catch((cause) => alive && setError(cause instanceof Error ? cause.message : String(cause)));
    return () => {
      alive = false;
    };
  }, [client, tick]);

  const neighbors = useMemo(() => {
    const map = new Map<number, Set<number>>();
    for (const [a, b] of data?.edges ?? []) {
      if (!map.has(a)) map.set(a, new Set());
      if (!map.has(b)) map.set(b, new Set());
      map.get(a)!.add(b);
      map.get(b)!.add(a);
    }
    return map;
  }, [data]);

  const visible = useCallback(
    (n: Node) => !hidden.has(categoryOf(n.tipo)) && !hiddenGroups.has(n.group) && (orphans || n.degree > 0),
    [hidden, hiddenGroups, orphans],
  );

  const fit = useCallback(() => {
    if (!data || !size.current.w) return;
    const shown = data.nodes.filter(visible);
    if (!shown.length) return;
    const xs = shown.map((n) => n.x);
    const ys = shown.map((n) => n.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const k = Math.min(size.current.w / (x1 - x0 + 80), size.current.h / (y1 - y0 + 80), 2.5);
    view.current = { k, x: size.current.w / 2 - ((x0 + x1) / 2) * k, y: size.current.h / 2 - ((y0 + y1) / 2) * k };
    redraw((n) => n + 1);
  }, [data, visible]);

  // O App troca o tema depois que o grafo já desenhou: redesenha quando o data-theme mudar.
  useEffect(() => {
    const observer = new MutationObserver(() => redraw((n) => n + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  // Tamanho da tela acompanha o painel.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      size.current = { w: el.clientWidth, h: el.clientHeight };
      if (!fitted.current && data) {
        fitted.current = true;
        fit();
      }
      redraw((n) => n + 1);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [data, fit]);

  useEffect(() => {
    if (data && size.current.w && !fitted.current) {
      fitted.current = true;
      fit();
    }
  }, [data, fit]);

  // Desenho: nuvens, ligações, nós e nomes dos projetos.
  useEffect(() => {
    const el = canvas.current;
    if (!el || !data) return;
    const dpr = window.devicePixelRatio || 1;
    const { w, h } = size.current;
    if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
      el.width = Math.round(w * dpr);
      el.height = Math.round(h * dpr);
    }
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const css = getComputedStyle(document.documentElement);
    const token = (name: string) => css.getPropertyValue(name).trim() || "#888";
    const color = Object.fromEntries(Object.entries(GROUP_VAR).map(([g, v]) => [g, token(v)]));
    const line = token("--line2");
    const accent = token("--acc");
    const text = token("--mut");
    const { k, x: vx, y: vy } = view.current;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(vx, vy);
    ctx.scale(k, k);

    const shown = data.nodes.map(visible);
    const focus = hover?.node.i ?? null;
    const near = focus !== null ? (neighbors.get(focus) ?? new Set<number>()) : null;
    const lit = (i: number) => (near ? i === focus || near.has(i) : highlight ? highlight.has(data.nodes[i].path) : true);

    // Nuvens: um brilho suave atrás de cada área.
    const sums = new Map<string, { x: number; y: number; n: number; r: number }>();
    data.nodes.forEach((n, i) => {
      if (!shown[i]) return;
      const s = sums.get(n.group) ?? { x: 0, y: 0, n: 0, r: 0 };
      s.x += n.x;
      s.y += n.y;
      s.n += 1;
      sums.set(n.group, s);
    });
    for (const [g, s] of sums) {
      const cx = s.x / s.n;
      const cy = s.y / s.n;
      let spread = 0;
      data.nodes.forEach((n, i) => {
        if (shown[i] && n.group === g) spread += Math.hypot(n.x - cx, n.y - cy);
      });
      const radius = Math.max(120, (spread / s.n) * 2.2);
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
      glow.addColorStop(0, `${color[g]}2e`);
      glow.addColorStop(1, `${color[g]}00`);
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fill();
    }

    // Ligações: dentro do projeto em cinza; entre projetos (os precedentes) na cor de acento.
    ctx.lineWidth = Math.max(0.35, 0.8 / k);
    for (const pass of ["plain", "cross"] as const) {
      ctx.strokeStyle = pass === "cross" && cross ? accent : line;
      for (const [a, b] of data.edges) {
        if (!shown[a] || !shown[b]) continue;
        const na = data.nodes[a];
        const nb = data.nodes[b];
        const isCross = !!na.projeto && !!nb.projeto && na.projeto !== nb.projeto;
        if ((pass === "cross") !== isCross) continue;
        const on = near ? (a === focus || b === focus) : lit(a) && lit(b);
        // Com o mouse num nó, as ligações dele acendem; parado, as entre projetos ficam discretas.
        ctx.globalAlpha = on ? (near ? 0.9 : pass === "cross" && cross ? 0.22 : 0.3) : 0.05;
        ctx.beginPath();
        ctx.moveTo(na.x, na.y);
        ctx.lineTo(nb.x, nb.y);
        ctx.stroke();
      }
    }

    // Nós.
    data.nodes.forEach((n, i) => {
      if (!shown[i]) return;
      ctx.globalAlpha = lit(i) ? 1 : 0.14;
      ctx.fillStyle = color[n.group];
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fill();
      if (n.path === current || i === focus) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = accent;
        ctx.lineWidth = Math.max(1, 2 / k);
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + 3 / k + 1, 0, Math.PI * 2);
        ctx.stroke();
        ctx.lineWidth = Math.max(0.35, 0.8 / k);
      }
    });
    ctx.restore();

    // Nomes em tamanho fixo: projetos sempre; o resto só bem de perto.
    ctx.globalAlpha = 1;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    data.nodes.forEach((n, i) => {
      if (!shown[i]) return;
      const project = n.tipo === "projeto";
      // Vizinhos do nó em foco ganham nome se forem poucos (ou de perto); muitos viram um borrão.
      const nearLabel = !!near && near.has(i) && (near.size <= 12 || k >= 1.6);
      if (!project && k < 2.2 && !nearLabel) return;
      const sx = n.x * k + vx;
      const sy = n.y * k + vy + n.r * k + 3;
      if (sx < -100 || sx > w + 100 || sy < -20 || sy > h + 20) return;
      ctx.globalAlpha = lit(i) ? 1 : 0.25;
      ctx.font = project ? '600 11px "Fira Code", ui-monospace, monospace' : "11px Inter, system-ui, sans-serif";
      ctx.fillStyle = project ? token("--tx") : text;
      const label = n.title.length > 42 ? `${n.title.slice(0, 40)}…` : n.title;
      ctx.fillText(label, sx, sy);
    });
  });

  const toWorld = (event: React.PointerEvent | React.WheelEvent) => {
    const rect = box.current!.getBoundingClientRect();
    const mx = event.clientX - rect.left;
    const my = event.clientY - rect.top;
    const { k, x, y } = view.current;
    return { mx, my, wx: (mx - x) / k, wy: (my - y) / k };
  };

  const hit = (wx: number, wy: number): Node | null => {
    if (!data) return null;
    let best: Node | null = null;
    let bestD = Infinity;
    const slack = 5 / view.current.k;
    for (const n of data.nodes) {
      if (!visible(n)) continue;
      const d = Math.hypot(n.x - wx, n.y - wy);
      if (d < n.r + slack && d < bestD) {
        best = n;
        bestD = d;
      }
    }
    return best;
  };

  const zoomAt = (mx: number, my: number, factor: number) => {
    const { k, x, y } = view.current;
    const next = Math.min(8, Math.max(0.08, k * factor));
    view.current = { k: next, x: mx - (mx - x) * (next / k), y: my - (my - y) * (next / k) };
    redraw((n) => n + 1);
  };

  const onWheel = (event: React.WheelEvent) => {
    const { mx, my } = toWorld(event);
    if (event.ctrlKey || event.metaKey) {
      // Pinça do trackpad (ou ⌘ + roda): zoom no ponto do cursor.
      zoomAt(mx, my, Math.exp(-event.deltaY * 0.01));
    } else {
      // Dois dedos: anda pelo grafo.
      view.current = { ...view.current, x: view.current.x - event.deltaX, y: view.current.y - event.deltaY };
      redraw((n) => n + 1);
    }
  };

  const onPointerDown = (event: React.PointerEvent) => {
    (event.target as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, vx: view.current.x, vy: view.current.y, moved: false };
  };

  const onPointerMove = (event: React.PointerEvent) => {
    const d = drag.current;
    if (d) {
      const dx = event.clientX - d.x;
      const dy = event.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
      if (d.moved) {
        view.current = { ...view.current, x: d.vx + dx, y: d.vy + dy };
        setHover(null);
        redraw((n) => n + 1);
        return;
      }
    }
    const { mx, my, wx, wy } = toWorld(event);
    const node = hit(wx, wy);
    setHover((last) => (node ? { node, x: mx, y: my } : last ? null : last));
  };

  const onPointerUp = (event: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved) {
      const { wx, wy } = toWorld(event);
      const node = hit(wx, wy);
      if (node) onOpen(node.path);
    }
  };

  const toggle = (set: Set<string>, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  };

  const shownCount = data ? data.nodes.filter(visible).length : 0;

  return (
    <div className="graph" ref={box}>
      <canvas
        ref={canvas}
        className="graph-canvas"
        style={{ cursor: hover ? "pointer" : drag.current?.moved ? "grabbing" : "grab" }}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setHover(null)}
        aria-label="Grafo das notas do Brain"
      />
      {!data && <div className="graph-status small">{error ? `Não deu para montar o grafo: ${error}` : "Montando o grafo…"}</div>}
      {data && (
        <>
          <div className="graph-bar" role="group" aria-label="Filtros do grafo">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className="filter-chip"
                aria-pressed={!hidden.has(f.key)}
                onClick={() => setHidden((s) => toggle(s, f.key))}
              >
                {f.label}
              </button>
            ))}
            <span className="graph-sep" />
            <button type="button" className="filter-chip" aria-pressed={cross} onClick={() => setCross((v) => !v)} title="Ligações entre notas de projetos diferentes">
              Precedentes entre projetos
            </button>
            <button type="button" className="filter-chip" aria-pressed={orphans} onClick={() => setOrphans((v) => !v)}>
              Notas sem ligação
            </button>
          </div>
          <div className="graph-legend" aria-label="Áreas">
            {data.groups.map((g) => (
              <button
                key={g.key}
                type="button"
                className="graph-legend-item"
                aria-pressed={!hiddenGroups.has(g.key)}
                onClick={() => setHiddenGroups((s) => toggle(s, g.key))}
                title={g.key === "semarea" ? "Projetos cuja nota não tem area: no frontmatter" : undefined}
              >
                <span className="graph-dot" style={{ background: `var(${GROUP_VAR[g.key]})` }} />
                {g.label}
                <span className="mono">{g.count}</span>
              </button>
            ))}
          </div>
          <div className="graph-zoom">
            <span className="small mono">
              {shownCount} notas · {data.edges.length} ligações
            </span>
            <button type="button" className="icon-btn" title="Aproximar" aria-label="Aproximar" onClick={() => zoomAt(size.current.w / 2, size.current.h / 2, 1.3)}>
              +
            </button>
            <button type="button" className="icon-btn" title="Afastar" aria-label="Afastar" onClick={() => zoomAt(size.current.w / 2, size.current.h / 2, 1 / 1.3)}>
              −
            </button>
            <button type="button" className="btn graph-fit" onClick={fit}>
              Centralizar
            </button>
          </div>
          {hover && (
            <div className="graph-tip" style={{ left: hover.x + 14, top: hover.y + 10 }}>
              <div className="graph-tip-title">
                {TYPE_ICON[hover.node.tipo] ?? "·"} {hover.node.title}
              </div>
              <div className="small mono">
                {[TYPE_LABEL[hover.node.tipo] ?? hover.node.tipo, hover.node.projeto, hover.node.status, hover.node.data].filter(Boolean).join(" · ")}
                {` · ${hover.node.degree} ligações`}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
