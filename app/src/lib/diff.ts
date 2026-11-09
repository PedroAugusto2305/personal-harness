// Diff unificado do git → linhas com número antigo e novo, para mostrar e anotar.

export type DiffLineKind = "hunk" | "context" | "add" | "del" | "meta";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  old: number | null;
  new: number | null;
  /** v0.9.6: em que trecho a linha está e a posição dela nele (a mesma do splitPatch). */
  hunk?: number;
  pos?: number;
}

export interface ParsedDiff {
  lines: DiffLine[];
  binary: boolean;
  added: number;
  removed: number;
}

export function parseDiff(raw: string): ParsedDiff {
  const lines: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;
  let inHunk = false;
  let binary = false;
  let added = 0;
  let removed = 0;
  let hunkIndex = -1;
  let pos = 0;
  for (const line of raw.split("\n")) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(line);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      inHunk = true;
      hunkIndex += 1;
      pos = 0;
      lines.push({ kind: "hunk", text: hunk[3].trim(), old: null, new: null, hunk: hunkIndex });
      continue;
    }
    if (!inHunk) {
      if (/^Binary files .* differ$/.test(line) || line.startsWith("GIT binary patch")) binary = true;
      continue; // cabeçalho: diff --git, index, ---, +++
    }
    if (line.startsWith("+")) {
      lines.push({ kind: "add", text: line.slice(1), old: null, new: newLine++, hunk: hunkIndex, pos: pos++ });
      added++;
    } else if (line.startsWith("-")) {
      lines.push({ kind: "del", text: line.slice(1), old: oldLine++, new: null, hunk: hunkIndex, pos: pos++ });
      removed++;
    } else if (line.startsWith(" ")) {
      lines.push({ kind: "context", text: line.slice(1), old: oldLine++, new: newLine++, hunk: hunkIndex, pos: pos++ });
    } else if (line.startsWith("\\")) {
      lines.push({ kind: "meta", text: line.slice(2), old: null, new: null, hunk: hunkIndex, pos: pos++ });
    } else if (line.startsWith("diff --git")) {
      inHunk = false; // outro arquivo no mesmo diff
    }
  }
  return { lines, binary, added, removed };
}
