// PROTÓTIPO da tela de Automações (o "n8n da MÊTIS"). Tudo aqui é dado de exemplo, guardado só
// na memória da tela: nada fala com o núcleo, nenhum conector é chamado, nenhum terminal abre.
// A proposta de como isto funcionaria de verdade está em docs/AUTOMACOES.md.

import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { ICON, Icon, MetisMark } from "../icons";
import { GreekBust } from "./AgentSprite";
import "./automations.css";

type Kind = "trigger" | "tool" | "agent" | "code" | "if" | "approval" | "brain" | "wait";
type Step = "running" | "ok" | "erro" | "esperando" | "pulado" | "recusado";
type Branch = "sim" | "não";

interface Section {
  t: string;
  kv?: [string, string][];
  text?: string;
  chips?: string[];
  code?: string;
  note?: string;
}

interface Persona {
  name: string;
  seed: string;
  color: string;
}

interface FlowNode {
  id: string;
  kind: Kind;
  title: string;
  sub: string;
  x: number;
  y: number;
  cost?: string;
  /** Alternativa por cota (DESIGN.md): o que roda no lugar se a janela de 5 h apertar. */
  alt?: string;
  /** Fala com outras pessoas: exige aprovação antes (princípio 4) e vira ensaio no teste. */
  people?: boolean;
  /** Passo importado sem equivalente direto. */
  warn?: string;
  /** Desligado: os dados passam direto, sem rodar. */
  off?: boolean;
  /** Agente da galeria (sprite greco-romana). Sem ele, é o Claude Code puro. */
  who?: Persona;
  tools?: string[];
  schema?: string;
  info: Section[];
}

interface FlowEdge {
  from: string;
  to: string;
  label?: Branch;
}

interface StickyNote {
  id: string;
  x: number;
  y: number;
  w: number;
  title: string;
  text: string;
}

interface StepResult {
  s: Step;
  ms?: number;
  out?: unknown;
  note?: string;
}

interface Run {
  id: string;
  when: string;
  how: string;
  took: string;
  quota: string;
  status: "ok" | "erro" | "aguardando";
  note?: string;
  steps: Record<string, StepResult>;
}

interface Flow {
  id: string;
  name: string;
  file: string;
  when: string;
  state: "ativa" | "pausada" | "rascunho";
  draft: number;
  published: number | null;
  where: string;
  origin?: string;
  diff?: string;
  outcome?: Record<string, Branch>;
  nodes: FlowNode[];
  edges: FlowEdge[];
  notes: StickyNote[];
  runs: Run[];
}

interface PanelCtx {
  after?: string;
  label?: Branch;
  between?: FlowEdge;
  trigger?: boolean;
}

type Draft = Omit<FlowNode, "id" | "x" | "y">;

// --- forma de cada passo --------------------------------------------------------------------

/** Lado do bloco quadrado; o agente é um bloco largo com modelo, ferramentas e saída pendurados embaixo. */
const S = 84;
const AW = 240;
const GAP = 130;
const OFF = 3000;
const nodeW = (n: { kind: Kind }) => (n.kind === "agent" ? AW : S);

const P = {
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
  diamond: "M12 3l9 9-9 9-9-9z",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4",
  hourglass: "M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9s8 4 8 9",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M5 11h14v10H5z",
  play: "M7 4l13 8-13 8z",
  stop: "M6 6h12v12H6z",
  minus: "M5 12h14",
  fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  power: "M12 3v8M7.5 6.5a7 7 0 1 0 9 0",
  pin: "M9 3h6l-1 6 4 4H6l4-4zM12 13v8",
  sticky: "M5 4h14v11l-5 5H5zM14 20v-5h5",
  back: "M15 6l-6 6 6 6",
};

const KIND: Record<Kind, { label: string; color: string; icon: string | null; hint: string }> = {
  trigger: {
    label: "Quando",
    color: "var(--wait)",
    icon: P.clock,
    hint: "agendado, evento da MÊTIS, conector por sondagem, captura rápida",
  },
  tool: {
    label: "Ferramenta",
    color: "var(--run)",
    icon: ICON.plug,
    hint: "uma ferramenta da central de MCP, sem gastar cota",
  },
  agent: {
    label: "Agente",
    color: "#d97757",
    icon: null,
    hint: "Claude ou Codex num terminal da MÊTIS, pelo seu plano",
  },
  code: {
    label: "Código",
    color: "var(--mut)",
    icon: P.code,
    hint: "Python ou JavaScript local, sem gastar cota",
  },
  if: {
    label: "Condição",
    color: "var(--acct)",
    icon: P.diamond,
    hint: "regra de uma linha, ou sim ou não de um agente barato",
  },
  approval: {
    label: "Aprovação",
    color: "var(--warn)",
    icon: P.shield,
    hint: "pausa até você aprovar; entra sozinha antes de quem fala com outras pessoas",
  },
  brain: {
    label: "Brain",
    color: "var(--g-brain)",
    icon: ICON.graph,
    hint: "ler, buscar ou registrar no vault",
  },
  wait: {
    label: "Esperar",
    color: "var(--fnt)",
    icon: P.hourglass,
    hint: "um tempo, ou até um evento chegar",
  },
};

const STEP_LABEL: Record<Step, string> = {
  running: "rodando",
  ok: "ok",
  erro: "erro",
  esperando: "esperando você",
  pulado: "pulado",
  recusado: "recusado",
};

// Conectores como "elementos": símbolo de duas letras na cor do conector, como numa tabela periódica.
interface Connector {
  id: string;
  name: string;
  mono: string;
  color: string;
  tools: { name: string; title: string; people?: boolean }[];
}

const CATALOG: Connector[] = [
  {
    id: "slack",
    name: "Slack",
    mono: "Sl",
    color: "var(--g-pessoal)",
    tools: [
      { name: "slack.enviar_dm", title: "Mandar DM para você" },
      {
        name: "slack.enviar_mensagem",
        title: "Mandar num canal",
        people: true,
      },
      { name: "slack.ler_canal", title: "Ler mensagens novas" },
    ],
  },
  {
    id: "clickup",
    name: "ClickUp",
    mono: "Cu",
    color: "var(--g-clientes)",
    tools: [
      { name: "clickup.criar_tarefa", title: "Criar tarefa" },
      { name: "clickup.mover_tarefa", title: "Mudar o status" },
      { name: "clickup.comentar", title: "Comentar na tarefa", people: true },
    ],
  },
  {
    id: "pipedrive",
    name: "Pipedrive",
    mono: "Pd",
    color: "var(--g-carreira)",
    tools: [
      { name: "pipedrive.buscar_negocios", title: "Buscar negócios" },
      { name: "pipedrive.criar_negocio", title: "Criar negócio" },
      { name: "pipedrive.atualizar_negocio", title: "Atualizar negócio" },
    ],
  },
  {
    id: "supabase",
    name: "Supabase",
    mono: "Sb",
    color: "var(--g-brain)",
    tools: [
      { name: "supabase.consultar", title: "Consultar (SQL)" },
      { name: "supabase.inserir", title: "Inserir linhas" },
      { name: "supabase.atualizar", title: "Atualizar linhas" },
    ],
  },
  {
    id: "github",
    name: "GitHub",
    mono: "Gh",
    color: "var(--mut)",
    tools: [
      { name: "github.ler_pr", title: "Ler PR e checks" },
      { name: "github.comentar", title: "Comentar no PR", people: true },
      { name: "github.push", title: "Push do branch", people: true },
    ],
  },
  {
    id: "n8n",
    name: "n8n (ponte)",
    mono: "n8",
    color: "var(--warn)",
    tools: [
      { name: "n8n.rodar_workflow", title: "Rodar um workflow do n8n" },
      { name: "n8n.execucoes", title: "Ler execuções" },
    ],
  },
  {
    id: "metis",
    name: "MÊTIS",
    mono: "",
    color: "var(--acc)",
    tools: [
      { name: "metis.tarefa", title: "Tarefa no kanban" },
      { name: "metis.avisar", title: "Aviso no Mac" },
      { name: "metis.web", title: "Abrir o navegador" },
    ],
  },
  {
    id: "brain",
    name: "Brain",
    mono: "Br",
    color: "var(--g-brain)",
    tools: [
      { name: "brain.buscar", title: "Buscar notas" },
      { name: "brain.ler", title: "Ler uma nota" },
      { name: "brain.registrar", title: "Registrar decisão ou aprendizado" },
      { name: "brain.diario", title: "Linha no diário" },
    ],
  },
];

const connectorOf = (text: string) => CATALOG.find((c) => text.includes(`${c.id}.`)) ?? null;

const GALLERY: { label: string; sub: string; who?: Persona; glyph?: string }[] = [
  { label: "Claude Code", sub: "claude · padrão", glyph: "✻" },
  { label: "Codex", sub: "codex · padrão", glyph: "◇" },
  {
    label: "Aurora",
    sub: "Aurora · claude · padrão",
    who: { name: "Aurora", seed: "auroraAurora", color: "#AF52DE" },
  },
  {
    label: "Alexandria",
    sub: "Alexandria · claude · barato",
    who: {
      name: "Alexandria",
      seed: "alexandriaAlexandria",
      color: "#FF3B30",
    },
  },
  {
    label: "Sócrates",
    sub: "Sócrates · claude · padrão",
    who: { name: "Sócrates", seed: "socratesSócrates", color: "#007AFF" },
  },
  {
    label: "Farol",
    sub: "Farol · claude · barato",
    who: { name: "Farol", seed: "farolFarol", color: "#007AFF" },
  },
];

const TRIGGERS: { title: string; sub: string; hint: string }[] = [
  {
    title: "Agendado",
    sub: "agendado",
    hint: "dia e hora; regra para o Mac dormindo",
  },
  {
    title: "Evento da MÊTIS",
    sub: "evento da MÊTIS",
    hint: "nota nova, tarefa mudou, agente terminou ou errou",
  },
  {
    title: "Novidade num conector",
    sub: "conector · sondagem",
    hint: "mensagem no Slack, tarefa no ClickUp, check no GitHub",
  },
  {
    title: "Captura rápida",
    sub: "captura rápida",
    hint: "o atalho global manda para esta automação",
  },
  {
    title: "Na mão",
    sub: "metis rodar",
    hint: "botão, ⌘K ou metis rodar no terminal",
  },
];

const LOGIC: Kind[] = ["if", "approval", "wait", "code"];

// --- dados de exemplo ------------------------------------------------------------------------

