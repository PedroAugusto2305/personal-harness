// Editor das notas do Brain (v0.9.7): CodeMirror 6, o mesmo motor do Obsidian, com a
// "visualização ao vivo": fora da linha do cursor, a marcação some (# ** > [[ ]]) e o texto
// aparece formatado; na linha do cursor, volta o markdown cru para editar. [[ sugere títulos
// do vault, / abre o menu de blocos, o frontmatter vira uma caixa de propriedades.
import { EditorState, StateEffect, StateField, type Extension, type Range } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  ViewPlugin,
  WidgetType,
  drawSelection,
  keymap,
  placeholder,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting, syntaxTree } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";
import { autocompletion, completionKeymap, startCompletion, type Completion, type CompletionContext } from "@codemirror/autocomplete";
import { search, searchKeymap } from "@codemirror/search";
import type { NoteTitle } from "../types";

export interface NoteEditorOptions {
  text: string;
  onChange: (text: string) => void;
  onSave: () => void;
  titles: (query: string) => Promise<NoteTitle[]>;
  /** Quais destes títulos existem no vault (para marcar link de nota que não existe). */
  known: (titles: string[]) => Promise<string[]>;
  onOpenNote: (title: string) => void;
  /** v1.0.0: só leitura (nota fora de UTF-8: gravar estragaria os acentos). */
  readOnly?: boolean;
}

const CALLOUT_LABEL: Record<string, string> = {
  note: "Nota",
  abstract: "Resumo",
  summary: "Resumo",
  info: "Info",
  todo: "A fazer",
  tip: "Dica",
  hint: "Dica",
  important: "Importante",
  success: "Feito",
  check: "Feito",
  question: "Pergunta",
  warning: "Aviso",
  caution: "Aviso",
  attention: "Aviso",
  failure: "Falhou",
  danger: "Perigo",
  error: "Erro",
  bug: "Bug",
  example: "Exemplo",
  quote: "Citação",
  cite: "Citação",
};

const refreshLinks = StateEffect.define<null>();

/** Linhas tocadas pela seleção: nelas o markdown aparece cru. */
function activeLines(state: EditorState): Set<number> {
  const lines = new Set<number>();
  for (const range of state.selection.ranges) {
    const first = state.doc.lineAt(range.from).number;
    const last = state.doc.lineAt(range.to).number;
    for (let n = first; n <= last; n += 1) lines.add(n);
  }
  return lines;
}

class CheckboxWidget extends WidgetType {
  constructor(
    readonly checked: boolean,
    readonly pos: number,
  ) {
    super();
  }
  eq(other: CheckboxWidget) {
    return other.checked === this.checked && other.pos === this.pos;
  }
  toDOM(view: EditorView) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "cm-task-box";
    box.checked = this.checked;
    box.addEventListener("mousedown", (event) => {
      event.preventDefault();
      if (view.state.readOnly) return;
      // "[ ]" ↔ "[x]": troca só o caractere do meio.
      view.dispatch({ changes: { from: this.pos + 1, to: this.pos + 2, insert: this.checked ? " " : "x" } });
    });
    return box;
  }
  ignoreEvent() {
    return true;
  }
}

class CalloutWidget extends WidgetType {
  constructor(readonly type: string) {
    super();
  }
  eq(other: CalloutWidget) {
    return other.type === this.type;
  }
  toDOM() {
    const chip = document.createElement("span");
    chip.className = `cm-callout-chip cm-callout-${this.type}`;
    chip.textContent = CALLOUT_LABEL[this.type] ?? this.type;
    return chip;
  }
}

class RuleWidget extends WidgetType {
  toDOM() {
    const hr = document.createElement("span");
    hr.className = "cm-hr";
    return hr;
  }
}

