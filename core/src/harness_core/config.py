"""Configuração do núcleo, lida das variáveis de ambiente."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 47830
# Mesma pasta do Orca: durante a migração, os dois enxergam as mesmas worktrees.
DEFAULT_WORKTREES = Path.home() / "orca" / "workspaces"


@dataclass(frozen=True)
class Settings:
    home: Path
    host: str
    port: int
    token: str
    worktrees: Path = DEFAULT_WORKTREES

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def relay_path(self) -> Path:
        return self.home / "bin" / "relay.sh"


def load_settings() -> Settings:
    home = Path(os.environ.get("HARNESS_HOME") or Path.home() / ".harness").expanduser()
    port = int(os.environ.get("HARNESS_PORT") or DEFAULT_PORT)
    token = os.environ.get("HARNESS_TOKEN") or secrets.token_urlsafe(32)
    worktrees = Path(os.environ.get("HARNESS_WORKTREES_DIR") or DEFAULT_WORKTREES).expanduser()
    return Settings(home=home, host="127.0.0.1", port=port, token=token, worktrees=worktrees)
