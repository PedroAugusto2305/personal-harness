// Monaco (o editor do VS Code) dentro da MÊTIS (v0.9.7). É grande: só carrega quando um
// arquivo é aberto para editar, e os workers de linguagem vêm empacotados pelo Vite (nada
// de CDN: o app roda sem internet e o CSP só aceita o próprio app).
import type * as Monaco from "monaco-editor";
import type { ThemeName } from "../types";
import { themeIsLight } from "./appearance";

export type MonacoApi = typeof Monaco;

let loading: Promise<MonacoApi> | null = null;

export function loadMonaco(): Promise<MonacoApi> {
  loading ??= (async () => {
    const [monaco, editorWorker, jsonWorker, cssWorker, htmlWorker, tsWorker] = await Promise.all([
      import("monaco-editor"),
      import("monaco-editor/editor/editor.worker?worker"),
      import("monaco-editor/languages/features/json/json.worker?worker"),
      import("monaco-editor/languages/features/css/css.worker?worker"),
      import("monaco-editor/languages/features/html/html.worker?worker"),
      import("monaco-editor/languages/features/typescript/ts.worker?worker"),
    ]);
    (self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
      getWorker(_id: string, label: string) {
        if (label === "json") return new jsonWorker.default();
        if (label === "css" || label === "scss" || label === "less") return new cssWorker.default();
        if (label === "html" || label === "handlebars" || label === "razor") return new htmlWorker.default();
        if (label === "typescript" || label === "javascript") return new tsWorker.default();
        return new editorWorker.default();
      },
    };
    // Projeto inteiro não é carregado: sem isso, todo import viraria erro vermelho.
    const ts = (monaco as unknown as { languages: { typescript?: { typescriptDefaults: { setDiagnosticsOptions: (o: object) => void }; javascriptDefaults: { setDiagnosticsOptions: (o: object) => void } } } }).languages.typescript;
    for (const defaults of [ts?.typescriptDefaults, ts?.javascriptDefaults]) {
      defaults?.setDiagnosticsOptions({ noSemanticValidation: true, noSyntaxValidation: false });
    }
    return monaco as MonacoApi;
  })();
  return loading;
}

/** Tema do Monaco tirado dos tokens CSS do tema da MÊTIS em vigor. */
export function applyMonacoTheme(monaco: MonacoApi, theme: ThemeName): string {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  const hex = (value: string) => value.replace("#", "");
  const light = themeIsLight(theme);
  const name = `metis-${theme}`;
  const bg = token("--term", light ? "#ffffff" : "#1e1f29");
  monaco.editor.defineTheme(name, {
    base: light ? "vs" : "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: hex(token("--fnt", "#8f95b2")), fontStyle: "italic" },
      { token: "keyword", foreground: hex(token("--warn", "#ff79c6")) },
      { token: "string", foreground: hex(token("--wait", "#bd93f9")) },
      { token: "number", foreground: hex(token("--acct", "#a9bcff")) },
      { token: "type", foreground: hex(token("--run", "#8be9fd")) },
    ],
    colors: {
      "editor.background": bg,
      "editor.foreground": token("--tx", light ? "#1f2330" : "#f8f8f2"),
      "editorLineNumber.foreground": token("--fnt", "#8f95b2"),
      "editorLineNumber.activeForeground": token("--tx", "#f8f8f2"),
      "editor.selectionBackground": token("--sel", "#44475a"),
      "editorCursor.foreground": token("--acc", "#82a0ff"),
      "editor.lineHighlightBackground": token("--elev", "#343746"),
      "editorWidget.background": token("--side", "#21222c"),
      "editorGutter.background": bg,
      "minimap.background": bg,
      "diffEditor.insertedTextBackground": "#50fa7b22",
      "diffEditor.removedTextBackground": "#ff555522",
    },
  });
  monaco.editor.setTheme(name);
  return name;
}

const EXT_LANGUAGE: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  mts: "typescript",
  cts: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  json: "json",
  jsonc: "json",
  md: "markdown",
  mdx: "markdown",
  py: "python",
  rs: "rust",
  go: "go",
  css: "css",
  scss: "scss",
  less: "less",
  html: "html",
  htm: "html",
  yml: "yaml",
  yaml: "yaml",
  toml: "ini",
  ini: "ini",
  sh: "shell",
  zsh: "shell",
  bash: "shell",
  sql: "sql",
  swift: "swift",
  kt: "kotlin",
  java: "java",
  rb: "ruby",
  php: "php",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  hpp: "cpp",
  cs: "csharp",
  xml: "xml",
  svg: "xml",
  dockerfile: "dockerfile",
  graphql: "graphql",
  vue: "html",
  svelte: "html",
};

/** A linguagem pelo nome do arquivo (o Monaco tem as cores de cada uma). */
export function languageFor(path: string): string {
  const name = path.split("/").pop()?.toLowerCase() ?? "";
  if (name === "dockerfile") return "dockerfile";
  if (name === "makefile") return "makefile";
  const ext = name.includes(".") ? name.split(".").pop()! : "";
  return EXT_LANGUAGE[ext] ?? "plaintext";
}
