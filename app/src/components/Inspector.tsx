import { useCallback, useEffect, useMemo, useState } from "react";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, fold } from "../lib/format";
import { buildTree, type TreeNode } from "../lib/tree";
import type { GitFile, GitStatus, ReviewNote, Session } from "../types";
import { worktreeLabel, type Place } from "../useWorktrees";

export type InspectorTab = "changes" | "files" | "ports";

interface Props {
  client: CoreClient | null;
  place: Place | null;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  sessions: Session[];
  notes: ReviewNote[];
  tick: number;
  onOpenDiff: (file: GitFile) => void;
  onOpenFile: (path: string) => void;
  onAskCommit: (staged: number) => void;
  onSendNotes: () => void;
  onClearNotes: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
  onClose: () => void;
}

/** Letra e cor do estado de um arquivo no git, no estilo do VS Code. */
export function fileMark(file: GitFile, side: "staged" | "unstaged"): { letter: string; color: string } {
  if (file.conflict) return { letter: "!", color: "var(--err)" };
  if (file.untracked) return { letter: "U", color: "var(--run)" };
  const code = side === "staged" ? file.x : file.y;
  const map: Record<string, [string, string]> = {
    M: ["M", "var(--wait)"],
    A: ["A", "var(--run)"],
    D: ["D", "var(--err)"],
    R: ["R", "var(--acct)"],
    C: ["C", "var(--acct)"],
    T: ["T", "var(--wait)"],
  };
  const [letter, color] = map[code] ?? [code, "var(--mut)"];
  return { letter, color };
}

export function Inspector(props: Props) {
  const { client, place, tab } = props;
  const path = place?.worktree.path ?? null;
  const [status, setStatus] = useState<GitStatus | null>(null);

  const load = useCallback(async () => {
    if (!client || !path) return setStatus(null);
    try {
      setStatus(await client.gitStatus(path));
    } catch {
      setStatus(null);
    }
  }, [client, path]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [load, props.tick]);

  return (
    <aside className="inspector" aria-label="Painel da worktree">
      <div className="inspector-tabs" role="tablist">
        {(
          [
            ["changes", "Mudanças", status?.files.length],
            ["files", "Arquivos", undefined],
            ["ports", "Portas", props.sessions.reduce((n, s) => n + s.ports.length, 0) || undefined],
          ] as [InspectorTab, string, number | undefined][]
        ).map(([key, label, count]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => props.onTab(key)}>
            {label}
            {count ? <span className="count">{count}</span> : null}
          </button>
        ))}
        <button type="button" className="icon-btn" title="Fechar painel (⌘⇧B)" aria-label="Fechar painel" onClick={props.onClose}>
          <Icon d={ICON.close} size={12} strokeWidth={2} />
        </button>
      </div>
      {!place ? (
        <p className="inspector-empty small">
          Escolha uma worktree na barra lateral, ou foque um terminal dentro de um projeto, para ver as mudanças, os arquivos e
          as portas dela.
        </p>
      ) : tab === "changes" ? (
        <Changes {...props} place={place} status={status} reload={load} />
      ) : tab === "files" ? (
        <Files client={client} root={place.worktree.path} status={status} onOpenFile={props.onOpenFile} />
      ) : (
        <Ports client={client} sessions={props.sessions} onError={props.onError} />
      )}
    </aside>
  );
}

