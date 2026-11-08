import { useEffect, useMemo, useRef, useState } from "react";
import { ICON, Icon } from "../icons";
import { openExternal } from "../lib/browser";
import type { CoreClient } from "../lib/core";
import { TYPE_ICON, TYPE_LABEL, renderNote, snippetParts } from "../lib/obsidian";
import type { BrainHit, BrainNote } from "../types";
import { BrainGraph } from "./BrainGraph";

/** Pedido vindo de fora da tela (kanban, painel da worktree, ⌘K): abrir uma nota ou buscar. */
export interface BrainRequest {
  id: number;
  title?: string;
  path?: string;
  query?: string;
}

interface Props {
  client: CoreClient | null;
  tick: number;
  request: BrainRequest | null;
  projects: string[];
  onOpenTasks: (project: string) => void;
  onError: (message: string) => void;
}

const FILTERS: { key: string; label: string; tipos: string[] }[] = [
  { key: "tudo", label: "Tudo", tipos: [] },
  { key: "decisao", label: "Decisões", tipos: ["decisao"] },
  { key: "incidente", label: "Incidentes", tipos: ["incidente"] },
  { key: "aprendizado", label: "Aprendizados", tipos: ["aprendizado"] },
  { key: "entrega", label: "Entregas", tipos: ["entrega"] },
  { key: "projeto", label: "Projetos", tipos: ["projeto"] },
  { key: "conhecimento", label: "Conhecimento", tipos: ["permanente", "literatura", "moc"] },
];

/** Sem busca, a lista mostra os registros mais recentes. */
const RECENT_TYPES = ["decisao", "incidente", "aprendizado", "entrega"];

export function Snippet({ text }: { text: string }) {
  return (
    <>
      {snippetParts(text).map((part, i) => (part.hit ? <mark key={i}>{part.text}</mark> : <span key={i}>{part.text}</span>))}
    </>
  );
}

export function HitRow({ hit, active, onOpen }: { hit: BrainHit; active?: boolean; onOpen: () => void }) {
  const preview = hit.snippet || hit.resumo;
  return (
    <button type="button" className="brain-hit" aria-current={active ? "true" : undefined} onClick={onOpen}>
      <span className="brain-hit-title">
        <span aria-hidden="true">{TYPE_ICON[hit.tipo] ?? "·"}</span> {hit.title}
      </span>
      <span className="brain-hit-meta mono">
        {[TYPE_LABEL[hit.tipo] ?? hit.tipo, hit.projeto, hit.status, hit.data].filter(Boolean).join(" · ")}
      </span>
      {preview && (
        <span className="brain-hit-snippet">
          <Snippet text={preview.slice(0, 260)} />
        </span>
      )}
    </button>
  );
}

