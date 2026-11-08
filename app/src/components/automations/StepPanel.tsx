// Painel do passo (dois cliques): Entrada | Parâmetros (e Ajustes) | Saída. A entrada e a saída vêm
// da execução mostrada (o teste de agora, a escolhida em Execuções ou a última com dados); os
// parâmetros editam o rascunho. Expressões {{…}} aparecem como peças verdes.

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { ICON, Icon } from "../../icons";
import type { CoreClient } from "../../lib/core";
import { KIND_COLOR } from "../../lib/format";
import type { Agent, AutoCatalog, AutoFlow, AutoOutputType, AutoRun, AutoStep, AutoTrigger } from "../../types";
import {
  BRAIN_LABEL,
  type Change,
  DAY_SHORT,
  KIND,
  P,
  STEP_LABEL,
  TRIGGER,
  type Tool,
  compact,
  isPlain,
  itemsLabel,
  itemsOf,
  span,
  stepSub,
  toolDescription,
  toolElem,
  toolGroup,
  toolTitle,
  triggerTitle,
  uniqueTitle,
  upstream,
} from "./model";
import { type DataMode, DataView, ElemMark, Expr, Field, Glyph, Segment, hasExpr } from "./parts";

interface Props {
  flow: AutoFlow;
  nodeId: string;
  editing: boolean;
  catalog: AutoCatalog | null;
  agents: Agent[];
  client: CoreClient | null;
  /** Execução de onde vêm a entrada e a saída, e o rótulo dela ("do teste de agora"). */
  run: AutoRun | null;
  runLabel: string;
  view: DataMode;
  onView: (view: DataMode) => void;
  onClose: () => void;
  onEdit: (change: Change) => void;
  /** Troca o nome (e as expressões que usam o antigo); devolve o erro, se houver. */
  onRename: (id: string, title: string) => string | null;
  onTestStep: (id: string) => void;
  onTestAll: () => void;
  onRerun: (stepId: string) => void;
  onAskFix: () => void;
  onOpenSession: (id: string) => void;
  onRemove: (id: string) => void;
  onToast: (message: string) => void;
}

type Prop = { type?: string | string[]; description?: string; enum?: unknown[] };

const OUTPUT_TYPES: [AutoOutputType, string][] = [
  ["texto", "texto"],
  ["numero", "número"],
  ["lista", "lista"],
  ["objeto", "objeto"],
  ["sim/nao", "sim/não"],
];

const num = (v: string) => {
  if (!v.trim()) return undefined;
  const n = Number(v.replace(",", "."));
  return Number.isFinite(n) ? n : undefined;
};

function schemaOf(tool: Tool | undefined): { props: Record<string, Prop>; required: string[] } | null {
  const props = tool?.esquema?.properties;
  if (!isPlain(props) || !Object.keys(props).length) return null;
  const required = Array.isArray(tool?.esquema?.required) ? (tool!.esquema.required as string[]) : [];
  return { props: props as Record<string, Prop>, required };
}

/** Editor de JSON: só aplica quando o texto é JSON válido; enquanto não for, avisa e guarda o texto. */
function JsonEditor({ value, onChange, rows = 6, object }: { value: unknown; onChange: (v: unknown) => void; rows?: number; object?: boolean }) {
  const show = (v: unknown) => (v === undefined ? "" : JSON.stringify(v, null, 2));
  const [text, setText] = useState(() => show(value));
  const [error, setError] = useState<string | null>(null);
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(show(value));
  }, [value]);
  return (
    <>
      <textarea
        className="af-input mono"
        rows={rows}
        value={text}
        spellCheck={false}
        onFocus={() => (focused.current = true)}
        onBlur={() => (focused.current = false)}
        onChange={(event) => {
          setText(event.target.value);
          if (!event.target.value.trim()) {
            setError(null);
            onChange(object ? {} : undefined);
            return;
          }
          try {
            const parsed = JSON.parse(event.target.value);
            if (object && !isPlain(parsed)) throw new Error("objeto");
            setError(null);
            onChange(parsed);
          } catch {
            setError(object ? "Ainda não é um objeto JSON { … } válido; nada mudou." : "Ainda não é JSON válido; nada mudou.");
          }
        }}
      />
      {error && <span className="af-field-error">{error}</span>}
    </>
  );
}

