// Diff unificado do git → linhas com número antigo e novo, para mostrar e anotar.

export type DiffLineKind = "hunk" | "context" | "add" | "del" | "meta";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  old: number | null;
  new: number | null;
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
  for (const line of raw.split("\n")) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(line);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      inHunk = true;
      lines.push({ kind: "hunk", text: hunk[3].trim(), old: null, new: null });
      continue;
    }
    if (!inHunk) {
      if (/^Binary files .* differ$/.test(line) || line.startsWith("GIT binary patch")) binary = true;
      continue; // cabeçalho: diff --git, index, ---, +++
    }
    if (line.startsWith("+")) {
      lines.push({ kind: "add", text: line.slice(1), old: null, new: newLine++ });
      added++;
    } else if (line.startsWith("-")) {
      lines.push({ kind: "del", text: line.slice(1), old: oldLine++, new: null });
      removed++;
    } else if (line.startsWith(" ")) {
      lines.push({ kind: "context", text: line.slice(1), old: oldLine++, new: newLine++ });
    } else if (line.startsWith("\\")) {
      lines.push({ kind: "meta", text: line.slice(2), old: null, new: null });
    } else if (line.startsWith("diff --git")) {
      inHunk = false; // outro arquivo no mesmo diff
    }
  }
  return { lines, binary, added, removed };
}
