import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { CoreClient } from "../lib/core";
import { renderInline, renderNote } from "../lib/obsidian";
import { ICON, Icon } from "../icons";
import type { Agent, AutoItem, AutoSettings, BoardProject, BoardTask, TaskAttachment, TaskEvent, TaskPatch, TaskPriority, TaskState } from "../types";
import { AgentSprite } from "./AgentSprite";
import { KindIcon } from "./KindIcon";
import { LabelChip, ProjectChip } from "./KanbanParts";
import { RunSettingsPanel, runSummary, saveRunSettings, useRunSettings } from "./KanbanRun";
import "./taskmodal.css";

/**
 * v1.1: o cartão aberto do kanban, no jeito do ClickUp que o Pedro mandou. À esquerda o que
 * mora na nota (título, status, prioridade, datas, rótulos, descrição, checklist) mais os anexos
 * e o agente que roda a tarefa (o mesmo painel do raio); à direita a atividade e os comentários.
 */

export const STATE_INFO: Record<TaskState, { label: string; color: string }> = {
  pendente: { label: "Pendente", color: "var(--kb-yellow)" },
  "em-andamento": { label: "Em andamento", color: "var(--wait)" },
  "em-teste": { label: "Em teste", color: "var(--run)" },
  concluida: { label: "Concluído", color: "var(--kb-green)" },
};
const ORDER: TaskState[] = ["pendente", "em-andamento", "em-teste", "concluida"];

export const PRIORITIES: [TaskPriority, string][] = [
  ["urgente", "Urgente"],
  ["alta", "Alta"],
  ["media", "Média"],
  ["", "Normal"],
  ["baixa", "Baixa"],
  ["minima", "Mínima"],
];
export const priorityLabel = (p: TaskPriority | undefined) => PRIORITIES.find(([key]) => key === (p ?? ""))?.[1] ?? "Normal";

const AUTO_STATUS: Record<AutoItem["status"], string> = {
  fila: "na fila do Auto",
  rodando: "rodando sozinha",
  feito: "pronta para revisar",
  erro: "não rodou",
  cancelado: "saiu da fila",
};

const two = (n: number) => String(n).padStart(2, "0");
export const dayMonth = (iso: string) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : "");
const when = (ts: number) => {
  const d = new Date(ts * 1000);
  return `${two(d.getDate())}/${two(d.getMonth() + 1)} às ${two(d.getHours())}:${two(d.getMinutes())}`;
};
const fullDate = (ts: number) => {
  const d = new Date(ts * 1000);
  return `${two(d.getDate())}/${two(d.getMonth() + 1)}/${d.getFullYear()}`;
};
const sizeText = (n: number) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);
const isImage = (name: string) => /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(name);
const person = (quem: string) => (quem === "Pedro" ? "Pedro (você)" : quem);
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
};
const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** Linha da atividade em palavras ("alterou a prioridade de Normal para Urgente"). */
function sentence(event: TaskEvent, agents: Agent[]): ReactNode {
  const d = event.dados as Record<string, string & string[] & boolean>;
  const b = (text: string) => <b>{text}</b>;
  switch (event.tipo) {
    case "criou":
      return <>criou esta tarefa em {b(STATE_INFO[d.estado as TaskState]?.label ?? "Pendente")}</>;
    case "moveu":
      return (
        <>
          moveu de {b(STATE_INFO[d.de as TaskState]?.label ?? d.de)} para {b(STATE_INFO[d.para as TaskState]?.label ?? d.para)}
        </>
      );
    case "rotulos": {
      const before: string[] = d.antes ?? [];
      const after: string[] = d.depois ?? [];
      const added = after.filter((l) => !before.includes(l));
      const removed = before.filter((l) => !after.includes(l));
      if (added.length && !removed.length) return <>pôs {added.length > 1 ? "as etiquetas" : "a etiqueta"} {b(added.map((l) => `#${l}`).join(" "))}</>;
      if (removed.length && !added.length) return <>tirou {removed.length > 1 ? "as etiquetas" : "a etiqueta"} {b(removed.map((l) => `#${l}`).join(" "))}</>;
      return <>trocou as etiquetas para {b(after.map((l) => `#${l}`).join(" ") || "nenhuma")}</>;
    }
    case "subtarefa": {
      const text = String(d.texto ?? "");
      if (d.acao === "criou") return <>pôs {b(text)} no checklist</>;
      if (d.acao === "marcou") return <>marcou {b(text)} como feito</>;
      if (d.acao === "desmarcou") return <>desmarcou {b(text)}</>;
      if (d.acao === "apagou") return <>tirou {b(text)} do checklist</>;
      return <>renomeou um item do checklist para {b(text)}</>;
    }
    case "titulo":
      return <>mudou o título para {b(String(d.para ?? ""))}</>;
    case "descricao":
      return !d.antes ? <>escreveu a descrição</> : !d.depois ? <>apagou a descrição</> : <>editou a descrição</>;
    case "prioridade":
      return (
        <>
          alterou a prioridade de {b(priorityLabel(d.de as TaskPriority))} para {b(priorityLabel(d.para as TaskPriority))}
        </>
      );
    case "data": {
      const field = d.campo === "inicio" ? "de início" : "de entrega";
      return d.para ? <>definiu a data {field} para {b(dayMonth(String(d.para)))}</> : <>tirou a data {field}</>;
    }
    case "anexo":
      return d.acao === "anexou" ? <>anexou {b(String(d.nome ?? ""))}</> : <>tirou o anexo {b(String(d.nome ?? ""))}</>;
    case "auto": {
      const status = d.status as unknown as AutoItem["status"];
      if (status === "fila") {
        const settings = { cli: d.cli, agente: d.agente, modelo: d.modelo, esforco: d.esforco, permissao: "auto", onde: d.onde } as unknown as AutoSettings;
        return <>pôs na fila do Auto ({runSummary(settings, agents)})</>;
      }
      if (status === "rodando") return <>começou a rodar sozinha</>;
      if (status === "feito") return <>terminou o turno; a tarefa foi para {b("Em teste")}</>;
      if (status === "erro") return <>não rodou: {String(d.erro || "erro")}</>;
      return <>tirou da fila do Auto</>;
    }
    default:
      return event.texto;
  }
}

