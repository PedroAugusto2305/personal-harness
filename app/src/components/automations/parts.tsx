// Pedaços de desenho das Automações: elementos de conector, ícone de cada passo, rosto do agente,
// expressões como peças verdes e a tabela/JSON dos dados de uma execução.

import type { ReactNode } from "react";
import { ICON, Icon, MetisMark } from "../../icons";
import type { CoreClient } from "../../lib/core";
import { KIND_COLOR } from "../../lib/format";
import type { Agent, AutoStep } from "../../types";
import { AgentSprite } from "../AgentSprite";
import { type Elem, type Kind, KIND, isPlain, toolElem } from "./model";

export function ElemMark({ elem, size = 14 }: { elem: Elem; size?: number }) {
  if (elem.metis) return <MetisMark size={Math.round(size * 1.15)} />;
  return (
    <span className="af-elem" style={{ color: elem.color, fontSize: size }}>
      {elem.mono}
    </span>
  );
}

/** Rosto do agente: a sprite da galeria, ou ✻ do Claude e ◇ do Codex. */
export function AgentFace({ step, agents, client, size = 32 }: { step: AutoStep; agents: Agent[]; client: CoreClient | null; size?: number }) {
  const agent = step.agente ? agents.find((a) => a.id === step.agente) : undefined;
  if (agent) return <AgentSprite agent={agent} client={client} size={size} />;
  const cli = step.cli ?? "claude";
  return (
    <span className="af-cli" style={{ color: KIND_COLOR[cli], fontSize: Math.round(size * 0.8) }}>
      {cli === "codex" ? "◇" : "✻"}
    </span>
  );
}

export function Glyph({
  kind,
  step,
  agents,
  client,
  size = 30,
}: {
  kind: Kind;
  step: AutoStep | null;
  agents: Agent[];
  client: CoreClient | null;
  size?: number;
}) {
  if (kind === "ferramenta" && step) {
    if (!step.ferramenta) return <Icon d={ICON.plug} size={size} strokeWidth={1.6} />;
    return <ElemMark elem={toolElem(step.ferramenta)} size={Math.round(size * 0.7)} />;
  }
  if (kind === "agente" && step) return <AgentFace step={step} agents={agents} client={client} size={size >= 30 ? 32 : 18} />;
  return <Icon d={KIND[kind].icon ?? ICON.plug} size={size} strokeWidth={1.6} />;
}

/** Expressões {{…}} aparecem como peças, para ficar claro o que vem de outro passo. */
export function Expr({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\{\{[^}]+\}\})/g).map((part, i) =>
        /^\{\{[^}]+\}\}$/.test(part) ? (
          <span key={i} className="af-expr mono">
            {part.slice(2, -2).trim()}
          </span>
        ) : (
          part
        ),
      )}
    </>
  );
}

export const hasExpr = (text: unknown) => typeof text === "string" && /\{\{[^}]+\}\}/.test(text);

function cellText(v: unknown) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Table({ rows }: { rows: Record<string, unknown>[] }) {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  return (
    <div className="af-table-wrap">
      <table className="af-table">
        <thead>
          <tr>
            <th>#</th>
            {cols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="mono af-rownum">{i + 1}</td>
              {cols.map((c) => (
                <td key={c} data-num={typeof r[c] === "number" ? "true" : undefined} title={cellText(r[c])}>
                  {cellText(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export type DataMode = "tabela" | "json";

export function DataView({ value, view }: { value: unknown; view: DataMode }) {
  if (value === null || value === undefined) return <p className="af-empty-note">vazio</p>;
  if (view === "json" || typeof value !== "object") {
    return <pre className="af-json mono">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>;
  }
  if (Array.isArray(value)) {
    if (value.length && value.every(isPlain)) return <Table rows={value} />;
    return <pre className="af-json mono">{JSON.stringify(value, null, 2)}</pre>;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  const isRows = (v: unknown) => Array.isArray(v) && v.length > 0 && v.every(isPlain);
  const nested = entries.filter(([, v]) => isRows(v));
  const flat = entries.filter(([, v]) => !isRows(v));
  return (
    <>
      {flat.length > 0 && <Table rows={[Object.fromEntries(flat)]} />}
      {nested.map(([k, v]) => (
        <div key={k} className="af-nested">
          <span className="af-caps">{k}</span>
          <Table rows={v as Record<string, unknown>[]} />
        </div>
      ))}
    </>
  );
}

export function Segment<T extends string>({
  value,
  options,
  onChange,
  disabled,
}: {
  value: T;
  options: [T, string][];
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="af-seg">
      {options.map(([v, label]) => (
        <button key={v} type="button" aria-pressed={value === v} disabled={disabled} onClick={() => onChange(v)}>
          {label}
        </button>
      ))}
    </div>
  );
}

/** Campo do painel: rótulo em cima, dica embaixo. Com `group`, não é um <label> (vários controles dentro). */
export function Field({ label, hint, children, group }: { label: ReactNode; hint?: ReactNode; children: ReactNode; group?: boolean }) {
  const body = (
    <>
      <span className="af-field-label">{label}</span>
      {children}
      {hint && <span className="af-field-hint">{hint}</span>}
    </>
  );
  return group ? <div className="af-field">{body}</div> : <label className="af-field">{body}</label>;
}
