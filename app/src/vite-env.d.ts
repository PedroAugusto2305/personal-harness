/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Só fora do Tauri (navegador em desenvolvimento): onde está o núcleo. */
  readonly VITE_HARNESS_URL?: string;
  readonly VITE_HARNESS_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
