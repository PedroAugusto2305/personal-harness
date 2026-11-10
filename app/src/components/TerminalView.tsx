import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { KindIcon } from "./KindIcon";
import { Terminal, type IBufferLine, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon, type ISearchOptions } from "@xterm/addon-search";
import { ClipboardAddon, type IClipboardProvider } from "@xterm/addon-clipboard";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { CoreError, type CoreClient } from "../lib/core";
import { KIND_LABEL, STATUS_COLOR, STATUS_LABEL, shortPath } from "../lib/format";
import { pastedFiles, terminals } from "../lib/terminals";
import { ICON, Icon } from "../icons";
import type { Session, SessionContext, TerminalColors, ThemeName } from "../types";
import { DEFAULT_APPEARANCE, monoFamily, themeIsLight, type Appearance } from "../lib/appearance";

const ANSI_DARK = {
  black: "#21222c",
  red: "#ff5555",
  green: "#50fa7b",
  yellow: "#f1fa8c",
  blue: "#82a0ff",
  magenta: "#ff79c6",
  cyan: "#8be9fd",
  white: "#f8f8f2",
  brightBlack: "#6272a4",
  brightRed: "#ff6e6e",
  brightGreen: "#69ff94",
  brightYellow: "#ffffa5",
  brightBlue: "#a9bcff",
  brightMagenta: "#ff92df",
  brightCyan: "#a4ffff",
  brightWhite: "#ffffff",
};

const ANSI_LIGHT = {
  black: "#1f2330",
  red: "#c62828",
  green: "#2e7d32",
  yellow: "#8a6d00",
  blue: "#2f53c0",
  magenta: "#a12a7a",
  cyan: "#0b7ea8",
  white: "#5e6478",
  brightBlack: "#4f5568",
  brightRed: "#d32f2f",
  brightGreen: "#388e3c",
  brightYellow: "#9a7b00",
  brightBlue: "#3b63d6",
  brightMagenta: "#b33a8a",
  brightCyan: "#0e8fbf",
  brightWhite: "#1f2330",
};

/**
 * OSC 52 só para copiar. O provedor padrão também atende a leitura (`ESC]52;c;?`): qualquer texto
 * que passasse pelo terminal (um README, a saída de um curl) leria a área de transferência do Mac e
 * a mandaria ao programa como entrada. Aqui a leitura volta sempre vazia.
 */
const COPY_ONLY_CLIPBOARD: IClipboardProvider = {
  readText: () => "",
  writeText: (selection, text) =>
    String(selection) === "c" ? navigator.clipboard.writeText(text).catch(() => undefined) : undefined,
};

/**
 * O tema do terminal sai dos mesmos tokens da interface; com um tema de terminal escolhido
 * (v0.9.3: importado do Ghostty), as cores dele vão por cima.
 */
function terminalTheme(theme: ThemeName, colors?: TerminalColors | null): ITheme {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string) => css.getPropertyValue(name).trim();
  return {
    background: token("--term"),
    foreground: token("--tx"),
    cursor: token("--acc"),
    cursorAccent: token("--term"),
    selectionBackground: token("--sel"),
    ...(themeIsLight(theme) ? ANSI_LIGHT : ANSI_DARK),
    ...(colors ?? {}),
  };
}

/** Linha de traços (borda da caixa de entrada do Claude), mesmo com o nome da sessão no meio. */
function isRule(text: string): boolean {
  const t = text.trim();
  if (t.length < 8 || !t.startsWith("─")) return false;
  return [...t].filter((c) => c === "─").length / t.length > 0.6;
}

/** O que vem depois do "❯" é vazio ou só dica apagada (dim): a caixa está vazia. */
function emptyPrompt(line: IBufferLine, cols: number): boolean {
  const text = line.translateToString(true);
  const at = text.indexOf("❯");
  if (at < 0 || text.slice(0, at).trim()) return false;
  for (let x = at + 1; x < cols; x += 1) {
    const cell = line.getCell(x);
    if (!cell) break;
    const ch = cell.getChars();
    if (ch && ch.trim() && !cell.isDim()) return false;
  }
  return true;
}

