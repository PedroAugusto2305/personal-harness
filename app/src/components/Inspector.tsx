import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { KindIcon } from "./KindIcon";
import { CodeGraphLine, type CodeGraphEvent } from "./CodeGraph";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { fold } from "../lib/format";
import { openExternal } from "../lib/browser";
import { buildTree, type TreeNode } from "../lib/tree";
import { TYPE_ICON, renderInline } from "../lib/obsidian";
import type { Approval, BrainPlace, ContextWindow, GitStatus, Prefs, ReviewNote, Session, Suggestion } from "../types";
import type { Place } from "../useWorktrees";
import { SuggestionCard } from "./SuggestionCard";
import { GitPanel, fileMark, type GitPanelProps } from "./GitPanel";

export { fileMark };

export type InspectorTab = "changes" | "files" | "ports" | "brain" | "context";

interface Props {
  client: CoreClient | null;
  place: Place | null;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  sessions: Session[];
  notes: ReviewNote[];
  tick: number;
  onOpenDiff: GitPanelProps["onOpenDiff"];
  /** v0.9.6: conflito bloco a bloco, pedido ao agente da worktree e as receitas dos Ajustes. */
  onOpenConflict: (path: string) => void;
  onAgent: (prompt: string) => void;
  prefs: Prefs | null;
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
  /** v0.9.8: terminal novo aberto por um botão do painel (revisão de PR por IA). */
  onSession?: (session: Session) => void;
  /** v0.9.9: aprovações pedidas pelos agentes, na aba do Brain (mockup). */
  approvals?: Approval[];
  onDecide?: (id: string, approve: boolean) => void;
  /** v0.9.8: o último aviso do `graphify update` (fim ou erro), para o grafo do código. */
  codeGraphEvent?: CodeGraphEvent | null;
}

