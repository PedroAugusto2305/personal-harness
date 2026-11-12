// A conversa desenhada (v1.2.0): o Markdown do agente em blocos, o código com cor do Monaco,
// os fluxogramas do Mermaid e o diff das edições. Tudo o que vem do transcript passa pelo
// DOMPurify antes de ir ao DOM.
import DOMPurify from "dompurify";
import { marked, type Token, type Tokens } from "marked";
import type { ChatItem } from "../types";

export type MdBlock = { kind: "html"; html: string } | { kind: "code"; lang: string; text: string } | { kind: "mermaid"; text: string };

/** Linguagens dos diagramas que o Mermaid desenha (```mermaid e os nomes diretos). */
const MERMAID_LANGS = new Set(["mermaid", "mmd", "flowchart", "sequencediagram", "gantt", "classdiagram", "statediagram", "erdiagram", "mindmap", "journey", "timeline", "pie", "quadrantchart", "gitgraph"]);
const MERMAID_START = /^\s*(flowchart|graph\s+(TD|TB|BT|RL|LR)|sequenceDiagram|classDiagram|stateDiagram(-v2)?|erDiagram|gantt|pie|mindmap|journey|timeline|gitGraph|quadrantChart|xychart-beta|block-beta|sankey-beta)\b/;

export function isMermaid(lang: string, text: string): boolean {
  const name = lang.trim().toLowerCase();
  if (MERMAID_LANGS.has(name)) return true;
  // Um bloco sem linguagem que começa como um diagrama também vira diagrama.
  return !name && MERMAID_START.test(text);
}

