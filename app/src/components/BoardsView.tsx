// Quadros (v0.9.1): um quadro livre por projeto, como o Canvas do Obsidian. Cada quadro É um
// .canvas (JSON Canvas 1.0) na pasta do projeto no Brain, então abre no Obsidian também. Cartões de
// nota do Brain, sessão viva (estado, últimas linhas, campo de mensagem), tarefa do kanban, link e
// nota solta. Ligar uma nota do Brain a uma sessão manda a nota para ela como contexto.
//
// Salvar: cada mudança sobe a versão local e grava ~800 ms depois, mandando o `alterado` que a tela
// conhece. Se o Obsidian salvou depois disso, o núcleo recusa (409) e a tela recarrega.

import { useEffect, useMemo, useRef, useState } from "react";
import { ICON, Icon } from "../icons";
import {
  type CardKind,
  type Point,
  type SessionMeta,
  CARD_SIZE,
  cardKind,
  colorOf,
  contextEdges,
  fileName,
  isNote,
  linkInfo,
  looksLikeUrl,
  newId,
  normalizeUrl,
  parseMeta,
  placeFree,
  sessionMetaOf,
  sessionText,
  TASK_STATE,
  taskMetaOf,
  taskText,
} from "../lib/canvas";
import { CoreError, type CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, KIND_LABEL, STATUS_COLOR } from "../lib/format";
import type { Agent, BoardFile, BoardProject, BoardSummary, BrainHit, CanvasDoc, CanvasEdge, CanvasNode, CanvasSide, KanbanTask, Session, SessionKind } from "../types";
import { AddMenu } from "./boards/AddMenu";
import { Board, type BoardApi, type Selection } from "./boards/Board";
import type { CardCtx } from "./boards/Cards";
import "./boards.css";

interface Props {
  client: CoreClient | null;
  sessions: Session[];
  agents: Agent[];
  onOpenSession: (id: string) => void;
  onOpenNote: (target: { path?: string; title?: string }) => void;
  onOpenTasks: (project?: string) => void;
  onOpenWeb: (url: string, design?: boolean) => void;
  /** Abre um terminal (e vai para ele); devolve a sessão, ou null se não abriu. */
  onNewSession: (kind: SessionKind, cwd: string, agent?: string) => Promise<Session | null>;
  onToast: (text: string) => void;
}

type SaveState = "salvo" | "pendente" | "salvando" | "erro";

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));
const isConflict = (cause: unknown) => (cause instanceof CoreError && cause.status === 409) || /409|mudou/i.test(message(cause));

// O quadro aberto sobrevive à troca de tela (a tela desmonta) e ao app fechar.
const LAST = "metis.quadros.ultimo";
const memory: { path: string | null; inflight: Promise<boolean> | null } = { path: null, inflight: null };

function lastPath(): string | null {
  if (memory.path) return memory.path;
  try {
    return localStorage.getItem(LAST);
  } catch {
    return null;
  }
}

function rememberPath(path: string) {
  memory.path = path;
  try {
    localStorage.setItem(LAST, path);
  } catch {
    // sem armazenamento: só esta sessão do app lembra
  }
}

const HERE: { kind: CardKind; label: string }[] = [
  { kind: "sessao", label: "Sessões" },
  { kind: "nota", label: "Notas do Brain" },
  { kind: "tarefa", label: "Tarefas" },
  { kind: "link", label: "Links" },
  { kind: "sticky", label: "Notas suas" },
  { kind: "anexo", label: "Anexos" },
  { kind: "grupo", label: "Grupos" },
];

