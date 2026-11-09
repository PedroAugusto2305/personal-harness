import { useEffect, useState } from "react";
import { CoreError, restartCore, switchProfile, type CoreClient } from "../lib/core";
import { shortPath } from "../lib/format";
import { ICON, Icon } from "../icons";
import type { BackupCheck, ProfilesState } from "../types";

const message = (cause: unknown) => (cause instanceof CoreError || cause instanceof Error ? cause.message : String(cause));

/**
 * Perfis e backup (v0.9.8). Cada perfil é uma pasta de dados própria (projetos, agentes,
 * automações, conectores, ajustes), com o próprio núcleo: trocar fecha os terminais deste
 * perfil e reabre a MÊTIS no outro. O backup leva a configuração num .zip, sem segredos.
 */
export function ProfilesSection({ client, openSessions }: { client: CoreClient | null; openSessions: number }) {
  const [state, setState] = useState<ProfilesState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [vault, setVault] = useState("");
  const [copy, setCopy] = useState(true);
  const [renaming, setRenaming] = useState<{ id: string; nome: string } | null>(null);
  const [armed, setArmed] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [file, setFile] = useState("");
  const [check, setCheck] = useState<BackupCheck | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!client) return;
    void client
      .profiles()
      .then(setState)
      .catch((cause) => setError(message(cause)));
  }, [client, reload]);

  const act = async (label: string, job: () => Promise<string | void>) => {
    setBusy(label);
    setError(null);
    setDone(null);
    try {
      const text = await job();
      if (text) setDone(text);
      setReload((n) => n + 1);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(null);
    }
  };

  const switchTo = (id: string) =>
    act("trocar", async () => {
      await client!.activateProfile(id);
      if (await switchProfile()) window.location.reload();
      else return "Perfil gravado como ativo; ele abre na próxima vez que a MÊTIS subir o núcleo.";
    });

  if (!client) return null;
  const current = state?.perfis.find((p) => p.id === state.atual);
  return (
    <section className="settings-page">
      <h1>Perfis e backup</h1>
      <p className="lead">
        Cada perfil é uma MÊTIS separada: projetos, agentes, automações, rotinas, conectores e ajustes próprios (ex.: Pessoal e Seller Pro). Trocar fecha os
        terminais deste perfil e reabre a MÊTIS no outro.
      </p>
      {error && <div className="error-box">{error}</div>}
      {done && <p className="small settings-done">{done}</p>}

      <h2 className="sub">Perfis</h2>
      {state?.travado && <p className="small conn-note">Esta MÊTIS foi aberta com uma pasta imposta (a de desenvolvimento): dá para ver e criar, não para trocar.</p>}
      <div className="card">
        {state?.perfis.map((p) => (
          <div className="setting-row" key={p.id}>
            {renaming?.id === p.id ? (
              <form
                className="inline-form profile-rename"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act("renomear", async () => {
                    await client.patchProfile(p.id, { nome: renaming.nome.trim() });
                    setRenaming(null);
                  });
                }}
              >
                <input autoFocus value={renaming.nome} maxLength={40} onChange={(event) => setRenaming({ id: p.id, nome: event.target.value })} />
                <button type="submit" className="btn primary">
                  Salvar
                </button>
                <button type="button" className="btn" onClick={() => setRenaming(null)}>
                  Cancelar
                </button>
              </form>
            ) : (
              <span className="setting-label">
                {p.nome}
                {p.id === state.atual && <span className="chip on">em uso</span>}
                <span className="small mono">
                  {shortPath(p.pasta)} · porta {p.porta}
                  {p.vault ? ` · Brain em ${shortPath(p.vault)}` : ""}
                </span>
              </span>
            )}
            {renaming?.id !== p.id && (
              <div className="row-buttons">
                {p.id !== state.atual && (
                  <button
                    type="button"
                    className={`btn ${armed === `trocar:${p.id}` ? "primary" : ""}`}
                    disabled={state.travado || !!busy}
                    title={openSessions ? `Fecha os ${openSessions} terminais deste perfil` : undefined}
                    onClick={() => (armed === `trocar:${p.id}` ? (setArmed(null), void switchTo(p.id)) : setArmed(`trocar:${p.id}`))}
                  >
                    {busy === "trocar" ? "Trocando…" : armed === `trocar:${p.id}` ? `Fechar ${openSessions} terminal(is) e trocar` : "Usar este perfil"}
                  </button>
                )}
                <button type="button" className="btn" onClick={() => setRenaming({ id: p.id, nome: p.nome })}>
                  Renomear
                </button>
                {p.id !== "principal" && p.id !== state.atual && (
                  <button
                    type="button"
                    className={`icon-btn ${armed === `apagar:${p.id}` ? "danger" : ""}`}
                    title={armed === `apagar:${p.id}` ? "Clique de novo: a pasta do perfil vai para a Lixeira" : "Apagar o perfil (a pasta vai para a Lixeira)"}
                    aria-label={`Apagar o perfil ${p.nome}`}
                    onClick={() =>
                      armed === `apagar:${p.id}`
                        ? (setArmed(null), void act("apagar", async () => (await client.deleteProfile(p.id), `Perfil ${p.nome} foi para a Lixeira.`)))
                        : setArmed(`apagar:${p.id}`)
                    }
                  >
                    <Icon d={ICON.trash} size={13} />
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
        <form
          className="setting-row inline-form profile-new"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim()) return;
            void act("criar", async () => {
              const made = await client.createProfile(name.trim(), copy, vault.trim());
              setName("");
              setVault("");
              return `Perfil ${made.nome} criado${copy ? ` com a configuração de ${current?.nome ?? "agora"}` : " vazio"}.`;
            });
          }}
        >
          <input value={name} maxLength={40} onChange={(event) => setName(event.target.value)} placeholder="Nome do perfil novo (ex.: Seller Pro)" />
          <input value={vault} onChange={(event) => setVault(event.target.value)} placeholder="Brain (vazio = o de sempre)" spellCheck={false} />
          <label className="small">
            <input type="checkbox" checked={copy} onChange={(event) => setCopy(event.target.checked)} /> começar com a configuração deste
          </label>
          <button type="submit" className="btn primary" disabled={!name.trim() || busy === "criar"}>
            Criar
          </button>
        </form>
      </div>

      <h2 className="sub">Backup</h2>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            Exportar a configuração
            <span className="small">
              Ajustes, atalhos, comandos, projetos, agentes (com as sprites), automações, rotinas, temas e o registro do estudo, num .zip em Downloads. Senhas e tokens
              nunca vão; as contas dos conectores voltam pedindo para conectar de novo.
            </span>
          </span>
          <button
            type="button"
            className="btn"
            disabled={!!busy}
            onClick={() => void act("exportar", async () => `Backup em ${shortPath((await client.exportBackup()).arquivo)}.`)}
          >
            {busy === "exportar" ? "Exportando…" : "Exportar"}
          </button>
        </div>
        <form
          className="setting-row inline-form backup-import"
          onSubmit={(event) => {
            event.preventDefault();
            if (!file.trim()) return;
            void act("conferir", async () => {
              setCheck(await client.checkBackup(file.trim()));
            });
          }}
        >
          <input value={file} onChange={(event) => (setFile(event.target.value), setCheck(null))} placeholder="~/Downloads/metis-backup-….zip" spellCheck={false} />
          <button type="submit" className="btn" disabled={!file.trim() || !!busy}>
            Conferir
          </button>
        </form>
        {check && (
          <div className="backup-check small">
            <p>
              Backup de <b>{check.perfil}</b>, {check.data} (MÊTIS {check.versao}): {check.novos.length} arquivo(s) novo(s), {check.substituidos.length} substituído(s).
              {check.contas_para_reconectar.length > 0 && ` Para conectar de novo depois: ${check.contas_para_reconectar.join(", ")}.`} Antes de importar, a MÊTIS guarda um
              backup automático de agora.
            </p>
            <button
              type="button"
              className="btn primary"
              disabled={!!busy}
              onClick={() =>
                void act("importar", async () => {
                  const answer = await client.importBackup(file.trim());
                  setCheck(null);
                  return `${answer.restaurados.length} arquivo(s) restaurado(s); o estado de antes ficou em ${shortPath(answer.backup_anterior)}. Reinicie o núcleo para tudo valer.`;
                })
              }
            >
              {busy === "importar" ? "Importando…" : "Importar"}
            </button>
          </div>
        )}
        {done?.includes("Reinicie o núcleo") && (
          <div className="setting-row">
            <span className="setting-label small">Os terminais deste perfil fecham ao reiniciar.</span>
            <button type="button" className="btn" onClick={() => void restartCore().then((ok) => ok && window.location.reload())}>
              Reiniciar o núcleo
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
