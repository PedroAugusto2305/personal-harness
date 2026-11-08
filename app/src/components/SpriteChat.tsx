import { useEffect, useRef, useState } from "react";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import { clock } from "../lib/format";
import type { SpriteJob } from "../types";

interface Message {
  id: string;
  role: "voce" | "metis";
  text?: string;
  job?: SpriteJob;
}

interface Props {
  client: CoreClient | null;
  name: string;
  description: string;
  color: string;
  /** A sprite escolhida no chat (para agente novo, aplica ao criar). */
  chosen: string | null;
  onUse: (jobId: string) => void;
}

const IDEAS = ["guerreira espartana com lança e escudo", "filósofo de barba longa com pergaminho", "sacerdotisa com lira e coroa de louros"];

/**
 * Chat da sprite: você descreve, o Codex desenha e a MÊTIS pixeliza em 32 × 32.
 * Sempre no estilo greco-romano. Com uma sprite pronta, a próxima mensagem a ajusta.
 */
export function SpriteChat({ client, name, description, color, chosen, onUse }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [editing, setEditing] = useState(true);
  const [now, setNow] = useState(Date.now());
  const list = useRef<HTMLDivElement>(null);

  const running = messages.find((m) => m.job?.status === "running")?.job ?? null;
  const lastDone = [...messages].reverse().find((m) => m.job?.status === "done")?.job ?? null;
  const base = editing ? lastDone : null;

  // Acompanha o trabalho em andamento.
  useEffect(() => {
    if (!running || !client) return;
    const timer = window.setInterval(async () => {
      setNow(Date.now());
      try {
        const job = await client.spriteJob(running.id);
        if (job.status !== "running") {
          setMessages((all) => all.map((m) => (m.job?.id === job.id ? { ...m, job } : m)));
        }
      } catch {
        // núcleo reiniciou: o trabalho se perdeu
        setMessages((all) =>
          all.map((m) => (m.job?.id === running.id ? { ...m, job: { ...running, status: "error", error: "o núcleo reiniciou no meio do desenho" } } : m)),
        );
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [running, client]);

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, running?.status]);

  const send = async (text: string) => {
    const prompt = text.trim();
    if (!prompt || !client || running) return;
    setInput("");
    const mine: Message = { id: `u${Date.now()}`, role: "voce", text: prompt };
    setMessages((all) => [...all, mine]);
    try {
      const job = await client.startSprite({ prompt, name, description, color, base: base?.id ?? null });
      setMessages((all) => [...all, { id: job.id, role: "metis", job }]);
      setEditing(true);
    } catch (cause) {
      setMessages((all) => [...all, { id: `e${Date.now()}`, role: "metis", text: cause instanceof Error ? cause.message : String(cause) }]);
    }
  };

  return (
    <div className="sprite-chat card">
      <div className="sprite-chat-head">
        <span className="setting-label">Criar a sprite por prompt</span>
        <span className="small">Estilo greco-romano sempre · o Codex desenha (usa o seu plano) e a MÊTIS deixa em pixel art 32 × 32</span>
      </div>
      <div className="sprite-chat-list" ref={list}>
        {messages.length === 0 && (
          <div className="sprite-ideas">
            {IDEAS.map((idea) => (
              <button key={idea} type="button" className="pill" onClick={() => void send(idea)} disabled={!client}>
                {idea}
              </button>
            ))}
          </div>
        )}
        {messages.map((message) =>
          message.role === "voce" ? (
            <div key={message.id} className="bubble mine">
              {message.text}
            </div>
          ) : (
            <div key={message.id} className="bubble theirs">
              {message.text && <span className="error-text">{message.text}</span>}
              {message.job?.status === "running" && (
                <span className="drawing">
                  <span className="rec-dot" aria-hidden="true" />
                  {message.job.base ? "ajustando" : "desenhando"} com o Codex… {clock((now - message.job.created_at * 1000) / 1000)}
                </span>
              )}
              {message.job?.status === "error" && <span className="error-text">Não deu: {message.job.error}</span>}
              {message.job?.status === "done" && client && (
                <div className="sprite-result">
                  <img className="pixel sprite-preview" src={client.spriteJobUrl(message.job.id)} width={96} height={96} alt="Sprite gerada" />
                  <div className="sprite-result-side">
                    {message.job.note && <span className="small">{message.job.note}</span>}
                    <div className="form-buttons">
                      <button
                        type="button"
                        className={chosen === message.job.id ? "btn" : "btn primary"}
                        disabled={chosen === message.job.id}
                        onClick={() => onUse(message.job!.id)}
                      >
                        <Icon d={ICON.check} size={13} strokeWidth={2.2} />
                        {chosen === message.job.id ? "Em uso" : "Usar esta"}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ),
        )}
      </div>
      {/* Sem <form>: o chat fica dentro do formulário do agente, e form dentro de form recarrega a página. */}
      <div className="sprite-chat-input">
        {base && (
          <button type="button" className="chip on" title="A próxima mensagem ajusta esta sprite. Clique para começar outra do zero." onClick={() => setEditing(false)}>
            ajustando a última ×
          </button>
        )}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={base ? "O que mudar? Ex.: elmo mais dourado, manto mais longo" : "Descreva o personagem. Ex.: estrategista com elmo coríntio e pergaminho"}
          disabled={!client || !!running}
          maxLength={2000}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void send(input);
            }
          }}
        />
        <button type="button" className="send" onClick={() => void send(input)} disabled={!input.trim() || !client || !!running} aria-label="Gerar sprite" title="Gerar sprite">
          <Icon d={ICON.send} size={15} strokeWidth={2.2} />
        </button>
      </div>
    </div>
  );
}
