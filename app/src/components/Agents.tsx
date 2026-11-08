import { useEffect, useRef, useState } from "react";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { KIND_LABEL, shortPath } from "../lib/format";
import type { Accounts, Agent, AgentDraft } from "../types";
import { AgentSprite, GreekBust } from "./AgentSprite";
import { SpriteChat } from "./SpriteChat";

const SWATCHES = ["#82a0ff", "#007AFF", "#5AC8FA", "#8be9fd", "#bd93f9", "#AF52DE", "#FF2D55", "#FF3B30", "#d97757", "#a9aec9"];
const EMPTY: AgentDraft = { name: "", description: "", cli: "claude", model: "", account: "", folder: "", color: "#82a0ff", prompt: "" };
const SPRITE_MAX = 256;

interface Props {
  client: CoreClient | null;
  agents: Agent[];
  accounts: Accounts;
  run: <T>(action: (core: CoreClient) => Promise<T>) => Promise<T | null>;
  onLaunch: (agent: Agent) => void;
}

const toDraft = (agent: Agent): AgentDraft => ({
  name: agent.name,
  description: agent.description,
  cli: agent.cli,
  model: agent.model,
  account: agent.account,
  folder: agent.folder,
  color: agent.color,
  prompt: agent.prompt,
});

/** Qualquer imagem vira PNG de até 256 px, para servir de sprite. */
async function toPng(file: File): Promise<Blob> {
  if (file.type === "image/png" && file.size < 2 * 1024 * 1024) return file;
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, SPRITE_MAX / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const ctx = canvas.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("não deu para converter"))), "image/png"));
}

