import { useEffect, useMemo, useState } from "react";
import { RoomScene } from "./RoomScene";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import type { Accounts, Agent, AgentEvent, ConnectorAccount, Routine, Session } from "../types";
import { AgentSprite, type SpriteState } from "./AgentSprite";
import "./room.css";

/**
 * Sala dos agentes (v0.9.9, mockup "Agentes · E Sala"): cada agente numa mesa, com o balão do
 * que está fazendo e a sprite no estado da sessão; clicar numa mesa mostra o agente à direita.
 * Editar e Novo agente abrem o formulário de sempre no lugar da sala.
 */

const STATE_COLOR: Record<SpriteState, string> = {
  waiting: "var(--wait)",
  working: "var(--run)",
  idle: "var(--mut)",
  sleeping: "var(--mut)",
  done: "var(--acct)",
  error: "var(--err)",
};

const LEGEND: { state: SpriteState; label: string }[] = [
  { state: "idle", label: "parado" },
  { state: "working", label: "trabalhando" },
  { state: "waiting", label: "esperando você" },
  { state: "sleeping", label: "dormindo" },
  { state: "done", label: "concluiu" },
  { state: "error", label: "erro" },
];

const WEEKDAY = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const DAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];

/** "sex 22h10", "hoje 20h50" ou "amanhã 9h00". */
function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  const hour = `${date.getHours()}h${String(date.getMinutes()).padStart(2, "0")}`;
  if (date.toDateString() === today.toDateString()) return `hoje ${hour}`;
  if (date.toDateString() === tomorrow.toDateString()) return `amanhã ${hour}`;
  return `${WEEKDAY[date.getDay()]} ${hour}`;
}

function routineLabel(routine: Routine): string {
  const days = routine.days.length === 7 ? "todo dia" : routine.days.length === 6 && !routine.days.includes(6) ? "seg a sáb" : routine.days.map((d) => DAYS[d]).join(", ");
  return `${routine.time} · ${days}`;
}

