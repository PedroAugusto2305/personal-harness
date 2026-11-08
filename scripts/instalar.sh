#!/bin/sh
# Instala (ou atualiza) a MÊTIS de uso a partir de uma versão marcada do repositório.
#
#   scripts/instalar.sh            a versão mais nova (a maior tag v*)
#   scripts/instalar.sh v0.9.4     uma versão específica (também serve para voltar)
#
# Cada versão vira uma cópia própria em ~/.harness/versoes/<versão>, com o núcleo dela, e o
# app vai para /Applications/MÊTIS.app (ou ~/Applications, sem permissão de escrita lá).
# O núcleo em uso nunca troca de arquivo: a versão nova só entra quando a MÊTIS é reaberta
# e o núcleo reiniciado (a janela nova oferece). Os dados ficam onde estão, em ~/.harness.
# A MÊTIS de desenvolvimento (scripts/dev.sh) é outra: roda do repositório, em ~/.harness-dev.
#
# Variáveis para teste: METIS_REPO (o repositório), HARNESS_HOME (os dados), METIS_APPS
# (a pasta do app) e METIS_BUILD (o cache de compilação, padrão ~/.harness/build).
set -eu

REPO="${METIS_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
DATA="${HARNESS_HOME:-$HOME/.harness}"
APP_NAME="MÊTIS.app"

say() { printf '\033[1m· %s\033[0m\n' "$*"; }
fail() { printf '\033[31mmetis: %s\033[0m\n' "$*" >&2; exit 1; }

for tool in git uv npm cargo; do
  command -v "$tool" >/dev/null 2>&1 || fail "falta o $tool no PATH"
done

TAG="${1:-$(git -C "$REPO" tag --list 'v*' --sort=-v:refname | head -n 1)}"
[ -n "$TAG" ] || fail "nenhuma versão marcada (tag v*) em $REPO"
git -C "$REPO" rev-parse -q --verify "refs/tags/$TAG" >/dev/null || fail "a versão $TAG não existe em $REPO"
DEST="$DATA/versoes/$TAG"

say "MÊTIS $TAG: cópia em $DEST"
mkdir -p "$DATA/versoes"
if [ ! -d "$DEST/.git" ]; then
  git clone --quiet --local --no-checkout "$REPO" "$DEST"
fi
git -C "$DEST" fetch --quiet --tags origin
git -C "$DEST" -c advice.detachedHead=false checkout --quiet --force "$TAG"

say "núcleo (uv sync)"
(cd "$DEST/core" && uv sync --quiet --frozen)

say "tela (npm ci)"
(cd "$DEST/app" && npm ci --no-audit --no-fund --loglevel=error)

# O alvo do Rust fica fora da cópia e é o mesmo para todas as versões: só a primeira
# compilação é longa (vários minutos num Mac Intel); as próximas reaproveitam as dependências.
say "app (tauri build; a primeira vez demora)"
TARGET_DIR="${METIS_BUILD:-$DATA/build}/target"
(cd "$DEST/app" && env -u METIS_DEV CARGO_TARGET_DIR="$TARGET_DIR" npm run tauri -- build --bundles app)
BUILT="$TARGET_DIR/release/bundle/macos/$APP_NAME"
[ -d "$BUILT" ] || fail "o build não gerou $BUILT"

if [ -n "${METIS_APPS:-}" ]; then
  APPS="$METIS_APPS"
elif [ -w /Applications ]; then
  APPS=/Applications
else
  APPS="$HOME/Applications"
fi
mkdir -p "$APPS"
say "instalando em $APPS/$APP_NAME"
rm -rf "$APPS/$APP_NAME.novo"
ditto "$BUILT" "$APPS/$APP_NAME.novo"
rm -rf "$APPS/$APP_NAME"
mv "$APPS/$APP_NAME.novo" "$APPS/$APP_NAME"
printf '%s\n' "$TAG" > "$DATA/versao-instalada"

# Ficam as duas versões mais novas e qualquer uma cujo núcleo ainda esteja rodando.
count=$(ls -1 "$DATA/versoes" | wc -l | tr -d ' ')
if [ "$count" -gt 2 ]; then
  ls -1 "$DATA/versoes" | sort -V | head -n $((count - 2)) | while read -r old; do
    [ "$old" = "$TAG" ] && continue
    if pgrep -f "$DATA/versoes/$old/core" >/dev/null 2>&1; then
      say "mantendo $old: o núcleo dela ainda está rodando"
    else
      rm -rf "$DATA/versoes/$old"
      say "apagada a cópia antiga $old"
    fi
  done
fi

say "pronto: MÊTIS $TAG instalada"
echo "  Feche a MÊTIS (⌘Q) e abra de novo. Os terminais continuam abertos: quando quiser,"
echo "  a janela oferece reiniciar o núcleo para a $TAG (isso fecha os terminais)."
