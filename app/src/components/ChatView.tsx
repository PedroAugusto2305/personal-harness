import { createContext, memo, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CoreClient } from "../lib/core";
import { applyMonacoTheme, loadMonaco } from "../lib/monaco";
import { themeIsLight } from "../lib/appearance";
import { pastedFiles } from "../lib/terminals";
import { KIND_LABEL } from "../lib/format";
import {
  groupItems,
  isLocalRef,
  lineDiff,
  markdownBlocks,
  mergeItems,
  monacoLanguage,
  patchRows,
  resolvePath,
  summarizeTools,
  type DiffRow,
} from "../lib/chat";
import { ICON, Icon } from "../icons";
import type { ChatImage, ChatItem, Session, ThemeName } from "../types";

/*
 * A conversa do agente (v1.2.0), no jeito do app do Codex: suas mensagens em balões à direita,
 * a resposta do agente em Markdown, as ferramentas em linhas compactas que abrem com o
 * resultado, o plano, os marcos do turno, e as imagens e os fluxogramas desenhados.
 *
 * Tudo vem do transcript que a CLI grava (o núcleo lê e manda só o que mudou). O terminal de
 * verdade continua no mesmo painel, logo atrás: é ele que roda o Claude e o Codex pelo plano, e
 * é por ele que passam os menus do agente.
 */

/** Primeira página e cada "carregar anteriores". */
const PAGE = 160;
/** Com o agente trabalhando, a conversa é conferida a cada 0,9 s; parado, a cada 2,5 s. */
const FAST_MS = 900;
const SLOW_MS = 2500;
/** Grupo de ferramentas a partir de quantas linhas fica fechado num resumo. */
const GROUP_COLLAPSE = 3;

interface Lightbox {
  url?: string;
  svg?: string;
  image?: ChatImage;
  title: string;
}

interface ChatContext {
  client: CoreClient;
  fonte: string;
  cwd: string;
  theme: ThemeName;
  openFile?: (path: string) => void;
  openLink: (url: string, external: boolean) => void;
  show: (box: Lightbox) => void;
  imageUrl: (image: ChatImage, version?: number) => string;
}

const Ctx = createContext<ChatContext | null>(null);
const useChat = () => useContext(Ctx)!;

interface Props {
  session: Session;
  client: CoreClient;
  theme: ThemeName;
  /** A conversa está na tela (o painel aparece e a vista é a conversa): só então ela pergunta ao núcleo. */
  visible: boolean;
  searchOpen: boolean;
  searchSignal?: number;
  onCloseSearch: () => void;
  onLink?: (url: string, external: boolean) => void;
  onOpenFile?: (path: string) => void;
  onFocusInput?: () => void;
  onShowTerminal: () => void;
  onPasteFiles?: (files: File[]) => void;
}

interface PageState {
  fonte: string;
  seq: number;
  inicio: number;
  items: ChatItem[];
  cwd: string;
  disponivel: boolean | null;
  motivo?: string;
}

const EMPTY: PageState = { fonte: "", seq: 0, inicio: 0, items: [], cwd: "", disponivel: null };

/** Grupos de ferramentas abertos ou fechados à mão, pelo id do primeiro item (sobrevive a remontar). */
const groupOpen = new Map<string, boolean>();

