import { useMemo, useState } from "react";
import { renderNote } from "../lib/obsidian";
import type { BrainNote } from "../types";

/**
 * Nota de estudo (v0.9.9, mockup "Estudo · B"): as propriedades no topo, como no Obsidian, e
 * cada bloco `> [!pergunta]` que o Sócrates escreve (ferramenta estudo_pergunta) vira um
 * formulário: alternativas, a régua de confiança e o raciocínio. Responder manda a resposta
 * ao Sócrates e marca a alternativa na nota.
 */

export interface QuestionBlock {
  kind: "q";
  /** Ordem do bloco na nota (0 = o primeiro [!pergunta]). */
  index: number;
  title: string;
  question: string;
  options: { text: string; done: boolean }[];
  answer: string;
}

type Segment = { kind: "md"; text: string } | QuestionBlock;

const OPEN = /^>\s*\[!pergunta\][+-]?\s*(.*)$/i;
const OPTION = /^>\s*-\s*\[( |x|X)\]\s*(.*)$/;

export function splitQuestions(body: string): Segment[] {
  const lines = body.split("\n");
  const out: Segment[] = [];
  let md: string[] = [];
  let index = 0;
  for (let i = 0; i < lines.length; i++) {
    const head = OPEN.exec(lines[i]);
    if (!head) {
      md.push(lines[i]);
      continue;
    }
    if (md.length) out.push({ kind: "md", text: md.join("\n") });
    md = [];
    const block: QuestionBlock = { kind: "q", index: index++, title: head[1] || "Pergunta · Sócrates", question: "", options: [], answer: "" };
    while (i + 1 < lines.length && lines[i + 1].startsWith(">")) {
      const line = lines[++i];
      const option = OPTION.exec(line);
      if (option) block.options.push({ text: option[2].trim(), done: option[1].toLowerCase() === "x" });
      else if (/^>\s*Resposta:/i.test(line)) block.answer = line.replace(/^>\s*Resposta:\s*/i, "").trim();
      else block.question = `${block.question} ${line.replace(/^>\s?/, "")}`.trim();
    }
    out.push(block);
  }
  if (md.length) out.push({ kind: "md", text: md.join("\n") });
  return out;
}

/** Marca a alternativa escolhida no n-ésimo bloco e guarda a confiança e o raciocínio. */
export function markAnswer(text: string, index: number, option: string, summary: string): string {
  const lines = text.split("\n");
  let seen = -1;
  for (let i = 0; i < lines.length; i++) {
    if (!OPEN.test(lines[i])) continue;
    seen++;
    if (seen !== index) continue;
    let end = i;
    while (end + 1 < lines.length && lines[end + 1].startsWith(">")) {
      end++;
      const m = OPTION.exec(lines[end]);
      if (m && m[2].trim() === option) lines[end] = lines[end].replace(/\[( |x|X)\]/, "[x]");
    }
    lines.splice(end + 1, 0, `> Resposta: ${summary.replace(/\s+/g, " ").trim()}`);
    return lines.join("\n");
  }
  return text;
}

/** Campos internos do mapa de estudo: a tela mostra o domínio e a próxima revisão. */
const HIDDEN_META = new Set(["aliases", "cssclasses", "intervalo_dias", "sequencia", "confianca_media", "calibracao", "criado", "atualizado", "acertos", "erros"]);
const DOMAIN = ["não vi", "já ouvi falar", "entendo com ajuda", "consigo usar", "consigo ensinar"];

interface Props {
  note: BrainNote;
  /** Há um Sócrates aberto para receber a resposta. */
  canAnswer: boolean;
  onAnswer: (block: QuestionBlock, option: number, confidence: number, reasoning: string) => Promise<void>;
  onLink: (event: React.MouseEvent) => void;
}