/** Primeira linha da nota solta, sem a marcação do Markdown. */
function firstLine(text: string): string {
  const line = text.split("\n").find((l) => l.trim()) ?? "";
  const clean = line.replace(/^[#>\-*\s]+|\[\[|\]\]|[*_`]/g, "").trim();
  return clean.length > 42 ? `${clean.slice(0, 40)}…` : clean;
}

export function BoardsView(props: Props) {
  const { client } = props;
  const [list, setList] = useState<BoardSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [projects, setProjects] = useState<BoardProject[]>([]);
  const [path, setPath] = useState<string | null>(null);
  const [info, setInfo] = useState<BoardSummary | null>(null);
  const [doc, setDoc] = useState<CanvasDoc | null>(null);
  const [notas, setNotas] = useState<Record<string, BrainHit | null>>({});
  const [boardError, setBoardError] = useState<string | null>(null);
  const [opens, setOpens] = useState(0);
  const [save, setSave] = useState<{ state: SaveState; error?: string }>({ state: "salvo" });
  const [tasks, setTasks] = useState<KanbanTask[] | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [creating, setCreating] = useState<{ projeto: string; nome: string; busy?: boolean; error?: string } | null>(null);

  const apiRef = useRef<BoardApi | null>(null);
  const docRef = useRef<CanvasDoc | null>(null);
  const pathRef = useRef<string | null>(null);
  const infoRef = useRef<BoardSummary | null>(null);
  infoRef.current = info;
  const baseRef = useRef(0);
  const version = useRef(0);
  const saved = useRef(0);
  const saveTimer = useRef<number | null>(null);
  const saving = useRef<Promise<boolean> | null>(null);
  const mounted = useRef(true);
  const selRef = useRef<Selection>(null);
  selRef.current = selection;
  const addingRef = useRef(false);
  addingRef.current = adding;
  const live = useRef(props);
  live.current = props;

  // --- leitura -------------------------------------------------------------------------------------

  const loadList = async (): Promise<BoardSummary[] | null> => {
    const c = live.current.client;
    if (!c) return null;
    try {
      const items = await c.boards();
      setList(items);
      setListError(null);
      return items;
    } catch (cause) {
      setListError(message(cause));
      return null;
    }
  };

  const apply = (file: BoardFile, fresh: boolean) => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = null;
    docRef.current = file.canvas;
    setDoc(file.canvas);
    setNotas(file.notas ?? {});
    setInfo({ path: file.path, nome: file.nome, projeto: file.projeto, itens: file.itens, alterado: file.alterado });
    baseRef.current = file.alterado;
    version.current = saved.current = 0;
    setSave({ state: "salvo" });
    setBoardError(null);
    if (fresh) {
      setOpens((n) => n + 1);
      setSelection(null);
      setEditingId(null);
    }
    setList((all) => all?.map((b) => (b.path === file.path ? { ...b, alterado: file.alterado, itens: file.canvas.nodes.length } : b)) ?? all);
  };

  const loadBoard = async (target: string, fresh: boolean) => {
    const c = live.current.client;
    if (!c) return;
    // Um salvamento ainda indo (de antes de sair da tela) chega primeiro.
    if (memory.inflight) await memory.inflight;
    try {
      const file = await c.board(target);
      if (pathRef.current === target) apply(file, fresh);
    } catch (cause) {
      if (pathRef.current !== target) return;
      if (fresh) {
        docRef.current = null;
        setDoc(null);
        setBoardError(message(cause));
      } else live.current.onToast(`Não deu para reler o quadro: ${message(cause)}`);
    }
  };

  const loadTasks = () => {
    const c = live.current.client;
    const projeto = infoRef.current?.projeto;
    if (!c || !projeto) return;
    c.tasks(projeto)
      .then((items) => infoRef.current?.projeto === projeto && setTasks(items))
      .catch(() => undefined);
  };

  // --- salvar --------------------------------------------------------------------------------------

  const runSave = async (): Promise<boolean> => {
    const c = live.current.client;
    const target = pathRef.current;
    if (!c || !target) return false;
    // Um salvamento por vez; quem esperava confere se o que ele ia mandar já foi.
    while (saving.current) await saving.current;
    if (pathRef.current !== target || !docRef.current || saved.current >= version.current) return true;
    const v = version.current;
    const canvas = docRef.current;
    const job = (async () => {
      setSave({ state: "salvando" });
      try {
        const answer = await c.saveBoard(target, canvas, baseRef.current);
        if (pathRef.current === target) {
          baseRef.current = answer.alterado;
          saved.current = Math.max(saved.current, v);
          setNotas((all) => ({ ...all, ...answer.notas }));
          setSave(saved.current >= version.current ? { state: "salvo" } : { state: "pendente" });
          setList((all) => all?.map((b) => (b.path === target ? { ...b, alterado: answer.alterado, itens: canvas.nodes.length } : b)) ?? all);
        }
        return true;
      } catch (cause) {
        if (isConflict(cause)) {
          live.current.onToast("O quadro mudou no Obsidian; recarreguei.");
          if (pathRef.current === target) void loadBoard(target, false);
        } else setSave({ state: "erro", error: message(cause) });
        return false;
      }
    })();
    saving.current = job;
    memory.inflight = job;
    const ok = await job;
    if (saving.current === job) saving.current = null;
    return ok;
  };
  const runSaveRef = useRef(runSave);
  runSaveRef.current = runSave;

  const scheduleSave = () => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = null;
    // Fora da tela (a sessão nova levou para o terminal), grava na hora.
    if (!mounted.current) return void runSave();
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      void runSave();
    }, 800);
  };

  const flush = async () => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = null;
    if (version.current > saved.current) await runSave();
    else if (saving.current) await saving.current;
  };

  /** Toda mudança no quadro passa por aqui. Só usa refs: vale mesmo depois de a tela sair. */
  const edit = (change: (current: CanvasDoc) => CanvasDoc) => {
    const current = docRef.current;
    if (!current) return;
    const next = change(current);
    if (next === current) return;
    docRef.current = next;
    setDoc(next);
    version.current += 1;
    setSave((s) => (s.state === "salvando" ? s : { state: "pendente" }));
    scheduleSave();
  };

  // --- abrir e criar quadros ---------------------------------------------------------------------------

  const open = async (target: string) => {
    if (target === pathRef.current && docRef.current) return;
    await flush();
    pathRef.current = target;
    rememberPath(target);
    setPath(target);
    docRef.current = null;
    setDoc(null);
    setInfo(null);
    setTasks(null);
    setBoardError(null);
    setSelection(null);
    setEditingId(null);
    setAdding(false);
    await loadBoard(target, true);
  };

  const startCreate = () => {
    setCreating({ projeto: infoRef.current?.projeto ?? projects[0]?.name ?? "", nome: "" });
    if (!projects.length) void live.current.client?.boardProjects().then(setProjects).catch(() => undefined);
  };

  const createBoard = async () => {
    const c = live.current.client;
    if (!c || !creating) return;
    const nome = creating.nome.trim();
    const projeto = creating.projeto || projects[0]?.name || "";
    if (!nome || !projeto) return;
    setCreating({ ...creating, busy: true, error: undefined });
    try {
      const summary = await c.createBoard(projeto, nome);
      setCreating(null);
      await loadList();
      await open(summary.path);
    } catch (cause) {
      setCreating((all) => all && { ...all, busy: false, error: message(cause) });
    }
  };

  // Primeira vez: lista, projetos e o último quadro aberto (ou o primeiro).
  useEffect(() => {
    if (!client) return;
    void client.boardProjects().then(setProjects).catch(() => undefined);
    void loadList().then((items) => {
      if (!items?.length || pathRef.current) return;
      const want = lastPath();
      void open(items.find((b) => b.path === want)?.path ?? items[0].path);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  // A cada 5 s com a tela à vista: a lista e, se o Obsidian salvou o quadro aberto (e não há
  // mudança nossa por gravar), relê. As tarefas do kanban acompanham se há cartão de tarefa.
  useEffect(() => {
    if (!client) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadList().then((items) => {
        const target = pathRef.current;
        const item = items?.find((b) => b.path === target);
        if (!target || !item || !docRef.current) return;
        const quiet = !saving.current && !saveTimer.current && version.current <= saved.current;
        if (quiet && item.alterado > baseRef.current + 0.001) void loadBoard(target, false);
      });
      if (docRef.current?.nodes.some((n) => !!taskMetaOf(n))) loadTasks();
    }, 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  useEffect(() => {
    setTasks(null);
    if (info?.projeto) loadTasks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info?.projeto, client]);

  // Sair da tela grava o que estiver pendente.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
      if (version.current > saved.current) void runSaveRef.current();
    };
  }, []);

  // --- cartões novos ------------------------------------------------------------------------------------

  const addNode = (partial: Partial<CanvasNode> & Pick<CanvasNode, "type">, kind: CardKind, at?: Point | null): string | null => {
    const current = docRef.current;
    if (!current) return null;
    const size = CARD_SIZE[kind];
    const c = at ?? apiRef.current?.center() ?? { x: 0, y: 0 };
    const spot = placeFree(current.nodes, c.x, c.y, size.width, size.height, kind === "grupo");
    const node: CanvasNode = { ...partial, id: newId(), x: spot.x, y: spot.y, width: size.width, height: size.height };
    // Grupo vai para o começo: no Obsidian a ordem é a de desenho, e a moldura fica atrás.
    edit((d) => ({ ...d, nodes: kind === "grupo" ? [node, ...d.nodes] : [...d.nodes, node] }));
    if (mounted.current) setSelection({ kind: "node", id: node.id });
    return node.id;
  };

  const sessionMeta = (s: Session): SessionMeta => {
    const agent = s.agent ? live.current.agents.find((a) => a.id === s.agent) : undefined;
    return {
      tipo: "sessao",
      sessao: s.id,
      titulo: agent?.name ?? (s.title || KIND_LABEL[s.kind]),
      kind: s.kind,
      cwd: s.cwd,
      ...(s.agent ? { agente: s.agent } : {}),
    };
  };

  const addSession = (s: Session, at?: Point | null) => addNode({ type: "text", text: sessionText(sessionMeta(s)) }, "sessao", at);

  const projectDir = () => projects.find((p) => p.name === infoRef.current?.projeto)?.directory || "~";

  const newSession = async () => {
    // O lugar é calculado antes: abrir a sessão leva para o terminal e a tela sai.
    const at = apiRef.current?.center() ?? null;
    setAdding(false);
    const s = await live.current.onNewSession("claude", projectDir());
    if (!s) return live.current.onToast("Não consegui abrir a sessão do Claude.");
    addSession(s, at);
  };

  const reopen = async (nodeId: string) => {
    const meta = sessionMetaOf(docRef.current?.nodes.find((n) => n.id === nodeId));
    if (!meta) return;
    // Sessão de agente volta com o mesmo agente (papel, modelo e conectores dele).
    const s = await live.current.onNewSession(meta.kind, meta.cwd, meta.agente);
    if (!s) return live.current.onToast("Não consegui abrir a sessão de novo.");
    const next: SessionMeta = {
      tipo: "sessao",
      sessao: s.id,
      titulo: meta.agente ? s.title || KIND_LABEL[s.kind] : meta.titulo,
      kind: s.kind,
      cwd: s.cwd || meta.cwd,
      ...(s.agent ? { agente: s.agent } : {}),
    };
    edit((d) => ({ ...d, nodes: d.nodes.map((n) => (n.id === nodeId ? { ...n, text: sessionText(next) } : n)) }));
  };

  const addTask = (task: KanbanTask) => {
    const projeto = infoRef.current?.projeto;
    if (!projeto) return;
    addNode({ type: "text", text: taskText({ tipo: "tarefa", projeto, id: task.id }, task) }, "tarefa");
    setAdding(false);
  };

  const addNote = (hit: BrainHit) => {
    setNotas((all) => ({ ...all, [hit.path]: hit }));
    addNode({ type: "file", file: hit.path }, "nota");
    setAdding(false);
  };

  const addSticky = (text = "", at?: Point | null) => {
    const id = addNode({ type: "text", text }, "sticky", at);
    if (!text) setEditingId(id);
    setAdding(false);
  };

  const dropExternal = (data: { url?: string; text?: string }, at: Point) => {
    const text = data.text?.trim() ?? "";
    if (data.url || looksLikeUrl(text)) addNode({ type: "link", url: normalizeUrl(data.url ?? text) }, "link", at);
    else if (text) addSticky(text, at);
  };

  // --- ligações -----------------------------------------------------------------------------------------

  /** Nota do Brain ligada a uma sessão: a ligação fica com o rótulo "contexto" e a sessão recebe a nota. */
  const linkContext = async (noteId: string, sessionNodeId: string, sides?: { from: CanvasSide; to: CanvasSide }) => {
    const d = docRef.current;
    const note = d?.nodes.find((n) => n.id === noteId);
    const meta = sessionMetaOf(d?.nodes.find((n) => n.id === sessionNodeId));
    if (!d || !note || !meta || !isNote(note)) return;
    const existing = d.edges.find((e) => (e.fromNode === noteId && e.toNode === sessionNodeId) || (e.fromNode === sessionNodeId && e.toNode === noteId));
    if (meta.kind === "shell") {
      // No shell o pedido viraria um comando digitado: só a ligação fica no quadro.
      if (!existing) {
        const edge: CanvasEdge = { id: newId(), fromNode: noteId, toNode: sessionNodeId, ...(sides ? { fromSide: sides.from, toSide: sides.to } : {}) };
        edit((doc) => ({ ...doc, edges: [...doc.edges, edge] }));
      }
      live.current.onToast("Ligada no quadro. Nota vira contexto só numa sessão do Claude ou do Codex.");
      return;
    }
    if (!existing) {
      const edge: CanvasEdge = { id: newId(), fromNode: noteId, toNode: sessionNodeId, label: "contexto", ...(sides ? { fromSide: sides.from, toSide: sides.to } : {}) };
      edit((doc) => ({ ...doc, edges: [...doc.edges, edge] }));
    } else if (!existing.label) {
      edit((doc) => ({ ...doc, edges: doc.edges.map((e) => (e.id === existing.id ? { ...e, label: "contexto" } : e)) }));
    }
    const c = live.current.client;
    const session = live.current.sessions.find((s) => s.id === meta.sessao);
    if (!c) return;
    if (!session || session.status === "exited") {
      live.current.onToast("A sessão está encerrada: abra de novo pelo cartão e ligue a nota outra vez.");
      return;
    }
    try {
      await c.linkNoteToSession(meta.sessao, note.file!);
      live.current.onToast("A sessão recebeu a nota como contexto.");
    } catch (cause) {
      live.current.onToast(`A nota não chegou à sessão: ${message(cause)}`);
    }
  };

  const connect = (from: string, fromSide: CanvasSide, to: string, toSide: CanvasSide) => {
    const d = docRef.current;
    if (!d) return;
    const a = d.nodes.find((n) => n.id === from);
    const b = d.nodes.find((n) => n.id === to);
    if (isNote(a) && sessionMetaOf(b)) return void linkContext(from, to, { from: fromSide, to: toSide });
    if (isNote(b) && sessionMetaOf(a)) return void linkContext(to, from, { from: toSide, to: fromSide });
    const existing = d.edges.find((e) => e.fromNode === from && e.toNode === to);
    if (existing) return setSelection({ kind: "edge", id: existing.id });
    const edge: CanvasEdge = { id: newId(), fromNode: from, fromSide, toNode: to, toSide };
    edit((doc) => ({ ...doc, edges: [...doc.edges, edge] }));
    // Selecionada, a ligação nova já mostra o campo do rótulo.
    setSelection({ kind: "edge", id: edge.id });
  };

  const removeSelection = () => {
    const sel = selRef.current;
    if (!sel) return;
    if (sel.kind === "node")
      edit((d) => ({ ...d, nodes: d.nodes.filter((n) => n.id !== sel.id), edges: d.edges.filter((e) => e.fromNode !== sel.id && e.toNode !== sel.id) }));
    else edit((d) => ({ ...d, edges: d.edges.filter((e) => e.id !== sel.id) }));
    setSelection(null);
    setEditingId(null);
  };

  // Delete tira o selecionado; Esc limpa. Dentro de campo de texto, as teclas são do campo.
  const keyAct = useRef(removeSelection);
  keyAct.current = removeSelection;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || addingRef.current) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (event.key === "Escape") {
        setSelection(null);
        setEditingId(null);
      } else if ((event.key === "Delete" || event.key === "Backspace") && !event.metaKey && !event.ctrlKey && selRef.current) {
        event.preventDefault();
        keyAct.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // --- o que os cartões pedem (estável: os cartões não redesenham à toa) -------------------------------

  const act = useRef({ edit, reopen, send: async (_id: string, _text: string) => false });
  act.current = {
    edit,
    reopen,
    send: async (id: string, text: string) => {
      const c = live.current.client;
      if (!c) return false;
      try {
        await c.sendToSession(id, text);
        return true;
      } catch (cause) {
        live.current.onToast(`A mensagem não foi: ${message(cause)}`);
        return false;
      }
    },
  };

  const ctx = useMemo<CardCtx>(
    () => ({
      client,
      openNote: (notePath) => live.current.onOpenNote({ path: notePath }),
      openNoteTitle: (title) => live.current.onOpenNote({ title }),
      openTasks: (projeto) => live.current.onOpenTasks(projeto),
      openWeb: (url, design) => live.current.onOpenWeb(url, design),
      openSession: (id) => live.current.onOpenSession(id),
      reopen: (id) => void act.current.reopen(id),
      send: (id, text) => act.current.send(id, text),
      setText: (id, text) => act.current.edit((d) => ({ ...d, nodes: d.nodes.map((n) => (n.id === id ? { ...n, text } : n)) })),
      setLabel: (id, label) => act.current.edit((d) => ({ ...d, nodes: d.nodes.map((n) => (n.id === id ? { ...n, label } : n)) })),
      stopEditing: () => setEditingId(null),
    }),
    [client],
  );

  // --- desenho ---------------------------------------------------------------------------------------------

  const groups = useMemo(() => {
    const out = new Map<string, BoardSummary[]>();
    for (const b of list ?? []) {
      const key = b.projeto ?? "Sem projeto";
      out.set(key, [...(out.get(key) ?? []), b]);
    }
    return Array.from(out.entries());
  }, [list]);

  const sessionsById = useMemo(() => new Map(props.sessions.map((s) => [s.id, s])), [props.sessions]);

  const here = useMemo(() => {
    if (!doc) return [];
    const items = doc.nodes.map((n) => {
      const kind = cardKind(n);
      let label = "";
      let color = colorOf(n.color) ?? "var(--line2)";
      let glyph: { text: string; color: string } | null = null;
      if (kind === "sessao") {
        const meta = sessionMetaOf(n)!;
        const s = sessionsById.get(meta.sessao);
        label = meta.titulo;
        glyph = { text: KIND_GLYPH[meta.kind], color: KIND_COLOR[meta.kind] };
        color = s ? STATUS_COLOR[s.status] : "var(--fnt)";
      } else if (kind === "nota") {
        label = notas[n.file ?? ""]?.title ?? fileName(n.file ?? "");
        color = colorOf(n.color) ?? "var(--acc)";
      } else if (kind === "tarefa") {
        const meta = taskMetaOf(n)!;
        const task = tasks?.find((t) => t.id === meta.id);
        label = task?.text ?? /- \[[ xX]\] (.+)/.exec(parseMeta(n.text).body)?.[1] ?? "Tarefa";
        if (task) color = TASK_STATE[task.state].color;
      } else if (kind === "link") {
        const link = linkInfo(n.url ?? "");
        label = `${link.host}${link.path}`;
      } else if (kind === "sticky") {
        label = firstLine(n.text ?? "") || "Nota vazia";
        color = colorOf(n.color) ?? "var(--wait)";
      } else if (kind === "anexo") label = (n.file ?? "").split("/").pop() ?? "";
      else label = n.label || "Grupo";
      return { id: n.id, kind, label, color, glyph };
    });
    return HERE.map((h) => ({ ...h, items: items.filter((i) => i.kind === h.kind) })).filter((h) => h.items.length);
  }, [doc, notas, tasks, sessionsById]);

  const present = useMemo(() => {
    const nodes = doc?.nodes ?? [];
    return {
      notes: new Set(nodes.filter((n) => n.type === "file").map((n) => n.file ?? "")),
      sessions: new Set(nodes.map((n) => sessionMetaOf(n)?.sessao).filter((x): x is string => !!x)),
      tasks: new Set(nodes.map((n) => taskMetaOf(n)?.id).filter((x): x is string => !!x)),
    };
  }, [doc]);

  const linked = doc ? contextEdges(doc).length : 0;
  const count = doc?.nodes.length ?? 0;
  const saveLabel = save.state === "salvo" ? "salvo" : save.state === "erro" ? "não salvo" : "salvando…";

  if (!client) {
    return (
      <div className="bd-screen">
        <p className="bd-blank">Conectando ao núcleo…</p>
      </div>
    );
  }

  const createForm = creating && (
    <form
      className="bd-create"
      onSubmit={(event) => {
        event.preventDefault();
        void createBoard();
      }}
    >
      <label className="bd-field">
        <span>Projeto</span>
        <select value={creating.projeto} onChange={(event) => setCreating({ ...creating, projeto: event.target.value })} aria-label="Projeto do quadro">
          {!projects.length && <option value="">Nenhum projeto no Brain</option>}
          {projects.map((p) => (
            <option key={p.path} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="bd-field">
        <span>Nome</span>
        <input
          autoFocus
          value={creating.nome}
          placeholder="go-live, arquitetura, ideias…"
          aria-label="Nome do quadro"
          onChange={(event) => setCreating({ ...creating, nome: event.target.value })}
          onKeyDown={(event) => event.key === "Escape" && setCreating(null)}
        />
      </label>
      {creating.error && <p className="bd-error">{creating.error}</p>}
      <div className="bd-row">
        <button type="submit" className="btn primary" disabled={!creating.nome.trim() || !(creating.projeto || projects[0]) || creating.busy}>
          {creating.busy ? "Criando…" : "Criar"}
        </button>
        <button type="button" className="btn" onClick={() => setCreating(null)}>
          Cancelar
        </button>
      </div>
    </form>
  );

  const empty = list !== null && list.length === 0;

  return (
    <div className="bd-screen">
      <aside className="bd-list">
        <header className="bd-list-head">
          <span className="bd-caps">Quadros</span>
          <button type="button" className="icon-btn" title="Novo quadro" aria-label="Novo quadro" onClick={() => (creating ? setCreating(null) : startCreate())}>
            <Icon d={ICON.plus} size={15} />
          </button>
        </header>
        <div className="bd-list-body">
          {listError && (
            <div className="bd-list-note">
              <p>Não deu para ler os quadros: {listError}</p>
              <button type="button" className="btn" onClick={() => void loadList()}>
                Tentar de novo
              </button>
            </div>
          )}
          {list === null && !listError && <p className="small bd-list-note">Carregando…</p>}
          {empty && <p className="small bd-list-note">Nenhum quadro ainda.</p>}
          {groups.map(([projeto, boards]) => (
            <section key={projeto} className="bd-proj">
              <span className="bd-proj-name">{projeto}</span>
              {boards.map((b) => (
                <button key={b.path} type="button" className="bd-item" aria-current={b.path === path ? "true" : undefined} title={b.path} onClick={() => void open(b.path)}>
                  <Icon d={ICON.canvas} size={14} strokeWidth={1.8} />
                  <span className="bd-item-name">{b.nome}</span>
                  <span className="bd-item-count mono">{b.path === path && doc ? doc.nodes.length : b.itens}</span>
                </button>
              ))}
            </section>
          ))}
          {doc && (
            <section className="bd-here" aria-label="Neste quadro">
              <span className="bd-proj-name">Neste quadro</span>
              {here.length === 0 && <p className="small bd-list-note">Nada ainda.</p>}
              {here.map((h) => (
                <div key={h.kind} className="bd-here-group">
                  <span className="bd-here-kind mono">{h.label}</span>
                  {h.items.map((i) => (
                    <button
                      key={i.id}
                      type="button"
                      className="bd-here-item"
                      aria-current={selection?.kind === "node" && selection.id === i.id ? "true" : undefined}
                      onClick={() => {
                        apiRef.current?.centerOn(i.id);
                        setSelection({ kind: "node", id: i.id });
                      }}
                    >
                      {i.glyph ? (
                        <span className="bd-here-glyph" style={{ color: i.glyph.color }}>
                          {i.glyph.text}
                        </span>
                      ) : (
                        <span className="bd-here-mark" style={{ background: i.color }} />
                      )}
                      <span className="bd-here-label">{i.label}</span>
                      {i.kind === "sessao" && <span className="dot" style={{ background: i.color }} />}
                    </button>
                  ))}
                </div>
              ))}
            </section>
          )}
        </div>
        {!empty && <footer className="bd-list-foot">{createForm || (
          <button type="button" className="btn" onClick={startCreate}>
            <Icon d={ICON.plus} size={12} strokeWidth={2.2} /> Novo quadro
          </button>
        )}</footer>}
      </aside>

      {empty ? (
        <section className="bd-main bd-welcome">
          <div>
            <span className="bd-welcome-icon">
              <Icon d={ICON.canvas} size={28} strokeWidth={1.6} />
            </span>
            <h2>Nenhum quadro ainda</h2>
            <p>
              Um quadro é um espaço livre por projeto, como o Canvas do Obsidian: notas do Brain, sessões vivas, tarefas do kanban e links lado a lado,
              ligados por setas. Ele mora na pasta do projeto no Brain como um arquivo .canvas, então abre no Obsidian também.
            </p>
            <p>Solte uma nota do Brain em cima de uma sessão e ela recebe a nota como contexto.</p>
            {createForm || (
              <button type="button" className="btn primary" onClick={startCreate}>
                <Icon d={ICON.plus} size={12} strokeWidth={2.2} /> Novo quadro
              </button>
            )}
          </div>
        </section>
      ) : (
        <section className="bd-main">
          <header className="bd-bar">
            <div className="bd-bar-left">
              <span className="bd-caps">Quadros{info?.projeto ? ` · ${info.projeto}` : ""}</span>
              {info && <b className="bd-title">{info.nome}</b>}
              {info && (
                <span className="bd-save mono" data-state={save.state} title={save.error}>
                  {saveLabel}
                  {save.state === "erro" && (
                    <button type="button" className="link-btn" onClick={() => scheduleSave()}>
                      tentar de novo
                    </button>
                  )}
                </span>
              )}
            </div>
            <div className="bd-addwrap">
              {info && client && (
                <button
                  type="button"
                  className="btn"
                  title="Abrir este .canvas no Obsidian"
                  onClick={() => void client.openInObsidian(info.path).catch((cause) => props.onToast(cause instanceof Error ? cause.message : String(cause)))}
                >
                  Abrir no Obsidian
                </button>
              )}
              <button type="button" className="btn primary bd-add-btn" disabled={!doc} aria-expanded={adding} onClick={() => setAdding((v) => !v)}>
                <Icon d={ICON.plus} size={13} strokeWidth={2.2} /> Adicionar
              </button>
              {adding && doc && (
                <AddMenu
                  client={client}
                  projeto={info?.projeto ?? null}
                  sessions={props.sessions.filter((s) => s.status !== "exited")}
                  agents={props.agents}
                  tasks={tasks}
                  present={present}
                  newSessionWhere={projectDir()}
                  onAddNote={addNote}
                  onAddSession={(s) => {
                    addSession(s);
                    setAdding(false);
                  }}
                  onNewSession={() => void newSession()}
                  onAddTask={addTask}
                  onAddLink={(url) => {
                    addNode({ type: "link", url }, "link");
                    setAdding(false);
                  }}
                  onAddSticky={() => addSticky()}
                  onAddGroup={() => {
                    const id = addNode({ type: "group", label: "Grupo" }, "grupo");
                    setEditingId(id);
                    setAdding(false);
                  }}
                  onLoadTasks={loadTasks}
                  onClose={() => setAdding(false)}
                />
              )}
            </div>
          </header>
          <div className="bd-stage">
            {doc && path ? (
              <Board
                doc={doc}
                notas={notas}
                sessions={props.sessions}
                agents={props.agents}
                tasks={tasks}
                selection={selection}
                editingId={editingId}
                viewKey={path}
                fitKey={`${path}#${opens}`}
                apiRef={apiRef}
                ctx={ctx}
                onSelect={setSelection}
                onEditing={setEditingId}
                onEdit={edit}
                onConnect={connect}
                onDropOnSession={(noteId, sessionNodeId) => void linkContext(noteId, sessionNodeId)}
                onRemove={removeSelection}
                onDropExternal={dropExternal}
              />
            ) : (
              <div className="bd-blank">
                {boardError ? (
                  <>
                    <p>Não deu para abrir o quadro: {boardError}</p>
                    {path && (
                      <button type="button" className="btn" onClick={() => void loadBoard(path, true)}>
                        Tentar de novo
                      </button>
                    )}
                  </>
                ) : path ? (
                  <p>Abrindo o quadro…</p>
                ) : (
                  <p>Escolha um quadro na lista.</p>
                )}
              </div>
            )}
          </div>
          <footer className="bd-foot">
            <span className="mono">
              {info ? `${info.nome}.canvas` : "—"} · {count} {count === 1 ? "item" : "itens"} · {linked} {linked === 1 ? "precedente ligado" : "precedentes ligados"}
            </span>
            <span className="bd-foot-hint">arraste uma nota do Brain para cima de uma sessão para ligar</span>
          </footer>
        </section>
      )}
    </div>
  );
}
