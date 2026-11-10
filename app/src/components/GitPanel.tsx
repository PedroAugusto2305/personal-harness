import { useCallback, useEffect, useRef, useState } from "react";
import { ICON, Icon } from "../icons";
import { CoreError, type CoreClient } from "../lib/core";
import type { ChangedFile, DiffMode, GitFile, GitStatus, GithubState, Prefs, PullRequest, ReviewNote, Session } from "../types";
import { worktreeLabel, type Place } from "../useWorktrees";

/** Letra e cor do estado de um arquivo no git, no estilo do VS Code. */
export function fileMark(file: GitFile, side: "staged" | "unstaged"): { letter: string; color: string } {
  if (file.conflict) return { letter: "!", color: "var(--err)" };
  if (file.untracked) return { letter: "U", color: "var(--run)" };
  const code = side === "staged" ? file.x : file.y;
  const map: Record<string, [string, string]> = {
    M: ["M", "var(--wait)"],
    A: ["A", "var(--run)"],
    D: ["D", "var(--err)"],
    R: ["R", "var(--acct)"],
    C: ["C", "var(--acct)"],
    T: ["T", "var(--wait)"],
  };
  const [letter, color] = map[code] ?? [code, "var(--mut)"];
  return { letter, color };
}

const STATUS_COLOR: Record<string, string> = { A: "var(--run)", M: "var(--wait)", D: "var(--err)", R: "var(--acct)", C: "var(--acct)" };

const OPERATION_LABEL: Record<NonNullable<GitStatus["operacao"]>, string> = {
  merge: "Merge",
  rebase: "Rebase",
  "cherry-pick": "Cherry-pick",
  revert: "Revert",
};

/** Último fetch por pasta: o painel busca o remoto ao abrir, no máximo a cada 3 minutos. */
const lastFetch = new Map<string, number>();

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** Uma ação que pede confirmação no segundo clique (descartar, abortar, forçar, juntar). */
function useArmed(timeoutMs = 4000) {
  const [armed, setArmed] = useState<string | null>(null);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(null), timeoutMs);
    return () => window.clearTimeout(timer);
  }, [armed, timeoutMs]);
  return { armed, arm: setArmed };
}

export interface GitPanelProps {
  client: CoreClient | null;
  place: Place;
  status: GitStatus | null;
  reload: () => Promise<void>;
  notes: ReviewNote[];
  prefs: Prefs | null;
  onOpenDiff: (file: { path: string; untracked?: boolean }, options?: { mode?: DiffMode; ref?: string }) => void;
  onOpenConflict: (path: string) => void;
  onOpenUrl: (url: string) => void;
  onAskCommit: (staged: number) => void;
  /** Manda um pedido ao agente desta worktree (abre um, se não houver). */
  onAgent: (prompt: string) => void;
  onSendNotes: () => void;
  onClearNotes: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
  /** v0.9.8: a revisão de PR por IA abre um terminal novo; a tela vai para ele. */
  onSession?: (session: Session) => void;
}

/**
 * A aba Mudanças do painel da worktree (v0.9.6): o branch com o botão que muda com o
 * estado (publicar, subir, puxar, sincronizar), a operação em andamento com os conflitos,
 * o PR do GitHub, o commit (com amend e o que o pre-commit disse), os arquivos marcados,
 * não marcados e em conflito, e comparar com outro branch.
 */
