import { useEffect, useState } from "react";
import type { CoreClient } from "../lib/core";
import { openExternal } from "../lib/browser";
import type { ActivityItem, AgentEvent, Approval, ConnectionTest, ConnectorAccount } from "../types";
import { AgentFeed, CliMcpCopy, GithubSetup, GoogleSetup, McpSetup, TestResult } from "./ConnectorsExtra";

interface Props {
  client: CoreClient | null;
  accounts: ConnectorAccount[] | null;
  approvals: Approval[];
  activity: ActivityItem[];
  onActivity: (items: ActivityItem[]) => void;
  onDecide: (id: string, approve: boolean) => void;
  onToast: (message: string) => void;
  /** v0.9.8: feed dos agentes e ir ao terminal deles. */
  events: AgentEvent[];
  onEvents: (events: AgentEvent[]) => void;
  onOpenSession: (id: string) => void;
}

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

const STATUS_LABEL: Record<string, string> = {
  ok: "ok",
  erro: "erro",
  recusado: "recusado",
  expirou: "expirou",
  rodando: "rodando…",
  "aguardando você": "aguardando você",
};

function when(ts: number): string {
  const date = new Date(ts * 1000);
  const today = new Date();
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return date.toDateString() === today.toDateString() ? time : `${date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${time}`;
}

/** O que a chamada levou, em uma linha. */
function argsLine(args: ActivityItem["args"]): string {
  if (typeof args === "string") return args;
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" · ")
    .slice(0, 220);
}

export function ApprovalCard({ approval, onDecide }: { approval: Approval; onDecide: (id: string, approve: boolean) => void }) {
  return (
    <div className="approval" role="alertdialog" aria-label="Aprovação pendente">
      <div className="approval-head">
        <span className="approval-dot" />
        <strong>{approval.who}</strong> quer agir em <strong>{approval.account}</strong>
      </div>
      <div className="approval-what small">{approval.summary}</div>
      <div className="approval-tool small mono">{approval.tool}</div>
      <div className="approval-actions">
        <button type="button" className="btn" onClick={() => onDecide(approval.id, false)}>
          Recusar
        </button>
        <button type="button" className="btn primary" onClick={() => onDecide(approval.id, true)}>
          Aprovar
        </button>
      </div>
    </div>
  );
}

function SlackSetup({ client, onDone, onToast }: { client: CoreClient; onDone: () => void; onToast: (m: string) => void }) {
  const [manifest, setManifest] = useState("");
  const [name, setName] = useState("Slack pessoal");
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void client.slackManifest().then(setManifest).catch(() => undefined);
  }, [client]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(manifest);
      onToast("Manifesto copiado.");
    } catch {
      onToast("Não deu para copiar; selecione o texto do manifesto.");
    }
  };

  const connect = async () => {
    setBusy(true);
    setError(null);
    try {
      const account = await client.connectSlack(name, token, email);
      setToken("");
      onToast(`${account.name} conectado (${account.meta.team}).`);
      onDone();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="conn-setup">
      <ol className="conn-steps">
        <li>
          Copie o manifesto do app da MÊTIS.{" "}
          <button type="button" className="link-btn" onClick={() => void copy()} disabled={!manifest}>
            copiar manifesto
          </button>
          <details>
            <summary className="small">ver o manifesto</summary>
            <pre className="conn-manifest">{manifest}</pre>
          </details>
        </li>
        <li>
          Em{" "}
          <button type="button" className="link-btn" onClick={() => void openExternal("https://api.slack.com/apps?new_app=1")}>
            api.slack.com/apps
          </button>
          : <em>Create New App → From a manifest</em>, escolha o workspace, cole e crie. Depois <em>Install to Workspace</em>.
        </li>
        <li>
          Em <em>OAuth &amp; Permissions</em>, copie o <em>Bot User OAuth Token</em> (começa com <code>xoxb-</code>) e cole abaixo. Para o
          outro workspace, repita com o mesmo manifesto.
        </li>
      </ol>
      <div className="conn-form">
        <label>
          <span className="small">Nome da conta</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Slack pessoal" />
        </label>
        <label>
          <span className="small">Token do bot</span>
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="xoxb-…" autoComplete="off" spellCheck={false} />
        </label>
        <label>
          <span className="small">Seu e-mail nesse workspace</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} spellCheck={false} />
        </label>
        {error && <p className="conn-error small">{error}</p>}
        <button type="button" className="btn primary" disabled={busy || !token.trim() || !email.trim()} onClick={() => void connect()}>
          {busy ? "Conectando…" : "Conectar"}
        </button>
        <p className="small conn-note">O token vai para o Keychain do Mac; a MÊTIS não guarda em arquivo.</p>
      </div>
    </div>
  );
}

