// Gaveta de passos: "O que acontece depois?" (ou "Quando ela começa?"), com busca. Agentes da
// galeria com a sprite, conectores com as ferramentas de cada conta (cadeado em quem fala com
// outras pessoas), lógica e dados. Tudo vem do catálogo do núcleo.

import { useState } from "react";
import { ICON, Icon } from "../../icons";
import type { CoreClient } from "../../lib/core";
import type { Agent, AutoCatalog, AutoFlow, AutoStep, AutoTrigger } from "../../types";
import { type AddCtx, type Tool, KIND, LOGIC, P, TRIGGER, fold, toolDescription, toolGroup, toolTitle } from "./model";
import { AgentFace, ElemMark } from "./parts";

/** O passo novo, sem id nem posição (quem chama dá os dois). */
export type StepDraft = Omit<AutoStep, "id" | "x" | "y">;

interface Props {
  ctx: AddCtx;
  flow: AutoFlow;
  catalog: AutoCatalog | null;
  catalogError: string | null;
  agents: Agent[];
  client: CoreClient | null;
  onClose: () => void;
  onPick: (draft: StepDraft) => void;
  onTrigger: (tipo: AutoTrigger["tipo"]) => void;
  onRetry: () => void;
}

const TRIGGERS: { tipo: AutoTrigger["tipo"]; title: string; hint: string }[] = [
  { tipo: "manual", title: "Na mão", hint: "botão Rodar, ⌘K ou metis rodar no terminal" },
  { tipo: "agendado", title: "Agendado", hint: "dias e hora; se o Mac dormir, roda ao acordar" },
];

const LOGIC_DRAFT: Record<(typeof LOGIC)[number], StepDraft> = {
  condicao: { tipo: "condicao", titulo: "Condição", regra: "" },
  aprovacao: { tipo: "aprovacao", titulo: "Aprovação", mensagem: "", prazo_min: 60 },
  esperar: { tipo: "esperar", titulo: "Esperar", minutos: 5 },
  brain: { tipo: "brain", titulo: "Brain", acao: "buscar", termos: "", limite: 10 },
  ferramenta: { tipo: "ferramenta", titulo: "Ferramenta" },
  agente: { tipo: "agente", titulo: "Agente" },
};