interface Props {
  client: CoreClient;
  task: BoardTask;
  project: BoardProject | null;
  tick: number;
  run: AutoItem | null;
  agents: Agent[];
  /** Rótulos já usados no projeto (sugestões ao acrescentar). */
  knownLabels: string[];
  onClose: () => void;
  /** Recarrega o quadro; com `id`, o cartão aberto passa a ser esse (o título mudou). */
  onRefresh: (id?: string) => Promise<void>;
  onMove: (state: TaskState) => Promise<void>;
  onQueue: (settings: AutoSettings) => Promise<void>;
  onRunNow: (settings: AutoSettings) => void;
  onOpenNote: (title: string) => void;
  onOpenUrl: (url: string) => void;
  onOpenSession: (id: string) => void;
  onError: (message: string) => void;
  /** v1.1.4: pede para excluir a tarefa (o quadro confirma antes). */
  onDelete: () => void;
}

export function TaskModal(props: Props) {
  const { client, task, project, run, agents } = props;
  const text = task.texto ?? task.text;
  const labels = task.rotulos ?? [];
  const subs = task.subtarefas ?? [];
  const done = task.state === "concluida";
  const canRun = !!project?.directory;
  const live = !!run && (run.status === "fila" || run.status === "rodando");

  const [title, setTitle] = useState<string | null>(null);
  const [desc, setDesc] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState<string | null>(null);
  const [subDraft, setSubDraft] = useState("");
  const [subEdit, setSubEdit] = useState<{ index: number; text: string } | null>(null);
  const [activity, setActivity] = useState<{ eventos: TaskEvent[]; anexos: TaskAttachment[] } | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [runOpen, setRunOpen] = useState(false);
  const runSettings = useRunSettings(agents);
  const dialog = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const feedEnd = useRef<HTMLDivElement>(null);

  const id = task.id;
  const projeto = task.projeto;

  const loadActivity = async () => {
    try {
      setActivity(await client.taskActivity(projeto, id));
    } catch {
      // a tarefa mudou de id por fora (Obsidian): o quadro recarrega e o cartão fecha
    }
  };

  useEffect(() => {
    void loadActivity();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projeto, id, props.tick]);

  useEffect(() => {
    dialog.current?.focus();
  }, []);

  // Esc fecha, a menos que esteja escrevendo (aí o campo desiste da edição primeiro). Na janela
  // inteira: depois de salvar um campo, o foco volta para o body, fora do modal.
  const closeRef = useRef(props.onClose);
  closeRef.current = props.onClose;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const el = document.activeElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT")) return;
      closeRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // A atividade nova aparece embaixo, perto da caixa de comentário.
  useEffect(() => {
    feedEnd.current?.scrollIntoView({ block: "end" });
  }, [activity?.eventos.length]);

  // Arquivos soltos do Finder (a janela da MÊTIS entrega os caminhos, não os bytes).
  useEffect(() => {
    const onPaths = (event: Event) => {
      const paths = (event as CustomEvent<string[]>).detail ?? [];
      void attachPaths(paths);
    };
    window.addEventListener("metis:anexar-tarefa", onPaths);
    return () => window.removeEventListener("metis:anexar-tarefa", onPaths);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projeto, id]);

  const act = async (run: () => Promise<unknown>) => {
    try {
      await run();
      await props.onRefresh();
      await loadActivity();
    } catch (cause) {
      props.onError(message(cause));
    }
  };

  const edit = async (patch: TaskPatch) => {
    try {
      const saved = await client.editTask(projeto, id, patch);
      await props.onRefresh(saved.id !== id ? saved.id : undefined);
      if (saved.id === id) await loadActivity();
    } catch (cause) {
      props.onError(message(cause));
    }
  };

  const saveTitle = async () => {
    if (title === null) return;
    const next = title.trim();
    setTitle(null);
    if (next && next !== text) await edit({ titulo: next });
  };

  const saveDesc = async () => {
    if (desc === null) return;
    const next = desc;
    setDesc(null);
    if (next.trim() !== (task.descricao ?? "").trim()) await edit({ descricao: next });
  };

  const addLabels = async () => {
    if (labelDraft === null) return;
    const typed = labelDraft
      .split(/[,\s]+/)
      .map((l) => l.replace(/^#/, "").trim().toLowerCase())
      .filter(Boolean);
    setLabelDraft(null);
    if (!typed.length) return;
    await act(() => client.setTaskLabels(projeto, id, [...new Set([...labels, ...typed])]));
  };

  const attachFiles = async (files: File[]) => {
    if (!files.length) return;
    setUploading((n) => n + files.length);
    try {
      for (const file of files) await client.attachToTask(projeto, id, file, file.name || "anexo");
      await props.onRefresh();
      await loadActivity();
    } catch (cause) {
      props.onError(message(cause));
    } finally {
      setUploading((n) => Math.max(0, n - files.length));
    }
  };

  const attachPaths = async (paths: string[]) => {
    if (!paths.length) return;
    setUploading((n) => n + paths.length);
    try {
      for (const path of paths) await client.attachPathToTask(projeto, id, path);
      await props.onRefresh();
      await loadActivity();
    } catch (cause) {
      props.onError(message(cause));
    } finally {
      setUploading((n) => Math.max(0, n - paths.length));
    }
  };

  const sendComment = async () => {
    const body = comment.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      await client.commentTask(projeto, id, body);
      setComment("");
      await loadActivity();
      await props.onRefresh();
    } catch (cause) {
      props.onError(message(cause));
    } finally {
      setSending(false);
    }
  };

  // [[links]] e endereços na descrição, no título e nos comentários.
  const onLinkCapture = (event: React.MouseEvent) => {
    const link = (event.target as HTMLElement).closest("a");
    if (!link) return;
    event.preventDefault();
    event.stopPropagation();
    if (link.classList.contains("wikilink") && link.dataset.note) props.onOpenNote(link.dataset.note);
    else if (link.getAttribute("href")?.startsWith("http")) props.onOpenUrl(link.getAttribute("href")!);
  };

  const events = activity?.eventos ?? [];
  const created = events.find((e) => e.tipo === "criou");
  const hiddenCount = useMemo(() => {
    if (expanded || events.length <= 8) return 0;
    return events.filter((e, i) => e.tipo !== "comentario" && i > 0 && i < events.length - 6).length;
  }, [events, expanded]);
  const visible = (e: TaskEvent, i: number) => expanded || events.length <= 8 || e.tipo === "comentario" || i === 0 || i >= events.length - 6;

  const nextState = ORDER[Math.min(ORDER.indexOf(task.state) + 1, ORDER.length - 1)];
  const overdue = !!task.entrega && !done && task.entrega < today();

  return (
    <div className="tm-back" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div
        ref={dialog}
        className="tm"
        role="dialog"
        aria-modal="true"
        aria-label={`Tarefa: ${text}`}
        tabIndex={-1}
        data-drop="tarefa"
        data-over={dragOver ? "true" : undefined}
        onPaste={(event) => {
          const files = Array.from(event.clipboardData.files);
          if (!files.length) return;
          event.preventDefault();
          void attachFiles(files);
        }}
        onDragOver={(event) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          event.stopPropagation();
          setDragOver(true);
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragOver(false);
        }}
        onDrop={(event) => {
          if (!event.dataTransfer.files.length) return;
          event.preventDefault();
          event.stopPropagation();
          setDragOver(false);
          void attachFiles(Array.from(event.dataTransfer.files));
        }}
        onClickCapture={onLinkCapture}
      >
        <header className="tm-head">
          <nav className="tm-crumbs" aria-label="Onde a tarefa está">
            <ProjectChip name={projeto} />
            <span className="tm-sep">/</span>
            <span className="tm-state-dot" style={{ "--st": STATE_INFO[task.state].color } as React.CSSProperties} />
            <span>{STATE_INFO[task.state].label}</span>
            <span className="tm-sep">/</span>
            <span className="mono tm-num">#{task.n}</span>
          </nav>
          <span className="grow" />
          <span className="tm-created small">
            {created ? `Criada em ${fullDate(created.ts)} por ${person(created.quem)}` : task.criada ? `Criada em ${task.criada.split("-").reverse().join("/")}` : ""}
          </span>
          <button type="button" className="kb2-icon tm-head-btn" onClick={() => props.onOpenNote(projeto)} title="Abrir a nota do projeto no Brain" aria-label="Abrir a nota do projeto">
            <Icon d={ICON.note} size={14} />
          </button>
          <button
            type="button"
            className="kb2-icon tm-head-btn kb2-trash"
            onClick={props.onDelete}
            disabled={run?.status === "rodando"}
            title={run?.status === "rodando" ? "Rodando no Auto: feche o terminal dela antes de excluir" : "Excluir a tarefa"}
            aria-label="Excluir a tarefa"
          >
            <Icon d={ICON.trash} size={14} />
          </button>
          <button type="button" className="kb2-icon tm-head-btn" onClick={props.onClose} title="Fechar (Esc)" aria-label="Fechar">
            <Icon d={ICON.close} size={14} />
          </button>
        </header>

        <div className="tm-body">
          <main className="tm-main">
            {title === null ? (
              <h2 className="tm-title" data-cancelled={task.cancelled ? "true" : undefined} tabIndex={0} title="Clique para editar" onClick={() => setTitle(text)} onKeyDown={(e) => e.key === "Enter" && setTitle(text)}>
                <span dangerouslySetInnerHTML={{ __html: renderInline(text) }} />
              </h2>
            ) : (
              <textarea
                className="tm-title-input"
                autoFocus
                rows={1}
                value={title}
                aria-label="Título da tarefa"
                onChange={(e) => setTitle(e.target.value)}
                onFocus={(e) => e.currentTarget.select()}
                onBlur={() => void saveTitle()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void saveTitle();
                  } else if (e.key === "Escape") {
                    e.stopPropagation();
                    setTitle(null);
                  }
                }}
              />
            )}

            <div className="tm-props">
              <div className="tm-prop">
                <span className="tm-prop-name">
                  <Icon d={ICON.status} size={14} /> Status
                </span>
                <div className="tm-prop-value">
                  <label className="tm-pill" style={{ "--st": STATE_INFO[task.state].color } as React.CSSProperties}>
                    <span className="tm-state-dot" />
                    <span>{STATE_INFO[task.state].label}</span>
                    <select value={task.state} onChange={(e) => void props.onMove(e.target.value as TaskState)} aria-label="Status">
                      {ORDER.map((s) => (
                        <option key={s} value={s}>
                          {STATE_INFO[s].label}
                        </option>
                      ))}
                    </select>
                    <Icon d={ICON.down} size={11} />
                  </label>
                  {!done && (
                    <button type="button" className="tm-square" onClick={() => void props.onMove(nextState)} title={`Passar para ${STATE_INFO[nextState].label}`} aria-label={`Passar para ${STATE_INFO[nextState].label}`}>
                      <Icon d={ICON.chevron} size={13} />
                    </button>
                  )}
                  <button
                    type="button"
                    className="tm-square"
                    data-on={done ? "true" : undefined}
                    onClick={() => void props.onMove(done ? "pendente" : "concluida")}
                    title={done ? "Reabrir (volta para Pendente)" : "Concluir"}
                    aria-label={done ? "Reabrir" : "Concluir"}
                  >
                    <Icon d={ICON.check} size={13} />
                  </button>
                </div>
              </div>

              <div className="tm-prop">
                <span className="tm-prop-name">
                  <Icon d={ICON.flag} size={14} /> Prioridade
                </span>
                <div className="tm-prop-value">
                  <label className="tm-pill tm-prio" data-prio={task.prioridade || "normal"}>
                    <Icon d={ICON.flag} size={12} />
                    <span>{priorityLabel(task.prioridade)}</span>
                    <select value={task.prioridade ?? ""} onChange={(e) => void edit({ prioridade: e.target.value as TaskPriority })} aria-label="Prioridade">
                      {PRIORITIES.filter(([key]) => key !== "minima" || task.prioridade === "minima").map(([key, label]) => (
                        <option key={key || "normal"} value={key}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <Icon d={ICON.down} size={11} />
                  </label>
                </div>
              </div>

              <div className="tm-prop">
                <span className="tm-prop-name">
                  <Icon d={ICON.calendar} size={14} /> Datas
                </span>
                <div className="tm-prop-value tm-dates">
                  <DateField label="Início" value={task.inicio ?? ""} onChange={(value) => void edit({ inicio: value })} />
                  <Icon d={ICON.arrowRight} size={12} />
                  <DateField label="Entrega" value={task.entrega ?? ""} late={overdue} onChange={(value) => void edit({ entrega: value })} />
                </div>
              </div>

              <div className="tm-prop">
                <span className="tm-prop-name">
                  <Icon d={ICON.folder} size={14} /> Projeto
                </span>
                <div className="tm-prop-value">
                  <ProjectChip name={projeto} />
                  {project?.directory ? (
                    <span className="tm-dir mono small" title={project.directory}>
                      {project.directory.replace(/^\/Users\/[^/]+/, "~")}
                    </span>
                  ) : (
                    <span className="small tm-muted">sem diretorio: na nota</span>
                  )}
                </div>
              </div>

              <div className="tm-prop tm-prop-wide">
                <span className="tm-prop-name">
                  <Icon d={ICON.tag} size={14} /> Etiquetas
                </span>
                <div className="tm-prop-value tm-labels">
                  {labels.map((label) => (
                    <span key={label} className="tm-label">
                      <LabelChip label={label} />
                      <button type="button" className="tm-x" onClick={() => void act(() => client.setTaskLabels(projeto, id, labels.filter((l) => l !== label)))} aria-label={`Tirar #${label}`} title="Tirar">
                        <Icon d={ICON.close} size={10} strokeWidth={2.2} />
                      </button>
                    </span>
                  ))}
                  {labelDraft === null ? (
                    <button type="button" className="tm-ghost" onClick={() => setLabelDraft("")}>
                      Adicionar
                    </button>
                  ) : (
                    <form
                      className="tm-inline"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void addLabels();
                      }}
                    >
                      <input
                        autoFocus
                        list="tm-known-labels"
                        value={labelDraft}
                        onChange={(e) => setLabelDraft(e.target.value)}
                        onBlur={() => void addLabels()}
                        onKeyDown={(e) => {
                          if (e.key === "Escape") {
                            e.stopPropagation();
                            setLabelDraft(null);
                          }
                        }}
                        placeholder="rótulo e Enter"
                        aria-label="Novo rótulo"
                      />
                      <datalist id="tm-known-labels">
                        {props.knownLabels
                          .filter((l) => !labels.includes(l))
                          .map((l) => (
                            <option key={l} value={l} />
                          ))}
                      </datalist>
                    </form>
                  )}
                </div>
              </div>
            </div>

            <section className="tm-agent" aria-label="Agente">
              <div className="tm-agent-row">
                <span className="tm-prop-name">
                  <Icon d={ICON.agents} size={14} /> Agente
                </span>
                <button type="button" className="tm-agent-who" onClick={() => setRunOpen((v) => !v)} aria-expanded={runOpen} title="Escolher agente, modelo e onde roda">
                  {runSettings.agent ? (
                    <AgentSprite agent={runSettings.agent} client={client} size={16} />
                  ) : (
                    <span className="kb2-glyph" data-cli={runSettings.cli}>
                      <KindIcon kind={runSettings.cli} size={15} />
                    </span>
                  )}
                  <span>{runSummary(runSettings.settings, agents)}</span>
                  <Icon d={runOpen ? ICON.up : ICON.down} size={11} />
                </button>
                <span className="grow" />
                {!done && (
                  <>
                    <button
                      type="button"
                      className="kb2-btn"
                      disabled={!canRun || live}
                      title={!canRun ? "O projeto não tem diretorio: na nota" : live ? "Já está no Auto" : "Executar agora: abre o agente com o pedido na barra, para você revisar e mandar"}
                      onClick={() => {
                        saveRunSettings(runSettings.settings);
                        props.onRunNow(runSettings.settings);
                      }}
                    >
                      <Icon d={ICON.send} size={13} /> Executar agora
                    </button>
                    <button
                      type="button"
                      className="kb2-btn primary"
                      disabled={!canRun || live}
                      title={!canRun ? "O projeto não tem diretorio: na nota" : live ? "Já está no Auto" : "Rodar sozinha: entra na fila do Auto e vai para Em teste quando o agente terminar"}
                      onClick={() => {
                        saveRunSettings(runSettings.settings);
                        void props.onQueue(runSettings.settings).then(loadActivity);
                      }}
                    >
                      <Icon d={ICON.bolt} size={13} /> Rodar sozinha
                    </button>
                  </>
                )}
              </div>
              {run && (
                <div className="tm-run" data-status={run.status}>
                  <Icon d={ICON.bolt} size={12} />
                  <span>
                    Auto: {AUTO_STATUS[run.status]}
                    {run.status === "erro" && run.erro ? ` (${run.erro})` : ""}
                    {" · "}
                    {runSummary(run as AutoSettings, agents)}
                  </span>
                  {run.sessao && (
                    <button type="button" className="kb2-link" onClick={() => props.onOpenSession(run.sessao)}>
                      ver terminal
                    </button>
                  )}
                </div>
              )}
              {runOpen && (
                <div className="tm-agent-panel">
                  <RunSettingsPanel
                    settings={runSettings.settings}
                    onChange={(next) => {
                      runSettings.setSettings(next);
                      saveRunSettings(next);
                    }}
                    agents={agents}
                    client={client}
                  />
                  <p className="small tm-muted">O pedido leva o título, a descrição, o checklist, as datas e os caminhos dos anexos. O jeito escolhido fica guardado para as próximas.</p>
                </div>
              )}
            </section>

            <hr className="tm-rule" />

            <section className="tm-section">
              <h3>
                <Icon d={ICON.lines} size={15} /> Descrição
              </h3>
              {desc !== null ? (
                <textarea
                  className="tm-desc-input"
                  autoFocus
                  value={desc}
                  rows={Math.min(18, Math.max(4, desc.split("\n").length + 1))}
                  onChange={(e) => setDesc(e.target.value)}
                  onBlur={() => void saveDesc()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      void saveDesc();
                    } else if (e.key === "Escape") {
                      e.stopPropagation();
                      setDesc(null);
                    }
                  }}
                  placeholder="Markdown: listas, `código`, [[nota do Brain]]… ⌘Enter salva, Esc desiste."
                  aria-label="Descrição"
                />
              ) : task.descricao ? (
                <div className="tm-desc note-body" tabIndex={0} title="Clique para editar" onClick={(e) => !(e.target as HTMLElement).closest("a") && setDesc(task.descricao ?? "")} onKeyDown={(e) => e.key === "Enter" && setDesc(task.descricao ?? "")}>
                  <div dangerouslySetInnerHTML={{ __html: renderNote(task.descricao) }} />
                </div>
              ) : (
                <button type="button" className="tm-empty" onClick={() => setDesc("")}>
                  Adicione uma descrição
                </button>
              )}
            </section>

            <section className="tm-section">
              <h3>
                <Icon d={ICON.checklist} size={15} /> Checklist
                {subs.length > 0 && (
                  <span className="tm-count mono">
                    {task.subtasks_done}/{task.subtasks_total}
                  </span>
                )}
              </h3>
              {subs.length > 0 && (
                <>
                  <div className="tm-progress" aria-hidden="true">
                    <span style={{ width: `${(100 * task.subtasks_done) / Math.max(1, task.subtasks_total)}%` }} />
                  </div>
                  <ul className="tm-checklist">
                    {subs.map((item) => (
                      <li key={`${item.indice}-${item.texto}`} data-done={item.feita ? "true" : undefined}>
                        <input type="checkbox" checked={item.feita} onChange={(e) => void act(() => client.setSubtask(projeto, id, item.indice, e.target.checked))} aria-label={item.texto} />
                        {subEdit?.index === item.indice ? (
                          <form
                            className="tm-inline grow"
                            onSubmit={(e) => {
                              e.preventDefault();
                              const next = subEdit.text.trim();
                              setSubEdit(null);
                              if (next && next !== item.texto) void act(() => client.editSubtask(projeto, id, item.indice, next));
                            }}
                          >
                            <input
                              autoFocus
                              value={subEdit.text}
                              onChange={(e) => setSubEdit({ index: item.indice, text: e.target.value })}
                              onBlur={(e) => e.currentTarget.form?.requestSubmit()}
                              onKeyDown={(e) => {
                                if (e.key === "Escape") {
                                  e.stopPropagation();
                                  setSubEdit(null);
                                }
                              }}
                              aria-label="Texto do item"
                            />
                          </form>
                        ) : (
                          <span className="tm-check-text" onClick={() => setSubEdit({ index: item.indice, text: item.texto })} title="Clique para editar" dangerouslySetInnerHTML={{ __html: renderInline(item.texto) }} />
                        )}
                        <button type="button" className="tm-x tm-row-x" onClick={() => void act(() => client.removeSubtask(projeto, id, item.indice))} aria-label={`Tirar ${item.texto}`} title="Tirar do checklist">
                          <Icon d={ICON.close} size={11} strokeWidth={2} />
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <form
                className="tm-add-item"
                onSubmit={(e) => {
                  e.preventDefault();
                  const value = subDraft.trim();
                  if (!value) return;
                  setSubDraft("");
                  void act(() => client.addSubtask(projeto, id, value));
                }}
              >
                <input value={subDraft} onChange={(e) => setSubDraft(e.target.value)} placeholder="Adicionar item e Enter" aria-label="Novo item do checklist" />
              </form>
            </section>

            <section className="tm-section">
              <h3>
                <Icon d={ICON.clip} size={15} /> Anexos
                <span className="grow" />
                <button type="button" className="kb2-btn" onClick={() => fileInput.current?.click()}>
                  Anexar arquivo
                </button>
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  hidden
                  onChange={(e) => {
                    const files = Array.from(e.target.files ?? []);
                    e.target.value = "";
                    void attachFiles(files);
                  }}
                />
              </h3>
              {(activity?.anexos.length ?? 0) > 0 ? (
                <ul className="tm-files">
                  {activity!.anexos.map((file) => (
                    <li key={file.id} className="tm-file">
                      <button type="button" className="tm-file-thumb" onClick={() => void client.openAttachment(file.id).catch((c) => props.onError(message(c)))} title="Abrir no app padrão do Mac">
                        {isImage(file.nome) ? <img src={client.attachmentUrl(file.id)} alt="" loading="lazy" /> : <Icon d={ICON.file} size={22} strokeWidth={1.4} />}
                      </button>
                      <div className="tm-file-meta">
                        <span className="tm-file-name" title={file.caminho}>
                          {file.nome}
                        </span>
                        <span className="small mono tm-muted">
                          {sizeText(file.tamanho)} · {when(file.ts)}
                        </span>
                      </div>
                      <button type="button" className="kb2-icon" onClick={() => void client.open({ reveal: file.caminho }).catch((c) => props.onError(message(c)))} title="Mostrar no Finder" aria-label="Mostrar no Finder">
                        <Icon d={ICON.folder} size={13} />
                      </button>
                      <button type="button" className="kb2-icon" onClick={() => void act(() => client.detachFromTask(projeto, id, file.id))} title="Tirar o anexo" aria-label={`Tirar ${file.nome}`}>
                        <Icon d={ICON.trash} size={13} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <button type="button" className="tm-empty tm-drop" onClick={() => fileInput.current?.click()}>
                  {uploading ? "Anexando…" : "Nenhum anexo. Arraste para cá, cole um print (⌘V) ou escolha um arquivo, até 50 MB."}
                </button>
              )}
              {uploading > 0 && (activity?.anexos.length ?? 0) > 0 && <p className="small tm-muted">Anexando {uploading}…</p>}
            </section>
          </main>

          <aside className="tm-side" aria-label="Atividade">
            <div className="tm-side-head">Atividade</div>
            <ol className="tm-feed">
              {activity === null && <li className="tm-muted small">Carregando…</li>}
              {activity !== null && events.length === 0 && (
                <li className="tm-muted small tm-feed-empty">Nada registrado ainda. O que mudar daqui em diante (pela MÊTIS ou por um agente) aparece aqui.</li>
              )}
              {events.map((event, i) =>
                !visible(event, i) ? null : (
                  <FeedItem key={event.id} event={event} agents={agents} onDelete={() => void act(() => client.uncommentTask(projeto, id, event.id))}>
                    {i === 0 && hiddenCount > 0 && (
                      <button type="button" className="tm-more" onClick={() => setExpanded(true)}>
                        <Icon d={ICON.chevron} size={11} /> Mostrar mais {hiddenCount} {hiddenCount === 1 ? "alteração" : "alterações"}
                      </button>
                    )}
                  </FeedItem>
                ),
              )}
              <div ref={feedEnd} />
            </ol>
            <form
              className="tm-comment"
              onSubmit={(e) => {
                e.preventDefault();
                void sendComment();
              }}
            >
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    void sendComment();
                  } else if (e.key === "Escape" && !comment) {
                    e.currentTarget.blur();
                  }
                }}
                rows={3}
                placeholder="Escreva um comentário…"
                aria-label="Comentário"
              />
              <div className="tm-comment-row">
                <span className="small tm-muted">⌘Enter envia · Markdown</span>
                <span className="grow" />
                <button type="submit" className="kb2-btn" disabled={!comment.trim() || sending}>
                  Comentar
                </button>
              </div>
            </form>
          </aside>
        </div>
      </div>
    </div>
  );
}

function FeedItem({ event, agents, onDelete, children }: { event: TaskEvent; agents: Agent[]; onDelete: () => void; children?: ReactNode }) {
  if (event.tipo === "comentario") {
    return (
      <li className="tm-comment-item">
        <div className="tm-comment-head">
          <b>{person(event.quem)}</b>
          <span className="grow" />
          <span className="small tm-muted">{when(event.ts)}</span>
          {event.quem === "Pedro" && (
            <button type="button" className="tm-x" onClick={onDelete} aria-label="Apagar o comentário" title="Apagar">
              <Icon d={ICON.close} size={10} strokeWidth={2} />
            </button>
          )}
        </div>
        <div className="tm-comment-body note-body" dangerouslySetInnerHTML={{ __html: renderNote(event.texto) }} />
        {children}
      </li>
    );
  }
  return (
    <li className="tm-event" data-kind={event.tipo}>
      <span className="tm-event-dot" />
      <span className="tm-event-text">
        <b>{event.quem === "Auto" ? "⚡ Auto" : person(event.quem)}</b> {sentence(event, agents)}
      </span>
      <span className="tm-event-when small">{when(event.ts)}</span>
      {children}
    </li>
  );
}

/**
 * v1.1.3: o calendário é nosso, não o do `<input type="date">`. O do WebKit, aberto pelo
 * `showPicker()` num campo escondido que nunca recebe o foco, não fechava ao clicar fora na
 * janela da MÊTIS (ao que tudo indica, ele só fecha quando o campo perde o foco). Aqui ele fecha ao escolher o dia, ao clicar
 * fora e no Esc (sem fechar o cartão junto), e sai em português e nas cores do tema.
 */
function DateField({ label, value, late, onChange }: { label: string; value: string; late?: boolean; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    // Na captura, antes do Esc do cartão, que desiste quando o evento chega com defaultPrevented.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
    };
    document.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  return (
    <span ref={box} className="tm-date" data-set={value ? "true" : undefined} data-late={late ? "true" : undefined}>
      <button
        type="button"
        className="tm-date-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        title={value ? `${label}: ${value.split("-").reverse().join("/")}` : `Escolher a data de ${label.toLowerCase()}`}
      >
        <Icon d={ICON.calendar} size={12} />
        {value ? dayMonth(value) : label}
      </button>
      {open && (
        <Calendar
          label={label}
          value={value}
          onPick={(iso) => {
            setOpen(false);
            if (iso !== value) onChange(iso);
          }}
        />
      )}
      {value && (
        <button type="button" className="tm-x" onClick={() => onChange("")} aria-label={`Tirar a data de ${label.toLowerCase()}`} title="Tirar">
          <Icon d={ICON.close} size={10} strokeWidth={2.2} />
        </button>
      )}
    </span>
  );
}

const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const WEEKDAYS = ["D", "S", "T", "Q", "Q", "S", "S"];
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** O mês da data (ou de hoje) em seis semanas fixas, de domingo a sábado, para a altura não pular. */
function Calendar({ label, value, onPick }: { label: string; value: string; onPick: (iso: string) => void }) {
  const today = isoDay(new Date());
  const [month, setMonth] = useState(() => {
    const [y, m] = (/^\d{4}-\d{2}-\d{2}$/.test(value) ? value : today).split("-").map(Number);
    return new Date(y, m - 1, 1);
  });
  const start = new Date(month.getFullYear(), month.getMonth(), 1 - month.getDay());
  const days = Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  const shift = (n: number) => setMonth((m) => new Date(m.getFullYear(), m.getMonth() + n, 1));
  return (
    <div className="tm-cal" role="dialog" aria-label={`Data de ${label.toLowerCase()}`}>
      <div className="tm-cal-head">
        <span className="tm-cal-title">
          {MONTHS[month.getMonth()]} de {month.getFullYear()}
        </span>
        <button type="button" className="tm-x" onClick={() => shift(-1)} aria-label="Mês anterior" title="Mês anterior">
          <Icon d={ICON.collapse} size={12} strokeWidth={2} />
        </button>
        <button type="button" className="tm-x" onClick={() => shift(1)} aria-label="Próximo mês" title="Próximo mês">
          <Icon d={ICON.chevron} size={12} strokeWidth={2} />
        </button>
      </div>
      <div className="tm-cal-grid">
        {WEEKDAYS.map((name, i) => (
          <span key={i} className="tm-cal-wd">
            {name}
          </span>
        ))}
        {days.map((day) => {
          const iso = isoDay(day);
          return (
            <button
              key={iso}
              type="button"
              className="tm-cal-day"
              data-out={day.getMonth() !== month.getMonth() ? "true" : undefined}
              data-today={iso === today ? "true" : undefined}
              aria-pressed={iso === value}
              aria-label={`${day.getDate()} de ${MONTHS[day.getMonth()]} de ${day.getFullYear()}`}
              onClick={() => onPick(iso)}
            >
              {day.getDate()}
            </button>
          );
        })}
      </div>
      <div className="tm-cal-foot">
        <button type="button" className="tm-ghost" onClick={() => onPick(today)}>
          Hoje
        </button>
      </div>
    </div>
  );
}