export function BrainView({ client, tick, request, projects, onOpenTasks, onError }: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("tudo");
  const [project, setProject] = useState("");
  const [hits, setHits] = useState<BrainHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [note, setNote] = useState<BrainNote | null>(null);
  const [history, setHistory] = useState<{ path: string }[]>([]);
  const [missing, setMissing] = useState<Set<string>>(new Set());
  const [vault, setVault] = useState<{ total: number; available: boolean } | null>(null);
  /** A última nota aberta continua marcada no grafo ao voltar para ele. */
  const [lastPath, setLastPath] = useState<string | null>(null);
  const noteRef = useRef(note);
  noteRef.current = note;
  const body = useRef<HTMLElement>(null);
  const searchBox = useRef<HTMLInputElement>(null);

  const tipos = useMemo(() => {
    const chosen = FILTERS.find((f) => f.key === filter)?.tipos ?? [];
    return chosen.length ? chosen : query.trim() ? [] : RECENT_TYPES;
  }, [filter, query]);

  useEffect(() => {
    if (!client) return;
    void client
      .brainStatus()
      .then((s) => setVault(s))
      .catch(() => setVault(null));
  }, [client, tick]);

  // Busca enquanto digita, com uma pausa curta para não disparar a cada letra.
  useEffect(() => {
    if (!client) return;
    let alive = true;
    setSearching(true);
    const timer = window.setTimeout(() => {
      client
        .brainSearch(query, { tipo: tipos, projeto: project, limit: 60 })
        .then((found) => alive && setHits(found))
        .catch((cause) => alive && onError(String(cause)))
        .finally(() => alive && setSearching(false));
    }, 160);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, query, tipos, project, tick]);

  const open = async (target: { path?: string; title?: string }, push = true) => {
    if (!client) return;
    try {
      const next = await client.brainNote(target);
      const current = noteRef.current;
      if (push && current && current.path !== next.path) setHistory((h) => [...h.slice(-30), { path: current.path }]);
      setNote(next);
      setLastPath(next.path);
      body.current?.scrollTo({ top: 0 });
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  // Pedido de fora: abre a nota ou preenche a busca.
  useEffect(() => {
    if (!request) return;
    if (request.query !== undefined) {
      setQuery(request.query);
      window.setTimeout(() => searchBox.current?.focus(), 30);
    }
    if (request.title || request.path) void open({ title: request.title, path: request.path });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.id]);

  // A nota aberta acompanha mudanças feitas pela MÊTIS (tarefa movida, estágio trocado).
  useEffect(() => {
    if (note && tick) void open({ path: note.path }, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  // O título já está no cabeçalho: o "# título" que abre as notas do vault não se repete.
  const html = useMemo(() => (note ? renderNote(note.body.replace(/^\s*# [^\n]*\n/, "")) : ""), [note]);

  // Links para notas que não existem ficam tracejados, como no Obsidian.
  useEffect(() => {
    if (!client || !body.current) return;
    const titles = [...new Set([...body.current.querySelectorAll<HTMLElement>("a.wikilink")].map((a) => a.dataset.note ?? ""))].filter(Boolean);
    if (!titles.length) return setMissing(new Set());
    void client
      .brainKnown(titles)
      .then((known) => {
        const ok = new Set(known.map((t) => t.toLowerCase()));
        setMissing(new Set(titles.filter((t) => !ok.has(t.toLowerCase()))));
      })
      .catch(() => undefined);
  }, [client, html]);

  useEffect(() => {
    body.current?.querySelectorAll<HTMLElement>("a.wikilink").forEach((a) => {
      a.classList.toggle("missing", missing.has(a.dataset.note ?? ""));
    });
  }, [missing, html]);

  const onBodyClick = (event: React.MouseEvent) => {
    const link = (event.target as HTMLElement).closest("a");
    if (!link) return;
    event.preventDefault();
    if (link.classList.contains("wikilink")) {
      if (!link.classList.contains("missing")) void open({ title: link.dataset.note });
      return;
    }
    const href = link.getAttribute("href") ?? "";
    if (/^https?:\/\//.test(href)) void openExternal(href);
  };

  const back = () => {
    const last = history[history.length - 1];
    if (!last) return;
    setHistory((h) => h.slice(0, -1));
    void open({ path: last.path }, false);
  };

  const meta = note?.meta ?? {};
  const found = useMemo(() => (query.trim() ? new Set(hits.map((h) => h.path)) : null), [query, hits]);
  const isProject = note?.tipo === "projeto";

  return (
    <div className="brain-screen">
      <section className="brain-list" aria-label="Busca no Brain">
        <div className="brain-search">
          <Icon d={ICON.search} size={13} strokeWidth={2} />
          <input
            ref={searchBox}
            value={query}
            placeholder="Buscar no Brain…"
            spellCheck={false}
            autoFocus
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && hits[0]) void open({ path: hits[0].path });
              if (event.key === "Escape") setQuery("");
            }}
          />
          {searching && <span className="rec-dot" aria-label="buscando" />}
        </div>
        <div className="brain-filters" role="group" aria-label="Tipo de nota">
          {FILTERS.map((f) => (
            <button key={f.key} type="button" className="filter-chip" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
        <select className="brain-project" value={project} onChange={(event) => setProject(event.target.value)} aria-label="Projeto">
          <option value="">Todos os projetos</option>
          {projects.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <div className="section-title brain-count">
          {query.trim() ? `${hits.length} resultado${hits.length === 1 ? "" : "s"}` : "Registros recentes"}
        </div>
        <div className="brain-hits">
          {hits.map((hit) => (
            <HitRow key={hit.path} hit={hit} active={hit.path === note?.path} onOpen={() => void open({ path: hit.path })} />
          ))}
          {!hits.length && !searching && (
            <p className="small brain-empty">
              {vault && !vault.available
                ? "Não achei o vault em ~/Documents/Brain. Ajuste a variável BRAIN_VAULT e reabra a MÊTIS."
                : query.trim()
                  ? "Nada encontrado. A busca é por palavra, sem acento: tente outra palavra do título ou do resumo."
                  : "Sem registros ainda."}
            </p>
          )}
        </div>
        {vault && <div className="brain-foot small mono">{vault.total} notas no índice</div>}
      </section>

      <article className="brain-reader" ref={body} onClick={onBodyClick} aria-label="Nota">
        {note ? (
          <>
            <header className="brain-note-head">
              <div className="brain-note-actions">
                <button type="button" className="icon-btn" title="Voltar" aria-label="Voltar" disabled={!history.length} onClick={back}>
                  <Icon d="M15 6l-6 6 6 6" size={15} strokeWidth={2} />
                </button>
                <button type="button" className="btn" title="Fechar a nota e ver o grafo" onClick={() => setNote(null)}>
                  <Icon d={ICON.graph} size={13} /> Grafo
                </button>
                <span className="small mono brain-path">{note.path}</span>
                {isProject && (
                  <button type="button" className="btn" onClick={() => onOpenTasks(note.title)}>
                    Tarefas no kanban
                  </button>
                )}
                <button
                  type="button"
                  className="btn"
                  onClick={() => client && void client.openInObsidian(note.path).catch((cause) => onError(String(cause)))}
                >
                  Abrir no Obsidian
                </button>
              </div>
              <h1>
                <span aria-hidden="true">{TYPE_ICON[note.tipo] ?? ""}</span> {note.title}
              </h1>
              <div className="brain-chips">
                {note.tipo && <span className="chip">{TYPE_LABEL[note.tipo] ?? note.tipo}</span>}
                {note.projeto && !isProject && (
                  <button type="button" className="chip chip-link" onClick={() => void open({ title: note.projeto })}>
                    {note.projeto}
                  </button>
                )}
                {meta.status && <span className="chip" data-status={meta.status}>{meta.status}</span>}
                {meta.estagio && <span className="chip">estágio: {meta.estagio}</span>}
                {(meta.data || meta.atualizado) && <span className="chip mono">{meta.data || meta.atualizado}</span>}
              </div>
            </header>
            <div className="markdown brain-markdown" dangerouslySetInnerHTML={{ __html: html }} />
            {note.backlinks.length > 0 && (
              <section className="brain-backlinks">
                <div className="section-title">Citada por ({note.backlinks.length})</div>
                {note.backlinks.slice(0, 60).map((hit) => (
                  <HitRow key={hit.path} hit={hit} onOpen={() => void open({ path: hit.path })} />
                ))}
              </section>
            )}
          </>
        ) : vault && !vault.available ? (
          <div className="brain-welcome">
            <h2>Brain</h2>
            <p>Não achei o vault em ~/Documents/Brain. Ajuste a variável BRAIN_VAULT e reabra a MÊTIS.</p>
          </div>
        ) : (
          <BrainGraph client={client} tick={tick} highlight={found} current={lastPath} onOpen={(path) => void open({ path })} />
        )}
      </article>
    </div>
  );
}
