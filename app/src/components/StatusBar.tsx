import { KIND_COLOR, KIND_GLYPH, money, pct, resetIn, tokens } from "../lib/format";
import type { AccountLimits, Accounts, Connection, Provider, RateWindow, Session, Usage } from "../types";

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

function Plan({ provider, usage, accounts, onOpen }: { provider: Provider; usage: Usage; accounts: Accounts; onOpen: () => void }) {
  const entry = accounts[provider];
  const active = entry.accounts.find((a) => a.id === entry.active);
  const many = entry.accounts.length > 1;
  return (
    <button type="button" className="usage plan" onClick={onOpen} title={`Uso do plano do ${PROVIDER_TITLE[provider]} · abrir Contas e uso`}>
      <span style={{ color: KIND_COLOR[provider] }}>{KIND_GLYPH[provider]}</span>
      {many && active && <span className="plan-account">{active.name}</span>}
      <Limits limits={usage[provider][entry.active]} />
    </button>
  );
}

interface Props {
  usage: Usage;
  accounts: Accounts;
  active: Session | null;
  connection: Connection;
  onOpenAccounts: () => void;
}

export function StatusBar({ usage, accounts, active, connection, onOpenAccounts }: Props) {
  const line = active?.statusline;
  const context = line?.context;
  return (
    <footer className="statusbar">
      <Plan provider="claude" usage={usage} accounts={accounts} onOpen={onOpenAccounts} />
      <Plan provider="codex" usage={usage} accounts={accounts} onOpen={onOpenAccounts} />
      {context && (
        <span className="mono" title="Janela de contexto do terminal em foco">
          contexto {tokens(context.used_tokens)} / {tokens(context.size)}
          {context.used_pct != null && ` · ${pct(context.used_pct)}`}
        </span>
      )}
      {line?.cost_usd != null && line.cost_usd > 0 && <span className="mono">{money(line.cost_usd)}</span>}
      <span className="right">
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            className="dot"
            style={{ background: connection === "online" ? "var(--run)" : connection === "offline" ? "var(--err)" : "var(--fnt)" }}
          />
          {CONNECTION_LABEL[connection]}
        </span>
        <span>v{__APP_VERSION__}</span>
      </span>
    </footer>
  );
}
