import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { KindIcon } from "./KindIcon";
import { Recording, micError } from "../lib/audio";
import type { CoreClient } from "../lib/core";
import { quotePaths, submit, terminals } from "../lib/terminals";
import { ICON, Icon } from "../icons";
import type { BarCommand, Session } from "../types";

/** Sugestão da barra (v0.9.8): @ cita uma nota do Brain, / no começo lista os comandos da CLI. */
interface Suggest {
  kind: "nota" | "comando";
  /** Onde começa o trecho que a sugestão troca (o @ ou o /). */
  start: number;
  items: { label: string; detail: string; insert: string }[];
  index: number;
}
import { Waveform } from "./Waveform";

const MAX_SECONDS = 300;

type VoiceState = "idle" | "starting" | "recording" | "transcribing";

export interface DockHandle {
  /** Acrescenta texto no campo (ditado, caminho de anexo). */
  insert(text: string): void;
  toggleVoice(): void;
  focus(): void;
  /** Acrescenta o texto como foi digitado (sem espaço extra) e foca a barra. */
  type(text: string): void;
}

interface Props {
  client: CoreClient | null;
  target: Session | null;
  targetAccount: string | null;
  language: string;
  dropping: boolean;
  ref?: Ref<DockHandle>;
  /** v0.9.9: a barra mora dentro do painel do terminal (mockup), mais enxuta. */
  compact?: boolean;
}

/** Modelos que a barra do painel oferece (vai como /model para a CLI). */
const MODELS: Record<string, [string, string][]> = {
  claude: [
    ["opus", "Opus"],
    ["sonnet", "Sonnet"],
    ["haiku", "Haiku"],
  ],
  codex: [],
};

/** "claude-opus-5-5" vira "Opus 5.5"; "gpt-5.5" fica como está. */
export function modelLabel(model: string | null | undefined): string {
  if (!model) return "";
  // Mesma regra do núcleo (model_label): versão de até 2 dígitos, para a data do fim não virar
  // versão ("claude-sonnet-4-20250514" é Sonnet 4); o nome antigo leva a versão antes (3-5-sonnet).
  const old = /claude-(\d)-(\d)-(opus|sonnet|haiku)/i.exec(model);
  const m = /(opus|sonnet|haiku|fable|mythos)(?:[-_ ](\d{1,2})(?:[-_.](\d{1,2}))?(?=$|\D))?/i.exec(model);
  if (m) {
    const family = `${m[1][0].toUpperCase()}${m[1].slice(1).toLowerCase()}`;
    if (m[2]) return `${family} ${m[2]}${m[3] ? `.${m[3]}` : ""}`;
    if (old) return `${family} ${old[1]}.${old[2]}`;
    return family;
  }
  return model.replace(/^claude-/, "");
}

/**
 * Barra de entrada: escreve ou dita, revisa e manda para o terminal em foco.
 * ⏎ cola e envia, ⌥⏎ só cola, ⇧⏎ quebra linha. O microfone vira onda enquanto grava.
 */
