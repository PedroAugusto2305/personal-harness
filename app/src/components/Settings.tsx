import { useEffect, useMemo, useRef, useState } from "react";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, PROVIDERS, fold, shortPath } from "../lib/format";
import { ACTIONS, formatCombo, hintFor, type Overrides } from "../lib/keymap";
import { ICON, Icon } from "../icons";
import type { Accounts, AppTheme, BrowserProfile, Prefs, Project, Provider, SavedCommand, Session, TerminalTheme, ThemeName, Usage, VersionInfo, VoiceStatus } from "../types";
import type { Appearance } from "../lib/appearance";
import { AppearanceSection, BrowserSection, type LinkTarget } from "./SettingsLook";
import { AgentsPrefsSection, ResourcesSection, SkillsSection } from "./SettingsSystem";
import { CommandsSection, KeymapSection, TerminalThemeCard, type FindEntry } from "./SettingsTerminal";
import { GitSection } from "./SettingsGit";
import { Limits } from "./StatusBar";

export type SettingsSection = "contas" | "agentes" | "git" | "skills" | "recursos" | "aparencia" | "navegador" | "atalhos" | "comandos" | "voz" | "sobre";

const SECTIONS: { key: SettingsSection; label: string; icon: keyof typeof ICON }[] = [
  { key: "contas", label: "Contas e uso", icon: "user" },
  { key: "agentes", label: "Agentes e avisos", icon: "bell" },
  { key: "git", label: "Git", icon: "branch" },
  { key: "skills", label: "Skills", icon: "spark" },
  { key: "recursos", label: "Recursos", icon: "cpu" },
  { key: "aparencia", label: "Aparência", icon: "palette" },
  { key: "navegador", label: "Navegador", icon: "globe" },
  { key: "atalhos", label: "Atalhos", icon: "keyboard" },
  { key: "comandos", label: "Comandos salvos", icon: "terminal" },
  { key: "voz", label: "Voz", icon: "mic" },
  { key: "sobre", label: "Sobre", icon: "info" },
];

/**
 * O que a busca dos ajustes acha (⌘,): cada linha leva à seção e acende o texto na tela.
 * Os termos trazem sinônimos e o mesmo em inglês e espanhol, para achar como lembrar.
 */
