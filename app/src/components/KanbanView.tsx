import { useEffect, useMemo, useState } from "react";
import type { CoreClient } from "../lib/core";
import { renderInline } from "../lib/obsidian";
import type { BoardProject, KanbanTask, Stage, TaskState } from "../types";

export interface KanbanRequest {
  id: number;
  project?: string;
}

interface Props {
  client: CoreClient | null;
  tick: number;
  request: KanbanRequest | null;
  onOpenNote: (title: string) => void;
  onOpenProject: (project: BoardProject) => void;
  onRunTask: (project: BoardProject, task: KanbanTask) => void;
  onError: (message: string) => void;
}

const STAGES: { key: Stage; label: string; dot: string; hint: string }[] = [
  { key: "", label: "Sem estágio", dot: "var(--line2)", hint: "arraste para uma coluna; o estágio vai para a nota (estagio:)" },
  { key: "ideia", label: "Ideia", dot: "var(--fnt)", hint: "" },
  { key: "planejando", label: "Planejando", dot: "var(--wait)", hint: "" },
  { key: "construindo", label: "Construindo", dot: "var(--run)", hint: "" },
  { key: "em-producao", label: "Em produção", dot: "var(--acc)", hint: "" },
  { key: "pausado", label: "Pausado", dot: "var(--line2)", hint: "" },
];

const STATES: { key: TaskState; label: string; dot: string }[] = [
  { key: "pendente", label: "Pendente", dot: "var(--fnt)" },
  { key: "em-andamento", label: "Em andamento", dot: "var(--run)" },
  { key: "em-teste", label: "Em teste", dot: "var(--wait)" },
  { key: "concluida", label: "Concluído", dot: "var(--acc)" },
];

