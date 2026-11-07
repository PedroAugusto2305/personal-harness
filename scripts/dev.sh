#!/bin/sh
# Abre o Harness na janela do Tauri. O app sobe o núcleo sozinho com uv e o encerra ao sair.
set -e
cd "$(dirname "$0")/.."
(cd core && uv sync --quiet)
(cd app && [ -d node_modules ] || npm install)
cd app && npm run tauri dev
