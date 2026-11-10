// Ponte entre a interface e os terminais montados: a barra de entrada, o ditado e o
// arrastar de arquivos escrevem no terminal em foco por aqui.

export interface TerminalHandle {
  /** Cola como colagem de verdade (bracketed paste quando a CLI pede). Não envia. */
  paste(text: string): void;
  /** Bytes crus para o processo, como teclas. */
  send(data: string): void;
  focus(): void;
}

export const terminals = new Map<string, TerminalHandle>();

/** Cola o texto e confirma com Enter, com uma pausa para a CLI fechar a colagem. */
export function submit(id: string, text: string): boolean {
  const handle = terminals.get(id);
  if (!handle) return false;
  handle.paste(text);
  window.setTimeout(() => handle.send("\r"), 120);
  handle.focus();
  return true;
}

/** Caminho pronto para colar no terminal: aspas simples só quando precisa. */
export function quotePath(path: string): string {
  return /^[\w@%+=:,./~-]+$/.test(path) ? path : `'${path.replace(/'/g, `'\\''`)}'`;
}

export function quotePaths(paths: string[]): string {
  return paths.map(quotePath).join(" ");
}

/**
 * Arquivos de uma colagem com ⌘V: um print copiado (⌘⌃⇧4), uma imagem copiada do navegador.
 * O WebKit entrega o print como "image.png", que ganha nome com a data e a hora.
 *
 * Vazio quando a colagem traz texto: um trecho copiado de planilha ou do Word leva junto uma
 * imagem dele, e aí o que vale é o texto.
 */
export function pastedFiles(data: DataTransfer | null, now = new Date()): File[] {
  if (!data || data.getData("text/plain")) return [];
  const files = data.files.length
    ? Array.from(data.files)
    : Array.from(data.items)
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp =
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return files.map((file, i) => {
    const generic = /^image\.(\w+)$/i.exec(file.name);
    if (!generic) return file;
    const name = `print-${stamp}${files.length > 1 ? `-${i + 1}` : ""}.${generic[1].toLowerCase()}`;
    return new File([file], name, { type: file.type, lastModified: file.lastModified });
  });
}
