import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { CoreClient } from "../lib/core";
import { renderInline } from "../lib/obsidian";
import type { BoardProject, GithubIssue, GithubPr, KanbanTask, Stage, TaskState } from "../types";

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
  /** v0.9.6: issues e PRs do GitHub do projeto, na coluna GitHub das tarefas. */
  onRunIssue: (project: BoardProject, issue: GithubIssue) => void;
  onOpenUrl: (url: string) => void;
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

/** Arrasto de cartão em andamento: qual cartão, onde está o ponteiro e a coluna embaixo dele. */
interface CardDrag {
  id: string;
  label: string;
  x: number;
  y: number;
  col: string | null;
}

const colAt = (x: number, y: number) => document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-col]")?.dataset.col ?? null;

/**
 * Arrastar cartão com o ponteiro (v0.9.4): o arrastar do HTML não chega na janela do Tauri
 * (o arrastar nativo de arquivos engole). O ponteiro é capturado já no clique, senão o
 * primeiro movimento rápido cai fora do cartão e o arrasto se perde; Esc cancela.
 */
function useCardDrag(onDrop: (col: string, id: string) => void) {
  const [drag, setDrag] = useState<CardDrag | null>(null);
  const moved = useRef(false);
  const live = useRef(onDrop);
  live.current = onDrop;

  const start = (event: ReactPointerEvent<HTMLElement>, id: string, label: string) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest("button, a, input, textarea, select")) return;
    event.preventDefault(); // sem seleção de texto ao arrastar; o clique continua chegando
    const el = event.currentTarget;
    const pointer = event.pointerId;
    const x0 = event.clientX;
    const y0 = event.clientY;
    let moving = false;
    moved.current = false;
    el.setPointerCapture(pointer);
    const move = (ev: PointerEvent) => {
      if (!moving && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 6) return;
      moving = true;
      moved.current = true;
      setDrag({ id, label, x: ev.clientX, y: ev.clientY, col: colAt(ev.clientX, ev.clientY) });
    };
    const stop = (ev: PointerEvent) => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", stop);
      el.removeEventListener("pointercancel", stop);
      window.removeEventListener("keydown", escape, true);
      if (!moving) return;
      setDrag(null);
      const col = ev.type === "pointerup" ? colAt(ev.clientX, ev.clientY) : null;
      if (col) live.current(col, id);
    };
    const escape = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape" || !moving) return;
      ev.preventDefault();
      ev.stopPropagation();
      moving = false;
      setDrag(null);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", stop);
    el.addEventListener("pointercancel", stop);
    window.addEventListener("keydown", escape, true);
  };

  /** O clique que encerra um arrasto não abre o cartão. */
  const consumeClick = () => {
    const was = moved.current;
    moved.current = false;
    return was;
  };

  return { drag, start, consumeClick };
}

/** Uma coluna que aceita cartão arrastado (`colKey` é o que o arrasto devolve ao soltar). */
function Column(props: {
  colKey: string;
  over: boolean;
  label: string;
  dot: string;
  count: number;
  hint?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <section className="kb-col" data-col={props.colKey} data-over={props.over ? "true" : undefined} aria-label={props.label}>
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

export function KanbanView({ client, tick, request, onOpenNote, onOpenProject, onRunTask, onRunIssue, onOpenUrl, onError }: Props) {
  const [projects, setProjects] = useState<BoardProject[]>([]);
  const [mode, setMode] = useState<"projects" | "tasks">("projects");
  const [current, setCurrent] = useState<string>("");
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [allDone, setAllDone] = useState(false);
  const [draft, setDraft] = useState("");
  const [loaded, setLoaded] = useState(false);

  const project = projects.find((p) => p.name === current) ?? null;
  // Projetos: a coluna "none" é Sem estágio. Tarefas: a coluna é o estado.
  const cardDrag = useCardDrag((col, id) => {
    if (mode === "projects") void moveProject(id, (col === "none" ? "" : col) as Stage);
    else if (col !== "github") void moveTask(id, col as TaskState);
  });
  // Issues e PRs abertos do repositório do projeto (pelo gh), ao lado das tarefas do Brain.
  const [github, setGithub] = useState<{ issues: GithubIssue[]; prs: GithubPr[] } | null>(null);
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
              <Column
                key={stage.key || "none"}
                colKey={stage.key || "none"}
                over={cardDrag.drag?.col === (stage.key || "none")}
                label={stage.label}
                dot={stage.dot}
                count={list.length}
                hint={stage.hint}
              >
                {list.map((p) => (
                  <article
                    key={p.name}
                    className="kb-card"
                    data-dragging={cardDrag.drag?.id === p.name ? "true" : undefined}
                    onPointerDown={(event) => cardDrag.start(event, p.name, p.name)}
                    onClick={() => !cardDrag.consumeClick() && showTasks(p.name)}
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
                colKey={state.key}
                over={cardDrag.drag?.col === state.key}
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
                    data-dragging={cardDrag.drag?.id === task.id ? "true" : undefined}
                    onPointerDown={(event) => cardDrag.start(event, task.id, task.text.replace(/[*_`[\]]/g, "").slice(0, 70))}
                    onClick={() => cardDrag.consumeClick()}
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
          {github && project && (
            <Column
              colKey="github"
              over={false}
              label="GitHub"
              dot="var(--fnt)"
              count={github.issues.length + github.prs.length}
              hint="issues e PRs abertos do repositório"
            >
              {github.issues.map((issue) => (
                <article key={`i-${issue.numero}`} className="kb-card kb-task kb-gh">
                  <div className="kb-task-text">
                    <span className="mono kb-gh-num">#{issue.numero}</span> {issue.titulo}
                  </div>
                  {issue.rotulos.length > 0 && (
                    <div className="kb-tags">
                      {issue.rotulos.slice(0, 4).map((label) => (
                        <span key={label} className="kb-tag">
                          {label}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="kb-card-actions">
                    <button type="button" className="link-btn" onClick={() => onOpenUrl(issue.url)}>
                      abrir
                    </button>
                    <button type="button" className="link-btn kb-run" onClick={() => onRunIssue(project, issue)}>
                      ▶ Executar com agente
                    </button>
                  </div>
                </article>
              ))}
              {github.prs.map((pr) => (
                <article key={`p-${pr.numero}`} className="kb-card kb-task kb-gh">
                  <div className="kb-task-text">
                    <span className="mono kb-gh-num">PR #{pr.numero}</span> {pr.titulo}
                  </div>
                  <div className="kb-meta small mono">
                    {pr.cabeca}
                    {pr.rascunho ? " · rascunho" : ""}
                    {pr.checks.falhou ? ` · ✗${pr.checks.falhou}` : pr.checks.pendente ? ` · ⏳${pr.checks.pendente}` : pr.checks.ok ? ` · ✓${pr.checks.ok}` : ""}
                  </div>
                  <div className="kb-card-actions">
                    <button type="button" className="link-btn" onClick={() => onOpenUrl(pr.url)}>
                      abrir
                    </button>
                  </div>
                </article>
              ))}
            </Column>
          )}
        </div>
      )}
      {cardDrag.drag && (
        <div className="kb-ghost" style={{ left: cardDrag.drag.x + 12, top: cardDrag.drag.y + 8 }} aria-hidden="true">
          {cardDrag.drag.label}
        </div>
      )}
    </div>
  );
}
