import { useEffect, useRef, useState, type ReactNode } from "react";
import { Terminal, type IBufferLine, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH, STATUS_COLOR, STATUS_LABEL, shortPath } from "../lib/format";
import { terminals } from "../lib/terminals";
import { ICON, Icon } from "../icons";
import type { Session, ThemeName } from "../types";

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

/** O tema do terminal sai dos mesmos tokens da interface. */
function terminalTheme(theme: ThemeName): ITheme {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string) => css.getPropertyValue(name).trim();
  return {
    background: token("--term"),
    foreground: token("--tx"),
    cursor: token("--acc"),
    cursorAccent: token("--term"),
    selectionBackground: token("--sel"),
    ...(theme === "claro" ? ANSI_LIGHT : ANSI_DARK),
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

/** Onde o terminal aparece. Todos ficam montados; só mudam de lugar ou somem. */
export type Slot = "left" | "right" | "float" | "hidden";

interface Props {
  session: Session;
  client: CoreClient;
  theme: ThemeName;
  slot: Slot;
  focused: boolean;
  split: boolean;
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
  /** Leva o foco para a barra de baixo. */
  onFocusInput?: () => void;
  onFocus: () => void;
  onHide?: () => void;
}

export function TerminalView({
  session,
  client,
  theme,
  slot,
  focused,
  split,
  accountName,
  badge,
  place,
  dropping,
  onLink,
  onFocus,
  onHide,
  readOnly = false,
  onTyped,
  onFocusInput,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fitter = useRef<FitAddon | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const focusRef = useRef(onFocus);
  focusRef.current = onFocus;
  const linkRef = useRef(onLink);
  linkRef.current = onLink;
  const live = useRef({ readOnly, onTyped, onFocusInput });
  live.current = { readOnly, onTyped, onFocusInput };
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
      fontFamily: '"Fira Code", ui-monospace, monospace',
      fontSize: 13,
      lineHeight: 1.15,
      cursorBlink: true,
      scrollback: 5000,
      macOptionIsMeta: true,
      theme: terminalTheme(theme),
    });
    const addon = new FitAddon();
    terminal.loadAddon(addon);
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
    });

    (async () => {
      await document.fonts.load('13px "Fira Code"');
      if (disposed || !host.current) return;
      terminal.open(host.current);
      terminal.textarea?.addEventListener("focus", () => focusRef.current());
      // Colar no terminal só para ler: o texto vai para a barra.
      terminal.textarea?.addEventListener(
        "paste",
        (event) => {
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
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id, client]);

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
    if (term.current) term.current.options.theme = terminalTheme(theme);
  }, [theme]);

  const status = session.status;
  return (
    <section
      className="pane"
      data-slot={slot}
      data-focused={focused && (split || slot === "float") ? "true" : undefined}
      data-drop={session.id}
      hidden={slot === "hidden"}
      aria-label={`Terminal: ${session.title}`}
      onMouseDown={onFocus}
    >
      <div className="pane-head">
        {badge ?? <span style={{ color: KIND_COLOR[session.kind] }}>{KIND_GLYPH[session.kind]}</span>}
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
        <span className="pane-status" style={{ color: STATUS_COLOR[status] }}>
          <span className="dot" style={{ background: STATUS_COLOR[status] }} />
          {STATUS_LABEL[status]}
        </span>
        {onHide && (
          <button type="button" className="icon-btn" title={slot === "float" ? "Esconder (⌃`)" : "Tirar da divisão"} onClick={onHide}>
            <Icon d={ICON.close} size={13} strokeWidth={2} />
          </button>
        )}
      </div>
      <div
        className="term-host"
        ref={host}
        onMouseUp={() => {
          // Clique sem selecionar texto num terminal só para ler: volta para a barra.
          if (readOnly && !term.current?.hasSelection()) onFocusInput?.();
        }}
      >
        {cover && (
          <div className="term-cover" style={{ top: `calc(10px + ${cover.top} * var(--cell-h, 17px))` }} aria-hidden="true">
            <span>escreva na barra de baixo · ↑↓ ↵ esc vão para o agente</span>
          </div>
        )}
      </div>
      {dropping && (
        <div className="drop-hint">
          <span>Solte para colar o caminho neste terminal</span>
        </div>
      )}
    </section>
  );
}
