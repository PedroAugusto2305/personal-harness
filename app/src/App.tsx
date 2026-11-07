import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Ribbon, THEME_LABEL, TitleBar } from "./components/Chrome";
import { Dock, type DockHandle } from "./components/Dock";
import { Palette, type PaletteItem } from "./components/Palette";
import { Settings, THEMES, type SettingsSection } from "./components/Settings";
import { Sidebar } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { Tabs } from "./components/Tabs";
import { TerminalView, type Slot } from "./components/TerminalView";
import { inTauri, type NewSessionOptions } from "./lib/core";
import { KIND_COLOR, KIND_GLYPH, KIND_LABEL } from "./lib/format";
import { quotePaths, terminals } from "./lib/terminals";
import type { Provider, Session, SessionKind, ThemeName, View } from "./types";
import { useHarness } from "./useHarness";

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

type Focus = 0 | 1 | "float";

/** O que está debaixo do ponto: um terminal (id), a barra de entrada ("dock") ou nada. */
function dropTargetAt(x: number, y: number): string | null {
  const el = document.elementFromPoint(x, y);
  return el?.closest<HTMLElement>("[data-drop]")?.dataset.drop ?? null;
}

export default function App() {
  const harness = useHarness();
  const [view, setView] = useState<View>("term");
  const [section, setSection] = useState<SettingsSection>("contas");
  const [folder, setFolder] = useState<string>(() => stored<string>("harness.folder", "~"));
  const [theme, setTheme] = useState<ThemeName>(() => stored<ThemeName>("harness.theme", "dracula"));
  const [language, setLanguage] = useState<string>(() => stored<string>("harness.voice.language", "pt"));
  const [slots, setSlots] = useState<[string | null, string | null]>([null, null]);
  const [split, setSplit] = useState(false);
  const [focus, setFocus] = useState<Focus>(0);
  const [floatOpen, setFloatOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const [drop, setDrop] = useState<string | null>(null);
  const dock = useRef<DockHandle>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    remember("harness.theme", theme);
  }, [theme]);
  useEffect(() => remember("harness.folder", folder), [folder]);
  useEffect(() => remember("harness.voice.language", language), [language]);

  const tabs = useMemo(() => harness.sessions.filter((s) => s.tag !== "float"), [harness.sessions]);
  const floatSession = harness.sessions.find((s) => s.tag === "float") ?? null;
  const tabIds = tabs.map((s) => s.id).join(",");

  // Mantém os lugares da tela válidos quando terminais abrem ou fecham.
  useEffect(() => {
    const ids = new Set(tabs.map((s) => s.id));
    setSlots(([a, b]) => {
      let right = b && ids.has(b) ? b : null;
      let left = a && ids.has(a) ? a : null;
      if (!left) {
        left = right ?? [...tabs].reverse().find((s) => s.id !== right)?.id ?? null;
        if (left === right) right = null;
      }
      return left === a && right === b ? [a, b] : [left, right];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabIds]);

  useEffect(() => {
    if (!floatSession && floatOpen) setFloatOpen(false);
  }, [floatSession, floatOpen]);

  // Último painel em foco fora do flutuante, para voltar a ele quando o flutuante fecha.
  const paneFocus = useRef<0 | 1>(0);
  if (focus !== "float") paneFocus.current = focus;

  useEffect(() => {
    if (focus === "float" && !floatOpen) setFocus(split ? paneFocus.current : 0);
    else if (focus === 1 && !split) setFocus(0);
  }, [focus, floatOpen, split]);

  const focusedId =
    focus === "float" && floatOpen && floatSession
      ? floatSession.id
      : split && focus === 1
        ? (slots[1] ?? slots[0])
        : slots[0];
  const focused = harness.sessions.find((s) => s.id === focusedId) ?? null;
  const ready = harness.connection === "online" && harness.client !== null;

  const accountName = (session: Session): string | null => {
    if (session.kind === "shell" || !session.account) return null;
    const entry = harness.accounts[session.kind];
    if (entry.accounts.length < 2) return null; // com uma conta só, o nome é ruído
    return entry.accounts.find((a) => a.id === session.account)?.name ?? session.account;
  };

  // --- ações -------------------------------------------------------------

  const select = (id: string) => {
    setView("term");
    if (floatSession?.id === id) {
      setFloatOpen(true);
      setFocus("float");
      return;
    }
    if (split) {
      if (slots[0] === id) return setFocus(0);
      if (slots[1] === id) return setFocus(1);
      const index = focus === 1 ? 1 : 0;
      setSlots(([a, b]) => (index === 0 ? [id, b] : [a, id]));
      setFocus(index);
    } else {
      setSlots(([, b]) => [id, b === id ? null : b]);
      setFocus(0);
    }
  };

  const create = async (kind: SessionKind, options: NewSessionOptions = {}) => {
    const session = await harness.create(kind, folder.trim() || "~", options);
    if (session) select(session.id);
    return session;
  };

  const openAccountSession = (provider: Provider, accountId: string, title: string) => {
    void create(provider, { account: accountId, title });
  };

  const toggleSplit = () => {
    setView("term");
    if (split) {
      const keep = focus === 1 && slots[1] ? 1 : 0;
      setSlots(([a, b]) => (keep === 1 ? [b, a] : [a, b]));
      setSplit(false);
      setFocus(0);
      return;
    }
    setSlots(([a, b]) => {
      const right = b && b !== a && tabs.some((s) => s.id === b) ? b : ([...tabs].reverse().find((s) => s.id !== a)?.id ?? null);
      return [a, right];
    });
    setSplit(true);
    setFocus(1);
  };

  const unsplitKeeping = (keep: 0 | 1) => {
    setSlots(([a, b]) => (keep === 1 ? [b, a] : [a, b]));
    setSplit(false);
    setFocus(0);
  };

  const toggleFloat = async () => {
    if (floatOpen) {
      setFloatOpen(false);
      return;
    }
    setView("term");
    if (!floatSession) {
      const session = await harness.create("shell", folder.trim() || "~", { tag: "float", title: "Flutuante" });
      if (!session) return;
    }
    setFloatOpen(true);
    setFocus("float");
  };

  /** Arquivos soltos: no terminal, o caminho vai direto; na barra, entra no texto. */
  const deliverPaths = (target: string | null, paths: string[]) => {
    if (!paths.length) return;
    const text = quotePaths(paths);
    const id = target && target !== "dock" ? target : null;
    if (target === "dock" || !(id ?? live.current.focusedId)) {
      dock.current?.insert(text);
      return;
    }
    const handle = terminals.get(id ?? live.current.focusedId!);
    if (!handle) return dock.current?.insert(text);
    handle.paste(`${text} `);
    handle.focus();
  };

  // Valores atuais para os ouvintes registrados uma vez só.
  const live = useRef({ focusedId, deliverPaths });
  live.current = { focusedId, deliverPaths };

  // --- arrastar arquivos -------------------------------------------------

  useEffect(() => {
    if (!inTauri()) return;
    let unlisten: (() => void) | undefined;
    let gone = false;
    (async () => {
      const { getCurrentWebview } = await import("@tauri-apps/api/webview");
      const stop = await getCurrentWebview().onDragDropEvent((event) => {
        const payload = event.payload;
        if (payload.type === "leave") return setDrop(null);
        const ratio = window.devicePixelRatio || 1;
        const target = dropTargetAt(payload.position.x / ratio, payload.position.y / ratio);
        if (payload.type === "drop") {
          setDrop(null);
          live.current.deliverPaths(target, payload.paths);
        } else {
          setDrop(target ?? live.current.focusedId);
        }
      });
      if (gone) stop();
      else unlisten = stop;
    })();
    return () => {
      gone = true;
      unlisten?.();
    };
  }, []);

  // No navegador (desenvolvimento) não há caminho do arquivo: sobe para o núcleo e usa o salvo.
  const browserDrag = inTauri()
    ? {}
    : {
        onDragOver: (event: DragEvent) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          setDrop(dropTargetAt(event.clientX, event.clientY) ?? focusedId);
        },
        onDragLeave: (event: DragEvent) => {
          if (event.relatedTarget === null) setDrop(null);
        },
        onDrop: async (event: DragEvent) => {
          event.preventDefault();
          setDrop(null);
          const target = dropTargetAt(event.clientX, event.clientY);
          const list = Array.from(event.dataTransfer.files);
          const client = harness.client;
          if (!client || !list.length) return;
          const paths = await harness.run(() => Promise.all(list.map((file) => client.upload(file, file.name))));
          if (paths) deliverPaths(target, paths);
        },
      };

  // --- atalhos -----------------------------------------------------------

  const keys = useRef<(event: KeyboardEvent) => void>(() => undefined);
  keys.current = (event: KeyboardEvent) => {
    const cmd = event.metaKey && !event.ctrlKey && !event.altKey;
    let handled = true;
    if (cmd && !event.shiftKey && event.key.toLowerCase() === "k") setPalette((open) => !open);
    else if (cmd && !event.shiftKey && event.key.toLowerCase() === "d") toggleSplit();
    else if (cmd && event.shiftKey && event.code === "KeyM") {
      setView("term");
      dock.current?.toggleVoice();
    } else if (cmd && !event.shiftKey && event.key.toLowerCase() === "l") {
      setView("term");
      dock.current?.focus();
    } else if (cmd && event.key === ",") setView((v) => (v === "settings" ? "term" : "settings"));
    else if (cmd && /^[1-9]$/.test(event.key) && tabs[Number(event.key) - 1]) select(tabs[Number(event.key) - 1].id);
    else if (event.ctrlKey && !event.metaKey && event.code === "Backquote") void toggleFloat();
    else handled = false;
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => keys.current(event);
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  // --- salto rápido ------------------------------------------------------

  const paletteItems: PaletteItem[] = [
    ...harness.sessions.map((session, index) => ({
      id: `go-${session.id}`,
      group: "Terminais",
      label: session.title,
      hint: session.tag === "float" ? "⌃`" : index < 9 ? `⌘${index + 1}` : undefined,
      glyph: <span style={{ color: KIND_COLOR[session.kind] }}>{KIND_GLYPH[session.kind]}</span>,
      run: () => select(session.id),
    })),
    ...(["claude", "codex", "shell"] as SessionKind[]).map((kind) => ({
      id: `new-${kind}`,
      group: "Abrir",
      label: `Novo ${KIND_LABEL[kind]} em ${folder.trim() || "~"}`,
      glyph: <span style={{ color: KIND_COLOR[kind] }}>{KIND_GLYPH[kind]}</span>,
      run: () => void create(kind),
    })),
    { id: "split", group: "Tela", label: split ? "Juntar a tela" : "Dividir a tela", hint: "⌘D", run: toggleSplit },
    { id: "float", group: "Tela", label: floatOpen ? "Esconder o terminal flutuante" : "Terminal flutuante", hint: "⌃`", run: () => void toggleFloat() },
    { id: "voice", group: "Tela", label: "Ditar para o terminal em foco", hint: "⌘⇧M", run: () => dock.current?.toggleVoice() },
    ...harness.accounts.claude.accounts
      .filter((a) => !a.active)
      .map((a) => ({ id: `acc-claude-${a.id}`, group: "Contas", label: `Usar a conta ${a.name} no Claude Code`, run: () => void harness.run((c) => c.activateAccount("claude", a.id)) })),
    ...harness.accounts.codex.accounts
      .filter((a) => !a.active)
      .map((a) => ({ id: `acc-codex-${a.id}`, group: "Contas", label: `Usar a conta ${a.name} no Codex`, run: () => void harness.run((c) => c.activateAccount("codex", a.id)) })),
    ...THEMES.filter((t) => t !== theme).map((t) => ({ id: `theme-${t}`, group: "Aparência", label: `Tema ${THEME_LABEL[t]}`, run: () => setTheme(t) })),
    { id: "settings-accounts", group: "Ajustes", label: "Contas e uso", hint: "⌘,", run: () => (setSection("contas"), setView("settings")) },
    { id: "settings-voice", group: "Ajustes", label: "Voz", run: () => (setSection("voz"), setView("settings")) },
    { id: "settings-about", group: "Ajustes", label: "Atalhos", run: () => (setSection("sobre"), setView("settings")) },
  ];

  // --- tela --------------------------------------------------------------

  const slotOf = (id: string): Slot => {
    if (floatSession?.id === id) return floatOpen ? "float" : "hidden";
    if (slots[0] === id) return "left";
    if (split && slots[1] === id) return "right";
    return "hidden";
  };

  const focusSlot = (id: string) => {
    if (floatSession?.id === id) return setFocus("float");
    if (split && slots[1] === id) return setFocus(1);
    if (slots[0] === id) return setFocus(0);
  };

  return (
    <div className="app" {...browserDrag}>
      <TitleBar
        theme={theme}
        onCycleTheme={() => setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length])}
        onPalette={() => setPalette(true)}
      />
      <div className="body">
        <Ribbon view={view} onView={setView} />
        {view === "settings" && (
          <Settings
            section={section}
            onSection={setSection}
            client={harness.client}
            accounts={harness.accounts}
            usage={harness.usage}
            theme={theme}
            onTheme={setTheme}
            language={language}
            onLanguage={setLanguage}
            run={harness.run}
            onOpenSession={(provider, accountId, title) => {
              setView("term");
              openAccountSession(provider, accountId, title);
            }}
          />
        )}
        {view === "term" && (
          <Sidebar
            sessions={tabs}
            focusedId={focusedId}
            folder={folder}
            ready={ready}
            error={harness.error}
            accounts={harness.accounts}
            accountName={accountName}
            onFolder={setFolder}
            onCreate={(kind) => void create(kind)}
            onSelect={select}
            onClose={harness.close}
            onAccounts={() => {
              setSection("contas");
              setView("settings");
            }}
            onDismissError={() => harness.setError(null)}
          />
        )}
        {/* Os terminais ficam sempre montados; nos Ajustes, só somem da tela. */}
        <main className="main" hidden={view !== "term"}>
          {tabs.length > 0 && (
            <Tabs
              sessions={tabs}
              visible={split ? slots : [slots[0]]}
              focusedId={focusedId}
              split={split}
              floatOpen={floatOpen}
              onSelect={select}
              onClose={harness.close}
              onToggleSplit={toggleSplit}
              onToggleFloat={() => void toggleFloat()}
              onPalette={() => setPalette(true)}
            />
          )}
          <div className="panes" data-split={split ? "true" : undefined}>
            {harness.client &&
              harness.sessions.map((session) => {
                const slot = slotOf(session.id);
                return (
                  <TerminalView
                    key={session.id}
                    session={session}
                    client={harness.client!}
                    theme={theme}
                    slot={slot}
                    focused={session.id === focusedId}
                    split={split}
                    accountName={accountName(session)}
                    dropping={drop === session.id}
                    onFocus={() => focusSlot(session.id)}
                    onHide={
                      slot === "float"
                        ? () => setFloatOpen(false)
                        : split && slot !== "hidden"
                          ? () => unsplitKeeping(slot === "left" ? 1 : 0)
                          : undefined
                    }
                  />
                );
              })}
            {split && !slots[1] && tabs.length > 0 && (
              <div className="pane-empty" onMouseDown={() => setFocus(1)} data-focused={focus === 1 ? "true" : undefined}>
                <span className="small">Lado direito vazio. Escolha uma aba ou abra um terminal aqui:</span>
                <div className="pane-empty-buttons">
                  {(["claude", "codex", "shell"] as SessionKind[]).map((kind) => (
                    <button key={kind} type="button" className="btn" disabled={!ready} onClick={() => void create(kind)}>
                      <span style={{ color: KIND_COLOR[kind] }}>{KIND_GLYPH[kind]}</span> {KIND_LABEL[kind]}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {tabs.length === 0 && (
              <div className="empty">
                <h1>Nenhum terminal aberto</h1>
                <p>
                  Escolha a pasta de trabalho na barra lateral e abra o Claude Code ou o Codex. Eles rodam aqui do mesmo
                  jeito que no seu terminal, com a sua conta, e o Harness mostra o contexto e a cota do plano embaixo.
                </p>
                <div className="pane-empty-buttons">
                  <button type="button" className="btn primary" disabled={!ready} onClick={() => void create("claude")}>
                    ✻ Claude Code
                  </button>
                  <button type="button" className="btn" disabled={!ready} onClick={() => void create("codex")}>
                    ◇ Codex
                  </button>
                  <button type="button" className="btn" disabled={!ready} onClick={() => void create("shell")}>
                    &gt;_ Shell
                  </button>
                </div>
                <span className="small">
                  {!ready
                    ? harness.connection === "offline"
                      ? "núcleo fora do ar"
                      : "conectando ao núcleo…"
                    : `em ${folder.trim() || "~"} · ⌘K para tudo`}
                </span>
              </div>
            )}
          </div>
          <Dock
            ref={dock}
            client={harness.client}
            target={focused}
            targetAccount={focused ? accountName(focused) : null}
            language={language}
            dropping={drop === "dock"}
          />
        </main>
      </div>
      <StatusBar
        usage={harness.usage}
        accounts={harness.accounts}
        active={focused}
        connection={harness.connection}
        onOpenAccounts={() => {
          setSection("contas");
          setView("settings");
        }}
      />
      {palette && <Palette items={paletteItems} onClose={() => setPalette(false)} />}
    </div>
  );
}
