import { useEffect, useState } from "react";
import type { CoreClient } from "../lib/core";
import { formatSize, playable } from "../lib/composer";
import { ICON, Icon } from "../icons";
import type { AttachmentKind } from "../types";

/*
 * v1.7.0: a prévia de um anexo, na barra (antes de enviar, com o × para tirar) e na sua mensagem
 * da conversa (depois de enviada). Imagem vira miniatura; vídeo, um quadro com ▶; PDF, texto e
 * documento, a miniatura do QuickLook; o resto, ícone do tipo, nome e tamanho. Clicar abre a
 * prévia grande: a imagem inteira, o player do vídeo e do áudio, ou a miniatura com o Finder.
 */

export const KIND_ICON: Record<AttachmentKind, string> = {
  imagem: ICON.image,
  video: ICON.video,
  audio: ICON.audio,
  pdf: ICON.pdf,
  planilha: ICON.sheet,
  apresentacao: ICON.slides,
  documento: ICON.file,
  compactado: ICON.archive,
  codigo: ICON.code,
  arquivo: ICON.file,
};

export const KIND_NAME: Record<AttachmentKind, string> = {
  imagem: "Imagem",
  video: "Vídeo",
  audio: "Áudio",
  pdf: "PDF",
  planilha: "Planilha",
  apresentacao: "Apresentação",
  documento: "Documento",
  compactado: "Compactado",
  codigo: "Código",
  arquivo: "Arquivo",
};

export interface PreviewItem {
  /** Caminho no disco: é o que o agente recebe. Vazio enquanto o arquivo sobe. */
  caminho?: string;
  nome: string;
  tipo: AttachmentKind;
  tamanho?: number | null;
  /** Imagem colada ou escolhida: aparece na hora, pela URL local, antes de o núcleo responder. */
  local?: string;
}

/** A miniatura (local, do núcleo) ou, enquanto ela vem e quando não há desenho, o ícone do tipo. */
export function AttachmentThumb({ client, item, px }: { client: CoreClient | null; item: PreviewItem; px: number }) {
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const url = item.local ?? (item.caminho && client && item.tipo !== "compactado" ? client.attachmentThumbUrl(item.caminho, px * 2) : null);
  useEffect(() => setState("loading"), [url]);
  return (
    <>
      {state !== "ok" && (
        <span className="att-icon" data-kind={item.tipo}>
          <Icon d={KIND_ICON[item.tipo]} size={Math.round(px * 0.42)} strokeWidth={1.6} />
        </span>
      )}
      {url && state !== "error" && (
        <img src={url} alt="" draggable={false} data-state={state} onLoad={() => setState("ok")} onError={() => setState("error")} />
      )}
    </>
  );
}

/**
 * Um anexo como cartão: imagem em miniatura quadrada; vídeo com o quadro e o ▶; os outros com a
 * miniatura (ou o ícone), o nome e "PDF · 1,2 MB". `onRemove` põe o × (só na barra).
 */
export function AttachmentCard({
  client,
  item,
  state = "pronto",
  error,
  onOpen,
  onRemove,
}: {
  client: CoreClient | null;
  item: PreviewItem;
  state?: "enviando" | "pronto" | "erro";
  error?: string | null;
  onOpen?: () => void;
  onRemove?: () => void;
}) {
  const square = item.tipo === "imagem" && state !== "erro";
  const sub = state === "erro" ? (error ?? "não deu para anexar") : state === "enviando" ? "anexando…" : [KIND_NAME[item.tipo], formatSize(item.tamanho)].filter(Boolean).join(" · ");
  return (
    <div className="att-card" data-kind={item.tipo} data-state={state} data-square={square || undefined} title={item.caminho || item.nome}>
      <button type="button" className="att-open" onClick={onOpen} disabled={!onOpen || state === "erro"} aria-label={`Ver ${item.nome}`}>
        <span className="att-thumb">
          <AttachmentThumb client={client} item={item} px={square ? 56 : 40} />
          {item.tipo === "video" && state !== "erro" && (
            <span className="att-play" aria-hidden="true">
              <Icon d={ICON.play} size={10} strokeWidth={2} />
            </span>
          )}
          {state === "enviando" && <span className="att-busy" aria-label="anexando" />}
        </span>
        {!square && (
          <span className="att-meta">
            <span className="att-name">{item.nome}</span>
            <span className="att-sub">{sub}</span>
          </span>
        )}
      </button>
      {onRemove && (
        <button type="button" className="att-remove" onClick={onRemove} title="Tirar este anexo" aria-label={`Tirar ${item.nome}`}>
          <Icon d={ICON.close} size={10} strokeWidth={2.4} />
        </button>
      )}
    </div>
  );
}

/** A prévia grande, por cima da janela: imagem inteira, player de vídeo e áudio, ou a miniatura. */
export function AttachmentViewer({ client, item, onClose }: { client: CoreClient | null; item: PreviewItem; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  const file = item.caminho && client ? client.attachmentFileUrl(item.caminho) : null;
  const whole = playable(item.tipo, item.nome);
  return (
    <div className="att-viewer" role="dialog" aria-label={item.nome} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="chat-box-bar">
        <span className="chat-box-title">
          {item.nome}
          <span className="small"> · {[KIND_NAME[item.tipo], formatSize(item.tamanho)].filter(Boolean).join(" · ")}</span>
        </span>
        {item.caminho && client && (
          <button type="button" className="chat-mini" onClick={() => void client.open({ reveal: item.caminho }).catch(() => undefined)}>
            <Icon d={ICON.folder} size={12} strokeWidth={2} /> Mostrar no Finder
          </button>
        )}
        <button type="button" className="icon-btn" onClick={onClose} title="Fechar (Esc)" aria-label="Fechar">
          <Icon d={ICON.close} size={14} strokeWidth={2} />
        </button>
      </div>
      <div className="chat-box-stage" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
        {item.tipo === "video" && file ? (
          <video src={file} controls autoPlay playsInline />
        ) : item.tipo === "audio" && file ? (
          <audio src={file} controls autoPlay />
        ) : item.tipo === "imagem" && (item.local || (whole && file)) ? (
          <img src={item.local ?? file ?? undefined} alt={item.nome} />
        ) : (
          <div className="att-viewer-file">
            <span className="att-viewer-thumb">
              <AttachmentThumb client={client} item={item} px={256} />
            </span>
            <span className="small">Sem prévia completa aqui: o agente recebe o arquivo do mesmo jeito.</span>
          </div>
        )}
      </div>
    </div>
  );
}
