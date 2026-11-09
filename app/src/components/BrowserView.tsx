import { useEffect, useRef, useState, type CSSProperties } from "react";
import { ICON, Icon } from "../icons";
import { appZoom, browser, DEVICES, normalizeUrl, openExternal, type Rect } from "../lib/browser";
import type { BrowserProfile } from "../types";

export interface WebInfo {
  url: string;
  title: string | null;
  loading: boolean;
  design: boolean;
  /** v0.9.8: aparelho emulado ("" = tela inteira). */
  device?: string;
  /** Última ação do agente nesta aba (o chip "agente" fica aceso uns segundos). */
  agentAt?: number;
}

/** Fechamentos em andamento: reabrir a mesma aba com outro perfil espera o fechamento terminar. */
const closing = new Map<string, Promise<void>>();

interface Props {
  label: string;
  initialUrl: string;
  incognito: boolean;
  info: WebInfo | undefined;
  /** Perfil da aba (v0.9.8): o cofre de cookies dela. */
  profileId: string;
  profiles: BrowserProfile[];
  /** O agente usou a aba: a página nativa existe mesmo escondida. */
  keepAlive: boolean;
  onProfile: (id: string) => void;
  onDevice: (id: string) => void;
  /** Na tela e sem nada por cima (salto rápido, diálogo, terminal flutuante). */
  shown: boolean;
  slot: "tile" | "hidden";
  /** Posição do painel na divisão (v0.9.3). */
  box?: CSSProperties;
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
  const { label, info } = props;
  const area = useRef<HTMLDivElement>(null);
  const address = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState<string | null>(null);
  const url = info?.url ?? props.initialUrl;

  // O laço de sincronia lê sempre o valor atual, sem depender de quando o efeito rodou.
  const live = useRef(props);
  live.current = props;

