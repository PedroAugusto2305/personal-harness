// Seções dos Ajustes da v0.9.2: agentes e avisos, skills e recursos. Ficam fora do
// Settings.tsx para ele continuar curto; a navegação e o visual são os mesmos.
import { KindIcon } from "./KindIcon";
import { useEffect, useMemo, useRef, useState } from "react";
import { nativeNotify, nativeNotifyStatus, restartCore, type CoreClient } from "../lib/core";
import { KIND_COLOR, STATUS_COLOR, STATUS_LABEL, fold, megabytes, shortPath } from "../lib/format";
import { chime } from "../lib/pomodoro";
import type { PermissionMode, Prefs, Provider, Resources, SemanticStatus, SkillInfo, SkillTarget } from "../types";

type PrefsChange = Partial<Omit<Prefs, "avisos">> & { avisos?: Partial<Prefs["avisos"]> };

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** Interruptor liga/desliga, com o rótulo ao lado (role="switch" para o leitor de tela). */
export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" className="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}>
      <span />
    </button>
  );
}

// --- Agentes e avisos -----------------------------------------------------------------------

const PERMISSION: { mode: PermissionMode; label: string; hint: Record<Provider, string> }[] = [
  {
    mode: "padrao",
    label: "Padrão",
    hint: {
      claude: "Usa o que está configurado na própria CLI; a MÊTIS não passa nada.",
      codex: "Usa o que está configurado na própria CLI; a MÊTIS não passa nada.",
    },
  },
  {
    mode: "manual",
    label: "Manual",
    hint: {
      claude: "Pede sua aprovação antes de editar arquivo ou rodar comando.",
      codex: "Pede aprovação para todo comando fora da lista dos seguros.",
    },
  },
  {
    mode: "auto",
    label: "Automático",
    hint: {
      claude: "Segue sozinho no que é seguro e pergunta só o que tem risco.",
      codex: "Aprova por você o que é seguro e pergunta o resto.",
    },
  },
  {
    mode: "yolo",
    label: "Sem perguntar",
    hint: {
      claude: "Não pede permissão para nada. Só em pasta em que você confia.",
      codex: "Sem aprovação e sem sandbox. Só em pasta em que você confia.",
    },
  },
];

const AWAKE: { mode: Prefs["manter_acordado"]; label: string }[] = [
  { mode: "nunca", label: "Nunca" },
  { mode: "agente", label: "Só com agente trabalhando" },
  { mode: "sempre", label: "Sempre" },
];

const NOTICES: { key: "terminou" | "espera" | "aprovacao" | "erro"; label: string; hint: string }[] = [
  { key: "terminou", label: "Quando o agente termina", hint: "Ele estava trabalhando e parou: a resposta está pronta." },
  { key: "espera", label: "Quando ele espera você", hint: "Uma pergunta, um menu ou uma permissão da própria CLI." },
  { key: "aprovacao", label: "Pedidos de aprovação", hint: "A central de MCP precisa do seu sim (Slack, ClickUp…)." },
  { key: "erro", label: "Erros de automação", hint: "Uma execução de automação terminou com erro." },
];

