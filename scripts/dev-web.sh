#!/bin/sh
# MÊTIS no navegador, sem a janela do Tauri: útil para testar a tela.
# Sobe o núcleo com um token novo e o Vite em http://localhost:1420.
set -e
cd "$(dirname "$0")/.."
export HARNESS_HOME="${HARNESS_HOME:-$HOME/.harness-dev}"
PORT="${HARNESS_PORT:-47840}"
TOKEN="${HARNESS_TOKEN:-$(head -c 24 /dev/urandom | xxd -p | tr -d '\n')}"
(cd core && uv sync --quiet)
(cd app && [ -d node_modules ] || npm install)
HARNESS_PORT="$PORT" HARNESS_TOKEN="$TOKEN" uv run --quiet --project core harness-core &
CORE=$!
trap 'kill "$CORE" 2>/dev/null' EXIT INT TERM
cd app
VITE_HARNESS_URL="http://127.0.0.1:$PORT" VITE_HARNESS_TOKEN="$TOKEN" npm run dev