const BRIEFING: Flow = {
  id: "briefing",
  name: "Briefing comercial da manhã",
  file: "~/.harness/automacoes/briefing-comercial.yaml",
  when: "dias úteis · 8h30",
  state: "ativa",
  draft: 4,
  published: 3,
  where: "no Mac · se ele dormir, roda ao acordar (até 11h)",
  diff: "+ passo «Tarefa para amanhã» (clickup.criar_tarefa)\n+ ligação «Algum follow-up urgente?» → não → «Tarefa para amanhã»\n~ pedido do agente: + «no tom da Seller Pro»",
  outcome: { c1: "sim" },
  notes: [
    {
      id: "k1",
      x: 0,
      y: 490,
      w: 300,
      title: "Como ela roda",
      text: "De segunda a sexta, 8h30. Se o Mac estiver dormindo, roda ao acordar, até as 11h. O envio no #comercial só sai depois da sua aprovação.",
    },
  ],
  nodes: [
    {
      id: "t1",
      kind: "trigger",
      title: "Dias úteis, 8h30",
      sub: "agendado",
      x: 0,
      y: 210,
      info: [
        {
          t: "Gatilho",
          kv: [
            ["Tipo", "agendado"],
            ["Quando", "seg a sex, 8h30"],
            ["Mac dormindo", "roda ao acordar, até 11h; depois, pula"],
          ],
        },
        {
          t: "Sem webhook",
          note: "A MÊTIS não abre porta na internet (princípio 3). O que vem de fora chega por sondagem do conector ou por uma ponte no n8n.",
        },
      ],
    },
    {
      id: "p1",
      kind: "tool",
      title: "Negócios parados há 3+ dias",
      sub: "pipedrive.buscar_negocios",
      x: 210,
      y: 100,
      cost: "0 cota",
      info: [
        {
          t: "Ferramenta",
          kv: [
            ["Chama", "pipedrive.buscar_negocios"],
            ["Conta", "Seller Pro"],
          ],
        },
        {
          t: "Parâmetros",
          code: "etapa: [Proposta, Negociação]\nsem_atividade_dias: 3\ndono: eu",
        },
        {
          t: "Custo",
          note: "Determinístico: a MÊTIS chama a ferramenta da central de MCP direto, sem agente e sem gastar cota.",
        },
      ],
    },
    {
      id: "s1",
      kind: "tool",
      title: "Leads de ontem por origem",
      sub: "supabase.consultar",
      x: 210,
      y: 320,
      cost: "0 cota",
      info: [
        {
          t: "Ferramenta",
          kv: [
            ["Chama", "supabase.consultar"],
            ["Conta", "Base de Leads (só leitura)"],
          ],
        },
        {
          t: "Consulta",
          code: "select utm_source as origem, count(*) as leads\nfrom leads\nwhere criado_em::date = {{ontem}}\ngroup by 1",
        },
      ],
    },
    {
      id: "a1",
      kind: "agent",
      title: "Escrever briefing e follow-ups",
      sub: "claude · padrão",
      x: 430,
      y: 210,
      cost: "≈ 3% da cota de 5 h",
      alt: "Codex · padrão se o Claude passar de 80%",
      tools: ["pipedrive.ler", "brain.buscar"],
      schema: "resumo: texto\nfollowups[]:\n  negocio: texto\n  prioridade: alta | média | baixa\n  mensagem: texto",
      info: [
        {
          t: "Agente",
          kv: [
            ["Quem", "Claude Code, sem papel"],
            ["Nível", "padrão"],
            ["Conta", "pessoal"],
            ["Onde", "terminal em segundo plano, aba Automações"],
          ],
        },
        {
          t: "Pedido",
          text: "Com os negócios parados ({{Negócios parados}}) e os leads de ontem ({{Leads de ontem}}), escreva um briefing de 5 linhas para mim e, para cada negócio, um follow-up curto de WhatsApp no tom da Seller Pro. Dê a prioridade (alta, média, baixa) pelo valor e pelo tempo parado.",
        },
        {
          t: "Ferramentas liberadas",
          chips: ["pipedrive.ler", "brain.buscar", "nada que envie"],
        },
        {
          t: "Saída combinada",
          code: "resumo: texto\nfollowups[]:\n  negocio: texto\n  prioridade: alta | média | baixa\n  mensagem: texto",
        },
        {
          t: "Como a resposta volta",
          note: "O agente roda interativo, como se você digitasse claude, pelo seu plano. Ele entrega a saída chamando metis saida; a MÊTIS confere o formato e, se faltar campo, pede de novo no mesmo terminal.",
        },
        {
          t: "Se a cota apertar",
          note: "Acima de 80% na janela de 5 h, este passo roda no Codex, nível padrão. A troca aparece na execução.",
        },
      ],
    },
    {
      id: "m1",
      kind: "tool",
      title: "Resumo na sua DM",
      sub: "slack.enviar_dm",
      x: 800,
      y: 30,
      cost: "0 cota",
      info: [
        {
          t: "Ferramenta",
          kv: [
            ["Chama", "slack.enviar_dm"],
            ["Para", "você (bot da MÊTIS)"],
          ],
        },
        {
          t: "Mensagem",
          code: "☀️ Briefing de {{hoje}}\n{{Escrever briefing.resumo}}",
        },
        {
          t: "Sem aprovação",
          note: "A mensagem é só para você, então não fala com outras pessoas e não precisa de aprovação.",
        },
      ],
    },
    {
      id: "c1",
      kind: "if",
      title: "Algum follow-up urgente?",
      sub: "prioridade = alta",
      x: 800,
      y: 210,
      info: [
        {
          t: "Condição",
          kv: [
            ["Regra", "algum followup com prioridade = alta"],
            ["Sim", "vai para a sua aprovação"],
            ["Não", "vira tarefa no ClickUp"],
          ],
        },
        {
          t: "Outra forma",
          note: "Quando a regra não couber numa linha, ela vira uma pergunta de sim ou não a um agente barato.",
        },
      ],
    },
    {
      id: "b1",
      kind: "brain",
      title: "Anotar no diário",
      sub: "brain.diario",
      x: 800,
      y: 400,
      cost: "0 cota",
      info: [
        {
          t: "Brain",
          kv: [
            ["Ação", "linha no diário do dia"],
            ["Projeto", "[[Seller Pro]]"],
          ],
        },
        {
          t: "Texto",
          code: "Briefing comercial: {{followups.length}} follow-ups, {{leads.total}} leads ontem.",
        },
      ],
    },
    {
      id: "ap",
      kind: "approval",
      title: "Você revisa as mensagens",
      sub: "até 11h",
      x: 1010,
      y: 120,
      info: [
        {
          t: "Aprovação",
          kv: [
            ["Quem aprova", "você"],
            ["Aviso", "notificação do macOS e DM no Slack"],
            ["Sem resposta até 11h", "não envia e anota no diário"],
          ],
        },
        {
          t: "O que você vê",
          note: "Cada mensagem, editável, com o negócio ao lado. Aprovar solta o envio; recusar encerra sem mandar nada.",
        },
        {
          t: "Por que está aqui",
          note: "O passo seguinte fala com outras pessoas. A MÊTIS põe a aprovação sozinha antes dele (princípio 4); tirar exige uma mudança sua, explícita.",
        },
      ],
    },
    {
      id: "sc",
      kind: "tool",
      title: "Mandar no #comercial",
      sub: "slack.enviar_mensagem",
      x: 1220,
      y: 120,
      cost: "0 cota",
      people: true,
      info: [
        {
          t: "Ferramenta",
          kv: [
            ["Chama", "slack.enviar_mensagem"],
            ["Canal", "#comercial"],
            ["Conta", "Seller Pro"],
          ],
        },
        {
          t: "Mensagem",
          code: "Follow-ups de hoje:\n{{Você revisa.aprovadas}}",
        },
        {
          t: "No teste",
          note: "Ao testar, este passo vira ensaio: a mensagem vai para a sua DM, nunca para o canal.",
        },
      ],
    },
    {
      id: "x1",
      kind: "tool",
      title: "Tarefa para amanhã",
      sub: "clickup.criar_tarefa",
      x: 1010,
      y: 320,
      cost: "0 cota",
      info: [
        {
          t: "Ferramenta",
          kv: [
            ["Chama", "clickup.criar_tarefa"],
            ["Lista", "Comercial · Follow-ups"],
            ["Prazo", "amanhã, 10h"],
          ],
        },
        {
          t: "Título",
          code: "Revisar {{followups.length}} follow-ups sem urgência",
        },
      ],
    },
  ],
  edges: [
    { from: "t1", to: "p1" },
    { from: "t1", to: "s1" },
    { from: "p1", to: "a1" },
    { from: "s1", to: "a1" },
    { from: "a1", to: "m1" },
    { from: "a1", to: "c1" },
    { from: "a1", to: "b1" },
    { from: "c1", to: "ap", label: "sim" },
    { from: "c1", to: "x1", label: "não" },
    { from: "ap", to: "sc" },
  ],
  runs: [],
};

const NEGOCIOS = [
  {
    negocio: "Mentoria · Cliente A",
    etapa: "Proposta",
    parado_dias: 4,
    valor: 4997,
  },
  {
    negocio: "Consultoria · Cliente B",
    etapa: "Negociação",
    parado_dias: 6,
    valor: 9800,
  },
  {
    negocio: "Mentoria · Cliente C",
    etapa: "Proposta",
    parado_dias: 3,
    valor: 4997,
  },
  {
    negocio: "Treinamento · Cliente D",
    etapa: "Proposta",
    parado_dias: 5,
    valor: 1997,
  },
  {
    negocio: "Consultoria · Cliente E",
    etapa: "Negociação",
    parado_dias: 9,
    valor: 12000,
  },
  {
    negocio: "Workshop · Cliente F",
    etapa: "Proposta",
    parado_dias: 3,
    valor: 697,
  },
];

const FOLLOWUPS = [
  {
    negocio: "Consultoria · Cliente E",
    prioridade: "alta",
    mensagem: "Oi! Ficou alguma dúvida na proposta? Consigo te ligar hoje às 15h.",
  },
  {
    negocio: "Consultoria · Cliente B",
    prioridade: "alta",
    mensagem: "Passando para saber se o valor fechou com o time. Posso ajustar o parcelamento.",
  },
  {
    negocio: "Treinamento · Cliente D",
    prioridade: "média",
    mensagem: "Separei os horários da próxima turma, quer que eu reserve uma vaga?",
  },
  {
    negocio: "Mentoria · Cliente A",
    prioridade: "média",
    mensagem: "Lembrei de você: abriu uma vaga na mentoria de dezembro.",
  },
  {
    negocio: "Mentoria · Cliente C",
    prioridade: "baixa",
    mensagem: "Qualquer dúvida sobre a proposta, me chama por aqui.",
  },
  {
    negocio: "Workshop · Cliente F",
    prioridade: "baixa",
    mensagem: "O workshop de sábado ainda tem lugar, se quiser.",
  },
];

BRIEFING.runs = [
  {
    id: "r1",
    when: "hoje 08:30",
    how: "agendado",
    took: "13 min 40 s",
    quota: "Claude 5 h +3%",
    status: "ok",
    note: "12 min esperando a sua aprovação",
    steps: {
      t1: { s: "ok", ms: 4, out: [{ hora: "08:30", motivo: "agendado" }] },
      p1: { s: "ok", ms: 820, out: NEGOCIOS },
      s1: {
        s: "ok",
        ms: 310,
        out: [
          { origem: "meta_ads", leads: 21 },
          { origem: "instagram", leads: 9 },
          { origem: "whatsapp", leads: 5 },
          { origem: "sem_utm", leads: 2 },
        ],
      },
      a1: {
        s: "ok",
        ms: 91000,
        note: "terminal «Automação · Briefing» · 1 min 31 s · 41 mil tokens · Claude 5 h de 52% para 55%",
        out: {
          resumo: "37 leads ontem (57% Meta Ads, 2 sem UTM). 6 negócios parados; 2 pedem contato hoje.",
          followups: FOLLOWUPS,
        },
      },
      m1: { s: "ok", ms: 640, out: [{ enviada: true, para: "você" }] },
      c1: { s: "ok", ms: 2, out: [{ urgentes: 2, resposta: "sim" }] },
      b1: { s: "ok", ms: 120, out: [{ arquivo: "06-DIARIO/2026-11-08.md" }] },
      ap: {
        s: "ok",
        ms: 720000,
        note: "aprovado às 08:42 por você · 1 mensagem editada antes de soltar",
        out: FOLLOWUPS.slice(0, 2).map((f, i) => ({
          negocio: f.negocio,
          mensagem: f.mensagem,
          editada: i === 0,
        })),
      },
      sc: { s: "ok", ms: 700, out: [{ enviadas: 2, canal: "#comercial" }] },
      x1: { s: "pulado", note: "o caminho «não» não rodou" },
    },
  },
  {
    id: "r2",
    when: "ontem 09:47",
    how: "ao acordar (o Mac dormia às 8h30)",
    took: "1 min 52 s",
    quota: "Claude 5 h +3%",
    status: "ok",
    steps: {
      t1: {
        s: "ok",
        ms: 4,
        out: [{ hora: "09:47", motivo: "atrasada: o Mac dormia às 08:30" }],
      },
      p1: { s: "ok", ms: 760, out: NEGOCIOS.slice(0, 4) },
      s1: { s: "ok", ms: 290 },
      a1: { s: "ok", ms: 98000 },
      m1: { s: "ok", ms: 610 },
      c1: { s: "ok", ms: 2, out: [{ urgentes: 0, resposta: "não" }] },
      b1: { s: "ok", ms: 130 },
      ap: { s: "pulado" },
      sc: { s: "pulado" },
      x1: {
        s: "ok",
        ms: 900,
        out: [
          {
            tarefa: "Revisar 4 follow-ups sem urgência",
            lista: "Comercial · Follow-ups",
          },
        ],
      },
    },
  },
  {
    id: "r3",
    when: "qua 08:30",
    how: "agendado",
    took: "3 s",
    quota: "0",
    status: "erro",
    note: "Pipedrive recusou o token; você recebeu o aviso",
    steps: {
      t1: { s: "ok", ms: 4, out: [{ hora: "08:30", motivo: "agendado" }] },
      p1: {
        s: "erro",
        ms: 2100,
        out: { erro: "401 Unauthorized", detalhe: "token expirado" },
        note: "A conta do Pipedrive precisa ser religada em Conectores. O erro não some: fica aqui e chega no Slack.",
      },
      s1: { s: "ok", ms: 300 },
      a1: { s: "pulado", note: "parou porque um passo anterior falhou" },
      m1: { s: "pulado" },
      c1: { s: "pulado" },
      b1: { s: "pulado" },
      ap: { s: "pulado" },
      sc: { s: "pulado" },
      x1: { s: "pulado" },
    },
  },
];

const AURORA: Flow = {
  id: "aurora",
  name: "Placar do estudo da Aurora",
  file: "~/.harness/automacoes/placar-aurora.yaml",
  when: "todo dia · 20h50",
  state: "ativa",
  draft: 2,
  published: 2,
  where: "no Mac · se ele dormir, pula o dia",
  notes: [
    {
      id: "k1",
      x: 560,
      y: 380,
      w: 270,
      title: "Rotina é automação",
      text: "A rotina mais simples é um gatilho e um agente. Por isso as Rotinas da v0.7 podem nascer neste módulo.",
    },
  ],
  nodes: [
    {
      id: "t1",
      kind: "trigger",
      title: "Todo dia, 20h50",
      sub: "agendado",
      x: 0,
      y: 120,
      info: [
        {
          t: "Gatilho",
          kv: [
            ["Tipo", "agendado"],
            ["Quando", "todo dia, 20h50"],
            ["Mac dormindo", "pula o dia"],
          ],
        },
      ],
    },
    {
      id: "a1",
      kind: "agent",
      title: "Atualizar o placar do estudo",
      sub: "Aurora · claude · padrão",
      x: 210,
      y: 120,
      cost: "≈ 2% da cota de 5 h",
      who: { name: "Aurora", seed: "auroraAurora", color: "#AF52DE" },
      tools: ["brain.ler", "brain.buscar"],
      schema: "placar: texto\npergunta: texto",
      info: [
        {
          t: "Agente",
          kv: [
            ["Quem", "Aurora (Coach de Estudo)"],
            ["Onde", "aba de terminal visível, para você conversar com ela"],
          ],
        },
        {
          t: "Pedido",
          text: "Leia o que eu estudei hoje no Brain, atualize o placar do AI Engineer 2027 e me faça uma pergunta de previsão para amanhã.",
        },
        { t: "Saída combinada", code: "placar: texto\npergunta: texto" },
      ],
    },
    {
      id: "b1",
      kind: "brain",
      title: "Registrar o placar",
      sub: "brain.registrar",
      x: 580,
      y: 40,
      cost: "0 cota",
      info: [
        {
          t: "Brain",
          kv: [
            ["Ação", "atualiza a nota do placar"],
            ["Projeto", "[[AI Engineer 2027]]"],
          ],
        },
      ],
    },
    {
      id: "m1",
      kind: "tool",
      title: "Aviso no Slack",
      sub: "slack.enviar_dm",
      x: 580,
      y: 220,
      cost: "0 cota",
      info: [
        {
          t: "Ferramenta",
          kv: [
            ["Chama", "slack.enviar_dm"],
            ["Para", "você"],
          ],
        },
      ],
    },
  ],
  edges: [
    { from: "t1", to: "a1" },
    { from: "a1", to: "b1" },
    { from: "a1", to: "m1" },
  ],
  runs: [],
};

