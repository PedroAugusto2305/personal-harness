// Automações (v0.9.0): o "n8n da MÊTIS". Lista à esquerda, barra com nome, estado e versão, abas
// Editor e Execuções, o canvas no meio e o painel do passo por cima. Tudo fala com o núcleo: o
// canvas edita o RASCUNHO (salvo sozinho, ~600 ms depois da última mudança), "Testar" roda o
// rascunho em ensaio, e só a versão publicada roda de verdade.

import { useEffect, useRef, useState } from "react";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { shortPath } from "../lib/format";
import type { Agent, AutoCatalog, AutoDetail, AutoEdge, AutoFlow, AutoRun, AutoRunStatus, AutoRunSummary, AutoSummary, AutoTrigger, CoreEvent } from "../types";
import "./automations.css";
import { Canvas, type CanvasApi } from "./automations/Canvas";
import { Drawer, type StepDraft } from "./automations/Drawer";
import {
  type AddCtx,
  type Change,
  type Ramo,
  GAP,
  P,
  RUN_LABEL,
  S,
  TRIGGER,
  accountElem,
  collides,
  compact,
  duration,
  message,
  nodeW,
  nodesOf,
  reaches,
  renameRefs,
  titleTaken,
  triggerWhen,
  uniqueId,
  uniqueTitle,
  when,
} from "./automations/model";
import { type DataMode, ElemMark } from "./automations/parts";
import { StepPanel } from "./automations/StepPanel";

type AutomationEvent = Extract<CoreEvent, { type: `automation.${string}` }>;

interface Props {
  client: CoreClient | null;
  agents: Agent[];
  tick: number;
  event: AutomationEvent | null;
  onOpenSession: (id: string) => void;
  onToast: (message: string) => void;
}

type SaveState = "salvo" | "pendente" | "salvando" | "erro";

const edgeOf = (de: string, para: string, ramo?: Ramo): AutoEdge => (ramo ? { de, para, ramo } : { de, para });

/** O núcleo sempre devolve as listas, mas um YAML editado à mão pode vir sem alguma. */
function normalize(flow: AutoFlow): AutoFlow {
  return {
    nome: flow.nome ?? "",
    descricao: flow.descricao ?? "",
    gatilho: flow.gatilho ?? { tipo: "manual" },
    passos: flow.passos ?? [],
    ligacoes: flow.ligacoes ?? [],
    notas: flow.notas ?? [],
  };
}

/** Como o teste terminou, em frase (o rótulo da execução é feminino; o do teste, masculino). */
const TEST_END: Record<AutoRunStatus, string> = {
  rodando: "Testando…",
  ok: "Teste concluído",
  erro: "O teste deu erro",
  recusada: "O teste parou numa aprovação recusada",
  cancelada: "Teste parado por você",
  pulada: "Teste pulado",
  interrompida: "Teste interrompido",
};

const stateOf = (a: AutoSummary) => (a.erro ? "erro" : a.ativa ? "ativa" : a.publicada == null ? "rascunho" : "pausada");

/** Primeiro ramo livre de uma condição (sim, depois não). */
const freeBranch = (flow: AutoFlow, id: string): Ramo => (flow.ligacoes.some((e) => e.de === id && e.ramo === "sim") ? "não" : "sim");

