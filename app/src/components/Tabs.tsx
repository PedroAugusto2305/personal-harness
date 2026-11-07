import { KIND_COLOR, KIND_GLYPH, STATUS_COLOR, STATUS_LABEL } from "../lib/format";
import { ICON, Icon } from "../icons";
import type { Session } from "../types";

interface Props {
  sessions: Session[];
  visible: (string | null)[];
  focusedId: string | null;
  split: boolean;
  floatOpen: boolean;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onToggleSplit: () => void;
  onToggleFloat: () => void;
  onPalette: () => void;
}

/** Abas de todos os terminais. As que estão na tela ficam marcadas; a em foco, destacada. */
export function Tabs({ sessions, visible, focusedId, split, floatOpen, onSelect, onClose, onToggleSplit, onToggleFloat, onPalette }: Props) {
  return (
    <div className="tabs">
      <div className="tab-strip" role="tablist" aria-label="Terminais abertos">
        {sessions.map((session, index) => (
          <div
            key={session.id}
            role="tab"
            tabIndex={0}
            className="tab"
            aria-selected={session.id === focusedId}
            data-visible={visible.includes(session.id) ? "true" : undefined}
            title={`${session.title} · ${STATUS_LABEL[session.status]}${index < 9 ? ` · ⌘${index + 1}` : ""}`}
            onClick={() => onSelect(session.id)}
            onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onSelect(session.id)}
            onAuxClick={(event) => event.button === 1 && onClose(session.id)}
          >
            <span style={{ color: KIND_COLOR[session.kind] }}>{KIND_GLYPH[session.kind]}</span>
            <span className="tab-title">{session.title}</span>
            <span className="dot" style={{ background: STATUS_COLOR[session.status] }} />
            <button
              type="button"
              className="tab-close"
              aria-label={`Fechar ${session.title}`}
              title="Fechar"
              onClick={(event) => {
                event.stopPropagation();
                onClose(session.id);
              }}
            >
              <Icon d={ICON.close} size={11} strokeWidth={2.2} />
            </button>
          </div>
        ))}
      </div>
      <div className="tab-actions">
        <button type="button" className="icon-btn" title="Novo terminal ou ação (⌘K)" aria-label="Salto rápido" onClick={onPalette}>
          <Icon d={ICON.plus} size={15} strokeWidth={2} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={split}
          title={split ? "Juntar a tela (⌘D)" : "Dividir a tela (⌘D)"}
          aria-label="Dividir a tela"
          onClick={onToggleSplit}
        >
          <Icon d={ICON.split} size={15} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={floatOpen}
          title="Terminal flutuante (⌃`)"
          aria-label="Terminal flutuante"
          onClick={onToggleFloat}
        >
          <Icon d={ICON.float} size={15} />
        </button>
      </div>
    </div>
  );
}
