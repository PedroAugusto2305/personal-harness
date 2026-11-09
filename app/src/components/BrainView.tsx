import { useEffect, useMemo, useRef, useState } from "react";
import { KindIcon } from "./KindIcon";
import { ICON, Icon } from "../icons";
import { openExternal } from "../lib/browser";
import type { CoreClient, NewSessionOptions } from "../lib/core";
import { TYPE_ICON, TYPE_LABEL, renderNote, snippetParts } from "../lib/obsidian";
import type { Agent, BrainHit, BrainNote, SemanticStatus, Session, SessionKind, Suggestion } from "../types";
import { BrainGraph } from "./BrainGraph";
import { NoteEditor } from "./NoteEditor";
import { SessionPeek } from "./SessionPeek";
import { SuggestionCard } from "./SuggestionCard";
import { VaultTree } from "./VaultTree";
import "./brain.css";

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
  suggestionsTick: number;
  /** v0.9.7: abre a nota para editar numa aba ao lado dos terminais. */
  onOpenTab: (path: string) => void;
  /** v0.9.9: a gaveta de conversas com os agentes. */
  sessions: Session[];
  agents: Agent[];
  onOpenSession: (id: string) => void;
  onStart: (kind: SessionKind, cwd: string, options: NewSessionOptions) => Promise<Session | null>;
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

const GRAPH = "grafo";
const TABS_KEY = "harness.brain.tabs";

function storedTabs(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(TABS_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((x) => typeof x === "string").slice(0, 12) : [];
  } catch {
    return [];
  }
}

const titleOf = (path: string) => path.split("/").pop()!.replace(/\.md$/, "");

