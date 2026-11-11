import { useCallback, useEffect, useMemo, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useCardDrag } from "../lib/cardDrag";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { renderInline } from "../lib/obsidian";
import type {
  Agent,
  AutoItem,
  AutoQueueView,
  AutoSettings,
  BoardProject,
  BoardTask,
  ClickupTask,
  ConnectorAccount,
  GithubIssue,
  GithubPr,
  KanbanTask,
  Stage,
  TaskState,
} from "../types";
import { AgentsBoard } from "./AgentsBoard";
import { ClickupColumn, LabelChip, ProjectChip } from "./KanbanParts";
import { RunSettingsPanel, saveRunSettings, useRunSettings } from "./KanbanRun";
import { dayMonth, priorityLabel, TaskModal } from "./TaskModal";
import "./kanban.css";

export interface KanbanRequest {
  id: number;
  project?: string;
  /** v0.9.8: abrir direto no painel de agentes. */
  agents?: boolean;
  /** v0.9.9: abrir nas tarefas (de todos os projetos, sem `project`). */
  tasks?: boolean;
}

interface Props {
  client: CoreClient | null;
  tick: number;
  request: KanbanRequest | null;
  onOpenNote: (title: string) => void;
  onOpenProject: (project: BoardProject) => void;
  /** v1.1: com `settings`, o agente, o modelo e o lugar escolhidos no cartão aberto. */
  onRunTask: (project: BoardProject, task: KanbanTask, settings?: AutoSettings) => void;
  /** v0.9.6: issues e PRs do GitHub do projeto, na coluna GitHub das tarefas. */
  onRunIssue: (project: BoardProject, issue: GithubIssue) => void;
  onOpenUrl: (url: string) => void;
  onError: (message: string) => void;
  /** v0.9.8: painel de agentes e o ClickUp do projeto. */
  onOpenSession: (id: string) => void;
  clickupAccounts: ConnectorAccount[];
  /** v0.9.9: a coluna Auto e os terminais. */
  auto: AutoQueueView | null;
  onAuto: (view: AutoQueueView) => void;
  agents: Agent[];
  onTerminals: () => void;
}

const STAGES: { key: Stage; label: string; color: string }[] = [
  { key: "", label: "Sem estágio", color: "var(--line2)" },
  { key: "ideia", label: "Ideia", color: "var(--fnt)" },
  { key: "planejando", label: "Planejando", color: "var(--wait)" },
  { key: "construindo", label: "Construindo", color: "var(--run)" },
  { key: "em-producao", label: "Em produção", color: "var(--acc)" },
  { key: "pausado", label: "Pausado", color: "var(--line2)" },
];

