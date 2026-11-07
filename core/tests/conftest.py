from __future__ import annotations

import socket
from pathlib import Path

import pytest

from harness_core.config import Settings

TOKEN = "token-de-teste"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Pasta com espaço de propósito: o caminho do relay precisa sobreviver às aspas.
    return Settings(
        home=tmp_path / "Harness Home",
        host="127.0.0.1",
        port=free_port(),
        token=TOKEN,
        worktrees=tmp_path / "workspaces",
    )


@pytest.fixture
def statusline_payload() -> dict:
    """Formato da statusline do Claude Code (code.claude.com/docs/en/statusline)."""
    return {
        "session_id": "abc",
        "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
        "workspace": {"current_dir": "/Users/teste/projeto"},
        "cost": {"total_cost_usd": 0.42},
        "context_window": {
            "context_window_size": 200000,
            "used_percentage": 38.2,
            "remaining_percentage": 61.8,
            "current_usage": {"input_tokens": 1200, "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 70000, "output_tokens": 900},
        },
        "rate_limits": {
            "five_hour": {"used_percentage": 23.5, "resets_at": 1794080000},
            "seven_day": {"used_percentage": 41.2, "resets_at": 1794400000},
        },
    }


@pytest.fixture
def accounts(settings: Settings, tmp_path: Path):
    """Contas numa pasta temporária, com um config.toml do Codex de mentira para copiar."""
    from harness_core.accounts import AccountStore

    source = tmp_path / "codex-config.toml"
    source.write_text('model = "gpt-teste"\n', encoding="utf-8")
    return AccountStore(settings.home, codex_config_source=source)


def run(*args: str, cwd: Path) -> str:
    import subprocess

    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Repositório git de verdade, com um commit e um .env fora do git."""
    path = tmp_path / "meu-repo"
    path.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=path)
    run("git", "config", "user.email", "teste@example.com", cwd=path)
    run("git", "config", "user.name", "Teste", cwd=path)
    (path / "app.py").write_text("print('oi')\n", encoding="utf-8")
    (path / ".gitignore").write_text(".env\n", encoding="utf-8")
    run("git", "add", ".", cwd=path)
    run("git", "commit", "-q", "-m", "primeiro", cwd=path)
    (path / ".env").write_text("CHAVE=local\n", encoding="utf-8")
    return path
