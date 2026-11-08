import { useEffect, useMemo, useState, type CSSProperties } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { parseDiff, type DiffLine } from "../lib/diff";
import { baseName, viewerFor } from "../lib/tree";
import type { ReviewNote, TextFile } from "../types";

/** Aba que não é terminal: o diff de um arquivo ou um arquivo aberto. */
export interface DocTab {
  key: string;
  type: "diff" | "file" | "web";
  root: string;
  /** Caminho do arquivo; numa aba de navegador, o endereço inicial. */
  path: string;
  untracked?: boolean;
  /** Só nas abas de navegador: o rótulo da página nativa. */
  label?: string;
  incognito?: boolean;
}

export function docTitle(doc: DocTab, webTitle?: string | null): string {
  if (doc.type === "web") {
    if (webTitle) return webTitle;
    const host = doc.path.replace(/^https?:\/\//, "").split("/")[0];
    return host && doc.path !== "about:blank" ? host : "Nova aba";
  }
  return doc.type === "diff" ? `Δ ${baseName(doc.path)}` : baseName(doc.path);
}

interface DocProps {
  doc: DocTab;
  client: CoreClient;
  visible: boolean;
  focused: boolean;
  slot: "tile" | "hidden";
  /** Posição do painel na divisão (v0.9.3). */
  box?: CSSProperties;
  notes: ReviewNote[];
  onAddNote: (note: Omit<ReviewNote, "id">) => void;
  onRemoveNote: (id: string) => void;
  onFocus: () => void;
  onOpenFile: (path: string) => void;
  onError: (message: string) => void;
}

export function DocView(props: DocProps) {
  return (
    <section
      className="pane doc-pane"
      data-slot={props.slot}
      style={props.slot === "tile" ? props.box : undefined}
      data-focused={props.focused ? "true" : undefined}
      hidden={props.slot === "hidden"}
      onMouseDown={props.onFocus}
      aria-label={docTitle(props.doc)}
    >
      {props.doc.type === "diff" ? <DiffView {...props} /> : <FileView {...props} />}
    </section>
  );
}

function DiffView({ doc, client, visible, notes, onAddNote, onRemoveNote, onOpenFile }: DocProps) {
  const [mode, setMode] = useState<"head" | "staged" | "worktree">("head");
  const [raw, setRaw] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (!visible) return;
    let alive = true;
    const load = () =>
      client.gitDiff(doc.root, doc.path, mode, !!doc.untracked).then(
        (text) => alive && setRaw(text),
        (cause) => alive && setRaw(`erro: ${cause instanceof Error ? cause.message : String(cause)}`),
      );
    void load();
    const timer = window.setInterval(load, 4000); // o agente pode estar mexendo no arquivo
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client, doc.root, doc.path, doc.untracked, mode, visible]);

  const parsed = useMemo(() => parseDiff(raw ?? ""), [raw]);
  const fileNotes = notes.filter((n) => n.file === doc.path);
  const noteAt = (line: DiffLine) =>
    fileNotes.filter((n) => (n.side === "new" ? n.line === line.new : n.line === line.old && line.new == null));

  const save = (line: DiffLine) => {
    if (!draft.trim()) return setEditing(null);
    onAddNote({
      file: doc.path,
      line: (line.new ?? line.old)!,
      side: line.new != null ? "new" : "old",
      code: line.text.trim().slice(0, 160),
      text: draft.trim(),
    });
    setDraft("");
    setEditing(null);
  };

  return (
    <>
      <div className="doc-head">
        <Icon d={ICON.file} size={14} />
        <span className="doc-path mono">{doc.path}</span>
        {raw != null && !raw.startsWith("erro:") && (
          <span className="small mono">
            <span style={{ color: "var(--run)" }}>+{parsed.added}</span> <span style={{ color: "var(--err)" }}>−{parsed.removed}</span>
          </span>
        )}
        <span className="grow" />
        {!doc.untracked && (
          <div className="segmented" role="radiogroup" aria-label="O que comparar">
            {(
              [
                ["head", "Tudo"],
                ["staged", "Marcado"],
                ["worktree", "Não marcado"],
              ] as const
            ).map(([key, label]) => (
              <button key={key} type="button" role="radio" aria-checked={mode === key} onClick={() => setMode(key)}>
                {label}
              </button>
            ))}
          </div>
        )}
        <button type="button" className="pill" onClick={() => onOpenFile(doc.path)}>
          Abrir arquivo
        </button>
      </div>
      <div className="diff-body mono">
        {raw == null && <p className="small doc-empty">carregando…</p>}
        {raw?.startsWith("erro:") && <div className="error-box">{raw.slice(5)}</div>}
        {raw != null && !raw.startsWith("erro:") && parsed.binary && <p className="small doc-empty">Arquivo binário: abra para ver.</p>}
        {raw != null && !raw.startsWith("erro:") && !parsed.binary && parsed.lines.length === 0 && (
          <p className="small doc-empty">Sem diferenças neste modo.</p>
        )}
        {parsed.lines.map((line, index) => {
          if (line.kind === "hunk") {
            return (
              <div key={index} className="diff-hunk">
                {line.text || "···"}
              </div>
            );
          }
          const lineNotes = noteAt(line);
          return (
            <div key={index}>
              <div className={`diff-line ${line.kind}`}>
                <span className="ln">{line.old ?? ""}</span>
                <span className="ln">{line.new ?? ""}</span>
                <button
                  type="button"
                  className="add-note"
                  title="Anotar esta linha para o agente"
                  aria-label="Anotar esta linha"
                  onClick={() => {
                    setEditing(index);
                    setDraft("");
                  }}
                >
                  <Icon d={ICON.plus} size={11} strokeWidth={2.4} />
                </button>
                <span className="sign">{line.kind === "add" ? "+" : line.kind === "del" ? "−" : " "}</span>
                <span className="code">{line.text || " "}</span>
              </div>
              {lineNotes.map((note) => (
                <div key={note.id} className="diff-note">
                  <Icon d={ICON.note} size={12} />
                  <span>{note.text}</span>
                  <button type="button" className="icon-btn" aria-label="Apagar nota" onClick={() => onRemoveNote(note.id)}>
                    <Icon d={ICON.close} size={11} strokeWidth={2} />
                  </button>
                </div>
              ))}
              {editing === index && (
                <div className="diff-note editing">
                  <textarea
                    autoFocus
                    rows={2}
                    value={draft}
                    placeholder="O que o agente deve mudar aqui? (⌘⏎ salva, Esc cancela)"
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault();
                        save(line);
                      } else if (e.key === "Escape") setEditing(null);
                    }}
                  />
                  <div className="form-buttons">
                    <button type="button" className="btn primary" onClick={() => save(line)} disabled={!draft.trim()}>
                      Salvar nota
                    </button>
                    <button type="button" className="btn" onClick={() => setEditing(null)}>
                      Cancelar
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

function FileView({ doc, client, visible, onError }: DocProps) {
  const kind = viewerFor(doc.path);
  const [file, setFile] = useState<TextFile | null>(null);
  const [rendered, setRendered] = useState(kind === "markdown" || kind === "csv");
  const raw = client.rawUrl(doc.root, doc.path);
  const needsText = kind === "text" || kind === "markdown" || kind === "csv" || kind === "html";

  useEffect(() => {
    if (!visible || !needsText) return;
    let alive = true;
    client.readText(doc.root, doc.path).then(
      (value) => alive && setFile(value),
      (cause) => alive && onError(cause instanceof Error ? cause.message : String(cause)),
    );
    return () => {
      alive = false;
    };
  }, [client, doc.root, doc.path, visible, needsText, onError]);

  const html = useMemo(() => {
    if (kind !== "markdown" || !file) return "";
    return DOMPurify.sanitize(marked.parse(file.text, { async: false }) as string);
  }, [file, kind]);

  const table = useMemo(() => {
    if (kind !== "csv" || !file) return [];
    const sep = doc.path.toLowerCase().endsWith(".tsv") ? "\t" : file.text.split("\n")[0].includes(";") ? ";" : ",";
    return file.text
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(0, 2000)
      .map((row) => row.split(sep));
  }, [file, kind, doc.path]);

  return (
    <>
      <div className="doc-head">
        <Icon d={ICON.file} size={14} />
        <span className="doc-path mono">{doc.path}</span>
        {file?.truncated && <span className="small">mostrando os primeiros 2 MB</span>}
        <span className="grow" />
        {(kind === "markdown" || kind === "csv" || kind === "html") && (
          <div className="segmented" role="radiogroup" aria-label="Como mostrar">
            <button type="button" role="radio" aria-checked={rendered} onClick={() => setRendered(true)}>
              Visualizar
            </button>
            <button type="button" role="radio" aria-checked={!rendered} onClick={() => setRendered(false)}>
              Código
            </button>
          </div>
        )}
        <button
          type="button"
          className="icon-btn"
          title="Mostrar no Finder"
          onClick={() => client.open({ reveal: `${doc.root}/${doc.path}` }).catch((e) => onError(e.message))}
        >
          <Icon d={ICON.folder} size={14} />
        </button>
      </div>
      <div className="file-body">
        {kind === "image" && (
          <div className="media">
            <img src={raw} alt={doc.path} />
          </div>
        )}
        {kind === "pdf" && <iframe className="frame" src={raw} title={doc.path} />}
        {kind === "audio" && (
          <div className="media">
            <audio src={raw} controls />
          </div>
        )}
        {kind === "video" && (
          <div className="media">
            <video src={raw} controls />
          </div>
        )}
        {kind === "html" && rendered && file && (
          // Sem scripts: o HTML do repositório só é desenhado.
          <iframe className="frame" sandbox="" srcDoc={file.text} title={doc.path} />
        )}
        {kind === "markdown" && rendered && file && <article className="markdown" dangerouslySetInnerHTML={{ __html: html }} />}
        {kind === "csv" && rendered && file && (
          <div className="csv">
            <table>
              <tbody>
                {table.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (r === 0 ? <th key={c}>{cell}</th> : <td key={c}>{cell}</td>))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {needsText && (!rendered || kind === "text") && file && (
          file.binary ? (
            <p className="small doc-empty">Arquivo binário ({Math.round(file.size / 1024)} KB).</p>
          ) : (
            <pre className="code-view mono">
              {file.text.split("\n").map((line, i) => (
                <div key={i} className="code-line">
                  <span className="ln">{i + 1}</span>
                  <span className="code">{line || " "}</span>
                </div>
              ))}
            </pre>
          )
        )}
        {needsText && !file && <p className="small doc-empty">carregando…</p>}
      </div>
    </>
  );
}