function ExprPreview({ text }: { text: unknown }) {
  if (!hasExpr(text)) return null;
  return (
    <span className="af-preview">
      <Expr text={String(text)} />
    </span>
  );
}

function ArgField({ name, prop, required, value, onChange }: { name: string; prop: Prop; required: boolean; value: unknown; onChange: (v: unknown) => void }) {
  const type = Array.isArray(prop.type) ? prop.type.find((t) => t !== "null") : prop.type;
  const hint = prop.description ? (prop.description.length > 180 ? `${prop.description.slice(0, 178)}…` : prop.description) : undefined;
  const label = (
    <>
      {name}
      {required && (
        <i className="af-req" title="obrigatório">
          *
        </i>
      )}
      <span className="mono af-type">{type ?? "texto"}</span>
    </>
  );
  const text = typeof value === "string" ? value : value === undefined || value === null ? "" : JSON.stringify(value);
  if (prop.enum?.length) {
    return (
      <Field label={label} hint={hint}>
        <select value={text} onChange={(event) => onChange(event.target.value || undefined)}>
          <option value="">—</option>
          {prop.enum.map((v) => (
            <option key={String(v)} value={String(v)}>
              {String(v)}
            </option>
          ))}
        </select>
      </Field>
    );
  }
  if (type === "boolean") {
    return (
      <Field label={label} hint={hint}>
        <select value={typeof value === "boolean" ? String(value) : ""} onChange={(event) => onChange(event.target.value ? event.target.value === "true" : undefined)}>
          <option value="">—</option>
          <option value="true">sim</option>
          <option value="false">não</option>
        </select>
      </Field>
    );
  }
  if (type === "object" || type === "array") {
    return (
      <Field label={label} hint={hint} group>
        <JsonEditor value={value} rows={4} onChange={onChange} />
      </Field>
    );
  }
  if (type === "number" || type === "integer") {
    return (
      <Field label={label} hint={hint}>
        <input
          className="af-input mono"
          value={text}
          placeholder="número ou {{Passo.campo}}"
          onChange={(event) => {
            const v = event.target.value;
            onChange(!v.trim() ? undefined : /^-?\d+([.,]\d+)?$/.test(v.trim()) ? Number(v.trim().replace(",", ".")) : v);
          }}
        />
        <ExprPreview text={value} />
      </Field>
    );
  }
  const long = /texto|mensagem|corpo|descri|conteudo|content|body|text|prompt|markdown/i.test(name);
  return (
    <Field label={label} hint={hint}>
      {long ? (
        <textarea className="af-input" rows={3} value={text} onChange={(event) => onChange(event.target.value || undefined)} />
      ) : (
        <input className="af-input" value={text} onChange={(event) => onChange(event.target.value || undefined)} />
      )}
      <ExprPreview text={value} />
    </Field>
  );
}

