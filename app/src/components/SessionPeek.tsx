import { useEffect, useRef, useState } from "react";
import { KindIcon } from "./KindIcon";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import type { Session } from "../types";

/**
 * Espiada numa sessão de agente (v0.9.9): a conversa (as últimas mensagens do transcript) e
 * uma caixa que manda a resposta direto para o terminal dela. Serve à gaveta do Brain e ao
 * Sócrates do Estudo, sem tirar o terminal de verdade do lugar.
 */

interface Props {
  client: CoreClient;
  session: Session;
  placeholder?: string;
  /** Texto pronto para mandar (ex.: a resposta de uma pergunta do Sócrates). */
  draft?: string | null;
  onDraftUsed?: () => void;
  onError: (message: string) => void;
  onOpen?: () => void;
}

interface Message {
  who: "voce" | "agente";
  text: string;
}

function parse(text: string): Message[] {
  if (!text.trim()) return [];
  return text
    .split(/\n\n(?=(?:você|agente): )/)
    .map((part) => {
      const agent = part.startsWith("agente: ");
      return { who: agent ? "agente" : "voce", text: part.replace(/^(?:você|agente): /, "").trim() } as Message;
    })
    .filter((m) => m.text);
}

export function SessionPeek({ client, session, placeholder, draft, onDraftUsed, onError, onOpen }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (draft == null) return;
    setText(draft);
    onDraftUsed?.();
    window.setTimeout(() => input.current?.focus(), 20);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  // A conversa: na abertura, a cada mudança de estado da sessão e, enquanto trabalha, a cada 2,5 s.
  useEffect(() => {
    let alive = true;
    const load = () =>
      void client
        .sessionContext(session.id)
        .then((ctx) => alive && setMessages(parse(ctx.texto ?? "")))
        .catch(() => undefined);
    load();
    const timer = session.status === "working" ? window.setInterval(load, 2500) : 0;
    return () => {
      alive = false;
      if (timer) window.clearInterval(timer);
    };
  }, [client, session.id, session.status, session.status_desde]);

  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight });
  }, [messages]);

  const send = async () => {
    const value = text.trim();
    if (!value || sending) return;
    setSending(true);
    try {
      await client.sendToSession(session.id, value);
      setText("");
      setMessages((all) => [...all, { who: "voce", text: value }]);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSending(false);
    }
  };

  const status =
    session.status === "working" ? "trabalhando…" : session.status === "waiting" ? "esperando você" : session.status === "exited" ? "saiu" : "parado";

  return (
    <div className="peek">
      <div className="peek-log mono" ref={box}>
        {messages.length === 0 && <p className="peek-empty">Nada dito ainda nesta conversa.</p>}
        {messages.slice(-12).map((m, i) => (
          <p key={i} className="peek-msg" data-who={m.who}>
            <span className="peek-mark" aria-hidden="true">
              {m.who === "voce" ? ">" : "●"}
            </span>
            {m.text}
          </p>
        ))}
        <p className="peek-status" data-status={session.status}>
          <span className="peek-mark" aria-hidden="true">
            <KindIcon kind={session.kind} size={13} />
          </span>
          {status}
          {onOpen && (
            <button type="button" className="peek-open" onClick={onOpen}>
              abrir o terminal ›
            </button>
          )}
        </p>
      </div>
      <form
        className="peek-input"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <textarea
          ref={input}
          rows={2}
          value={text}
          disabled={session.status === "exited"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={session.status === "exited" ? "A sessão saiu." : (placeholder ?? "Responda ao agente…")}
          aria-label="Mensagem para o agente"
        />
        <button type="submit" className="peek-send" aria-label="Enviar" disabled={!text.trim() || sending || session.status === "exited"}>
          <Icon d={ICON.up} size={13} strokeWidth={2.4} />
        </button>
      </form>
    </div>
  );
}