function Changes(props: Props & { place: Place; status: GitStatus | null; reload: () => Promise<void> }) {
  const { client, place, status, notes } = props;
  const path = place.worktree.path;
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const staged = status?.files.filter((f) => f.staged) ?? [];
  const unstaged = status?.files.filter((f) => f.unstaged) ?? [];

  const act = async (label: string, action: () => Promise<unknown>) => {
    if (!client) return;
    setBusy(label);
    try {
      await action();
    } catch (cause) {
      props.onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
      await props.reload();
      props.onChanged();
    }
  };

  const row = (file: GitFile, side: "staged" | "unstaged") => {
    const mark = fileMark(file, side);
    const parts = file.path.split("/");
    const name = parts.pop();
    return (
      <div key={`${side}-${file.path}`} className="change-row">
        <button type="button" className="change-main" onClick={() => props.onOpenDiff(file)} title={`Ver o diff de ${file.path}`}>
          <span className="change-name">{name}</span>
          <span className="change-dir small">{parts.join("/")}</span>
        </button>
        <button
          type="button"
          className="icon-btn row-action"
          title={side === "staged" ? "Desmarcar" : "Marcar para o commit"}
          aria-label={side === "staged" ? `Desmarcar ${file.path}` : `Marcar ${file.path}`}
          onClick={() => act(side, () => (side === "staged" ? client!.unstage(path, [file.path]) : client!.stage(path, [file.path])))}
        >
          <Icon d={side === "staged" ? ICON.minus : ICON.plus} size={13} strokeWidth={2} />
        </button>
        <span className="change-mark mono" style={{ color: mark.color }}>
          {mark.letter}
        </span>
      </div>
    );
  };

  return (
    <div className="inspector-body">
      <div className="branch-bar">
        <Icon d={ICON.branch} size={13} />
        <span className="mono branch-name">{status?.branch ?? worktreeLabel(place.worktree)}</span>
        {status && status.ahead > 0 && <span className="badge">↑{status.ahead}</span>}
        {status && status.behind > 0 && <span className="badge">↓{status.behind}</span>}
        <span className="grow" />
        <button type="button" className="icon-btn" title="Puxar (pull --ff-only)" disabled={!!busy} onClick={() => act("pull", () => client!.pull(path))}>
          <Icon d={ICON.down} size={14} />
        </button>
        <button type="button" className="icon-btn" title="Subir (push)" disabled={!!busy} onClick={() => act("push", () => client!.push(path))}>
          <Icon d={ICON.up} size={14} />
        </button>
      </div>
      {busy === "push" || busy === "pull" ? <div className="small busy-line">{busy === "push" ? "subindo…" : "puxando…"}</div> : null}

      {notes.length > 0 && (
        <div className="notes-box">
          <Icon d={ICON.note} size={13} />
          <span>
            {notes.length} nota{notes.length > 1 ? "s" : ""} na revisão
          </span>
          <span className="grow" />
          <button type="button" className="pill" onClick={props.onSendNotes} title="Vai para a barra de entrada do agente desta worktree">
            Mandar ao agente
          </button>
          <button type="button" className="icon-btn" title="Limpar notas" onClick={props.onClearNotes}>
            <Icon d={ICON.trash} size={12} />
          </button>
        </div>
      )}

      <div className="commit-box">
        <textarea
          value={message}
          rows={2}
          placeholder={staged.length ? "Mensagem do commit (ou peça ao agente)" : "Marque arquivos ou peça ao agente"}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.metaKey && message.trim() && staged.length) {
              e.preventDefault();
              void act("commit", async () => {
                await client!.commit(path, message.trim());
                setMessage("");
              });
            }
          }}
        />
        <div className="form-buttons">
          <button
            type="button"
            className="btn primary"
            disabled={!message.trim() || !staged.length || !!busy}
            title="Commit dos arquivos marcados (⌘⏎)"
            onClick={() =>
              act("commit", async () => {
                await client!.commit(path, message.trim());
                setMessage("");
              })
            }
          >
            <Icon d={ICON.check} size={13} strokeWidth={2.2} />
            Commit
          </button>
          <button
            type="button"
            className="btn"
            disabled={!status?.files.length}
            onClick={() => props.onAskCommit(staged.length)}
            title="O agente desta worktree escreve a mensagem e faz o commit, no terminal dele"
          >
            ✻ Pedir ao agente
          </button>
        </div>
      </div>

      <div className="change-group">
        <div className="group-head">
          <span>Marcados · {staged.length}</span>
          {staged.length > 0 && (
            <button type="button" className="link-btn" onClick={() => act("unstage", () => client!.unstage(path, staged.map((f) => f.path)))}>
              desmarcar todos
            </button>
          )}
        </div>
        {staged.map((f) => row(f, "staged"))}
      </div>
      <div className="change-group">
        <div className="group-head">
          <span>Não marcados · {unstaged.length}</span>
          {unstaged.length > 0 && (
            <button type="button" className="link-btn" onClick={() => act("stage", () => client!.stage(path, unstaged.map((f) => f.path)))}>
              marcar todos
            </button>
          )}
        </div>
        {unstaged.map((f) => row(f, "unstaged"))}
        {status && status.files.length === 0 && <p className="small inspector-empty">Nada mudou desde o último commit.</p>}
      </div>
    </div>
  );
}