/** Seletor de ferramenta agrupado por conta (a conta da MÊTIS e o Brain inclusive). */
function ToolSelect({ catalog, value, exclude, placeholder, onChange }: { catalog: AutoCatalog | null; value: string; exclude?: string[]; placeholder: string; onChange: (name: string) => void }) {
  const tools = (catalog?.ferramentas ?? []).filter((t) => !exclude?.includes(t.nome));
  const groups = new Map<string, { name: string; tools: Tool[] }>();
  for (const t of tools) {
    const g = toolGroup(t);
    if (!groups.has(g.key)) groups.set(g.key, { name: g.name, tools: [] });
    groups.get(g.key)!.tools.push(t);
  }
  const known = !value || tools.some((t) => t.nome === value);
  return (
    <select value={value} onChange={(event) => event.target.value && onChange(event.target.value)}>
      <option value="">{catalog ? placeholder : "carregando o catálogo…"}</option>
      {!known && <option value={value}>{value} (não encontrada)</option>}
      {[...groups.entries()].map(([key, g]) => (
        <optgroup key={key} label={g.name}>
          {g.tools.map((t) => (
            <option key={t.nome} value={t.nome}>
              {toolTitle(t.nome)}
              {t.pessoas ? " · fala com outras pessoas" : ""}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

export function StepPanel(props: Props) {
  const { flow, nodeId, editing, catalog, agents, client, run, view, onView, onEdit } = props;
  const isTrigger = nodeId === TRIGGER;
  const step = flow.passos.find((s) => s.id === nodeId) ?? null;
  const kind = isTrigger ? "gatilho" : (step?.tipo ?? "ferramenta");
  const [tab, setTab] = useState<"parametros" | "ajustes">("parametros");
  const [title, setTitle] = useState(step?.titulo ?? "");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [rows, setRows] = useState<{ k: string; t: AutoOutputType }[]>(() => Object.entries(step?.saida ?? {}).map(([k, t]) => ({ k, t })));

  useEffect(() => {
    setTitle(step?.titulo ?? "");
    setTitleError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId, step?.titulo]);
  useEffect(() => {
    setRows(Object.entries(step?.saida ?? {}).map(([k, t]) => ({ k, t })));
    setTab("parametros");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId]);

  if (!isTrigger && !step) return null;

  const patch = (p: Partial<AutoStep>) => onEdit((f) => ({ ...f, passos: f.passos.map((s) => (s.id === nodeId ? compact({ ...s, ...p }) : s)) }));
  const patchTrigger = (p: Partial<AutoTrigger>) => onEdit((f) => ({ ...f, gatilho: compact({ ...f.gatilho, ...p }) }));

  const commitTitle = () => {
    if (!step || title === step.titulo) return;
    const error = props.onRename(step.id, title);
    setTitleError(error);
    if (error) props.onToast(error);
  };

  const mine = run?.steps[nodeId] ?? null;
  const pinned = step?.fixado !== undefined && step?.fixado !== null;
  const tool = step?.ferramenta ? catalog?.ferramentas.find((t) => t.nome === step.ferramenta) : undefined;
  const color = kind === "agente" ? KIND_COLOR[step?.cli ?? "claude"] : KIND[kind].color;
  const sessao = mine?.sessao ?? null;
  const running = run?.status === "rodando";
  const before = upstream(flow, nodeId);
  const exprs = [
    ...(before.includes(TRIGGER) || isTrigger ? ["{{gatilho.hoje}}", "{{gatilho.agora}}"] : []),
    ...before.filter((id) => id !== TRIGGER).map((id) => `{{${flow.passos.find((s) => s.id === id)?.titulo ?? id}}}`),
  ];

  const copy = (text: string) =>
    void navigator.clipboard
      ?.writeText(text)
      .then(() => props.onToast(`Copiado: ${text}`))
      .catch(() => props.onToast("Não deu para copiar."));

  const setSaida = (next: { k: string; t: AutoOutputType }[]) => {
    setRows(next);
    const clean = next.filter((r) => r.k.trim());
    patch({ saida: clean.length ? Object.fromEntries(clean.map((r) => [r.k.trim(), r.t])) : undefined });
  };

  const chooseTool = (name: string) => {
    if (!step) return;
    const next = catalog?.ferramentas.find((t) => t.nome === name);
    const schema = schemaOf(next);
    const args = step.argumentos ?? {};
    patch({ ferramenta: name, argumentos: schema ? Object.fromEntries(Object.entries(args).filter(([k]) => k in schema.props)) : args });
    if (!step.ferramenta || step.titulo === toolTitle(step.ferramenta)) {
      const fresh = uniqueTitle({ ...flow, passos: flow.passos.filter((s) => s.id !== step.id) }, toolTitle(name));
      props.onRename(step.id, fresh);
    }
  };

  // --- parâmetros de cada tipo ---------------------------------------------------------------------

  const triggerForm = () => {
    const t = flow.gatilho;
    return (
      <>
        <Field label="Como ela começa" group>
          <Segment
            value={t.tipo}
            disabled={!editing}
            options={[
              ["manual", "Na mão"],
              ["agendado", "Agendado"],
            ]}
            onChange={(tipo) =>
              patchTrigger(tipo === "agendado" ? { tipo, dias: t.dias?.length ? t.dias : [0, 1, 2, 3, 4], hora: t.hora || "08:00", recupera_min: t.recupera_min ?? 60 } : { tipo })
            }
          />
        </Field>
        {t.tipo === "agendado" ? (
          <>
            <Field label="Dias" group>
              <div className="af-days">
                {DAY_SHORT.map((label, d) => {
                  const on = (t.dias ?? []).includes(d);
                  return (
                    <button
                      key={label}
                      type="button"
                      aria-pressed={on}
                      onClick={() => patchTrigger({ dias: on ? (t.dias ?? []).filter((x) => x !== d) : [...(t.dias ?? []), d].sort((a, b) => a - b) })}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
            </Field>
            <div className="af-row2">
              <Field label="Hora">
                <input className="af-input mono" type="time" value={t.hora ?? ""} onChange={(event) => patchTrigger({ hora: event.target.value || undefined })} />
              </Field>
              <Field label="Mac dormindo (min)" hint="roda ao acordar até esse tempo depois da hora; depois, pula">
                <input className="af-input mono" inputMode="numeric" value={t.recupera_min ?? ""} placeholder="60" onChange={(event) => patchTrigger({ recupera_min: num(event.target.value) })} />
              </Field>
            </div>
          </>
        ) : (
          <p className="af-note">Roda quando você manda: «Rodar a publicada agora», o ⌘K ou metis rodar no terminal.</p>
        )}
        <p className="af-note">Sem webhook: a MÊTIS não abre porta na internet, e só roda com o Mac acordado.</p>
      </>
    );
  };

  const toolForm = (s: AutoStep) => {
    const schema = schemaOf(tool);
    const args = s.argumentos ?? {};
    const setArg = (key: string, v: unknown) => patch({ argumentos: compact({ ...args, [key]: v }) });
    return (
      <>
        <Field label="Ferramenta" group hint={tool ? toolDescription(tool) : catalog && s.ferramenta ? "Essa ferramenta não está na central agora (conta desligada em Conectores?)." : undefined}>
          <ToolSelect catalog={catalog} value={s.ferramenta ?? ""} placeholder="Escolha a ferramenta" onChange={chooseTool} />
        </Field>
        {tool?.pessoas && (
          <p className="af-people-note">
            <Icon d={P.lock} size={11} strokeWidth={2} /> Fala com outras pessoas: só envia depois da sua aprovação, e no teste vira ensaio na sua DM.
          </p>
        )}
        <section className="af-sec">
          <h4>Argumentos</h4>
          {schema ? (
            Object.entries(schema.props).map(([key, prop]) => (
              <ArgField key={key} name={key} prop={prop} required={schema.required.includes(key)} value={args[key]} onChange={(v) => setArg(key, v)} />
            ))
          ) : (
            <Field label="JSON" group hint="Sem descrição dos campos: escreva o objeto. Vale {{Passo.campo}} dentro dos textos.">
              <JsonEditor value={args} object onChange={(v) => patch({ argumentos: v as Record<string, unknown> })} />
            </Field>
          )}
          {schema && Object.keys(args).some((k) => !(k in schema.props)) && (
            <p className="af-field-error">Há argumentos que essa ferramenta não conhece: {Object.keys(args).filter((k) => !(k in schema.props)).join(", ")}.</p>
          )}
        </section>
      </>
    );
  };

  const agentForm = (s: AutoStep) => {
    const who = s.agente ? `agente:${s.agente}` : `cli:${s.cli ?? "claude"}`;
    const gallery = catalog?.agentes ?? agents.map((a) => ({ id: a.id, nome: a.name, cli: a.cli, cor: a.color, descricao: a.description }));
    const chosen = s.ferramentas ?? [];
    return (
      <>
        <Field label="Quem">
          <select
            value={who}
            onChange={(event) => {
              const [type, id] = event.target.value.split(":");
              if (type === "cli") patch({ agente: undefined, cli: id as "claude" | "codex" });
              else patch({ agente: id, cli: gallery.find((a) => a.id === id)?.cli ?? "claude" });
            }}
          >
            <option value="cli:claude">✻ Claude Code</option>
            <option value="cli:codex">◇ Codex</option>
            {s.agente && !gallery.some((a) => a.id === s.agente) && <option value={who}>{s.agente} (não encontrado)</option>}
            {gallery.length > 0 && (
              <optgroup label="Agentes da galeria">
                {gallery.map((a) => (
                  <option key={a.id} value={`agente:${a.id}`}>
                    {a.nome} · {a.cli}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </Field>
        <Field label="Pedido" hint="O que o agente faz com o que chega. Traga dados de outros passos com {{Passo.campo}}.">
          <textarea className="af-input" rows={6} value={s.pedido ?? ""} placeholder="Com {{Tarefas do dia}}, escreva um resumo de 5 linhas…" onChange={(event) => patch({ pedido: event.target.value })} />
          <ExprPreview text={s.pedido} />
        </Field>
        <div className="af-row2">
          <Field label="Modelo">
            <input className="af-input mono" value={s.modelo ?? ""} placeholder="padrão" onChange={(event) => patch({ modelo: event.target.value || undefined })} />
          </Field>
          <Field label="Onde roda" group>
            <Segment
              value={s.onde ?? "segundo-plano"}
              disabled={!editing}
              options={[
                ["segundo-plano", "Segundo plano"],
                ["visivel", "Visível"],
              ]}
              onChange={(onde) => patch({ onde })}
            />
          </Field>
        </div>
        <Field label="Ferramentas liberadas" group hint="Só estas na central de MCP do terminal, mais a saida, por onde o resultado volta.">
          {chosen.length > 0 && (
            <div className="af-tools">
              {chosen.map((name) => (
                <span key={name} className="af-toolchip" title={name}>
                  <ElemMark elem={toolElem(name)} size={11} />
                  {toolTitle(name)}
                  {editing && (
                    <button type="button" aria-label={`Tirar ${toolTitle(name)}`} onClick={() => patch({ ferramentas: chosen.filter((t) => t !== name) })}>
                      <Icon d={ICON.close} size={9} strokeWidth={2.4} />
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}
          <ToolSelect catalog={catalog} value="" exclude={chosen} placeholder="+ liberar uma ferramenta" onChange={(name) => patch({ ferramentas: [...chosen, name] })} />
        </Field>
        <Field label="Saída combinada" group hint="Vazio: saída livre. Com campos, a MÊTIS confere e pede de novo no mesmo terminal se faltar algum.">
          {rows.map((r, i) => (
            <div key={i} className="af-outrow">
              <input
                className="af-input mono"
                value={r.k}
                placeholder="campo"
                aria-label="Nome do campo"
                onChange={(event) => setSaida(rows.map((x, j) => (j === i ? { ...x, k: event.target.value.replace(/\s+/g, "_") } : x)))}
              />
              <select value={r.t} aria-label="Tipo do campo" onChange={(event) => setSaida(rows.map((x, j) => (j === i ? { ...x, t: event.target.value as AutoOutputType } : x)))}>
                {OUTPUT_TYPES.map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
              {editing && (
                <button type="button" className="icon-btn" aria-label="Tirar o campo" onClick={() => setSaida(rows.filter((_, j) => j !== i))}>
                  <Icon d={ICON.close} size={11} strokeWidth={2} />
                </button>
              )}
            </div>
          ))}
          {editing && (
            <button type="button" className="btn af-add" onClick={() => setRows([...rows, { k: "", t: "texto" }])}>
              <Icon d={ICON.plus} size={11} strokeWidth={2.2} /> Campo
            </button>
          )}
        </Field>
        <div className="af-row2">
          <Field label="Pasta">
            <input className="af-input mono" value={s.pasta ?? ""} placeholder="a do agente ou a pessoal" onChange={(event) => patch({ pasta: event.target.value || undefined })} />
          </Field>
          <Field label="Tempo limite (min)">
            <input className="af-input mono" inputMode="numeric" value={s.tempo_limite_min ?? ""} placeholder="20" onChange={(event) => patch({ tempo_limite_min: num(event.target.value) })} />
          </Field>
        </div>
        <p className="af-note">Roda interativo, como se você digitasse {s.cli ?? "claude"}, pelo seu plano, numa aba do grupo Automações.</p>
      </>
    );
  };

  const conditionForm = (s: AutoStep) => (
    <>
      <Field label="Regra">
        <input className="af-input mono" value={s.regra ?? ""} placeholder="{{Tarefas do dia.total}} > 0" onChange={(event) => patch({ regra: event.target.value })} />
        <ExprPreview text={s.regra} />
      </Field>
      <p className="af-note">
        Uma linha, como <Expr text="{{Passo.campo}} > 0 e não vazio({{Outro}})" />. Funções: <code>len()</code>, <code>vazio()</code>, <code>contem(texto, 'parte')</code>. Verdadeira segue pelo
        sim; falsa, pelo não.
      </p>
    </>
  );

  const approvalForm = (s: AutoStep) => (
    <>
      <Field label="Mensagem" hint="Vazio: «Seguir com a automação?»">
        <textarea className="af-input" rows={4} value={s.mensagem ?? ""} placeholder="Mandar {{Escrever.followups}} no #comercial?" onChange={(event) => patch({ mensagem: event.target.value || undefined })} />
        <ExprPreview text={s.mensagem} />
      </Field>
      <Field label="Prazo para responder (min)" hint="Sem resposta no prazo, a automação para aqui, sem seguir.">
        <input className="af-input mono" inputMode="numeric" value={s.prazo_min ?? ""} placeholder="60" onChange={(event) => patch({ prazo_min: num(event.target.value) })} />
      </Field>
      <p className="af-note">A pergunta chega no cartão de aprovação da MÊTIS (e na DM do Slack). Aprovar solta o que vem depois; recusar para aqui.</p>
    </>
  );

  const brainForm = (s: AutoStep) => {
    const text = (key: "termos" | "tipos" | "projeto" | "texto" | "nota", label: string, placeholder = "", hint?: string) => (
      <Field label={label} hint={hint}>
        <input className="af-input" value={s[key] ?? ""} placeholder={placeholder} onChange={(event) => patch({ [key]: event.target.value || undefined } as Partial<AutoStep>)} />
        <ExprPreview text={s[key]} />
      </Field>
    );
    const limit = (
      <Field label="Limite">
        <input className="af-input mono" inputMode="numeric" value={s.limite ?? ""} placeholder="10" onChange={(event) => patch({ limite: num(event.target.value) })} />
      </Field>
    );
    return (
      <>
        <Field label="Ação">
          <select value={s.acao ?? "buscar"} onChange={(event) => patch({ acao: event.target.value as AutoStep["acao"] })}>
            {Object.entries(BRAIN_LABEL).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        {(s.acao ?? "buscar") === "buscar" && (
          <>
            {text("termos", "Termos", "o que procurar")}
            {text("tipos", "Tipos", "decisao, incidente, aprendizado", "vírgula para vários; vazio = todos")}
            <div className="af-row2">
              {text("projeto", "Projeto", "todos")}
              {limit}
            </div>
          </>
        )}
        {s.acao === "ler" && text("nota", "Título da nota", "Webhook da Guru passa por fila", "o título exato, como no Obsidian; aceita {{…}}")}
        {s.acao === "precedentes" && (
          <>
            {text("projeto", "Projeto", "o do momento")}
            {text("termos", "Assunto", "uma frase; vazio = o momento do projeto")}
          </>
        )}
        {s.acao === "tarefas" && text("projeto", "Projeto", "nome do projeto no Brain", "as tarefas abertas do kanban desse projeto")}
        {s.acao === "diario" && (
          <Field label="Linha" hint="Vai para o Registro de trabalho do diário de hoje. No teste, não grava.">
            <textarea className="af-input" rows={3} value={s.texto ?? ""} onChange={(event) => patch({ texto: event.target.value || undefined })} />
            <ExprPreview text={s.texto} />
          </Field>
        )}
      </>
    );
  };

  const waitForm = (s: AutoStep) => (
    <Field label="Minutos" hint="No teste, espera só 3 segundos.">
      <input className="af-input mono" inputMode="numeric" value={s.minutos ?? ""} placeholder="1" onChange={(event) => patch({ minutos: num(event.target.value) })} />
    </Field>
  );

  const params = () => {
    if (isTrigger) return triggerForm();
    const s = step!;
    if (s.tipo === "ferramenta") return toolForm(s);
    if (s.tipo === "agente") return agentForm(s);
    if (s.tipo === "condicao") return conditionForm(s);
    if (s.tipo === "aprovacao") return approvalForm(s);
    if (s.tipo === "brain") return brainForm(s);
    return waitForm(s);
  };

  const settings = () =>
    isTrigger ? (
      <section className="af-sec">
        <h4>Nas expressões</h4>
        <p className="af-note">
          O gatilho entrega <Expr text="{{gatilho.hoje}}" />, <Expr text="{{gatilho.agora}}" />, <Expr text="{{gatilho.origem}}" /> e <Expr text="{{gatilho.modo}}" /> (teste ou producao).
        </p>
      </section>
    ) : (
      <>
        <section className="af-sec">
          <h4>Ligado</h4>
          <label className="af-check">
            <input type="checkbox" checked={!step!.desligado} onChange={(event) => patch({ desligado: event.target.checked ? undefined : true })} />
            {step!.desligado ? "Desligado: os dados passam direto, sem rodar" : "Ligado"}
          </label>
        </section>
        <section className="af-sec">
          <h4>Dados fixados</h4>
          {pinned ? (
            <>
              <p className="af-note">
                {itemsLabel(Array.isArray(step!.fixado) ? step!.fixado.length : 1)} fixados. No teste, substituem a chamada; em produção, o passo roda de verdade.
              </p>
              {editing && (
                <div className="af-row">
                  <button type="button" className="btn" onClick={() => patch({ fixado: undefined })}>
                    Desafixar
                  </button>
                </div>
              )}
            </>
          ) : (
            <p className="af-note">Nada fixado. Na saída de uma execução, o alfinete guarda os dados para os próximos testes.</p>
          )}
        </section>
        <section className="af-sec">
          <h4>Nas expressões</h4>
          <p className="af-note">
            Use <Expr text={`{{${step!.titulo}.campo}}`} /> ou, pelo id que não muda, <Expr text={`{{${step!.id}.campo}}`} />.
          </p>
        </section>
        {editing && (
          <section className="af-sec">
            <h4>Tirar</h4>
            <div className="af-row">
              <button type="button" className="btn" onClick={() => props.onRemove(nodeId)}>
                <Icon d={ICON.trash} size={12} strokeWidth={2} /> Tirar o passo
              </button>
            </div>
          </section>
        )}
      </>
    );

  const outValue = mine?.saida ?? (pinned && !mine ? step!.fixado : undefined);

  return (
    <div className="af-ndv" onPointerDown={(event) => event.stopPropagation()}>
      <header className="af-ndv-head">
        <button type="button" className="btn" onClick={props.onClose}>
          <Icon d={P.back} size={13} strokeWidth={2} /> Canvas
        </button>
        <span className="af-ndv-icon" style={{ ["--k" as string]: color } as CSSProperties}>
          <Glyph kind={kind} step={step} agents={agents} client={client} size={22} />
        </span>
        <div className="af-ndv-title">
          <span className="af-caps" style={{ color }}>
            {KIND[kind].label}
          </span>
          {step && editing ? (
            <input
              className="af-title-input"
              value={title}
              aria-label="Nome do passo"
              aria-invalid={titleError ? "true" : undefined}
              title={titleError ?? "O nome é usado nas expressões; precisa ser único"}
              onChange={(event) => (setTitle(event.target.value), setTitleError(null))}
              onBlur={commitTitle}
              onKeyDown={(event) => {
                if (event.key === "Enter") (event.target as HTMLInputElement).blur();
                if (event.key === "Escape") {
                  event.preventDefault();
                  setTitle(step.titulo);
                  setTitleError(null);
                }
              }}
            />
          ) : (
            <h3>{step ? step.titulo : triggerTitle(flow.gatilho)}</h3>
          )}
        </div>
        <span className="mono small af-ndv-sub">{step ? (step.tipo === "ferramenta" ? (step.ferramenta ?? "") : stepSub(step)) : flow.gatilho.tipo}</span>
        <span className="af-spacer" />
        {step?.desligado && <span className="chip">desligado</span>}
        {editing && step && (
          <button type="button" className="btn primary" onClick={() => props.onTestStep(nodeId)} title="Roda só este passo, com as entradas guardadas da última execução">
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
              onChange={onView}
            />
          </header>
          <div className="af-ndv-scroll">
            {isTrigger ? (
              <p className="af-empty-note">O gatilho é o começo: não recebe nada, só dispara.</p>
            ) : mine && mine.entrada !== null && mine.entrada !== undefined ? (
              <div className="af-io-block">
                <span className="af-io-from mono">{itemsLabel(Array.isArray(mine.entrada) ? mine.entrada.length : 1)}</span>
                <DataView value={mine.entrada} view={view} />
              </div>
            ) : (
              <div className="af-empty-note">
                <p>{run ? "Nada chegou neste passo nessa execução." : "Nada chegou aqui ainda. Teste a automação para ver o que este passo recebe."}</p>
                {editing && (
                  <button type="button" className="btn" onClick={props.onTestAll}>
                    <Icon d={P.play} size={11} strokeWidth={2} /> Testar automação
                  </button>
                )}
              </div>
            )}
            {!isTrigger && exprs.length > 0 && (
              <section className="af-sec">
                <h4>Dá para usar aqui</h4>
                <div className="af-chips">
                  {exprs.map((e) => (
                    <button key={e} type="button" className="af-expr mono af-expr-btn" title="Copiar" onClick={() => copy(e)}>
                      {e.slice(2, -2)}
                    </button>
                  ))}
                </div>
              </section>
            )}
          </div>
          {run && mine && <footer className="small">dados {props.runLabel}</footer>}
        </section>

        <section className="af-ndv-col af-ndv-mid">
          <header>
            <Segment
              value={tab}
              options={[
                ["parametros", "Parâmetros"],
                ["ajustes", "Ajustes"],
              ]}
              onChange={setTab}
            />
          </header>
          <div className="af-ndv-scroll">
            {mine?.status === "esperando" && (
              <section className="af-waiting">
                <h4>Esperando você</h4>
                <p className="af-note">Responda no cartão de aprovação da MÊTIS (ou na DM do Slack). Assim que você responder, a automação segue.</p>
              </section>
            )}
            {!editing && <p className="af-note af-readonly">Desenho desta execução, só para ler. Para mudar, use o Editor.</p>}
            <fieldset className="af-fieldset" disabled={!editing}>
              {tab === "parametros" ? params() : settings()}
            </fieldset>
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
              onChange={onView}
            />
            {editing && step && (pinned || (mine?.status === "ok" && mine.saida !== null && mine.saida !== undefined)) && (
              <button
                type="button"
                className="af-pin"
                aria-pressed={pinned}
                title={pinned ? "Desafixar: os testes voltam a chamar o passo" : "Fixar: os próximos testes usam estes dados sem chamar o passo"}
                onClick={() => patch({ fixado: pinned ? undefined : mine?.saida })}
              >
                <Icon d={P.pin} size={12} strokeWidth={2} />
              </button>
            )}
          </header>
          <div className="af-ndv-scroll">
            {mine ? (
              <>
                <p className="af-io-status mono" data-step={mine.status}>
                  {mine.status === "ok" ? "✓" : mine.status === "erro" ? "✕" : "·"} {STEP_LABEL[mine.status]}
                  {mine.status === "ok" ? ` · ${itemsLabel(itemsOf(mine))}` : ""}
                  {span(mine.started, mine.ended) ? ` · ${span(mine.started, mine.ended)}` : ""}
                </p>
                {mine.nota && <p className="af-note">{mine.nota}</p>}
                {mine.erro && <p className="af-error mono">{mine.erro}</p>}
                {outValue !== undefined && outValue !== null && <DataView value={outValue} view={view} />}
                {mine.status === "ok" && (outValue === undefined || outValue === null) && <p className="af-empty-note">O passo não devolveu dados.</p>}
                <div className="af-row">
                  {mine.status === "erro" && run?.status === "erro" && (
                    <button type="button" className="btn" onClick={props.onAskFix} title="Abre um Claude com o arquivo e o log; a correção vai só para o rascunho">
                      Pedir conserto
                    </button>
                  )}
                  {step && run && !running && (!editing || run.mode === "teste") && (mine.status === "erro" || mine.status === "ok" || mine.status === "recusado") && (
                    <button type="button" className="btn" onClick={() => props.onRerun(nodeId)} title="Roda de novo daqui, com as entradas guardadas desta execução">
                      <Icon d={P.rerun} size={11} strokeWidth={2} /> Reexecutar daqui
                    </button>
                  )}
                  {sessao && (
                    <button type="button" className="btn" onClick={() => props.onOpenSession(sessao)}>
                      <Icon d={ICON.term} size={12} strokeWidth={2} /> Abrir o terminal
                    </button>
                  )}
                </div>
              </>
            ) : pinned ? (
              <>
                <p className="af-io-status mono">dados fixados</p>
                <DataView value={step!.fixado} view={view} />
              </>
            ) : (
              <p className="af-empty-note">Sem saída ainda. Teste o passo ou a automação.</p>
            )}
          </div>
          {pinned && <footer className="small">fixados: no teste, estes dados substituem a chamada</footer>}
        </section>
      </div>
    </div>
  );
}
