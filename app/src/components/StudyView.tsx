import { useEffect, useMemo, useState } from "react";
import { KindIcon } from "./KindIcon";
import { ICON, Icon } from "../icons";
import { openExternal } from "../lib/browser";
import type { CoreClient } from "../lib/core";
import type { Pomodoro } from "../lib/pomodoro";
import type { Agent, BrainNote, BrowserProfile, Session, StudySummary, ThemeName } from "../types";
import { AgentSprite } from "./AgentSprite";
import type { WebInfo } from "./BrowserView";
import { StudyChat } from "./StudyChat";
import { StudyNotebook } from "./StudyNotebook";
import { StudyNote, markAnswer, type QuestionBlock } from "./StudyNote";
import { StudyActions, StudyMapView, StudyPlanView } from "./StudyParts";
import { VaultTree } from "./VaultTree";
import "./brain.css";
import "./study.css";

interface Props {
  client: CoreClient | null;
  tick: number;
  pomodoro: Pomodoro;
  agents: Agent[];
  onLaunch: (agent: Agent) => void;
  /** v0.9.8: sessões com o Sócrates e abrir a nota de um conceito. */
  onSession: (session: Session) => void;
  onOpenNote: (title: string) => void;
  /** v0.9.9: o Estudo do mockup (nota no centro e o Sócrates ao lado). */
  sessions: Session[];
  onAdopt: (session: Session) => void;
  onOpenSession: (id: string) => void;
  onError: (message: string) => void;
  /** v1.3.0: a conversa rica do Sócrates e o NotebookLM no navegador embutido. */
  theme: ThemeName;
  notebookTick: number;
  webInfo: WebInfo | undefined;
  /** Algo da interface por cima (⌘K, diálogo…): a página nativa do NotebookLM some. */
  covered: boolean;
  browserProfiles: BrowserProfile[];
  defaultProfile: string;
  onWebDesign: (on: boolean) => void;
  onWebDevice: (id: string) => void;
  onLink: (url: string, external: boolean) => void;
  onOpenFile: (path: string, cwd: string) => void;
}

const DAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];
const PRESETS: [number, number][] = [
  [25, 5],
  [50, 10],
  [15, 3],
];
type Fixed = "foco" | "mapa" | "plano" | "notebooklm";
const FIXED: Fixed[] = ["foco", "mapa", "plano", "notebooklm"];
const TABS_KEY = "harness.study.tabs";
const ACTIVE_KEY = "harness.study.active";
const WIDE_KEY = "harness.study.chat.wide";

function stored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

const titleOf = (path: string) => path.split("/").pop()!.replace(/\.md$/, "");

