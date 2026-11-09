// Automações (v0.9.0): o que a tela sabe do desenho. Tudo aqui é puro (sem React): a forma de
// cada passo no canvas, os "elementos" dos conectores, nomes e ids únicos, datas e durações.

import { ICON } from "../../icons";
import { KIND_COLOR } from "../../lib/format";
import type { AutoCatalog, AutoEdge, AutoFlow, AutoRunStatus, AutoStep, AutoStepRun, AutoStepStatus, AutoStepType, AutoTrigger } from "../../types";

export const TRIGGER = "gatilho";

/** Lado do bloco quadrado; o agente é um bloco largo com modelo, ferramentas e saída pendurados embaixo. */
export const S = 84;
export const AW = 240;
export const GAP = 130;
export const OFF = 3000;

export type Kind = "gatilho" | AutoStepType;
export type Ramo = "sim" | "não";
export type Tool = AutoCatalog["ferramentas"][number];
export type GalleryAgent = AutoCatalog["agentes"][number];
export type Change = (flow: AutoFlow) => AutoFlow;

/** Onde a gaveta põe o passo novo: depois de um passo (num ramo), no meio de uma ligação, ou solto. */
export interface AddCtx {
  after?: string;
  ramo?: Ramo;
  between?: AutoEdge;
  trigger?: boolean;
}

export const P = {
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
  diamond: "M12 3l9 9-9 9-9-9z",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4",
  hourglass: "M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9s8 4 8 9",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M5 11h14v10H5z",
  play: "M7 4l13 8-13 8z",
  stop: "M6 6h12v12H6z",
  fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  power: "M12 3v8M7.5 6.5a7 7 0 1 0 9 0",
  pin: "M9 3h6l-1 6 4 4H6l4-4zM12 13v8",
  sticky: "M5 4h14v11l-5 5H5zM14 20v-5h5",
  back: "M15 6l-6 6 6 6",
  rerun: "M4 12a8 8 0 1 0 2.3-5.6M4 4v4h4",
  copy: "M8 8h11v11H8zM5 16V5h11",
};

export const KIND: Record<Kind, { label: string; color: string; icon: string | null; hint: string }> = {
  gatilho: { label: "Gatilho", color: "var(--wait)", icon: P.clock, hint: "na mão ou agendado, com a regra para o Mac dormindo" },
  ferramenta: { label: "Ferramenta", color: "var(--run)", icon: ICON.plug, hint: "uma ferramenta da central de MCP, sem gastar cota" },
  agente: { label: "Agente", color: KIND_COLOR.claude, icon: null, hint: "Claude ou Codex num terminal da MÊTIS, pelo seu plano" },
  condicao: { label: "Condição", color: "var(--acct)", icon: P.diamond, hint: "regra de uma linha; segue pelo sim ou pelo não" },
  aprovacao: { label: "Aprovação", color: "var(--warn)", icon: P.shield, hint: "pausa até você aprovar no cartão da MÊTIS" },
  brain: { label: "Brain", color: "var(--g-brain)", icon: ICON.graph, hint: "buscar, ler, precedentes, tarefas ou linha no diário" },
  esperar: { label: "Esperar", color: "var(--fnt)", icon: P.hourglass, hint: "um tempo antes de seguir (no teste, 3 s)" },
  codigo: { label: "Código", color: "var(--mut)", icon: P.code, hint: "Python ou JavaScript local; o Claude escreve a partir da descrição" },
};

/** Lógica e dados, na ordem da gaveta. */
export const LOGIC: AutoStepType[] = ["condicao", "aprovacao", "esperar", "codigo", "brain"];

export const STEP_LABEL: Record<AutoStepStatus, string> = {
  rodando: "rodando",
  ok: "ok",
  erro: "erro",
  esperando: "esperando você",
  pulado: "pulado",
  recusado: "recusado",
};

export const RUN_LABEL: Record<AutoRunStatus, string> = {
  rodando: "rodando",
  ok: "ok",
  erro: "erro",
  recusada: "recusada",
  cancelada: "parada",
  pulada: "pulada",
  interrompida: "interrompida",
};

