import { useEffect, useState } from "react";
import { openExternal } from "../lib/browser";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, money, shortPath } from "../lib/format";
import type { AgentEvent, AgentPanelItem, CliMcp, ConnectionTest, RegistryServer } from "../types";

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** Resultado do "testar" de uma conta, em uma linha. */
export function TestResult({ result }: { result: ConnectionTest }) {
  return (
    <span className="conn-test small" data-ok={result.ok ? "true" : "false"}>
      {result.ok ? "✓" : "✗"} {result.detalhe}
      {result.ferramentas != null && ` · ${result.ferramentas} ferramentas`} · {result.ms} ms
    </span>
  );
}

/** GitHub (v0.9.8): o MCP oficial do GitHub com o login do `gh` (ou um token colado). */
export function GithubSetup({ client, onDone, onToast }: { client: CoreClient; onDone: () => void; onToast: (m: string) => void }) {
  const [name, setName] = useState("GitHub");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const connect = async () => {
    setBusy(true);
    setError(null);
    try {
      const account = await client.connectGithub(name, token.trim());
      setToken("");
      onToast(`${account.name} conectado${account.meta.login ? ` como ${account.meta.login}` : ""}.`);
      onDone();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="conn-setup">
      <p className="small">
        Usa o MCP oficial do GitHub (issues, PRs, código, Actions). Sem token, a MÊTIS usa o login do <code>gh</code> deste Mac; para outra conta,
        cole um token pessoal.
      </p>
      <div className="conn-form">
        <label>
          <span className="small">Nome da conta</span>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          <span className="small">Token (opcional)</span>
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="vazio = o login do gh" autoComplete="off" spellCheck={false} />
        </label>
        {error && <p className="conn-error small">{error}</p>}
        <button type="button" className="btn primary" disabled={busy || !name.trim()} onClick={() => void connect()}>
          {busy ? "Conectando…" : "Conectar"}
        </button>
      </div>
    </div>
  );
}

/** Google (v0.9.8): Gmail, Agenda e Drive pelas APIs do Google, com o cliente OAuth do Pedro. */
export function GoogleSetup({ client, onToast }: { client: CoreClient; onToast: (m: string) => void }) {
  const [state, setState] = useState<{ configurado: boolean; client_id_fim: string } | null>(null);
  const [id, setId] = useState("");
  const [secret, setSecret] = useState("");
  const [name, setName] = useState("Google pessoal");
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    void client
      .googleClient()
      .then(setState)
      .catch((cause) => setError(message(cause)));
  }, [client]);

  const saveClient = async () => {
    setError(null);
    try {
      setState(await client.saveGoogleClient(id.trim(), secret.trim()));
      setId("");
      setSecret("");
      setEditing(false);
    } catch (cause) {
      setError(message(cause));
    }
  };

  const start = async () => {
    setError(null);
    try {
      const { url } = await client.startGoogle(name);
      await openExternal(url);
      setWaiting(true);
      onToast("Termine o login do Google no navegador; a conta aparece aqui sozinha.");
    } catch (cause) {
      setError(message(cause));
    }
  };

  if (!state) return <div className="conn-setup small">{error ?? "carregando…"}</div>;
  return (
    <div className="conn-setup">
      {(!state.configurado || editing) && (
        <>
          <ol className="conn-steps">
            <li>
              No{" "}
              <button type="button" className="link-btn" onClick={() => void openExternal("https://console.cloud.google.com/apis/credentials")}>
                Google Cloud → Credenciais
              </button>
              , crie um projeto (se não tiver) e ative as APIs do Gmail, do Google Calendar e do Google Drive.
            </li>
            <li>
              Em <em>Tela de permissão OAuth</em>, escolha <em>Externo</em>, adicione você como usuário de teste.
            </li>
            <li>
              Crie um <em>ID do cliente OAuth</em> do tipo <em>App para computador</em> e cole o ID e a chave secreta abaixo. Vale para todas
              as contas do Google que você conectar.
            </li>
          </ol>
          <div className="conn-form">
            <label>
              <span className="small">ID do cliente</span>
              <input value={id} onChange={(e) => setId(e.target.value)} placeholder="….apps.googleusercontent.com" spellCheck={false} />
            </label>
            <label>
              <span className="small">Chave secreta do cliente</span>
              <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="GOCSPX-…" autoComplete="off" spellCheck={false} />
            </label>
            <button type="button" className="btn primary" disabled={!id.trim() || !secret.trim()} onClick={() => void saveClient()}>
              Salvar o cliente
            </button>
          </div>
        </>
      )}
      {state.configurado && !editing && (
        <div className="conn-form">
          <p className="small">
            Cliente OAuth configurado (…{state.client_id_fim}).{" "}
            <button type="button" className="link-btn" onClick={() => setEditing(true)}>
              trocar
            </button>
          </p>
          <label>
            <span className="small">Nome da conta</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <button type="button" className="btn primary" disabled={!name.trim()} onClick={() => void start()}>
            Entrar no Google
          </button>
          {waiting && <p className="small conn-note">Esperando o retorno do navegador…</p>}
        </div>
      )}
      {error && <p className="conn-error small conn-wide">{error}</p>}
      <p className="small conn-note conn-wide">
        Ferramentas: buscar e ler e-mails, rascunho de e-mail, eventos da agenda, criar evento, buscar e ler arquivos do Drive. Rascunho e
        evento esperam a sua aprovação. A chave e os tokens ficam no Keychain.
      </p>
    </div>
  );
}

