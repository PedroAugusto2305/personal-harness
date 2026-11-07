import { money, pct, resetIn, tokens } from "../lib/format";
import type { Connection, RateWindow, Session, Usage } from "../types";

function Window({ label, window }: { label: string; window?: RateWindow }) {
  if (!window) return <span className="mono">{label} —</span>;
  const color = window.used_pct >= 80 ? "var(--warn)" : "var(--acc)";
  const reset = resetIn(window.resets_at);
  return (
    <span className="usage" title={`Janela de ${label} do plano: ${pct(window.used_pct)} usado`}>
      <span className="bar">
        <span style={{ width: `${Math.min(100, window.used_pct)}%`, background: color }} />
      </span>
      <span className="mono" style={{ color: window.used_pct >= 80 ? "var(--warn)" : undefined }}>
        {label} {pct(window.used_pct)}
        {reset && ` · ${reset}`}
      </span>
    </span>
  );
}

const CONNECTION_LABEL: Record<Connection, string> = {
  connecting: "conectando ao núcleo…",
  online: "núcleo conectado",
  offline: "núcleo fora do ar",
};

export function StatusBar({ usage, active, connection }: { usage: Usage; active: Session | null; connection: Connection }) {
  const line = active?.statusline;
  const context = line?.context;
  return (
    <footer className="statusbar">
      <span className="usage" title="Uso do plano do Claude">
        <span style={{ color: "#d97757" }}>✻</span>
        <Window label="5h" window={usage.claude.five_hour} />
        <Window label="7d" window={usage.claude.seven_day} />
      </span>
      {context && (
        <span className="mono" title="Janela de contexto da sessão ativa">
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
        <span>v0.1.0</span>
      </span>
    </footer>
  );
}