export function Dock({ client, target, targetAccount, language, dropping, ref, compact = false }: Props) {
  const [text, setText] = useState("");
  const [voice, setVoice] = useState<VoiceState>("idle");
  const [recording, setRecording] = useState<Recording | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const files = useRef<HTMLInputElement>(null);
  const voiceRef = useRef(voice);
  voiceRef.current = voice;
  const [suggest, setSuggest] = useState<Suggest | null>(null);
  /** Comandos da barra por sessão e a pasta do vault, buscados uma vez. */
  const barCache = useRef(new Map<string, BarCommand[]>());
  const vaultRoot = useRef<string | null>(null);
  const suggestSeq = useRef(0);

  /** Olha o que está antes do cursor e abre (ou fecha) as sugestões. */
  const lookForSuggest = async (value: string, caret: number) => {
    const seq = ++suggestSeq.current;
    const before = value.slice(0, caret);
    const command = /^\/([\w:.-]*)$/.exec(before);
    const mention = /(^|\s)@([^\s@]{0,60})$/.exec(before);
    if (command && client && target && target.kind !== "shell") {
      let list = barCache.current.get(target.id);
      if (!list) {
        list = await client.sessionBar(target.id).then((r) => r.comandos, () => []);
        barCache.current.set(target.id, list);
      }
      const q = command[1].toLowerCase();
      // O igual vem primeiro, depois quem começa com o digitado, depois quem só contém:
      // "/clear" não pode perder para um "/clear-cache" do usuário, que vem antes na lista.
      const rank = (c: BarCommand) => {
        const name = c.nome.slice(1).toLowerCase();
        return name === q ? 0 : name.startsWith(q) ? 1 : 2;
      };
      const items = list
        .filter((c) => c.nome.slice(1).toLowerCase().includes(q))
        .sort((a, b) => rank(a) - rank(b))
        .slice(0, 10)
        .map((c) => ({ label: c.nome, detail: c.descricao || c.origem, insert: `${c.nome} ` }));
      if (seq === suggestSeq.current) setSuggest(items.length ? { kind: "comando", start: 0, items, index: 0 } : null);
      return;
    }
    if (mention && client) {
      if (vaultRoot.current === null) vaultRoot.current = await client.brainStatus().then((s) => s.vault, () => "");
      const notes = await client.brainTitles(mention[2], 8).catch(() => []);
      const root = vaultRoot.current.replace(/\/$/, "");
      const items = notes.map((n) => ({
        label: n.titulo,
        detail: [n.tipo, n.projeto].filter(Boolean).join(" · "),
        // O agente lê pelo caminho; o [[título]] deixa claro de que nota se trata.
        insert: `a nota do Brain [[${n.titulo}]] (${root}/${n.path}) `,
      }));
      if (seq === suggestSeq.current) setSuggest(items.length ? { kind: "nota", start: caret - mention[2].length - 1, items, index: 0 } : null);
      return;
    }
    if (seq === suggestSeq.current) setSuggest(null);
  };

  const accept = (item: Suggest["items"][number]) => {
    if (!suggest) return;
    const el = field.current;
    const caret = el?.selectionStart ?? text.length;
    const next = text.slice(0, suggest.start) + item.insert + text.slice(caret);
    setText(next);
    setSuggest(null);
    const pos = suggest.start + item.insert.length;
    requestAnimationFrame(() => {
      field.current?.focus();
      field.current?.setSelectionRange(pos, pos);
    });
  };
  const recRef = useRef(recording);
  recRef.current = recording;

  /** Texto cru digitado ou colado num terminal só para ler: entra como foi escrito. */
  const type = (value: string) => {
    if (!value) return;
    setText((current) => current + value);
    requestAnimationFrame(() => {
      const el = field.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  };

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

  useImperativeHandle(ref, () => ({ insert, type, toggleVoice, focus: () => field.current?.focus() }));

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
      : compact
        ? "Pergunte, use @ para notas, / para comandos"
        : `Escreva ou dite para ${target.title}…`;
  const models = target ? (MODELS[target.kind] ?? []) : [];
  const current = modelLabel(target?.statusline?.model);

  return (
    <div className="dock" data-compact={compact ? "true" : undefined} data-drop={compact && target ? `dock:${target.id}` : "dock"} data-dropping={dropping ? "true" : undefined}>
      {suggest && (
        <ul className="dock-suggest" role="listbox" aria-label={suggest.kind === "nota" ? "Notas do Brain" : "Comandos"}>
          {suggest.items.map((item, i) => (
            <li key={`${item.label}-${i}`} role="presentation">
              <button
                type="button"
                role="option"
                aria-selected={i === suggest.index}
                onMouseDown={(event) => {
                  event.preventDefault();
                  accept(item);
                }}
              >
                <span className={suggest.kind === "comando" ? "mono" : undefined}>{item.label}</span>
                <span className="small">{item.detail}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
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
            onChange={(event) => {
              setText(event.target.value);
              void lookForSuggest(event.target.value, event.target.selectionStart ?? event.target.value.length);
            }}
            onBlur={() => window.setTimeout(() => setSuggest(null), 150)}
            onKeyDown={(event) => {
              // Sugestões abertas: ↑↓ escolhem, ⏎ ou ⇥ aceitam, Esc fecha.
              if (suggest && !event.nativeEvent.isComposing) {
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  const step = event.key === "ArrowDown" ? 1 : -1;
                  setSuggest({ ...suggest, index: (suggest.index + step + suggest.items.length) % suggest.items.length });
                  return;
                }
                const chosen = suggest.items[suggest.index];
                // ⏎ com o comando escolhido já inteiro na barra envia (em vez de só acrescentar o espaço).
                const whole = event.key === "Enter" && suggest.kind === "comando" && text.trim() === chosen.label;
                if (whole) {
                  setSuggest(null);
                } else if ((event.key === "Enter" && !event.shiftKey && !event.altKey) || event.key === "Tab") {
                  event.preventDefault();
                  accept(chosen);
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setSuggest(null);
                  return;
                }
              }
              // Barra vazia num terminal de agente: as teclas de menu vão para ele
              // (escolher opção, confirmar, interromper, trocar de modo).
              if (target && target.kind !== "shell" && !text && !event.nativeEvent.isComposing) {
                const keys: Record<string, string> = { ArrowUp: "\x1b[A", ArrowDown: "\x1b[B", Enter: "\r", Escape: "\x1b" };
                const seq =
                  event.key === "Tab" && event.shiftKey ? "\x1b[Z" : event.ctrlKey && event.key.toLowerCase() === "c" ? "\x03" : event.metaKey || event.altKey ? undefined : keys[event.key];
                if (seq && !(event.key === "Enter" && event.shiftKey)) {
                  event.preventDefault();
                  terminals.get(target.id)?.send(seq);
                  return;
                }
              }
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
        {compact ? (
          <div className="dock-row compact">
            <button
              type="button"
              className="dock-icon"
              disabled={!client || !!busy || voice === "recording"}
              onClick={() => files.current?.click()}
              title={busy ?? "Anexar arquivos: o caminho vai junto com o texto"}
              aria-label="Anexar"
            >
              <Icon d={ICON.plus} size={15} strokeWidth={2} />
            </button>
            <input ref={files} type="file" multiple hidden onChange={(event) => void attach(event.target.files)} />
            {targetAccount && (
              <span className="dock-chip" title="Conta desta sessão">
                <Icon d={ICON.user} size={12} /> {targetAccount}
              </span>
            )}
            {busy && <span className="dock-chip">{busy}</span>}
            <span className="grow" />
            {target && target.kind !== "shell" && (models.length ? (
              <label className="dock-model" title="Trocar o modelo desta conversa (manda /model para a CLI)">
                <select
                  value=""
                  onChange={(event) => {
                    if (event.target.value && target) submit(target.id, `/model ${event.target.value}`);
                    event.target.value = "";
                  }}
                  aria-label="Modelo"
                >
                  <option value="">{current || "modelo"} ⌄</option>
                  {models.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              current && <span className="dock-chip mono">{current}</span>
            ))}
            {recordingNow ? (
              <>
                <button type="button" className="dock-icon stop" onClick={() => void stop()} title="Parar e transcrever (⌘⇧M)" aria-label="Parar e transcrever">
                  <span className="stop-square" aria-hidden="true" />
                </button>
                <button type="button" className="dock-icon" onClick={() => void cancel()} title="Descartar (Esc)" aria-label="Descartar">
                  <Icon d={ICON.close} size={13} strokeWidth={2} />
                </button>
              </>
            ) : (
              <button
                type="button"
                className="dock-icon"
                disabled={!client || voice !== "idle"}
                onClick={toggleVoice}
                title="Ditar (⌘⇧M): o áudio é transcrito no seu Mac"
                aria-label="Ditar"
                data-busy={voice !== "idle" ? "true" : undefined}
              >
                <Icon d={ICON.mic} size={14} strokeWidth={1.9} />
              </button>
            )}
            <button
              type="button"
              className="dock-send"
              disabled={!text.trim() || !target || voice !== "idle"}
              onClick={() => deliver(true)}
              title="Enviar (⏎) · ⌥⏎ só cola · ⇧⏎ quebra linha"
              aria-label="Enviar para o terminal"
            >
              <Icon d={ICON.up} size={13} strokeWidth={2.4} />
            </button>
          </div>
        ) : (
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
                para <KindIcon kind={target.kind} /> {target.title}
                {targetAccount && <span className="small"> · {targetAccount}</span>}
              </span>
            )}
            <span className="dock-hint mono">⏎ envia · ⌥⏎ só cola · ⇧⏎ linha · @ nota · / comando</span>
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
        )}
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