function Files({
  client,
  root,
  status,
  onOpenFile,
}: {
  client: CoreClient | null;
  root: string;
  status: GitStatus | null;
  onOpenFile: (path: string) => void;
}) {
  const [files, setFiles] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    setError(null);
    client.files(root).then(
      (answer) => alive && setFiles(answer.files),
      (cause) => alive && setError(cause instanceof Error ? cause.message : String(cause)),
    );
    setOpen(new Set());
    return () => {
      alive = false;
    };
  }, [client, root]);

  const colors = useMemo(() => {
    const map = new Map<string, string>();
    for (const file of status?.files ?? []) map.set(file.path, fileMark(file, file.staged && !file.unstaged ? "staged" : "unstaged").color);
    return map;
  }, [status]);
  const tree = useMemo(() => buildTree(files), [files]);
  const matches = useMemo(() => {
    const words = fold(query).split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    return files.filter((f) => words.every((w) => fold(f).includes(w))).slice(0, 300);
  }, [files, query]);

  const toggle = (dir: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(dir)) next.delete(dir);
      else next.add(dir);
      return next;
    });

  const node = (item: TreeNode, depth: number): React.ReactNode =>
    item.dir ? (
      <div key={item.path}>
        <button type="button" className="file-row" style={{ paddingLeft: 8 + depth * 12 }} onClick={() => toggle(item.path)}>
          <span className="chev" data-open={open.has(item.path) ? "true" : undefined}>
            <Icon d={ICON.chevron} size={11} strokeWidth={2.2} />
          </span>
          <span>{item.name}</span>
        </button>
        {open.has(item.path) && item.children.map((child) => node(child, depth + 1))}
      </div>
    ) : (
      <button
        key={item.path}
        type="button"
        className="file-row"
        style={{ paddingLeft: 22 + depth * 12, color: colors.get(item.path) }}
        onClick={() => onOpenFile(item.path)}
        title={item.path}
      >
        <span>{item.name}</span>
      </button>
    );

  return (
    <div className="inspector-body files">
      <input className="filter" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filtrar arquivos (⌘P abre direto)" spellCheck={false} />
      {error && <div className="error-box">{error}</div>}
      <div className="file-tree">
        {query.trim()
          ? matches.map((f) => (
              <button key={f} type="button" className="file-row" style={{ color: colors.get(f) }} onClick={() => onOpenFile(f)} title={f}>
                <span>{f}</span>
              </button>
            ))
          : tree.children.map((child) => node(child, 0))}
      </div>
      <p className="small file-count">{files.length} arquivos · sem os ignorados pelo git</p>
    </div>
  );
}

function Ports({ client, sessions, onError }: { client: CoreClient | null; sessions: Session[]; onError: (m: string) => void }) {
  const withPorts = sessions.filter((s) => s.ports.length > 0);
  return (
    <div className="inspector-body">
      {withPorts.length === 0 && (
        <p className="small inspector-empty">
          Nenhuma porta aberta pelos terminais desta worktree. Quando um agente subir um servidor (npm run dev, uvicorn), a porta
          aparece aqui.
        </p>
      )}
      {withPorts.map((session) => (
        <div key={session.id} className="port-group">
          <div className="group-head">
            <span>
              <span style={{ color: KIND_COLOR[session.kind] }}>{KIND_GLYPH[session.kind]}</span> {session.title}
            </span>
          </div>
          {session.ports.map((port) => (
            <div key={port} className="port-row">
              <Icon d={ICON.port} size={13} />
              <span className="mono">localhost:{port}</span>
              <span className="grow" />
              <button
                type="button"
                className="pill"
                onClick={() => client?.open({ url: `http://localhost:${port}` }).catch((e) => onError(e.message))}
              >
                Abrir
              </button>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
