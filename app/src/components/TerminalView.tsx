import { useEffect, useRef } from "react";
import { Terminal, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import type { CoreClient } from "../lib/core";
import { STATUS_COLOR, STATUS_LABEL, shortPath } from "../lib/format";
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

interface Props {
  session: Session;
  client: CoreClient;
  active: boolean;
  theme: ThemeName;
}

export function TerminalView({ session, client, active, theme }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fitter = useRef<FitAddon | null>(null);
  const socket = useRef<WebSocket | null>(null);

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

  // Um xterm por sessão, montado uma vez e só escondido quando a aba não está ativa.
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

    const input = terminal.onData((data) => {
      if (socket.current?.readyState === WebSocket.OPEN) {
        socket.current.send(JSON.stringify({ type: "input", data }));
      }
    });

    const observer = new ResizeObserver(() => fit());

    (async () => {
      await document.fonts.load('13px "Fira Code"');
      if (disposed || !host.current) return;
      terminal.open(host.current);
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
      if (active) terminal.focus();
    })();

    return () => {
      disposed = true;
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
    if (!active) return;
    const frame = requestAnimationFrame(() => {
      fit();
      term.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    if (term.current) term.current.options.theme = terminalTheme(theme);
  }, [theme]);

  const status = session.status;
  const isClaude = session.kind === "claude";
  return (
    <section className="pane" hidden={!active} aria-label={`Terminal: ${session.title}`}>
      <div className="pane-tabs">
        <div className="pane-tab">
          <span style={{ color: isClaude ? "#d97757" : "var(--tx)" }}>{isClaude ? "✻" : ">_"}</span>
          <span>{session.title}</span>
        </div>
        <span className="pane-status" style={{ color: STATUS_COLOR[status] }}>
          <span className="dot" style={{ background: STATUS_COLOR[status] }} />
          {STATUS_LABEL[status]}
        </span>
      </div>
      <div className="pane-head">
        <span style={{ fontWeight: 600 }}>{isClaude ? "Claude Code" : "Shell"}</span>
        <span className="path-chip">{shortPath(session.statusline?.cwd ?? session.cwd)}</span>
        {session.statusline?.model && <span className="small mono">{session.statusline.model}</span>}
      </div>
      <div className="term-host" ref={host} />
    </section>
  );
}
