import { useEffect, useState } from "react";
import { CoreError, type CoreClient } from "../lib/core";
import { renderInline } from "../lib/obsidian";
import type { BoardProject, ClickupBoard, ClickupList, ClickupTask, ConnectorAccount, KanbanTask } from "../types";

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** Rótulo com uma cor estável (a mesma etiqueta tem sempre a mesma cor). */
export function labelHue(label: string): number {
  let hash = 0;
  for (const ch of label) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  return hash;
}

export function LabelChip({ label, active, onClick }: { label: string; active?: boolean; onClick?: () => void }) {
  const style = { "--hue": labelHue(label) } as React.CSSProperties;
  return onClick ? (
    <button type="button" className="kb-label" style={style} aria-pressed={!!active} onClick={onClick}>
      #{label}
    </button>
  ) : (
    <span className="kb-label" style={style}>
      #{label}
    </span>
  );
}

/**
 * Cartão de tarefa (v0.9.8): rótulos (#etiquetas) e subtarefas abrem no próprio cartão;
 * marcar uma subtarefa ou mudar os rótulos grava na nota do Brain na hora.
 */
export function TaskCard(props: {
  task: KanbanTask;
  done: boolean;
  dragging: boolean;
  canRun: boolean;
  onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
  onClick: () => void;
  onRun: () => void;
  onLabels: (labels: string[]) => Promise<void>;
  onAddSubtask: (text: string) => Promise<void>;
  onToggleSubtask: (index: number, done: boolean) => Promise<void>;
  onLabelClick: (label: string) => void;
}) {
  const { task } = props;
  const [open, setOpen] = useState(false);
  const [editingLabels, setEditingLabels] = useState<string | null>(null);
  const [subtask, setSubtask] = useState("");
  const subtasks = task.subtarefas ?? [];
  const labels = task.rotulos ?? [];
  const text = task.texto ?? task.text;

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
      className="kb-card kb-task"
      data-cancelled={task.cancelled ? "true" : undefined}
      data-dragging={props.dragging ? "true" : undefined}
      onPointerDown={props.onPointerDown}
      onClick={props.onClick}
    >
      <div className="kb-task-text" dangerouslySetInnerHTML={{ __html: renderInline(text) }} />
      {labels.length > 0 && editingLabels === null && (
        <div className="kb-tags">
          {labels.map((label) => (
            <LabelChip key={label} label={label} onClick={() => props.onLabelClick(label)} />
          ))}
        </div>
      )}
      {editingLabels !== null && (
        <form
          className="kb-inline"
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
            placeholder="rótulos separados por espaço (ex.: bug front)"
            aria-label="Rótulos"
          />
        </form>
      )}
      <div className="kb-meta small mono">
        <span title="id para metis tarefa mover">{task.id}</span>
        {task.subtasks_total > 0 && (
          <button type="button" className="link-btn kb-sub-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            · {task.subtasks_done}/{task.subtasks_total} subtarefas
          </button>
        )}
        {task.done_on && <span> · {task.done_on}</span>}
      </div>
      {open && (
        <ul className="kb-subtasks">
          {subtasks.map((item) => (
            <li key={item.indice}>
              <label>
                <input type="checkbox" checked={item.feita} onChange={(event) => void props.onToggleSubtask(item.indice, event.target.checked)} />
                <span dangerouslySetInnerHTML={{ __html: renderInline(item.texto) }} />
              </label>
            </li>
          ))}
          <li>
            <form
              className="kb-inline"
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
      <div className="kb-card-actions">
        <button type="button" className="link-btn" onClick={() => setEditingLabels(labels.join(" "))}>
          rótulos
        </button>
        {task.subtasks_total === 0 && (
          <button type="button" className="link-btn" onClick={() => setOpen((v) => !v)}>
            subtarefas
          </button>
        )}
        {!props.done && props.canRun && (
          <button type="button" className="link-btn kb-run" onClick={props.onRun}>
            ▶ Executar com agente
          </button>
        )}
      </div>
    </article>
  );
}

/**
 * Coluna do ClickUp (v0.9.8): as tarefas abertas da lista ligada ao projeto, com o status do
 * ClickUp (mudar aqui muda lá), abrir no navegador da MÊTIS e executar com um agente.
 */
export function ClickupColumn(props: {
  client: CoreClient;
  project: BoardProject;
  accounts: ConnectorAccount[];
  tick: number;
  onOpenUrl: (url: string) => void;
  onRun: (task: ClickupTask) => void;
  onBring: (task: ClickupTask) => void;
  onError: (message: string) => void;
}) {
  const { client, project } = props;
  const [board, setBoard] = useState<ClickupBoard | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);
  const [account, setAccount] = useState(props.accounts[0]?.id ?? "");
  const [lists, setLists] = useState<ClickupList[] | null>(null);
  const [list, setList] = useState("");
  const [needsToken, setNeedsToken] = useState(false);
  const [token, setToken] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    setProblem(null);
    client
      .clickupBoard(project.name)
      .then((answer) => alive && setBoard(answer))
      .catch((cause) => {
        if (!alive) return;
        setBoard(null);
        setProblem(message(cause));
        if (cause instanceof CoreError && cause.status === 409) setNeedsToken(true);
      });
    return () => {
      alive = false;
    };
  }, [client, project.name, props.tick, reload]);

  useEffect(() => {
    if (!linking || !account) return;
    let alive = true;
    setLists(null);
    setNeedsToken(false);
    client
      .clickupLists(account)
      .then((answer) => {
        if (!alive) return;
        setLists(answer.listas);
        setList(answer.listas[0]?.id ?? "");
      })
      .catch((cause) => {
        if (!alive) return;
        setProblem(message(cause));
        if (cause instanceof CoreError && cause.status === 409) setNeedsToken(true);
      });
    return () => {
      alive = false;
    };
  }, [client, linking, account, reload]);

  const link = async () => {
    const chosen = lists?.find((l) => l.id === list);
    if (!chosen) return;
    try {
      await client.linkClickup(project.name, account, chosen.id, `${chosen.espaco}${chosen.pasta ? ` › ${chosen.pasta}` : ""} › ${chosen.nome}`);
      setLinking(false);
      setReload((n) => n + 1);
    } catch (cause) {
      props.onError(message(cause));
    }
  };

  const saveToken = async () => {
    const conta = board?.ligacao?.conta ?? account;
    try {
      await client.saveClickupApiToken(conta, token.trim());
      setToken("");
      setNeedsToken(false);
      setProblem(null);
      setReload((n) => n + 1);
    } catch (cause) {
      setProblem(message(cause));
    }
  };

  const move = async (task: ClickupTask, status: string) => {
    if (!board?.ligacao || status === task.status) return;
    try {
      const saved = await client.setClickupStatus(board.ligacao.conta, task.id, status);
      setBoard((current) => (current ? { ...current, tarefas: current.tarefas.map((t) => (t.id === task.id ? saved : t)) } : current));
    } catch (cause) {
      props.onError(message(cause));
    }
  };

  const linked = board?.ligacao;
  return (
    <section className="kb-col kb-clickup" aria-label="ClickUp">
      <header className="kb-col-head">
        <span className="kb-dot" style={{ background: "#7b68ee" }} />
        <span>ClickUp</span>
        <span className="kb-count mono">{board?.tarefas.length ?? 0}</span>
      </header>
      <p className="kb-hint small">
        {linked ? (
          <>
            {linked.nome}{" "}
            <button type="button" className="link-btn" onClick={() => setLinking((v) => !v)}>
              trocar
            </button>
          </>
        ) : (
          "nenhuma lista ligada a este projeto"
        )}
      </p>
      {(!linked || linking) && (
        <div className="kb-link">
          <select value={account} onChange={(event) => setAccount(event.target.value)} aria-label="Conta do ClickUp">
            {props.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          {!linking ? (
            <button type="button" className="btn" onClick={() => setLinking(true)}>
              Ligar uma lista
            </button>
          ) : lists === null ? (
            !needsToken && <span className="small">procurando as listas…</span>
          ) : (
            <>
              <select value={list} onChange={(event) => setList(event.target.value)} aria-label="Lista do ClickUp">
                {lists.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.espaco}
                    {l.pasta ? ` › ${l.pasta}` : ""} › {l.nome}
                  </option>
                ))}
              </select>
              <button type="button" className="btn primary" disabled={!list} onClick={() => void link()}>
                Ligar
              </button>
              {linked && (
                <button
                  type="button"
                  className="link-btn danger"
                  onClick={() =>
                    void client
                      .unlinkClickup(project.name)
                      .then(() => (setLinking(false), setReload((n) => n + 1)))
                      .catch((cause) => props.onError(message(cause)))
                  }
                >
                  desligar
                </button>
              )}
            </>
          )}
        </div>
      )}
      {needsToken && (
        <form
          className="kb-link"
          onSubmit={(event) => {
            event.preventDefault();
            void saveToken();
          }}
        >
          <span className="small">O ClickUp recusou o token do login para o kanban. Cole um token pessoal (ClickUp → Configurações → Apps → API Token):</span>
          <input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="pk_…" autoComplete="off" />
          <button type="submit" className="btn primary" disabled={!token.trim()}>
            Salvar
          </button>
        </form>
      )}
      {problem && !needsToken && <p className="small kb-error">{problem}</p>}
      <div className="kb-cards">
        {board?.tarefas.map((task) => (
          <article key={task.id} className="kb-card kb-task kb-gh">
            <div className="kb-task-text">{task.nome}</div>
            <div className="kb-tags">
              <select
                className="kb-status"
                value={task.status}
                style={{ "--status": task.cor || "var(--fnt)" } as React.CSSProperties}
                onChange={(event) => void move(task, event.target.value)}
                aria-label="Status no ClickUp"
              >
                {(board.status.length ? board.status : [{ nome: task.status, cor: task.cor, tipo: "" }]).map((s) => (
                  <option key={s.nome} value={s.nome}>
                    {s.nome}
                  </option>
                ))}
              </select>
              {task.prioridade && <span className="kb-tag">{task.prioridade}</span>}
            </div>
            <div className="kb-meta small mono">
              {task.responsaveis.join(", ") || "sem responsável"}
              {task.prazo ? ` · prazo ${new Date(task.prazo * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}` : ""}
            </div>
            <div className="kb-card-actions">
              <button type="button" className="link-btn" onClick={() => props.onOpenUrl(task.url)}>
                abrir
              </button>
              <button type="button" className="link-btn" title="Copia para as Próximas ações da nota do projeto" onClick={() => props.onBring(task)}>
                trazer
              </button>
              {project.directory && (
                <button type="button" className="link-btn kb-run" onClick={() => props.onRun(task)}>
                  ▶ Executar com agente
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
