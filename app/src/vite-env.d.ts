/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Só fora do Tauri (navegador em desenvolvimento): onde está o núcleo. */
  readonly VITE_HARNESS_URL?: string;
  readonly VITE_HARNESS_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** Versão do app, vinda do package.json. */
declare const __APP_VERSION__: string;
