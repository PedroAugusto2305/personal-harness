import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { Recording, micError } from "../lib/audio";
import type { CoreClient } from "../lib/core";
import { KIND_COLOR, KIND_GLYPH } from "../lib/format";
import { quotePaths, submit, terminals } from "../lib/terminals";
import { ICON, Icon } from "../icons";
import type { Session } from "../types";
import { Waveform } from "./Waveform";

const MAX_SECONDS = 300;

type VoiceState = "idle" | "starting" | "recording" | "transcribing";

export interface DockHandle {
  /** Acrescenta texto no campo (ditado, caminho de anexo). */
  insert(text: string): void;
  toggleVoice(): void;
  focus(): void;
}

interface Props {
  client: CoreClient | null;
  target: Session | null;
  targetAccount: string | null;
  language: string;
  dropping: boolean;
  ref?: Ref<DockHandle>;
}

/**
 * Barra de entrada: escreve ou dita, revisa e manda para o terminal em foco.
 * ⏎ cola e envia, ⌥⏎ só cola, ⇧⏎ quebra linha. O microfone vira onda enquanto grava.
 */
export function Dock({ client, target, targetAccount, language, dropping, ref }: Props) {
  const [text, setText] = useState("");
  const [voice, setVoice] = useState<VoiceState>("idle");
  const [recording, setRecording] = useState<Recording | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const files = useRef<HTMLInputElement>(null);
  const voiceRef = useRef(voice);
  voiceRef.current = voice;
  const recRef = useRef(recording);
  recRef.current = recording;

  const insert = (value: string) => {
    const clean = value.trim();
    if (!clean) return;
    setText((current) => (current && !/\s$/.test(current) ? `${current} ${clean}` : current + clean));
    requestAnimationFrame(() => {
      const el = field.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  };

  const start = async () => {
    if (!client) return;
    setError(null);
    setVoice("starting");
    client.prepareVoice().catch(() => undefined); // o modelo carrega enquanto você fala
    try {
      const rec = await Recording.start();
      setRecording(rec);
      setVoice("recording");
    } catch (cause) {
      setVoice("idle");
      setError(micError(cause));
    }
  };

  const stop = async () => {
    const rec = recRef.current;
    if (!rec || !client) return;
    setRecording(null);
    setVoice("transcribing");
    try {
      const wav = await rec.stop();
      const spoken = await client.transcribe(wav, language);
      if (spoken) insert(spoken);
      else setError("Não deu para ouvir nada. Tente de novo mais perto do microfone.");
    } catch (cause) {
      setError(`Falha ao transcrever: ${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setVoice("idle");
    }
  };

  const cancel = async () => {
    const rec = recRef.current;
    setRecording(null);
    setVoice("idle");
    await rec?.cancel();
  };

  const toggleVoice = () => {
    if (voiceRef.current === "idle") void start();
    else if (voiceRef.current === "recording") void stop();
  };

  useImperativeHandle(ref, () => ({ insert, toggleVoice, focus: () => field.current?.focus() }));

  // Esc cancela a gravação; a gravação para sozinha em 5 minutos.
  useEffect(() => {
    if (voice !== "recording" || !recording) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        void cancel();
      }
    };
    const limit = window.setTimeout(() => void stop(), MAX_SECONDS * 1000);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.clearTimeout(limit);
      window.removeEventListener("keydown", onKey, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice, recording]);

  // Campo cresce com o texto até umas 8 linhas.
  useEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  const deliver = (andSend: boolean) => {
    const value = text.trim();
    if (!value) return;
    if (!target || !terminals.has(target.id)) {
      setError("Abra um terminal para receber o texto.");
      return;
    }
    if (andSend) submit(target.id, value);
    else {
      terminals.get(target.id)!.paste(value);
      terminals.get(target.id)!.focus();
    }
    setText("");
    setError(null);
  };

  const attach = async (list: FileList | null) => {
    if (!client || !list?.length) return;
    setBusy(list.length === 1 ? "enviando anexo…" : `enviando ${list.length} anexos…`);
    setError(null);
    try {
      const paths = await Promise.all(Array.from(list).map((file) => client.upload(file, file.name)));
      insert(quotePaths(paths));
    } catch (cause) {
      setError(`Falha no anexo: ${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setBusy(null);
      if (files.current) files.current.value = "";
    }
  };

  const recordingNow = voice === "recording" && recording;
  const placeholder = !target
    ? "Abra um terminal para escrever ou ditar para ele…"
    : voice === "transcribing"
      ? "Transcrevendo no seu Mac…"
      : `Escreva ou dite para ${target.title}…`;

  return (
    <div className="dock" data-drop="dock" data-dropping={dropping ? "true" : undefined}>
      <div className="composer" data-voice={voice}>
        {recordingNow ? (
          <Waveform recording={recording} />
        ) : (
          <textarea
            ref={field}
            rows={1}
            value={text}
            placeholder={placeholder}
            disabled={voice === "transcribing"}
            spellCheck={false}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                deliver(!event.altKey);
              } else if (event.key === "Escape" && target) {
                event.preventDefault();
                terminals.get(target.id)?.focus();
              }
            }}
          />
        )}
        {voice === "transcribing" && <div className="shimmer" aria-hidden="true" />}
        <div className="dock-row">
          {recordingNow ? (
            <>
              <button type="button" className="pill stop" onClick={() => void stop()} title="Parar e transcrever (⌘⇧M)">
                <span className="stop-square" aria-hidden="true" />
                Parar
              </button>
              <button type="button" className="pill ghost" onClick={() => void cancel()} title="Descartar (Esc)">
                Cancelar
              </button>
            </>
          ) : (
            <button
              type="button"
              className="pill mic"
              disabled={!client || voice !== "idle"}
              onClick={toggleVoice}
              title="Ditar (⌘⇧M): o áudio é transcrito no seu Mac"
              aria-label="Ditar"
            >
              <Icon d={ICON.mic} size={14} strokeWidth={1.9} />
              {voice === "starting" ? "Abrindo o microfone…" : voice === "transcribing" ? "Transcrevendo…" : "Ditar"}
            </button>
          )}
          <button
            type="button"
            className="pill"
            disabled={!client || !!busy || voice === "recording"}
            onClick={() => files.current?.click()}
            title="Anexar arquivos: o caminho vai junto com o texto"
          >
            <Icon d={ICON.clip} size={14} strokeWidth={1.9} />
            {busy ?? "Anexar"}
          </button>
          <input ref={files} type="file" multiple hidden onChange={(event) => void attach(event.target.files)} />
          {target && (
            <span className="dock-target" title="O texto vai para o terminal em foco">
              para <span style={{ color: KIND_COLOR[target.kind] }}>{KIND_GLYPH[target.kind]}</span> {target.title}
              {targetAccount && <span className="small"> · {targetAccount}</span>}
            </span>
          )}
          <span className="dock-hint mono">⏎ envia · ⌥⏎ só cola · ⇧⏎ linha</span>
          <button
            type="button"
            className="send"
            disabled={!text.trim() || !target || voice !== "idle"}
            onClick={() => deliver(true)}
            title="Enviar para o terminal (⏎)"
            aria-label="Enviar para o terminal"
          >
            <Icon d={ICON.send} size={15} strokeWidth={2.2} />
          </button>
        </div>
      </div>
      {error && (
        <div className="dock-error" role="alert">
          {error}
          <button type="button" className="icon-btn" onClick={() => setError(null)} aria-label="Fechar aviso">
            <Icon d={ICON.close} size={12} strokeWidth={2} />
          </button>
        </div>
      )}
      {dropping && <div className="drop-hint dock-drop">Solte para anexar à mensagem</div>}
    </div>
  );
}
