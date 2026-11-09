import { useEffect, useRef, useState } from "react";
import { themeLabel } from "../lib/appearance";
import { restartCore, windowAction } from "../lib/core";
import { ago } from "../lib/format";
import type { Notice, NoticeKind } from "../lib/inbox";
import { ICON, Icon, MetisMark } from "../icons";
import type { ThemeName, View } from "../types";


export function TitleBar({
  theme,
  onCycleTheme,
  onPalette,
  pomodoro,
  onPomodoro,
  bell,
}: {
  theme: ThemeName;
  onCycleTheme: () => void;
  onPalette: () => void;
  /** Relógio do Pomodoro quando está correndo (foco ou pausa). */
  pomodoro?: { label: string; phase: string } | null;
  onPomodoro?: () => void;
  /** Sino dos avisos (v0.9.2): o menu fica aberto pelo App, que esconde as páginas nativas por baixo. */
  bell?: BellProps;
}) {
  return (
    <header className="titlebar" data-tauri-drag-region>
      <div className="traffic">
        <button type="button" aria-label="Fechar janela" title="Fechar" onClick={() => windowAction("close")} />
        <button type="button" aria-label="Minimizar janela" title="Minimizar" onClick={() => windowAction("minimize")} />
        <button
          type="button"
          aria-label="Maximizar janela"
          title="Maximizar"
          onClick={() => windowAction("toggleMaximize")}
        />
      </div>
      <span className="name" data-tauri-drag-region>
        <MetisMark size={15} />
        MÊTIS
      </span>
      <button type="button" className="search" onClick={onPalette} title="Salto rápido (⌘K)">
        <Icon d={ICON.search} size={13} strokeWidth={2} />
        <span style={{ flex: 1, textAlign: "left" }}>Buscar ou pular para…</span>
        <span className="mono" style={{ fontSize: 11 }}>
          ⌘K
        </span>
      </button>
      {pomodoro && (
        <button type="button" className="chip pomodoro-chip" data-phase={pomodoro.phase} onClick={onPomodoro} title="Estudo">
          🍅 {pomodoro.label}
        </button>
      )}
      {bell && <Bell {...bell} />}
      <button type="button" className="chip" onClick={onCycleTheme} title="Trocar tema (mais opções em Ajustes)">
        tema: {themeLabel(theme)}
      </button>
      <span className="chip">v{__APP_VERSION__}</span>
    </header>
  );
}

interface BellProps {
  items: Notice[];
  unread: number;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  onPick: (notice: Notice) => void;
  onMarkAllRead: () => void;
  onClear: () => void;
}

const NOTICE_GLYPH: Record<NoticeKind, { glyph: string; color: string }> = {
  terminou: { glyph: "✓", color: "var(--run)" },
  espera: { glyph: "●", color: "var(--wait)" },
  aprovacao: { glyph: "?", color: "var(--warn)" },
  erro: { glyph: "!", color: "var(--err)" },
  versao: { glyph: "↑", color: "var(--acc)" },
};

