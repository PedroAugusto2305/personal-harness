import { useState } from "react";
import type { CoreClient } from "../lib/core";
import type { Agent, AutoSettings } from "../types";
import { AgentSprite } from "./AgentSprite";
import { KindIcon } from "./KindIcon";

/**
 * Quem roda a tarefa e como (v0.9.9, no "Rodar sozinha" do raio). Na v1.1 o mesmo painel
 * aparece no cartão aberto, então mora aqui. O jeito escolhido fica guardado para as próximas.
 */

const AUTO_KEY = "harness.kanban.auto";
const DEFAULT_AUTO: AutoSettings = { cli: "claude", agente: "", modelo: "", esforco: "", permissao: "auto", onde: "worktree" };

export const MODELS: Record<"claude" | "codex", [string, string][]> = {
  claude: [
    ["", "padrão da CLI"],
    ["opus", "Opus"],
    ["sonnet", "Sonnet"],
    ["haiku", "Haiku"],
  ],
  codex: [
    ["", "padrão da CLI"],
    ["gpt-5.5", "GPT-5.5"],
    ["gpt-5.5-codex", "GPT-5.5 Codex"],
    ["gpt-5.5-mini", "GPT-5.5 mini"],
  ],
};

const EFFORTS: [AutoSettings["esforco"], string][] = [
  ["", "padrão"],
  ["low", "baixo"],
  ["medium", "médio"],
  ["high", "alto"],
  ["xhigh", "máximo"],
];

const PERMISSIONS: [AutoSettings["permissao"], string][] = [
  ["auto", "Automático (a CLI decide o que é seguro)"],
  ["manual", "Pedir aprovação (para no meio, à sua espera)"],
  ["padrao", "Como está configurado na CLI"],
  ["yolo", "Acesso total, sem perguntar"],
];

function storedAuto(): AutoSettings {
  try {
    return { ...DEFAULT_AUTO, ...JSON.parse(localStorage.getItem(AUTO_KEY) || "{}") };
  } catch {
    return DEFAULT_AUTO;
  }
}

export function saveRunSettings(settings: AutoSettings): void {
  try {
    localStorage.setItem(AUTO_KEY, JSON.stringify(settings));
  } catch {
    // sem armazenamento: só não lembra
  }
}

/** O jeito guardado (o agente apagado volta para a CLI, sem mandar um id morto) e a CLI que vale. */
export function useRunSettings(agents: Agent[]) {
  const [settings, setSettings] = useState<AutoSettings>(() => {
    const saved = storedAuto();
    return saved.agente && !agents.some((a) => a.id === saved.agente) ? { ...saved, agente: "", modelo: "" } : saved;
  });
  const agent = agents.find((a) => a.id === settings.agente) ?? null;
  const cli = (agent && agent.cli !== "outra" ? agent.cli : settings.cli) as "claude" | "codex";
  return { settings: { ...settings, cli }, setSettings, agent, cli };
}

/** Rótulo curto do jeito escolhido ("Claude Code · Opus · worktree"). */
export function runSummary(settings: AutoSettings, agents: Agent[]): string {
  const agent = agents.find((a) => a.id === settings.agente);
  const who = agent ? agent.name : settings.cli === "codex" ? "Codex" : "Claude Code";
  const model = MODELS[settings.cli]?.find(([value]) => value === settings.modelo)?.[1];
  return [who, settings.modelo ? (model ?? settings.modelo) : agent?.model || "", settings.onde === "worktree" ? "worktree" : "pasta do projeto"]
    .filter(Boolean)
    .join(" · ");
}

export function RunSettingsPanel(props: {
  settings: AutoSettings;
  onChange: (next: AutoSettings) => void;
  agents: Agent[];
  client: CoreClient | null;
}) {
  const { settings: s, agents } = props;
  const agent = agents.find((a) => a.id === s.agente) ?? null;
  const cli = (agent && agent.cli !== "outra" ? agent.cli : s.cli) as "claude" | "codex";
  const set = <K extends keyof AutoSettings>(key: K, value: AutoSettings[K]) => props.onChange({ ...s, [key]: value });
  const usable = agents.filter((a) => a.cli === "claude" || a.cli === "codex");
  return (
    <>
      <div className="kb2-options" role="radiogroup" aria-label="Quem roda">
        {(["claude", "codex"] as const).map((c) => (
          <button key={c} type="button" role="radio" aria-checked={!s.agente && s.cli === c} className="kb2-option" onClick={() => props.onChange({ ...s, cli: c, agente: "", modelo: "" })}>
            <span className="kb2-glyph" data-cli={c}>
              <KindIcon kind={c} size={16} />
            </span>
            {c === "claude" ? "Claude Code" : "Codex"}
          </button>
        ))}
        {usable.map((a) => (
          <button key={a.id} type="button" role="radio" aria-checked={s.agente === a.id} className="kb2-option" onClick={() => props.onChange({ ...s, agente: a.id, modelo: "" })} title={a.description}>
            <AgentSprite agent={a} client={props.client} size={16} />
            {a.name}
          </button>
        ))}
      </div>
      <div className="kb2-fields">
        <label>
          <span>Modelo</span>
          <select value={s.modelo} onChange={(e) => set("modelo", e.target.value)}>
            {MODELS[cli].map(([value, label]) => (
              <option key={value} value={value}>
                {agent && !value && agent.model ? `o do agente (${agent.model})` : label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Raciocínio</span>
          <select value={s.esforco} onChange={(e) => set("esforco", e.target.value as AutoSettings["esforco"])}>
            {EFFORTS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="wide">
          <span>Permissões</span>
          <select value={s.permissao} onChange={(e) => set("permissao", e.target.value as AutoSettings["permissao"])}>
            {PERMISSIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="kb2-places" role="radiogroup" aria-label="Onde roda">
        <button type="button" role="radio" aria-checked={s.onde === "worktree"} className="kb2-place" onClick={() => set("onde", "worktree")}>
          <span className="kb2-radio" />
          <span>
            <b>Worktree git</b>
            <small>cópia de trabalho separada</small>
          </span>
        </button>
        <button type="button" role="radio" aria-checked={s.onde === "pasta"} className="kb2-place" onClick={() => set("onde", "pasta")}>
          <span className="kb2-radio" />
          <span>
            <b>Pasta do projeto</b>
            <small>usa a pasta que já existe</small>
          </span>
        </button>
      </div>
    </>
  );
}
