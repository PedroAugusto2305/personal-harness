import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import { useMemo } from "react";
import type { BrainGraphData, GraphNodeData } from "../types";

/**
 * Grafo por projeto (v0.9.9, o desenho do mockup): cada projeto é um nó com nome, com as notas
 * mais ligadas dele em volta, e as ligações entre projetos (decisões citadas de um projeto
 * no outro) aparecem em destaque. Leve: SVG, posições calculadas uma vez.
 */

const GROUP_VAR: Record<string, string> = {
  carreira: "var(--g-carreira)",
  trabalho: "var(--g-trabalho)",
  clientes: "var(--g-clientes)",
  pessoal: "var(--g-pessoal)",
  brain: "var(--g-brain)",
  semarea: "var(--g-semarea)",
};

interface GNode extends SimulationNodeDatum {
  id: string;
  label: string;
  project: string;
  group: string;
  hub: boolean;
  r: number;
  path: string;
}

interface GLink extends SimulationLinkDatum<GNode> {
  cross: boolean;
  weight: number;
}

export interface ProjectGraphLayout {
  nodes: GNode[];
  links: { a: GNode; b: GNode; cross: boolean; weight: number }[];
  box: { x: number; y: number; w: number; h: number };
}

/**
 * Monta e assenta o grafo (300 passos de força, sem animação) e encaixa num quadro de
 * `width` × `height`, para o texto ficar do mesmo tamanho em qualquer tamanho de grafo.
 */