export function StudyView(props: Props) {
  const { client, tick, pomodoro, agents, onLaunch, onOpenNote, sessions, onAdopt, onOpenSession, onError } = props;
  const [summary, setSummary] = useState<StudySummary | null>(null);
  const [project, setProject] = useState<string | null>(null);
  const [tabs, setTabs] = useState<string[]>(() => stored<string[]>(TABS_KEY, []).slice(0, 10));
  const [active, setActive] = useState<string>(() => stored<string>(ACTIVE_KEY, "foco"));
  const [note, setNote] = useState<BrainNote | null>(null);
  const [subject, setSubject] = useState(pomodoro.state.subject);
  const [peekId, setPeekId] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [wide, setWide] = useState<boolean>(() => stored(WIDE_KEY, false));
  const { state } = pomodoro;

  useEffect(() => {
    try {
      localStorage.setItem(WIDE_KEY, JSON.stringify(wide));
    } catch {
      // sem armazenamento
    }
  }, [wide]);

  useEffect(() => {
    if (!client) return;
    void client.study().then(setSummary).catch(() => undefined);
    void client
      .studyMap()
      .then((m) => setProject(m.projeto))
      .catch(() => setProject(""));
  }, [client, tick, state.phase]);

  useEffect(() => {
    try {
      localStorage.setItem(TABS_KEY, JSON.stringify(tabs));
      localStorage.setItem(ACTIVE_KEY, JSON.stringify(active));
    } catch {
      // sem armazenamento
    }
  }, [tabs, active]);

  const isNote = !FIXED.includes(active as Fixed);

  // A nota da aba ativa (e de novo quando o Sócrates escreve nela: estudo.mudou vira tick).
  useEffect(() => {
    if (!client || !isNote) return;
    let alive = true;
    client
      .brainNote({ path: active })
      .then((n) => alive && setNote(n))
      .catch(() => {
        if (!alive) return;
        setTabs((all) => all.filter((p) => p !== active));
        setActive("foco");
      });
    return () => {
      alive = false;
    };
  }, [client, active, isNote, tick]);

  const openPath = (path: string) => {
    setTabs((all) => (all.includes(path) ? all : [...all.slice(-9), path]));
    setActive(path);
  };
  const openTitle = async (title: string) => {
    if (!client) return;
    try {
      const found = await client.brainNote({ title });
      openPath(found.path);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    }
  };
  const closeTab = (path: string) => {
    setTabs((all) => {
      const next = all.filter((p) => p !== path);
      if (active === path) setActive(next[next.length - 1] ?? "foco");
      return next;
    });
  };

  const tutor = agents.find((a) => a.id === "socrates") ?? agents.find((a) => a.name.toLowerCase().startsWith("sócrates")) ?? null;
  const coach = agents.find((a) => a.id === "aurora") ?? null;
  // v1.3.0: o Sócrates padrão (sem agente na galeria) também conta: agente socrates ou sessão aberta pelo Estudo.
  const tutorSessions = useMemo(
    () =>
      sessions
        .filter((s) => s.status !== "exited" && (s.agent === "socrates" || (tutor && s.agent === tutor.id) || s.tag === "estudo" || /sócrates/i.test(s.title)))
        .sort((a, b) => b.created_at - a.created_at),
    [sessions, tutor],
  );
  const peek = tutorSessions.find((s) => s.id === peekId) ?? tutorSessions[0] ?? null;
  const background = sessions.filter((s) => (s.kind === "claude" || s.kind === "codex") && s.status === "working" && s.id !== peek?.id).slice(0, 3);

  const onLink = (event: React.MouseEvent) => {
    const link = (event.target as HTMLElement).closest("a");
    if (!link) return;
    event.preventDefault();
    if (link.classList.contains("wikilink") && link.dataset.note) void openTitle(link.dataset.note);
    else if (/^https?:\/\//.test(link.getAttribute("href") ?? "")) void openExternal(link.getAttribute("href")!);
  };

  const answer = async (block: QuestionBlock, option: number, confidence: number, reasoning: string) => {
    if (!client || !peek || !note) return;
    const letter = String.fromCharCode(65 + option);
    const level = Math.min(5, Math.max(1, Math.round(confidence / 25) + 1));
    const reply = [
      `Minha resposta à pergunta «${block.question}» (nota ${note.title}): ${letter}) ${block.options[option].text}.`,
      `Confiança: ${level} de 5 (${confidence}%).`,
      reasoning.trim() ? `Raciocínio: ${reasoning.trim()}` : "",
    ]
      .filter(Boolean)
      .join(" ");
    try {
      await client.sendToSession(peek.id, reply);
      const current = await client.brainNoteText(note.path);
      const next = markAnswer(current.texto, block.index, block.options[option].text, `${letter} · confiança ${confidence}%${reasoning.trim() ? ` · ${reasoning.trim()}` : ""}`);
      if (next !== current.texto) await client.saveBrainNote(note.path, next, current.hash);
      setNote(await client.brainNote({ path: note.path }));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  /** v1.3.0: conversa de estudo com o Sócrates (modo visual e, se houver, o caderno do NotebookLM). */
  const startChat = async (text?: string) => {
    if (!client || starting) return;
    setStarting(true);
    try {
      const session = await client.studySession("conversa");
      onAdopt(session);
      setPeekId(session.id);
      if (text) setDraft(text);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setStarting(false);
    }
  };

  /** Pergunta sugerida pelo NotebookLM: vai para a caixa do Sócrates (abre uma conversa se não houver). */
  const askTutor = (text: string) => {
    if (peek && peek.status !== "exited") setDraft(text);
    else void startChat(text);
  };

  const max = Math.max(60, ...(summary?.week.map((d) => d.minutes) ?? [0]));
  const running = state.phase !== "idle";
  const week = summary?.semana_atual;
  const crumbs = note && isNote ? note.path.split("/").slice(1, -1).join(" / ") : "";

  return (
    <div className="sv">
      <section className="sv-left" aria-label="Arquivos do estudo">
        {project !== null && (
          <VaultTree
            key={project}
            client={client}
            tick={tick}
            current={isNote ? active : null}
            onOpen={openPath}
            storageKey="harness.study.tree"
            initialOpen={project ? ["01-PROJETOS", `01-PROJETOS/${project}`, `01-PROJETOS/${project}/conceitos`] : ["01-PROJETOS"]}
          />
        )}
        <div className="sv-score">
          <div className="sv-score-row">
            <span className="mono sv-big">{Math.round(summary?.today ?? 0)}</span>
            <span className="small">min hoje{summary && !summary.rest_day ? ` · piso ${summary.floor}` : " · descanso"}</span>
          </div>
          {summary && (
            <>
              <div className="study-floor">
                <span style={{ width: `${Math.min(100, (summary.today / Math.max(1, summary.floor)) * 100)}%` }} />
              </div>
              <div className="sv-week" aria-label="Minutos na semana">
                {summary.week.map((d, i) => (
                  <span key={d.day} className="sv-day" title={`${d.day}: ${Math.round(d.minutes)} min`}>
                    <span className="sv-bar" style={{ height: `${(d.minutes / max) * 100}%` }} data-floor={d.minutes >= summary.floor ? "true" : undefined} />
                    <span className="sv-day-label">{DAYS[i][0]}</span>
                  </span>
                ))}
              </div>
              {summary.risk && <p className="sv-risk small">Ontem ficou abaixo do piso: hoje não pode passar em branco.</p>}
            </>
          )}
        </div>
        {background.length > 0 && (
          <div className="sv-bg">
            <span className="small sv-bg-title">Em segundo plano</span>
            {background.map((s) => {
              const agent = agents.find((a) => a.id === s.agent);
              return (
                <button key={s.id} type="button" className="sv-bg-row" onClick={() => onOpenSession(s.id)}>
                  {agent ? <AgentSprite agent={agent} client={client} size={18} state="working" /> : <KindIcon kind="claude" size={14} />}
                  <span className="sv-bg-name">{agent?.name ?? s.title}</span>
                  <span className="small mono">{s.status_desde ? `${Math.max(0, Math.round((Date.now() / 1000 - s.status_desde) / 60))} min` : ""}</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <main className="sv-center">
        <div className="bv-tabs" role="tablist" aria-label="Abas do estudo">
          {(
            [
              ["foco", "Foco"],
              ["mapa", summary?.vencidos ? `O que eu sei · ${summary.vencidos}` : "O que eu sei"],
              ["plano", "Plano"],
              ["notebooklm", "NotebookLM"],
            ] as const
          ).map(([key, label]) => (
            <button key={key} type="button" role="tab" className="bv-tab" aria-selected={active === key} onClick={() => setActive(key)}>
              {label}
            </button>
          ))}
          {tabs.map((path) => (
            <span key={path} className="bv-tab" role="tab" aria-selected={active === path}>
              <button type="button" className="bv-tab-name" onClick={() => setActive(path)} title={path}>
                {titleOf(path)}
              </button>
              <button type="button" className="bv-tab-close" aria-label={`Fechar ${titleOf(path)}`} onClick={() => closeTab(path)}>
                ×
              </button>
            </span>
          ))}
          <span className="grow" />
          {running && (
            <button type="button" className="sv-pomo mono" onClick={() => setActive("foco")} title="Pomodoro em andamento">
              {state.phase === "focus" ? "foco" : "pausa"} {pomodoro.label}
            </button>
          )}
        </div>

        {active === "foco" ? (
          <section className="study-timer sv-timer" data-phase={state.phase}>
            {week && (
              <div className="sv-week-line small mono">
                semana {week.numero} · {week.foco}
              </div>
            )}
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
            <p className="small study-note">Cada foco terminado vira uma linha em 📚 Estudo na nota do dia do Brain, que a Aurora lê às 20h50. Abra a nota da aula à esquerda para estudar ao lado do Sócrates.</p>
          </section>
        ) : active === "mapa" && client ? (
          <div className="sv-scroll">
            <StudyMapView client={client} tick={tick} onSession={onAdopt} onOpenNote={(title) => void openTitle(title)} />
          </div>
        ) : active === "plano" && client ? (
          <div className="sv-scroll">
            <StudyPlanView client={client} tick={tick} onOpenNote={(title) => void openTitle(title)} />
          </div>
        ) : active === "notebooklm" && client ? (
          <StudyNotebook
            client={client}
            tick={props.notebookTick}
            shown={!props.covered}
            info={props.webInfo}
            profiles={props.browserProfiles}
            defaultProfile={props.defaultProfile}
            onDesign={props.onWebDesign}
            onDevice={props.onWebDevice}
            onAskTutor={askTutor}
            onError={onError}
          />
        ) : note && note.path === active ? (
          <article className="sv-note">
            <div className="sv-note-bar">
              <span className="sv-crumbs">
                {crumbs} {crumbs && "/"} <b>{note.title}</b>
              </span>
              <span className="grow" />
              <button type="button" className="sv-icon" title="Abrir no Brain" aria-label="Abrir no Brain" onClick={() => onOpenNote(note.title)}>
                <Icon d={ICON.graph} size={13} />
              </button>
              <button type="button" className="sv-icon" title="Abrir no Obsidian" aria-label="Abrir no Obsidian" onClick={() => client && void client.openInObsidian(note.path).catch((c) => onError(String(c)))}>
                <Icon d={ICON.note} size={13} />
              </button>
            </div>
            <div className="sv-note-body">
              <h1 className="sv-note-title">{note.title}</h1>
              <StudyNote note={note} canAnswer={!!peek} onAnswer={answer} onLink={onLink} />
            </div>
          </article>
        ) : (
          <p className="sv-loading small">abrindo a nota…</p>
        )}
      </main>

      <aside className="sv-right" aria-label="Sócrates" data-wide={wide || undefined}>
        <div className="sv-tutor-head">
          {tutor ? <AgentSprite agent={tutor} client={client} size={28} state={peek ? (peek.status === "working" ? "working" : peek.status === "waiting" ? "waiting" : "idle") : "idle"} /> : null}
          <span className="sv-tutor-who">
            <b>{tutor?.name ?? "Sócrates"}</b>
            <span className="small mono">
              {peek ? `${peek.kind}${peek.statusline?.model ? ` · ${peek.statusline.model}` : ""}` : "tutor"}
              {week ? ` · semana ${week.numero}` : ""}
            </span>
          </span>
          <span className="grow" />
          {peek && (
            <span className="sv-tutor-state" data-status={peek.status}>
              {peek.status === "working" ? "trabalhando" : peek.status === "waiting" ? "esperando você" : "parado"}
            </span>
          )}
          {peek && (
            <button type="button" className="sv-icon" title="Nova conversa de estudo" aria-label="Nova conversa de estudo" disabled={starting} onClick={() => void startChat()}>
              <Icon d={ICON.plus} size={13} />
            </button>
          )}
          <button type="button" className="sv-icon" aria-pressed={wide} title={wide ? "Estreitar a conversa" : "Alargar a conversa (diagramas e imagens maiores)"} aria-label="Largura da conversa" onClick={() => setWide((v) => !v)}>
            <Icon d={ICON.split} size={13} />
          </button>
        </div>
        {tutorSessions.length > 1 && (
          <div className="sv-tutor-tabs">
            {tutorSessions.map((s, i) => (
              <button key={s.id} type="button" aria-pressed={s.id === peek?.id} onClick={() => setPeekId(s.id)}>
                {i === 0 ? "última" : s.title.replace(/^Sócrates\s*·?\s*/i, "") || `sessão ${i + 1}`}
              </button>
            ))}
          </div>
        )}
        {client && peek ? (
          <StudyChat
            client={client}
            session={peek}
            theme={props.theme}
            visible
            draft={draft}
            onDraftUsed={() => setDraft(null)}
            onError={onError}
            onOpenTerminal={() => onOpenSession(peek.id)}
            onLink={props.onLink}
            onOpenFile={(path) => props.onOpenFile(path, peek.cwd)}
          />
        ) : (
          <div className="sv-start">
            <p className="small">
              Converse com o Sócrates: ele explica em passos, com diagramas, tabelas e imagens desenhados na conversa, e faz perguntas de fixação. Com um caderno escolhido na aba NotebookLM, ele responde com base nas fontes dele.
            </p>
            {client && (
              <button type="button" className="btn primary" disabled={starting} onClick={() => void startChat()}>
                <Icon d={ICON.chat} size={14} />
                {starting ? "Abrindo…" : "Conversar com o Sócrates"}
              </button>
            )}
            <p className="small">Ou uma sessão guiada: ele pergunta antes de explicar, escreve as perguntas na nota do conceito e registra cada resposta no mapa.</p>
            {client && <StudyActions client={client} dueCount={summary?.vencidos ?? 0} onSession={onAdopt} />}
            {client && note && isNote && (
              <button
                type="button"
                className="btn"
                onClick={() =>
                  void client
                    .studySession("aprender", note.title)
                    .then(onAdopt)
                    .catch((c) => onError(String(c)))
                }
              >
                Aprender «{note.title}»
              </button>
            )}
            {coach && (
              <div className="sv-start-agents">
                <button type="button" className="btn" onClick={() => onLaunch(coach)}>
                  <AgentSprite agent={coach} client={client} size={18} />
                  Check-in com a Aurora
                </button>
              </div>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
