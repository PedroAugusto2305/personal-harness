import { useEffect, useRef, useState } from "react";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, ago, shortPath } from "../lib/format";
import type { HistoryItem } from "../types";

interface Props {
  client: CoreClient | null;
  /** Pasta da worktree em foco, para o filtro "só aqui" (vazio = sem filtro). */
  here: string;
  hereLabel: string | null;
  /** Abre a sessão retomada; devolve o erro, se houver, para mostrar aqui mesmo. */
  onResume: (item: HistoryItem) => Promise<string | null>;
  onClose: () => void;
}

/**
 * "Retomar uma conversa" (v0.9.2): as conversas do Claude e do Codex que estão no disco, de
 * todas as contas, mais novas primeiro. Retomar abre a CLI com `--resume` na pasta e na conta
 * em que a conversa aconteceu. A busca vai ao núcleo (título, primeiro pedido e pasta).
 */
export function HistoryPanel({ client, here, hereLabel, onResume, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [onlyHere, setOnlyHere] = useState(false);
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ id: string; text: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => input.current?.focus(), []);

  // Busca com espera curta: o núcleo lê o começo e o fim de cada arquivo.
  useEffect(() => {
    if (!client) return;
    let alive = true;
    const timer = window.setTimeout(
      () => {
        client
          .history(query.trim(), onlyHere ? here : "", 80)
          .then((found) => {
            if (!alive) return;
            setItems(found);
            setLoadError(null);
            setIndex(0);
          })
          .catch((cause) => alive && setLoadError(cause instanceof Error ? cause.message : String(cause)));
      },
      items === null ? 0 : 250,
    );
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, query, onlyHere, here]);

  useEffect(() => {
    list.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  const resume = async (item: HistoryItem | undefined) => {
    if (!item || busy) return;
    setBusy(item.id);
    setError(null);
    const problem = await onResume(item);
    setBusy(null);
    if (problem) setError({ id: item.id, text: problem });
    else onClose();
  };

  const shown = items ?? [];
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className="palette history-panel" role="dialog" aria-label="Retomar uma conversa" onMouseDown={(event) => event.stopPropagation()}>
        <div className="history-search">
          <input
            ref={input}
            value={query}
            placeholder="Retomar uma conversa: busque pelo título, pelo pedido ou pela pasta…"
            spellCheck={false}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setIndex((i) => Math.min(shown.length - 1, i + 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setIndex((i) => Math.max(0, i - 1));
              } else if (event.key === "Enter") {
                event.preventDefault();
                void resume(shown[index]);
              } else if (event.key === "Escape") {
                event.preventDefault();
                onClose();
              }
            }}
          />
          {here && (
            <button
              type="button"
              className="filter-chip"
              aria-pressed={onlyHere}
              title={shortPath(here)}
              onClick={() => {
                setOnlyHere((v) => !v);
                input.current?.focus();
              }}
            >
              só em {hereLabel ?? shortPath(here)}
            </button>
          )}
        </div>
        <ul ref={list} className="history-list" aria-label="Conversas">
          {loadError && <li className="error-box history-error">{loadError}</li>}
          {!loadError && items === null && <li className="palette-empty">Lendo as conversas…</li>}
          {!loadError && items !== null && shown.length === 0 && (
            <li className="palette-empty">
              {query.trim() ? `Nenhuma conversa com “${query.trim()}”.` : "Nenhuma conversa do Claude ou do Codex no disco ainda."}
            </li>
          )}
          {shown.map((item, i) => (
            <li
              key={`${item.cli}-${item.id}`}
              className="history-item"
              data-index={i}
              aria-selected={i === index}
              title="Clique duas vezes para retomar"
              onMouseEnter={() => setIndex(i)}
              onDoubleClick={() => void resume(item)}
            >
              <span className="history-glyph" style={{ color: KIND_COLOR[item.cli] }} aria-hidden="true">
                {KIND_GLYPH[item.cli]}
              </span>
              <span className="history-main">
                <span className="history-title">{item.titulo || "(sem título)"}</span>
                {item.primeiro && item.primeiro !== item.titulo && <span className="small history-first">{item.primeiro}</span>}
                <span className="small mono history-meta">
                  {shortPath(item.cwd)} · {item.conta} · <span title={new Date(item.atualizado * 1000).toLocaleString("pt-BR")}>{ago(item.atualizado * 1000)}</span>
                </span>
                {error?.id === item.id && <span className="history-problem">{error.text}</span>}
              </span>
              <button type="button" className="btn" disabled={!!busy} onClick={() => void resume(item)}>
                {busy === item.id ? "Abrindo…" : "Retomar"}
              </button>
            </li>
          ))}
        </ul>
        <footer className="history-foot small">
          ↑↓ escolhe · ↵ retoma · esc fecha · abre na pasta e na conta em que a conversa aconteceu
        </footer>
      </div>
    </div>
  );
}
