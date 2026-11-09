import { BrandIcon, brandFor, type Brand } from "./BrandIcon";
import { useEffect, useMemo, useState } from "react";
import type { CoreClient } from "../lib/core";
import { openExternal } from "../lib/browser";
import { shortPath } from "../lib/format";
import type { ActivityItem, Agent, AgentEvent, Approval, ConnectionTest, ConnectorAccount, ConnectorTool, ToolMode } from "../types";
import { AgentFeed, CliMcpCopy, GithubSetup, GoogleSetup, McpSetup, TestResult } from "./ConnectorsExtra";
import "./connectors.css";

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
  /** v0.9.9: Permissões por agente. */
  agents: Agent[];
  onSaveAgent: (agent: Agent, connectors: string) => void;
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


const SERVICES: { kind: ConnectorAccount["kind"]; label: string; kindLabel: string; description: string }[] = [
  { kind: "slack", label: "Slack", kindLabel: "bot da MÊTIS", description: "Bot da MÊTIS no workspace: avisos e lembretes na sua DM, que tocam no iPhone." },
  { kind: "clickup", label: "ClickUp", kindLabel: "MCP remoto com login", description: "Tarefas, documentos e chat pelo MCP oficial do ClickUp. A lista de um projeto aparece no kanban." },
  { kind: "notion", label: "Notion", kindLabel: "MCP remoto com login", description: "Páginas e bancos de dados pelo MCP oficial do Notion." },
  { kind: "github", label: "GitHub", kindLabel: "gh CLI + MCP", description: "Issues, PRs, código e Actions pelo MCP oficial do GitHub, com o login do gh." },
  { kind: "google", label: "Google", kindLabel: "Gmail, Agenda e Drive", description: "Buscar e ler, rascunho de e-mail e evento novo (com a sua aprovação)." },
  { kind: "mcp", label: "MCP próprio", kindLabel: "URL ou comando", description: "Qualquer servidor MCP, por endereço ou por comando, ou um do catálogo oficial." },
];

const MODE_LABEL: Record<ToolMode, string> = { livre: "livre", aprovacao: "pede aprovação", desligada: "desligada" };

type Selection = { type: "account"; id: string } | { type: "setup"; kind: string } | { type: "brain" } | null;

/** O logo da conta: pelo tipo, e o MCP próprio pelo nome, servidor, endereço ou comando. */
const accountBrand = (account: ConnectorAccount) =>
  brandFor(account.kind, [account.name, account.meta.servidor, account.meta.url, account.meta.comando]);

function serviceOf(kind: string) {
  return SERVICES.find((s) => s.kind === kind) ?? { kind, label: kind, kindLabel: "", description: "" };
}

/** O que cabe no cartão: equipe, e-mail, login ou endereço da conta. */
function accountChips(account: ConnectorAccount): string[] {
  const meta = account.meta;
  const out: string[] = [];
  if (meta.team) out.push(String(meta.team));
  if (meta.login) out.push(`@${meta.login}`);
  if (meta.email && account.kind !== "slack") out.push(String(meta.email));
  if (account.kind === "mcp" && (meta.transporte as string)) out.push(String(meta.transporte));
  if (account.reminders) out.push("lembretes");
  return out.slice(0, 3);
}

function accountSummary(account: ConnectorAccount): string {
  const tools = account.meta.ferramentas ?? account.meta.tools;
  const parts = [] as string[];
  if (tools != null) parts.push(`${tools} ferramentas`);
  if (account.kind === "slack") parts.push(`DM com ${account.meta.user_name || account.meta.email || "você"}`);
  if (account.kind === "mcp") parts.push(shortPath(String(account.meta.url ?? account.meta.comando ?? "")));
  parts.push(account.approve_writes ? "escrita pede aprovação" : "escrita livre");
  return parts.filter(Boolean).join(" · ");
}

/** Quem pode usar a conta pela central: "" = todas, "nenhum" = nenhuma, senão a lista. */
function allows(agent: Agent, accountId: string): boolean {
  if (agent.cli === "outra" || agent.connectors === "nenhum") return false;
  if (!agent.connectors) return true;
  return agent.connectors.split(",").includes(accountId);
}

