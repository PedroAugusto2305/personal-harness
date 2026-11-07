"""Script que o Claude Code executa para mandar a statusline e os hooks ao núcleo.

O Claude Code roda o comando da statusline e de cada hook passando um JSON no stdin.
O script repassa esse JSON ao núcleo por HTTP local e sai sempre com 0, para nunca
travar o agente se o núcleo estiver fora do ar.
"""

from __future__ import annotations

from pathlib import Path

RELAY_SCRIPT = """#!/bin/sh
# Gerado pelo Personal Harness. Não edite: é recriado a cada início do núcleo.
# Repassa ao núcleo o JSON que o Claude Code manda para a statusline e para os hooks.
kind="$1"
name="$2"
if [ -z "$HARNESS_CORE_URL" ] || [ -z "$HARNESS_SESSION_ID" ]; then
  cat >/dev/null
  exit 0
fi
if [ "$kind" = "statusline" ]; then
  curl -s -m 2 -X POST -H "Content-Type: application/json" -H "X-Harness-Token: $HARNESS_TOKEN" \\
    --data-binary @- "$HARNESS_CORE_URL/hooks/statusline?session=$HARNESS_SESSION_ID" 2>/dev/null
else
  curl -s -m 2 -o /dev/null -X POST -H "Content-Type: application/json" -H "X-Harness-Token: $HARNESS_TOKEN" \\
    --data-binary @- "$HARNESS_CORE_URL/hooks/event?session=$HARNESS_SESSION_ID&name=$name" 2>/dev/null
fi
exit 0
"""


def install_relay(path: Path) -> Path:
    """Grava o script no disco com permissão de execução e devolve o caminho."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RELAY_SCRIPT, encoding="utf-8")
    path.chmod(0o755)
    return path
