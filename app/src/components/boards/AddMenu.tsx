// O "Adicionar" do quadro: nota do Brain (busca), sessão aberta ou nova, tarefa do kanban do
// projeto, link, nota sua e grupo. Cada cartão novo entra no meio da tela, sem encostar em outro.

import { KindIcon } from "../KindIcon";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ICON, Icon } from "../../icons";
import { normalizeUrl, TASK_STATE } from "../../lib/canvas";
import type { CoreClient } from "../../lib/core";
import { KIND_COLOR, STATUS_COLOR, STATUS_LABEL, shortPath } from "../../lib/format";
import { TYPE_ICON, TYPE_LABEL } from "../../lib/obsidian";
import type { Agent, BrainHit, KanbanTask, Session, TaskState } from "../../types";
import { AgentSprite } from "../AgentSprite";

type Panel = "menu" | "nota" | "sessao" | "tarefa" | "link";

interface Props {
  client: CoreClient | null;
  projeto: string | null;
  sessions: Session[];
  agents: Agent[];
  tasks: KanbanTask[] | null;
  /** O que já está no quadro, para marcar "no quadro" na lista. */
  present: { notes: Set<string>; sessions: Set<string>; tasks: Set<string> };
  newSessionWhere: string;
  onAddNote: (hit: BrainHit) => void;
  onAddSession: (session: Session) => void;
  onNewSession: () => void;
  onAddTask: (task: KanbanTask) => void;
  onAddLink: (url: string) => void;
  onAddSticky: () => void;
  onAddGroup: () => void;
  onLoadTasks: () => void;
  onClose: () => void;
}

const P = {
  sticky: "M5 4h14v11l-5 5H5zM14 20v-5h5",
  group: "M4 7V4h3M17 4h3v3M20 17v3h-3M7 20H4v-3M9 4h6M9 20h6M4 9v6M20 9v6",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  back: "M15 6l-6 6 6 6",
};