const PRECEDENTES: Flow = {
  id: "precedentes",
  name: "Decisão nova → precedentes",
  file: "~/.harness/automacoes/decisao-precedentes.yaml",
  when: "nota nova em */decisoes/",
  state: "ativa",
  draft: 1,
  published: 1,
  where: "no Mac · evento perdido roda ao acordar",
  outcome: { c1: "não" },
  notes: [
    {
      id: "k1",
      x: 0,
      y: 330,
      w: 180,
      title: "Gatilho do Brain",
      text: "Dispara quando uma decisão nova aparece em qualquer projeto do vault.",
    },
  ],
  nodes: [
    {
      id: "t1",
      kind: "trigger",
      title: "Decisão nova no Brain",
      sub: "evento da MÊTIS",
      x: 0,
      y: 150,
      info: [
        {
          t: "Gatilho",
          kv: [
            ["Tipo", "evento da MÊTIS"],
            ["Quando", "nota nova em 01-PROJETOS/*/decisoes/"],
          ],
        },
        {
          t: "Eventos da MÊTIS",
          chips: ["nota nova", "tarefa mudou de coluna", "agente terminou", "agente errou", "worktree criada", "check do PR falhou"],
        },
      ],
    },
    {
      id: "a1",
      kind: "agent",
      title: "Comparar com outros projetos",
      sub: "Alexandria · claude · barato",
      x: 210,
      y: 150,
      cost: "≈ 1% da cota de 5 h",
      alt: "Codex · barato se o Claude passar de 80%",
      who: {
        name: "Alexandria",
        seed: "alexandriaAlexandria",
        color: "#FF3B30",
      },
      tools: ["brain.buscar", "brain.ler"],
      schema: "conflitos[]: { nota, motivo }\nparecidas[]: texto",
      info: [
        {
          t: "Agente",
          kv: [
            ["Quem", "Alexandria (Bibliotecário)"],
            ["Nível", "barato"],
            ["Onde", "terminal em segundo plano"],
          ],
        },
        {
          t: "Pedido",
          text: "Leia a decisão nova e procure, nos outros projetos, decisões que ela contradiz ou repete. Explique cada conflito em uma linha.",
        },
        {
          t: "Saída combinada",
          code: "conflitos[]:\n  nota: texto\n  motivo: texto\nparecidas[]: texto",
        },
      ],
    },
    {
      id: "c1",
      kind: "if",
      title: "Contradiz alguma?",
      sub: "conflitos > 0",
      x: 580,
      y: 150,
      info: [
        {
          t: "Condição",
          kv: [["Regra", "a lista de conflitos tem algum item"]],
        },
      ],
    },
    {
      id: "k1",
      kind: "tool",
      title: "Tarefa no kanban",
      sub: "metis.tarefa",
      x: 790,
      y: 20,
      cost: "0 cota",
      info: [
        {
          t: "Ferramenta",
          kv: [
            ["Chama", "metis.tarefa adicionar"],
            ["Texto", "Revisar conflito com {{conflitos[0].nota}}"],
          ],
        },
      ],
    },
    {
      id: "n1",
      kind: "tool",
      title: "Aviso no Mac",
      sub: "metis.avisar",
      x: 790,
      y: 170,
      cost: "0 cota",
      info: [
        {
          t: "Ferramenta",
          kv: [
            ["Chama", "metis.avisar"],
            ["Texto", "A decisão nova contradiz {{conflitos.length}} decisões"],
          ],
        },
      ],
    },
    {
      id: "b1",
      kind: "brain",
      title: "Ligar as parecidas",
      sub: "brain.registrar",
      x: 790,
      y: 330,
      cost: "0 cota",
      info: [{ t: "Brain", kv: [["Ação", "acrescenta as parecidas em Conexões"]] }],
    },
  ],
  edges: [
    { from: "t1", to: "a1" },
    { from: "a1", to: "c1" },
    { from: "c1", to: "k1", label: "sim" },
    { from: "c1", to: "n1", label: "sim" },
    { from: "c1", to: "b1", label: "não" },
  ],
  runs: [],
};

const PR: Flow = {
  id: "pr",
  name: "Check falhou no PR → conserto",
  file: "~/.harness/automacoes/pr-check-conserto.yaml",
  when: "GitHub · sondagem a cada 5 min",
  state: "pausada",
  draft: 3,
  published: 3,
  where: "no Mac",
  notes: [
    {
      id: "k1",
      x: 790,
      y: 300,
      w: 270,
      title: "Nada de push sozinho",
      text: "O agente roda numa aba visível, na worktree do PR. Você vê o diff com notas antes de qualquer push.",
    },
  ],
  nodes: [
    {
      id: "t1",
      kind: "trigger",
      title: "Check falhou num PR meu",
      sub: "github · sondagem 5 min",
      x: 0,
      y: 120,
      info: [
        {
          t: "Gatilho",
          kv: [
            ["Tipo", "conector, por sondagem"],
            ["Quando", "um check de PR seu falha"],
            ["Repositórios", "os da barra lateral"],
          ],
        },
      ],
    },
    {
      id: "w1",
      kind: "code",
      title: "Juntar o log do check",
      sub: "python · 12 linhas",
      x: 210,
      y: 120,
      cost: "0 cota",
      info: [
        {
          t: "Código",
          code: "falhas = [j for j in entrada.jobs\n          if j.conclusion == 'failure']\nreturn {\n  'log': '\\n'.join(j.log[-80:] for j in falhas),\n  'branch': entrada.branch,\n}",
        },
        {
          t: "Escrito por quem",
          note: "Você descreve, o Claude escreve; o código fica no arquivo da automação e roda local, sem gastar cota.",
        },
      ],
    },
    {
      id: "a1",
      kind: "agent",
      title: "Consertar na worktree do PR",
      sub: "claude · forte · visível",
      x: 420,
      y: 120,
      cost: "≈ 8% da cota de 5 h",
      alt: "Codex · forte se o Claude passar de 80%",
      tools: ["github.ler_pr"],
      info: [
        {
          t: "Agente",
          kv: [
            ["Quem", "Claude Code"],
            ["Nível", "forte"],
            ["Onde", "aba visível na worktree do branch do PR"],
          ],
        },
        {
          t: "Pedido",
          text: "O check do PR falhou. O log está abaixo. Ache a causa, conserte e rode os testes. Não faça push.",
        },
      ],
    },
    {
      id: "ap",
      kind: "approval",
      title: "Você revisa o diff",
      sub: "diff com notas",
      x: 790,
      y: 120,
      info: [
        {
          t: "Aprovação",
          kv: [
            ["O que você vê", "o diff da worktree, com notas por linha"],
            ["Recusar com nota", "a nota volta para o agente"],
          ],
        },
      ],
    },
    {
      id: "g1",
      kind: "tool",
      title: "Push e comentário",
      sub: "github.push",
      x: 1000,
      y: 120,
      cost: "0 cota",
      people: true,
      info: [{ t: "Ferramenta", kv: [["Chama", "github.push e github.comentar"]] }],
    },
  ],
  edges: [
    { from: "t1", to: "w1" },
    { from: "w1", to: "a1" },
    { from: "a1", to: "ap" },
    { from: "ap", to: "g1" },
  ],
  runs: [],
};

const FUNIL: Flow = {
  id: "funil",
  name: "Funil · Guru → Supabase",
  file: "~/.harness/automacoes/funil-guru-supabase.yaml",
  when: "webhook (sem equivalente)",
  state: "rascunho",
  draft: 1,
  published: null,
  where: "a decidir: este fluxo precisa de 24 h",
  origin: "importada do n8n · 6 nós · 2 para revisar",
  outcome: { i1: "sim" },
  notes: [
    {
      id: "k1",
      x: 0,
      y: 330,
      w: 300,
      title: "Veio do n8n",
      text: "O webhook não tem par na MÊTIS: ou este pedaço fica no n8n e manda o lead pelo Slack, ou vira sondagem da API da Guru a cada 5 min.",
    },
  ],
  nodes: [
    {
      id: "t1",
      kind: "trigger",
      title: "Webhook da Guru",
      sub: "n8n: Webhook",
      x: 0,
      y: 150,
      warn: "sem equivalente",
      info: [
        { t: "Veio do n8n", kv: [["Nó original", "Webhook (POST /guru)"]] },
        {
          t: "Sem equivalente",
          note: "A MÊTIS não recebe chamadas da internet e só roda com o Mac acordado. Saídas: deixar este pedaço no n8n e mandar o lead para a MÊTIS pelo Slack, ou trocar por sondagem da API da Guru a cada 5 min.",
        },
      ],
    },
    {
      id: "c0",
      kind: "code",
      title: "Normalizar o lead",
      sub: "Code → python",
      x: 210,
      y: 150,
      cost: "0 cota",
      info: [
        {
          t: "Veio do n8n",
          kv: [
            ["Nó original", "Code (JavaScript)"],
            ["Tradução", "Python, conferido com os 3 casos fixados no n8n"],
          ],
        },
      ],
    },
    {
      id: "i1",
      kind: "if",
      title: "Tem UTM?",
      sub: "IF",
      x: 420,
      y: 150,
      info: [
        {
          t: "Veio do n8n",
          kv: [
            ["Nó original", "IF"],
            ["Regra", "utm_source não está vazio"],
          ],
        },
      ],
    },
    {
      id: "a0",
      kind: "agent",
      title: "Inferir a origem",
      sub: "claude · barato",
      x: 560,
      y: 330,
      cost: "≈ 0,5% da cota de 5 h",
      schema: "origem: texto\nconfianca: número",
      info: [
        {
          t: "Veio do n8n",
          kv: [
            ["Nó original", "AI Agent (OpenAI)"],
            ["Tradução", "agente Claude, nível barato"],
          ],
        },
        {
          t: "Atenção",
          note: "No n8n este nó pagava API da OpenAI; aqui sai da cota do seu plano.",
        },
      ],
    },
    {
      id: "s1",
      kind: "tool",
      title: "Gravar no Supabase",
      sub: "supabase.inserir",
      x: 930,
      y: 150,
      cost: "0 cota",
      info: [
        {
          t: "Veio do n8n",
          kv: [
            ["Nó original", "Supabase · Insert"],
            ["Tradução", "supabase.inserir, tabela leads"],
          ],
        },
      ],
    },
    {
      id: "h1",
      kind: "code",
      title: "Avisar o SDR",
      sub: "HTTP Request",
      x: 1140,
      y: 150,
      warn: "revisar",
      info: [
        {
          t: "Veio do n8n",
          kv: [["Nó original", "HTTP Request (POST para a rota do CRM)"]],
        },
        {
          t: "Revisar",
          note: "Chamada HTTP solta, sem conector na central. Virou passo de Código; o segredo da rota precisa ir para o Keychain.",
        },
      ],
    },
  ],
  edges: [
    { from: "t1", to: "c0" },
    { from: "c0", to: "i1" },
    { from: "i1", to: "s1", label: "sim" },
    { from: "i1", to: "a0", label: "não" },
    { from: "a0", to: "s1" },
    { from: "s1", to: "h1" },
  ],
  runs: [],
};

// --- o caminho de uma execução ---------------------------------------------------------------

function incoming(flow: Flow, id: string) {
  return flow.edges.filter((e) => e.to === id);
}

/** Camadas por caminho mais longo a partir do gatilho: o que está na mesma camada roda junto. */
function layers(flow: Flow): string[][] {
  const level = new Map<string, number>();
  const visit = (id: string, seen: Set<string>): number => {
    const known = level.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0;
    seen.add(id);
    const preds = incoming(flow, id).map((e) => visit(e.from, seen));
    const value = preds.length ? Math.max(...preds) + 1 : 0;
    level.set(id, value);
    return value;
  };
  flow.nodes.forEach((n) => visit(n.id, new Set()));
  const out: string[][] = [];
  for (const [id, l] of level) (out[l] ??= []).push(id);
  return out.filter(Boolean);
}

/** Um passo não roda se todas as ligações que chegam nele estão mortas (ramo não escolhido, passo anterior parado). */
function isDead(flow: Flow, id: string, status: Record<string, Step | undefined>, outcome: Record<string, Branch>) {
  const ins = incoming(flow, id);
  if (!ins.length) return false;
  return ins.every((e) => {
    const from = status[e.from];
    if (from === "pulado" || from === "recusado" || from === "erro") return true;
    const node = flow.nodes.find((n) => n.id === e.from);
    return node?.kind === "if" && !!e.label && e.label !== (outcome[e.from] ?? "sim");
  });
}

function settled(flow: Flow, outcome: Record<string, Branch>): Record<string, StepResult> {
  const status: Record<string, Step> = {};
  for (const layer of layers(flow)) for (const id of layer) status[id] = isDead(flow, id, status, outcome) ? "pulado" : "ok";
  return Object.fromEntries(Object.entries(status).map(([id, s]) => [id, { s }]));
}

