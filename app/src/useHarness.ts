import { useCallback, useEffect, useRef, useState } from "react";
import { CoreClient, getCoreInfo, type NewSessionOptions } from "./lib/core";
import type { Accounts, ActivityItem, Agent, Approval, Connection, ConnectorAccount, CoreEvent, Project, Session, SessionKind, Usage } from "./types";

const NO_ACCOUNTS: Accounts = { claude: { active: "padrao", accounts: [] }, codex: { active: "padrao", accounts: [] } };

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

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
  /** Último pedido de aba do navegador vindo do núcleo (`metis web`). */
  const [webRequest, setWebRequest] = useState<{ id: number; url: string; cwd: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const retry = useRef<number | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;

    const apply = (event: CoreEvent) => {
      switch (event.type) {
        case "hello":
          setSessions(Object.fromEntries(event.sessions.map((s) => [s.id, s])));
          setUsage(event.usage);
          setAccounts(event.accounts);
          setProjects(event.projects ?? []);
          setAgents(event.agents ?? []);
          break;
        case "session.created":
          setSessions((all) => ({ ...all, [event.session.id]: event.session }));
          break;
        case "session.closed":
          setSessions((all) => {
            const { [event.id]: _closed, ...rest } = all;
            return rest;
          });
          break;
        case "session.status":
          setSessions((all) => (all[event.id] ? { ...all, [event.id]: { ...all[event.id], status: event.status } } : all));
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
        case "approval":
          setApprovals((all) => [...all.filter((a) => a.id !== event.approval.id), event.approval]);
          break;
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
        setClient(core);
        listen(core);
        void core
          .connectors()
          .then((c) => !cancelled && setConnectors(c.accounts))
          .catch(() => undefined);
        void core
          .approvals()
          .then((list) => !cancelled && setApprovals(list))
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
    webRequest,
    bumpWorktrees: () => setWorktreesTick((n) => n + 1),
    error,
    setError,
    create,
    close,
    run,
  };
}