export function Agents({ client, agents, accounts, run, onLaunch }: Props) {
  const [selectedId, setSelectedId] = useState<string | "novo" | null>(agents[0]?.id ?? null);
  const [draft, setDraft] = useState<AgentDraft>(EMPTY);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  /** Sprite escolhida no chat: num agente novo, só é aplicada ao criar. */
  const [chosenSprite, setChosenSprite] = useState<string | null>(null);
  const spriteInput = useRef<HTMLInputElement>(null);
  const current = agents.find((a) => a.id === selectedId) ?? null;

  useEffect(() => {
    if (selectedId === "novo") return;
    if (!current && agents.length) setSelectedId(agents[0].id);
  }, [agents, current, selectedId]);

  useEffect(() => {
    setConfirmDelete(false);
    setChosenSprite(null);
    if (selectedId === "novo") setDraft(EMPTY);
    else if (current) setDraft(toDraft(current));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, current?.updated_at]);

  const dirty = selectedId === "novo" ? !!draft.name.trim() : current ? JSON.stringify(toDraft(current)) !== JSON.stringify(draft) : false;
  const set = <K extends keyof AgentDraft>(key: K, value: AgentDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const save = async () => {
    const creating = selectedId === "novo" || !current;
    const saved = creating ? await run((c) => c.createAgent(draft)) : await run((c) => c.updateAgent(current.id, draft));
    if (saved) {
      if (creating && chosenSprite) await run((c) => c.useSpriteJob(saved.id, chosenSprite));
      setSelectedId(saved.id);
      setNotice("Salvo.");
    }
  };

  const applySprite = async (job: string) => {
    if (current) {
      const ok = await run((c) => c.useSpriteJob(current.id, job));
      if (ok !== null) setChosenSprite(job);
    } else {
      setChosenSprite(job); // agente novo: aplica ao criar
    }
  };

  const importMaestri = async () => {
    const result = await run((c) => c.importMaestri());
    if (result) setNotice(result.imported.length ? `Importados: ${result.imported.join(", ")}.` : "Nada novo para importar do Maestri.");
  };

  const accountOptions = accounts[draft.cli].accounts;

  return (
    <div className="agents-screen">
      <div className="agents-list">
        <div className="tree-head">
          <span className="section-title">Agentes · {agents.length}</span>
        </div>
        <div className="agents-actions">
          <button type="button" className="btn primary" onClick={() => setSelectedId("novo")}>
            <Icon d={ICON.plus} size={13} strokeWidth={2.2} />
            Novo agente
          </button>
          <button type="button" className="btn" onClick={importMaestri} title="Lê ~/Documents/Brain/.maestri/roles e os terminais do Maestri">
            Importar do Maestri
          </button>
        </div>
        {notice && <p className="small notice">{notice}</p>}
        <div className="agent-cards">
          {agents.map((agent) => (
            <button
              key={agent.id}
              type="button"
              className="agent-card"
              aria-current={agent.id === selectedId ? "true" : undefined}
              onClick={() => setSelectedId(agent.id)}
            >
              <AgentSprite agent={agent} client={client} size={36} />
              <span className="meta">
                <span className="agent-card-name">{agent.name}</span>
                <span className="small">{agent.description || KIND_LABEL[agent.cli]}</span>
              </span>
              <span className="chip">{agent.cli}</span>
            </button>
          ))}
          {agents.length === 0 && (
            <p className="small tree-hint">
              Agente é um papel com prompt próprio que abre o Claude Code ou o Codex já sabendo o que fazer. Crie um ou importe os do
              Maestri.
            </p>
          )}
        </div>
      </div>

      <div className="agent-editor">
        {selectedId == null ? (
          <p className="small inspector-empty">Escolha um agente à esquerda.</p>
        ) : (
          <form
            className="settings-page"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <div className="agent-hero">
              <div className="sprite-box" style={{ borderColor: draft.color }}>
                {!current && chosenSprite && client ? (
                  <img className="pixel sprite-img" src={client.spriteJobUrl(chosenSprite)} width={96} height={96} alt="" />
                ) : current ? (
                  <AgentSprite agent={{ ...current, color: draft.color, name: draft.name || current.name }} client={client} size={96} />
                ) : (
                  <GreekBust seed={`novo${draft.name}`} color={draft.color} size={96} />
                )}
              </div>
              <div className="agent-hero-text">
                <h1>{draft.name || "Novo agente"}</h1>
                <p className="small">
                  {current?.origin?.startsWith("maestri:") && "Importado do Maestri · "}
                  {current ? `~/.harness/agentes/${current.id}.md` : "vira um arquivo em ~/.harness/agentes/"}
                </p>
                {current && (
                  <div className="form-buttons">
                    <button type="button" className="pill" onClick={() => spriteInput.current?.click()}>
                      Enviar PNG
                    </button>
                    {current.sprite && (
                      <button type="button" className="pill ghost" onClick={() => run((c) => c.clearSprite(current.id))}>
                        Usar a padrão
                      </button>
                    )}
                    <input
                      ref={spriteInput}
                      type="file"
                      accept="image/*"
                      hidden
                      onChange={async (event) => {
                        const file = event.target.files?.[0];
                        event.target.value = "";
                        if (!file) return;
                        try {
                          const png = await toPng(file);
                          await run((c) => c.setSprite(current.id, png));
                        } catch (cause) {
                          setNotice(cause instanceof Error ? cause.message : String(cause));
                        }
                      }}
                    />
                  </div>
                )}
                {!current && (
                  <p className="small">
                    {chosenSprite ? "Sprite escolhida: entra quando você criar o agente." : "Sem sprite escolhida, fica o busto padrão na cor do agente."}
                  </p>
                )}
              </div>
            </div>

            <SpriteChat
              key={selectedId}
              client={client}
              name={draft.name}
              description={draft.description}
              color={draft.color}
              chosen={chosenSprite}
              onUse={(job) => void applySprite(job)}
            />

            <div className="card form-grid">
              <label>
                <span className="setting-label">Nome</span>
                <input value={draft.name} maxLength={60} onChange={(e) => set("name", e.target.value)} placeholder="Ex.: Revisor" required />
              </label>
              <label>
                <span className="setting-label">Descrição</span>
                <input value={draft.description} onChange={(e) => set("description", e.target.value)} placeholder="Ex.: Revisa o diff antes do PR" />
              </label>
              <div>
                <span className="setting-label">CLI</span>
                <div className="segmented" role="radiogroup" aria-label="CLI do agente">
                  {(["claude", "codex"] as const).map((cli) => (
                    <button key={cli} type="button" role="radio" aria-checked={draft.cli === cli} onClick={() => setDraft((d) => ({ ...d, cli, account: "" }))}>
                      {KIND_LABEL[cli]}
                    </button>
                  ))}
                </div>
              </div>
              <label>
                <span className="setting-label">Modelo</span>
                <input value={draft.model} onChange={(e) => set("model", e.target.value)} placeholder="padrão da CLI (ex.: sonnet, opus, gpt-5)" />
              </label>
              <label>
                <span className="setting-label">Conta</span>
                <select value={draft.account} onChange={(e) => set("account", e.target.value)}>
                  <option value="">a conta em uso</option>
                  {accountOptions.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="setting-label">Pasta</span>
                <input value={draft.folder} onChange={(e) => set("folder", e.target.value)} placeholder="vazio = abre na worktree escolhida" spellCheck={false} />
              </label>
              <div className="wide">
                <span className="setting-label">Cor</span>
                <div className="swatches">
                  {SWATCHES.map((color) => (
                    <button
                      key={color}
                      type="button"
                      className="swatch"
                      style={{ background: color }}
                      aria-label={`Cor ${color}`}
                      aria-pressed={draft.color.toLowerCase() === color.toLowerCase()}
                      onClick={() => set("color", color)}
                    />
                  ))}
                  <input type="color" value={draft.color} onChange={(e) => set("color", e.target.value)} aria-label="Outra cor" />
                </div>
              </div>
              <label className="wide">
                <span className="setting-label">
                  Papel
                  <span className="small">
                    Vai junto como instrução de sistema: {draft.cli === "claude" ? "--append-system-prompt" : "developer_instructions"}.
                  </span>
                </span>
                <textarea className="prompt mono" value={draft.prompt} onChange={(e) => set("prompt", e.target.value)} rows={14} spellCheck={false} />
              </label>
            </div>

            <div className="form-buttons">
              <button type="submit" className="btn primary" disabled={!dirty || !draft.name.trim()}>
                {selectedId === "novo" ? "Criar agente" : "Salvar"}
              </button>
              {current && (
                <button type="button" className="btn" onClick={() => onLaunch(current)} disabled={dirty} title={dirty ? "Salve antes de abrir" : undefined}>
                  Abrir agente {current.folder ? `em ${shortPath(current.folder)}` : "na worktree escolhida"}
                </button>
              )}
              <span className="grow" />
              {current &&
                (confirmDelete ? (
                  <>
                    <span className="small">Vai para ~/.harness/agentes/.lixeira.</span>
                    <button
                      type="button"
                      className="btn danger"
                      onClick={async () => {
                        await run((c) => c.deleteAgent(current.id));
                        setSelectedId(null);
                      }}
                    >
                      Apagar mesmo
                    </button>
                    <button type="button" className="btn" onClick={() => setConfirmDelete(false)}>
                      Não
                    </button>
                  </>
                ) : (
                  <button type="button" className="btn" onClick={() => setConfirmDelete(true)}>
                    <Icon d={ICON.trash} size={13} />
                    Apagar
                  </button>
                ))}
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