export function BrainView({ client, tick, request, projects, onOpenTasks, onError, suggestionsTick, onOpenTab, sessions, agents, onOpenSession, onStart }: Props) {
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("tudo");
  const [project, setProject] = useState("");
  const [hits, setHits] = useState<BrainHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [note, setNote] = useState<BrainNote | null>(null);
  const [missing, setMissing] = useState<Set<string>>(new Set());
  const [vault, setVault] = useState<{ vault: string; total: number; available: boolean } | null>(null);
  const [semantic, setSemantic] = useState<SemanticStatus | null>(null);
  const [scanning, setScanning] = useState(false);
  const [related, setRelated] = useState<Suggestion[]>([]);
  const [pending, setPending] = useState<Suggestion[]>([]);
  /** Abas do centro: o grafo sempre, e as notas abertas. */
  const [tabs, setTabs] = useState<string[]>(storedTabs);
  const [active, setActive] = useState<string>(GRAPH);
  /** A última nota aberta: fica marcada no grafo e no painel da direita. */
  const [lastPath, setLastPath] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(true);
  const [peek, setPeek] = useState<string | null>(null);
  const [ask, setAsk] = useState("");
  const noteRef = useRef(note);
  noteRef.current = note;
  const body = useRef<HTMLElement>(null);
  const searchBox = useRef<HTMLInputElement>(null);

  const tipos = useMemo(() => {
    const chosen = FILTERS.find((f) => f.key === filter)?.tipos ?? [];
    return chosen.length ? chosen : query.trim() ? [] : RECENT_TYPES;
  }, [filter, query]);

  useEffect(() => {
    try {
      localStorage.setItem(TABS_KEY, JSON.stringify(tabs));
    } catch {
      // sem armazenamento
    }
  }, [tabs]);

  useEffect(() => {
    if (!client) return;
    void client
      .brainStatus()
      .then((s) => setVault(s))
      .catch(() => setVault(null));
  }, [client, tick]);

  useEffect(() => {
    if (!client) return;
    const load = () => void client.brainSemantic().then(setSemantic).catch(() => setSemantic(null));
    load();
    void client.suggestions().then(setPending).catch(() => setPending([]));
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, [client, tick, suggestionsTick]);

  useEffect(() => {
    if (!client || !note) return setRelated([]);
    let alive = true;
    const asks = [client.suggestions({ note: note.path })];
    if (note.tipo === "projeto") asks.push(client.suggestions({ project: note.title }));
    void Promise.all(asks)
      .then((lists) => {
        const seen = new Set<number>();
        alive && setRelated(lists.flat().filter((s) => !seen.has(s.id) && seen.add(s.id)));
      })
      .catch(() => alive && setRelated([]));
    return () => {
      alive = false;
    };
  }, [client, note, suggestionsTick]);

  const scan = async () => {
    if (!client || scanning) return;
    setScanning(true);
    try {
      const done = await client.scanSuggestions();
      onError(
        done.skipped
          ? "Já tem uma varredura em andamento."
          : done.baseline != null
            ? `Começou a acompanhar o Brain: ${done.baseline} registros existentes ficam como vistos.`
            : `${done.new ?? 0} registro(s) novo(s), ${done.judged ?? 0} julgado(s), ${done.created?.length ?? 0} sugestão(ões) nova(s).`,
      );
      setSemantic(await client.brainSemantic());
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setScanning(false);
    }
  };

  // Busca enquanto digita, com uma pausa curta para não disparar a cada letra.
  useEffect(() => {
    if (!client || !query.trim()) {
      setHits([]);
      return;
    }
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

  /** Abre a nota numa aba (ou vai para a aba dela). */
  const open = async (target: { path?: string; title?: string }) => {
    if (!client) return;
    try {
      const next = await client.brainNote(target);
      setNote(next);
      setLastPath(next.path);
      setTabs((all) => (all.includes(next.path) ? all : [...all.slice(-11), next.path]));
      setActive(next.path);
      setEditing(false);
      body.current?.scrollTo({ top: 0 });
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const activate = (key: string) => {
    setActive(key);
    if (key !== GRAPH) void open({ path: key });
  };

  const closeTab = (path: string) => {
    // Fora do setTabs: abrir a outra aba chama o núcleo, e função de estado não pode ter efeito.
    const next = tabs.filter((p) => p !== path);
    setTabs(next);
    if (active === path) {
      const fallback = next[next.length - 1];
      if (fallback) void open({ path: fallback });
      else setActive(GRAPH);
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
    if (note && tick && active === note.path) void client?.brainNote({ path: note.path }).then(setNote).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

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
  }, [client, html, active]);

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

  // Gaveta: as conversas com os agentes abertos (as do vault primeiro).
  const agentSessions = sessions.filter((s) => (s.kind === "claude" || s.kind === "codex") && s.status !== "exited");
  const inVault = (s: Session) => !!vault?.vault && s.cwd.startsWith(vault.vault);
  const drawerList = [...agentSessions.filter(inVault), ...agentSessions.filter((s) => !inVault(s))];
  const peekSession = drawerList.find((s) => s.id === peek) ?? drawerList[0] ?? null;
  const agentOf = (s: Session) => agents.find((a) => a.id === s.agent) ?? null;

  const startAsk = async () => {
    const text = ask.trim();
    if (!text || !vault?.vault) return;
    const hermes = agents.find((a) => a.id === "hermes" || a.name.toLowerCase() === "hermes");
    const session = await onStart(hermes && hermes.cli !== "outra" ? hermes.cli : "claude", hermes?.folder || vault.vault, {
      prompt: text,
      title: hermes ? undefined : "Brain",
      agent: hermes?.id,
    });
    if (session) {
      setAsk("");
      setPeek(session.id);
    }
  };

  const meta = note?.meta ?? {};
  const isProject = note?.tipo === "projeto";
  const showNote = active !== GRAPH && note && note.path === active;
  const found = useMemo(() => (query.trim() ? new Set(hits.map((h) => h.path)) : null), [query, hits]);
  const crumbs = note ? note.path.split("/").slice(1, -1).join(" / ") : "";

  return (
    <div className="bv">
      <div className="bv-cols">
        <section className="bv-left" aria-label="Arquivos e busca do Brain">
          <div className="brain-search">
            <Icon d={ICON.search} size={13} strokeWidth={2} />
            <input
              ref={searchBox}
              value={query}
              placeholder="Buscar no Brain…"
              spellCheck={false}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && hits[0]) void open({ path: hits[0].path });
                if (event.key === "Escape") setQuery("");
              }}
            />
            {searching && <span className="rec-dot" aria-label="buscando" />}
          </div>
          {query.trim() ? (
            <>
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
              <div className="section-title brain-count">{`${hits.length} resultado${hits.length === 1 ? "" : "s"}`}</div>
              <div className="brain-hits">
                {hits.map((hit) => (
                  <HitRow key={hit.path} hit={hit} active={hit.path === note?.path} onOpen={() => void open({ path: hit.path })} />
                ))}
                {!hits.length && !searching && <p className="small brain-empty">Nada encontrado. Tente outra palavra do título ou do resumo.</p>}
              </div>
            </>
          ) : (
            <VaultTree client={client} tick={tick} current={lastPath} onOpen={(path) => void open({ path })} storageKey="harness.brain.tree" />
          )}
          {vault && (
            <div className="brain-foot small mono">
              <div>{vault.total} notas no índice</div>
              {semantic && (
                <SemanticLine
                  status={semantic}
                  scanning={scanning}
                  onScan={() => void scan()}
                  onDownload={() => client && void client.brainSemanticDownload().then(() => client.brainSemantic().then(setSemantic))}
                />
              )}
            </div>
          )}
        </section>

        <main className="bv-center">
          <div className="bv-tabs" role="tablist" aria-label="Abas do Brain">
            <button type="button" role="tab" className="bv-tab" aria-selected={active === GRAPH} onClick={() => activate(GRAPH)}>
              <Icon d={ICON.graph} size={12} /> Visualização de grafo
            </button>
            {tabs.map((path) => (
              <span key={path} className="bv-tab" role="tab" aria-selected={active === path}>
                <button type="button" className="bv-tab-name" onClick={() => activate(path)} title={path}>
                  {titleOf(path)}
                </button>
                <button type="button" className="bv-tab-close" aria-label={`Fechar ${titleOf(path)}`} onClick={() => closeTab(path)}>
                  ×
                </button>
              </span>
            ))}
            <button type="button" className="bv-tab-plus" aria-label="Buscar outra nota" title="Buscar outra nota" onClick={() => searchBox.current?.focus()}>
              +
            </button>
          </div>

          {showNote ? (
            <article className="bv-reader" ref={body} onClick={onBodyClick} aria-label="Nota">
              <h1 className="bv-note-title">
                <span aria-hidden="true">{TYPE_ICON[note.tipo] ?? ""}</span> {note.title}
              </h1>
              {editing && client ? (
                <NoteEditor
                  client={client}
                  path={note.path}
                  docKey="brain-reader"
                  visible
                  onOpenNote={(title) => void open({ title })}
                  onError={onError}
                  onSaved={() => void client.brainNote({ path: note.path }).then((fresh) => setNote((current) => (current?.path === fresh.path ? fresh : current))).catch(() => undefined)}
                />
              ) : (
                <div className="markdown brain-markdown" dangerouslySetInnerHTML={{ __html: html }} />
              )}
            </article>
          ) : vault && !vault.available ? (
            <div className="brain-welcome">
              <h2>Brain</h2>
              <p>Não achei o vault em ~/Documents/Brain. Ajuste a variável BRAIN_VAULT e reabra a MÊTIS.</p>
            </div>
          ) : (
            <div className="bv-graph">
              {/* O grafo de sempre (pedido do Pedro na v0.9.9): zoom, arrasto, filtros e forças. A
                  busca da esquerda acende as notas achadas. */}
              <BrainGraph client={client} tick={tick} highlight={found} current={lastPath} onOpen={(path) => void open({ path })} />
            </div>
          )}
        </main>

        <aside className="bv-aside" aria-label="Nota selecionada">
          {note ? (
            <>
              <span className="bv-crumbs">{crumbs || "vault"}</span>
              <span className="bv-aside-title">{note.title}</span>
              <div className="bv-props">
                {[
                  ["tipo", TYPE_LABEL[note.tipo] ?? note.tipo ?? "—"],
                  ["status", meta.status],
                  ["data", meta.data || meta.atualizado],
                  ["projeto", note.projeto],
                  ["estágio", meta.estagio],
                ]
                  .filter(([, v]) => v)
                  .map(([k, v]) => (
                    <div key={k} className="bv-prop">
                      <span className="bv-prop-key">{k}</span>
                      {k === "projeto" ? (
                        <button type="button" className="bv-prop-link" onClick={() => void open({ title: v })}>
                          {v}
                        </button>
                      ) : (
                        <span className="bv-prop-value" data-status={k === "status" ? v : undefined}>
                          {v}
                        </span>
                      )}
                    </div>
                  ))}
              </div>
              <div className="bv-actions">
                <button type="button" className={editing && showNote ? "btn primary" : "btn"} onClick={() => (showNote ? setEditing((v) => !v) : void open({ path: note.path }))}>
                  {editing && showNote ? "Ler" : "Editar"}
                </button>
                <button type="button" className="btn" title="Editar numa aba ao lado dos terminais" onClick={() => onOpenTab(note.path)}>
                  Ao lado
                </button>
                <button type="button" className="btn" onClick={() => client && void client.openInObsidian(note.path).catch((cause) => onError(String(cause)))}>
                  Obsidian
                </button>
                {isProject && (
                  <button type="button" className="btn" onClick={() => onOpenTasks(note.title)}>
                    Tarefas
                  </button>
                )}
              </div>
              <div className="bv-block">
                <span className="bv-block-title">Backlinks · {note.backlinks.length}</span>
                {note.backlinks.slice(0, 30).map((hit) => (
                  <button key={hit.path} type="button" className="bv-backlink" onClick={() => void open({ path: hit.path })}>
                    <span className="bv-backlink-title">{hit.title}</span>
                    <span className="bv-backlink-path">{hit.path.split("/").slice(1, -1).join(" / ")}</span>
                  </button>
                ))}
                {!note.backlinks.length && <span className="small bv-quiet">Nenhuma nota cita esta.</span>}
              </div>
              {related.filter((r) => r.status === "pendente").map((item) => (
                <div key={item.id} className="bv-serve">
                  <span className="bv-serve-title">Pode servir em</span>
                  <SuggestionCard client={client} item={item} showTarget compact onOpenNote={(title) => void open({ title })} onDone={onError} onError={onError} />
                </div>
              ))}
              {related
                .filter((r) => r.status !== "pendente")
                .map((item) => (
                  <p key={item.id} className="small brain-suggestion-past">
                    {item.status === "aceita" ? "✓ virou decisão em" : "✗ recusada para"} {item.target_project}:{" "}
                    <button type="button" className="link-btn" onClick={() => void open(item.note ? { path: item.note } : { title: item.title })}>
                      {item.title}
                    </button>
                  </p>
                ))}
            </>
          ) : (
            <>
              <span className="bv-aside-title">Brain</span>
              <span className="small bv-quiet">
                {vault ? `${vault.total} notas · ${projects.length} projetos.` : ""} Clique numa nota (na árvore, na busca ou no grafo) para ver as propriedades, quem
                cita e onde mais ela pode servir.
              </span>
              <div className="bv-block">
                <span className="bv-block-title">Precedentes esperando você · {pending.length}</span>
                {pending.slice(0, 4).map((item) => (
                  <div key={item.id} className="bv-serve">
                    <SuggestionCard client={client} item={item} showTarget compact onOpenNote={(title) => void open({ title })} onDone={onError} onError={onError} />
                  </div>
                ))}
                {!pending.length && <span className="small bv-quiet">Nenhum agora.</span>}
              </div>
            </>
          )}
        </aside>
      </div>

      <section className="bv-drawer" data-open={drawer ? "true" : undefined} aria-label="Conversas com os agentes">
        <div className="bv-drawer-tabs">
          {drawerList.slice(0, 6).map((s) => {
            const agent = agentOf(s);
            return (
              <button key={s.id} type="button" className="bv-drawer-tab" aria-selected={peekSession?.id === s.id} onClick={() => (setPeek(s.id), setDrawer(true))}>
                <KindIcon kind={s.kind as "claude" | "codex"} />
                <span className="bv-drawer-name">{agent?.name ?? s.title}</span>
                <span className="bv-drawer-dot" data-status={s.status} />
              </button>
            );
          })}
          <button type="button" className="bv-drawer-plus" title="Nova conversa no vault" aria-label="Nova conversa no vault" onClick={() => (setPeek("__nova__"), setDrawer(true))}>
            +
          </button>
          <button type="button" className="bv-drawer-toggle" onClick={() => setDrawer((v) => !v)} aria-expanded={drawer}>
            Conversas {drawer ? "⌄" : "⌃"}
          </button>
        </div>
        {drawer && (
          <div className="bv-drawer-body" data-ask={client && peekSession && peek !== "__nova__" ? undefined : "true"}>
            {client && peekSession && peek !== "__nova__" ? (
              <SessionPeek
                client={client}
                session={peekSession}
                placeholder="Responda ou peça mais…"
                onError={onError}
                onOpen={() => onOpenSession(peekSession.id)}
              />
            ) : (
              <form
                className="bv-ask"
                onSubmit={(event) => {
                  event.preventDefault();
                  void startAsk();
                }}
              >
                <textarea
                  rows={2}
                  value={ask}
                  onChange={(e) => setAsk(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      void startAsk();
                    }
                  }}
                  placeholder="Pergunte ao Brain ou peça ao Hermes… (abre uma conversa no vault)"
                  aria-label="Pergunta ao Brain"
                />
                <div className="bv-ask-row">
                  <span className="small">@ nota · / comando, na conversa</span>
                  <button type="submit" className="peek-send" aria-label="Perguntar" disabled={!ask.trim() || !vault?.vault}>
                    <Icon d={ICON.up} size={13} strokeWidth={2.4} />
                  </button>
                </div>
              </form>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

const MODEL_STATE: Record<string, string> = {
  pronto: "carregado",
  parado: "pronto (fora da memória)",
  carregando: "carregando…",
  baixando: "baixando…",
  ausente: "não baixado",
  erro: "com erro",
};

/** Rodapé da lista: o modelo de significado, os vetores e o juiz das sugestões. */
function SemanticLine({ status, scanning, onScan, onDownload }: { status: SemanticStatus; scanning: boolean; onScan: () => void; onDownload: () => void }) {
  const { model, index, suggestions } = status;
  const pending = suggestions.counts.pendente ?? 0;
  return (
    <div className="brain-semantic" title={model.error || `${model.model} · ${model.url}`}>
      <div>
        significado: {MODEL_STATE[model.state] ?? model.state}
        {model.state !== "ausente" && ` · ${index.vectors}/${index.notes} vetores`}
        {model.state === "ausente" && (
          <button type="button" className="link-btn" onClick={onDownload}>
            baixar (500 MB)
          </button>
        )}
      </div>
      <div>
        sugestões: {pending} pendente{pending === 1 ? "" : "s"} · juiz {suggestions.judged_today}/{suggestions.daily_max} hoje
        <button type="button" className="link-btn" disabled={scanning} onClick={onScan}>
          {scanning ? "procurando…" : "procurar agora"}
        </button>
      </div>
      {model.error && <div className="brain-semantic-err">{model.error}</div>}
    </div>
  );
}
