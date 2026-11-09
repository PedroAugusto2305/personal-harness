import { useEffect, useMemo, useRef, useState } from "react";
import { KindIcon } from "./KindIcon";
import { ICON, Icon } from "../icons";
import { inTauri, type CoreClient } from "../lib/core";
import { ago, shortPath } from "../lib/format";
import type { Agent, Project, RefBranch, RefCommit, WorktreeMode } from "../types";
import { AgentSprite } from "./AgentSprite";
import "./projects.css";

/**
 * Projetos no jeito do Orca (v0.9.9, pedido do Pedro): o cabeçalho de Projetos tem "Adicionar
 * projeto" e "Novo workspace" (⌘N), cada um num diálogo próprio, em vez do caminho digitado e
 * do formulário espremido na árvore.
 *
 * Adicionar projeto: abrir uma pasta (seletor do macOS), os repositórios que já estão no Mac
 * com um clique, clonar de uma URL ou criar um projeto novo.
 * Novo workspace: projeto, de onde sai (branch novo, branch existente ou commit), o que abre
 * nele (Claude, Codex, um agente ou um terminal), o pedido inicial e "criar mais".
 */

async function pickFolder(defaultPath?: string): Promise<string | null> {
  if (!inTauri()) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const chosen = await open({ directory: true, multiple: false, defaultPath, title: "Escolha a pasta do projeto" });
  return typeof chosen === "string" ? chosen : null;
}