class PropertiesWidget extends WidgetType {
  constructor(readonly pairs: [string, string][]) {
    super();
  }
  eq(other: PropertiesWidget) {
    return JSON.stringify(other.pairs) === JSON.stringify(this.pairs);
  }
  toDOM(view: EditorView) {
    const box = document.createElement("div");
    box.className = "cm-props";
    box.title = "Clique para editar as propriedades (o frontmatter)";
    for (const [key, value] of this.pairs) {
      const row = document.createElement("div");
      row.className = "cm-prop";
      const k = document.createElement("span");
      k.className = "cm-prop-key";
      k.textContent = key;
      const v = document.createElement("span");
      v.className = "cm-prop-value";
      v.textContent = value.replace(/^"(.*)"$/, "$1").replace(/\[\[(.+?)\]\]/g, "$1");
      row.append(k, v);
      box.append(row);
    }
    box.addEventListener("mousedown", (event) => {
      event.preventDefault();
      view.dispatch({ selection: { anchor: 4 } });
      view.focus();
    });
    return box;
  }
  ignoreEvent() {
    return true;
  }
}

/** O frontmatter (--- … ---) vira uma caixa de propriedades enquanto o cursor está fora dele. */
function frontmatterDecorations(state: EditorState): DecorationSet {
  const head = state.doc.sliceString(0, Math.min(state.doc.length, 8000));
  const match = /^---\n([\s\S]*?)\n---(?=\n|$)/.exec(head);
  if (!match) return Decoration.none;
  const end = match[0].length;
  const sel = state.selection.main;
  if (sel.from <= end) {
    // Cursor dentro: o YAML cru, só mais apagado.
    const lines: Range<Decoration>[] = [];
    for (let n = 1; n <= state.doc.lineAt(end).number; n += 1) lines.push(Decoration.line({ class: "cm-frontmatter" }).range(state.doc.line(n).from));
    return Decoration.set(lines);
  }
  const pairs: [string, string][] = [];
  for (const line of match[1].split("\n")) {
    const kv = /^([\w-]+):\s*(.*)$/.exec(line);
    if (kv) pairs.push([kv[1], kv[2]]);
    else if (/^\s+-\s+/.test(line) && pairs.length) pairs[pairs.length - 1][1] += `${pairs[pairs.length - 1][1] ? ", " : ""}${line.replace(/^\s+-\s+/, "")}`;
  }
  return Decoration.set([Decoration.replace({ widget: new PropertiesWidget(pairs), block: true }).range(0, end)]);
}

const frontmatterField = StateField.define<DecorationSet>({
  create: frontmatterDecorations,
  update: (value, tr) => (tr.docChanged || tr.selection ? frontmatterDecorations(tr.state) : value),
  provide: (field) => EditorView.decorations.from(field),
});

