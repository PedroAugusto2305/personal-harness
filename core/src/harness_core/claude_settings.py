"""O `--settings` que cada sessão do Claude Code recebe.

Passado na linha de comando, ele tem precedência sobre as configurações de usuário,
então a statusline do Harness vale só nas sessões do Harness e o
`~/.claude/settings.json` (usado também pelo Orca) fica intacto.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "Notification", "SessionEnd")


def _command(relay_path: Path, *args: str) -> str:
    return " ".join(["/bin/sh", shlex.quote(str(relay_path)), *args])


def build_claude_settings(relay_path: Path) -> dict:
    hooks = {
        event: [{"hooks": [{"type": "command", "command": _command(relay_path, "hook", event), "timeout": 5}]}]
        for event in HOOK_EVENTS
    }
    # No início da sessão, o que o relay imprime entra no contexto do Claude: os precedentes
    # do Brain para o projeto da pasta (vazio fora de um projeto do Brain).
    hooks["SessionStart"][0]["hooks"].append({"type": "command", "command": _command(relay_path, "context"), "timeout": 8})
    return {
        "statusLine": {
            "type": "command",
            "command": _command(relay_path, "statusline"),
            "padding": 0,
        },
        "hooks": hooks,
    }


def claude_argv(executable: str, relay_path: Path) -> list[str]:
    return [executable, "--settings", json.dumps(build_claude_settings(relay_path), separators=(",", ":"))]
