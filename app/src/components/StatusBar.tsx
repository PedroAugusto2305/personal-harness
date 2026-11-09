import { useCallback, useEffect, useRef, useState } from "react";
import { KindIcon } from "./KindIcon";
import { createPortal } from "react-dom";
import type { CoreClient } from "../lib/core";
import { ago, money, pct, resetIn, tokens } from "../lib/format";
import type { AccountLimits, Accounts, Connection, ModelUsageReport, Provider, RateWindow, Session, Usage } from "../types";

const ALERT_AT = 80;

/** Barrinha de uma janela do plano. Passa a cor de alerta a partir de 80%. */
export function UsageMeter({ label, window }: { label: string; window?: RateWindow }) {
  if (!window) return <span className="mono meter-empty">{label} —</span>;
  const hot = window.used_pct >= ALERT_AT;
  const reset = resetIn(window.resets_at);
  return (
    <span className="usage" title={`Janela de ${label} do plano: ${pct(window.used_pct)} usado${reset ? `, zera em ${reset}` : ""}`}>
      <span className="bar">
        <span style={{ width: `${Math.min(100, window.used_pct)}%`, background: hot ? "var(--warn)" : "var(--acc)" }} />
      </span>
      <span className="mono" style={{ color: hot ? "var(--warn)" : undefined }}>
        {label} {pct(window.used_pct)}
        {reset && ` · ${reset}`}
      </span>
    </span>
  );
}

export function Limits({ limits }: { limits?: AccountLimits }) {
  return (
    <>
      <UsageMeter label="5h" window={limits?.five_hour} />
      <UsageMeter label="7d" window={limits?.seven_day} />
    </>
  );
}

const CONNECTION_LABEL: Record<Connection, string> = {
  connecting: "conectando ao núcleo…",
  online: "núcleo conectado",
  offline: "núcleo fora do ar",
};

const PROVIDER_TITLE: Record<Provider, string> = { claude: "Claude Code", codex: "Codex" };

/** O que o provedor gastou hoje (v0.9.9): custo equivalente em API (Claude) e tokens. */
export interface TodaySpend {
  custo: number;
  tokens: number;
}

function Plan({ provider, usage, accounts, today, onOpen }: { provider: Provider; usage: Usage; accounts: Accounts; today?: TodaySpend; onOpen: () => void }) {
  const entry = accounts[provider];
  const active = entry.accounts.find((a) => a.id === entry.active);
  const many = entry.accounts.length > 1;
  const limits = usage[provider][entry.active];
  const known = !!(limits?.five_hour || limits?.seven_day);
  const spent = today && today.tokens > 0 ? (provider === "claude" ? `hoje ${money(today.custo)}` : `hoje ${tokens(today.tokens)} tok`) : null;
  const tip = `${PROVIDER_TITLE[provider]}: ${known ? "uso do plano (5h e 7d)" : "o limite do plano aparece quando uma sessão da MÊTIS responder"}${
    today ? ` · hoje ${tokens(today.tokens)} tokens${provider === "claude" ? `, ${money(today.custo)} se fosse pela API` : ""}` : ""
  } · clique para ver as barras de uso`;
  return (
    <button type="button" className="usage plan" onClick={onOpen} title={tip}>
      <KindIcon kind={provider} />
      {many && active && <span className="plan-account">{active.name}</span>}
      {known || !spent ? <Limits limits={limits} /> : null}
      {spent && <span className="mono plan-today">{spent}</span>}
    </button>
  );
}

/** Gasto de hoje por provedor, lido do núcleo a cada 2 minutos (a leitura é incremental). */
export function useTodaySpend(client: CoreClient | null | undefined): Partial<Record<Provider, TodaySpend>> {
  return useTodayUsage(client).spend;
}

/** O relatório de hoje é um só para a janela inteira: a barra de baixo e o Hoje dividem a mesma
 * leitura, refeita no máximo a cada 2 minutos. */
type TodayState = { spend: Partial<Record<Provider, TodaySpend>>; report: ModelUsageReport | null };
const todayCache: { at: number; state: TodayState | null; pending: Promise<TodayState> | null; client: CoreClient | null } = {
  at: 0,
  state: null,
  pending: null,
  client: null,
};