/**
 * A caixa de entrada vazia do Claude no fim da tela: [traços, "❯ …", traços, status…].
 * Devolve a linha onde ela começa (para cobrir dali para baixo) e o texto das linhas de
 * status/modo abaixo dela; null quando há menu, pergunta ou texto de verdade na caixa.
 */
function findInputBox(terminal: Terminal): { top: number; status: string } | null {
  const buffer = terminal.buffer.active;
  const base = buffer.viewportY;
  const rows = terminal.rows;
  const text = (i: number) => buffer.getLine(base + i)?.translateToString(true) ?? "";
  for (let p = rows - 1; p > 0; p -= 1) {
    const line = buffer.getLine(base + p);
    if (!line || !text(p).trimStart().startsWith("❯")) continue;
    if (!isRule(text(p - 1)) || !emptyPrompt(line, terminal.cols)) return null;
    const bottom = [...Array(Math.min(4, rows - p - 1)).keys()].map((k) => p + 1 + k).find((i) => isRule(text(i)));
    if (bottom === undefined) return null;
    const status = [...Array(rows - bottom - 1).keys()]
      .map((k) => text(bottom + 1 + k).trim())
      // A linha "◆ …" é a statusline da própria MÊTIS (já na barra de status): fica de fora.
      .filter((line) => line && !line.startsWith("◆"))
      .slice(-2)
      .join(" · ");
    return { top: p - 1, status };
  }
  return null;
}

/**
 * Onde o terminal aparece. Todos ficam montados; só mudam de lugar ou somem.
 * "tile" é um painel da divisão da worktree (a posição vem em `box`).
 */
export type Slot = "tile" | "float" | "hidden";

interface Props {
  session: Session;
  client: CoreClient;
  theme: ThemeName;
  slot: Slot;
  focused: boolean;
  /** A tela está dividida (o painel em foco ganha contorno). */
  tiled: boolean;
  /** Posição do painel na divisão (v0.9.3). */
  box?: CSSProperties;
  /** Cores do tema de terminal escolhido (null = as do tema da MÊTIS). */
  colors?: TerminalColors | null;
  /** Fonte mono e tamanho da letra (Ajustes → Aparência, v0.9.8). */
  font?: Appearance;
  /** Sobe para abrir a busca neste terminal (⌘F). */
  searchSignal?: number;
  accountName: string | null;
  /** Sprite do agente, quando a sessão é de um agente. */
  badge?: ReactNode;
  /** "projeto · worktree" quando o terminal está dentro de um projeto. */
  place?: string | null;
  dropping: boolean;
  /** ⌘ + clique num link: abre no navegador da MÊTIS (com ⇧, no do Mac). */
  onLink?: (url: string, external: boolean) => void;
  /**
   * Terminal só para ler (Claude e Codex): o que se digita aqui vai para a barra de baixo,
   * que é a única entrada; setas, Enter, Esc, ⇧Tab e ⌃C seguem para os menus do agente.
   */
  readOnly?: boolean;
  /** Texto digitado ou colado num terminal só para ler: vai para a barra. */
  onTyped?: (text: string) => void;
  /** Print (ou outro arquivo) colado com ⌘V no terminal: vira anexo. */
  onPasteFiles?: (files: File[]) => void;
  /** Leva o foco para a barra de baixo. */
  onFocusInput?: () => void;
  onFocus: () => void;
  onHide?: () => void;
  /** Canto de cima à direita, sobre o terminal: o mini-mapa do Brain (v0.8). */
  corner?: ReactNode;
  /**
   * Agente que saiu (v0.9.2): reinicia na mesma pasta e conta, do zero ou continuando a
   * conversa. A sessão nova toma o lugar desta na tela; o erro (409: conversa não achada) sobe.
   */
  onRestart?: (continuar: boolean) => Promise<void>;
  /** Passa o trabalho para a outra CLI (Claude ↔ Codex); esta sessão continua aberta. */
  onHandOff?: (nota: string) => Promise<void>;
  /** v0.9.8: a conta deste terminal passou de 80% na janela de 5 h e a outra CLI tem folga. */
  quotaHint?: string | null;
  /** Fecha a sessão (o mesmo × da aba). */
  onClose?: () => void;
  /** Abre "Retomar uma conversa" (quando a conversa desta não é achada). */
  onHistory?: () => void;
  /** v0.9.9: a barra de entrada do painel (agentes). */
  footer?: React.ReactNode;
}

