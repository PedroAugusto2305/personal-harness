import { useEffect, useRef, useState } from "react";
import { MetisMark } from "../icons";
import { CoreClient, getCoreInfo, inTauri } from "../lib/core";

const ICON: Record<string, string> = { lembrete: "⏰", tarefa: "☑", nota: "✎", concierge: "✉" };

async function hideWindow() {
  if (!inTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().hide();
}

/**
 * Caixinha da captura rápida (⌥Espaço, de qualquer app). Lembrete, tarefa e anotação
 * acontecem na hora; o resto vai para o Hermes, o concierge, num terminal da MÊTIS.
 */
export function CaptureApp() {
  const [client, setClient] = useState<CoreClient | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ acao: string; mensagem: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;

  useEffect(() => {
    try {
      document.documentElement.dataset.theme = localStorage.getItem("harness.theme") || "dracula";
    } catch {
      document.documentElement.dataset.theme = "dracula";
    }
    let alive = true;
    void (async () => {
      try {
        const core = new CoreClient(await getCoreInfo());
        await core.waitUntilHealthy(20000);
        if (alive) setClient(core);
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : String(cause));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Toda vez que o ⌥Espaço abre a caixinha: limpa e foca.
  useEffect(() => {
    const reset = () => {
      setText("");
      setResult(null);
      setError(null);
      window.setTimeout(() => input.current?.focus(), 30);
    };
    reset();
    let stop: (() => void) | undefined;
    if (inTauri()) {
      void import("@tauri-apps/api/event").then(({ listen }) => listen("captura:abrir", reset).then((fn) => (stop = fn)));
    }
    // Clicou fora: a caixinha some, como o Spotlight.
    const onBlur = () => window.setTimeout(() => !busyRef.current && void hideWindow(), 120);
    window.addEventListener("blur", onBlur);
    return () => {
      stop?.();
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  const submit = async () => {
    const value = text.trim();
    if (!value || !client || busy) return;
    setBusy(true);
    setError(null);
    try {
      const done = await client.capture(value);
      setResult(done);
      setText("");
      window.setTimeout(() => void hideWindow(), 1800);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="capture">
      <div className="capture-row">
        <MetisMark size={18} />
        <input
          ref={input}
          value={text}
          autoFocus
          spellCheck={false}
          placeholder="Me lembra de… · tarefa… · anota… · ou peça ao Hermes"
          onChange={(event) => {
            setText(event.target.value);
            setResult(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") void submit();
            if (event.key === "Escape") void hideWindow();
          }}
          disabled={!client}
        />
        {busy && <span className="rec-dot" aria-label="mandando" />}
      </div>
      <div className="capture-foot small">
        {error ? (
          <span className="capture-error">{error}</span>
        ) : result ? (
          <span className="capture-done">
            {ICON[result.acao] ?? "✓"} {result.mensagem}
          </span>
        ) : !client ? (
          <span>Ligando na MÊTIS…</span>
        ) : (
          <span>
            <b>me lembra de</b> pagar o boleto sexta 9h · <b>tarefa</b> revisar o PR no Personal Harness · <b>anota</b> ideia · o resto vai para o{" "}
            <b>Hermes</b>
          </span>
        )}
        <span className="capture-keys mono">⏎ manda · esc fecha</span>
      </div>
    </div>
  );
}
