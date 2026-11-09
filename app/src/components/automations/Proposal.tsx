// Automações por IA e por importação (v0.9.8): descrever numa frase, importar um workflow do
// n8n e começar de uma estratégia de agentes. A proposta da IA nunca é salva sozinha: ela
// aparece tracejada no canvas e só vira rascunho quando o Pedro aplica.

import { useEffect, useState } from "react";
import { ICON, Icon } from "../../icons";
import type { CoreClient } from "../../lib/core";
import type { AutoProposal, AutoStrategy, ConnectorAccount } from "../../types";

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export type CreateWay = "frase" | "n8n" | "estrategia";

interface Props {
  client: CoreClient;
  way: CreateWay;
  /** Contas de MCP próprio (uma delas pode ser o n8n). */
  mcpAccounts: ConnectorAccount[];
  onWay: (way: CreateWay) => void;
  onClose: () => void;
  /** A proposta pronta: a tela cria a automação com esse nome e mostra a proposta tracejada. */
  onProposal: (nome: string, proposal: AutoProposal) => Promise<void>;
  /** A estratégia já criou o rascunho. */
  onCreated: (id: string) => Promise<void>;
}

/** Janela "Nova automação" com os três jeitos novos de começar. */
export function CreateDialog({ client, way, mcpAccounts, onWay, onClose, onProposal, onCreated }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // frase
  const [phrase, setPhrase] = useState("");
  // n8n
  const [json, setJson] = useState("");
  const [account, setAccount] = useState(mcpAccounts[0]?.id ?? "");
  const [flows, setFlows] = useState<{ id: string; nome: string; ativo: boolean }[] | null>(null);
  const [flowId, setFlowId] = useState("");
  // estratégia
  const [strategies, setStrategies] = useState<AutoStrategy[] | null>(null);
  const [strategy, setStrategy] = useState("");
  const [params, setParams] = useState<Record<string, string | number>>({});

  useEffect(() => {
    if (way !== "estrategia" || strategies) return;
    void client
      .strategies()
      .then((answer) => {
        setStrategies(answer.estrategias);
        const first = answer.estrategias[0];
        if (first) {
          setStrategy(first.id);
          setParams(Object.fromEntries(first.parametros.map((p) => [p.nome, p.padrao])));
        }
      })
      .catch((cause) => setError(message(cause)));
  }, [client, way, strategies]);

  const run = async (job: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await job();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  };

  const fromPhrase = () =>
    run(async () => {
      const answer = await client.proposeAutomation(phrase.trim());
      await onProposal(answer.proposta.nome || phrase.trim().slice(0, 60), answer);
    });

  const fromN8n = () =>
    run(async () => {
      let body: { fluxo: unknown } | { conta: string; workflow_id: string };
      if (json.trim()) {
        try {
          body = { fluxo: JSON.parse(json) };
        } catch {
          throw new Error("isso não é um JSON válido: copie o workflow inteiro (no n8n, ⋯ → Download, ou selecione tudo e copie)");
        }
      } else body = { conta: account, workflow_id: flowId };
      const answer = await client.importN8n(body);
      await onProposal(answer.nome || answer.proposta.nome, answer);
    });

  const loadFlows = () =>
    run(async () => {
      setFlows(null);
      const answer = await client.n8nFlows(account);
      setFlows(answer.fluxos);
      setFlowId(answer.fluxos[0]?.id ?? "");
    });

  const fromStrategy = () =>
    run(async () => {
      const answer = await client.createFromStrategy(strategy, params);
      await onCreated(answer.id);
    });

  const chosen = strategies?.find((s) => s.id === strategy);
  return (
    <div className="af-modal af-overlay" onPointerDown={(event) => event.stopPropagation()}>
      <div className="af-modal-box" role="dialog" aria-label="Nova automação">
        <header className="af-modal-head">
          <div className="segmented small-seg" role="tablist">
            {(
              [
                ["frase", "Descrever numa frase"],
                ["n8n", "Importar do n8n"],
                ["estrategia", "Estratégia de agentes"],
              ] as [CreateWay, string][]
            ).map(([value, label]) => (
              <button key={value} type="button" role="tab" aria-selected={way === value} onClick={() => (setError(null), onWay(value))}>
                {label}
              </button>
            ))}
          </div>
          <button type="button" className="icon-btn" aria-label="Fechar" onClick={onClose}>
            <Icon d={ICON.close} size={13} strokeWidth={2} />
          </button>
        </header>

        {way === "frase" && (
          <div className="af-modal-body">
            <p className="small">
              Diga o que a automação faz, quando começa e onde chega o resultado. O Claude monta os passos com os seus conectores e agentes; você vê a proposta tracejada e aplica
              se gostar.
            </p>
            <textarea
              className="af-input"
              rows={4}
              autoFocus
              value={phrase}
              onChange={(event) => setPhrase(event.target.value)}
              placeholder="Toda segunda às 8h, ler as tarefas atrasadas do ClickUp, pedir ao Claude um resumo por cliente e mandar na minha DM do Slack"
            />
            <div className="af-row">
              <button type="button" className="btn primary" disabled={busy || phrase.trim().length < 3} onClick={() => void fromPhrase()}>
                {busy ? "Montando…" : "Montar a proposta"}
              </button>
            </div>
          </div>
        )}

        {way === "n8n" && (
          <div className="af-modal-body">
            <p className="small">
              Cole o JSON de um workflow do n8n. A MÊTIS traduz nó a nó; o que não tem igual (webhook, HTTP solto, nó de IA) entra marcado para revisar. Credenciais do
              workflow não vêm junto.
            </p>
            <textarea className="af-input mono" rows={7} value={json} onChange={(event) => setJson(event.target.value)} placeholder='{"name": "…", "nodes": [...], "connections": {...}}' spellCheck={false} />
            {mcpAccounts.length > 0 && (
              <div className="af-n8n-account">
                <span className="small">ou ler de um n8n ligado em Conectores (MCP próprio):</span>
                <select value={account} onChange={(event) => (setAccount(event.target.value), setFlows(null))}>
                  {mcpAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                <button type="button" className="btn" disabled={busy || !account} onClick={() => void loadFlows()}>
                  Ver workflows
                </button>
                {flows && (
                  <select value={flowId} onChange={(event) => setFlowId(event.target.value)}>
                    {flows.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.nome}
                        {f.ativo ? " · ativo" : ""}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
            <div className="af-row">
              <button type="button" className="btn primary" disabled={busy || (!json.trim() && !flowId)} onClick={() => void fromN8n()}>
                {busy ? "Traduzindo…" : "Traduzir"}
              </button>
            </div>
          </div>
        )}

        {way === "estrategia" && (
          <div className="af-modal-body">
            {!strategies && !error && <p className="small">Carregando…</p>}
            {strategies && (
              <>
                <div className="af-strategies">
                  {strategies.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className="af-pick"
                      aria-pressed={s.id === strategy}
                      onClick={() => {
                        setStrategy(s.id);
                        setParams(Object.fromEntries(s.parametros.map((p) => [p.nome, p.padrao])));
                      }}
                    >
                      <span>
                        <b>{s.nome}</b>
                        <span className="small">{s.descricao}</span>
                      </span>
                    </button>
                  ))}
                </div>
                {chosen && (
                  <div className="af-strategy-params">
                    {chosen.parametros.map((p) => (
                      <label key={p.nome}>
                        <span className="small">{p.rotulo}</span>
                        {p.tipo === "cli" ? (
                          <select value={String(params[p.nome] ?? p.padrao)} onChange={(event) => setParams({ ...params, [p.nome]: event.target.value })}>
                            <option value="claude">Claude</option>
                            <option value="codex">Codex</option>
                          </select>
                        ) : p.tipo === "texto" ? (
                          <textarea className="af-input" rows={3} value={String(params[p.nome] ?? "")} onChange={(event) => setParams({ ...params, [p.nome]: event.target.value })} />
                        ) : (
                          <input
                            className="af-input mono"
                            inputMode={p.tipo === "numero" ? "numeric" : undefined}
                            value={String(params[p.nome] ?? "")}
                            placeholder={p.tipo === "pasta" ? "~/orca/workspaces/projeto/tarefa" : ""}
                            onChange={(event) => setParams({ ...params, [p.nome]: p.tipo === "numero" ? Number(event.target.value) || 0 : event.target.value })}
                          />
                        )}
                      </label>
                    ))}
                  </div>
                )}
                <div className="af-row">
                  <button type="button" className="btn primary" disabled={busy || !strategy} onClick={() => void fromStrategy()}>
                    {busy ? "Criando…" : "Criar o rascunho"}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
        {error && <p className="af-error small af-modal-error">{error}</p>}
      </div>
    </div>
  );
}

/** Faixa em cima da proposta tracejada: o que o Claude montou, o que revisar, aplicar ou descartar. */
export function ProposalBanner({ proposal, busy, onApply, onDiscard }: { proposal: AutoProposal; busy: boolean; onApply: () => void; onDiscard: () => void }) {
  return (
    <div className="af-proposal af-overlay" onPointerDown={(event) => event.stopPropagation()}>
      <div className="af-proposal-head">
        <b>Proposta</b>
        <span className="small">tracejada: ainda não está no rascunho</span>
      </div>
      {proposal.explicacao && <p className="small">{proposal.explicacao}</p>}
      {proposal.revisar && proposal.revisar.length > 0 && (
        <ul className="af-proposal-review small">
          {proposal.revisar.map((item, i) => (
            <li key={i}>
              <b>{item.passo}</b>: {item.motivo}
            </li>
          ))}
        </ul>
      )}
      <div className="af-row">
        <button type="button" className="btn primary" disabled={busy} onClick={onApply}>
          Aplicar ao rascunho
        </button>
        <button type="button" className="btn" onClick={onDiscard}>
          Descartar
        </button>
      </div>
    </div>
  );
}