export const BRAIN_LABEL: Record<NonNullable<AutoStep["acao"]>, string> = {
  buscar: "buscar notas",
  ler: "ler uma nota",
  precedentes: "precedentes",
  tarefas: "tarefas do kanban",
  diario: "linha no diário",
};

export const DAY_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];

// --- texto ------------------------------------------------------------------------------------

export const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
export const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));
export const capital = (text: string) => text.replace(/^./, (c) => c.toUpperCase());

export function slug(text: string): string {
  return fold(text).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/-+$/, "");
}

export function daysLabel(days: number[] | undefined): string {
  const list = [...(days ?? [])].sort((a, b) => a - b);
  const key = list.join(",");
  if (list.length === 7) return "todo dia";
  if (key === "0,1,2,3,4") return "seg a sex";
  if (key === "0,1,2,3,4,5") return "seg a sáb";
  if (key === "5,6") return "fim de semana";
  if (!list.length) return "sem dias";
  return list.map((d) => DAY_SHORT[d]).join(", ");
}

export function triggerTitle(t: AutoTrigger): string {
  return t.tipo === "agendado" ? capital(`${daysLabel(t.dias)}, ${t.hora || "--:--"}`) : "Na mão";
}

export const EVENT_LABEL: Record<string, string> = {
  "brain.nota": "nota nova no Brain",
  "tarefa.moveu": "tarefa mudou de coluna",
  "agente.terminou": "agente terminou",
  "agente.errou": "agente saiu com erro",
  "worktree.criada": "worktree criada",
  captura: "captura rápida",
};

export function triggerWhen(t: AutoTrigger | undefined): string {
  if (!t) return "";
  if (t.tipo === "agendado") return `${daysLabel(t.dias)} · ${t.hora || "--:--"}`;
  if (t.tipo === "evento") return t.evento ? EVENT_LABEL[t.evento] ?? t.evento : "evento";
  if (t.tipo === "sondagem") return `a cada ${t.cada_min ?? 15} min`;
  return "na mão";
}

// --- conectores como "elementos" -------------------------------------------------------------

export interface Elem {
  mono: string;
  color: string;
  /** Ferramenta da própria MÊTIS: usa a marca, não letras. */
  metis?: boolean;
}

const KNOWN: Record<string, Elem> = {
  slack: { mono: "Sl", color: "var(--g-pessoal)" },
  clickup: { mono: "Cu", color: "var(--g-clientes)" },
  pipedrive: { mono: "Pd", color: "var(--g-carreira)" },
  supabase: { mono: "Sb", color: "var(--g-brain)" },
  github: { mono: "Gh", color: "var(--mut)" },
  n8n: { mono: "n8", color: "var(--warn)" },
  brain: { mono: "Br", color: "var(--g-brain)" },
};

const METIS: Elem = { mono: "", color: "var(--acc)", metis: true };

/** Conta de conector (id "slack-pessoal", "clickup-seller-pro", "brain" ou "" para a MÊTIS) → elemento. */
export function accountElem(account: string): Elem {
  if (!account) return METIS;
  const kind = account.split("-")[0].toLowerCase();
  if (KNOWN[kind]) return KNOWN[kind];
  const letters = kind.replace(/[^a-z0-9]/g, "");
  return { mono: capital(letters.slice(0, 2)) || "?", color: "var(--g-trabalho)" };
}

export const toolAccount = (name: string) => (name.includes("__") ? name.split("__")[0] : "");

export function toolElem(name: string): Elem {
  if (name.startsWith("brain_")) return KNOWN.brain;
  return accountElem(toolAccount(name));
}

const BUILTIN_TITLE: Record<string, string> = {
  brain_buscar: "Buscar no Brain",
  brain_ler: "Ler uma nota",
  brain_precedentes: "Precedentes",
  brain_conflitos: "Conflitos com decisões",
  brain_sugestoes: "Sugestões de precedente",
  tarefas: "Tarefas do kanban",
  tarefa_mover: "Mover uma tarefa",
  tarefa_nova: "Nova tarefa",
  lembrete: "Lembrete no Slack",
};

/** "slack-pessoal__mensagem_para_mim" → "mensagem_para_mim". */
export const toolShort = (name: string) => (name.includes("__") ? name.split("__").slice(1).join("__") : name);

