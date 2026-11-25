import { useEffect, useImperativeHandle, useRef, useState, useSyncExternalStore, type Ref } from "react";
import { KindIcon } from "./KindIcon";
import { Recording, micError } from "../lib/audio";
import type { CoreClient } from "../lib/core";
import { pastedFiles, submit, terminals } from "../lib/terminals";
import { EFFORT_HINT, MAX_UPLOAD_BYTES, browserImage, composeMessage, effortLabel, effortsFor, formatSize, kindOf, modelName, shownChoice } from "../lib/composer";
import { ICON, Icon } from "../icons";
import type { BarCommand, Session, SessionModels } from "../types";
import { AttachmentCard, AttachmentViewer, type PreviewItem } from "./AttachmentPreview";
import { Waveform } from "./Waveform";

/** Sugestão da barra (v0.9.8): @ cita uma nota do Brain, / no começo lista os comandos da CLI. */
interface Suggest {
  kind: "nota" | "comando";
  /** Onde começa o trecho que a sugestão troca (o @ ou o /). */
  start: number;
  items: { label: string; detail: string; insert: string }[];
  index: number;
}

const MAX_SECONDS = 300;

type VoiceState = "idle" | "starting" | "recording" | "transcribing";

export interface DockHandle {
  /** Acrescenta texto no campo (ditado). */
  insert(text: string): void;
  toggleVoice(): void;
  focus(): void;
  /** Acrescenta o texto como foi digitado (sem espaço extra) e foca a barra. */
  type(text: string): void;
  /** Sobe os arquivos e os mostra como anexo (print colado, arquivo escolhido). */
  attach(files: File[]): void;
  /** v1.7.0: arquivos que já estão no disco (arrastados do Finder) viram anexo pelo caminho. */
  attachPaths(paths: string[]): void;
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
  /**
   * v1.7.0: troca o modelo e a força da conversa. O núcleo reabre a mesma conversa numa sessão
   * nova, que toma o lugar desta na tela (o rascunho e os anexos vão junto). Sem ela, a barra não
   * mostra os seletores.
   */
  onSettings?: (ajustes: { modelo: string | null; esforco: string | null }) => Promise<void>;
}

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

// --- rascunho de cada conversa ----------------------------------------------------------------

/** Um anexo na barra: a prévia e se já subiu (o caminho é o que o agente recebe). */
interface DockAttachment extends PreviewItem {
  id: string;
  state: "enviando" | "pronto" | "erro";
  error?: string;
}

interface Draft {
  text: string;
  attachments: DockAttachment[];
}

const EMPTY: Draft = { text: "", attachments: [] };

/**
 * v1.7.0: o rascunho (texto e anexos) de cada conversa fica fora do componente. Trocar o modelo
 * ou a força reabre a conversa numa sessão nova, com outra barra: o rascunho passa para ela, e o
 * anexo que ainda subia termina de subir no lugar certo.
 */
const drafts = new Map<string, Draft>();
const draftListeners = new Set<() => void>();

function setDraft(key: string, next: Draft): void {
  if (!next.text && !next.attachments.length) drafts.delete(key);
  else drafts.set(key, next);
  draftListeners.forEach((listener) => listener());
}

function subscribeDrafts(listener: () => void): () => void {
  draftListeners.add(listener);
  return () => draftListeners.delete(listener);
}

function patchAttachment(id: string, patch: Partial<DockAttachment>): void {
  for (const [key, draft] of drafts) {
    if (draft.attachments.some((a) => a.id === id)) {
      setDraft(key, { ...draft, attachments: draft.attachments.map((a) => (a.id === id ? { ...a, ...patch } : a)) });
      return;
    }
  }
}

/** O rascunho de uma sessão passa para a que tomou o lugar dela (reabrir, reiniciar). */
export function moveDraft(from: string, to: string): void {
  const draft = drafts.get(from);
  if (!draft || from === to) return;
  drafts.delete(from);
  setDraft(to, draft);
}

let attachmentSeq = 0;
const nextId = () => `anexo-${Date.now().toString(36)}-${(attachmentSeq += 1)}`;

// --- a barra ----------------------------------------------------------------------------------

/** O agente acabou de abrir (ou reabrir): a mensagem espera ele ficar pronto para receber. */
function useReady(target: Session | null): boolean {
  const [, tick] = useState(0);
  const age = target ? Date.now() / 1000 - target.created_at : Infinity;
  const ready = !target || target.kind === "shell" ? true : target.kind === "claude" ? target.status !== "starting" || age > 20 : age > 2.5;
  useEffect(() => {
    if (ready || !target) return;
    const timer = window.setTimeout(() => tick((n) => n + 1), 500);
    return () => window.clearTimeout(timer);
  });
  return ready;
}