/** A visualização ao vivo: esconde a marcação fora da linha do cursor e desenha links, tarefas e callouts. */
function livePreview(options: NoteEditorOptions): Extension {
  const knownTitles = new Map<string, boolean>(); // título → existe
  const pending = new Set<string>();

  const build = (view: EditorView): DecorationSet => {
    const { state } = view;
    const active = activeLines(state);
    const out: Range<Decoration>[] = [];
    const hide = (from: number, to: number) => from < to && out.push(Decoration.replace({}).range(from, to));
    const lineOf = (pos: number) => state.doc.lineAt(pos).number;
    const missing: string[] = [];
    // O frontmatter é da caixa de propriedades (o "---" dele viraria divisor ou título).
    const fm = /^---\n[\s\S]*?\n---(?=\n|$)/.exec(state.doc.sliceString(0, Math.min(state.doc.length, 8000)));
    const fmEnd = fm ? fm[0].length : -1;

    for (const { from, to } of view.visibleRanges) {
      syntaxTree(state).iterate({
        from,
        to,
        enter: (node) => {
          if (node.from <= fmEnd) return node.to > fmEnd ? undefined : false;
          const name = node.name;
          const isActive = active.has(lineOf(node.from));
          if (/^ATXHeading[1-6]$/.test(name)) {
            out.push(Decoration.line({ class: `cm-h${name.slice(-1)}` }).range(state.doc.lineAt(node.from).from));
          } else if (name === "HeaderMark" && !isActive) {
            const after = state.sliceDoc(node.to, node.to + 1) === " " ? 1 : 0;
            hide(node.from, node.to + after);
          } else if ((name === "EmphasisMark" || name === "StrikethroughMark") && !isActive) {
            hide(node.from, node.to);
          } else if (name === "CodeMark" && node.node.parent?.name === "InlineCode" && !isActive) {
            hide(node.from, node.to);
          } else if (name === "Blockquote") {
            // Callout do Obsidian: "> [!tipo] título" na primeira linha.
            const first = state.doc.lineAt(node.from);
            const callout = /^>\s*\[!(\w+)\][+-]?/.exec(first.text);
            const type = callout ? callout[1].toLowerCase() : null;
            for (let n = first.number; n <= lineOf(node.to); n += 1) {
              const line = state.doc.line(n);
              const cls = type ? `cm-callout cm-callout-${type}${n === first.number ? " cm-callout-first" : ""}` : "cm-quote";
              out.push(Decoration.line({ class: cls }).range(line.from));
            }
            if (callout && !active.has(first.number)) {
              const start = first.from + first.text.indexOf("[");
              const endMark = first.from + callout[0].length;
              out.push(Decoration.replace({ widget: new CalloutWidget(type!) }).range(start, endMark));
            }
          } else if (name === "QuoteMark" && !isActive) {
            const after = state.sliceDoc(node.to, node.to + 1) === " " ? 1 : 0;
            hide(node.from, node.to + after);
          } else if (name === "ListMark" && !isActive && node.node.nextSibling?.name === "Task") {
            // Tarefa: some o "-" da lista, fica só a caixinha (como no Obsidian).
            const after = state.sliceDoc(node.to, node.to + 1) === " " ? 1 : 0;
            hide(node.from, node.to + after);
          } else if (name === "TaskMarker" && !isActive) {
            const checked = /x/i.test(state.sliceDoc(node.from, node.to));
            out.push(Decoration.replace({ widget: new CheckboxWidget(checked, node.from) }).range(node.from, node.to));
          } else if (name === "HorizontalRule" && !isActive) {
            out.push(Decoration.replace({ widget: new RuleWidget() }).range(node.from, node.to));
          } else if (name === "Link" && !isActive) {
            // [texto](url): fica só o texto, com cara de link.
            const text = state.sliceDoc(node.from, node.to);
            const close = text.indexOf("](");
            if (text.startsWith("[") && close > 0) {
              hide(node.from, node.from + 1);
              out.push(Decoration.mark({ class: "cm-md-link" }).range(node.from + 1, node.from + close));
              hide(node.from + close, node.to);
            }
          } else if (name === "FencedCode") {
            for (let n = lineOf(node.from); n <= lineOf(node.to); n += 1) out.push(Decoration.line({ class: "cm-codeblock" }).range(state.doc.line(n).from));
          }
        },
      });

      // [[links]] do Obsidian: não fazem parte do markdown padrão, então vão por expressão.
      const text = state.sliceDoc(from, to);
      for (const match of text.matchAll(/\[\[([^[\]\n]+?)\]\]/g)) {
        const start = from + match.index!;
        const end = start + match[0].length;
        if (start <= fmEnd) continue;
        const inner = match[1];
        const target = inner.split("|")[0].split("#")[0].trim();
        const label = inner.includes("|") ? inner.slice(inner.indexOf("|") + 1) : inner;
        const exists = knownTitles.get(target);
        if (exists === undefined && !pending.has(target)) missing.push(target);
        const cls = `cm-wikilink${exists === false ? " cm-wikilink-missing" : ""}`;
        if (active.has(lineOf(start))) {
          out.push(Decoration.mark({ class: `${cls} cm-wikilink-raw` }).range(start, end));
        } else {
          hide(start, start + 2 + (inner.length - label.length));
          out.push(Decoration.mark({ class: cls, attributes: { "data-target": target } }).range(start + 2 + (inner.length - label.length), end - 2));
          hide(end - 2, end);
        }
      }
    }

    if (missing.length) {
      const batch = [...new Set(missing)];
      batch.forEach((title) => pending.add(title));
      void options
        .known(batch)
        .then((found) => {
          const set = new Set(found);
          batch.forEach((title) => {
            knownTitles.set(title, set.has(title));
            pending.delete(title);
          });
          view.dispatch({ effects: refreshLinks.of(null) });
        })
        .catch(() => batch.forEach((title) => pending.delete(title)));
    }
    return Decoration.set(out, true);
  };

  const plugin = ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;
      constructor(view: EditorView) {
        this.decorations = build(view);
      }
      update(update: ViewUpdate) {
        const refreshed = update.transactions.some((tr) => tr.effects.some((e) => e.is(refreshLinks)));
        if (update.docChanged || update.viewportChanged || update.selectionSet || refreshed || syntaxTree(update.startState) !== syntaxTree(update.state)) {
          this.decorations = build(update.view);
        }
      }
    },
    { decorations: (plugin) => plugin.decorations },
  );

  const clicks = EditorView.domEventHandlers({
    mousedown(event) {
      const link = (event.target as HTMLElement).closest<HTMLElement>(".cm-wikilink[data-target]");
      if (!link) return false;
      event.preventDefault();
      options.onOpenNote(link.dataset.target!);
      return true;
    },
  });

  return [plugin, clicks];
}

