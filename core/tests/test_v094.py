"""v0.9.4: versão instalada e atualização, aviso do Codex pelo notify, código de saída no evento."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core import updates
from harness_core.app import create_app
from harness_core.relay import install_relay
from harness_core.sessions import codex_notify_args

from .conftest import TOKEN, run

AUTH = {"X-Harness-Token": TOKEN}


def fake_argv(kind, settings):
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


# --- versão instalada e atualização ---------------------------------------------------------------


def test_version_key_only_accepts_release_tags():
    assert updates.version_key("v0.9.10") == (0, 9, 10)
    assert updates.version_key("v1.0.0") > updates.version_key("v0.9.10")
    for bad in ("0.9.4", "v0.9", "v0.9.4-rc1", "", "ideia/automacoes"):
        assert updates.version_key(bad) is None


def test_dev_checkout_is_not_installed_and_never_offers_an_update(repo, tmp_path):
    run("git", "tag", "v0.9.9", cwd=repo)
    (repo / "core").mkdir()
    info = updates.check(tmp_path / "home", fetch=False, core_dir=repo / "core")
    assert info["instalada"] is False and info["tag"] is None
    assert info["repositorio"] == str(repo.resolve()) and info["ultima"] == "v0.9.9"
    assert info["nova"] is None  # a de desenvolvimento não se atualiza


def test_installed_copy_finds_its_repo_and_the_newer_tag(repo, tmp_path):
    run("git", "tag", "v0.9.4", cwd=repo)
    home = tmp_path / "home"
    copy = home / "versoes" / "v0.9.4"
    copy.parent.mkdir(parents=True)
    run("git", "clone", "-q", "--local", str(repo), str(copy), cwd=tmp_path)
    (copy / "core").mkdir()
    info = updates.check(home, fetch=False, core_dir=copy / "core")
    assert info["instalada"] is True and info["tag"] == "v0.9.4"
    assert info["repositorio"] == str(repo) and info["nova"] is None
    run("git", "commit", "-q", "--allow-empty", "-m", "segundo", cwd=repo)
    run("git", "tag", "v0.9.10", cwd=repo)
    run("git", "tag", "v0.9.5", cwd=repo)
    assert updates.tags(repo) == ["v0.9.10", "v0.9.5", "v0.9.4"]  # por número, não por texto
    assert updates.check(home, fetch=False, core_dir=copy / "core")["nova"] == "v0.9.10"


def test_update_command_quotes_the_repo_and_refuses_odd_versions(tmp_path):
    command = updates.update_command("/Users/pedro/meu repo", "v0.9.5")
    assert "'/Users/pedro/meu repo'" in command and "show v0.9.5:scripts/instalar.sh" in command
    assert 'sh "$f" v0.9.5' in command
    with pytest.raises(ValueError):
        updates.update_command("/repo", "v0.9.5; rm -rf ~")


def test_version_route_answers_for_the_dev_checkout(core):
    client, _ = core
    info = client.get("/sistema/versao", headers=AUTH).json()
    assert info["instalada"] is False and info["versao"]
    assert client.post("/sistema/atualizar", json={"versao": "v99.0.0"}, headers=AUTH).status_code in (400, 409)


# --- aviso do Codex pelo notify ---------------------------------------------------------------


def test_codex_notify_chains_the_notify_already_in_the_config(tmp_path):
    relay = tmp_path / "relay.sh"
    config = tmp_path / "config.toml"
    config.write_text('model = "x"\nnotify = ["/apps/Computer Use", "turn-ended"]\n', encoding="utf-8")
    args = codex_notify_args(relay, config)
    assert args[0] == "-c" and args[1].startswith("notify=")
    assert json.loads(args[1][len("notify=") :]) == [str(relay), "codex", "/apps/Computer Use", "turn-ended"]
    config.write_text("notify = 'texto solto'\n", encoding="utf-8")
    assert json.loads(codex_notify_args(relay, config)[1][7:]) == [str(relay), "codex"]
    config.write_text("isto não é toml [\n", encoding="utf-8")
    assert json.loads(codex_notify_args(relay, config)[1][7:]) == [str(relay), "codex"]
    assert json.loads(codex_notify_args(relay, tmp_path / "nao-existe.toml")[1][7:]) == [str(relay), "codex"]


def test_codex_session_gets_the_notify(core, settings, monkeypatch, tmp_path):
    client, app = core
    monkeypatch.setenv("HOME", str(tmp_path))  # a conta padrão lê ~/.codex
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text('notify = ["/bin/echo", "fim"]\n', encoding="utf-8")
    session = client.post("/sessions", json={"kind": "codex", "cwd": str(tmp_path)}, headers=AUTH).json()
    argv = app.state.manager.get(session["id"]).pty.argv
    value = next(a for a in argv if a.startswith("notify="))
    assert json.loads(value[7:]) == [str(settings.relay_path), "codex", "/bin/echo", "fim"]


def test_relay_codex_branch_calls_the_chained_notify_with_the_payload(tmp_path):
    relay = install_relay(tmp_path / "bin" / "relay.sh")
    out = tmp_path / "chamado.txt"
    chained = tmp_path / "anterior.sh"
    chained.write_text(f'#!/bin/sh\nprintf "%s|" "$@" > "{out}"\n', encoding="utf-8")
    chained.chmod(0o755)
    payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": "pronto"})
    env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_")}
    done = subprocess.run([str(relay), "codex", str(chained), "turn-ended", payload], env=env, capture_output=True, timeout=10)
    assert done.returncode == 0
    assert out.read_text(encoding="utf-8") == f"turn-ended|{payload}|"
    # Sem notify anterior: só avisa (aqui, sem núcleo) e sai com 0.
    assert subprocess.run([str(relay), "codex", payload], env=env, capture_output=True, timeout=10).returncode == 0


def test_codex_stop_and_enter_move_the_status(core, settings, tmp_path):
    client, app = core
    manager = app.state.manager
    session = client.post("/sessions", json={"kind": "shell", "cwd": str(tmp_path)}, headers=AUTH).json()
    live = manager.get(session["id"])
    live.kind = "codex"  # o shell de teste faz o papel do Codex (o binário de verdade não roda aqui)
    client.post("/hooks/event", params={"session": session["id"], "name": "Stop"}, json={"type": "agent-turn-complete"}, headers=AUTH)
    assert live.status == "waiting"
    manager.note_input(session["id"], "olá")
    assert live.status == "waiting"  # sem Enter, ainda escrevendo
    manager.note_input(session["id"], "\r")
    assert live.status == "working"
    client.delete(f"/sessions/{session['id']}", headers=AUTH)


# --- código de saída no evento ------------------------------------------------------------------


def test_exit_event_carries_the_exit_code(core, tmp_path):
    client, app = core
    manager = app.state.manager
    session = client.post("/sessions", json={"kind": "shell", "cwd": str(tmp_path)}, headers=AUTH).json()
    published: list[dict] = []
    original = manager.events.publish
    manager.events.publish = lambda event: (published.append(event), original(event))[1]
    manager._on_exit(session["id"], 3)
    manager.events.publish = original
    exited = [e for e in published if e.get("type") == "session.status"]
    assert exited and exited[-1]["status"] == "exited" and exited[-1]["exit_code"] == 3
    client.delete(f"/sessions/{session['id']}", headers=AUTH)
