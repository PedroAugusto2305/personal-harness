import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

export interface CardDrag {
  id: string;
  label: string;
  x: number;
  y: number;
  col: string | null;
}

const colAt = (x: number, y: number) => document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-col]")?.dataset.col ?? null;

/**
 * Arrastar cartão com o ponteiro. v0.9.9: os ouvintes ficam na janela (e não no cartão) e a
 * captura do ponteiro é opcional: na janela do app (WebKit) a captura podia falhar e o
 * cartão não saía do lugar, e o arrastar nativo do WebKit (que dispara pointercancel) fica
 * desligado no CSS e no dragstart.
 */
export function useCardDrag(onDrop: (col: string, id: string) => void) {
  const [drag, setDrag] = useState<CardDrag | null>(null);
  const moved = useRef(false);
  const live = useRef(onDrop);
  live.current = onDrop;

  const start = (event: ReactPointerEvent<HTMLElement>, id: string, label: string) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest("button, a, input, textarea, select, label")) return;
    event.preventDefault();
    const el = event.currentTarget;
    const pointer = event.pointerId;
    const x0 = event.clientX;
    const y0 = event.clientY;
    let moving = false;
    moved.current = false;
    try {
      el.setPointerCapture(pointer);
    } catch {
      // sem captura: os ouvintes da janela bastam
    }
    const move = (ev: PointerEvent) => {
      if (!moving && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 6) return;
      moving = true;
      moved.current = true;
      setDrag({ id, label, x: ev.clientX, y: ev.clientY, col: colAt(ev.clientX, ev.clientY) });
    };
    const finish = () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", stop, true);
      window.removeEventListener("pointercancel", stop, true);
      window.removeEventListener("keydown", escape, true);
      try {
        el.releasePointerCapture(pointer);
      } catch {
        // já solta
      }
    };
    const stop = (ev: PointerEvent) => {
      finish();
      if (!moving) return;
      setDrag(null);
      const col = ev.type === "pointerup" ? colAt(ev.clientX, ev.clientY) : null;
      if (col) live.current(col, id);
    };
    const escape = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape" || !moving) return;
      ev.preventDefault();
      ev.stopPropagation();
      moving = false;
      finish();
      setDrag(null);
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", stop, true);
    window.addEventListener("pointercancel", stop, true);
    window.addEventListener("keydown", escape, true);
  };

  /** O clique que encerra um arrasto não abre o cartão. */
  const consumeClick = () => {
    const was = moved.current;
    moved.current = false;
    return was;
  };

  return { drag, start, consumeClick };
}

