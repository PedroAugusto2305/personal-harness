import { useRef, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { ICON, Icon } from "../icons";

export interface TabItem {
  key: string;
  title: string;
  glyph: ReactNode;
  hint?: string;
  dot?: string;
  /** Aba de outra worktree: aparece na divisão de lá (fica em cinza aqui). */
  away?: boolean;
}

interface Props {
  items: TabItem[];
  visible: string[];
  focusedKey: string | null;
  tiled: boolean;
  floatOpen: boolean;
  inspectorOpen: boolean;
  /** Atalhos em vigor (seguem o que o Pedro remapeou). */
  hints: { split: string; splitDown: string; float: string; panel: string; palette: string };
  onSelect: (key: string) => void;
  onClose: (key: string) => void;
  onSplit: (side: "right" | "bottom") => void;
  /** Arrasto de uma aba para um painel (feito com o ponteiro: o arrastar do HTML não chega na janela do Tauri). */
  onDrag: (phase: "move" | "end" | "cancel", key: string, x: number, y: number) => void;
  onToggleFloat: () => void;
  onToggleInspector: () => void;
  onPalette: () => void;
}

const withHint = (label: string, hint: string) => (hint ? `${label} (${hint})` : label);

/** Abas de terminais, diffs e arquivos. As que estão na tela ficam marcadas; a em foco, destacada. */
export function Tabs(props: Props) {
  const { items, visible, focusedKey } = props;
  /** O arrasto que acabou não vira clique na aba. */
  const dragged = useRef(false);

  const startDrag = (event: ReactPointerEvent<HTMLDivElement>, key: string) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest(".tab-close")) return;
    const el = event.currentTarget;
    const x0 = event.clientX;
    const y0 = event.clientY;
    const pointer = event.pointerId;
    let moving = false;
    dragged.current = false;
    // Captura já no clique: o primeiro movimento pode cair fora da aba (mouse rápido).
    el.setPointerCapture(pointer);
    const move = (ev: PointerEvent) => {
      if (!moving && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 6) return;
      if (!moving) {
        moving = true;
        dragged.current = true;
      }
      props.onDrag("move", key, ev.clientX, ev.clientY);
    };
    const stop = (ev: PointerEvent) => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", stop);
      el.removeEventListener("pointercancel", stop);
      window.removeEventListener("keydown", escape, true);
      if (moving) props.onDrag(ev.type === "pointerup" ? "end" : "cancel", key, ev.clientX, ev.clientY);
    };
    const escape = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape" || !moving) return;
      ev.preventDefault();
      ev.stopPropagation();
      moving = false;
      props.onDrag("cancel", key, 0, 0);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", stop);
    el.addEventListener("pointercancel", stop);
    window.addEventListener("keydown", escape, true);
  };

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
            data-away={item.away ? "true" : undefined}
            title={`${item.title}${item.hint ? ` · ${item.hint}` : ""}${index < 9 ? ` · ⌘${index + 1}` : ""}${item.away ? " · de outra worktree" : " · arraste para um painel"}`}
            onPointerDown={(event) => startDrag(event, item.key)}
            onClick={() => {
              if (dragged.current) {
                dragged.current = false;
                return;
              }
              props.onSelect(item.key);
            }}
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
        <button
          type="button"
          className="icon-btn"
          title={withHint("Novo terminal ou ação", props.hints.palette)}
          aria-label="Salto rápido"
          onClick={props.onPalette}
        >
          <Icon d={ICON.plus} size={15} strokeWidth={2} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={props.tiled}
          title={withHint("Dividir à direita", props.hints.split)}
          aria-label="Dividir à direita"
          onClick={() => props.onSplit("right")}
        >
          <Icon d={ICON.split} size={15} />
        </button>
        <button
          type="button"
          className="icon-btn"
          title={withHint("Dividir para baixo", props.hints.splitDown)}
          aria-label="Dividir para baixo"
          onClick={() => props.onSplit("bottom")}
        >
          <Icon d={ICON.splitDown} size={15} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={props.floatOpen}
          title={withHint("Terminal flutuante", props.hints.float)}
          aria-label="Terminal flutuante"
          onClick={props.onToggleFloat}
        >
          <Icon d={ICON.float} size={15} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={props.inspectorOpen}
          title={withHint("Mudanças, arquivos e portas da worktree", props.hints.panel)}
          aria-label="Painel da worktree"
          onClick={props.onToggleInspector}
        >
          <Icon d={ICON.panel} size={15} />
        </button>
      </div>
    </div>
  );
}
