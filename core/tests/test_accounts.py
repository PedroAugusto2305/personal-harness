import json
import stat

import pytest

from harness_core.accounts import DEFAULT_ID, AccountStore, UnknownAccount, slugify
from harness_core.cli import main as harness_cli
from harness_core.sessions import SessionManager


def test_store_starts_with_the_default_account_for_each_cli(accounts):
    listed = accounts.list()
    for provider in ("claude", "codex"):
        assert listed[provider]["active"] == DEFAULT_ID
        assert listed[provider]["accounts"] == [{"id": DEFAULT_ID, "name": "padrão", "dir": None, "active": True}]
    assert accounts.env("claude", accounts.active("claude")) == {}  # padrão = ~/.claude de sempre


def test_add_creates_a_private_folder_and_switch_changes_the_env(accounts, settings):
    trabalho = accounts.add("claude", "Trabalho Seller")
    assert trabalho.id == "trabalho-seller"
    folder = settings.home / "contas" / "claude-trabalho-seller"
    assert trabalho.dir == str(folder) and folder.is_dir()
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700

    accounts.activate("claude", "trabalho-seller")
    assert accounts.active("claude").name == "Trabalho Seller"
    assert accounts.env("claude", accounts.active("claude")) == {"CLAUDE_CONFIG_DIR": str(folder)}
    assert stat.S_IMODE((settings.home / "accounts.json").stat().st_mode) == 0o600


def test_codex_account_copies_config_but_never_the_login(accounts):
    pessoal = accounts.add("codex", "Pessoal")
    files = {p.name for p in __import__("pathlib").Path(pessoal.dir).iterdir()}
    assert files == {"config.toml"}
    assert accounts.env("codex", pessoal) == {"CODEX_HOME": pessoal.dir}


def test_names_are_unique_and_find_accepts_name_or_id(accounts):
    assert accounts.add("codex", "Pessoal").id == "pessoal"
    assert accounts.add("codex", "pessoal").id == "pessoal-2"
    assert accounts.find("codex", "PESSOAL").id == "pessoal"
    assert accounts.find("codex", "pessoal-2").id == "pessoal-2"
    with pytest.raises(UnknownAccount):
        accounts.find("codex", "não existe")
    with pytest.raises(UnknownAccount):
        accounts.activate("claude", "pessoal")  # conta do Codex não vale para o Claude


def test_slugify_handles_accents_and_symbols():
    assert slugify("Conta Ação #2") == "conta-acao-2"
    assert slugify("***") == "conta"


def test_corrupted_file_falls_back_to_default(settings):
    settings.home.mkdir(parents=True)
    (settings.home / "accounts.json").write_text("{quebrado", encoding="utf-8")
    assert AccountStore(settings.home).active("codex").id == DEFAULT_ID


def test_session_env_uses_the_chosen_or_active_account(settings, accounts, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    manager = SessionManager(settings, accounts)
    trabalho = accounts.add("claude", "Trabalho")

    env, used = manager.session_env("claude", "s1", None)
    assert used == DEFAULT_ID and "CLAUDE_CONFIG_DIR" not in env

    env, used = manager.session_env("claude", "s1", "trabalho")
    assert used == "trabalho" and env["CLAUDE_CONFIG_DIR"] == trabalho.dir

    accounts.activate("claude", "trabalho")
    env, used = manager.session_env("claude", "s1", None)
    assert used == "trabalho" and env["CLAUDE_CONFIG_DIR"] == trabalho.dir

    env, used = manager.session_env("shell", "s1", None)
    assert used is None and "CLAUDE_CONFIG_DIR" not in env


def test_cli_lists_switches_and_tells_the_core(settings, accounts, monkeypatch, capsys):
    monkeypatch.setenv("HARNESS_HOME", str(settings.home))
    accounts.add("codex", "Pessoal")
    notified = []
    monkeypatch.setattr("harness_core.cli._notify_core", lambda home: notified.append(home))

    assert harness_cli(["contas"]) == 0
    out = capsys.readouterr().out
    assert "codex" in out and "Pessoal" in out and "pasta padrão da CLI" in out

    assert harness_cli(["switch", "codex", "pessoal"]) == 0
    assert "agora usando a conta Pessoal" in capsys.readouterr().out
    assert json.loads((settings.home / "accounts.json").read_text())["codex"]["active"] == "pessoal"
    assert notified == [settings.home]

    assert harness_cli(["switch", "codex", "fantasma"]) == 1
    assert "não encontrada" in capsys.readouterr().err


def test_cli_login_runs_the_official_login_in_the_account_folder(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_HOME", str(settings.home))
    monkeypatch.setattr("harness_core.cli._notify_core", lambda home: None)
    monkeypatch.setattr("harness_core.cli.shutil.which", lambda name: f"/opt/bin/{name}")
    calls = []
    monkeypatch.setattr("harness_core.cli.os.execvpe", lambda exe, argv, env: calls.append((exe, argv, env)))

    harness_cli(["login", "codex", "Cliente X"])
    exe, argv, env = calls[0]
    assert argv == ["/opt/bin/codex", "login"]
    assert env["CODEX_HOME"] == str(settings.home / "contas" / "codex-cliente-x")

    harness_cli(["login", "claude", "Cliente X"])
    exe, argv, env = calls[1]
    assert argv == ["/opt/bin/claude"]
    assert env["CLAUDE_CONFIG_DIR"] == str(settings.home / "contas" / "claude-cliente-x")
