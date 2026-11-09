import { useEffect, useState } from "react";
import type { CoreClient } from "../lib/core";
import type { Pomodoro } from "../lib/pomodoro";
import type { Agent, Session, StudySummary } from "../types";
import { AgentSprite } from "./AgentSprite";
import { StudyActions, StudyMapView, StudyPlanView } from "./StudyParts";

interface Props {
  client: CoreClient | null;
  tick: number;
  pomodoro: Pomodoro;
  agents: Agent[];
  onLaunch: (agent: Agent) => void;
  /** v0.9.8: sessões com o Sócrates e abrir a nota de um conceito. */
  onSession: (session: Session) => void;
  onOpenNote: (title: string) => void;
}

const DAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];
const PRESETS: [number, number][] = [
  [25, 5],
  [50, 10],
  [15, 3],
];

export function StudyView({ client, tick, pomodoro, agents, onLaunch, onSession, onOpenNote }: Props) {
  const [summary, setSummary] = useState<StudySummary | null>(null);
  const [tab, setTab] = useState<"foco" | "mapa" | "plano">("foco");
  const [subject, setSubject] = useState(pomodoro.state.subject);
  const { state } = pomodoro;

  useEffect(() => {
    if (!client) return;
    void client.study().then(setSummary).catch(() => undefined);
  }, [client, tick, state.phase]);

  const max = Math.max(60, ...(summary?.week.map((d) => d.minutes) ?? [0]));
  const coach = agents.find((a) => a.id === "aurora");
  const tutor = agents.find((a) => a.id === "socrates");
  const running = state.phase !== "idle";

  const tabs = (
    <header className="kb-bar study-tabs">
      <div className="segmented" role="tablist" aria-label="Estudo">
        {(
          [
            ["foco", "Foco"],
            ["mapa", "O que eu sei"],
            ["plano", "Plano"],
          ] as const
        ).map(([value, label]) => (
          <button key={value} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>
            {label}
            {value === "mapa" && summary?.vencidos ? ` · ${summary.vencidos} para revisar` : ""}
          </button>
        ))}
      </div>
      {summary?.semana_atual && (
        <span className="kb-summary small mono">
          semana {summary.semana_atual.numero} · {summary.semana_atual.foco}
        </span>
      )}
    </header>
  );

  if (tab !== "foco" && client) {
    return (
      <div className="study-screen study-wide">
        {tabs}
        <StudyActions client={client} dueCount={summary?.vencidos ?? 0} onSession={onSession} />
        {tab === "mapa" ? (
          <StudyMapView client={client} tick={tick} onSession={onSession} onOpenNote={onOpenNote} />
        ) : (
          <StudyPlanView client={client} tick={tick} onOpenNote={onOpenNote} />
        )}
      </div>
    );
  }

  return (
    <div className="study-screen">
      {tabs}
      <section className="study-timer" data-phase={state.phase}>
        <div className="study-phase small">{state.phase === "focus" ? "Foco" : state.phase === "break" ? "Pausa" : "Pronto para estudar"}</div>
        <div className="study-clock mono">{pomodoro.label}</div>
        <input
          className="study-subject"
          value={running ? state.subject : subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="O que você vai estudar? (ex.: RAG com pgvector)"
          disabled={running}
        />
        <div className="study-controls">
          {!running ? (
            <>
              <div className="segmented" role="radiogroup" aria-label="Duração">
                {PRESETS.map(([f, b]) => (
                  <button key={f} type="button" role="radio" aria-checked={state.focusMin === f && state.breakMin === b} onClick={() => pomodoro.setDurations(f, b)}>
                    {f}/{b}
                  </button>
                ))}
              </div>
              <button type="button" className="btn primary" onClick={() => pomodoro.start(subject)}>
                Começar {state.focusMin} min
              </button>
            </>
          ) : (
            <button type="button" className="btn" onClick={pomodoro.stop}>
              {state.phase === "focus" ? "Parar (5 min ou mais contam)" : "Pular a pausa"}
            </button>
          )}
        </div>
        <p className="small study-note">Cada foco terminado vira uma linha em 📚 Estudo na nota do dia do Brain, que a Aurora lê às 20h50.</p>
      </section>

      <section className="study-board">
        <div className="section-title">Placar</div>
        {summary && (
          <>
            <div className="study-today">
              <div>
                <span className="study-big mono">{Math.round(summary.today)}</span> min hoje
                {summary.rest_day ? <span className="small"> · domingo é descanso</span> : <span className="small"> · piso {summary.floor} min</span>}
              </div>
              <div className="study-floor">
                <span style={{ width: `${Math.min(100, (summary.today / summary.floor) * 100)}%` }} />
              </div>
              {summary.risk && <p className="study-risk small">Ontem ficou abaixo do piso: hoje não pode passar em branco (nunca dois dias seguidos sem estudar).</p>}
            </div>
            <div className="study-week" aria-label="Minutos na semana">
              {summary.week.map((d, i) => (
                <div key={d.day} className="study-day" title={`${d.day}: ${Math.round(d.minutes)} min`}>
                  <span className="study-bar" style={{ height: `${(d.minutes / max) * 100}%` }} data-floor={d.minutes >= summary.floor ? "true" : undefined} />
                  <span className="small">{DAYS[i]}</span>
                </div>
              ))}
            </div>
            <div className="small study-stats mono">
              semana: {Math.round(summary.week_total)} min · sequência: {summary.streak} dia{summary.streak === 1 ? "" : "s"} no piso
            </div>
            {summary.recent.length > 0 && (
              <>
                <div className="section-title">Últimos blocos</div>
                {summary.recent.map((b) => (
                  <div key={b.id} className="small study-block">
                    <span className="mono">
                      {b.day.slice(8)}/{b.day.slice(5, 7)} {new Date(b.started * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
                    </span>{" "}
                    🍅 {Math.round(b.minutes)} min {b.subject && `· ${b.subject}`}
                  </div>
                ))}
              </>
            )}
          </>
        )}
        {client && (
          <>
            <div className="section-title">Sessões com o Sócrates</div>
            <StudyActions client={client} dueCount={summary?.vencidos ?? 0} onSession={onSession} />
          </>
        )}
        <div className="section-title">Agentes do estudo</div>
        <div className="study-agents">
          {[coach, tutor].filter(Boolean).map((agent) => (
            <button key={agent!.id} type="button" className="btn study-agent" onClick={() => onLaunch(agent!)}>
              <AgentSprite agent={agent!} client={client} size={22} />
              {agent!.id === "aurora" ? "Check-in com a Aurora" : `Estudar com ${agent!.name}`}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