const FIND: FindEntry[] = [
  { section: "contas", label: "Contas e uso", terms: "account accounts login usage limits plan plano cuenta uso limites" },
  { section: "contas", label: "Adicionar conta", terms: "add account new login nova conta agregar cuenta" },
  { section: "contas", label: "Trocar a conta em uso", find: "Usar esta", terms: "switch account activate ativa trocar cambiar cuenta" },
  { section: "contas", label: "Atualizar uso do Codex", find: "Atualizar uso", terms: "refresh usage codex limites" },
  { section: "agentes", label: "Modo de permissão das sessões novas", terms: "permission mode yolo auto manual permisos skip permissions aprovar" },
  { section: "agentes", label: "Confiar nas pastas dos projetos e worktrees da MÊTIS", terms: "trust folder trusted confiar pasta carpeta confianza" },
  { section: "agentes", label: "Manter o Mac acordado", terms: "awake sleep caffeinate dormir despierto energia" },
  { section: "agentes", label: "Avisos", terms: "notifications alerts notificações notificaciones sino bell terminou espera" },
  { section: "agentes", label: "Som", terms: "sound sonido volume beep" },
  { section: "agentes", label: "Silenciar tudo", terms: "mute silence do not disturb silenciar no molestar" },
  { section: "agentes", label: "Hibernar agente parado", terms: "hibernate sleep pause pausar hibernar parado idle memoria cpu" },
  { section: "agentes", label: "Desligar a MÊTIS", terms: "quit shutdown stop core nucleo desligar apagar reiniciar restart" },
  { section: "git", label: "Agente do git", terms: "git commit pr pull request agente receita recipe codex claude" },
  { section: "git", label: "Commit (nada marcado)", find: "Receitas", terms: "receitas recipes prompt commit mensagem message" },
  { section: "git", label: "Pull request", terms: "pr pull request receita github" },
  { section: "git", label: "Assinar os commits", terms: "sign signing gpg ssh assinatura assinar firma commits" },
  { section: "git", label: "Editor externo", terms: "editor vscode visual studio code cursor zed sublime xcode abrir em open in" },
  { section: "skills", label: "Skills", terms: "skills habilidades plugins claude" },
  { section: "recursos", label: "Recursos", terms: "resources memory cpu memoria processos procesos sessões" },
  { section: "aparencia", label: "Aparência", terms: "appearance theme colors dark light tema cores escuro claro dracula grafite apariencia" },
  { section: "aparencia", label: "Tema do terminal", terms: "terminal theme colors palette paleta cores xterm" },
  { section: "aparencia", label: "Importar do Ghostty", terms: "ghostty import theme importar tema" },
  { section: "aparencia", label: "Colar um tema", terms: "paste theme pegar tema ghostty" },
  { section: "aparencia", label: "Criar tema com prompt", terms: "prompt theme generate gerar tema ia ai cores colors crear" },
  { section: "aparencia", label: "Importar do VS Code ou do Obsidian", terms: "vscode visual studio code cursor obsidian import theme importar tema" },
  { section: "aparencia", label: "Fonte da interface", terms: "font fonte letra tipografia typography interface inter sf pro fuente" },
  { section: "aparencia", label: "Fonte do terminal e do código", terms: "font mono monospace fira code jetbrains menlo terminal editor fonte" },
  { section: "aparencia", label: "Tamanho da letra do terminal", terms: "font size tamanho letra terminal tamaño" },
  { section: "aparencia", label: "Densidade", terms: "density compact comfortable densidade compacta confortavel espaçamento spacing" },
  { section: "aparencia", label: "Zoom da janela", terms: "zoom scale escala aumentar diminuir maior menor" },
  { section: "navegador", label: "Perfis", terms: "browser profiles perfil perfis navegador cookies login contas partition partição" },
  { section: "navegador", label: "Importar cookies do Chrome", terms: "chrome cookies import importar brave edge arc login sessão" },
  { section: "navegador", label: "⌘ + clique num link do terminal abre", find: "clique num link", terms: "links terminal open abrir navegador mac safari chrome routing roteamento" },
  { section: "navegador", label: "Histórico do navegador", terms: "history historico apagar limpar clear navegador" },
  { section: "atalhos", label: "Atalhos", terms: "shortcuts keybindings hotkeys keyboard teclado atajos remapear" },
  { section: "comandos", label: "Comandos salvos", terms: "saved commands snippets prompts scripts comandos guardados" },
  { section: "voz", label: "Voz", terms: "voice dictation whisper ditado microfone microphone dictado" },
  { section: "voz", label: "Idioma do ditado", terms: "language idioma lingua" },
  { section: "sobre", label: "Sobre", find: "Versão", terms: "about version versao version nucleo core codigo github" },
];

const PROVIDER_INFO: Record<Provider, { title: string; env: string; home: string; usageHint: string }> = {
  claude: {
    title: "Claude Code",
    env: "CLAUDE_CONFIG_DIR",
    home: "~/.claude",
    usageHint: "O uso do Claude aparece depois da primeira resposta numa sessão da conta.",
  },
  codex: {
    title: "Codex",
    env: "CODEX_HOME",
    home: "~/.codex",
    usageHint: "O uso do Codex é lido da própria CLI a cada 3 minutos.",
  },
};