export function GitPanel(props: GitPanelProps) {
  const { client, place, status, notes } = props;
  const path = place.worktree.path;
  const [message, setMessage] = useState("");
  const [amend, setAmend] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [commitError, setCommitError] = useState<{ output: string; message: string } | null>(null);
  const [pushError, setPushError] = useState<string | null>(null);
  const { armed, arm } = useArmed();
  const files = status?.files ?? [];
  const conflicts = files.filter((f) => f.conflict);
  const staged = files.filter((f) => f.staged && !f.conflict);
  const unstaged = files.filter((f) => f.unstaged && !f.conflict);
  const operation = status?.operacao ?? null;

  const act = async (label: string, action: () => Promise<unknown>, onFail?: (cause: unknown) => boolean) => {
    if (!client) return;
    setBusy(label);
    try {
      await action();
    } catch (cause) {
      if (!onFail?.(cause)) props.onError(errorText(cause));
    } finally {
      setBusy(null);
      await props.reload();
      props.onChanged();
    }
  };

  // Ao abrir (no máximo a cada 3 min por pasta): busca o remoto, para o ↑↓ valer.
  useEffect(() => {
    if (!client) return;
    const last = lastFetch.get(path) ?? 0;
    if (Date.now() - last < 3 * 60_000) return;
    lastFetch.set(path, Date.now());
    void client
      .gitFetch(path)
      .then(() => props.reload())
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, path]);

  useEffect(() => {
    setCommitError(null);
    setPushError(null);
    setAmend(false);
  }, [path]);

  const doCommit = () =>
    act(
      "commit",
      async () => {
        await client!.commit(path, message.trim(), amend);
        setMessage("");
        setAmend(false);
        setCommitError(null);
      },
      (cause) => {
        // O pre-commit (ou outro hook) recusou: a saída fica à vista, com o conserto pelo agente.
        setCommitError({ output: errorText(cause), message: message.trim() });
        return true;
      },
    );

  const sync = () =>
    act(
      "sync",
      async () => {
        const done = await client!.gitSync(path);
        setPushError(null);
        props.onNotice(
          done.feito === "nada"
            ? "Já estava em dia com o remoto."
            : done.feito === "push"
              ? "Subiu."
              : done.feito === "pull"
                ? "Puxou o que havia no remoto."
                : "Sincronizado: puxou o remoto e subiu os seus commits.",
        );
      },
      (cause) => {
        setPushError(errorText(cause));
        return true;
      },
    );

  const forcePush = () =>
    act(
      "force",
      async () => {
        await client!.push(path, true);
        setPushError(null);
        props.onNotice("Subiu com --force-with-lease.");
      },
      (cause) => {
        setPushError(errorText(cause));
        return true;
      },
    );

  const ahead = status?.ahead ?? 0;
  const behind = status?.behind ?? 0;
  const syncLabel = !status?.upstream
    ? "Publicar branch"
    : ahead && behind
      ? `Sincronizar ↓${behind} ↑${ahead}`
      : ahead
        ? `Subir ↑${ahead}`
        : behind
          ? `Puxar ↓${behind}`
          : "Em dia";
  const syncIdle = !!status?.upstream && !ahead && !behind;

  const conflictPrompt = () => {
    const op = operation ? OPERATION_LABEL[operation].toLowerCase() : "merge";
    return [
      `Há um ${op} em andamento nesta worktree com conflitos em: ${conflicts.map((f) => f.path).join(", ")}.`,
      "Resolva cada conflito mantendo a intenção dos dois lados, rode os testes que houver, marque os arquivos (git add) e continue o " +
        `${op} (git ${operation === "merge" ? "commit --no-edit" : `${operation ?? "merge"} --continue`}).`,
      "Se a escolha entre os lados não for óbvia, me pergunte antes.",
    ].join("\n");
  };

  const row = (file: GitFile, side: "staged" | "unstaged") => {
    const mark = fileMark(file, side);
    const parts = file.path.split("/");
    const name = parts.pop();
    const discardKey = `discard-${file.path}`;
    return (
      <div key={`${side}-${file.path}`} className="change-row">
        <button
          type="button"
          className="change-main"
          onClick={() => props.onOpenDiff(file, { mode: file.untracked ? "head" : side === "staged" ? "staged" : "worktree" })}
          title={`Ver o diff de ${file.path}`}
        >
          <span className="change-name">{name}</span>
          <span className="change-dir small">{parts.join("/")}</span>
        </button>
        {side === "unstaged" && (
          <button
            type="button"
            className="icon-btn row-action"
            data-armed={armed === discardKey ? "true" : undefined}
            title={
              armed === discardKey
                ? "Clique de novo para descartar"
                : file.untracked
                  ? "Descartar: o arquivo vai para a Lixeira"
                  : "Descartar as mudanças não marcadas (não dá para desfazer)"
            }
            aria-label={`Descartar ${file.path}`}
            onClick={() =>
              armed === discardKey
                ? void act("discard", async () => {
                    const done = await client!.gitDiscard(path, [file.path]);
                    arm(null);
                    if (done.lixeira.length) props.onNotice(`${file.path} foi para a Lixeira.`);
                  })
                : arm(discardKey)
            }
          >
            <Icon d={ICON.trash} size={12} />
          </button>
        )}
        <button
          type="button"
          className="icon-btn row-action"
          title={side === "staged" ? "Desmarcar" : "Marcar para o commit"}
          aria-label={side === "staged" ? `Desmarcar ${file.path}` : `Marcar ${file.path}`}
          onClick={() => act(side, () => (side === "staged" ? client!.unstage(path, [file.path]) : client!.stage(path, [file.path])))}
        >
          <Icon d={side === "staged" ? ICON.minus : ICON.plus} size={13} strokeWidth={2} />
        </button>
        <span className="change-mark mono" style={{ color: mark.color }}>
          {mark.letter}
        </span>
      </div>
    );
  };

  const last = status?.ultimo_commit ?? null;
  return (
    <div className="inspector-body">
      <div className="branch-bar">
        <Icon d={ICON.branch} size={13} />
        <span className="mono branch-name" title={status?.upstream ? `segue ${status.upstream}` : "sem branch remoto ainda"}>
          {status?.branch ?? worktreeLabel(place.worktree)}
        </span>
        <span className="grow" />
        {props.prefs?.editor_externo && (
          <button
            type="button"
            className="icon-btn"
            title="Abrir a worktree no editor externo (Ajustes → Git)"
            aria-label="Abrir no editor"
            onClick={() => void client?.openIn(props.prefs!.editor_externo!, path).catch((cause) => props.onError(errorText(cause)))}
          >
            <Icon d={ICON.code} size={13} />
          </button>
        )}
        <button
          type="button"
          className="icon-btn"
          title="Buscar o remoto (fetch)"
          disabled={!!busy}
          onClick={() =>
            act("fetch", async () => {
              lastFetch.set(path, Date.now());
              await client!.gitFetch(path);
            })
          }
        >
          <Icon d={ICON.refresh} size={13} />
        </button>
        <button
          type="button"
          className="pill sync-btn"
          disabled={!!busy || !!operation || syncIdle}
          title={
            !status?.upstream
              ? "Sobe o branch e passa a seguir o origin"
              : ahead && behind
                ? "Puxa o remoto com rebase (guardando o que não foi commitado) e sobe os seus commits"
                : ahead
                  ? "git push"
                  : behind
                    ? "git pull --rebase"
                    : "Nada para subir nem puxar"
          }
          onClick={() => void sync()}
        >
          {busy === "sync" ? "…" : syncLabel}
        </button>
      </div>
      {busy === "fetch" || busy === "sync" || busy === "force" ? (
        <div className="small busy-line">{busy === "fetch" ? "buscando o remoto…" : busy === "force" ? "forçando a subida…" : "sincronizando…"}</div>
      ) : null}
      {pushError && (
        <div className="error-box git-output">
          <pre>{pushError}</pre>
          {ahead > 0 && (
            <button
              type="button"
              className="pill ghost danger"
              disabled={!!busy}
              title="Sobrescreve o remoto, mas só se lá não houver commit que você ainda não puxou para este branch"
              onClick={() => (armed === "force" ? void forcePush() : arm("force"))}
            >
              {armed === "force" ? "Confirmar: forçar a subida" : "Forçar (--force-with-lease)"}
            </button>
          )}
        </div>
      )}

      {operation && (
        <div className="operation-box">
          <div className="operation-head">
            <b>{OPERATION_LABEL[operation]} em andamento</b>
            <span className="small">
              {conflicts.length
                ? `${conflicts.length} arquivo${conflicts.length > 1 ? "s" : ""} em conflito`
                : "sem conflitos: dá para continuar"}
            </span>
          </div>
          <div className="form-buttons">
            <button
              type="button"
              className="btn primary"
              disabled={!!busy || conflicts.length > 0}
              onClick={() => void act("continuar", () => client!.gitOperation(path, "continuar"))}
            >
              Continuar
            </button>
            {conflicts.length > 0 && (
              <button type="button" className="btn" onClick={() => props.onAgent(conflictPrompt())}>
                ✻ Resolver com o agente
              </button>
            )}
            <button
              type="button"
              className="btn danger"
              disabled={!!busy}
              onClick={() => (armed === "abort" ? void act("abortar", () => client!.gitOperation(path, "abortar")) : arm("abort"))}
            >
              {armed === "abort" ? "Confirmar: abortar" : "Abortar"}
            </button>
          </div>
        </div>
      )}

      <PrBox client={client} path={path} status={status} prefs={props.prefs} onAgent={props.onAgent} onOpenUrl={props.onOpenUrl} onNotice={props.onNotice} onSession={props.onSession} />

      {notes.length > 0 && (
        <div className="notes-box">
          <Icon d={ICON.note} size={13} />
          <span>
            {notes.length} nota{notes.length > 1 ? "s" : ""} na revisão
          </span>
          <span className="grow" />
          <button type="button" className="pill" onClick={props.onSendNotes} title="Vai para a barra de entrada do agente desta worktree">
            Mandar ao agente
          </button>
          <button type="button" className="icon-btn" title="Limpar notas" onClick={props.onClearNotes}>
            <Icon d={ICON.trash} size={12} />
          </button>
        </div>
      )}

      <div className="commit-box">
        <textarea
          value={message}
          rows={2}
          placeholder={
            amend
              ? "Nova mensagem (vazio mantém a do último commit)"
              : staged.length
                ? "Mensagem do commit (ou peça ao agente)"
                : "Marque arquivos ou peça ao agente"
          }
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.metaKey && (message.trim() || amend) && (staged.length || amend)) {
              e.preventDefault();
              void doCommit();
            }
          }}
        />
        {last && (
          <label className="amend-check small">
            <input type="checkbox" checked={amend} onChange={(e) => setAmend(e.target.checked)} />
            Corrigir o último commit ({last.sha} {last.assunto.slice(0, 40)})
            {amend && last.subiu && <span className="amend-warn"> · já subiu: depois vai precisar forçar a subida</span>}
          </label>
        )}
        <div className="form-buttons">
          <button
            type="button"
            className="btn primary"
            disabled={(!message.trim() && !amend) || (!staged.length && !amend) || !!busy}
            title={amend ? "Refaz o último commit com o que está marcado (⌘⏎)" : "Commit dos arquivos marcados (⌘⏎)"}
            onClick={() => void doCommit()}
          >
            <Icon d={ICON.check} size={13} strokeWidth={2.2} />
            {amend ? "Corrigir commit" : "Commit"}
          </button>
          <button
            type="button"
            className="btn"
            disabled={!files.length}
            onClick={() => props.onAskCommit(staged.length)}
            title="O agente desta worktree escreve a mensagem e faz o commit, no terminal dele (receita em Ajustes → Git)"
          >
            ✻ Pedir ao agente
          </button>
        </div>
        {commitError && (
          <div className="error-box git-output">
            <b>O commit não passou.</b>
            <pre>{commitError.output}</pre>
            <div className="form-buttons">
              <button
                type="button"
                className="pill"
                onClick={() => {
                  props.onAgent(
                    [
                      "O commit desta worktree falhou com esta saída:",
                      "```",
                      commitError.output.slice(0, 6000),
                      "```",
                      `Corrija o que for preciso, marque de novo e faça o commit${commitError.message ? ` com a mensagem "${commitError.message}"` : ""}.`,
                    ].join("\n"),
                  );
                  setCommitError(null);
                }}
              >
                ✻ Consertar com o agente
              </button>
              <button type="button" className="link-btn" onClick={() => setCommitError(null)}>
                fechar
              </button>
            </div>
          </div>
        )}
      </div>

      {conflicts.length > 0 && (
        <div className="change-group">
          <div className="group-head">
            <span>Em conflito · {conflicts.length}</span>
          </div>
          {conflicts.map((file) => (
            <div key={`c-${file.path}`} className="change-row">
              <button type="button" className="change-main" onClick={() => props.onOpenConflict(file.path)} title="Resolver bloco a bloco">
                <span className="change-name">{file.path.split("/").pop()}</span>
                <span className="change-dir small">{file.path.split("/").slice(0, -1).join("/")}</span>
              </button>
              <button
                type="button"
                className="pill ghost tiny"
                title="Fica a versão deste branch inteira"
                onClick={() => void act("nosso", () => client!.resolveConflictSide(path, file.path, "nosso"))}
              >
                nosso
              </button>
              <button
                type="button"
                className="pill ghost tiny"
                title="Fica a versão que está entrando inteira"
                onClick={() => void act("deles", () => client!.resolveConflictSide(path, file.path, "deles"))}
              >
                deles
              </button>
              <span className="change-mark mono" style={{ color: "var(--err)" }}>
                !
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="change-group">
        <div className="group-head">
          <span>Marcados · {staged.length}</span>
          {staged.length > 0 && (
            <button type="button" className="link-btn" onClick={() => act("unstage", () => client!.unstage(path, staged.map((f) => f.path)))}>
              desmarcar todos
            </button>
          )}
        </div>
        {staged.map((f) => row(f, "staged"))}
      </div>
      <div className="change-group">
        <div className="group-head">
          <span>Não marcados · {unstaged.length}</span>
          {unstaged.length > 0 && (
            <button type="button" className="link-btn" onClick={() => act("stage", () => client!.stage(path, unstaged.map((f) => f.path)))}>
              marcar todos
            </button>
          )}
        </div>
        {unstaged.map((f) => row(f, "unstaged"))}
        {status && files.length === 0 && <p className="small inspector-empty">Nada mudou desde o último commit.</p>}
      </div>

      <Compare client={client} path={path} onOpenDiff={props.onOpenDiff} onError={props.onError} />
    </div>
  );
}

/**
 * O PR do branch no GitHub (pelo `gh` já logado): estado, checks e revisão, com marcar como
 * pronto e juntar; sem PR, o formulário para abrir um ou o pedido ao agente (receita).
 */
function PrBox({
  client,
  path,
  status,
  prefs,
  onAgent,
  onOpenUrl,
  onNotice,
  onSession,
}: {
  client: CoreClient | null;
  path: string;
  status: GitStatus | null;
  prefs: Prefs | null;
  onAgent: (prompt: string) => void;
  onOpenUrl: (url: string) => void;
  onNotice: (message: string) => void;
  onSession?: (session: Session) => void;
}) {
  const [state, setState] = useState<GithubState | null>(null);
  const [base, setBase] = useState("");
  /** O branch padrão do repositório: sem PR, a caixa não oferece abrir um a partir dele. */
  const [padrao, setPadrao] = useState("");
  const [branches, setBranches] = useState<string[]>([]);
  const [form, setForm] = useState<{ titulo: string; corpo: string; rascunho: boolean } | null>(null);
  const [method, setMethod] = useState<"rebase" | "squash" | "merge">("rebase");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** v0.9.8: quem revisa o PR (só de leitura). */
  const [reviewer, setReviewer] = useState<"claude" | "codex">("claude");
  const { armed, arm } = useArmed();

  const load = useCallback(async () => {
    if (!client) return;
    try {
      setState(await client.github(path));
    } catch {
      setState(null);
    }
  }, [client, path]);

  const seenBranch = useRef<string | null>(null);
  useEffect(() => {
    setState(null);
    setForm(null);
    setError(null);
    seenBranch.current = null;
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(timer);
  }, [load]);

  // Trocou de branch na mesma pasta: o PR mostrado era o do branch anterior. Status que falhou
  // ou HEAD solto (no meio de um rebase) não contam como troca.
  const currentBranch = status?.branch ?? null;
  useEffect(() => {
    if (!currentBranch) return;
    if (seenBranch.current && seenBranch.current !== currentBranch) {
      setState(null);
      setForm(null);
      setError(null);
      void load();
    }
    seenBranch.current = currentBranch;
  }, [currentBranch, load]);

  // Os branches e o padrão vêm já ao abrir (não só com o formulário): o {base} da receita
  // e a regra de não oferecer PR no branch padrão dependem deles.
  const formOpen = form !== null;
  useEffect(() => {
    setBase("");
    setPadrao("");
  }, [path]);
  useEffect(() => {
    if (!client) return;
    void client
      .gitRefs(path)
      .then((refs) => {
        setBranches(refs.branches.filter((b) => b !== refs.atual));
        setPadrao(refs.padrao);
        setBase((current) => current || refs.padrao);
      })
      .catch(() => undefined);
  }, [client, path, formOpen]);

  if (!state?.gh || !state.repo) return null;
  const pr = state.pr;

  const run = async (label: string, action: () => Promise<PullRequest | { ok: boolean } | unknown>, done?: string) => {
    setBusy(label);
    setError(null);
    try {
      await action();
      if (done) onNotice(done);
      await load();
    } catch (cause) {
      setError(cause instanceof CoreError || cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
      arm(null);
    }
  };

  if (pr && pr.estado === "OPEN") {
    const checks = pr.checks;
    const mergeKey = "merge";
    return (
      <div className="pr-box">
        <div className="pr-head">
          <button type="button" className="link-btn pr-link" onClick={() => onOpenUrl(pr.url)} title="Abrir no navegador da MÊTIS">
            #{pr.numero} {pr.titulo}
          </button>
          <span className={`chip ${pr.rascunho ? "" : "on"}`}>{pr.rascunho ? "rascunho" : "aberto"}</span>
        </div>
        <div className="pr-meta small mono">
          {pr.cabeca} → {pr.base}
          {checks.ok + checks.falhou + checks.pendente > 0 && (
            <span className="pr-checks">
              {" · "}
              {checks.falhou > 0 && <span style={{ color: "var(--err)" }}>✗{checks.falhou} </span>}
              {checks.pendente > 0 && <span style={{ color: "var(--wait)" }}>⏳{checks.pendente} </span>}
              {checks.ok > 0 && <span style={{ color: "var(--run)" }}>✓{checks.ok}</span>}
            </span>
          )}
          {pr.revisao === "APPROVED" && <span style={{ color: "var(--run)" }}> · aprovado</span>}
          {pr.revisao === "CHANGES_REQUESTED" && <span style={{ color: "var(--err)" }}> · pediram mudanças</span>}
          {pr.mesclavel === "CONFLICTING" && <span style={{ color: "var(--err)" }}> · conflita com o {pr.base}</span>}
        </div>
        <div className="pr-ai">
          {checks.falhou > 0 && (
            <button
              type="button"
              className="pill"
              disabled={!!busy}
              title="Junta os logs dos checks que falharam e manda ao agente da worktree, para achar a causa e corrigir"
              onClick={() =>
                void run("checks", async () => {
                  const { pedido } = await client!.failedChecksRequest(path);
                  onAgent(pedido);
                }, "Os logs dos checks foram para o agente.")
              }
            >
              ✻ Checks falhos ao agente
            </button>
          )}
          <button
            type="button"
            className="pill ghost"
            disabled={!!busy}
            title="Abre um agente que só lê: revisa o diff do PR e lista os problemas por gravidade, sem mexer em nada"
            onClick={() =>
              void run("revisao", async () => {
                const session = await client!.reviewPr(path, reviewer);
                onSession?.(session);
              }, "A revisão abriu num terminal novo, só de leitura.")
            }
          >
            Revisar com IA
          </button>
          <select className="pr-reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value as "claude" | "codex")} aria-label="Quem revisa">
            <option value="claude">Claude</option>
            <option value="codex">Codex</option>
          </select>
        </div>
        <div className="form-buttons">
          {pr.rascunho ? (
            <button type="button" className="pill" disabled={!!busy} onClick={() => void run("ready", () => client!.readyPr(path, pr.numero), "O PR saiu do rascunho.")}>
              Pronto para revisão
            </button>
          ) : (
            <>
              <select value={method} onChange={(e) => setMethod(e.target.value as typeof method)} aria-label="Como juntar">
                <option value="rebase">rebase</option>
                <option value="squash">squash</option>
                <option value="merge">merge</option>
              </select>
              <button
                type="button"
                className="pill"
                disabled={!!busy || pr.mesclavel === "CONFLICTING"}
                title={checks.falhou ? "Há checks falhando" : `Juntar no ${pr.base} por ${method}`}
                onClick={() =>
                  armed === mergeKey ? void run("merge", () => client!.mergePr(path, pr.numero, method), `PR #${pr.numero} juntado no ${pr.base}.`) : arm(mergeKey)
                }
              >
                {busy === "merge" ? "Juntando…" : armed === mergeKey ? `Confirmar: juntar no ${pr.base}` : "Juntar"}
              </button>
            </>
          )}
        </div>
        {error && <div className="error-box git-output"><pre>{error}</pre></div>}
      </div>
    );
  }

  if (pr && pr.estado === "MERGED") {
    return (
      <div className="pr-box">
        <div className="pr-head">
          <button type="button" className="link-btn pr-link" onClick={() => onOpenUrl(pr.url)}>
            #{pr.numero} {pr.titulo}
          </button>
          <span className="chip on">juntado</span>
        </div>
        <p className="small">Este branch já entrou no {pr.base}. Dá para apagar a worktree pela barra lateral.</p>
      </div>
    );
  }

  // Sem PR: só oferece fora do branch padrão (o PR sai dele para outro) e com algum commit.
  const branch = status?.branch;
  if (!branch || !padrao || branch === padrao) return null;
  if (!status?.upstream && !(status?.ahead ?? 0) && !(status?.ultimo_commit ?? null)) return null;
  return (
    <div className="pr-box">
      {!form ? (
        <>
          <span className="small pr-none">Sem PR no GitHub ({state.repo})</span>
          <div className="form-buttons">
          <button
            type="button"
            className="pill"
            onClick={() => setForm({ titulo: status?.ultimo_commit?.assunto ?? "", corpo: "", rascunho: false })}
          >
            Criar PR
          </button>
          <button
            type="button"
            className="pill ghost"
            title="O agente da worktree escreve o título e o texto e abre o PR com o gh (receita em Ajustes → Git)"
            onClick={() =>
              onAgent(
                (prefs?.receita_pr ??
                  "Abra um pull request deste branch para o {base} com o gh: título curto no padrão dos commits recentes e corpo com o que mudou, o porquê e como testar. Se o branch não subiu, suba antes. Me devolva o link.")
                  .split("{base}")
                  .join(base || "branch padrão")
                  .split("{branch}")
                  .join(branch),
              )
            }
          >
            ✻ Pedir ao agente
          </button>
          </div>
        </>
      ) : (
        <form
          className="pr-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!form.titulo.trim()) return;
            void run(
              "create",
              async () => {
                const created = await client!.createPr(path, form.titulo.trim(), form.corpo, base, form.rascunho);
                setForm(null);
                onNotice(`PR #${created.numero} aberto.`);
              },
            );
          }}
        >
          <input autoFocus value={form.titulo} placeholder="Título" maxLength={200} onChange={(e) => setForm({ ...form, titulo: e.target.value })} />
          <textarea rows={4} value={form.corpo} placeholder="O que mudou, por quê e como testar" onChange={(e) => setForm({ ...form, corpo: e.target.value })} />
          <div className="pr-form-row small">
            <span>para</span>
            <select value={base} onChange={(e) => setBase(e.target.value)} aria-label="Branch de destino">
              {[base, ...branches.filter((b) => b !== base)].filter(Boolean).map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
            <label>
              <input type="checkbox" checked={form.rascunho} onChange={(e) => setForm({ ...form, rascunho: e.target.checked })} /> rascunho
            </label>
          </div>
          <div className="form-buttons">
            <button type="submit" className="btn primary" disabled={!form.titulo.trim() || !!busy}>
              {busy === "create" ? "Abrindo…" : "Abrir PR"}
            </button>
            <button type="button" className="btn" onClick={() => setForm(null)}>
              Cancelar
            </button>
          </div>
        </form>
      )}
      {error && <div className="error-box git-output"><pre>{error}</pre></div>}
    </div>
  );
}

/** Comparar a worktree com outro branch, tag ou commit: o que mudou desde que saiu dele. */
function Compare({
  client,
  path,
  onOpenDiff,
  onError,
}: {
  client: CoreClient | null;
  path: string;
  onOpenDiff: GitPanelProps["onOpenDiff"];
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [refs, setRefs] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [result, setResult] = useState<{ ref: string; base: string; files: ChangedFile[] } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setResult(null);
    setOpen(false);
  }, [path]);

  useEffect(() => {
    if (!open || !client) return;
    void client
      .gitRefs(path)
      .then((r) => {
        setRefs([...r.branches, ...r.remotos, ...r.tags]);
        setDraft((current) => current || r.padrao);
      })
      .catch(() => undefined);
  }, [open, client, path]);

  const compare = async () => {
    if (!client || !draft.trim()) return;
    setBusy(true);
    try {
      setResult(await client.gitChanged(path, draft.trim()));
    } catch (cause) {
      onError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="change-group compare-group">
      <button type="button" className="group-head link-btn compare-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>{open ? "▾" : "▸"} Comparar com outro branch</span>
      </button>
      {open && (
        <form
          className="compare-form"
          onSubmit={(event) => {
            event.preventDefault();
            void compare();
          }}
        >
          <input
            className="mono"
            list={`compare-${path}`}
            value={draft}
            spellCheck={false}
            placeholder="main, origin/main, v0.9.5"
            onChange={(e) => setDraft(e.target.value)}
          />
          <datalist id={`compare-${path}`}>
            {refs.map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>
          <button type="submit" className="pill" disabled={busy || !draft.trim()}>
            {busy ? "…" : "Comparar"}
          </button>
        </form>
      )}
      {open && result && (
        <>
          <p className="small compare-hint">
            {result.files.length} arquivo{result.files.length === 1 ? "" : "s"} mudou desde que saiu de {result.ref} ({result.base}), contando o que não foi
            commitado.
          </p>
          {result.files.map((file) => {
            const parts = file.path.split("/");
            const name = parts.pop();
            return (
              <div key={`cmp-${file.path}`} className="change-row">
                <button
                  type="button"
                  className="change-main"
                  title={`Diff de ${file.path} contra ${result.ref}`}
                  onClick={() => onOpenDiff({ path: file.path }, { mode: "ref", ref: result.ref })}
                >
                  <span className="change-name">{name}</span>
                  <span className="change-dir small">{parts.join("/")}</span>
                </button>
                <span className="change-mark mono" style={{ color: STATUS_COLOR[file.status[0]] ?? "var(--mut)" }}>
                  {file.status[0]}
                </span>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