export function Drawer({ ctx, flow, catalog, catalogError, agents, client, onClose, onPick, onTrigger, onRetry }: Props) {
  const [search, setSearch] = useState("");
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const q = fold(search);
  const searching = !!q;
  const matches = (text: string) => !q || fold(text).includes(q);

  const after = ctx.after ? (ctx.after === TRIGGER ? "o gatilho" : `«${flow.passos.find((s) => s.id === ctx.after)?.titulo ?? ctx.after}»`) : null;
  const where = ctx.trigger
    ? "troca o jeito de começar; os passos ficam"
    : ctx.between
      ? "entra no meio da ligação"
      : after
        ? `depois de ${after}${ctx.ramo ? `, no ramo ${ctx.ramo}` : ""}`
        : "solto no canvas; ligue depois";

  const tools = catalog?.ferramentas ?? [];
  const groups = new Map<string, { name: string; elem: ReturnType<typeof toolGroup>["elem"]; tools: Tool[] }>();
  for (const t of tools) {
    const g = toolGroup(t);
    if (!groups.has(g.key)) groups.set(g.key, { name: g.name, elem: g.elem, tools: [] });
    groups.get(g.key)!.tools.push(t);
  }
  const toolHits = tools.filter((t) => matches(`${toolGroup(t).name} ${toolTitle(t.nome)} ${t.nome} ${t.descricao}`));
  const gallery = [
    { key: "claude", label: "Claude Code", sub: "claude · padrão", draft: { tipo: "agente", titulo: "Pedido ao Claude", cli: "claude" } as StepDraft },
    { key: "codex", label: "Codex", sub: "codex · padrão", draft: { tipo: "agente", titulo: "Pedido ao Codex", cli: "codex" } as StepDraft },
    ...(catalog?.agentes ?? []).filter((a) => (a.cli as string) !== "outra").map((a) => ({
      key: a.id,
      label: a.nome,
      sub: a.cli,
      draft: { tipo: "agente", titulo: `Pedido para ${a.nome}`, agente: a.id, cli: a.cli } as StepDraft,
    })),
  ].filter((g) => matches(`${g.label} ${g.sub} agente`));
  const logic = LOGIC.filter((k) => matches(`${KIND[k].label} ${KIND[k].hint}`));
  const codeHit = matches("código python javascript");
  const triggers = TRIGGERS.filter((t) => matches(`${t.title} ${t.hint} gatilho`));
  const nothing = searching && !toolHits.length && !gallery.length && !logic.length && !(ctx.trigger && triggers.length);

  const pickTool = (t: Tool) =>
    onPick({ tipo: "ferramenta", titulo: toolTitle(t.nome), ferramenta: t.nome, argumentos: {} });

  const toolRow = (t: Tool, sub: boolean) => (
    <button key={t.nome} type="button" className={sub ? "af-pick af-sub-pick" : "af-pick"} onClick={() => pickTool(t)} title={t.descricao}>
      {!sub && (
        <span className="af-pick-icon">
          <ElemMark elem={toolGroup(t).elem} size={13} />
        </span>
      )}
      <span>
        <b>{toolTitle(t.nome)}</b>
        <span className="small af-clamp">{toolDescription(t) || t.nome}</span>
      </span>
      {t.pessoas && (
        <span className="af-people" title="Fala com outras pessoas: pede aprovação, e no teste vira ensaio">
          <Icon d={P.lock} size={11} strokeWidth={2} />
        </span>
      )}
    </button>
  );

  return (
    <aside className="af-drawer" onPointerDown={(event) => event.stopPropagation()}>
      <header className="af-drawer-head">
        <div>
          <h3>{ctx.trigger ? "Quando ela começa?" : "O que acontece depois?"}</h3>
          <span className="small">{where}</span>
        </div>
        <button type="button" className="icon-btn" aria-label="Fechar" onClick={onClose}>
          <Icon d={ICON.close} size={14} />
        </button>
      </header>
      <label className="af-search">
        <Icon d={ICON.search} size={13} strokeWidth={2} />
        <input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar passo, conector ou agente…" />
      </label>
      <div className="af-drawer-body">
        {nothing && <p className="af-empty-note af-drawer-empty">Nada com «{search.trim()}». Tente o nome do conector ou o que o passo faz.</p>}
        {ctx.trigger && triggers.length > 0 && (
          <section>
            <h4 className="af-caps">Gatilhos</h4>
            {triggers.map((t) => (
              <button key={t.tipo} type="button" className="af-pick" aria-pressed={flow.gatilho.tipo === t.tipo} onClick={() => onTrigger(t.tipo)}>
                <span className="af-pick-icon" style={{ color: KIND.gatilho.color }}>
                  <Icon d={P.bolt} size={16} strokeWidth={1.8} />
                </span>
                <span>
                  <b>{t.title}</b>
                  <span className="small">{t.hint}</span>
                </span>
                {flow.gatilho.tipo === t.tipo && <span className="af-current small">agora</span>}
              </button>
            ))}
          </section>
        )}
        {(!ctx.trigger || searching) && (
          <>
            {gallery.length > 0 && (
              <section>
                <h4 className="af-caps">Agentes</h4>
                <div className="af-agents">
                  {gallery.map((g) => (
                    <button key={g.key} type="button" className="af-agent-pick" onClick={() => onPick(g.draft)}>
                      <span className="af-agent-face">
                        <AgentFace step={{ ...g.draft, id: "" }} agents={agents} client={client} size={32} />
                      </span>
                      <b>{g.label}</b>
                      <span className="mono small">{g.sub}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}
            {(!searching || toolHits.length > 0) && (
              <section>
                <h4 className="af-caps">Conectores</h4>
                {!catalog && !catalogError && <p className="af-empty-note af-drawer-empty">Carregando as ferramentas da central…</p>}
                {catalogError && (
                  <div className="af-empty-note af-drawer-empty">
                    <p>Não deu para ler o catálogo: {catalogError}</p>
                    <button type="button" className="btn" onClick={onRetry}>
                      Tentar de novo
                    </button>
                  </div>
                )}
                {searching
                  ? toolHits.map((t) => toolRow(t, false))
                  : [...groups.entries()].map(([key, g]) => (
                      <div key={key} className="af-group" data-open={openGroup === key ? "true" : undefined}>
                        <button type="button" className="af-pick" onClick={() => setOpenGroup((cur) => (cur === key ? null : key))}>
                          <span className="af-pick-icon">
                            <ElemMark elem={g.elem} size={13} />
                          </span>
                          <span>
                            <b>{g.name}</b>
                            <span className="small">
                              {g.tools.length} {g.tools.length === 1 ? "ferramenta" : "ferramentas"}
                            </span>
                          </span>
                          <span className="af-chev">
                            <Icon d={ICON.chevron} size={13} />
                          </span>
                        </button>
                        {openGroup === key && g.tools.map((t) => toolRow(t, true))}
                      </div>
                    ))}
              </section>
            )}
            {(logic.length > 0 || (!searching && codeHit)) && (
              <section>
                <h4 className="af-caps">Lógica e dados</h4>
                {logic.map((k) => (
                  <button key={k} type="button" className="af-pick" onClick={() => onPick({ ...LOGIC_DRAFT[k] })}>
                    <span className="af-pick-icon" style={{ color: KIND[k].color }}>
                      <Icon d={KIND[k].icon!} size={16} strokeWidth={1.8} />
                    </span>
                    <span>
                      <b>{KIND[k].label}</b>
                      <span className="small">{KIND[k].hint}</span>
                    </span>
                  </button>
                ))}
                {codeHit && (
                  <button type="button" className="af-pick" disabled title="Chega na 0.9.x">
                    <span className="af-pick-icon" style={{ color: "var(--mut)" }}>
                      <Icon d={P.code} size={16} strokeWidth={1.8} />
                    </span>
                    <span>
                      <b>Código</b>
                      <span className="small">Python ou JavaScript local · chega na 0.9.x</span>
                    </span>
                  </button>
                )}
              </section>
            )}
          </>
        )}
      </div>
      <footer className="af-drawer-foot small">Cada conta ligada em Conectores aparece aqui com as ferramentas dela, sem configurar nada.</footer>
    </aside>
  );
}
