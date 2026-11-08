import { useEffect, useRef, useState } from "react";
import { ICON, Icon } from "../icons";
import { browser, normalizeUrl, openExternal, type Rect } from "../lib/browser";

export interface WebInfo {
  url: string;
  title: string | null;
  loading: boolean;
  design: boolean;
}

interface Props {
  label: string;
  initialUrl: string;
  incognito: boolean;
  info: WebInfo | undefined;
  /** Na tela e sem nada por cima (salto rápido, diálogo, terminal flutuante). */
  shown: boolean;
  slot: "left" | "right" | "hidden";
  focused: boolean;
  focusUrlSignal: number;
  onFocus: () => void;
  onDesign: (on: boolean) => void;
  onError: (message: string) => void;
}

const native = browser.available();

/**
 * Aba de navegador. No app, a página é um WebKit nativo posicionado sobre a área
 * reservada aqui (o React só desenha a barra de endereço). No navegador de
 * desenvolvimento, vira um iframe, sem modo de design.
 */
export function BrowserView(props: Props) {
  const { label, info, shown } = props;
  const area = useRef<HTMLDivElement>(null);
  const address = useRef<HTMLInputElement>(null);
  const created = useRef(false);
  const lastRect = useRef("");
  const [typed, setTyped] = useState<string | null>(null);
  const url = info?.url ?? props.initialUrl;

  const rect = (): Rect | null => {
    const el = area.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    return { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) };
  };

  // Cria a página nativa na primeira vez que a aba aparece; depois só mostra, esconde e reposiciona.
  useEffect(() => {
    if (!native) return;
    let frame = 0;
    let alive = true;
    const sync = async () => {
      if (!alive) return;
      const r = rect();
      if (shown && r) {
        const key = `${r.x},${r.y},${r.width},${r.height}`;
        try {
          if (!created.current) {
            created.current = true;
            await browser.open(label, normalizeUrl(props.initialUrl), r, props.incognito);
            lastRect.current = key;
          } else if (key !== lastRect.current) {
            lastRect.current = key;
            await browser.bounds(label, r);
          }
        } catch (cause) {
          props.onError(cause instanceof Error ? cause.message : String(cause));
        }
      }
      frame = requestAnimationFrame(() => void sync());
    };
    if (shown) {
      if (created.current) void browser.visible(label, true).catch(() => undefined);
      void sync();
    } else if (created.current) {
      void browser.visible(label, false).catch(() => undefined);
    }
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, label]);

  // Fechar a aba fecha a página nativa.
  useEffect(
    () => () => {
      if (native && created.current) void browser.close(label).catch(() => undefined);
    },
    [label],
  );

  useEffect(() => {
    if (props.focusUrlSignal && props.focused) {
      address.current?.focus();
      address.current?.select();
    }
  }, [props.focusUrlSignal, props.focused]);

  const go = (target: string) => {
    const next = normalizeUrl(target);
    setTyped(null);
    if (native) void browser.navigate(label, next).catch((cause) => props.onError(String(cause)));
    else if (area.current) area.current.querySelector("iframe")?.setAttribute("src", next);
  };

  const action = (name: "back" | "forward" | "reload" | "devtools") => {
    if (native) void browser.go(label, name).catch((cause) => props.onError(String(cause)));
  };

  return (
    <section
      className="pane web-pane"
      data-slot={props.slot}
      data-focused={props.focused ? "true" : undefined}
      hidden={props.slot === "hidden"}
      onMouseDown={props.onFocus}
      aria-label={`Navegador: ${info?.title || url}`}
    >
      <div className="web-bar">
        <button type="button" className="icon-btn" title="Voltar (⌘[)" aria-label="Voltar" onClick={() => action("back")} disabled={!native}>
          <Icon d="M15 6l-6 6 6 6" size={15} strokeWidth={2} />
        </button>
        <button type="button" className="icon-btn" title="Avançar (⌘])" aria-label="Avançar" onClick={() => action("forward")} disabled={!native}>
          <Icon d={ICON.chevron} size={15} strokeWidth={2} />
        </button>
        <button type="button" className="icon-btn" title="Recarregar (⌘R)" aria-label="Recarregar" onClick={() => action("reload")}>
          <Icon d={ICON.refresh} size={14} />
        </button>
        <form
          className="web-address"
          onSubmit={(event) => {
            event.preventDefault();
            go(typed ?? url);
          }}
        >
          {props.incognito && <span className="chip">anônima</span>}
          {info?.loading && <span className="rec-dot web-loading" aria-label="carregando" />}
          <input
            ref={address}
            value={typed ?? (url === "about:blank" ? "" : url)}
            placeholder="Endereço ou busca (⌘L)"
            spellCheck={false}
            onChange={(event) => setTyped(event.target.value)}
            onFocus={(event) => event.target.select()}
            onBlur={() => setTyped(null)}
            onKeyDown={(event) => event.key === "Escape" && (event.target as HTMLInputElement).blur()}
          />
        </form>
        <button
          type="button"
          className="btn design-toggle"
          aria-pressed={!!info?.design}
          title={native ? "Modo de design: clique num elemento e ele vai para o agente (Esc sai)" : "Modo de design só no app"}
          aria-label="Modo de design"
          disabled={!native}
          onClick={() => props.onDesign(!info?.design)}
        >
          <Icon d="M4 4l7 16 2.5-6.5L20 11z" size={14} strokeWidth={1.9} />
          <span>Design</span>
        </button>
        <button type="button" className="icon-btn" title="Inspetor (devtools)" aria-label="Abrir o inspetor" onClick={() => action("devtools")} disabled={!native}>
          <Icon d="M8 9l-4 3 4 3M16 9l4 3-4 3M13.5 6l-3 12" size={15} strokeWidth={1.9} />
        </button>
        <button type="button" className="icon-btn" title="Abrir no navegador do Mac" aria-label="Abrir no navegador do Mac" onClick={() => void openExternal(normalizeUrl(url))}>
          <Icon d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" size={14} strokeWidth={1.9} />
        </button>
      </div>
      {info?.design && (
        <div className="design-banner">
          Modo de design: passe o mouse e clique num elemento para mandar ao agente. <kbd>Esc</kbd> sai.
        </div>
      )}
      <div className="web-area" ref={area}>
        {!native && <iframe className="frame" src={normalizeUrl(props.initialUrl)} title={info?.title ?? url} />}
        {native && url === "about:blank" && (
          <div className="web-blank small">Digite um endereço acima. As portas abertas pelos seus terminais aparecem no painel Portas.</div>
        )}
      </div>
    </section>
  );
}
