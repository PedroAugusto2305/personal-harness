import { useEffect, useRef, useState } from "react";
import type { EditorView } from "@codemirror/view";
import { CoreError, type CoreClient } from "../lib/core";
import { dirtyDocs } from "../lib/editors";
import { createNoteEditor, replaceText } from "../lib/noteEditor";

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

interface Props {
  client: CoreClient;
  /** Caminho da nota relativo ao vault. */
  path: string;
  /** Chave para o aviso de mudança não salva (aba ou "brain"). */
  docKey: string;
  visible: boolean;
  onOpenNote: (title: string) => void;
  onError: (message: string) => void;
  /** A nota foi gravada (o leitor e o índice recarregam). */
  onSaved?: () => void;
}

/**
 * Editor de nota do Brain (v0.9.7): CodeMirror com a visualização ao vivo do Obsidian.
 * Salva sozinho 1,2 s depois da última tecla (⌘S salva na hora), sempre conferindo que o
 * Obsidian não gravou depois; se gravou, nada é sobrescrito sem você escolher.
 */
export function NoteEditor({ client, path, docKey, visible, onOpenNote, onError, onSaved }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const disk = useRef<{ hash: string; text: string } | null>(null);
  const [ready, setReady] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ text: string; hash: string } | null>(null);
  const live = useRef({ save: async (_force?: string) => undefined as void, onOpenNote, onError, onSaved });
  live.current.onOpenNote = onOpenNote;
  live.current.onError = onError;
  live.current.onSaved = onSaved;

  useEffect(() => {
    if (dirty) dirtyDocs.add(docKey);
    else dirtyDocs.delete(docKey);
    return () => {
      dirtyDocs.delete(docKey);
    };
  }, [dirty, docKey]);

  const save = async (force?: string) => {
    const editor = view.current;
    if (!editor || !disk.current) return;
    const text = editor.state.doc.toString();
    if (text === disk.current.text && !force) return;
    setSaving(true);
    try {
      const answer = await client.saveBrainNote(path, text, force ?? disk.current.hash);
      disk.current = { hash: answer.hash, text };
      setDirty(editor.state.doc.toString() !== text);
      setConflict(null);
      setProblem(null);
      live.current.onSaved?.();
    } catch (cause) {
      if (cause instanceof CoreError && cause.status === 409) {
        const now = await client.brainNoteText(path).catch(() => null);
        if (now) setConflict({ text: now.texto, hash: now.hash });
      } else if (cause instanceof CoreError && cause.status === 400) {
        setProblem(errorText(cause)); // nota vazia: o Brain nunca apaga
      } else {
        live.current.onError(errorText(cause));
      }
    } finally {
      setSaving(false);
    }
  };
  live.current.save = save;

  useEffect(() => {
    let disposed = false;
    let created: EditorView | null = null;
    setReady(false);
    client
      .brainNoteText(path)
      .then((note) => {
        if (disposed || !host.current) return;
        disk.current = { hash: note.hash, text: note.texto };
        created = createNoteEditor(host.current, {
          text: note.texto,
          onChange: (text) => setDirty(text !== disk.current?.text),
          onSave: () => void live.current.save(),
          titles: (query) => client.brainTitles(query, 12),
          known: (titles) => client.brainKnown(titles),
          onOpenNote: (title) => live.current.onOpenNote(title),
        });
        view.current = created;
        setDirty(false);
        setConflict(null);
        setReady(true);
        created.focus();
      })
      .catch((cause) => !disposed && live.current.onError(errorText(cause)));
    return () => {
      disposed = true;
      created?.destroy();
      view.current = null;
    };
  }, [client, path]);

  // Salva sozinho, como o Obsidian.
  useEffect(() => {
    if (!dirty || conflict || !ready) return;
    const timer = window.setTimeout(() => void live.current.save(), 1200);
    return () => window.clearTimeout(timer);
  });

  // O Obsidian (ou um agente pelo brain.py) gravou a nota: recarrega se não há edição pendente.
  useEffect(() => {
    if (!visible || !ready) return;
    const timer = window.setInterval(async () => {
      const editor = view.current;
      if (!editor || !disk.current || saving) return;
      const now = await client.brainNoteText(path).catch(() => null);
      if (!now || now.hash === disk.current.hash) return;
      if (editor.state.doc.toString() === disk.current.text) {
        replaceText(editor, now.texto);
        disk.current = { hash: now.hash, text: now.texto };
        setDirty(false);
      } else {
        setConflict({ text: now.texto, hash: now.hash });
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [client, path, visible, ready, saving]);

  const takeTheirs = () => {
    if (!view.current || !conflict) return;
    replaceText(view.current, conflict.text);
    disk.current = { hash: conflict.hash, text: conflict.text };
    setDirty(false);
    setConflict(null);
  };

  return (
    <div className="note-editor">
      <div className="editor-bar small">
        {saving ? (
          <span className="editor-state">salvando…</span>
        ) : dirty ? (
          <span className="editor-state dirty">● salva sozinho em instantes (⌘S agora)</span>
        ) : (
          <span className="editor-state">salvo no vault</span>
        )}
        <span className="grow" />
        <span className="editor-hint">[[ liga a uma nota · / insere um bloco</span>
      </div>
      {problem && <div className="error-box">{problem}</div>}
      {conflict && (
        <div className="editor-conflict">
          <span>
            <b>A nota mudou fora daqui</b> (no Obsidian?) enquanto você editava.
          </span>
          <span className="grow" />
          <button type="button" className="pill ghost" onClick={takeTheirs}>
            Ficar com a de fora
          </button>
          <button type="button" className="pill danger" disabled={saving} onClick={() => void save(conflict.hash)}>
            Gravar a minha por cima
          </button>
        </div>
      )}
      <div className="note-editor-host" ref={host}>
        {!ready && <p className="small doc-empty">carregando a nota…</p>}
      </div>
    </div>
  );
}
