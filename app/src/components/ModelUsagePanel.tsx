import { useEffect, useMemo, useState } from "react";
import { KindIcon } from "./KindIcon";
import type { CoreClient } from "../lib/core";
import { ago, money, tokens } from "../lib/format";
import type { ModelUsageModel, ModelUsageReport } from "../types";
import "./usage.css";

/**
 * Uso dos modelos (v0.9.9, pedido do Pedro: "quero ver o tanto gasto e afins"). Tokens e custo
 * equivalente em API por modelo, por dia e por projeto, lidos pelo núcleo dos registros que o
 * Claude Code e o Codex gravam no Mac (também das sessões abertas fora da MÊTIS).
 *
 * Cor por família, sempre a mesma (a cor segue o modelo, nunca a posição): Opus, Sonnet, Haiku,
 * Fable e Codex; o resto entra em "Outros". Paleta conferida com o validador do dataviz nos
 * três temas (Drácula, Grafite e Claro).
 */

const FAMILIES = ["Opus", "Sonnet", "Haiku", "Fable", "Codex", "Outros"] as const;
type Family = (typeof FAMILIES)[number];

function familyOf(label: string, provider?: string): Family {
  if (provider === "codex" || /^gpt|^o\d|codex/i.test(label)) return "Codex";
  const first = label.split(" ")[0];
  if (first === "Mythos") return "Fable";
  return (FAMILIES as readonly string[]).includes(first) ? (first as Family) : "Outros";
}

const PERIODS = [
  { dias: 1, label: "Hoje" },
  { dias: 7, label: "7 dias" },
  { dias: 30, label: "30 dias" },
];
const PERIOD_KEY = "metis.uso.dias";

function storedPeriod(): number {
  try {
    const value = Number(localStorage.getItem(PERIOD_KEY));
    return PERIODS.some((p) => p.dias === value) ? value : 7;
  } catch {
    return 7;
  }
}

const usd = (value: number) => (value >= 1000 ? `US$ ${Math.round(value).toLocaleString("pt-BR")}` : money(value));

export function ModelUsagePanel({ client }: { client: CoreClient | null }) {
  const [dias, setDias] = useState(storedPeriod);
  const [metric, setMetric] = useState<"custo" | "tokens">("custo");
  const [report, setReport] = useState<ModelUsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(PERIOD_KEY, String(dias));
    } catch {
      // sem armazenamento: o período vale só agora
    }
  }, [dias]);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    const load = () => {
      setLoading(true);
      client
        .modelUsage(dias)
        .then((next) => {
          if (!alive) return;
          setReport(next);
          setError(null);
        })
        .catch((cause) => alive && setError(cause instanceof Error ? cause.message : String(cause)))
        .finally(() => alive && setLoading(false));
    };
    load();
    const timer = window.setInterval(load, 120_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client, dias]);

  const top = report?.por_modelo.find((m) => m.custo > 0) ?? null;
  const share = top && report && report.total.custo > 0 ? Math.round((top.custo / report.total.custo) * 100) : 0;
  const written = report ? report.total.cache_5m + report.total.cache_1h : 0;

  return (
    <div className="card uso" aria-label="Uso dos modelos">
      <header className="uso-head">
        <div className="uso-title">
          <h2>Uso dos modelos</h2>
          <span className="small">
            {report ? `${fmtDay(report.desde)}${report.dias > 1 ? ` a ${fmtDay(report.ate)}` : ""} · atualizado ${ago(report.atualizado * 1000)}` : "lendo os registros do Claude e do Codex…"}
            {loading && report ? " · atualizando…" : ""}
          </span>
        </div>
        <div className="uso-seg" role="group" aria-label="Período">
          {PERIODS.map((p) => (
            <button key={p.dias} type="button" aria-pressed={dias === p.dias} onClick={() => setDias(p.dias)}>
              {p.label}
            </button>
          ))}
        </div>
      </header>

      {error && <p className="uso-error small">Não deu para ler o uso: {error}</p>}
      {!report && !error && <p className="small uso-wait">A primeira leitura de um mês de registros leva uns 10 segundos.</p>}

      {report && (
        <>
          <div className="uso-kpis">
            <Kpi label="Custo equivalente em API" value={usd(report.total.custo)} sub={report.dias > 1 ? `hoje ${usd(report.hoje.custo)}` : `${report.hoje.respostas} respostas`} />
            <Kpi label="Tokens" value={tokens(report.total.tokens)} sub={`saída ${tokens(report.total.saida)} · cache lido ${tokens(report.total.cache_lido)}`} />
            <Kpi label="Respostas" value={report.total.respostas.toLocaleString("pt-BR")} sub={`em ${report.total.sessoes} ${report.total.sessoes === 1 ? "sessão" : "sessões"}`} />
            <Kpi label="Modelo que mais gastou" value={top ? top.nome : "—"} sub={top ? `${share}% do custo · ${usd(top.custo)}` : "nada no período"} />
          </div>

          {report.dias > 1 && (
            <div className="uso-chart-block">
              <div className="uso-chart-bar">
                <span className="uso-chart-title">{metric === "custo" ? "Custo por dia (US$)" : "Tokens por dia"}</span>
                <div className="uso-seg small-seg" role="group" aria-label="Medida">
                  <button type="button" aria-pressed={metric === "custo"} onClick={() => setMetric("custo")}>
                    Custo
                  </button>
                  <button type="button" aria-pressed={metric === "tokens"} onClick={() => setMetric("tokens")}>
                    Tokens
                  </button>
                </div>
              </div>
              <DailyChart report={report} metric={metric} />
            </div>
          )}

          <ModelTable models={report.por_modelo} total={report.total.custo} written={written} />

          {report.por_projeto.length > 0 && (
            <div className="uso-projects">
              <span className="uso-chart-title">Por projeto</span>
              {report.por_projeto.slice(0, 8).map((p) => {
                const max = report.por_projeto[0];
                const value = max.custo > 0 ? p.custo / max.custo : p.tokens / Math.max(1, max.tokens);
                const models = Object.entries(p.modelos)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 2)
                  .map(([name]) => name)
                  .join(", ");
                return (
                  <div key={p.projeto} className="uso-proj">
                    <span className="uso-proj-name" title={p.projeto}>
                      {p.projeto}
                    </span>
                    <span className="uso-proj-bar" aria-hidden="true">
                      <span style={{ width: `${Math.max(2, value * 100)}%` }} />
                    </span>
                    <span className="mono uso-proj-num">{usd(p.custo)}</span>
                    <span className="mono uso-proj-num">{tokens(p.tokens)}</span>
                    <span className="small uso-proj-models">{models}</span>
                  </div>
                );
              })}
            </div>
          )}

          <p className="small uso-note">
            Custo equivalente em API: quanto essas respostas custariam pagando por token (entrada, saída, cache gravado a 1,25× ou 2× e cache lido, pelo preço de
            cada modelo). O plano não cobra assim; o limite dele é o 5h e o 7d das contas abaixo. Do Codex, a CLI registra só o total de tokens.
            {written > 0 && ` Cache gravado no período: ${tokens(written)}.`}
            {report.sem_preco.length > 0 && ` Sem preço conhecido: ${report.sem_preco.join(", ")}.`}
          </p>
        </>
      )}
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="uso-kpi">
      <span className="uso-kpi-label">{label}</span>
      <span className="uso-kpi-value">{value}</span>
      <span className="uso-kpi-sub small">{sub}</span>
    </div>
  );
}

