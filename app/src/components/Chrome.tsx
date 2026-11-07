import { windowAction } from "../lib/core";
import { ICON, Icon } from "../icons";
import type { ThemeName, View } from "../types";

export const THEME_LABEL: Record<ThemeName, string> = { dracula: "Drácula azul", grafite: "Grafite", claro: "Claro" };

export function TitleBar({ theme, onCycleTheme, onPalette }: { theme: ThemeName; onCycleTheme: () => void; onPalette: () => void }) {
  return (
    <header className="titlebar" data-tauri-drag-region>
      <div className="traffic">
        <button type="button" aria-label="Fechar janela" title="Fechar" onClick={() => windowAction("close")} />
        <button type="button" aria-label="Minimizar janela" title="Minimizar" onClick={() => windowAction("minimize")} />
        <button
          type="button"
          aria-label="Maximizar janela"
          title="Maximizar"
          onClick={() => windowAction("toggleMaximize")}
        />
      </div>
      <span className="name" data-tauri-drag-region>
        Harness
      </span>
      <button type="button" className="search" onClick={onPalette} title="Salto rápido (⌘K)">
        <Icon d={ICON.search} size={13} strokeWidth={2} />
        <span style={{ flex: 1, textAlign: "left" }}>Buscar ou pular para…</span>
        <span className="mono" style={{ fontSize: 11 }}>
          ⌘K
        </span>
      </button>
      <button type="button" className="chip" onClick={onCycleTheme} title="Trocar tema (mais opções em Ajustes)">
        tema: {THEME_LABEL[theme]}
      </button>
      <span className="chip">v{__APP_VERSION__}</span>
    </header>
  );
}

const NAV: { key: keyof typeof ICON; label: string; version: string }[] = [
  { key: "home", label: "Hoje", version: "v0.7" },
  { key: "term", label: "Terminais", version: "" },
  { key: "study", label: "Estudo", version: "v0.7" },
  { key: "graph", label: "Brain", version: "v0.5" },
  { key: "kanban", label: "Kanban", version: "v0.5" },
  { key: "canvas", label: "Quadros", version: "v0.9" },
  { key: "agents", label: "Agentes", version: "v0.7" },
  { key: "plug", label: "Conectores", version: "v0.6" },
];

/** Faixa de ícones. Terminais e Ajustes já existem; o resto mostra quando chega. */
export function Ribbon({ view, onView }: { view: View; onView: (view: View) => void }) {
  return (
    <nav className="ribbon" aria-label="Módulos">
      {NAV.map((item) => {
        const here = item.key === "term";
        return (
          <button
            key={item.key}
            type="button"
            aria-label={here ? item.label : `${item.label} (chega na ${item.version})`}
            title={here ? item.label : `${item.label} · chega na ${item.version}`}
            aria-current={here && view === "term" ? "page" : undefined}
            disabled={!here}
            onClick={() => here && onView("term")}
          >
            <Icon d={ICON[item.key]} />
          </button>
        );
      })}
      <button
        type="button"
        className="spacer"
        aria-label="Ajustes"
        title="Ajustes (⌘,)"
        aria-current={view === "settings" ? "page" : undefined}
        onClick={() => onView(view === "settings" ? "term" : "settings")}
      >
        <Icon d={ICON.gear} />
      </button>
    </nav>
  );
}
