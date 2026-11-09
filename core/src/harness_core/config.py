"""Configuração do núcleo, lida das variáveis de ambiente."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 47830
# Mesma pasta do Orca: durante a migração, os dois enxergam as mesmas worktrees.
DEFAULT_WORKTREES = Path.home() / "orca" / "workspaces"
# O vault Obsidian do Pedro; BRAIN_VAULT é a mesma variável que o brain.py usa.
DEFAULT_BRAIN = Path.home() / "Documents" / "Brain"
# Onde o Claude Code guarda as pastas confiáveis da conta padrão (as outras contas usam
# <CLAUDE_CONFIG_DIR>/.claude.json).
DEFAULT_CLAUDE_JSON = Path.home() / ".claude.json"


@dataclass(frozen=True)
class Settings:
    home: Path
    host: str
    port: int
    token: str
    worktrees: Path = DEFAULT_WORKTREES
    brain: Path = DEFAULT_BRAIN
    claude_json: Path = DEFAULT_CLAUDE_JSON
    #: v0.9.8: o perfil deste núcleo (HARNESS_PROFILE); "principal" é a ~/.harness de sempre.
    profile: str = "principal"
    #: A pasta foi imposta pelo ambiente (HARNESS_HOME, como no app de desenvolvimento e nos
    #: testes): dá para ver os perfis, não dá para trocar daqui.
    locked: bool = False

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def relay_path(self) -> Path:
        return self.home / "bin" / "relay.sh"


def load_settings() -> Settings:
    """Pasta, porta e Brain vêm do perfil (HARNESS_PROFILE, lido do registro de perfis);
    HARNESS_HOME, HARNESS_PORT e BRAIN_VAULT, quando vêm no ambiente, valem por cima."""
    from . import profiles

    profile_id, profile = profiles.resolve(os.environ.get("HARNESS_PROFILE"), DEFAULT_PORT)
    env_home = os.environ.get("HARNESS_HOME")
    if env_home:
        home = Path(env_home).expanduser()
    elif profile is not None and profile_id != profiles.MAIN_ID:
        home = profile.folder
    else:
        home = profiles.main_home()
    expected = profile.folder if profile is not None and profile_id != profiles.MAIN_ID else profiles.main_home()
    locked = bool(env_home) and home.resolve() != expected.resolve()
    port = int(os.environ.get("HARNESS_PORT") or (profile.porta if profile is not None and profile_id != profiles.MAIN_ID else DEFAULT_PORT))
    token = os.environ.get("HARNESS_TOKEN") or secrets.token_urlsafe(32)
    worktrees = Path(os.environ.get("HARNESS_WORKTREES_DIR") or DEFAULT_WORKTREES).expanduser()
    # O Brain do perfil (quando ele tem um) vale mais que o padrão do ambiente.
    brain = (profile.brain if profile is not None and profile.brain else None) or Path(os.environ.get("BRAIN_VAULT") or DEFAULT_BRAIN).expanduser()
    claude_json = Path(os.environ.get("HARNESS_CLAUDE_JSON") or DEFAULT_CLAUDE_JSON).expanduser()
    return Settings(
        home=home,
        host="127.0.0.1",
        port=port,
        token=token,
        worktrees=worktrees,
        brain=brain,
        claude_json=claude_json,
        profile=profile_id,
        locked=locked,
    )