function readToday(client: CoreClient): Promise<TodayState> {
  const fresh = todayCache.client === client && todayCache.state && Date.now() - todayCache.at < 110_000;
  if (fresh) return Promise.resolve(todayCache.state!);
  if (todayCache.pending && todayCache.client === client) return todayCache.pending;
  todayCache.client = client;
  todayCache.pending = client
    .modelUsage(1)
    .then((report) => {
      const spend: Partial<Record<Provider, TodaySpend>> = {};
      for (const m of report.por_modelo) {
        const item = spend[m.provedor] ?? { custo: 0, tokens: 0 };
        item.custo += m.custo;
        item.tokens += m.tokens;
        spend[m.provedor] = item;
      }
      const state = { spend, report };
      todayCache.state = state;
      todayCache.at = Date.now();
      return state;
    })
    .finally(() => {
      todayCache.pending = null;
    });
  return todayCache.pending;
}

/** O relatório de hoje inteiro (por modelo) e o resumo por provedor. */
function useTodayUsage(client: CoreClient | null | undefined): TodayState {
  const [state, setState] = useState<TodayState>(() => todayCache.state ?? { spend: {}, report: null });
  useEffect(() => {
    if (!client) return;
    let alive = true;
    const load = () =>
      void readToday(client)
        .then((next) => alive && setState(next))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 120_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client]);
  return state;
}

/** Barra grande de uma janela do plano, para a janela suspensa. */
function WindowBar({ label, window: win }: { label: string; window?: RateWindow }) {
  if (!win) {
    return (
      <div className="upop-bar">
        <span className="upop-bar-label">{label}</span>
        <span className="upop-track" aria-hidden="true" />
        <span className="upop-bar-value mono">—</span>
      </div>
    );
  }
  const used = Math.max(0, Math.min(100, win.used_pct));
  const hot = used >= ALERT_AT;
  const reset = resetIn(win.resets_at);
  return (
    <div className="upop-bar" title={`${label}: ${pct(used)} usado${reset ? `, zera em ${reset}` : ""}`}>
      <span className="upop-bar-label">{label}</span>
      <span className="upop-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(used)}>
        <span style={{ width: `${used}%`, background: hot ? "var(--warn)" : "var(--acc)" }} />
      </span>
      <span className="upop-bar-value mono" style={hot ? { color: "var(--warn)" } : undefined}>
        {pct(used)}
        {reset && <span className="upop-reset"> · zera em {reset}</span>}
      </span>
    </div>
  );
}

/** Janela suspensa do uso (v0.9.9, pedido do Pedro): as barras do plano de cada conta, o
 * gasto de hoje por modelo e o atalho para o painel completo. */
