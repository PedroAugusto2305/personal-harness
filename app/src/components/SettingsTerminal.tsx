import { useEffect, useMemo, useState } from "react";
import type { CoreClient } from "../lib/core";
import { ACTIONS, FIXED, comboOf, comboProblem, compact, effective, formatCombo, recorder, type Overrides } from "../lib/keymap";
import { shortPath } from "../lib/format";
import { ICON, Icon } from "../icons";
import type { GhosttyInfo, Project, SavedCommand, TerminalColors, TerminalTheme, ThemeEntry } from "../types";

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

// --- Atalhos ------------------------------------------------------------------------------

/**
 * Atalhos (v0.9.3): todos mudam aqui ou à mão em ~/.harness/atalhos.json (só o que mudou).
 * "Mudar" grava a próxima tecla; um atalho já usado por outra ação passa para esta e a
 * outra fica sem atalho (com aviso), para nunca haver duas ações na mesma tecla.
 */
export function KeymapSection({
  keymap,
  file,
  onSave,
  onReload,
}: {
  keymap: Overrides;
  file: string | null;
  onSave: (overrides: Overrides) => Promise<void>;
  onReload: () => void;
}) {
  const [recording, setRecording] = useState<string | null>(null);
  const [note, setNote] = useState<{ id: string; text: string; bad?: boolean } | null>(null);
  const current = effective(keymap);
  const groups = [...new Set(ACTIONS.map((a) => a.group))];

  // O arquivo pode ter sido editado à mão: relê ao abrir a tela.
  useEffect(() => {
    onReload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!recording) return;
    recorder.active = true;
    const onKey = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === "Escape" && !event.metaKey && !event.ctrlKey && !event.altKey) {
        setRecording(null);
        return;
      }
      const combo = comboOf(event);
      if (!combo) return; // só o modificador: espera a tecla
      const problem = comboProblem(combo);
      if (problem) {
        setNote({ id: recording, text: problem, bad: true });
        return;
      }
      const taken = ACTIONS.find((a) => a.id !== recording && current[a.id] === combo);
      const next: Overrides = { ...keymap, [recording]: combo };
      if (taken) next[taken.id] = "";
      setNote(taken ? { id: recording, text: `${formatCombo(combo)} era de “${taken.label}”, que ficou sem atalho.` } : null);
      setRecording(null);
      void onSave(compact(next));
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      recorder.active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recording, keymap]);

  const set = (id: string, combo: string) => {
    setNote(null);
    void onSave(compact({ ...keymap, [id]: combo }));
  };

  return (
    <section className="settings-page">
      <h1>Atalhos</h1>
      <p className="lead">
        Clique em <b>Mudar</b> e aperte a combinação nova (Esc cancela). Os atalhos valem em toda a janela, também por cima das
        páginas do navegador embutido. O que você muda vai para <span className="mono">{file ? shortPath(file) : "~/.harness/atalhos.json"}</span>,
        que também dá para editar à mão.
      </p>
      {groups.map((group) => (
        <div className="card keymap" key={group}>
          <header className="card-head">
            <h2>{group}</h2>
          </header>
          {ACTIONS.filter((a) => a.group === group).map((action) => {
            const combo = current[action.id];
            const changed = action.id in keymap && keymap[action.id] !== action.combo;
            return (
              <div className="setting-row keymap-row" key={action.id} data-recording={recording === action.id ? "true" : undefined}>
                <span className="setting-label">
                  {action.label}
                  {note?.id === action.id && <span className={note.bad ? "small keymap-bad" : "small"}>{note.text}</span>}
                </span>
                <kbd className={combo ? undefined : "off"}>{recording === action.id ? "aperte…" : combo ? formatCombo(combo) : "sem atalho"}</kbd>
                <button type="button" className="pill" onClick={() => (setNote(null), setRecording(recording === action.id ? null : action.id))}>
                  {recording === action.id ? "Cancelar" : "Mudar"}
                </button>
                {combo ? (
                  <button type="button" className="pill ghost" title="Deixar esta ação sem atalho" onClick={() => set(action.id, "")}>
                    Desligar
                  </button>
                ) : (
                  <span />
                )}
                {changed ? (
                  <button type="button" className="pill ghost" title={`Padrão: ${action.combo ? formatCombo(action.combo) : "sem atalho"}`} onClick={() => set(action.id, action.combo)}>
                    Padrão
                  </button>
                ) : (
                  <span />
                )}
              </div>
            );
          })}
        </div>
      ))}
      <div className="card keymap">
        <header className="card-head">
          <h2>Fixos</h2>
        </header>
        {FIXED.map(([keys, label]) => (
          <div className="setting-row" key={keys}>
            <span className="setting-label">{label}</span>
            <kbd>{keys}</kbd>
          </div>
        ))}
      </div>
      {Object.keys(keymap).length > 0 && (
        <button type="button" className="btn" onClick={() => (setNote(null), void onSave({}))}>
          Voltar todos ao padrão
        </button>
      )}
    </section>
  );
}

