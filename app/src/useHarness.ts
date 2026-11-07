import { useCallback, useEffect, useRef, useState } from "react";
import { CoreClient, getCoreInfo, type NewSessionOptions } from "./lib/core";
import type { Accounts, Connection, CoreEvent, Session, SessionKind, Usage } from "./types";

const NO_ACCOUNTS: Accounts = { claude: { active: "padrao", accounts: [] }, codex: { active: "padrao", accounts: [] } };

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** Estado do app ligado ao núcleo: sessões, contas, uso do plano e conexão. */
export function useHarness() {
  const [client, setClient] = useState<CoreClient | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [sessions, setSessions] = useState<Record<string, Session>>({});
  const [usage, setUsage] = useState<Usage>({ claude: {}, codex: {} });
  const [accounts, setAccounts] = useState<Accounts>(NO_ACCOUNTS);
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
  return { client, connection, sessions: ordered, usage, accounts, error, setError, create, close, run };
}
