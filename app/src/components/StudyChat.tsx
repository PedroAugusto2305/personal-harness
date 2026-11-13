import { useEffect, useRef, useState } from "react";
import { ChatView } from "./ChatView";
import { ICON, Icon } from "../icons";
import type { CoreClient } from "../lib/core";
import type { Session, ThemeName } from "../types";

/**
 * O chat do Estudo (v1.3.0): a conversa do agente de estudo desenhada do transcript, a mesma da v1.2.0
 * (Markdown, fluxogramas Mermaid, tabelas e imagens na própria conversa), com a caixa de
 * mensagem logo abaixo. Antes, o painel era a espiada em texto puro (SessionPeek), e o diagrama
 * chegava como código. O terminal de verdade continua na tela Terminais.
 */

interface Props {
  client: CoreClient;
  /** O agente de estudo conectado. */
  agentName: string;
  session: Session;
  theme: ThemeName;
  /** O painel aparece (aba Estudo na tela): só então a conversa pergunta ao núcleo. */
  visible: boolean;
  /** Texto pronto para a caixa (ex.: um tema sugerido pelo NotebookLM). */
  draft?: string | null;
  onDraftUsed?: () => void;
  onError: (message: string) => void;
  onOpenTerminal: () => void;
  onLink?: (url: string, external: boolean) => void;
  onOpenFile?: (path: string) => void;
}

export function StudyChat({ client, agentName, session, theme, visible, draft, onDraftUsed, onError, onOpenTerminal, onLink, onOpenFile }: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (draft == null) return;
    setText(draft);
    onDraftUsed?.();
    window.setTimeout(() => input.current?.focus(), 20);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  const send = async () => {
    const value = text.trim();
    if (!value || sending) return;
    setSending(true);
    try {
      await client.sendToSession(session.id, value);
      setText("");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSending(false);
    }
  };

  const exited = session.status === "exited";
  return (
    <div className="sv-chat">
      <div className="sv-chat-log">
        <ChatView
          session={session}
          client={client}
          theme={theme}
          visible={visible}
          searchOpen={false}
          onCloseSearch={() => undefined}
          onLink={onLink}
          onOpenFile={onOpenFile}
          onFocusInput={() => input.current?.focus()}
          onShowTerminal={onOpenTerminal}
        />
      </div>
      <form
        className="peek-input sv-chat-input"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <textarea
          ref={input}
          rows={2}
          value={text}
          disabled={exited}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={exited ? "A sessão saiu." : `Pergunte a ${agentName} (ex.: me explica com um diagrama)…`}
          aria-label={`Mensagem para ${agentName}`}
        />
        <button type="submit" className="peek-send" aria-label="Enviar" disabled={!text.trim() || sending || exited}>
          <Icon d={ICON.up} size={13} strokeWidth={2.4} />
        </button>
      </form>
    </div>
  );
}