AURORA.runs = [
  {
    id: "r1",
    when: "ontem 20:50",
    how: "agendado",
    took: "6 min 10 s",
    quota: "Claude 5 h +2%",
    status: "ok",
    note: "você conversou com a Aurora na aba",
    steps: settled(AURORA, {}),
  },
  {
    id: "r2",
    when: "sex 20:50",
    how: "pulada: o Mac dormia",
    took: "—",
    quota: "0",
    status: "ok",
    steps: Object.fromEntries(AURORA.nodes.map((n) => [n.id, { s: "pulado" as Step }])),
  },
];
PRECEDENTES.runs = [
  {
    id: "r1",
    when: "hoje 11:12",
    how: "evento: nota nova",
    took: "48 s",
    quota: "Claude 5 h +1%",
    status: "ok",
    steps: settled(PRECEDENTES, { c1: "não" }),
  },
  {
    id: "r2",
    when: "ontem 22:10",
    how: "evento: nota nova",
    took: "1 min 05 s",
    quota: "Claude 5 h +1%",
    status: "ok",
    note: "1 conflito: virou tarefa no kanban",
    steps: settled(PRECEDENTES, { c1: "sim" }),
  },
];
PR.runs = [
  {
    id: "r1",
    when: "ter 16:20",
    how: "conector: check falhou",
    took: "22 min",
    quota: "Claude 5 h +9%",
    status: "ok",
    note: "você recusou uma vez com nota",
    steps: settled(PR, {}),
  },
];

const EXAMPLES = [BRIEFING, AURORA, PRECEDENTES, PR, FUNIL];

const IDEAS = [
  "Toda segunda às 9h, resumir os e-mails não lidos e mandar na minha DM do Slack",
  "Quando uma tarefa do kanban for para Em teste, abrir o navegador na porta do projeto",
  "Toda sexta às 18h, a Aurora fecha a semana de estudo e registra no Brain",
];

// --- utilidades -------------------------------------------------------------------------------

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const count = (v: unknown) => (v === undefined ? 0 : Array.isArray(v) ? v.length : 1);
const itemsLabel = (n: number) => `${n} ${n === 1 ? "item" : "itens"}`;

function duration(ms: number | undefined) {
  if (ms === undefined) return "";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
  return `${Math.round(ms / 60000)} min`;
}

function nextVersion(flow: Flow): Flow {
  return flow.draft === flow.published ? { ...flow, draft: flow.draft + 1 } : flow;
}

function collides(nodes: FlowNode[], x: number, y: number) {
  return nodes.some((n) => Math.abs(n.x - x) < 170 && Math.abs(n.y - y) < S + 60);
}

/** Proposta do "Claude" para o pedido escrito. No app de verdade, um Claude edita o YAML num terminal. */
function propose(text: string, anchor: FlowNode, flow: Flow): FlowNode {
  const t = fold(text);
  const base = {
    id: `n${Date.now().toString(36)}`,
    x: anchor.x + nodeW(anchor) + GAP,
    y: anchor.y,
    info: [] as Section[],
  };
  while (collides(flow.nodes, base.x, base.y)) base.y += S + 70;
  const said: Section = { t: "Você pediu", text };
  if (t.includes("clickup"))
    return {
      ...base,
      kind: "tool",
      title: "Tarefa no ClickUp",
      sub: "clickup.criar_tarefa",
      cost: "0 cota",
      info: [said],
    };
  if (t.includes("whats"))
    return {
      ...base,
      kind: "tool",
      title: "Mensagem no WhatsApp",
      sub: "whatsapp.enviar",
      people: true,
      info: [
        said,
        {
          t: "Atenção",
          note: "Fala com outras pessoas: a MÊTIS pede uma aprovação antes deste passo.",
        },
      ],
    };
  if (t.includes("brain") || t.includes("registr") || t.includes("anot"))
    return {
      ...base,
      kind: "brain",
      title: "Registrar no Brain",
      sub: "brain.registrar",
      info: [said],
    };
  if (t.includes("esper") || t.includes("aguard"))
    return {
      ...base,
      kind: "wait",
      title: "Esperar",
      sub: "tempo ou evento",
      info: [said],
    };
  const title = text.trim().replace(/^./, (c) => c.toUpperCase());
  return {
    ...base,
    kind: "agent",
    title: title.length > 38 ? `${title.slice(0, 36)}…` : title,
    sub: "claude · padrão",
    cost: "≈ 2% da cota de 5 h",
    info: [said, { t: "Pedido", text }],
  };
}

function draftFrom(text: string, keep: Pick<Flow, "id" | "file">): Flow {
  const t = fold(text);
  const event = /kanban|tarefa/.test(t);
  const aurora = t.includes("aurora");
  const when = /segunda/.test(t) ? "segunda, 9h" : /sexta/.test(t) ? "sexta, 18h" : event ? "tarefa mudou de coluna" : "a definir";
  return {
    ...keep,
    name: text.length > 46 ? `${text.slice(0, 44)}…` : text,
    when,
    state: "rascunho",
    draft: 1,
    published: null,
    where: "no Mac",
    notes: [],
    runs: [],
    nodes: [
      {
        id: "t1",
        kind: "trigger",
        title: event ? "Tarefa foi para Em teste" : when.replace(/^./, (c) => c.toUpperCase()),
        sub: event ? "evento da MÊTIS" : "agendado",
        x: 0,
        y: 120,
        info: [{ t: "Você pediu", text }],
      },
      {
        id: "a1",
        kind: "agent",
        title: aurora ? "Fechar a semana de estudo" : event ? "Achar a porta do projeto" : "Fazer o pedido",
        sub: aurora ? "Aurora · claude · padrão" : "claude · barato",
        who: aurora ? { name: "Aurora", seed: "auroraAurora", color: "#AF52DE" } : undefined,
        tools: aurora ? ["brain.ler"] : event ? ["metis.tarefa"] : [],
        x: 210,
        y: 120,
        cost: "≈ 2% da cota de 5 h",
        info: [{ t: "Pedido", text }],
      },
      {
        id: "m1",
        kind: aurora ? "brain" : "tool",
        title: event ? "Abrir o navegador" : aurora ? "Registrar no Brain" : "Aviso para você",
        sub: event ? "metis.web" : aurora ? "brain.registrar" : "slack.enviar_dm",
        x: 580,
        y: 120,
        info: [],
      },
    ],
    edges: [
      { from: "t1", to: "a1" },
      { from: "a1", to: "m1" },
    ],
  };
}

// --- pedaços de desenho ------------------------------------------------------------------------

function Glyph({ node, size = 30 }: { node: Pick<FlowNode, "kind" | "sub" | "who">; size?: number }) {
  if (node.kind === "tool") {
    const c = connectorOf(node.sub);
    if (c?.id === "metis") return <MetisMark size={Math.round(size * 0.8)} />;
    if (c)
      return (
        <span className="af-elem" style={{ color: c.color, fontSize: Math.round(size * 0.7) }}>
          {c.mono}
        </span>
      );
    return <Icon d={ICON.plug} size={size} strokeWidth={1.6} />;
  }
  if (node.kind === "agent") {
    if (node.who) return <GreekBust seed={node.who.seed} color={node.who.color} size={size >= 30 ? 32 : 16} />;
    return (
      <span className="af-claude" style={{ fontSize: Math.round(size * 0.85) }}>
        {node.sub.includes("codex") ? "◇" : "✻"}
      </span>
    );
  }
  return <Icon d={KIND[node.kind].icon!} size={size} strokeWidth={1.6} />;
}