// --- Comandos salvos -----------------------------------------------------------------------

interface Draft {
  nome: string;
  texto: string;
  tipo: "comando" | "prompt";
  projeto: string | null;
}

/**
 * Comandos salvos (v0.9.3): um comando roda no shell (o em foco, o mais recente da
 * worktree ou um novo); um prompt vai para a barra de entrada do agente, para revisar.
 * Valem em todos os projetos ou só num. Rodam pelo ⌘⇧K (ou ⌘K) e ficam em ~/.harness/comandos.json.
 */
export function CommandsSection({
  client,
  commands,
  projects,
  currentProject,
  onRun,
  shortcut,
}: {
  client: CoreClient | null;
  commands: SavedCommand[];
  projects: Project[];
  currentProject: string | null;
  onRun: (command: SavedCommand) => void;
  /** Atalho em vigor dos comandos salvos ("" se desligado). */
  shortcut: string;
}) {
  const [editing, setEditing] = useState<{ id: string | null; draft: Draft } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nameOf = (path: string) => projects.find((p) => p.path === path)?.name ?? shortPath(path);

  const groups = useMemo(() => {
    const map = new Map<string, SavedCommand[]>();
    for (const c of commands) {
      const key = c.projeto ?? "";
      map.set(key, [...(map.get(key) ?? []), c]);
    }
    return [...map.entries()].sort(([a], [b]) => (a === "" ? -1 : b === "" ? 1 : nameOf(a).localeCompare(nameOf(b))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commands, projects]);

  const save = async () => {
    if (!client || !editing) return;
    setBusy(true);
    setError(null);
    try {
      await client.saveCommand(editing.draft, editing.id ?? undefined);
      setEditing(null);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!client) return;
    try {
      await client.deleteCommand(id);
    } catch (cause) {
      setError(errorText(cause));
    }
  };

  const form = editing && (
    <form
      className="card command-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (editing.draft.nome.trim() && editing.draft.texto.trim()) void save();
      }}
      onKeyDown={(event) => event.key === "Escape" && setEditing(null)}
    >
      <div className="command-form-row">
        <input
          autoFocus
          value={editing.draft.nome}
          maxLength={80}
          placeholder="Nome, ex.: Rodar os testes"
          onChange={(event) => setEditing({ ...editing, draft: { ...editing.draft, nome: event.target.value } })}
        />
        <select
          value={editing.draft.tipo}
          aria-label="Tipo"
          onChange={(event) => setEditing({ ...editing, draft: { ...editing.draft, tipo: event.target.value as Draft["tipo"] } })}
        >
          <option value="comando">Comando do shell</option>
          <option value="prompt">Prompt para o agente</option>
        </select>
        <select
          value={editing.draft.projeto ?? ""}
          aria-label="Onde vale"
          onChange={(event) => setEditing({ ...editing, draft: { ...editing.draft, projeto: event.target.value || null } })}
        >
          <option value="">Todos os projetos</option>
          {projects.map((p) => (
            <option key={p.id} value={p.path}>
              Só em {p.name}
            </option>
          ))}
        </select>
      </div>
      <textarea
        className="mono"
        rows={editing.draft.tipo === "prompt" ? 5 : 3}
        maxLength={8000}
        value={editing.draft.texto}
        placeholder={editing.draft.tipo === "prompt" ? "O pedido, como você mandaria na barra de entrada" : "ex.: cd core && uv run pytest -q"}
        onChange={(event) => setEditing({ ...editing, draft: { ...editing.draft, texto: event.target.value } })}
      />
      <span className="small">
        {editing.draft.tipo === "prompt"
          ? "Vai para a barra de entrada do terminal em foco, para você revisar e mandar."
          : "Roda no shell em foco; sem shell aberto na worktree, abre um."}
      </span>
      {error && <div className="error-box">{error}</div>}
      <div className="form-buttons">
        <button type="submit" className="btn primary" disabled={busy || !editing.draft.nome.trim() || !editing.draft.texto.trim()}>
          {busy ? "Salvando…" : "Salvar"}
        </button>
        <button type="button" className="btn" onClick={() => setEditing(null)}>
          Cancelar
        </button>
      </div>
    </form>
  );

  return (
    <section className="settings-page">
      <h1>Comandos salvos</h1>
      <p className="lead">
        Comandos do shell e prompts que você repete, para rodar {shortcut ? <>com <kbd>{shortcut}</kbd> (ou pelo salto rápido)</> : "pelo salto rápido"}.
        Cada um vale em todos os projetos ou só num; ficam em <span className="mono">~/.harness/comandos.json</span>.
      </p>
      {!editing && (
        <button
          type="button"
          className="btn primary"
          disabled={!client}
          onClick={() => {
            setError(null);
            setEditing({ id: null, draft: { nome: "", texto: "", tipo: "comando", projeto: currentProject } });
          }}
        >
          <Icon d={ICON.plus} size={13} strokeWidth={2} /> Novo comando
        </button>
      )}
      {editing && !editing.id && form}
      {!commands.length && !editing && <p className="small">Nenhum comando salvo ainda.</p>}
      {error && !editing && <div className="error-box">{error}</div>}
      {groups.map(([project, list]) => (
        <div className="card" key={project || "todos"}>
          <header className="card-head">
            <h2>{project ? nameOf(project) : "Todos os projetos"}</h2>
            {project && <span className="path-chip">{shortPath(project)}</span>}
          </header>
          {list.map((command) =>
            editing?.id === command.id ? (
              <div key={command.id}>{form}</div>
            ) : (
              <div className="setting-row command-row" key={command.id}>
                <span className="command-kind mono" title={command.tipo === "prompt" ? "Prompt para o agente" : "Comando do shell"}>
                  {command.tipo === "prompt" ? "✎" : "$"}
                </span>
                <span className="setting-label">
                  {command.nome}
                  <span className="small mono command-text">{command.texto}</span>
                </span>
                <button type="button" className="pill" onClick={() => onRun(command)}>
                  Rodar
                </button>
                <button
                  type="button"
                  className="pill ghost"
                  onClick={() => {
                    setError(null);
                    setEditing({ id: command.id, draft: { nome: command.nome, texto: command.texto, tipo: command.tipo, projeto: command.projeto } });
                  }}
                >
                  Editar
                </button>
                <button type="button" className="pill ghost" title="Apagar" aria-label={`Apagar ${command.nome}`} onClick={() => void remove(command.id)}>
                  <Icon d={ICON.trash} size={12} />
                </button>
              </div>
            ),
          )}
        </div>
      ))}
    </section>
  );
}

