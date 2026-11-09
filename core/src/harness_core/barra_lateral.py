"""Barra lateral (v0.9.8): worktrees fixadas no alto, apelidos e a cor de cada projeto.

Fica em ~/.harness/barra.json, só com o que o Pedro mudou:

    {"fixados": ["/caminho/da/worktree"], "nomes": {"/caminho": "apelido"}, "cores": {"projeto-id": "#rrggbb"}}

Cada mudança é um PATCH com uma ação só (fixar, nome ou cor) e devolve o estado inteiro.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

MAX_NAME = 60
MAX_PATH = 1000
COLOR = re.compile(r"#[0-9a-f]{6}")


class BarraError(ValueError):
    pass


def _empty() -> dict:
    return {"fixados": [], "nomes": {}, "cores": {}}


def _text(value: Any, field: str, limit: int = MAX_PATH) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BarraError(f"{field} vazio")
    value = value.strip()
    if len(value) > limit:
        raise BarraError(f"{field} longo demais")
    return value


class SidebarStore:
    def __init__(self, home: Path) -> None:
        self.path = home / "barra.json"
        self._lock = threading.Lock()

    def state(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty()
        if not isinstance(data, dict):
            return _empty()
        state = _empty()
        pinned = data.get("fixados")
        if isinstance(pinned, list):
            state["fixados"] = [p for p in pinned if isinstance(p, str) and p]
        for key in ("nomes", "cores"):
            value = data.get(key)
            if isinstance(value, dict):
                state[key] = {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str) and v}
        state["cores"] = {k: v for k, v in state["cores"].items() if COLOR.fullmatch(v)}
        return state

    def patch(self, body: Any) -> dict:
        """Uma ação: {"fixar": {caminho, fixo}} | {"nome": {caminho, nome}} | {"cor": {projeto, cor}}."""
        if not isinstance(body, dict):
            raise BarraError("corpo inválido")
        actions = [key for key in ("fixar", "nome", "cor") if key in body]
        if len(actions) != 1 or len(body) != 1:
            raise BarraError("mande uma ação só: fixar, nome ou cor")
        action = actions[0]
        args = body[action]
        if not isinstance(args, dict):
            raise BarraError(f"{action} inválido")
        with self._lock:
            state = self.state()
            if action == "fixar":
                path = _text(args.get("caminho"), "caminho")
                fixed = args.get("fixo")
                if not isinstance(fixed, bool):
                    raise BarraError("fixo precisa ser verdadeiro ou falso")
                pinned = [p for p in state["fixados"] if p != path]
                state["fixados"] = pinned + [path] if fixed else pinned
            elif action == "nome":
                path = _text(args.get("caminho"), "caminho")
                name = args.get("nome", "")
                if not isinstance(name, str):
                    raise BarraError("nome inválido")
                name = " ".join(name.split())
                if len(name) > MAX_NAME:
                    raise BarraError(f"o nome passa de {MAX_NAME} caracteres")
                if name:
                    state["nomes"][path] = name
                else:
                    state["nomes"].pop(path, None)
            else:
                project = _text(args.get("projeto"), "projeto", 200)
                color = args.get("cor", "")
                if not isinstance(color, str):
                    raise BarraError("cor inválida")
                color = color.strip().lower()
                if not color:
                    state["cores"].pop(project, None)
                elif COLOR.fullmatch(color):
                    state["cores"][project] = color
                else:
                    raise BarraError("a cor precisa ser #rrggbb")
            self._write(state)
            return state

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".barra-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
