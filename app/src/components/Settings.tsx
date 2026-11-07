import { useEffect, useState } from "react";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, PROVIDERS, shortPath } from "../lib/format";
import { ICON, Icon } from "../icons";
import type { Accounts, Provider, ThemeName, Usage, VoiceStatus } from "../types";
import { THEME_LABEL } from "./Chrome";
import { Limits } from "./StatusBar";

export type SettingsSection = "contas" | "aparencia" | "voz" | "sobre";

const SECTIONS: { key: SettingsSection; label: string; icon: keyof typeof ICON }[] = [
  { key: "contas", label: "Contas e uso", icon: "user" },
  { key: "aparencia", label: "Aparência", icon: "palette" },
  { key: "voz", label: "Voz", icon: "mic" },
  { key: "sobre", label: "Sobre e atalhos", icon: "info" },
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

export const THEMES: ThemeName[] = ["dracula", "grafite", "claro"];

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
}

export function Settings(props: Props) {
  return (
    <div className="settings">
      <nav className="settings-nav" aria-label="Seções dos ajustes">
        <span className="section-title">Ajustes</span>
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
      <div className="settings-body">
        {props.section === "contas" && <AccountsSection {...props} />}
        {props.section === "aparencia" && <AppearanceSection theme={props.theme} onTheme={props.onTheme} />}
        {props.section === "voz" && <VoiceSection {...props} />}
        {props.section === "sobre" && <AboutSection client={props.client} />}
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

function AppearanceSection({ theme, onTheme }: { theme: ThemeName; onTheme: (theme: ThemeName) => void }) {
  return (
    <section className="settings-page">
      <h1>Aparência</h1>
      <p className="lead">O tema é um conjunto de cores. Trocar aqui muda a interface e os terminais na hora.</p>
      <div className="themes">
        {THEMES.map((name) => (
          <button key={name} type="button" className="theme-card" aria-pressed={theme === name} onClick={() => onTheme(name)}>
            <span className="theme-preview" data-theme={name} aria-hidden="true">
              <span className="tp-bar" />
              <span className="tp-body">
                <span className="tp-side">
                  <span className="tp-line acc" />
                  <span className="tp-line" />
                  <span className="tp-line" />
                </span>
                <span className="tp-term">
                  <span className="tp-line acc short" />
                  <span className="tp-line" />
                  <span className="tp-line short" />
                </span>
              </span>
            </span>
            <span className="theme-name">{THEME_LABEL[name]}</span>
          </button>
        ))}
        <div className="theme-card soon" aria-disabled="true">
          <span className="theme-preview prompt" aria-hidden="true">
            <Icon d={ICON.palette} size={26} strokeWidth={1.4} />
          </span>
          <span className="theme-name">Criar tema com prompt</span>
          <span className="small">Você descreve, um agente gera as cores e a MÊTIS confere o contraste. Chega numa próxima versão.</span>
        </div>
      </div>
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

const SHORTCUTS: [string, string][] = [
  ["⌘K", "Salto rápido: terminais e ações"],
  ["⌘1 … ⌘9", "Ir para a aba"],
  ["⌘D", "Dividir ou juntar a tela"],
  ["⌃`", "Terminal flutuante"],
  ["⌘L", "Ir para a barra de entrada"],
  ["⌘⇧M", "Ditar / parar"],
  ["Esc", "Cancelar a gravação · voltar ao terminal"],
  ["⌘,", "Ajustes"],
];

function AboutSection({ client }: { client: CoreClient | null }) {
  return (
    <section className="settings-page">
      <h1>Sobre e atalhos</h1>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">Versão</span>
          <span className="mono">v{__APP_VERSION__}</span>
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
      <h2 className="sub">Atalhos</h2>
      <div className="card">
        {SHORTCUTS.map(([keys, label]) => (
          <div className="setting-row" key={keys}>
            <span className="setting-label">{label}</span>
            <kbd>{keys}</kbd>
          </div>
        ))}
      </div>
    </section>
  );
}
