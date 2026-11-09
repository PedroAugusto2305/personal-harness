import { useEffect, useRef, useState } from "react";
import { Confirm } from "./Confirm";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { shortPath } from "../lib/format";
import type { Accounts, Agent, AgentDraft, AgentEvent, ConnectorAccount, Session } from "../types";
import { AgentSprite, GreekBust } from "./AgentSprite";
import { AgentsRoom } from "./AgentsRoom";
import { SpriteChat } from "./SpriteChat";

const SWATCHES = ["#82a0ff", "#007AFF", "#5AC8FA", "#8be9fd", "#bd93f9", "#AF52DE", "#FF2D55", "#FF3B30", "#d97757", "#a9aec9"];
const EMPTY: AgentDraft = { name: "", description: "", pain: "", cli: "claude", model: "", account: "", folder: "", color: "#82a0ff", connectors: "", prompt: "", args: "", env: "", command: "" };
const CLI_LABEL: Record<Agent["cli"], string> = { claude: "Claude Code", codex: "Codex", outra: "Outra CLI" };
const SPRITE_MAX = 256;

interface Props {
  client: CoreClient | null;
  agents: Agent[];
  accounts: Accounts;
  run: <T>(action: (core: CoreClient) => Promise<T>) => Promise<T | null>;
  onLaunch: (agent: Agent) => void;
  /** Abre um terminal com o rascunho, sem salvar ("testar antes de salvar"). */
  onTest: (draft: AgentDraft) => void;
  connectors: ConnectorAccount[];
  /** v0.9.9: a Sala dos agentes. */
  sessions: Session[];
  events: AgentEvent[];
  tick: number;
  onOpenSession: (id: string) => void;
}

const SELECTED_KEY = "harness.agents.selected";

function storedSelected(): string | null {
  try {
    return localStorage.getItem(SELECTED_KEY);
  } catch {
    return null;
  }
}

/**
 * Tela de Agentes (v0.9.9): abre na Sala dos agentes, com o último agente aberto à direita;
 * Editar e Novo agente trocam a sala pelo formulário, com o caminho de volta no topo.
 */
