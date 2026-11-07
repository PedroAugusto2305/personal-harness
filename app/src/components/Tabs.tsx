import type { ReactNode } from "react";
import { ICON, Icon } from "../icons";

export interface TabItem {
  key: string;
  title: string;
  glyph: ReactNode;
  hint?: string;
  dot?: string;
}

interface Props {
  items: TabItem[];
  visible: (string | null)[];
  focusedKey: string | null;
  split: boolean;
  floatOpen: boolean;
  inspectorOpen: boolean;
  onSelect: (key: string) => void;
  onClose: (key: string) => void;
  onToggleSplit: () => void;
  onToggleFloat: () => void;
  onToggleInspector: () => void;
  onPalette: () => void;
}

/** Abas de terminais, diffs e arquivos. As que estão na tela ficam marcadas; a em foco, destacada. */
export function Tabs(props: Props) {
  const { items, visible, focusedKey } = props;
  return (
    <div className="tabs">
      <div className="tab-strip" role="tablist" aria-label="Abas abertas">
        {items.map((item, index) => (
          <div
            key={item.key}
            role="tab"
            tabIndex={0}
            className="tab"
            aria-selected={item.key === focusedKey}
            data-visible={visible.includes(item.key) ? "true" : undefined}
            title={`${item.title}${item.hint ? ` · ${item.hint}` : ""}${index < 9 ? ` · ⌘${index + 1}` : ""}`}
            onClick={() => props.onSelect(item.key)}
            onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && props.onSelect(item.key)}
            onAuxClick={(event) => event.button === 1 && props.onClose(item.key)}
          >
            <span className="tab-glyph">{item.glyph}</span>
            <span className="tab-title">{item.title}</span>
            {item.dot && <span className="dot" style={{ background: item.dot }} />}
            <button
              type="button"
              className="tab-close"
              aria-label={`Fechar ${item.title}`}
              title="Fechar"
              onClick={(event) => {
                event.stopPropagation();
                props.onClose(item.key);
              }}
            >
              <Icon d={ICON.close} size={11} strokeWidth={2.2} />
            </button>
          </div>
        ))}
      </div>
      <div className="tab-actions">
        <button type="button" className="icon-btn" title="Novo terminal ou ação (⌘K)" aria-label="Salto rápido" onClick={props.onPalette}>
          <Icon d={ICON.plus} size={15} strokeWidth={2} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={props.split}
          title={props.split ? "Juntar a tela (⌘D)" : "Dividir a tela (⌘D)"}
          aria-label="Dividir a tela"
          onClick={props.onToggleSplit}
        >
          <Icon d={ICON.split} size={15} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={props.floatOpen}
          title="Terminal flutuante (⌃`)"
          aria-label="Terminal flutuante"
          onClick={props.onToggleFloat}
        >
          <Icon d={ICON.float} size={15} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={props.inspectorOpen}
          title="Mudanças, arquivos e portas da worktree (⌘⇧B)"
          aria-label="Painel da worktree"
          onClick={props.onToggleInspector}
        >
          <Icon d={ICON.panel} size={15} />
        </button>
      </div>
    </div>
  );
}