const clip = (text: string, size: number) => {
  const flat = text.replace(/\s+/g, " ").replace(/[*_`#>]/g, "").trim();
  return flat.length > size ? `${flat.slice(0, size - 1).trimEnd()}…` : flat;
};

const minutes = (since?: number) => (since ? Math.max(0, Math.round((Date.now() / 1000 - since) / 60)) : 0);

/** A sessão que conta para o agente: a que espera você, senão a que trabalha, senão a mais nova. */
function sessionOf(agent: Agent, sessions: Session[]): Session | null {
  const own = sessions.filter((s) => s.agent === agent.id);
  const rank = (s: Session) => (s.status === "waiting" ? 3 : s.status === "working" ? 2 : s.status === "exited" ? 0 : 1);
  return own.sort((a, b) => rank(b) - rank(a) || b.created_at - a.created_at)[0] ?? null;
}

interface Desk {
  agent: Agent;
  session: Session | null;
  state: SpriteState;
  status: string;
  bubble: string;
  message: string;
  routine: Routine | null;
}

export function deskOf(agent: Agent, sessions: Session[], events: AgentEvent[], routines: Routine[]): Desk {
  const session = sessionOf(agent, sessions);
  const sessionIds = new Set(sessions.filter((s) => s.agent === agent.id).map((s) => s.id));
  const last = events.find((e) => sessionIds.has(e.session) || e.who === agent.name || e.who.startsWith(`${agent.name} `)) ?? null;
  const routine = routines.find((r) => r.active && (r.agent === agent.id || r.agent === agent.name)) ?? null;
  const preview = last?.preview ? clip(last.preview, 160) : "";
  let state: SpriteState = "idle";
  let status = "parado";
  let bubble = preview ? clip(preview, 26) : "livre agora";
  if (session?.status === "waiting") {
    state = "waiting";
    status = session.atencao === "terminou" ? "terminou · esperando você" : "esperando você";
    if (!preview) bubble = "esperando você";
  } else if (session?.status === "working") {
    state = "working";
    const min = minutes(session.status_desde);
    status = min ? `trabalhando · ${min} min` : "trabalhando";
    if (!preview) bubble = "trabalhando…";
  } else if (session?.status === "exited") {
    state = session.exit_code ? "error" : "done";
    status = session.exit_code ? `erro · saiu com código ${session.exit_code}` : "concluiu";
  } else if (session) {
    status = session.hibernando ? "hibernando" : "parado";
  } else if (routine) {
    state = "sleeping";
    const next = when(routine.next);
    status = "dormindo";
    bubble = next ? `zzz… ${next}` : "zzz…";
  }
  const message = preview || (routine ? `Dormindo até ${when(routine.next) || routine.time}: ${routine.name}.` : "Sem conversa ainda. Abra o terminal para chamar.");
  return { agent, session, state, status, bubble, message, routine };
}

/** Primeiro parágrafo do papel: o que o agente faz. */
function mission(agent: Agent): string {
  const text = agent.prompt.replace(/^#.*$/gm, "").trim();
  const first = text.split(/\n\s*\n/)[0] ?? "";
  return clip(first || agent.description || "Sem papel escrito.", 260);
}

interface Props {
  client: CoreClient | null;
  agents: Agent[];
  accounts: Accounts;
  sessions: Session[];
  events: AgentEvent[];
  connectors: ConnectorAccount[];
  tick: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onEdit: (id: string) => void;
  onNew: () => void;
  onImport: () => void;
  onLaunch: (agent: Agent) => void;
  onOpenSession: (id: string) => void;
  /** v0.9.9: apagar o agente (com confirmação; o arquivo vai para a lixeira dos agentes). */
  onDelete: (agent: Agent) => void;
  notice: string | null;
}

export function AgentsRoom(props: Props) {
  const { client, agents, sessions, tick } = props;
  const [routines, setRoutines] = useState<Routine[]>([]);
  /** Os eventos já gravados (os novos chegam ao vivo por props.events). */
  const [history, setHistory] = useState<AgentEvent[]>([]);
  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .agentEvents(200)
      .then((answer) => alive && setHistory(answer.eventos))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [client]);
  const events = useMemo(() => {
    const byId = new Map<number, AgentEvent>();
    for (const e of [...props.events, ...history]) if (!byId.has(e.id)) byId.set(e.id, e);
    return [...byId.values()].sort((a, b) => b.ts - a.ts);
  }, [props.events, history]);
  const [, setNow] = useState(0);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .routines()
      .then((r) => alive && setRoutines(r.routines))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [client, tick]);

  // Os minutos de "trabalhando · N min" andam sozinhos.
  useEffect(() => {
    const timer = window.setInterval(() => setNow((n) => n + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const desks = useMemo(() => agents.map((agent) => deskOf(agent, sessions, events, routines)), [agents, sessions, events, routines]);
  const current = desks.find((d) => d.agent.id === props.selected) ?? null;
  const waiting = desks.filter((d) => d.state === "waiting").length;
  const failed = desks.filter((d) => d.state === "error").length;

  return (
    <div className="room-screen">
      <nav className="room-files" aria-label="Arquivos de agentes">
        <span className="room-files-head">agentes/</span>
        {desks.map((d) => (
          <div key={d.agent.id} className="room-file-row">
            <button
              type="button"
              className="room-file"
              aria-current={d.agent.id === props.selected ? "true" : undefined}
              onClick={() => props.onSelect(d.agent.id)}
            >
              <span className="room-dot" style={{ background: STATE_COLOR[d.state] }} />
              <span className="room-file-name">{d.agent.id}.md</span>
              <span className="room-file-cli">{d.agent.cli}</span>
            </button>
            <button type="button" className="room-file-del" title={`Apagar ${d.agent.name}`} aria-label={`Apagar ${d.agent.name}`} onClick={() => props.onDelete(d.agent)}>
              <Icon d={ICON.trash} size={13} />
            </button>
          </div>
        ))}
        <button type="button" className="room-new" onClick={props.onNew}>
          + Novo agente
        </button>
        <button type="button" className="room-import small" onClick={props.onImport} title="Lê ~/Documents/Brain/.maestri/roles e os terminais do Maestri">
          Importar do Maestri
        </button>
        {props.notice && <p className="small room-notice">{props.notice}</p>}
      </nav>

      <main className="room-main">
        <div className="room-head">
          <span className="room-title">Sala dos agentes</span>
          <span className="room-sub">
            {agents.length} {agents.length === 1 ? "agente" : "agentes"}
            {waiting > 0 && <span style={{ color: "var(--wait)" }}> · {waiting} esperando você</span>}
            {failed > 0 && <span style={{ color: "var(--err)" }}> · {failed} com erro</span>}
          </span>
          <span className="room-hint small">clique num agente para ver · arraste para mover (perto de uma mesa, ele senta) · dois cliques abrem o terminal</span>
        </div>
        <div className="room-floor">
          {agents.length === 0 && (
            <p className="room-empty">
              Agente é um papel com prompt próprio que abre o Claude Code ou o Codex já sabendo o que fazer. Crie um em "+ Novo agente" ou importe
              os do Maestri.
            </p>
          )}
          {agents.length > 0 && (
            <RoomScene
              client={client}
              selected={props.selected}
              onSelect={props.onSelect}
              onOpen={(agent) => {
                const desk = desks.find((d) => d.agent.id === agent.id);
                if (desk?.session) props.onOpenSession(desk.session.id);
                else props.onLaunch(agent);
              }}
              items={desks.map((d) => ({
                agent: d.agent,
                state: d.state,
                bubble: d.bubble,
                loud: d.state === "waiting" || d.state === "error",
                color: STATE_COLOR[d.state],
                status: d.status,
              }))}
            />
          )}
        </div>
        <section className="room-legend" aria-label="Estados da sprite">
          <span className="room-legend-title">Estados</span>
          {agents[0] &&
            LEGEND.map((l) => (
              <span key={l.state} className="room-legend-item">
                <AgentSprite agent={agents[0]} client={client} size={28} state={l.state} />
                <span style={{ color: STATE_COLOR[l.state] }}>{l.label}</span>
              </span>
            ))}
        </section>
      </main>

      <aside className="room-aside" aria-label={current ? `${current.agent.id}.md` : "Agente"}>
        <div className="room-aside-tabs">
          {current ? (
            <div className="room-aside-tab">
              <span>{current.agent.id}.md</span>
              <button type="button" className="room-aside-close" aria-label="Fechar" onClick={() => props.onSelect(null)}>
                ×
              </button>
            </div>
          ) : (
            <div className="room-aside-tab muted">nenhum agente aberto</div>
          )}
        </div>
        {current ? <AgentCard desk={current} {...props} /> : <p className="room-aside-empty small">Clique num agente na sala (ou num arquivo à esquerda) para ver o agente: o que ele faz, a conta, a rotina e o que disse por último.</p>}
      </aside>
    </div>
  );
}

function AgentCard({ desk, client, accounts, connectors, onEdit, onLaunch, onOpenSession, onDelete }: Props & { desk: Desk }) {
  const { agent, session, routine } = desk;
  const accountName =
    agent.cli === "outra" ? "—" : agent.account ? (accounts[agent.cli].accounts.find((a) => a.id === agent.account)?.name ?? agent.account) : "a conta em uso";
  const allowed =
    agent.cli === "outra"
      ? "nenhum (outra CLI)"
      : agent.connectors === "nenhum"
        ? "nenhum"
        : agent.connectors
          ? agent.connectors
              .split(",")
              .map((id) => connectors.find((c) => c.id === id)?.name ?? id)
              .join(" · ")
          : connectors.length
            ? `todas as contas (${connectors.length})`
            : "todas as contas";
  const props: [string, string, boolean?][] = [
    ["cli", agent.cli === "outra" ? (agent.command || "outra") : agent.cli],
    ["conta", accountName],
    ["modelo", agent.model || "padrão da CLI"],
    ["rotina", routine ? routineLabel(routine) : "nenhuma"],
    ["conectores", allowed, true],
    ["dor", agent.pain || "—"],
  ];
  return (
    <div className="room-card">
      <div className="room-card-hero">
        <AgentSprite agent={agent} client={client} size={80} state={desk.state} />
        <div className="room-card-who">
          <span className="room-card-name">{agent.name}</span>
          <span className="room-card-role">{agent.description}</span>
          <span className="mono room-card-status" style={{ color: STATE_COLOR[desk.state] }}>
            {desk.status}
          </span>
        </div>
      </div>
      <div className="room-props">
        <span className="room-label">Propriedades</span>
        {props.map(([key, value, link]) => (
          <div key={key} className="room-prop">
            <span className="room-prop-key">{key}</span>
            <span className="room-prop-value" style={link ? { color: "var(--acct)" } : undefined}>
              {value}
            </span>
          </div>
        ))}
      </div>
      <div className="room-mission">
        <span className="room-mission-title">Missão</span>
        <span className="room-mission-text">{mission(agent)}</span>
      </div>
      <div className="room-msg mono">● {desk.message}</div>
      <div className="room-actions">
        <button type="button" className="room-open" onClick={() => (session && session.status !== "exited" ? onOpenSession(session.id) : onLaunch(agent))}>
          {session && session.status !== "exited" ? "Ir para o terminal" : "Abrir terminal"}
        </button>
        <button type="button" className="room-edit" onClick={() => onEdit(agent.id)}>
          Editar
        </button>
        <button type="button" className="room-delete" title={`Apagar ${agent.name}`} aria-label={`Apagar ${agent.name}`} onClick={() => onDelete(agent)}>
          <Icon d={ICON.trash} size={15} />
        </button>
      </div>
      <div className="room-sprite">
        <div className="room-sprite-head">
          <span className="room-sprite-title">Sprite{agent.sprite ? "" : " · busto padrão"}</span>
          <button type="button" className="room-link" onClick={() => onEdit(agent.id)}>
            gerar outras
          </button>
        </div>
        <div className="room-sprite-row">
          <span className="room-sprite-cell" data-on="true">
            <AgentSprite agent={agent} client={client} size={48} />
          </span>
          <span className="small room-sprite-note">
            {agent.sprite ? "Desenhada pelo GPT no modelo da MÊTIS (ou enviada em PNG) e pixelizada na grade do desenho." : "Sem sprite própria: o busto greco-romano na cor do agente. Em Editar, crie uma no modelo."}
          </span>
        </div>
      </div>
    </div>
  );
}