interface Props {
  section: SettingsSection;
  onSection: (section: SettingsSection) => void;
  client: CoreClient | null;
  accounts: Accounts;
  usage: Usage;
  theme: ThemeName;
  onTheme: (theme: ThemeName) => void;
  language: string;
  onLanguage: (language: string) => void;
  run: <T>(action: (core: CoreClient) => Promise<T>) => Promise<T | null>;
  onOpenSession: (provider: Provider, accountId: string, title: string) => void;
  // v0.9.2: agentes e avisos, skills e recursos
  prefs: Prefs | null;
  onSavePrefs: (changes: Partial<Omit<Prefs, "avisos">> & { avisos?: Partial<Prefs["avisos"]> }) => Promise<void>;
  /** Terminais que não saíram (o que desligar ou reiniciar o núcleo fecha). */
  openSessions: number;
  /** Pasta da worktree em foco, para as skills do projeto ("" = só as do usuário). */
  skillsCwd: string;
  skillsCwdLabel: string | null;
  onCloseSession: (id: string) => Promise<void>;
  onGoToSession: (id: string) => void;
  // v0.9.3: atalhos, comandos salvos e tema do terminal
  keymap: Overrides;
  keymapFile: string | null;
  onSaveKeymap: (overrides: Overrides) => Promise<void>;
  onReloadKeymap: () => void;
  commands: SavedCommand[];
  projects: Project[];
  currentProject: string | null;
  onRunCommand: (command: SavedCommand) => void;
  termTheme: TerminalTheme | null;
  onTermTheme: (theme: TerminalTheme | null) => void;
  /** v0.9.4: o terminal da atualização nasceu; a tela vai para ele. */
  onUpdateStarted: (session: Session) => void;
  // v0.9.8: aparência e navegador
  appThemes: AppTheme[];
  appearance: Appearance;
  onAppearance: (value: Appearance) => void;
  profiles: BrowserProfile[];
  defaultProfile: string;
  onDefaultProfile: (id: string) => void;
  linkTarget: LinkTarget;
  onLinkTarget: (value: LinkTarget) => void;
  openTabs: (profileId: string) => number;
  onCloseProfileTabs: (profileId: string) => void;
}

/**
 * Busca nos ajustes: campo no topo da lista de seções (já com o foco ao abrir com ⌘,).
 * Escolher um resultado abre a seção e acende a linha achada.
 */