/**
 * Barra de entrada: escreve ou dita, revisa e manda para o terminal em foco.
 * ⏎ cola e envia, ⌥⏎ só cola, ⇧⏎ quebra linha. O microfone vira onda enquanto grava.
 * v1.7.0: os anexos aparecem como prévia (no lugar do caminho) e o modelo e a força da conversa
 * se escolhem aqui, no jeito do campo do Codex.
 */
export function Dock({ client, target, targetAccount, language, dropping, ref, compact = false, onSettings }: Props) {
  const key = target?.id ?? "";
  const draft = useSyncExternalStore(subscribeDrafts, () => drafts.get(key) ?? EMPTY);
  const { text, attachments } = draft;
  const [voice, setVoice] = useState<VoiceState>("idle");
  const [recording, setRecording] = useState<Recording | null>(null);
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
  const [viewing, setViewing] = useState<PreviewItem | null>(null);
  /** v1.7.0: modelos e forças da conversa, o menu aberto e a troca em andamento. */
  const [models, setModels] = useState<SessionModels | null>(null);
  const [menu, setMenu] = useState<{ kind: "modelo" | "esforco" | "atalhos"; rect: DOMRect } | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  /** Mensagem pedida com o agente ainda abrindo: vai assim que ele estiver pronto (true = envia). */
  const [queued, setQueued] = useState<boolean | null>(null);
  const ready = useReady(target);
  const agentTarget = !!target && (target.kind === "claude" || target.kind === "codex") && !!onSettings;

  const setText = (next: string | ((current: string) => string)) => {
    const current = drafts.get(key) ?? EMPTY;
    setDraft(key, { ...current, text: typeof next === "function" ? next(current.text) : next });
  };
  const addAttachments = (list: DockAttachment[]) => {
    const current = drafts.get(key) ?? EMPTY;
    setDraft(key, { ...current, attachments: [...current.attachments, ...list] });
  };
  const removeAttachment = (id: string) => {
    const current = drafts.get(key) ?? EMPTY;
    const gone = current.attachments.find((a) => a.id === id);
    if (gone?.local) URL.revokeObjectURL(gone.local);
    setDraft(key, { ...current, attachments: current.attachments.filter((a) => a.id !== id) });
    field.current?.focus();
  };

  // Os modelos da conversa (o do Codex vem do cache da conta): uma vez por sessão.
  useEffect(() => {
    setModels(null);
    if (!client || !target || !agentTarget) return;
    let alive = true;
    client.sessionModels(target.id).then(
      (found) => alive && setModels(found),
      () => undefined,
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, target?.id]);

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

  const toEnd = () =>
    requestAnimationFrame(() => {
      const el = field.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });

  /** Texto cru digitado ou colado num terminal só para ler: entra como foi escrito. */
  const type = (value: string) => {
    if (!value) return;
    setText((current) => current + value);
    toEnd();
  };

  const insert = (value: string) => {
    const clean = value.trim();
    if (!clean) return;
    setText((current) => (current && !/\s$/.test(current) ? `${current} ${clean}` : current + clean));
    toEnd();
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

  /** Arquivos escolhidos ou colados: aparecem na hora e sobem para ~/.harness/anexos. */
  const attach = (list: FileList | File[] | null) => {
    if (!client || !list?.length) return;
    setError(null);
    const added = Array.from(list).map((file): DockAttachment => {
      const nome = file.name || "anexo";
      const tipo = kindOf(nome);
      const big = file.size > MAX_UPLOAD_BYTES;
      return {
        id: nextId(),
        nome,
        tipo,
        tamanho: file.size,
        local: tipo === "imagem" && browserImage(nome) && !big ? URL.createObjectURL(file) : undefined,
        state: big ? "erro" : "enviando",
        error: big ? `grande demais (${formatSize(file.size)}; máximo 50 MB). Arraste do Finder para mandar pelo caminho.` : undefined,
      };
    });
    addAttachments(added);
    Array.from(list).forEach((file, i) => {
      const item = added[i];
      if (item.state === "erro") return;
      client.uploadAttachment(file, item.nome).then(
        // O nome mostrado é o do arquivo (o núcleo guarda com um prefixo e sem espaços).
        (info) => patchAttachment(item.id, { state: "pronto", caminho: info.caminho, tipo: info.tipo, tamanho: info.tamanho }),
        (cause) => patchAttachment(item.id, { state: "erro", error: `não subiu: ${cause instanceof Error ? cause.message : String(cause)}` }),
      );
    });
    if (files.current) files.current.value = "";
    field.current?.focus();
  };

  /** Arquivos que já estão no disco (arrastados do Finder): vão pelo caminho original. */
  const attachPaths = (paths: string[]) => {
    if (!paths.length) return;
    setError(null);
    const known = new Set((drafts.get(key) ?? EMPTY).attachments.map((a) => a.caminho));
    const added = paths
      .filter((path) => !known.has(path))
      .map((path): DockAttachment => {
        const nome = path.split("/").pop() || path;
        return { id: nextId(), caminho: path, nome, tipo: kindOf(nome), tamanho: null, state: "pronto" };
      });
    addAttachments(added);
    for (const item of added) {
      client?.attachmentInfo(item.caminho!).then(
        (info) => patchAttachment(item.id, { nome: info.nome, tipo: info.tipo, tamanho: info.tamanho }),
        () => undefined, // sem informação: o caminho vai do mesmo jeito
      );
    }
    field.current?.focus();
  };

  useImperativeHandle(ref, () => ({
    insert,
    type,
    toggleVoice,
    focus: () => field.current?.focus(),
    attach: (list) => attach(list),
    attachPaths,
  }));

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

  const uploading = attachments.some((a) => a.state === "enviando");
  const broken = attachments.some((a) => a.state === "erro");
  const hasContent = !!text.trim() || attachments.length > 0;

  const deliver = (andSend: boolean, auto = false) => {
    const current = drafts.get(key) ?? EMPTY;
    if (!current.text.trim() && !current.attachments.length) return;
    if (!target || !terminals.has(target.id)) {
      setError("Abra um terminal para receber o texto.");
      return;
    }
    if (current.attachments.some((a) => a.state === "erro")) {
      setError("Tire o anexo com problema (×) para enviar.");
      return;
    }
    if (current.attachments.some((a) => a.state === "enviando") || !ready || applying) {
      setQueued(andSend); // vai sozinha quando o anexo subir ou o agente abrir
      return;
    }
    if (auto && terminals.get(target.id)?.menuOpen?.()) {
      // A mensagem que esperava não vai sozinha para um menu (o Enter escolheria a opção marcada).
      setQueued(null);
      setError("O agente abriu um menu no terminal: escolha nele e envie a mensagem de novo (ela ficou na barra).");
      return;
    }
    // O agente recebe como antes: o texto e os caminhos numa colagem só.
    const value = composeMessage(current.text, current.attachments.map((a) => a.caminho ?? ""));
    if (andSend) submit(target.id, value);
    else {
      terminals.get(target.id)!.paste(value);
      terminals.get(target.id)!.focus();
    }
    current.attachments.forEach((a) => a.local && URL.revokeObjectURL(a.local));
    setDraft(key, EMPTY);
    setQueued(null);
    setError(null);
  };

  // A mensagem pedida enquanto o anexo subia ou o agente abria vai quando dá.
  useEffect(() => {
    if (queued === null) return;
    if (broken) {
      setQueued(null);
      setError("Um anexo não subiu: tire-o (×) e envie de novo.");
      return;
    }
    if (!uploading && ready && !applying) deliver(queued, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queued, uploading, broken, ready, applying]);

  // --- modelo e força ---------------------------------------------------------------------------

  const lockReason = !target
    ? "Abra um agente"
    : applying
      ? applying
      : target.status === "working"
        ? "O agente está trabalhando: troque quando ele terminar a resposta"
        : target.atencao === "pergunta"
          ? "O agente espera uma resposta sua no terminal: responda antes de trocar"
          : target.status === "exited"
            ? "O agente saiu"
            : null;

  const apply = async (next: { modelo: string | null; esforco: string | null }, label: string) => {
    setMenu(null);
    if (!onSettings || !target || lockReason) return;
    const cli = target.kind === "claude" ? "Claude" : "Codex";
    setApplying(`Reabrindo o ${cli} com ${label}…`);
    setError(null);
    try {
      await onSettings(next);
    } catch (cause) {
      setError(`Não deu para trocar: ${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setApplying(null);
    }
  };

  const openMenu = (kind: "modelo" | "esforco" | "atalhos", button: HTMLButtonElement) => {
    if (menu?.kind === kind) return setMenu(null);
    setMenu({ kind, rect: button.getBoundingClientRect() });
    if (kind !== "atalhos" && client && target) client.sessionModels(target.id).then(setModels, () => undefined);
  };

  const shown = target && agentTarget ? shownChoice(target, models) : { model: "", effort: "" };
  const chosenModel = target?.modelo ?? null;
  const chosenEffort = target?.esforco ?? null;
  const efforts = effortsFor(models, chosenModel);

  const modelItems: MenuItem[] = models
    ? [
        {
          id: null,
          label: models.padrao.do_agente ? "O do agente" : "Padrão da CLI",
          hint: models.padrao.modelo ? modelName(models, models.padrao.modelo) : target?.kind === "claude" ? "o que o Claude Code escolher" : "o do config do Codex",
          active: chosenModel === null || (!!models.padrao.do_agente && chosenModel === models.padrao.modelo),
        },
        ...models.modelos
          .filter((m) => !(models.padrao.do_agente && m.id === models.padrao.modelo))
          .map((m) => ({ id: m.id, label: m.nome, hint: m.nome.toLowerCase() !== m.id.toLowerCase() ? m.id : undefined, active: chosenModel === m.id })),
      ]
    : [];
  const effortItems: MenuItem[] = models
    ? [
        {
          id: null,
          label: "Padrão",
          hint: models.padrao.esforco ? effortLabel(models.padrao.esforco).toLowerCase() : target?.kind === "claude" ? "o automático do Claude" : "o do modelo",
          active: chosenEffort === null,
        },
        ...efforts.map((e) => ({ id: e, label: effortLabel(e), hint: EFFORT_HINT[e], active: chosenEffort === e })),
      ]
    : [];

  const pickModel = (id: string | null) => {
    const label = id ? modelName(models, id) : "o modelo padrão";
    // A força escolhida que o modelo novo não aceita volta ao padrão.
    const allowed = effortsFor(models, id);
    apply({ modelo: id, esforco: chosenEffort && allowed.includes(chosenEffort) ? chosenEffort : null }, label);
  };
  const pickEffort = (id: string | null) => apply({ modelo: chosenModel, esforco: id }, id ? `força ${effortLabel(id).toLowerCase()}` : "a força padrão");

  // --- tela -------------------------------------------------------------------------------------

  const recordingNow = voice === "recording" && recording;
  const placeholder = !target
    ? "Abra um terminal para escrever ou ditar para ele…"
    : voice === "transcribing"
      ? "Transcrevendo no seu Mac…"
      : compact
        ? attachments.length
          ? "Diga o que fazer com os anexos…"
          : "Pergunte, use @ para notas, / para comandos"
        : `Escreva ou dite para ${target.title}…`;
  const sendBlocked = !hasContent || !target || voice !== "idle" || broken;
  const sendTitle = broken
    ? "Tire o anexo com problema (×) para enviar"
    : queued !== null
      ? "Vai assim que o anexo subir e o agente estiver pronto"
      : "Enviar (⏎) · ⌥⏎ só cola · ⇧⏎ quebra linha";

  const attachmentRow = attachments.length > 0 && (
    <div className="att-row" role="list" aria-label="Anexos da mensagem">
      {attachments.map((a) => (
        <div role="listitem" key={a.id}>
          <AttachmentCard
            client={client}
            item={a}
            state={a.state}
            error={a.error}
            onOpen={a.state === "erro" ? undefined : () => setViewing(a)}
            onRemove={() => removeAttachment(a.id)}
          />
        </div>
      ))}
    </div>
  );

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
      <div className="composer" data-voice={voice} data-busy={applying ? "true" : undefined}>
        {attachmentRow}
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
            onPaste={(event) => {
              // Print colado com ⌘V vira anexo, como no botão de anexar.
              const pasted = pastedFiles(event.clipboardData);
              if (!pasted.length) return;
              event.preventDefault();
              attach(pasted);
            }}
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
              // Barra vazia (sem texto e sem anexo) num terminal de agente: as teclas de menu vão
              // para ele (escolher opção, confirmar, interromper, trocar de modo). v1.7.0: com um menu
              // do agente na tela, ↑↓ e Esc vão para ele mesmo com texto na barra (a mensagem que
              // espera a reabertura não precisa ser apagada para fechar um aviso do agente).
              const menuNow = !!target && ["ArrowUp", "ArrowDown", "Escape"].includes(event.key) && !!terminals.get(target.id)?.menuOpen?.();
              if (target && target.kind !== "shell" && ((!text && !attachments.length) || menuNow) && !event.nativeEvent.isComposing) {
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
        {applying && <div className="shimmer" aria-hidden="true" />}
        {compact ? (
          <div className="dock-row compact">
            <button
              type="button"
              className="dock-icon"
              disabled={!client || voice === "recording"}
              onClick={() => files.current?.click()}
              title="Anexar arquivos (ou colar um print com ⌘V, ou arrastar do Finder)"
              aria-label="Anexar"
            >
              <Icon d={ICON.plus} size={15} strokeWidth={2} />
            </button>
            <input ref={files} type="file" multiple hidden onChange={(event) => attach(event.target.files)} />
            {agentTarget && (
              <>
                <button
                  type="button"
                  className="dock-pick"
                  disabled={!!lockReason}
                  aria-haspopup="menu"
                  aria-expanded={menu?.kind === "modelo"}
                  title={lockReason ?? "Modelo desta conversa (vale a partir da próxima resposta)"}
                  onClick={(event) => openMenu("modelo", event.currentTarget)}
                >
                  <Icon d={ICON.cpu} size={13} strokeWidth={1.8} />
                  <span className="dock-pick-label">{shown.model || "Modelo"}</span>
                  <Icon d={ICON.down} size={10} strokeWidth={2.2} />
                </button>
                <button
                  type="button"
                  className="dock-pick"
                  disabled={!!lockReason}
                  aria-haspopup="menu"
                  aria-expanded={menu?.kind === "esforco"}
                  title={lockReason ?? "Força do raciocínio nesta conversa (vale a partir da próxima resposta)"}
                  onClick={(event) => openMenu("esforco", event.currentTarget)}
                >
                  <Icon d={ICON.brain} size={13} strokeWidth={1.7} />
                  <span className="dock-pick-label">{shown.effort || "Força"}</span>
                  <Icon d={ICON.down} size={10} strokeWidth={2.2} />
                </button>
              </>
            )}
            {targetAccount && (
              <span className="dock-chip" title="Conta desta sessão">
                <Icon d={ICON.user} size={12} /> {targetAccount}
              </span>
            )}
            {applying && <span className="dock-chip dock-applying">{applying}</span>}
            {!applying && queued !== null && <span className="dock-chip">{uploading ? "enviando quando o anexo subir…" : "enviando quando o agente abrir…"}</span>}
            <span className="grow" />
            <button
              type="button"
              className="dock-icon"
              aria-haspopup="dialog"
              aria-expanded={menu?.kind === "atalhos"}
              title="Atalhos da barra"
              aria-label="Atalhos da barra"
              onClick={(event) => openMenu("atalhos", event.currentTarget)}
            >
              <Icon d={ICON.help} size={14} strokeWidth={1.8} />
            </button>
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
              disabled={sendBlocked}
              data-waiting={queued !== null ? "true" : undefined}
              onClick={() => deliver(true)}
              title={sendTitle}
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
              disabled={!client || voice === "recording"}
              onClick={() => files.current?.click()}
              title="Anexar arquivos (ou colar um print com ⌘V)"
            >
              <Icon d={ICON.clip} size={14} strokeWidth={1.9} />
              {uploading ? "anexando…" : "Anexar"}
            </button>
            <input ref={files} type="file" multiple hidden onChange={(event) => attach(event.target.files)} />
            {target && (
              <span className="dock-target" title="O texto vai para o terminal em foco">
                para <KindIcon kind={target.kind} /> {target.title}
                {targetAccount && <span className="small"> · {targetAccount}</span>}
              </span>
            )}
            <span className="dock-hint mono">⏎ envia · ⌥⏎ só cola · ⇧⏎ linha · @ nota · / comando</span>
            <button type="button" className="send" disabled={sendBlocked} onClick={() => deliver(true)} title="Enviar para o terminal (⏎)" aria-label="Enviar para o terminal">
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
      {menu?.kind === "modelo" && (
        <DockMenu rect={menu.rect} title="Modelo desta conversa" note={reopenNote(target)} items={modelItems} loading={!models} onPick={pickModel} onClose={() => setMenu(null)} />
      )}
      {menu?.kind === "esforco" && (
        <DockMenu
          rect={menu.rect}
          title="Força do raciocínio"
          note={reopenNote(target)}
          items={effortItems}
          loading={!models}
          onPick={pickEffort}
          onClose={() => setMenu(null)}
        />
      )}
      {menu?.kind === "atalhos" && <ShortcutsPop rect={menu.rect} kind={target?.kind ?? "shell"} onClose={() => setMenu(null)} />}
      {viewing && <AttachmentViewer client={client} item={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

const reopenNote = (target: Session | null) =>
  `Vale só para esta conversa, a partir da próxima resposta. O ${target?.kind === "codex" ? "Codex" : "Claude"} reabre na mesma conversa em alguns segundos; o rascunho e os anexos ficam.`;

// --- menus da barra -----------------------------------------------------------------------------

interface MenuItem {
  id: string | null;
  label: string;
  hint?: string;
  active: boolean;
}

/** Onde o menu abre: acima do botão, fixo na janela (o painel corta o que passa da borda). */
function placement(rect: DOMRect, width: number): React.CSSProperties {
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
  return { left, bottom: Math.max(8, window.innerHeight - rect.top + 6), width };
}

function useDismiss(box: React.RefObject<HTMLElement | null>, onClose: () => void) {
  useEffect(() => {
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", onClose);
    return () => {
      window.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", onClose);
    };
  }, [box, onClose]);
}

function DockMenu({
  rect,
  title,
  note,
  items,
  loading,
  onPick,
  onClose,
}: {
  rect: DOMRect;
  title: string;
  note: string;
  items: MenuItem[];
  loading: boolean;
  onPick: (id: string | null) => void;
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useDismiss(box, onClose);
  // Abre com o foco na opção que vale agora; ↑↓ andam, ⏎ escolhe.
  useEffect(() => {
    const el = box.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]') ?? box.current?.querySelector<HTMLButtonElement>("button");
    el?.focus();
  }, [loading]);
  return (
    <div
      ref={box}
      className="dock-menu"
      role="menu"
      aria-label={title}
      style={placement(rect, 268)}
      onKeyDown={(event) => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        const buttons = Array.from(box.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
        const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
        buttons[(at + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
      }}
    >
      <div className="dock-menu-title">{title}</div>
      {loading ? (
        <div className="dock-menu-empty">Buscando os modelos…</div>
      ) : (
        items.map((item) => (
          <button key={item.id ?? "padrao"} type="button" role="menuitemradio" aria-checked={item.active} onClick={() => onPick(item.id)}>
            <span className="dock-menu-check">{item.active && <Icon d={ICON.check} size={12} strokeWidth={2.4} />}</span>
            <span className="dock-menu-label">{item.label}</span>
            {item.hint && <span className="dock-menu-hint">{item.hint}</span>}
          </button>
        ))
      )}
      <div className="dock-menu-note">{note}</div>
    </div>
  );
}

const SHORTCUTS: [string, string][] = [
  ["⏎", "envia"],
  ["⌥⏎", "só cola no terminal, sem enviar"],
  ["⇧⏎", "quebra a linha"],
  ["@", "cita uma nota do Brain"],
  ["/", "comandos e skills da CLI"],
  ["⌘V", "um print colado vira anexo"],
  ["⌘⇧M", "dita (o áudio é transcrito no Mac)"],
  ["⌘⇧T", "alterna conversa e terminal"],
];

const EMPTY_BAR: [string, string][] = [
  ["↑ ↓ ⏎", "escolhem nos menus do agente"],
  ["Esc", "interrompe o agente"],
  ["⌃C", "interrompe o comando"],
];

function ShortcutsPop({ rect, kind, onClose }: { rect: DOMRect; kind: string; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  useDismiss(box, onClose);
  const empty = kind === "claude" ? [...EMPTY_BAR, ["⇧⇥", "troca o modo de aprovação do Claude"] as [string, string]] : EMPTY_BAR;
  const width = 300;
  return (
    <div ref={box} className="dock-menu dock-keys" role="dialog" aria-label="Atalhos da barra" style={{ ...placement(rect, width), left: Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8)) }}>
      <div className="dock-menu-title">Atalhos da barra</div>
      <dl>
        {SHORTCUTS.map(([keys, what]) => (
          <div key={keys}>
            <dt className="mono">{keys}</dt>
            <dd>{what}</dd>
          </div>
        ))}
      </dl>
      <div className="dock-menu-title">Com a barra vazia</div>
      <dl>
        {empty.map(([keys, what]) => (
          <div key={keys}>
            <dt className="mono">{keys}</dt>
            <dd>{what}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
