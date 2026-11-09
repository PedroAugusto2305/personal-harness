import { useEffect, useRef, useState } from "react";
import type * as Monaco from "monaco-editor";
import { CoreError, type CoreClient } from "../lib/core";
import { dirtyDocs } from "../lib/editors";
import { applyMonacoTheme, languageFor, loadMonaco, type MonacoApi } from "../lib/monaco";
import type { ThemeName } from "../types";

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

function storedFlag(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw == null ? fallback : raw === "true";
  } catch {
    return fallback;
  }
}

interface Props {
  client: CoreClient;
  /** Chave da aba (para o aviso de mudança não salva ao fechar). */
  docKey: string;
  root: string;
  path: string;
  theme: ThemeName;
  visible: boolean;
  onError: (message: string) => void;
}

/**
 * Editor de arquivo da worktree (v0.9.7): o Monaco, o editor do VS Code, dentro da aba.
 * ⌘S salva (ou "Salvar sozinho"); só grava se o arquivo não mudou no disco desde que
 * abriu. Se o agente mexer no arquivo: sem edição pendente, a aba recarrega sozinha; com
 * edição pendente, aparece o aviso, com as duas versões lado a lado para decidir.
 */
export function CodeEditor({ client, docKey, root, path, theme, visible, onError }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const diffHost = useRef<HTMLDivElement>(null);
  const editor = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<MonacoApi | null>(null);
  /** O que está no disco (texto e hash) desde a última leitura ou gravação. */
  const disk = useRef<{ hash: string; text: string } | null>(null);
  const [ready, setReady] = useState(false);
  const [readOnly, setReadOnly] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState<{ text: string; hash: string } | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [autosave, setAutosave] = useState(() => storedFlag("harness.editor.autosave", false));
  const live = useRef({ save: async (_force?: string) => undefined as void, onError });
  live.current.onError = onError;

  useEffect(() => {
    if (dirty) dirtyDocs.add(docKey);
    else dirtyDocs.delete(docKey);
    return () => {
      dirtyDocs.delete(docKey);
    };
  }, [dirty, docKey]);

  const save = async (force?: string) => {
    const ed = editor.current;
    if (!ed || !disk.current || readOnly) return;
    const text = ed.getValue();
    setSaving(true);
    try {
      const answer = await client.writeText(root, path, text, force ?? disk.current.hash);
      disk.current = { hash: answer.hash, text };
      setDirty(ed.getValue() !== text);
      setConflict(null);
      setShowDiff(false);
    } catch (cause) {
      if (cause instanceof CoreError && cause.status === 409) {
        const now = await client.readText(root, path).catch(() => null);
        if (now?.hash) setConflict({ text: now.text, hash: now.hash });
      } else {
        live.current.onError(errorText(cause));
      }
    } finally {
      setSaving(false);
    }
  };
  live.current.save = save;

  // Monta o Monaco uma vez por arquivo.
  useEffect(() => {
    let disposed = false;
    let created: Monaco.editor.IStandaloneCodeEditor | null = null;
    (async () => {
      const [monaco, file] = await Promise.all([loadMonaco(), client.readText(root, path)]);
      if (disposed || !host.current) return;
      monacoRef.current = monaco;
      const locked = file.binary ? "arquivo binário" : file.truncated ? "maior que 2 MB: só leitura" : null;
      setReadOnly(locked);
      const uri = monaco.Uri.file(`${root}/${path}`);
      monaco.editor.getModel(uri)?.dispose();
      const model = monaco.editor.createModel(file.text, languageFor(path), uri);
      created = monaco.editor.create(host.current, {
        model,
        theme: applyMonacoTheme(monaco, theme),
        automaticLayout: true,
        fontFamily: '"Fira Code", ui-monospace, monospace',
        fontLigatures: true,
        fontSize: 13,
        lineHeight: 20,
        readOnly: !!locked,
        scrollBeyondLastLine: false,
        wordWrap: /\.(md|mdx|txt)$/i.test(path) ? "on" : "off",
        renderWhitespace: "selection",
        minimap: { enabled: true, renderCharacters: false },
        smoothScrolling: true,
        padding: { top: 8 },
      });
      disk.current = { hash: file.hash ?? "", text: file.text };
      created.onDidChangeModelContent(() => setDirty(created!.getValue() !== disk.current?.text));
      created.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => void live.current.save());
      editor.current = created;
      setReady(true);
    })().catch((cause) => !disposed && live.current.onError(errorText(cause)));
    return () => {
      disposed = true;
      created?.getModel()?.dispose();
      created?.dispose();
      editor.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, root, path]);

  useEffect(() => {
    if (monacoRef.current && ready) applyMonacoTheme(monacoRef.current, theme);
  }, [theme, ready]);

  // O agente (ou outro programa) mudou o arquivo: recarrega se não há edição pendente.
  useEffect(() => {
    if (!visible || !ready) return;
    const timer = window.setInterval(async () => {
      const ed = editor.current;
      if (!ed || !disk.current || saving) return;
      const now = await client.readText(root, path).catch(() => null);
      if (!now?.hash || now.hash === disk.current.hash) return;
      if (ed.getValue() === disk.current.text) {
        const view = ed.saveViewState();
        const model = ed.getModel()!;
        model.pushEditOperations([], [{ range: model.getFullModelRange(), text: now.text }], () => null);
        ed.restoreViewState(view);
        disk.current = { hash: now.hash, text: now.text };
        setDirty(false);
      } else {
        setConflict({ text: now.text, hash: now.hash });
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [client, root, path, visible, ready, saving]);

  // Salvar sozinho: 1 s depois da última tecla.
  useEffect(() => {
    try {
      localStorage.setItem("harness.editor.autosave", String(autosave));
    } catch {
      // sem armazenamento: só não lembra
    }
    if (!autosave || !dirty || conflict || readOnly) return;
    const timer = window.setTimeout(() => void live.current.save(), 1000);
    return () => window.clearTimeout(timer);
  });

  // As duas versões lado a lado: o disco à esquerda, a sua à direita.
  useEffect(() => {
    const monaco = monacoRef.current;
    const ed = editor.current;
    if (!showDiff || !conflict || !monaco || !ed || !diffHost.current) return;
    const original = monaco.editor.createModel(conflict.text, languageFor(path));
    const modified = monaco.editor.createModel(ed.getValue(), languageFor(path));
    const diff = monaco.editor.createDiffEditor(diffHost.current, {
      automaticLayout: true,
      readOnly: true,
      renderSideBySide: true,
      fontFamily: '"Fira Code", ui-monospace, monospace',
      fontSize: 12.5,
    });
    diff.setModel({ original, modified });
    return () => {
      diff.dispose();
      original.dispose();
      modified.dispose();
    };
  }, [showDiff, conflict, path]);

  const takeDisk = () => {
    const ed = editor.current;
    if (!ed || !conflict) return;
    const model = ed.getModel()!;
    model.pushEditOperations([], [{ range: model.getFullModelRange(), text: conflict.text }], () => null);
    disk.current = { hash: conflict.hash, text: conflict.text };
    setDirty(false);
    setConflict(null);
    setShowDiff(false);
  };

  return (
    <div className="code-editor">
      <div className="editor-bar small">
        {readOnly ? (
          <span className="editor-state">{readOnly}</span>
        ) : saving ? (
          <span className="editor-state">salvando…</span>
        ) : dirty ? (
          <span className="editor-state dirty">● não salvo · ⌘S salva</span>
        ) : (
          <span className="editor-state">salvo</span>
        )}
        <span className="grow" />
        {!readOnly && (
          <label className="editor-autosave">
            <input type="checkbox" checked={autosave} onChange={(e) => setAutosave(e.target.checked)} />
            Salvar sozinho
          </label>
        )}
      </div>
      {conflict && (
        <div className="editor-conflict">
          <span>
            <b>O arquivo mudou no disco</b> (o agente?) enquanto você editava.
          </span>
          <span className="grow" />
          <button type="button" className="pill ghost" onClick={() => setShowDiff((v) => !v)}>
            {showDiff ? "Esconder as diferenças" : "Ver as diferenças"}
          </button>
          <button type="button" className="pill ghost" onClick={takeDisk}>
            Ficar com o do disco
          </button>
          <button type="button" className="pill danger" disabled={saving} onClick={() => void save(conflict.hash)}>
            Salvar o meu por cima
          </button>
        </div>
      )}
      {conflict && showDiff && (
        <div className="editor-diff">
          <div className="editor-diff-labels small">
            <span>no disco</span>
            <span>o seu</span>
          </div>
          <div className="editor-diff-host" ref={diffHost} />
        </div>
      )}
      <div className="editor-host" ref={host} hidden={!!(conflict && showDiff)}>
        {!ready && <p className="small doc-empty">carregando o editor…</p>}
      </div>
    </div>
  );
}