function SettingsFind({ entries, onPick }: { entries: FindEntry[]; onPick: (entry: FindEntry) => void }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const sectionLabel = (key: string) => SECTIONS.find((s) => s.key === key)?.label ?? key;
  const results = useMemo(() => {
    const words = fold(query).split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    return entries
      .filter((e) => {
        const hay = fold(`${e.label} ${e.terms} ${sectionLabel(e.section)}`);
        return words.every((w) => hay.includes(w));
      })
      .slice(0, 12);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, query]);
  useEffect(() => setIndex(0), [query]);

  const pick = (entry: FindEntry | undefined) => {
    if (!entry) return;
    setQuery("");
    onPick(entry);
  };

  return (
    <div className="settings-find">
      <span className="settings-find-input">
        <Icon d={ICON.search} size={13} strokeWidth={2} />
        <input
          autoFocus
          value={query}
          placeholder="Buscar nos ajustes"
          spellCheck={false}
          aria-label="Buscar nos ajustes"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setIndex((i) => Math.min(results.length - 1, i + 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setIndex((i) => Math.max(0, i - 1));
            } else if (event.key === "Enter") {
              event.preventDefault();
              pick(results[index]);
            } else if (event.key === "Escape" && query) {
              event.preventDefault();
              setQuery("");
            }
          }}
        />
      </span>
      {query && (
        <ul className="settings-find-results" role="listbox" aria-label="Resultados da busca">
          {results.length === 0 && <li className="small settings-find-empty">Nada com “{query}”.</li>}
          {results.map((entry, i) => (
            <li key={`${entry.section}-${entry.label}`} role="presentation">
              <button type="button" role="option" aria-selected={i === index} onMouseEnter={() => setIndex(i)} onClick={() => pick(entry)}>
                <span>{entry.label}</span>
                <span className="small">{sectionLabel(entry.section)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Settings(props: Props) {
  const body = useRef<HTMLDivElement>(null);
  const [flash, setFlash] = useState<{ text: string; n: number } | null>(null);

  const entries = useMemo<FindEntry[]>(
    () => [
      ...FIND,
      ...ACTIONS.map((a) => ({
        section: "atalhos",
        label: a.label,
        terms: `atalho shortcut keybinding ${a.group} ${formatCombo((a.id in props.keymap ? props.keymap[a.id] : a.combo) || "")}`,
      })),
      ...props.commands.map((c) => ({ section: "comandos", label: c.nome, terms: `comando command ${c.tipo} ${c.texto.slice(0, 200)}` })),
    ],
    [props.keymap, props.commands],
  );

  // Acende o que a busca achou: a seção pode demorar a carregar, então procura por até 1,5 s.
  useEffect(() => {
    if (!flash) return;
    const wanted = fold(flash.text);
    let tries = 0;
    let lit: Element | null = null;
    const timer = window.setInterval(() => {
      tries += 1;
      const candidates = body.current?.querySelectorAll("h1, h2, .setting-label, .theme-name, .skill-name, button.pill") ?? [];
      const hit = [...candidates].find((el) => fold(el.textContent ?? "").startsWith(wanted)) ?? [...candidates].find((el) => fold(el.textContent ?? "").includes(wanted));
      if (hit || tries > 15) {
        window.clearInterval(timer);
        if (!hit) return;
        lit = hit.closest(".setting-row, .card-head, h1, h2") ?? hit;
        lit.scrollIntoView({ block: "center", behavior: "smooth" });
        lit.classList.add("find-flash");
        window.setTimeout(() => lit?.classList.remove("find-flash"), 1800);
      }
    }, 100);
    return () => {
      window.clearInterval(timer);
      lit?.classList.remove("find-flash");
    };
  }, [flash]);

  return (
    <div className="settings">
      <nav className="settings-nav" aria-label="Seções dos ajustes">
        <span className="section-title">Ajustes</span>
        <SettingsFind
          entries={entries}
          onPick={(entry) => {
            props.onSection(entry.section as SettingsSection);
            setFlash((last) => ({ text: entry.find ?? entry.label, n: (last?.n ?? 0) + 1 }));
          }}
        />
        {SECTIONS.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-current={props.section === item.key ? "page" : undefined}
            onClick={() => props.onSection(item.key)}
          >
            <Icon d={ICON[item.icon]} size={15} />
            {item.label}
          </button>
        ))}
      </nav>
      <div className="settings-body" ref={body}>
        {props.section === "contas" && <AccountsSection {...props} />}
        {props.section === "agentes" && (
          <AgentsPrefsSection client={props.client} prefs={props.prefs} onSave={props.onSavePrefs} openSessions={props.openSessions} />
        )}
        {props.section === "git" && <GitSection client={props.client} prefs={props.prefs} onSave={props.onSavePrefs} />}
        {props.section === "skills" && <SkillsSection client={props.client} cwd={props.skillsCwd} cwdLabel={props.skillsCwdLabel} />}
        {props.section === "recursos" && <ResourcesSection client={props.client} onClose={props.onCloseSession} onOpen={props.onGoToSession} />}
        {props.section === "aparencia" && (
          <AppearanceSection
            client={props.client}
            theme={props.theme}
            onTheme={props.onTheme}
            themes={props.appThemes}
            appearance={props.appearance}
            onAppearance={props.onAppearance}
          >
            <TerminalThemeCard client={props.client} value={props.termTheme} onChange={props.onTermTheme} />
          </AppearanceSection>
        )}
        {props.section === "navegador" && (
          <BrowserSection
            client={props.client}
            profiles={props.profiles}
            defaultProfile={props.defaultProfile}
            onDefaultProfile={props.onDefaultProfile}
            linkTarget={props.linkTarget}
            onLinkTarget={props.onLinkTarget}
            openTabs={props.openTabs}
            onCloseProfileTabs={props.onCloseProfileTabs}
          />
        )}
        {props.section === "atalhos" && (
          <KeymapSection keymap={props.keymap} file={props.keymapFile} onSave={props.onSaveKeymap} onReload={props.onReloadKeymap} />
        )}
        {props.section === "comandos" && (
          <CommandsSection
            client={props.client}
            commands={props.commands}
            projects={props.projects}
            currentProject={props.currentProject}
            onRun={props.onRunCommand}
            shortcut={hintFor(props.keymap, "comandos")}
          />
        )}
        {props.section === "voz" && <VoiceSection {...props} />}
        {props.section === "sobre" && <AboutSection client={props.client} onUpdateStarted={props.onUpdateStarted} />}
      </div>
    </div>
  );
}

function AccountsSection({ accounts, usage, run, onOpenSession }: Props) {
  const [adding, setAdding] = useState<Provider | null>(null);
  const [name, setName] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const create = async (provider: Provider) => {
    const account = await run((core) => core.addAccount(provider, name.trim()));
    if (!account) return;
    setAdding(null);
    setName("");
    onOpenSession(provider, account.id, `Login · ${account.name}`);
  };

  return (
    <section className="settings-page">
      <h1>Contas e uso</h1>
      <p className="lead">
        Cada conta é uma pasta de configuração com o próprio login, e o Claude Code e o Codex rodam aqui como no seu
        terminal. A MÊTIS não lê nem guarda token: o login acontece na própria CLI, na primeira vez que você abre uma
        sessão da conta.
      </p>
      {PROVIDERS.map((provider) => {
        const info = PROVIDER_INFO[provider];
        const entry = accounts[provider];
        return (
          <div className="card" key={provider}>
            <header className="card-head">
              <span className="card-glyph" style={{ color: KIND_COLOR[provider] }}>
                {KIND_GLYPH[provider]}
              </span>
              <h2>{info.title}</h2>
              <span className="path-chip">{info.env}</span>
              <span className="grow" />
              {provider === "codex" && (
                <button
                  type="button"
                  className="pill"
                  disabled={refreshing}
                  onClick={async () => {
                    setRefreshing(true);
                    await run((core) => core.refreshUsage());
                    setRefreshing(false);
                  }}
                >
                  <Icon d={ICON.refresh} size={13} strokeWidth={1.9} />
                  {refreshing ? "Lendo…" : "Atualizar uso"}
                </button>
              )}
              <button
                type="button"
                className="pill"
                onClick={() => {
                  setAdding(adding === provider ? null : provider);
                  setName("");
                }}
              >
                <Icon d={ICON.plus} size={13} strokeWidth={2} />
                Adicionar conta
              </button>
            </header>
            {adding === provider && (
              <form
                className="add-account"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (name.trim()) void create(provider);
                }}
              >
                <input
                  autoFocus
                  value={name}
                  maxLength={60}
                  placeholder="Nome da conta, ex.: Trabalho"
                  onChange={(event) => setName(event.target.value)}
                />
                <button type="submit" className="btn primary" disabled={!name.trim()}>
                  Criar e entrar
                </button>
                <button type="button" className="btn" onClick={() => setAdding(null)}>
                  Cancelar
                </button>
                <span className="small">Abre um terminal com o login oficial do {info.title} para essa conta.</span>
              </form>
            )}
            <ul className="accounts">
              {entry.accounts.map((account) => {
                const limits = usage[provider][account.id];
                return (
                  <li key={account.id} className="account" data-active={account.active ? "true" : undefined}>
                    <span className="radio" aria-hidden="true" />
                    <span className="account-main">
                      <span className="account-name">
                        {account.name}
                        {limits?.plan && <span className="chip plan-chip">{limits.plan}</span>}
                      </span>
                      <span className="small mono">{account.dir ? shortPath(account.dir) : `${info.home} (pasta de sempre)`}</span>
                    </span>
                    <span className="account-usage">
                      <Limits limits={limits} />
                    </span>
                    {account.active ? (
                      <span className="chip on">em uso</span>
                    ) : (
                      <button type="button" className="pill" onClick={() => run((core) => core.activateAccount(provider, account.id))}>
                        Usar esta
                      </button>
                    )}
                    <button
                      type="button"
                      className="pill ghost"
                      title="Abre um terminal desta conta (faz o login se for a primeira vez)"
                      onClick={() => onOpenSession(provider, account.id, `${info.title} · ${account.name}`)}
                    >
                      Abrir sessão
                    </button>
                  </li>
                );
              })}
            </ul>
            <p className="small card-foot">
              {info.usageHint} No terminal: <span className="mono">metis switch {provider} &lt;conta&gt;</span>. A troca
              vale para as sessões novas.
            </p>
          </div>
        );
      })}
    </section>
  );
}

function VoiceSection({ client, language, onLanguage, run }: Props) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    const read = () => client.voiceStatus().then((value) => alive && setStatus(value), () => undefined);
    read();
    const timer = window.setInterval(read, 1500);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client]);

  const STATE_LABEL: Record<VoiceStatus["state"], string> = {
    idle: "carrega no primeiro ditado",
    loading: "carregando…",
    ready: "pronto",
    error: "com erro",
  };

  return (
    <section className="settings-page">
      <h1>Voz</h1>
      <p className="lead">
        Aperte <b>Ditar</b> na barra de entrada (ou ⌘⇧M), fale e aperte <b>Parar</b>. O áudio é transcrito no seu Mac pelo
        Whisper, sem internet e sem custo, e o texto cai na barra para você revisar antes de enviar.
      </p>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            Modelo
            <span className="small">Whisper “{status?.model ?? "small"}”, em ~/.harness/modelos</span>
          </span>
          <span className="chip">{status ? STATE_LABEL[status.state] : "…"}</span>
          <button
            type="button"
            className="pill"
            disabled={!status || status.state === "loading" || status.state === "ready"}
            onClick={() => run((core) => core.prepareVoice())}
          >
            Carregar agora
          </button>
        </div>
        {status?.error && <div className="error-box">{status.error}</div>}
        <div className="setting-row">
          <span className="setting-label">
            Idioma do ditado
            <span className="small">Termos técnicos em inglês no meio da frase são esperados.</span>
          </span>
          <select value={language} onChange={(event) => onLanguage(event.target.value)}>
            <option value="pt">Português</option>
            <option value="en">Inglês</option>
            <option value="es">Espanhol</option>
          </select>
        </div>
      </div>
    </section>
  );
}