export function ConnectorsView(props: Props) {
  const { client, accounts, approvals, activity, onActivity, onDecide, onToast, events, onEvents, onOpenSession, agents } = props;
  const list = useMemo(() => accounts ?? [], [accounts]);
  const [tab, setTab] = useState<"conn" | "cat" | "perm" | "act">("conn");
  const [sel, setSel] = useState<Selection>(null);

  useEffect(() => {
    if (!client || tab !== "act") return;
    void client.activity().then(onActivity).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, tab]);

  // Abre na primeira conta; se a escolhida sumiu (desconectada), volta para ela.
  useEffect(() => {
    if (sel?.type === "account" && list.some((a) => a.id === sel.id)) return;
    if (sel?.type === "setup" || sel?.type === "brain") return;
    setSel(list[0] ? { type: "account", id: list[0].id } : null);
  }, [list, sel]);

  if (!client) return <div className="cx-screen" />;

  const openSetup = (kind: string) => setSel({ type: "setup", kind });
  /** Chamada da central: o logo da conta usada; sem conta, é do Brain e kanban. */
  const callBrand = (accountId: string) => {
    const account = list.find((a) => a.id === accountId);
    return account ? accountBrand(account) : "metis";
  };
  const tabs: [typeof tab, string][] = [
    ["conn", `Conectados · ${list.length}`],
    ["cat", "Catálogo"],
    ["perm", "Permissões por agente"],
    ["act", approvals.length ? `Atividade · ${approvals.length} aguardando` : "Atividade"],
  ];

  return (
    <div className="cx-screen">
      <main className="cx-main">
        <div className="cx-head">
          <div className="cx-head-text">
            <h1>Conectores</h1>
            <span>Cada ferramenta entra uma vez na MÊTIS. Os terminais recebem um único MCP ("metis"), só com o que cada agente pode usar.</span>
          </div>
          <button type="button" className="cx-btn" onClick={() => openSetup("mcp")}>
            Conector personalizado
          </button>
        </div>

        <div className="cx-tabs" role="tablist" aria-label="Seções">
          {tabs.map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>

        {tab === "conn" && (
          <div className="cx-grid">
            {list.map((account) => {
              const service = serviceOf(account.kind);
              const on = sel?.type === "account" && sel.id === account.id;
              return (
                <button key={account.id} type="button" className="cx-card" aria-pressed={on} onClick={() => setSel({ type: "account", id: account.id })}>
                  <span className="cx-card-top">
                    <BrandIcon brand={accountBrand(account)} />
                    <span className="cx-card-name">
                      <span className="cx-name">{account.name}</span>
                      <span className="cx-kind">{service.kindLabel}</span>
                    </span>
                    <span className="cx-on">
                      <span className="cx-dot" />
                      conectado
                    </span>
                  </span>
                  <span className="cx-chips">
                    {accountChips(account).map((chip) => (
                      <span key={chip} className="cx-chip">
                        {chip}
                      </span>
                    ))}
                  </span>
                  <span className="cx-summary">{accountSummary(account)}</span>
                </button>
              );
            })}
            <button type="button" className="cx-card" aria-pressed={sel?.type === "brain"} onClick={() => setSel({ type: "brain" })}>
              <span className="cx-card-top">
                <BrandIcon brand="metis" />
                <span className="cx-card-name">
                  <span className="cx-name">Brain e kanban</span>
                  <span className="cx-kind">interno da MÊTIS</span>
                </span>
                <span className="cx-on">
                  <span className="cx-dot" />
                  sempre
                </span>
              </span>
              <span className="cx-chips">
                <span className="cx-chip">~/Documents/Brain</span>
              </span>
              <span className="cx-summary">precedentes, notas, tarefas, navegador e estudo</span>
            </button>
            {list.length === 0 && (
              <button type="button" className="cx-card cx-card-empty" onClick={() => setTab("cat")}>
                <span className="cx-name">Nenhuma conta ainda</span>
                <span className="cx-summary">Abra o Catálogo e conecte o Slack, o ClickUp, o GitHub ou qualquer MCP.</span>
              </button>
            )}
          </div>
        )}

        {tab === "cat" && (
          <>
            <div className="cx-grid">
              {SERVICES.map((service) => {
                const mine = list.filter((a) => a.kind === service.kind).length;
                return (
                  <div key={service.kind} className="cx-card static">
                    <span className="cx-card-top">
                      <BrandIcon brand={brandFor(service.kind)} />
                      <span className="cx-card-name">
                        <span className="cx-name">{service.label}</span>
                        <span className="cx-kind">{service.kindLabel}</span>
                      </span>
                      {mine > 0 && (
                        <span className="cx-on">
                          <span className="cx-dot" />
                          {mine} {mine === 1 ? "conta" : "contas"}
                        </span>
                      )}
                    </span>
                    <span className="cx-summary">{service.description}</span>
                    <button type="button" className="cx-btn primary" onClick={() => openSetup(service.kind)}>
                      {mine ? "Conectar outra conta" : "Conectar"}
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="cx-section">
              <CliMcpCopy client={client} onToast={onToast} />
            </div>
          </>
        )}

        {tab === "perm" && <Permissions agents={agents} accounts={list} onToggle={props.onSaveAgent} />}

        {tab === "act" && (
          <div className="cx-activity">
            {approvals.map((approval) => (
              <ApprovalCard key={approval.id} approval={approval} onDecide={onDecide} />
            ))}
            <AgentFeed client={client} events={events} onEvents={onEvents} onOpenSession={onOpenSession} />
            <div className="section-title">Central de MCP</div>
            <div className="cx-calls">
              {activity.map((item) => (
                <div key={item.id} className="cx-call">
                  <span className="mono small cx-call-time">{when(item.ts)}</span>
                  <span className="cx-call-who">{item.who}</span>
                  <span className="mono small cx-call-tool">
                    <BrandIcon brand={callBrand(item.account)} size={18} />
                    <span>{item.tool}</span>
                  </span>
                  <span className="small cx-call-what" title={item.detail || undefined}>
                    {argsLine(item.args)}
                  </span>
                  <span className="activity-status" data-status={item.status}>
                    {STATUS_LABEL[item.status] ?? item.status}
                  </span>
                </div>
              ))}
              {!activity.length && <p className="small conn-note">Nada ainda. Quando um agente usar a central (Brain, kanban, Slack, ClickUp), aparece aqui.</p>}
            </div>
          </div>
        )}
      </main>

      <aside className="cx-aside" aria-label="Detalhe do conector">
        {sel?.type === "account" && list.find((a) => a.id === sel.id) ? (
          <AccountPanel client={client} account={list.find((a) => a.id === sel.id)!} siblings={list} onPick={(id) => setSel({ type: "account", id })} onSetup={openSetup} onToast={onToast} />
        ) : sel?.type === "setup" ? (
          <SetupPanel client={client} kind={sel.kind} onDone={() => setSel(null)} onToast={onToast} />
        ) : sel?.type === "brain" ? (
          <div className="cx-panel">
            <PanelHead brand="metis" name="Brain e kanban" kind="interno da MÊTIS" />
            <p className="cx-note">
              Todo agente aberto pela MÊTIS recebe pela central as ferramentas do Brain (precedentes, notas, registro), do kanban (tarefas do projeto), do
              navegador embutido e do estudo. Não passam por aprovação e não saem do Mac.
            </p>
          </div>
        ) : (
          <p className="cx-note cx-aside-empty">Escolha um conector para ver as contas e as ferramentas, ou conecte um pelo Catálogo.</p>
        )}
      </aside>
    </div>
  );
}

function PanelHead({ brand, name, kind }: { brand: Brand; name: string; kind: string }) {
  return (
    <div className="cx-panel-head">
      <BrandIcon brand={brand} size={38} />
      <span className="cx-card-name">
        <span className="cx-panel-name">{name}</span>
        <span className="cx-kind">{kind}</span>
      </span>
    </div>
  );
}

function SetupPanel({ client, kind, onDone, onToast }: { client: CoreClient; kind: string; onDone: () => void; onToast: (m: string) => void }) {
  const service = serviceOf(kind);
  return (
    <div className="cx-panel">
      <PanelHead brand={brandFor(kind)} name={kind === "mcp" ? "Conector personalizado" : `Conectar ${service.label}`} kind={service.kindLabel} />
      <div className="cx-setup">
        {kind === "slack" ? (
          <SlackSetup client={client} onDone={onDone} onToast={onToast} />
        ) : kind === "github" ? (
          <GithubSetup client={client} onDone={onDone} onToast={onToast} />
        ) : kind === "google" ? (
          <GoogleSetup client={client} onToast={onToast} />
        ) : kind === "mcp" ? (
          <McpSetup client={client} onDone={onDone} onToast={onToast} />
        ) : (
          <OAuthSetup client={client} kind={kind} label={service.label} onToast={onToast} />
        )}
      </div>
      <button type="button" className="cx-link" onClick={onDone}>
        Cancelar
      </button>
    </div>
  );
}

function AccountPanel({
  client,
  account,
  siblings,
  onPick,
  onSetup,
  onToast,
}: {
  client: CoreClient;
  account: ConnectorAccount;
  siblings: ConnectorAccount[];
  onPick: (id: string) => void;
  onSetup: (kind: string) => void;
  onToast: (m: string) => void;
}) {
  const service = serviceOf(account.kind);
  const [tools, setTools] = useState<ConnectorTool[] | null>(null);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [test, setTest] = useState<ConnectionTest | "testando" | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let alive = true;
    setTools(null);
    setToolsError(null);
    setTest(null);
    setConfirm(false);
    setShowAll(false);
    client
      .connectorTools(account.id)
      .then((answer) => alive && setTools(answer.ferramentas))
      .catch((cause) => alive && setToolsError(message(cause)));
    return () => {
      alive = false;
    };
    // O padrão de cada ferramenta segue "escrita pede aprovação": mudou, a lista relê.
  }, [client, account.id, account.approve_writes]);

  const patch = (changes: Parameters<CoreClient["patchConnector"]>[1]) =>
    client.patchConnector(account.id, changes).catch((cause) => {
      onToast(message(cause));
      return null;
    });

  /** "padrao" tira o modo escolhido: a ferramenta volta a seguir "escrita pede aprovação" da conta. */
  const setMode = async (tool: ConnectorTool, mode: ToolMode | "padrao") => {
    const fallback: ToolMode = tool.escrita && account.approve_writes ? "aprovacao" : "livre";
    const next = mode === "padrao" ? { modo: fallback, escolhido: false } : { modo: mode, escolhido: true };
    setTools((all) => all?.map((t) => (t.nome === tool.nome ? { ...t, ...next } : t)) ?? null);
    const saved = await patch({ tool_modes: { [tool.nome]: mode } });
    if (!saved) setTools((all) => all?.map((t) => (t.nome === tool.nome ? tool : t)) ?? null);
  };

  const same = siblings.filter((a) => a.kind === account.kind);
  const shown = tools && !showAll ? tools.slice(0, 12) : tools;
  const short = (name: string) => (name.includes("__") ? name.split("__").slice(1).join("__") : name);

  return (
    <div className="cx-panel">
      <PanelHead brand={accountBrand(account)} name={account.kind === "mcp" ? account.name : service.label} kind={service.kindLabel} />

      <div className="cx-block">
        <span className="cx-block-title">Contas</span>
        {same.map((a) => (
          <button key={a.id} type="button" className="cx-account" aria-current={a.id === account.id ? "true" : undefined} onClick={() => onPick(a.id)}>
            <BrandIcon brand={accountBrand(a)} size={20} />
            <span className="cx-account-name">{a.name}</span>
            <span className="cx-kind">Keychain</span>
          </button>
        ))}
        <button type="button" className="cx-add" onClick={() => onSetup(account.kind)}>
          + Adicionar conta
        </button>
      </div>

      <div className="cx-block">
        <label className="cx-check">
          <input type="checkbox" checked={account.approve_writes} onChange={(e) => void patch({ approve_writes: e.target.checked })} />
          escrita pede aprovação (padrão das ferramentas sem modo escolhido)
        </label>
        {account.kind === "slack" && (
          <label className="cx-check">
            <input type="checkbox" checked={account.reminders} onChange={(e) => void patch({ reminders: e.target.checked })} />
            usar para os lembretes (metis lembrete)
          </label>
        )}
      </div>

      <div className="cx-block">
        <span className="cx-block-title">Ferramentas{tools ? ` · ${tools.length}` : ""}</span>
        {!tools && !toolsError && <span className="cx-note">lendo as ferramentas…</span>}
        {toolsError && <span className="cx-note cx-error">Não deu para listar: {toolsError}</span>}
        {shown?.map((tool) => (
          <div key={tool.nome} className="cx-tool" title={tool.descricao}>
            <input
              type="checkbox"
              aria-label={`Ligar ${short(tool.nome)}`}
              checked={tool.modo !== "desligada"}
              onChange={(e) => void setMode(tool, e.target.checked ? "padrao" : "desligada")}
            />
            <span className="cx-tool-name mono">{short(tool.nome)}</span>
            <select
              className="cx-mode"
              data-mode={tool.modo}
              value={tool.escolhido ? tool.modo : "padrao"}
              onChange={(e) => void setMode(tool, e.target.value as ToolMode | "padrao")}
              aria-label={`Modo de ${short(tool.nome)}`}
            >
              <option value="padrao">padrão da conta ({MODE_LABEL[tool.escrita && account.approve_writes ? "aprovacao" : "livre"]})</option>
              {(Object.keys(MODE_LABEL) as ToolMode[]).map((mode) => (
                <option key={mode} value={mode}>
                  {MODE_LABEL[mode]}
                </option>
              ))}
            </select>
          </div>
        ))}
        {tools && tools.length > 12 && (
          <button type="button" className="cx-link" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "mostrar menos" : `mostrar as ${tools.length}`}
          </button>
        )}
      </div>

      <div className="cx-buttons">
        <button
          type="button"
          className="cx-btn primary"
          disabled={test === "testando"}
          onClick={() => {
            setTest("testando");
            void client
              .checkConnector(account.id)
              .then(setTest)
              .catch((cause) => (setTest(null), onToast(message(cause))));
          }}
        >
          {test === "testando" ? "Testando…" : "Testar conexão"}
        </button>
        {confirm ? (
          <button
            type="button"
            className="cx-btn danger"
            onClick={() =>
              void client
                .deleteConnector(account.id)
                .then(() => onToast(`${account.name} desconectado.`))
                .catch((cause) => onToast(message(cause)))
            }
          >
            Tirar mesmo
          </button>
        ) : (
          <button type="button" className="cx-btn" onClick={() => setConfirm(true)}>
            Desconectar
          </button>
        )}
      </div>
      {test && test !== "testando" && <TestResult result={test} />}
      {account.kind === "slack" && <ReminderTry client={client} onToast={onToast} />}
      <span className="cx-note">O token fica no Keychain do macOS. Credencial da Anthropic e da OpenAI nunca passa por aqui.</span>
    </div>
  );
}

function Permissions({ agents, accounts, onToggle }: { agents: Agent[]; accounts: ConnectorAccount[]; onToggle: (agent: Agent, connectors: string) => void }) {
  if (!accounts.length) return <p className="cx-note">Conecte uma conta primeiro: a tabela mostra o que cada agente pode usar dela.</p>;
  const toggle = (agent: Agent, account: ConnectorAccount) => {
    const ids = accounts.map((a) => a.id);
    const now = ids.filter((id) => allows(agent, id));
    const next = now.includes(account.id) ? now.filter((id) => id !== account.id) : [...now, account.id];
    onToggle(agent, next.length === ids.length ? "" : next.length ? next.join(",") : "nenhum");
  };
  return (
    <>
      <div className="cx-table-wrap">
        <table className="cx-table">
          <thead>
            <tr>
              <th scope="col">Agente</th>
              {accounts.map((a) => (
                <th key={a.id} scope="col">
                  <span className="cx-th-brand">
                    <BrandIcon brand={accountBrand(a)} size={18} />
                    {a.name}
                  </span>
                </th>
              ))}
              <th scope="col">
                <span className="cx-th-brand">
                  <BrandIcon brand="metis" size={18} />
                  Brain e kanban
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {agents.map((agent) => (
              <tr key={agent.id}>
                <th scope="row">{agent.name}</th>
                {accounts.map((account) => {
                  const on = allows(agent, account.id);
                  const label = agent.cli === "outra" ? "—" : on ? (account.approve_writes ? "pede aprovação" : "escrever") : "—";
                  return (
                    <td key={account.id}>
                      <button
                        type="button"
                        className="cx-cell"
                        data-v={on ? (account.approve_writes ? "aprovacao" : "livre") : "nao"}
                        disabled={agent.cli === "outra"}
                        title={on ? "Clique para tirar" : "Clique para liberar"}
                        onClick={() => toggle(agent, account)}
                      >
                        {label}
                      </button>
                    </td>
                  );
                })}
                <td>
                  <span className="cx-cell" data-v={agent.cli === "outra" ? "nao" : "livre"}>
                    {agent.cli === "outra" ? "—" : "escrever"}
                  </span>
                </td>
              </tr>
            ))}
            <tr>
              <th scope="row">Sessões sem agente</th>
              {accounts.map((account) => (
                <td key={account.id}>
                  <span className="cx-cell" data-v={account.approve_writes ? "aprovacao" : "livre"}>
                    {account.approve_writes ? "pede aprovação" : "escrever"}
                  </span>
                </td>
              ))}
              <td>
                <span className="cx-cell" data-v="livre">
                  escrever
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <span className="cx-note">
        "Pede aprovação" para a escrita na central e espera você em Hoje ou no sino, mesmo com o agente sem confirmação. Clique numa célula para liberar ou tirar
        a conta do agente; o modo de cada ferramenta fica no painel do conector.
      </span>
    </>
  );
}
