import { useEffect, useState } from "react";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, money, shortPath } from "../lib/format";
import { renderInline } from "../lib/obsidian";
import type { AgentPanelItem, PanelColumn, SessionKind } from "../types";

const COLUMNS: { key: PanelColumn; label: string; dot: string; hint: string }[] = [
  { key: "precisa", label: "Precisa de você", dot: "var(--warn)", hint: "uma pergunta ou um pedido de licença" },
  { key: "trabalhando", label: "Trabalhando", dot: "var(--run)", hint: "" },
  { key: "feito", label: "Feito", dot: "var(--acc)", hint: "terminou o turno: veja o que ele fez" },
  { key: "parado", label: "Parado", dot: "var(--line2)", hint: "esperando sem pedir nada, hibernando ou fechado" },
];

/** "há 3 min", "há 2 h", "há 1 d". */
function since(epoch: number): string {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - epoch) / 60));
  if (minutes < 1) return "agora";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `há ${hours} h` : `há ${Math.round(hours / 24)} d`;
}

function duration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/**
 * Painel de agentes (v0.9.8): cada Claude e Codex aberto como um cartão, na coluna do estado
 * dele. Clicar leva ao terminal. Atualiza sozinho enquanto aparece.
 */
export function AgentsBoard({ client, onOpenSession, onError }: { client: CoreClient; onOpenSession: (id: string) => void; onError: (message: string) => void }) {
  const [items, setItems] = useState<AgentPanelItem[] | null>(null);

  useEffect(() => {
    let alive = true;
    let warned = false;
    const load = () =>
      void client
        .agentsPanel()
        .then((answer) => alive && setItems(answer.agentes))
        .catch((cause) => {
          if (alive && !warned) {
            warned = true;
            onError(cause instanceof Error ? cause.message : String(cause));
          }
        });
    load();
    const timer = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  return (
    <div className="kb-board">
      {COLUMNS.map((column) => {
        const list = (items ?? []).filter((item) => item.coluna === column.key).sort((a, b) => b.desde - a.desde);
        return (
          <section key={column.key} className="kb-col" aria-label={column.label}>
            <header className="kb-col-head">
              <span className="kb-dot" style={{ background: column.dot }} />
              <span>{column.label}</span>
              <span className="kb-count mono">{list.length}</span>
            </header>
            {column.hint && <p className="kb-hint small">{column.hint}</p>}
            <div className="kb-cards">
              {list.map((item) => (
                <button key={item.id} type="button" className="kb-card agent-card" onClick={() => onOpenSession(item.id)} title="Ir para o terminal">
                  <div className="kb-card-title">
                    <span style={{ color: KIND_COLOR[item.cli as SessionKind] }}>{KIND_GLYPH[item.cli as SessionKind] ?? "›"}</span> {item.titulo}
                  </div>
                  <div className="kb-meta small mono">
                    {shortPath(item.cwd)} · {since(item.desde)}
                    {item.tag ? ` · ${item.tag}` : ""}
                  </div>
                  {item.previa && <div className="agent-preview small" dangerouslySetInnerHTML={{ __html: renderInline(item.previa) }} />}
                  <div className="kb-meta small mono">
                    aberto há {duration(item.duracao_s)}
                    {item.custo_usd != null && ` · ${money(item.custo_usd)}`}
                  </div>
                </button>
              ))}
              {items !== null && list.length === 0 && <p className="kb-hint small">ninguém</p>}
            </div>
          </section>
        );
      })}
      {items !== null && items.length === 0 && <p className="kb-empty small">Nenhum Claude ou Codex aberto. Os agentes aparecem aqui conforme o estado deles.</p>}
    </div>
  );
}
