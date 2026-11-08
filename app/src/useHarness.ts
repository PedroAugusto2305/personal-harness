import { useCallback, useEffect, useRef, useState } from "react";
import { CoreClient, getCoreInfo, type NewSessionOptions } from "./lib/core";
import { useInbox, type NoticeInput } from "./lib/inbox";
import type {
  Accounts,
  ActivityItem,
  Agent,
  Approval,
  Connection,
  ConnectorAccount,
  CoreEvent,
  Prefs,
  Project,
  Session,
  SessionKind,
  SessionStatus,
  Usage,
} from "./types";

const NO_ACCOUNTS: Accounts = { claude: { active: "padrao", accounts: [] }, codex: { active: "padrao", accounts: [] } };

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** O que importa de cada sessão para montar o aviso. */
interface Seen {
  status: SessionStatus;
  kind: SessionKind;
  title: string;
  cwd: string;
}

const folderName = (cwd: string) => cwd.replace(/\/+$/, "").split("/").pop() || cwd;

/** O aviso que um hook do agente pede (a mesma regra do núcleo, em `app.py`): Stop = terminou;
 *  Notification = espera você (pedido de licença ou pergunta), menos o "estou esperando sua
 *  resposta" que o Claude manda depois de um minuto parado, porque o Stop já avisou. */
function hookNotice(id: string, seen: Seen, name: string, text?: string | null): NoticeInput | null {
  if (seen.kind === "shell") return null;
  if (name === "Stop") return { kind: "terminou", titulo: `${seen.title} terminou`, texto: folderName(seen.cwd), sessao: id };
  if (name === "Notification" && !(text ?? "").toLowerCase().startsWith("claude is waiting for your input")) {
    return { kind: "espera", titulo: `${seen.title} espera você`, texto: text || folderName(seen.cwd), sessao: id };
  }
  return null;
}