function OAuthSetup({ client, kind, label, onToast }: { client: CoreClient; kind: string; label: string; onToast: (m: string) => void }) {
  const [name, setName] = useState(`${label} pessoal`);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setError(null);
    try {
      const { url } = await client.startOAuth(kind, name);
      await openExternal(url);
      setWaiting(true);
      onToast(`Termine o login do ${label} no navegador; a conta aparece aqui sozinha.`);
    } catch (cause) {
      setError(message(cause));
    }
  };

  return (
    <div className="conn-setup">
      <p className="small">
        O login abre no navegador, direto no {label}. Para outra conta (ex.: a da Seller Pro), conecte de novo com outro nome e entre com a
        outra conta.
      </p>
      <div className="conn-form">
        <label>
          <span className="small">Nome da conta</span>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        {error && <p className="conn-error small">{error}</p>}
        <button type="button" className="btn primary" disabled={!name.trim()} onClick={() => void start()}>
          Entrar no {label}
        </button>
        {waiting && <p className="small conn-note">Esperando o retorno do navegador…</p>}
      </div>
    </div>
  );
}

function AccountRow({ client, account, onToast }: { client: CoreClient; account: ConnectorAccount; onToast: (m: string) => void }) {
  const [confirm, setConfirm] = useState(false);
  const [test, setTest] = useState<ConnectionTest | "testando" | null>(null);
  const patch = (changes: { approve_writes?: boolean; reminders?: boolean }) =>
    void client.patchConnector(account.id, changes).catch((cause) => onToast(message(cause)));
  const tools = account.meta.ferramentas ?? account.meta.tools;
  const where =
    account.kind === "slack"
      ? `${account.meta.team} · DM com ${account.meta.user_name || account.meta.email}`
      : account.kind === "google"
        ? `${account.meta.email ?? ""} · Gmail, Agenda e Drive`
        : account.kind === "github"
          ? `${account.meta.login ? `@${account.meta.login} · ` : ""}${tools ?? "?"} ferramentas`
          : account.kind === "mcp"
            ? `${account.meta.transporte ?? ""} · ${account.meta.url ?? account.meta.comando ?? ""} · ${tools ?? "?"} ferramentas`
            : `${tools ?? "?"} ferramentas`;
  return (
    <div className="conn-account">
      <div className="conn-account-main">
        <div className="conn-account-name">
          {account.name}
          {account.reminders && <span className="chip">lembretes</span>}
        </div>
        <div className="small mono conn-account-meta">
          {account.id} · {where}
        </div>
      </div>
      <label className="conn-toggle small" title="Mensagem para outras pessoas, criar ou mudar algo: espera o seu sim">
        <input type="checkbox" checked={account.approve_writes} onChange={(e) => patch({ approve_writes: e.target.checked })} />
        pedir aprovação para escrever
      </label>
      {account.kind === "slack" && !account.reminders && (
        <button type="button" className="link-btn" onClick={() => patch({ reminders: true })}>
          usar para lembretes
        </button>
      )}
      <button
        type="button"
        className="link-btn"
        disabled={test === "testando"}
        onClick={() => {
          setTest("testando");
          void client
            .checkConnector(account.id)
            .then(setTest)
            .catch((cause) => (setTest(null), onToast(message(cause))));
        }}
      >
        {test === "testando" ? "testando…" : "testar"}
      </button>
      {confirm ? (
        <span className="conn-confirm small">
          tirar a conta?{" "}
          <button
            type="button"
            className="link-btn danger"
            onClick={() =>
              void client
                .deleteConnector(account.id)
                .then(() => onToast(`${account.name} desconectado.`))
                .catch((cause) => onToast(message(cause)))
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
          remover
        </button>
      )}
      {test && test !== "testando" && <TestResult result={test} />}
    </div>
  );
}

export function ReminderTry({ client, onToast }: { client: CoreClient; onToast: (m: string) => void }) {
  const [text, setText] = useState("Teste da MÊTIS: este lembrete tocou no iPhone?");
  const [whenText, setWhen] = useState("em 2 min");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="conn-reminder"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        void client
          .remind(text, whenText)
          .then((r) => onToast(r.message))
          .catch((cause) => onToast(message(cause)))
          .finally(() => setBusy(false));
      }}
    >
      <div className="section-title">Agendar um lembrete</div>
      <div className="conn-reminder-row">
        <input value={text} onChange={(e) => setText(e.target.value)} aria-label="Texto do lembrete" />
        <input value={whenText} onChange={(e) => setWhen(e.target.value)} aria-label="Quando" className="conn-when" />
        <button type="submit" className="btn" disabled={busy || !text.trim() || !whenText.trim()}>
          Agendar
        </button>
      </div>
      <p className="small conn-note">
        "sexta 9h", "amanhã 14:30", "13/11 9h", "em 20 min". O bot manda na sua DM do Slack na hora, mesmo com o Mac dormindo. No terminal:{" "}
        <code>metis lembrete "texto" sexta 9h</code>.
      </p>
    </form>
  );
}

