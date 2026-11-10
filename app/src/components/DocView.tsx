import { useEffect, useMemo, useState, type CSSProperties } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { parseDiff, type DiffLine } from "../lib/diff";
import { buildPatch, splitPatch } from "../lib/patch";
import { baseName, viewerFor } from "../lib/tree";
import type { ConflictBlock, ConflictChoice, DiffMode, ReviewNote, TextFile, ThemeName } from "../types";
import { CodeEditor } from "./CodeEditor";
import { NoteEditor } from "./NoteEditor";

/** Aba que não é terminal: o diff de um arquivo ou um arquivo aberto. */
export interface DocTab {
  key: string;
  type: "diff" | "file" | "web" | "conflict" | "note";
  root: string;
  /** Caminho do arquivo; numa aba de navegador, o endereço inicial. */
  path: string;
  untracked?: boolean;
  /** v0.9.6: modo do diff ao abrir e a ref, quando é comparar com um branch, tag ou commit. */
  mode?: DiffMode;
  ref?: string;
  /** Sobe quando a aba é pedida de novo com outro modo (o diff troca para ele). */
  seq?: number;
  /** Só nas abas de navegador: o rótulo da página nativa. */
  label?: string;
  incognito?: boolean;
  /** v0.9.8: perfil do navegador (id; ausente = Padrão). */
  profile?: string;
}

export function docTitle(doc: DocTab, webTitle?: string | null): string {
  if (doc.type === "web") {
    if (webTitle) return webTitle;
    const host = doc.path.replace(/^https?:\/\//, "").split("/")[0];
    return host && doc.path !== "about:blank" ? host : "Nova aba";
  }
  if (doc.type === "conflict") return `Conflito · ${baseName(doc.path)}`;
  if (doc.type === "note") return baseName(doc.path).replace(/\.md$/, "");
  return doc.type === "diff" ? `Δ ${baseName(doc.path)}${doc.mode === "ref" && doc.ref ? ` · ${doc.ref}` : ""}` : baseName(doc.path);
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
  /** v0.9.6: o diff marcou, desmarcou ou descartou algo (o painel de mudanças recarrega). */
  onGitChanged?: () => void;
  /** Manda um pedido ao agente da worktree (conflito: "resolva este arquivo"). */
  onAgent?: (prompt: string) => void;
  /** v0.9.7: o tema, para o editor de código seguir as cores da MÊTIS. */
  theme: ThemeName;
  /** v0.9.7: [[link]] clicado numa aba de nota abre a nota no Brain. */
  onOpenNote?: (title: string) => void;
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
      {props.doc.type === "diff" ? (
        <DiffView {...props} />
      ) : props.doc.type === "conflict" ? (
        <ConflictView {...props} />
      ) : props.doc.type === "note" ? (
        <>
          <div className="doc-head">
            <Icon d={ICON.note} size={14} />
            <span className="doc-path mono">{props.doc.path}</span>
          </div>
          <NoteEditor
            client={props.client}
            path={props.doc.path}
            docKey={props.doc.key}
            visible={props.visible}
            onOpenNote={(title) => props.onOpenNote?.(title)}
            onError={props.onError}
          />
        </>
      ) : (
        <FileView {...props} />
      )}
    </section>
  );
}

/** Uma ação no diff que pede confirmação no segundo clique (descartar não volta). */
function useArmed(timeoutMs = 4000) {
  const [armed, setArmed] = useState<string | null>(null);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(null), timeoutMs);
    return () => window.clearTimeout(timer);
  }, [armed, timeoutMs]);
  return { armed, arm: setArmed };
}

const MODE_LABEL: Record<DiffMode, string> = { head: "Tudo", staged: "Marcado", worktree: "Não marcado", ref: "Comparar" };

/**
 * Diff de um arquivo (v0.9.6): marcar, desmarcar e descartar por trecho ou por linha
 * (clique no número da linha; ⇧ + clique escolhe um intervalo), comparar com qualquer ref
 * (desde que o branch saiu dela) e, para imagem, as duas versões lado a lado.
 */
