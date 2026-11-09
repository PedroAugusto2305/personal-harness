import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type ForceLink,
  type ForceManyBody,
  type ForceX,
  type ForceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
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

interface Link extends SimulationLinkDatum<Node> {
  same: boolean;
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

// --- Forças, no jeito do Obsidian: quatro controles de 0 a 100 ----------------------------------

interface Forces {
  center: number;
  repel: number;
  link: number;
  distance: number;
}

// O padrão reproduz o layout que o grafo tinha antes dos controles.
const DEFAULT_FORCES: Forces = { center: 35, repel: 15, link: 45, distance: 18 };
const FORCES_KEY = "metis.graph.forces";

const FORCE_LABEL: { key: keyof Forces; label: string; hint: string }[] = [
  { key: "center", label: "Força de centro", hint: "puxa cada nota para a nuvem da área e o centro do projeto" },
  { key: "repel", label: "Repulsão", hint: "as notas se empurram" },
  { key: "link", label: "Força das ligações", hint: "quanto uma ligação puxa as duas notas" },
  { key: "distance", label: "Distância das ligações", hint: "comprimento da ligação em repouso" },
];

/** Controle (0 a 100) → valor da força. As ligações entre projetos são bem mais frouxas. */
const physics = (f: Forces) => ({
  center: (f.center / 100) * 0.2,
  repel: -(4 + (f.repel / 100) * 120),
  link: (f.link / 100) * 0.5,
  distance: 8 + (f.distance / 100) * 90,
});

function loadForces(): Forces {
  try {
    const saved = JSON.parse(localStorage.getItem(FORCES_KEY) ?? "null");
    if (saved && typeof saved === "object") return { ...DEFAULT_FORCES, ...saved };
  } catch {
    // sem armazenamento: fica o padrão
  }
  return DEFAULT_FORCES;
}

/** Posições guardadas por conjunto de notas: voltar ao grafo não recomeça do zero. */
let positions: { signature: string; xy: Float64Array } | null = null;
const signatureOf = (nodes: Node[], edges: [number, number][]) =>
  `${nodes.length}:${edges.length}:${nodes[0]?.path}:${nodes[nodes.length - 1]?.path}`;

/** Centro de cada nota: a nuvem da área, e dentro dela o ponto do projeto. */
function anchors(nodes: Node[]): (n: Node) => { x: number; y: number } {
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
  return (n: Node) => center.get(`${n.group}:${n.projeto}`) ?? groupCenter.get(n.group)!;
}

interface Sim {
  simulation: Simulation<Node, Link>;
  link: ForceLink<Node, Link>;
  charge: ForceManyBody<Node>;
  fx: ForceX<Node>;
  fy: ForceY<Node>;
}

function applyForces(sim: Sim, f: Forces): void {
  const p = physics(f);
  sim.link.distance((l) => (l.same ? p.distance : p.distance * 3)).strength((l) => (l.same ? p.link : p.link * 0.07));
  sim.charge.strength(p.repel);
  sim.fx.strength(p.center);
  sim.fy.strength(p.center);
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
  /** Nomes dos projetos no grafo. Desligado: o nome só aparece passando o mouse (pedido do Pedro). */
  const [names, setNames] = useState(false);
  const [forces, setForces] = useState<Forces>(loadForces);
  const [showForces, setShowForces] = useState(false);
  const forcesNow = useRef(forces);
  forcesNow.current = forces;
  const [hover, setHover] = useState<{ node: Node; x: number; y: number } | null>(null);
  const view = useRef({ k: 1, x: 0, y: 0 });
  const size = useRef({ w: 0, h: 0 });
  const touched = useRef(false); // o Pedro já mexeu na vista: não reenquadra sozinho
  const fitted = useRef(false);
  const sim = useRef<Sim | null>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean; node: Node | null } | null>(null);
  const paint = useRef<() => void>(() => undefined);
  const frame = useRef(0);

