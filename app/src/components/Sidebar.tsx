import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { KindIcon } from "./KindIcon";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, PROVIDERS, STATUS_COLOR, STATUS_LABEL, fold, shortPath } from "../lib/format";
import type { Accounts, Agent, Project, Session, SessionKind, SidebarState, Worktree } from "../types";
import { placeOf, worktreeLabel } from "../useWorktrees";
import { AgentSprite, spriteState } from "./AgentSprite";
import { modelLabel } from "./Dock";

export interface Selected {
  project: string;
  path: string;
}

interface Props {
  client: CoreClient | null;
  projects: Project[];
  worktrees: Record<string, Worktree[]>;
  worktreeErrors: Record<string, string>;
  sessions: Session[];
  agents: Agent[];
  accounts: Accounts;
  focusedId: string | null;
  selected: Selected | null;
  folder: string;
  ready: boolean;
  error: string | null;
  accountName: (session: Session) => string | null;
  onSelectPlace: (place: Selected | null) => void;
  onFolder: (value: string) => void;
  onCreate: (kind: SessionKind) => void;
  onWeb: () => void;
  onLaunchAgent: (agent: Agent) => void;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  /** v0.9.9: os diálogos do Orca: adicionar projeto e novo workspace (⌘N). */
  onOpenAddProject: () => void;
  onNewWorkspace: (projectId?: string) => void;
  onRemoveProject: (project: Project) => void;
  onDeleteWorktree: (project: Project, worktree: Worktree) => void;
  onAccounts: () => void;
  onAgents: () => void;
  onDismissError: () => void;
  // v0.9.8: fixados, apelidos, cores e renomear terminal
  sidebar: SidebarState;
  onPin: (path: string, pinned: boolean) => void;
  onAlias: (path: string, name: string) => void;
  onColor: (projectId: string, color: string) => void;
  onRenameSession: (id: string, title: string) => void;
  /** v0.9.9: os atalhos do topo (mockup): Tarefas abre o kanban, Rotinas abre o Hoje. */
  onTasks: () => void;
  onRoutines: () => void;
}

function useStoredSet(key: string): [Set<string>, (id: string) => void] {
  const [value, setValue] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(key) ?? "[]"));
    } catch {
      return new Set();
    }
  });
  const toggle = (id: string) =>
    setValue((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        localStorage.setItem(key, JSON.stringify([...next]));
      } catch {
        // sem armazenamento: só não lembra
      }
      return next;
    });
  return [value, toggle];
}

/** "4m", "2h", "3d": há quanto tempo (o mockup mostra o modelo e o tempo na linha da sessão). */
function ageOf(epoch: number | null | undefined): string {
  if (!epoch) return "";
  const seconds = Math.max(0, Date.now() / 1000 - epoch);
  if (seconds < 60) return "agora";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

/** Cores para o projeto (v0.9.8): um ponto na barra e uma faixa nas worktrees dele. */
const PROJECT_COLORS = ["#82a0ff", "#8be9fd", "#50fa7b", "#f1fa8c", "#ffb86c", "#ff79c6", "#bd93f9", "#ff5555", "#a9aec9"];

type StatusFilter = "esperando" | "trabalhando" | "mudancas";
const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "esperando", label: "Esperando você" },
  { key: "trabalhando", label: "Trabalhando" },
  { key: "mudancas", label: "Com mudanças" },
];

