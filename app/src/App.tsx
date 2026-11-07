import { useEffect, useState } from "react";
import { Ribbon, TitleBar } from "./components/Chrome";
import { Sidebar } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { TerminalView } from "./components/TerminalView";
import type { SessionKind, ThemeName } from "./types";
import { useHarness } from "./useHarness";

const THEMES: ThemeName[] = ["dracula", "grafite", "claro"];

function stored<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}

function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // armazenamento indisponível: só não lembra
  }
}

export default function App() {
  const harness = useHarness();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [folder, setFolder] = useState<string>(() => stored<string>("harness.folder", "~"));
  const [theme, setTheme] = useState<ThemeName>(() => stored<ThemeName>("harness.theme", "dracula"));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    remember("harness.theme", theme);
  }, [theme]);

  useEffect(() => remember("harness.folder", folder), [folder]);

  // Mantém uma aba ativa válida quando sessões aparecem ou somem.
  useEffect(() => {
    if (activeId && harness.sessions.some((s) => s.id === activeId)) return;
    setActiveId(harness.sessions[harness.sessions.length - 1]?.id ?? null);
  }, [harness.sessions, activeId]);

  const create = async (kind: SessionKind) => {
    const session = await harness.create(kind, folder.trim() || "~");
    if (session) setActiveId(session.id);
  };

  const active = harness.sessions.find((s) => s.id === activeId) ?? null;
  const ready = harness.connection === "online" && harness.client !== null;

  return (
    <div className="app">
      <TitleBar theme={theme} onCycleTheme={() => setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length])} />
      <div className="body">
        <Ribbon />
        <Sidebar
          sessions={harness.sessions}
          activeId={activeId}
          folder={folder}
          ready={ready}
          error={harness.error}
          onFolder={setFolder}
          onCreate={create}
          onSelect={setActiveId}
          onClose={harness.close}
        />
        <main className="main">
          {harness.client &&
            harness.sessions.map((session) => (
              <TerminalView
                key={session.id}
                session={session}
                client={harness.client!}
                active={session.id === activeId}
                theme={theme}
              />
            ))}
          {harness.sessions.length === 0 && (
            <div className="empty">
              <h1>Nenhum terminal aberto</h1>
              <p>
                Escolha a pasta de trabalho na barra lateral e abra o Claude Code. Ele roda aqui do mesmo jeito que no
                seu terminal, com a sua conta, e o Harness mostra o contexto e a cota do plano na barra de baixo.
              </p>
              <button type="button" className="btn primary" disabled={!ready} onClick={() => create("claude")}>
                Abrir o Claude Code em {folder.trim() || "~"}
              </button>
              {!ready && <span className="small">{harness.connection === "offline" ? "núcleo fora do ar" : "conectando ao núcleo…"}</span>}
            </div>
          )}
        </main>
      </div>
      <StatusBar usage={harness.usage} active={active} connection={harness.connection} />
    </div>
  );
}
