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