/**
 * Sobre (v0.9.4): a versão em uso e de onde ela roda. A MÊTIS instalada (scripts/instalar.sh)
 * procura versão nova no repositório e atualiza num terminal à vista; a de desenvolvimento
 * (scripts/dev.sh) só mostra de onde roda.
 */
function AboutSection({ client, onUpdateStarted }: { client: CoreClient | null; onUpdateStarted: (session: Session) => void }) {
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [busy, setBusy] = useState<"buscar" | "atualizar" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async (buscar: boolean) => {
    if (!client) return;
    setBusy(buscar ? "buscar" : null);
    setError(null);
    try {
      setInfo(await client.systemVersion(buscar));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  const update = async () => {
    if (!client || !info?.nova) return;
    setBusy("atualizar");
    setError(null);
    try {
      onUpdateStarted(await client.systemUpdate(info.nova));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const coreOld = info && info.versao !== __APP_VERSION__;
  return (
    <section className="settings-page">
      <h1>Sobre</h1>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            Versão
            <span className="small">
              {!info
                ? "…"
                : info.instalada
                  ? `A MÊTIS de uso, instalada da versão ${info.tag}.`
                  : `A MÊTIS de desenvolvimento, rodando do repositório.`}
              {coreOld ? ` O núcleo em execução é a v${info!.versao}.` : ""}
            </span>
          </span>
          <span className="mono">v{__APP_VERSION__}</span>
        </div>
        {info?.instalada ? (
          <div className="setting-row">
            <span className="setting-label">
              Atualização
              <span className="small">
                {info.nova
                  ? `A ${info.nova} está no repositório. Atualizar abre um terminal que monta a versão nova (a primeira compilação demora alguns minutos); depois é fechar e abrir a MÊTIS.`
                  : `Esta é a mais nova${info.ultima ? ` (${info.ultima})` : ""}. A MÊTIS procura sozinha a cada 6 horas.`}
              </span>
            </span>
            {info.nova ? (
              <button type="button" className="pill" disabled={!!busy} onClick={() => void update()}>
                {busy === "atualizar" ? "Abrindo…" : `Atualizar para ${info.nova}`}
              </button>
            ) : (
              <button type="button" className="pill ghost" disabled={!!busy} onClick={() => void load(true)}>
                {busy === "buscar" ? "Procurando…" : "Procurar agora"}
              </button>
            )}
          </div>
        ) : (
          info && (
            <div className="setting-row">
              <span className="setting-label">
                Instalar a de uso
                <span className="small">
                  Esta janela recompila quando o código muda. Para o dia a dia, instale a versão marcada mais nova
                  {info.ultima ? ` (${info.ultima})` : ""} com <span className="mono">scripts/instalar.sh</span>: ela vai para
                  /Applications e usa os seus dados em ~/.harness.
                </span>
              </span>
            </div>
          )
        )}
        {error && <div className="error-box">{error}</div>}
        <div className="setting-row">
          <span className="setting-label">
            Pasta
            <span className="small mono">{info?.pasta ?? "—"}</span>
          </span>
        </div>
        <div className="setting-row">
          <span className="setting-label">Núcleo</span>
          <span className="mono small">{client?.info.url ?? "—"}</span>
        </div>
        <div className="setting-row">
          <span className="setting-label">Código</span>
          <span className="mono small">github.com/PedroAugusto2305/personal-harness</span>
        </div>
      </div>
      <p className="small">Os atalhos estão em Ajustes → Atalhos, onde dá para mudar qualquer um. A lista de mudanças de cada versão está no CHANGELOG.md.</p>
    </section>
  );
}