export function AgentsPrefsSection({
  client,
  prefs,
  onSave,
  openSessions,
}: {
  client: CoreClient | null;
  prefs: Prefs | null;
  onSave: (changes: PrefsChange) => Promise<void>;
  /** Terminais abertos agora (o que "Desligar" fecha). */
  openSessions: number;
}) {
  // O volume só grava quando o arrasto para; até lá, vale o daqui.
  const [volume, setVolume] = useState<number | null>(null);
  const volumeTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(volumeTimer.current), []);

  if (!prefs) {
    return (
      <section className="settings-page">
        <h1>Agentes e avisos</h1>
        <p className="lead">{client ? "Lendo os ajustes do núcleo…" : "O núcleo está fora do ar."}</p>
      </section>
    );
  }

  const avisos = prefs.avisos;
  const shownVolume = volume ?? avisos.volume;
  const changeVolume = (value: number) => {
    setVolume(value);
    window.clearTimeout(volumeTimer.current);
    volumeTimer.current = window.setTimeout(() => {
      void onSave({ avisos: { volume: value } }).then(() => setVolume(null));
    }, 350);
  };

  return (
    <section className="settings-page">
      <h1>Agentes e avisos</h1>
      <p className="lead">
        Como o Claude Code e o Codex abrem aqui, e quando a MÊTIS chama você. As mudanças valem para as sessões abertas depois;
        as que já estão abertas seguem como nasceram.
      </p>

      <h2 className="sub">Modo de permissão das sessões novas</h2>
      <div className="perm-grid">
        {(["claude", "codex"] as Provider[]).map((cli) => {
          const key = cli === "claude" ? "permissao_claude" : "permissao_codex";
          return (
            <div className="card perm-card" key={cli} role="radiogroup" aria-label={`Modo de permissão do ${cli === "claude" ? "Claude Code" : "Codex"}`}>
              <header className="card-head">
                <span className="card-glyph" style={{ color: KIND_COLOR[cli] }}>
                  <KindIcon kind={cli} size={18} />
                </span>
                <h2>{cli === "claude" ? "Claude Code" : "Codex"}</h2>
              </header>
              {PERMISSION.map((option) => (
                <label key={option.mode} className="perm-option" data-checked={prefs[key] === option.mode ? "true" : undefined}>
                  <input
                    type="radio"
                    name={`perm-${cli}`}
                    checked={prefs[key] === option.mode}
                    onChange={() => void onSave(cli === "claude" ? { permissao_claude: option.mode } : { permissao_codex: option.mode })}
                  />
                  <span className="setting-label">
                    {option.label}
                    <span className="small">{option.hint[cli]}</span>
                  </span>
                </label>
              ))}
            </div>
          );
        })}
      </div>

      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            Confiar nas pastas dos projetos e worktrees da MÊTIS
            <span className="small">
              Elas entram como confiáveis antes de a CLI abrir, e o “Do you trust this folder?” não trava cada worktree nova. Só essas
              pastas, nunca uma qualquer.
            </span>
          </span>
          <Switch label="Confiar nas pastas" checked={prefs.confiar_pastas} onChange={(value) => void onSave({ confiar_pastas: value })} />
        </div>
        <div className="setting-row">
          <span className="setting-label">
            Manter o Mac acordado
            <span className="small">O Mac não dorme por inatividade (a tela pode apagar). “Só com agente” vale enquanto um agente ou uma automação trabalha.</span>
          </span>
          <div className="segmented" role="radiogroup" aria-label="Manter o Mac acordado">
            {AWAKE.map((option) => (
              <button
                key={option.mode}
                type="button"
                role="radio"
                aria-checked={prefs.manter_acordado === option.mode}
                onClick={() => void onSave({ manter_acordado: option.mode })}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className="setting-row">
          <span className="setting-label">
            Hibernar agente parado
            <span className="small">
              O Claude ou o Codex esperando você há esse tempo fica pausado e para de gastar memória e CPU; acorda quando você foca o terminal ou
              escreve para ele. Automações e rotinas não hibernam.
            </span>
          </span>
          <div className="segmented" role="radiogroup" aria-label="Hibernar agente parado">
            {[0, 15, 30, 60].map((minutes) => (
              <button
                key={minutes}
                type="button"
                role="radio"
                aria-checked={(prefs.hibernar_min ?? 0) === minutes}
                onClick={() => void onSave({ hibernar_min: minutes })}
              >
                {minutes ? `${minutes} min` : "Nunca"}
              </button>
            ))}
          </div>
        </div>
        <div className="setting-row">
          <span className="setting-label">
            O Claude e o Codex abrem em
            <span className="small">
              Na conversa, as imagens, os fluxogramas, as tabelas e o código aparecem desenhados, e as ferramentas viram linhas que abrem com o resultado. O
              terminal de verdade continua no mesmo painel e aparece sozinho quando o agente abre um menu; ⌘⇧T alterna.
            </span>
          </span>
          <div className="segmented" role="radiogroup" aria-label="O agente abre em">
            {(
              [
                ["conversa", "Conversa"],
                ["terminal", "Terminal"],
              ] as const
            ).map(([value, label]) => (
              <button key={value} type="button" role="radio" aria-checked={(prefs.vista_agente ?? "conversa") === value} onClick={() => void onSave({ vista_agente: value })}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <h2 className="sub">Avisos</h2>
      <div className="card">
        {NOTICES.map((notice) => (
          <div className="setting-row" key={notice.key}>
            <span className="setting-label">
              {notice.label}
              <span className="small">{notice.hint}</span>
            </span>
            <Switch label={notice.label} checked={avisos[notice.key]} onChange={(value) => void onSave({ avisos: { [notice.key]: value } as Partial<Prefs["avisos"]> })} />
          </div>
        ))}
        <div className="setting-row">
          <span className="setting-label">
            Som
            <span className="small">Com a janela em foco, um sino curto; sem foco, o som da notificação do macOS.</span>
          </span>
          <Switch label="Som" checked={avisos.som} disabled={avisos.silencio} onChange={(value) => void onSave({ avisos: { som: value } })} />
        </div>
        <div className="setting-row">
          <span className="setting-label">
            Volume
            <span className="small mono">{Math.round(shownVolume * 100)}%</span>
          </span>
          <input
            type="range"
            className="volume"
            min={0}
            max={1}
            step={0.05}
            value={shownVolume}
            disabled={!avisos.som || avisos.silencio}
            aria-label="Volume dos avisos"
            onChange={(event) => changeVolume(Number(event.target.value))}
          />
          <button type="button" className="pill" disabled={!avisos.som || avisos.silencio} onClick={() => chime(2, shownVolume)}>
            Testar
          </button>
        </div>
        <NativeNoticeRow client={client} som={avisos.som} disabled={avisos.silencio} />
        <div className="setting-row">
          <span className="setting-label">
            Silenciar tudo
            <span className="small">Sem som, sem notificação do macOS e sem número no Dock. O sino da janela continua anotando.</span>
          </span>
          <Switch label="Silenciar tudo" checked={avisos.silencio} onChange={(value) => void onSave({ avisos: { silencio: value } })} />
        </div>
      </div>

      <ShutdownCard client={client} openSessions={openSessions} />
    </section>
  );
}

/**
 * Desde a v0.9.2 fechar a janela não para nada: o núcleo e os agentes seguem, e a janela
 * se liga de novo ao abrir. Desligar de vez é daqui.
 */
function ShutdownCard({ client, openSessions }: { client: CoreClient | null; openSessions: number }) {
  const [step, setStep] = useState<"idle" | "confirm" | "busy" | "off">("idle");
  const [closed, setClosed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const shutdown = async () => {
    if (!client) return;
    setStep("busy");
    setError(null);
    try {
      const answer = await client.shutdown();
      setClosed(answer.fechando);
      setStep("off");
    } catch (cause) {
      setError(errorText(cause));
      setStep("confirm");
    }
  };

  const turnOn = async () => {
    setError(null);
    try {
      if (await restartCore()) window.location.reload();
      else setError("Fora do app, suba o núcleo de novo pelo terminal.");
    } catch (cause) {
      setError(errorText(cause));
    }
  };

  const terminals = `${openSessions} termina${openSessions === 1 ? "l" : "is"}`;
  return (
    <>
      <h2 className="sub">Desligar a MÊTIS</h2>
      <div className="card">
        {step === "off" ? (
          <div className="setting-row">
            <span className="setting-label">
              O núcleo está desligado
              <span className="small">
                {closed ? `Fechou ${closed} termina${closed === 1 ? "l" : "is"}. ` : ""}Pode fechar a janela; ao abrir a MÊTIS de novo, ele sobe
                outra vez.
              </span>
            </span>
            <span className="chip">desligado</span>
            <button type="button" className="pill" onClick={() => void turnOn()}>
              Ligar de novo
            </button>
          </div>
        ) : (
          <div className="setting-row">
            <span className="setting-label">
              Parar o núcleo e os agentes
              <span className="small">
                Fechar a janela não para nada: o núcleo e os agentes seguem trabalhando, e a janela se liga de novo a eles quando você abre a
                MÊTIS. Desligar fecha {openSessions ? `os ${terminals} abertos` : "tudo"} e para as automações.
              </span>
            </span>
            {step === "idle" ? (
              <button type="button" className="btn" disabled={!client} onClick={() => setStep("confirm")}>
                Desligar…
              </button>
            ) : (
              <span className="inline-confirm">
                <span className="small">{openSessions ? `Fecha ${terminals}.` : "Desligar agora?"}</span>
                <button type="button" className="btn danger" disabled={step === "busy"} onClick={() => void shutdown()}>
                  {step === "busy" ? "Desligando…" : "Desligar agora"}
                </button>
                <button type="button" className="btn" disabled={step === "busy"} onClick={() => setStep("idle")}>
                  Cancelar
                </button>
              </span>
            )}
          </div>
        )}
        {error && <div className="error-box">{error}</div>}
      </div>
    </>
  );
}

// --- Skills ---------------------------------------------------------------------------------

const TARGET_LABEL: Record<SkillTarget, string> = { claude: "Claude", codex: "Codex", projeto: "este projeto" };

/** O núcleo acha a skill pela pasta, não pelo `name` do SKILL.md (que pode ser "Brain Registrar"). */
const skillFolder = (skill: SkillInfo) => skill.pasta.split("/").filter(Boolean).pop() ?? skill.nome;

export function SkillsSection({ client, cwd, cwdLabel }: { client: CoreClient | null; cwd: string; cwdLabel: string | null }) {
  const [skills, setSkills] = useState<SkillInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  /** v0.9.8: instalar e compartilhar. */
  const [origin, setOrigin] = useState("");
  const [target, setTarget] = useState<SkillTarget>("claude");
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [armedDelete, setArmedDelete] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .skills(cwd)
      .then((list) => alive && (setSkills(list), setError(null)))
      .catch((cause) => alive && setError(errorText(cause)));
    return () => {
      alive = false;
    };
  }, [client, cwd, reload]);

  const act = async (label: string, job: () => Promise<string>) => {
    if (!client) return;
    setBusy(label);
    setError(null);
    setDone(null);
    try {
      setDone(await job());
      setReload((n) => n + 1);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  };

  const install = () =>
    act("instalar", async () => {
      const answer = await client!.installSkill(origin.trim(), target, cwd, replace);
      setOrigin("");
      const skipped = answer.ignoradas.length ? ` Ficaram de fora: ${answer.ignoradas.map((i) => `${i.nome} (${i.motivo})`).join("; ")}.` : "";
      return answer.instaladas.length
        ? `Instalada${answer.instaladas.length > 1 ? "s" : ""} no ${TARGET_LABEL[target]}: ${answer.instaladas.join(", ")}.${skipped}`
        : `Nenhuma skill instalada.${skipped}`;
    });

  const shown = useMemo(() => {
    const words = fold(query).split(/\s+/).filter(Boolean);
    const list = (skills ?? []).filter((skill) => {
      const haystack = fold(`${skill.nome} ${skill.descricao} ${skill.origem}`);
      return words.every((word) => haystack.includes(word));
    });
    // As do projeto primeiro: são as que mudam de uma worktree para outra.
    return list.sort((a, b) => (a.origem === b.origem ? a.nome.localeCompare(b.nome) : a.origem === "projeto" ? -1 : 1));
  }, [skills, query]);

  const reveal = (pasta: string) => {
    void client?.open({ reveal: pasta }).catch((cause) => setError(errorText(cause)));
  };

  return (
    <section className="settings-page">
      <h1>Skills</h1>
      <p className="lead">
        As skills que o Claude Code e o Codex enxergam: as suas (em ~/.claude/skills, ~/.codex/skills e nas pastas de cada conta) e as do
        projeto {cwdLabel ? <b>{cwdLabel}</b> : "em foco"}. Cada uma é uma pasta com um SKILL.md.
      </p>
      <MetisSkillCard client={client} />
      <div className="card skill-install">
        <div className="setting-row">
          <span className="setting-label">
            Instalar uma skill
            <span className="small">De um repositório git (https), de uma pasta ou de um .zip. A MÊTIS acha cada pasta com SKILL.md e copia; nada é executado.</span>
          </span>
        </div>
        <form
          className="skill-install-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (origin.trim()) void install();
          }}
        >
          <input value={origin} onChange={(event) => setOrigin(event.target.value)} placeholder="https://github.com/… ou ~/Downloads/skill.zip" spellCheck={false} />
          <select value={target} onChange={(event) => setTarget(event.target.value as SkillTarget)} aria-label="Onde instalar">
            <option value="claude">no Claude</option>
            <option value="codex">no Codex</option>
            {cwd && <option value="projeto">neste projeto</option>}
          </select>
          <label className="small">
            <input type="checkbox" checked={replace} onChange={(event) => setReplace(event.target.checked)} /> substituir a que tiver o mesmo nome
          </label>
          <button type="submit" className="btn primary" disabled={!origin.trim() || busy === "instalar"}>
            {busy === "instalar" ? "Instalando…" : "Instalar"}
          </button>
        </form>
      </div>
      {done && <p className="small settings-done">{done}</p>}
      <div className="skills-bar">
        <input className="skills-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar skill pelo nome ou pelo que ela faz…" spellCheck={false} />
        {skills && (
          <span className="small mono">
            {shown.length === skills.length ? `${skills.length} skill${skills.length === 1 ? "" : "s"}` : `${shown.length} de ${skills.length}`}
          </span>
        )}
      </div>
      {error && <div className="error-box">{error}</div>}
      {!skills && !error && <p className="small">Lendo as skills…</p>}
      {skills && skills.length === 0 && (
        <div className="card skills-empty">
          <p>Nenhuma skill ainda.</p>
          <p className="small">
            Crie uma pasta em <span className="mono">~/.claude/skills/&lt;nome&gt;/</span> com um <span className="mono">SKILL.md</span>, ou em{" "}
            <span className="mono">.claude/skills/</span> dentro do projeto, e ela aparece aqui.
          </p>
        </div>
      )}
      {skills && skills.length > 0 && shown.length === 0 && <p className="small">Nenhuma skill com “{query}”.</p>}
      {shown.length > 0 && (
        <div className="card skills-list">
          {shown.map((skill) => (
            <div className="setting-row skill-row" key={skill.arquivo}>
              <span className="setting-label">
                <span className="skill-name">
                  {skill.nome}
                  <span className={`chip skill-origin${skill.origem === "projeto" ? " on" : ""}`}>{skill.origem}</span>
                </span>
                {skill.descricao && <span className="skill-description">{skill.descricao}</span>}
                <span className="small mono">{shortPath(skill.pasta)}</span>
              </span>
              <div className="row-buttons skill-actions">
                {skill.destino && skill.fonte?.tipo === "git" && (
                  <button
                    type="button"
                    className="pill ghost"
                    disabled={!!busy}
                    title={`Busca de novo em ${skill.fonte.origem}`}
                    onClick={() =>
                      void act(`atualizar:${skill.arquivo}`, async () => {
                        const answer = await client!.updateSkill(skillFolder(skill), skill.destino!, cwd);
                        return answer.antes === answer.commit ? `${skill.nome} já estava em dia.` : `${skill.nome} atualizada.`;
                      })
                    }
                  >
                    Atualizar
                  </button>
                )}
                {skill.destino && (
                  <button
                    type="button"
                    className="pill ghost"
                    disabled={!!busy}
                    title="Um .zip em Downloads para mandar a quem quiser"
                    onClick={() => void act(`exportar:${skill.arquivo}`, async () => `Zip em ${shortPath((await client!.exportSkill(skillFolder(skill), skill.destino!, cwd)).arquivo)}.`)}
                  >
                    Exportar
                  </button>
                )}
                {skill.destino &&
                  (["claude", "codex", ...(cwd ? (["projeto"] as const) : [])] as SkillTarget[])
                    .filter((t) => t !== skill.destino)
                    .slice(0, 1)
                    .map((t) => (
                      <button
                        key={t}
                        type="button"
                        className="pill ghost"
                        disabled={!!busy}
                        onClick={() => void act(`copiar:${skill.arquivo}`, async () => (await client!.copySkill(skillFolder(skill), skill.destino!, t, cwd), `${skill.nome} copiada para o ${TARGET_LABEL[t]}.`))}
                      >
                        Copiar para o {TARGET_LABEL[t]}
                      </button>
                    ))}
                <button type="button" className="pill ghost" onClick={() => reveal(skill.pasta)}>
                  Mostrar no Finder
                </button>
                {skill.destino && (
                  <button
                    type="button"
                    className={`pill ${armedDelete === skill.arquivo ? "danger" : "ghost"}`}
                    disabled={!!busy}
                    title="Vai para a Lixeira (dá para recuperar)"
                    onClick={() => {
                      if (armedDelete !== skill.arquivo) {
                        setArmedDelete(skill.arquivo);
                        return;
                      }
                      setArmedDelete(null);
                      void act(`apagar:${skill.arquivo}`, async () => (await client!.deleteSkill(skillFolder(skill), skill.destino!, cwd), `${skill.nome} foi para a Lixeira.`));
                    }}
                  >
                    {armedDelete === skill.arquivo ? "Confirmar" : "Lixeira"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// --- Recursos -------------------------------------------------------------------------------

const MODEL_LABEL: Record<SemanticStatus["model"]["state"], string> = {
  ausente: "não baixado",
  baixando: "baixando…",
  carregando: "carregando…",
  pronto: "pronto",
  parado: "parado (carrega quando precisar)",
  erro: "com erro",
};

const AWAKE_LABEL: Record<Prefs["manter_acordado"], string> = { nunca: "nunca", agente: "só com agente trabalhando", sempre: "sempre" };

const cpu = (value: number) => `${Math.round(value)}%`;

export function ResourcesSection({
  client,
  onClose,
  onOpen,
}: {
  client: CoreClient | null;
  onClose: (id: string) => Promise<void>;
  /** Vai para o terminal da sessão. */
  onOpen: (id: string) => void;
}) {
  const [data, setData] = useState<Resources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [closing, setClosing] = useState<string | null>(null);

  // A cada 3 s enquanto a seção está na tela (e a janela visível).
  useEffect(() => {
    if (!client) return;
    let alive = true;
    const read = () => {
      if (document.visibilityState !== "visible") return;
      client
        .resources()
        .then((value) => alive && (setData(value), setError(null)))
        .catch((cause) => alive && setError(errorText(cause)));
    };
    read();
    const timer = window.setInterval(read, 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client]);

  const close = async (id: string) => {
    setClosing(id);
    await onClose(id);
    setClosing(null);
    setConfirm(null);
    setData((current) => (current ? { ...current, sessoes: current.sessoes.filter((s) => s.id !== id) } : current));
  };

  const sessions = data ? [...data.sessoes].sort((a, b) => b.mb - a.mb) : [];
  return (
    <section className="settings-page">
      <h1>Recursos</h1>
      <p className="lead">Memória e CPU do núcleo e de cada terminal, contando os processos filhos (servidores, testes, builds). Atualiza a cada 3 segundos.</p>
      {error && <div className="error-box">{error}</div>}
      {!data && !error && <p className="small">Medindo…</p>}
      {data && (
        <>
          <div className="res-tiles">
            <div className="card res-tile">
              <span className="small">Núcleo</span>
              <span className="res-value mono">{megabytes(data.nucleo.mb)}</span>
              <span className="small mono">CPU {cpu(data.nucleo.cpu)}</span>
            </div>
            <div className="card res-tile">
              <span className="small">Com todas as sessões</span>
              <span className="res-value mono">{megabytes(data.nucleo.com_sessoes_mb)}</span>
              <span className="small mono">
                {data.sessoes.length} sess{data.sessoes.length === 1 ? "ão" : "ões"}
              </span>
            </div>
            <div className="card res-tile">
              <span className="small">Janelas ligadas</span>
              <span className="res-value mono">{data.janelas}</span>
              <span className="small">ao núcleo agora</span>
            </div>
          </div>
          <div className="card">
            <div className="setting-row">
              <span className="setting-label">
                Modelo de significado
                <span className="small">
                  {data.modelo.model}
                  {data.modelo.disk_mb ? ` · ${megabytes(data.modelo.disk_mb)} no disco` : ""}
                </span>
              </span>
              <span className={`chip${data.modelo.state === "pronto" ? " on" : ""}`}>{MODEL_LABEL[data.modelo.state] ?? data.modelo.state}</span>
            </div>
            {data.modelo.error && <div className="error-box">{data.modelo.error}</div>}
            <div className="setting-row">
              <span className="setting-label">
                Mac acordado
                <span className="small">Modo: {AWAKE_LABEL[data.acordado.modo] ?? data.acordado.modo} (muda em Agentes e avisos)</span>
              </span>
              <span className={`chip${data.acordado.ativo ? " on" : ""}`}>{data.acordado.ativo ? "ativo agora" : "inativo"}</span>
            </div>
          </div>

          <h2 className="sub">Sessões</h2>
          {sessions.length === 0 ? (
            <p className="small">Nenhum terminal aberto.</p>
          ) : (
            <div className="card res-sessions">
              {sessions.map((s) => (
                <div className="res-row" key={s.id}>
                  <button type="button" className="res-title" title={`Ir para ${s.title} · ${shortPath(s.cwd)}`} onClick={() => onOpen(s.id)}>
                    <KindIcon kind={s.kind} />
                    <span className="res-name">{s.title}</span>
                    <span className="small mono res-status">
                      <span className="dot" style={{ background: STATUS_COLOR[s.status] }} /> {STATUS_LABEL[s.status]}
                    </span>
                  </button>
                  <span className="mono res-num" title="Memória (com os processos filhos)">
                    {megabytes(s.mb)}
                  </span>
                  <span className="mono res-num small" title="CPU">
                    {cpu(s.cpu)}
                  </span>
                  <span className="mono res-num small" title="Processos">
                    {s.processos} proc.
                  </span>
                  <span className="res-commands">
                    {s.comandos.slice(0, 4).map((command, i) => (
                      <span key={`${command}-${i}`} className="path-chip" title={command}>
                        {command}
                      </span>
                    ))}
                  </span>
                  {confirm === s.id ? (
                    <span className="inline-confirm">
                      <button type="button" className="btn danger" disabled={closing === s.id} onClick={() => void close(s.id)}>
                        {closing === s.id ? "Fechando…" : "Fechar mesmo"}
                      </button>
                      <button type="button" className="btn" disabled={closing === s.id} onClick={() => setConfirm(null)}>
                        Cancelar
                      </button>
                    </span>
                  ) : (
                    <button type="button" className="pill ghost" onClick={() => setConfirm(s.id)}>
                      Fechar
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

/**
 * A skill da MÊTIS (v0.9.8): ensina o Claude e o Codex a usar o comando `metis` e a central
 * de MCP (Brain, kanban, lembretes, worktrees, sessões). Instalar grava o SKILL.md na pasta
 * de skills de cada CLI; instalar de novo atualiza.
 */
function MetisSkillCard({ client }: { client: CoreClient | null }) {
  const [state, setState] = useState<{ texto: string; instalada: { claude: boolean; codex: boolean } } | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    client.metisSkill().then(setState, () => setState(null));
  }, [client]);

  if (!state) return null;
  const install = async (destino: "claude" | "codex" | "ambos") => {
    if (!client) return;
    setBusy(true);
    setError(null);
    try {
      setState(await client.installMetisSkill(destino));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };
  const both = state.instalada.claude && state.instalada.codex;
  return (
    <div className="card metis-skill">
      <div className="setting-row">
        <span className="setting-label">
          Skill da MÊTIS
          <span className="small">
            Ensina o Claude e o Codex a usar o <span className="mono">metis</span> e a central de MCP: Brain, tarefas, lembretes, worktrees e sessões.{" "}
            {state.instalada.claude || state.instalada.codex
              ? `Instalada no ${[state.instalada.claude && "Claude", state.instalada.codex && "Codex"].filter(Boolean).join(" e no ")}.`
              : "Ainda não instalada."}
          </span>
        </span>
        <button type="button" className="pill ghost" onClick={() => setOpen((v) => !v)}>
          {open ? "Esconder" : "Ver o texto"}
        </button>
        <button type="button" className="pill" disabled={busy} onClick={() => void install("ambos")}>
          {busy ? "Instalando…" : both ? "Atualizar" : "Instalar no Claude e no Codex"}
        </button>
      </div>
      {open && <pre className="metis-skill-text mono">{state.texto}</pre>}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

const NATIVE_HINT: Record<string, string> = {
  ativo: "Saem pela Central de Notificações com o ícone da MÊTIS; clicar abre a sessão. Com a janela fechada, o núcleo avisa pelo app.",
  pendente: "O macOS ainda vai perguntar se a MÊTIS pode mandar avisos. Até lá, saem pelo Editor de Scripts.",
  negado: "Desligados no macOS. Para ligar: Ajustes do Sistema → Notificações → MÊTIS. Até lá, saem pelo Editor de Scripts.",
  "fora do app": "Esta MÊTIS não roda de um .app (desenvolvimento): os avisos saem pelo núcleo, com o ícone do Editor de Scripts.",
};

/** v0.9.9: os avisos nativos (ícone da MÊTIS) e um teste de verdade. */
function NativeNoticeRow({ client, som, disabled }: { client: CoreClient | null; som: boolean; disabled: boolean }) {
  const [status, setStatus] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  useEffect(() => {
    void nativeNotifyStatus().then(setStatus);
  }, []);
  const key = status?.startsWith("negado") ? "negado" : (status ?? "");
  const test = async () => {
    setResult(null);
    const failed = await nativeNotify({ titulo: "Aviso da MÊTIS", texto: "Assim chegam os avisos dos agentes: clique para voltar à MÊTIS.", som, alvo: "", grupo: "teste" });
    if (!failed) return setResult("mandado: veja no canto da tela");
    // Sem o aviso nativo, o de antes (pelo núcleo), para o teste ainda mostrar algo.
    await client?.notifyMac("Aviso da MÊTIS", "Aviso pelo núcleo (Editor de Scripts).").catch(() => undefined);
    setResult(`não saiu pelo app (${failed}); mandei pelo núcleo`);
    void nativeNotifyStatus().then(setStatus);
  };
  return (
    <div className="setting-row">
      <span className="setting-label">
        Avisos do macOS {status && <span className="mono small">· {key === "ativo" ? "com o ícone da MÊTIS" : key}</span>}
        <span className="small">{NATIVE_HINT[key] ?? status ?? "conferindo…"}</span>
        {result && <span className="small">{result}</span>}
      </span>
      <button type="button" className="pill" disabled={disabled} onClick={() => void test()}>
        Testar aviso
      </button>
    </div>
  );
}
