"""Comandos salvos (v0.9.3) em ~/.harness/comandos.json, e os atalhos remapeáveis em ~/.harness/atalhos.json.

Comando salvo é um texto que o Pedro repete: um comando de shell ("comando") ou um pedido
para o agente ("prompt"), global ou de um projeto (o caminho do repositório). A interface
filtra pelo projeto da worktree em foco; o núcleo só guarda, na ordem de criação.

Atalhos: a lista de ações e os padrões moram na interface, porque são dela. O arquivo guarda
só o que o Pedro mudou, legível e editável à mão ({"acao.id": "Meta+Shift+KeyD"}, "" desliga),
e o núcleo confere o formato para um erro de digitação não travar a janela.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Any

KINDS = ("comando", "prompt")
MAX_NAME = 80
MAX_TEXT = 8000


class CommandError(ValueError):
    pass


class UnknownCommand(KeyError):
    pass


def _write_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _clean(changes: dict, partial: bool) -> dict:
    """Confere e normaliza os campos de um comando (todos, ou só os que vieram)."""
    out: dict[str, Any] = {}
    allowed = {"nome", "texto", "tipo", "projeto"}
    unknown = set(changes) - allowed
    if unknown:
        raise CommandError(f"campo desconhecido: {', '.join(sorted(unknown))}")
    if not partial:
        for key in ("nome", "texto", "tipo"):
            if key not in changes:
                raise CommandError(f"falta o campo {key}")
    if "nome" in changes:
        name = changes["nome"]
        if not isinstance(name, str) or not name.strip():
            raise CommandError("o nome não pode ficar vazio")
        name = name.strip()
        if len(name) > MAX_NAME:
            raise CommandError(f"o nome passa de {MAX_NAME} caracteres")
        out["nome"] = name
    if "texto" in changes:
        text = changes["texto"]
        if not isinstance(text, str) or not text.strip():
            raise CommandError("o texto não pode ficar vazio")
        if len(text) > MAX_TEXT:
            raise CommandError(f"o texto passa de {MAX_TEXT} caracteres")
        out["texto"] = text
    if "tipo" in changes:
        if changes["tipo"] not in KINDS:
            raise CommandError(f"tipo é {' ou '.join(KINDS)}")
        out["tipo"] = changes["tipo"]
    if "projeto" in changes:
        project = changes["projeto"]
        if project is not None and not isinstance(project, str):
            raise CommandError("projeto é o caminho do repositório, ou nulo para global")
        out["projeto"] = (project.strip() or None) if isinstance(project, str) else None
    elif not partial:
        out["projeto"] = None
    return out


class CommandStore:
    def __init__(self, home: Path) -> None:
        self.path = home / "comandos.json"
        self._lock = threading.Lock()
        home.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("comandos") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]

    def _save(self, items: list[dict]) -> None:
        _write_atomic(self.path, {"comandos": items})

    def add(self, body: dict) -> dict:
        fields = _clean(body, partial=False)
        with self._lock:
            items = self.list()
            taken = {item["id"] for item in items}
            ident = secrets.token_hex(4)
            while ident in taken:
                ident = secrets.token_hex(4)
            item = {"id": ident, "nome": fields["nome"], "texto": fields["texto"], "tipo": fields["tipo"], "projeto": fields["projeto"]}
            items.append(item)
            self._save(items)
            return item

    def update(self, ident: str, changes: dict) -> dict:
        fields = _clean(changes, partial=True)
        with self._lock:
            items = self.list()
            for item in items:
                if item["id"] == ident:
                    item.update(fields)
                    self._save(items)
                    return item
        raise UnknownCommand(ident)

    def delete(self, ident: str) -> None:
        with self._lock:
            items = self.list()
            kept = [item for item in items if item["id"] != ident]
            if len(kept) == len(items):
                raise UnknownCommand(ident)
            self._save(kept)


# --- atalhos ------------------------------------------------------------------------------------

ACTION_RE = re.compile(r"^[a-z0-9._-]{1,60}$")
MODIFIERS = ("Meta", "Ctrl", "Alt", "Shift")
CODE_RE = re.compile(r"^[A-Za-z0-9]{1,24}$")


def valid_combo(combo: str) -> bool:
    """"" (desligado) ou modificadores em ordem (Meta, Ctrl, Alt, Shift) + um KeyboardEvent.code."""
    if combo == "":
        return True
    parts = combo.split("+")
    code, mods = parts[-1], parts[:-1]
    if not CODE_RE.match(code) or code in MODIFIERS:
        return False
    order = [MODIFIERS.index(m) if m in MODIFIERS else -1 for m in mods]
    return all(i >= 0 for i in order) and order == sorted(set(order))


class Keymap:
    def __init__(self, home: Path) -> None:
        self.path = home / "atalhos.json"
        self._lock = threading.Lock()
        home.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict:
        """As sobrescritas válidas; arquivo ausente, ilegível ou com lixo não derruba nada."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        keys = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and ACTION_RE.match(k) and valid_combo(v)}
        return {"atalhos": keys, "arquivo": str(self.path.resolve())}

    def set(self, keys: Any) -> dict:
        if not isinstance(keys, dict):
            raise CommandError("atalhos é um objeto {ação: atalho}")
        for action, combo in keys.items():
            if not isinstance(action, str) or not ACTION_RE.match(action):
                raise CommandError(f"ação inválida: {action!r}")
            if not isinstance(combo, str) or not valid_combo(combo):
                raise CommandError(f"atalho inválido para {action}: {combo!r} (ex.: Meta+Shift+KeyD, ou vazio para desligar)")
        with self._lock:
            _write_atomic(self.path, dict(sorted(keys.items())))
        return self.get()