const TAB_ICON: Record<InspectorTab, [string, string]> = {
  brain: ["M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1", "Brain: precedentes, aprovações e tarefas"],
  changes: [ICON.branch, "Mudanças (git)"],
  files: [ICON.file, "Arquivos"],
  ports: [ICON.port, "Portas"],
  context: [ICON.cpu, "Contexto da sessão"],
};
const TAB_NAME: Record<InspectorTab, string> = { brain: "Brain", changes: "Mudanças", files: "Arquivos", ports: "Portas", context: "Contexto" };

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
      <div className="inspector-tabs icons" role="tablist" ref={tabs}>
        {(
          [
            ["brain", undefined],
            ["changes", status?.files.length],
            ["files", undefined],
            ["ports", props.sessions.reduce((n, s) => n + s.ports.length, 0) || undefined],
            ["context", undefined],
          ] as [InspectorTab, number | undefined][]
        ).map(([key, count]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} aria-label={TAB_ICON[key][1]} title={TAB_ICON[key][1]} onClick={() => props.onTab(key)}>
            <Icon d={TAB_ICON[key][0]} size={15} strokeWidth={1.8} />
            {count ? <span className="count">{count > 99 ? "99+" : count}</span> : null}
          </button>
        ))}
        <span className="inspector-tab-name">{TAB_NAME[tab]}</span>
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
        <GitPanel
          client={client}
          place={place}
          status={status}
          reload={load}
          notes={props.notes}
          prefs={props.prefs}
          onOpenDiff={props.onOpenDiff}
          onOpenConflict={props.onOpenConflict}
          onOpenUrl={props.onOpenUrl}
          onAskCommit={props.onAskCommit}
          onAgent={props.onAgent}
          onSendNotes={props.onSendNotes}
          onClearNotes={props.onClearNotes}
          onChanged={props.onChanged}
          onError={props.onError}
          onNotice={props.onNotice}
          onSession={props.onSession}
        />
      ) : tab === "files" ? (
        <>
          {client && <CodeGraphLine client={client} root={place.worktree.path} onAgent={props.onAgent} event={props.codeGraphEvent ?? null} />}
          <Files client={client} root={place.worktree.path} status={status} onOpenFile={props.onOpenFile} />
        </>
      ) : tab === "brain" ? (
        <BrainPanel
          client={client}
          cwd={place.worktree.path}
          approvals={props.approvals ?? []}
          onDecide={props.onDecide}
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
              <KindIcon kind={session.kind} /> {session.title}
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
  approvals: Approval[];
  onDecide?: (id: string, approve: boolean) => void;
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
      <div className="ins-head">
        <b>Precedentes</b>
        <span className="small">de outros projetos</span>
      </div>
      {(place.precedents ?? []).slice(0, 6).map((hit) => (
        <button key={hit.path} type="button" className="ins-prec" onClick={() => props.onOpenNote(hit.title)} title={hit.via?.length ? `achado por ${hit.via.join(" e ")}` : undefined}>
          <span className="ins-prec-title">
            {TYPE_ICON[hit.tipo] ?? "·"} {hit.title}
          </span>
          <span className="ins-prec-path">
            {hit.projeto} / {hit.tipo === "decisao" ? "decisões" : hit.tipo === "aprendizado" ? "aprendizados" : hit.tipo === "incidente" ? "incidentes" : hit.tipo}
            {hit.status ? ` · ${hit.status}` : ""}
          </span>
          {(hit.snippet || hit.resumo) && <span className="ins-prec-snippet">{(hit.resumo || hit.snippet || "").replace(/[\x02\x03]/g, "").slice(0, 200)}</span>}
        </button>
      ))}
      {!place.precedents?.length && <p className="small brain-panel-none">Nada de outro projeto bateu com o momento do projeto.</p>}
      {props.approvals.map((approval) => (
        <div key={approval.id} className="ins-approval" role="alertdialog" aria-label="Aprovação pendente">
          <span className="ins-approval-title">
            <Icon d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z" size={14} strokeWidth={2} /> Aprovação
          </span>
          <span className="small">
            <b>{approval.who}</b> quer usar <span className="mono">{approval.tool}</span> em {approval.account}: {approval.summary}
          </span>
          <div className="ins-approval-actions">
            <button type="button" className="ok" onClick={() => props.onDecide?.(approval.id, true)}>
              Aprovar
            </button>
            <button type="button" className="no" onClick={() => props.onDecide?.(approval.id, false)}>
              Recusar
            </button>
          </div>
        </div>
      ))}
      {(place.precedents ?? []).length > 0 && (
        <>
          <div className="ins-head">
            <b>Grafo local</b>
          </div>
          <LocalGraph center={project.name} others={[...new Set((place.precedents ?? []).map((h) => h.projeto).filter((p) => p && p !== project.name))].slice(0, 6)} />
        </>
      )}
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
      <p className="small brain-panel-note">
        Por significado e por palavra: confira antes de seguir. Os agentes recebem esta lista ao abrir e consultam o resto pelo MCP
        (brain_conflitos antes de decidir).
      </p>
    </div>
  );
}

/** Grafo local (mockup): o projeto no meio e os projetos de onde vêm os precedentes em volta. */
function LocalGraph({ center, others }: { center: string; others: string[] }) {
  const w = 280;
  const h = 130;
  const cx = w / 2;
  const cy = h / 2;
  const points = others.map((name, i) => {
    const angle = (i / Math.max(1, others.length)) * Math.PI * 2 - Math.PI / 2;
    return { name, x: cx + Math.cos(angle) * 100, y: cy + Math.sin(angle) * 44 };
  });
  return (
    <svg className="ins-graph" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Grafo local: ${center} ligado a ${others.join(", ") || "nenhum outro projeto"}`}>
      {points.map((p) => (
        <line key={`l-${p.name}`} x1={cx} y1={cy} x2={p.x} y2={p.y} style={{ stroke: "var(--line2)" }} strokeWidth={1} />
      ))}
      {points.map((p) => (
        <g key={p.name}>
          <circle cx={p.x} cy={p.y} r={4} style={{ fill: "var(--g-semarea)" }} />
          <text x={p.x} y={p.y - 7} textAnchor="middle">
            {p.name.length > 18 ? `${p.name.slice(0, 17)}…` : p.name}
          </text>
        </g>
      ))}
      <circle cx={cx} cy={cy} r={6} style={{ fill: "var(--acc)" }} />
      <text x={cx} y={cy + 17} textAnchor="middle">
        {center.length > 20 ? `${center.slice(0, 19)}…` : center}
      </text>
    </svg>
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
