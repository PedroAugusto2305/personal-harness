import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { fold } from "../lib/format";

export interface PaletteItem {
  id: string;
  label: string;
  group: string;
  hint?: string;
  glyph?: ReactNode;
  run: () => void;
}

/** Salto rápido (⌘K): pula para um terminal ou roda uma ação, só com o teclado. */
export function Palette({ items, onClose }: { items: PaletteItem[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  const shown = useMemo(() => {
    const words = fold(query).split(/\s+/).filter(Boolean);
    return items.filter((item) => {
      const haystack = fold(`${item.label} ${item.group} ${item.hint ?? ""}`);
      return words.every((word) => haystack.includes(word));
    });
  }, [items, query]);

  useEffect(() => input.current?.focus(), []);
  useEffect(() => setIndex(0), [query]);
  useEffect(() => {
    list.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  const choose = (item: PaletteItem | undefined) => {
    if (!item) return;
    onClose();
    item.run();
  };

  let lastGroup = "";
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-label="Salto rápido" onMouseDown={(event) => event.stopPropagation()}>
        <input
          ref={input}
          value={query}
          placeholder="Pular para um terminal ou fazer algo…"
          spellCheck={false}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setIndex((i) => Math.min(shown.length - 1, i + 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setIndex((i) => Math.max(0, i - 1));
            } else if (event.key === "Enter") {
              event.preventDefault();
              choose(shown[index]);
            } else if (event.key === "Escape") {
              event.preventDefault();
              onClose();
            }
          }}
        />
        <ul ref={list} role="listbox" aria-label="Resultados">
          {shown.length === 0 && <li className="palette-empty">Nada com “{query}”.</li>}
          {shown.map((item, i) => {
            const header = item.group !== lastGroup ? item.group : null;
            lastGroup = item.group;
            return (
              <li key={item.id} role="presentation">
                {header && <div className="palette-group">{header}</div>}
                <button
                  type="button"
                  role="option"
                  data-index={i}
                  aria-selected={i === index}
                  onMouseEnter={() => setIndex(i)}
                  onClick={() => choose(item)}
                >
                  <span className="palette-glyph">{item.glyph}</span>
                  <span className="palette-label">{item.label}</span>
                  {item.hint && <span className="palette-hint mono">{item.hint}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
