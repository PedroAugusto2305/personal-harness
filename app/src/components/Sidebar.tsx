import { ICON, Icon } from "../icons";
import { KIND_COLOR, KIND_GLYPH, PROVIDERS, STATUS_COLOR, STATUS_LABEL, shortPath } from "../lib/format";
import type { Accounts, Session, SessionKind } from "../types";

interface Props {
  sessions: Session[];
  focusedId: string | null;
  folder: string;
  ready: boolean;
  error: string | null;
  accounts: Accounts;
  accountName: (session: Session) => string | null;
  onFolder: (value: string) => void;
  onCreate: (kind: SessionKind) => void;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onAccounts: () => void;
  onDismissError: () => void;
}

export function Sidebar(props: Props) {
  const { sessions, focusedId, folder, ready, error, accounts, accountName } = props;
  return (
    <nav className="sidebar" aria-label="Sessões">
      <label className="folder">
        <span className="section-title">Pasta de trabalho</span>
        <input
          value={folder}
          onChange={(event) => props.onFolder(event.target.value)}
          spellCheck={false}
          placeholder="~/orca/projects/…"
        />
      </label>
      <div className="new-buttons">
        <button type="button" className="btn primary" disabled={!ready} onClick={() => props.onCreate("claude")}>
          <Icon d={ICON.plus} size={13} strokeWidth={2.2} />
          Claude
        </button>
        <button type="button" className="btn" disabled={!ready} onClick={() => props.onCreate("codex")}>
          <Icon d={ICON.plus} size={13} strokeWidth={2.2} />
          Codex
        </button>
        <button type="button" className="btn" disabled={!ready} onClick={() => props.onCreate("shell")}>
          <Icon d={ICON.plus} size={13} strokeWidth={2.2} />
          Shell
        </button>
      </div>
      <button type="button" className="account-line" onClick={props.onAccounts} title="Trocar de conta">
        <Icon d={ICON.user} size={13} strokeWidth={1.9} />
        {PROVIDERS.map((provider) => {
          const entry = accounts[provider];
          const name = entry.accounts.find((a) => a.id === entry.active)?.name ?? "padrão";
          return (
            <span key={provider}>
              <span style={{ color: KIND_COLOR[provider] }}>{KIND_GLYPH[provider]}</span> {name}
            </span>
          );
        })}
        <span className="account-switch">trocar</span>
      </button>
      {error && (
        <div className="error-box" role="alert">
          {error}
          <button type="button" className="icon-btn" onClick={props.onDismissError} aria-label="Fechar aviso">
            <Icon d={ICON.close} size={12} strokeWidth={2} />
          </button>
        </div>
      )}
      <span className="section-title" style={{ marginTop: 4 }}>
        Sessões · {sessions.length}
      </span>
      <div className="session-list">
        {sessions.map((session) => {
          const account = accountName(session);
          return (
            <div key={session.id} className="session-item">
              <button
                type="button"
                className="session-row"
                aria-current={session.id === focusedId ? "true" : undefined}
                onClick={() => props.onSelect(session.id)}
              >
                <span className="dot" style={{ background: STATUS_COLOR[session.status] }} />
                <span className="meta">
                  <span style={{ fontWeight: 500 }}>
                    <span style={{ color: KIND_COLOR[session.kind] }}>{KIND_GLYPH[session.kind]}</span> {session.title}
                    {account && <span className="small"> · {account}</span>}
                  </span>
                  <span className="small mono">
                    {STATUS_LABEL[session.status]} · {shortPath(session.cwd)}
                  </span>
                </span>
              </button>
              <button
                type="button"
                className="session-close"
                aria-label={`Fechar sessão ${session.title}`}
                title="Fechar sessão"
                onClick={() => props.onClose(session.id)}
              >
                <Icon d={ICON.close} size={12} strokeWidth={2} />
              </button>
            </div>
          );
        })}
      </div>
    </nav>
  );
}