/** Sino dos avisos: o número é o que falta ler; o menu lista os últimos 50. */
function Bell({ items, unread, open, onToggle, onClose, onPick, onMarkAllRead, onClear }: BellProps) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) onClose();
    };
    const esc = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", esc);
    };
  }, [open, onClose]);
  return (
    <div className="bell-wrap" ref={box}>
      <button
        type="button"
        className="icon-btn bell"
        aria-label={unread ? `Avisos: ${unread} sem ler` : "Avisos"}
        aria-expanded={open}
        title="Avisos dos agentes, aprovações e automações"
        onClick={onToggle}
      >
        <Icon d={ICON.bell} size={15} />
        {unread > 0 && <span className="bell-count mono">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="inbox-menu" role="menu" aria-label="Avisos">
          <header className="inbox-head">
            <span className="section-title">Avisos</span>
            <span className="grow" />
            {unread > 0 && (
              <button type="button" className="link-btn" onClick={onMarkAllRead}>
                marcar tudo como lido
              </button>
            )}
            {unread === 0 && items.length > 0 && (
              <button type="button" className="link-btn" onClick={onClear}>
                limpar
              </button>
            )}
          </header>
          {items.length === 0 ? (
            <p className="inbox-empty small">
              Nada por aqui. Quando um agente terminar, esperar você, pedir aprovação ou uma automação der erro, o aviso aparece aqui.
            </p>
          ) : (
            <ul className="inbox-list">
              {items.map((notice) => (
                <li key={notice.id}>
                  <button type="button" role="menuitem" className="inbox-item" data-unread={notice.lido ? undefined : "true"} onClick={() => onPick(notice)}>
                    <span className="inbox-glyph mono" style={{ color: NOTICE_GLYPH[notice.kind].color }} aria-hidden="true">
                      {NOTICE_GLYPH[notice.kind].glyph}
                    </span>
                    <span className="inbox-text">
                      <span className="inbox-title">{notice.titulo}</span>
                      {notice.texto && <span className="small">{notice.texto}</span>}
                    </span>
                    <span className="small mono inbox-time" title={new Date(notice.at).toLocaleString("pt-BR")}>
                      {ago(notice.at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Faixa sob a barra de título quando o núcleo em execução é de outra versão. Desde a v0.9.2,
 * fechar a janela não derruba o núcleo nem os agentes: a janela nova se liga ao que já está
 * no ar, que pode ser de antes de uma atualização. Reiniciar fecha os terminais.
 */
export function CoreVersionBanner({ core, open }: { core: string; open: number }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const restart = async () => {
    setBusy(true);
    setError(null);
    try {
      if (await restartCore()) window.location.reload();
      else setError("Fora do app não dá para reiniciar daqui: pare o núcleo e rode de novo pelo terminal.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const terminals = `${open} termina${open === 1 ? "l" : "is"}`;
  return (
    <div className="core-banner" role="status">
      <Icon d={ICON.info} size={14} />
      <span>
        O núcleo em execução é a <b className="mono">v{core}</b> e o app é a <b className="mono">v{__APP_VERSION__}</b>.
      </span>
      {confirming ? (
        <>
          <span className="core-banner-warn">
            Fecha {terminals} {open === 1 ? "aberto" : "abertos"}. Continuar?
          </span>
          <button type="button" className="btn danger" disabled={busy} onClick={() => void restart()}>
            {busy ? "Reiniciando…" : "Reiniciar agora"}
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(false)}>
            Cancelar
          </button>
        </>
      ) : (
        <>
          <button type="button" className="btn" disabled={busy} onClick={() => (open > 0 ? setConfirming(true) : void restart())}>
            {busy ? "Reiniciando…" : "Reiniciar o núcleo"}
          </button>
          <span className="small">{open > 0 ? `(fecha ${terminals})` : "(nenhum terminal aberto)"}</span>
        </>
      )}
      {error && <span className="core-banner-error">{error}</span>}
    </div>
  );
}

const NAV: { key: keyof typeof ICON; label: string; version: string }[] = [
  { key: "home", label: "Hoje", version: "v0.7" },
  { key: "term", label: "Terminais", version: "" },
  { key: "study", label: "Estudo", version: "v0.7" },
  { key: "graph", label: "Brain", version: "v0.5" },
  { key: "kanban", label: "Kanban", version: "v0.5" },
  { key: "canvas", label: "Quadros", version: "v0.9" },
  { key: "agents", label: "Agentes", version: "v0.7" },
  { key: "flow", label: "Automações", version: "v0.9" },
  { key: "plug", label: "Conectores", version: "v0.6" },
];

const READY: Partial<Record<keyof typeof ICON, View>> = { home: "today", term: "term", study: "study", graph: "brain", kanban: "kanban", canvas: "boards", agents: "agents", flow: "automations", plug: "connectors" };

/** Faixa de ícones. O que já existe abre a tela; o resto mostra a versão em que chega. */
export function Ribbon({ view, onView }: { view: View; onView: (view: View) => void }) {
  return (
    <nav className="ribbon" aria-label="Módulos">
      {NAV.map((item) => {
        const target = READY[item.key];
        return (
          <button
            key={item.key}
            type="button"
            aria-label={target ? item.label : `${item.label} (chega na ${item.version})`}
            title={target ? item.label : `${item.label} · chega na ${item.version}`}
            aria-current={target && view === target ? "page" : undefined}
            disabled={!target}
            onClick={() => target && onView(target)}
          >
            <Icon d={ICON[item.key]} />
          </button>
        );
      })}
      <button
        type="button"
        className="spacer"
        aria-label="Ajustes"
        title="Ajustes (⌘,)"
        aria-current={view === "settings" ? "page" : undefined}
        onClick={() => onView(view === "settings" ? "term" : "settings")}
      >
        <Icon d={ICON.gear} />
      </button>
    </nav>
  );
}
