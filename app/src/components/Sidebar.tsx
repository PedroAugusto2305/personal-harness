import { ICON, Icon } from "../icons";
import { STATUS_COLOR, STATUS_LABEL, shortPath } from "../lib/format";
import type { Session, SessionKind } from "../types";

interface Props {
  sessions: Session[];
  activeId: string | null;
  folder: string;
  ready: boolean;
  error: string | null;
  onFolder: (value: string) => void;
  onCreate: (kind: SessionKind) => void;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
}

export function Sidebar({ sessions, activeId, folder, ready, error, onFolder, onCreate, onSelect, onClose }: Props) {
  return (
    <nav className="sidebar" aria-label="Sessões">
      <label className="folder">
        <span className="section-title">Pasta de trabalho</span>
        <input
          value={folder}
          onChange={(event) => onFolder(event.target.value)}
          spellCheck={false}
          placeholder="~/orca/projects/…"
        />
      </label>
      <div className="new-buttons">
        <button type="button" className="btn primary" disabled={!ready} onClick={() => onCreate("claude")}>
          <Icon d={ICON.plus} size={13} strokeWidth={2.2} />
          Claude
        </button>
        <button type="button" className="btn" disabled={!ready} onClick={() => onCreate("shell")}>
          <Icon d={ICON.plus} size={13} strokeWidth={2.2} />
          Shell
        </button>
      </div>
      {error && <div className="error-box">{error}</div>}
      <span className="section-title" style={{ marginTop: 6 }}>
        Sessões · {sessions.length}
      </span>
      <div className="session-list">
        {sessions.map((session) => (
          <div key={session.id} style={{ display: "flex", alignItems: "center" }}>
            <button
              type="button"
              className="session-row"
              aria-current={session.id === activeId ? "true" : undefined}
              onClick={() => onSelect(session.id)}
            >
              <span className="dot" style={{ background: STATUS_COLOR[session.status] }} />
              <span className="meta">
                <span style={{ fontWeight: 500 }}>
                  {session.kind === "claude" ? "✻ " : ">_ "}
                  {session.title}
                </span>
                <span className="small mono">
                  {STATUS_LABEL[session.status]} · {shortPath(session.cwd)}
                </span>
              </span>
            </button>
            <button
              type="button"
              className="session-row close"
              aria-label={`Fechar sessão ${session.title}`}
              title="Fechar sessão"
              onClick={() => onClose(session.id)}
              style={{ width: 26, minHeight: 26, justifyContent: "center", padding: 0 }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </nav>
  );
}