export function ConnectorsView({ client, accounts, approvals, activity, onActivity, onDecide, onToast, events, onEvents, onOpenSession }: Props) {
  const [tab, setTab] = useState<"contas" | "atividade">("contas");
  const [setup, setSetup] = useState<string | null>(null);

  useEffect(() => {
    if (!client || tab !== "atividade") return;
    void client.activity().then(onActivity).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, tab]);

  if (!client) return <div className="connectors-screen" />;
  const list = accounts ?? [];
  const services: { kind: string; label: string; description: string }[] = [
    { kind: "slack", label: "Slack", description: "Bot da MÊTIS no workspace: avisos e lembretes na sua DM, que tocam no iPhone." },
    { kind: "clickup", label: "ClickUp", description: "Tarefas, documentos e chat pelo MCP oficial do ClickUp. A lista de um projeto aparece no kanban." },
    { kind: "notion", label: "Notion", description: "Páginas e bancos de dados pelo MCP oficial do Notion." },
    { kind: "github", label: "GitHub", description: "Issues, PRs, código e Actions pelo MCP oficial do GitHub, com o login do gh." },
    { kind: "google", label: "Google", description: "Gmail, Agenda e Drive: buscar e ler, rascunho de e-mail e evento novo (com a sua aprovação)." },
    { kind: "mcp", label: "MCP próprio", description: "Qualquer servidor MCP, por endereço ou por comando, ou um do catálogo oficial." },
  ];

  return (
    <div className="connectors-screen">
      <header className="kb-bar">
        <div className="segmented" role="tablist" aria-label="Conectores">
          <button type="button" role="tab" aria-selected={tab === "contas"} onClick={() => setTab("contas")}>
            Contas
          </button>
          <button type="button" role="tab" aria-selected={tab === "atividade"} onClick={() => setTab("atividade")}>
            Atividade{approvals.length ? ` · ${approvals.length} aguardando` : ""}
          </button>
        </div>
        <span className="kb-summary small mono">
          {list.length} conta{list.length === 1 ? "" : "s"} · a central entrega as ferramentas aos agentes como o MCP "metis"
        </span>
      </header>

      {tab === "contas" ? (
        <div className="conn-body">
          {services.map((service) => {
            const mine = list.filter((a) => a.kind === service.kind);
            return (
              <section key={service.kind} className="conn-card">
                <div className="conn-card-head">
                  <div>
                    <h3>{service.label}</h3>
                    <p className="small">{service.description}</p>
                  </div>
                  <button type="button" className="btn" onClick={() => setSetup(setup === service.kind ? null : service.kind)}>
                    {setup === service.kind ? "Fechar" : mine.length ? "Conectar outra conta" : "Conectar"}
                  </button>
                </div>
                {mine.map((account) => (
                  <AccountRow key={account.id} client={client} account={account} onToast={onToast} />
                ))}
                {setup === service.kind &&
                  (service.kind === "slack" ? (
                    <SlackSetup client={client} onDone={() => setSetup(null)} onToast={onToast} />
                  ) : service.kind === "github" ? (
                    <GithubSetup client={client} onDone={() => setSetup(null)} onToast={onToast} />
                  ) : service.kind === "google" ? (
                    <GoogleSetup client={client} onToast={onToast} />
                  ) : service.kind === "mcp" ? (
                    <McpSetup client={client} onDone={() => setSetup(null)} onToast={onToast} />
                  ) : (
                    <OAuthSetup client={client} kind={service.kind} label={service.label} onToast={onToast} />
                  ))}
              </section>
            );
          })}
          {list.some((a) => a.kind === "slack") && <ReminderTry client={client} onToast={onToast} />}
          <CliMcpCopy client={client} onToast={onToast} />
        </div>
      ) : (
        <div className="conn-body">
          {approvals.map((approval) => (
            <ApprovalCard key={approval.id} approval={approval} onDecide={onDecide} />
          ))}
          <AgentFeed client={client} events={events} onEvents={onEvents} onOpenSession={onOpenSession} />
          <div className="section-title">Central de MCP</div>
          <table className="activity">
            <thead>
              <tr>
                <th>Quando</th>
                <th>Quem</th>
                <th>Ferramenta</th>
                <th>O quê</th>
                <th>Resultado</th>
              </tr>
            </thead>
            <tbody>
              {activity.map((item) => (
                <tr key={item.id}>
                  <td className="mono small">{when(item.ts)}</td>
                  <td>{item.who}</td>
                  <td className="mono small">{item.tool}</td>
                  <td className="small">{argsLine(item.args)}</td>
                  <td>
                    <span className="activity-status" data-status={item.status}>
                      {STATUS_LABEL[item.status] ?? item.status}
                    </span>
                    {item.detail && <div className="small activity-detail">{item.detail.slice(0, 200)}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!activity.length && <p className="small conn-note">Nada ainda. Quando um agente usar a central (Brain, kanban, Slack, ClickUp), aparece aqui.</p>}
        </div>
      )}
    </div>
  );
}