const DONE_SHOWN = 12;
const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** Uma coluna que aceita cartão arrastado. */
function Column(props: {
  label: string;
  dot: string;
  count: number;
  hint?: string;
  onDrop: (id: string) => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const [over, setOver] = useState(false);
  return (
    <section
      className="kb-col"
      data-over={over ? "true" : undefined}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        setOver(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setOver(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        const id = event.dataTransfer.getData("text/x-metis-card");
        if (id) props.onDrop(id);
      }}
      aria-label={props.label}
    >
      <header className="kb-col-head">
        <span className="kb-dot" style={{ background: props.dot }} />
        <span>{props.label}</span>
        <span className="kb-count mono">{props.count}</span>
      </header>
      {props.hint && <p className="kb-hint small">{props.hint}</p>}
      <div className="kb-cards">{props.children}</div>
      {props.footer}
    </section>
  );
}

export function KanbanView({ client, tick, request, onOpenNote, onOpenProject, onRunTask, onError }: Props) {
  const [projects, setProjects] = useState<BoardProject[]>([]);
  const [mode, setMode] = useState<"projects" | "tasks">("projects");
  const [current, setCurrent] = useState<string>("");
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [allDone, setAllDone] = useState(false);
  const [draft, setDraft] = useState("");
  const [loaded, setLoaded] = useState(false);

  const project = projects.find((p) => p.name === current) ?? null;

  useEffect(() => {
    if (!client) return;
    void client
      .boardProjects()
      .then((list) => {
        setProjects(list);
        setLoaded(true);
      })
      .catch((cause) => onError(message(cause)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, tick]);

  useEffect(() => {
    if (!client || mode !== "tasks" || !current) return;
    void client
      .tasks(current)
      .then(setTasks)
      .catch((cause) => onError(message(cause)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, mode, current, tick]);

  useEffect(() => {
    if (!request) return;
    if (request.project) {
      setCurrent(request.project);
      setMode("tasks");
      setAllDone(false);
    } else {
      setMode("projects");
    }
  }, [request?.id]);

  const showTasks = (name: string) => {
    setCurrent(name);
    setMode("tasks");
    setAllDone(false);
  };

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

  const moveTask = async (id: string, state: TaskState) => {
    const before = tasks;
    if (!client || !current || before.find((t) => t.id === id)?.state === state) return;
    setTasks((all) => all.map((t) => (t.id === id ? { ...t, state } : t)));
    try {
      await client.moveTask(current, id, state);
      setTasks(await client.tasks(current));
    } catch (cause) {
      setTasks(before);
      onError(message(cause));
    }
  };

  const addTask = async () => {
    const text = draft.trim();
    if (!text || !client || !current) return;
    try {
      await client.addTask(current, text);
      setDraft("");
      setTasks(await client.tasks(current));
    } catch (cause) {
      onError(message(cause));
    }
  };

  const byStage = useMemo(() => {
    const groups = new Map<Stage, BoardProject[]>(STAGES.map((s) => [s.key, []]));
    for (const p of projects) groups.get(p.stage)?.push(p);
    for (const list of groups.values()) list.sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
    return groups;
  }, [projects]);

  const open = projects.reduce((n, p) => n + p.tasks.pendente + p.tasks["em-andamento"] + p.tasks["em-teste"], 0);

  // [[links]] dentro dos cartões abrem a nota no Brain, sem disparar o clique do cartão.
  const onLinkCapture = (event: React.MouseEvent) => {
    const link = (event.target as HTMLElement).closest("a");
    if (!link) return;
    event.preventDefault();
    event.stopPropagation();
    if (link.classList.contains("wikilink") && link.dataset.note) onOpenNote(link.dataset.note);
  };

  return (
    <div className="kanban-screen">
      <header className="kb-bar">
        <div className="segmented" role="tablist" aria-label="Quadro">
          <button type="button" role="tab" aria-selected={mode === "projects"} onClick={() => setMode("projects")}>
            Projetos
          </button>
          <button type="button" role="tab" aria-selected={mode === "tasks"} onClick={() => (current ? setMode("tasks") : projects[0] && showTasks(projects[0].name))}>
            Tarefas
          </button>
        </div>
        {mode === "tasks" && (
          <select value={current} onChange={(event) => showTasks(event.target.value)} aria-label="Projeto">
            {projects.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        {mode === "tasks" && project && (
          <>
            <button type="button" className="btn" onClick={() => onOpenNote(project.name)}>
              Nota no Brain
            </button>
            {project.directory && (
              <button type="button" className="btn" onClick={() => onOpenProject(project)} title={project.directory}>
                Abrir o repositório
              </button>
            )}
          </>
        )}
        <span className="kb-summary small mono">
          {mode === "projects"
            ? `${projects.length} projetos · ${open} ações abertas`
            : `${tasks.filter((t) => t.state !== "concluida").length} abertas · ${tasks.filter((t) => t.state === "concluida").length} concluídas`}
        </span>
      </header>

      {mode === "projects" ? (
        <div className="kb-board" onClickCapture={onLinkCapture}>
          {STAGES.filter((s) => s.key !== "" || (byStage.get("")?.length ?? 0) > 0).map((stage) => {
            const list = byStage.get(stage.key) ?? [];
            return (
              <Column key={stage.key || "none"} label={stage.label} dot={stage.dot} count={list.length} hint={stage.hint} onDrop={(name) => void moveProject(name, stage.key)}>
                {list.map((p) => (
                  <article
                    key={p.name}
                    className="kb-card"
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.setData("text/x-metis-card", p.name);
                      event.dataTransfer.effectAllowed = "move";
                    }}
                    onClick={() => showTasks(p.name)}
                  >
                    <div className="kb-card-title">{p.name}</div>
                    <div className="kb-tags">
                      {p.area && <span className="kb-tag">{p.area}</span>}
                      {p.deadline && <span className="kb-tag mono">prazo {p.deadline}</span>}
                      {p.proposals > 0 && <span className="kb-tag warn">{p.proposals} {p.proposals > 1 ? "decisões" : "decisão"} em aberto</span>}
                    </div>
                    <div className="kb-meta small mono">
                      {p.tasks.pendente + p.tasks["em-andamento"] + p.tasks["em-teste"]} abertas
                      {p.tasks["em-andamento"] ? ` · ${p.tasks["em-andamento"]} em andamento` : ""}
                      {p.records.decisoes ? ` · ${p.records.decisoes} decisões` : ""}
                    </div>
                    {p.next[0] && <div className="kb-next small" dangerouslySetInnerHTML={{ __html: renderInline(p.next[0]) }} />}
                    <div className="kb-card-actions">
                      <button
                        type="button"
                        className="link-btn"
                        onClick={(event) => {
                          event.stopPropagation();
                          onOpenNote(p.name);
                        }}
                      >
                        nota ›
                      </button>
                      {p.directory && (
                        <button
                          type="button"
                          className="link-btn"
                          title={p.directory}
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenProject(p);
                          }}
                        >
                          abrir ›
                        </button>
                      )}
                    </div>
                  </article>
                ))}
              </Column>
            );
          })}
          {loaded && !projects.length && (
            <p className="kb-empty small">Nenhum projeto em 01-PROJETOS do Brain. Cada pasta com a nota do projeto vira um cartão.</p>
          )}
        </div>
      ) : (
        <div className="kb-board" onClickCapture={onLinkCapture}>
          {STATES.map((state) => {
            const list = tasks.filter((t) => t.state === state.key);
            const done = state.key === "concluida";
            const shown = done && !allDone ? list.slice(-DONE_SHOWN).reverse() : done ? [...list].reverse() : list;
            return (
              <Column
                key={state.key}
                label={state.label}
                dot={state.dot}
                count={list.length}
                onDrop={(id) => void moveTask(id, state.key)}
                footer={
                  state.key === "pendente" ? (
                    <form
                      className="kb-add"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void addTask();
                      }}
                    >
                      <input value={draft} placeholder="+ Adicionar tarefa" onChange={(event) => setDraft(event.target.value)} aria-label="Nova tarefa" />
                    </form>
                  ) : done && list.length > DONE_SHOWN ? (
                    <button type="button" className="link-btn kb-more" onClick={() => setAllDone((v) => !v)}>
                      {allDone ? "mostrar só as recentes" : `ver todas (${list.length})`}
                    </button>
                  ) : null
                }
              >
                {shown.map((task) => (
                  <article
                    key={task.id}
                    className="kb-card kb-task"
                    data-cancelled={task.cancelled ? "true" : undefined}
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.setData("text/x-metis-card", task.id);
                      event.dataTransfer.effectAllowed = "move";
                    }}
                  >
                    <div className="kb-task-text" dangerouslySetInnerHTML={{ __html: renderInline(task.text) }} />
                    <div className="kb-meta small mono">
                      <span title="id para metis tarefa mover">{task.id}</span>
                      {task.subtasks_total > 0 && (
                        <span>
                          {" "}
                          · {task.subtasks_done}/{task.subtasks_total} subtarefas
                        </span>
                      )}
                      {task.done_on && <span> · {task.done_on}</span>}
                    </div>
                    {!done && project?.directory && (
                      <button type="button" className="link-btn kb-run" onClick={() => project && onRunTask(project, task)}>
                        ▶ Executar com agente
                      </button>
                    )}
                  </article>
                ))}
              </Column>
            );
          })}
        </div>
      )}
    </div>
  );
}