/** MCP próprio (v0.9.8): qualquer servidor MCP, por endereço (http) ou por comando (stdio). */
export function McpSetup({ client, onDone, onToast }: { client: CoreClient; onDone: () => void; onToast: (m: string) => void }) {
  const [transport, setTransport] = useState<"http" | "stdio">("http");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [auth, setAuth] = useState<"nenhuma" | "token" | "oauth">("oauth");
  const [token, setToken] = useState("");
  const [command, setCommand] = useState("");
  const [env, setEnv] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<RegistryServer[] | null>(null);
  const [searching, setSearching] = useState(false);

  const search = async () => {
    setSearching(true);
    setError(null);
    try {
      setFound((await client.mcpRegistry(query.trim())).servidores);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setSearching(false);
    }
  };

  const pick = (server: RegistryServer) => {
    setName(server.titulo || server.nome.split("/").pop() || server.nome);
    const remote = server.remotos.find((r) => r.tipo.includes("http")) ?? server.remotos[0];
    const pkg = server.pacotes[0];
    if (remote) {
      setTransport("http");
      setUrl(remote.url);
      setAuth("oauth");
    } else if (pkg) {
      setTransport("stdio");
      setCommand(pkg.comando);
      setEnv(pkg.env.map((e) => `${e.nome}=`).join("\n"));
    }
    setFound(null);
  };

  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      const answer =
        transport === "http"
          ? await client.addMcp({ nome: name.trim(), transporte: "http", url: url.trim(), auth, token: auth === "token" ? token.trim() : undefined })
          : await client.addMcp({ nome: name.trim(), transporte: "stdio", comando: command.trim(), env: env.trim() || undefined });
      if ("url" in answer && !("id" in answer)) {
        await openExternal(answer.url);
        onToast("Termine o login no navegador; a conta aparece aqui sozinha.");
      } else {
        onToast(`${name.trim()} conectado.`);
        onDone();
      }
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  };

  const ready = name.trim() && (transport === "http" ? url.trim() && (auth !== "token" || token.trim()) : command.trim());
  return (
    <div className="conn-setup conn-setup-one">
      <form
        className="conn-registry"
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar no catálogo oficial de MCP (ex.: linear, sentry, postgres)" />
        <button type="submit" className="btn" disabled={searching}>
          {searching ? "Buscando…" : "Buscar"}
        </button>
      </form>
      {found && (
        <ul className="registry-list">
          {found.length === 0 && <li className="small">Nada com isso no catálogo.</li>}
          {found.map((server) => (
            <li key={`${server.nome}@${server.versao}`}>
              <button type="button" onClick={() => pick(server)}>
                <span className="registry-name">
                  {server.titulo || server.nome} <span className="small mono">{server.versao}</span>
                </span>
                <span className="small">{server.descricao}</span>
                <span className="small mono">
                  {server.remotos.length ? `remoto · ${server.remotos[0].url}` : server.pacotes[0] ? server.pacotes[0].comando : "sem forma de instalar"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="segmented small-seg" role="radiogroup" aria-label="Transporte">
        <button type="button" role="radio" aria-checked={transport === "http"} onClick={() => setTransport("http")}>
          Endereço (http)
        </button>
        <button type="button" role="radio" aria-checked={transport === "stdio"} onClick={() => setTransport("stdio")}>
          Comando (stdio)
        </button>
      </div>
      <div className="conn-form">
        <label>
          <span className="small">Nome da conta</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="ex.: Linear" />
        </label>
        {transport === "http" ? (
          <>
            <label>
              <span className="small">Endereço do MCP</span>
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/mcp" spellCheck={false} />
            </label>
            <div className="segmented small-seg" role="radiogroup" aria-label="Autenticação">
              {(
                [
                  ["oauth", "Login no navegador"],
                  ["token", "Token"],
                  ["nenhuma", "Nenhuma"],
                ] as const
              ).map(([value, label]) => (
                <button key={value} type="button" role="radio" aria-checked={auth === value} onClick={() => setAuth(value)}>
                  {label}
                </button>
              ))}
            </div>
            {auth === "token" && (
              <label>
                <span className="small">Token (vai como Bearer)</span>
                <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" spellCheck={false} />
              </label>
            )}
          </>
        ) : (
          <>
            <label>
              <span className="small">Comando</span>
              <input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx -y @empresa/mcp-server" spellCheck={false} />
            </label>
            <label>
              <span className="small">Variáveis de ambiente (uma por linha, CHAVE=valor; ficam no Keychain)</span>
              <textarea value={env} onChange={(e) => setEnv(e.target.value)} rows={3} spellCheck={false} />
            </label>
          </>
        )}
        {error && <p className="conn-error small">{error}</p>}
        <button type="button" className="btn primary" disabled={busy || !ready} onClick={() => void add()}>
          {busy ? "Conferindo…" : transport === "http" && auth === "oauth" ? "Entrar e conectar" : "Conectar"}
        </button>
        <p className="small conn-note">A MÊTIS confere se o servidor responde e lista as ferramentas antes de salvar. Elas chegam aos agentes pela central.</p>
      </div>
    </div>
  );
}

/** Os MCPs que o Claude e o Codex já têm, e copiar um de um para o outro (v0.9.8). */
export function CliMcpCopy({ client, onToast }: { client: CoreClient; onToast: (m: string) => void }) {
  const [lists, setLists] = useState<{ claude: CliMcp[]; codex: CliMcp[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    void client
      .cliMcps()
      .then(setLists)
      .catch((cause) => setError(message(cause)));
  }, [client]);

  const copy = async (from: "claude" | "codex", to: "claude" | "codex", name: string) => {
    setBusy(`${from}:${name}`);
    try {
      const answer = await client.copyCliMcp(from, to, name);
      setLists({ claude: answer.claude, codex: answer.codex });
      const notes = answer.avisos?.length ? ` ${answer.avisos.join(" ")}` : "";
      onToast(`${name} copiado para o ${to === "claude" ? "Claude Code" : "Codex"}. Vale para as sessões novas.${notes}`);
    } catch (cause) {
      onToast(message(cause));
    } finally {
      setBusy(null);
    }
  };

  const column = (cli: "claude" | "codex") => {
    const other = cli === "claude" ? "codex" : "claude";
    const mine = lists?.[cli] ?? [];
    const theirs = new Set((lists?.[other] ?? []).map((m) => m.nome));
    return (
      <div className="cli-mcp-col">
        <div className="section-title">
          <span style={{ color: KIND_COLOR[cli] }}>{KIND_GLYPH[cli]}</span> {cli === "claude" ? "Claude Code" : "Codex"}
        </div>
        {mine.length === 0 && <p className="small conn-note">nenhum MCP próprio</p>}
        {mine.map((mcp) => (
          <div key={`${mcp.escopo}:${mcp.nome}`} className="cli-mcp">
            <span className="cli-mcp-name">
              {mcp.nome}
              <span className="small mono">
                {" "}
                {mcp.tipo} · {mcp.url ?? [mcp.comando, ...(mcp.args ?? [])].join(" ").slice(0, 60)}
                {mcp.escopo !== "usuario" ? ` · ${mcp.escopo.startsWith("projeto:") ? `projeto ${shortPath(mcp.escopo.slice(8))}` : mcp.escopo}` : ""}
              </span>
            </span>
            {mcp.escopo === "usuario" &&
              (theirs.has(mcp.nome) ? (
                <span className="small conn-note">também no {other === "claude" ? "Claude" : "Codex"}</span>
              ) : (
                <button type="button" className="link-btn" disabled={busy !== null} onClick={() => void copy(cli, other, mcp.nome)}>
                  {busy === `${cli}:${mcp.nome}` ? "copiando…" : `copiar para o ${other === "claude" ? "Claude" : "Codex"} ›`}
                </button>
              ))}
          </div>
        ))}
      </div>
    );
  };

  return (
    <section className="conn-card">
      <div className="conn-card-head">
        <div>
          <h3>MCPs do Claude e do Codex</h3>
          <p className="small">Os servidores configurados direto em cada CLI (fora da central). Copiar usa a própria CLI do outro lado; as chaves vão juntas e não aparecem aqui.</p>
        </div>
      </div>
      {error ? <p className="conn-error small">{error}</p> : !lists ? <p className="small conn-note">lendo as configurações…</p> : <div className="cli-mcp-cols">{column("claude")}{column("codex")}</div>}
    </section>
  );
}

const EVENT: Record<AgentEvent["kind"], { label: string; tone: string }> = {
  inicio: { label: "começou", tone: "run" },
  terminou: { label: "terminou", tone: "ok" },
  pergunta: { label: "precisa de você", tone: "warn" },
  saiu: { label: "saiu", tone: "off" },
  hibernou: { label: "hibernou", tone: "off" },
  acordou: { label: "acordou", tone: "run" },
};

function clock(ts: number): string {
  const date = new Date(ts * 1000);
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return date.toDateString() === new Date().toDateString() ? time : `${date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${time}`;
}

/**
 * Atividade dos agentes (v0.9.8): quem está aberto agora, há quanto tempo e quanto custou,
 * e a linha do tempo do que cada um fez (terminou, perguntou, saiu), com a prévia.
 */
export function AgentFeed({ client, events, onEvents, onOpenSession }: { client: CoreClient; events: AgentEvent[]; onEvents: (list: AgentEvent[]) => void; onOpenSession: (id: string) => void }) {
  const [agents, setAgents] = useState<AgentPanelItem[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => {
      void client.agentsPanel().then((answer) => alive && setAgents(answer.agentes)).catch(() => undefined);
    };
    load();
    void client.agentEvents(150).then((answer) => alive && onEvents(answer.eventos)).catch(() => undefined);
    const timer = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);
  const total = agents.reduce((sum, a) => sum + (a.custo_usd ?? 0), 0);
  return (
    <div className="agent-feed">
      <div className="section-title">
        Agentes abertos · {agents.length}
        {total > 0 && <span className="small"> · {money(total)} nas sessões do Claude</span>}
      </div>
      <table className="activity">
        <tbody>
          {agents.map((a) => (
            <tr key={a.id} className="clickable" onClick={() => onOpenSession(a.id)}>
              <td>
                <span style={{ color: KIND_COLOR[a.cli as "claude" | "codex"] }}>{KIND_GLYPH[a.cli as "claude" | "codex"]}</span> {a.titulo}
              </td>
              <td className="small mono">{shortPath(a.cwd)}</td>
              <td className="small">{a.coluna === "precisa" ? "precisa de você" : a.coluna}</td>
              <td className="small mono">{Math.round(a.duracao_s / 60)} min</td>
              <td className="small mono">{a.custo_usd != null ? money(a.custo_usd) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {agents.length === 0 && <p className="small conn-note">Nenhum Claude ou Codex aberto agora.</p>}
      <div className="section-title">O que os agentes fizeram</div>
      <ul className="event-list">
        {events.map((event) => (
          <li key={event.id}>
            <button type="button" onClick={() => onOpenSession(event.session)}>
              <span className="mono small event-time">{clock(event.ts)}</span>
              <span className="event-kind" data-tone={EVENT[event.kind]?.tone}>
                {EVENT[event.kind]?.label ?? event.kind}
              </span>
              <span className="event-who">{event.who}</span>
              {(event.preview || (event.title !== EVENT[event.kind]?.label ? event.title : "")) && (
                <span className="small event-preview">{event.preview || event.title}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
      {events.length === 0 && <p className="small conn-note">Nada ainda. Cada turno que um agente termina, cada pergunta e cada saída aparecem aqui.</p>}
    </div>
  );
}