export function ChatView({ session, client, theme, visible, searchOpen, searchSignal, onCloseSearch, onLink, onOpenFile, onFocusInput, onShowTerminal, onPasteFiles }: Props) {
  const [page, setPage] = useState<PageState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [older, setOlder] = useState(false);
  const [box, setBox] = useState<Lightbox | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);
  const column = useRef<HTMLDivElement>(null);
  const pageRef = useRef(page);
  pageRef.current = page;
  const stick = useRef(true);
  const lastTop = useRef(0);
  const kick = useRef<() => void>(() => undefined);
  const anchor = useRef<{ height: number; top: number } | null>(null);

  const cwd = page.cwd || session.cwd;
  const working = session.status === "working";
  const workingRef = useRef(working);
  workingRef.current = working;

  // Pergunta ao núcleo o que mudou; com o agente trabalhando, mais vezes.
  useEffect(() => {
    if (!visible) return;
    let stopped = false;
    let timer = 0;
    let busy = false;
    const tick = async () => {
      if (busy || stopped) return;
      busy = true;
      window.clearTimeout(timer);
      const current = pageRef.current;
      try {
        const answer = await client.conversation(session.id, current.fonte ? { fonte: current.fonte, apos: current.seq } : { limite: PAGE });
        if (stopped) return;
        setError(null);
        setPage((last) => {
          if (!answer.disponivel) return { ...EMPTY, disponivel: false, motivo: answer.motivo, cwd: answer.cwd };
          if (answer.reset || answer.fonte !== last.fonte) {
            return { fonte: answer.fonte, seq: answer.seq, inicio: answer.inicio, items: answer.itens, cwd: answer.cwd, disponivel: true };
          }
          const gap = answer.itens.some((item) => item.n - last.inicio > last.items.length);
          if (gap) return { ...last, fonte: "", seq: 0 }; // perdeu um pedaço: a próxima volta pede tudo de novo
          if (!answer.itens.length && answer.seq === last.seq) return last;
          return { ...last, seq: answer.seq, items: mergeItems(last.items, last.inicio, answer.itens), cwd: answer.cwd };
        });
      } catch (cause) {
        if (!stopped) setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        busy = false;
        if (!stopped) timer = window.setTimeout(() => void tick(), document.hidden ? SLOW_MS * 2 : workingRef.current ? FAST_MS : SLOW_MS);
      }
    };
    kick.current = () => void tick();
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      kick.current = () => undefined;
    };
  }, [visible, session.id, client]);

  // Mudou o estado do agente (começou, terminou, pediu você) ou a conversa dele: confere na hora.
  useEffect(() => {
    kick.current();
  }, [session.status, session.atencao, session.statusline?.transcript]);

  const loadOlder = async () => {
    const current = pageRef.current;
    if (!current.fonte || current.inicio <= 0 || older) return;
    setOlder(true);
    try {
      const answer = await client.conversation(session.id, { fonte: current.fonte, antes: current.inicio, limite: PAGE });
      const el = scroller.current;
      if (el) anchor.current = { height: el.scrollHeight, top: el.scrollTop };
      setPage((last) =>
        answer.fonte !== last.fonte ? { ...last, fonte: "", seq: 0 } : { ...last, inicio: answer.inicio, items: [...answer.itens, ...last.items] },
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setOlder(false);
    }
  };

  // Mensagens antigas entram em cima sem a tela pular.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (anchor.current) {
      el.scrollTop = anchor.current.top + (el.scrollHeight - anchor.current.height);
      anchor.current = null;
    } else if (stick.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [page.items]);

  // Imagem ou diagrama que termina de carregar muda a altura: quem estava no fim continua no fim.
  useEffect(() => {
    const el = scroller.current;
    const col = column.current;
    if (!el || !col) return;
    const observer = new ResizeObserver(() => {
      if (stick.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(col);
    return () => observer.disconnect();
  }, []);

  // Voltou a aparecer (aba, divisão, terminal ↔ conversa): no fim, se estava no fim.
  useLayoutEffect(() => {
    if (visible && stick.current && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [visible]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    // Só você solta a conversa do fim, rolando para cima: imagem ou diagrama que cresce depois
    // também gera rolagem, e não pode tirar a tela do fim.
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 48) stick.current = true;
    else if (el.scrollTop < lastTop.current - 2) stick.current = false;
    lastTop.current = el.scrollTop;
    setAtBottom(stick.current);
    if (el.scrollTop < 120 && pageRef.current.inicio > 0) void loadOlder();
  };

  const toBottom = () => {
    const el = scroller.current;
    if (!el) return;
    stick.current = true;
    setAtBottom(true);
    el.scrollTop = el.scrollHeight;
  };

  const imageUrl = useCallback(
    (image: ChatImage, version?: number) => {
      const url = client.conversationImageUrl(pageRef.current.fonte, image);
      return image.arquivo && version ? `${url}&v=${version}` : url;
    },
    [client],
  );

  const context = useMemo<ChatContext>(
    () => ({
      client,
      fonte: page.fonte,
      cwd,
      theme,
      openFile: onOpenFile,
      openLink: (url, external) => onLink?.(url, external),
      show: setBox,
      imageUrl,
    }),
    [client, page.fonte, cwd, theme, onOpenFile, onLink, imageUrl],
  );

  const blocks = useMemo(() => groupItems(page.items), [page.items]);
  const lastPlan = useMemo(() => [...page.items].reverse().find((i) => i.tipo === "plano")?.id, [page.items]);
  const lastBlock = blocks.length ? blocks[blocks.length - 1] : null;

  const agent = KIND_LABEL[session.kind] ?? session.kind;

  return (
    <Ctx.Provider value={context}>
      <div
        className="chat"
        data-hidden={visible ? undefined : "true"}
        aria-hidden={!visible}
        aria-label={`Conversa com o ${agent}`}
        onMouseUp={(event) => {
          // Clique sem selecionar texto volta para a barra de baixo (é a única entrada).
          const target = event.target as Element;
          if (window.getSelection()?.toString() || target.closest("button, a, input, textarea, select, summary, .chat-box")) return;
          onFocusInput?.();
        }}
        onPaste={(event) => {
          const files = pastedFiles(event.clipboardData);
          if (files.length && onPasteFiles) {
            event.preventDefault();
            onPasteFiles(files);
          }
        }}
      >
        {searchOpen && <ChatSearch root={column} signal={searchSignal} onClose={onCloseSearch} items={page.items} />}
        <div className="chat-scroll" ref={scroller} onScroll={onScroll}>
          <div className="chat-col" ref={column}>
            {page.inicio > 0 && (
              <button type="button" className="chat-older" disabled={older} onClick={() => void loadOlder()}>
                {older ? "Carregando…" : `Carregar ${Math.min(PAGE, page.inicio)} anteriores`}
              </button>
            )}
            {page.disponivel === false && page.items.length === 0 && (
              <div className="chat-empty">
                <Icon d={ICON.chat} size={28} strokeWidth={1.5} />
                <b>Conversa com o {agent}</b>
                <span>
                  Escreva ou dite na barra abaixo. Imagens, fluxogramas, tabelas e código aparecem desenhados aqui.
                  <br />O {agent} roda no terminal de sempre, logo atrás desta tela: <kbd>⌘⇧T</kbd> alterna.
                </span>
              </div>
            )}
            {page.disponivel === null && !error && <div className="chat-loading">Lendo a conversa…</div>}
            {blocks.map((block) =>
              block.kind === "item" ? (
                <ItemView key={block.item.id} item={block.item} compactPlan={block.item.tipo === "plano" && block.item.id !== lastPlan} />
              ) : (
                <ToolGroup key={block.key} groupKey={block.key} items={block.items} live={working && block === lastBlock} />
              ),
            )}
            <StatusLine session={session} onShowTerminal={onShowTerminal} />
            {error && <div className="chat-error">Não deu para ler a conversa: {error}</div>}
          </div>
        </div>
        {!atBottom && (
          <button type="button" className="chat-bottom" onClick={toBottom} title="Ir para o fim da conversa">
            <Icon d={ICON.down} size={14} strokeWidth={2} />
          </button>
        )}
        {box && <LightboxView box={box} onClose={() => setBox(null)} />}
      </div>
    </Ctx.Provider>
  );
}

// --- itens -----------------------------------------------------------------------------------

const ItemView = memo(function ItemView({ item, compactPlan }: { item: ChatItem; compactPlan: boolean }) {
  switch (item.tipo) {
    case "voce":
      return <YouMessage item={item} />;
    case "agente":
      return <AgentMessage item={item} />;
    case "pensamento":
      return <ThinkingRow item={item} />;
    case "plano":
      return <PlanCard item={item} compact={compactPlan} />;
    case "evento":
      return <EventLine item={item} />;
    default:
      return <ToolRow item={item} />;
  }
});

function clock(iso?: string): string | undefined {
  if (!iso) return undefined;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? undefined : date.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function YouMessage({ item }: { item: ChatItem }) {
  return (
    <div className="msg-you" title={clock(item.hora)}>
      <div className="msg-you-bubble">
        {!!item.imagens?.length && <ImageStrip images={item.imagens} version={item.v} big />}
        {item.texto && <div className="msg-you-text">{item.texto}</div>}
      </div>
      {item.fila && <span className="msg-you-tag">entrou na fila enquanto o agente trabalhava</span>}
    </div>
  );
}

function AgentMessage({ item }: { item: ChatItem }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="msg-agent" title={clock(item.hora)}>
      <Markdown text={item.texto ?? ""} />
      {!!item.imagens?.length && <ImageStrip images={item.imagens} version={item.v} big />}
      <div className="msg-tools">
        <button
          type="button"
          className="chat-mini"
          onClick={() => {
            navigator.clipboard.writeText(item.texto ?? "").then(
              () => setCopied(true),
              () => undefined,
            );
            window.setTimeout(() => setCopied(false), 1400);
          }}
        >
          <Icon d={copied ? ICON.check : ICON.copy} size={12} strokeWidth={2} />
          {copied ? "Copiado" : "Copiar"}
        </button>
      </div>
    </div>
  );
}

function ThinkingRow({ item }: { item: ChatItem }) {
  const [open, setOpen] = useState(false);
  const first = (item.texto ?? "").split("\n").find((l) => l.trim()) ?? "";
  return (
    <div className="chat-think" data-open={open || undefined}>
      <button type="button" className="tool-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <Icon d={ICON.spark} size={13} strokeWidth={1.8} />
        <span className="tool-label">Pensou</span>
        {!open && <span className="tool-hint">{first.slice(0, 140)}</span>}
        <span className="tool-chevron"><Icon d={ICON.chevron} size={12} strokeWidth={2} /></span>
      </button>
      {open && (
        <div className="tool-body think-body">
          <Markdown text={item.texto ?? ""} />
        </div>
      )}
    </div>
  );
}

const CATEGORY_ICON: Record<string, string> = {
  comando: ICON.terminal,
  leitura: ICON.file,
  edicao: ICON.edit,
  busca: ICON.search,
  web: ICON.globe,
  mcp: ICON.plug,
  agente: ICON.agents,
  skill: ICON.spark,
  pergunta: ICON.info,
  plano: ICON.checklist,
  imagem: ICON.image,
  outra: ICON.code,
};

function ToolGroup({ groupKey, items, live }: { groupKey: string; items: ChatItem[]; live: boolean }) {
  const tools = items.filter((i) => i.tipo === "ferramenta");
  const [open, setOpenState] = useState(() => groupOpen.get(groupKey) ?? false);
  const setOpen = (value: boolean) => {
    groupOpen.set(groupKey, value);
    setOpenState(value);
  };
  const images = items.flatMap((i) => (i.imagens ?? []).map((image) => ({ image, v: i.v })));
  if (tools.length < GROUP_COLLAPSE) {
    return (
      <div className="tool-group flat">
        {items.map((item) => (item.tipo === "pensamento" ? <ThinkingRow key={item.id} item={item} /> : <ToolRow key={item.id} item={item} />))}
      </div>
    );
  }
  const running = tools.some((t) => t.estado === "rodando");
  const failed = tools.filter((t) => t.estado === "erro").length;
  // Com o agente trabalhando, o grupo do fim mostra as últimas linhas abertas.
  const shown = open ? items : live ? items.slice(-3) : [];
  return (
    <div className="tool-group" data-open={open || undefined}>
      <button type="button" className="tool-head chat-group-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        {running ? <span className="tool-spin" aria-label="rodando" /> : <Icon d={ICON.lines} size={13} strokeWidth={1.8} />}
        <span className="tool-label">
          {tools.length} ações <span className="tool-hint">· {summarizeTools(tools)}</span>
        </span>
        {failed > 0 && <span className="tool-fail">{failed} com erro</span>}
        <span className="tool-chevron"><Icon d={ICON.chevron} size={12} strokeWidth={2} /></span>
      </button>
      {!open && live && items.length > 3 && (
        <button type="button" className="tool-more" onClick={() => setOpen(true)}>
          + {items.length - 3} antes
        </button>
      )}
      {shown.map((item) => (item.tipo === "pensamento" ? <ThinkingRow key={item.id} item={item} /> : <ToolRow key={item.id} item={item} />))}
      {!open && !live && images.length > 0 && (
        <div className="tool-images">
          {images.slice(-8).map(({ image, v }, i) => (
            <Thumb key={`${image.ref ?? image.arquivo}-${i}`} image={image} version={v} />
          ))}
        </div>
      )}
    </div>
  );
}

function countDiff(rows: DiffRow[]): [number, number] {
  let add = 0;
  let del = 0;
  for (const row of rows) {
    if (row.kind === "add") add += 1;
    else if (row.kind === "del") del += 1;
  }
  return [add, del];
}

function ToolRow({ item }: { item: ChatItem }) {
  const { openFile } = useChat();
  const [open, setOpen] = useState(false);
  const diffRows = useMemo(() => {
    if (item.diff?.length) return item.diff.flatMap((d, i) => [...(i ? [{ kind: "same" as const, text: "⋯" }] : []), ...lineDiff(d.antes, d.depois)]);
    if (item.patch) return patchRows(item.patch);
    return null;
  }, [item.diff, item.patch]);
  const [add, del] = diffRows ? countDiff(diffRows) : [0, 0];
  const hasBody = !!(item.detalhe || item.saida || diffRows || item.arquivo);
  return (
    <div className="tool-row" data-state={item.estado} data-open={open || undefined}>
      <button type="button" className="tool-head" onClick={() => hasBody && setOpen((v) => !v)} aria-expanded={open} data-static={!hasBody || undefined}>
        {item.estado === "rodando" ? <span className="tool-spin" aria-label="rodando" /> : <Icon d={CATEGORY_ICON[item.categoria ?? "outra"] ?? ICON.code} size={13} strokeWidth={1.8} />}
        <span className="tool-label" data-mono={(item.categoria === "comando" && !!item.detalhe && item.detalhe.startsWith(item.rotulo ?? "\u0000")) || undefined}>
          {item.voce && <span className="tool-you">você</span>}
          {item.rotulo || item.nome}
        </span>
        {diffRows && (add > 0 || del > 0) && (
          <span className="tool-diffcount">
            <span className="add">+{add}</span> <span className="del">−{del}</span>
          </span>
        )}
        {item.estado === "erro" && <span className="tool-fail">{item.codigo != null && item.codigo !== 0 ? `código ${item.codigo}` : "erro"}</span>}
        {hasBody && <span className="tool-chevron"><Icon d={ICON.chevron} size={12} strokeWidth={2} /></span>}
      </button>
      {open && (
        <div className="tool-body">
          {item.arquivo && openFile && (
            <button type="button" className="chat-mini" onClick={() => openFile(item.arquivo!)}>
              <Icon d={ICON.file} size={12} strokeWidth={2} /> Abrir {item.arquivo.split("/").pop()}
            </button>
          )}
          {item.detalhe && !diffRows && (item.lingua === "markdown" ? <Markdown text={item.detalhe} /> : <CodeBlock lang={item.lingua ?? ""} text={item.detalhe} small />)}
          {diffRows && <DiffView rows={diffRows} />}
          {item.saida && (item.lingua === "markdown" && item.categoria === "web" ? <Markdown text={item.saida} /> : <pre className="tool-out">{item.saida}</pre>)}
        </div>
      )}
      {!!item.imagens?.length && <ImageStrip images={item.imagens} version={item.v} />}
    </div>
  );
}

function DiffView({ rows }: { rows: DiffRow[] }) {
  return (
    <pre className="chat-diff">
      {rows.map((row, i) => (
        <span key={i} className={`diff-${row.kind}`}>
          {row.kind === "add" ? "+ " : row.kind === "del" ? "- " : "  "}
          {row.text}
          {"\n"}
        </span>
      ))}
    </pre>
  );
}

function PlanCard({ item, compact }: { item: ChatItem; compact: boolean }) {
  const steps = item.passos ?? [];
  const done = steps.filter((s) => s.estado === "feito").length;
  if (compact) {
    return (
      <div className="chat-plan-line">
        <Icon d={ICON.checklist} size={13} strokeWidth={1.8} /> Plano atualizado · {done} de {steps.length} feitos
      </div>
    );
  }
  return (
    <div className="chat-plan">
      <div className="chat-plan-head">
        <Icon d={ICON.checklist} size={14} strokeWidth={1.8} />
        <b>Plano</b>
        <span className="small">
          {done} de {steps.length} feitos
        </span>
      </div>
      {item.texto && <div className="chat-plan-note">{item.texto}</div>}
      <ol>
        {steps.map((step, i) => (
          <li key={i} data-state={step.estado}>
            <span className="plan-mark" aria-hidden="true">
              {step.estado === "feito" ? <Icon d={ICON.check} size={11} strokeWidth={2.6} /> : null}
            </span>
            {step.texto}
          </li>
        ))}
      </ol>
    </div>
  );
}

function EventLine({ item }: { item: ChatItem }) {
  const [open, setOpen] = useState(false);
  if (item.evento === "duracao") return <div className="chat-turn-end">{item.texto}</div>;
  if (item.evento === "compactada") return <div className="chat-divider">{item.texto}</div>;
  if (item.evento === "interrompido") return <div className="chat-event interrupted">{item.texto}</div>;
  return (
    <div className="chat-event" data-kind={item.evento}>
      {item.detalhe ? (
        <button type="button" className="chat-event-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          <span className={item.evento === "comando" ? "mono" : undefined}>{item.texto}</span>
          <span className="tool-chevron"><Icon d={ICON.chevron} size={11} strokeWidth={2} /></span>
        </button>
      ) : (
        <span className={item.evento === "comando" ? "mono" : undefined}>{item.texto}</span>
      )}
      {open && item.detalhe && (item.evento === "resumo" ? <div className="chat-event-body"><Markdown text={item.detalhe} /></div> : <pre className="tool-out">{item.detalhe}</pre>)}
    </div>
  );
}

function StatusLine({ session, onShowTerminal }: { session: Session; onShowTerminal: () => void }) {
  const [, tick] = useState(0);
  const working = session.status === "working";
  useEffect(() => {
    if (!working) return;
    const timer = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [working]);
  if (session.hibernando) return <div className="chat-status">Hibernando · acorda quando você escrever</div>;
  if (session.status === "starting") return <div className="chat-status working">Abrindo o {KIND_LABEL[session.kind] ?? session.kind}…</div>;
  if (working) {
    const since = session.status_desde ? Math.max(0, Math.round(Date.now() / 1000 - session.status_desde)) : null;
    return (
      <div className="chat-status working">
        <span className="tool-spin" aria-hidden="true" />
        <span className="shine">Trabalhando</span>
        {since != null && <span className="small mono">{since < 60 ? `${since}s` : `${Math.floor(since / 60)}m ${String(since % 60).padStart(2, "0")}s`}</span>}
        <span className="small">· Esc na barra vazia interrompe</span>
      </div>
    );
  }
  if (session.status === "waiting" && session.atencao === "pergunta") {
    return (
      <div className="chat-ask">
        <b>O agente está esperando uma resposta sua.</b>
        <span>A pergunta ou o pedido de permissão está no terminal. Escolha com ↑↓ e ⏎ na barra vazia, ou veja o terminal.</span>
        <button type="button" className="btn" onClick={onShowTerminal}>
          Ver o terminal
        </button>
      </div>
    );
  }
  return null;
}

// --- conteúdo rico ------------------------------------------------------------------------------

const Markdown = memo(function Markdown({ text }: { text: string }) {
  const { cwd, imageUrl, openLink, openFile, show } = useChat();
  const blocks = useMemo(
    () =>
      markdownBlocks(text, (src) => {
        const path = resolvePath(src, cwd);
        return imageUrl({ arquivo: path });
      }),
    [text, cwd, imageUrl],
  );
  return (
    <div
      className="md chat-md"
      onClick={(event) => {
        const target = event.target as HTMLElement;
        const img = target.closest("img");
        if (img) {
          event.preventDefault();
          show({ url: img.getAttribute("src") ?? "", title: img.getAttribute("alt") || img.getAttribute("data-local") || "Imagem", image: img.getAttribute("data-local") ? { arquivo: resolvePath(img.getAttribute("data-local")!, cwd) } : undefined });
          return;
        }
        const link = target.closest("a");
        if (!link) return;
        event.preventDefault();
        const href = link.getAttribute("href") ?? "";
        if (/^https?:/i.test(href)) openLink(href, event.shiftKey);
        else if (isLocalRef(href) && openFile) openFile(resolvePath(href.split("#")[0], cwd));
      }}
    >
      {blocks.map((block, i) =>
        block.kind === "html" ? (
          <div key={i} className="md-chunk" dangerouslySetInnerHTML={{ __html: block.html }} />
        ) : block.kind === "mermaid" ? (
          <MermaidBlock key={i} text={block.text} />
        ) : (
          <CodeBlock key={i} lang={block.lang} text={block.text} />
        ),
      )}
    </div>
  );
});

let monacoTheme: string | null = null;

/** Código com a cor do Monaco (o mesmo do editor), em segundo plano: primeiro sai sem cor. */
async function colorize(text: string, lang: string, theme: ThemeName): Promise<string> {
  const monaco = await loadMonaco();
  if (monacoTheme !== theme) {
    monaco.editor.setTheme(applyMonacoTheme(monaco, theme));
    monacoTheme = theme;
  }
  return monaco.editor.colorize(text, monacoLanguage(lang) || "plaintext", { tabSize: 2 });
}

function CodeBlock({ lang, text, small = false }: { lang: string; text: string; small?: boolean }) {
  const { theme } = useChat();
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let alive = true;
    setHtml(null);
    if (!lang || text.length > 40_000) return;
    colorize(text.replace(/\n$/, ""), lang, theme).then(
      (out) => alive && setHtml(out),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [text, lang, theme]);
  return (
    <div className="chat-code" data-small={small || undefined}>
      {!small && (
        <div className="chat-code-head">
          <span className="mono">{lang || "texto"}</span>
          <button
            type="button"
            className="chat-mini"
            onClick={() => {
              navigator.clipboard.writeText(text).then(
                () => setCopied(true),
                () => undefined,
              );
              window.setTimeout(() => setCopied(false), 1400);
            }}
          >
            <Icon d={copied ? ICON.check : ICON.copy} size={12} strokeWidth={2} />
            {copied ? "Copiado" : "Copiar"}
          </button>
        </div>
      )}
      {html ? <pre className="chat-code-body" dangerouslySetInnerHTML={{ __html: html }} /> : <pre className="chat-code-body">{text.replace(/\n$/, "")}</pre>}
    </div>
  );
}

type MermaidApi = (typeof import("mermaid"))["default"];
let mermaidLoad: Promise<MermaidApi> | null = null;
let mermaidQueue: Promise<unknown> = Promise.resolve();
let mermaidCount = 0;

/** O Mermaid pesa: só carrega no primeiro diagrama. Um desenho por vez (ele guarda estado). */
function renderMermaid(text: string, theme: ThemeName): Promise<string> {
  mermaidLoad ??= import("mermaid").then((m) => m.default);
  const job = mermaidQueue.then(async () => {
    const mermaid = await mermaidLoad!;
    const css = getComputedStyle(document.documentElement);
    const token = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
    const light = themeIsLight(theme);
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      fontFamily: token("--ui-font", "Inter, system-ui, sans-serif"),
      themeVariables: {
        darkMode: !light,
        background: token("--bg", light ? "#ffffff" : "#282a36"),
        primaryColor: token("--elev", light ? "#eef0f6" : "#343746"),
        primaryTextColor: token("--tx", light ? "#1f2330" : "#f8f8f2"),
        primaryBorderColor: token("--acc", "#82a0ff"),
        secondaryColor: token("--side", light ? "#f4f5f9" : "#21222c"),
        tertiaryColor: token("--term", light ? "#ffffff" : "#1e1f29"),
        lineColor: token("--mut", "#a9aec9"),
        textColor: token("--tx", light ? "#1f2330" : "#f8f8f2"),
        noteBkgColor: token("--elev", "#343746"),
        noteTextColor: token("--tx", "#f8f8f2"),
        edgeLabelBackground: token("--bg", light ? "#ffffff" : "#282a36"),
        fontSize: "13px",
      },
    });
    const valid = await mermaid.parse(text, { suppressErrors: true });
    if (!valid) throw new Error("o diagrama tem um erro de sintaxe");
    mermaidCount += 1;
    const { svg } = await mermaid.render(`metis-mermaid-${mermaidCount}`, text);
    return svg;
  });
  mermaidQueue = job.catch(() => undefined);
  return job;
}

function MermaidBlock({ text }: { text: string }) {
  const { theme, show } = useChat();
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState(false);
  useEffect(() => {
    let alive = true;
    setError(null);
    renderMermaid(text, theme).then(
      (out) => alive && setSvg(out),
      (cause) => alive && setError(cause instanceof Error ? cause.message : String(cause)),
    );
    return () => {
      alive = false;
    };
  }, [text, theme]);
  return (
    <div className="chat-diagram">
      <div className="chat-code-head">
        <span>
          <Icon d={ICON.flow} size={12} strokeWidth={1.8} /> Diagrama
        </span>
        <span className="grow" />
        {svg && !code && (
          <button type="button" className="chat-mini" onClick={() => show({ svg, title: "Diagrama" })}>
            <Icon d={ICON.eye} size={12} strokeWidth={2} /> Ampliar
          </button>
        )}
        <button type="button" className="chat-mini" onClick={() => setCode((v) => !v)} aria-pressed={code}>
          <Icon d={ICON.code} size={12} strokeWidth={2} /> {code ? "Desenho" : "Código"}
        </button>
      </div>
      {error && !code && <div className="chat-diagram-error">Não deu para desenhar: {error}</div>}
      {code || error ? (
        <pre className="chat-code-body">{text}</pre>
      ) : svg ? (
        <button type="button" className="chat-diagram-svg" onClick={() => show({ svg, title: "Diagrama" })} dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="chat-loading">Desenhando o diagrama…</div>
      )}
    </div>
  );
}

function ImageStrip({ images, version, big = false }: { images: ChatImage[]; version?: number; big?: boolean }) {
  return (
    <div className="chat-images" data-big={big || undefined}>
      {images.map((image, i) => (
        <Thumb key={`${image.ref ?? image.arquivo}-${i}`} image={image} version={version} />
      ))}
    </div>
  );
}

function Thumb({ image, version }: { image: ChatImage; version?: number }) {
  const { imageUrl, show } = useChat();
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const url = imageUrl(image, version);
  useEffect(() => setState("loading"), [url]);
  if (state === "error") return image.ref ? <span className="chat-thumb-missing">imagem indisponível</span> : null;
  const name = image.nome ?? image.arquivo?.split("/").pop() ?? "Imagem";
  return (
    <button type="button" className="chat-thumb" data-state={state} title={image.arquivo ?? name} onClick={() => show({ url, image, title: name })}>
      <img src={url} alt={name} loading="lazy" onLoad={() => setState("ok")} onError={() => setState("error")} />
    </button>
  );
}

function LightboxView({ box, onClose }: { box: Lightbox; onClose: () => void }) {
  const { openFile, client } = useChat();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  const file = box.image?.arquivo;
  return (
    <div className="chat-box" role="dialog" aria-label={box.title} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="chat-box-bar">
        <span className="chat-box-title">{box.title}</span>
        {file && openFile && (
          <button type="button" className="chat-mini" onClick={() => openFile(file)}>
            <Icon d={ICON.file} size={12} strokeWidth={2} /> Abrir numa aba
          </button>
        )}
        {file && (
          <button type="button" className="chat-mini" onClick={() => void client.open({ reveal: file }).catch(() => undefined)}>
            <Icon d={ICON.folder} size={12} strokeWidth={2} /> Mostrar no Finder
          </button>
        )}
        <button type="button" className="icon-btn" onClick={onClose} title="Fechar (Esc)" aria-label="Fechar">
          <Icon d={ICON.close} size={14} strokeWidth={2} />
        </button>
      </div>
      <div className="chat-box-stage" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
        {box.svg ? <div className="chat-box-svg" dangerouslySetInnerHTML={{ __html: box.svg }} /> : <img src={box.url} alt={box.title} />}
      </div>
    </div>
  );
}

// --- busca (⌘F) --------------------------------------------------------------------------------

type HighlightApi = { highlights: Map<string, unknown> };
const highlightApi = (): HighlightApi | null => {
  const css = (globalThis as unknown as { CSS?: HighlightApi }).CSS;
  return css?.highlights && "Highlight" in globalThis ? css : null;
};
const makeHighlight = (ranges: Range[]) => new (globalThis as unknown as { Highlight: new (...r: Range[]) => unknown }).Highlight(...ranges);

/** Busca na conversa (⌘F): acende os achados com o Highlight do CSS, sem mexer no DOM. */
function ChatSearch({ root, signal, onClose, items }: { root: React.RefObject<HTMLDivElement | null>; signal?: number; onClose: () => void; items: ChatItem[] }) {
  const [query, setQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [ranges, setRanges] = useState<Range[]>([]);
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, [signal]);

  useEffect(() => {
    const el = root.current;
    if (!el || !query) {
      setRanges([]);
      return;
    }
    const found: Range[] = [];
    const needle = caseSensitive ? query : query.toLowerCase();
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node && found.length < 2000; node = walker.nextNode()) {
      const text = node.textContent ?? "";
      const hay = caseSensitive ? text : text.toLowerCase();
      for (let at = hay.indexOf(needle); at >= 0 && found.length < 2000; at = hay.indexOf(needle, at + needle.length)) {
        const range = document.createRange();
        range.setStart(node, at);
        range.setEnd(node, at + needle.length);
        found.push(range);
      }
    }
    setRanges(found);
    setIndex(found.length ? found.length - 1 : 0); // o mais recente primeiro, como quem lê de baixo
  }, [query, caseSensitive, items, root]);

  useEffect(() => {
    const api = highlightApi();
    if (api) {
      api.highlights.set("chat-busca", makeHighlight(ranges));
      api.highlights.set("chat-busca-atual", makeHighlight(ranges[index] ? [ranges[index]] : []));
    }
    ranges[index]?.startContainer.parentElement?.scrollIntoView({ block: "center" });
  }, [ranges, index]);

  useEffect(
    () => () => {
      const api = highlightApi();
      api?.highlights.delete("chat-busca");
      api?.highlights.delete("chat-busca-atual");
    },
    [],
  );

  const step = (delta: number) => ranges.length && setIndex((i) => (i + delta + ranges.length) % ranges.length);
  const count = !query ? "" : ranges.length ? `${index + 1}/${ranges.length}` : "nada";

  return (
    <div
      className="term-search chat-search"
      role="search"
      onMouseDown={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        } else if (event.key === "Enter") {
          event.preventDefault();
          step(event.shiftKey ? 1 : -1);
        }
      }}
    >
      <Icon d={ICON.search} size={13} strokeWidth={2} />
      <input ref={input} value={query} placeholder="Buscar na conversa" spellCheck={false} aria-label="Buscar na conversa" onChange={(event) => setQuery(event.target.value)} />
      <span className="small mono term-search-count" data-bad={query && !ranges.length ? "true" : undefined}>
        {count}
      </span>
      <button type="button" className="search-opt" aria-pressed={caseSensitive} title="Diferenciar maiúsculas" onClick={() => setCaseSensitive((v) => !v)}>
        Aa
      </button>
      <button type="button" className="icon-btn" title="Anterior (↵)" aria-label="Achado anterior" onClick={() => step(-1)}>
        <Icon d="M6 15l6-6 6 6" size={13} strokeWidth={2} />
      </button>
      <button type="button" className="icon-btn" title="Próximo (⇧↵)" aria-label="Próximo achado" onClick={() => step(1)}>
        <Icon d="M6 9l6 6 6-6" size={13} strokeWidth={2} />
      </button>
      <button type="button" className="icon-btn" title="Fechar (Esc)" aria-label="Fechar a busca" onClick={onClose}>
        <Icon d={ICON.close} size={12} strokeWidth={2} />
      </button>
    </div>
  );
}

