import { useEffect, useRef, useState } from "react";
import type { CoreClient } from "../lib/core";
import type { CodeGraph as Graph, CoreEvent } from "../types";

export type CodeGraphEvent = Extract<CoreEvent, { type: "codigo.grafo" }>;

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
export function CodeGraphLine({
  client,
  root,
  onAgent,
  event,
}: {
  client: CoreClient;
  root: string;
  onAgent: (prompt: string) => void;
  /** O aviso codigo.grafo do núcleo: é ele que diz que o `graphify update` acabou ou deu erro. */
  event: CodeGraphEvent | null;
}) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [updating, setUpdating] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  /** O último aviso que já existia no clique: só um aviso novo encerra o "atualizando". */
  const before = useRef<CodeGraphEvent | null>(null);

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

  // O fim de verdade vem do núcleo: com erro, o graph.json não muda e a data nunca serviria.
  useEffect(() => {
    if (!updating || !event || event === before.current || event.root !== root) return;
    setUpdating(false);
    setFailure(event.status === "erro" ? event.detalhe || "o graphify update falhou" : null);
  }, [event, root, updating]);

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
              before.current = event;
              setUpdating(true);
              setFailure(null);
              void client.updateCodeGraph(root).catch(() => setUpdating(false));
            }}
          >
            {updating ? "atualizando…" : "atualizar"}
          </button>
          {failure && <span className="error-text">Não atualizou: {failure}</span>}
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
