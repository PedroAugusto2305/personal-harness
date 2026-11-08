// Sugestão de precedente (v0.8): um registro novo de outro projeto que o juiz achou que vale
// aqui. Aceitar vira decisão aceita no projeto alvo, pelo brain.py; dá para editar antes.
import { useState } from "react";
import type { CoreClient } from "../lib/core";
import { TYPE_ICON } from "../lib/obsidian";
import type { Suggestion } from "../types";

interface Props {
  client: CoreClient | null;
  item: Suggestion;
  /** Mostra "para <projeto>" no topo (fora do painel do próprio projeto). */
  showTarget?: boolean;
  compact?: boolean;
  onOpenNote: (title: string) => void;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export function SuggestionCard({ client, item, showTarget, compact, onOpenNote, onDone, onError }: Props) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [resumo, setResumo] = useState(item.resumo);
  const [busy, setBusy] = useState<"" | "aceitar" | "recusar">("");
  const [result, setResult] = useState<Suggestion | null>(item.status === "pendente" ? null : item);

  const accept = async () => {
    if (!client || busy) return;
    setBusy("aceitar");
    try {
      const done = await client.acceptSuggestion(item.id, title.trim(), resumo.trim());
      setResult(done);
      onDone(`Virou decisão em ${done.target_project}: ${done.title}`);
    } catch (cause) {
      onError(`Não aceitei: ${message(cause)}`);
    } finally {
      setBusy("");
    }
  };

  const reject = async () => {
    if (!client || busy) return;
    setBusy("recusar");
    try {
      setResult(await client.rejectSuggestion(item.id));
    } catch (cause) {
      onError(`Não recusei: ${message(cause)}`);
    } finally {
      setBusy("");
    }
  };

  if (result && result.status !== "pendente") {
    return (
      <div className="suggestion done" data-status={result.status}>
        {result.status === "aceita" ? (
          <>
            ✓ Decisão aceita em {result.target_project}:{" "}
            <button type="button" className="link-btn" onClick={() => onOpenNote(result.title)}>
              {result.title}
            </button>
          </>
        ) : (
          <>Recusada: {result.title}</>
        )}
      </div>
    );
  }

  return (
    <div className="suggestion" data-compact={compact || undefined}>
      <div className="suggestion-head small mono">
        💡 {showTarget ? `para ${item.target_project}` : "sugestão"} · de{" "}
        <button type="button" className="link-btn" onClick={() => onOpenNote(item.source_title)} title={`Abrir a nota de origem: ${item.source_title}`}>
          {TYPE_ICON[item.source_tipo] ?? "·"} {item.source_project}
        </button>
      </div>
      {editing ? (
        <>
          <input className="suggestion-title-input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Título da decisão" />
          <textarea className="suggestion-resumo-input" value={resumo} rows={3} onChange={(e) => setResumo(e.target.value)} aria-label="Resumo da decisão" />
        </>
      ) : (
        <>
          <div className="suggestion-title">{title}</div>
          <p className="suggestion-resumo small">{resumo}</p>
        </>
      )}
      <p className="suggestion-why small">
        <strong>Por quê:</strong> {item.motivo}
      </p>
      {!compact && item.matches.length > 0 && (
        <div className="suggestion-matches small">
          Parecido com:{" "}
          {item.matches.map((m, i) => (
            <span key={m.path}>
              {i > 0 && " · "}
              <button type="button" className="link-btn" onClick={() => onOpenNote(m.title)}>
                {TYPE_ICON[m.tipo] ?? "·"} {m.title}
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="suggestion-actions">
        <button type="button" className="btn primary" disabled={!!busy || !title.trim() || !resumo.trim()} onClick={() => void accept()}>
          {busy === "aceitar" ? "Registrando…" : "Aceitar como decisão"}
        </button>
        <button type="button" className="btn" disabled={!!busy} onClick={() => setEditing((v) => !v)}>
          {editing ? "Pronto" : "Editar"}
        </button>
        <button type="button" className="link-btn" disabled={!!busy} onClick={() => void reject()}>
          Recusar
        </button>
      </div>
    </div>
  );
}