/** Nome de gente para a ferramenta: "Mensagem para mim". */
export function toolTitle(name: string): string {
  if (BUILTIN_TITLE[name]) return BUILTIN_TITLE[name];
  return capital(toolShort(name).replace(/[_-]+/g, " ").trim()) || name;
}

/** A descrição sem o "[Conta] " do começo (a conta já aparece no grupo). */
export const toolDescription = (tool: Tool) => tool.descricao.replace(/^\[[^\]]*\]\s*/, "");

/** Grupo da gaveta: conta de conector, o Brain ou a própria MÊTIS. */
export function toolGroup(tool: Tool): { key: string; name: string; elem: Elem } {
  if (tool.conta) return { key: tool.conta, name: tool.conta_nome || tool.conta, elem: accountElem(tool.conta) };
  if (tool.nome.startsWith("brain_")) return { key: "brain", name: "Brain", elem: KNOWN.brain };
  return { key: "metis", name: "MÊTIS", elem: METIS };
}

// --- o desenho como blocos -----------------------------------------------------------------------

export interface CNode {
  id: string;
  kind: Kind;
  title: string;
  x: number;
  y: number;
  step: AutoStep | null;
}

export const nodeW = (kind: Kind) => (kind === "agente" ? AW : S);

/** Camadas pelo caminho mais longo a partir do gatilho (a mesma regra do motor). */
export function depthOf(flow: AutoFlow): Map<string, number> {
  const depth = new Map<string, number>([[TRIGGER, 0]]);
  for (let round = 0, changed = true; changed && round <= flow.passos.length + 1; round++) {
    changed = false;
    for (const e of flow.ligacoes) {
      const from = depth.get(e.de);
      if (from !== undefined && (depth.get(e.para) ?? -1) < from + 1) {
        depth.set(e.para, from + 1);
        changed = true;
      }
    }
  }
  return depth;
}

/** Blocos do canvas. Passo sem posição (YAML editado à mão) ganha uma pela camada. */
export function nodesOf(flow: AutoFlow): CNode[] {
  const depth = depthOf(flow);
  const perLayer = new Map<number, number>();
  const nodes: CNode[] = [
    { id: TRIGGER, kind: "gatilho", title: triggerTitle(flow.gatilho), x: flow.gatilho.x ?? 0, y: flow.gatilho.y ?? 0, step: null },
  ];
  for (const step of flow.passos) {
    let { x, y } = step;
    if (x === undefined || y === undefined) {
      const layer = depth.get(step.id) ?? 1;
      const index = perLayer.get(layer) ?? 0;
      perLayer.set(layer, index + 1);
      x ??= layer * (S + GAP);
      y ??= index * 160;
    }
    nodes.push({ id: step.id, kind: step.tipo, title: step.titulo, x, y, step });
  }
  return nodes;
}

export function moveNode(flow: AutoFlow, id: string, x: number, y: number): AutoFlow {
  if (id === TRIGGER) return { ...flow, gatilho: { ...flow.gatilho, x, y } };
  return { ...flow, passos: flow.passos.map((s) => (s.id === id ? { ...s, x, y } : s)) };
}

export function collides(nodes: CNode[], x: number, y: number) {
  return nodes.some((n) => Math.abs(n.x - x) < 170 && Math.abs(n.y - y) < S + 60);
}

/** Linha embaixo do nome do passo. */
export function stepSub(step: AutoStep): string {
  switch (step.tipo) {
    case "ferramenta":
      return step.ferramenta ? toolShort(step.ferramenta) : "escolha a ferramenta";
    case "agente":
      return `${step.cli ?? "claude"} · ${step.modelo || "padrão"}`;
    case "condicao":
      return step.regra?.trim() || "sem regra ainda";
    case "aprovacao":
      return `responder em até ${step.prazo_min ?? 60} min`;
    case "brain":
      return step.acao ? BRAIN_LABEL[step.acao] : "escolha a ação";
    case "esperar":
      return `${step.minutos ?? 1} min`;
    case "codigo":
      return `${step.linguagem === "javascript" ? "JavaScript" : "Python"}${step.codigo?.trim() ? "" : " · sem código ainda"}`;
  }
}