// --- Tema do terminal ------------------------------------------------------------------------

const ANSI_ORDER: (keyof TerminalColors)[] = [
  "black",
  "red",
  "green",
  "yellow",
  "blue",
  "magenta",
  "cyan",
  "white",
  "brightBlack",
  "brightRed",
  "brightGreen",
  "brightYellow",
  "brightBlue",
  "brightMagenta",
  "brightCyan",
  "brightWhite",
];

const ORIGIN_LABEL: Record<GhosttyInfo["temas"][number]["origem"], string> = {
  metis: "vem com a MÊTIS",
  usuario: "seu",
  ghostty: "do Ghostty",
};

/** Prévia de um tema: fundo, texto e as 16 cores. */
function ThemePreview({ colors }: { colors: TerminalColors }) {
  return (
    <div className="term-preview mono" style={{ background: colors.background, color: colors.foreground }} aria-hidden="true">
      <span>
        <span style={{ color: colors.green }}>pedro</span>
        <span style={{ color: colors.brightBlack }}> ~/metis </span>
        <span style={{ color: colors.magenta }}>git:(main)</span> claude
      </span>
      <span className="term-preview-swatches">
        {ANSI_ORDER.map((key) => (
          <span key={key} style={{ background: colors[key] ?? "transparent" }} title={key} />
        ))}
      </span>
    </div>
  );
}

/**
 * Tema do terminal (v0.9.3): por padrão, as cores do tema da MÊTIS. Dá para usar um tema do
 * Ghostty (os do Ghostty.app e da sua pasta de temas, o do seu config, e o Ghostty Default
 * Style Dark, que é o do seu Orca e vem junto) ou colar um tema no formato do Ghostty.
 */