function isPlain(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function cellText(v: unknown) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Table({ rows }: { rows: Record<string, unknown>[] }) {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  return (
    <div className="af-table-wrap">
      <table className="af-table">
        <thead>
          <tr>
            <th>#</th>
            {cols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="mono af-rownum">{i + 1}</td>
              {cols.map((c) => (
                <td key={c} data-num={typeof r[c] === "number" ? "true" : undefined}>
                  {cellText(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DataView({ value, view }: { value: unknown; view: "tabela" | "json" }) {
  if (view === "json") return <pre className="af-json mono">{JSON.stringify(value, null, 2)}</pre>;
  if (Array.isArray(value) && value.every(isPlain)) return <Table rows={value} />;
  if (isPlain(value)) {
    const entries = Object.entries(value);
    const nested = entries.filter(([, v]) => Array.isArray(v) && v.every(isPlain));
    const flat = entries.filter(([, v]) => !(Array.isArray(v) && v.every(isPlain)));
    return (
      <>
        {flat.length > 0 && <Table rows={[Object.fromEntries(flat)]} />}
        {nested.map(([k, v]) => (
          <div key={k} className="af-nested">
            <span className="af-caps">{k}</span>
            <Table rows={v as Record<string, unknown>[]} />
          </div>
        ))}
      </>
    );
  }
  return <pre className="af-json mono">{JSON.stringify(value, null, 2)}</pre>;
}

/** Expressões {{…}} aparecem como peças, para ficar claro o que vem de outro passo. */
function Expr({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\{\{[^}]+\}\})/g).map((part, i) =>
        /^\{\{[^}]+\}\}$/.test(part) ? (
          <span key={i} className="af-expr mono">
            {part.slice(2, -2).trim()}
          </span>
        ) : (
          part
        ),
      )}
    </>
  );
}

function SectionView({ sec }: { sec: Section }) {
  return (
    <section className="af-sec">
      <h4>{sec.t}</h4>
      {sec.kv && (
        <dl className="af-kv">
          {sec.kv.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {sec.text && (
        <p className="af-prompt">
          <Expr text={sec.text} />
        </p>
      )}
      {sec.chips && (
        <div className="af-chips">
          {sec.chips.map((c) => (
            <span key={c} className="chip">
              {c}
            </span>
          ))}
        </div>
      )}
      {sec.code && (
        <pre className="af-code mono">
          <Expr text={sec.code} />
        </pre>
      )}
      {sec.note && <p className="af-note">{sec.note}</p>}
    </section>
  );
}

function Segment<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="af-seg">
      {options.map(([v, label]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}>
          {label}
        </button>
      ))}
    </div>
  );
}

/** Modelo, ferramentas e saída do agente, pendurados embaixo do bloco. */
function agentParts(n: FlowNode) {
  const parts = n.sub.split(" · ");
  const provider = parts.find((p) => /claude|codex/.test(p)) ?? "claude";
  const level = parts[parts.indexOf(provider) + 1] ?? "padrão";
  const cy = n.y + S + 84;
  const tools = (n.tools ?? []).slice(0, 2);
  return {
    cy,
    ports: [
      { key: "modelo", label: "Modelo", x: n.x + AW * 0.15 },
      { key: "ferramentas", label: "Ferramentas", x: n.x + AW * 0.5 },
      { key: "saida", label: "Saída", x: n.x + AW * 0.85 },
    ],
    model: { x: n.x + AW * 0.15, provider, level },
    tools: tools.length
      ? tools.map((t, i) => ({
          x: n.x + AW * 0.5 + (i - (tools.length - 1) / 2) * 58,
          name: t,
          c: connectorOf(t),
        }))
      : [{ x: n.x + AW * 0.5, name: "", c: null as Connector | null }],
    out: { x: n.x + AW * 0.85, has: !!n.schema },
  };
}

// --- tela ---------------------------------------------------------------------------------------

export function AutomationsView() {
  const [flows, setFlows] = useState<Flow[]>(EXAMPLES);
  const [currentId, setCurrentId] = useState(EXAMPLES[0].id);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [panel, setPanel] = useState<PanelCtx | null>(null);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [infoOpen, setInfoOpen] = useState(false);
  const [mode, setMode] = useState<"editor" | "runs">("editor");
  const [runId, setRunId] = useState<string | null>(null);
  const [live, setLive] = useState<Record<string, StepResult> | null>(null);
  const [running, setRunning] = useState(false);
  const [waitingId, setWaitingId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(0.9);
  const [pan, setPan] = useState({ x: 60, y: 60 });
  const [ask, setAsk] = useState("");
  const [thinking, setThinking] = useState(false);
  const [proposal, setProposal] = useState<{
    node: FlowNode;
    from: string;
  } | null>(null);
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const [view, setView] = useState<"tabela" | "json">("tabela");
  const [paramTab, setParamTab] = useState<"parametros" | "ajustes">("parametros");
  const [pinned, setPinned] = useState<Record<string, boolean>>({});
  const [toast, setToast] = useState<string | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const runToken = useRef(0);
  const approver = useRef<((ok: boolean) => void) | null>(null);
  const hoverTimer = useRef<number | null>(null);
  const lastClick = useRef<{ id: string; t: number } | null>(null);

  const flow = flows.find((f) => f.id === currentId) ?? flows[0];
  const run = mode === "runs" ? (flow.runs.find((r) => r.id === runId) ?? flow.runs[0] ?? null) : null;
  const selected = flow.nodes.find((n) => n.id === selectedId) ?? null;
  const detail = flow.nodes.find((n) => n.id === detailId) ?? null;
  const editing = mode === "editor";

  /** O que pinta o canvas: a execução escolhida no histórico, ou o teste mais recente no editor. */
  const shown: Record<string, StepResult> = (mode === "runs" ? run?.steps : live) ?? {};
  const statusOf = (id: string) => shown[id]?.s;

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 7000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(
    () => () => {
      runToken.current += 1;
      approver.current = null;
    },
    [],
  );

  const update = (change: (f: Flow) => Flow) => setFlows((all) => all.map((f) => (f.id === flow.id ? change(f) : f)));

  /** Enquadra o fluxo no canvas, deixando espaço embaixo para a barra de testar. */
  const fit = (target: Flow = flow) => {
    const box = canvas.current?.getBoundingClientRect();
    if (!box || !target.nodes.length) {
      setZoom(1);
      setPan({ x: 60, y: 60 });
      return;
    }
    const xs = [...target.nodes.map((n) => n.x), ...target.notes.map((n) => n.x)];
    const ys = [...target.nodes.map((n) => n.y), ...target.notes.map((n) => n.y)];
    const minX = Math.min(...xs) - 20;
    const minY = Math.min(...ys) - 40;
    const maxX = Math.max(...target.nodes.map((n) => n.x + nodeW(n) + 40), ...target.notes.map((n) => n.x + n.w));
    const maxY = Math.max(...target.nodes.map((n) => n.y + S + (n.kind === "agent" ? 150 : 60)), ...target.notes.map((n) => n.y + 120));
    const scale = Math.max(0.5, Math.min(1.1, (box.width - 80) / (maxX - minX), (box.height - 150) / (maxY - minY)));
    setZoom(scale);
    setPan({
      x: (box.width - (maxX - minX) * scale) / 2 - minX * scale,
      y: (box.height - 90 - (maxY - minY) * scale) / 2 - minY * scale,
    });
  };

  const stopRun = () => {
    runToken.current += 1;
    approver.current?.(false);
    approver.current = null;
    setWaitingId(null);
    setRunning(false);
  };

  const resetView = () => {
    stopRun();
    setLive(null);
    setSelectedId(null);
    setDetailId(null);
    setPanel(null);
    setRunId(null);
    setProposal(null);
    setInfoOpen(false);
  };

  const choose = (id: string) => {
    resetView();
    setCurrentId(id);
    const target = flows.find((f) => f.id === id);
    if (target) window.requestAnimationFrame(() => fit(target));
  };

  useEffect(() => {
    fit();
    const el = canvas.current;
    if (!el) return;
    let last = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (Math.abs(el.clientWidth - last) > 40) {
        last = el.clientWidth;
        fit();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- executar o teste, passo a passo -----------------------------------------------------------

  const sampleOut = (id: string) => flow.runs.find((r) => r.steps[id]?.out !== undefined && r.steps[id]?.s === "ok")?.steps[id]?.out;

  const test = async () => {
    if (running || !flow.nodes.length) return;
    const token = ++runToken.current;
    const snapshot = flow;
    const outcome = snapshot.outcome ?? {};
    const started = Date.now();
    const now: Record<string, StepResult> = {};
    const statusMap = () => Object.fromEntries(Object.entries(now).map(([k, v]) => [k, v.s]));
    setRunning(true);
    setLive({});
    setDetailId(null);
    for (const layer of layers(snapshot)) {
      const active = layer.filter((id) => !isDead(snapshot, id, statusMap(), outcome));
      layer.filter((id) => !active.includes(id)).forEach((id) => (now[id] = { s: "pulado", note: "ramo não escolhido no teste" }));
      active.forEach((id) => (now[id] = { s: "running" }));
      setLive({ ...now });
      await Promise.all(
        active.map(async (id) => {
          const node = snapshot.nodes.find((n) => n.id === id)!;
          const t0 = Date.now();
          await sleep(node.off ? 250 : node.kind === "agent" ? 2400 : node.kind === "trigger" ? 450 : 850);
          if (token !== runToken.current) return;
          if (node.kind === "approval" && !node.off) {
            now[id] = { s: "esperando" };
            setLive({ ...now });
            setWaitingId(id);
            const ok = await new Promise<boolean>((resolve) => (approver.current = resolve));
            approver.current = null;
            setWaitingId(null);
            if (token !== runToken.current) return;
            now[id] = {
              s: ok ? "ok" : "recusado",
              ms: Date.now() - t0,
              out: ok ? sampleOut(id) : undefined,
              note: ok ? "aprovado por você no teste" : "recusado por você no teste",
            };
          } else {
            const fixed = pinned[`${snapshot.id}:${id}`];
            now[id] = {
              s: "ok",
              ms: Date.now() - t0,
              out: sampleOut(id),
              note: node.off
                ? "desligado: os dados passaram direto"
                : node.people
                  ? "ensaio: no teste, o envio foi para a sua DM, não para outras pessoas"
                  : fixed
                    ? "usou os dados fixados, sem chamar o conector"
                    : node.kind === "agent"
                      ? "no app de verdade: terminal do agente, tokens e cota gastos aqui"
                      : undefined,
            };
          }
          setLive({ ...now });
        }),
      );
      if (token !== runToken.current) return;
    }
    setRunning(false);
    const record: Run = {
      id: `t${Date.now().toString(36)}`,
      when: "agora",
      how: `teste do rascunho v${snapshot.draft}`,
      took: duration(Date.now() - started),
      quota: snapshot.nodes.some((n) => n.kind === "agent") ? "Claude 5 h +3%" : "0",
      status: "ok",
      note: snapshot.nodes.some((n) => n.people) ? "passos com outras pessoas rodaram em ensaio" : undefined,
      steps: { ...now },
    };
    setFlows((all) => all.map((f) => (f.id === snapshot.id ? { ...f, runs: [record, ...f.runs] } : f)));
    setToast("Teste concluído. Dê dois cliques num passo para ver o que entrou e o que saiu.");
  };

  const answerApproval = (ok: boolean) => approver.current?.(ok);

  // --- editar -------------------------------------------------------------------------------------

  const removeNode = (id: string) => {
    update((f) =>
      nextVersion({
        ...f,
        nodes: f.nodes.filter((n) => n.id !== id),
        edges: f.edges.filter((e) => e.from !== id && e.to !== id),
      }),
    );
    setSelectedId(null);
    setDetailId(null);
  };

  const toggleOff = (id: string) =>
    update((f) =>
      nextVersion({
        ...f,
        nodes: f.nodes.map((n) => (n.id === id ? { ...n, off: !n.off } : n)),
      }),
    );

  const removeEdge = (edge: FlowEdge) => {
    update((f) =>
      nextVersion({
        ...f,
        edges: f.edges.filter((e) => !(e.from === edge.from && e.to === edge.to)),
      }),
    );
    setHoverEdge(null);
  };

  const openPanel = (ctx: PanelCtx) => {
    setPanel(ctx);
    setSearch("");
    setOpenGroup(null);
    setInfoOpen(false);
  };

  const addStep = (draft: Draft) => {
    const id = `n${Date.now().toString(36)}`;
    const ctx = panel ?? {};
    const box = canvas.current?.getBoundingClientRect();
    update((f) => {
      let nodes = f.nodes;
      let edges = f.edges;
      let x = box ? Math.round((box.width / 2 - pan.x) / zoom - nodeW(draft) / 2) : 200;
      let y = box ? Math.round((box.height / 2 - pan.y) / zoom - S / 2) : 200;
      const between = ctx.between;
      const after = ctx.after ? f.nodes.find((n) => n.id === ctx.after) : null;
      if (between) {
        const a = f.nodes.find((n) => n.id === between.from)!;
        const b = f.nodes.find((n) => n.id === between.to)!;
        const shift = nodeW(draft) + GAP;
        x = b.x;
        y = Math.round(a.kind === "if" ? b.y : (a.y + b.y) / 2);
        nodes = nodes.map((n) => (n.x >= b.x ? { ...n, x: n.x + shift } : n));
        edges = [
          ...edges.filter((e) => !(e.from === between.from && e.to === between.to)),
          { from: a.id, to: id, label: between.label },
          { from: id, to: b.id },
        ];
      } else if (after) {
        x = after.x + nodeW(after) + GAP;
        y = after.y + (ctx.label === "sim" ? -80 : ctx.label === "não" ? 100 : 0);
        while (collides(nodes, x, y)) y += S + 70;
        edges = [...edges, { from: after.id, to: id, label: ctx.label }];
      } else if (!f.nodes.length) {
        x = 0;
        y = 120;
      }
      return nextVersion({
        ...f,
        nodes: [...nodes, { ...draft, id, x, y }],
        edges,
      });
    });
    setPanel(null);
    setSelectedId(id);
    setDetailId(id);
    setParamTab("parametros");
  };

  const sendAsk = async (text = ask.trim()) => {
    if (!text || thinking) return;
    setThinking(true);
    await sleep(1300);
    setThinking(false);
    setAsk("");
    if (!flow.nodes.length) {
      const made = draftFrom(text, { id: flow.id, file: flow.file });
      setFlows((all) => all.map((f) => (f.id === flow.id ? made : f)));
      window.requestAnimationFrame(() => fit(made));
      setToast("O Claude montou 3 passos. Dê dois cliques em cada um para conferir antes de publicar.");
      return;
    }
    const anchor = selected ?? [...flow.nodes].sort((a, b) => b.x + nodeW(b) - (a.x + nodeW(a)))[0];
    const node = propose(text, anchor, flow);
    setProposal({ node, from: anchor.id });
    window.requestAnimationFrame(() => fit({ ...flow, nodes: [...flow.nodes, node] }));
  };

  const applyProposal = () => {
    if (!proposal) return;
    update((f) =>
      nextVersion({
        ...f,
        nodes: [...f.nodes, proposal.node],
        edges: [...f.edges, { from: proposal.from, to: proposal.node.id }],
      }),
    );
    setSelectedId(proposal.node.id);
    setProposal(null);
  };

  const addNote = () => {
    const box = canvas.current?.getBoundingClientRect();
    const note: StickyNote = {
      id: `k${Date.now().toString(36)}`,
      x: box ? Math.round((box.width / 2 - pan.x) / zoom - 130) : 100,
      y: box ? Math.round((box.height / 3 - pan.y) / zoom) : 100,
      w: 260,
      title: "Nota",
      text: "Notas explicam o porquê do fluxo para você daqui a três meses. Não rodam.",
    };
    update((f) => ({ ...f, notes: [...f.notes, note] }));
  };

  const newFlow = () => {
    const id = `nova-${Date.now().toString(36)}`;
    const blank: Flow = {
      id,
      name: "Nova automação",
      file: `~/.harness/automacoes/${id}.yaml`,
      when: "—",
      state: "rascunho",
      draft: 1,
      published: null,
      where: "no Mac",
      nodes: [],
      edges: [],
      notes: [],
      runs: [],
    };
    resetView();
    setMode("editor");
    setFlows((all) => [blank, ...all]);
    setCurrentId(id);
    setZoom(1);
    setPan({ x: 60, y: 60 });
  };

  const publish = () => {
    update((f) => ({
      ...f,
      published: f.draft,
      state: f.state === "rascunho" ? "pausada" : f.state,
    }));
    setToast(`v${flow.draft} publicada. É ela que roda a partir de agora; o próximo rascunho não muda nada até você publicar de novo.`);
  };

  // Esc fecha o que estiver por cima; Delete tira o passo escolhido.
  const keyRef = useRef<(event: KeyboardEvent) => void>(() => undefined);
  keyRef.current = (event: KeyboardEvent) => {
    const typing = (event.target as HTMLElement | null)?.closest("input, textarea");
    if (event.key === "Escape") {
      if (detailId) setDetailId(null);
      else if (panel) setPanel(null);
      else if (infoOpen) setInfoOpen(false);
      else setSelectedId(null);
    } else if ((event.key === "Delete" || event.key === "Backspace") && !typing && selectedId && editing && !detailId) {
      removeNode(selectedId);
    }
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => keyRef.current(event);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // --- arrastar passos, notas e o canvas ----------------------------------------------------------

  const drag = useRef<{
    kind: "node" | "note" | "pan";
    id?: string;
    sx: number;
    sy: number;
    ox: number;
    oy: number;
    moved: boolean;
  } | null>(null);

  const onItemDown = (event: ReactPointerEvent, kind: "node" | "note", item: { id: string; x: number; y: number }) => {
    if ((event.target as HTMLElement).closest("button")) return;
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = {
      kind,
      id: item.id,
      sx: event.clientX,
      sy: event.clientY,
      ox: item.x,
      oy: item.y,
      moved: false,
    };
  };

  const onCanvasDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = {
      kind: "pan",
      sx: event.clientX,
      sy: event.clientY,
      ox: pan.x,
      oy: pan.y,
      moved: false,
    };
  };

  const onMove = (event: ReactPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = event.clientX - d.sx;
    const dy = event.clientY - d.sy;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true;
    if (d.kind === "pan") setPan({ x: d.ox + dx, y: d.oy + dy });
    else if (d.kind === "node" && editing)
      update((f) => ({
        ...f,
        nodes: f.nodes.map((n) =>
          n.id === d.id
            ? {
                ...n,
                x: Math.round(d.ox + dx / zoom),
                y: Math.round(d.oy + dy / zoom),
              }
            : n,
        ),
      }));
    else if (d.kind === "note" && editing)
      update((f) => ({
        ...f,
        notes: f.notes.map((n) =>
          n.id === d.id
            ? {
                ...n,
                x: Math.round(d.ox + dx / zoom),
                y: Math.round(d.oy + dy / zoom),
              }
            : n,
        ),
      }));
  };

  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved) return;
    if (d.kind === "node" && d.id) {
      const now = Date.now();
      const twice = lastClick.current?.id === d.id && now - lastClick.current.t < 380;
      lastClick.current = { id: d.id, t: now };
      setSelectedId(d.id);
      if (twice) {
        setDetailId(d.id);
        setParamTab("parametros");
      }
    } else if (d.kind === "pan") {
      setSelectedId(null);
    }
  };

  const zoomBy = (factor: number) => {
    const box = canvas.current?.getBoundingClientRect();
    const next = Math.max(0.4, Math.min(1.6, zoom * factor));
    if (box) {
      const cx = box.width / 2;
      const cy = box.height / 2;
      setPan({
        x: cx - ((cx - pan.x) / zoom) * next,
        y: cy - ((cy - pan.y) / zoom) * next,
      });
    }
    setZoom(next);
  };

  const keepEdge = (key: string | null) => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
    if (key) setHoverEdge(key);
  };
  const dropEdge = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => setHoverEdge(null), 220);
  };

  // --- geometria ------------------------------------------------------------------------------------

  const allNodes = proposal ? [...flow.nodes, proposal.node] : flow.nodes;
  const byId = new Map(allNodes.map((n) => [n.id, n]));
  const allEdges = proposal ? [...flow.edges, { from: proposal.from, to: proposal.node.id }] : flow.edges;
  const portIn = (n: FlowNode) => ({ x: n.x, y: n.y + S / 2 });
  const portOut = (n: FlowNode, label?: Branch) => ({
    x: n.x + nodeW(n),
    y: n.y + (n.kind === "if" && label ? (label === "sim" ? S * 0.3 : S * 0.7) : S / 2),
  });
  const bez = (a: { x: number; y: number }, b: { x: number; y: number }) => {
    const dx = Math.max(40, Math.abs(b.x - a.x) / 2);
    return {
      d: `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x - 3},${b.y}`,
      mid: {
        x: (a.x + 3 * (a.x + dx) + 3 * (b.x - dx) + b.x) / 8,
        y: (a.y + 3 * a.y + 3 * b.y + b.y) / 8,
      },
    };
  };
  const edgeState = (e: FlowEdge) => {
    const from = shown[e.from];
    const to = statusOf(e.to);
    if (from?.s === "ok" && to && to !== "pulado" && to !== "recusado") return "ok";
    return undefined;
  };

  /** Saídas sem ligação ganham o "+" na ponta, para emendar o próximo passo. */
  const stubs = editing
    ? flow.nodes.flatMap((n) => {
        const outs: (Branch | undefined)[] = n.kind === "if" ? ["sim", "não"] : [undefined];
        return outs
          .filter((label) => !flow.edges.some((e) => e.from === n.id && (n.kind !== "if" || e.label === label)))
          .map((label) => ({ node: n, label, p: portOut(n, label) }));
      })
    : [];

  const changed = flow.published === null || flow.draft !== flow.published;
  const okRuns = flow.runs.filter((r) => r.status === "ok").length;
  const doneSteps = Object.values(live ?? {}).filter((r) => r.s !== "running").length;
  const waitingNode = waitingId ? flow.nodes.find((n) => n.id === waitingId) : null;

  // Dados do painel do passo: a execução escolhida, o teste de agora ou a última execução com dados.
  const dataRun: { label: string; steps: Record<string, StepResult> } | null =
    mode === "runs" && run
      ? { label: `da execução de ${run.when}`, steps: run.steps }
      : live && Object.keys(live).length
        ? { label: "do teste de agora", steps: live }
        : (() => {
            const r = flow.runs.find((x) => Object.values(x.steps).some((s) => s.out !== undefined));
            return r
              ? {
                  label: r.when === "agora" ? "do teste de agora" : `da execução de ${r.when}`,
                  steps: r.steps,
                }
              : null;
          })();

  // --- desenho --------------------------------------------------------------------------------------

  const renderNode = (n: FlowNode, ghost = false) => {
    const meta = KIND[n.kind];
    const s = ghost ? undefined : statusOf(n.id);
    const w = nodeW(n);
    const style = {
      left: n.x,
      top: n.y,
      width: w,
      height: S,
      ["--k" as string]: meta.color,
    } as CSSProperties;
    const parts = n.kind === "agent" ? agentParts(n) : null;
    return (
      <div key={n.id} className="af-nwrap" data-off={n.off ? "true" : undefined}>
        <div
          className="af-n"
          data-kind={n.kind}
          data-status={s}
          data-selected={selectedId === n.id ? "true" : undefined}
          data-proposal={ghost ? "true" : undefined}
          data-warn={n.warn ? "true" : undefined}
          style={style}
          onPointerDown={ghost ? undefined : (event) => onItemDown(event, "node", n)}
        >
          {n.kind === "agent" ? (
            <div className="af-n-agent">
              <span className="af-n-avatar">
                <Glyph node={n} size={32} />
              </span>
              <span className="af-n-text">
                <b>{ghost ? `proposta: ${n.title}` : n.title}</b>
                <span className="mono">{n.who ? n.who.name : "Claude Code"}</span>
                {n.cost && <span className="af-cost mono">{n.cost}</span>}
              </span>
            </div>
          ) : (
            <span className="af-n-glyph">
              <Glyph node={n} size={32} />
            </span>
          )}
          {n.kind === "trigger" && (
            <span className="af-bolt" title="Gatilho">
              <Icon d={P.bolt} size={11} strokeWidth={2} />
            </span>
          )}
          {n.people && (
            <span className="af-lock" title="Fala com outras pessoas: só roda depois de uma aprovação, e vira ensaio no teste">
              <Icon d={P.lock} size={10} strokeWidth={2.2} />
            </span>
          )}
          {s && s !== "pulado" && (
            <span className="af-st" data-step={s} title={STEP_LABEL[s]}>
              {s === "running" ? (
                <span className="af-spin" />
              ) : s === "ok" ? (
                <Icon d={ICON.check} size={11} strokeWidth={3} />
              ) : s === "erro" ? (
                "!"
              ) : s === "esperando" ? (
                "‖"
              ) : (
                "✕"
              )}
            </span>
          )}
          {pinned[`${flow.id}:${n.id}`] && (
            <span className="af-pinned" title="Dados fixados: o teste usa estes dados em vez de chamar o conector">
              <Icon d={P.pin} size={10} strokeWidth={2} />
            </span>
          )}
          {n.kind !== "trigger" && <span className="af-port in" />}
          {n.kind === "if" ? (
            <>
              <span className="af-port out" style={{ top: S * 0.3 }} />
              <span className="af-port out" style={{ top: S * 0.7 }} />
              <span className="af-branch mono" style={{ top: S * 0.3 }}>
                sim
              </span>
              <span className="af-branch mono" data-no="true" style={{ top: S * 0.7 }}>
                não
              </span>
            </>
          ) : (
            <span className="af-port out" />
          )}
          {editing && !ghost && (
            <div className="af-n-tools">
              <button
                type="button"
                title="Testar só este passo"
                onClick={() => setToast(`«${n.title}» rodaria sozinho, com as entradas da última execução. O resultado aparece na saída do passo.`)}
              >
                <Icon d={P.play} size={10} strokeWidth={2.2} />
              </button>
              <button type="button" title={n.off ? "Ligar o passo" : "Desligar o passo (os dados passam direto)"} onClick={() => toggleOff(n.id)}>
                <Icon d={P.power} size={11} strokeWidth={2.2} />
              </button>
              <button type="button" title="Tirar o passo" onClick={() => removeNode(n.id)}>
                <Icon d={ICON.trash} size={11} strokeWidth={2} />
              </button>
            </div>
          )}
        </div>
        {n.kind !== "agent" && (
          <div className="af-n-label" style={{ left: n.x + w / 2 - 85, top: n.y + S + 8 }}>
            <b>{ghost ? `proposta: ${n.title}` : n.title}</b>
            <span className="mono">{n.sub}</span>
            {n.warn && <span className="af-warn mono">⚠ {n.warn}</span>}
          </div>
        )}
        {parts && (
          <>
            {parts.ports.map((p) => (
              <span key={p.key} className="af-sub-port" style={{ left: p.x - 5, top: n.y + S - 5 }} />
            ))}
            {parts.ports.map((p) => (
              <span key={`${p.key}-l`} className="af-sub-label mono" style={{ left: p.x - 40, top: n.y + S + 12 }}>
                {p.label}
              </span>
            ))}
            <div
              className="af-sub"
              data-alt={n.alt ? "true" : undefined}
              style={{ left: parts.model.x - 18, top: parts.cy - 18 }}
              title={n.alt ? `Alternativa por cota: ${n.alt}` : undefined}
            >
              <span className="af-claude">{parts.model.provider === "codex" ? "◇" : "✻"}</span>
            </div>
            <span className="af-sub-name mono" style={{ left: parts.model.x - 36, top: parts.cy + 23 }}>
              {parts.model.provider} · {parts.model.level}
              {n.alt && <i>↻ codex</i>}
            </span>
            {parts.tools.map((t) => (
              <div key={`${t.name}-${t.x}`}>
                <div
                  className="af-sub"
                  data-empty={!t.name ? "true" : undefined}
                  style={{ left: t.x - 18, top: parts.cy - 18 }}
                  title={t.name || "Nenhuma ferramenta liberada"}
                >
                  {t.c?.id === "metis" ? (
                    <MetisMark size={16} />
                  ) : t.c ? (
                    <span className="af-elem" style={{ color: t.c.color, fontSize: 14 }}>
                      {t.c.mono}
                    </span>
                  ) : (
                    "+"
                  )}
                </div>
                <span className="af-sub-name mono" style={{ left: t.x - 36, top: parts.cy + 23 }}>
                  {t.name ? t.name.split(".")[1] : "nenhuma"}
                </span>
              </div>
            ))}
            <div
              className="af-sub"
              data-empty={!parts.out.has ? "true" : undefined}
              style={{ left: parts.out.x - 18, top: parts.cy - 18 }}
              title={n.schema ?? "Saída livre"}
            >
              <span className="mono af-brace">{parts.out.has ? "{ }" : "+"}</span>
            </div>
            <span className="af-sub-name mono" style={{ left: parts.out.x - 36, top: parts.cy + 23 }}>
              {parts.out.has ? "formato" : "livre"}
            </span>
          </>
        )}
      </div>
    );
  };

  const matches = (text: string) => !search.trim() || fold(text).includes(fold(search.trim()));

  const renderPanel = () => {
    const trigger = !!panel?.trigger || !flow.nodes.some((n) => n.kind === "trigger");
    const after = panel?.after ? flow.nodes.find((n) => n.id === panel.after) : null;
    const searching = !!search.trim();
    const toolItems = CATALOG.flatMap((c) => c.tools.map((t) => ({ c, t }))).filter(({ c, t }) => matches(c.name + t.title + t.name));
    const triggers = TRIGGERS.filter((t) => matches(t.title + t.hint));
    const agents = GALLERY.filter((g) => matches(g.label + g.sub));
    const logic = LOGIC.filter((k) => matches(KIND[k].label + KIND[k].hint));
    const nothing = searching && !toolItems.length && !agents.length && !logic.length && !(trigger && triggers.length);
    const pickTool = (c: Connector, t: Connector["tools"][number]) =>
      addStep({
        kind: c.id === "brain" ? "brain" : "tool",
        title: t.title,
        sub: t.name,
        people: t.people,
        cost: "0 cota",
        info: [{ t: "Ferramenta", kv: [["Chama", t.name]] }],
      });
    const elem = (c: Connector) =>
      c.id === "metis" ? (
        <MetisMark size={15} />
      ) : (
        <span className="af-elem" style={{ color: c.color }}>
          {c.mono}
        </span>
      );
    return (
      <aside className="af-drawer" onPointerDown={(event) => event.stopPropagation()}>
        <header className="af-drawer-head">
          <div>
            <h3>{trigger ? "Quando ela começa?" : "O que acontece depois?"}</h3>
            <span className="small">
              {panel?.between
                ? "entra no meio da ligação"
                : after
                  ? `depois de «${after.title}»${panel?.label ? `, no ramo ${panel.label}` : ""}`
                  : "solto no canvas; ligue depois"}
            </span>
          </div>
          <button type="button" className="icon-btn" aria-label="Fechar" onClick={() => setPanel(null)}>
            <Icon d={ICON.close} size={14} />
          </button>
        </header>
        <label className="af-search">
          <Icon d={ICON.search} size={13} strokeWidth={2} />
          <input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar passo, conector ou agente…" />
        </label>
        <div className="af-drawer-body">
          {nothing && <p className="af-empty-note af-drawer-empty">Nada com «{search.trim()}». Tente o nome do conector ou o que o passo faz.</p>}
          {trigger && triggers.length > 0 && (
            <section>
              <h4 className="af-caps">Gatilhos</h4>
              {triggers.map((t) => (
                <button
                  key={t.title}
                  type="button"
                  className="af-pick"
                  onClick={() =>
                    addStep({
                      kind: "trigger",
                      title: t.title,
                      sub: t.sub,
                      info: [{ t: "Gatilho", note: t.hint }],
                    })
                  }
                >
                  <span className="af-pick-icon" style={{ color: KIND.trigger.color }}>
                    <Icon d={P.bolt} size={16} strokeWidth={1.8} />
                  </span>
                  <span>
                    <b>{t.title}</b>
                    <span className="small">{t.hint}</span>
                  </span>
                </button>
              ))}
            </section>
          )}
          {(!trigger || searching) && (
            <>
              {agents.length > 0 && (
                <section>
                  <h4 className="af-caps">Agentes</h4>
                  <div className="af-agents">
                    {agents.map((g) => (
                      <button
                        key={g.label}
                        type="button"
                        className="af-agent-pick"
                        onClick={() =>
                          addStep({
                            kind: "agent",
                            title: g.who ? `Pedido para ${g.label}` : "Novo pedido",
                            sub: g.sub,
                            who: g.who,
                            tools: [],
                            cost: "≈ 2% da cota de 5 h",
                            info: [
                              {
                                t: "Pedido",
                                text: "Escreva o que o agente deve fazer com o que chega do passo anterior.",
                              },
                            ],
                          })
                        }
                      >
                        <span className="af-agent-face">
                          {g.who ? <GreekBust seed={g.who.seed} color={g.who.color} size={32} /> : <span className="af-claude">{g.glyph}</span>}
                        </span>
                        <b>{g.label}</b>
                        <span className="mono small">{g.sub.split(" · ").slice(-2).join(" · ")}</span>
                      </button>
                    ))}
                  </div>
                </section>
              )}
              {(!searching || toolItems.length > 0) && (
                <section>
                  <h4 className="af-caps">Conectores</h4>
                  {searching
                    ? toolItems.map(({ c, t }) => (
                        <button key={t.name} type="button" className="af-pick" onClick={() => pickTool(c, t)}>
                          <span className="af-pick-icon">{elem(c)}</span>
                          <span>
                            <b>{t.title}</b>
                            <span className="small mono">{t.name}</span>
                          </span>
                          {t.people && (
                            <span className="af-people" title="Fala com outras pessoas">
                              <Icon d={P.lock} size={11} strokeWidth={2} />
                            </span>
                          )}
                        </button>
                      ))
                    : CATALOG.map((c) => (
                        <div key={c.id} className="af-group" data-open={openGroup === c.id ? "true" : undefined}>
                          <button type="button" className="af-pick" onClick={() => setOpenGroup((g) => (g === c.id ? null : c.id))}>
                            <span className="af-pick-icon">{elem(c)}</span>
                            <span>
                              <b>{c.name}</b>
                              <span className="small">{c.tools.length} ferramentas</span>
                            </span>
                            <span className="af-chev">
                              <Icon d={ICON.chevron} size={13} />
                            </span>
                          </button>
                          {openGroup === c.id &&
                            c.tools.map((t) => (
                              <button key={t.name} type="button" className="af-pick af-sub-pick" onClick={() => pickTool(c, t)}>
                                <span>
                                  <b>{t.title}</b>
                                  <span className="small mono">{t.name}</span>
                                </span>
                                {t.people && (
                                  <span className="af-people" title="Fala com outras pessoas">
                                    <Icon d={P.lock} size={11} strokeWidth={2} />
                                  </span>
                                )}
                              </button>
                            ))}
                        </div>
                      ))}
                </section>
              )}
              {logic.length > 0 && (
                <section>
                  <h4 className="af-caps">Lógica e dados</h4>
                  {logic.map((k) => (
                    <button
                      key={k}
                      type="button"
                      className="af-pick"
                      onClick={() =>
                        addStep({
                          kind: k,
                          title: KIND[k].label,
                          sub: "a configurar",
                          info: [{ t: KIND[k].label, note: KIND[k].hint }],
                        })
                      }
                    >
                      <span className="af-pick-icon" style={{ color: KIND[k].color }}>
                        <Icon d={KIND[k].icon!} size={16} strokeWidth={1.8} />
                      </span>
                      <span>
                        <b>{KIND[k].label}</b>
                        <span className="small">{KIND[k].hint}</span>
                      </span>
                    </button>
                  ))}
                </section>
              )}
            </>
          )}
        </div>
        <footer className="af-drawer-foot small">Cada conta ligada em Conectores aparece aqui com as ferramentas dela, sem configurar nada.</footer>
      </aside>
    );
  };

  const renderDetail = (n: FlowNode) => {
    const preds = flow.edges
      .filter((e) => e.to === n.id)
      .map((e) => flow.nodes.find((x) => x.id === e.from))
      .filter((x): x is FlowNode => !!x);
    const input = dataRun ? preds.map((p) => ({ node: p, r: dataRun.steps[p.id] })).filter((x) => x.r?.out !== undefined) : [];
    const mine = dataRun?.steps[n.id];
    const pinKey = `${flow.id}:${n.id}`;
    const waiting = waitingId === n.id;
    const ajustes: Section[] = [
      {
        t: "Se der erro",
        kv: [
          ["Fazer", "parar a automação e avisar você"],
          ["Tentar de novo", "2 vezes, com 30 s entre elas"],
        ],
      },
      {
        t: "Ligado",
        kv: [["Estado", n.off ? "desligado: os dados passam direto" : "ligado"]],
      },
      n.kind === "agent"
        ? {
            t: "Cota",
            kv: [
              ["Custo médio", n.cost ?? "—"],
              ["Se a cota apertar", n.alt ?? "espera a janela abrir"],
            ],
          }
        : {
            t: "Cota",
            note: "Este passo é determinístico: não abre terminal e não gasta cota do plano.",
          },
    ];
    return (
      <div className="af-ndv" onPointerDown={(event) => event.stopPropagation()}>
        <header className="af-ndv-head">
          <button type="button" className="btn" onClick={() => setDetailId(null)}>
            <Icon d={P.back} size={13} strokeWidth={2} /> Canvas
          </button>
          <span className="af-ndv-icon" style={{ ["--k" as string]: KIND[n.kind].color } as CSSProperties}>
            <Glyph node={n} size={22} />
          </span>
          <div className="af-ndv-title">
            <span className="af-caps" style={{ color: KIND[n.kind].color }}>
              {KIND[n.kind].label}
            </span>
            <h3>{n.title}</h3>
          </div>
          <span className="mono small af-ndv-sub">{n.sub}</span>
          <span className="af-spacer" />
          {editing && (
            <button
              type="button"
              className="btn primary"
              onClick={() => setToast(`«${n.title}» rodaria sozinho com a entrada da esquerda, e a saída apareceria à direita.`)}
            >
              <Icon d={P.play} size={11} strokeWidth={2} /> Testar passo
            </button>
          )}
        </header>
        <div className="af-ndv-body">
          <section className="af-ndv-col">
            <header>
              <span className="af-caps">Entrada</span>
              <Segment
                value={view}
                options={[
                  ["tabela", "Tabela"],
                  ["json", "JSON"],
                ]}
                onChange={setView}
              />
            </header>
            <div className="af-ndv-scroll">
              {n.kind === "trigger" ? (
                <p className="af-empty-note">O gatilho é o começo: não recebe nada, só dispara.</p>
              ) : input.length ? (
                input.map(({ node: p, r }) => (
                  <div key={p.id} className="af-io-block">
                    <span className="af-io-from mono">
                      de «{p.title}» · {itemsLabel(count(r!.out))}
                    </span>
                    <DataView value={r!.out} view={view} />
                  </div>
                ))
              ) : (
                <div className="af-empty-note">
                  <p>Nada chegou aqui ainda. Rode os passos anteriores para ver o que este passo recebe.</p>
                  {editing && (
                    <button type="button" className="btn" onClick={() => (setDetailId(null), void test())}>
                      <Icon d={P.play} size={11} strokeWidth={2} /> Testar automação
                    </button>
                  )}
                </div>
              )}
            </div>
            {dataRun && input.length > 0 && <footer className="small">dados {dataRun.label}</footer>}
          </section>

          <section className="af-ndv-col af-ndv-mid">
            <header>
              <Segment
                value={paramTab}
                options={[
                  ["parametros", "Parâmetros"],
                  ["ajustes", "Ajustes"],
                ]}
                onChange={setParamTab}
              />
            </header>
            <div className="af-ndv-scroll">
              {waiting && (
                <section className="af-waiting">
                  <h4>Esperando você</h4>
                  <p className="af-note">No app de verdade, isto chega também como notificação do macOS e DM no Slack, com cada mensagem para editar.</p>
                  <div className="af-row">
                    <button type="button" className="btn primary" onClick={() => answerApproval(true)}>
                      Aprovar
                    </button>
                    <button type="button" className="btn" onClick={() => answerApproval(false)}>
                      Recusar
                    </button>
                  </div>
                </section>
              )}
              {(paramTab === "parametros" ? n.info : ajustes).map((sec, i) => (
                <SectionView key={`${n.id}-${paramTab}-${i}`} sec={sec} />
              ))}
              {paramTab === "parametros" && !n.info.length && (
                <p className="af-empty-note">Passo novo. No app de verdade, os campos vêm da descrição da ferramenta na central de MCP.</p>
              )}
            </div>
          </section>

          <section className="af-ndv-col">
            <header>
              <span className="af-caps">Saída</span>
              <Segment
                value={view}
                options={[
                  ["tabela", "Tabela"],
                  ["json", "JSON"],
                ]}
                onChange={setView}
              />
              {editing && mine?.out !== undefined && (
                <button
                  type="button"
                  className="af-pin"
                  aria-pressed={!!pinned[pinKey]}
                  title="Fixar: os próximos testes usam estes dados sem chamar o conector"
                  onClick={() => setPinned((all) => ({ ...all, [pinKey]: !all[pinKey] }))}
                >
                  <Icon d={P.pin} size={12} strokeWidth={2} />
                </button>
              )}
            </header>
            <div className="af-ndv-scroll">
              {mine ? (
                <>
                  <p className="af-io-status mono" data-step={mine.s}>
                    {mine.s === "ok" ? "✓" : mine.s === "erro" ? "✕" : "·"} {STEP_LABEL[mine.s]}
                    {mine.out !== undefined && mine.s !== "erro" ? ` · ${itemsLabel(count(mine.out))}` : ""}
                    {mine.ms !== undefined ? ` · ${duration(mine.ms)}` : ""}
                  </p>
                  {mine.note && <p className="af-note">{mine.note}</p>}
                  {mine.out !== undefined ? (
                    <DataView value={mine.out} view={view} />
                  ) : (
                    mine.s === "ok" && <p className="af-empty-note">Sem saída de exemplo neste protótipo.</p>
                  )}
                  {mine.s === "erro" && (
                    <div className="af-row">
                      <button
                        type="button"
                        className="btn"
                        onClick={() =>
                          setToast(
                            "Pedir conserto: abre um Claude num terminal com o arquivo da automação e o log desta execução. A correção vai para o rascunho; você testa e publica.",
                          )
                        }
                      >
                        Pedir conserto
                      </button>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => setToast("Reexecutar daqui: roda de novo a partir deste passo, com as entradas guardadas desta execução.")}
                      >
                        Reexecutar daqui
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <p className="af-empty-note">Sem saída ainda. Teste o passo ou a automação.</p>
              )}
            </div>
            {pinned[pinKey] && <footer className="small">fixados: o teste usa estes dados em vez de chamar o conector</footer>}
          </section>
        </div>
      </div>
    );
  };

  const renderInfo = () => (
    <aside className="af-drawer" onPointerDown={(event) => event.stopPropagation()}>
      <header className="af-drawer-head">
        <div>
          <h3>{flow.name}</h3>
          <span className="small mono">{flow.file}</span>
        </div>
        <button type="button" className="icon-btn" aria-label="Fechar" onClick={() => setInfoOpen(false)}>
          <Icon d={ICON.close} size={14} />
        </button>
      </header>
      <div className="af-drawer-body af-info">
        {flow.origin && <SectionView sec={{ t: "Origem", note: flow.origin }} />}
        <SectionView
          sec={{
            t: "Versões",
            kv: [
              ["Rascunho", `v${flow.draft}`],
              ["Publicada", flow.published === null ? "nenhuma" : `v${flow.published}`],
              ["O que roda", flow.published === null ? "nada, até publicar" : `sempre a v${flow.published}`],
            ],
          }}
        />
        {flow.diff && changed && (
          <SectionView
            sec={{
              t: `Diferença v${flow.published} → v${flow.draft}`,
              code: flow.diff,
            }}
          />
        )}
        <SectionView
          sec={{
            t: "Onde roda",
            kv: [
              ["Lugar", flow.where],
              ["Execuções", flow.runs.length ? `${okRuns} ok de ${flow.runs.length} recentes` : "nenhuma"],
            ],
          }}
        />
        <SectionView
          sec={{
            t: "Como isto funcionaria",
            note: "O fluxo é um arquivo YAML legível, versionado. Ferramentas vêm da central de MCP: cada conector ligado vira passo, sem gastar cota. Agente é um terminal real do Claude ou do Codex, pelo seu plano. Tudo que fala com outras pessoas passa por aprovação, e no teste vira ensaio.",
          }}
        />
      </div>
    </aside>
  );

  let dock: ReactNode = null;
  if (editing && flow.nodes.length > 0) {
    dock = (
      <div className="af-dock" onPointerDown={(event) => event.stopPropagation()}>
        {proposal && (
          <div className="af-proposal">
            <span className="af-claude">✻</span>
            <span>
              Proposta: <b>+ 1 passo</b>, «{proposal.node.title}», depois de «{byId.get(proposal.from)?.title}». Vai para o rascunho; nada é publicado.
            </span>
            <button type="button" className="btn primary" onClick={applyProposal}>
              Aplicar
            </button>
            <button type="button" className="btn" onClick={() => setProposal(null)}>
              Descartar
            </button>
          </div>
        )}
        {waitingNode && (
          <div className="af-waitcard">
            <span className="af-st" data-step="esperando">
              ‖
            </span>
            <span>
              <b>Esperando você</b> em «{waitingNode.title}»
            </span>
            <button type="button" className="btn" onClick={() => setDetailId(waitingNode.id)}>
              Ver
            </button>
            <button type="button" className="btn primary" onClick={() => answerApproval(true)}>
              Aprovar
            </button>
            <button type="button" className="btn" onClick={() => answerApproval(false)}>
              Recusar
            </button>
          </div>
        )}
        <div className="af-dock-row">
          {running ? (
            <button type="button" className="af-go" data-stop="true" onClick={() => (stopRun(), setLive(null))}>
              <Icon d={P.stop} size={12} strokeWidth={2} /> Parar · {doneSteps} de {flow.nodes.length}
            </button>
          ) : (
            <button type="button" className="af-go" onClick={() => void test()} title="Roda o rascunho agora; o que fala com outras pessoas vira ensaio">
              <Icon d={P.play} size={13} strokeWidth={2} /> Testar automação
            </button>
          )}
          <form
            className="af-ask"
            onSubmit={(event) => {
              event.preventDefault();
              void sendAsk();
            }}
          >
            <span className="af-claude">✻</span>
            <input
              value={ask}
              onChange={(event) => setAsk(event.target.value)}
              placeholder={selected ? `Pedir uma mudança depois de «${selected.title}»…` : "Pedir ao Claude: «crie também uma tarefa no ClickUp quando…»"}
              aria-label="Pedir uma mudança ao Claude"
            />
            <button type="submit" className="btn" disabled={!ask.trim() || thinking}>
              {thinking ? "Pensando…" : "Pedir"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="af-screen">
      <aside className="af-list">
        <header className="af-list-head">
          <span className="af-caps">Automações</span>
          <button type="button" className="icon-btn" title="Nova automação" aria-label="Nova automação" onClick={newFlow}>
            <Icon d={ICON.plus} size={15} />
          </button>
        </header>
        <div className="af-items">
          {flows.map((f) => {
            const last = f.runs[0];
            const elems = [...new Set(f.nodes.map((n) => (n.kind === "tool" ? connectorOf(n.sub)?.mono : undefined)).filter((m): m is string => !!m))].slice(
              0,
              4,
            );
            return (
              <button key={f.id} type="button" className="af-item" aria-current={f.id === flow.id ? "true" : undefined} onClick={() => choose(f.id)}>
                <span className="af-item-name">{f.name}</span>
                <span className="af-item-icons">
                  <span className="af-mini-trigger">
                    <Icon d={P.bolt} size={10} strokeWidth={2} />
                  </span>
                  {f.nodes.some((n) => n.kind === "agent") && <span className="af-claude af-mini-claude">✻</span>}
                  {elems.map((m) => (
                    <span key={m} className="af-mini-elem mono">
                      {m}
                    </span>
                  ))}
                  <span className="af-item-when mono">{f.when}</span>
                </span>
                <span className="af-item-meta mono">
                  <span className="dot" data-state={f.state} />
                  {f.state}
                  {last && (
                    <span className="af-item-last" data-status={last.status}>
                      {" "}
                      · {last.when} {last.status === "ok" ? "✓" : last.status === "erro" ? "✕" : "…"}
                    </span>
                  )}
                  {f.origin && <span className="af-badge">n8n</span>}
                </span>
              </button>
            );
          })}
        </div>
        <footer className="af-list-foot">
          <button
            type="button"
            className="btn"
            onClick={() => (
              choose("funil"),
              setToast(
                "Importar do n8n: a MÊTIS lê o workflow pelo MCP do n8n e traduz nó a nó. O que tem conector vira Ferramenta, Code vira Código, AI Agent vira Agente; o que não tem par fica marcado para revisar.",
              )
            )}
          >
            Importar do n8n
          </button>
          <p className="small">Protótipo. Os dados são de exemplo e nada aqui chama conector ou abre terminal.</p>
        </footer>
      </aside>

      <section className="af-main">
        <header className="af-bar">
          <div className="af-bar-left">
            <span className="af-name">{flow.name}</span>
            <span className="chip" data-state={flow.state}>
              {flow.state}
            </span>
            <button
              type="button"
              className="chip af-version"
              onClick={() => (setPanel(null), setInfoOpen(true))}
              title="Versões: o que roda é sempre a publicada"
            >
              {flow.published === null
                ? `v${flow.draft} · nunca publicada`
                : changed
                  ? `rascunho v${flow.draft} · publicada v${flow.published}`
                  : `v${flow.published} publicada`}
            </button>
          </div>
          <div className="af-tabs" role="tablist" aria-label="Modo">
            <button type="button" role="tab" aria-selected={mode === "editor"} onClick={() => (setMode("editor"), setRunId(null), setDetailId(null))}>
              Editor
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "runs"}
              onClick={() => {
                resetView();
                setMode("runs");
              }}
            >
              Execuções {flow.runs.length ? <span className="af-count mono">{flow.runs.length}</span> : null}
            </button>
          </div>
          <div className="af-bar-right">
            <span className="chip af-mock" title="Nada aqui é real ainda">
              protótipo
            </span>
            <button type="button" className="btn" onClick={() => (setPanel(null), setInfoOpen((v) => !v))}>
              <Icon d={ICON.info} size={13} strokeWidth={2} /> Detalhes
            </button>
            <button type="button" className="btn primary" disabled={!changed || !flow.nodes.length} onClick={publish}>
              {changed ? `Publicar v${flow.draft}` : "Publicada"}
            </button>
            <button
              type="button"
              className="af-switch"
              role="switch"
              aria-checked={flow.state === "ativa"}
              disabled={flow.published === null}
              title={flow.published === null ? "Publique antes de ativar" : flow.state === "ativa" ? "Pausar" : "Ativar"}
              onClick={() =>
                update((f) => ({
                  ...f,
                  state: f.state === "ativa" ? "pausada" : "ativa",
                }))
              }
            >
              <span />
              {flow.state === "ativa" ? "Ativa" : "Pausada"}
            </button>
          </div>
        </header>

        <div className="af-work">
          {mode === "runs" && (
            <aside className="af-runlist">
              <span className="af-caps">Execuções</span>
              {flow.runs.length === 0 && <p className="small">Nenhuma ainda. Teste no Editor para criar a primeira.</p>}
              {flow.runs.map((r) => (
                <button key={r.id} type="button" className="af-runitem" aria-current={run?.id === r.id ? "true" : undefined} onClick={() => setRunId(r.id)}>
                  <span className="af-run-dot" data-status={r.status} />
                  <span className="af-runitem-main">
                    <b>{r.when}</b>
                    <span className="small">{r.how}</span>
                    <span className="mono small">
                      {r.took} · {r.quota}
                    </span>
                    {r.note && <span className="small af-run-note">{r.note}</span>}
                  </span>
                </button>
              ))}
            </aside>
          )}

          <div className="af-stage">
            <div
              ref={canvas}
              className="af-canvas"
              data-mode={mode}
              style={{
                backgroundPosition: `${pan.x}px ${pan.y}px`,
                backgroundSize: `${20 * zoom}px ${20 * zoom}px`,
              }}
              onPointerDown={onCanvasDown}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onWheel={(event) => {
                if (event.ctrlKey || event.metaKey) zoomBy(event.deltaY < 0 ? 1.08 : 1 / 1.08);
                else
                  setPan((p) => ({
                    x: p.x - event.deltaX,
                    y: p.y - event.deltaY,
                  }));
              }}
            >
              <div
                className="af-world"
                style={{
                  transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                }}
              >
                <svg className="af-edges" width={OFF * 2} height={OFF * 2} style={{ left: -OFF, top: -OFF }} aria-hidden="true">
                  <defs>
                    <marker id="af-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                      <path d="M0,0 L10,5 L0,10 z" className="af-arr" />
                    </marker>
                    <marker id="af-arr-ok" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                      <path d="M0,0 L10,5 L0,10 z" className="af-arr-ok" />
                    </marker>
                    <marker id="af-arr-acc" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                      <path d="M0,0 L10,5 L0,10 z" className="af-arr-acc" />
                    </marker>
                  </defs>
                  <g transform={`translate(${OFF},${OFF})`}>
                    {allNodes
                      .filter((n) => n.kind === "agent")
                      .flatMap((n) => {
                        const parts = agentParts(n);
                        const targets = [parts.model.x, ...parts.tools.map((t) => t.x), parts.out.x];
                        const sources = [parts.ports[0].x, ...parts.tools.map(() => parts.ports[1].x), parts.ports[2].x];
                        return targets.map((tx, i) => (
                          <path
                            key={`${n.id}-sub-${i}`}
                            className="af-subline"
                            d={`M${sources[i]},${n.y + S + 4} C${sources[i]},${n.y + S + 46} ${tx},${parts.cy - 50} ${tx},${parts.cy - 19}`}
                          />
                        ));
                      })}
                    {allEdges.map((e) => {
                      const a = byId.get(e.from);
                      const b = byId.get(e.to);
                      if (!a || !b) return null;
                      const { d } = bez(portOut(a, e.label), portIn(b));
                      const key = `${e.from}>${e.to}`;
                      const st = edgeState(e);
                      const isProposal = proposal?.node.id === e.to;
                      return (
                        <g
                          key={key}
                          className="af-edge"
                          data-branch={e.label}
                          data-state={st}
                          data-proposal={isProposal ? "true" : undefined}
                          data-hover={hoverEdge === key ? "true" : undefined}
                        >
                          <path d={d} markerEnd={`url(#${isProposal ? "af-arr-acc" : st === "ok" ? "af-arr-ok" : "af-arr"})`} />
                          {editing && !isProposal && <path className="af-hit" d={d} onPointerEnter={() => keepEdge(key)} onPointerLeave={dropEdge} />}
                        </g>
                      );
                    })}
                    {stubs.map(({ node, label, p }) => (
                      <path key={`${node.id}-stub-${label ?? ""}`} className="af-stubline" d={`M${p.x},${p.y} L${p.x + 34},${p.y}`} />
                    ))}
                  </g>
                </svg>

                {flow.notes.map((k) => (
                  <div key={k.id} className="af-sticky" style={{ left: k.x, top: k.y, width: k.w }} onPointerDown={(event) => onItemDown(event, "note", k)}>
                    <span className="af-caps">{k.title}</span>
                    <p>{k.text}</p>
                    {editing && (
                      <button
                        type="button"
                        className="af-sticky-x"
                        title="Tirar a nota"
                        onClick={() =>
                          update((f) => ({
                            ...f,
                            notes: f.notes.filter((x) => x.id !== k.id),
                          }))
                        }
                      >
                        <Icon d={ICON.close} size={10} strokeWidth={2} />
                      </button>
                    )}
                  </div>
                ))}

                {flow.nodes.map((n) => renderNode(n))}
                {proposal && renderNode(proposal.node, true)}

                {allEdges.map((e) => {
                  const a = byId.get(e.from);
                  const b = byId.get(e.to);
                  if (!a || !b) return null;
                  const key = `${e.from}>${e.to}`;
                  const { mid } = bez(portOut(a, e.label), portIn(b));
                  const out = shown[e.from]?.out;
                  const lit = edgeState(e) === "ok" && out !== undefined;
                  return (
                    <div key={`lbl-${key}`}>
                      {lit && (
                        <span className="af-edge-count mono" style={{ left: mid.x, top: mid.y }}>
                          {itemsLabel(count(out))}
                        </span>
                      )}
                      {editing && hoverEdge === key && (
                        <span
                          className="af-edge-tools"
                          style={{ left: mid.x, top: mid.y }}
                          onPointerEnter={() => keepEdge(null)}
                          onPointerLeave={dropEdge}
                          onPointerDown={(event) => event.stopPropagation()}
                        >
                          <button type="button" title="Pôr um passo aqui no meio" onClick={() => openPanel({ between: e })}>
                            <Icon d={ICON.plus} size={12} strokeWidth={2.2} />
                          </button>
                          <button type="button" title="Tirar a ligação" onClick={() => removeEdge(e)}>
                            <Icon d={ICON.trash} size={11} strokeWidth={2} />
                          </button>
                        </span>
                      )}
                    </div>
                  );
                })}

                {stubs.map(({ node, label, p }) => (
                  <button
                    key={`${node.id}-plus-${label ?? ""}`}
                    type="button"
                    className="af-stub"
                    style={{ left: p.x + 34, top: p.y - 11 }}
                    title={label ? `Próximo passo no ramo ${label}` : "Próximo passo"}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={() => openPanel({ after: node.id, label })}
                  >
                    <Icon d={ICON.plus} size={12} strokeWidth={2.2} />
                  </button>
                ))}
              </div>

              {!flow.nodes.length && (
                <div className="af-empty" onPointerDown={(event) => event.stopPropagation()}>
                  <button type="button" className="af-first" onClick={() => openPanel({ trigger: true })}>
                    <span>
                      <Icon d={ICON.plus} size={26} strokeWidth={1.6} />
                    </span>
                    Escolher o gatilho
                  </button>
                  <div className="af-or small">ou descreva em uma frase e o Claude monta os passos</div>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void sendAsk();
                    }}
                  >
                    <textarea
                      value={ask}
                      rows={2}
                      placeholder="Ex.: toda segunda às 9h, resumir os e-mails não lidos e mandar na minha DM"
                      onChange={(event) => setAsk(event.target.value)}
                    />
                    <button type="submit" className="btn primary" disabled={!ask.trim() || thinking}>
                      {thinking ? "Montando…" : "Montar"}
                    </button>
                  </form>
                  <div className="af-ideas">
                    {IDEAS.map((idea) => (
                      <button key={idea} type="button" className="chip" onClick={() => setAsk(idea)}>
                        {idea}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {mode === "runs" && run && (
                <div className="af-runbanner" onPointerDown={(event) => event.stopPropagation()}>
                  <span className="af-run-dot" data-status={run.status} />
                  <b>{run.when}</b>
                  <span className="small">
                    {run.how} · {run.took} · {run.quota}
                  </span>
                  <button
                    type="button"
                    className="btn"
                    onClick={() =>
                      setToast(
                        "Copiar para o editor: abre o rascunho com os dados desta execução fixados em cada passo, para depurar sem chamar os conectores de novo.",
                      )
                    }
                  >
                    Copiar para o editor
                  </button>
                </div>
              )}

              {editing && (
                <div className="af-corner" onPointerDown={(event) => event.stopPropagation()}>
                  <button type="button" title="Adicionar passo" aria-label="Adicionar passo" onClick={() => openPanel(selected ? { after: selected.id } : {})}>
                    <Icon d={ICON.plus} size={16} strokeWidth={2} />
                  </button>
                  <button type="button" title="Nota no canvas" aria-label="Nota no canvas" onClick={addNote}>
                    <Icon d={P.sticky} size={15} strokeWidth={1.8} />
                  </button>
                </div>
              )}

              <div className="af-zoom" onPointerDown={(event) => event.stopPropagation()}>
                <button type="button" onClick={() => fit()} aria-label="Enquadrar" title="Enquadrar">
                  <Icon d={P.fit} size={13} strokeWidth={2} />
                </button>
                <button type="button" onClick={() => zoomBy(1.15)} aria-label="Aproximar">
                  <Icon d={ICON.plus} size={13} strokeWidth={2} />
                </button>
                <button type="button" onClick={() => zoomBy(1 / 1.15)} aria-label="Afastar">
                  <Icon d={P.minus} size={13} strokeWidth={2} />
                </button>
                <span className="mono">{Math.round(zoom * 100)}%</span>
              </div>

              {dock}
            </div>
            {panel && renderPanel()}
            {infoOpen && !panel && renderInfo()}
          </div>
          {detail && renderDetail(detail)}
        </div>
      </section>
      {toast && (
        <div className="toast" role="status" onClick={() => setToast(null)}>
          {toast}
        </div>
      )}
    </div>
  );
}
