#!/bin/sh
# MÊTIS de desenvolvimento: a janela do Tauri rodando deste repositório (recompila ao editar).
#
# Desde a v0.9.4 ela usa os próprios dados, em ~/.harness-dev, e a porta 47840: não divide o
# núcleo, os terminais nem as rotinas com a MÊTIS de uso (a instalada pelo scripts/instalar.sh,
# em ~/.harness). Para mexer nos dados de uso de propósito: HARNESS_HOME=~/.harness scripts/dev.sh.
set -e
cd "$(dirname "$0")/.."
export HARNESS_HOME="${HARNESS_HOME:-$HOME/.harness-dev}"
export HARNESS_PORT="${HARNESS_PORT:-47840}"
export METIS_DEV=1
mkdir -p "$HARNESS_HOME"
# Os modelos (Whisper e embeddings, mais de 1 GB) são os mesmos da MÊTIS de uso.
if [ ! -e "$HARNESS_HOME/modelos" ] && [ -d "$HOME/.harness/modelos" ]; then
  ln -s "$HOME/.harness/modelos" "$HARNESS_HOME/modelos"
fi
# Os agentes da galeria vêm copiados na primeira vez. As rotinas não: rodariam duas vezes.
if [ ! -e "$HARNESS_HOME/agentes" ] && [ -d "$HOME/.harness/agentes" ]; then
  cp -R "$HOME/.harness/agentes" "$HARNESS_HOME/agentes"
fi
(cd core && uv sync --quiet)
(cd app && [ -d node_modules ] || npm install)
# Outro identificador: outra pasta de dados da janela (abas, divisões) e outro nome no Dock.
cd app && npm run tauri dev -- --config '{"identifier":"dev.pedroaquino.metis.dev","productName":"MÊTIS Dev"}'
