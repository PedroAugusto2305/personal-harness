import { useCallback, useEffect, useMemo, useState } from "react";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import type { Session, StudyPlanDraft, StudyPlanInfo } from "../types";
import { Confirm } from "./Confirm";

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

/** 2026-11-16 → 16/11/2026 */
function br(date: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? `${date.slice(8, 10)}/${date.slice(5, 7)}/${date.slice(0, 4)}` : date || "?";
}

/** 2026-11-16 → 16/11 */
function short(date: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? `${date.slice(8, 10)}/${date.slice(5, 7)}` : date || "—";
}

/** O dia local em AAAA-MM-DD (toISOString daria o dia em UTC). */
function iso(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

/** O objetivo vem do Markdown da nota: sem **negrito**, `código` e [[links]] (fica o texto). */
function plain(text: string): string {
  return text
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_m, target: string, alias?: string) => alias ?? target)
    .replace(/\*\*|__|`/g, "");
}

function addDays(date: string, days: number): string {
  const [y, m, d] = date.split("-").map(Number);
  return iso(new Date(y, m - 1, d + days));
}

interface Row {
  inicio: string;
  fim: string;
  foco: string;
  entrega: string;
}

interface Props {
  client: CoreClient;
  tick: number;
  /** O agente de estudo conectado (null = nenhum): é ele quem monta o cronograma junto com o Pedro. */
  tutorName: string | null;
  onPlanSession: (session: Session) => void;
  onOpenNote: (title: string) => void;
}

/**
 * v1.4.0: os planos de estudo. Cada plano é um projeto do Brain (plano_estudo: ativo ou inativo), com
 * o cronograma na tabela da nota. Aqui dá para criar, editar, ativar, desativar, pôr em foco e
 * excluir (a pasta vai para 04-ARQUIVO), e montar ou ajustar o cronograma com o agente de estudo.
 */
export function StudyPlansView({ client, tick, tutorName, onPlanSession, onOpenNote }: Props) {
  const [plans, setPlans] = useState<StudyPlanInfo[] | null>(null);
  const [focus, setFocus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<StudyPlanInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<{ mode: "novo" | "editar"; draft: StudyPlanDraft; withAgent: boolean } | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<StudyPlanInfo | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    client
      .studyPlans()
      .then((value) => {
        if (!alive) return;
        setPlans(value.planos);
        setFocus(value.foco);
        setSelected((current) => (current && value.planos.some((p) => p.nome === current) ? current : value.foco || value.planos[0]?.nome || null));
      })
      .catch((cause) => alive && setError(message(cause)));
    return () => {
      alive = false;
    };
  }, [client, tick, reload]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let alive = true;
    client
      .studyPlanDetail(selected)
      .then((value) => alive && setDetail(value))
      .catch((cause) => alive && setError(message(cause)));
    return () => {
      alive = false;
    };
  }, [client, selected, tick, reload]);

  /** Faz a ação, relê os planos e devolve o resultado (undefined quando falhou, com o erro na tela). */
  const run = useCallback(async <T,>(key: string, action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(key);
    setError(null);
    try {
      const result = await action();
      setReload((n) => n + 1);
      return result;
    } catch (cause) {
      setError(message(cause));
      return undefined;
    } finally {
      setBusy(null);
    }
  }, []);

  const openNew = () => {
    const start = iso(new Date());
    setForm({ mode: "novo", draft: { nome: "", tema: "", inicio: start, fim: addDays(start, 8 * 7 - 1), objetivo: "" }, withAgent: !!tutorName });
  };

  const openEdit = (plan: StudyPlanInfo) =>
    setForm({ mode: "editar", draft: { nome: plan.nome, tema: plan.tema, inicio: plan.inicio, fim: plan.fim, objetivo: plan.objetivo ?? "" }, withAgent: false });

  const planWithAgent = async (name: string) => {
    setBusy(`agente:${name}`);
    setError(null);
    try {
      onPlanSession(await client.studySession("planejar", undefined, name));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(null);
    }
  };

  const submit = async () => {
    if (!form) return;
    const { draft, mode, withAgent } = form;
    if (mode === "novo") {
      const created = await run("form", () => client.createStudyPlan({ ...draft, nome: draft.nome.trim() }));
      if (!created) return;
      setForm(null);
      setSelected(created.nome);
      setRows(null);
      if (withAgent && tutorName) await planWithAgent(created.nome);
      return;
    }
    const ok = await run("form", () => client.patchStudyPlan(draft.nome, { tema: draft.tema, inicio: draft.inicio, fim: draft.fim, objetivo: draft.objetivo }));
    if (ok) setForm(null);
  };

  const startEditRows = () => setRows((detail?.cronograma ?? []).map(({ inicio, fim, foco, entrega }) => ({ inicio, fim, foco, entrega })));

  const addRow = () =>
    setRows((current) => {
      const list = current ?? [];
      const last = list[list.length - 1];
      const valid = (d?: string) => !!d && /^\d{4}-\d{2}-\d{2}$/.test(d);
      const start = last && valid(last.inicio) ? addDays(last.inicio, 7) : valid(detail?.inicio) ? detail!.inicio : iso(new Date());
      const end = last && valid(last.fim) ? addDays(last.fim, 7) : addDays(start, 6);
      return [...list, { inicio: start, fim: end, foco: "", entrega: "" }];
    });

  const saveRows = async () => {
    if (!detail || !rows) return;
    const ok = await run("rows", () => client.saveStudySchedule(detail.nome, rows));
    if (ok) setRows(null);
  };

  const remove = async (plan: StudyPlanInfo) => {
    const ok = await run(`excluir:${plan.nome}`, () => client.deleteStudyPlan(plan.nome));
    if (ok) {
      setDeleting(null);
      if (selected === plan.nome) setSelected(null);
    }
  };

  const counts = useMemo(() => ({ total: plans?.length ?? 0, active: plans?.filter((p) => p.estado === "ativo").length ?? 0 }), [plans]);

  if (error && !plans) return <div className="study-plan error-box">{error}</div>;
  if (!plans) return <p className="small study-plan">Lendo os planos…</p>;

  const filled = (detail?.semanas_com_foco ?? 0) > 0;

  return (
    <div className="study-plan sp">
      <div className="study-map-head">
        <span>
          <b>{counts.total}</b> plano{counts.total === 1 ? "" : "s"} de estudo · <b>{counts.active}</b> ativo{counts.active === 1 ? "" : "s"}
          {focus ? (
            <>
              {" "}
              · em foco: <b>{focus}</b>
            </>
          ) : null}
        </span>
        <button type="button" className="btn primary" onClick={openNew} disabled={form?.mode === "novo"}>
          <Icon d={ICON.plus} size={13} />
          Novo plano
        </button>
      </div>
      {error && <p className="small error-box">{error}</p>}

      {form && (
        <form
          className="sp-form form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="wide sp-form-title">
            <b>{form.mode === "novo" ? "Novo plano de estudos" : `Editar «${form.draft.nome}»`}</b>
            <span className="small">
              {form.mode === "novo"
                ? "Vira um projeto no Brain (01-PROJETOS), com a nota do plano, as semanas do período no cronograma e os conceitos numa pasta própria."
                : "O nome não muda por aqui: renomeie a nota no Obsidian, que atualiza os links."}
            </span>
          </div>
          {form.mode === "novo" && (
            <label className="wide">
              <span className="setting-label">Nome</span>
              <input
                value={form.draft.nome}
                onChange={(event) => setForm({ ...form, draft: { ...form.draft, nome: event.target.value } })}
                placeholder="ex.: Inglês para entrevistas"
                maxLength={80}
                autoFocus
                required
              />
            </label>
          )}
          <label className="wide">
            <span className="setting-label">Tema</span>
            <input value={form.draft.tema} onChange={(event) => setForm({ ...form, draft: { ...form.draft, tema: event.target.value } })} placeholder="ex.: conversação técnica em inglês" maxLength={160} />
          </label>
          <label>
            <span className="setting-label">Início</span>
            <input type="date" value={form.draft.inicio} onChange={(event) => setForm({ ...form, draft: { ...form.draft, inicio: event.target.value } })} required />
          </label>
          <label>
            <span className="setting-label">Fim</span>
            <input type="date" value={form.draft.fim} min={form.draft.inicio} onChange={(event) => setForm({ ...form, draft: { ...form.draft, fim: event.target.value } })} required />
          </label>
          <label className="wide">
            <span className="setting-label">Objetivo</span>
            <textarea
              rows={3}
              value={form.draft.objetivo}
              onChange={(event) => setForm({ ...form, draft: { ...form.draft, objetivo: event.target.value } })}
              placeholder="O resultado do plano, numa ou duas frases (vai para o > [!abstract] da nota)."
              maxLength={8000}
            />
          </label>
          {form.mode === "novo" && (
            <label className="wide check sp-check">
              <input type="checkbox" checked={form.withAgent} disabled={!tutorName} onChange={(event) => setForm({ ...form, withAgent: event.target.checked })} />
              {tutorName ? `Montar o cronograma com ${tutorName} logo depois de criar` : "Conecte um agente de estudo (painel à direita) para montar o cronograma com ele"}
            </label>
          )}
          <div className="wide form-buttons">
            <span className="grow" />
            <button type="button" className="btn" onClick={() => setForm(null)}>
              Cancelar
            </button>
            <button type="submit" className="btn primary" disabled={busy === "form" || (form.mode === "novo" && !form.draft.nome.trim())}>
              {busy === "form" ? "Gravando…" : form.mode === "novo" ? "Criar plano" : "Salvar"}
            </button>
          </div>
        </form>
      )}

      {plans.length === 0 && !form ? (
        <p className="small study-empty">
          Nenhum plano de estudos. Crie um com <b>Novo plano</b>: ele vira um projeto no Brain com o cronograma do período, e o agente de estudo ajuda a montar o foco e a entrega de cada semana.
        </p>
      ) : (
        <div className="sp-list">
          {plans.map((plan) => {
            const week = plan.semana_atual;
            return (
              <article
                key={plan.nome}
                className="sp-card"
                data-state={plan.estado}
                data-selected={plan.nome === selected || undefined}
                onClick={() => {
                  setSelected(plan.nome);
                  setRows(null);
                }}
              >
                <header className="sp-card-head">
                  <b className="sp-name">{plan.nome}</b>
                  <span className={`badge ${plan.estado === "ativo" ? "sp-on" : ""}`}>{plan.estado}</span>
                  {plan.em_foco && <span className="badge sp-focus">em foco</span>}
                </header>
                <span className="small sp-theme">{plan.tema || "sem tema"}</span>
                <span className="small mono">
                  {br(plan.inicio)} a {br(plan.fim)}
                </span>
                <span className="small sp-week">
                  {week ? `semana ${week.numero} de ${plan.semanas} · ${week.foco || "sem foco escrito"}` : plan.semanas ? `fora do cronograma hoje · ${plan.semanas} semanas` : "cronograma vazio"}
                </span>
                <span className="small mono sp-numbers">
                  {plan.conceitos ?? 0} conceitos{plan.vencidos ? ` · ${plan.vencidos} para revisar` : ""} · {Math.round(plan.minutos_semana ?? 0)} min na semana
                </span>
                <footer className="sp-card-actions" onClick={(event) => event.stopPropagation()}>
                  {plan.estado === "ativo" && !plan.em_foco && (
                    <button type="button" className="link-btn" disabled={!!busy} onClick={() => void run(`foco:${plan.nome}`, () => client.setStudyFocus(plan.nome))}>
                      pôr em foco
                    </button>
                  )}
                  <button type="button" className="link-btn" disabled={!!busy} onClick={() => openEdit(plan)}>
                    editar
                  </button>
                  <button
                    type="button"
                    className="link-btn"
                    disabled={!!busy}
                    title={plan.estado === "ativo" ? "Sai do foco e das sessões; a nota fica no Brain e volta com Ativar" : "Volta a valer no Estudo"}
                    onClick={() => void run(`estado:${plan.nome}`, () => client.setStudyPlanActive(plan.nome, plan.estado !== "ativo"))}
                  >
                    {busy === `estado:${plan.nome}` ? "…" : plan.estado === "ativo" ? "desativar" : "ativar"}
                  </button>
                  <button type="button" className="link-btn sp-danger" disabled={!!busy} onClick={() => setDeleting(plan)}>
                    excluir
                  </button>
                </footer>
              </article>
            );
          })}
        </div>
      )}

      {detail && (
        <section className="sp-detail" aria-label={`Cronograma de ${detail.nome}`}>
          <div className="study-map-head">
            <span>
              Cronograma de <b>{detail.nome}</b>
              {detail.semana_atual ? ` · semana ${detail.semana_atual.numero} agora` : " · fora do cronograma hoje"}
              {detail.estado === "inativo" ? " · desativado" : ""}
            </span>
            <span className="sp-detail-actions">
              <button type="button" className="link-btn" onClick={() => onOpenNote(detail.nome)}>
                abrir a nota ›
              </button>
              {!rows && (
                <button type="button" className="btn" onClick={startEditRows}>
                  Editar cronograma
                </button>
              )}
              <button
                type="button"
                className="btn primary"
                disabled={!tutorName || !!busy}
                title={tutorName ? `Abre uma conversa com ${tutorName} para ${filled ? "ajustar" : "montar"} o cronograma; ele grava na nota quando você aprovar` : "Conecte um agente de estudo no painel à direita"}
                onClick={() => void planWithAgent(detail.nome)}
              >
                <Icon d={ICON.chat} size={13} />
                {busy === `agente:${detail.nome}` ? "Abrindo…" : `${filled ? "Ajustar" : "Montar"} com ${tutorName ?? "o agente"}`}
              </button>
            </span>
          </div>
          {detail.objetivo && <p className="small sp-goal">{plain(detail.objetivo)}</p>}
          {rows ? (
            <div className="sp-editor">
              <table className="activity study-weeks">
                <thead>
                  <tr>
                    <th>Sem.</th>
                    <th>Início</th>
                    <th>Fim</th>
                    <th>Foco</th>
                    <th>Entrega</th>
                    <th aria-label="Tirar" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => {
                    const set = (patch: Partial<Row>) => setRows(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)));
                    return (
                      <tr key={i}>
                        <td className="mono">{i + 1}</td>
                        <td>
                          <input type="date" value={row.inicio} onChange={(event) => set({ inicio: event.target.value })} aria-label={`Início da semana ${i + 1}`} />
                        </td>
                        <td>
                          <input type="date" value={row.fim} min={row.inicio} onChange={(event) => set({ fim: event.target.value })} aria-label={`Fim da semana ${i + 1}`} />
                        </td>
                        <td>
                          <input value={row.foco} onChange={(event) => set({ foco: event.target.value })} placeholder="foco da semana" aria-label={`Foco da semana ${i + 1}`} maxLength={300} />
                        </td>
                        <td>
                          <input value={row.entrega} onChange={(event) => set({ entrega: event.target.value })} placeholder="entrega demonstrável" aria-label={`Entrega da semana ${i + 1}`} maxLength={300} />
                        </td>
                        <td>
                          <button type="button" className="sv-icon" title="Tirar a semana" aria-label={`Tirar a semana ${i + 1}`} onClick={() => setRows(rows.filter((_r, k) => k !== i))}>
                            <Icon d={ICON.close} size={12} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="form-buttons">
                <button type="button" className="btn" onClick={addRow}>
                  <Icon d={ICON.plus} size={13} />
                  Semana
                </button>
                <span className="small sp-hint">As semanas ficam em ordem de data e são numeradas de novo ao salvar. A nota do plano no Brain é atualizada.</span>
                <span className="grow" />
                <button type="button" className="btn" onClick={() => setRows(null)}>
                  Cancelar
                </button>
                <button type="button" className="btn primary" disabled={busy === "rows"} onClick={() => void saveRows()}>
                  {busy === "rows" ? "Salvando…" : "Salvar cronograma"}
                </button>
              </div>
            </div>
          ) : (detail.cronograma ?? []).length === 0 ? (
            <p className="small study-empty">O cronograma está vazio. Use Editar cronograma ou monte com o agente de estudo.</p>
          ) : (
            <table className="activity study-weeks sp-weeks-view">
              <thead>
                <tr>
                  <th>Sem.</th>
                  <th>Datas</th>
                  <th>Foco</th>
                  <th>Entrega</th>
                </tr>
              </thead>
              <tbody>
                {(detail.cronograma ?? []).map((w) => (
                  <tr key={w.numero} data-current={w.atual ? "true" : undefined}>
                    <td className="mono">{w.numero}</td>
                    <td className="mono small">
                      {short(w.inicio)} a {short(w.fim)}
                    </td>
                    <td>{w.foco || <span className="sp-empty-cell">—</span>}</td>
                    <td className="small">{w.entrega}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {deleting && (
        <Confirm
          title={`Excluir o plano «${deleting.nome}»?`}
          confirmLabel="Excluir plano"
          danger
          busy={busy === `excluir:${deleting.nome}`}
          onCancel={() => setDeleting(null)}
          onConfirm={() => void remove(deleting)}
        >
          <p>
            A pasta do plano no Brain (a nota{deleting.conceitos ? `, os ${deleting.conceitos} conceitos` : ""} e o que mais estiver nela) vai para <span className="mono">04-ARQUIVO/{deleting.nome}</span>, com um aviso no topo da nota.
            Nada é apagado: o vault não apaga nota.
          </p>
          <p className="small">
            O plano sai da aba de Estudos e do kanban de projetos.{deleting.em_foco ? " O foco passa para outro plano ativo." : ""} Para só pausar, use <b>desativar</b>.
          </p>
        </Confirm>
      )}
    </div>
  );
}