interface SlashItem {
  key: string;
  label: string;
  insert: string;
  /** Onde o cursor fica (a partir do começo do que foi inserido); padrão: no fim. */
  cursor?: number;
  then?: "wiki";
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const SLASH: SlashItem[] = [
  { key: "titulo1", label: "Título 1", insert: "# " },
  { key: "titulo2", label: "Título 2", insert: "## " },
  { key: "titulo3", label: "Título 3", insert: "### " },
  { key: "tarefa", label: "Tarefa", insert: "- [ ] " },
  { key: "lista", label: "Lista", insert: "- " },
  { key: "numerada", label: "Lista numerada", insert: "1. " },
  { key: "callout", label: "Callout: nota", insert: "> [!note] \n> ", cursor: 10 },
  { key: "aviso", label: "Callout: aviso", insert: "> [!warning] \n> ", cursor: 13 },
  { key: "dica", label: "Callout: dica", insert: "> [!tip] \n> ", cursor: 9 },
  { key: "importante", label: "Callout: importante", insert: "> [!important] \n> ", cursor: 15 },
  { key: "citacao", label: "Citação", insert: "> " },
  { key: "tabela", label: "Tabela", insert: "| Coluna | Coluna |\n|---|---|\n|  |  |", cursor: 2 },
  { key: "codigo", label: "Bloco de código", insert: "```\n\n```", cursor: 4 },
  { key: "divisor", label: "Divisor", insert: "---\n" },
  { key: "link", label: "Link para nota", insert: "[[]]", cursor: 2, then: "wiki" },
  { key: "hoje", label: "Data de hoje", insert: "" },
];

function slashSource(context: CompletionContext) {
  const line = context.state.doc.lineAt(context.pos);
  const before = line.text.slice(0, context.pos - line.from);
  const match = /^(\s*)\/([\p{L}\w-]*)$/u.exec(before);
  if (!match) return null;
  const from = line.from + match[1].length;
  return {
    from,
    validFor: /^\/[\p{L}\w-]*$/u,
    options: SLASH.map(
      (item): Completion => ({
        label: `/${item.key}`,
        displayLabel: item.label,
        detail: `/${item.key}`,
        apply: (view, _completion, start, end) => {
          const insert = item.key === "hoje" ? today() : item.insert;
          view.dispatch({ changes: { from: start, to: end, insert }, selection: { anchor: start + (item.cursor ?? insert.length) } });
          if (item.then === "wiki") window.setTimeout(() => startCompletion(view), 0);
        },
      }),
    ),
  };
}

function wikiSource(options: NoteEditorOptions) {
  return async (context: CompletionContext) => {
    const match = context.matchBefore(/\[\[[^[\]\n|#]*$/);
    if (!match) return null;
    const query = match.text.slice(2);
    const list = await options.titles(query).catch(() => [] as NoteTitle[]);
    const closed = context.state.sliceDoc(context.pos, context.pos + 2) === "]]";
    return {
      from: match.from + 2,
      filter: false,
      options: list.map(
        (note): Completion => ({
          label: note.titulo,
          detail: [note.tipo, note.projeto].filter(Boolean).join(" · "),
          apply: closed ? note.titulo : `${note.titulo}]]`,
        }),
      ),
    };
  };
}

const highlight = HighlightStyle.define([
  { tag: t.heading1, fontSize: "1.55em", fontWeight: "700", lineHeight: "1.3" },
  { tag: t.heading2, fontSize: "1.32em", fontWeight: "700" },
  { tag: t.heading3, fontSize: "1.15em", fontWeight: "650" },
  { tag: [t.heading4, t.heading5, t.heading6], fontSize: "1.03em", fontWeight: "650" },
  { tag: t.strong, fontWeight: "700" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: t.link, color: "var(--acc)" },
  { tag: t.url, color: "var(--fnt)" },
  { tag: t.monospace, fontFamily: "var(--mono)", fontSize: "0.88em" },
  { tag: t.quote, color: "var(--mut)" },
  { tag: [t.processingInstruction, t.meta, t.contentSeparator], color: "var(--fnt)" },
]);

const theme = EditorView.theme({
  "&": { height: "100%", backgroundColor: "var(--bg)", color: "var(--tx)", fontSize: "14.5px" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "Inter, system-ui, sans-serif", lineHeight: "1.7" },
  ".cm-content": { maxWidth: "780px", margin: "0 auto", padding: "22px 32px 120px", caretColor: "var(--acc)" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--acc)", borderLeftWidth: "2px" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground": { backgroundColor: "var(--sel)" },
  ".cm-tooltip": { backgroundColor: "var(--side)", border: "1px solid var(--line2)", borderRadius: "8px", color: "var(--tx)" },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": { backgroundColor: "var(--sel)", color: "var(--tx)" },
  ".cm-completionDetail": { color: "var(--fnt)", fontStyle: "normal", marginLeft: "8px" },
  ".cm-panels": { backgroundColor: "var(--side)", color: "var(--tx)", borderTop: "1px solid var(--line)" },
});

export function createNoteEditor(parent: HTMLElement, options: NoteEditorOptions): EditorView {
  const live = { options };
  const state = EditorState.create({
    doc: options.text,
    extensions: [
      history(),
      drawSelection(),
      EditorView.lineWrapping,
      markdown({ base: markdownLanguage }),
      syntaxHighlighting(highlight),
      frontmatterField,
      livePreview(options),
      autocompletion({ override: [wikiSource(options), slashSource], icons: false }),
      search({ top: true }),
      placeholder("Escreva… ([[ liga a uma nota, / insere um bloco)"),
      keymap.of([
        { key: "Mod-s", preventDefault: true, run: () => (live.options.onSave(), true) },
        ...completionKeymap,
        ...searchKeymap,
        ...historyKeymap,
        indentWithTab,
        ...defaultKeymap,
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) live.options.onChange(update.state.doc.toString());
      }),
      EditorState.readOnly.of(!!options.readOnly),
      theme,
    ],
  });
  return new EditorView({ state, parent });
}

/** Troca o texto todo (a nota mudou no Obsidian) sem perder a posição do cursor, se couber. */
export function replaceText(view: EditorView, text: string) {
  const head = Math.min(view.state.selection.main.head, text.length);
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text }, selection: { anchor: head } });
}
