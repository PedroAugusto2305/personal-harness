import { useEffect, useState } from "react";
import type { CoreClient } from "../lib/core";
import { shortPath } from "../lib/format";
import { renderInline } from "../lib/obsidian";
import type { Agent, Approval, Routine, RoutineDraft, RoutineRun, Session, TodayData } from "../types";
import { AgentSprite } from "./AgentSprite";
import { ApprovalCard, ReminderTry } from "./ConnectorsView";

interface Props {
  client: CoreClient | null;
  tick: number;
  agents: Agent[];
  sessions: Session[];
  approvals: Approval[];
  hasSlack: boolean;
  onOpenSession: (id: string) => void;
  onOpenTasks: (project: string) => void;
  onDecide: (id: string, approve: boolean) => void;
  onToast: (message: string) => void;
}

const DAY_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];
const STATUS: Record<string, { label: string; tone: string }> = {
  rodou: { label: "rodou", tone: "ok" },
  recuperada: { label: "rodou ao acordar", tone: "ok" },
  manual: { label: "rodou (manual)", tone: "ok" },
  pulou: { label: "pulou", tone: "warn" },
  erro: { label: "erro", tone: "err" },
};
const EMPTY: RoutineDraft = { name: "", agent: "", cli: "claude", folder: "", days: [0, 1, 2, 3, 4, 5], time: "09:00", catchup: 60, notify: true, active: true, prompt: "" };
const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

const clock = (iso: string) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
const nextLabel = (iso?: string | null) => {
  if (!iso) return "sem próxima";
  const date = new Date(iso);
  const today = new Date();
  const tomorrow = new Date(today.getTime() + 86400000);
  const day =
    date.toDateString() === today.toDateString()
      ? "hoje"
      : date.toDateString() === tomorrow.toDateString()
        ? "amanhã"
        : date.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" });
  return `${day} ${clock(iso)}`;
};
const daysLabel = (days: number[]) =>
  days.length === 7 ? "todo dia" : days.join(",") === "0,1,2,3,4,5" ? "seg a sáb" : days.join(",") === "0,1,2,3,4" ? "seg a sex" : days.map((d) => DAY_SHORT[d]).join(", ");