  const rect = (): Rect | null => {
    const el = area.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    return { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) };
  };

  /** Onde a página fica e com que zoom: a área inteira, ou o aparelho emulado no centro
   *  (encolhido, com o zoom da página, quando não cabe no painel). */
  const geometry = (): { rect: Rect; zoom: number } | null => {
    const r = rect();
    if (!r) return null;
    const device = DEVICES.find((d) => d.id === (live.current.info?.device ?? ""));
    if (!device || !device.w) return { rect: r, zoom: 1 };
    const z = appZoom.get();
    const scale = Math.min(1, (r.width * z) / device.w, (r.height * z) / device.h);
    const width = Math.round((device.w * scale) / z);
    const height = Math.round((device.h * scale) / z);
    return { rect: { x: r.x + Math.round((r.width - width) / 2), y: r.y, width, height }, zoom: Math.round(scale * 1000) / 1000 };
  };

  // A página nativa é desenhada por cima da interface e não sabe do layout do React. Um laço
  // por quadro cria a página quando a aba aparece, mostra ou esconde e a põe sobre .web-area.
  // Uma chamada nativa por vez: nada de reposicionar uma página que ainda está nascendo.
  // A posição só conta como aplicada depois que a chamada deu certo, e é reaplicada a cada
  // segundo e quando a janela volta ao foco ou muda de tamanho, para a página nunca ficar
  // presa num lugar velho (ela chegou a cobrir a janela inteira).
  useEffect(() => {
    if (!native) return;
    let alive = true;
    let frame = 0;
    const s = { created: false, opening: false, busy: false, visible: true, applied: "", stale: true, warned: "", zoom: 1, last: null as Rect | null };
    const profile = live.current.profiles.find((p) => p.id === live.current.profileId)?.identificador ?? null;
    const fail = (cause: unknown) => {
      const message = cause instanceof Error ? cause.message : String(cause);
      if (message.includes("não existe")) {
        // A página sumiu (recarga do código, por exemplo): nasce de novo no próximo quadro.
        s.created = false;
        s.applied = "";
        return;
      }
      if (s.warned !== message) {
        s.warned = message;
        live.current.onError(message);
      }
    };
    const call = (run: () => Promise<void>, done: () => void, failed?: () => void) => {
      s.busy = true;
      run()
        .then(() => alive && done())
        .catch((cause) => {
          failed?.();
          if (alive) fail(cause);
        })
        .finally(() => {
          s.busy = false;
        });
    };
    const tick = () => {
      if (!alive) return;
      frame = requestAnimationFrame(tick);
      if (s.opening || s.busy) return;
      const want = live.current.shown;
      if (!s.created) {
        // Escondida, a página só nasce se o agente precisa dela (no último lugar, ou num
        // tamanho de tela comum, e logo some).
        const g = want ? geometry() : live.current.keepAlive ? { rect: s.last ?? { x: 0, y: 0, width: 1200, height: 800 }, zoom: 1 } : null;
        if (!g) return;
        s.opening = true;
        const device = DEVICES.find((d) => d.id === (live.current.info?.device ?? ""));
        (closing.get(label) ?? Promise.resolve())
          .then(() =>
            browser
              // Ao renascer, volta para a página em que estava, não para a inicial.
              .open(label, normalizeUrl(live.current.info?.url || live.current.initialUrl), g.rect, {
                incognito: live.current.incognito,
                profile,
                userAgent: device?.ua ?? null,
              }),
          )
          .then(() => {
            if (!alive) {
              void browser.close(label).catch(() => undefined);
              return;
            }
            s.created = true;
            s.visible = true;
            s.stale = true;
            s.warned = "";
            // Pedido de "Modo de design" feito antes de a página existir.
            if (live.current.info?.design) live.current.onDesign(true);
          })
          .catch((cause) => alive && fail(cause))
          .finally(() => {
            s.opening = false;
          });
        return;
      }
      if (s.visible !== want) {
        call(
          () => browser.visible(label, want),
          () => {
            s.visible = want;
            s.stale = true;
          },
        );
        return;
      }
      if (!want) return;
      const g = geometry();
      if (!g) return;
      const r = g.rect;
      s.last = r;
      if (g.zoom !== s.zoom) {
        call(
          () => browser.pageZoom(label, g.zoom),
          () => {
            s.zoom = g.zoom;
          },
        );
        return;
      }
      const key = `${r.x},${r.y},${r.width},${r.height}`;
      if (key === s.applied && !s.stale) return;
      s.stale = false;
      call(
        () => browser.bounds(label, r),
        () => {
          s.applied = key;
        },
        () => {
          s.applied = "";
        },
      );
    };
    const nudge = () => {
      s.stale = true;
    };
    window.addEventListener("resize", nudge);
    window.addEventListener("focus", nudge);
    document.addEventListener("visibilitychange", nudge);
    const timer = window.setInterval(nudge, 1000);
    tick();
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      window.clearInterval(timer);
      window.removeEventListener("resize", nudge);
      window.removeEventListener("focus", nudge);
      document.removeEventListener("visibilitychange", nudge);
      // Fechar a aba fecha a página nativa (se ainda estiver nascendo, o open fecha ao terminar).
      if (s.created) {
        const done = browser.close(label).catch(() => undefined);
        closing.set(label, done);
        void done.then(() => closing.get(label) === done && closing.delete(label));
      }
    };
    // Trocar de perfil fecha a página e abre outra, com o cofre do perfil novo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [label, props.profileId]);

  // Aparelho novo: o user agent dele e a página de novo (o tamanho o laço acima ajusta).
  const device = info?.device ?? "";
  const firstDevice = useRef(true);
  useEffect(() => {
    if (firstDevice.current) {
      firstDevice.current = false;
      return;
    }
    if (!native) return;
    const ua = DEVICES.find((d) => d.id === device)?.ua ?? null;
    void browser
      .userAgent(label, ua)
      .then(() => browser.go(label, "reload"))
      .catch(() => undefined);
  }, [device, label]);

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

  // O chip "agente" fica aceso 8 s depois da última ação dele.
  const [now, setNow] = useState(() => Date.now());
  const agentAt = info?.agentAt ?? 0;
  useEffect(() => {
    if (!agentAt) return;
    setNow(Date.now());
    const timer = window.setTimeout(() => setNow(Date.now()), 8100);
    return () => window.clearTimeout(timer);
  }, [agentAt]);
  const agentNow = agentAt > 0 && now - agentAt < 8000;

  const action = (name: "back" | "forward" | "reload" | "devtools") => {
    if (native) void browser.go(label, name).catch((cause) => props.onError(String(cause)));
  };

  return (
    <section
      className="pane web-pane"
      data-slot={props.slot}
      style={props.slot === "tile" ? props.box : undefined}
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
          {agentNow && (
            <span className="chip web-agent" title="O agente está usando esta aba pelo MCP">
              agente
            </span>
          )}
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
        {native && (
          <select
            className="web-select"
            value={device}
            title="Emular um aparelho (tamanho da tela e user agent)"
            aria-label="Aparelho emulado"
            onChange={(event) => props.onDevice(event.target.value)}
          >
            {DEVICES.map((d) => (
              <option key={d.id} value={d.id}>
                {d.id ? `${d.nome} · ${d.w}×${d.h}` : "Tela inteira"}
              </option>
            ))}
          </select>
        )}
        {native && !props.incognito && props.profiles.length > 1 && (
          <select
            className="web-select"
            value={props.profileId}
            title="Perfil: cada um tem os próprios cookies e logins"
            aria-label="Perfil do navegador"
            onChange={(event) => props.onProfile(event.target.value)}
          >
            {props.profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.nome}
              </option>
            ))}
          </select>
        )}
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
      <div className="web-area" ref={area} data-device={device || undefined}>
        {device && (
          <span className="web-device small">
            {DEVICES.find((d) => d.id === device)?.nome} · a página acha que a tela tem {DEVICES.find((d) => d.id === device)?.w} px
          </span>
        )}
        {!native && <iframe className="frame" src={normalizeUrl(props.initialUrl)} title={info?.title ?? url} />}
        {native && url === "about:blank" && (
          <div className="web-blank small">
            Digite um endereço acima. As portas abertas pelos seus terminais aparecem no painel Portas. Com a página aberta, o botão
            Design (ou ⌘K → Modo de design) manda o elemento clicado para o agente.
          </div>
        )}
      </div>
    </section>
  );
}