/** Estado do app ligado ao núcleo: sessões, contas, uso do plano e conexão. */
export function useHarness() {
  const [client, setClient] = useState<CoreClient | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [sessions, setSessions] = useState<Record<string, Session>>({});
  const [usage, setUsage] = useState<Usage>({ claude: {}, codex: {} });
  const [accounts, setAccounts] = useState<Accounts>(NO_ACCOUNTS);
  const [projects, setProjects] = useState<Project[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  /** Sobe a cada mudança de worktrees num projeto, para quem lista recarregar. */
  const [worktreesTick, setWorktreesTick] = useState(0);
  /** Contas de conector (galeria) e o que espera aprovação do Pedro. */
  const [connectors, setConnectors] = useState<ConnectorAccount[] | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  /** Últimas chamadas da central de MCP, mais nova primeiro (a tela de Atividade completa com a API). */
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  /** Sobe quando uma rotina muda ou roda; a última execução vira aviso na tela. */
  const [routinesTick, setRoutinesTick] = useState(0);
  const [routineRun, setRoutineRun] = useState<{ id: number; name: string; status: string; session?: string; detail: string } | null>(null);
  /** Sobe quando uma nota do Brain muda pela MÊTIS (kanban, `metis tarefa`), para as telas recarregarem. */
  const [brainTick, setBrainTick] = useState(0);
  /** Sobe quando uma sugestão de precedente nasce ou é decidida (v0.8). */
  const [suggestionsTick, setSuggestionsTick] = useState(0);
  /** Por sessão: sobe quando ela vê uma nota nova do Brain (mini-mapa). */
  const [sessionMapTicks, setSessionMapTicks] = useState<Record<string, number>>({});
  /** Automações (v0.9): sobe a cada evento do motor; o último evento diz qual execução mudou. */
  const [automationTick, setAutomationTick] = useState(0);
  const [automationEvent, setAutomationEvent] = useState<Extract<CoreEvent, { type: `automation.${string}` }> | null>(null);
  /** Último pedido de aba do navegador vindo do núcleo (`metis web`). */
  const [webRequest, setWebRequest] = useState<{ id: number; url: string; cwd: string | null } | null>(null);
  /** Versão do núcleo em execução (v0.9.2): a janela se liga a um núcleo que pode ser mais velho que ela. */
  const [coreVersion, setCoreVersion] = useState<string | null>(null);
  /** Ajustes de agentes e avisos (v0.9.2); null até o núcleo responder. */
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const retry = useRef<number | undefined>(undefined);
  const inbox = useInbox(client, prefs);
  const notify = useRef(inbox.push);
  notify.current = inbox.push;
  /** Último estado de cada sessão, fora do React: o evento traz só o estado novo. */
  const seen = useRef<Record<string, Seen>>({});
  /** Aprovações já avisadas (o núcleo pode publicar a mesma de novo). */
  const seenApprovals = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;

    const apply = (event: CoreEvent) => {
      switch (event.type) {
        case "hello":
          setSessions(Object.fromEntries(event.sessions.map((s) => [s.id, s])));
          // Ao (re)ligar, o estado atual vira a base; o que mudou com a janela desligada não avisa.
          seen.current = Object.fromEntries(event.sessions.map((s) => [s.id, { status: s.status, kind: s.kind, title: s.title, cwd: s.cwd }]));
          if (event.version) setCoreVersion(event.version);
          // Núcleo de antes da v0.9.2 não manda a versão no hello; o /health sempre mandou.
          else if (coreRef)
            void fetch(`${coreRef.info.url}/health`)
              .then((response) => response.json())
              .then((data: { version?: unknown }) => setCoreVersion(typeof data.version === "string" ? data.version : null))
              .catch(() => undefined);
          setUsage(event.usage);
          setAccounts(event.accounts);
          setProjects(event.projects ?? []);
          setAgents(event.agents ?? []);
          break;
        case "session.created": {
          const s = event.session;
          seen.current[s.id] = { status: s.status, kind: s.kind, title: s.title, cwd: s.cwd };
          setSessions((all) => ({ ...all, [s.id]: s }));
          break;
        }
        case "session.closed":
          delete seen.current[event.id];
          setSessions((all) => {
            const { [event.id]: _closed, ...rest } = all;
            return rest;
          });
          break;
        case "session.hook": {
          const known = seen.current[event.id];
          const notice = known ? hookNotice(event.id, known, event.name, event.message) : null;
          if (notice) notify.current(notice);
          break;
        }
        case "session.status": {
          const before = seen.current[event.id];
          if (before) seen.current[event.id] = { ...before, status: event.status };
          setSessions((all) => (all[event.id] ? { ...all, [event.id]: { ...all[event.id], status: event.status } } : all));
          break;
        }
        case "prefs":
          setPrefs(event.prefs);
          break;
        case "session.statusline":
          setSessions((all) =>
            all[event.id] ? { ...all, [event.id]: { ...all[event.id], statusline: event.statusline } } : all,
          );
          break;
        case "usage":
          setUsage(event.usage);
          break;
        case "accounts":
          setAccounts(event.accounts);
          break;
        case "projects":
          setProjects(event.projects);
          break;
        case "worktrees":
          setWorktreesTick((n) => n + 1);
          break;
        case "agents":
          setAgents(event.agents);
          break;
        case "connectors":
          setConnectors(event.accounts);
          break;
        case "approval": {
          const approval = event.approval;
          if (!seenApprovals.current.has(approval.id)) {
            seenApprovals.current.add(approval.id);
            notify.current({
              kind: "aprovacao",
              titulo: `${approval.who || "Um agente"} pede aprovação`,
              texto: approval.summary || approval.tool,
              aprovacao: approval.id,
              sessao: approval.session || undefined,
            });
          }
          setApprovals((all) => [...all.filter((a) => a.id !== approval.id), approval]);
          break;
        }
        case "approval.done":
          setApprovals((all) => all.filter((a) => a.id !== event.id));
          break;
        case "activity":
          setActivity((all) => [event.item, ...all.filter((a) => a.id !== event.item.id)].slice(0, 300));
          break;
        case "routines":
          setRoutinesTick((n) => n + 1);
          break;
        case "study":
          setRoutinesTick((n) => n + 1);
          break;
        case "routine.run":
          setRoutinesTick((n) => n + 1);
          setRoutineRun({ id: event.run.id, name: event.routine.name, status: event.run.status, session: event.session, detail: event.run.detail });
          break;
        case "brain.changed":
          setBrainTick((n) => n + 1);
          break;
        case "suggestions":
          setSuggestionsTick((n) => n + 1);
          if (event.decided) setBrainTick((n) => n + 1);
          break;
        case "automation.run":
          if (event.status === "erro") void automationNotice(event.automation, event.error ?? "");
          setAutomationEvent(event);
          setAutomationTick((n) => n + 1);
          break;
        case "automation.step":
        case "automation.published":
        case "automation.error":
          setAutomationEvent(event);
          setAutomationTick((n) => n + 1);
          break;
        case "brain.session":
          setSessionMapTicks((all) => ({ ...all, [event.session]: (all[event.session] ?? 0) + 1 }));
          break;
        case "open-web":
          setWebRequest((last) => ({ id: (last?.id ?? 0) + 1, url: event.url, cwd: event.cwd }));
          break;
        case "ports":
          setSessions((all) => {
            const next = { ...all };
            for (const [id, ports] of Object.entries(event.ports)) {
              if (next[id]) next[id] = { ...next[id], ports };
            }
            return next;
          });
          break;
      }
    };

    /** O evento traz o id da automação; o aviso fica melhor com o nome. */
    const names: Record<string, string> = {};
    let coreRef: CoreClient | null = null;
    const automationNotice = async (id: string, detail: string) => {
      if (!names[id] && coreRef) {
        try {
          for (const item of await coreRef.automations()) names[item.id] = item.nome;
        } catch {
          // sem a lista: o aviso sai com o id
        }
      }
      notify.current({ kind: "erro", titulo: `Automação ${names[id] ?? id} deu erro`, texto: detail || "veja em Automações → Execuções", automacao: id });
    };

    const listen = (core: CoreClient) => {
      if (cancelled) return;
      socket = new WebSocket(core.wsUrl("/events"));
      socket.onopen = () => setConnection("online");
      socket.onmessage = (event) => apply(JSON.parse(event.data) as CoreEvent);
      socket.onclose = () => {
        if (cancelled) return;
        setConnection("offline");
        retry.current = window.setTimeout(() => listen(core), 1500);
      };
    };

    (async () => {
      try {
        const core = new CoreClient(await getCoreInfo());
        await core.waitUntilHealthy();
        if (cancelled) return;
        coreRef = core;
        setClient(core);
        listen(core);
        void core
          .prefs()
          .then((value) => !cancelled && setPrefs(value))
          .catch(() => undefined);
        void core
          .connectors()
          .then((c) => !cancelled && setConnectors(c.accounts))
          .catch(() => undefined);
        void core
          .approvals()
          .then((list) => {
            if (cancelled) return;
            // As que já esperavam antes de a janela abrir aparecem no cartão, sem aviso novo.
            for (const a of list) seenApprovals.current.add(a.id);
            setApprovals(list);
          })
          .catch(() => undefined);
      } catch (cause) {
        if (!cancelled) {
          setConnection("offline");
          setError(message(cause));
        }
      }
    })();

    return () => {
      cancelled = true;
      window.clearTimeout(retry.current);
      socket?.close();
    };
  }, []);

  const create = useCallback(
    async (kind: SessionKind, cwd: string, options: NewSessionOptions = {}): Promise<Session | null> => {
      if (!client) return null;
      setError(null);
      try {
        const session = await client.createSession(kind, cwd, options);
        setSessions((all) => ({ ...all, [session.id]: session }));
        return session;
      } catch (cause) {
        setError(message(cause));
        return null;
      }
    },
    [client],
  );

  const close = useCallback(
    async (id: string) => {
      if (!client) return;
      await client.closeSession(id).catch(() => undefined);
      setSessions((all) => {
        const { [id]: _closed, ...rest } = all;
        return rest;
      });
    },
    [client],
  );

  /** Sessão que o núcleo criou por outro caminho (reiniciar, passar o trabalho, retomar): entra na lista já. */
  const adopt = useCallback((session: Session) => {
    seen.current[session.id] ??= { status: session.status, kind: session.kind, title: session.title, cwd: session.cwd };
    // Se o evento do núcleo chegou antes da resposta, a cópia dele é a mais nova: fica.
    setSessions((all) => (all[session.id] ? all : { ...all, [session.id]: session }));
  }, []);

  /** Ajustes: muda na tela na hora e grava; se o núcleo recusar, volta ao que ele tem. */
  const savePrefs = useCallback(
    async (changes: Partial<Omit<Prefs, "avisos">> & { avisos?: Partial<Prefs["avisos"]> }) => {
      if (!client) return;
      setPrefs((current) => (current ? { ...current, ...changes, avisos: { ...current.avisos, ...changes.avisos } } : current));
      try {
        setPrefs(await client.savePrefs(changes as Partial<Prefs>));
      } catch (cause) {
        setError(message(cause));
        void client
          .prefs()
          .then(setPrefs)
          .catch(() => undefined);
      }
    },
    [client],
  );

  /** Roda uma ação no núcleo e mostra o erro na barra lateral se falhar. */
  const run = useCallback(
    async <T,>(action: (core: CoreClient) => Promise<T>): Promise<T | null> => {
      if (!client) return null;
      setError(null);
      try {
        return await action(client);
      } catch (cause) {
        setError(message(cause));
        return null;
      }
    },
    [client],
  );

  const ordered = Object.values(sessions).sort((a, b) => a.created_at - b.created_at);
  return {
    client,
    connection,
    sessions: ordered,
    usage,
    accounts,
    projects,
    agents,
    worktreesTick,
    connectors,
    routinesTick,
    routineRun,
    approvals,
    activity,
    setActivity,
    brainTick,
    bumpBrain: () => setBrainTick((n) => n + 1),
    suggestionsTick,
    bumpSuggestions: () => setSuggestionsTick((n) => n + 1),
    sessionMapTicks,
    automationTick,
    automationEvent,
    webRequest,
    coreVersion,
    prefs,
    savePrefs,
    inbox,
    adopt,
    bumpWorktrees: () => setWorktreesTick((n) => n + 1),
    error,
    setError,
    create,
    close,
    run,
  };
}
