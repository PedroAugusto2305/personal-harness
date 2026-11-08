import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, fold } from "../lib/format";
import { openExternal } from "../lib/browser";
import { buildTree, type TreeNode } from "../lib/tree";
import { TYPE_ICON, renderInline } from "../lib/obsidian";
import type { BrainPlace, ContextWindow, GitFile, GitStatus, ReviewNote, Session, Suggestion } from "../types";
import { worktreeLabel, type Place } from "../useWorktrees";
import { SuggestionCard } from "./SuggestionCard";

export type InspectorTab = "changes" | "files" | "ports" | "brain" | "context";

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
  onOpenUrl: (url: string) => void;
  onAskCommit: (staged: number) => void;
  onSendNotes: () => void;
  onClearNotes: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
  onClose: () => void;
  brainTick: number;
  onOpenNote: (title: string) => void;
  onOpenTasks: (project: string) => void;
  /** v0.8: sugestões de precedente e a janela de contexto da sessão em foco. */
  suggestionsTick: number;
  contextSession: Session | null;
  onNotice: (message: string) => void;
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

  // Cinco abas não cabem em 330 px: a barra rola de lado e a aba escolhida aparece sempre.
  const tabs = useRef<HTMLDivElement>(null);
  useEffect(() => {
    tabs.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab]);

  return (
    <aside className="inspector" aria-label="Painel da worktree">
      <div className="inspector-tabs" role="tablist" ref={tabs}>
        {(
          [
            ["changes", "Mudanças", status?.files.length],
            ["files", "Arquivos", undefined],
            ["ports", "Portas", props.sessions.reduce((n, s) => n + s.ports.length, 0) || undefined],
            ["brain", "Brain", undefined],
            ["context", "Contexto", undefined],
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
      {tab === "context" ? (
        <ContextPanel client={client} session={props.contextSession} />
      ) : !place ? (
        <p className="inspector-empty small">
          Escolha uma worktree na barra lateral, ou foque um terminal dentro de um projeto, para ver as mudanças, os arquivos e
          as portas dela.
        </p>
      ) : tab === "changes" ? (
        <Changes {...props} place={place} status={status} reload={load} />
      ) : tab === "files" ? (
        <Files client={client} root={place.worktree.path} status={status} onOpenFile={props.onOpenFile} />
      ) : tab === "brain" ? (
        <BrainPanel
          client={client}
          cwd={place.worktree.path}
          tick={props.brainTick + props.suggestionsTick}
          onOpenNote={props.onOpenNote}
          onOpenTasks={props.onOpenTasks}
          onNotice={props.onNotice}
          onError={props.onError}
        />
      ) : (
        <Ports sessions={props.sessions} onOpenUrl={props.onOpenUrl} />
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

function Ports({ sessions, onOpenUrl }: { sessions: Session[]; onOpenUrl: (url: string) => void }) {
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
              <button type="button" className="pill" title="Abrir no navegador da MÊTIS" onClick={() => onOpenUrl(`http://localhost:${port}`)}>
                Abrir
              </button>
              <button
                type="button"
                className="icon-btn"
                title="Abrir no navegador do Mac"
                aria-label={`Abrir localhost:${port} no navegador do Mac`}
                onClick={() => void openExternal(`http://localhost:${port}`)}
              >
                <Icon d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" size={13} strokeWidth={1.9} />
              </button>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

const STATE_DOT: Record<string, string> = { pendente: "var(--fnt)", "em-andamento": "var(--run)", "em-teste": "var(--wait)" };
const STATE_NAME: Record<string, string> = { pendente: "pendente", "em-andamento": "em andamento", "em-teste": "em teste" };

/** O projeto do Brain desta worktree: tarefas abertas e precedentes de outros projetos. */
function BrainPanel(props: {
  client: CoreClient | null;
  cwd: string;
  tick: number;
  onOpenNote: (title: string) => void;
  onOpenTasks: (project: string) => void;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
}) {
  const { client, cwd } = props;
  const [place, setPlace] = useState<BrainPlace | null>(null);
  const [pending, setPending] = useState<Suggestion[]>([]);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    void client
      .brainPlace(cwd)
      .then(async (found) => {
        if (!alive) return;
        setPlace(found);
        const name = found.project?.name;
        setPending(name ? await client.suggestions({ project: name }).catch(() => []) : []);
      })
      .catch(() => alive && setPlace({ project: null }));
    return () => {
      alive = false;
    };
  }, [client, cwd, props.tick]);

  // [[links]] no texto das tarefas abrem a nota.
  const onLink = (event: React.MouseEvent) => {
    const link = (event.target as HTMLElement).closest("a");
    if (!link) return;
    event.preventDefault();
    if (link.classList.contains("wikilink") && link.dataset.note) props.onOpenNote(link.dataset.note);
  };

  if (!place) return <p className="inspector-empty small">Lendo o Brain…</p>;
  const project = place.project;
  if (!project) {
    return (
      <p className="inspector-empty small">
        Esta pasta não é de nenhum projeto do Brain. Para ligar, ponha <code>diretorio: "{cwd.replace(/^\/Users\/[^/]+/, "~")}"</code> no
        frontmatter da nota do projeto (ou rode <code>brain.py vincular</code>).
      </p>
    );
  }
  const open = (place.tasks ?? []).filter((t) => t.state !== "concluida");
  const order = ["em-andamento", "em-teste", "pendente"];
  open.sort((a, b) => order.indexOf(a.state) - order.indexOf(b.state));
  return (
    <div className="inspector-body brain-panel" onClick={onLink}>
      <div className="brain-panel-head">
        <button type="button" className="link-btn brain-panel-title" onClick={() => props.onOpenNote(project.name)}>
          🎯 {project.name}
        </button>
        {project.stage && <span className="chip">{project.stage}</span>}
      </div>
      {pending.length > 0 && (
        <>
          <div className="section-title brain-panel-section">Sugestões de outros projetos ({pending.length})</div>
          {pending.map((item) => (
            <SuggestionCard key={item.id} client={client} item={item} onOpenNote={props.onOpenNote} onDone={props.onNotice} onError={props.onError} />
          ))}
        </>
      )}
      <div className="section-title brain-panel-section">
        Tarefas abertas ({open.length})
        <button type="button" className="link-btn" onClick={() => props.onOpenTasks(project.name)}>
          kanban ›
        </button>
      </div>
      {open.slice(0, 10).map((task) => (
        <div key={task.id} className="brain-panel-task small">
          <span className="kb-dot" style={{ background: STATE_DOT[task.state] }} title={STATE_NAME[task.state]} />
          <span dangerouslySetInnerHTML={{ __html: renderInline(task.text) }} />
        </div>
      ))}
      {!open.length && <p className="small brain-panel-none">Nenhuma tarefa aberta nas Próximas ações.</p>}
      <div className="section-title brain-panel-section">Precedentes de outros projetos</div>
      {(place.precedents ?? []).map((hit) => (
        <button key={hit.path} type="button" className="brain-panel-prec" onClick={() => props.onOpenNote(hit.title)} title={hit.resumo}>
          <span>
            {TYPE_ICON[hit.tipo] ?? "·"} {hit.title}
          </span>
          <span className="small mono">
            {hit.projeto}
            {hit.status ? ` · ${hit.status}` : ""}
            {hit.via?.length ? ` · por ${hit.via.join(" e ")}` : ""}
          </span>
        </button>
      ))}
      {!place.precedents?.length && <p className="small brain-panel-none">Nada de outro projeto bateu com o momento do projeto.</p>}
      <p className="small brain-panel-note">
        Por significado e por palavra: confira antes de seguir. Os agentes recebem esta lista ao abrir e consultam o resto pelo MCP
        (brain_conflitos antes de decidir).
      </p>
    </div>
  );
}

const CATEGORY_COLOR: Record<string, string> = {
  sistema: "var(--fnt)",
  conversa: "var(--acc)",
  respostas: "var(--acct)",
  raciocinio: "var(--wait)",
  leituras: "var(--run)",
  comandos: "var(--warn)",
  edicoes: "var(--err)",
  mcp: "var(--acc)",
  outras: "var(--mut)",
  injetado: "var(--wait)",
  resumo: "var(--mut)",
};

const kTokens = (n: number) =>
  n >= 1_000_000
    ? `${(n / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}M`
    : n >= 1000
      ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1).replace(".", ",")}k`
      : String(n);

/** Janela de contexto da sessão do Claude em foco: o que está ocupando o contexto agora. */
function ContextPanel({ client, session }: { client: CoreClient | null; session: Session | null }) {
  const [data, setData] = useState<ContextWindow | null>(null);
  const id = session?.id ?? null;
  const used = session?.statusline?.context?.used_tokens ?? null;

  useEffect(() => {
    if (!client || !id || session?.kind !== "claude") return setData(null);
    let alive = true;
    void client
      .contextWindow(id)
      .then((found) => alive && setData(found))
      .catch(() => alive && setData({ available: false, reason: "o núcleo não respondeu" }));
    return () => {
      alive = false;
    };
    // used muda a cada resposta do Claude: é a hora de reler o transcript.
  }, [client, id, used, session?.kind]);

  if (!session) return <p className="inspector-empty small">Foque um terminal do Claude para ver o que ocupa a janela de contexto dele.</p>;
  if (session.kind !== "claude") return <p className="inspector-empty small">A janela de contexto por enquanto é só das sessões do Claude.</p>;
  if (!data) return <p className="inspector-empty small">Lendo o transcript…</p>;
  if (!data.available) return <p className="inspector-empty small">Sem dados ainda: {data.reason}.</p>;
  const size = data.size ?? 200000;
  return (
    <div className="inspector-body context-panel">
      <div className="context-head">
        <span className="context-total">{kTokens(data.used ?? 0)}</span>
        <span className="small mono">
          / {kTokens(size)} · {data.pct?.toLocaleString("pt-BR")}% · livre {kTokens(data.free ?? 0)}
        </span>
      </div>
      <div className="context-bar" role="img" aria-label="Divisão da janela de contexto">
        {data.categories?.map((c) => (
          <span key={c.key} style={{ width: `${(100 * c.tokens) / size}%`, background: CATEGORY_COLOR[c.key] ?? "var(--mut)" }} title={`${c.label}: ${kTokens(c.tokens)}`} />
        ))}
      </div>
      <ul className="context-cats">
        {data.categories?.map((c) => (
          <li key={c.key}>
            <span className="context-swatch" style={{ background: CATEGORY_COLOR[c.key] ?? "var(--mut)" }} />
            <span className="context-label">{c.label}</span>
            <span className="mono small">{kTokens(c.tokens)}</span>
          </li>
        ))}
      </ul>
      <div className="section-title brain-panel-section">O que mais pesa</div>
      <ul className="context-top">
        {data.top?.map((item) => (
          <li key={item.label} title={item.label}>
            <span className="context-label">{item.label}</span>
            <span className="mono small">
              {item.times > 1 ? `${item.times}× · ` : ""}
              {kTokens(item.tokens)}
            </span>
          </li>
        ))}
      </ul>
      <p className="small brain-panel-note">
        O total é o da última resposta do Claude. A divisão é estimada pelo tamanho do texto desde a
        {data.compacted ? " última compactação" : "s primeiras mensagens"}; o fixo inclui o prompt do Claude Code, as definições de ferramentas e o
        CLAUDE.md.
      </p>
    </div>
  );
}