export function TerminalThemeCard({
  client,
  value,
  onChange,
}: {
  client: CoreClient | null;
  value: TerminalTheme | null;
  onChange: (theme: TerminalTheme | null) => void;
}) {
  const [info, setInfo] = useState<GhosttyInfo | null>(null);
  /** v0.9.8: os temas do Ghostty, do Kitty e do Warp achados no Mac. */
  const [themes, setThemes] = useState<ThemeEntry[]>([]);
  const [pick, setPick] = useState("");
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .ghostty()
      .then((answer) => {
        if (!alive) return;
        setInfo(answer);
        setPick((current) => current || `ghostty::${answer.config?.tema || answer.temas[0]?.nome || ""}`);
      })
      .catch((cause) => alive && setError(errorText(cause)));
    client
      .themes()
      .then((answer) => alive && setThemes(answer.temas))
      .catch(() => undefined); // núcleo de antes da v0.9.8: só os do Ghostty
    return () => {
      alive = false;
    };
  }, [client]);

  const use = async (load: () => Promise<TerminalTheme>) => {
    setBusy(true);
    setError(null);
    try {
      onChange(await load());
      setPasting(false);
      setText("");
      setName("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card term-theme">
      <header className="card-head">
        <span className="card-glyph">
          <Icon d={ICON.terminal} size={16} />
        </span>
        <h2>Tema do terminal</h2>
        <span className="grow" />
        {value && (
          <button type="button" className="pill ghost" onClick={() => onChange(null)}>
            Voltar às cores da MÊTIS
          </button>
        )}
      </header>
      <div className="setting-row">
        <span className="setting-label">
          Em uso
          <span className="small">{value ? value.nome : "As cores do tema da MÊTIS (mudam com o tema acima)."}</span>
        </span>
        {value && <ThemePreview colors={value.cores} />}
      </div>
      <div className="setting-row">
        <span className="setting-label">
          Importar do Ghostty, Kitty ou Warp
          <span className="small">
            {info?.config
              ? `Seu config: ${shortPath(info.config.arquivo)}${info.config.tema ? `, com o tema ${info.config.tema}` : ""}.`
              : "O Ghostty não está neste Mac; a MÊTIS traz o Ghostty Default Style Dark, o tema do seu Orca."}
          </span>
        </span>
        <select value={pick} disabled={!themes.length && !info?.temas.length} onChange={(event) => setPick(event.target.value)} aria-label="Tema importado">
          {(themes.length ? themes : (info?.temas ?? []).map((t) => ({ ...t, formato: "ghostty" as const }))).map((t) => (
            <option key={`${t.formato}::${t.nome}`} value={`${t.formato}::${t.nome}`}>
              {t.nome} · {t.formato === "ghostty" ? ORIGIN_LABEL[t.origem] : t.formato === "kitty" ? "do Kitty" : "do Warp"}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="pill"
          disabled={!client || !pick || busy}
          onClick={() => {
            const [formato, ...rest] = pick.split("::");
            const nome = rest.join("::");
            void use(() => (themes.length ? client!.theme(nome, formato) : client!.ghosttyTheme(nome)));
          }}
        >
          Usar
        </button>
      </div>
      <div className="setting-row">
        <span className="setting-label">
          Colar um tema
          <span className="small">
            Do Ghostty (<span className="mono">palette = 0=#1d1f21</span>), do Kitty (<span className="mono">color0 #1d1f21</span>) ou do Warp
            (YAML com <span className="mono">terminal_colors</span>): o formato é reconhecido sozinho.
          </span>
        </span>
        <button type="button" className="pill" onClick={() => setPasting((v) => !v)}>
          {pasting ? "Fechar" : "Colar…"}
        </button>
      </div>
      {pasting && (
        <form
          className="term-theme-paste"
          onSubmit={(event) => {
            event.preventDefault();
            if (text.trim() && client)
              void use(() => client.readTheme(text, name.trim() || undefined).catch(() => client.readGhosttyTheme(text, name.trim() || undefined)));
          }}
        >
          <input value={name} maxLength={60} placeholder="Nome (opcional)" onChange={(event) => setName(event.target.value)} />
          <textarea
            className="mono"
            rows={8}
            value={text}
            placeholder={"background = #282c34\nforeground = #ffffff\npalette = 0=#1d1f21\npalette = 1=#cc6666\n…"}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="form-buttons">
            <button type="submit" className="btn primary" disabled={!text.trim() || busy}>
              {busy ? "Lendo…" : "Importar e usar"}
            </button>
          </div>
        </form>
      )}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

// --- Busca nos ajustes -----------------------------------------------------------------------

export interface FindEntry {
  section: string;
  label: string;
  /** Texto na tela para achar e acender (o próprio label quando vazio). */
  find?: string;
  /** Sinônimos e os termos em inglês e espanhol. */
  terms: string;
}