export function Sidebar(props: Props) {
  const { projects, worktrees, sessions, selected, accounts, sidebar } = props;
  const [collapsed, toggleCollapsed] = useStoredSet("harness.projects.collapsed");
  const [statusFilter, toggleStatus] = useStoredSet("harness.sidebar.filtros");
  const [filter, setFilter] = useState("");
  const [filterOpen, setFilterOpen] = useState(() => statusFilter.size > 0);
  /** Projeto com o editor de scripts da worktree aberto (v0.9.2). */
  const [scriptsFor, setScriptsFor] = useState<string | null>(null);
  const [agentMenu, setAgentMenu] = useState(false);
  /** v0.9.8: renomear worktree (apelido) ou terminal, e a paleta de cor de um projeto. */
  const [renaming, setRenaming] = useState<{ kind: "worktree" | "session"; key: string; value: string } | null>(null);
  const [colorFor, setColorFor] = useState<string | null>(null);
  /** v0.9.9: o que mostrar nos atalhos do topo (tarefas andando e rotinas ativas). */
  const [counts, setCounts] = useState<{ tasks: number; routines: number } | null>(null);
  useEffect(() => {
    const client = props.client;
    if (!client) return;
    let alive = true;
    const load = () =>
      void Promise.all([client.boardProjects(), client.routines()])
        .then(([board, r]) => {
          if (!alive) return;
          setCounts({
            tasks: board.reduce((n, p) => n + p.tasks["em-andamento"] + p.tasks["em-teste"], 0),
            routines: r.routines.filter((x) => x.active).length,
          });
        })
        .catch(() => undefined);
    load();
    // A contagem lê as notas de todos os projetos no núcleo: a cada 5 minutos basta.
    const timer = window.setInterval(load, 300_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [props.client]);

  const placeOfSession = (s: Session) => placeOf(s.cwd, projects, worktrees);
  const loose = sessions.filter((s) => !placeOfSession(s));
  const selectedProject = selected ? projects.find((p) => p.id === selected.project) : null;
  const selectedWorktree = selected ? worktrees[selected.project]?.find((w) => w.path === selected.path) : null;
  const nameOf = (worktree: Worktree) => sidebar.nomes[worktree.path] || worktreeLabel(worktree);
  const pinned = new Set(sidebar.fixados);
  const insideOf = (worktree: Worktree) => sessions.filter((s) => placeOfSession(s)?.worktree.path === worktree.path);

  const words = fold(filter).split(/\s+/).filter(Boolean);
  const filtering = words.length > 0 || statusFilter.size > 0;
  const matches = (project: Project, worktree: Worktree) => {
    const inside = insideOf(worktree);
    if (statusFilter.has("esperando") && !inside.some((s) => s.status === "waiting")) return false;
    if (statusFilter.has("trabalhando") && !inside.some((s) => s.status === "working")) return false;
    if (statusFilter.has("mudancas") && !(worktree.changes > 0)) return false;
    if (!words.length) return true;
    const hay = fold([project.name, nameOf(worktree), worktree.branch ?? "", ...inside.map((s) => s.title)].join(" "));
    return words.every((word) => hay.includes(word));
  };

  const finishRename = () => {
    if (!renaming) return;
    const value = renaming.value.trim();
    if (renaming.kind === "worktree") props.onAlias(renaming.key, value);
    else if (value) props.onRenameSession(renaming.key, value);
    setRenaming(null);
  };

  const renameInput = (label: string) =>
    renaming && (
      <input
        className="rename-input"
        autoFocus
        value={renaming.value}
        maxLength={renaming.kind === "worktree" ? 60 : 80}
        aria-label={label}
        onChange={(event) => setRenaming({ ...renaming, value: event.target.value })}
        onKeyDown={(event) => {
          if (event.key === "Enter") finishRename();
          else if (event.key === "Escape") setRenaming(null);
        }}
        onBlur={finishRename}
        onClick={(event) => event.stopPropagation()}
      />
    );

  const sessionRow = (session: Session, nested: boolean) => {
    const account = props.accountName(session);
    const agent = session.agent ? props.agents.find((a) => a.id === session.agent) : null;
    const editing = renaming?.kind === "session" && renaming.key === session.id;
    return (
      <div key={session.id} className="session-item" data-nested={nested ? "true" : undefined}>
        <button
          type="button"
          className="session-row one-line"
          aria-current={session.id === props.focusedId ? "true" : undefined}
          onClick={() => props.onSelect(session.id)}
          onDoubleClick={() => setRenaming({ kind: "session", key: session.id, value: session.title })}
          title={`${session.title}${account ? ` · ${account}` : ""} · ${session.hibernando ? "hibernando" : STATUS_LABEL[session.status]}${session.ports.length ? ` · :${session.ports.join(" :")}` : ""} · duplo clique renomeia`}
        >
          <span className="session-dot" style={{ background: session.hibernando ? "var(--fnt)" : STATUS_COLOR[session.status] }} />
          {agent ? (
            <AgentSprite agent={agent} client={props.client} size={16} state={spriteState(session)} />
          ) : (
            <span className="session-glyph" style={{ color: KIND_COLOR[session.kind] }}>
              <KindIcon kind={session.kind} size={14} />
            </span>
          )}
          <span className="meta">
            {editing ? (
              renameInput("Novo nome do terminal")
            ) : (
              <span className="session-title">
                {session.title}
                {account && <span className="small"> · {account}</span>}
              </span>
            )}
            <span className="session-meta">
              {[modelLabel(session.statusline?.model).toLowerCase(), ageOf(session.status_desde ?? session.created_at), session.ports.length ? `:${session.ports[0]}` : ""]
                .filter(Boolean)
                .join(" ")}
            </span>
          </span>
        </button>
        <button
          type="button"
          className="session-close"
          aria-label={`Fechar ${session.title}`}
          title="Fechar terminal"
          onClick={() => props.onClose(session.id)}
        >
          <Icon d={ICON.close} size={12} strokeWidth={2} />
        </button>
      </div>
    );
  };

  const worktreeRow = (project: Project, worktree: Worktree, showProject: boolean) => {
    const here = selected?.project === project.id && selected.path === worktree.path;
    const inside = insideOf(worktree);
    const isPinned = pinned.has(worktree.path);
    const alias = sidebar.nomes[worktree.path];
    const editing = renaming?.kind === "worktree" && renaming.key === worktree.path;
    const color = sidebar.cores[project.id];
    return (
      <div key={worktree.path} className="worktree" style={color ? ({ "--proj": color } as CSSProperties) : undefined} data-colored={color ? "true" : undefined}>
        <div className="worktree-row" aria-current={here ? "true" : undefined}>
          <button
            type="button"
            className="worktree-main"
            title={`${shortPath(worktree.path)}${worktree.main ? " · pasta principal" : ""}${alias ? ` · branch ${worktreeLabel(worktree)}` : ""} · duplo clique dá um apelido`}
            onClick={() => props.onSelectPlace({ project: project.id, path: worktree.path })}
            onDoubleClick={() => setRenaming({ kind: "worktree", key: worktree.path, value: alias ?? "" })}
          >
            <Icon d={worktree.main ? ICON.folder : ICON.branch} size={15} />
            {editing ? (
              renameInput("Apelido da worktree (vazio volta ao nome do branch)")
            ) : (
              <span className="worktree-name">
                {showProject && <span className="small">{project.name} · </span>}
                {nameOf(worktree)}
              </span>
            )}
            {worktree.missing && <span className="badge warn">sumiu</span>}
            {worktree.changes > 0 && (
              <span className="badge" title={`${worktree.changes} mudança(s) sem commit`}>
                ●{worktree.changes}
              </span>
            )}
            {worktree.ahead > 0 && <span className="badge" title="commits para subir">↑{worktree.ahead}</span>}
            {worktree.behind > 0 && <span className="badge" title="commits para puxar">↓{worktree.behind}</span>}
          </button>
          <button
            type="button"
            className="icon-btn row-action"
            data-on={isPinned ? "true" : undefined}
            title={isPinned ? "Desafixar" : "Fixar no topo"}
            aria-label={`${isPinned ? "Desafixar" : "Fixar"} ${nameOf(worktree)}`}
            onClick={() => props.onPin(worktree.path, !isPinned)}
          >
            <Icon d={ICON.pin} size={13} />
          </button>
          <button
            type="button"
            className="icon-btn row-action"
            title="Apelido (o branch continua o mesmo)"
            aria-label={`Dar um apelido a ${nameOf(worktree)}`}
            onClick={() => setRenaming({ kind: "worktree", key: worktree.path, value: alias ?? "" })}
          >
            <Icon d={ICON.edit} size={13} />
          </button>
          {!worktree.main && (
            <button
              type="button"
              className="icon-btn row-action"
              title="Apagar worktree"
              aria-label={`Apagar a worktree ${nameOf(worktree)}`}
              onClick={() => props.onDeleteWorktree(project, worktree)}
            >
              <Icon d={ICON.trash} size={13} />
            </button>
          )}
        </div>
        {inside.map((s) => sessionRow(s, true))}
      </div>
    );
  };

  const pinnedRows = projects.flatMap((project) =>
    (worktrees[project.id] ?? []).filter((w) => pinned.has(w.path) && matches(project, w)).map((w) => worktreeRow(project, w, true)),
  );

  return (
    <nav className="sidebar" aria-label="Projetos e terminais">
      <div className="side-top">
        <button type="button" className="side-link" onClick={props.onTasks} title="Kanban: tarefas dos projetos">
          <Icon d={ICON.kanban} size={15} />
          <span className="side-label">Tarefas</span>
          {counts && counts.tasks > 0 && <span className="side-count" title="em andamento ou em teste">{counts.tasks}</span>}
        </button>
        <button type="button" className="side-link" onClick={props.onRoutines} title="Rotinas de hoje (tela Hoje)">
          <Icon d={ICON.history} size={15} />
          <span className="side-label">Rotinas</span>
          {counts && <span className="side-count">{counts.routines}</span>}
        </button>
      </div>
      <div className="context">
        <div className="side-new">
          <span className="side-new-label" title={selectedProject && selectedWorktree ? selectedWorktree.path : props.folder || "~"}>
            novo em{" "}
            {selectedProject && selectedWorktree ? (
              <>
                {selectedProject.name} · {nameOf(selectedWorktree)}{" "}
                <button type="button" className="side-clear" onClick={() => props.onSelectPlace(null)} title="Abrir terminais fora dos projetos" aria-label="Tirar a worktree escolhida">
                  ×
                </button>
              </>
            ) : (
              shortPath(props.folder || "~")
            )}
          </span>
          <button type="button" disabled={!props.ready} onClick={() => props.onCreate("claude")} title="Claude Code" aria-label="Novo Claude Code">
            <KindIcon kind="claude" size={16} />
          </button>
          <button type="button" disabled={!props.ready} onClick={() => props.onCreate("codex")} title="Codex" aria-label="Novo Codex">
            <KindIcon kind="codex" size={16} />
          </button>
          <button type="button" disabled={!props.ready} onClick={() => props.onCreate("shell")} title="Shell" aria-label="Novo shell">
            <span className="mono">{">_"}</span>
          </button>
          <button type="button" onClick={props.onWeb} title="Navegador da MÊTIS (com modo de design)" aria-label="Abrir navegador">
            <Icon d={ICON.globe} size={16} strokeWidth={1.7} />
          </button>
          <button type="button" disabled={!props.ready} aria-expanded={agentMenu} onClick={() => setAgentMenu((open) => !open)} title="Abrir um agente" aria-label="Abrir um agente">
            <Icon d={ICON.agents} size={16} strokeWidth={1.7} />
          </button>
        </div>
        {!(selectedProject && selectedWorktree) && (
          <label className="folder">
            <span className="section-title">Pasta</span>
            <input value={props.folder} onChange={(event) => props.onFolder(event.target.value)} spellCheck={false} placeholder="~/pasta" />
          </label>
        )}
        {agentMenu && (
          <AgentMenu
            agents={props.agents}
            client={props.client}
            onPick={(agent) => {
              setAgentMenu(false);
              props.onLaunchAgent(agent);
            }}
            onManage={() => {
              setAgentMenu(false);
              props.onAgents();
            }}
            onClose={() => setAgentMenu(false)}
          />
        )}
      </div>

      {props.error && (
        <div className="error-box" role="alert">
          {props.error}
          <button type="button" className="icon-btn" onClick={props.onDismissError} aria-label="Fechar aviso">
            <Icon d={ICON.close} size={12} strokeWidth={2} />
          </button>
        </div>
      )}

      <div className="tree">
        {pinnedRows.length > 0 && (
          <>
            <div className="tree-head">
              <span className="section-title">Fixados</span>
            </div>
            <div className="project-body pinned">{pinnedRows}</div>
          </>
        )}
        <div className="tree-head">
          <span className="section-title">Projetos</span>
          {/* v0.9.9: os três juntos à direita, como no Orca. */}
          <span className="tree-actions">
            <button
              type="button"
              className="icon-btn"
              title="Filtrar worktrees e terminais"
              aria-label="Filtrar"
              aria-expanded={filterOpen}
              data-on={filtering ? "true" : undefined}
              onClick={() => setFilterOpen((v) => !v)}
            >
              <Icon d={ICON.sliders} size={17} strokeWidth={1.7} />
            </button>
            <button type="button" className="icon-btn" title="Adicionar projeto" aria-label="Adicionar projeto" onClick={props.onOpenAddProject}>
              <Icon d={ICON.folderPlus} size={17} strokeWidth={1.7} />
            </button>
            <button type="button" className="icon-btn" title="Novo workspace (⌘N)" aria-label="Novo workspace" onClick={() => props.onNewWorkspace()}>
              <Icon d={ICON.plus} size={17} strokeWidth={1.8} />
            </button>
          </span>
        </div>
        {filterOpen && (
          <div className="tree-filter">
            <input
              autoFocus
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filtrar por nome, branch ou terminal"
              spellCheck={false}
              onKeyDown={(event) => event.key === "Escape" && (setFilter(""), setFilterOpen(statusFilter.size > 0))}
            />
            <div className="filter-chips">
              {STATUS_FILTERS.map((item) => (
                <button key={item.key} type="button" className="chip-toggle" aria-pressed={statusFilter.has(item.key)} onClick={() => toggleStatus(item.key)}>
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        )}
        {projects.length === 0 && (
          <div className="tree-empty">
            <p className="tree-hint small">Adicione um repositório git para ver as worktrees e abrir agentes nelas.</p>
            <button type="button" className="btn primary" onClick={props.onOpenAddProject}>
              Adicionar projeto
            </button>
          </div>
        )}

        {projects.map((project) => {
          const all = worktrees[project.id] ?? [];
          const list = all.filter((w) => !pinned.has(w.path) && matches(project, w));
          if (filtering && list.length === 0 && !(words.length && words.every((w) => fold(project.name).includes(w)))) return null;
          const open = filtering || !collapsed.has(project.id);
          const color = sidebar.cores[project.id];
          return (
            <div className="project" key={project.id}>
              <div className="project-row">
                <button type="button" className="project-toggle" aria-expanded={open} onClick={() => toggleCollapsed(project.id)}>
                  <span className="chev" data-open={open ? "true" : undefined}>
                    <Icon d={ICON.chevron} size={12} strokeWidth={2.2} />
                  </span>
                  <span className="project-name">{project.name}</span>
                  {all.length > 1 && <span className="count">{all.length}</span>}
                </button>
                <button
                  type="button"
                  className="project-color"
                  style={color ? { background: color } : undefined}
                  data-empty={color ? undefined : "true"}
                  title="Cor do projeto"
                  aria-label={`Cor de ${project.name}`}
                  aria-expanded={colorFor === project.id}
                  onClick={() => setColorFor(colorFor === project.id ? null : project.id)}
                />
                <button
                  type="button"
                  className="icon-btn row-action"
                  title="Novo workspace neste projeto"
                  aria-label={`Novo workspace em ${project.name}`}
                  onClick={() => props.onNewWorkspace(project.id)}
                >
                  <Icon d={ICON.plus} size={13} strokeWidth={2} />
                </button>
                <button
                  type="button"
                  className="icon-btn row-action"
                  title="Scripts da worktree…"
                  aria-label={`Scripts da worktree em ${project.name}`}
                  aria-expanded={scriptsFor === project.id}
                  onClick={() => setScriptsFor(scriptsFor === project.id ? null : project.id)}
                >
                  <Icon d={ICON.code} size={13} strokeWidth={1.9} />
                </button>
                <button
                  type="button"
                  className="icon-btn row-action"
                  title="Tirar da lista (o repositório fica no disco)"
                  aria-label={`Tirar ${project.name} da lista`}
                  onClick={() => props.onRemoveProject(project)}
                >
                  <Icon d={ICON.close} size={12} strokeWidth={2} />
                </button>
              </div>
              {colorFor === project.id && (
                <div className="color-pick" role="radiogroup" aria-label={`Cor de ${project.name}`}>
                  {PROJECT_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      role="radio"
                      aria-checked={color === c}
                      aria-label={c}
                      style={{ background: c }}
                      onClick={() => (props.onColor(project.id, c), setColorFor(null))}
                    />
                  ))}
                  <button type="button" className="color-none" aria-label="Sem cor" onClick={() => (props.onColor(project.id, ""), setColorFor(null))}>
                    <Icon d={ICON.close} size={11} strokeWidth={2} />
                  </button>
                </div>
              )}
              {scriptsFor === project.id && <ProjectScriptsForm client={props.client} project={project} onClose={() => setScriptsFor(null)} />}
              {open && (
                <div className="project-body">
                  {props.worktreeErrors[project.id] && <div className="tree-hint small">{props.worktreeErrors[project.id]}</div>}
                  {list.map((worktree) => worktreeRow(project, worktree, false))}
                </div>
              )}
            </div>
          );
        })}
        {filtering && pinnedRows.length === 0 && projects.every((p) => !(worktrees[p.id] ?? []).some((w) => matches(p, w))) && (
          <p className="tree-hint small">Nada com esse filtro.</p>
        )}

        {loose.length > 0 && !filtering && (
          <>
            <div className="tree-head">
              <span className="section-title">Fora dos projetos</span>
            </div>
            {loose.map((s) => sessionRow(s, false))}
          </>
        )}
      </div>

      <button type="button" className="account-line" onClick={props.onAccounts} title="Trocar de conta">
        <Icon d={ICON.user} size={13} strokeWidth={1.9} />
        {PROVIDERS.map((provider) => {
          const entry = accounts[provider];
          const name = entry.accounts.find((a) => a.id === entry.active)?.name ?? "padrão";
          return (
            <span key={provider}>
              <KindIcon kind={provider} /> {name}
            </span>
          );
        })}
        <span className="account-switch">trocar</span>
      </button>
    </nav>
  );
}

/**
 * Scripts da worktree (v0.9.2): o de setup roda num terminal à vista em cada worktree nova
 * (instalar dependências, copiar segredos…); o de arquivar roda antes de apagar uma, e se
 * falhar a worktree fica (até você apagar mesmo assim).
 */
function ProjectScriptsForm({ client, project, onClose }: { client: CoreClient | null; project: Project; onClose: () => void }) {
  const [setup, setSetup] = useState("");
  const [archive, setArchive] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .projectScripts(project.id)
      .then((scripts) => {
        if (!alive) return;
        setSetup(scripts.setup);
        setArchive(scripts.arquivar);
        setLoaded(true);
      })
      .catch((cause) => alive && setError(cause instanceof Error ? cause.message : String(cause)));
    return () => {
      alive = false;
    };
  }, [client, project.id]);

  return (
    <form
      className="inline-form scripts-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!client) return;
        setBusy(true);
        setError(null);
        try {
          await client.setProjectScripts(project.id, { setup, arquivar: archive });
          onClose();
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : String(cause));
        } finally {
          setBusy(false);
        }
      }}
      onKeyDown={(event) => event.key === "Escape" && onClose()}
    >
      <span className="section-title scripts-title">Scripts da worktree · {project.name}</span>
      <label className="scripts-field">
        <span className="small">Ao criar a worktree (roda num terminal à vista)</span>
        <textarea
          autoFocus
          rows={3}
          value={setup}
          disabled={!loaded}
          spellCheck={false}
          placeholder={loaded ? "ex.: pnpm install && cp ../.env.local ." : "carregando…"}
          onChange={(event) => setSetup(event.target.value)}
        />
      </label>
      <label className="scripts-field">
        <span className="small">Antes de apagar a worktree (se falhar, não apaga)</span>
        <textarea
          rows={2}
          value={archive}
          disabled={!loaded}
          spellCheck={false}
          placeholder={loaded ? "ex.: docker compose down" : "carregando…"}
          onChange={(event) => setArchive(event.target.value)}
        />
      </label>
      {error && <div className="error-box">{error}</div>}
      <div className="form-buttons">
        <button type="submit" className="btn primary" disabled={!loaded || busy}>
          {busy ? "Salvando…" : "Salvar"}
        </button>
        <button type="button" className="btn" onClick={onClose}>
          Cancelar
        </button>
      </div>
      <span className="small">Rodam no zsh, dentro da pasta da worktree. Vazio = nada roda.</span>
    </form>
  );
}

function AgentMenu({
  agents,
  client,
  onPick,
  onManage,
  onClose,
}: {
  agents: Agent[];
  client: CoreClient | null;
  onPick: (agent: Agent) => void;
  onManage: () => void;
  onClose: () => void;
}): ReactNode {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) onClose();
    };
    const esc = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", esc);
    };
  }, [onClose]);
  return (
    <div className="agent-menu" ref={box} role="menu">
      {agents.length === 0 && <p className="small">Nenhum agente ainda.</p>}
      {agents.map((agent) => (
        <button key={agent.id} type="button" role="menuitem" className="agent-menu-item" onClick={() => onPick(agent)}>
          <AgentSprite agent={agent} client={client} size={24} />
          <span className="meta">
            <span className="agent-menu-name">{agent.name}</span>
            <span className="small">
              {agent.description || (agent.cli === "claude" ? "Claude Code" : agent.cli === "codex" ? "Codex" : agent.command || "outra CLI")}
              {agent.folder ? ` · ${shortPath(agent.folder)}` : " · na worktree escolhida"}
            </span>
          </span>
        </button>
      ))}
      <button type="button" className="agent-menu-manage" onClick={onManage}>
        Gerenciar agentes…
      </button>
    </div>
  );
}