const errorText = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export function TerminalView({
  session,
  client,
  theme,
  font = DEFAULT_APPEARANCE,
  slot,
  focused,
  tiled,
  box,
  colors,
  searchSignal,
  accountName,
  badge,
  place,
  dropping,
  onLink,
  onFocus,
  onHide,
  corner,
  readOnly = false,
  onTyped,
  onPasteFiles,
  onFocusInput,
  onRestart,
  onHandOff,
  quotaHint,
  onClose,
  onHistory,
  footer,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fitter = useRef<FitAddon | null>(null);
  const searcher = useRef<SearchAddon | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const socket = useRef<WebSocket | null>(null);
  const focusRef = useRef(onFocus);
  focusRef.current = onFocus;
  const linkRef = useRef(onLink);
  linkRef.current = onLink;
  const live = useRef({ readOnly, onTyped, onPasteFiles, onFocusInput });
  live.current = { readOnly, onTyped, onPasteFiles, onFocusInput };
  /** Caixa vazia do Claude coberta: a partir de que linha, e o status que estava abaixo dela. */
  const [cover, setCover] = useState<{ top: number; rows: number; status: string } | null>(null);

  const sendInput = (data: string) => {
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ type: "input", data }));
    }
  };

  const sendResize = () => {
    const t = term.current;
    if (t && socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ type: "resize", cols: t.cols, rows: t.rows }));
    }
  };

  const fit = () => {
    const el = host.current;
    if (!el || !fitter.current || el.clientWidth < 40 || el.clientHeight < 40) return;
    fitter.current.fit();
    sendResize();
    // Altura de uma linha, para o véu da caixa de entrada começar no lugar certo.
    const screen = el.querySelector(".xterm-screen") as HTMLElement | null;
    const rows = term.current?.rows ?? 0;
    if (screen && rows) el.style.setProperty("--cell-h", `${screen.clientHeight / rows}px`);
  };

  // Um xterm por sessão, montado uma vez e só escondido quando não aparece.
  useEffect(() => {
    let disposed = false;
    const terminal = new Terminal({
      fontFamily: monoFamily(font),
      fontSize: font.termSize,
      lineHeight: 1.15,
      cursorBlink: true,
      scrollback: 5000,
      macOptionIsMeta: true,
      theme: terminalTheme(theme, colors),
      // A busca acende os achados com decorações (e conta quantos são).
      allowProposedApi: true,
    });
    const addon = new FitAddon();
    terminal.loadAddon(addon);
    const search = new SearchAddon();
    terminal.loadAddon(search);
    searcher.current = search;
    // OSC 52 (v0.9.8): o programa no terminal (tmux, nvim, um agente) copia para a área de transferência do Mac.
    terminal.loadAddon(new ClipboardAddon(undefined, COPY_ONLY_CLIPBOARD));
    terminal.loadAddon(
      new WebLinksAddon((event, uri) => {
        if (event.metaKey) linkRef.current?.(uri, event.shiftKey);
      }),
    );
    term.current = terminal;
    fitter.current = addon;

    // Só leitura: letra e número vão para a barra; teclas de menu seguem para o agente.
    const PASS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape", "Tab", "PageUp", "PageDown", "Home", "End"]);
    terminal.attachCustomKeyEventHandler((event) => {
      const { readOnly: locked, onTyped: typed, onFocusInput: toInput } = live.current;
      if (!locked) return true;
      if (event.metaKey) return true; // ⌘C copia; os atalhos da MÊTIS são da janela
      if (event.ctrlKey) return ["c", "d", "o", "r", "t"].includes(event.key.toLowerCase());
      if (PASS.has(event.key)) return true;
      if (event.type === "keydown") {
        if (event.key.length === 1 && !event.altKey) typed?.(event.key);
        else if (event.key === "Backspace") toInput?.();
        event.preventDefault();
      }
      return false;
    });

    // Caixa de entrada vazia do Claude: some atrás de um véu, conferida a cada desenho.
    let frame = 0;
    const scan = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!live.current.readOnly) return setCover(null);
        const found = findInputBox(terminal);
        setCover((last) => {
          const next = found ? { top: found.top, rows: terminal.rows, status: found.status } : null;
          if (!next && !last) return last;
          if (next && last && next.top === last.top && next.rows === last.rows && next.status === last.status) return last;
          return next;
        });
      });
    };
    const drawn = terminal.onRender(scan);
    const scrolled = terminal.onScroll(scan);

    const input = terminal.onData(sendInput);
    const observer = new ResizeObserver(() => fit());
    terminals.set(session.id, {
      paste: (text) => terminal.paste(text),
      send: sendInput,
      // Num terminal só para ler, "focar" é ir para a barra de baixo.
      focus: () => (live.current.readOnly && live.current.onFocusInput ? live.current.onFocusInput() : terminal.focus()),
      focusTerminal: () => terminal.focus(),
    });

    (async () => {
      await document.fonts.load(`${font.termSize}px ${monoFamily(font)}`).catch(() => undefined);
      if (disposed || !host.current) return;
      terminal.open(host.current);
      terminal.textarea?.addEventListener("focus", () => focusRef.current());
      // Colar no terminal só para ler: o texto vai para a barra. Um print colado (em qualquer
      // terminal) vira anexo; no shell, o xterm sozinho não faria nada com ele.
      terminal.textarea?.addEventListener(
        "paste",
        (event) => {
          const files = pastedFiles(event.clipboardData);
          if (files.length && live.current.onPasteFiles) {
            event.preventDefault();
            event.stopImmediatePropagation();
            live.current.onPasteFiles(files);
            return;
          }
          if (!live.current.readOnly) return;
          event.preventDefault();
          event.stopImmediatePropagation();
          const text = event.clipboardData?.getData("text/plain") ?? "";
          if (text) live.current.onTyped?.(text);
        },
        true,
      );
      observer.observe(host.current);
      fit();
      const ws = new WebSocket(client.wsUrl(`/sessions/${session.id}/pty`));
      ws.binaryType = "arraybuffer";
      ws.onopen = () => sendResize();
      ws.onmessage = (message) => {
        if (typeof message.data === "string") {
          const control = JSON.parse(message.data);
          if (control.type === "exit") {
            const code = control.code == null ? "" : ` · código ${control.code}`;
            terminal.write(`\r\n\x1b[2m[sessão encerrada${code}]\x1b[0m\r\n`);
          }
          return;
        }
        terminal.write(new Uint8Array(message.data as ArrayBuffer));
      };
      socket.current = ws;
    })();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      terminals.delete(session.id);
      observer.disconnect();
      drawn.dispose();
      scrolled.dispose();
      input.dispose();
      socket.current?.close();
      socket.current = null;
      terminal.dispose();
      term.current = null;
      searcher.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id, client]);

  // Agente hibernado (v0.9.8) acorda quando o terminal dele ganha o foco.
  useEffect(() => {
    if (focused && slot !== "hidden" && session.hibernando) void client.wakeSession(session.id).catch(() => undefined);
  }, [focused, slot, session.hibernando, session.id, client]);

  useEffect(() => {
    if (!focused || slot === "hidden") return;
    const frame = requestAnimationFrame(() => {
      fit();
      if (live.current.readOnly && live.current.onFocusInput) live.current.onFocusInput();
      else term.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focused, slot]);

  useEffect(() => {
    if (term.current) term.current.options.theme = terminalTheme(theme, colors);
  }, [theme, colors]);

  // Fonte ou tamanho novos (Ajustes → Aparência): o xterm troca e o terminal recalcula as colunas.
  const family = monoFamily(font);
  useEffect(() => {
    const terminal = term.current;
    if (!terminal || (terminal.options.fontFamily === family && terminal.options.fontSize === font.termSize)) return;
    void document.fonts
      .load(`${font.termSize}px ${family}`)
      .catch(() => undefined)
      .then(() => {
        terminal.options.fontFamily = family;
        terminal.options.fontSize = font.termSize;
        fit();
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [family, font.termSize]);

  // ⌘F no terminal em foco abre a busca (o sinal sobe a cada ⌘F; se já aberta, só foca o campo).
  const lastSignal = useRef(searchSignal);
  useEffect(() => {
    if (searchSignal === lastSignal.current) return;
    lastSignal.current = searchSignal;
    if (searchSignal) setSearchOpen(true);
  }, [searchSignal]);

  const status = session.status;
  const agentKind = session.kind === "claude" || session.kind === "codex" ? session.kind : null;
  const other = agentKind === "claude" ? "codex" : "claude";
  return (
    <section
      className="pane"
      data-slot={slot}
      style={slot === "tile" ? box : undefined}
      data-focused={focused && (tiled || slot === "float") ? "true" : undefined}
      data-drop={session.id}
      hidden={slot === "hidden"}
      aria-label={`Terminal: ${session.title}`}
      onMouseDown={onFocus}
    >
      <div className="pane-head">
        {badge ?? <KindIcon kind={session.kind} />}
        <span className="pane-title">{session.title}</span>
        {accountName && (
          <span className="path-chip" title="Conta usada nesta sessão">
            {accountName}
          </span>
        )}
        <span className="path-chip" title={session.cwd}>
          {place ?? shortPath(session.statusline?.cwd ?? session.cwd)}
        </span>
        {session.ports.length > 0 && <span className="small mono">:{session.ports.join(" :")}</span>}
        {session.statusline?.model && <span className="small mono">{session.statusline.model}</span>}
        {cover?.status && (
          <span className="small mono pane-mode" title="Linha de status do agente (a caixa dele fica escondida: escreva na barra de baixo)">
            {cover.status}
          </span>
        )}
        {session.hibernando ? (
          <span className="pane-status hibernating" title="Pausado por estar parado há muito tempo (Ajustes → Agentes e avisos). Acorda ao focar ou escrever.">
            <span className="dot" />
            hibernando
          </span>
        ) : (
          <span className="pane-status" style={{ color: STATUS_COLOR[status] }}>
            <span className="dot" style={{ background: STATUS_COLOR[status] }} />
            {STATUS_LABEL[status]}
          </span>
        )}
        <SessionMenu client={client} session={session} />
        {agentKind && onHandOff && <HandOffButton other={other} onHandOff={onHandOff} hint={quotaHint ?? null} />}
        <button
          type="button"
          className="icon-btn"
          title="Buscar no terminal (⌘F)"
          aria-label="Buscar no terminal"
          aria-pressed={searchOpen}
          onClick={() => setSearchOpen((v) => !v)}
        >
          <Icon d={ICON.search} size={13} strokeWidth={2} />
        </button>
        {onHide && (
          <button type="button" className="icon-btn" title={slot === "float" ? "Esconder (⌃`)" : "Tirar da divisão (⌘⇧W)"} onClick={onHide}>
            <Icon d={ICON.close} size={13} strokeWidth={2} />
          </button>
        )}
      </div>
      {searchOpen && (
        <TerminalSearch
          addon={searcher.current}
          onClose={() => {
            setSearchOpen(false);
            searcher.current?.clearDecorations();
            if (live.current.readOnly && live.current.onFocusInput) live.current.onFocusInput();
            else term.current?.focus();
          }}
          signal={searchSignal}
        />
      )}
      <div
        className="term-host"
        ref={host}
        onMouseUp={() => {
          // Clique sem selecionar texto num terminal só para ler: volta para a barra.
          if (readOnly && !term.current?.hasSelection()) onFocusInput?.();
        }}
      >
        {corner}
        {cover && (
          <div className="term-cover" style={{ top: `calc(10px + ${cover.top} * var(--cell-h, 17px))` }} aria-hidden="true">
            <span>{footer ? "escreva na barra abaixo · ↑↓ ↵ esc vão para o agente" : "escreva na barra de baixo · ↑↓ ↵ esc vão para o agente"}</span>
          </div>
        )}
      </div>
      {agentKind && status === "exited" && onRestart && (
        <ExitStrip
          key={session.id}
          code={session.exit_code}
          // O Claude que saiu antes da primeira resposta não tem conversa para continuar.
          hasConversation={session.kind !== "claude" || !!session.statusline?.session_id}
          onRestart={onRestart}
          onClose={onClose}
          onHistory={onHistory}
        />
      )}
      {footer && status !== "exited" && <div className="pane-dock">{footer}</div>}
      {dropping && (
        <div className="drop-hint">
          <span>{footer ? "Solte para anexar à mensagem" : "Solte para colar o caminho neste terminal"}</span>
        </div>
      )}
    </section>
  );
}

/**
 * Faixa no pé do terminal quando o agente sai: reiniciar do zero ou continuar a conversa
 * (o Claude guarda o id dela; o Codex é achado pela pasta e pela hora). O 409 do núcleo
 * quer dizer que a conversa não foi achada: aí só resta reiniciar ou procurar no histórico.
 */
function ExitStrip({
  code,
  hasConversation,
  onRestart,
  onClose,
  onHistory,
}: {
  code: number | null;
  hasConversation: boolean;
  onRestart: (continuar: boolean) => Promise<void>;
  onClose?: () => void;
  onHistory?: () => void;
}) {
  const [busy, setBusy] = useState<"reiniciar" | "continuar" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lost, setLost] = useState(!hasConversation);

  const run = async (continuar: boolean) => {
    setBusy(continuar ? "continuar" : "reiniciar");
    setError(null);
    try {
      await onRestart(continuar);
    } catch (cause) {
      if (cause instanceof CoreError && cause.status === 409) {
        setLost(true);
        setError("Não achei a conversa desta sessão para continuar. Reinicie do zero ou procure no histórico.");
      } else {
        setError(errorText(cause));
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="exit-strip" role="status">
      <span className="exit-strip-text">
        <b>O agente saiu.</b>
        {code != null && code !== 0 && <span className="small mono"> código {code}</span>}
        {error && <span className="exit-strip-error">{error}</span>}
      </span>
      <button type="button" className="btn" disabled={!!busy} onClick={() => void run(false)}>
        {busy === "reiniciar" ? "Reiniciando…" : "Reiniciar"}
      </button>
      {lost ? (
        onHistory && (
          <button type="button" className="btn" onClick={onHistory}>
            Procurar no histórico…
          </button>
        )
      ) : (
        <button type="button" className="btn primary" disabled={!!busy} onClick={() => void run(true)}>
          {busy === "continuar" ? "Continuando…" : "Continuar a conversa"}
        </button>
      )}
      {onClose && (
        <button type="button" className="btn" disabled={!!busy} onClick={onClose}>
          Fechar
        </button>
      )}
    </div>
  );
}

/**
 * "Passar para o Codex/Claude": abre um campo pequeno para um recado opcional e cria a
 * sessão na outra CLI, com o registro da conversa e as últimas mensagens desta.
 */
function HandOffButton({ other, onHandOff, hint }: { other: "claude" | "codex"; onHandOff: (nota: string) => Promise<void>; hint: string | null }) {
  const [open, setOpen] = useState(false);
  const [nota, setNota] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!busy && box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", away);
    return () => window.removeEventListener("mousedown", away);
  }, [open, busy]);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await onHandOff(nota.trim());
      setOpen(false);
      setNota("");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="handoff" ref={box}>
      <button
        type="button"
        className="handoff-btn"
        aria-label={`Passar para o ${KIND_LABEL[other]}`}
        title={`Passar para o ${KIND_LABEL[other]}: sessão nova na mesma pasta, com a conversa desta (que continua aberta)`}
        aria-expanded={open}
        onClick={() => {
          setOpen((v) => !v);
          setError(null);
        }}
      >
        <Icon d={ICON.handoff} size={12} strokeWidth={2} />
        <KindIcon kind={other} />
        {hint && <span className="quota-hint">{hint} · passar para o {KIND_LABEL[other]}</span>}
      </button>
      {open && (
        <form
          className="handoff-pop"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy) void send();
          }}
          onKeyDown={(event) => {
            // As teclas aqui são do campo, não dos atalhos de terminal.
            event.stopPropagation();
            if (event.key === "Escape") setOpen(false);
          }}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <span className="setting-label">
            Passar para o {KIND_LABEL[other]}
            <span className="small">Abre o {KIND_LABEL[other]} nesta pasta com a conversa daqui. Esta sessão continua aberta.</span>
          </span>
          <input
            autoFocus
            value={nota}
            maxLength={2000}
            placeholder="Recado (opcional): o que ele deve fazer agora"
            onChange={(event) => setNota(event.target.value)}
          />
          {error && <div className="error-box">{error}</div>}
          <div className="form-buttons">
            <button type="submit" className="btn primary" disabled={busy}>
              {busy ? "Passando…" : "Passar"}
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => setOpen(false)}>
              Cancelar
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/**
 * Busca no terminal (⌘F): texto, maiúsculas e regex, com o número de achados.
 * Enter vai para o próximo, ⇧Enter para o anterior, Esc fecha (e apaga os destaques).
 * O que está no histórico de rolagem (5.000 linhas) também é buscado.
 */
function TerminalSearch({ addon, onClose, signal }: { addon: SearchAddon | null; onClose: () => void; signal?: number }) {
  const [query, setQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [regex, setRegex] = useState(false);
  const [result, setResult] = useState<{ index: number; count: number } | null>(null);
  const [bad, setBad] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, [signal]);

  useEffect(() => {
    if (!addon) return;
    const sub = addon.onDidChangeResults((r) => setResult({ index: r.resultIndex, count: r.resultCount }));
    return () => sub.dispose();
  }, [addon]);

  const options = (): ISearchOptions => {
    const css = getComputedStyle(document.documentElement);
    const acc = css.getPropertyValue("--acc").trim() || "#82a0ff";
    return {
      caseSensitive,
      regex,
      decorations: {
        matchBackground: "#7a6a2a",
        matchOverviewRuler: "#c9a227",
        activeMatchBackground: acc,
        activeMatchColorOverviewRuler: acc,
      },
    };
  };

  const find = (direction: "next" | "previous", incremental = false) => {
    if (!addon) return;
    if (!query) {
      addon.clearDecorations();
      setResult(null);
      return;
    }
    if (regex) {
      try {
        new RegExp(query);
      } catch {
        setBad(true);
        return;
      }
    }
    setBad(false);
    const found = direction === "next" ? addon.findNext(query, { ...options(), incremental }) : addon.findPrevious(query, options());
    if (!found) setResult({ index: -1, count: 0 });
  };

  // Cada letra busca de novo a partir do achado atual (incremental), como no navegador.
  useEffect(() => {
    find("next", true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, caseSensitive, regex]);

  const count = !query ? "" : bad ? "regex inválida" : !result || result.count === 0 ? "nada" : result.index < 0 ? `${result.count}+` : `${result.index + 1}/${result.count}`;

  return (
    <div
      className="term-search"
      role="search"
      onMouseDown={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        // As teclas aqui são do campo, não dos atalhos de terminal.
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        } else if (event.key === "Enter") {
          event.preventDefault();
          find(event.shiftKey ? "previous" : "next");
        }
      }}
    >
      <Icon d={ICON.search} size={13} strokeWidth={2} />
      <input
        ref={input}
        value={query}
        placeholder="Buscar no terminal"
        spellCheck={false}
        aria-label="Buscar no terminal"
        onChange={(event) => setQuery(event.target.value)}
      />
      <span className="small mono term-search-count" data-bad={bad || (query && result?.count === 0) ? "true" : undefined}>
        {count}
      </span>
      <button type="button" className="search-opt" aria-pressed={caseSensitive} title="Diferenciar maiúsculas" onClick={() => setCaseSensitive((v) => !v)}>
        Aa
      </button>
      <button type="button" className="search-opt mono" aria-pressed={regex} title="Expressão regular" onClick={() => setRegex((v) => !v)}>
        .*
      </button>
      <button type="button" className="icon-btn" title="Anterior (⇧↵)" aria-label="Achado anterior" onClick={() => find("previous")}>
        <Icon d="M6 15l6-6 6 6" size={13} strokeWidth={2} />
      </button>
      <button type="button" className="icon-btn" title="Próximo (↵)" aria-label="Próximo achado" onClick={() => find("next")}>
        <Icon d="M6 9l6 6 6-6" size={13} strokeWidth={2} />
      </button>
      <button type="button" className="icon-btn" title="Fechar (Esc)" aria-label="Fechar a busca" onClick={onClose}>
        <Icon d={ICON.close} size={12} strokeWidth={2} />
      </button>
    </div>
  );
}

/**
 * "⋯" do cabeçalho (v0.9.8): copiar o ID da conversa (para retomar em outro lugar), o
 * caminho do transcript, as últimas mensagens (para levar o contexto a outro agente) e a pasta.
 */
function SessionMenu({ client, session }: { client: CoreClient; session: Session }) {
  // Onde o menu abre: fixo na janela, porque o cabeçalho do painel corta o que passa dele.
  const [open, setOpen] = useState<{ top: number; right: number } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  // A conversa, buscada ao abrir o menu: no WKWebView a escrita na área de transferência só vale
  // dentro do clique, e um await de rede antes dela faz o clique "vencer" (a cópia é recusada).
  const [conversation, setConversation] = useState<SessionContext | "buscando" | "erro">("buscando");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(null);
    };
    const close = () => setOpen(null);
    window.addEventListener("mousedown", away);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("mousedown", away);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const agent = session.kind === "claude" || session.kind === "codex";

  const toggle = (button: HTMLButtonElement) => {
    if (open) return setOpen(null);
    const rect = button.getBoundingClientRect();
    setOpen({ top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) });
    if (!agent) return;
    setConversation("buscando");
    client.sessionContext(session.id).then(setConversation, () => setConversation("erro"));
  };

  useEffect(() => {
    if (!done) return;
    const timer = window.setTimeout(() => setDone(null), 1800);
    return () => window.clearTimeout(timer);
  }, [done]);

  // Sem await antes do writeText: a escrita sai ainda dentro do clique.
  const copy = (what: "id" | "transcript" | "texto" | "pasta") => {
    setOpen(null);
    if (what !== "pasta" && typeof conversation === "string") {
      setDone(conversation === "buscando" ? "ainda buscando a conversa; tente de novo" : "não deu para ler a conversa");
      return;
    }
    const context = typeof conversation === "string" ? null : conversation;
    const text = what === "pasta" ? session.cwd : what === "id" ? context?.id_conversa : what === "transcript" ? context?.transcript : context?.texto;
    if (!text) {
      setDone(what === "id" ? "sem conversa ainda" : what === "transcript" ? "sem transcript" : "nada para copiar");
      return;
    }
    try {
      navigator.clipboard.writeText(text).then(
        () => setDone("copiado"),
        () => setDone("não deu para copiar"),
      );
    } catch {
      setDone("não deu para copiar");
    }
  };

  return (
    <div className="session-menu" ref={box}>
      {done && <span className="small session-menu-done">{done}</span>}
      <button type="button" className="icon-btn" title="Copiar o ID, o transcript, o contexto ou a pasta" aria-label="Mais" aria-expanded={!!open} onClick={(event) => toggle(event.currentTarget)}>
        <span aria-hidden="true">⋯</span>
      </button>
      {open && (
        <div className="session-menu-pop" role="menu" style={{ top: open.top, right: open.right }} onMouseDown={(event) => event.stopPropagation()}>
          {agent && (
            <>
              <button type="button" role="menuitem" onClick={() => copy("id")}>
                Copiar o ID da conversa
              </button>
              <button type="button" role="menuitem" onClick={() => copy("transcript")}>
                Copiar o caminho do transcript
              </button>
              <button type="button" role="menuitem" onClick={() => copy("texto")}>
                Copiar as últimas mensagens
              </button>
            </>
          )}
          <button type="button" role="menuitem" onClick={() => copy("pasta")}>
            Copiar a pasta
          </button>
        </div>
      )}
    </div>
  );
}