function DiffView({ doc, client, visible, notes, onAddNote, onRemoveNote, onOpenFile, onError, onGitChanged }: DocProps) {
  const [mode, setMode] = useState<DiffMode>(doc.mode ?? "head");
  const [ref, setRef] = useState(doc.ref ?? "");
  const [refDraft, setRefDraft] = useState(doc.ref ?? "");
  const [refs, setRefs] = useState<string[]>([]);
  const [raw, setRaw] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [anchor, setAnchor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const { armed, arm } = useArmed();
  const image = viewerFor(doc.path) === "image";
  const staging = (mode === "worktree" || mode === "staged") && !doc.untracked;

  // Pedida de novo (outra linha do painel, outra ref): segue o modo pedido.
  useEffect(() => {
    if (doc.mode) setMode(doc.mode);
    if (doc.ref) {
      setRef(doc.ref);
      setRefDraft(doc.ref);
    }
  }, [doc.mode, doc.ref, doc.seq]);

  useEffect(() => {
    if (!visible || (mode === "ref" && !ref)) return;
    let alive = true;
    const load = () =>
      client.gitDiff(doc.root, doc.path, mode, !!doc.untracked, ref).then(
        (text) => alive && setRaw(text),
        (cause) => alive && setRaw(`erro: ${cause instanceof Error ? cause.message : String(cause)}`),
      );
    void load();
    const timer = window.setInterval(load, 4000); // o agente pode estar mexendo no arquivo
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client, doc.root, doc.path, doc.untracked, mode, ref, visible, reload]);

  // A escolha de linhas vale para um diff só: trocar de modo ou o diff mudar a desfaz.
  useEffect(() => {
    setPicked(new Set());
    setAnchor(null);
  }, [mode, ref, raw]);

  useEffect(() => {
    if (mode !== "ref" || refs.length) return;
    void client
      .gitRefs(doc.root)
      .then((r) => {
        setRefs([...r.branches, ...r.remotos, ...r.tags]);
        if (!ref) {
          setRefDraft(r.padrao);
          setRef(r.padrao);
        }
      })
      .catch(() => undefined);
  }, [client, doc.root, mode, ref, refs.length]);

  const parsed = useMemo(() => parseDiff(raw ?? ""), [raw]);
  const patch = useMemo(() => splitPatch(raw ?? ""), [raw]);
  const fileNotes = notes.filter((n) => n.file === doc.path);
  const noteAt = (line: DiffLine) =>
    fileNotes.filter((n) => (n.side === "new" ? n.line === line.new : n.line === line.old && line.new == null));
  const keyOf = (line: DiffLine) => `${line.hunk}:${line.pos}`;
  const changeable = (line: DiffLine) => line.kind === "add" || line.kind === "del";

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

  /** Clique no número: escolhe a linha; com ⇧, todas as mudanças entre a última escolhida e esta. */
  const toggle = (index: number, shift: boolean) => {
    const line = parsed.lines[index];
    if (!staging || !changeable(line)) return;
    setPicked((current) => {
      const next = new Set(current);
      if (shift && anchor !== null) {
        const [from, to] = anchor < index ? [anchor, index] : [index, anchor];
        for (let i = from; i <= to; i += 1) if (changeable(parsed.lines[i])) next.add(keyOf(parsed.lines[i]));
      } else if (next.has(keyOf(line))) next.delete(keyOf(line));
      else next.add(keyOf(line));
      return next;
    });
    setAnchor(index);
  };

  /** Aplica a escolha: marcar (no índice), desmarcar (índice, ao contrário) ou descartar (árvore, ao contrário). */
  const apply = async (action: "marcar" | "desmarcar" | "descartar", pick: (hunk: number, line: number) => boolean) => {
    const text = buildPatch(patch, pick, action !== "marcar");
    if (!text) return;
    setBusy(true);
    try {
      await client.gitApply(doc.root, text, action !== "descartar", action !== "marcar");
      setPicked(new Set());
      setReload((n) => n + 1);
      onGitChanged?.();
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
      arm(null);
    }
  };

  const hunkActions = (hunk: number) => {
    const all = (h: number) => h === hunk;
    if (mode === "staged") {
      return (
        <button type="button" className="link-btn" disabled={busy} onClick={() => void apply("desmarcar", all)}>
          desmarcar trecho
        </button>
      );
    }
    const key = `hunk-${hunk}`;
    return (
      <>
        <button type="button" className="link-btn" disabled={busy} onClick={() => void apply("marcar", all)}>
          marcar trecho
        </button>
        <button
          type="button"
          className="link-btn danger"
          disabled={busy}
          title="Volta este trecho ao que está marcado (ou ao último commit). Não dá para desfazer."
          onClick={() => (armed === key ? void apply("descartar", all) : arm(key))}
        >
          {armed === key ? "confirmar descarte" : "descartar trecho"}
        </button>
      </>
    );
  };

  const pickedFn = (h: number, i: number) => picked.has(`${h}:${i}`);

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
            {(["head", "staged", "worktree", "ref"] as const).map((key) => (
              <button key={key} type="button" role="radio" aria-checked={mode === key} onClick={() => setMode(key)}>
                {MODE_LABEL[key]}
              </button>
            ))}
          </div>
        )}
        {mode === "ref" && (
          <form
            className="ref-form"
            onSubmit={(event) => {
              event.preventDefault();
              setRef(refDraft.trim());
            }}
          >
            <input
              className="mono"
              list={`refs-${doc.key}`}
              value={refDraft}
              placeholder="main, origin/main, v0.9.5, HEAD~3"
              spellCheck={false}
              onChange={(event) => setRefDraft(event.target.value)}
              onBlur={() => setRef(refDraft.trim())}
              aria-label="Comparar com"
            />
            <datalist id={`refs-${doc.key}`}>
              {refs.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
          </form>
        )}
        <button type="button" className="pill" onClick={() => onOpenFile(doc.path)}>
          Abrir arquivo
        </button>
      </div>
      {staging && picked.size > 0 && (
        <div className="diff-pickbar">
          <span>
            {picked.size} linha{picked.size > 1 ? "s" : ""} escolhida{picked.size > 1 ? "s" : ""}
          </span>
          {mode === "worktree" ? (
            <>
              <button type="button" className="pill" disabled={busy} onClick={() => void apply("marcar", pickedFn)}>
                Marcar linhas
              </button>
              <button
                type="button"
                className="pill ghost danger"
                disabled={busy}
                onClick={() => (armed === "linhas" ? void apply("descartar", pickedFn) : arm("linhas"))}
              >
                {armed === "linhas" ? "Confirmar descarte" : "Descartar linhas"}
              </button>
            </>
          ) : (
            <button type="button" className="pill" disabled={busy} onClick={() => void apply("desmarcar", pickedFn)}>
              Desmarcar linhas
            </button>
          )}
          <button type="button" className="link-btn" onClick={() => setPicked(new Set())}>
            limpar
          </button>
        </div>
      )}
      {mode === "head" && !doc.untracked && parsed.lines.length > 0 && (
        <p className="small diff-tip">Para marcar ou descartar por trecho ou por linha, escolha Não marcado (ou Marcado, para desmarcar).</p>
      )}
      {staging && picked.size === 0 && parsed.lines.length > 0 && (
        <p className="small diff-tip">Clique no número de uma linha para escolhê-la (⇧ + clique escolhe um intervalo).</p>
      )}
      {image && !doc.untracked && (
        <div className="diff-images">
          <figure>
            <figcaption className="small">{mode === "ref" ? ref || "ref" : "último commit"}</figcaption>
            <img src={client.gitBlobUrl(doc.root, doc.path, mode === "ref" && ref ? ref : "HEAD")} alt="antes" />
          </figure>
          <figure>
            <figcaption className="small">agora</figcaption>
            <img src={`${client.rawUrl(doc.root, doc.path)}&v=${reload}`} alt="agora" />
          </figure>
        </div>
      )}
      <div className="diff-body mono">
        {mode === "ref" && !ref && <p className="small doc-empty">Escolha com o que comparar: um branch, uma tag ou um commit.</p>}
        {raw == null && !(mode === "ref" && !ref) && <p className="small doc-empty">carregando…</p>}
        {raw?.startsWith("erro:") && <div className="error-box">{raw.slice(5)}</div>}
        {raw != null && !raw.startsWith("erro:") && parsed.binary && !image && <p className="small doc-empty">Arquivo binário: abra para ver.</p>}
        {raw != null && !raw.startsWith("erro:") && !parsed.binary && parsed.lines.length === 0 && (
          <p className="small doc-empty">Sem diferenças neste modo.</p>
        )}
        {!parsed.binary &&
          parsed.lines.map((line, index) => {
            if (line.kind === "hunk") {
              return (
                <div key={index} className="diff-hunk">
                  <span className="diff-hunk-text">{line.text || "···"}</span>
                  {staging && line.hunk !== undefined && <span className="diff-hunk-actions">{hunkActions(line.hunk)}</span>}
                </div>
              );
            }
            const lineNotes = noteAt(line);
            const isPicked = changeable(line) && picked.has(keyOf(line));
            return (
              <div key={index}>
                <div className={`diff-line ${line.kind}`} data-picked={isPicked ? "true" : undefined}>
                  <span
                    className="ln"
                    data-pickable={staging && changeable(line) ? "true" : undefined}
                    onClick={(event) => toggle(index, event.shiftKey)}
                  >
                    {line.old ?? ""}
                  </span>
                  <span
                    className="ln"
                    data-pickable={staging && changeable(line) ? "true" : undefined}
                    onClick={(event) => toggle(index, event.shiftKey)}
                  >
                    {line.new ?? ""}
                  </span>
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

const CHOICE_LABEL: Record<ConflictChoice, string> = { nosso: "o nosso", deles: "o deles", ambos: "os dois", base: "a base" };

/**
 * Conflito bloco a bloco (v0.9.6): cada trecho em conflito mostra o lado deste branch e o
 * que está entrando; escolha um, os dois (o nosso primeiro) ou a base, e aplique. Sem
 * marcador sobrando, o arquivo é marcado como resolvido.
 */
function ConflictView({ doc, client, visible, onOpenFile, onError, onGitChanged, onAgent }: DocProps) {
  const [blocks, setBlocks] = useState<ConflictBlock[] | null>(null);
  const [choices, setChoices] = useState<Record<number, ConflictChoice>>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!visible) return;
    let alive = true;
    client.gitConflict(doc.root, doc.path).then(
      (answer) => {
        if (!alive) return;
        setBlocks(answer.blocos);
        setChoices({});
      },
      (cause) => alive && onError(cause instanceof Error ? cause.message : String(cause)),
    );
    return () => {
      alive = false;
    };
  }, [client, doc.root, doc.path, visible, reload, onError]);

  const apply = async () => {
    if (!blocks) return;
    setBusy(true);
    try {
      const answer = await client.resolveConflict(
        doc.root,
        doc.path,
        blocks.map((b) => choices[b.indice] ?? "nosso"),
      );
      setDone(answer.resolvido);
      onGitChanged?.();
      setReload((n) => n + 1);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const chosen = blocks ? blocks.filter((b) => choices[b.indice]).length : 0;
  return (
    <>
      <div className="doc-head">
        <Icon d={ICON.file} size={14} />
        <span className="doc-path mono">{doc.path}</span>
        <span className="small">{blocks ? `${blocks.length} conflito${blocks.length === 1 ? "" : "s"}` : ""}</span>
        <span className="grow" />
        {onAgent && blocks && blocks.length > 0 && (
          <button
            type="button"
            className="pill ghost"
            onClick={() =>
              onAgent(
                `Resolva os conflitos de ${doc.path} nesta worktree mantendo a intenção dos dois lados, rode os testes que houver e marque o arquivo (git add). Se a escolha não for óbvia, me pergunte.`,
              )
            }
          >
            ✻ Resolver com o agente
          </button>
        )}
        <button type="button" className="pill" onClick={() => onOpenFile(doc.path)}>
          Abrir arquivo
        </button>
      </div>
      <div className="conflict-body">
        {blocks == null && <p className="small doc-empty">carregando…</p>}
        {blocks?.length === 0 && (
          <p className="small doc-empty">{done ? "Resolvido e marcado para o commit." : "Nenhum marcador de conflito neste arquivo."}</p>
        )}
        {blocks?.map((block) => {
          const choice = choices[block.indice];
          const options: ConflictChoice[] = block.base != null ? ["nosso", "deles", "ambos", "base"] : ["nosso", "deles", "ambos"];
          return (
            <section key={block.indice} className="conflict-block" data-choice={choice}>
              <header className="conflict-head small">
                <span>Conflito {block.indice + 1}</span>
                <span className="grow" />
                {options.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className="pill ghost tiny"
                    aria-pressed={choice === option}
                    onClick={() => setChoices((all) => ({ ...all, [block.indice]: option }))}
                  >
                    {CHOICE_LABEL[option]}
                  </button>
                ))}
              </header>
              <div className="conflict-sides">
                <div className="conflict-side" data-side="nosso" data-on={choice === "nosso" || choice === "ambos" ? "true" : undefined}>
                  <div className="conflict-label small mono">nosso · {block.rotulo_nosso || "este branch"}</div>
                  <pre className="mono">{block.nosso || " "}</pre>
                </div>
                <div className="conflict-side" data-side="deles" data-on={choice === "deles" || choice === "ambos" ? "true" : undefined}>
                  <div className="conflict-label small mono">deles · {block.rotulo_deles || "o que entra"}</div>
                  <pre className="mono">{block.deles || " "}</pre>
                </div>
              </div>
              {block.base != null && choice === "base" && (
                <div className="conflict-side" data-on="true">
                  <div className="conflict-label small mono">base (antes dos dois)</div>
                  <pre className="mono">{block.base || " "}</pre>
                </div>
              )}
            </section>
          );
        })}
      </div>
      {blocks && blocks.length > 0 && (
        <div className="conflict-foot">
          <span className="small">
            {chosen} de {blocks.length} escolhido{blocks.length === 1 ? "" : "s"}
            {chosen < blocks.length ? " · os sem escolha ficam com o nosso" : ""}
          </span>
          <button type="button" className="btn primary" disabled={busy || chosen === 0} onClick={() => void apply()}>
            {busy ? "Aplicando…" : "Aplicar e marcar"}
          </button>
        </div>
      )}
    </>
  );
}

function FileView({ doc, client, visible, onError, theme }: DocProps) {
  const kind = viewerFor(doc.path);
  const [file, setFile] = useState<TextFile | null>(null);
  // v0.9.7: abre editando; a prévia (markdown, CSV, HTML) fica em Visualizar.
  const [rendered, setRendered] = useState(false);
  const raw = client.rawUrl(doc.root, doc.path);
  const needsText = kind === "text" || kind === "markdown" || kind === "csv" || kind === "html";

  // v1.0.0: relê também ao trocar entre Editar e Visualizar, para a prévia mostrar o que o
  // editor ao lado acabou de salvar (antes ficava o texto de quando a aba apareceu).
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
  }, [client, doc.root, doc.path, visible, needsText, onError, rendered]);

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
              Editar
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
        {needsText && (!rendered || kind === "text") && file?.binary && (
          <p className="small doc-empty">Arquivo binário ({Math.round(file.size / 1024)} KB).</p>
        )}
        {needsText && file && !file.binary && (
          // v0.9.7: o Monaco no lugar do texto só para ler (⌘S salva). Fica montado durante a
          // prévia, para a edição não salva não se perder ao trocar de modo.
          <div className="editor-wrap" hidden={rendered && kind !== "text"}>
            <CodeEditor client={client} docKey={doc.key} root={doc.root} path={doc.path} theme={theme} visible={visible && !(rendered && kind !== "text")} onError={onError} />
          </div>
        )}
        {needsText && !file && <p className="small doc-empty">carregando…</p>}
      </div>
    </>
  );
}
