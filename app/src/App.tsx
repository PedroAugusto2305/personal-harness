import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type PointerEvent as ReactPointerEvent } from "react";
import { Agents } from "./components/Agents";
import { ICON, Icon } from "./icons";
import { AgentSprite, spriteState } from "./components/AgentSprite";
import { AutomationsView } from "./components/AutomationsView";
import { BoardsView } from "./components/BoardsView";
import { BrainView, type BrainRequest } from "./components/BrainView";
import { BrowserView, type WebInfo } from "./components/BrowserView";
import { CoreVersionBanner, Ribbon, THEME_LABEL, TitleBar } from "./components/Chrome";
import { Confirm } from "./components/Confirm";
import { ApprovalCard, ConnectorsView } from "./components/ConnectorsView";
import { StudyView } from "./components/StudyView";
import { TodayView } from "./components/TodayView";
import { usePomodoro } from "./lib/pomodoro";
import { DocView, docTitle, type DocTab } from "./components/DocView";
import { Dock, type DockHandle } from "./components/Dock";
import { HistoryPanel } from "./components/HistoryPanel";
import { Inspector, type InspectorTab } from "./components/Inspector";
import { KanbanView, type KanbanRequest } from "./components/KanbanView";
import { Palette, type PaletteItem } from "./components/Palette";
import { Settings, THEMES, type SettingsSection } from "./components/Settings";
import { Sidebar, type Selected } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { Tabs, type TabItem } from "./components/Tabs";
import { TerminalView, type Slot } from "./components/TerminalView";
import { MiniMap } from "./components/MiniMap";
import { browser, describePick, onBrowserEvent, openExternal, type BrowserState, type DesignPick, type ForwardedKey } from "./lib/browser";
import { CoreError, inTauri, type NewSessionOptions } from "./lib/core";
import { KIND_COLOR, KIND_GLYPH, KIND_LABEL, STATUS_COLOR, fold, shortPath } from "./lib/format";
import type { Notice } from "./lib/inbox";
import { quotePaths, submit, terminals } from "./lib/terminals";
import { bindings, comboOf, hintFor, recorder } from "./lib/keymap";
import { dirtyDocs } from "./lib/editors";

/** Ações da janela que cedem a vez ao editor em foco (os atalhos de edição são dele). */
const EDITOR_KEYS = new Set(["dividir.direita", "dividir.baixo", "buscar", "barra", "foco.esquerda", "foco.direita", "foco.cima", "foco.baixo", "web.recarregar", "web.voltar", "web.avancar"]);
import {
  dropZone,
  findLeaf,
  leafWithTab,
  leaves,
  measure,
  neighbor,
  parseLayout,
  prune,
  removeLeaf,
  replaceTab,
  setRatio,
  setTab,
  single,
  splitLeaf,
  visibleTabs,
  type Direction,
  type Layout,
  type Rect,
  type Side,
} from "./lib/layout";
import type {
  Agent,
  BoardProject,
  DiffMode,
  GithubIssue,
  HistoryItem,
  KanbanTask,
  Project,
  ReviewNote,
  SavedCommand,
  Session,
  SessionKind,
  TerminalTheme,
  ThemeName,
  View,
  Worktree,
} from "./types";
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

type PaletteMode = "all" | "files" | "jump" | "commands" | null;

/** Layouts salvos, um por worktree ("" = fora dos projetos); o que não confere é descartado. */
function storedLayouts(): Record<string, Layout> {
  const raw = stored<Record<string, unknown>>("harness.layouts", {});
  const out: Record<string, Layout> = {};
  for (const [place, value] of Object.entries(raw && typeof raw === "object" ? raw : {})) {
    const layout = parseLayout(value);
    if (layout) out[place] = layout;
  }
  return out;
}

/** Posição de um painel em porcentagem, com 1px de folga nas bordas de dentro (vira a divisória). */
function boxStyle(r: Rect): CSSProperties {
  const pct = (n: number) => `${(n * 100).toFixed(4)}%`;
  const inner = (edge: number) => (edge < 0.9999 ? " - 1px" : "");
  return {
    left: pct(r.x),
    top: pct(r.y),
    width: `calc(${pct(r.w)}${inner(r.x + r.w)})`,
    height: `calc(${pct(r.h)}${inner(r.y + r.h)})`,
  };
}

