import { useEffect, useState } from "react";
import type { CoreClient } from "../lib/core";
import type { GitConfig, Prefs } from "../types";
import { Switch } from "./SettingsSystem";

type RecipeKey = "receita_commit" | "receita_commit_marcado" | "receita_pr";

const RECIPES: { key: RecipeKey; label: string; hint: string }[] = [
  {
    key: "receita_commit",
    label: "Commit (nada marcado)",
    hint: "O que o agente da worktree recebe em “Pedir ao agente” quando nada está marcado.",
  },
  {
    key: "receita_commit_marcado",
    label: "Commit (só o marcado)",
    hint: "O mesmo, quando há arquivos marcados: o commit é só deles.",
  },
  {
    key: "receita_pr",
    label: "Pull request",
    hint: "“Pedir ao agente” no cartão do PR. {base} vira o branch de destino; {branch}, o desta worktree.",
  },
];

/**
 * Ajustes → Git (v0.9.6): as receitas do que o agente da worktree faz (commit e PR, sempre
 * no terminal dele, como decidido para o commit por IA), qual CLI abre quando não há agente
 * na worktree, a assinatura dos commits e o editor externo do "Abrir no editor".
 */
export function GitSection({
  client,
  prefs,
  onSave,
}: {
  client: CoreClient | null;
  prefs: Prefs | null;
  onSave: (changes: Partial<Omit<Prefs, "avisos">>) => Promise<void>;
}) {
  const [drafts, setDrafts] = useState<Partial<Record<RecipeKey, string>>>({});
  const [config, setConfig] = useState<GitConfig | null>(null);
  const [editors, setEditors] = useState<{ id: string; nome: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    client.gitConfig().then(setConfig, () => undefined);
    client.editors().then(setEditors, () => undefined);
  }, [client]);

  const toggleSigning = async (on: boolean) => {
    if (!client) return;
    setError(null);
    try {
      setConfig(await client.saveGitConfig(on));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  return (
    <section className="settings-page">
      <h1>Git</h1>
      <p className="lead">
        O commit e o PR escritos por IA são feitos pelo agente da worktree, no terminal dele. Aqui ficam as receitas: o pedido que ele
        recebe em cada ação. Elas valem para todos os projetos.
      </p>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            Agente do git
            <span className="small">Quem abre quando a worktree não tem um Claude ou um Codex aberto.</span>
          </span>
          <select
            value={prefs?.agente_git ?? "claude"}
            disabled={!prefs}
            onChange={(e) => void onSave({ agente_git: e.target.value as "claude" | "codex" })}
          >
            <option value="claude">Claude Code</option>
            <option value="codex">Codex</option>
          </select>
        </div>
      </div>
      <h2 className="sub">Receitas</h2>
      <div className="card recipes">
        {RECIPES.map((recipe) => {
          const saved = prefs?.[recipe.key] ?? "";
          const draft = drafts[recipe.key];
          const dirty = draft !== undefined && draft !== saved;
          return (
            <div className="recipe" key={recipe.key}>
              <span className="setting-label">
                {recipe.label}
                <span className="small">{recipe.hint}</span>
              </span>
              <textarea
                rows={4}
                value={draft ?? saved}
                maxLength={4000}
                disabled={!prefs}
                onChange={(e) => setDrafts((all) => ({ ...all, [recipe.key]: e.target.value }))}
              />
              <div className="form-buttons">
                <button
                  type="button"
                  className="pill"
                  disabled={!dirty}
                  onClick={() => void onSave({ [recipe.key]: draft }).then(() => setDrafts((all) => ({ ...all, [recipe.key]: undefined })))}
                >
                  Salvar
                </button>
                <button
                  type="button"
                  className="pill ghost"
                  title="Volta ao texto que vem com a MÊTIS"
                  onClick={() => void onSave({ [recipe.key]: "" }).then(() => setDrafts((all) => ({ ...all, [recipe.key]: undefined })))}
                >
                  Padrão
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <h2 className="sub">Commits e editor</h2>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            Assinar os commits
            <span className="small">
              {config
                ? `git config --global commit.gpgsign (${config.formato}${config.tem_chave ? ", com chave definida" : ", sem user.signingkey: defina a chave antes"}). Autor: ${config.nome || "?"} <${config.email || "?"}>`
                : "…"}
            </span>
          </span>
          <Switch checked={!!config?.assinar} disabled={!config} label="Assinar os commits" onChange={(on) => void toggleSigning(on)} />
        </div>
        <div className="setting-row">
          <span className="setting-label">
            Editor externo
            <span className="small">O “Abrir no editor” do painel de mudanças abre a worktree nele.</span>
          </span>
          <select value={prefs?.editor_externo ?? ""} disabled={!prefs} onChange={(e) => void onSave({ editor_externo: e.target.value })}>
            <option value="">Nenhum</option>
            {editors.map((editor) => (
              <option key={editor.id} value={editor.id}>
                {editor.nome}
              </option>
            ))}
          </select>
        </div>
        {error && <div className="error-box">{error}</div>}
      </div>
    </section>
  );
}
