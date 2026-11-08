"""Ajustes da MÊTIS (v0.9.2) em ~/.harness/ajustes.json, e o que eles mudam nas sessões.

- Modo de permissão das sessões novas, por CLI: "padrao" (não passa nada: vale o que o
  Pedro configurou na própria CLI), "manual", "auto" ou "yolo".
- Confiar nas pastas: as pastas dos projetos da MÊTIS e as worktrees deles entram como
  confiáveis antes de a CLI abrir, para o "Do you trust this folder?" não travar cada
  worktree nova. Só essas pastas; nunca uma pasta qualquer.
- Manter o Mac acordado: nunca, só com agente trabalhando, ou sempre com o núcleo no ar.
- Avisos: notificação e som quando o agente termina ou espera você.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

PERMISSION_MODES = ("padrao", "manual", "auto", "yolo")
AWAKE_MODES = ("nunca", "agente", "sempre")

DEFAULTS: dict[str, Any] = {
    "permissao_claude": "padrao",
    "permissao_codex": "padrao",
    "confiar_pastas": True,
    "manter_acordado": "agente",
    "avisos": {"terminou": True, "espera": True, "aprovacao": True, "erro": True, "som": True, "volume": 0.6, "silencio": False},
}


class PrefsError(ValueError):
    pass


class Prefs:
    def __init__(self, home: Path) -> None:
        self.path = home / "ajustes.json"
        self._lock = threading.Lock()
        home.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        data = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
        data["avisos"] = {**DEFAULTS["avisos"], **(saved.get("avisos") or {})}
        return data

    def update(self, changes: dict) -> dict:
        with self._lock:
            data = self.get()
            for key, value in changes.items():
                if key not in DEFAULTS:
                    raise PrefsError(f"ajuste desconhecido: {key}")
                if key.startswith("permissao_") and value not in PERMISSION_MODES:
                    raise PrefsError(f"modo de permissão é {', '.join(PERMISSION_MODES)}")
                if key == "manter_acordado" and value not in AWAKE_MODES:
                    raise PrefsError(f"manter acordado é {', '.join(AWAKE_MODES)}")
                if key == "avisos":
                    if not isinstance(value, dict):
                        raise PrefsError("avisos é um objeto")
                    value = {**data["avisos"], **{k: v for k, v in value.items() if k in DEFAULTS["avisos"]}}
                    value["volume"] = max(0.0, min(1.0, float(value["volume"])))
                if key == "confiar_pastas":
                    value = bool(value)
                data[key] = value
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return data


def permission_args(kind: str, mode: str) -> list[str]:
    """Os argumentos da CLI para o modo escolhido (vazio em "padrao")."""
    if kind == "claude":
        return {"manual": ["--permission-mode", "manual"], "auto": ["--permission-mode", "auto"], "yolo": ["--dangerously-skip-permissions"]}.get(mode, [])
    if kind == "codex":
        return {"manual": ["-a", "untrusted"], "auto": ["--approve-for-me"], "yolo": ["--dangerously-bypass-approvals-and-sandbox"]}.get(mode, [])
    return []


def codex_trust_args(folder: str) -> list[str]:
    return ["-c", f'projects."{folder}".trust_level="trusted"']


def trust_claude_folder(config_file: Path, folder: str) -> bool:
    """Marca a pasta como confiável no .claude.json da conta. Devolve True se mudou algo.

    O arquivo é do Claude Code (vários Claudes abertos o regravam): lê, muda só a chave da
    pasta e troca de uma vez; se a pasta já é confiável, nem toca no arquivo."""
    try:
        data = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    except (OSError, ValueError):
        return False  # arquivo ilegível agora (um Claude gravando): fica para a próxima
    if not isinstance(data, dict):
        return False
    projects = data.setdefault("projects", {})
    entry = projects.setdefault(folder, {})
    if not isinstance(entry, dict) or entry.get("hasTrustDialogAccepted"):
        return False
    entry["hasTrustDialogAccepted"] = True
    mode = config_file.stat().st_mode & 0o777 if config_file.exists() else 0o600
    fd, tmp = tempfile.mkstemp(prefix=".claude.json.metis-", dir=config_file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.chmod(tmp, mode)
        os.replace(tmp, config_file)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        return False
    return True