export function AutomationsView({ client, agents, tick, event, onOpenSession, onToast }: Props) {
  const [list, setList] = useState<AutoSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AutoDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [draft, setDraft] = useState<AutoFlow | null>(null);
  const [loads, setLoads] = useState(0);
  const [save, setSave] = useState<{ state: SaveState; error?: string }>({ state: "salvo" });
  const [catalog, setCatalog] = useState<AutoCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [mode, setMode] = useState<"editor" | "runs">("editor");
  const [runs, setRuns] = useState<AutoRunSummary[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [liveId, setLiveId] = useState<number | null>(null);
  const [latestId, setLatestId] = useState<number | null>(null);
  const [runCache, setRunCache] = useState<Record<number, AutoRun>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [panelId, setPanelId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<AddCtx | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);
  const [dataView, setDataView] = useState<DataMode>("tabela");
  const [creating, setCreating] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"archive" | "copy" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [name, setName] = useState("");

  const canvasApi = useRef<CanvasApi | null>(null);
  const draftRef = useRef<AutoFlow | null>(null);
  const currentRef = useRef<string | null>(null);
  currentRef.current = currentId;
  // Salvar: cada mudança sobe a versão local; o que foi salvo de verdade fica em `saved`.
  const version = useRef(0);
  const saved = useRef(0);
  const saveTimer = useRef<number | null>(null);
  const saving = useRef<Promise<boolean> | null>(null);
  const lastError = useRef("");
  const watch = useRef({ liveId, runId, latestId });
  watch.current = { liveId, runId, latestId };
  const timers = useRef<Record<string, number>>({});
  const seenTick = useRef(tick);
  const infoRef = useRef(false);
  infoRef.current = infoOpen;

  const later = (key: string, ms: number, job: () => void) => {
    if (timers.current[key]) return;
    timers.current[key] = window.setTimeout(() => {
      delete timers.current[key];
      job();
    }, ms);
  };
  useEffect(
    () => () => {
      Object.values(timers.current).forEach((t) => window.clearTimeout(t));
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    },
    [],
  );

  // --- leitura ------------------------------------------------------------------------------------

  const applySummary = (s: AutoSummary) => {
    setList((all) => (all ? all.map((a) => (a.id === s.id ? { ...a, ...s } : a)) : all));
    setDetail((d) => (d && d.id === s.id ? { ...d, ...s } : d));
  };

  /** mtime do rascunho que esta tela conhece: se o arquivo mudar por fora (Pedir conserto, edição à mão), relê. */
  const knownMtime = useRef<Record<string, number>>({});

  const loadList = async () => {
    if (!client) return;
    try {
      const items = await client.automations();
      setList(items);
      setListError(null);
      if (!currentRef.current && items.length) setCurrentId(items[0].id);
    } catch (cause) {
      setListError(message(cause));
    }
  };

  const loadCatalog = async () => {
    if (!client) return;
    try {
      setCatalog(await client.automationCatalog());
      setCatalogError(null);
    } catch (cause) {
      setCatalogError(message(cause));
    }
  };

  const loadDetail = async (id: string, keepDraft: boolean) => {
    if (!client) return;
    try {
      const d = await client.automation(id);
      if (currentRef.current !== id) return;
      if (!keepDraft) knownMtime.current[id] = d.alterado ?? 0;
      setDetail(d);
      setDetailError(null);
      if (!keepDraft) {
        const flow = normalize(d.rascunho);
        draftRef.current = flow;
        setDraft(flow);
        version.current = saved.current = 0;
        setSave({ state: "salvo" });
        setLoads((n) => n + 1);
      }
    } catch (cause) {
      if (currentRef.current !== id) return;
      if (keepDraft) onToast(message(cause));
      else {
        setDetail(null);
        setDraft(null);
        draftRef.current = null;
        setDetailError(message(cause));
      }
    }
  };

  const loadRuns = async (id: string) => {
    if (!client) return;
    try {
      const items = await client.automationRuns(id);
      if (currentRef.current === id) setRuns(items);
    } catch (cause) {
      if (currentRef.current === id) onToast(message(cause));
    }
  };

  const loadRun = async (id: number) => {
    if (!client) return;
    try {
      const run = await client.automationRun(id);
      setRunCache((all) => ({ ...all, [id]: { ...run, flow: normalize(run.flow), steps: run.steps ?? {} } }));
    } catch (cause) {
      onToast(message(cause));
    }
  };

  useEffect(() => {
    void loadList();
    void loadCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    setDraft(null);
    draftRef.current = null;
    setRuns([]);
    setRunId(null);
    setLiveId(null);
    setLatestId(null);
    setSelectedId(null);
    setPanelId(null);
    setDrawer(null);
    setInfoOpen(false);
    setConfirm(null);
    setMode("editor");
    if (!currentId) return;
    void loadDetail(currentId, false);
    void loadRuns(currentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId, client]);

  // O núcleo avisa a cada passo e a cada execução: busca de novo só o que está na tela.
  useEffect(() => {
    if (tick === seenTick.current) return;
    seenTick.current = tick;
    if (!event || !client) return;
    if (event.type === "automation.run" || event.type === "automation.step") {
      const w = watch.current;
      if (event.run === w.liveId || event.run === w.runId || event.run === w.latestId) later(`run:${event.run}`, 120, () => void loadRun(event.run));
    }
    if (event.type === "automation.run") {
      later("list", 300, () => void loadList());
      if (event.automation === currentRef.current) later("runs", 300, () => void loadRuns(event.automation));
      // Erro já aparece na faixa vermelha do canvas, com Pedir conserto: o aviso no canto não repete.
      // O fim do teste já aparece na faixa do canvas; o aviso no canto só traz a dica do teste que deu certo.
      if (event.run === watch.current.liveId && event.status === "ok") {
        onToast("Teste concluído. Dois cliques num passo mostram o que entrou e o que saiu.");
      }
    } else if (event.type === "automation.published") {
      later("list", 300, () => void loadList());
      if (event.automation === currentRef.current) void loadDetail(event.automation, true);
    } else if (event.type === "automation.error") {
      onToast(`Automação ${event.automation}: ${event.error}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  // A cada 5 s com a tela à vista: a lista (estado e última execução) e o rascunho mudado por fora.
  useEffect(() => {
    if (!client) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadList();
    }, 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);
  useEffect(() => {
    const item = list?.find((a) => a.id === currentId);
    const known = currentId ? knownMtime.current[currentId] : undefined;
    if (!currentId || !item?.alterado || !known || item.alterado <= known + 0.001 || save.state !== "salvo") return;
    knownMtime.current[currentId] = item.alterado;
    void loadDetail(currentId, false);
    onToast("O rascunho mudou fora da tela (Pedir conserto ou edição no arquivo): recarreguei.");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list]);

  // Em Execuções, abre a mais recente; no editor, o painel usa a última com dados se não houver teste.
  useEffect(() => {
    if (mode === "runs" && runId === null && runs.length) setRunId(runs[0].id);
  }, [mode, runId, runs]);
  useEffect(() => {
    if (runId !== null && !runCache[runId]) void loadRun(runId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);
  useEffect(() => {
    if (mode !== "editor" || !panelId || liveId !== null || !runs.length) return;
    const latest = runs.find((r) => r.status !== "rodando") ?? runs[0];
    setLatestId(latest.id);
    if (!runCache[latest.id]) void loadRun(latest.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, panelId, liveId, runs]);

  useEffect(() => {
    if (draft && document.activeElement?.classList.contains("af-name-input") !== true) setName(draft.nome);
  }, [draft]);

  // --- salvar o rascunho --------------------------------------------------------------------------------

  const runSave = async (id: string, flow: AutoFlow, v: number): Promise<boolean> => {
    if (!client) return false;
    // Um salvamento por vez; quem esperava confere se o que ele ia mandar já foi.
    while (saving.current) await saving.current;
    if (saved.current >= v && currentRef.current === id) return true;
    const job = (async () => {
      if (currentRef.current === id) setSave({ state: "salvando" });
      try {
        const summary = await client.saveAutomation(id, flow);
        knownMtime.current[id] = summary.alterado ?? knownMtime.current[id] ?? 0;
        applySummary(summary);
        if (currentRef.current === id) {
          saved.current = Math.max(saved.current, v);
          if (saved.current >= version.current) setSave({ state: "salvo" });
        }
        lastError.current = "";
        if (infoRef.current && currentRef.current === id) void loadDetail(id, true);
        return true;
      } catch (cause) {
        lastError.current = message(cause);
        if (currentRef.current === id) setSave({ state: "erro", error: lastError.current });
        return false;
      }
    })();
    saving.current = job;
    const ok = await job;
    if (saving.current === job) saving.current = null;
    return ok;
  };

  /** Toda mudança no canvas ou no painel passa por aqui: muda na tela já e salva ~600 ms depois. */
  const edit = (change: Change) => {
    const base = draftRef.current;
    const id = currentRef.current;
    if (!base || !id) return;
    const next = change(base);
    if (next === base) return;
    draftRef.current = next;
    setDraft(next);
    version.current += 1;
    const v = version.current;
    setSave({ state: "pendente" });
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      void runSave(id, next, v);
    }, 600);
  };

  /** Salva já o que estiver pendente. false = o núcleo recusou o desenho (o erro está em lastError). */
  const flush = async (): Promise<boolean> => {
    const id = currentRef.current;
    const flow = draftRef.current;
    if (saveTimer.current) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    if (!id || !flow) return true;
    if (saved.current >= version.current) {
      if (saving.current) return saving.current;
      return true;
    }
    return runSave(id, flow, version.current);
  };

  /** Antes de testar ou publicar: o núcleo roda o rascunho SALVO. */
  const ready = async () => {
    const ok = await flush();
    if (!ok) onToast(`O rascunho não salvou: ${lastError.current}. Corrija antes; o núcleo usa o rascunho salvo.`);
    return ok;
  };

  // --- automação ------------------------------------------------------------------------------------

  const choose = async (id: string) => {
    if (id === currentId) {
      // Clicar na que já está aberta relê o arquivo (por exemplo, depois de um Pedir conserto).
      if (await flush()) void loadDetail(id, false);
      return;
    }
    const before = draftRef.current?.nome;
    if (!(await flush()) && before) onToast(`As últimas mudanças em «${before}» não foram salvas: ${lastError.current}`);
    version.current = saved.current = 0;
    setSave({ state: "salvo" });
    setCurrentId(id);
  };

  const create = async () => {
    const nome = creating?.trim();
    if (!client || !nome) return;
    setBusy("criar");
    try {
      const summary = await client.createAutomation(nome);
      setList((all) => [...(all ?? []), summary]);
      setCreating(null);
      await choose(summary.id);
    } catch (cause) {
      onToast(message(cause));
    } finally {
      setBusy(null);
    }
  };

  const act = async (label: string, job: () => Promise<void>) => {
    setBusy(label);
    try {
      await job();
    } catch (cause) {
      onToast(message(cause));
    } finally {
      setBusy(null);
    }
  };

  const publish = (versao?: { hash: string; number: number }) =>
    act("publicar", async () => {
      if (!client || !currentId || !(await ready())) return;
      const summary = await client.publishAutomation(currentId, versao?.hash ?? "");
      applySummary(summary);
      void loadDetail(currentId, true);
      onToast(
        versao
          ? `A v${versao.number} voltou ao ar como v${summary.publicada}.`
          : `v${summary.publicada} publicada. É ela que roda; mudanças no rascunho só valem quando você publicar de novo.`,
      );
    });

  const toggleActive = () =>
    act("ativa", async () => {
      if (!client || !currentId || !detail) return;
      const summary = await client.setAutomationActive(currentId, !detail.ativa);
      applySummary(summary);
      onToast(summary.ativa ? `Ativa: roda sozinha (${triggerWhen(summary.gatilho)}), sempre a v${summary.publicada}.` : "Pausada: não roda sozinha até você ativar de novo.");
    });

  const archive = () =>
    act("arquivar", async () => {
      if (!client || !currentId) return;
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
      version.current = saved.current = 0;
      const nome = draftRef.current?.nome ?? currentId;
      await client.archiveAutomation(currentId);
      const rest = (list ?? []).filter((a) => a.id !== currentId);
      setList(rest);
      setConfirm(null);
      setCurrentId(rest[0]?.id ?? null);
      onToast(`«${nome}» saiu da lista. Os arquivos ficam em arquivadas/, no histórico.`);
    });

  const testAll = () =>
    act("testar", async () => {
      if (!client || !currentId || !(await ready())) return;
      const { execucao } = await client.testAutomation(currentId);
      setMode("editor");
      setPanelId(null);
      setLiveId(execucao);
      void loadRun(execucao);
    });

  const testStep = (stepId: string) =>
    act("testar", async () => {
      if (!client || !currentId || !(await ready())) return;
      const base = mode === "editor" ? (liveId ?? latestId) : runId;
      const { execucao } = await client.testAutomation(currentId, { passo: stepId, execucao: base ?? undefined });
      setMode("editor");
      setLiveId(execucao);
      void loadRun(execucao);
      const title = draftRef.current?.passos.find((s) => s.id === stepId)?.titulo ?? stepId;
      onToast(`Testando «${title}» sozinho, com as entradas guardadas da última execução.`);
    });

  const rerun = (base: AutoRun, stepId: string) =>
    act("reexecutar", async () => {
      if (!client || !currentId) return;
      if (base.mode === "teste" && !(await ready())) return;
      const { execucao } = await client.rerunFrom(base.id, stepId);
      if (mode === "runs") {
        setRunId(execucao);
        void loadRuns(currentId);
      } else setLiveId(execucao);
      void loadRun(execucao);
    });

  const stop = (id: number) =>
    act("parar", async () => {
      if (!client) return;
      await client.stopRun(id);
      void loadRun(id);
    });

  const askFix = (id: number) =>
    act("conserto", async () => {
      if (!client) return;
      const { session, title } = await client.askFix(id);
      onOpenSession(session);
      onToast(`${title}: o Claude abriu com o arquivo e o log. A correção vai só para o rascunho; depois, clique na automação para reler.`);
    });

  const runPublished = () =>
    act("rodar", async () => {
      if (!client || !currentId) return;
      const { execucao } = await client.runAutomation(currentId);
      setMode("runs");
      setPanelId(null);
      setRunId(execucao);
      void loadRun(execucao);
      void loadRuns(currentId);
      onToast(`Rodando a v${detail?.publicada} de verdade. Acompanhe em Execuções.`);
    });

  const copyToEditor = (run: AutoRun) =>
    act("copiar", async () => {
      if (!client || !currentId) return;
      const flow = normalize(run.flow);
      const summary = await client.saveAutomation(currentId, flow);
      knownMtime.current[currentId] = summary.alterado ?? 0;
      applySummary(summary);
      draftRef.current = flow;
      setDraft(flow);
      version.current = saved.current = 0;
      setSave({ state: "salvo" });
      setConfirm(null);
      setMode("editor");
      setLiveId(null);
      setLoads((n) => n + 1);
      onToast(`O desenho da execução #${run.id} virou o rascunho. Teste e publique quando quiser.`);
    });

  // --- editar o desenho -------------------------------------------------------------------------------

  const rename = (id: string, title: string): string | null => {
    const f = draftRef.current;
    const step = f?.passos.find((s) => s.id === id);
    const clean = title.trim();
    if (!f || !step) return null;
    if (!clean) return "O passo precisa de um nome.";
    if (titleTaken(f, clean, id)) return `Já existe um passo «${clean}». As expressões usam o nome, então ele precisa ser único.`;
    if (clean === step.titulo) return null;
    edit((flow) => ({
      ...flow,
      passos: flow.passos.map((s) => (s.id === id ? { ...renameRefs(s, step.titulo, clean), titulo: clean } : renameRefs(s, step.titulo, clean))),
    }));
    return null;
  };

  const removeStep = (id: string) => {
    if (id === TRIGGER) return;
    edit((f) => ({ ...f, passos: f.passos.filter((s) => s.id !== id), ligacoes: f.ligacoes.filter((e) => e.de !== id && e.para !== id) }));
    setSelectedId(null);
    setPanelId(null);
  };

  const toggleOff = (id: string) =>
    edit((f) => ({ ...f, passos: f.passos.map((s) => (s.id === id ? compact({ ...s, desligado: s.desligado ? undefined : true }) : s)) }));

  const link = (de: string, para: string, ramo?: Ramo) => {
    const f = draftRef.current;
    if (!f) return;
    if (para === TRIGGER) return onToast("O gatilho é o começo: nada liga nele.");
    const fromKind = de === TRIGGER ? "gatilho" : f.passos.find((s) => s.id === de)?.tipo;
    const r = fromKind === "condicao" ? (ramo ?? freeBranch(f, de)) : undefined;
    if (f.ligacoes.some((e) => e.de === de && e.para === para && e.ramo === r)) return;
    if (reaches(f, para, de)) return onToast("Essa ligação fecharia um ciclo; a automação anda sempre para a frente.");
    edit((flow) => ({ ...flow, ligacoes: [...flow.ligacoes, edgeOf(de, para, r)] }));
  };

  const addStep = (d: StepDraft) => {
    const base = draftRef.current;
    if (!base) return;
    const ctx = drawer ?? {};
    const titulo = uniqueTitle(base, d.titulo);
    const id = uniqueId(base, titulo);
    const nodes = nodesOf(base);
    const w = nodeW(d.tipo);
    const center = canvasApi.current?.center() ?? { x: 200, y: 200 };
    edit((f) => {
      let passos = f.passos;
      let ligacoes = f.ligacoes;
      let x = Math.round(center.x - w / 2);
      let y = Math.round(center.y - S / 2);
      const between = ctx.between;
      const after = ctx.after ? nodes.find((n) => n.id === ctx.after) : undefined;
      if (between) {
        const a = nodes.find((n) => n.id === between.de);
        const b = nodes.find((n) => n.id === between.para);
        if (a && b) {
          const shift = w + GAP;
          x = b.x;
          y = Math.round(a.kind === "condicao" ? b.y : (a.y + b.y) / 2);
          passos = passos.map((s) => {
            const n = nodes.find((m) => m.id === s.id);
            return n && n.x >= b.x ? { ...s, x: n.x + shift, y: n.y } : s;
          });
          ligacoes = [
            ...ligacoes.filter((e) => !(e.de === between.de && e.para === between.para && e.ramo === between.ramo)),
            edgeOf(a.id, id, between.ramo),
            edgeOf(id, b.id, d.tipo === "condicao" ? "sim" : undefined),
          ];
        }
      } else if (after) {
        x = after.x + nodeW(after.kind) + GAP;
        y = after.y + (ctx.ramo === "sim" ? -80 : ctx.ramo === "não" ? 100 : 0);
        while (collides(nodes, x, y)) y += S + 70;
        ligacoes = [...ligacoes, edgeOf(after.id, id, after.kind === "condicao" ? (ctx.ramo ?? freeBranch(f, after.id)) : undefined)];
      } else if (collides(nodes, x, y)) {
        while (collides(nodes, x, y)) y += S + 70;
      }
      return { ...f, passos: [...passos, compact({ ...d, titulo, id, x, y })], ligacoes };
    });
    setDrawer(null);
    setSelectedId(id);
    setPanelId(id);
  };

  const setTrigger = (tipo: AutoTrigger["tipo"]) => {
    edit((f) => {
      const t = f.gatilho;
      return {
        ...f,
        gatilho: tipo === "agendado" ? { ...t, tipo, dias: t.dias?.length ? t.dias : [0, 1, 2, 3, 4], hora: t.hora || "08:00", recupera_min: t.recupera_min ?? 60 } : { ...t, tipo },
      };
    });
    setDrawer(null);
    setPanelId(TRIGGER);
  };

  const addNote = () => {
    const c = canvasApi.current?.center() ?? { x: 100, y: 100 };
    edit((f) => ({
      ...f,
      notas: [
        ...f.notas,
        {
          id: `nota-${Date.now().toString(36)}`,
          titulo: "Nota",
          texto: "Notas explicam o porquê do fluxo para você daqui a três meses. Não rodam. Dois cliques para editar.",
          x: c.x - 130,
          y: c.y - 60,
          w: 260,
        },
      ],
    }));
  };

  const openDrawer = (ctx: AddCtx) => {
    setDrawer(ctx);
    setInfoOpen(false);
    if (!catalog) void loadCatalog();
  };

  const openInfo = () => {
    setDrawer(null);
    setInfoOpen((open) => !open);
    if (currentId) void loadDetail(currentId, true);
  };

  // --- teclado: Esc fecha o que estiver por cima; Delete tira o passo escolhido ---------------------------

  const keyRef = useRef<(event: KeyboardEvent) => void>(() => undefined);
  keyRef.current = (event: KeyboardEvent) => {
    if (event.defaultPrevented) return;
    const target = event.target as HTMLElement | null;
    const typing = !!target?.closest("input, textarea, select, [contenteditable='true']");
    if (event.key === "Escape") {
      if (typing && target?.closest(".af-drawer")) return setDrawer(null);
      if (typing) return (target as HTMLElement).blur();
      if (confirm) setConfirm(null);
      else if (panelId) setPanelId(null);
      else if (drawer) setDrawer(null);
      else if (infoOpen) setInfoOpen(false);
      else setSelectedId(null);
    } else if ((event.key === "Delete" || event.key === "Backspace") && !typing && mode === "editor" && selectedId && selectedId !== TRIGGER && !panelId) {
      removeStep(selectedId);
    }
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => keyRef.current(event);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // --- o que aparece --------------------------------------------------------------------------------------

  const editing = mode === "editor";
  const liveRun = liveId !== null ? (runCache[liveId] ?? null) : null;
  const pickedRun = runId !== null ? (runCache[runId] ?? null) : null;
  const shownRun = editing ? liveRun : pickedRun;
  const panelRun = editing ? (liveRun ?? (latestId !== null ? (runCache[latestId] ?? null) : null)) : pickedRun;
  const flow = editing ? draft : (pickedRun?.flow ?? draft);
  const current = list?.find((a) => a.id === currentId) ?? null;
  const dirty = save.state !== "salvo";
  const published = detail?.publicada ?? null;
  const changed = published === null || !!detail?.mudou || dirty;
  const running = liveRun?.status === "rodando";
  const waiting = liveRun ? Object.entries(liveRun.steps).find(([, st]) => st.status === "esperando") : undefined;
  const failedStep = (run: AutoRun) => Object.entries(run.steps).find(([, st]) => st.status === "erro")?.[0];
  const titleOf = (f: AutoFlow | null, id: string) => (id === TRIGGER ? "gatilho" : (f?.passos.find((s) => s.id === id)?.titulo ?? id));
  const fitKey = editing ? `draft:${currentId}:${loads}` : `runs:${currentId}:${pickedRun ? "run" : "draft"}`;
  const runLabel = (run: AutoRun | null) =>
    !run ? "" : run.id === liveId ? "do teste de agora" : `da execução #${run.id} (${when(run.started)})`;

  if (!client) {
    return (
      <div className="af-screen">
        <p className="af-blank">Conectando ao núcleo…</p>
      </div>
    );
  }

  const createForm = (
    <form
      className="af-create"
      onSubmit={(event) => {
        event.preventDefault();
        void create();
      }}
    >
      <input
        autoFocus
        value={creating ?? ""}
        placeholder="Nome da automação"
        aria-label="Nome da automação"
        onChange={(event) => setCreating(event.target.value)}
        onKeyDown={(event) => event.key === "Escape" && setCreating(null)}
      />
      <div className="af-row">
        <button type="submit" className="btn primary" disabled={!creating?.trim() || busy === "criar"}>
          {busy === "criar" ? "Criando…" : "Criar"}
        </button>
        <button type="button" className="btn" onClick={() => setCreating(null)}>
          Cancelar
        </button>
      </div>
    </form>
  );

  const renderInfo = () => {
    if (!detail) return null;
    const lines = detail.diferenca ? detail.diferenca.split("\n") : [];
    return (
      <aside className="af-drawer" onPointerDown={(event) => event.stopPropagation()}>
        <header className="af-drawer-head">
          <div>
            <h3>{draft?.nome ?? detail.nome}</h3>
            <span className="small mono">{shortPath(detail.arquivo)}</span>
          </div>
          <button type="button" className="icon-btn" aria-label="Fechar" onClick={() => setInfoOpen(false)}>
            <Icon d={ICON.close} size={14} />
          </button>
        </header>
        <div className="af-drawer-body af-info">
          <section className="af-sec">
            <h4>O que roda</h4>
            <dl className="af-kv">
              <div>
                <dt>Publicada</dt>
                <dd>{published === null ? "nenhuma: nada roda até publicar" : `v${published}, sempre ela`}</dd>
              </div>
              <div>
                <dt>Estado</dt>
                <dd>{detail.ativa ? "ativa: roda sozinha" : published === null ? "rascunho" : "pausada"}</dd>
              </div>
              <div>
                <dt>Quando</dt>
                <dd>{triggerWhen(detail.publicada_desenho?.gatilho ?? draft?.gatilho)}</dd>
              </div>
            </dl>
          </section>
          <section className="af-sec">
            <h4>Versões</h4>
            {detail.versoes.length === 0 ? (
              <p className="af-note">Nenhuma ainda. Publicar grava a primeira.</p>
            ) : (
              <ul className="af-versions">
                {detail.versoes.map((v, i) => (
                  <li key={v.hash}>
                    <b className="mono">v{v.number}</b>
                    <span className="small">{when(v.when)}</span>
                    {i === 0 ? (
                      <span className="chip" data-state="ativa">
                        no ar
                      </span>
                    ) : (
                      <button type="button" className="btn" disabled={busy === "publicar"} onClick={() => void publish({ hash: v.hash, number: v.number })}>
                        Publicar de novo
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="af-sec">
            <h4>{published === null ? "Rascunho" : `Diferença da v${published} para o rascunho`}</h4>
            {published === null ? (
              <p className="af-note">Ainda não publicada: tudo no rascunho é novo.</p>
            ) : lines.length === 0 ? (
              <p className="af-note">O rascunho é igual à publicada.</p>
            ) : (
              <pre className="af-diff mono">
                {lines.map((line, i) => (
                  <span key={i} data-line={line.startsWith("+++") || line.startsWith("---") ? "head" : line[0] === "+" ? "add" : line[0] === "-" ? "del" : line.startsWith("@@") ? "hunk" : undefined}>
                    {line}
                    {"\n"}
                  </span>
                ))}
              </pre>
            )}
            {dirty && <p className="af-note">Há mudanças ainda salvando; a diferença atualiza em seguida.</p>}
          </section>
          <section className="af-sec">
            <h4>Arquivo</h4>
            <p className="af-note">
              YAML legível em <span className="mono">{shortPath(detail.arquivo)}</span>, com histórico num git local. Editar à mão também vale e só mexe no rascunho.
            </p>
          </section>
        </div>
      </aside>
    );
  };

  const renderList = () => (
    <aside className="af-list">
      <header className="af-list-head">
        <span className="af-caps">Automações</span>
        <button type="button" className="icon-btn" title="Nova automação" aria-label="Nova automação" onClick={() => setCreating((c) => (c === null ? "" : null))}>
          <Icon d={ICON.plus} size={15} />
        </button>
      </header>
      <div className="af-items">
        {listError && (
          <div className="af-empty-note af-list-note">
            <p>Não deu para ler a lista: {listError}</p>
            <button type="button" className="btn" onClick={() => void loadList()}>
              Tentar de novo
            </button>
          </div>
        )}
        {list === null && !listError && <p className="small af-list-note">Carregando…</p>}
        {list?.map((a) => {
          const st = stateOf(a);
          const last = a.ultima;
          return (
            <button key={a.id} type="button" className="af-item" aria-current={a.id === currentId ? "true" : undefined} onClick={() => void choose(a.id)}>
              <span className="af-item-name">{a.id === currentId && draft ? draft.nome : a.nome}</span>
              <span className="af-item-icons">
                <span className="af-mini-trigger">
                  <Icon d={P.bolt} size={10} strokeWidth={2} />
                </span>
                {a.conectores.slice(0, 4).map((c) => {
                  const elem = accountElem(c);
                  return (
                    <span key={c} className="af-mini-elem mono" title={c} style={{ color: elem.color }}>
                      {elem.metis ? <ElemMark elem={elem} size={9} /> : elem.mono}
                    </span>
                  );
                })}
                <span className="af-item-when mono">{a.erro ? "" : triggerWhen(a.gatilho)}</span>
              </span>
              <span className="af-item-meta mono">
                <span className="dot" data-state={st} />
                {st === "erro" ? "não abre" : st}
                {last && (
                  <span className="af-item-last" data-status={last.status}>
                    {" "}
                    · {when(last.started)} {last.status === "ok" ? "✓" : last.status === "erro" ? "✕" : last.status === "rodando" ? "…" : "·"}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
      <footer className="af-list-foot">
        {creating !== null ? (
          createForm
        ) : (
          <button type="button" className="btn" onClick={() => setCreating("")}>
            <Icon d={ICON.plus} size={12} strokeWidth={2.2} /> Nova automação
          </button>
        )}
      </footer>
    </aside>
  );

  if (list && list.length === 0) {
    return (
      <div className="af-screen">
        {renderList()}
        <section className="af-main af-welcome">
          <div>
            <h2>Automações</h2>
            <p>
              Passos ligados num canvas que rodam com o Mac acordado: ferramentas dos seus conectores (sem gastar cota), agentes de verdade do Claude e do Codex pelo seu plano,
              condições, aprovações e o Brain.
            </p>
            <p>Cada automação é um arquivo YAML com histórico. Você edita e testa o rascunho à vontade; o que roda é sempre a versão publicada.</p>
            {creating === null && (
              <button type="button" className="btn primary" onClick={() => setCreating("")}>
                <Icon d={ICON.plus} size={12} strokeWidth={2.2} /> Nova automação
              </button>
            )}
          </div>
        </section>
      </div>
    );
  }

  const stepCount = flow?.passos.length ?? 0;
  const doneCount = liveRun ? Object.values(liveRun.steps).filter((st) => st.status !== "rodando" && st.status !== "esperando").length : 0;

  let dock = null;
  if (editing && flow && stepCount > 0) {
    const failed = liveRun?.status === "erro" ? failedStep(liveRun) : undefined;
    dock = (
      <div className={`af-dock af-overlay${waiting ? " af-dock-waiting" : ""}`} onPointerDown={(event) => event.stopPropagation()}>
        {waiting && (
          <div className="af-waitcard">
            <span className="af-st" data-step="esperando">
              ‖
            </span>
            <span>
              <b>Esperando você</b> em «{titleOf(liveRun?.flow ?? flow, waiting[0])}». Responda no cartão de aprovação.
            </span>
            <button type="button" className="btn" onClick={() => setPanelId(waiting[0])}>
              Ver
            </button>
          </div>
        )}
        {liveRun && !running && liveRun.status !== "ok" && (
          <div className="af-runcard" data-status={liveRun.status}>
            <span className="af-run-dot" data-status={liveRun.status} />
            <span>
              <b>{TEST_END[liveRun.status]}</b>
              {liveRun.error
                ? `: ${liveRun.error}`
                : liveRun.nota && !TEST_END[liveRun.status].toLowerCase().includes(liveRun.nota.toLowerCase())
                  ? `: ${liveRun.nota}`
                  : ""}
            </span>
            {liveRun.status === "erro" && (
              <button type="button" className="btn" disabled={busy === "conserto"} onClick={() => void askFix(liveRun.id)}>
                Pedir conserto
              </button>
            )}
            {failed && (
              <button type="button" className="btn" onClick={() => void rerun(liveRun, failed)}>
                Reexecutar daqui
              </button>
            )}
            <button type="button" className="btn" onClick={() => setLiveId(null)}>
              Limpar
            </button>
          </div>
        )}
        <div className="af-dock-row">
          {running && liveRun ? (
            <button type="button" className="af-go" data-stop="true" onClick={() => void stop(liveRun.id)}>
              <Icon d={P.stop} size={12} strokeWidth={2} /> Parar · {doneCount} de {stepCount + 1}
            </button>
          ) : (
            <button type="button" className="af-go" disabled={busy === "testar"} onClick={() => void testAll()} title="Roda o rascunho agora; o que fala com outras pessoas vira ensaio">
              <Icon d={P.play} size={13} strokeWidth={2} /> {busy === "testar" ? "Começando…" : "Testar automação"}
            </button>
          )}
          {liveRun && liveRun.status === "ok" && !running && (
            <span className="af-dock-note small">
              teste ok · {duration(liveRun.ended && liveRun.started ? liveRun.ended - liveRun.started : null)}
              <button type="button" className="link-btn" onClick={() => setLiveId(null)}>
                limpar
              </button>
            </span>
          )}
          <span className="af-spacer" />
          {published !== null && (
            <button type="button" className="af-go" data-secondary="true" disabled={busy === "rodar"} onClick={() => void runPublished()} title="Roda a versão publicada de verdade, agora">
              <Icon d={P.play} size={12} strokeWidth={2} /> Rodar a publicada agora
            </button>
          )}
        </div>
      </div>
    );
  }

  const banner = !editing && pickedRun && (
    <div className="af-runbanner af-overlay" data-status={pickedRun.status} onPointerDown={(event) => event.stopPropagation()}>
      <div className="af-runbanner-row">
        <span className="af-run-dot" data-status={pickedRun.status} />
        <b>
          #{pickedRun.id} · {RUN_LABEL[pickedRun.status]}
        </b>
        <span className="small">
          {pickedRun.mode === "teste" ? "teste" : "produção"} · {pickedRun.origem} · {pickedRun.versao} · {when(pickedRun.started)}
          {pickedRun.ended ? ` · ${duration(pickedRun.ended - pickedRun.started)}` : ""}
        </span>
        {pickedRun.status === "rodando" ? (
          <button type="button" className="btn" onClick={() => void stop(pickedRun.id)}>
            <Icon d={P.stop} size={11} strokeWidth={2} /> Parar
          </button>
        ) : confirm === "copy" ? (
          <span className="af-confirm">
            Trocar o rascunho por este desenho?
            <button type="button" className="btn primary" disabled={busy === "copiar"} onClick={() => void copyToEditor(pickedRun)}>
              Copiar
            </button>
            <button type="button" className="btn" onClick={() => setConfirm(null)}>
              Cancelar
            </button>
          </span>
        ) : (
          <button type="button" className="btn" onClick={() => setConfirm("copy")} title="O desenho desta execução vira o rascunho">
            <Icon d={P.copy} size={12} strokeWidth={2} /> Copiar para o editor
          </button>
        )}
      </div>
      {(pickedRun.error || pickedRun.nota) && (
        <div className="af-runbanner-row">
          <span className={pickedRun.error ? "af-error mono" : "small"}>{pickedRun.error || pickedRun.nota}</span>
          {pickedRun.status === "erro" && (
            <button type="button" className="btn" disabled={busy === "conserto"} onClick={() => void askFix(pickedRun.id)}>
              Pedir conserto
            </button>
          )}
          {pickedRun.status === "erro" && failedStep(pickedRun) && (
            <button type="button" className="btn" onClick={() => void rerun(pickedRun, failedStep(pickedRun)!)}>
              <Icon d={P.rerun} size={11} strokeWidth={2} /> Reexecutar daqui
            </button>
          )}
        </div>
      )}
    </div>
  );

  return (
    <div className="af-screen">
      {renderList()}

      <section className="af-main">
        <header className="af-bar">
          <div className="af-bar-left">
            <input
              className="af-name-input"
              value={name}
              disabled={!draft}
              aria-label="Nome da automação"
              onChange={(event) => setName(event.target.value)}
              onBlur={() => {
                const clean = name.trim();
                if (!clean) setName(draft?.nome ?? "");
                else if (draft && clean !== draft.nome) edit((f) => ({ ...f, nome: clean }));
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") (event.target as HTMLInputElement).blur();
                if (event.key === "Escape") {
                  event.preventDefault();
                  setName(draft?.nome ?? "");
                }
              }}
            />
            {detail?.ativa && (
              <span className="chip" data-state="ativa">
                ativa
              </span>
            )}
            {detail && (
              <button type="button" className="chip af-version" data-state={published === null ? "rascunho" : changed ? "mudou" : "publicada"} onClick={openInfo} title="Versões e diferença">
                {published === null ? "rascunho" : changed ? `mudou desde a v${published}` : `publicada v${published}`}
              </button>
            )}
            {draft && (
              <span className="af-save mono" data-state={save.state} title={save.error}>
                {save.state === "erro" ? `não salvo: ${save.error}` : save.state === "salvo" ? "salvo" : "salvando…"}
              </span>
            )}
          </div>
          <div className="af-tabs" role="tablist" aria-label="Modo">
            <button
              type="button"
              role="tab"
              aria-selected={editing}
              onClick={() => {
                setMode("editor");
                setPanelId(null);
                setConfirm(null);
              }}
            >
              Editor
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!editing}
              onClick={() => {
                setMode("runs");
                setPanelId(null);
                setDrawer(null);
                setSelectedId(null);
                setConfirm(null);
                if (currentId) void loadRuns(currentId);
              }}
            >
              Execuções {runs.length ? <span className="af-count mono">{runs.length}</span> : null}
            </button>
          </div>
          <div className="af-bar-right">
            {confirm === "archive" ? (
              <span className="af-confirm">
                Tirar da lista?
                <button type="button" className="btn primary" disabled={busy === "arquivar"} title="Para de rodar; os arquivos vão para arquivadas/, no histórico" onClick={() => void archive()}>
                  Tirar
                </button>
                <button type="button" className="btn" onClick={() => setConfirm(null)}>
                  Cancelar
                </button>
              </span>
            ) : (
              <>
                <button type="button" className="btn" disabled={!detail} onClick={openInfo} aria-pressed={infoOpen}>
                  <Icon d={ICON.info} size={13} strokeWidth={2} /> Detalhes
                </button>
                <button
                  type="button"
                  className="btn primary"
                  disabled={!detail || !changed || !stepCount || busy === "publicar" || save.state === "erro"}
                  title={save.state === "erro" ? "Corrija o rascunho antes de publicar" : "Grava o rascunho como a versão que roda"}
                  onClick={() => void publish()}
                >
                  {busy === "publicar" ? "Publicando…" : !changed ? "Publicada" : published === null ? "Publicar" : `Publicar v${published + 1}`}
                </button>
                <button
                  type="button"
                  className="af-switch"
                  role="switch"
                  aria-checked={!!detail?.ativa}
                  disabled={!detail || published === null || busy === "ativa"}
                  title={published === null ? "Publique antes de ativar" : detail?.ativa ? "Pausar" : "Ativar: roda sozinha pelo gatilho"}
                  onClick={() => void toggleActive()}
                >
                  <span />
                  {detail?.ativa ? "Ativa" : "Pausada"}
                </button>
                <button type="button" className="icon-btn" title="Tirar da lista" aria-label="Tirar da lista" disabled={!currentId} onClick={() => setConfirm("archive")}>
                  <Icon d={ICON.trash} size={14} strokeWidth={1.8} />
                </button>
              </>
            )}
          </div>
        </header>

        <div className="af-work">
          {!editing && (
            <aside className="af-runlist">
              <span className="af-caps">Execuções</span>
              {runs.length === 0 && <p className="small af-runlist-empty">Nenhuma ainda. Teste no Editor para criar a primeira.</p>}
              {runs.map((r) => (
                <button key={r.id} type="button" className="af-runitem" aria-current={runId === r.id ? "true" : undefined} onClick={() => (setRunId(r.id), setConfirm(null), setPanelId(null))}>
                  <span className="af-run-dot" data-status={r.status} />
                  <span className="af-runitem-main">
                    <b>
                      {when(r.started)} <span className="af-run-mode mono">{r.mode === "teste" ? "teste" : "produção"}</span>
                    </b>
                    <span className="small">
                      {r.origem} · {r.versao} · #{r.id}
                    </span>
                    <span className="mono small">{r.status === "rodando" ? "rodando…" : `${RUN_LABEL[r.status]} · ${duration(r.ended ? r.ended - r.started : null)}`}</span>
                    {(r.error || r.nota) && <span className="small af-run-note" data-error={r.error ? "true" : undefined}>{r.error || r.nota}</span>}
                  </span>
                </button>
              ))}
            </aside>
          )}

          <div className="af-stage">
            {detailError ? (
              <div className="af-blank">
                <p className="af-error">Esta automação não abre: {detailError}</p>
                <p className="small">{current?.erro ? "O YAML foi editado à mão e tem um erro. Corrija o arquivo e clique de novo na lista." : ""}</p>
                {currentId && (
                  <button type="button" className="btn" onClick={() => void loadDetail(currentId, false)}>
                    Tentar de novo
                  </button>
                )}
              </div>
            ) : !flow ? (
              <p className="af-blank">{currentId ? "Abrindo…" : "Escolha uma automação na lista."}</p>
            ) : (
              <Canvas
                flow={flow}
                editing={editing}
                steps={shownRun?.steps ?? {}}
                catalog={catalog}
                agents={agents}
                client={client}
                selectedId={selectedId}
                fitKey={fitKey}
                apiRef={canvasApi}
                onSelect={setSelectedId}
                onOpen={(id) => (setSelectedId(id), setPanelId(id), setDrawer(null))}
                onEdit={edit}
                onAdd={openDrawer}
                onLink={link}
                onTestStep={(id) => void testStep(id)}
                onToggleOff={toggleOff}
                onRemove={removeStep}
              >
                {editing && stepCount === 0 && (
                  <div className="af-empty af-overlay" onPointerDown={(event) => event.stopPropagation()}>
                    <button type="button" className="af-first" onClick={() => openDrawer({ after: TRIGGER })}>
                      <span>
                        <Icon d={ICON.plus} size={26} strokeWidth={1.6} />
                      </span>
                      Escolher o primeiro passo
                    </button>
                    <p className="small">
                      Ela começa {flow.gatilho.tipo === "agendado" ? `agendada (${triggerWhen(flow.gatilho)})` : "na mão"}.{" "}
                      <button type="button" className="link-btn" onClick={() => openDrawer({ trigger: true })}>
                        Trocar o gatilho
                      </button>
                    </p>
                  </div>
                )}
                {banner}
                {!editing && !pickedRun && runs.length === 0 && (
                  <div className="af-runbanner af-overlay" onPointerDown={(event) => event.stopPropagation()}>
                    <div className="af-runbanner-row small">Sem execuções. Este é o rascunho, só para ver.</div>
                  </div>
                )}
                {editing && (
                  <div className="af-corner af-overlay" onPointerDown={(event) => event.stopPropagation()}>
                    <button
                      type="button"
                      title="Adicionar passo"
                      aria-label="Adicionar passo"
                      onClick={() => openDrawer(selectedId ? { after: selectedId } : stepCount ? {} : { after: TRIGGER })}
                    >
                      <Icon d={ICON.plus} size={16} strokeWidth={2} />
                    </button>
                    <button type="button" title="Nota no canvas" aria-label="Nota no canvas" onClick={addNote}>
                      <Icon d={P.sticky} size={15} strokeWidth={1.8} />
                    </button>
                  </div>
                )}
                {dock}
              </Canvas>
            )}
            {drawer && editing && flow && (
              <Drawer
                ctx={drawer}
                flow={flow}
                catalog={catalog}
                catalogError={catalogError}
                agents={agents}
                client={client}
                onClose={() => setDrawer(null)}
                onPick={addStep}
                onTrigger={setTrigger}
                onRetry={() => void loadCatalog()}
              />
            )}
            {infoOpen && !drawer && renderInfo()}
          </div>
          {panelId && flow && (panelId === TRIGGER || flow.passos.some((s) => s.id === panelId)) && (
            <StepPanel
              key={`${mode}:${panelId}`}
              flow={flow}
              nodeId={panelId}
              editing={editing}
              catalog={catalog}
              agents={agents}
              client={client}
              run={panelRun}
              runLabel={runLabel(panelRun)}
              view={dataView}
              onView={setDataView}
              onClose={() => setPanelId(null)}
              onEdit={edit}
              onRename={rename}
              onTestStep={(id) => void testStep(id)}
              onTestAll={() => (setPanelId(null), void testAll())}
              onRerun={(stepId) => panelRun && void rerun(panelRun, stepId)}
              onAskFix={() => panelRun && void askFix(panelRun.id)}
              onOpenSession={onOpenSession}
              onRemove={removeStep}
              onToast={onToast}
            />
          )}
        </div>
      </section>
    </div>
  );
}