const STATE_ORDER: TaskState[] = ["em-andamento", "em-teste", "pendente", "concluida"];

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export function AddMenu(props: Props) {
  const [panel, setPanel] = useState<Panel>("menu");
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(props.onClose);
  close.current = props.onClose;

  // Clique fora fecha (o botão "Adicionar" fica dentro do mesmo invólucro, então não reabre).
  // Esc volta ao menu e, no menu, fecha.
  useEffect(() => {
    const onDown = (event: PointerEvent) => {
      const wrap = box.current?.parentElement;
      if (wrap && !wrap.contains(event.target as Node)) close.current();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (panel === "menu") close.current();
      else setPanel("menu");
    };
    document.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [panel]);

  useEffect(() => {
    if (panel === "tarefa") props.onLoadTasks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panel]);

  const item = (key: Panel | "sticky" | "grupo", icon: ReactNode, label: string, hint: string, action: () => void) => (
    <button key={key} type="button" className="bd-add-item" onClick={action}>
      <span className="bd-add-icon">{icon}</span>
      <span className="bd-add-text">
        <b>{label}</b>
        <span>{hint}</span>
      </span>
    </button>
  );

  const head = (title: string) => (
    <header className="bd-add-head">
      <button type="button" className="icon-btn" aria-label="Voltar" title="Voltar" onClick={() => setPanel("menu")}>
        <Icon d={P.back} size={14} strokeWidth={2} />
      </button>
      <span>{title}</span>
    </header>
  );

  return (
    <div className="bd-add bd-overlay" ref={box} role="dialog" aria-label="Adicionar ao quadro" onPointerDown={(event) => event.stopPropagation()}>
      {panel === "menu" && (
        <div className="bd-add-list">
          {item("nota", <Icon d={ICON.graph} size={15} />, "Nota do Brain", props.projeto ? `busca, começando por ${props.projeto}` : "busca no Brain", () => setPanel("nota"))}
          {item("sessao", <Icon d={ICON.term} size={15} />, "Sessão", "Claude, Codex ou shell aberto, ou um Claude novo", () => setPanel("sessao"))}
          {item("tarefa", <Icon d={ICON.kanban} size={15} />, "Tarefa do projeto", props.projeto ? `do kanban de ${props.projeto}` : "do kanban do projeto", () => setPanel("tarefa"))}
          {item("link", <Icon d={P.link} size={15} />, "Link", "endereço que abre no navegador da MÊTIS", () => setPanel("link"))}
          {item("sticky", <Icon d={P.sticky} size={15} />, "Nota sua", "texto livre em Markdown", props.onAddSticky)}
          {item("grupo", <Icon d={P.group} size={15} />, "Grupo", "moldura com nome para juntar cartões", props.onAddGroup)}
        </div>
      )}
      {panel === "nota" && (
        <>
          {head("Nota do Brain")}
          <NotePicker client={props.client} projeto={props.projeto} present={props.present.notes} onPick={props.onAddNote} />
        </>
      )}
      {panel === "sessao" && (
        <>
          {head("Sessão")}
          <div className="bd-add-results">
            <button type="button" className="bd-add-row" data-primary="true" onClick={props.onNewSession}>
              <span className="bd-row-glyph" style={{ color: KIND_COLOR.claude }}>
                <KindIcon kind="claude" size={16} />
              </span>
              <span className="bd-row-text">
                <b>Nova sessão do Claude aqui</b>
                <span className="mono">{shortPath(props.newSessionWhere)}</span>
              </span>
            </button>
            {props.sessions.length === 0 && <p className="bd-add-note">Nenhuma sessão aberta agora.</p>}
            {props.sessions.map((s) => {
              const agent = s.agent ? props.agents.find((a) => a.id === s.agent) : undefined;
              return (
                <button key={s.id} type="button" className="bd-add-row" onClick={() => props.onAddSession(s)}>
                  <span className="bd-row-glyph" style={{ color: KIND_COLOR[s.kind] }}>
                    {agent ? <AgentSprite agent={agent} client={props.client} size={20} /> : <KindIcon kind={s.kind} size={16} />}
                  </span>
                  <span className="bd-row-text">
                    <b>{agent?.name ?? s.title}</b>
                    <span className="mono">{shortPath(s.cwd)}</span>
                  </span>
                  <span className="bd-row-side mono" style={{ color: STATUS_COLOR[s.status] }}>
                    {props.present.sessions.has(s.id) ? "no quadro" : STATUS_LABEL[s.status]}
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}
      {panel === "tarefa" && (
        <>
          {head("Tarefa do projeto")}
          <div className="bd-add-results">
            {!props.projeto ? (
              <p className="bd-add-note">Este quadro não está na pasta de um projeto, então não há kanban para puxar.</p>
            ) : props.tasks === null ? (
              <p className="bd-add-note">Lendo o kanban de {props.projeto}…</p>
            ) : props.tasks.filter((t) => !t.cancelled).length === 0 ? (
              <p className="bd-add-note">O kanban de {props.projeto} não tem tarefas.</p>
            ) : (
              STATE_ORDER.flatMap((state) =>
                props.tasks!
                  .filter((t) => t.state === state && !t.cancelled)
                  .slice(0, state === "concluida" ? 8 : 60)
                  .map((t) => (
                    <button key={t.id} type="button" className="bd-add-row" onClick={() => props.onAddTask(t)}>
                      <span className="dot" style={{ background: TASK_STATE[t.state].color }} />
                      <span className="bd-row-text">
                        <b className="bd-row-wrap">{t.text}</b>
                      </span>
                      <span className="bd-row-side mono" style={{ color: TASK_STATE[t.state].color }}>
                        {props.present.tasks.has(t.id) ? "no quadro" : TASK_STATE[t.state].label}
                      </span>
                    </button>
                  )),
              )
            )}
          </div>
        </>
      )}
      {panel === "link" && (
        <>
          {head("Link")}
          <LinkForm onAdd={props.onAddLink} />
        </>
      )}
    </div>
  );
}

function NotePicker({ client, projeto, present, onPick }: { client: CoreClient | null; projeto: string | null; present: Set<string>; onPick: (hit: BrainHit) => void }) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"projeto" | "todos">(projeto ? "projeto" : "todos");
  const [hits, setHits] = useState<BrainHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) return;
    let stop = false;
    const timer = window.setTimeout(() => {
      client
        .brainSearch(query, { projeto: scope === "projeto" && projeto ? projeto : "", limit: 30 })
        .then((list) => {
          if (stop) return;
          setHits(list);
          setError(null);
        })
        .catch((cause) => !stop && setError(message(cause)));
    }, 220);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [client, query, scope, projeto]);

  return (
    <>
      <div className="bd-add-search">
        <input
          autoFocus
          value={query}
          placeholder="Buscar decisões, incidentes, aprendizados…"
          aria-label="Buscar no Brain"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && hits?.length) onPick(hits[0]);
          }}
        />
        {projeto && (
          <div className="segmented" role="radiogroup" aria-label="Onde buscar">
            <button type="button" role="radio" aria-checked={scope === "projeto"} onClick={() => setScope("projeto")}>
              {projeto}
            </button>
            <button type="button" role="radio" aria-checked={scope === "todos"} onClick={() => setScope("todos")}>
              Todo o Brain
            </button>
          </div>
        )}
      </div>
      <div className="bd-add-results">
        {error && <p className="bd-add-note">Não deu para buscar: {error}</p>}
        {!error && hits === null && <p className="bd-add-note">Buscando…</p>}
        {!error && hits?.length === 0 && <p className="bd-add-note">Nada encontrado{query ? ` para “${query}”` : ""}.</p>}
        {hits?.map((hit) => (
          <button key={hit.path} type="button" className="bd-add-row" onClick={() => onPick(hit)}>
            <span className="bd-row-glyph" aria-hidden="true">
              {TYPE_ICON[hit.tipo] ?? "·"}
            </span>
            <span className="bd-row-text">
              <b className="bd-row-wrap">{hit.title}</b>
              <span className="mono">{[TYPE_LABEL[hit.tipo] ?? hit.tipo, hit.projeto, hit.status].filter(Boolean).join(" · ")}</span>
            </span>
            {present.has(hit.path) && <span className="bd-row-side mono">no quadro</span>}
          </button>
        ))}
      </div>
    </>
  );
}

function LinkForm({ onAdd }: { onAdd: (url: string) => void }) {
  const [value, setValue] = useState("");
  const url = normalizeUrl(value);
  return (
    <form
      className="bd-add-search"
      onSubmit={(event) => {
        event.preventDefault();
        if (url) onAdd(url);
      }}
    >
      <input autoFocus value={value} placeholder="localhost:3000/admin ou https://…" aria-label="Endereço do link" onChange={(event) => setValue(event.target.value)} />
      <div className="bd-add-actions">
        <span className="small mono">{url || " "}</span>
        <button type="submit" className="btn primary" disabled={!url}>
          Adicionar
        </button>
      </div>
    </form>
  );
}
