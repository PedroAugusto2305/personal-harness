import { useEffect, useRef, useState } from "react";
import type { EditorView } from "@codemirror/view";
import { CoreError, type CoreClient } from "../lib/core";
import { dirtyDocs } from "../lib/editors";
import { createNoteEditor, replaceText } from "../lib/noteEditor";

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** O que está no vault (texto e hash) desde a última leitura ou gravação. */
type Disk = { hash: string; text: string };

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
  const disk = useRef<Disk | null>(null);
  /** v1.0.0: a gravação a caminho do vault, e de qual editor; resolve com o que ficou gravado (null se falhou). */
  const inflight = useRef<{ editor: EditorView; run: Promise<Disk | null> } | null>(null);
  const [ready, setReady] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Disk | null>(null);
  /** v1.0.0: a gravação falhou (nota vazia, apagada, conflito sem releitura): o salvar sozinho
   * espera a próxima tecla. Antes tentava de novo a cada 1,2 s, sem fim. */
  const [stalled, setStalled] = useState(false);
  /** v1.0.0: a nota não está em UTF-8 e abre só para leitura (gravar estragaria os acentos). */
  const [locked, setLocked] = useState(false);
  const live = useRef({ save: (_force?: string): Promise<Disk | null> => Promise.resolve(null), onOpenNote, onError, onSaved });
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

  const save = (force?: string): Promise<Disk | null> => {
    const editor = view.current;
    const base = disk.current;
    if (!editor || !base || locked) return Promise.resolve(null);
    if (inflight.current) return inflight.current.run; // uma gravação de cada vez; o resto vai na próxima
    const text = editor.state.doc.toString();
    if (text === base.text && !force) return Promise.resolve(null);
    setSaving(true);
    const run = (async (): Promise<Disk | null> => {
      try {
        const answer = await client.saveBrainNote(path, text, force ?? base.hash);
        const saved = { hash: answer.hash, text };
        live.current.onSaved?.();
        if (view.current !== editor) return saved; // a nota já saiu da tela: a gravação da saída usa este hash
        disk.current = saved;
        setDirty(editor.state.doc.toString() !== text);
        setConflict(null);
        setProblem(null);
        setStalled(false);
        return saved;
      } catch (cause) {
        if (view.current !== editor) return null; // a nota já saiu da tela: quem avisa é a gravação da saída
        const now = cause instanceof CoreError && cause.status === 409 ? await client.brainNoteText(path).catch(() => null) : null;
        if (now && view.current === editor) {
          setConflict({ text: now.texto, hash: now.hash });
        } else {
          setStalled(true);
          if (cause instanceof CoreError && cause.status === 400) setProblem(errorText(cause)); // nota vazia: o Brain nunca apaga
          else live.current.onError(cause instanceof CoreError && cause.status === 409 ? `A nota ${path} mudou fora daqui e não deu para ler a versão nova.` : errorText(cause));
        }
        return null;
      } finally {
        inflight.current = null;
        setSaving(false);
      }
    })();
    inflight.current = { editor, run };
    return run;
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
        const readOnly = note.utf8 === false;
        created = createNoteEditor(host.current, {
          text: note.texto,
          readOnly,
          onChange: (text) => {
            setDirty(text !== disk.current?.text);
            setStalled(false);
          },
          onSave: () => void live.current.save(),
          titles: (query) => client.brainTitles(query, 12),
          known: (titles) => client.brainKnown(titles),
          onOpenNote: (title) => live.current.onOpenNote(title),
        });
        // O texto como o CodeMirror o guarda (CRLF vira LF): comparar com o texto cru do disco
        // daria "mudou" sem ninguém ter editado.
        disk.current = { hash: note.hash, text: created.state.doc.toString() };
        view.current = created;
        setLocked(readOnly);
        setProblem(readOnly ? "Esta nota não está em UTF-8: abre só para leitura, porque gravar daqui estragaria os acentos." : null);
        setDirty(false);
        setConflict(null);
        setStalled(false);
        setReady(true);
        created.focus();
      })
      .catch((cause) => !disposed && live.current.onError(errorText(cause)));
    return () => {
      disposed = true;
      const base = disk.current;
      const text = created?.state.doc.toString();
      const prior = created && inflight.current?.editor === created ? inflight.current.run : null;
      created?.destroy();
      view.current = null;
      // v1.0.0: o que ainda esperava os 1,2 s (clicou num [[link]], abriu outra nota, voltou a
      // Ler) é gravado agora. Antes sumia junto com o editor. Se havia uma gravação a caminho,
      // espera por ela e grava por cima do que ela deixou.
      if (!created || !base || text === undefined || text === base.text || !text.trim()) return;
      void (async () => {
        const from = (prior ? await prior : null) ?? base;
        if (text === from.text) return;
        try {
          await client.saveBrainNote(path, text, from.hash);
          live.current.onSaved?.();
        } catch (cause) {
          live.current.onError(
            cause instanceof CoreError && cause.status === 409
              ? `A nota ${path} mudou fora daqui (no Obsidian?) e a sua última edição não foi gravada.`
              : `A sua última edição em ${path} não foi gravada: ${errorText(cause)}`,
          );
        }
      })();
    };
  }, [client, path]);

  // Salva sozinho, como o Obsidian.
  useEffect(() => {
    if (!dirty || conflict || !ready || saving || stalled || locked) return;
    const timer = window.setTimeout(() => void live.current.save(), 1200);
    return () => window.clearTimeout(timer);
  });

  // O Obsidian (ou um agente pelo brain.py) gravou a nota: recarrega se não há edição pendente.
  useEffect(() => {
    if (!visible || !ready) return;
    const timer = window.setInterval(async () => {
      const editor = view.current;
      const before = disk.current;
      if (!editor || !before || inflight.current) return;
      const now = await client.brainNoteText(path).catch(() => null);
      // Uma gravação começou ou terminou enquanto lia: o que veio pode ser de antes dela, e
      // recarregar trocaria o texto recém-gravado pela versão velha.
      if (inflight.current || disk.current !== before || view.current !== editor) return;
      if (!now || now.hash === before.hash) return;
      if (editor.state.doc.toString() === before.text) {
        replaceText(editor, now.texto);
        disk.current = { hash: now.hash, text: editor.state.doc.toString() };
        setDirty(false);
      } else {
        setConflict((shown) => (shown?.hash === now.hash ? shown : { text: now.texto, hash: now.hash }));
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [client, path, visible, ready]);

  const takeTheirs = () => {
    if (!view.current || !conflict) return;
    replaceText(view.current, conflict.text);
    disk.current = { hash: conflict.hash, text: view.current.state.doc.toString() };
    setDirty(false);
    setConflict(null);
  };

  return (
    <div className="note-editor">
      <div className="editor-bar small">
        {locked ? (
          <span className="editor-state">só leitura</span>
        ) : saving ? (
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
