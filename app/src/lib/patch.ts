// Patch de parte de um diff (v0.9.6): marcar, desmarcar ou descartar um trecho ou linhas
// soltas, como o `git add -p`. O núcleo aplica com `git apply --recount`, então os números
// do cabeçalho de cada trecho (@@ -a,b +c,d @@) não precisam ser refeitos aqui.

export interface PatchHunk {
  /** A linha "@@ … @@" como veio do git. */
  header: string;
  /** As linhas do trecho, com o primeiro caractere (" ", "+", "-" ou "\\"). */
  lines: string[];
}

export interface FilePatch {
  /** diff --git, index, ---, +++ (e new file mode, quando há). */
  header: string[];
  hunks: PatchHunk[];
}

/** Separa o diff de um arquivo em cabeçalho e trechos (na mesma ordem do parseDiff). */
export function splitPatch(raw: string): FilePatch {
  const header: string[] = [];
  const hunks: PatchHunk[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("@@")) {
      hunks.push({ header: line, lines: [] });
    } else if (line.startsWith("diff --git") && hunks.length) {
      break; // um arquivo por diff: o resto não é deste
    } else if (!hunks.length) {
      if (line) header.push(line);
    } else if (line && " +-\\".includes(line[0])) {
      hunks[hunks.length - 1].lines.push(line);
    }
  }
  return { header, hunks };
}

/**
 * O patch só com as linhas escolhidas. Linha não escolhida vira contexto do lado em que
 * ela existe: aplicado direto (marcar), um "-" não escolhido continua no índice, então
 * fica como contexto, e um "+" não escolhido some; aplicado ao contrário (desmarcar,
 * descartar), é o inverso. Devolve null se nada mudaria.
 */
export function buildPatch(patch: FilePatch, pick: (hunk: number, line: number) => boolean, reverse: boolean): string | null {
  const out = [...patch.header];
  let any = false;
  patch.hunks.forEach((hunk, h) => {
    const body: string[] = [];
    let changed = false;
    let lastKept = false;
    hunk.lines.forEach((line, i) => {
      const sign = line[0];
      const rest = line.slice(1);
      if (sign === "\\") {
        if (lastKept) body.push(line); // "\ No newline at end of file" vale para a linha anterior
        return;
      }
      if (sign === " ") {
        body.push(line);
        lastKept = true;
        return;
      }
      const chosen = pick(h, i);
      const keepAsContext = sign === "-" ? !reverse : reverse;
      if (chosen) {
        body.push(line);
        changed = true;
        lastKept = true;
      } else if (keepAsContext) {
        body.push(` ${rest}`);
        lastKept = true;
      } else {
        lastKept = false;
      }
    });
    if (changed) {
      out.push(hunk.header, ...body);
      any = true;
    }
  });
  return any ? `${out.join("\n")}\n` : null;
}