const DONE_SHOWN = 15;
const ALL = "__todos__";
const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));
const plain = (text: string) => text.replace(/\[\[([^\]|]+)\|?([^\]]*)\]\]/g, (_, a, b) => b || a).replace(/[*_`]/g, "");

// --- pedaços ----------------------------------------------------------------------------

function Column(props: {
  colKey: string;
  over: boolean;
  label: string;
  color: string;
  count: number;
  wide?: boolean;
  highlight?: boolean;
  head?: React.ReactNode;
  /** Linha logo abaixo do cabeçalho (o "N rodando · N na fila" do Auto). */
  sub?: React.ReactNode;
  empty?: React.ReactNode;
  /** Mostra os filhos mesmo com contagem zero (avisos do Auto). */
  always?: boolean;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  onCollapse?: () => void;
}) {
  const hasCards = props.count > 0 || !!props.always;
  return (
    <section
      className="kb2-col"
      data-col={props.colKey}
      data-over={props.over ? "true" : undefined}
      data-highlight={props.highlight ? "true" : undefined}
      aria-label={props.label}
      style={{ "--col": props.color } as React.CSSProperties}
    >
      <header className="kb2-col-head">
        <span className="kb2-col-bar" />
        <span className="kb2-col-title">{props.label}</span>
        <span className="kb2-col-count mono">{props.count}</span>
        <span className="grow" />
        {props.head}
        {props.onCollapse && (
          <button type="button" className="kb2-icon" onClick={props.onCollapse} aria-label={`Recolher ${props.label}`} title="Recolher">
            <Icon d={ICON.collapse} size={14} />
          </button>
        )}
      </header>
      {props.sub}
      <div className="kb2-cards">{hasCards ? props.children : props.empty}</div>
      {props.footer}
    </section>
  );
}

function CollapsedColumn({ label, color, count, colKey, over, onOpen }: { label: string; color: string; count: number; colKey: string; over: boolean; onOpen: () => void }) {
  return (
    <button
      type="button"
      className="kb2-col-collapsed"
      data-col={colKey}
      data-over={over ? "true" : undefined}
      style={{ "--col": color } as React.CSSProperties}
      onClick={onOpen}
      aria-label={`${label}: ${count}. Abrir`}
    >
      <span className="kb2-col-bar horizontal" />
      <span className="kb2-vertical">{label}</span>
      <span className="kb2-col-count mono">{count}</span>
    </button>
  );
}

function EmptyState({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="kb2-empty">
      <Icon d={icon} size={22} strokeWidth={1.4} />
      <span>{text}</span>
    </div>
  );
}

function TaskCard(props: {
  task: BoardTask;
  run: AutoItem | null;
  dragging: boolean;
  canRun: boolean;
  onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
  /** Devolve true quando o clique só encerrou um arrasto. */
  onClick: () => boolean;
  /** v1.1: abre o cartão inteiro (modal). */
  onOpen: () => void;
  onAuto: () => void;
  onRun: () => void;
  onNote: () => void;
  onOpenSession: (id: string) => void;
  onLabels: (labels: string[]) => Promise<void>;
  onAddSubtask: (text: string) => Promise<void>;
  onToggleSubtask: (index: number, done: boolean) => Promise<void>;
  onLabelClick: (label: string) => void;
  /** v1.1.4: pede para excluir (a tela confirma antes). */
  onDelete: () => void;
}) {
  const { task, run } = props;
  const running = run?.status === "rodando";
  const [open, setOpen] = useState(false);
  const [editingLabels, setEditingLabels] = useState<string | null>(null);
  const [subtask, setSubtask] = useState("");
  const labels = task.rotulos ?? [];
  const text = task.texto ?? task.text;
  const done = task.state === "concluida";

  const saveLabels = async () => {
    if (editingLabels === null) return;
    const next = editingLabels
      .split(/[,\s]+/)
      .map((l) => l.replace(/^#/, "").trim().toLowerCase())
      .filter(Boolean);
    setEditingLabels(null);
    await props.onLabels([...new Set(next)]);
  };

  return (
    <article
      className="kb2-card"
      data-done={done ? "true" : undefined}
      data-cancelled={task.cancelled ? "true" : undefined}
      data-dragging={props.dragging ? "true" : undefined}
      data-open={open ? "true" : undefined}
      onPointerDown={props.onPointerDown}
      onDragStart={(event) => event.preventDefault()}
      onClick={(event) => {
        if (props.onClick()) return; // o clique só encerrou um arrasto
        // Botões, links, rótulos, caixas e campos do próprio cartão fazem a coisa deles.
        if ((event.target as HTMLElement).closest("button, a, input, textarea, select, label, form")) return;
        props.onOpen();
      }}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter") props.onOpen();
        else if ((event.key === "Backspace" || event.key === "Delete") && !running && !event.metaKey && !event.ctrlKey && !event.altKey) {
          event.preventDefault();
          props.onDelete();
        }
      }}
      tabIndex={0}
      aria-label={`${plain(text)}. Enter abre o cartão, ⌫ exclui`}
    >
      <div className="kb2-card-top">
        <ProjectChip name={task.projeto} />
        <span className="kb2-num mono">#{task.n}</span>
      </div>
      <div className="kb2-title" dangerouslySetInnerHTML={{ __html: renderInline(text) }} />
      {!!(task.prioridade || task.entrega || task.descricao || task.anexos || task.comentarios) && (
        <div className="kb2-meta">
          {task.prioridade && (
            <span className="kb2-prio" data-prio={task.prioridade} title={`Prioridade ${priorityLabel(task.prioridade).toLowerCase()}`}>
              <Icon d={ICON.flag} size={11} strokeWidth={2} />
              {priorityLabel(task.prioridade)}
            </span>
          )}
          {task.entrega && (
            <span className="kb2-due mono" data-late={!done && task.entrega < new Date().toISOString().slice(0, 10) ? "true" : undefined} title={`Entrega ${task.entrega.split("-").reverse().join("/")}`}>
              <Icon d={ICON.calendar} size={11} />
              {dayMonth(task.entrega)}
            </span>
          )}
          {task.descricao && (
            <span className="kb2-meta-icon" title="Tem descrição">
              <Icon d={ICON.lines} size={12} />
            </span>
          )}
          {!!task.anexos && (
            <span className="kb2-meta-icon mono" title={`${task.anexos} anexo(s)`}>
              <Icon d={ICON.clip} size={12} />
              {task.anexos}
            </span>
          )}
          {!!task.comentarios && (
            <span className="kb2-meta-icon mono" title={`${task.comentarios} comentário(s)`}>
              <Icon d={ICON.note} size={11} />
              {task.comentarios}
            </span>
          )}
        </div>
      )}
      {(labels.length > 0 || task.subtasks_total > 0 || run) && editingLabels === null && (
        <div className="kb2-tags">
          {run && (
            <span className="kb2-auto-chip" data-status={run.status} title={run.erro || undefined}>
              <Icon d={ICON.bolt} size={11} strokeWidth={2} />
              {run.status === "rodando" ? "auto · rodando" : run.status === "feito" ? "auto · pronto para revisar" : run.status === "erro" ? "auto · erro" : "auto"}
            </span>
          )}
          {labels.map((label) => (
            <LabelChip key={label} label={label} onClick={() => props.onLabelClick(label)} />
          ))}
          {task.subtasks_total > 0 && (
            <button type="button" className="kb2-subcount mono" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
              {task.subtasks_done}/{task.subtasks_total}
            </button>
          )}
        </div>
      )}
      {editingLabels !== null && (
        <form
          className="kb2-inline"
          onSubmit={(event) => {
            event.preventDefault();
            void saveLabels();
          }}
        >
          <input
            autoFocus
            value={editingLabels}
            onChange={(event) => setEditingLabels(event.target.value)}
            onKeyDown={(event) => event.key === "Escape" && setEditingLabels(null)}
            onBlur={() => void saveLabels()}
            placeholder="rótulos separados por espaço (ex.: bug front)"
            aria-label="Rótulos"
          />
        </form>
      )}
      {open && (
        <ul className="kb2-subtasks">
          {(task.subtarefas ?? []).map((item) => (
            <li key={item.indice}>
              <label>
                <input type="checkbox" checked={item.feita} onChange={(event) => void props.onToggleSubtask(item.indice, event.target.checked)} />
                <span dangerouslySetInnerHTML={{ __html: renderInline(item.texto) }} />
              </label>
            </li>
          ))}
          <li>
            <form
              className="kb2-inline"
              onSubmit={(event) => {
                event.preventDefault();
                const value = subtask.trim();
                if (!value) return;
                setSubtask("");
                void props.onAddSubtask(value);
              }}
            >
              <input value={subtask} onChange={(event) => setSubtask(event.target.value)} placeholder="+ subtarefa" aria-label="Nova subtarefa" />
            </form>
          </li>
        </ul>
      )}
      <div className="kb2-card-foot">
        <span className="kb2-foot-meta mono">{task.done_on || (run?.sessao && run.status !== "fila" ? "" : task.id.split("-")[0])}</span>
        {run?.sessao && (
          <button type="button" className="kb2-link" onClick={() => props.onOpenSession(run.sessao)}>
            ver terminal
          </button>
        )}
        <span className="grow" />
        {!done && (
          <>
            <button type="button" className="kb2-icon" onClick={props.onAuto} disabled={!props.canRun} title={props.canRun ? "Rodar sozinha (coluna Auto)" : "O projeto não tem diretorio: na nota"} aria-label="Rodar sozinha">
              <Icon d={ICON.bolt} size={14} />
            </button>
            <button type="button" className="kb2-icon" onClick={props.onRun} disabled={!props.canRun} title={props.canRun ? "Executar agora com o Claude (o pedido vai para a barra)" : "O projeto não tem diretorio: na nota"} aria-label="Executar agora">
              <Icon d={ICON.send} size={14} />
            </button>
          </>
        )}
        <button type="button" className="kb2-icon" onClick={() => setEditingLabels(labels.join(" "))} title="Rótulos" aria-label="Rótulos">
          <Icon d={ICON.edit} size={13} />
        </button>
        {task.subtasks_total === 0 && (
          <button type="button" className="kb2-icon" onClick={() => setOpen((v) => !v)} title="Subtarefas" aria-label="Subtarefas">
            <Icon d={ICON.check} size={13} />
          </button>
        )}
        <button type="button" className="kb2-icon" onClick={props.onNote} title="Abrir a nota do projeto" aria-label="Abrir a nota">
          <Icon d={ICON.note} size={13} />
        </button>
        <button
          type="button"
          className="kb2-icon kb2-trash"
          onClick={props.onDelete}
          disabled={running}
          title={running ? "Rodando no Auto: feche o terminal dela antes de excluir" : "Excluir a tarefa (⌫ com o cartão em foco)"}
          aria-label="Excluir a tarefa"
        >
          <Icon d={ICON.trash} size={13} />
        </button>
      </div>
    </article>
  );
}

const listPt = (items: string[]) => (items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} e ${items[items.length - 1]}`);

/** v1.1.4: a confirmação de excluir, com o que vai junto (nada disso volta). */
function DeleteDialog(props: { task: BoardTask; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  const { task } = props;
  const cancel = props.onCancel;
  // Esc fecha só a confirmação: na captura, antes do Esc do cartão aberto (que desiste com defaultPrevented).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      cancel();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [cancel]);
  const subs = task.subtasks_total;
  const comments = task.comentarios ?? 0;
  const files = task.anexos ?? 0;
  const inNote = [task.descricao ? "a descrição" : "", subs ? `o checklist (${subs} ${subs === 1 ? "item" : "itens"})` : ""].filter(Boolean);
  const inCore = [
    "a atividade",
    comments ? (comments === 1 ? "o comentário" : `os ${comments} comentários`) : "",
    files ? (files === 1 ? "o anexo" : `os ${files} anexos`) : "",
  ].filter(Boolean);
  const core = listPt(inCore);
  return (
    <div className="kb2-modal-back kb2-over" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && !props.busy && cancel()}>
      <form
        className="kb2-modal kb2-modal-danger"
        role="alertdialog"
        aria-label="Excluir a tarefa"
        onSubmit={(event) => {
          event.preventDefault();
          if (!props.busy) props.onConfirm();
        }}
      >
        <div className="kb2-modal-title">
          <Icon d={ICON.trash} size={16} />
          Excluir a tarefa?
        </div>
        <div className="kb2-modal-task">
          <ProjectChip name={task.projeto} />
          <span className="mono kb2-num">#{task.n}</span>
          <span className="kb2-modal-task-text">{plain(task.texto ?? task.text)}</span>
        </div>
        <p className="kb2-modal-sub">
          Ela sai das Próximas ações da nota <b>{task.projeto}</b> no Brain{inNote.length ? `, junto com ${listPt(inNote)}` : ""}.{" "}
          {core.charAt(0).toUpperCase() + core.slice(1)} {inCore.length > 1 ? "somem" : "some"} da MÊTIS{files ? " (os arquivos guardados por ela também)" : ""}.{" "}
          <b>Não dá para desfazer.</b>
        </p>
        <div className="kb2-modal-actions">
          <button type="button" className="kb2-btn" onClick={cancel} disabled={props.busy}>
            Cancelar
          </button>
          <button type="submit" className="kb2-btn danger" autoFocus disabled={props.busy}>
            <Icon d={ICON.trash} size={13} /> {props.busy ? "Excluindo…" : "Excluir"}
          </button>
        </div>
      </form>
    </div>
  );
}

function AutoDialog(props: {
  task: BoardTask;
  agents: Agent[];
  client: CoreClient | null;
  onCancel: () => void;
  onQueue: (settings: AutoSettings) => void;
}) {
  const run = useRunSettings(props.agents);
  const [open, setOpen] = useState(true);
  return (
    <div className="kb2-modal-back" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && props.onCancel()}>
      <form
        className="kb2-modal"
        role="dialog"
        aria-label="Rodar sozinha"
        onSubmit={(event) => {
          event.preventDefault();
          saveRunSettings(run.settings);
          props.onQueue(run.settings);
        }}
        onKeyDown={(event) => event.key === "Escape" && props.onCancel()}
      >
        <div className="kb2-modal-title">
          <Icon d={ICON.bolt} size={16} />
          Rodar sozinha
        </div>
        <p className="kb2-modal-sub">Escolha como esta tarefa roda. O jeito escolhido fica guardado para as próximas.</p>
        <div className="kb2-modal-task">
          <ProjectChip name={props.task.projeto} />
          <span className="mono kb2-num">#{props.task.n}</span>
          <span className="kb2-modal-task-text">{plain(props.task.texto ?? props.task.text)}</span>
        </div>
        <div className="kb2-modal-box">
          <button type="button" className="kb2-modal-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            <Icon d={open ? ICON.down : ICON.chevron} size={12} /> Agente e lugar
          </button>
          {open && <RunSettingsPanel settings={run.settings} onChange={run.setSettings} agents={props.agents} client={props.client} />}
        </div>
        <div className="kb2-modal-actions">
          <button type="button" className="kb2-btn" onClick={props.onCancel}>
            Cancelar
          </button>
          <button type="submit" className="kb2-btn primary" autoFocus>
            Pôr na fila
          </button>
        </div>
      </form>
    </div>
  );
}