const SAFE_URL = /^(https?:|mailto:|#)/i;

/** Caminho local num link ou numa imagem do Markdown (nem http, nem âncora, nem data:). */
export function isLocalRef(href: string): boolean {
  return !!href && !SAFE_URL.test(href) && !/^(data|blob|javascript|vbscript):/i.test(href);
}

/** Caminho absoluto a partir da pasta da sessão (~ e relativo). */
export function resolvePath(path: string, cwd: string, home = ""): string {
  let p = path.replace(/^file:\/\//, "");
  try {
    p = decodeURI(p);
  } catch {
    // caminho com % solto: fica como veio
  }
  if (p.startsWith("~")) return home ? home + p.slice(1) : p; // o núcleo entende o ~
  if (!p.startsWith("/") && cwd) p = `${cwd.replace(/\/$/, "")}/${p}`;
  const parts: string[] = [];
  for (const part of p.split("/")) {
    if (part === "..") parts.pop();
    else if (part && part !== ".") parts.push(part);
  }
  return `/${parts.join("/")}`;
}

/**
 * O Markdown em blocos: o código e os diagramas viram componentes (cor do Monaco, desenho do
 * Mermaid); o resto é HTML limpo. `imageSrc` troca a imagem local pela rota da MÊTIS.
 */
export function markdownBlocks(text: string, imageSrc: (path: string) => string | null): MdBlock[] {
  let tokens: Token[];
  try {
    tokens = marked.lexer(text, { gfm: true });
  } catch {
    return [{ kind: "html", html: escapeHtml(text).replace(/\n/g, "<br>") }];
  }
  const links = (tokens as unknown as { links?: Tokens.Generic["links"] }).links ?? {};
  const blocks: MdBlock[] = [];
  let pending: Token[] = [];
  const flush = () => {
    if (!pending.length) return;
    const list = Object.assign(pending, { links });
    const html = marked.parser(list as never, { gfm: true }) as string;
    blocks.push({ kind: "html", html: cleanHtml(html, imageSrc) });
    pending = [];
  };
  for (const token of tokens) {
    if (token.type === "code") {
      flush();
      const code = token as Tokens.Code;
      const lang = (code.lang ?? "").trim().split(/\s+/)[0] ?? "";
      blocks.push(isMermaid(lang, code.text) ? { kind: "mermaid", text: code.text } : { kind: "code", lang, text: code.text });
    } else {
      pending.push(token);
    }
  }
  flush();
  return blocks;
}

/** HTML limpo; imagens locais pela rota da MÊTIS, imagens de fora viram link (o CSP não deixa carregar). */
export function cleanHtml(html: string, imageSrc: (path: string) => string | null): string {
  const fragment = DOMPurify.sanitize(html, { RETURN_DOM_FRAGMENT: true }) as DocumentFragment;
  fragment.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") ?? "";
    if (isLocalRef(src)) {
      const url = imageSrc(src);
      if (url) {
        img.setAttribute("src", url);
        img.setAttribute("data-local", src);
        img.setAttribute("loading", "lazy");
        return;
      }
    }
    if (/^data:image\//i.test(src)) return;
    const link = document.createElement("a");
    link.href = src;
    link.textContent = img.getAttribute("alt") || src;
    img.replaceWith(link);
  });
  fragment.querySelectorAll("a").forEach((a) => a.setAttribute("rel", "noreferrer"));
  const box = document.createElement("div");
  box.appendChild(fragment);
  return box.innerHTML;
}

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** Nome de linguagem do bloco de código (```ts) para o id do Monaco. */
const MONACO_LANG: Record<string, string> = {
  ts: "typescript", tsx: "typescript", typescript: "typescript", js: "javascript", jsx: "javascript", mjs: "javascript", javascript: "javascript",
  py: "python", python: "python", sh: "shell", bash: "shell", zsh: "shell", shell: "shell", console: "shell", json: "json", jsonc: "json",
  css: "css", scss: "scss", less: "less", html: "html", xml: "xml", svg: "xml", md: "markdown", markdown: "markdown", rs: "rust", rust: "rust",
  go: "go", sql: "sql", yml: "yaml", yaml: "yaml", toml: "ini", ini: "ini", swift: "swift", java: "java", kt: "kotlin", kotlin: "kotlin",
  rb: "ruby", ruby: "ruby", php: "php", c: "c", h: "c", cpp: "cpp", "c++": "cpp", cs: "csharp", csharp: "csharp", dockerfile: "dockerfile",
  diff: "plaintext", patch: "plaintext", graphql: "graphql", lua: "lua", r: "r", dart: "dart", vue: "html",
};

export function monacoLanguage(lang: string): string {
  return MONACO_LANG[lang.trim().toLowerCase()] ?? (lang.trim().toLowerCase() || "plaintext");
}

export type DiffRow = { kind: "del" | "add" | "same"; text: string };

/**
 * Diff por linha entre o trecho antes e o depois de uma edição (o Edit do Claude manda os dois
 * trechos inteiros). LCS simples: os trechos de uma edição são pequenos; acima de 400 linhas, o
 * antes sai todo como removido e o depois como acrescentado.
 */
export function lineDiff(before: string, after: string): DiffRow[] {
  const a = before ? before.split("\n") : [];
  const b = after ? after.split("\n") : [];
  if (a.length * b.length > 160_000) return [...a.map((text) => ({ kind: "del" as const, text })), ...b.map((text) => ({ kind: "add" as const, text }))];
  const table: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      rows.push({ kind: "same", text: a[i] });
      i += 1;
      j += 1;
    } else if (i < a.length && (j >= b.length || table[i + 1][j] >= table[i][j + 1])) {
      rows.push({ kind: "del", text: a[i] }); // o que saiu vem antes do que entrou, como no git
      i += 1;
    } else {
      rows.push({ kind: "add", text: b[j] });
      j += 1;
    }
  }
  return rows;
}

/** Linhas de um patch (apply_patch do Codex, diff unificado) com o tipo de cada uma. */
export function patchRows(patch: string): DiffRow[] {
  return patch.split("\n").map((text) => ({
    kind: text.startsWith("+") && !text.startsWith("+++") ? "add" : text.startsWith("-") && !text.startsWith("---") ? "del" : "same",
    text,
  }));
}

/** Um bloco da tela: uma mensagem, ou um grupo de ferramentas (e pensamentos) seguidos. */
export type ChatBlock = { kind: "item"; item: ChatItem } | { kind: "tools"; key: string; items: ChatItem[] };

/** Ferramentas seguidas (com o pensamento entre elas) viram um grupo, como no app do Codex. */
export function groupItems(items: ChatItem[]): ChatBlock[] {
  const blocks: ChatBlock[] = [];
  let group: ChatItem[] = [];
  const flush = () => {
    if (!group.length) return;
    // Pensamento sozinho entre duas mensagens não é grupo de ferramentas.
    if (group.every((i) => i.tipo === "pensamento")) group.forEach((item) => blocks.push({ kind: "item", item }));
    else blocks.push({ kind: "tools", key: group[0].id, items: group });
    group = [];
  };
  for (const item of items) {
    if (item.tipo === "ferramenta" || item.tipo === "pensamento") group.push(item);
    else {
      flush();
      blocks.push({ kind: "item", item });
    }
  }
  flush();
  return blocks;
}

const CATEGORY_NAME: Record<string, [string, string]> = {
  comando: ["comando", "comandos"],
  leitura: ["leitura", "leituras"],
  edicao: ["edição", "edições"],
  busca: ["busca", "buscas"],
  web: ["pesquisa na web", "pesquisas na web"],
  mcp: ["ferramenta MCP", "ferramentas MCP"],
  agente: ["subagente", "subagentes"],
  skill: ["skill", "skills"],
  imagem: ["imagem", "imagens"],
  pergunta: ["pergunta", "perguntas"],
  plano: ["plano", "planos"],
  outra: ["outra", "outras"],
};

/** "3 comandos · 2 leituras · 1 edição" de um grupo de ferramentas. */
export function summarizeTools(items: ChatItem[]): string {
  const counts = new Map<string, number>();
  for (const item of items) {
    if (item.tipo !== "ferramenta") continue;
    const key = item.categoria ?? "outra";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((x, y) => y[1] - x[1])
    .map(([key, n]) => `${n} ${(CATEGORY_NAME[key] ?? [key, key])[n === 1 ? 0 : 1]}`)
    .join(" · ");
}

/** Item que muda o que a tela mostra: o merge da página nova na lista que a tela já tem. */
export function mergeItems(current: ChatItem[], start: number, incoming: ChatItem[]): ChatItem[] {
  if (!incoming.length) return current;
  const next = current.slice();
  for (const item of incoming) {
    const index = item.n - start;
    if (index < 0) continue; // antes da janela que a tela tem: aparece quando rolar para cima
    if (index < next.length) next[index] = item;
    else if (index === next.length) next.push(item);
  }
  return next;
}
