import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { browser } from "../lib/browser";
import { CoreError, type CoreClient } from "../lib/core";
import {
  BUILTIN_THEMES,
  fontInstalled,
  MONO_FONTS,
  themeKey,
  themeLabel,
  UI_FONTS,
  ZOOM_STEPS,
  type Appearance,
  type Density,
} from "../lib/appearance";
import { ICON, Icon } from "../icons";
import type { AppTheme, AppThemeSource, BrowserProfile, CookieSource, ThemeName } from "../types";

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** Prévia de um tema: os tokens do tema do núcleo por cima do de base. */
function Preview({ name, theme }: { name: ThemeName; theme?: AppTheme }) {
  const style = theme ? (Object.fromEntries(Object.entries(theme.cores).map(([k, v]) => [`--${k}`, v])) as CSSProperties) : undefined;
  return (
    <span className="theme-preview" data-theme={theme ? (theme.base === "claro" ? "claro" : "dracula") : name} style={style} aria-hidden="true">
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
  );
}

const ORIGIN: Record<AppTheme["origem"], string> = { prompt: "por prompt", vscode: "do VS Code", obsidian: "do Obsidian" };

interface AppearanceProps {
  client: CoreClient | null;
  theme: ThemeName;
  onTheme: (theme: ThemeName) => void;
  themes: AppTheme[];
  appearance: Appearance;
  onAppearance: (value: Appearance) => void;
  children?: ReactNode;
}

/**
 * Aparência (v0.9.8): os três temas da MÊTIS, os feitos por prompt e os importados do VS Code
 * e do Obsidian, com fontes, densidade e zoom.
 */