export function Agents(props: Props) {
  const [mode, setMode] = useState<"sala" | "editar">("sala");
  const [selected, setSelected] = useState<string | null>(storedSelected);
  const [editing, setEditing] = useState<string | "novo">("novo");
  const [notice, setNotice] = useState<string | null>(null);
  /** v0.9.9: o agente esperando a confirmação para ir para a lixeira. */
  const [deleting, setDeleting] = useState<Agent | null>(null);
  const [busy, setBusy] = useState(false);
  const openCount = (id: string) => props.sessions.filter((s) => s.agent === id && s.status !== "exited").length;

  const select = (id: string | null) => {
    setSelected(id);
    try {
      if (id) localStorage.setItem(SELECTED_KEY, id);
      else localStorage.removeItem(SELECTED_KEY);
    } catch {
      // sem armazenamento: só não lembra
    }
  };

  useEffect(() => {
    if (selected && props.agents.length && !props.agents.some((a) => a.id === selected)) select(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.agents, selected]);

  if (mode === "editar") {
    return (
      <AgentEditor
        {...props}
        selectedId={editing}
        onBack={() => setMode("sala")}
        onSaved={(id) => {
          select(id);
          setEditing(id);
        }}
        onDeleted={() => {
          select(null);
          setMode("sala");
        }}
      />
    );
  }
  return (
    <>
    <AgentsRoom
      client={props.client}
      agents={props.agents}
      accounts={props.accounts}
      sessions={props.sessions}
      events={props.events}
      connectors={props.connectors}
      tick={props.tick}
      selected={selected}
      onSelect={select}
      onEdit={(id) => {
        select(id);
        setEditing(id);
        setMode("editar");
      }}
      onNew={() => {
        setEditing("novo");
        setMode("editar");
      }}
      onImport={async () => {
        const result = await props.run((c) => c.importMaestri());
        if (result) setNotice(result.imported.length ? `Importados: ${result.imported.join(", ")}.` : "Nada novo para importar do Maestri.");
      }}
      onLaunch={props.onLaunch}
      onOpenSession={props.onOpenSession}
      onDelete={setDeleting}
      notice={notice}
    />
    {deleting && (
      <Confirm
        title={`Apagar ${deleting.name}?`}
        confirmLabel="Apagar"
        danger
        busy={busy}
        onCancel={() => setDeleting(null)}
        onConfirm={async () => {
          setBusy(true);
          const ok = await props.run((c) => c.deleteAgent(deleting.id));
          setBusy(false);
          if (ok === null) return;
          if (selected === deleting.id) select(null);
          setNotice(`${deleting.name} foi para a lixeira dos agentes.`);
          setDeleting(null);
        }}
      >
        <p>
          O arquivo e a sprite vão para <span className="mono">~/.harness/agentes/.lixeira</span>: dá para recuperar de lá.
          {openCount(deleting.id) > 0 &&
            ` ${openCount(deleting.id) === 1 ? "A sessão aberta dele continua" : `As ${openCount(deleting.id)} sessões abertas dele continuam`} até você fechar.`}
        </p>
      </Confirm>
    )}
    </>
  );
}

interface EditorProps extends Props {
  selectedId: string | "novo";
  onBack: () => void;
  onSaved: (id: string) => void;
  onDeleted: () => void;
}

export const toDraft = (agent: Agent): AgentDraft => ({
  name: agent.name,
  description: agent.description,
  pain: agent.pain ?? "",
  cli: agent.cli,
  model: agent.model,
  account: agent.account,
  folder: agent.folder,
  connectors: agent.connectors ?? "",
  color: agent.color,
  prompt: agent.prompt,
  args: agent.args ?? "",
  env: agent.env ?? "",
  command: agent.command ?? "",
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

function AgentEditor({ client, agents, accounts, run, onLaunch, onTest, connectors, selectedId, onBack, onSaved, onDeleted }: EditorProps) {
  const [describe, setDescribe] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [spriteIdea, setSpriteIdea] = useState("");
  const [draft, setDraft] = useState<AgentDraft>(EMPTY);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  /** Sprite escolhida no chat: num agente novo, só é aplicada ao criar. */
  const [chosenSprite, setChosenSprite] = useState<string | null>(null);
  const spriteInput = useRef<HTMLInputElement>(null);
  const current = agents.find((a) => a.id === selectedId) ?? null;

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
      onSaved(saved.id);
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

  const accountOptions = draft.cli === "outra" ? [] : accounts[draft.cli].accounts;

  return (
    <div className="agents-screen">
      <div className="agent-editor">
        <div className="agent-editor-top">
          <button type="button" className="room-link" onClick={onBack}>
            ← Sala dos agentes
          </button>
          {notice && <span className="small notice">{notice}</span>}
        </div>
        {(
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

            {selectedId === "novo" && (
              <div className="card agent-describe">
                <span className="setting-label">
                  Descrever o agente
                  <span className="small">Em uma frase: o que ele faz e qual dor sua resolve. O Claude rascunha os campos e você revisa antes de criar.</span>
                </span>
                <textarea
                  rows={2}
                  value={describe}
                  onChange={(e) => setDescribe(e.target.value)}
                  placeholder="Ex.: um agente que lê minhas capturas do dia toda noite e transforma em tarefas nos projetos certos"
                />
                <div className="form-buttons">
                  <button
                    type="button"
                    className="btn"
                    disabled={drafting || describe.trim().length < 8}
                    onClick={async () => {
                      setDrafting(true);
                      setNotice("Rascunhando com o Claude (uns 20 a 60 segundos)…");
                      const suggestion = await run((c) => c.draftAgent(describe));
                      setDrafting(false);
                      if (!suggestion) return setNotice(null);
                      setDraft((d) => ({
                        ...d,
                        name: suggestion.name,
                        description: suggestion.description,
                        pain: suggestion.pain,
                        cli: suggestion.cli,
                        color: suggestion.color,
                        folder: suggestion.folder,
                        prompt: suggestion.prompt,
                      }));
                      setSpriteIdea(suggestion.sprite);
                      setNotice("Rascunho pronto: revise os campos, teste e crie.");
                    }}
                  >
                    {drafting ? "Rascunhando…" : "Rascunhar com o Claude"}
                  </button>
                  {spriteIdea && <span className="small agent-sprite-idea">Ideia de sprite: {spriteIdea}</span>}
                </div>
              </div>
            )}

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
              <label className="wide">
                <span className="setting-label">Qual dor resolve?</span>
                <input value={draft.pain} onChange={(e) => set("pain", e.target.value)} placeholder="Um agente, uma tarefa: agente novo só com dor real" />
              </label>
              <div>
                <span className="setting-label">CLI</span>
                <div className="segmented" role="radiogroup" aria-label="CLI do agente">
                  {(["claude", "codex", "outra"] as const).map((cli) => (
                    <button key={cli} type="button" role="radio" aria-checked={draft.cli === cli} onClick={() => setDraft((d) => ({ ...d, cli, account: "" }))}>
                      {CLI_LABEL[cli]}
                    </button>
                  ))}
                </div>
              </div>
              {draft.cli === "outra" ? (
                <label className="wide">
                  <span className="setting-label">
                    Comando
                    <span className="small">A CLI e os argumentos de sempre, como você digitaria no terminal (ex.: opencode, aider --model sonnet). Roda num terminal comum, sem a central de MCP.</span>
                  </span>
                  <input className="mono" value={draft.command ?? ""} onChange={(e) => set("command", e.target.value)} placeholder="opencode" spellCheck={false} required />
                </label>
              ) : (
              <label>
                <span className="setting-label">Modelo</span>
                <input value={draft.model} onChange={(e) => set("model", e.target.value)} placeholder="padrão da CLI (ex.: sonnet, opus, gpt-5)" />
              </label>
              )}
              {draft.cli !== "outra" && (
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
              )}
              <label>
                <span className="setting-label">Pasta</span>
                <input value={draft.folder} onChange={(e) => set("folder", e.target.value)} placeholder="vazio = abre na worktree escolhida" spellCheck={false} />
              </label>
              {draft.cli !== "outra" && (
              <div className="wide">
                <span className="setting-label">
                  Conectores
                  <span className="small">O que este agente pode usar pela central de MCP (Slack, ClickUp). Brain e kanban valem sempre.</span>
                </span>
                <div className="agent-connectors">
                  {(
                    [
                      ["", "Todas as contas"],
                      ["nenhum", "Nenhuma"],
                    ] as const
                  ).map(([value, label]) => (
                    <label key={label} className="small">
                      <input type="radio" checked={draft.connectors === value} onChange={() => set("connectors", value)} />
                      {label}
                    </label>
                  ))}
                  {connectors.map((account) => {
                    const chosen = draft.connectors && draft.connectors !== "nenhum" ? draft.connectors.split(",") : [];
                    const on = chosen.includes(account.id);
                    return (
                      <label key={account.id} className="small">
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => {
                            const next = on ? chosen.filter((c) => c !== account.id) : [...chosen, account.id];
                            set("connectors", next.join(",") || "nenhum");
                          }}
                        />
                        {account.name}
                      </label>
                    );
                  })}
                  {!connectors.length && <span className="small">Nenhuma conta conectada ainda (tela Conectores).</span>}
                </div>
              </div>
              )}
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
                  Argumentos extras
                  <span className="small">Vão no fim da linha de comando, em sintaxe de shell (ex.: --verbose --max-turns 30).</span>
                </span>
                <input className="mono" value={draft.args ?? ""} onChange={(e) => set("args", e.target.value)} placeholder="nenhum" spellCheck={false} />
              </label>
              <label className="wide">
                <span className="setting-label">
                  Variáveis de ambiente
                  <span className="small">Uma por linha, CHAVE=valor. Só deste agente (as da MÊTIS e o PATH não mudam).</span>
                </span>
                <textarea className="mono" rows={3} value={draft.env ?? ""} onChange={(e) => set("env", e.target.value)} placeholder="ANTHROPIC_MODEL=claude-opus-5-5" spellCheck={false} />
              </label>
              {draft.cli !== "outra" && (
              <label className="wide">
                <span className="setting-label">
                  Papel
                  <span className="small">
                    Vai junto como instrução de sistema: {draft.cli === "claude" ? "--append-system-prompt" : "developer_instructions"}.
                  </span>
                </span>
                <textarea className="prompt mono" value={draft.prompt} onChange={(e) => set("prompt", e.target.value)} rows={14} spellCheck={false} />
              </label>
              )}
            </div>

            <div className="form-buttons">
              <button type="submit" className="btn primary" disabled={!dirty || !draft.name.trim()}>
                {selectedId === "novo" ? "Criar agente" : "Salvar"}
              </button>
              {(selectedId === "novo" || dirty) && (
                <button
                  type="button"
                  className="btn"
                  disabled={!draft.name.trim() || !draft.prompt.trim()}
                  title="Abre um terminal com este papel, sem salvar"
                  onClick={() => onTest(draft)}
                >
                  Testar sem salvar
                </button>
              )}
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
                        onDeleted();
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