export function StudyNote({ note, canAnswer, onAnswer, onLink }: Props) {
  const segments = useMemo(() => splitQuestions(note.body.replace(/^\s*# [^\n]*\n/, "")), [note.body]);
  const props = Object.entries(note.meta).filter(([k, v]) => v && !HIDDEN_META.has(k));
  return (
    <div className="sn">
      {props.length > 0 && (
        <section className="sn-props" aria-label="Propriedades">
          <span className="sn-props-title">Propriedades</span>
          {props.map(([key, value]) => (
            <div key={key} className="sn-prop">
              <span className="sn-prop-key">{key}</span>
              <span className="sn-prop-value">
                {key === "tags"
                  ? value
                      .replace(/[[\]]/g, "")
                      .split(/[,\s]+/)
                      .filter(Boolean)
                      .map((t) => (
                        <span key={t} className="sn-tag">
                          #{t.replace(/^#/, "")}
                        </span>
                      ))
                  : key === "dominio" && DOMAIN[Number(value)]
                    ? `${value} · ${DOMAIN[Number(value)]}${note.meta.acertos || note.meta.erros ? ` (${note.meta.acertos || 0} acertos, ${note.meta.erros || 0} erros)` : ""}`
                    : value.replace(/^\[\[|\]\]$/g, "")}
              </span>
            </div>
          ))}
        </section>
      )}
      <div onClick={onLink}>
        {segments.map((seg, i) =>
          seg.kind === "md" ? (
            <div key={i} className="markdown brain-markdown" dangerouslySetInnerHTML={{ __html: renderNote(seg.text) }} />
          ) : (
            <Question key={`q-${seg.index}-${note.path}`} block={seg} canAnswer={canAnswer} onAnswer={onAnswer} />
          ),
        )}
      </div>
    </div>
  );
}

function Question({ block, canAnswer, onAnswer }: { block: QuestionBlock; canAnswer: boolean; onAnswer: Props["onAnswer"] }) {
  const answered = block.options.findIndex((o) => o.done);
  const [choice, setChoice] = useState<number>(answered);
  const [confidence, setConfidence] = useState(60);
  const [reasoning, setReasoning] = useState("");
  const [busy, setBusy] = useState(false);
  const done = answered >= 0;
  return (
    <form
      className="sq"
      data-done={done ? "true" : undefined}
      onSubmit={async (event) => {
        event.preventDefault();
        if (choice < 0 || busy || done) return;
        setBusy(true);
        try {
          await onAnswer(block, choice, confidence, reasoning);
        } finally {
          setBusy(false);
        }
      }}
    >
      <span className="sq-title">
        <span className="sq-icon" aria-hidden="true">
          ?
        </span>
        {block.title}
      </span>
      <p className="sq-question">{block.question}</p>
      <div className="sq-options" role="radiogroup" aria-label={block.question}>
        {block.options.map((option, i) => (
          <label key={i} className="sq-option" data-on={choice === i ? "true" : undefined}>
            <input type="radio" name={`q-${block.index}`} checked={choice === i} disabled={done} onChange={() => setChoice(i)} />
            <span>{option.text}</span>
          </label>
        ))}
      </div>
      {done ? (
        <p className="sq-answered">Respondida{block.answer ? ` · ${block.answer}` : ""}</p>
      ) : (
        <>
          <label className="sq-confidence">
            <span>Confiança</span>
            <input type="range" min={0} max={100} step={5} value={confidence} onChange={(e) => setConfidence(Number(e.target.value))} />
            <span className="mono">{confidence}%</span>
          </label>
          <label className="sq-reason">
            <span>Seu raciocínio</span>
            <textarea rows={2} value={reasoning} onChange={(e) => setReasoning(e.target.value)} placeholder="Por que essa resposta? Escreva ou fale." />
          </label>
          <div className="sq-actions">
            {!canAnswer && <span className="sq-hint">Abra uma sessão com o Sócrates (à direita) para a resposta chegar a ele.</span>}
            <button type="submit" className="sq-send" disabled={choice < 0 || busy || !canAnswer}>
              {busy ? "Mandando…" : "Responder"}
            </button>
          </div>
        </>
      )}
    </form>
  );
}
