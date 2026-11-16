import { useEffect, useMemo, useState } from "react";
import type { CoreClient } from "../lib/core";
import type { Session, StudyConcept, StudyMap, StudySessionKind } from "../types";

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export const DOMAIN_LABEL = ["não vi", "ouvi falar", "entendo com ajuda", "faço sozinho", "consigo ensinar"];

function dayLabel(date: string | null): string {
  if (!date) return "—";
  const [, m, d] = date.split("-");
  return `${d}/${m}`;
}

/** Calibração: 0 = a confiança bate com o acerto; perto de 1 = confiante e errando (ou o contrário). */
function calibrationLabel(value: number | null): string {
  if (value == null) return "sem dado";
  if (value < 0.2) return "calibrado";
  if (value < 0.4) return "um pouco descalibrado";
  return "descalibrado";
}

/** Botões das sessões com o agente de estudo: cada uma abre um terminal com o pedido certo. */
export function StudyActions({
  client,
  dueCount,
  onSession,
}: {
  client: CoreClient;
  dueCount: number;
  onSession: (session: Session) => void;
}) {
  const [busy, setBusy] = useState<StudySessionKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const open = async (kind: StudySessionKind) => {
    setBusy(kind);
    setError(null);
    try {
      onSession(await client.studySession(kind));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="study-actions">
      <button type="button" className="btn primary" disabled={!!busy || dueCount === 0} onClick={() => void open("revisar")} title="Só os conceitos que vencem hoje, uma pergunta por conceito">
        {busy === "revisar" ? "Abrindo…" : `Revisar ${dueCount} vencido${dueCount === 1 ? "" : "s"}`}
      </button>
      <button type="button" className="btn" disabled={!!busy} onClick={() => void open("medir")} title="Diagnóstico da semana: você prevê a resposta e diz a confiança antes da explicação">
        {busy === "medir" ? "Abrindo…" : "Medir o que eu sei"}
      </button>
      <button type="button" className="btn" disabled={!!busy} onClick={() => void open("praticar")} title="Um exercício do foco da semana, no repositório do projeto">
        {busy === "praticar" ? "Abrindo…" : "Praticar"}
      </button>
      {error && <p className="small error-box">{error}</p>}
    </div>
  );
}

/**
 * Mapa do que você sabe (v0.9.8): os conceitos do projeto de estudo, cada um uma nota em
 * 01-PROJETOS/<projeto>/conceitos, com domínio, próxima revisão e calibração. O agente de estudo
 * registra cada resposta; aqui dá para abrir a nota, aprender um conceito e criar outro.
 */
export function StudyMapView({
  client,
  tick,
  onSession,
  onOpenNote,
}: {
  client: CoreClient;
  tick: number;
  onSession: (session: Session) => void;
  onOpenNote: (title: string) => void;
}) {
  const [map, setMap] = useState<StudyMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    client
      .studyMap()
      .then((value) => alive && (setMap(value), setError(null)))
      .catch((cause) => alive && setError(message(cause)));
    return () => {
      alive = false;
    };
  }, [client, tick, reload]);

  const byDomain = useMemo(() => {
    const groups: StudyConcept[][] = [[], [], [], [], []];
    for (const c of map?.conceitos ?? []) groups[Math.max(0, Math.min(4, c.dominio))].push(c);
    for (const g of groups) g.sort((a, b) => Number(b.vencido) - Number(a.vencido) || a.titulo.localeCompare(b.titulo));
    return groups;
  }, [map]);

  const learn = async (concept: StudyConcept) => {
    setBusy(concept.titulo);
    try {
      onSession(await client.studySession("aprender", concept.titulo));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(null);
    }
  };

  const create = async () => {
    if (!name.trim()) return;
    try {
      await client.addConcept(name.trim());
      setName("");
      setReload((n) => n + 1);
    } catch (cause) {
      setError(message(cause));
    }
  };

  if (error && !map) return <div className="study-map error-box">{error}</div>;
  if (!map) return <p className="small study-map">Lendo o mapa…</p>;
  const r = map.resumo;
  return (
    <div className="study-map">
      <div className="study-map-head">
        <span>
          <b>{r.total}</b> conceitos em <b>{map.projeto}</b> · <b>{r.vencidos}</b> para revisar hoje · confiança {calibrationLabel(r.calibracao_media)}
        </span>
        <form
          className="study-new"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Conceito novo (ex.: Embeddings)" />
          <button type="submit" className="btn" disabled={!name.trim()}>
            Criar
          </button>
        </form>
      </div>
      {error && <p className="small error-box">{error}</p>}
      {r.total === 0 && (
        <p className="small study-empty">
          Nenhum conceito ainda. Use <b>Medir o que eu sei</b>: o agente de estudo pergunta os conceitos da semana e cada resposta vira uma nota em{" "}
          <span className="mono">01-PROJETOS/{map.projeto}/conceitos</span>, ligada às outras no grafo do Brain.
        </p>
      )}
      <div className="study-domains">
        {byDomain
          .map((list, level) => ({ list, level }))
          .reverse()
          .filter(({ list }) => list.length > 0)
          .map(({ list, level }) => (
            <section key={level} className="study-domain" data-level={level}>
              <div className="section-title">
                {DOMAIN_LABEL[level]} · {list.length}
              </div>
              {list.map((c) => (
                <div key={c.caminho} className="study-concept" data-due={c.vencido ? "true" : undefined}>
                  <button type="button" className="link-btn study-concept-name" onClick={() => onOpenNote(c.titulo)} title="Abrir a nota no Brain">
                    {c.titulo}
                  </button>
                  <span className="small mono">
                    {c.acertos}✓ {c.erros}✗ · revisão {c.vencido ? "hoje" : dayLabel(c.proxima_revisao)}
                    {c.calibracao != null && c.calibracao >= 0.4 ? " · confiança desalinhada" : ""}
                  </span>
                  <button type="button" className="link-btn" disabled={busy === c.titulo} onClick={() => void learn(c)}>
                    {busy === c.titulo ? "abrindo…" : "aprender"}
                  </button>
                </div>
              ))}
            </section>
          ))}
      </div>
    </div>
  );
}
