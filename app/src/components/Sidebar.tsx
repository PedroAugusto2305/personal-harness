import { useEffect, useRef, useState, type ReactNode } from "react";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, PROVIDERS, STATUS_COLOR, STATUS_LABEL, shortPath } from "../lib/format";
import type { Accounts, Agent, Project, Session, SessionKind, Worktree } from "../types";
import { placeOf, worktreeLabel } from "../useWorktrees";
import { AgentSprite, spriteState } from "./AgentSprite";

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
  onAddProject: (path: string) => Promise<boolean>;
  onRemoveProject: (project: Project) => void;
  onCreateWorktree: (project: Project, name: string, copyEnv: boolean, openClaude: boolean) => Promise<boolean>;
  onDeleteWorktree: (project: Project, worktree: Worktree) => void;
  onAccounts: () => void;
  onAgents: () => void;
  onDismissError: () => void;
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

export function Sidebar(props: Props) {
  const { projects, worktrees, sessions, selected, accounts } = props;
  const [collapsed, toggleCollapsed] = useStoredSet("harness.projects.collapsed");
  const [adding, setAdding] = useState(false);
  const [newPath, setNewPath] = useState("");
  const [creatingIn, setCreatingIn] = useState<string | null>(null);
  const [agentMenu, setAgentMenu] = useState(false);

  const placeOfSession = (s: Session) => placeOf(s.cwd, projects, worktrees);
  const loose = sessions.filter((s) => !placeOfSession(s));
  const selectedProject = selected ? projects.find((p) => p.id === selected.project) : null;
  const selectedWorktree = selected ? worktrees[selected.project]?.find((w) => w.path === selected.path) : null;

  const sessionRow = (session: Session, nested: boolean) => {
    const account = props.accountName(session);
    const agent = session.agent ? props.agents.find((a) => a.id === session.agent) : null;
    return (
      <div key={session.id} className="session-item" data-nested={nested ? "true" : undefined}>
        <button
          type="button"
          className="session-row"
          aria-current={session.id === props.focusedId ? "true" : undefined}
          onClick={() => props.onSelect(session.id)}
        >
          {agent ? (
            <AgentSprite agent={agent} client={props.client} size={18} state={spriteState(session)} />
          ) : (
            <span className="session-glyph" style={{ color: KIND_COLOR[session.kind] }}>
              {KIND_GLYPH[session.kind]}
            </span>
          )}
          <span className="meta">
            <span className="session-title">
              {session.title}
              {account && <span className="small"> · {account}</span>}
            </span>
            <span className="small mono">
              <span className="dot" style={{ background: STATUS_COLOR[session.status] }} /> {STATUS_LABEL[session.status]}
              {session.ports.length > 0 && ` · :${session.ports.join(" :")}`}
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

  return (
    <nav className="sidebar" aria-label="Projetos e terminais">
      <div className="context">
        {selectedProject && selectedWorktree ? (
          <button type="button" className="context-chip" onClick={() => props.onSelectPlace(null)} title="Abrir terminais fora dos projetos">
            <Icon d={ICON.branch} size={13} />
            <span className="context-name">
              {selectedProject.name} <span className="small">· {worktreeLabel(selectedWorktree)}</span>
            </span>
            <Icon d={ICON.close} size={11} strokeWidth={2} />
          </button>
        ) : (
          <label className="folder">
            <span className="section-title">Abrir em</span>
            <input
              value={props.folder}
              onChange={(event) => props.onFolder(event.target.value)}
              spellCheck={false}
              placeholder="~/pasta"
            />
          </label>
        )}
        <div className="new-buttons">
          <button type="button" className="btn primary" disabled={!props.ready} onClick={() => props.onCreate("claude")}>
            Claude
          </button>
          <button type="button" className="btn" disabled={!props.ready} onClick={() => props.onCreate("codex")}>
            Codex
          </button>
          <button type="button" className="btn" disabled={!props.ready} onClick={() => props.onCreate("shell")}>
            Shell
          </button>
          <button type="button" className="btn" onClick={props.onWeb} title="Abrir o navegador da MÊTIS (com modo de design)" aria-label="Abrir navegador">
            <Icon d={ICON.globe} size={14} />
          </button>
          <button
            type="button"
            className="btn"
            disabled={!props.ready}
            aria-expanded={agentMenu}
            onClick={() => setAgentMenu((open) => !open)}
            title="Abrir um agente"
          >
            <Icon d={ICON.agents} size={14} />
          </button>
        </div>
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
        <div className="tree-head">
          <span className="section-title">Projetos</span>
          <button type="button" className="icon-btn" title="Adicionar projeto" aria-label="Adicionar projeto" onClick={() => setAdding((v) => !v)}>
            <Icon d={ICON.plus} size={14} strokeWidth={2} />
          </button>
        </div>
        {adding && (
          <form
            className="inline-form"
            onSubmit={async (event) => {
              event.preventDefault();
              if (newPath.trim() && (await props.onAddProject(newPath.trim()))) {
                setNewPath("");
                setAdding(false);
              }
            }}
          >
            <input autoFocus value={newPath} onChange={(e) => setNewPath(e.target.value)} placeholder="~/caminho/do/repositorio" spellCheck={false} />
            <button type="submit" className="btn primary" disabled={!newPath.trim()}>
              Adicionar
            </button>
          </form>
        )}
        {projects.length === 0 && !adding && (
          <p className="tree-hint small">Adicione um repositório git para ver as worktrees e abrir agentes nelas.</p>
        )}

        {projects.map((project) => {
          const open = !collapsed.has(project.id);
          const list = worktrees[project.id] ?? [];
          return (
            <div className="project" key={project.id}>
              <div className="project-row">
                <button type="button" className="project-toggle" aria-expanded={open} onClick={() => toggleCollapsed(project.id)}>
                  <span className="chev" data-open={open ? "true" : undefined}>
                    <Icon d={ICON.chevron} size={12} strokeWidth={2.2} />
                  </span>
                  <span className="project-name">{project.name}</span>
                  {list.length > 1 && <span className="count">{list.length}</span>}
                </button>
                <button
                  type="button"
                  className="icon-btn row-action"
                  title="Nova worktree"
                  aria-label={`Nova worktree em ${project.name}`}
                  onClick={() => setCreatingIn(creatingIn === project.id ? null : project.id)}
                >
                  <Icon d={ICON.plus} size={13} strokeWidth={2} />
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
              {open && (
                <div className="project-body">
                  {props.worktreeErrors[project.id] && <div className="tree-hint small">{props.worktreeErrors[project.id]}</div>}
                  {creatingIn === project.id && (
                    <NewWorktreeForm
                      project={project}
                      onCancel={() => setCreatingIn(null)}
                      onCreate={async (name, copyEnv, openClaude) => {
                        const ok = await props.onCreateWorktree(project, name, copyEnv, openClaude);
                        if (ok) setCreatingIn(null);
                        return ok;
                      }}
                    />
                  )}
                  {list.map((worktree) => {
                    const here = selected?.project === project.id && selected.path === worktree.path;
                    const inside = sessions.filter((s) => placeOfSession(s)?.worktree.path === worktree.path);
                    return (
                      <div key={worktree.path} className="worktree">
                        <div className="worktree-row" aria-current={here ? "true" : undefined}>
                          <button
                            type="button"
                            className="worktree-main"
                            title={`${shortPath(worktree.path)}${worktree.main ? " · pasta principal" : ""}`}
                            onClick={() => props.onSelectPlace({ project: project.id, path: worktree.path })}
                          >
                            <Icon d={worktree.main ? ICON.folder : ICON.branch} size={13} />
                            <span className="worktree-name">{worktreeLabel(worktree)}</span>
                            {worktree.missing && <span className="badge warn">sumiu</span>}
                            {worktree.changes > 0 && (
                              <span className="badge" title={`${worktree.changes} mudança(s) sem commit`}>
                                ●{worktree.changes}
                              </span>
                            )}
                            {worktree.ahead > 0 && <span className="badge" title="commits para subir">↑{worktree.ahead}</span>}
                            {worktree.behind > 0 && <span className="badge" title="commits para puxar">↓{worktree.behind}</span>}
                          </button>
                          {!worktree.main && (
                            <button
                              type="button"
                              className="icon-btn row-action"
                              title="Apagar worktree"
                              aria-label={`Apagar a worktree ${worktreeLabel(worktree)}`}
                              onClick={() => props.onDeleteWorktree(project, worktree)}
                            >
                              <Icon d={ICON.trash} size={13} />
                            </button>
                          )}
                        </div>
                        {inside.map((s) => sessionRow(s, true))}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {loose.length > 0 && (
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
              <span style={{ color: KIND_COLOR[provider] }}>{KIND_GLYPH[provider]}</span> {name}
            </span>
          );
        })}
        <span className="account-switch">trocar</span>
      </button>
    </nav>
  );
}

function NewWorktreeForm({
  project,
  onCreate,
  onCancel,
}: {
  project: Project;
  onCreate: (name: string, copyEnv: boolean, openClaude: boolean) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [copyEnv, setCopyEnv] = useState(true);
  const [openClaude, setOpenClaude] = useState(true);
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="inline-form worktree-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!name.trim()) return;
        setBusy(true);
        await onCreate(name.trim(), copyEnv, openClaude);
        setBusy(false);
      }}
      onKeyDown={(event) => event.key === "Escape" && onCancel()}
    >
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={`nome da tarefa em ${project.name}`} spellCheck={false} />
      <label className="check">
        <input type="checkbox" checked={copyEnv} onChange={(e) => setCopyEnv(e.target.checked)} /> copiar o .env
      </label>
      <label className="check">
        <input type="checkbox" checked={openClaude} onChange={(e) => setOpenClaude(e.target.checked)} /> abrir o Claude nela
      </label>
      <div className="form-buttons">
        <button type="submit" className="btn primary" disabled={!name.trim() || busy}>
          {busy ? "Criando…" : "Criar worktree"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancelar
        </button>
      </div>
      <span className="small">Branch novo com esse nome, em ~/orca/workspaces/{project.path.split("/").pop()}/.</span>
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
              {agent.description || (agent.cli === "claude" ? "Claude Code" : "Codex")}
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
