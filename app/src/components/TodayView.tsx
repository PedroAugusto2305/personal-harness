import { useEffect, useMemo, useState } from "react";
import { KindIcon } from "./KindIcon";
import { ICON, Icon } from "../icons";
import { useCardDrag } from "../lib/cardDrag";
import type { CoreClient } from "../lib/core";
import { money, pct, resetIn, shortPath, tokens } from "../lib/format";
import type {
  Accounts,
  Agent,
  AgentEvent,
  Approval,
  BoardProject,
  BrainGraphData,
  ConnectorAccount,
  RateWindow,
  Routine,
  RoutineDraft,
  Session,
  Stage,
  Suggestion,
  TodayData,
  Usage,
} from "../types";
import { AgentSprite } from "./AgentSprite";
import { deskOf } from "./AgentsRoom";
import { BrandIcon, brandFor } from "./BrandIcon";
import { ApprovalCard } from "./ConnectorsView";
import { ProjectGraph } from "./ProjectGraph";
import { useTodaySpend } from "./StatusBar";
import { SuggestionCard } from "./SuggestionCard";
import "./today.css";

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
  /** v0.8: sugestões de precedente esperando o Pedro, de todos os projetos. */
  suggestionsTick: number;
  onOpenNote: (title: string) => void;
  /** v0.9.8: cota dos planos, por conta. */
  usage: Usage;
  accounts: Accounts;
  onOpenAccounts: () => void;
  /** v0.9.9: o Hoje do mockup. */
  events: AgentEvent[];
  connectors: ConnectorAccount[];
  onView: (view: "kanban" | "brain" | "agents" | "connectors") => void;
  onOpenKanban: (project?: string) => void;
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
    <div className="routine-editor td-modal" role="dialog" aria-label={routine ? routine.name : "Nova rotina"}>
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
  const spend = useTodaySpend(client);
  const [today, setToday] = useState<TodayData | null>(null);
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [projects, setProjects] = useState<BoardProject[]>([]);
  const [graph, setGraph] = useState<BrainGraphData | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [editing, setEditing] = useState<Routine | "nova" | null>(null);
  const [capture, setCapture] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    const load = () => {
      void client.today().then((t) => alive && setToday(t)).catch(() => undefined);
      void client.routines().then((r) => alive && setRoutines(r.routines)).catch(() => undefined);
      void client.boardProjects().then((p) => alive && setProjects(p)).catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 60000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client, tick, editing]);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    void client.brainGraph().then((g) => alive && setGraph(g)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [client, tick]);

  useEffect(() => {
    if (!client) return;
    void client
      .suggestions()
      .then(setSuggestions)
      .catch(() => setSuggestions([]));
  }, [client, props.suggestionsTick]);

  const drag = useCardDrag((col, name) => void moveProject(name, (col === "none" ? "" : col) as Stage));
  const moveProject = async (name: string, stage: Stage) => {
    if (!client) return;
    const before = projects;
    if (before.find((p) => p.name === name)?.stage === stage) return;
    setProjects((all) => all.map((p) => (p.name === name ? { ...p, stage } : p)));
    try {
      const saved = await client.setStage(name, stage);
      setProjects((all) => all.map((p) => (p.name === name ? saved : p)));
    } catch (cause) {
      setProjects(before);
      props.onToast(message(cause));
    }
  };

  const desks = useMemo(() => props.agents.map((a) => deskOf(a, props.sessions, props.events, routines)), [props.agents, props.sessions, props.events, routines]);

  if (!client) return <div className="td" />;
  const agentOf = (id: string) => props.agents.find((a) => a.id === id);
  const now = today ? new Date(today.now) : new Date();
  const date = now.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  const live = props.sessions.filter((s) => (s.kind === "claude" || s.kind === "codex") && s.status !== "exited");
  const waiting = props.approvals.length + live.filter((s) => s.status === "waiting").length;
  const openActions = projects.reduce((n, p) => n + p.tasks.pendente + p.tasks["em-andamento"] + p.tasks["em-teste"], 0);

  const send = async () => {
    const text = capture.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const answer = await client.capture(text);
      setCapture("");
      props.onToast(answer.mensagem || "Mandado para o Hermes.");
    } catch (cause) {
      props.onToast(message(cause));
    } finally {
      setSending(false);
    }
  };

  const run = (routine: Routine) =>
    void client
      .runRoutine(routine.id)
      .then((r) => props.onToast(r.status === "erro" ? `Erro: ${r.detail}` : `${routine.name} abriu num terminal.`))
      .catch((cause) => props.onToast(message(cause)));

  // Colunas do mini-kanban: os estágios de sempre, mais "Ideia" e "Sem estágio" quando têm projeto.
  const stages: { key: Stage; label: string }[] = [
    { key: "", label: "Sem estágio" },
    { key: "ideia", label: "Ideia" },
    { key: "planejando", label: "Planejando" },
    { key: "construindo", label: "Construindo" },
    { key: "em-producao", label: "Em produção" },
    { key: "pausado", label: "Pausado" },
  ].filter((s) => (s.key !== "" && s.key !== "ideia") || projects.some((p) => p.stage === s.key)) as { key: Stage; label: string }[];
  const sessionsIn = (p: BoardProject) => {
    const dir = p.directory?.replace(/^~/, "") ?? "";
    return dir ? live.filter((s) => s.cwd.endsWith(dir) || s.cwd.includes(`${dir}/`) || (p.directory && s.cwd.startsWith(p.directory))) : [];
  };

  const suggestion = suggestions[0] ?? null;

  return (
    <div className="td">
      <div className="td-tabs" role="tablist" aria-label="Abas">
        <div className="td-tab" role="tab" aria-selected="true">
          Hoje
        </div>
        <button type="button" className="td-tab muted" role="tab" aria-selected="false" onClick={() => props.onOpenNote("HOME")}>
          HOME
        </button>
      </div>

      <div className="td-body">
        <div className="td-top">
          <div className="td-title">
            <h1>Hoje</h1>
            <span className="td-sub">
              {date} · {live.length} {live.length === 1 ? "agente" : "agentes"} · {openActions} ações abertas
              {waiting > 0 && <span className="td-waiting"> · {waiting} {waiting === 1 ? "coisa esperando" : "coisas esperando"} você</span>}
            </span>
            {today?.study && !today.study.rest_day && (
              <span className="td-study" data-risk={today.study.risk ? "true" : undefined}>
                {Math.round(today.study.today)} min de estudo hoje (piso {today.study.floor})
                {today.study.risk ? " · ontem ficou abaixo do piso: hoje não pode passar em branco" : ""}
              </span>
            )}
          </div>
          <form
            className="td-capture"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <label className="td-capture-input">
              <span className="sr-only">Captura rápida para o Hermes</span>
              <input value={capture} onChange={(e) => setCapture(e.target.value)} placeholder="Mande para o Hermes: “me lembra de pagar o IPVA sexta 9h”" />
            </label>
            <div className="td-capture-row">
              <span className="td-capture-who">
                <span className="td-dot" />
                Hermes
              </span>
              <span>vira tarefa, lembrete ou nota</span>
              <span className="td-kbd mono">⌥ espaço</span>
              <button type="submit" className="td-send" aria-label="Enviar" disabled={!capture.trim() || sending}>
                <Icon d={ICON.up} size={13} strokeWidth={2.4} />
              </button>
            </div>
          </form>
        </div>

        {props.approvals.length > 0 && (
          <div className="td-approvals">
            {props.approvals.map((a) => (
              <ApprovalCard key={a.id} approval={a} onDecide={props.onDecide} />
            ))}
          </div>
        )}

        <div className="td-middle">
          <section className="td-projects" aria-label="Kanban de projetos">
            <div className="td-section-head">
              <button type="button" className="td-section-link" onClick={() => props.onOpenKanban()}>
                Projetos ›
              </button>
              <span className="td-hint">arraste para mudar o estágio no Brain</span>
            </div>
            <div className="td-cols" style={{ gridTemplateColumns: `repeat(${stages.length}, minmax(170px, 1fr))` }}>
              {stages.map((stage) => {
                const list = projects.filter((p) => p.stage === stage.key).sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
                const key = stage.key || "none";
                return (
                  <div key={key} className="td-col" data-col={key} data-over={drag.drag?.col === key ? "true" : undefined}>
                    <div className="td-col-head">
                      <span>{stage.label}</span>
                      <span className="td-count">{list.length}</span>
                    </div>
                    {list.slice(0, 6).map((p) => {
                      const here = sessionsIn(p);
                      const withAgent = here.map((s) => agentOf(s.agent ?? "")).filter(Boolean) as Agent[];
                      const open = p.tasks.pendente + p.tasks["em-andamento"] + p.tasks["em-teste"];
                      return (
                        <article
                          key={p.name}
                          className="td-card"
                          data-dragging={drag.drag?.id === p.name ? "true" : undefined}
                          data-live={here.length ? "true" : undefined}
                          onPointerDown={(event) => drag.start(event, p.name, p.name)}
                          onDragStart={(event) => event.preventDefault()}
                          onClick={() => !drag.consumeClick() && props.onOpenKanban(p.name)}
                        >
                          <span className="td-card-name">{p.name}</span>
                          <span className="td-card-meta">
                            {open} {open === 1 ? "ação" : "ações"}
                            {p.next[0] ? ` · ${p.next[0].replace(/\[\[([^\]|]+)\|?([^\]]*)\]\]/g, (_, a, b) => b || a).replace(/[*_`]/g, "").slice(0, 40)}` : ""}
                          </span>
                          <span className="td-card-row">
                            {p.area && <span className="td-tag">#{p.area.toLowerCase().replace(/\s+/g, "-")}</span>}
                            {withAgent.slice(0, 3).map((a) => (
                              <AgentSprite key={a.id} agent={a} client={client} size={18} />
                            ))}
                            {here.length > 0 && (
                              <span className="td-clis mono">
                                {here[0].kind}
                                {here.length > 1 ? ` +${here.length - 1}` : ""}
                              </span>
                            )}
                          </span>
                        </article>
                      );
                    })}
                    {list.length > 6 && (
                      <button type="button" className="td-more" onClick={() => props.onOpenKanban()}>
                        +{list.length - 6} no kanban
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          <aside className="td-brain" aria-label="Brain">
            <div className="td-graph">
              <div className="td-graph-head">
                <button type="button" className="td-section-link" onClick={() => props.onView("brain")}>
                  Visualização de grafo ›
                </button>
                <span className="td-hint">
                  {projects.length} projetos · {graph?.nodes.length ?? "…"} notas
                </span>
              </div>
              <ProjectGraph data={graph} satellites={3} className="td-graph-svg" onProject={(name) => props.onOpenNote(name)} onNote={(path) => props.onOpenNote(path.split("/").pop()!.replace(/\.md$/, ""))} />
            </div>
            {suggestion ? (
              <div className="td-suggestion">
                <span className="td-suggestion-title">
                  <Icon d={ICON.spark} size={14} /> Precedente sugerido
                  {suggestions.length > 1 && <span className="td-hint"> · mais {suggestions.length - 1}</span>}
                </span>
                <SuggestionCard client={client} item={suggestion} showTarget compact onOpenNote={props.onOpenNote} onDone={props.onToast} onError={props.onToast} />
              </div>
            ) : (
              <div className="td-suggestion quiet">
                <span className="td-suggestion-title">
                  <Icon d={ICON.spark} size={14} /> Precedentes
                </span>
                <span className="td-hint">Nenhuma sugestão esperando você. Quando uma decisão de um projeto servir em outro, ela aparece aqui.</span>
              </div>
            )}
          </aside>
        </div>

        <div className="td-bottom">
          <section className="td-box" aria-label="Agentes">
            <button type="button" className="td-section-link" onClick={() => props.onView("agents")}>
              Agentes ›
            </button>
            <div className="td-agents">
              {desks.slice(0, 10).map((d) => (
                <button
                  key={d.agent.id}
                  type="button"
                  className="td-agent"
                  title={d.message}
                  onClick={() => (d.session && d.session.status !== "exited" ? props.onOpenSession(d.session.id) : props.onView("agents"))}
                >
                  <AgentSprite agent={d.agent} client={client} size={32} state={d.state} />
                  <span className="td-agent-name">{d.agent.name}</span>
                  <span className="td-agent-status" data-state={d.state}>
                    {d.status}
                  </span>
                </button>
              ))}
              {!desks.length && <span className="td-hint">Nenhum agente ainda.</span>}
            </div>
          </section>

          <section className="td-box" aria-label="Rotinas">
            <div className="td-box-head">
              <span className="td-box-title">Rotinas</span>
              <button type="button" className="td-link" onClick={() => setEditing("nova")}>
                + nova
              </button>
            </div>
            {(today?.slots ?? []).map(({ routine, slot, run: done }) => {
              const due = new Date(slot) <= now;
              const ok = !!done && ["rodou", "recuperada", "manual"].includes(done.status);
              return (
                <div key={routine.id} className="td-routine" data-done={ok ? "true" : undefined}>
                  <input type="checkbox" checked={ok} readOnly aria-label={ok ? "rodou" : "ainda não rodou"} />
                  <span className="mono td-routine-time">{clock(slot)}</span>
                  <button type="button" className="td-routine-name" onClick={() => setEditing(routine)} title={done?.detail || undefined}>
                    {routine.name}
                    {agentOf(routine.agent) && <span className="td-hint"> · {agentOf(routine.agent)!.name}</span>}
                    {done && !ok && <span className="td-routine-flag"> · {STATUS[done.status]?.label ?? done.status}</span>}
                  </button>
                  {done?.session && props.sessions.some((s) => s.id === done.session) ? (
                    <button type="button" className="td-link" onClick={() => props.onOpenSession(done.session)}>
                      abrir
                    </button>
                  ) : (
                    !ok && (
                      <button type="button" className="td-link" onClick={() => run(routine)}>
                        {due ? "rodar" : "agora"}
                      </button>
                    )
                  )}
                </div>
              );
            })}
            {routines
              .filter((r) => !(today?.slots ?? []).some((s) => s.routine.id === r.id))
              .slice(0, 4)
              .map((routine) => (
                <div key={routine.id} className="td-routine" data-later="true">
                  <input type="checkbox" checked={false} readOnly disabled aria-label="não é hoje" />
                  <span className="mono td-routine-time">{daysLabel(routine.days).slice(0, 3)}</span>
                  <button type="button" className="td-routine-name" onClick={() => setEditing(routine)}>
                    {routine.name}
                    <span className="td-hint"> · {routine.active ? nextLabel(routine.next) : "pausada"}</span>
                  </button>
                </div>
              ))}
            {!routines.length && <span className="td-hint">Nenhuma rotina. "+ nova" agenda um agente.</span>}
          </section>

          <section className="td-box" aria-label="Uso dos planos">
            <button type="button" className="td-section-link" onClick={props.onOpenAccounts}>
              Uso dos planos ›
            </button>
            {(["claude", "codex"] as const).flatMap((provider) =>
              props.accounts[provider].accounts.map((account) => {
                const limits = props.usage[provider][account.id];
                return (["five_hour", "seven_day"] as const).map((win) => (
                  <QuotaRow key={`${provider}-${account.id}-${win}`} provider={provider} label={win === "five_hour" ? "5h" : "7d"} name={props.accounts[provider].accounts.length > 1 ? account.name : ""} window={limits?.[win]} />
                ));
              }),
            )}
            {(spend.claude || spend.codex) && (
              <span className="td-hint td-spend">
                Hoje: {spend.claude ? `${money(spend.claude.custo)} se fosse pela API · ${tokens(spend.claude.tokens)} tokens do Claude` : ""}
                {spend.codex ? `${spend.claude ? " · " : ""}${tokens(spend.codex.tokens)} do Codex` : ""}
              </span>
            )}
          </section>

          <section className="td-box" aria-label="Conectores">
            <button type="button" className="td-section-link" onClick={() => props.onView("connectors")}>
              Conectores ›
            </button>
            {props.connectors.slice(0, 5).map((c) => (
              <div key={c.id} className="td-conn">
                <BrandIcon brand={brandFor(c.kind, [c.name, c.meta.servidor, c.meta.url, c.meta.comando])} size={22} />
                <span className="td-conn-name">{c.name}</span>
                <span className="td-conn-on">conectado</span>
              </div>
            ))}
            {props.connectors.length === 0 &&
              ["Slack", "ClickUp", "GitHub"].map((name) => (
                <div key={name} className="td-conn">
                  <BrandIcon brand={brandFor(name.toLowerCase())} size={22} />
                  <span className="td-conn-name">{name}</span>
                  <button type="button" className="td-link" onClick={() => props.onView("connectors")}>
                    conectar
                  </button>
                </div>
              ))}
          </section>
        </div>
      </div>

      {editing && (
        <div className="td-modal-back" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && setEditing(null)}>
          <RoutineEditor
            key={editing === "nova" ? "nova" : editing.id}
            client={client}
            agents={props.agents}
            routine={editing === "nova" ? null : editing}
            onClose={() => setEditing(null)}
            onToast={props.onToast}
          />
        </div>
      )}
    </div>
  );
}

function QuotaRow({ provider, label, name, window }: { provider: "claude" | "codex"; label: string; name: string; window?: RateWindow }) {
  const used = window?.used_pct ?? null;
  const hot = used != null && used >= 80;
  const reset = window ? resetIn(window.resets_at) : "";
  return (
    <div className="td-quota" title={name ? `${provider} · ${name}` : provider}>
      <KindIcon kind={provider} />
      <span>{label}</span>
      <span className="td-bar">
        <span style={{ width: `${Math.min(100, used ?? 0)}%`, background: hot ? "var(--warn)" : provider === "claude" ? "var(--acc)" : "var(--wait)" }} />
      </span>
      <span className="mono td-quota-text" style={hot ? { color: "var(--warn)" } : undefined}>
        {used == null ? "—" : `${pct(used)}${reset ? ` · ${reset}` : ""}`}
      </span>
    </div>
  );
}
