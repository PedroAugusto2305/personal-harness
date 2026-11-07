import { useEffect, useRef, type ReactNode } from "react";
import { Terminal, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
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
  onFocus: () => void;
  onHide?: () => void;
}

export function TerminalView({ session, client, theme, slot, focused, split, accountName, badge, place, dropping, onFocus, onHide }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fitter = useRef<FitAddon | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const focusRef = useRef(onFocus);
  focusRef.current = onFocus;

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
    term.current = terminal;
    fitter.current = addon;

    const input = terminal.onData(sendInput);
    const observer = new ResizeObserver(() => fit());
    terminals.set(session.id, {
      paste: (text) => terminal.paste(text),
      send: sendInput,
      focus: () => terminal.focus(),
    });

    (async () => {
      await document.fonts.load('13px "Fira Code"');
      if (disposed || !host.current) return;
      terminal.open(host.current);
      terminal.textarea?.addEventListener("focus", () => focusRef.current());
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
      terminals.delete(session.id);
      observer.disconnect();
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
      term.current?.focus();
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
      <div className="term-host" ref={host} />
      {dropping && (
        <div className="drop-hint">
          <span>Solte para colar o caminho neste terminal</span>
        </div>
      )}
    </section>
  );
}