const fmtDay = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

function familyVar(family: Family): string {
  return `var(--uso-${family.toLowerCase()})`;
}

/** Barras empilhadas por dia, uma cor por família; passar o mouse mostra o dia. */
function DailyChart({ report, metric }: { report: ModelUsageReport; metric: "custo" | "tokens" }) {
  const [hover, setHover] = useState<number | null>(null);
  const days = useMemo(
    () =>
      report.por_dia.map((d) => {
        const source = metric === "custo" ? d.modelos : d.tokens_modelos;
        const parts = new Map<Family, number>();
        for (const [label, value] of Object.entries(source ?? {})) {
          const fam = familyOf(label);
          parts.set(fam, (parts.get(fam) ?? 0) + value);
        }
        return { dia: d.dia, parts, total: [...parts.values()].reduce((a, b) => a + b, 0) };
      }),
    [report, metric],
  );
  const present = FAMILIES.filter((f) => days.some((d) => (d.parts.get(f) ?? 0) > 0));
  const max = Math.max(...days.map((d) => d.total), 0);
  const top = niceMax(max);
  const W = 720;
  const H = 190;
  const pad = { l: 52, r: 8, t: 8, b: 22 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;
  const slot = plotW / days.length;
  const barW = Math.max(4, Math.min(28, slot * 0.62));
  const fmt = (v: number) => (metric === "custo" ? (v >= 100 ? `${Math.round(v)}` : v.toFixed(v >= 10 ? 0 : 1).replace(".", ",")) : tokens(v));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * top);
  const every = days.length > 14 ? 5 : 1;
  const hovered = hover != null ? days[hover] : null;

  if (!present.length) return <p className="small uso-wait">Nada no período.</p>;

  return (
    <div className="uso-chart">
      <div className="uso-legend" aria-label="Legenda">
        {present.map((f) => (
          <span key={f} className="uso-legend-item">
            <span className="uso-swatch" style={{ background: familyVar(f) }} />
            {f}
          </span>
        ))}
      </div>
      <div className="uso-plot" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={metric === "custo" ? "Custo por dia" : "Tokens por dia"}>
          {ticks.map((t, i) => {
            const y = pad.t + plotH - (t / (top || 1)) * plotH;
            return (
              <g key={i}>
                <line x1={pad.l} x2={W - pad.r} y1={y} y2={y} className="uso-grid" />
                <text x={pad.l - 6} y={y + 3} className="uso-axis" textAnchor="end">
                  {fmt(t)}
                </text>
              </g>
            );
          })}
          {days.map((d, i) => {
            const x = pad.l + slot * i + (slot - barW) / 2;
            let y = pad.t + plotH;
            const segs = present.filter((f) => (d.parts.get(f) ?? 0) > 0);
            return (
              <g key={d.dia}>
                {segs.map((f, k) => {
                  const h = ((d.parts.get(f) ?? 0) / (top || 1)) * plotH;
                  const gap = k > 0 ? 2 : 0; // 2px de fundo entre os pedaços
                  const height = Math.max(0, h - gap);
                  y -= h;
                  const last = k === segs.length - 1;
                  return last ? (
                    <path key={f} d={roundTop(x, y, barW, height, Math.min(4, height, barW / 2))} fill={familyVar(f)} opacity={hover == null || hover === i ? 1 : 0.45} />
                  ) : (
                    <rect key={f} x={x} y={y + gap} width={barW} height={height} fill={familyVar(f)} opacity={hover == null || hover === i ? 1 : 0.45} />
                  );
                })}
                {(i % every === 0 || i === days.length - 1) && (
                  <text x={x + barW / 2} y={H - 6} className="uso-axis" textAnchor="middle">
                    {fmtDay(d.dia)}
                  </text>
                )}
                <rect x={pad.l + slot * i} y={pad.t} width={slot} height={plotH} fill="transparent" onMouseEnter={() => setHover(i)} />
              </g>
            );
          })}
        </svg>
        {hovered && hover != null && (
          <div className="uso-tip" style={{ left: `${((pad.l + slot * hover + slot / 2) / W) * 100}%` }}>
            <div className="uso-tip-day">
              {fmtDay(hovered.dia)} · {metric === "custo" ? usd(hovered.total) : `${tokens(hovered.total)} tokens`}
            </div>
            {present
              .filter((f) => (hovered.parts.get(f) ?? 0) > 0)
              .map((f) => (
                <div key={f} className="uso-tip-row">
                  <span className="uso-swatch" style={{ background: familyVar(f) }} />
                  <span>{f}</span>
                  <span className="mono">{metric === "custo" ? usd(hovered.parts.get(f) ?? 0) : tokens(hovered.parts.get(f) ?? 0)}</span>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}

function roundTop(x: number, y: number, w: number, h: number, r: number): string {
  if (h <= 0) return "";
  const rr = Math.max(0, r);
  return `M${x},${y + h} L${x},${y + rr} Q${x},${y} ${x + rr},${y} L${x + w - rr},${y} Q${x + w},${y} ${x + w},${y + rr} L${x + w},${y + h} Z`;
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(value)));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * exp >= value) return step * exp;
  return 10 * exp;
}

function ModelTable({ models, total, written }: { models: ModelUsageModel[]; total: number; written: number }) {
  if (!models.length) return null;
  return (
    <div className="uso-table-wrap">
      <table className="uso-table">
        <thead>
          <tr>
            <th scope="col">Modelo</th>
            <th scope="col" className="num">
              Respostas
            </th>
            <th scope="col" className="num">
              Entrada
            </th>
            <th scope="col" className="num">
              Saída
            </th>
            <th scope="col" className="num" title={written ? "Cache gravado (5 min + 1 h)" : undefined}>
              Cache gravado
            </th>
            <th scope="col" className="num">
              Cache lido
            </th>
            <th scope="col" className="num">
              Custo
            </th>
            <th scope="col">Parte do custo</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => {
            const part = total > 0 ? m.custo / total : 0;
            const codexOnlyTotal = m.provedor === "codex" && !m.entrada && !m.saida;
            return (
              <tr key={`${m.provedor}:${m.modelo}`}>
                <th scope="row">
                  <span className="uso-model">
                    <span className="uso-swatch" style={{ background: familyVar(familyOf(m.nome, m.provedor)) }} />
                    <KindIcon kind={m.provedor} size={13} />
                    {m.nome}
                    <span className="small uso-sessions">{m.sessoes} sess.</span>
                  </span>
                </th>
                <td className="num mono">{m.respostas.toLocaleString("pt-BR")}</td>
                {codexOnlyTotal ? (
                  <td className="num mono uso-total-only" colSpan={4}>
                    {tokens(m.tokens)} tokens no total
                  </td>
                ) : (
                  <>
                    <td className="num mono">{tokens(m.entrada)}</td>
                    <td className="num mono">{tokens(m.saida)}</td>
                    <td className="num mono">{tokens(m.cache_5m + m.cache_1h)}</td>
                    <td className="num mono">{tokens(m.cache_lido)}</td>
                  </>
                )}
                <td className="num mono">{m.provedor === "codex" ? "—" : usd(m.custo)}</td>
                <td>
                  {m.provedor === "claude" && (
                    <span className="uso-share-cell">
                      <span className="uso-share" aria-hidden="true">
                        <span style={{ width: `${Math.max(part > 0 ? 2 : 0, part * 100)}%`, background: familyVar(familyOf(m.nome, m.provedor)) }} />
                      </span>
                      <span className="mono small">{part >= 0.995 ? "100" : part < 0.01 && part > 0 ? "<1" : Math.round(part * 100)}%</span>
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