/** Arrasto de uma aba para um painel: onde está o ponteiro e o que soltar ali faria. */
interface TabDrag {
  key: string;
  x: number;
  y: number;
  target: { leaf: string; zone: Side | "center" } | null;
}

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
  const [pomodoroToast, setPomodoroToast] = useState<string | null>(null);
  const pomodoro = usePomodoro(harness.client, setPomodoroToast);
  const wt = useWorktrees(harness.client, harness.projects, harness.worktreesTick);
  const [view, setView] = useState<View>("term");
  const [section, setSection] = useState<SettingsSection>("contas");
  const [folder, setFolder] = useState<string>(() => stored("harness.folder", "~"));
  const [selected, setSelected] = useState<Selected | null>(() => stored<Selected | null>("harness.selected", null));
  const [theme, setTheme] = useState<ThemeName>(() => stored<ThemeName>("harness.theme", "dracula"));
  const [language, setLanguage] = useState<string>(() => stored("harness.voice.language", "pt"));
  /** v0.9.3: a divisão da tela de cada worktree ("" = fora dos projetos), salva entre aberturas. */
  const [layouts, setLayouts] = useState<Record<string, Layout>>(storedLayouts);
  /** O terminal flutuante tem o foco (por cima da divisão). */
  const [floatFocused, setFloatFocused] = useState(false);
  /** Abas na ordem em que tiveram o foco, mais recente primeiro (⌘J). */
  const [recents, setRecents] = useState<string[]>(() => stored<string[]>("harness.recents", []));
  const [tabDrag, setTabDrag] = useState<TabDrag | null>(null);
  const [resizing, setResizing] = useState(false);
  /** ⌘F: qual terminal abre a busca, e um contador para abrir de novo. */
  const [searchSignal, setSearchSignal] = useState<{ id: string; n: number } | null>(null);
  /** Tema do terminal (v0.9.3, importado do Ghostty); null = as cores do tema da MÊTIS. */
  const [termTheme, setTermTheme] = useState<TerminalTheme | null>(() => stored<TerminalTheme | null>("harness.termTheme", null));
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
  /** Pedidos para as telas do Brain e do kanban (abrir nota, buscar, abrir tarefas de um projeto). */
  const [brainRequest, setBrainRequest] = useState<BrainRequest | null>(null);
  const [kanbanRequest, setKanbanRequest] = useState<KanbanRequest | null>(null);
  const [boardNames, setBoardNames] = useState<string[]>([]);
  const [urlFocusTick, setUrlFocusTick] = useState(0);
  /** v0.9.2: o menu do sino e o painel "Retomar uma conversa". */
  const [bellOpen, setBellOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
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
  useEffect(() => remember("harness.layouts", layouts), [layouts]);
  useEffect(() => remember("harness.recents", recents), [recents]);
  useEffect(() => {
    remember("harness.termTheme", termTheme);
    // O fundo em volta do terminal (a margem do term-host) acompanha o tema do terminal.
    const root = document.documentElement;
    if (termTheme?.cores.background) root.style.setProperty("--term", termTheme.cores.background);
    else root.style.removeProperty("--term");
  }, [termTheme]);
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

  // --- divisão da tela por worktree (v0.9.3) ------------------------------------------

  /** A worktree em que se está: a escolhida na barra lateral ("" = fora dos projetos). */
  const placeKey = selected?.path ?? "";
  const placeKeyOf = (cwd: string) => placeFor(cwd)?.worktree.path ?? "";
  /** A worktree de uma aba (é na tela dela que a aba aparece); null = aba desconhecida. */
  const tabPlace = (key: string): string | null => {
    const session = harness.sessions.find((s) => s.id === key);
    if (session) return placeKeyOf(session.cwd);
    const doc = docs.find((d) => d.key === key);
    if (doc) return doc.root ? placeKeyOf(doc.root) : "";
    return null;
  };
  /** A aba mais nova de uma worktree que não esteja na lista. */
  const newestIn = (place: string, except?: Set<string>) =>
    [...tabKeys].reverse().find((k) => !except?.has(k) && tabPlace(k) === place) ?? null;
  /**
   * A divisão de uma worktree; a que nunca foi mexida mostra a aba mais nova dela num
   * painel só (id fixo, para o foco e o React não se perderem a cada desenho).
   */
  const layoutOf = (place: string, all: Record<string, Layout> = layouts): Layout => {
    const saved = all[place];
    if (saved) return saved;
    const id = `base:${place}`;
    return { root: { t: "leaf", id, tab: newestIn(place) }, focus: id };
  };
  const updateLayout = (place: string, change: (layout: Layout) => Layout) =>
    setLayouts((all) => {
      const before = layoutOf(place, all);
      const after = change(before);
      return after === before && all[place] ? all : { ...all, [place]: after };
    });

  const current = layoutOf(placeKey);
  const { rects, dividers } = useMemo(() => measure(current.root), [current.root]);
  const tiled = rects.size > 1;
  const focusLeaf = findLeaf(current.root, current.focus) ?? leaves(current.root)[0];

  /** Abas que não somem da divisão enquanto trocam (agente reiniciando: a antiga fecha antes da nova chegar). */
  const keepTabs = useRef(new Set<string>());

  // Aba fechada sai da divisão de todas as worktrees: o painel dela some (a vizinha cresce);
  // o último painel fica, com a aba mais nova da worktree ou vazio. Só depois de o núcleo
  // mandar a lista: antes disso, aba que falta não é aba fechada.
  useEffect(() => {
    if (!harness.hydrated) return;
    const keys = new Set(tabKeys);
    const exists = (k: string) => keys.has(k) || keepTabs.current.has(k);
    setLayouts((all) => {
      let changed = false;
      const next: Record<string, Layout> = {};
      for (const [place, layout] of Object.entries(all)) {
        const after = prune(layout, exists, () => newestIn(place, new Set(visibleTabs(layout.root))));
        next[place] = after;
        if (after !== layout) changed = true;
      }
      return changed ? next : all;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabKeyList, harness.hydrated]);

  useEffect(() => {
    if (!floatSession && floatOpen) setFloatOpen(false);
  }, [floatSession, floatOpen]);

  useEffect(() => {
    if (floatFocused && !floatOpen) setFloatFocused(false);
  }, [floatFocused, floatOpen]);

  // A worktree escolhida pode sumir (apagada por fora); volta para a pasta principal do projeto.
  useEffect(() => {
    if (!selected) return;
    const list = wt.byProject[selected.project];
    if (harness.projects.length && !harness.projects.some((p) => p.id === selected.project)) setSelected(null);
    else if (list && list.length && !list.some((w) => w.path === selected.path)) setSelected({ project: selected.project, path: list[0].path });
  }, [selected, wt.byProject, harness.projects]);

  const focusedKey = floatFocused && floatOpen && floatSession ? floatSession.id : focusLeaf.tab;
  const focusedSession = harness.sessions.find((s) => s.id === focusedKey) ?? null;
  useEffect(() => {
    if (focusedKey) setRecents((list) => (list[0] === focusedKey ? list : [focusedKey, ...list.filter((k) => k !== focusedKey)].slice(0, 40)));
  }, [focusedKey]);
  const focusedDoc = docs.find((d) => d.key === focusedKey) ?? null;
  if (focusedSession) lastTerm.current = focusedSession.id;
  // O último terminal usado só vale se for desta worktree: a barra nunca escreve num terminal fora da tela.
  const dockTarget =
    focusedSession ??
    harness.sessions.find((s) => s.id === dockOverride) ??
    harness.sessions.find((s) => s.id === lastTerm.current && placeKeyOf(s.cwd) === placeKey) ??
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
      <AgentSprite agent={agent} client={harness.client} size={size} state={spriteState(session)} />
    ) : (
      <span style={{ color: KIND_COLOR[session.kind] }}>{KIND_GLYPH[session.kind]}</span>
    );
  };

  // --- ações -------------------------------------------------------------

  /** Vai para a tela de outra worktree ("" = fora dos projetos). */
  const goToPlace = (path: string) => {
    if (!path) return setSelected(null);
    const place = placeFor(path);
    if (place) setSelected({ project: place.project.id, path: place.worktree.path });
  };

  /**
   * Mostra a aba: na tela da worktree dela (troca de worktree se precisar); se ela já está
   * num painel, foca o painel; senão, ocupa o painel em foco. `place` vale quando a aba
   * acabou de nascer e ainda não está na lista.
   */
  const select = (key: string, place?: string) => {
    setView("term");
    if (floatSession?.id === key) {
      setFloatOpen(true);
      setFloatFocused(true);
      return;
    }
    setFloatFocused(false);
    const where = place ?? tabPlace(key) ?? placeKey;
    if (where !== placeKey) goToPlace(where);
    updateLayout(where, (layout) => {
      const there = leafWithTab(layout.root, key);
      if (there) return there.id === layout.focus ? layout : { ...layout, focus: there.id };
      return { ...layout, root: setTab(layout.root, layout.focus, key) };
    });
  };

  const focusLeafId = (leafId: string) => {
    setFloatFocused(false);
    updateLayout(placeKey, (layout) => (layout.focus === leafId ? layout : { ...layout, focus: leafId }));
  };

  /** Parte o painel em foco; o novo lado ganha a aba mais nova desta worktree que não está na tela (ou fica vazio). */
  const splitFocused = (side: Side) => {
    setView("term");
    setFloatFocused(false);
    updateLayout(placeKey, (layout) => {
      const next = newestIn(placeKey, new Set(visibleTabs(layout.root)));
      const { root, created } = splitLeaf(layout.root, layout.focus, side, next);
      return { root, focus: created };
    });
  };

  /** Tira o painel da divisão (a aba continua aberta); o foco vai para o vizinho. */
  const closePane = (leafId = current.focus) =>
    updateLayout(placeKey, (layout) => {
      const root = removeLeaf(layout.root, leafId);
      if (!root) return layout;
      const near = (["left", "right", "top", "bottom"] as Direction[]).map((d) => neighbor(layout.root, leafId, d)).find((id) => id && findLeaf(root, id));
      const focus = layout.focus !== leafId && findLeaf(root, layout.focus) ? layout.focus : (near ?? leaves(root)[0].id);
      return { root, focus };
    });

  /** Um painel só, com a aba em foco. */
  const joinAll = () => updateLayout(placeKey, (layout) => (layout.root.t === "leaf" ? layout : single(focusLeaf.tab)));

  const focusNeighbor = (dir: Direction) => {
    const id = neighbor(current.root, current.focus, dir);
    if (id) focusLeafId(id);
    return !!id;
  };

  /** Aba arrastada e solta num painel: no meio, ocupa o painel; numa borda, divide ali. */
  const dropTab = (key: string, leafId: string, zone: Side | "center") => {
    const place = tabPlace(key);
    if (place !== null && place !== placeKey) {
      setToast("Essa aba é de outra worktree: ela aparece na divisão de lá.");
      return;
    }
    setFloatFocused(false);
    updateLayout(placeKey, (layout) => {
      const own = leafWithTab(layout.root, key);
      if (own?.id === leafId) return { ...layout, focus: leafId };
      if (zone === "center") return { root: setTab(layout.root, leafId, key), focus: leafId };
      // Saindo de outro painel, aquele painel sai junto (em vez de ficar vazio).
      const base = own ? (removeLeaf(layout.root, own.id) ?? layout.root) : layout.root;
      if (!findLeaf(base, leafId)) return layout;
      const { root, created } = splitLeaf(base, leafId, zone, key);
      return { root, focus: created };
    });
  };

  const cwdNow = () => selectedPlace?.worktree.path ?? (folder.trim() || "~");

  const create = async (kind: SessionKind, options: NewSessionOptions & { cwd?: string | null } = {}) => {
    const { cwd, ...rest } = options;
    const session = await harness.create(kind, cwd === null ? "" : (cwd ?? cwdNow()), rest);
    if (session) select(session.id, placeKeyOf(session.cwd));
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
    // O agente do git dos Ajustes (v0.9.6) abre quando não há nenhum na worktree.
    const kind = harness.prefs?.agente_git ?? "claude";
    setToast(`Abrindo o ${KIND_LABEL[kind]} nesta worktree…`);
    const session = await create(kind, { cwd: place.worktree.path });
    if (!session) return null;
    await whenReady(session.id);
    return session;
  };

  const askCommit = async (staged: number) => {
    if (!contextPlace) return;
    // As receitas vêm de Ajustes → Git (v0.9.6); sem núcleo novo, os textos de antes.
    const prompt = staged
      ? (harness.prefs?.receita_commit_marcado ??
        "Escreva a mensagem e faça o commit só das mudanças já marcadas nesta worktree (git diff --cached), no padrão das mensagens recentes (git log -5 --oneline). Não marque nem desmarque outros arquivos.")
      : (harness.prefs?.receita_commit ??
        "Veja as mudanças desta worktree (git status e git diff), marque o que faz parte do mesmo trabalho e faça o commit com uma mensagem no padrão das mensagens recentes (git log -5 --oneline). Se houver mais de um assunto, me pergunte antes.");
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
    // Comparar com uma ref é outra aba (dá para ter o diff normal e o contra o main lado a lado).
    const key = `doc:${doc.type}:${doc.root}:${doc.path}${doc.mode === "ref" && doc.ref ? `@${doc.ref}` : ""}`;
    setDocs((all) =>
      all.some((d) => d.key === key)
        ? // Pedida de novo com outro modo: a aba segue o pedido.
          doc.mode
          ? all.map((d) => (d.key === key ? { ...d, mode: doc.mode, ref: doc.ref, seq: (d.seq ?? 0) + 1 } : d))
          : all
        : [...all, { ...doc, key }],
    );
    select(key, doc.root ? placeKeyOf(doc.root) : "");
  };
  const openDiff = (file: { path: string; untracked?: boolean }, options: { mode?: DiffMode; ref?: string } = {}) => {
    if (contextPlace) openDoc({ type: "diff", root: contextPlace.worktree.path, path: file.path, untracked: file.untracked, ...options });
  };
  /** Nota do Brain para editar numa aba ao lado dos terminais (na tela da worktree em uso). */
  const openNoteTab = (path: string) => openDoc({ type: "note", root: contextPlace?.worktree.path ?? "", path });
  const openConflict = (path: string) => {
    if (contextPlace) openDoc({ type: "conflict", root: contextPlace.worktree.path, path });
  };
  /** Pedido ao agente da worktree em foco (abre um, se não houver), mandado na hora. */
  const askAgent = async (prompt: string, root = contextPlace?.worktree.path) => {
    const place = root ? placeFor(root) : null;
    if (!place) return setToast("Escolha uma worktree para pedir ao agente.");
    const session = await agentSessionIn(place);
    if (!session) return;
    select(session.id);
    submit(session.id, prompt);
  };
  const openFile = (path: string, root = contextPlace?.worktree.path) => {
    if (root) openDoc({ type: "file", root, path });
  };

  const webCount = useRef(0);
  /** Aba de navegador nova, ligada à worktree em foco (é para o agente dela que o modo de design manda). */
  const openWeb = (url?: string, options: { root?: string; incognito?: boolean; design?: boolean } = {}) => {
    const root = options.root ?? contextPlace?.worktree.path ?? "";
    const port = contextPlace ? harness.sessions.find((s) => placeFor(s.cwd)?.worktree.path === root && s.ports.length)?.ports[0] : undefined;
    const start = url ?? (port ? `http://localhost:${port}` : "about:blank");
    webCount.current += 1;
    const label = `browser-${Date.now().toString(36)}${webCount.current}`;
    const key = `doc:web:${label}`;
    setDocs((all) => [...all, { key, type: "web", root, path: start, label, incognito: options.incognito }]);
    // design: true pede o modo de design assim que a página nativa nascer (ver BrowserView).
    setWebInfo((all) => ({ ...all, [label]: { url: start, title: null, loading: start !== "about:blank", design: !!options.design } }));
    select(key, root ? placeKeyOf(root) : "");
    if (start === "about:blank") window.setTimeout(() => setUrlFocusTick((n) => n + 1), 50);
  };

  /** Fechar aba com edição não salva (v0.9.7): o primeiro clique avisa, o segundo (em 5 s) descarta. */
  const closeArmed = useRef<{ key: string; at: number } | null>(null);
  const closeTab = (key: string) => {
    if (key.startsWith("doc:")) {
      if (dirtyDocs.has(key) && !(closeArmed.current?.key === key && Date.now() - closeArmed.current.at < 5000)) {
        closeArmed.current = { key, at: Date.now() };
        setToast("Há mudança não salva nessa aba: ⌘S salva. Feche de novo para descartar.");
        return;
      }
      closeArmed.current = null;
      setDocs((all) => all.filter((d) => d.key !== key));
    } else void harness.close(key);
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
    setFloatFocused(true);
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
    const setup = created.setup
      ? "; o script de setup roda num terminal à vista"
      : created.setup_erro
        ? `; o script de setup não abriu (${created.setup_erro})`
        : "";
    setToast(`Worktree ${created.branch} criada${created.copied.length ? `, com ${created.copied.join(", ")}` : ""}${setup}.`);
    // O terminal do setup entra na lista na hora (o evento do núcleo pode chegar depois da resposta);
    // ganha o foco só se o Claude não for abrir.
    if (created.setup) {
      const id = created.setup;
      if (!sessionsRef.current.some((s) => s.id === id)) {
        const found = (await harness.client?.listSessions().catch(() => []))?.find((s) => s.id === id);
        if (found) harness.adopt(found);
      }
      if (!openClaude) select(id, created.path);
    }
    if (openClaude) void create("claude", { cwd: created.path });
    return true;
  };

  // --- sessões: retomar, reiniciar e passar o trabalho (v0.9.2) ------------------------

  /** A conta da conversa: o id que o núcleo manda; núcleo antigo manda só o nome. */
  const accountFor = (item: HistoryItem): string | undefined => {
    const list = harness.accounts[item.cli].accounts;
    if (item.conta_id && list.some((a) => a.id === item.conta_id)) return item.conta_id;
    const byName = list.find((a) => a.name === item.conta);
    if (byName) return byName.id;
    // "padrão" é a pasta de sempre (~/.claude, ~/.codex): a conta sem pasta própria.
    if (item.conta === "padrão") return list.find((a) => !a.dir)?.id;
    return undefined;
  };

  /** Retoma uma conversa do histórico na pasta e na conta dela; devolve o erro para o painel mostrar. */
  const resumeConversation = async (item: HistoryItem): Promise<string | null> => {
    const client = harness.client;
    if (!client) return "O núcleo está fora do ar.";
    const title = item.titulo.length > 32 ? `${item.titulo.slice(0, 31).trimEnd()}…` : item.titulo;
    try {
      const session = await client.createSession(item.cli, item.cwd, { resume: item.id, account: accountFor(item), title: title || undefined });
      harness.adopt(session);
      select(session.id, placeKeyOf(session.cwd));
      return null;
    } catch (cause) {
      return errorText(cause);
    }
  };

  /**
   * O agente saiu: sessão nova na mesma pasta e conta, no mesmo lugar da tela. O núcleo tira a
   * antiga da lista (fecha, se ainda estiver viva) e a nova nasce com o mesmo nome.
   * O painel é guardado: o aviso de "fechou" da antiga chega antes da resposta e tiraria o
   * painel dela da divisão; enquanto reinicia, a aba antiga conta como aberta.
   * O erro (409: conversa não achada) sobe para a faixa do terminal mostrar.
   */
  const restartAgent = async (old: Session, continuar: boolean) => {
    const client = harness.client;
    if (!client) throw new Error("O núcleo está fora do ar.");
    const wasLast = lastTerm.current === old.id;
    keepTabs.current.add(old.id);
    try {
      const session = await client.restartSession(old.id, continuar);
      harness.adopt(session);
      setLayouts((all) => {
        let changed = false;
        const next: Record<string, Layout> = {};
        for (const [place, layout] of Object.entries(all)) {
          const root = replaceTab(layout.root, old.id, session.id);
          next[place] = root === layout.root ? layout : { ...layout, root };
          if (root !== layout.root) changed = true;
        }
        return changed ? next : all;
      });
      select(session.id, placeKeyOf(session.cwd));
      if (wasLast) lastTerm.current = session.id;
      setDockOverride((current) => (current === old.id ? session.id : current));
      void harness.close(old.id);
    } finally {
      keepTabs.current.delete(old.id);
    }
  };

  /**
   * Passa o trabalho para a outra CLI; a sessão de origem fica aberta. Com a tela dividida,
   * a nova vai para um painel vizinho ao da origem (as duas ficam à vista).
   */
  const handOffAgent = async (old: Session, nota: string) => {
    const client = harness.client;
    if (!client) throw new Error("O núcleo está fora do ar.");
    const para = old.kind === "claude" ? "codex" : "claude";
    const session = await client.handOff(old.id, para, nota);
    harness.adopt(session);
    const place = placeKeyOf(session.cwd);
    const layout = layoutOf(place);
    const from = leafWithTab(layout.root, old.id);
    const other = from
      ? ((["right", "left", "bottom", "top"] as Direction[]).map((d) => neighbor(layout.root, from.id, d)).find(Boolean) ?? null)
      : null;
    if (other) {
      setView("term");
      setFloatFocused(false);
      if (place !== placeKey) goToPlace(place);
      updateLayout(place, (l) => ({ root: setTab(l.root, other, session.id), focus: other }));
    } else {
      select(session.id, place);
    }
    setToast(`O trabalho passou para o ${KIND_LABEL[para]}. ${old.title} continua aberto.`);
  };

  /** Clique num aviso do sino: vai para a sessão, a aprovação ou a automação, quando dá. */
  const openNotice = (notice: Notice) => {
    harness.inbox.markRead(notice.id);
    setBellOpen(false);
    if (notice.kind === "versao") {
      setSection("sobre");
      setView("settings");
      return;
    }
    const sessionOpen = !!notice.sessao && harness.sessions.some((s) => s.id === notice.sessao);
    if (notice.aprovacao) {
      // O cartão da aprovação aparece em toda tela menos Conectores: basta ir ao agente que pediu.
      if (sessionOpen && harness.approvals.some((a) => a.id === notice.aprovacao)) select(notice.sessao!);
      else setView("connectors");
      return;
    }
    if (sessionOpen) return select(notice.sessao!);
    if (notice.automacao) return setView("automations");
    if (notice.sessao) setToast("Essa sessão já foi fechada.");
  };
  const closeBell = useCallback(() => setBellOpen(false), []);

  // --- Brain e kanban -------------------------------------------------------

  const openNote = (target: { title?: string; path?: string; query?: string }) => {
    setView("brain");
    setBrainRequest((last) => ({ id: (last?.id ?? 0) + 1, ...target }));
  };

  const openTasks = (project?: string) => {
    setView("kanban");
    setKanbanRequest((last) => ({ id: (last?.id ?? 0) + 1, project }));
  };

  /** Cartão do kanban → o repositório do projeto na barra lateral (ou um terminal na pasta, se não for git). */
  const openBoardProject = async (project: BoardProject) => {
    if (!harness.client || !project.directory) return;
    setView("term");
    try {
      const repo = await harness.client.addProject(project.directory);
      setSelected({ project: repo.id, path: repo.path });
      harness.bumpWorktrees();
    } catch {
      setSelected(null);
      setFolder(project.directory);
      setToast(`${project.name} não é um repositório git; os terminais novos abrem em ${project.directory}.`);
    }
  };

  /**
   * "Executar com agente": worktree nova com o nome da tarefa, Claude nela, a tarefa em
   * "Em andamento" e o pedido na barra de entrada para você revisar antes de mandar.
   */
  const runTask = async (project: BoardProject, task: KanbanTask) => {
    const client = harness.client;
    if (!client || !project.directory) return;
    setView("term");
    let cwd = project.directory;
    let where = project.directory;
    try {
      const repo = await client.addProject(project.directory);
      const name = `tarefa-${fold(task.text).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 36)}`.replace(/-+$/, "");
      const created = await client.createWorktree(repo.id, name, true);
      await wt.refresh();
      harness.bumpWorktrees();
      setSelected({ project: repo.id, path: created.path });
      cwd = created.path;
      where = `a worktree ${created.branch}`;
    } catch (cause) {
      setToast(`Sem worktree (${cause instanceof Error ? cause.message : String(cause)}); o agente abre na pasta do projeto.`);
    }
    await client.moveTask(project.name, task.id, "em-andamento").catch(() => undefined);
    const session = await create("claude", { cwd });
    if (!session) return;
    await whenReady(session.id);
    const prompt = [
      `Tarefa do kanban da MÊTIS · projeto ${project.name} · id ${task.id}`,
      task.text,
      "",
      `Ela já está em "Em andamento". Quando estiver pronta para eu testar, rode \`metis tarefa mover ${task.id} em-teste\`. Se precisar de uma decisão minha, pergunte antes de seguir.`,
    ].join("\n");
    setDockOverride(session.id);
    window.setTimeout(() => dock.current?.insert(prompt), 50);
    setToast(`Claude aberto em ${where}. O pedido está na barra de entrada: revise e mande.`);
  };

  /**
   * Issue do GitHub no kanban (v0.9.6): como "Executar com agente" de uma tarefa, com a
   * worktree issue-<n>-<título> e o pedido de resolver e abrir o PR que fecha a issue.
   */
  const runIssue = async (project: BoardProject, issue: GithubIssue) => {
    const client = harness.client;
    if (!client || !project.directory) return;
    setView("term");
    let cwd = project.directory;
    let where = project.directory;
    try {
      const repo = await client.addProject(project.directory);
      const slug = fold(issue.titulo).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30).replace(/-+$/, "");
      const created = await client.createWorktree(repo.id, `issue-${issue.numero}-${slug}`, true);
      await wt.refresh();
      harness.bumpWorktrees();
      setSelected({ project: repo.id, path: created.path });
      cwd = created.path;
      where = `a worktree ${created.branch}`;
    } catch (cause) {
      setToast(`Sem worktree (${cause instanceof Error ? cause.message : String(cause)}); o agente abre na pasta do projeto.`);
    }
    const kind = harness.prefs?.agente_git ?? "claude";
    const session = await create(kind, { cwd });
    if (!session) return;
    await whenReady(session.id);
    const prompt = [
      `Issue #${issue.numero} do GitHub · ${issue.titulo}`,
      issue.url,
      "",
      `Leia a issue com \`gh issue view ${issue.numero}\` (e os comentários) e resolva nesta worktree. Quando estiver pronto, abra um PR com "Closes #${issue.numero}" no texto. Se precisar de uma decisão minha, pergunte antes de seguir.`,
    ].join("\n");
    setDockOverride(session.id);
    window.setTimeout(() => dock.current?.insert(prompt), 50);
    setToast(`${KIND_LABEL[kind]} aberto em ${where}. O pedido está na barra de entrada: revise e mande.`);
  };

  // Nomes dos projetos do Brain, para o filtro da busca.
  useEffect(() => {
    if (!harness.client || (view !== "brain" && !boardNames.length)) return;
    void harness.client
      .boardProjects()
      .then((list) => setBoardNames(list.map((p) => p.name)))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [harness.client, view, harness.brainTick]);

  // O Pomodoro nasce antes do aviso da tela; o que ele tem a dizer passa por aqui.
  useEffect(() => {
    if (!pomodoroToast) return;
    setToast(pomodoroToast);
    setPomodoroToast(null);
  }, [pomodoroToast]);

  // Rotina que rodou (ou pulou) vira aviso; o terminal dela aparece nas abas.
  useEffect(() => {
    const run = harness.routineRun;
    if (!run) return;
    if (run.status === "pulou") setToast(`Rotina "${run.name}" pulou: ${run.detail}.`);
    else if (run.status === "erro") setToast(`Rotina "${run.name}" deu erro: ${run.detail}`);
    else setToast(`Rotina "${run.name}" abriu num terminal${run.detail ? ` (${run.detail})` : ""}.`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [harness.routineRun?.id]);

  /** Captura rápida: a mesma caixinha do ⌥Espaço, aberta pelo ⌘K. */
  const openCapture = () => {
    if (!inTauri()) return setToast("A captura rápida abre no app (⌥Espaço).");
    void import("@tauri-apps/api/core").then(({ invoke }) => invoke("capture_open")).catch((cause) => setToast(String(cause)));
  };

  /** Resposta do Pedro a um pedido de aprovação da central de MCP. */
  const decide = (id: string, approve: boolean) => {
    void harness.client?.decide(id, approve).catch((cause) => setToast(cause instanceof Error ? cause.message : String(cause)));
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
          reason: busy
            ? detail
            : /arquivamento/.test(detail)
              ? `${detail}. Apagando mesmo assim, a worktree sai mesmo com o script falhando.`
              : `${detail}. Apagando mesmo assim, essas mudanças se perdem.`,
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

  /** Roda a ação de um atalho; false quando ela não vale agora (a tecla segue o caminho normal). */
  const runAction = (id: string): boolean => {
    const paletteToggle = (mode: Exclude<PaletteMode, null>) => setPalette((open) => (open === mode ? null : mode));
    const web = focusedDoc?.type === "web" && view === "term" ? focusedDoc : null;
    switch (id) {
      case "paleta":
        paletteToggle("all");
        return true;
      case "pular":
        paletteToggle("jump");
        return true;
      case "comandos":
        paletteToggle("commands");
        return true;
      case "arquivo":
        void openFilePalette();
        return true;
      case "ajustes":
        setView((v) => (v === "settings" ? "term" : "settings"));
        return true;
      case "painel":
        setInspectorOpen((v) => !v);
        return true;
      case "flutuante":
        void toggleFloat();
        return true;
      case "barra":
        setView("term");
        if (focusedDoc?.type === "web") setUrlFocusTick((n) => n + 1);
        else dock.current?.focus();
        return true;
      case "ditar":
        setView("term");
        dock.current?.toggleVoice();
        return true;
      case "buscar":
        if (view !== "term" || !focusedSession) return false;
        setSearchSignal((last) => ({ id: focusedSession.id, n: (last?.n ?? 0) + 1 }));
        return true;
      case "dividir.direita":
        splitFocused("right");
        return true;
      case "dividir.baixo":
        splitFocused("bottom");
        return true;
      case "dividir.fechar":
        if (view !== "term" || !tiled) return false;
        closePane();
        return true;
      case "dividir.juntar":
        joinAll();
        return true;
      case "foco.esquerda":
        return view === "term" && focusNeighbor("left");
      case "foco.direita":
        return view === "term" && focusNeighbor("right");
      case "foco.cima":
        return view === "term" && focusNeighbor("top");
      case "foco.baixo":
        return view === "term" && focusNeighbor("bottom");
      case "web.recarregar":
      case "web.voltar":
      case "web.avancar":
        if (!web?.label) return false;
        void browser.go(web.label, id === "web.recarregar" ? "reload" : id === "web.voltar" ? "back" : "forward").catch(() => undefined);
        return true;
    }
    return false;
  };

  const keyBindings = useMemo(() => bindings(harness.keymap), [harness.keymap]);
  /** Rótulo do atalho de uma ação, para as dicas da tela (segue o que o Pedro remapeou). */
  const hint = (id: string) => hintFor(harness.keymap, id);

  const keys = useRef<(event: KeyboardEvent) => void>(() => undefined);
  keys.current = (event: KeyboardEvent) => {
    if (recorder.active) return; // Ajustes → Atalhos está gravando uma tecla
    let handled = false;
    const onlyCmd = event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey;
    if (onlyCmd && /^Digit[1-9]$/.test(event.code)) {
      const key = tabKeys[Number(event.code.slice(5)) - 1];
      if (key) {
        select(key);
        handled = true;
      }
    } else {
      const combo = comboOf(event);
      const action = combo ? keyBindings.get(combo) : undefined;
      // Com o foco num editor (Monaco, CodeMirror), os atalhos de edição são dele:
      // ⌘D próxima ocorrência, ⌘F buscar, ⌘L linha, ⌘⌥ e as setas, cursores.
      const inEditor = !!(event.target as Element | null)?.closest?.(".monaco-editor, .cm-editor");
      if (action && !(inEditor && EDITOR_KEYS.has(action))) handled = runAction(action);
    }
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

  // `metis web <endereço>` num terminal (de você ou de um agente) abre a aba aqui.
  useEffect(() => {
    const request = harness.webRequest;
    if (!request) return;
    const { openWeb: open, placeFor: place } = browserLive.current;
    open(request.url || undefined, { root: request.cwd ? place(request.cwd)?.worktree.path : undefined });
  }, [harness.webRequest]);

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
  // Ao arrastar uma aba ou uma divisória também: a página nativa engoliria o ponteiro.
  const overlayOpen = !!palette || !!pendingDelete || floatOpen || bellOpen || historyOpen || !!tabDrag || resizing;

  // Ver a sessão é ler o que ela avisou: com a janela em foco, os avisos do terminal em foco saem do número.
  const markSession = harness.inbox.markSession;
  const focusedId = view === "term" ? (focusedSession?.id ?? null) : null;
  useEffect(() => {
    if (!focusedId) return;
    const mark = () => document.hasFocus() && markSession(focusedId);
    mark();
    window.addEventListener("focus", mark);
    return () => window.removeEventListener("focus", mark);
  }, [focusedId, markSession, harness.inbox.unread]);

  const openSessions = harness.sessions.filter((s) => s.status !== "exited").length;

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
        away: (place?.worktree.path ?? "") !== placeKey,
      };
    }),
    ...docs.map((doc) => ({
      key: doc.key,
      title: docTitle(doc, doc.label ? webInfo[doc.label]?.title : null),
      glyph: <span className="mono doc-glyph">{doc.type === "diff" ? "±" : doc.type === "web" ? "◍" : doc.type === "conflict" ? "!" : doc.type === "note" ? "✎" : "▤"}</span>,
      hint: doc.path,
      away: (doc.root ? placeKeyOf(doc.root) : "") !== placeKey,
    })),
  ];
  const tabByKey = new Map(tabItems.map((item) => [item.key, item]));
  const placeLabel = selectedPlace ? `${selectedPlace.project.name} · ${worktreeLabel(selectedPlace.worktree)}` : "fora dos projetos";

  // --- comandos salvos (v0.9.3) -------------------------------------------------------

  /** Comandos que valem aqui: os globais e os do projeto da worktree em foco. */
  const projectPath = contextPlace?.project.path ?? null;
  const commandsHere = harness.commands.filter((c) => !c.projeto || c.projeto === projectPath);

  /** Espera o terminal montar e o shell nascer, e digita (shell recém-aberto mostra as marcas de colagem). */
  const typeWhenReady = (id: string, text: string) => {
    const started = Date.now();
    const timer = window.setInterval(() => {
      const handle = terminals.get(id);
      if (handle || Date.now() - started > 8000) {
        window.clearInterval(timer);
        if (handle) window.setTimeout(() => handle.send(`${text}\r`), 1300);
      }
    }, 100);
  };

  /**
   * Comando: roda no shell em foco, ou no shell mais recente desta worktree, ou num shell
   * novo nela. Prompt: vai para a barra de entrada do terminal em foco, para revisar e mandar.
   */
  const runCommand = (command: SavedCommand) => {
    setView("term");
    if (command.tipo === "prompt") {
      if (!dockTarget) setToast("Abra um terminal do Claude ou do Codex: o prompt fica na barra de entrada dele.");
      window.setTimeout(() => dock.current?.insert(command.texto), 30);
      return;
    }
    const alive = (s: Session) => s.kind === "shell" && s.status !== "exited" && s.tag !== "float";
    const shell =
      (focusedSession && alive(focusedSession) ? focusedSession : null) ??
      [...tabs].reverse().find((s) => alive(s) && placeKeyOf(s.cwd) === placeKey) ??
      null;
    if (shell) {
      select(shell.id);
      terminals.get(shell.id)?.send(`${command.texto}\r`);
      return;
    }
    void create("shell", { title: command.nome }).then((session) => session && typeWhenReady(session.id, command.texto));
  };

  const screens: { id: View; label: string; hint?: string }[] = [
    { id: "term", label: "Terminais" },
    { id: "today", label: "Hoje", hint: "rotinas, em andamento, aprovações" },
    { id: "brain", label: "Brain" },
    { id: "kanban", label: "Kanban de projetos" },
    { id: "boards", label: "Quadros" },
    { id: "automations", label: "Automações" },
    { id: "connectors", label: "Conectores" },
    { id: "study", label: "Estudo" },
    { id: "agents", label: "Agentes" },
    { id: "settings", label: "Ajustes", hint: hint("ajustes") },
  ];

  /** ⌘J: as abas pelas mais recentes, depois as worktrees e as telas. */
  const jumpItems = (): PaletteItem[] => {
    const recent = recents.filter((k) => k !== focusedKey && tabByKey.has(k)).slice(0, 9);
    const recentSet = new Set(recent);
    const tabItem = (item: TabItem, group: string): PaletteItem => ({
      id: `${group}-${item.key}`,
      group,
      label: item.title,
      hint: item.hint,
      glyph: item.glyph,
      run: () => select(item.key),
    });
    return [
      ...recent.map((k) => tabItem(tabByKey.get(k)!, "Recentes")),
      ...tabItems.filter((item) => !recentSet.has(item.key) && item.key !== focusedKey).map((item) => tabItem(item, "Abas")),
      ...harness.projects.flatMap((project) =>
        (wt.byProject[project.id] ?? []).map((worktree) => ({
          id: `jump-place-${worktree.path}`,
          group: "Worktrees",
          label: `${project.name} · ${worktreeLabel(worktree)}`,
          hint: worktree.path === placeKey ? "aqui" : worktree.changes ? `●${worktree.changes}` : undefined,
          glyph: <Icon d={worktree.main ? ICON.folder : ICON.branch} size={13} />,
          run: () => {
            setView("term");
            setFloatFocused(false);
            setSelected({ project: project.id, path: worktree.path });
          },
        })),
      ),
      {
        id: "jump-loose",
        group: "Worktrees",
        label: "Fora dos projetos",
        hint: placeKey === "" ? "aqui" : undefined,
        run: () => {
          setView("term");
          setFloatFocused(false);
          setSelected(null);
        },
      },
      ...screens.map((screen) => ({ id: `jump-view-${screen.id}`, group: "Telas", label: screen.label, hint: screen.hint, run: () => setView(screen.id) })),
    ];
  };

  /** ⌘⇧K: os comandos salvos daqui, e os atalhos para criar um. */
  const commandItems = (): PaletteItem[] => [
    ...commandsHere.map((command) => ({
      id: `cmd-${command.id}`,
      group: command.projeto ? `Comandos · ${contextPlace?.project.name ?? "projeto"}` : "Comandos · todos os projetos",
      label: command.nome,
      hint: `${command.tipo === "prompt" ? "prompt" : "$"} ${command.texto.split("\n")[0].slice(0, 60)}`,
      glyph: <span className="mono doc-glyph">{command.tipo === "prompt" ? "✎" : "$"}</span>,
      run: () => runCommand(command),
    })),
    {
      id: "cmd-new",
      group: "Comandos salvos",
      label: commandsHere.length ? "Editar os comandos salvos…" : "Nenhum comando salvo ainda: criar um…",
      hint: "Ajustes → Comandos salvos",
      glyph: <Icon d={ICON.plus} size={13} strokeWidth={2} />,
      run: () => (setSection("comandos"), setView("settings")),
    },
  ];

  const paletteItems: PaletteItem[] =
    palette === "jump"
      ? jumpItems()
      : palette === "commands"
        ? commandItems()
        : palette === "files"
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
          {
            id: "history",
            group: "Abrir",
            label: "Retomar uma conversa…",
            hint: "Claude e Codex, todas as contas",
            glyph: <Icon d={ICON.history} size={14} />,
            run: () => setHistoryOpen(true),
          },
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
              run: () => (setView("term"), setFloatFocused(false), setSelected({ project: project.id, path: worktree.path })),
            })),
          ),
          { id: "web", group: "Navegador", label: "Abrir navegador", hint: contextPlace ? worktreeLabel(contextPlace.worktree) : undefined, run: () => openWeb() },
          { id: "web-private", group: "Navegador", label: "Abrir aba anônima", run: () => openWeb(undefined, { incognito: true }) },
          focusedDoc?.type === "web" && focusedDoc.label
            ? {
                id: "design",
                group: "Navegador",
                label: webInfo[focusedDoc.label]?.design ? "Sair do modo de design" : "Modo de design",
                hint: "clique num elemento da página e ele vai para o agente",
                run: () => setDesign(focusedDoc, !webInfo[focusedDoc.label!]?.design),
              }
            : { id: "design", group: "Navegador", label: "Modo de design", hint: "abre uma aba do navegador já no modo", run: () => openWeb(undefined, { design: true }) },
          ...harness.sessions.flatMap((s) =>
            s.ports.map((port) => ({ id: `port-${s.id}-${port}`, group: "Navegador", label: `Abrir localhost:${port}`, hint: s.title, run: () => openWeb(`http://localhost:${port}`, { root: placeFor(s.cwd)?.worktree.path }) })),
          ),
          { id: "jump", group: "Tela", label: "Pular para…", hint: `${hint("pular")} recentes, worktrees e telas`, run: () => window.setTimeout(() => setPalette("jump"), 0) },
          { id: "commands", group: "Tela", label: "Comandos salvos…", hint: hint("comandos"), run: () => window.setTimeout(() => setPalette("commands"), 0) },
          { id: "files", group: "Tela", label: "Abrir arquivo da worktree", hint: hint("arquivo"), run: () => void openFilePalette() },
          { id: "split-right", group: "Divisão", label: "Dividir à direita", hint: hint("dividir.direita"), run: () => splitFocused("right") },
          { id: "split-down", group: "Divisão", label: "Dividir para baixo", hint: hint("dividir.baixo"), run: () => splitFocused("bottom") },
          ...(tiled
            ? [
                { id: "split-close", group: "Divisão", label: "Tirar o painel em foco da divisão", hint: hint("dividir.fechar"), run: () => closePane() },
                { id: "split-join", group: "Divisão", label: "Juntar tudo num painel", hint: hint("dividir.juntar") || placeLabel, run: joinAll },
              ]
            : []),
          ...(focusedSession
            ? [{ id: "search", group: "Tela", label: "Buscar no terminal", hint: hint("buscar"), run: () => setSearchSignal((last) => ({ id: focusedSession.id, n: (last?.n ?? 0) + 1 })) }]
            : []),
          { id: "float", group: "Tela", label: floatOpen ? "Esconder o terminal flutuante" : "Terminal flutuante", hint: hint("flutuante"), run: () => void toggleFloat() },
          { id: "inspector", group: "Tela", label: inspectorOpen ? "Fechar o painel da worktree" : "Painel da worktree", hint: hint("painel"), run: () => setInspectorOpen((v) => !v) },
          { id: "voice", group: "Tela", label: "Ditar para o terminal em foco", hint: hint("ditar"), run: () => dock.current?.toggleVoice() },
          ...commandsHere.map((command) => ({
            id: `cmd-${command.id}`,
            group: "Comandos salvos",
            label: command.nome,
            hint: `${command.tipo === "prompt" ? "prompt" : "$"} ${command.texto.split("\n")[0].slice(0, 60)}`,
            glyph: <span className="mono doc-glyph">{command.tipo === "prompt" ? "✎" : "$"}</span>,
            run: () => runCommand(command),
          })),
          {
            id: "inbox",
            group: "Tela",
            label: "Avisos",
            hint: harness.inbox.unread ? `${harness.inbox.unread} sem ler` : "o sino da barra de título",
            glyph: <Icon d={ICON.bell} size={14} />,
            run: () => setBellOpen(true),
          },
          ...harness.accounts.claude.accounts
            .filter((a) => !a.active)
            .map((a) => ({ id: `acc-claude-${a.id}`, group: "Contas", label: `Usar a conta ${a.name} no Claude Code`, run: () => void harness.run((c) => c.activateAccount("claude", a.id)) })),
          ...harness.accounts.codex.accounts
            .filter((a) => !a.active)
            .map((a) => ({ id: `acc-codex-${a.id}`, group: "Contas", label: `Usar a conta ${a.name} no Codex`, run: () => void harness.run((c) => c.activateAccount("codex", a.id)) })),
          ...THEMES.filter((t) => t !== theme).map((t) => ({ id: `theme-${t}`, group: "Aparência", label: `Tema ${THEME_LABEL[t]}`, run: () => setTheme(t) })),
          { id: "capture", group: "Hoje", label: "Captura rápida", hint: "⌥Espaço de qualquer app", run: openCapture },
          { id: "study", group: "Estudo", label: "Estudo", hint: "Pomodoro e placar", run: () => setView("study") },
          pomodoro.state.phase === "idle"
            ? { id: "pomodoro", group: "Estudo", label: `Começar Pomodoro de ${pomodoro.state.focusMin} min`, run: () => (pomodoro.start(pomodoro.state.subject), setView("study")) }
            : { id: "pomodoro", group: "Estudo", label: "Parar o Pomodoro", hint: pomodoro.label, run: pomodoro.stop },
          { id: "today", group: "Hoje", label: "Hoje", hint: "rotinas do dia, em andamento, aprovações", run: () => setView("today") },
          { id: "routine-new", group: "Hoje", label: "Rotinas", hint: "agendar um agente", run: () => setView("today") },
          { id: "connectors", group: "Conectores", label: "Conectores", hint: "Slack, ClickUp e lembretes", run: () => setView("connectors") },
          { id: "automations", group: "Automações", label: "Automações", hint: "passos ligados: ferramentas, agentes, condições e aprovações", run: () => setView("automations") },
          { id: "brain-search", group: "Brain", label: "Buscar no Brain", hint: "decisões, incidentes, aprendizados, notas", run: () => openNote({ query: "" }) },
          { id: "kanban", group: "Brain", label: "Kanban de projetos", run: () => openTasks() },
          { id: "boards", group: "Brain", label: "Quadros", hint: "quadro livre por projeto, o .canvas que abre no Obsidian", run: () => setView("boards") },
          ...(contextPlace ? [{ id: "brain-panel", group: "Brain", label: "Precedentes desta worktree", hint: "painel da worktree → Brain", run: () => (setInspectorOpen(true), setInspectorTab("brain")) }] : []),
          { id: "agents", group: "Ajustes", label: "Agentes", run: () => setView("agents") },
          { id: "settings-accounts", group: "Ajustes", label: "Contas e uso", hint: hint("ajustes"), run: () => (setSection("contas"), setView("settings")) },
          { id: "settings-agents", group: "Ajustes", label: "Agentes e avisos", hint: "permissões, Mac acordado, avisos, desligar", run: () => (setSection("agentes"), setView("settings")) },
          { id: "settings-skills", group: "Ajustes", label: "Skills", run: () => (setSection("skills"), setView("settings")) },
          { id: "settings-resources", group: "Ajustes", label: "Recursos", hint: "memória e CPU do núcleo e das sessões", run: () => (setSection("recursos"), setView("settings")) },
          { id: "settings-voice", group: "Ajustes", label: "Voz", run: () => (setSection("voz"), setView("settings")) },
          { id: "settings-keys", group: "Ajustes", label: "Atalhos", hint: "mudar qualquer atalho", run: () => (setSection("atalhos"), setView("settings")) },
          { id: "settings-commands", group: "Ajustes", label: "Comandos salvos", hint: "comandos e prompts, globais ou do projeto", run: () => (setSection("comandos"), setView("settings")) },
          { id: "settings-look", group: "Ajustes", label: "Aparência e tema do terminal", hint: "temas, importar do Ghostty", run: () => (setSection("aparencia"), setView("settings")) },
          { id: "settings-about", group: "Ajustes", label: "Sobre", run: () => (setSection("sobre"), setView("settings")) },
        ];

  // --- tela --------------------------------------------------------------

  /** Folha de cada aba à vista nesta worktree. */
  const leafOfTab = new Map(leaves(current.root).flatMap((l) => (l.tab ? [[l.tab, l.id] as const] : [])));

  const slotOf = (key: string): Slot => {
    if (floatSession?.id === key) return floatOpen ? "float" : "hidden";
    return leafOfTab.has(key) ? "tile" : "hidden";
  };
  const boxOf = (key: string): CSSProperties | undefined => {
    const id = leafOfTab.get(key);
    const r = id ? rects.get(id) : undefined;
    return r ? boxStyle(r) : undefined;
  };

  const focusSlot = (key: string) => {
    if (!key.startsWith("doc:")) setDockOverride(null);
    if (floatSession?.id === key) return setFloatFocused(true);
    const id = leafOfTab.get(key);
    if (id) focusLeafId(id);
  };

  // --- arrastar abas e divisórias --------------------------------------------------

  const panesRef = useRef<HTMLDivElement>(null);
  /** Folhas em pixels na tela agora (para o arrasto achar o painel sob o ponteiro). */
  const leafAt = (x: number, y: number): TabDrag["target"] => {
    const box = panesRef.current?.getBoundingClientRect();
    if (!box) return null;
    for (const [id, r] of rects) {
      const px = { left: box.left + r.x * box.width, top: box.top + r.y * box.height, width: r.w * box.width, height: r.h * box.height };
      if (x >= px.left && x < px.left + px.width && y >= px.top && y < px.top + px.height) return { leaf: id, zone: dropZone(px, x, y) };
    }
    return null;
  };

  const onTabDrag = (phase: "move" | "end" | "cancel", key: string, x: number, y: number) => {
    if (phase === "cancel") return setTabDrag(null);
    const target = leafAt(x, y);
    if (phase === "move") return setTabDrag({ key, x, y, target });
    setTabDrag(null);
    if (target) dropTab(key, target.leaf, target.zone);
  };

  /** Arrastar a divisória muda a proporção; dois cliques voltam ao meio. */
  const startResize = (event: ReactPointerEvent<HTMLDivElement>, splitId: string, dir: "row" | "col", box: Rect) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const host = panesRef.current?.getBoundingClientRect();
    if (!host) return;
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    setResizing(true);
    const place = placeKey;
    const move = (ev: PointerEvent) => {
      const ratio =
        dir === "row" ? ((ev.clientX - host.left) / host.width - box.x) / box.w : ((ev.clientY - host.top) / host.height - box.y) / box.h;
      updateLayout(place, (layout) => {
        const root = setRatio(layout.root, splitId, ratio);
        return root === layout.root ? layout : { ...layout, root };
      });
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      setResizing(false);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  };

  /** Onde fica a divisória de um nó (6px para pegar com o mouse, centrada na linha de 1px). */
  const dividerStyle = (dir: "row" | "col", box: Rect, ratio: number): CSSProperties => {
    const pct = (n: number) => `${(n * 100).toFixed(4)}%`;
    return dir === "row"
      ? { left: `calc(${pct(box.x + box.w * ratio)} - 3.5px)`, top: pct(box.y), height: pct(box.h), width: "6px" }
      : { top: `calc(${pct(box.y + box.h * ratio)} - 3.5px)`, left: pct(box.x), width: pct(box.w), height: "6px" };
  };

  /** Realce do que soltar a aba faria: o painel todo (trocar) ou a metade do lado (dividir). */
  const dropPreview = (target: NonNullable<TabDrag["target"]>): CSSProperties | undefined => {
    const r = rects.get(target.leaf);
    if (!r) return undefined;
    const half = { ...r };
    if (target.zone === "left") half.w = r.w / 2;
    else if (target.zone === "right") (half.x = r.x + r.w / 2), (half.w = r.w / 2);
    else if (target.zone === "top") half.h = r.h / 2;
    else if (target.zone === "bottom") (half.y = r.y + r.h / 2), (half.h = r.h / 2);
    return boxStyle(half);
  };

  const inspectorSessions = contextPlace ? harness.sessions.filter((s) => placeFor(s.cwd)?.worktree.path === contextPlace.worktree.path) : [];

  return (
    <div className="app" {...browserDrag}>
      <TitleBar
        theme={theme}
        onCycleTheme={() => setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length])}
        onPalette={() => setPalette("all")}
        pomodoro={pomodoro.state.phase !== "idle" ? { label: pomodoro.label, phase: pomodoro.state.phase } : null}
        onPomodoro={() => setView("study")}
        bell={{
          items: harness.inbox.items,
          unread: harness.inbox.unread,
          open: bellOpen,
          onToggle: () => setBellOpen((v) => !v),
          onClose: closeBell,
          onPick: openNotice,
          onMarkAllRead: harness.inbox.markAllRead,
          onClear: harness.inbox.clear,
        }}
      />
      {harness.coreVersion && harness.coreVersion !== __APP_VERSION__ && <CoreVersionBanner core={harness.coreVersion} open={openSessions} />}
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
            prefs={harness.prefs}
            onSavePrefs={harness.savePrefs}
            openSessions={openSessions}
            skillsCwd={contextPlace?.worktree.path ?? ""}
            skillsCwdLabel={contextPlace ? `${contextPlace.project.name} · ${worktreeLabel(contextPlace.worktree)}` : null}
            onCloseSession={harness.close}
            onGoToSession={(id) => select(id)}
            keymap={harness.keymap}
            keymapFile={harness.keymapFile}
            onSaveKeymap={harness.saveKeymap}
            onReloadKeymap={() => void harness.reloadKeymap()}
            commands={harness.commands}
            projects={harness.projects}
            currentProject={projectPath}
            onRunCommand={runCommand}
            termTheme={termTheme}
            onTermTheme={setTermTheme}
            onUpdateStarted={(session) => {
              harness.adopt(session);
              select(session.id, placeKeyOf(session.cwd));
              setToast("Atualizando num terminal à vista. Quando terminar, feche e abra a MÊTIS.");
            }}
          />
        )}
        {view === "agents" && (
          <Agents
            client={harness.client}
            agents={harness.agents}
            accounts={harness.accounts}
            run={harness.run}
            onLaunch={launchAgent}
            onTest={(draft) => {
              setView("term");
              void create(draft.cli, {
                cwd: draft.folder || null,
                title: `${draft.name} (teste)`,
                draft: { name: draft.name, cli: draft.cli, model: draft.model, folder: draft.folder, prompt: draft.prompt },
              });
            }}
            connectors={harness.connectors ?? []}
          />
        )}
        {view === "study" && (
          <StudyView client={harness.client} tick={harness.routinesTick} pomodoro={pomodoro} agents={harness.agents} onLaunch={launchAgent} />
        )}
        {view === "today" && (
          <TodayView
            client={harness.client}
            tick={harness.routinesTick + harness.brainTick}
            agents={harness.agents}
            sessions={harness.sessions}
            approvals={harness.approvals}
            hasSlack={(harness.connectors ?? []).some((a) => a.kind === "slack")}
            onOpenSession={select}
            onOpenTasks={(project) => openTasks(project)}
            onDecide={decide}
            onToast={setToast}
            suggestionsTick={harness.suggestionsTick}
            onOpenNote={(title) => openNote({ title })}
          />
        )}
        {view === "connectors" && (
          <ConnectorsView
            client={harness.client}
            accounts={harness.connectors}
            approvals={harness.approvals}
            activity={harness.activity}
            onActivity={harness.setActivity}
            onDecide={decide}
            onToast={setToast}
          />
        )}
        {view === "automations" && (
          <AutomationsView
            client={harness.client}
            agents={harness.agents}
            tick={harness.automationTick}
            event={harness.automationEvent}
            onOpenSession={select}
            onToast={setToast}
          />
        )}
        {view === "boards" && (
          <BoardsView
            client={harness.client}
            sessions={harness.sessions}
            agents={harness.agents}
            onOpenSession={select}
            onOpenNote={(target) => openNote(target)}
            onOpenTasks={(project) => openTasks(project)}
            onOpenWeb={(url, design) => openWeb(url, { design })}
            onNewSession={(kind, cwd, agent) => create(kind, { cwd, agent })}
            onToast={setToast}
          />
        )}
        {view === "brain" && (
          <BrainView
            client={harness.client}
            tick={harness.brainTick}
            request={brainRequest}
            projects={boardNames}
            onOpenTasks={(project) => openTasks(project)}
            onError={setToast}
            suggestionsTick={harness.suggestionsTick}
            onOpenTab={openNoteTab}
          />
        )}
        {view === "kanban" && (
          <KanbanView
            client={harness.client}
            tick={harness.brainTick}
            request={kanbanRequest}
            onOpenNote={(title) => openNote({ title })}
            onOpenProject={(project) => void openBoardProject(project)}
            onRunTask={(project, task) => void runTask(project, task)}
            onRunIssue={(project, issue) => void runIssue(project, issue)}
            onOpenUrl={(url) => openWeb(url)}
            onError={setToast}
          />
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
            onWeb={() => openWeb()}
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
              visible={visibleTabs(current.root)}
              focusedKey={focusedKey}
              tiled={tiled}
              floatOpen={floatOpen}
              inspectorOpen={inspectorOpen}
              hints={{ split: hint("dividir.direita"), splitDown: hint("dividir.baixo"), float: hint("flutuante"), panel: hint("painel"), palette: hint("paleta") }}
              onSelect={(key) => select(key)}
              onClose={closeTab}
              onSplit={splitFocused}
              onDrag={onTabDrag}
              onToggleFloat={() => void toggleFloat()}
              onToggleInspector={() => setInspectorOpen((v) => !v)}
              onPalette={() => setPalette("all")}
            />
          )}
          <div className="workspace">
            <div className="panes" ref={panesRef} data-split={tiled ? "true" : undefined} data-resizing={resizing ? "true" : undefined}>
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
                      box={boxOf(session.id)}
                      focused={session.id === focusedKey}
                      tiled={tiled}
                      colors={termTheme?.cores}
                      searchSignal={searchSignal?.id === session.id ? searchSignal.n : undefined}
                      accountName={accountName(session)}
                      badge={agent ? <AgentSprite agent={agent} client={harness.client} size={16} /> : undefined}
                      place={place ? `${place.project.name} · ${worktreeLabel(place.worktree)}` : null}
                      dropping={drop === session.id}
                      onLink={(url, external) => (external ? void openExternal(url) : openWeb(url, { root: place?.worktree.path }))}
                      onFocus={() => focusSlot(session.id)}
                      readOnly={session.kind !== "shell"}
                      onTyped={(text) => {
                        focusSlot(session.id);
                        window.setTimeout(() => dock.current?.type(text), 0);
                      }}
                      onFocusInput={() => dock.current?.focus()}
                      corner={
                        session.kind !== "shell" && slot !== "float" ? (
                          <MiniMap
                            client={harness.client!}
                            sessionId={session.id}
                            tick={(harness.sessionMapTicks[session.id] ?? 0) + harness.brainTick}
                            onOpenNote={(title) => openNote({ title })}
                          />
                        ) : undefined
                      }
                      onHide={
                        slot === "float"
                          ? () => setFloatOpen(false)
                          : tiled && slot === "tile"
                            ? () => closePane(leafOfTab.get(session.id))
                            : undefined
                      }
                      onRestart={session.kind !== "shell" ? (continuar) => restartAgent(session, continuar) : undefined}
                      onHandOff={session.kind !== "shell" ? (nota) => handOffAgent(session, nota) : undefined}
                      onClose={() => closeTab(session.id)}
                      onHistory={() => setHistoryOpen(true)}
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
                        box={boxOf(doc.key)}
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
                      theme={theme}
                      client={harness.client!}
                      visible={docSlot !== "hidden" && view === "term"}
                      focused={doc.key === focusedKey && tiled}
                      slot={docSlot}
                      box={boxOf(doc.key)}
                      notes={notes[doc.root] ?? []}
                      onAddNote={(note) => addNote(doc.root, note)}
                      onRemoveNote={(id) => removeNote(doc.root, id)}
                      onFocus={() => focusSlot(doc.key)}
                      onOpenFile={(path) => openFile(path, doc.root)}
                      onError={setToast}
                      onGitChanged={() => {
                        setGitTick((n) => n + 1);
                        void wt.refresh();
                      }}
                      onAgent={(prompt) => void askAgent(prompt, doc.root)}
                      onOpenNote={(title) => openNote({ title })}
                    />
                  );
                })}
              {/* Painéis vazios da divisão: escolher uma aba ou abrir algo ali. */}
              {tiled &&
                leaves(current.root)
                  .filter((l) => !l.tab)
                  .map((l) => (
                    <div
                      key={l.id}
                      className="pane pane-empty"
                      data-slot="tile"
                      style={boxStyle(rects.get(l.id)!)}
                      onMouseDown={() => focusLeafId(l.id)}
                      data-focused={l.id === current.focus && !floatFocused ? "true" : undefined}
                    >
                      <button type="button" className="icon-btn pane-empty-close" title={`Tirar da divisão (${hint("dividir.fechar")})`} onClick={() => closePane(l.id)}>
                        <Icon d={ICON.close} size={13} strokeWidth={2} />
                      </button>
                      <span className="small">Painel vazio. Arraste uma aba para cá, escolha uma aba ou abra aqui:</span>
                      <div className="pane-empty-buttons">
                        {(["claude", "codex", "shell"] as SessionKind[]).map((kind) => (
                          <button key={kind} type="button" className="btn" disabled={!ready} onClick={() => void create(kind)}>
                            <span style={{ color: KIND_COLOR[kind] }}>{KIND_GLYPH[kind]}</span> {KIND_LABEL[kind]}
                          </button>
                        ))}
                        <button type="button" className="btn" onClick={() => openWeb()}>
                          ◍ Navegador
                        </button>
                      </div>
                    </div>
                  ))}
              {!tiled && !focusLeaf.tab && (
                <div className="empty">
                  <h1>{tabItems.length === 0 ? "Nenhum terminal aberto" : "Nada aberto aqui"}</h1>
                  <p>
                    {tabItems.length > 0
                      ? `Os terminais abertos são de outras worktrees (na barra de abas, em cinza). Abra um em ${placeLabel}:`
                      : harness.projects.length === 0
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
                    <button type="button" className="btn" onClick={() => openWeb()}>
                      ◍ Navegador
                    </button>
                  </div>
                  <button type="button" className="link-btn empty-history" disabled={!ready} onClick={() => setHistoryOpen(true)}>
                    <Icon d={ICON.history} size={13} /> Retomar uma conversa…
                  </button>
                  <span className="small">
                    {!ready
                      ? harness.connection === "offline"
                        ? "núcleo fora do ar"
                        : "conectando ao núcleo…"
                      : `em ${selectedPlace ? `${selectedPlace.project.name} · ${worktreeLabel(selectedPlace.worktree)}` : folder.trim() || "~"} · ${hint("paleta")} para tudo · ${hint("pular")} para pular`}
                  </span>
                </div>
              )}
              {/* Divisórias: arrastar muda a proporção, dois cliques voltam ao meio. */}
              {dividers.map((d) => (
                <div
                  key={d.id}
                  className="pane-divider"
                  data-dir={d.dir}
                  role="separator"
                  aria-orientation={d.dir === "row" ? "vertical" : "horizontal"}
                  title="Arraste para mudar o tamanho · dois cliques voltam ao meio"
                  style={dividerStyle(d.dir, d.box, d.ratio)}
                  onPointerDown={(event) => startResize(event, d.id, d.dir, d.box)}
                  onDoubleClick={() => updateLayout(placeKey, (layout) => ({ ...layout, root: setRatio(layout.root, d.id, 0.5) }))}
                />
              ))}
              {tabDrag && (
                <>
                  <div className="tab-drop-cover" />
                  {tabDrag.target && <div className="tab-drop-preview" data-zone={tabDrag.target.zone} style={dropPreview(tabDrag.target)} />}
                </>
              )}
              {/* Sem abas não há barra de abas, e era nela o único botão do painel: ele fica aqui, no mesmo canto. */}
              {tabItems.length === 0 && !inspectorOpen && (
                <button
                  type="button"
                  className="icon-btn panel-reopen"
                  title="Mudanças, arquivos, portas e Brain da worktree (⌘⇧B)"
                  aria-label="Abrir o painel da worktree"
                  onClick={() => setInspectorOpen(true)}
                >
                  <Icon d={ICON.panel} size={15} />
                </button>
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
                onOpenConflict={openConflict}
                onAgent={(prompt) => void askAgent(prompt)}
                prefs={harness.prefs}
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
                brainTick={harness.brainTick}
                onOpenNote={(title) => openNote({ title })}
                onOpenTasks={(project) => openTasks(project)}
                suggestionsTick={harness.suggestionsTick}
                contextSession={dockTarget}
                onNotice={setToast}
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
        onOpenContext={() => {
          setView("term");
          setInspectorOpen(true);
          setInspectorTab("context");
        }}
        onOpenResources={() => {
          setSection("recursos");
          setView("settings");
        }}
      />
      {historyOpen && (
        <HistoryPanel
          client={harness.client}
          here={contextPlace?.worktree.path ?? ""}
          hereLabel={contextPlace ? worktreeLabel(contextPlace.worktree) : null}
          onResume={resumeConversation}
          onClose={() => setHistoryOpen(false)}
        />
      )}
      {palette && (
        <Palette
          key={palette}
          items={paletteItems}
          onClose={() => setPalette(null)}
          placeholder={
            palette === "files"
              ? "Abrir arquivo…"
              : palette === "jump"
                ? "Pular para uma aba, worktree ou tela…"
                : palette === "commands"
                  ? "Rodar um comando salvo…"
                  : undefined
          }
        />
      )}
      {tabDrag && tabByKey.get(tabDrag.key) && (
        <div className="tab-drag-ghost" style={{ left: tabDrag.x + 12, top: tabDrag.y + 10 }}>
          {tabByKey.get(tabDrag.key)!.glyph} {tabByKey.get(tabDrag.key)!.title}
          <span className="small">
            {!tabDrag.target
              ? "solte num painel"
              : tabDrag.target.zone === "center"
                ? "mostrar aqui"
                : `dividir: ${{ left: "à esquerda", right: "à direita", top: "em cima", bottom: "embaixo" }[tabDrag.target.zone]}`}
          </span>
        </div>
      )}
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
      {harness.approvals.length > 0 && view !== "connectors" && (
        <div className="approval-float">
          <ApprovalCard approval={harness.approvals[0]} onDecide={decide} />
          {harness.approvals.length > 1 && (
            <button type="button" className="link-btn approval-more" onClick={() => setView("connectors")}>
              mais {harness.approvals.length - 1} aguardando
            </button>
          )}
        </div>
      )}
      {toast && (
        <div className="toast" role="status" onClick={() => setToast(null)}>
          {toast}
        </div>
      )}
    </div>
  );
}
