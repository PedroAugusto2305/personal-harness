// Mini-mapa do Brain no canto do terminal (v0.8, padrão 6 do docs/DESIGN.md): o projeto da
// sessão em âmbar no centro e, em volta, as notas que ela viu (precedentes do início, leituras,
// buscas e conflitos pelo MCP) e as que ela registrou. Clique abre a nota no Brain.
import { useEffect, useMemo, useState } from "react";
import type { CoreClient } from "../lib/core";
import { TYPE_ICON } from "../lib/obsidian";
import type { SessionMap, SessionMapNode } from "../types";

const W = 168;
const H = 112;
const AMBER = "#f5b942";
const TYPE_FILL: Record<string, string> = {
  decisao: "var(--acc)",
  incidente: "var(--err)",
  aprendizado: "var(--wait)",
  entrega: "var(--run)",
  projeto: AMBER,
};
const VIA_LABEL: Record<string, string> = {
  início: "precedente do início",
  precedente: "precedente pedido",
  leitura: "lida",
  busca: "achada na busca",
  conflito: "checada antes de decidir",
  sugestão: "sugestão",
  registro: "registrada nesta sessão",
};
const KEY = "metis.minimap.open";

function stored(): boolean {
  try {
    return localStorage.getItem(KEY) !== "0";
  } catch {
    return true;
  }
}

interface Props {
  client: CoreClient;
  sessionId: string;
  tick: number;
  onOpenNote: (title: string) => void;
}

export function MiniMap({ client, sessionId, tick, onOpenNote }: Props) {
  const [data, setData] = useState<SessionMap | null>(null);
  const [open, setOpen] = useState(stored);
  const [hover, setHover] = useState<SessionMapNode | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      void client
        .sessionMap(sessionId)
        .then((found) => alive && setData(found))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 90_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client, sessionId, tick]);

  const layout = useMemo(() => {
    const nodes = data?.nodes ?? [];
    const cx = W / 2;
    const cy = H / 2;
    // Um anel até 10 notas; depois, dois (dentro as do próprio projeto, fora as dos outros).
    const inner = nodes.filter((n) => n.projeto === data?.project);
    const outer = nodes.filter((n) => n.projeto !== data?.project);
    const rings: [SessionMapNode[], number][] = nodes.length <= 10 ? [[nodes, 40]] : [[inner, 26], [outer, 46]];
    const at = new Map<string, { x: number; y: number }>();
    for (const [list, radius] of rings) {
      list.forEach((node, i) => {
        const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, list.length);
        at.set(node.path, { x: cx + radius * 1.45 * Math.cos(angle), y: cy + radius * Math.sin(angle) });
      });
    }
    return { cx, cy, at, nodes };
  }, [data]);

  if (!data?.project) return null;
  const count = data.nodes.length;
  const toggle = () => {
    setOpen((v) => {
      try {
        localStorage.setItem(KEY, v ? "0" : "1");
      } catch {
        // sem armazenamento: vale só nesta janela
      }
      return !v;
    });
  };

  if (!open) {
    return (
      <button type="button" className="minimap-chip" onClick={toggle} title={`Brain desta sessão: ${data.project} e ${count} nota(s) vistas`}>
        🧠 {count}
      </button>
    );
  }

  const { cx, cy, at, nodes } = layout;
  return (
    <div className="minimap" onMouseLeave={() => setHover(null)}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Mini-mapa do Brain: ${data.project}`}>
        {nodes.map((n) => {
          const p = at.get(n.path);
          return p ? <line key={`c-${n.path}`} x1={cx} y1={cy} x2={p.x} y2={p.y} className="minimap-spoke" data-other={n.projeto !== data.project || undefined} /> : null;
        })}
        {data.edges.map(([a, b]) => {
          const p = at.get(nodes[a]?.path ?? "");
          const q = at.get(nodes[b]?.path ?? "");
          return p && q ? <line key={`e-${a}-${b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} className="minimap-edge" /> : null;
        })}
        <circle cx={cx} cy={cy} r={6} fill={AMBER} className="minimap-center" />
        {nodes.map((n) => {
          const p = at.get(n.path);
          if (!p) return null;
          const mine = n.via.includes("registro");
          return (
            <circle
              key={n.path}
              cx={p.x}
              cy={p.y}
              r={hover?.path === n.path ? 5.5 : 4}
              fill={TYPE_FILL[n.tipo] ?? "var(--mut)"}
              stroke={mine ? AMBER : n.projeto !== data.project ? "var(--tx)" : "none"}
              strokeWidth={mine ? 1.6 : 0.6}
              className="minimap-node"
              onMouseEnter={() => setHover(n)}
              onClick={() => onOpenNote(n.title)}
            >
              <title>{n.title}</title>
            </circle>
          );
        })}
      </svg>
      <div className="minimap-caption small">
        {hover ? (
          <>
            {TYPE_ICON[hover.tipo] ?? "·"} {hover.title}
            <span className="mono">
              {" "}
              · {hover.projeto || "sem projeto"} · {hover.via.map((v) => VIA_LABEL[v] ?? v).join(", ")}
            </span>
          </>
        ) : (
          <>
            <span style={{ color: AMBER }}>●</span> {data.project}
            <span className="mono"> · {count ? `${count} nota${count > 1 ? "s" : ""} do Brain` : "nenhuma nota ainda"}</span>
          </>
        )}
      </div>
      <button type="button" className="minimap-close" onClick={toggle} title="Recolher o mini-mapa" aria-label="Recolher o mini-mapa">
        ×
      </button>
    </div>
  );
}