function RoutineEditor(props: {
  client: CoreClient;
  agents: Agent[];
  routine: Routine | null;
  onClose: () => void;
  onToast: (m: string) => void;
}) {
  const { client, routine } = props;
  const [draft, setDraft] = useState<RoutineDraft>(routine ? { ...EMPTY, ...routine } : EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const set = <K extends keyof RoutineDraft>(key: K, value: RoutineDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const agent = props.agents.find((a) => a.id === draft.agent);

  const save = async () => {
    setError(null);
    try {
      const saved = await client.saveRoutine(draft, routine?.id);
      props.onToast(`Rotina "${saved.name}" salva; próxima: ${nextLabel(saved.next)}.`);
      props.onClose();
    } catch (cause) {
      setError(message(cause));
    }
  };

  return (
    <div className="routine-editor">
      <div className="routine-editor-head">
        <strong>{routine ? routine.name : "Nova rotina"}</strong>
        <button type="button" className="link-btn" onClick={props.onClose}>
          fechar
        </button>
      </div>
      <label>
        <span className="small">Nome</span>
        <input value={draft.name} onChange={(e) => set("name", e.target.value)} placeholder="Check-in de estudo" />
      </label>
      <label>
        <span className="small">Agente</span>
        <select value={draft.agent} onChange={(e) => set("agent", e.target.value)}>
          <option value="">Nenhum (Claude ou Codex puro)</option>
          {props.agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} · {a.description}
            </option>
          ))}
        </select>
      </label>
      {!agent && (
        <label>
          <span className="small">CLI</span>
          <select value={draft.cli} onChange={(e) => set("cli", e.target.value as RoutineDraft["cli"])}>
            <option value="claude">Claude Code</option>
            <option value="codex">Codex</option>
          </select>
        </label>
      )}
      <div>
        <span className="small">Dias</span>
        <div className="routine-days">
          {DAY_SHORT.map((label, day) => (
            <button
              key={label}
              type="button"
              className="filter-chip"
              aria-pressed={draft.days.includes(day)}
              onClick={() => set("days", draft.days.includes(day) ? draft.days.filter((d) => d !== day) : [...draft.days, day].sort())}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="routine-row">
        <label>
          <span className="small">Hora</span>
          <input type="time" value={draft.time} onChange={(e) => set("time", e.target.value)} />
        </label>
        <label title="Se o Mac estava dormindo na hora: roda se acordar até esse tempo depois; senão, pula">
          <span className="small">Recuperar até (min)</span>
          <input type="number" min={0} value={draft.catchup} onChange={(e) => set("catchup", Number(e.target.value))} />
        </label>
      </div>
      <label>
        <span className="small routine-hint">Pasta {agent?.folder ? `(vazio = a do agente: ${shortPath(agent.folder)})` : "(vazio = sua pasta pessoal)"}</span>
        <input value={draft.folder} onChange={(e) => set("folder", e.target.value)} spellCheck={false} />
      </label>
      <label>
        <span className="small">Pedido (a primeira mensagem para o agente)</span>
        <textarea rows={6} value={draft.prompt} onChange={(e) => set("prompt", e.target.value)} />
      </label>
      <label className="routine-check small">
        <input type="checkbox" checked={draft.notify} onChange={(e) => set("notify", e.target.checked)} />
        avisar no Slack quando abrir (toca no iPhone)
      </label>
      <label className="routine-check small">
        <input type="checkbox" checked={draft.active} onChange={(e) => set("active", e.target.checked)} />
        ativa
      </label>
      {error && <p className="conn-error small">{error}</p>}
      <div className="routine-actions">
        {routine &&
          (confirm ? (
            <span className="small">
              apagar?{" "}
              <button
                type="button"
                className="link-btn danger"
                onClick={() =>
                  void client
                    .deleteRoutine(routine.id)
                    .then(() => {
                      props.onToast(`Rotina "${routine.name}" foi para a lixeira.`);
                      props.onClose();
                    })
                    .catch((cause) => setError(message(cause)))
                }
              >
                sim
              </button>{" "}
              <button type="button" className="link-btn" onClick={() => setConfirm(false)}>
                não
              </button>
            </span>
          ) : (
            <button type="button" className="link-btn" onClick={() => setConfirm(true)}>
              apagar
            </button>
          ))}
        <button type="button" className="btn primary" disabled={!draft.name.trim() || !draft.prompt.trim() || !draft.days.length} onClick={() => void save()}>
          Salvar
        </button>
      </div>
    </div>
  );
}

export function TodayView(props: Props) {
  const { client, tick } = props;
  const [today, setToday] = useState<TodayData | null>(null);
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [runs, setRuns] = useState<RoutineRun[]>([]);
  const [editing, setEditing] = useState<Routine | "nova" | null>(null);

  useEffect(() => {
    if (!client) return;
    const load = () => {
      void client.today().then(setToday).catch(() => undefined);
      void client
        .routines()
        .then((r) => {
          setRoutines(r.routines);
          setRuns(r.runs);
        })
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 60000);
    return () => window.clearInterval(timer);
  }, [client, tick, editing]);

  if (!client) return <div className="today-screen" />;
  const agentOf = (id: string) => props.agents.find((a) => a.id === id);
  const open = (sessionId: string) => props.sessions.some((s) => s.id === sessionId);
  const now = today ? new Date(today.now) : new Date();
  const title = now.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });

  const run = (routine: Routine) =>
    void client
      .runRoutine(routine.id)
      .then((r) => props.onToast(r.status === "erro" ? `Erro: ${r.detail}` : `${routine.name} abriu num terminal.`))
      .catch((cause) => props.onToast(message(cause)));

  return (
    <div className="today-screen">
      <section className="today-main">
        <h1 className="today-title">Hoje · {title}</h1>

        <div className="section-title">Rotinas de hoje</div>
        {today?.slots.length ? (
          <ul className="today-timeline">
            {today.slots.map(({ routine, slot, run: done }) => {
              const agent = agentOf(routine.agent);
              const status = done ? STATUS[done.status] : null;
              const due = new Date(slot) <= now;
              return (
                <li key={routine.id} className="today-slot" data-past={due ? "true" : undefined}>
                  <span className="today-time mono">{clock(slot)}</span>
                  {agent ? <AgentSprite agent={agent} client={client} size={24} /> : <span className="today-glyph">✻</span>}
                  <span className="today-slot-name">
                    {routine.name}
                    {agent && <span className="small"> · {agent.name}</span>}
                  </span>
                  {status ? (
                    <span className="activity-status" data-status={status.tone === "ok" ? "ok" : status.tone === "err" ? "erro" : "aguardando você"} title={done?.detail || undefined}>
                      {status.label}
                    </span>
                  ) : (
                    <span className="activity-status">{due ? "aguardando" : "agendada"}</span>
                  )}
                  {done?.session && open(done.session) ? (
                    <button type="button" className="link-btn" onClick={() => props.onOpenSession(done.session)}>
                      abrir ›
                    </button>
                  ) : (
                    <button type="button" className="link-btn" onClick={() => run(routine)}>
                      rodar agora
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="small today-empty">Nenhuma rotina para hoje{today?.weekday === "dom" ? " (domingo é descanso)" : ""}.</p>
        )}

        {props.approvals.length > 0 && (
          <>
            <div className="section-title">Aguardando você</div>
            <div className="today-approvals">
              {props.approvals.map((a) => (
                <ApprovalCard key={a.id} approval={a} onDecide={props.onDecide} />
              ))}
            </div>
          </>
        )}

        <div className="section-title">Em andamento</div>
        {today?.doing.length ? (
          <ul className="today-doing">
            {today.doing.map((task) => (
              <li key={`${task.project}-${task.id}`}>
                <span className="kb-dot" style={{ background: task.state === "em-teste" ? "var(--wait)" : "var(--run)" }} />
                <span className="today-task" dangerouslySetInnerHTML={{ __html: renderInline(task.text) }} />
                <button type="button" className="link-btn" onClick={() => props.onOpenTasks(task.project)}>
                  {task.project} ›
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="small today-empty">Nenhuma tarefa em andamento ou em teste nos projetos do Brain.</p>
        )}

        {props.hasSlack && <ReminderTry client={client} onToast={props.onToast} />}
      </section>

      <aside className="today-side">
        <div className="today-side-head">
          <div className="section-title">Rotinas</div>
          <button type="button" className="btn" onClick={() => setEditing("nova")}>
            Nova rotina
          </button>
        </div>
        {editing && (
          <RoutineEditor
            key={editing === "nova" ? "nova" : editing.id}
            client={client}
            agents={props.agents}
            routine={editing === "nova" ? null : editing}
            onClose={() => setEditing(null)}
            onToast={props.onToast}
          />
        )}
        {routines.map((routine) => {
          const agent = agentOf(routine.agent);
          return (
            <button key={routine.id} type="button" className="routine-card" data-off={routine.active ? undefined : "true"} onClick={() => setEditing(routine)}>
              <span className="routine-card-head">
                {agent ? <AgentSprite agent={agent} client={client} size={20} /> : <span className="today-glyph">✻</span>}
                <strong>{routine.name}</strong>
                {!routine.active && <span className="chip">pausada</span>}
              </span>
              <span className="small mono">
                {daysLabel(routine.days)} · {routine.time} · {routine.active ? `próxima ${nextLabel(routine.next)}` : "não roda"}
              </span>
              <span className="small">
                recupera até {routine.catchup} min{routine.notify ? " · avisa no Slack" : ""}
              </span>
            </button>
          );
        })}
        {!routines.length && !editing && (
          <p className="small today-empty">
            Nenhuma rotina. Uma rotina abre um agente num terminal na hora marcada, com um pedido; com o Mac dormindo, recupera dentro da janela
            ou pula.
          </p>
        )}
        {runs.length > 0 && (
          <>
            <div className="section-title today-history">Últimas execuções</div>
            {runs.slice(0, 8).map((r) => (
              <div key={r.id} className="today-run small">
                <span className="mono">{new Date(r.ts * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
                <span>{routines.find((x) => x.id === r.routine)?.name ?? r.routine}</span>
                <span className="activity-status">{STATUS[r.status]?.label ?? r.status}</span>
                {r.detail && <span className="today-run-detail">{r.detail}</span>}
              </div>
            ))}
          </>
        )}
      </aside>
    </div>
  );
}
