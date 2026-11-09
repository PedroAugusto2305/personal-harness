import { useEffect, useState } from "react";
import type { CoreClient } from "../lib/core";
import type { CodeGraph as Graph } from "../types";

function age(epoch: number): string {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - epoch) / 60));
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `há ${hours} h` : `há ${Math.round(hours / 24)} dias`;
}

/**
 * Grafo do código (v0.9.8): o graphify desta worktree. Com o grafo, os agentes daqui ganham
 * as ferramentas codigo_grafo_* na central; atualizar não usa IA, gerar do zero é com o Claude.
 */
export function CodeGraphLine({ client, root, onAgent }: { client: CoreClient; root: string; onAgent: (prompt: string) => void }) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      void client
        .codeGraph(root)
        .then((value) => alive && setGraph(value))
        .catch(() => alive && setGraph(null));
    load();
    // Atualizando em segundo plano: confere de tempos em tempos até a data do grafo mudar.
    const timer = updating ? window.setInterval(load, 3000) : 0;
    return () => {
      alive = false;
      if (timer) window.clearInterval(timer);
    };
  }, [client, root, updating]);

  useEffect(() => {
    if (!updating || !graph?.atualizado) return;
    if (Date.now() / 1000 - graph.atualizado < 30) setUpdating(false);
  }, [graph, updating]);

  if (!graph || !graph.graphify) return null;
  return (
    <div className="code-graph small">
      {graph.existe ? (
        <>
          <span>
            Grafo do código: {graph.nos ?? "?"} nós{graph.atualizado ? `, ${age(graph.atualizado)}` : ""}. Os agentes daqui consultam pela central.
          </span>
          <button
            type="button"
            className="link-btn"
            disabled={updating}
            title="Reextrai o código mudado (sem IA)"
            onClick={() => {
              setUpdating(true);
              void client.updateCodeGraph(root).catch(() => setUpdating(false));
            }}
          >
            {updating ? "atualizando…" : "atualizar"}
          </button>
        </>
      ) : (
        <>
          <span>Sem grafo do código nesta worktree.</span>
          <button type="button" className="link-btn" title="O agente da worktree roda /graphify (usa o seu plano)" onClick={() => onAgent("/graphify .")}>
            gerar com o agente
          </button>
        </>
      )}
    </div>
  );
}
