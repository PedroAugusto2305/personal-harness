// Markdown do Obsidian para a tela: [[links]] clicáveis, callouts (> [!abstract]) como
// caixas e ![[anexos]] como etiqueta. Tudo passa pelo DOMPurify antes de ir ao DOM.
import DOMPurify from "dompurify";
import { marked } from "marked";

const WIKILINK = /(!?)\[\[([^\]|#^]+)((?:[#^][^\]|]*)?)(?:\|([^\]]*))?\]\]/g;

const escapeHtml = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function links(markdown: string): string {
  // Dentro de bloco de código o texto fica como está.
  return markdown
    .split(/(```[\s\S]*?```)/g)
    .map((part, index) =>
      index % 2
        ? part
        : part.replace(WIKILINK, (_all, bang: string, target: string, section: string, alias?: string) => {
            const title = target.trim();
            const label = (alias ?? `${title}${section ?? ""}`).trim();
            if (bang) return `<span class="embed">📎 ${escapeHtml(label)}</span>`;
            return `<a class="wikilink" href="#" data-note="${escapeHtml(title)}">${escapeHtml(label)}</a>`;
          }),
    )
    .join("");
}

const sanitize = (html: string) => DOMPurify.sanitize(html, { ADD_ATTR: ["data-note", "data-callout"] });

function callouts(html: string): string {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  doc.querySelectorAll("blockquote").forEach((quote) => {
    const first = quote.firstElementChild;
    if (!first || first.tagName !== "P") return;
    const match = first.innerHTML.match(/^\s*\[!([\w-]+)\][+-]?[ \t]*([^\n<]*)(?:\n|<br>)?/i);
    if (!match) return;
    const kind = match[1].toLowerCase();
    quote.classList.add("callout");
    quote.setAttribute("data-callout", kind);
    const title = doc.createElement("div");
    title.className = "callout-title";
    title.innerHTML = match[2].trim() || kind;
    first.innerHTML = first.innerHTML.slice(match[0].length);
    if (!first.innerHTML.trim()) first.remove();
    quote.prepend(title);
  });
  return doc.body.firstElementChild?.innerHTML ?? "";
}

/** Nota inteira (sem o frontmatter) → HTML limpo. */
export function renderNote(markdown: string): string {
  return callouts(sanitize(marked.parse(links(markdown), { async: false, gfm: true }) as string));
}

/** Uma linha (texto de tarefa, resumo) → HTML limpo, sem parágrafo em volta. */
export function renderInline(markdown: string): string {
  return sanitize(marked.parseInline(links(markdown), { async: false }) as string);
}

/** Trecho da busca: o núcleo marca as palavras achadas com \x02 … \x03. */
export function snippetParts(snippet: string): { text: string; hit: boolean }[] {
  const parts: { text: string; hit: boolean }[] = [];
  for (const piece of snippet.replace(/\s+/g, " ").split("\x02")) {
    const [hit, rest] = piece.includes("\x03") ? piece.split("\x03", 2) : [null, piece];
    if (hit !== null) parts.push({ text: hit, hit: true });
    if (rest) parts.push({ text: rest, hit: false });
  }
  return parts;
}

export const TYPE_LABEL: Record<string, string> = {
  decisao: "Decisão",
  incidente: "Incidente",
  aprendizado: "Aprendizado",
  entrega: "Entrega",
  projeto: "Projeto",
  permanente: "Permanente",
  literatura: "Literatura",
  moc: "Mapa",
  daily: "Diário",
};

export const TYPE_ICON: Record<string, string> = {
  decisao: "⚖️",
  incidente: "🔥",
  aprendizado: "💡",
  entrega: "🛠️",
  projeto: "🎯",
  permanente: "🌱",
  literatura: "📚",
  moc: "🗺️",
  daily: "📅",
};

/** obsidian://open do vault Brain (o nome do cofre é o nome da pasta). */
export function obsidianUrl(vaultPath: string, notePath: string): string {
  const vault = vaultPath.replace(/\/+$/, "").split("/").pop() || "Brain";
  return `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(notePath.replace(/\.md$/, ""))}`;
}
