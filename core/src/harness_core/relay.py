"""Script que o Claude Code executa para mandar a statusline e os hooks ao núcleo.

O Claude Code roda o comando da statusline e de cada hook passando um JSON no stdin.
O script repassa esse JSON ao núcleo por HTTP local e sai sempre com 0, para nunca
travar o agente se o núcleo estiver fora do ar.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

RELAY_SCRIPT = """#!/bin/sh
# Gerado pelo Personal Harness. Não edite: é recriado a cada início do núcleo.
# Repassa ao núcleo o JSON que o Claude Code manda para a statusline e para os hooks.
kind="$1"
name="$2"
# Codex (v0.9.4): chamado pelo `notify` com o JSON no último argumento. Avisa o núcleo
# (fim de turno = Stop; pedido de aprovação = Notification) e chama o notify que já
# estava no config.toml da conta, se houver, com os mesmos argumentos.
if [ "$kind" = "codex" ]; then
  shift
  payload=""
  for payload; do :; done
  case "$payload" in
    *agent-turn-complete*) event=Stop ;;
    *approval*) event=Notification ;;
    *) event="" ;;
  esac
  if [ -n "$event" ] && [ -n "$HARNESS_CORE_URL" ] && [ -n "$HARNESS_SESSION_ID" ]; then
    printf '%s' "$payload" | curl -s -m 2 -o /dev/null -X POST -H "Content-Type: application/json" \\
      -H "X-Harness-Token: $HARNESS_TOKEN" --data-binary @- \\
      "$HARNESS_CORE_URL/hooks/event?session=$HARNESS_SESSION_ID&name=$event" 2>/dev/null
  fi
  if [ "$#" -gt 1 ]; then
    exec "$@"
  fi
  exit 0
fi
if [ -z "$HARNESS_CORE_URL" ] || [ -z "$HARNESS_SESSION_ID" ]; then
  cat >/dev/null
  exit 0
fi
if [ "$kind" = "context" ]; then
  cat >/dev/null
  curl -s -m 6 -H "X-Harness-Token: $HARNESS_TOKEN" \\
    "$HARNESS_CORE_URL/brain/session-context?session=$HARNESS_SESSION_ID" 2>/dev/null
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


def install_cli_shim(bin_dir: Path, home: Path, profile: str = "principal") -> Path:
    """Põe o comando `metis` em ~/.harness/bin, que entra no PATH dos terminais do app.

    O nome antigo, `harness`, continua instalado como apelido enquanto a troca de nome assenta.
    Num perfil que não é o principal (v0.9.8), o comando leva também HARNESS_PROFILE: o
    `metis` daquele terminal fala com o núcleo e com o Brain do próprio perfil.
    Devolve o caminho do `metis`.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    extra = "" if profile in ("", "principal") else f"HARNESS_PROFILE={shlex.quote(profile)}\nexport HARNESS_PROFILE\n"
    body = (
        "#!/bin/sh\n"
        "# Gerado pela MÊTIS: o comando `metis` (e o antigo `harness`) dentro dos terminais do app.\n"
        f"HARNESS_HOME={shlex.quote(str(home))}\n"
        "export HARNESS_HOME\n"
        f"{extra}"
        f'exec {shlex.quote(sys.executable)} -m harness_core.cli "$@"\n'
    )
    for name in ("metis", "harness"):
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    return bin_dir / "metis"