export function layoutProjects(
  data: BrainGraphData,
  satellites = 5,
  crossMax = 14,
  hidden: Set<string> = new Set(),
  width = 400,
  height = 290,
): ProjectGraphLayout {
  const byProject = new Map<string, GraphNodeData[]>();
  data.nodes.forEach((n) => {
    if (!n.projeto || hidden.has(n.group)) return;
    byProject.set(n.projeto, [...(byProject.get(n.projeto) ?? []), n]);
  });
  const nodes: GNode[] = [];
  const links: GLink[] = [];
  const hubOf = new Map<string, GNode>();
  for (const [project, notes] of byProject) {
    const own = notes.find((n) => n.tipo === "projeto") ?? notes[0];
    const hub: GNode = { id: `p:${project}`, label: project, project, group: own.group, hub: true, r: 5 + Math.min(4, Math.sqrt(notes.length) * 0.6), path: own.path };
    nodes.push(hub);
    hubOf.set(project, hub);
    notes
      .filter((n) => n !== own)
      .sort((a, b) => b.degree - a.degree)
      .slice(0, satellites)
      .forEach((n) => {
        const sat: GNode = { id: n.path, label: n.title, project, group: n.group, hub: false, r: 2.2 + Math.min(2.2, Math.sqrt(n.degree) * 0.4), path: n.path };
        nodes.push(sat);
        links.push({ source: hub, target: sat, cross: false, weight: 1 });
      });
  }
  // Ligações entre projetos: as arestas de notas de projetos diferentes, somadas por par.
  const pairs = new Map<string, number>();
  for (const [i, j] of data.edges) {
    const a = data.nodes[i]?.projeto;
    const b = data.nodes[j]?.projeto;
    if (!a || !b || a === b || !hubOf.has(a) || !hubOf.has(b)) continue;
    const key = a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`;
    pairs.set(key, (pairs.get(key) ?? 0) + 1);
  }
  [...pairs.entries()]
    .sort((x, y) => y[1] - x[1])
    .slice(0, crossMax)
    .forEach(([key, weight]) => {
      const [a, b] = key.split("\u0000");
      links.push({ source: hubOf.get(a)!, target: hubOf.get(b)!, cross: true, weight });
    });

  const sim = forceSimulation<GNode>(nodes)
    .force("charge", forceManyBody<GNode>().strength((n) => (n.hub ? -340 : -26)))
    .force(
      "link",
      forceLink<GNode, GLink>(links)
        .distance((l) => (l.cross ? 150 : 24))
        .strength((l) => (l.cross ? 0.04 : 0.9)),
    )
    .force("collide", forceCollide<GNode>((n) => n.r + (n.hub ? 28 : 3)))
    .force("x", forceX<GNode>(0).strength(0.05))
    .force("y", forceY<GNode>(0).strength(0.07))
    .stop();
  for (let i = 0; i < 300; i++) sim.tick();

  // Encaixa no quadro (com margem para os nomes), sem distorcer.
  const xs = nodes.map((n) => n.x ?? 0);
  const ys = nodes.map((n) => n.y ?? 0);
  const minX = Math.min(...xs, 0);
  const minY = Math.min(...ys, 0);
  const spanX = Math.max(1, Math.max(...xs, 0) - minX);
  const spanY = Math.max(1, Math.max(...ys, 0) - minY);
  const padX = 46;
  const padY = 22;
  const scale = Math.min((width - padX * 2) / spanX, (height - padY * 2 - 10) / spanY);
  const offX = (width - spanX * scale) / 2;
  const offY = (height - 10 - spanY * scale) / 2;
  for (const n of nodes) {
    n.x = offX + ((n.x ?? 0) - minX) * scale;
    n.y = offY + ((n.y ?? 0) - minY) * scale;
  }
  return {
    nodes,
    links: links.map((l) => ({ a: l.source as GNode, b: l.target as GNode, cross: l.cross, weight: l.weight })),
    box: { x: 0, y: 0, w: width, h: height },
  };
}

interface Props {
  data: BrainGraphData | null;
  /** Notas em volta de cada projeto. */
  satellites?: number;
  /** Tamanho do quadro do desenho (o SVG se ajusta à caixa). */
  width?: number;
  height?: number;
  /** Grupos (áreas) escondidos. */
  hidden?: Set<string>;
  showCross?: boolean;
  /** O projeto (ou a nota) em destaque, e as ligações dele. */
  focus?: string | null;
  className?: string;
  label?: string;
  onProject?: (name: string) => void;
  onNote?: (path: string) => void;
}

export function ProjectGraph({ data, satellites = 5, width = 400, height = 290, hidden, showCross = true, focus = null, className, label, onProject, onNote }: Props) {
  const hiddenKey = [...(hidden ?? [])].sort().join(",");
  const layout = useMemo(
    () => (data ? layoutProjects(data, satellites, 14, new Set(hiddenKey ? hiddenKey.split(",") : []), width, height) : null),
    [data, satellites, hiddenKey, width, height],
  );
  if (!layout) return <div className={className} aria-busy="true" />;
  const { nodes, links, box } = layout;
  const lit = (n: GNode) => !!focus && (n.project === focus || n.path === focus);
  return (
    <svg className={className} viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={label ?? `Grafo do Brain: ${nodes.filter((n) => n.hub).length} projetos`}>
      <g>
        {links
          .filter((l) => !l.cross)
          .map((l) => (
            <line key={`${l.a.id}-${l.b.id}`} x1={l.a.x} y1={l.a.y} x2={l.b.x} y2={l.b.y} className="pg-link" />
          ))}
      </g>
      {showCross && (
        <g>
          {links
            .filter((l) => l.cross)
            .map((l) => (
              <line
                key={`${l.a.id}-${l.b.id}`}
                x1={l.a.x}
                y1={l.a.y}
                x2={l.b.x}
                y2={l.b.y}
                className="pg-cross"
                data-lit={focus && (l.a.project === focus || l.b.project === focus) ? "true" : undefined}
                strokeWidth={Math.min(3, 0.9 + Math.log2(1 + l.weight) * 0.5)}
              >
                <title>
                  {l.a.project} ↔ {l.b.project}: {l.weight} {l.weight === 1 ? "ligação" : "ligações"}
                </title>
              </line>
            ))}
        </g>
      )}
      <g>
        {nodes.map((n) => (
          <circle
            key={n.id}
            cx={n.x}
            cy={n.y}
            r={n.r}
            className={n.hub ? "pg-hub" : "pg-note"}
            data-lit={lit(n) ? "true" : undefined}
            style={{ fill: GROUP_VAR[n.group] ?? "var(--g-semarea)" }}
            onClick={() => (n.hub ? onProject?.(n.project) : onNote?.(n.path))}
          >
            <title>{n.hub ? `${n.label} (projeto)` : `${n.label} · ${n.project}`}</title>
          </circle>
        ))}
      </g>
      <g>
        {nodes
          .filter((n) => n.hub)
          .map((n) => (
            <text key={`t-${n.id}`} x={n.x} y={(n.y ?? 0) + n.r + 11} className="pg-label" data-lit={lit(n) ? "true" : undefined} textAnchor="middle" onClick={() => onProject?.(n.project)}>
              {n.label.length > 24 ? `${n.label.slice(0, 23)}…` : n.label}
            </text>
          ))}
      </g>
    </svg>
  );
}