function UsagePopover({ usage, accounts, today, onClose, onOpenFull }: { usage: Usage; accounts: Accounts; today: { spend: Partial<Record<Provider, TodaySpend>>; report: ModelUsageReport | null }; onClose: () => void; onOpenFull: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (box.current?.contains(target) || target.closest(".usage.plan")) return;
      onClose();
    };
    const key = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("mousedown", down);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("mousedown", down);
      window.removeEventListener("keydown", key);
    };
  }, [onClose]);
  const models = today.report?.por_modelo ?? [];
  const maxTokens = Math.max(1, ...models.map((m) => m.tokens));
  return createPortal(
    <div className="upop" ref={box} role="dialog" aria-label="Uso dos modelos">
      <div className="upop-head">
        <span className="upop-title">Uso dos modelos</span>
        <span className="small upop-sub">{today.report ? `hoje · atualizado ${ago(today.report.atualizado * 1000)}` : "lendo…"}</span>
      </div>
      {(["claude", "codex"] as const).map((provider) => {
        const entry = accounts[provider];
        const spent = today.spend[provider];
        return (
          <section key={provider} className="upop-provider">
            {entry.accounts.map((account) => {
              const limits = usage[provider][account.id];
              const known = !!(limits?.five_hour || limits?.seven_day);
              return (
                <div key={account.id} className="upop-account">
                  <div className="upop-account-head">
                    <KindIcon kind={provider} />
                    <span className="upop-name">{PROVIDER_TITLE[provider]}</span>
                    {entry.accounts.length > 1 && <span className="small upop-acc">{account.name}</span>}
                    {limits?.plan && <span className="chip plan-chip">{limits.plan}</span>}
                    {account.id === entry.active && entry.accounts.length > 1 && <span className="small upop-acc">em uso</span>}
                    <span className="grow" />
                    {limits?.updated_at ? <span className="small upop-seen">visto {ago(limits.updated_at * 1000)}</span> : null}
                  </div>
                  <WindowBar label="5 horas" window={limits?.five_hour} />
                  <WindowBar label="Semana" window={limits?.seven_day} />
                  {!known && provider === "claude" && <p className="small upop-hint">O limite do Claude aparece na primeira resposta de uma sessão aberta pela MÊTIS.</p>}
                </div>
              );
            })}
            {spent && spent.tokens > 0 && (
              <div className="small upop-today">
                Hoje: {tokens(spent.tokens)} tokens{provider === "claude" ? ` · ${money(spent.custo)} se fosse pela API` : ""}
              </div>
            )}
          </section>
        );
      })}
      {models.length > 0 && (
        <section className="upop-models">
          <span className="upop-section">Hoje por modelo</span>
          {models.map((m) => (
            <div key={`${m.provedor}:${m.modelo}`} className="upop-model">
              <span className="upop-model-name">
                <KindIcon kind={m.provedor} /> {m.nome}
              </span>
              <span className="upop-track small-track" aria-hidden="true">
                <span style={{ width: `${Math.max(2, (m.tokens / maxTokens) * 100)}%` }} />
              </span>
              <span className="mono upop-model-value">{m.provedor === "claude" ? money(m.custo) : `${tokens(m.tokens)} tok`}</span>
            </div>
          ))}
        </section>
      )}
      <button type="button" className="upop-full" onClick={onOpenFull}>
        Ver o uso completo ›
      </button>
    </div>,
    document.body,
  );
}

interface Props {
  /** v0.9.9: para o gasto de hoje ao lado dos limites. */
  client?: CoreClient | null;
  usage: Usage;
  accounts: Accounts;
  active: Session | null;
  connection: Connection;
  onOpenAccounts: () => void;
  /** Abre a aba Contexto do painel (o que ocupa a janela de contexto). */
  onOpenContext?: () => void;
  /** Abre Ajustes → Recursos (memória e CPU do núcleo e das sessões). */
  onOpenResources?: () => void;
}

export function StatusBar({ client, usage, accounts, active, connection, onOpenAccounts, onOpenContext, onOpenResources }: Props) {
  const line = active?.statusline;
  const context = line?.context;
  const today = useTodayUsage(client);
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  return (
    <footer className="statusbar">
      <Plan provider="claude" usage={usage} accounts={accounts} today={today.spend.claude} onOpen={() => setOpen((v) => !v)} />
      <Plan provider="codex" usage={usage} accounts={accounts} today={today.spend.codex} onOpen={() => setOpen((v) => !v)} />
      {open && (
        <UsagePopover
          usage={usage}
          accounts={accounts}
          today={today}
          onClose={close}
          onOpenFull={() => {
            setOpen(false);
            onOpenAccounts();
          }}
        />
      )}
      {context && (
        <button type="button" className="mono statusbar-context" title="Janela de contexto do terminal em foco: clique para ver o que ocupa" onClick={onOpenContext}>
          contexto {tokens(context.used_tokens)} / {tokens(context.size)}
          {context.used_pct != null && ` · ${pct(context.used_pct)}`}
        </button>
      )}
      {line?.cost_usd != null && line.cost_usd > 0 && <span className="mono">{money(line.cost_usd)}</span>}
      <span className="right">
        <button type="button" className="statusbar-core" onClick={onOpenResources} title="Memória e CPU do núcleo e das sessões: abrir Recursos">
          <span
            className="dot"
            style={{ background: connection === "online" ? "var(--run)" : connection === "offline" ? "var(--err)" : "var(--fnt)" }}
          />
          {CONNECTION_LABEL[connection]}
        </button>
        <span>v{__APP_VERSION__}</span>
      </span>
    </footer>
  );
}
