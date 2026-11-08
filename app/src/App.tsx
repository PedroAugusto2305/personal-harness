import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Agents } from "./components/Agents";
import { AgentSprite } from "./components/AgentSprite";
import { BrowserView, type WebInfo } from "./components/BrowserView";
import { Ribbon, THEME_LABEL, TitleBar } from "./components/Chrome";
import { Confirm } from "./components/Confirm";
import { DocView, docTitle, type DocTab } from "./components/DocView";
import { Dock, type DockHandle } from "./components/Dock";
import { Inspector, type InspectorTab } from "./components/Inspector";
import { Palette, type PaletteItem } from "./components/Palette";
import { Settings, THEMES, type SettingsSection } from "./components/Settings";
import { Sidebar, type Selected } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { Tabs, type TabItem } from "./components/Tabs";
import { TerminalView, type Slot } from "./components/TerminalView";
import { browser, describePick, onBrowserEvent, openExternal, type BrowserState, type DesignPick, type ForwardedKey } from "./lib/browser";
import { CoreError, inTauri, type NewSessionOptions } from "./lib/core";
import { KIND_COLOR, KIND_GLYPH, KIND_LABEL, STATUS_COLOR, shortPath } from "./lib/format";
import { quotePaths, submit, terminals } from "./lib/terminals";
import type { Agent, GitFile, Project, ReviewNote, Session, SessionKind, ThemeName, View, Worktree } from "./types";
import { useHarness } from "./useHarness";
import { placeOf, useWorktrees, worktreeLabel, type Place } from "./useWorktrees";

function stored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return fallback;
    return typeof fallback === "string" ? (raw as T) : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function remember(key: string, value: unknown) {
  try {
    localStorage.setItem(key, typeof value === "string" ? value : JSON.stringify(value));
  } catch {
    // armazenamento indisponível: só não lembra
  }
}

type Focus = 0 | 1 | "float";
type PaletteMode = "all" | "files" | null;

interface PendingDelete {
  project: Project;
  worktree: Worktree;
  force: boolean;
  reason: string | null;
  busyTerminals: string[];
}