/** Saídas de um bloco: a condição tem duas (sim e não). */
export const outputsOf = (kind: Kind): (Ramo | undefined)[] => (kind === "condicao" ? ["sim", "não"] : [undefined]);

/** "para" chega em "de" andando pelas ligações? (aí a ligação nova fecharia um ciclo) */
export function reaches(flow: AutoFlow, from: string, to: string): boolean {
  const seen = new Set<string>();
  const todo = [from];
  while (todo.length) {
    const id = todo.pop()!;
    if (id === to) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    for (const e of flow.ligacoes) if (e.de === id) todo.push(e.para);
  }
  return false;
}

/** Passos que vêm antes (para as expressões disponíveis no painel). */
export function upstream(flow: AutoFlow, id: string): string[] {
  const out: string[] = [];
  const todo = [id];
  while (todo.length) {
    const cur = todo.pop()!;
    for (const e of flow.ligacoes)
      if (e.para === cur && !out.includes(e.de)) {
        out.push(e.de);
        todo.push(e.de);
      }
  }
  return out;
}

// --- nomes e ids únicos -------------------------------------------------------------------------------

/** O motor recusa dois passos com o mesmo nome (as expressões usam o nome). */
export function titleTaken(flow: AutoFlow, title: string, exceptId?: string): boolean {
  const key = fold(title);
  return key === TRIGGER || flow.passos.some((s) => s.id !== exceptId && fold(s.titulo) === key);
}

export function uniqueTitle(flow: AutoFlow, base: string): string {
  const clean = base.trim() || "Passo";
  if (!titleTaken(flow, clean)) return clean;
  for (let n = 2; ; n++) if (!titleTaken(flow, `${clean} ${n}`)) return `${clean} ${n}`;
}

/** Id do passo: minúsculas, números e hífen, único, nunca "gatilho". Não muda depois de criado. */
export function uniqueId(flow: AutoFlow, title: string): string {
  let base = slug(title) || "passo";
  if (!/^[a-z0-9]/.test(base)) base = `p-${base}`;
  const taken = new Set([TRIGGER, ...flow.passos.map((s) => s.id)]);
  if (!taken.has(base)) return base;
  for (let n = 2; ; n++) if (!taken.has(`${base}-${n}`)) return `${base}-${n}`;
}

const escapeRe = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Trocou o nome do passo: as expressões {{Nome antigo…}} dos outros passos passam a usar o novo. */
export function renameRefs<T>(value: T, from: string, to: string): T {
  const re = new RegExp(`\\{\\{(\\s*)${escapeRe(from.trim())}(?=\\s*(?:\\.|\\[|\\}\\}))`, "gi");
  const walk = (v: unknown): unknown => {
    if (typeof v === "string") return v.replace(re, (_m, space: string) => `{{${space}${to}`);
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x)]));
    return v;
  };
  return walk(value) as T;
}

// --- execuções ------------------------------------------------------------------------------------------

export const itemsLabel = (n: number) => `${n} ${n === 1 ? "item" : "itens"}`;

export function countItems(v: unknown): number {
  if (v === undefined || v === null) return 0;
  return Array.isArray(v) ? v.length : 1;
}

export const itemsOf = (r: AutoStepRun) => r.itens ?? countItems(r.saida);

/** Epoch em segundos → "hoje 08:30", "ontem 20:50", "sex 06/11 08:30". */
export function when(epoch: number | null | undefined): string {
  if (!epoch) return "";
  const date = new Date(epoch * 1000);
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86400000);
  if (date.toDateString() === today.toDateString()) return `hoje ${time}`;
  if (date.toDateString() === yesterday.toDateString()) return `ontem ${time}`;
  const day = date.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" }).replace(".", "").replace(",", "");
  return `${day} ${time}`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return "";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0).replace(".", ",")} s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min ${String(Math.round(seconds % 60)).padStart(2, "0")} s`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

export const span = (started: number | null, ended: number | null) => (started && ended ? duration(ended - started) : "");

export const isPlain = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** Deixa o objeto sem as chaves vazias (o YAML fica limpo). */
export function compact<T extends object>(value: T): T {
  return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined)) as T;
}