function useEscape(onClose: () => void) {
  useEffect(() => {
    const key = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
}

// --- Adicionar projeto ----------------------------------------------------------------------

type AddStep = "inicio" | "clonar" | "criar" | "caminho";

interface AddProps {
  client: CoreClient | null;
  onClose: () => void;
  /** Adiciona a pasta como projeto; devolve o projeto ou null (o erro já virou aviso). */
  onAddPath: (path: string) => Promise<Project | null>;
  onAdded: (project: Project) => void;
  onError: (message: string) => void;
}

export function AddProjectDialog({ client, onClose, onAddPath, onAdded, onError }: AddProps) {
  const [step, setStep] = useState<AddStep>("inicio");
  const [found, setFound] = useState<{ path: string; name: string; atualizado: number }[] | null>(null);
  const [parent, setParent] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEscape(onClose);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .projectSuggestions()
      .then((answer) => {
        if (!alive) return;
        setFound(answer.repositorios);
        setParent((current) => current || answer.pasta_padrao);
      })
      .catch(() => alive && setFound([]));
    return () => {
      alive = false;
    };
  }, [client]);

  const run = async (label: string, work: () => Promise<Project | null>) => {
    setBusy(label);
    setError(null);
    try {
      const project = await work();
      if (project) onAdded(project);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      onError(message);
    } finally {
      setBusy(null);
    }
  };

  const browse = async () => {
    if (!inTauri()) {
      setStep("caminho");
      return;
    }
    const chosen = await pickFolder(parent || undefined);
    if (chosen) void run("abrindo", () => onAddPath(chosen));
  };

  const shown = useMemo(() => {
    const words = filter.trim().toLowerCase();
    return (found ?? []).filter((r) => !words || r.name.toLowerCase().includes(words) || r.path.toLowerCase().includes(words));
  }, [found, filter]);

  return (
    <div className="overlay center" onMouseDown={onClose}>
      <div className="pd" role="dialog" aria-label="Adicionar um projeto" onMouseDown={(event) => event.stopPropagation()}>
        <header className="pd-head">
          {step !== "inicio" && (
            <button type="button" className="pd-back" aria-label="Voltar" onClick={() => (setStep("inicio"), setError(null))}>
              ‹
            </button>
          )}
          <span className="pd-title">
            {step === "inicio" ? "Adicionar um projeto" : step === "clonar" ? "Clonar de uma URL" : step === "criar" ? "Criar um projeto novo" : "Digitar o caminho"}
          </span>
          <button type="button" className="pd-x" aria-label="Fechar" onClick={onClose}>
            ×
          </button>
        </header>

        {step === "inicio" && (
          <div className="pd-body">
            <button type="button" className="pd-primary" onClick={() => void browse()} disabled={!!busy} autoFocus>
              <span className="pd-primary-icon">
                <Icon d={ICON.folder} size={18} />
              </span>
              <span className="pd-primary-text">
                <span className="pd-primary-title">{busy === "abrindo" ? "Abrindo…" : "Abrir pasta"}</span>
                <span className="small">Um repositório git que já está no Mac</span>
              </span>
              <span className="pd-kbd">↵</span>
            </button>

            <div className="pd-section">
              <div className="pd-section-head">
                <span className="pd-label">Repositórios no seu Mac</span>
                {found && found.length > 6 && (
                  <input className="pd-filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filtrar" spellCheck={false} />
                )}
              </div>
              {!found && <span className="small pd-muted">procurando nas pastas de projetos…</span>}
              {found && found.length === 0 && <span className="small pd-muted">Nenhum repositório novo nas pastas de costume. Use Abrir pasta.</span>}
              <div className="pd-repos">
                {shown.slice(0, 30).map((repo) => (
                  <button key={repo.path} type="button" className="pd-repo" disabled={!!busy} onClick={() => void run(repo.path, () => onAddPath(repo.path))} title={repo.path}>
                    <Icon d={ICON.folder} size={13} />
                    <span className="pd-repo-name">{repo.name}</span>
                    <span className="small pd-repo-path">{shortPath(repo.path.replace(/\/[^/]+$/, ""))}</span>
                    <span className="small pd-repo-age">{busy === repo.path ? "adicionando…" : ago(repo.atualizado * 1000)}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="pd-section">
              <span className="pd-label">Outros jeitos</span>
              <div className="pd-others">
                <button type="button" className="pd-other" onClick={() => setStep("clonar")}>
                  <Icon d={ICON.download} size={14} />
                  <span>
                    <span className="pd-other-title">Clonar de uma URL</span>
                    <span className="small">Um repositório do GitHub ou de outro lugar</span>
                  </span>
                  <span className="pd-chev">›</span>
                </button>
                <button type="button" className="pd-other" onClick={() => setStep("criar")}>
                  <Icon d={ICON.plus} size={14} />
                  <span>
                    <span className="pd-other-title">Criar um projeto novo</span>
                    <span className="small">Pasta nova com git e o primeiro commit</span>
                  </span>
                  <span className="pd-chev">›</span>
                </button>
                <button type="button" className="pd-other" onClick={() => setStep("caminho")}>
                  <Icon d={ICON.terminal} size={14} />
                  <span>
                    <span className="pd-other-title">Digitar o caminho</span>
                    <span className="small">Quando você já sabe onde está</span>
                  </span>
                  <span className="pd-chev">›</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {step === "clonar" && (
          <form
            className="pd-body"
            onSubmit={(event) => {
              event.preventDefault();
              if (!client || !url.trim()) return;
              void run("clonando", () => client.cloneProject(url.trim(), parent.trim()));
            }}
          >
            <label className="pd-field">
              <span className="pd-label">Endereço do repositório</span>
              <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/dono/repositorio.git" spellCheck={false} />
            </label>
            <ParentField value={parent} onChange={setParent} />
            {error && <p className="pd-error small">{error}</p>}
            <div className="pd-foot">
              <span className="small pd-muted">{url.trim() ? `Vai para ${shortPath(parent)}/${url.trim().replace(/\/$/, "").split(/[/:]/).pop()?.replace(/\.git$/, "")}` : ""}</span>
              <button type="submit" className="btn primary" disabled={!url.trim() || !!busy}>
                {busy === "clonando" ? "Clonando…" : "Clonar e adicionar"}
              </button>
            </div>
          </form>
        )}

        {step === "criar" && (
          <form
            className="pd-body"
            onSubmit={(event) => {
              event.preventDefault();
              if (!client || !name.trim()) return;
              void run("criando", () => client.createProject(name.trim(), parent.trim()));
            }}
          >
            <label className="pd-field">
              <span className="pd-label">Nome do projeto</span>
              <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="meu-projeto" spellCheck={false} />
            </label>
            <ParentField value={parent} onChange={setParent} />
            {error && <p className="pd-error small">{error}</p>}
            <div className="pd-foot">
              <span className="small pd-muted">Cria a pasta com git, um README e o primeiro commit.</span>
              <button type="submit" className="btn primary" disabled={!name.trim() || !!busy}>
                {busy === "criando" ? "Criando…" : "Criar projeto"}
              </button>
            </div>
          </form>
        )}

        {step === "caminho" && (
          <form
            className="pd-body"
            onSubmit={(event) => {
              event.preventDefault();
              if (typed.trim()) void run("caminho", () => onAddPath(typed.trim()));
            }}
          >
            <label className="pd-field">
              <span className="pd-label">Pasta do repositório</span>
              <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="~/Documents/projetos/meu-repositorio" spellCheck={false} />
            </label>
            {error && <p className="pd-error small">{error}</p>}
            <div className="pd-foot">
              <span className="small pd-muted">Dentro de uma worktree, entra o repositório principal.</span>
              <button type="submit" className="btn primary" disabled={!typed.trim() || !!busy}>
                {busy ? "Adicionando…" : "Adicionar"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function ParentField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="pd-field">
      <span className="pd-label">Pasta onde fica</span>
      <span className="pd-row">
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="~/Documents/projetos" spellCheck={false} />
        {inTauri() && (
          <button
            type="button"
            className="btn"
            onClick={async () => {
              const chosen = await pickFolder(value || undefined);
              if (chosen) onChange(chosen);
            }}
          >
            Escolher…
          </button>
        )}
      </span>
    </label>
  );
}

// --- Novo workspace -------------------------------------------------------------------------

export type WorkspaceOpen = { kind: "claude" | "codex" | "shell"; agent?: string } | null;

export interface NewWorkspaceRequest {
  project: Project;
  name: string;
  mode: WorktreeMode;
  base?: string;
  copyEnv: boolean;
  open: WorkspaceOpen;
  prompt: string;
}

interface WorkspaceProps {
  client: CoreClient | null;
  projects: Project[];
  colors: Record<string, string>;
  agents: Agent[];
  initialProject: string | null;
  onClose: () => void;
  onAddProject: () => void;
  onCreate: (request: NewWorkspaceRequest) => Promise<boolean>;
}

const MODES: { key: WorktreeMode; label: string }[] = [
  { key: "nova", label: "Branch novo" },
  { key: "branch", label: "Branch existente" },
  { key: "commit", label: "Commit" },
];

const OPEN_KEY = "metis.workspace.abrir";

function storedOpen(): string {
  try {
    return localStorage.getItem(OPEN_KEY) ?? "claude";
  } catch {
    return "claude";
  }
}

export function NewWorkspaceDialog({ client, projects, colors, agents, initialProject, onClose, onAddProject, onCreate }: WorkspaceProps) {
  const [projectId, setProjectId] = useState(initialProject ?? projects[0]?.id ?? "");
  const [mode, setMode] = useState<WorktreeMode>("nova");
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [base, setBase] = useState<string | null>(null);
  const [refs, setRefs] = useState<{ branches: RefBranch[]; commits: RefCommit[] } | null>(null);
  const [openKey, setOpenKey] = useState(storedOpen);
  const [prompt, setPrompt] = useState("");
  const [copyEnv, setCopyEnv] = useState(true);
  const [advanced, setAdvanced] = useState(false);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  useEscape(onClose);

  const project = projects.find((p) => p.id === projectId) ?? null;
  const usable = agents.filter((a) => a.cli === "claude" || a.cli === "codex");

  useEffect(() => {
    try {
      localStorage.setItem(OPEN_KEY, openKey);
    } catch {
      // sem armazenamento
    }
  }, [openKey]);

  useEffect(() => {
    if (mode === "nova" || !client || !project) return;
    let stale = false;
    const timer = window.setTimeout(() => {
      void client
        .refs(project.id, query)
        .then((answer) => !stale && setRefs(answer))
        .catch(() => !stale && setRefs({ branches: [], commits: [] }));
    }, 150);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [client, project, mode, query]);

  const open: WorkspaceOpen =
    openKey === "nada"
      ? null
      : openKey === "claude" || openKey === "codex" || openKey === "shell"
        ? { kind: openKey }
        : (() => {
            const agent = usable.find((a) => a.id === openKey);
            return agent ? { kind: agent.cli as "claude" | "codex", agent: agent.id } : { kind: "claude" };
          })();
  const needsName = mode !== "branch";
  const canCreate = !!project && (!needsName || name.trim()) && (mode === "nova" || base) && !busy;
  const folder = project?.path.split("/").pop() ?? "";

  const submit = async () => {
    if (!canCreate || !project) return;
    setBusy(true);
    const ok = await onCreate({ project, name: name.trim(), mode, base: base ?? undefined, copyEnv, open, prompt: prompt.trim() });
    setBusy(false);
    if (!ok) return;
    if (more) {
      setName("");
      setPrompt("");
      setBase(null);
      setQuery("");
      nameRef.current?.focus();
    } else onClose();
  };

  if (!projects.length) {
    return (
      <div className="overlay center" onMouseDown={onClose}>
        <div className="pd" role="dialog" aria-label="Novo workspace" onMouseDown={(event) => event.stopPropagation()}>
          <header className="pd-head">
            <span className="pd-title">Novo workspace</span>
            <button type="button" className="pd-x" aria-label="Fechar" onClick={onClose}>
              ×
            </button>
          </header>
          <div className="pd-body">
            <p className="small pd-muted">Adicione um projeto antes de criar um workspace.</p>
            <div className="pd-foot">
              <span />
              <button type="button" className="btn primary" onClick={onAddProject}>
                Adicionar projeto
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="overlay center" onMouseDown={onClose}>
      <form
        className="pd pd-wide"
        role="dialog"
        aria-label="Novo workspace"
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            void submit();
          }
        }}
      >
        <header className="pd-head">
          <span className="pd-title">Novo workspace</span>
          <span className="small pd-muted">uma worktree com o agente já aberto</span>
          <button type="button" className="pd-x" aria-label="Fechar" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="pd-body">
          <div className="pd-field">
            <span className="pd-label">Projeto</span>
            <div className="pd-projects" role="radiogroup" aria-label="Projeto">
              {projects.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  role="radio"
                  aria-checked={p.id === projectId}
                  className="pd-project"
                  title={p.path}
                  onClick={() => {
                    setProjectId(p.id);
                    setBase(null);
                    setRefs(null);
                  }}
                >
                  <span className="pd-dot" style={{ background: colors[p.id] || "var(--fnt)" }} />
                  {p.name}
                </button>
              ))}
              <button type="button" className="pd-project pd-project-add" onClick={onAddProject}>
                + Adicionar projeto
              </button>
            </div>
          </div>

          <div className="pd-field">
            <span className="pd-label">Criar a partir de</span>
            <div className="segmented small-seg" role="radiogroup" aria-label="De onde sai o workspace">
              {MODES.map((m) => (
                <button
                  key={m.key}
                  type="button"
                  role="radio"
                  aria-checked={mode === m.key}
                  onClick={() => {
                    setMode(m.key);
                    setBase(null);
                    setQuery("");
                  }}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          {mode !== "nova" && (
            <div className="pd-field">
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={mode === "branch" ? "procurar branch (local ou origin/…)" : "procurar commit (sha ou mensagem)"} spellCheck={false} autoFocus />
              <ul className="pd-refs" role="listbox" aria-label={mode === "branch" ? "Branches" : "Commits"}>
                {mode === "branch" &&
                  refs?.branches.map((b) => (
                    <li key={b.nome}>
                      <button type="button" role="option" aria-selected={base === b.nome} disabled={!!b.em_uso} title={b.em_uso ? `já aberto em ${shortPath(b.em_uso)}` : b.titulo} onClick={() => setBase(b.nome)}>
                        <span className="mono">{b.nome}</span>
                        <span className="small">{b.em_uso ? "já aberto" : b.titulo}</span>
                      </button>
                    </li>
                  ))}
                {mode === "commit" &&
                  refs?.commits.map((c) => (
                    <li key={c.sha}>
                      <button type="button" role="option" aria-selected={base === c.sha} title={`${c.autor} · ${c.quando}`} onClick={() => setBase(c.sha)}>
                        <span className="mono">{c.curto}</span>
                        <span className="small">{c.titulo}</span>
                      </button>
                    </li>
                  ))}
                {refs && (mode === "branch" ? refs.branches : refs.commits).length === 0 && <li className="small pd-muted">Nada com isso.</li>}
                {!refs && <li className="small pd-muted">lendo…</li>}
              </ul>
            </div>
          )}

          <label className="pd-field">
            <span className="pd-label">{mode === "branch" ? "Nome da pasta (opcional)" : "Nome do workspace"}</span>
            <input
              ref={nameRef}
              autoFocus={mode === "nova"}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={mode === "branch" ? "usa o nome do branch" : "ex.: login-com-google"}
              spellCheck={false}
            />
          </label>

          <div className="pd-field">
            <span className="pd-label">Abrir nele</span>
            <div className="pd-agents" role="radiogroup" aria-label="O que abre no workspace">
              {(
                [
                  ["claude", "Claude Code"],
                  ["codex", "Codex"],
                  ["shell", "Terminal"],
                ] as const
              ).map(([key, label]) => (
                <button key={key} type="button" role="radio" aria-checked={openKey === key} className="pd-agent" onClick={() => setOpenKey(key)}>
                  <KindIcon kind={key} size={14} /> {label}
                </button>
              ))}
              {usable.map((agent) => (
                <button key={agent.id} type="button" role="radio" aria-checked={openKey === agent.id} className="pd-agent" onClick={() => setOpenKey(agent.id)} title={agent.description}>
                  <AgentSprite agent={agent} client={client} size={16} /> {agent.name}
                </button>
              ))}
              <button type="button" role="radio" aria-checked={openKey === "nada"} className="pd-agent" onClick={() => setOpenKey("nada")}>
                Nada
              </button>
            </div>
          </div>

          {open && open.kind !== "shell" && (
            <label className="pd-field">
              <span className="pd-label">Pedido inicial (opcional)</span>
              <textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="O que o agente faz primeiro. Ex.: implemente o login com Google seguindo o padrão do projeto." />
            </label>
          )}

          <button type="button" className="pd-disclosure" aria-expanded={advanced} onClick={() => setAdvanced((v) => !v)}>
            <span className="chev" data-open={advanced ? "true" : undefined}>
              <Icon d={ICON.chevron} size={11} strokeWidth={2.2} />
            </span>
            Avançado
          </button>
          {advanced && (
            <div className="pd-advanced">
              <label className="check">
                <input type="checkbox" checked={copyEnv} onChange={(e) => setCopyEnv(e.target.checked)} /> copiar o .env do projeto
              </label>
              <span className="small pd-muted">
                {mode === "nova"
                  ? `Branch novo com o nome do workspace, em ~/orca/workspaces/${folder}/.`
                  : mode === "branch"
                    ? "Abre o branch numa pasta própria (o do remoto vira um branch local que o acompanha)."
                    : "Branch novo com o nome do workspace, a partir do commit escolhido."}
              </span>
            </div>
          )}
        </div>
        <footer className="pd-foot pd-foot-bar">
          <button type="button" role="switch" aria-checked={more} className="pd-switch" onClick={() => setMore((v) => !v)}>
            <span className="pd-switch-track" data-on={more ? "true" : undefined}>
              <span />
            </span>
            Criar mais
          </button>
          <button type="submit" className="btn primary" disabled={!canCreate}>
            {busy ? "Criando…" : "Criar workspace"} <span className="pd-kbd-inline">⌘↵</span>
          </button>
        </footer>
      </form>
    </div>
  );
}