  /** Um desenho por quadro, no máximo: a simulação chama isto a cada passo. */
  const schedule = useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      paint.current();
    });
  }, []);

  // Zera a marca ao cancelar: no StrictMode o React desmonta e remonta, e uma marca presa
  // deixava o agendador achando que já havia um quadro a caminho (o grafo nunca desenhava).
  useEffect(
    () => () => {
      cancelAnimationFrame(frame.current);
      frame.current = 0;
    },
    [],
  );

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .brainGraph()
      .then((graph) => {
        if (!alive) return;
        const nodes: Node[] = graph.nodes.map((n, i) => ({
          ...n,
          i,
          r: n.tipo === "projeto" ? 7 : 2.6 + Math.min(5, Math.sqrt(n.degree) * 0.75),
          x: 0,
          y: 0,
        }));
        setData({ nodes, edges: graph.edges, groups: graph.groups });
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
    let [x0, x1, y0, y1] = [Infinity, -Infinity, Infinity, -Infinity];
    for (const n of shown) {
      x0 = Math.min(x0, n.x);
      x1 = Math.max(x1, n.x);
      y0 = Math.min(y0, n.y);
      y1 = Math.max(y1, n.y);
    }
    const k = Math.min(size.current.w / (x1 - x0 + 80), size.current.h / (y1 - y0 + 80), 2.5);
    view.current = { k, x: size.current.w / 2 - ((x0 + x1) / 2) * k, y: size.current.h / 2 - ((y0 + y1) / 2) * k };
    schedule();
  }, [data, visible, schedule]);

  // A simulação vive enquanto o grafo está na tela, como no Obsidian.
  useEffect(() => {
    if (!data) return;
    const { nodes, edges } = data;
    const signature = signatureOf(nodes, edges);
    const target = anchors(nodes);
    const cached = positions?.signature === signature ? positions.xy : null;
    let seed = 7;
    const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5) * 80;
    nodes.forEach((n, i) => {
      const t = target(n);
      n.x = cached ? cached[i * 2] : t.x + rand();
      n.y = cached ? cached[i * 2 + 1] : t.y + rand();
      n.vx = 0;
      n.vy = 0;
    });
    const links: Link[] = edges.map(([a, b]) => ({ source: a, target: b, same: nodes[a].projeto === nodes[b].projeto }));
    const link = forceLink<Node, Link>(links);
    const charge = forceManyBody<Node>().distanceMax(260).theta(0.9);
    const fx = forceX<Node>((n) => target(n).x);
    const fy = forceY<Node>((n) => target(n).y);
    const simulation = forceSimulation<Node, Link>(nodes)
      .force("link", link)
      .force("charge", charge)
      .force("x", fx)
      .force("y", fy)
      .force("collide", forceCollide<Node>((n) => n.r + 1.5))
      .stop();
    const current: Sim = { simulation, link, charge, fx, fy };
    applyForces(current, forcesNow.current);
    sim.current = current;

    const save = () => {
      const xy = new Float64Array(nodes.length * 2);
      nodes.forEach((n, i) => {
        xy[i * 2] = n.x;
        xy[i * 2 + 1] = n.y;
      });
      positions = { signature, xy };
    };
    simulation.on("tick", schedule);
    simulation.on("end", () => {
      save();
      if (!touched.current) fit();
    });
    if (cached) {
      // Já acomodado antes: aparece parado, e só anda quando alguém mexer.
      simulation.alpha(0);
      fitted.current = false;
    } else {
      // Primeiros passos sem desenhar, para não abrir num emaranhado; o resto anima.
      simulation.alpha(1);
      for (let i = 0; i < 60; i += 1) simulation.tick();
      simulation.restart();
    }
    if (size.current.w) {
      fitted.current = true;
      fit();
    }
    return () => {
      simulation.stop();
      save();
      sim.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // Mexer num controle das forças rearruma o grafo na hora.
  useEffect(() => {
    try {
      localStorage.setItem(FORCES_KEY, JSON.stringify(forces));
    } catch {
      // sem armazenamento: vale só nesta sessão
    }
    const s = sim.current;
    if (!s) return;
    applyForces(s, forces);
    s.simulation.alpha(Math.max(s.simulation.alpha(), 0.5)).restart();
  }, [forces]);

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
      schedule();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [data, fit, schedule]);

  // O App troca o tema depois que o grafo já desenhou: redesenha quando o data-theme mudar.
  useEffect(() => {
    const observer = new MutationObserver(schedule);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, [schedule]);

  // Desenho: nuvens, ligações, nós e nomes. Sempre com o estado mais recente (hover, filtros, busca).
  paint.current = () => {
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
    const token = (name: string) => css.getPropertyValue(name).trim() || "#888888";
    const color = Object.fromEntries(Object.entries(GROUP_VAR).map(([g, v]) => [g, token(v)]));
    const line = token("--line2");
    const accent = token("--acc");
    const text = token("--mut");
    const strong = token("--tx");
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
    const sums = new Map<string, { x: number; y: number; n: number }>();
    data.nodes.forEach((n, i) => {
      if (!shown[i]) return;
      const s = sums.get(n.group) ?? { x: 0, y: 0, n: 0 };
      s.x += n.x;
      s.y += n.y;
      s.n += 1;
      sums.set(n.group, s);
    });
    const spread = new Map<string, number>();
    data.nodes.forEach((n, i) => {
      if (!shown[i]) return;
      const s = sums.get(n.group)!;
      spread.set(n.group, (spread.get(n.group) ?? 0) + Math.hypot(n.x - s.x / s.n, n.y - s.y / s.n));
    });
    for (const [g, s] of sums) {
      const cx = s.x / s.n;
      const cy = s.y / s.n;
      const radius = Math.max(120, ((spread.get(g) ?? 0) / s.n) * 2.2);
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
        const on = near ? a === focus || b === focus : lit(a) && lit(b);
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

    // Nomes: por padrão nenhum (o do nó sob o mouse vem na dica); com "Nomes", os dos projetos.
    if (!names) return;
    ctx.globalAlpha = 1;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    data.nodes.forEach((n, i) => {
      if (!shown[i]) return;
      const project = n.tipo === "projeto";
      if (!project) return;
      const sx = n.x * k + vx;
      const sy = n.y * k + vy + n.r * k + 3;
      if (sx < -100 || sx > w + 100 || sy < -20 || sy > h + 20) return;
      ctx.globalAlpha = lit(i) ? 1 : 0.25;
      ctx.font = project ? '600 11px "Fira Code", ui-monospace, monospace' : "11px Inter, system-ui, sans-serif"; // o canvas não lê variável CSS
      ctx.fillStyle = project ? strong : text;
      const label = n.title.length > 42 ? `${n.title.slice(0, 40)}…` : n.title;
      ctx.fillText(label, sx, sy);
    });
  };

  // Qualquer mudança de estado (hover, filtro, busca) redesenha.
  useEffect(() => schedule());

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
    touched.current = true;
    const { k, x, y } = view.current;
    const next = Math.min(8, Math.max(0.08, k * factor));
    view.current = { k: next, x: mx - (mx - x) * (next / k), y: my - (my - y) * (next / k) };
    schedule();
  };

  const onWheel = (event: React.WheelEvent) => {
    const { mx, my } = toWorld(event);
    if (event.ctrlKey || event.metaKey) {
      // Pinça do trackpad (ou ⌘ + roda): zoom no ponto do cursor.
      zoomAt(mx, my, Math.exp(-event.deltaY * 0.01));
    } else {
      // Dois dedos: anda pelo grafo.
      touched.current = true;
      view.current = { ...view.current, x: view.current.x - event.deltaX, y: view.current.y - event.deltaY };
      schedule();
    }
  };

  const onPointerDown = (event: React.PointerEvent) => {
    (event.target as HTMLElement).setPointerCapture(event.pointerId);
    const { wx, wy } = toWorld(event);
    const node = hit(wx, wy);
    drag.current = { x: event.clientX, y: event.clientY, vx: view.current.x, vy: view.current.y, moved: false, node };
  };

  const onPointerMove = (event: React.PointerEvent) => {
    const d = drag.current;
    const { mx, my, wx, wy } = toWorld(event);
    if (d) {
      const dx = event.clientX - d.x;
      const dy = event.clientY - d.y;
      if (!d.moved && Math.abs(dx) + Math.abs(dy) > 3) {
        d.moved = true;
        // Arrastar um nó: ele segue o mouse e a simulação acorda, puxando os vizinhos.
        if (d.node && sim.current) sim.current.simulation.alphaTarget(0.25).restart();
      }
      if (d.moved) {
        if (d.node) {
          d.node.fx = wx;
          d.node.fy = wy;
          setHover({ node: d.node, x: mx, y: my });
        } else {
          touched.current = true;
          view.current = { ...view.current, x: d.vx + dx, y: d.vy + dy };
          setHover(null);
        }
        schedule();
        return;
      }
    }
    const node = hit(wx, wy);
    setHover((last) => (node ? { node, x: mx, y: my } : last ? null : last));
  };

  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.node && !d.moved) {
      onOpen(d.node.path);
      return;
    }
    if (d.node) {
      // Solto, o nó volta a obedecer às forças, como no Obsidian.
      d.node.fx = null;
      d.node.fy = null;
      sim.current?.simulation.alphaTarget(0);
    }
  };

  const toggle = (set: Set<string>, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  };

  const reheat = () => sim.current?.simulation.alpha(1).restart();

  const shownCount = data ? data.nodes.filter(visible).length : 0;

  return (
    <div className="graph" ref={box}>
      <canvas
        ref={canvas}
        className="graph-canvas"
        style={{ cursor: drag.current?.moved ? "grabbing" : hover ? "pointer" : "grab" }}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => !drag.current && setHover(null)}
        aria-label="Grafo das notas do Brain"
      />
      {!data && <div className="graph-status small">{error ? `Não deu para montar o grafo: ${error}` : "Montando o grafo…"}</div>}
      {data && (
        <>
          <div className="graph-bar" role="group" aria-label="Filtros do grafo">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" className="filter-chip" aria-pressed={!hidden.has(f.key)} onClick={() => setHidden((s) => toggle(s, f.key))}>
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
            <button type="button" className="filter-chip" aria-pressed={names} onClick={() => setNames((v) => !v)} title="Mostra o nome dos projetos no grafo">
              Nomes
            </button>
            <span className="graph-sep" />
            <button type="button" className="filter-chip" aria-pressed={showForces} aria-expanded={showForces} onClick={() => setShowForces((v) => !v)}>
              Forças
            </button>
          </div>
          {showForces && (
            <div className="graph-forces" role="group" aria-label="Forças do grafo">
              {FORCE_LABEL.map(({ key, label, hint }) => (
                <label key={key} className="graph-force" title={hint}>
                  <span>
                    {label}
                    <span className="mono">{forces[key]}</span>
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={forces[key]}
                    onChange={(event) => setForces((f) => ({ ...f, [key]: Number(event.target.value) }))}
                  />
                </label>
              ))}
              <div className="graph-forces-actions">
                <button type="button" className="link-btn" onClick={() => setForces(DEFAULT_FORCES)}>
                  restaurar padrão
                </button>
                <button type="button" className="link-btn" onClick={reheat}>
                  reorganizar
                </button>
              </div>
            </div>
          )}
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
            <button
              type="button"
              className="btn graph-fit"
              onClick={() => {
                touched.current = false;
                fit();
              }}
            >
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