/** O que está debaixo do ponto: um terminal (id), a barra de entrada ("dock") ou nada. */
function dropTargetAt(x: number, y: number): string | null {
  const el = document.elementFromPoint(x, y);
  return el?.closest<HTMLElement>("[data-drop]")?.dataset.drop ?? null;
}

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export default function App() {
  const harness = useHarness();
  const wt = useWorktrees(harness.client, harness.projects, harness.worktreesTick);
  const [view, setView] = useState<View>("term");
  const [section, setSection] = useState<SettingsSection>("contas");
  const [folder, setFolder] = useState<string>(() => stored("harness.folder", "~"));
  const [selected, setSelected] = useState<Selected | null>(() => stored<Selected | null>("harness.selected", null));
  const [theme, setTheme] = useState<ThemeName>(() => stored<ThemeName>("harness.theme", "dracula"));
  const [language, setLanguage] = useState<string>(() => stored("harness.voice.language", "pt"));
  const [slots, setSlots] = useState<[string | null, string | null]>([null, null]);
  const [split, setSplit] = useState(false);
  const [focus, setFocus] = useState<Focus>(0);
  const [floatOpen, setFloatOpen] = useState(false);
  const [palette, setPalette] = useState<PaletteMode>(null);
  const [paletteFiles, setPaletteFiles] = useState<string[]>([]);
  const [drop, setDrop] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocTab[]>([]);
  const [inspectorOpen, setInspectorOpen] = useState<boolean>(() => stored("harness.inspector.open", true));
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>(() => stored<InspectorTab>("harness.inspector.tab", "changes"));
  const [notes, setNotes] = useState<Record<string, ReviewNote[]>>(() => stored("harness.notes", {}));
  const [gitTick, setGitTick] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [webInfo, setWebInfo] = useState<Record<string, WebInfo>>({});
  /** Para onde a barra de entrada manda quando o foco está numa aba que não é terminal. */
  const [dockOverride, setDockOverride] = useState<string | null>(null);
  const [urlFocusTick, setUrlFocusTick] = useState(0);
  const dock = useRef<DockHandle>(null);
  const lastTerm = useRef<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    remember("harness.theme", theme);
  }, [theme]);
  useEffect(() => remember("harness.folder", folder), [folder]);
  useEffect(() => remember("harness.selected", selected), [selected]);
  useEffect(() => remember("harness.voice.language", language), [language]);
  useEffect(() => remember("harness.inspector.open", inspectorOpen), [inspectorOpen]);
  useEffect(() => remember("harness.inspector.tab", inspectorTab), [inspectorTab]);
  useEffect(() => remember("harness.notes", notes), [notes]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const placeFor = useCallback((path: string) => placeOf(path, harness.projects, wt.byProject), [harness.projects, wt.byProject]);
  const tabs = useMemo(() => harness.sessions.filter((s) => s.tag !== "float"), [harness.sessions]);
  const floatSession = harness.sessions.find((s) => s.tag === "float") ?? null;
  const tabKeys = [...tabs.map((s) => s.id), ...docs.map((d) => d.key)];
  const tabKeyList = tabKeys.join(",");

  // Mantém os lugares da tela válidos quando abas abrem ou fecham.
  useEffect(() => {
    const keys = new Set(tabKeys);
    setSlots(([a, b]) => {
      let right = b && keys.has(b) ? b : null;
      let left = a && keys.has(a) ? a : null;
      if (!left) {
        left = right ?? [...tabKeys].reverse().find((k) => k !== right) ?? null;
        if (left === right) right = null;
      }
      return left === a && right === b ? [a, b] : [left, right];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabKeyList]);

  useEffect(() => {
    if (!floatSession && floatOpen) setFloatOpen(false);
  }, [floatSession, floatOpen]);

  const paneFocus = useRef<0 | 1>(0);
  if (focus !== "float") paneFocus.current = focus;
  useEffect(() => {
    if (focus === "float" && !floatOpen) setFocus(split ? paneFocus.current : 0);
    else if (focus === 1 && !split) setFocus(0);
  }, [focus, floatOpen, split]);

  // A worktree escolhida pode sumir (apagada por fora); volta para a pasta principal do projeto.
  useEffect(() => {
    if (!selected) return;
    const list = wt.byProject[selected.project];
    if (harness.projects.length && !harness.projects.some((p) => p.id === selected.project)) setSelected(null);
    else if (list && list.length && !list.some((w) => w.path === selected.path)) setSelected({ project: selected.project, path: list[0].path });
  }, [selected, wt.byProject, harness.projects]);

  const focusedKey =
    focus === "float" && floatOpen && floatSession ? floatSession.id : split && focus === 1 ? (slots[1] ?? slots[0]) : slots[0];
  const focusedSession = harness.sessions.find((s) => s.id === focusedKey) ?? null;
  const focusedDoc = docs.find((d) => d.key === focusedKey) ?? null;
  if (focusedSession) lastTerm.current = focusedSession.id;
  const dockTarget =
    focusedSession ??
    harness.sessions.find((s) => s.id === dockOverride) ??
    harness.sessions.find((s) => s.id === lastTerm.current) ??
    null;
  const ready = harness.connection === "online" && harness.client !== null;

  const selectedPlace: Place | null = useMemo(() => {
    if (!selected) return null;
    const project = harness.projects.find((p) => p.id === selected.project);
    const worktree = wt.byProject[selected.project]?.find((w) => w.path === selected.path);
    return project && worktree ? { project, worktree } : null;
  }, [selected, harness.projects, wt.byProject]);
  const contextPlace: Place | null =
    (focusedSession && placeFor(focusedSession.cwd)) || (focusedDoc && placeFor(focusedDoc.root)) || selectedPlace;
  const contextNotes = contextPlace ? (notes[contextPlace.worktree.path] ?? []) : [];

  const agentById = (id: string | null) => (id ? (harness.agents.find((a) => a.id === id) ?? null) : null);
  const accountName = (session: Session): string | null => {
    if (session.kind === "shell" || !session.account) return null;
    const entry = harness.accounts[session.kind];
    if (entry.accounts.length < 2) return null; // com uma conta só, o nome é ruído
    return entry.accounts.find((a) => a.id === session.account)?.name ?? session.account;
  };
  const sessionGlyph = (session: Session, size = 14) => {
    const agent = agentById(session.agent);
    return agent ? (
      <AgentSprite agent={agent} client={harness.client} size={size} />
    ) : (
      <span style={{ color: KIND_COLOR[session.kind] }}>{KIND_GLYPH[session.kind]}</span>
    );
  };

  // --- ações -------------------------------------------------------------

  const select = (key: string) => {
    setView("term");
    if (floatSession?.id === key) {
      setFloatOpen(true);
      setFocus("float");
      return;
    }
    if (split) {
      if (slots[0] === key) return setFocus(0);
      if (slots[1] === key) return setFocus(1);
      const index = focus === 1 ? 1 : 0;
      setSlots(([a, b]) => (index === 0 ? [key, b] : [a, key]));
      setFocus(index);
    } else {
      setSlots(([, b]) => [key, b === key ? null : b]);
      setFocus(0);
    }
  };

  const cwdNow = () => selectedPlace?.worktree.path ?? (folder.trim() || "~");

  const create = async (kind: SessionKind, options: NewSessionOptions & { cwd?: string | null } = {}) => {
    const { cwd, ...rest } = options;
    const session = await harness.create(kind, cwd === null ? "" : (cwd ?? cwdNow()), rest);
    if (session) select(session.id);
    return session;
  };

  const launchAgent = (agent: Agent) => {
    setView("term");
    // Agente com pasta própria (os do Brain) abre nela; os de código, na worktree escolhida.
    void create(agent.cli, { agent: agent.id, cwd: agent.folder ? null : cwdNow() });
  };

  const sessionsRef = useRef(harness.sessions);
  sessionsRef.current = harness.sessions;

  /** Espera a CLI ficar pronta para receber texto (o Claude avisa pelo hook; o Codex, só tempo). */
  const whenReady = (id: string, timeoutMs = 25000) =>
    new Promise<boolean>((resolve) => {
      const started = Date.now();
      const timer = window.setInterval(() => {
        const session = sessionsRef.current.find((s) => s.id === id);
        const elapsed = Date.now() - started;
        const ok = !!session && terminals.has(id) && (session.kind === "claude" ? session.status === "waiting" : elapsed > 4000);
        if (ok || !session || elapsed > timeoutMs) {
          window.clearInterval(timer);
          resolve(ok);
        }
      }, 300);
    });

  /** O agente da worktree: o terminal em foco, o último usado ou o mais novo; senão abre um Claude. */
  const agentSessionIn = async (place: Place): Promise<Session | null> => {
    const inside = tabs.filter((s) => s.kind !== "shell" && s.status !== "exited" && placeFor(s.cwd)?.worktree.path === place.worktree.path);
    const found =
      inside.find((s) => s.id === focusedKey) ?? inside.find((s) => s.id === lastTerm.current) ?? inside[inside.length - 1] ?? null;
    if (found) return found;
    setToast("Abrindo o Claude nesta worktree…");
    const session = await create("claude", { cwd: place.worktree.path });
    if (!session) return null;
    await whenReady(session.id);
    return session;
  };

  const askCommit = async (staged: number) => {
    if (!contextPlace) return;
    const prompt = staged
      ? "Escreva a mensagem e faça o commit só das mudanças já marcadas nesta worktree (git diff --cached), no padrão das mensagens recentes (git log -5 --oneline). Não marque nem desmarque outros arquivos."
      : "Veja as mudanças desta worktree (git status e git diff), marque o que faz parte do mesmo trabalho e faça o commit com uma mensagem no padrão das mensagens recentes (git log -5 --oneline). Se houver mais de um assunto, me pergunte antes.";
    const session = await agentSessionIn(contextPlace);
    if (!session) return;
    select(session.id);
    submit(session.id, prompt);
  };

  const sendNotes = async () => {
    if (!contextPlace || !contextNotes.length) return;
    const branch = worktreeLabel(contextPlace.worktree);
    const text = [
      `Notas da revisão do diff (${branch}):`,
      ...contextNotes.map((n) => `- ${n.file}:${n.line} — ${n.text}${n.code ? `\n  linha: ${n.code}` : ""}`),
      "Ajuste o código conforme cada nota e me diga o que mudou.",
    ].join("\n");
    const session = await agentSessionIn(contextPlace);
    if (!session) return;
    select(session.id);
    // Vai para a barra de entrada, para revisar antes de mandar.
    window.setTimeout(() => dock.current?.insert(text), 50);
  };

  const addNote = (root: string, note: Omit<ReviewNote, "id">) =>
    setNotes((all) => ({ ...all, [root]: [...(all[root] ?? []), { ...note, id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}` }] }));
  const removeNote = (root: string, id: string) => setNotes((all) => ({ ...all, [root]: (all[root] ?? []).filter((n) => n.id !== id) }));

  const openDoc = (doc: Omit<DocTab, "key">) => {
    const key = `doc:${doc.type}:${doc.root}:${doc.path}`;
    setDocs((all) => (all.some((d) => d.key === key) ? all : [...all, { ...doc, key }]));
    select(key);
  };
  const openDiff = (file: GitFile) => {
    if (contextPlace) openDoc({ type: "diff", root: contextPlace.worktree.path, path: file.path, untracked: file.untracked });
  };
  const openFile = (path: string, root = contextPlace?.worktree.path) => {
    if (root) openDoc({ type: "file", root, path });
  };

  const webCount = useRef(0);
  /** Aba de navegador nova, ligada à worktree em foco (é para o agente dela que o modo de design manda). */
  const openWeb = (url?: string, options: { root?: string; incognito?: boolean } = {}) => {
    const root = options.root ?? contextPlace?.worktree.path ?? "";
    const port = contextPlace ? harness.sessions.find((s) => placeFor(s.cwd)?.worktree.path === root && s.ports.length)?.ports[0] : undefined;
    const start = url ?? (port ? `http://localhost:${port}` : "about:blank");
    webCount.current += 1;
    const label = `browser-${Date.now().toString(36)}${webCount.current}`;
    const key = `doc:web:${label}`;
    setDocs((all) => [...all, { key, type: "web", root, path: start, label, incognito: options.incognito }]);
    setWebInfo((all) => ({ ...all, [label]: { url: start, title: null, loading: start !== "about:blank", design: false } }));
    select(key);
    if (start === "about:blank") window.setTimeout(() => setUrlFocusTick((n) => n + 1), 50);
  };

  const closeTab = (key: string) => {
    if (key.startsWith("doc:")) setDocs((all) => all.filter((d) => d.key !== key));
    else void harness.close(key);
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
      const right = b && b !== a && tabKeys.includes(b) ? b : ([...tabKeys].reverse().find((k) => k !== a) ?? null);
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
      const session = await harness.create("shell", cwdNow(), { tag: "float", title: "Flutuante" });
      if (!session) return;
    }
    setFloatOpen(true);
    setFocus("float");
  };

  // --- projetos e worktrees ------------------------------------------------

  const addProject = async (path: string) => {
    const project = await harness.run((c) => c.addProject(path));
    if (!project) return false;
    setSelected({ project: project.id, path: project.path });
    harness.bumpWorktrees();
    return true;
  };

  const createWorktree = async (project: Project, name: string, copyEnv: boolean, openClaude: boolean) => {
    const created = await harness.run((c) => c.createWorktree(project.id, name, copyEnv));
    if (!created) return false;
    await wt.refresh();
    setSelected({ project: project.id, path: created.path });
    setToast(`Worktree ${created.branch} criada${created.copied.length ? `, com ${created.copied.join(", ")}` : ""}.`);
    if (openClaude) void create("claude", { cwd: created.path });
    return true;
  };

  const confirmDelete = async (closeTerminals: boolean) => {
    if (!pendingDelete || !harness.client) return;
    const { project, worktree, force } = pendingDelete;
    setDeleting(true);
    try {
      if (closeTerminals) {
        for (const s of harness.sessions.filter((s) => placeFor(s.cwd)?.worktree.path === worktree.path)) await harness.close(s.id);
      }
      const result = await harness.client.deleteWorktree(project.id, worktree.path, force);
      setPendingDelete(null);
      setDocs((all) => all.filter((d) => d.root !== worktree.path));
      setNotes((all) => {
        const { [worktree.path]: _gone, ...rest } = all;
        return rest;
      });
      if (selected?.path === worktree.path) setSelected({ project: project.id, path: project.path });
      setToast(
        result.branch_kept
          ? `Worktree apagada. O branch ${result.branch} ficou guardado: tem commits que não foram juntados.`
          : `Worktree apagada${result.branch_deleted ? `, com o branch ${result.branch}` : ""}.`,
      );
      await wt.refresh();
    } catch (cause) {
      const detail = errorText(cause);
      if (cause instanceof CoreError && cause.status === 409) {
        const busy = /terminais/.test(detail);
        setPendingDelete({
          ...pendingDelete,
          force: !busy || force,
          reason: busy ? detail : `${detail}. Apagando mesmo assim, essas mudanças se perdem.`,
          busyTerminals: busy ? detail.split(": ").pop()!.split(", ") : [],
        });
      } else {
        setPendingDelete({ ...pendingDelete, reason: detail });
      }
    } finally {
      setDeleting(false);
    }
  };

  // --- arrastar arquivos -------------------------------------------------

  /** Arquivos soltos: no terminal, o caminho vai direto; na barra, entra no texto. */
  const deliverPaths = (target: string | null, paths: string[]) => {
    if (!paths.length) return;
    const text = quotePaths(paths);
    const id = target && target !== "dock" ? target : null;
    const handle = terminals.get(id ?? live.current.dockTargetId ?? "");
    if (target === "dock" || !handle) {
      dock.current?.insert(text);
      return;
    }
    handle.paste(`${text} `);
    handle.focus();
  };

  const live = useRef({ dockTargetId: dockTarget?.id ?? null, deliverPaths });
  live.current = { dockTargetId: dockTarget?.id ?? null, deliverPaths };

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
          setDrop(target ?? live.current.dockTargetId);
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

  const browserDrag = inTauri()
    ? {}
    : {
        onDragOver: (event: DragEvent) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          setDrop(dropTargetAt(event.clientX, event.clientY) ?? dockTarget?.id ?? null);
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

  const openFilePalette = async () => {
    if (!contextPlace || !harness.client) {
      setToast("Escolha uma worktree para abrir arquivos.");
      return;
    }
    const answer = await harness.run((c) => c.files(contextPlace.worktree.path));
    if (!answer) return;
    setPaletteFiles(answer.files);
    setPalette("files");
  };

  const keys = useRef<(event: KeyboardEvent) => void>(() => undefined);
  keys.current = (event: KeyboardEvent) => {
    const cmd = event.metaKey && !event.ctrlKey && !event.altKey;
    const key = event.key.toLowerCase();
    let handled = true;
    if (cmd && !event.shiftKey && key === "k") setPalette((open) => (open ? null : "all"));
    else if (cmd && !event.shiftKey && key === "p") void openFilePalette();
    else if (cmd && !event.shiftKey && key === "d") toggleSplit();
    else if (cmd && event.shiftKey && event.code === "KeyB") setInspectorOpen((v) => !v);
    else if (cmd && event.shiftKey && event.code === "KeyM") {
      setView("term");
      dock.current?.toggleVoice();
    } else if (cmd && !event.shiftKey && key === "l") {
      setView("term");
      if (focusedDoc?.type === "web") setUrlFocusTick((n) => n + 1);
      else dock.current?.focus();
    } else if (cmd && !event.shiftKey && focusedDoc?.type === "web" && (key === "r" || key === "[" || key === "]")) {
      void browser.go(focusedDoc.label!, key === "r" ? "reload" : key === "[" ? "back" : "forward").catch(() => undefined);
    } else if (cmd && event.key === ",") setView((v) => (v === "settings" ? "term" : "settings"));
    else if (cmd && /^[1-9]$/.test(event.key) && tabKeys[Number(event.key) - 1]) select(tabKeys[Number(event.key) - 1]);
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

  // --- navegador embutido: eventos que vêm das páginas ---------------------------

  const browserLive = useRef({ docs, placeFor, keys, openWeb, setToast });
  browserLive.current = { docs, placeFor, keys, openWeb, setToast };

  const handlePick = async (label: string, data: string) => {
    const doc = docs.find((d) => d.label === label);
    let pick: DesignPick;
    try {
      pick = JSON.parse(data) as DesignPick;
    } catch {
      return;
    }
    const place = doc?.root ? placeFor(doc.root) : null;
    const text = describePick(pick, doc?.root || null);
    let target: Session | null = null;
    if (place) {
      const inside = tabs.filter((s) => s.kind !== "shell" && s.status !== "exited" && placeFor(s.cwd)?.worktree.path === place.worktree.path);
      target = inside.find((s) => s.id === lastTerm.current) ?? inside[inside.length - 1] ?? null;
      if (!target) {
        target = await agentSessionIn(place); // abre um Claude na worktree
        if (doc) select(doc.key); // e volta para a página
      }
    }
    if (target) setDockOverride(target.id);
    window.setTimeout(() => dock.current?.insert(text), 30);
    setToast(target ? `Elemento mandado para a barra de entrada de ${target.title}.` : "Elemento na barra de entrada. Escolha um terminal para mandar.");
  };
  const pickRef = useRef(handlePick);
  pickRef.current = handlePick;

  useEffect(() => {
    if (!inTauri()) return;
    const stops: Promise<() => void>[] = [
      onBrowserEvent<BrowserState>("browser:state", (state) =>
        setWebInfo((all) => {
          const prev = all[state.label] ?? { url: "about:blank", title: null, loading: false, design: false };
          return {
            ...all,
            [state.label]: {
              ...prev,
              url: state.url ?? prev.url,
              title: state.title ?? (state.url && state.url !== prev.url ? null : prev.title),
              loading: state.loading ?? prev.loading,
            },
          };
        }),
      ),
      onBrowserEvent<{ label: string; data: string }>("browser:pick", ({ label, data }) => void pickRef.current(label, data)),
      onBrowserEvent<{ label: string; data: string }>("browser:design", ({ label }) =>
        setWebInfo((all) => (all[label] ? { ...all, [label]: { ...all[label], design: false } } : all)),
      ),
      onBrowserEvent<{ label: string; data: string }>("browser:key", ({ data }) => {
        try {
          const k = JSON.parse(data) as ForwardedKey;
          const fake = {
            key: k.key,
            code: k.code,
            metaKey: k.meta,
            shiftKey: k.shift,
            ctrlKey: k.ctrl,
            altKey: k.alt,
            preventDefault: () => undefined,
            stopPropagation: () => undefined,
          } as unknown as KeyboardEvent;
          browserLive.current.keys.current(fake);
        } catch {
          // tecla malformada: ignora
        }
      }),
      onBrowserEvent<{ label: string; data: string }>("browser:new-window", ({ label, data }) => {
        const from = browserLive.current.docs.find((d) => d.label === label);
        browserLive.current.openWeb(data, { root: from?.root });
      }),
      onBrowserEvent<{ label: string; url: string; path: string | null; success: boolean | null }>("browser:download", (event) => {
        if (event.success === true) browserLive.current.setToast(`Baixado em ${event.path ? shortPath(event.path) : "~/Downloads"}.`);
        else if (event.success === false) browserLive.current.setToast("O download falhou.");
        else browserLive.current.setToast(`Baixando para ${event.path ? shortPath(event.path) : "~/Downloads"}…`);
      }),
    ];
    return () => {
      stops.forEach((stop) => void stop.then((fn) => fn()));
    };
  }, []);

  const setDesign = (doc: DocTab, on: boolean) => {
    setWebInfo((all) => ({ ...all, [doc.label!]: { ...(all[doc.label!] ?? { url: doc.path, title: null, loading: false }), design: on } }));
    void browser.design(doc.label!, on).catch((cause) => setToast(String(cause)));
    if (on) void browser.go(doc.label!, "focus").catch(() => undefined);
  };

  // Páginas nativas ficam por cima de tudo; somem quando algo da interface precisa aparecer em cima.
  const overlayOpen = !!palette || !!pendingDelete || floatOpen;

  // --- abas e salto rápido -------------------------------------------------

  const tabItems: TabItem[] = [
    ...tabs.map((session) => {
      const place = placeFor(session.cwd);
      return {
        key: session.id,
        title: session.title,
        glyph: sessionGlyph(session, 14),
        dot: STATUS_COLOR[session.status],
        hint: place ? `${place.project.name} · ${worktreeLabel(place.worktree)}` : shortPath(session.cwd),
      };
    }),
    ...docs.map((doc) => ({
      key: doc.key,
      title: docTitle(doc, doc.label ? webInfo[doc.label]?.title : null),
      glyph: <span className="mono doc-glyph">{doc.type === "diff" ? "±" : doc.type === "web" ? "◍" : "▤"}</span>,
      hint: doc.path,
    })),
  ];

  const paletteItems: PaletteItem[] =
    palette === "files"
      ? paletteFiles.map((path) => ({
          id: `file-${path}`,
          group: contextPlace ? `Arquivos · ${contextPlace.project.name} · ${worktreeLabel(contextPlace.worktree)}` : "Arquivos",
          label: path,
          run: () => openFile(path),
        }))
      : [
          ...tabItems.map((item, index) => ({
            id: `go-${item.key}`,
            group: "Abas",
            label: item.title,
            hint: index < 9 ? `⌘${index + 1}` : item.hint,
            glyph: item.glyph,
            run: () => select(item.key),
          })),
          ...(["claude", "codex", "shell"] as SessionKind[]).map((kind) => ({
            id: `new-${kind}`,
            group: "Abrir",
            label: `Novo ${KIND_LABEL[kind]} em ${selectedPlace ? `${selectedPlace.project.name} · ${worktreeLabel(selectedPlace.worktree)}` : folder.trim() || "~"}`,
            glyph: <span style={{ color: KIND_COLOR[kind] }}>{KIND_GLYPH[kind]}</span>,
            run: () => void create(kind),
          })),
          ...harness.agents.map((agent) => ({
            id: `agent-${agent.id}`,
            group: "Agentes",
            label: `Abrir ${agent.name}`,
            hint: agent.description,
            glyph: <AgentSprite agent={agent} client={harness.client} size={16} />,
            run: () => launchAgent(agent),
          })),
          ...harness.projects.flatMap((project) =>
            (wt.byProject[project.id] ?? []).map((worktree) => ({
              id: `place-${worktree.path}`,
              group: "Worktrees",
              label: `${project.name} · ${worktreeLabel(worktree)}`,
              hint: worktree.changes ? `●${worktree.changes}` : undefined,
              run: () => setSelected({ project: project.id, path: worktree.path }),
            })),
          ),
          { id: "web", group: "Navegador", label: "Abrir navegador", hint: contextPlace ? worktreeLabel(contextPlace.worktree) : undefined, run: () => openWeb() },
          { id: "web-private", group: "Navegador", label: "Abrir aba anônima", run: () => openWeb(undefined, { incognito: true }) },
          ...harness.sessions.flatMap((s) =>
            s.ports.map((port) => ({ id: `port-${s.id}-${port}`, group: "Navegador", label: `Abrir localhost:${port}`, hint: s.title, run: () => openWeb(`http://localhost:${port}`, { root: placeFor(s.cwd)?.worktree.path }) })),
          ),
          { id: "files", group: "Tela", label: "Abrir arquivo da worktree", hint: "⌘P", run: () => void openFilePalette() },
          { id: "split", group: "Tela", label: split ? "Juntar a tela" : "Dividir a tela", hint: "⌘D", run: toggleSplit },
          { id: "float", group: "Tela", label: floatOpen ? "Esconder o terminal flutuante" : "Terminal flutuante", hint: "⌃`", run: () => void toggleFloat() },
          { id: "inspector", group: "Tela", label: inspectorOpen ? "Fechar o painel da worktree" : "Painel da worktree", hint: "⌘⇧B", run: () => setInspectorOpen((v) => !v) },
          { id: "voice", group: "Tela", label: "Ditar para o terminal em foco", hint: "⌘⇧M", run: () => dock.current?.toggleVoice() },
          ...harness.accounts.claude.accounts
            .filter((a) => !a.active)
            .map((a) => ({ id: `acc-claude-${a.id}`, group: "Contas", label: `Usar a conta ${a.name} no Claude Code`, run: () => void harness.run((c) => c.activateAccount("claude", a.id)) })),
          ...harness.accounts.codex.accounts
            .filter((a) => !a.active)
            .map((a) => ({ id: `acc-codex-${a.id}`, group: "Contas", label: `Usar a conta ${a.name} no Codex`, run: () => void harness.run((c) => c.activateAccount("codex", a.id)) })),
          ...THEMES.filter((t) => t !== theme).map((t) => ({ id: `theme-${t}`, group: "Aparência", label: `Tema ${THEME_LABEL[t]}`, run: () => setTheme(t) })),
          { id: "agents", group: "Ajustes", label: "Agentes", run: () => setView("agents") },
          { id: "settings-accounts", group: "Ajustes", label: "Contas e uso", hint: "⌘,", run: () => (setSection("contas"), setView("settings")) },
          { id: "settings-voice", group: "Ajustes", label: "Voz", run: () => (setSection("voz"), setView("settings")) },
          { id: "settings-about", group: "Ajustes", label: "Atalhos", run: () => (setSection("sobre"), setView("settings")) },
        ];

  // --- tela --------------------------------------------------------------

  const slotOf = (key: string): Slot => {
    if (floatSession?.id === key) return floatOpen ? "float" : "hidden";
    if (slots[0] === key) return "left";
    if (split && slots[1] === key) return "right";
    return "hidden";
  };

  const focusSlot = (key: string) => {
    if (!key.startsWith("doc:")) setDockOverride(null);
    if (floatSession?.id === key) return setFocus("float");
    if (split && slots[1] === key) return setFocus(1);
    if (slots[0] === key) return setFocus(0);
  };

  const inspectorSessions = contextPlace ? harness.sessions.filter((s) => placeFor(s.cwd)?.worktree.path === contextPlace.worktree.path) : [];

  return (
    <div className="app" {...browserDrag}>
      <TitleBar
        theme={theme}
        onCycleTheme={() => setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length])}
        onPalette={() => setPalette("all")}
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
              void create(provider, { account: accountId, title });
            }}
          />
        )}
        {view === "agents" && (
          <Agents client={harness.client} agents={harness.agents} accounts={harness.accounts} run={harness.run} onLaunch={launchAgent} />
        )}
        {view === "term" && (
          <Sidebar
            client={harness.client}
            projects={harness.projects}
            worktrees={wt.byProject}
            worktreeErrors={wt.errors}
            sessions={tabs}
            agents={harness.agents}
            accounts={harness.accounts}
            focusedId={focusedSession?.id ?? null}
            selected={selected}
            folder={folder}
            ready={ready}
            error={harness.error}
            accountName={accountName}
            onSelectPlace={setSelected}
            onFolder={setFolder}
            onCreate={(kind) => void create(kind)}
            onLaunchAgent={launchAgent}
            onSelect={select}
            onClose={harness.close}
            onAddProject={addProject}
            onRemoveProject={(project) => {
              void harness.run((c) => c.removeProject(project.id)).then(() => setToast(`${project.name} saiu da lista; o repositório continua no disco.`));
              if (selected?.project === project.id) setSelected(null);
            }}
            onCreateWorktree={createWorktree}
            onDeleteWorktree={(project, worktree) => setPendingDelete({ project, worktree, force: false, reason: null, busyTerminals: [] })}
            onAccounts={() => {
              setSection("contas");
              setView("settings");
            }}
            onAgents={() => setView("agents")}
            onDismissError={() => harness.setError(null)}
          />
        )}
        {/* Os terminais ficam sempre montados; nas outras telas, só somem. */}
        <main className="main" hidden={view !== "term"}>
          {tabItems.length > 0 && (
            <Tabs
              items={tabItems}
              visible={split ? slots : [slots[0]]}
              focusedKey={focusedKey}
              split={split}
              floatOpen={floatOpen}
              inspectorOpen={inspectorOpen}
              onSelect={select}
              onClose={closeTab}
              onToggleSplit={toggleSplit}
              onToggleFloat={() => void toggleFloat()}
              onToggleInspector={() => setInspectorOpen((v) => !v)}
              onPalette={() => setPalette("all")}
            />
          )}
          <div className="workspace">
            <div className="panes" data-split={split ? "true" : undefined}>
              {harness.client &&
                harness.sessions.map((session) => {
                  const slot = slotOf(session.id);
                  const agent = agentById(session.agent);
                  const place = placeFor(session.cwd);
                  return (
                    <TerminalView
                      key={session.id}
                      session={session}
                      client={harness.client!}
                      theme={theme}
                      slot={slot}
                      focused={session.id === focusedKey}
                      split={split}
                      accountName={accountName(session)}
                      badge={agent ? <AgentSprite agent={agent} client={harness.client} size={16} /> : undefined}
                      place={place ? `${place.project.name} · ${worktreeLabel(place.worktree)}` : null}
                      dropping={drop === session.id}
                      onLink={(url, external) => (external ? void openExternal(url) : openWeb(url, { root: place?.worktree.path }))}
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
              {harness.client &&
                docs.map((doc) => {
                  const slot = slotOf(doc.key);
                  const docSlot = slot === "float" ? "hidden" : slot;
                  if (doc.type === "web") {
                    return (
                      <BrowserView
                        key={doc.key}
                        label={doc.label!}
                        initialUrl={doc.path}
                        incognito={!!doc.incognito}
                        info={webInfo[doc.label!]}
                        shown={docSlot !== "hidden" && view === "term" && !overlayOpen}
                        slot={docSlot}
                        focused={doc.key === focusedKey}
                        focusUrlSignal={urlFocusTick}
                        onFocus={() => focusSlot(doc.key)}
                        onDesign={(on) => setDesign(doc, on)}
                        onError={setToast}
                      />
                    );
                  }
                  return (
                    <DocView
                      key={doc.key}
                      doc={doc}
                      client={harness.client!}
                      visible={docSlot !== "hidden" && view === "term"}
                      focused={doc.key === focusedKey && split}
                      slot={docSlot}
                      notes={notes[doc.root] ?? []}
                      onAddNote={(note) => addNote(doc.root, note)}
                      onRemoveNote={(id) => removeNote(doc.root, id)}
                      onFocus={() => focusSlot(doc.key)}
                      onOpenFile={(path) => openFile(path, doc.root)}
                      onError={setToast}
                    />
                  );
                })}
              {split && !slots[1] && tabItems.length > 0 && (
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
              {tabItems.length === 0 && (
                <div className="empty">
                  <h1>Nenhum terminal aberto</h1>
                  <p>
                    {harness.projects.length === 0
                      ? "Adicione um projeto na barra lateral para trabalhar por worktree, ou abra um terminal numa pasta qualquer."
                      : "Escolha uma worktree na barra lateral e abra o Claude Code, o Codex ou um agente nela."}
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
                      : `em ${selectedPlace ? `${selectedPlace.project.name} · ${worktreeLabel(selectedPlace.worktree)}` : folder.trim() || "~"} · ⌘K para tudo`}
                  </span>
                </div>
              )}
            </div>
            {inspectorOpen && (
              <Inspector
                client={harness.client}
                place={contextPlace}
                tab={inspectorTab}
                onTab={setInspectorTab}
                sessions={inspectorSessions}
                notes={contextNotes}
                tick={gitTick}
                onOpenDiff={openDiff}
                onOpenUrl={(url) => openWeb(url, { root: contextPlace?.worktree.path })}
                onOpenFile={(path) => openFile(path)}
                onAskCommit={(staged) => void askCommit(staged)}
                onSendNotes={() => void sendNotes()}
                onClearNotes={() => {
                  if (contextPlace) setNotes((all) => ({ ...all, [contextPlace.worktree.path]: [] }));
                }}
                onChanged={() => {
                  setGitTick((n) => n + 1);
                  void wt.refresh();
                }}
                onError={(message) => harness.setError(message)}
                onClose={() => setInspectorOpen(false)}
              />
            )}
          </div>
          <Dock
            ref={dock}
            client={harness.client}
            target={dockTarget}
            targetAccount={dockTarget ? accountName(dockTarget) : null}
            language={language}
            dropping={drop === "dock"}
          />
        </main>
      </div>
      <StatusBar
        usage={harness.usage}
        accounts={harness.accounts}
        active={dockTarget}
        connection={harness.connection}
        onOpenAccounts={() => {
          setSection("contas");
          setView("settings");
        }}
      />
      {palette && <Palette items={paletteItems} onClose={() => setPalette(null)} placeholder={palette === "files" ? "Abrir arquivo…" : undefined} />}
      {pendingDelete && (
        <Confirm
          title={`Apagar a worktree ${worktreeLabel(pendingDelete.worktree)}?`}
          confirmLabel={pendingDelete.busyTerminals.length ? "Fechar terminais e apagar" : pendingDelete.force ? "Apagar mesmo assim" : "Apagar"}
          danger
          busy={deleting}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void confirmDelete(pendingDelete.busyTerminals.length > 0)}
        >
          <p className="mono small">{shortPath(pendingDelete.worktree.path)}</p>
          <p>
            A pasta sai do disco. O branch <b>{pendingDelete.worktree.branch ?? "—"}</b> sai junto se já foi juntado; se tiver commits só
            dele, fica guardado.
          </p>
          {pendingDelete.reason && <div className="error-box">{pendingDelete.reason}</div>}
        </Confirm>
      )}
      {toast && (
        <div className="toast" role="status" onClick={() => setToast(null)}>
          {toast}
        </div>
      )}
    </div>
  );
}