// --- a tela -----------------------------------------------------------------------------

export function KanbanView(props: Props) {
  const { client, tick, request, onOpenNote, onOpenProject, onRunTask, onRunIssue, onOpenUrl, onError, onOpenSession, clickupAccounts, auto, onAuto, agents } = props;
  const [projects, setProjects] = useState<BoardProject[]>([]);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [mode, setMode] = useState<"projects" | "tasks" | "agents">("tasks");
  const [current, setCurrent] = useState<string>(ALL);
  const [query, setQuery] = useState("");
  const [labelFilter, setLabelFilter] = useState<string[]>([]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ concluida: true });
  const [allDone, setAllDone] = useState(false);
  const [composer, setComposer] = useState<{ text: string; project: string } | null>(null);
  const [dialog, setDialog] = useState<BoardTask | null>(null);
  /** v1.1: o cartão aberto (projeto e id; o id muda quando o título muda). */
  const [opened, setOpened] = useState<{ projeto: string; id: string } | null>(null);
  /** v1.1.4: a tarefa esperando a confirmação de excluir. */
  const [deleting, setDeleting] = useState<BoardTask | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [reload, setReload] = useState(0);
  const [github, setGithub] = useState<{ issues: GithubIssue[]; prs: GithubPr[] } | null>(null);

  const project = current === ALL ? null : (projects.find((p) => p.name === current) ?? null);
  const projectOf = (name: string) => projects.find((p) => p.name === name) ?? null;

  useEffect(() => {
    if (!client) return;
    let alive = true;
    Promise.all([client.boardProjects(), client.allTasks()])
      .then(([list, all]) => {
        if (!alive) return;
        setProjects(list);
        setTasks(all);
        setLoaded(true);
      })
      .catch((cause) => onError(message(cause)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, tick, reload]);

  useEffect(() => {
    if (!client || auto) return;
    void client.autoQueue().then(onAuto).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  useEffect(() => {
    setGithub(null);
    if (!client || mode !== "tasks" || !project?.directory) return;
    let alive = true;
    client
      .githubItems(project.directory)
      .then((items) => alive && setGithub(items.issues.length || items.prs.length ? items : null))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [client, mode, project?.directory, tick]);

  useEffect(() => {
    if (!request) return;
    if (request.agents) setMode("agents");
    else if (request.project) {
      setCurrent(request.project);
      setMode("tasks");
    } else if (request.tasks) {
      setCurrent(ALL);
      setMode("tasks");
    } else setMode("projects");
  }, [request?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => setReload((n) => n + 1);

  const cardDrag = useCardDrag((col, id) => {
    if (mode === "projects") {
      void moveProject(id, (col === "none" ? "" : col) as Stage);
      return;
    }
    const task = tasks.find((t) => `${t.projeto}::${t.id}` === id);
    if (!task) return;
    if (col === "auto") {
      if (projectOf(task.projeto)?.directory) setDialog(task);
      else onError(`${task.projeto} não tem diretorio: na nota; a coluna Auto precisa da pasta do código.`);
    } else if (["pendente", "em-andamento", "em-teste", "concluida"].includes(col)) void moveTask(task, col as TaskState);
  });

  const moveProject = async (name: string, stage: Stage) => {
    const before = projects;
    if (before.find((p) => p.name === name)?.stage === stage || !client) return;
    setProjects((all) => all.map((p) => (p.name === name ? { ...p, stage } : p)));
    try {
      const saved = await client.setStage(name, stage);
      setProjects((all) => all.map((p) => (p.name === name ? saved : p)));
    } catch (cause) {
      setProjects(before);
      onError(message(cause));
    }
  };

  const moveTask = async (task: BoardTask, state: TaskState) => {
    if (!client || task.state === state) return;
    const before = tasks;
    setTasks((all) => all.map((t) => (t.projeto === task.projeto && t.id === task.id ? { ...t, state } : t)));
    try {
      await client.moveTask(task.projeto, task.id, state);
      setTasks(await client.allTasks());
    } catch (cause) {
      setTasks(before);
      onError(message(cause));
    }
  };

  const change = async (run: () => Promise<unknown>) => {
    if (!client) return;
    try {
      await run();
      setTasks(await client.allTasks());
    } catch (cause) {
      onError(message(cause));
    }
  };

  const queue = async (task: BoardTask, settings: AutoSettings) => {
    if (!client) return;
    setDialog(null);
    try {
      await client.autoEnqueue(task.projeto, task.id, settings);
      onAuto(await client.autoQueue());
    } catch (cause) {
      onError(message(cause));
    }
  };

  const closeDelete = useCallback(() => setDeleting(null), []);

  const removeTask = async (task: BoardTask) => {
    if (!client || deleteBusy) return;
    setDeleteBusy(true);
    try {
      const saved = await client.deleteTask(task.projeto, task.id);
      setDeleting(null);
      // O cartão aberto fecha se era ele; uma repetida aberta segue o id que herdou.
      setOpened((cur) => (!cur || cur.projeto !== task.projeto ? cur : cur.id === task.id ? null : saved.ids[cur.id] ? { ...cur, id: saved.ids[cur.id] } : cur));
      setTasks((all) => all.filter((t) => !(t.projeto === task.projeto && t.id === task.id)));
      refresh(); // as contas dos projetos e os números dos cartões
    } catch (cause) {
      onError(message(cause));
    } finally {
      setDeleteBusy(false);
    }
  };

  const addTask = async () => {
    if (!client || !composer) return;
    const text = composer.text.trim();
    const target = composer.project;
    if (!text || !target) return;
    try {
      await client.addTask(target, text);
      setComposer(null);
      setTasks(await client.allTasks());
    } catch (cause) {
      onError(message(cause));
    }
  };

  // Auto: o item mais novo de cada tarefa.
  const runOf = useMemo(() => {
    const map = new Map<string, AutoItem>();
    for (const item of auto?.itens ?? []) {
      const key = `${item.projeto}::${item.tarefa}`;
      const prev = map.get(key);
      if (!prev || item.criado > prev.criado) map.set(key, item);
    }
    return map;
  }, [auto]);

  const scoped = useMemo(() => {
    const q = query.trim().toLowerCase();
    return tasks.filter((t) => {
      if (current !== ALL && t.projeto !== current) return false;
      if (labelFilter.length && !labelFilter.every((l) => (t.rotulos ?? []).includes(l))) return false;
      if (q && !`${t.texto ?? t.text} ${t.projeto} ${(t.rotulos ?? []).join(" ")}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [tasks, current, labelFilter, query]);

  const queued = (t: BoardTask) => runOf.get(`${t.projeto}::${t.id}`)?.status === "fila";
  const byState = (state: TaskState) => scoped.filter((t) => t.state === state && !(state === "pendente" && queued(t)));
  const autoCards = scoped.filter(queued);
  const autoErrors = (auto?.itens ?? []).filter((i) => i.status === "erro" && (current === ALL || i.projeto === current)).slice(-3);

  const labels = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of tasks) if (current === ALL || t.projeto === current) for (const label of t.rotulos ?? []) counts.set(label, (counts.get(label) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([label]) => label);
  }, [tasks, current]);

  const openedTask = opened ? (tasks.find((t) => t.projeto === opened.projeto && t.id === opened.id) ?? null) : null;
  const knownLabels = useMemo(() => {
    const set = new Set<string>();
    for (const t of tasks) if (!opened || t.projeto === opened.projeto) for (const label of t.rotulos ?? []) set.add(label);
    return [...set].sort();
  }, [tasks, opened]);

  const toggleLabel = (label: string) => setLabelFilter((cur) => (cur.includes(label) ? cur.filter((l) => l !== label) : [...cur, label]));

  // [[links]] dentro dos cartões abrem a nota no Brain, sem disparar o clique do cartão.
  const onLinkCapture = (event: React.MouseEvent) => {
    const link = (event.target as HTMLElement).closest("a");
    if (!link) return;
    event.preventDefault();
    event.stopPropagation();
    if (link.classList.contains("wikilink") && link.dataset.note) onOpenNote(link.dataset.note);
    else if (link.getAttribute("href")?.startsWith("http")) onOpenUrl(link.getAttribute("href")!);
  };

  const card = (task: BoardTask) => {
    const key = `${task.projeto}::${task.id}`;
    const p = projectOf(task.projeto);
    return (
      <TaskCard
        key={key}
        task={task}
        run={runOf.get(key) ?? null}
        dragging={cardDrag.drag?.id === key}
        canRun={!!p?.directory}
        onPointerDown={(event) => cardDrag.start(event, key, plain(task.texto ?? task.text).slice(0, 70))}
        onClick={cardDrag.consumeClick}
        onOpen={() => setOpened({ projeto: task.projeto, id: task.id })}
        onAuto={() => setDialog(task)}
        onRun={() => p && onRunTask(p, task)}
        onNote={() => onOpenNote(task.projeto)}
        onOpenSession={onOpenSession}
        onLabels={(next) => change(() => client!.setTaskLabels(task.projeto, task.id, next))}
        onAddSubtask={(text) => change(() => client!.addSubtask(task.projeto, task.id, text))}
        onToggleSubtask={(index, value) => change(() => client!.setSubtask(task.projeto, task.id, index, value))}
        onLabelClick={toggleLabel}
        onDelete={() => setDeleting(task)}
      />
    );
  };

  const clickupTask = (task: ClickupTask): KanbanTask => ({
    id: `clickup-${task.id}`,
    text: `${task.nome} (tarefa do ClickUp: ${task.url})`,
    state: "pendente",
    line: 0,
    subtasks_done: 0,
    subtasks_total: 0,
    cancelled: false,
    done_on: "",
  });

  const open = projects.reduce((n, p) => n + p.tasks.pendente + p.tasks["em-andamento"] + p.tasks["em-teste"], 0);
  const done = byState("concluida");
  const doneShown = allDone ? [...done].reverse() : done.slice(-DONE_SHOWN).reverse();
  const toggle = (key: string) => setCollapsed((cur) => ({ ...cur, [key]: !cur[key] }));
  const over = (key: string) => cardDrag.drag?.col === key;

  const col = (key: TaskState, label: string, color: string, list: BoardTask[], empty: React.ReactNode, extra?: { footer?: React.ReactNode; head?: React.ReactNode }) =>
    collapsed[key] ? (
      <CollapsedColumn key={key} colKey={key} label={label} color={color} count={list.length} over={over(key)} onOpen={() => toggle(key)} />
    ) : (
      <Column key={key} colKey={key} over={over(key)} label={label} color={color} count={list.length} empty={empty} footer={extra?.footer} head={extra?.head} onCollapse={() => toggle(key)}>
        {list.map(card)}
      </Column>
    );

  return (
    <div className="kb2">
      <header className="kb2-bar">
        <span className="kb2-logo">
          <Icon d={ICON.kanban} size={16} />
          KANBAN
        </span>
        <div className="segmented kb2-modes" role="tablist" aria-label="Quadro">
          <button type="button" role="tab" aria-selected={mode === "tasks"} onClick={() => setMode("tasks")}>
            Tarefas
          </button>
          <button type="button" role="tab" aria-selected={mode === "projects"} onClick={() => setMode("projects")}>
            Projetos
          </button>
          <button type="button" role="tab" aria-selected={mode === "agents"} onClick={() => setMode("agents")}>
            Agentes
          </button>
        </div>
        {mode === "tasks" && (
          <>
            <label className="kb2-search">
              <Icon d={ICON.search} size={13} />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar tarefa…" aria-label="Buscar tarefa" />
            </label>
            <label className="kb2-project">
              <Icon d={ICON.folder} size={13} />
              <span>Projeto:</span>
              <select
                value={current}
                onChange={(e) => {
                  setCurrent(e.target.value);
                  setLabelFilter([]);
                }}
                aria-label="Projeto"
              >
                <option value={ALL}>Todos os projetos</option>
                {projects.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        <span className="grow" />
        {mode === "tasks" && project && (
          <>
            <button type="button" className="kb2-btn" onClick={() => onOpenNote(project.name)}>
              Nota no Brain
            </button>
            {project.directory && (
              <button type="button" className="kb2-btn" onClick={() => onOpenProject(project)} title={project.directory}>
                Abrir o repositório
              </button>
            )}
          </>
        )}
        {mode === "tasks" && (
          <button type="button" className="kb2-btn primary" onClick={() => setComposer({ text: "", project: project?.name ?? projects[0]?.name ?? "" })}>
            <Icon d={ICON.plus} size={13} strokeWidth={2.2} /> Nova tarefa
          </button>
        )}
        <button type="button" className="kb2-btn" onClick={refresh}>
          <Icon d={ICON.refresh} size={13} /> Atualizar
        </button>
        <button type="button" className="kb2-btn" onClick={props.onTerminals}>
          <Icon d={ICON.terminal} size={13} /> Terminais
        </button>
      </header>

      {mode === "tasks" && labels.length > 0 && (
        <div className="kb2-filter" aria-label="Filtrar por rótulo">
          <span className="small">rótulos</span>
          {labels.slice(0, 14).map((label) => (
            <LabelChip key={label} label={label} active={labelFilter.includes(label)} onClick={() => toggleLabel(label)} />
          ))}
          {labelFilter.length > 0 && (
            <button type="button" className="kb2-link" onClick={() => setLabelFilter([])}>
              limpar
            </button>
          )}
        </div>
      )}

      {mode === "agents" && client ? (
        <AgentsBoard client={client} onOpenSession={onOpenSession} onError={onError} />
      ) : mode === "projects" ? (
        <div className="kb2-board" onClickCapture={onLinkCapture}>
          {STAGES.filter((s) => s.key !== "" || projects.some((p) => !p.stage)).map((stage) => {
            const list = projects.filter((p) => p.stage === stage.key).sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
            const key = stage.key || "none";
            return (
              <Column
                key={key}
                colKey={key}
                over={over(key)}
                label={stage.label}
                color={stage.color}
                count={list.length}
                empty={<EmptyState icon={ICON.inbox} text={stage.key ? "Arraste um projeto para cá: o estágio vai para a nota (estagio:)." : ""} />}
              >
                {list.map((p) => (
                  <article
                    key={p.name}
                    className="kb2-card"
                    data-dragging={cardDrag.drag?.id === p.name ? "true" : undefined}
                    onPointerDown={(event) => cardDrag.start(event, p.name, p.name)}
                    onDragStart={(event) => event.preventDefault()}
                    onClick={() => {
                      if (cardDrag.consumeClick()) return;
                      setCurrent(p.name);
                      setMode("tasks");
                    }}
                  >
                    <div className="kb2-card-top">
                      <ProjectChip name={p.area || p.name} />
                      {p.deadline && <span className="kb2-num mono">prazo {p.deadline}</span>}
                    </div>
                    <div className="kb2-title">{p.name}</div>
                    {p.next[0] && <div className="kb2-desc" dangerouslySetInnerHTML={{ __html: renderInline(p.next[0]) }} />}
                    <div className="kb2-card-foot">
                      <span className="kb2-foot-meta mono">
                        {p.tasks.pendente + p.tasks["em-andamento"] + p.tasks["em-teste"]} abertas
                        {p.tasks["em-andamento"] ? ` · ${p.tasks["em-andamento"]} andando` : ""}
                        {p.proposals ? ` · ${p.proposals} em aberto` : ""}
                      </span>
                      <span className="grow" />
                      <button type="button" className="kb2-icon" title="Abrir a nota" aria-label="Abrir a nota" onClick={() => onOpenNote(p.name)}>
                        <Icon d={ICON.note} size={13} />
                      </button>
                      {p.directory && (
                        <button type="button" className="kb2-icon" title={`Abrir o repositório (${p.directory})`} aria-label="Abrir o repositório" onClick={() => onOpenProject(p)}>
                          <Icon d={ICON.folder} size={13} />
                        </button>
                      )}
                    </div>
                  </article>
                ))}
              </Column>
            );
          })}
          {loaded && !projects.length && <p className="kb2-note">Nenhum projeto em 01-PROJETOS do Brain. Cada pasta com a nota do projeto vira um cartão.</p>}
        </div>
      ) : (
        <div className="kb2-board" onClickCapture={onLinkCapture}>
          {col("pendente", "Pendente", "var(--kb-yellow)", byState("pendente"), <EmptyState icon={ICON.inbox} text="Nada pendente. + Nova tarefa escreve nas Próximas ações do projeto." />, {
            footer: composer ? (
              <form
                className="kb2-composer"
                onSubmit={(event) => {
                  event.preventDefault();
                  void addTask();
                }}
              >
                <textarea
                  autoFocus
                  rows={3}
                  value={composer.text}
                  onChange={(e) => setComposer({ ...composer, text: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setComposer(null);
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void addTask();
                    }
                  }}
                  placeholder="O que precisa ser feito? (#rótulo vira rótulo)"
                  aria-label="Nova tarefa"
                />
                <div className="kb2-composer-row">
                  <select value={composer.project} onChange={(e) => setComposer({ ...composer, project: e.target.value })} aria-label="Projeto da tarefa">
                    {projects.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="kb2-btn" onClick={() => setComposer(null)}>
                    Cancelar
                  </button>
                  <button type="submit" className="kb2-btn primary" disabled={!composer.text.trim()}>
                    Adicionar
                  </button>
                </div>
              </form>
            ) : (
              <button type="button" className="kb2-add" onClick={() => setComposer({ text: "", project: project?.name ?? projects[0]?.name ?? "" })}>
                + Nova tarefa
              </button>
            ),
          })}

          <Column
            colKey="auto"
            over={over("auto")}
            highlight
            label="Auto"
            color="var(--acc)"
            count={autoCards.length}
            head={
              <select
                className="kb2-limit mono"
                value={auto?.limite ?? 1}
                aria-label="Quantas rodam ao mesmo tempo"
                title="Quantas tarefas da fila rodam ao mesmo tempo"
                onChange={(e) => client && void client.autoLimit(Number(e.target.value)).then(onAuto).catch((cause) => onError(message(cause)))}
              >
                {[1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n} por vez
                  </option>
                ))}
              </select>
            }
            always={autoErrors.length > 0}
            sub={
              <div className="kb2-auto-status mono">
                <span className="kb2-live" data-on={auto?.rodando ? "true" : undefined} />
                {auto?.rodando ?? 0} rodando · {auto?.na_fila ?? 0} na fila
              </div>
            }
            empty={<EmptyState icon={ICON.bolt} text="Arraste uma tarefa para cá ou use o ⚡ dela. Ela começa sozinha, numa worktree, e vai para Em teste quando o agente terminar." />}
          >
            {autoCards.map((task) => {
              const item = runOf.get(`${task.projeto}::${task.id}`)!;
              return (
                <article
                  key={item.id}
                  className="kb2-card kb2-queued"
                  tabIndex={0}
                  onClick={(event) => !(event.target as HTMLElement).closest("button, a") && setOpened({ projeto: task.projeto, id: task.id })}
                  onKeyDown={(event) => event.key === "Enter" && event.target === event.currentTarget && setOpened({ projeto: task.projeto, id: task.id })}
                >
                  <div className="kb2-card-top">
                    <ProjectChip name={task.projeto} />
                    <span className="kb2-num mono">#{task.n}</span>
                  </div>
                  <div className="kb2-title" dangerouslySetInnerHTML={{ __html: renderInline(task.texto ?? task.text) }} />
                  <div className="kb2-card-foot">
                    <span className="kb2-foot-meta mono">
                      na fila · {item.agente ? (agents.find((a) => a.id === item.agente)?.name ?? item.agente) : item.cli}
                      {item.modelo ? ` · ${item.modelo}` : ""} · {item.onde === "worktree" ? "worktree" : "pasta"}
                    </span>
                    <span className="grow" />
                    <button
                      type="button"
                      className="kb2-icon"
                      title="Tirar da fila"
                      aria-label="Tirar da fila"
                      onClick={() => client && void client.autoCancel(item.id).then(() => client.autoQueue().then(onAuto)).catch((cause) => onError(message(cause)))}
                    >
                      <Icon d={ICON.close} size={13} />
                    </button>
                  </div>
                </article>
              );
            })}
            {autoErrors.map((item) => (
              <div key={item.id} className="kb2-auto-error">
                <b>Não rodou:</b> {plain(item.texto).slice(0, 80)}
                <span className="small">{item.erro}</span>
                {item.sessao && (
                  <button type="button" className="kb2-link" onClick={() => onOpenSession(item.sessao)}>
                    ver terminal
                  </button>
                )}
              </div>
            ))}
            {autoErrors.length > 0 && (
              <button type="button" className="kb2-link" onClick={() => client && void client.autoClear().then(() => client.autoQueue().then(onAuto))}>
                limpar os avisos
              </button>
            )}
          </Column>

          {col("em-andamento", "Em andamento", "var(--wait)", byState("em-andamento"), <EmptyState icon={ICON.inbox} text="Nenhuma tarefa em andamento." />)}
          {col("em-teste", "Em teste", "var(--run)", byState("em-teste"), <EmptyState icon={ICON.inbox} text="O trabalho pronto espera aqui a sua revisão." />)}
          {collapsed.concluida ? (
            <CollapsedColumn colKey="concluida" label="Concluído" color="var(--kb-green)" count={done.length} over={over("concluida")} onOpen={() => toggle("concluida")} />
          ) : (
            <Column
              colKey="concluida"
              over={over("concluida")}
              label="Concluído"
              color="var(--kb-green)"
              count={done.length}
              onCollapse={() => toggle("concluida")}
              empty={<EmptyState icon={ICON.check} text="Nada concluído ainda." />}
              footer={
                done.length > DONE_SHOWN ? (
                  <button type="button" className="kb2-add" onClick={() => setAllDone((v) => !v)}>
                    {allDone ? "só as recentes" : `ver todas (${done.length})`}
                  </button>
                ) : null
              }
            >
              {doneShown.map(card)}
            </Column>
          )}

          {client && project && clickupAccounts.length > 0 && (
            <ClickupColumn
              client={client}
              project={project}
              accounts={clickupAccounts}
              tick={tick}
              onOpenUrl={onOpenUrl}
              onRun={(task) => onRunTask(project, clickupTask(task))}
              onBring={(task) => void change(() => client.addTask(project.name, `${task.nome} ([ClickUp](${task.url}))`))}
              onError={onError}
            />
          )}
          {github && project && (
            <Column colKey="github" over={false} label="GitHub" color="var(--fnt)" count={github.issues.length + github.prs.length}>
              {github.issues.map((issue) => (
                <article key={`i-${issue.numero}`} className="kb2-card">
                  <div className="kb2-card-top">
                    <ProjectChip name={project.name} />
                    <span className="kb2-num mono">issue #{issue.numero}</span>
                  </div>
                  <div className="kb2-title">{issue.titulo}</div>
                  {issue.rotulos.length > 0 && (
                    <div className="kb2-tags">
                      {issue.rotulos.slice(0, 4).map((label) => (
                        <LabelChip key={label} label={label} />
                      ))}
                    </div>
                  )}
                  <div className="kb2-card-foot">
                    <button type="button" className="kb2-link" onClick={() => onOpenUrl(issue.url)}>
                      abrir
                    </button>
                    <span className="grow" />
                    <button type="button" className="kb2-icon" title="Executar com agente" aria-label="Executar com agente" onClick={() => onRunIssue(project, issue)}>
                      <Icon d={ICON.send} size={14} />
                    </button>
                  </div>
                </article>
              ))}
              {github.prs.map((pr) => (
                <article key={`p-${pr.numero}`} className="kb2-card">
                  <div className="kb2-card-top">
                    <ProjectChip name={project.name} />
                    <span className="kb2-num mono">PR #{pr.numero}</span>
                  </div>
                  <div className="kb2-title">{pr.titulo}</div>
                  <div className="kb2-card-foot">
                    <span className="kb2-foot-meta mono">
                      {pr.cabeca}
                      {pr.rascunho ? " · rascunho" : ""}
                      {pr.checks.falhou ? ` · ✗${pr.checks.falhou}` : pr.checks.pendente ? ` · ⏳${pr.checks.pendente}` : pr.checks.ok ? ` · ✓${pr.checks.ok}` : ""}
                    </span>
                    <span className="grow" />
                    <button type="button" className="kb2-link" onClick={() => onOpenUrl(pr.url)}>
                      abrir
                    </button>
                  </div>
                </article>
              ))}
            </Column>
          )}
        </div>
      )}

      <footer className="kb2-foot small mono">
        {mode === "projects"
          ? `${projects.length} projetos · ${open} ações abertas`
          : mode === "tasks"
            ? `${scoped.filter((t) => t.state !== "concluida").length} abertas · ${done.length} concluídas${current === ALL ? ` · ${projects.length} projetos` : ""}`
            : "os Claude e Codex abertos, pelo estado"}
      </footer>

      {cardDrag.drag && (
        <div className="kb2-ghost" style={{ left: cardDrag.drag.x + 12, top: cardDrag.drag.y + 8 }} aria-hidden="true">
          {cardDrag.drag.label}
        </div>
      )}
      {dialog && <AutoDialog task={dialog} agents={agents} client={client} onCancel={() => setDialog(null)} onQueue={(settings) => void queue(dialog, settings)} />}
      {client && openedTask && (
        <TaskModal
          client={client}
          task={openedTask}
          project={projectOf(openedTask.projeto)}
          tick={tick}
          run={runOf.get(`${openedTask.projeto}::${openedTask.id}`) ?? null}
          agents={agents}
          knownLabels={knownLabels}
          onClose={() => setOpened(null)}
          onRefresh={async (id) => {
            if (id) setOpened({ projeto: openedTask.projeto, id });
            setTasks(await client.allTasks());
          }}
          onMove={(state) => moveTask(openedTask, state)}
          onQueue={(settings) => queue(openedTask, settings)}
          onRunNow={(settings) => {
            const p = projectOf(openedTask.projeto);
            if (p) onRunTask(p, openedTask, settings);
          }}
          onOpenNote={onOpenNote}
          onOpenUrl={onOpenUrl}
          onOpenSession={onOpenSession}
          onError={onError}
          onDelete={() => setDeleting(openedTask)}
        />
      )}
      {deleting && <DeleteDialog task={deleting} busy={deleteBusy} onCancel={closeDelete} onConfirm={() => void removeTask(deleting)} />}
    </div>
  );
}