export function AppearanceSection({ client, theme, onTheme, themes, appearance, onAppearance, children }: AppearanceProps) {
  const [prompt, setPrompt] = useState("");
  const [making, setMaking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [sources, setSources] = useState<AppThemeSource[] | null>(null);
  const [source, setSource] = useState("");
  const [importing, setImporting] = useState(false);

  const created = (made: AppTheme) => {
    onTheme(themeKey(made));
    setNotes(made.ajustes);
  };

  const make = async () => {
    if (!client || prompt.trim().length < 3) return;
    setMaking(true);
    setProblem(null);
    setNotes([]);
    try {
      created(await client.promptAppTheme(prompt.trim()));
      setPrompt("");
    } catch (cause) {
      setProblem(errorText(cause));
    } finally {
      setMaking(false);
    }
  };

  const loadSources = async () => {
    if (!client) return;
    try {
      const answer = await client.appThemeSources();
      setSources(answer.fontes);
      setSource(answer.fontes.find((f) => f.em_uso)?.id ?? answer.fontes[0]?.id ?? "");
    } catch (cause) {
      setProblem(errorText(cause));
    }
  };

  const importOne = async () => {
    if (!client || !source) return;
    setImporting(true);
    setProblem(null);
    setNotes([]);
    try {
      created(await client.importAppTheme(source));
    } catch (cause) {
      setProblem(errorText(cause));
    } finally {
      setImporting(false);
    }
  };

  const remove = async (item: AppTheme) => {
    if (!client) return;
    if (theme === themeKey(item)) onTheme("dracula");
    await client.deleteAppTheme(item.id).catch((cause) => setProblem(errorText(cause)));
  };

  const fonts = useMemo(
    () => ({
      ui: UI_FONTS.filter((f) => f.embutida || f.valor === appearance.ui || fontInstalled(f.valor)),
      mono: MONO_FONTS.filter((f) => f.embutida || f.valor === appearance.mono || fontInstalled(f.valor)),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const set = (change: Partial<Appearance>) => onAppearance({ ...appearance, ...change });
  const grouped = (origin: AppThemeSource["origem"]) => (sources ?? []).filter((s) => s.origem === origin);

  return (
    <section className="settings-page">
      <h1>Aparência</h1>
      <p className="lead">O tema é um conjunto de cores. Trocar aqui muda a interface e os terminais na hora.</p>
      <div className="themes">
        {BUILTIN_THEMES.map((name) => (
          <button key={name} type="button" className="theme-card" aria-pressed={theme === name} onClick={() => onTheme(name)}>
            <Preview name={name} />
            <span className="theme-name">{themeLabel(name)}</span>
          </button>
        ))}
        {themes.map((item) => (
          <div key={item.id} className="theme-card custom" aria-pressed={theme === themeKey(item)}>
            <button type="button" className="theme-pick" onClick={() => onTheme(themeKey(item))} title={item.fonte}>
              <Preview name={themeKey(item)} theme={item} />
              <span className="theme-name">{item.nome}</span>
              <span className="small">{ORIGIN[item.origem]}</span>
            </button>
            <button type="button" className="icon-btn theme-remove" title="Apagar este tema" aria-label={`Apagar o tema ${item.nome}`} onClick={() => void remove(item)}>
              <Icon d={ICON.trash} size={13} />
            </button>
          </div>
        ))}
      </div>

      <div className="card theme-maker">
        <div className="setting-row">
          <span className="setting-label">
            Criar tema com prompt
            <span className="small">Descreva as cores; o Claude gera o tema e a MÊTIS confere o contraste do texto (e corrige o que precisar).</span>
          </span>
        </div>
        <form
          className="theme-prompt"
          onSubmit={(event) => {
            event.preventDefault();
            void make();
          }}
        >
          <input
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="ex.: noite em Atenas, mármore escuro com dourado e azul do Egeu"
            maxLength={400}
            disabled={making}
          />
          <button type="submit" className="btn primary" disabled={!client || making || prompt.trim().length < 3}>
            {making ? "Criando…" : "Criar"}
          </button>
        </form>
        <div className="setting-row">
          <span className="setting-label">
            Importar do VS Code ou do Obsidian
            <span className="small">Os temas instalados no VS Code (e no Cursor) e os dos cofres do Obsidian, convertidos para as cores da MÊTIS.</span>
          </span>
          {sources === null ? (
            <button type="button" className="btn" disabled={!client} onClick={() => void loadSources()}>
              Ver temas
            </button>
          ) : (
            <div className="theme-import">
              <select value={source} onChange={(event) => setSource(event.target.value)} aria-label="Tema para importar">
                {(["vscode", "obsidian"] as const).map((origin) =>
                  grouped(origin).length ? (
                    <optgroup key={origin} label={origin === "vscode" ? "VS Code" : "Obsidian"}>
                      {grouped(origin).map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.nome} · {item.base}
                          {item.em_uso ? " (em uso)" : ""}
                        </option>
                      ))}
                    </optgroup>
                  ) : null,
                )}
              </select>
              <button type="button" className="btn" disabled={!source || importing} onClick={() => void importOne()}>
                {importing ? "Importando…" : "Importar"}
              </button>
            </div>
          )}
        </div>
        {problem && <div className="error-box">{problem}</div>}
        {notes.length > 0 && (
          <p className="small theme-notes">
            Ajustes de contraste: {notes.join("; ")}.
          </p>
        )}
      </div>

      <h2 className="sub">Letras e tamanho</h2>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            Fonte da interface
            <span className="small">Só aparecem as instaladas neste Mac.</span>
          </span>
          <select value={appearance.ui} onChange={(event) => set({ ui: event.target.value })} aria-label="Fonte da interface">
            {fonts.ui.map((f) => (
              <option key={f.valor} value={f.valor}>
                {f.nome}
              </option>
            ))}
          </select>
        </div>
        <div className="setting-row">
          <span className="setting-label">
            Fonte do terminal e do código
            <span className="small">Terminais, editores e diffs.</span>
          </span>
          <select value={appearance.mono} onChange={(event) => set({ mono: event.target.value })} aria-label="Fonte mono" style={{ fontFamily: `"${appearance.mono}"` }}>
            {fonts.mono.map((f) => (
              <option key={f.valor} value={f.valor}>
                {f.nome}
              </option>
            ))}
          </select>
        </div>
        <div className="setting-row">
          <span className="setting-label">Tamanho da letra do terminal</span>
          <div className="segmented" role="radiogroup" aria-label="Tamanho da letra do terminal">
            {[11, 12, 13, 14, 15, 16].map((size) => (
              <button key={size} type="button" role="radio" aria-checked={appearance.termSize === size} onClick={() => set({ termSize: size })}>
                {size}
              </button>
            ))}
          </div>
        </div>
        <div className="setting-row">
          <span className="setting-label">
            Densidade
            <span className="small">Quanto espaço entre as linhas das listas, das abas e da barra lateral.</span>
          </span>
          <div className="segmented" role="radiogroup" aria-label="Densidade">
            {(
              [
                ["compacta", "Compacta"],
                ["normal", "Normal"],
                ["confortavel", "Confortável"],
              ] as [Density, string][]
            ).map(([value, label]) => (
              <button key={value} type="button" role="radio" aria-checked={appearance.density === value} onClick={() => set({ density: value })}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="setting-row">
          <span className="setting-label">
            Zoom da janela
            <span className="small">⌘+ e ⌘- também mudam; ⌘0 volta a 100%.</span>
          </span>
          <div className="segmented" role="radiogroup" aria-label="Zoom da janela">
            {ZOOM_STEPS.map((step) => (
              <button key={step} type="button" role="radio" aria-checked={Math.abs(appearance.zoom - step) < 0.001} onClick={() => set({ zoom: step })}>
                {Math.round(step * 100)}%
              </button>
            ))}
          </div>
        </div>
      </div>
      {children}
    </section>
  );
}

// --- Navegador ------------------------------------------------------------------------------

export type LinkTarget = "metis" | "mac";

interface BrowserProps {
  client: CoreClient | null;
  profiles: BrowserProfile[];
  defaultProfile: string;
  onDefaultProfile: (id: string) => void;
  linkTarget: LinkTarget;
  onLinkTarget: (value: LinkTarget) => void;
  /** Abas abertas por perfil (apagar um perfil fecha as dele antes). */
  openTabs: (profileId: string) => number;
  onCloseProfileTabs: (profileId: string) => void;
}

/** Navegador (v0.9.8): perfis com cofres separados, cookies do Chrome, histórico e links. */
export function BrowserSection(props: BrowserProps) {
  const { client, profiles } = props;
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; nome: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [sources, setSources] = useState<CookieSource[] | null>(null);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("padrao");
  const [domains, setDomains] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!done) return;
    const timer = window.setTimeout(() => setDone(null), 6000);
    return () => window.clearTimeout(timer);
  }, [done]);

  const fail = (cause: unknown) => setProblem(cause instanceof CoreError ? cause.message : errorText(cause));

  const create = async () => {
    if (!client || !name.trim()) return;
    setProblem(null);
    try {
      await client.createBrowserProfile(name.trim());
      setName("");
    } catch (cause) {
      fail(cause);
    }
  };

  const rename = async () => {
    if (!client || !renaming?.nome.trim()) return;
    try {
      await client.renameBrowserProfile(renaming.id, renaming.nome.trim());
      setRenaming(null);
    } catch (cause) {
      fail(cause);
    }
  };

  const remove = async (profile: BrowserProfile) => {
    if (!client || !profile.identificador) return;
    setProblem(null);
    props.onCloseProfileTabs(profile.id);
    try {
      // As abas dele precisam sumir antes de o WebKit apagar o cofre.
      await new Promise((done) => window.setTimeout(done, 600));
      if (browser.available()) await browser.removeProfile(profile.identificador);
      await client.deleteBrowserProfile(profile.id);
      if (props.defaultProfile === profile.id) props.onDefaultProfile("padrao");
      setDone(`Perfil ${profile.nome} apagado, com os cookies e os dados dele.`);
    } catch (cause) {
      fail(cause);
    }
  };

  const loadSources = async () => {
    if (!client) return;
    try {
      const answer = await client.cookieSources();
      setSources(answer.fontes);
      setSource(answer.fontes[0]?.id ?? "");
    } catch (cause) {
      fail(cause);
    }
  };

  const importCookies = async () => {
    if (!client || !source) return;
    setBusy(true);
    setProblem(null);
    try {
      const list = domains
        .split(/[\s,]+/)
        .map((d) => d.trim())
        .filter(Boolean);
      const answer = await client.readCookies(source, list);
      // Os de localhost ficam de fora (a não ser que você peça): o Chrome junta cookies de
      // todo projeto local, e o servidor de dev responde 431 com o cabeçalho grande demais.
      const local = (domain: string) => ["localhost", "127.0.0.1", "[::1]"].includes(domain.replace(/^\./, ""));
      const wantsLocal = list.some(local);
      const cookies = answer.cookies.filter((c) => wantsLocal || !local(c.dominio));
      const skipped = answer.cookies.length - cookies.length;
      const profile = profiles.find((p) => p.id === target);
      if (!browser.available()) throw new Error("importar cookies só funciona no app");
      const count = await browser.importCookies(profile?.identificador ?? null, cookies);
      const from = sources?.find((s) => s.id === source);
      setDone(
        `${count} cookie(s) do ${from?.navegador ?? "Chrome"} (${from?.perfil ?? source}) no perfil ${profile?.nome ?? "Padrão"}` +
          (answer.ignorados ? `; ${answer.ignorados} não decifraram` : "") +
          (skipped ? `; ${skipped} de localhost ficaram de fora` : "") +
          ". Recarregue as abas desse perfil.",
      );
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  const clearHistory = async () => {
    if (!client) return;
    await client.clearWebHistory().then(
      () => setDone("Histórico do navegador apagado."),
      (cause) => fail(cause),
    );
  };

  return (
    <section className="settings-page">
      <h1>Navegador</h1>
      <p className="lead">
        Cada perfil tem os próprios cookies, logins e armazenamento: uma conta de trabalho e outra pessoal no mesmo site, sem uma ver a outra.
      </p>

      <h2 className="sub">Perfis</h2>
      <div className="card">
        {profiles.map((profile) => (
          <div className="setting-row" key={profile.id}>
            {renaming?.id === profile.id ? (
              <form
                className="inline-form profile-rename"
                onSubmit={(event) => {
                  event.preventDefault();
                  void rename();
                }}
              >
                <input autoFocus value={renaming.nome} maxLength={40} onChange={(event) => setRenaming({ id: profile.id, nome: event.target.value })} />
                <button type="submit" className="btn primary">
                  Salvar
                </button>
                <button type="button" className="btn" onClick={() => setRenaming(null)}>
                  Cancelar
                </button>
              </form>
            ) : (
              <span className="setting-label">
                {profile.nome}
                <span className="small">
                  {profile.identificador ? `${props.openTabs(profile.id)} aba(s) aberta(s)` : "o cofre de sempre do navegador da MÊTIS"}
                  {props.defaultProfile === profile.id ? " · abas novas abrem nele" : ""}
                </span>
              </span>
            )}
            {renaming?.id !== profile.id && (
              <div className="row-buttons">
                {props.defaultProfile !== profile.id && (
                  <button type="button" className="btn" onClick={() => props.onDefaultProfile(profile.id)}>
                    Usar nas abas novas
                  </button>
                )}
                {profile.identificador && (
                  <>
                    <button type="button" className="btn" onClick={() => setRenaming({ id: profile.id, nome: profile.nome })}>
                      Renomear
                    </button>
                    <button type="button" className="icon-btn" title="Apagar o perfil e os dados dele" aria-label={`Apagar o perfil ${profile.nome}`} onClick={() => void remove(profile)}>
                      <Icon d={ICON.trash} size={13} />
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        <form
          className="setting-row inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <input value={name} maxLength={40} onChange={(event) => setName(event.target.value)} placeholder="Nome do perfil novo (ex.: Seller Pro)" />
          <button type="submit" className="btn primary" disabled={!client || !name.trim()}>
            Criar perfil
          </button>
        </form>
      </div>

      <h2 className="sub">Importar cookies do Chrome</h2>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            Entrar nos sites como no Chrome
            <span className="small">
              Lê os cookies de um perfil do Chrome (ou Brave, Edge, Arc) e grava num perfil da MÊTIS. O macOS pede licença para a MÊTIS ler a chave
              do Chrome no Keychain; os cookies não saem do Mac.
            </span>
          </span>
          {sources === null && (
            <button type="button" className="btn" disabled={!client} onClick={() => void loadSources()}>
              Procurar navegadores
            </button>
          )}
        </div>
        {sources !== null && sources.length === 0 && <p className="small doc-empty">Nenhum Chrome, Brave, Edge ou Arc com cookies neste Mac.</p>}
        {sources !== null && sources.length > 0 && (
          <div className="cookie-import">
            <label>
              <span className="small">De</span>
              <select value={source} onChange={(event) => setSource(event.target.value)}>
                {sources.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.navegador} · {item.perfil}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="small">Para o perfil</span>
              <select value={target} onChange={(event) => setTarget(event.target.value)}>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nome}
                  </option>
                ))}
              </select>
            </label>
            <label className="grow">
              <span className="small">Só destes sites (opcional)</span>
              <input value={domains} onChange={(event) => setDomains(event.target.value)} placeholder="ex.: github.com, google.com" />
            </label>
            <button type="button" className="btn primary" disabled={busy || !source} onClick={() => void importCookies()}>
              {busy ? "Importando…" : "Importar"}
            </button>
          </div>
        )}
      </div>

      <h2 className="sub">Links e histórico</h2>
      <div className="card">
        <div className="setting-row">
          <span className="setting-label">
            ⌘ + clique num link do terminal abre
            <span className="small">Com ⇧ junto, abre no outro.</span>
          </span>
          <div className="segmented" role="radiogroup" aria-label="Onde abrem os links do terminal">
            {(
              [
                ["metis", "Na MÊTIS"],
                ["mac", "No navegador do Mac"],
              ] as [LinkTarget, string][]
            ).map(([value, label]) => (
              <button key={value} type="button" role="radio" aria-checked={props.linkTarget === value} onClick={() => props.onLinkTarget(value)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="setting-row">
          <span className="setting-label">
            Histórico do navegador
            <span className="small">As páginas abertas (menos as abas anônimas) aparecem no ⌘K ao digitar.</span>
          </span>
          <button type="button" className="btn danger" disabled={!client} onClick={() => void clearHistory()}>
            Apagar o histórico
          </button>
        </div>
      </div>
      {problem && <div className="error-box">{problem}</div>}
      {done && <p className="small settings-done">{done}</p>}
    </section>
  );
}
