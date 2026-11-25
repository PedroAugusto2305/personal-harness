// v1.7.0: a barra de entrada da conversa, no jeito do campo do Codex: modelo, força e a prévia
// de cada anexo no lugar do caminho. Aqui ficam as regras sem tela (testáveis sem o React).

import { quotePaths } from "./terminals";
import type { AttachmentKind, ModelOption, Session, SessionModels } from "../types";

/** A força (nível de raciocínio) em português, na ordem da mais leve para a mais pesada. */
export const EFFORT_LABEL: Record<string, string> = {
  minimal: "Mínima",
  low: "Baixa",
  medium: "Média",
  high: "Alta",
  xhigh: "Extra alta",
  max: "Máxima",
  ultra: "Ultra",
};

export const EFFORT_HINT: Record<string, string> = {
  minimal: "responde quase sem pensar",
  low: "rápida, pensa pouco",
  medium: "equilíbrio para o dia a dia",
  high: "pensa mais nos problemas difíceis",
  xhigh: "ainda mais raciocínio",
  max: "o máximo de raciocínio",
  ultra: "o máximo, dividindo a tarefa em partes",
};

export const effortLabel = (effort: string | null | undefined): string => (effort ? (EFFORT_LABEL[effort] ?? effort) : "");

/** Acima disso o núcleo recusa o upload (o mesmo limite de antes): o anexo fica com aviso. */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

const KIND_BY_EXT: Record<string, AttachmentKind> = {};
for (const [kind, exts] of Object.entries({
  imagem: "png jpg jpeg gif webp svg avif bmp heic heif tif tiff ico",
  video: "mp4 mov m4v webm mkv avi mpg mpeg 3gp",
  audio: "mp3 m4a wav aac ogg oga flac aiff aif opus",
  pdf: "pdf",
  planilha: "xlsx xls csv tsv numbers ods",
  apresentacao: "ppt pptx key odp",
  documento: "doc docx pages rtf odt md markdown txt",
  compactado: "zip tar gz tgz bz2 xz rar 7z dmg",
  codigo: "py ts tsx js jsx mjs json html css scss sh zsh rs go java rb swift kt c cc cpp h hpp yaml yml toml sql ipynb",
}) as [AttachmentKind, string][]) {
  for (const ext of exts.split(" ")) KIND_BY_EXT[ext] = kind;
}

/** O tipo pelo nome, enquanto o núcleo não responde (a mesma tabela do núcleo). */
export function kindOf(name: string): AttachmentKind {
  const ext = /\.([A-Za-z0-9]+)$/.exec(name)?.[1]?.toLowerCase() ?? "";
  return KIND_BY_EXT[ext] ?? "arquivo";
}

/** Imagens que o WebKit desenha direto (as outras, como HEIC, vão pela miniatura do QuickLook). */
export const browserImage = (name: string) => /\.(png|jpe?g|gif|webp|avif|bmp|svg)$/i.test(name);

/** Tipos que abrem inteiros na prévia grande (o resto mostra a miniatura e o Finder). */
export const playable = (kind: AttachmentKind, name: string) => kind === "video" || kind === "audio" || (kind === "imagem" && browserImage(name));

export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1).replace(".", ",") : Math.round(value)} ${units[unit]}`;
}

/**
 * O que vai para o agente: o texto e os caminhos dos anexos numa colagem só, como antes da v1.7.0
 * (o caminho ia para o campo e seguia junto com o texto). Os caminhos vão depois do texto.
 */
export function composeMessage(text: string, paths: string[]): string {
  return [text.trim(), quotePaths(paths)].filter(Boolean).join(" ");
}

/**
 * Tira do texto da sua mensagem os caminhos dos anexos que aparecem como prévia. Só os do fim
 * (onde a barra os põe desde a v1.7.0) e os do começo (onde o caminho entrava antes, ao anexar
 * primeiro): um caminho citado no meio da frase é parte do que você escreveu e fica.
 */
export function stripAttachmentPaths(text: string, paths: string[]): string {
  const forms = paths.filter(Boolean).flatMap((path) => [`'${path.replace(/'/g, `'\\''`)}'`, path]);
  if (!forms.length) return text;
  let out = text.trim();
  for (let changed = true; changed && out; ) {
    changed = false;
    for (const form of forms) {
      if (out === form) {
        out = "";
      } else if (out.endsWith(form) && /\s/.test(out[out.length - form.length - 1] ?? "")) {
        out = out.slice(0, -form.length).trimEnd();
      } else if (out.startsWith(form) && /\s/.test(out[form.length] ?? "")) {
        out = out.slice(form.length).trimStart();
      } else continue;
      changed = true;
    }
  }
  return out === text.trim() ? text : out;
}

/**
 * O que os botões mostram: a escolha da conversa; sem ela, o que a CLI informa (a statusline do
 * Claude traz o modelo e a força) ou o padrão dela (o config.toml do Codex, o modelo do agente).
 */
export function shownChoice(session: Session, models: SessionModels | null): { model: string; effort: string } {
  const line = session.kind === "claude" ? session.statusline : null;
  const model = session.modelo ? modelName(models, session.modelo) : line?.model || modelName(models, models?.padrao.modelo);
  const effort = session.esforco ?? line?.effort ?? models?.padrao.esforco ?? null;
  return { model: model || "", effort: effortLabel(effort) };
}

/** As forças que valem para um modelo (a do Claude é a mesma lista para todos). */
export function effortsFor(models: SessionModels | null, model: string | null): string[] {
  if (!models) return [];
  const id = model ?? models.padrao.modelo;
  const found = models.modelos.find((m) => m.id === id);
  return found?.esforcos.length ? found.esforcos : models.esforcos;
}

/** O nome do modelo para o botão: o do catálogo, senão o que a CLI informou. */
export function modelName(models: SessionModels | null, id: string | null | undefined): string {
  if (!id) return "";
  return models?.modelos.find((m: ModelOption) => m.id === id)?.nome ?? id;
}
