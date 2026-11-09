// Os cartões do quadro, um por tipo de nó do JSON Canvas: nota do Brain (file), sessão e tarefa
// (text com %%metis), link, nota solta (text puro, em Markdown) e grupo (moldura atrás).

import { KindIcon } from "../KindIcon";
import { memo, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { ICON, Icon } from "../../icons";
import {
  type CardKind,
  type SessionMeta,
  type TaskMeta,
  colorOf,
  fileName,
  linkInfo,
  notePlace,
  parseMeta,
  TASK_STATE,
} from "../../lib/canvas";
import type { CoreClient } from "../../lib/core";
import { KIND_COLOR, STATUS_COLOR, STATUS_LABEL, shortPath } from "../../lib/format";
import { renderInline, renderNote, TYPE_ICON } from "../../lib/obsidian";
import type { Agent, BrainHit, CanvasNode, CanvasSide, KanbanTask, Session, SessionGlance } from "../../types";
import { AgentSprite, spriteState } from "../AgentSprite";

/** O que os cartões pedem para a tela (estável entre renders). */
export interface CardCtx {
  client: CoreClient | null;
  openNote: (path: string) => void;
  openNoteTitle: (title: string) => void;
  openTasks: (projeto: string) => void;
  openWeb: (url: string, design?: boolean) => void;
  openSession: (id: string) => void;
  reopen: (nodeId: string) => void;
  send: (sessionId: string, text: string) => Promise<boolean>;
  setText: (nodeId: string, text: string) => void;
  setLabel: (nodeId: string, label: string) => void;
  stopEditing: () => void;
}

export interface CardHandlers {
  down: (event: ReactPointerEvent, node: CanvasNode) => void;
  handle: (event: ReactPointerEvent, node: CanvasNode, side: CanvasSide) => void;
  resize: (event: ReactPointerEvent, node: CanvasNode) => void;
}

interface Props {
  node: CanvasNode;
  kind: CardKind;
  ctx: CardCtx;
  on: CardHandlers;
  selected: boolean;
  editing: boolean;
  dropTarget: boolean;
  /** A nota sendo arrastada por cima de uma sessão: fica translúcida para o alvo aparecer. */
  lifted: boolean;
  linkTarget: boolean;
  visible: boolean;
  hit?: BrainHit | null;
  session?: Session | null;
  agent?: Agent | null;
  task?: KanbanTask | null;
  tasksLoaded: boolean;
}

const SIDES: CanvasSide[] = ["top", "right", "bottom", "left"];

/** Clique em link dentro do Markdown: [[nota]] abre no Brain, http abre no navegador da MÊTIS. */
function linkClick(event: MouseEvent, ctx: CardCtx) {
  const a = (event.target as HTMLElement).closest("a");
  if (!a) return;
  event.preventDefault();
  if (a.classList.contains("wikilink") && a.dataset.note) ctx.openNoteTitle(a.dataset.note);
  else if (/^https?:/i.test(a.getAttribute("href") ?? "")) ctx.openWeb(a.getAttribute("href")!);
}

function sessionBorder(session: Session | null | undefined): string {
  if (session?.status === "waiting") return "var(--wait)";
  if (session?.status === "working") return "var(--run)";
  return "var(--line2)";
}

const DEFAULT_BORDER: Record<CardKind, string> = {
  nota: "var(--acc)",
  anexo: "var(--line2)",
  sessao: "var(--line2)",
  tarefa: "var(--line2)",
  link: "var(--line2)",
  sticky: "var(--wait)",
  grupo: "var(--line2)",
};

export const Card = memo(function Card(props: Props) {
  const { node, kind, ctx, on, selected, editing } = props;
  const tint = colorOf(node.color);
  const border = tint ?? (kind === "sessao" ? sessionBorder(props.session) : DEFAULT_BORDER[kind]);
  const missing = (kind === "nota" && props.hit === null) || (kind === "sessao" && !props.session) || (kind === "tarefa" && props.tasksLoaded && !props.task);
  const style = { left: node.x, top: node.y, width: node.width, height: node.height, ["--c" as string]: border };

  const handles = (
    <>
      {SIDES.map((side) => (
        <span key={side} className="bd-handle" data-side={side} title="Arraste até outro cartão para ligar" onPointerDown={(event) => on.handle(event, node, side)} />
      ))}
      <span className="bd-resize" title="Arraste para mudar o tamanho" onPointerDown={(event) => on.resize(event, node)} />
    </>
  );

  if (kind === "grupo") {
    return (
      <div
        className="bd-group"
        data-card-id={node.id}
        data-selected={selected ? "true" : undefined}
        data-link-target={props.linkTarget ? "true" : undefined}
        style={style}
        onPointerDown={(event) => on.down(event, node)}
      >
        <div className="bd-group-label">
          {editing ? (
            <input
              autoFocus
              value={node.label ?? ""}
              placeholder="Nome do grupo"
              aria-label="Nome do grupo"
              onChange={(event) => ctx.setLabel(node.id, event.target.value)}
              onFocus={(event) => event.currentTarget.select()}
              onBlur={ctx.stopEditing}
              onKeyDown={(event) => (event.key === "Enter" || event.key === "Escape") && ctx.stopEditing()}
            />
          ) : (
            <span title="Dois cliques para renomear">{node.label || "Grupo"}</span>
          )}
        </div>
        {handles}
      </div>
    );
  }

  return (
    <div
      className="bd-card"
      data-card-id={node.id}
      data-kind={kind}
      data-selected={selected ? "true" : undefined}
      data-drop={props.dropTarget ? "true" : undefined}
      data-lifted={props.lifted ? "true" : undefined}
      data-link-target={props.linkTarget ? "true" : undefined}
      data-missing={missing ? "true" : undefined}
      data-editing={editing ? "true" : undefined}
      style={style}
      onPointerDown={(event) => on.down(event, node)}
    >
      {kind === "nota" && <NoteBody node={node} hit={props.hit} ctx={ctx} />}
      {kind === "anexo" && <AttachmentBody node={node} />}
      {kind === "sessao" && <SessionBody node={node} session={props.session ?? null} agent={props.agent ?? null} visible={props.visible} ctx={ctx} />}
      {kind === "tarefa" && <TaskBody node={node} task={props.task ?? null} loaded={props.tasksLoaded} ctx={ctx} />}
      {kind === "link" && <LinkBody url={node.url ?? ""} ctx={ctx} />}
      {kind === "sticky" && <StickyBody node={node} editing={editing} ctx={ctx} />}
      {handles}
    </div>
  );
});

// --- nota do Brain ---------------------------------------------------------------------------------

function NoteBody({ node, hit, ctx }: { node: CanvasNode; hit: BrainHit | null | undefined; ctx: CardCtx }) {
  const file = node.file ?? "";
  if (!hit) {
    return (
      <div className="bd-note">
        <span className="bd-note-path">{notePlace(file)}</span>
        <span className="bd-note-title" data-plain="true">
          {fileName(file)}
        </span>
        <span className="bd-missing-note">{hit === null ? "nota não encontrada" : "lendo a nota…"}</span>
      </div>
    );
  }
  return (
    <div className="bd-note">
      <span className="bd-note-path">
        <span aria-hidden="true">{TYPE_ICON[hit.tipo] ?? "·"}</span> {notePlace(hit.path, hit.projeto)}
        {node.subpath ? <span className="mono"> {node.subpath}</span> : null}
      </span>
      <button type="button" className="bd-note-title" title="Abrir no Brain" onClick={() => ctx.openNote(hit.path)}>
        {hit.title}
      </button>
      {hit.resumo && <p className="bd-note-sum bd-scroll">{hit.resumo}</p>}
      <span className="bd-tags">
        {hit.tipo && <span className="bd-tag">#{hit.tipo}</span>}
        {hit.status && (
          <span className="bd-tag" data-status={hit.status}>
            {hit.status}
          </span>
        )}
      </span>
    </div>
  );
}

function AttachmentBody({ node }: { node: CanvasNode }) {
  const file = node.file ?? "";
  return (
    <div className="bd-note">
      <span className="bd-note-path">
        <Icon d={ICON.file} size={12} /> anexo do vault
      </span>
      <span className="bd-note-title" data-plain="true">
        {file.split("/").pop()}
      </span>
      <span className="bd-note-sum mono">{file}</span>
    </div>
  );
}

// --- sessão ---------------------------------------------------------------------------------------

function SessionBody({ node, session, agent, visible, ctx }: { node: CanvasNode; session: Session | null; agent: Agent | null; visible: boolean; ctx: CardCtx }) {
  const meta = parseMeta(node.text).meta as SessionMeta;
  const [glance, setGlance] = useState<SessionGlance | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const lines = useRef<HTMLDivElement>(null);
  const liveId = session?.id ?? null;
  const client = ctx.client;

  // Últimas linhas: a cada 4 s, só com o cartão à vista e a sessão existindo.
  useEffect(() => {
    if (!visible || !liveId || !client) return;
    let stop = false;
    const pull = () => {
      if (document.visibilityState !== "visible") return;
      client
        .sessionGlance(liveId)
        .then((g) => !stop && setGlance(g))
        .catch(() => undefined);
    };
    pull();
    const timer = window.setInterval(pull, 4000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [visible, liveId, client]);

  useEffect(() => {
    const el = lines.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [glance]);

  const status = session?.status ?? "exited";
  const alive = !!session && status !== "exited";
  const title = agent?.name ?? meta.titulo;
  const cwd = session?.cwd ?? meta.cwd;

  const send = async () => {
    const value = text.trim();
    if (!value || !session || sending) return;
    setSending(true);
    const ok = await ctx.send(session.id, value);
    setSending(false);
    if (ok) setText("");
  };

  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  };

  const messages = glance?.ultimas ?? [];
  const tail = glance?.linhas ?? [];

  return (
    <div className="bd-session">
      <header className="bd-session-head">
        <span className="bd-avatar">
          {agent ? (
            <AgentSprite agent={agent} client={client} size={28} state={session ? spriteState(session) : "sleeping"} />
          ) : (
            <span className="bd-glyph" style={{ color: KIND_COLOR[meta.kind] }}>
              <KindIcon kind={meta.kind} size={18} />
            </span>
          )}
        </span>
        <span className="bd-session-name">
          <b>{title}</b>
          <span className="mono" style={{ color: STATUS_COLOR[status] }}>
            <span className="dot" style={{ background: STATUS_COLOR[status] }} />
            {session ? STATUS_LABEL[status] : "encerrada"}
            {alive && glance?.context_pct != null && <span className="bd-ctx"> · {Math.round(glance.context_pct)}% do contexto</span>}
          </span>
        </span>
        {session && (
          <button type="button" className="bd-open" title="Abrir o terminal inteiro" onClick={() => ctx.openSession(session.id)}>
            Abrir ↗
          </button>
        )}
      </header>
      <span className="bd-cwd mono" title={cwd}>
        {shortPath(cwd)}
      </span>
      {session ? (
        <div className="bd-lines bd-scroll" ref={lines}>
          {messages.length ? (
            messages.slice(-8).map((m, i) => (
              <p key={i} className="bd-msg" data-role={m.role}>
                <span className="bd-msg-who mono">{m.role === "voce" ? "você" : title}</span>
                {m.text}
              </p>
            ))
          ) : tail.length ? (
            <pre className="bd-term mono">{tail.join("\n")}</pre>
          ) : (
            <p className="bd-quiet">{glance ? "Nada no terminal ainda." : visible ? "Lendo a sessão…" : ""}</p>
          )}
        </div>
      ) : (
        <div className="bd-lines bd-ended">
          <p>Esta sessão não existe mais. Abra outra na mesma pasta; o cartão passa a apontar para ela.</p>
        </div>
      )}
      <footer className="bd-session-foot">
        {alive ? (
          <div className="bd-say">
            <input
              value={text}
              placeholder="Mensagem para a sessão…"
              aria-label="Mensagem para a sessão"
              disabled={sending}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={onKey}
            />
            <button type="button" className="bd-say-send" title="Mandar (Enter)" aria-label="Mandar" disabled={!text.trim() || sending} onClick={() => void send()}>
              <Icon d={ICON.send} size={13} strokeWidth={2} />
            </button>
          </div>
        ) : (
          <button type="button" className="btn bd-reopen" onClick={() => ctx.reopen(node.id)}>
            <KindIcon kind={meta.kind} /> Abrir de novo
          </button>
        )}
      </footer>
    </div>
  );
}

// --- tarefa do kanban --------------------------------------------------------------------------

function TaskBody({ node, task, loaded, ctx }: { node: CanvasNode; task: KanbanTask | null; loaded: boolean; ctx: CardCtx }) {
  const { meta, body } = parseMeta(node.text);
  const projeto = (meta as TaskMeta).projeto;
  const html = useMemo(() => (task ? renderInline(task.text) : ""), [task]);
  // Sem a tarefa no kanban, mostra o que ficou escrito no cartão.
  const fallback = useMemo(() => /- \[[ xX]\] (.+)/.exec(body)?.[1] ?? "", [body]);
  const state = task ? TASK_STATE[task.state] : null;
  return (
    <div className="bd-task" onClick={(event) => linkClick(event, ctx)}>
      <span className="bd-task-head">
        <button type="button" className="bd-open" title="Abrir no kanban" onClick={() => ctx.openTasks(projeto)}>
          Tarefa · Kanban ↗
        </button>
        {state && (
          <span className="bd-task-state mono" style={{ color: state.color }}>
            <span className="dot" style={{ background: state.color }} />
            {task?.cancelled ? "cancelada" : state.label}
          </span>
        )}
      </span>
      {task ? (
        <span className="bd-task-text bd-scroll" data-done={task.state === "concluida" || task.cancelled ? "true" : undefined} dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <span className="bd-task-text" data-done="true">
          {fallback || "Tarefa"}
        </span>
      )}
      <span className="bd-task-meta mono">
        {projeto}
        {task && task.subtasks_total > 0 ? ` · ${task.subtasks_done}/${task.subtasks_total} subtarefas` : ""}
        {!task && (loaded ? " · não está mais no kanban" : " · lendo o kanban…")}
      </span>
    </div>
  );
}

// --- link ------------------------------------------------------------------------------------------

function LinkBody({ url, ctx }: { url: string; ctx: CardCtx }) {
  const info = linkInfo(url);
  return (
    <div className="bd-link">
      <span className="bd-link-head">
        <Icon d={ICON.globe} size={13} />
        {info.clickup ? "Tarefa · ClickUp" : info.local ? "Página local" : "Link"}
      </span>
      <span className="bd-addr mono" title={url}>
        <b>{info.host}</b>
        {info.path}
      </span>
      <span className="bd-link-actions">
        <button type="button" className="btn" onClick={() => ctx.openWeb(url)}>
          Abrir na MÊTIS
        </button>
        {info.local && (
          <button type="button" className="btn" onClick={() => ctx.openWeb(url, true)}>
            Modo de design
          </button>
        )}
      </span>
    </div>
  );
}

// --- nota solta ------------------------------------------------------------------------------------

function StickyBody({ node, editing, ctx }: { node: CanvasNode; editing: boolean; ctx: CardCtx }) {
  const text = node.text ?? "";
  const html = useMemo(() => (editing ? "" : renderNote(text)), [text, editing]);
  return (
    <div className="bd-sticky">
      <span className="bd-caps">Nota sua</span>
      {editing ? (
        <textarea
          autoFocus
          className="bd-sticky-edit"
          value={text}
          placeholder="Escreva em Markdown. Esc para sair."
          aria-label="Texto da nota"
          onChange={(event) => ctx.setText(node.id, event.target.value)}
          onBlur={ctx.stopEditing}
          onKeyDown={(event) => event.key === "Escape" && ctx.stopEditing()}
          onFocus={(event) => event.currentTarget.setSelectionRange(event.currentTarget.value.length, event.currentTarget.value.length)}
        />
      ) : text.trim() ? (
        <div className="markdown bd-md bd-scroll" onClick={(event) => linkClick(event, ctx)} dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <p className="bd-quiet">Dois cliques para escrever.</p>
      )}
    </div>
  );
}
