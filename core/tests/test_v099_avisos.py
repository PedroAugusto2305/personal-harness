"""v0.9.9: aviso do macOS pelo app da MÊTIS (ícone dela), com o osascript como reserva."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from harness_core import system
from harness_core.app import create_app

from .conftest import TOKEN


def make_app(tmp_path: Path) -> Path:
    exe = tmp_path / "MÊTIS.app" / "Contents" / "MacOS" / "harness"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    return exe


def test_set_notifier_accepts_only_an_app_executable(tmp_path):
    exe = make_app(tmp_path)
    assert system.set_notifier(str(exe)) is True
    assert system.notifier() == str(exe)
    loose = tmp_path / "harness"
    loose.write_text("")
    assert system.set_notifier(str(loose)) is False
    assert system.notifier() == ""
    assert system.set_notifier("relativo/MÊTIS.app/Contents/MacOS/harness") is False
    assert system.set_notifier(str(tmp_path / "Falta.app" / "Contents" / "MacOS" / "harness")) is False
    assert system.set_notifier("") is False


def test_app_notify_passes_json_and_reads_exit_code(tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0 if len(calls) == 1 else 3)

    payload = {"titulo": "Sócrates terminou", "texto": "estudo", "som": True, "alvo": "sessao:abc", "grupo": "abc"}
    assert system._app_notify("/x/MÊTIS.app/Contents/MacOS/harness", payload, run=run) is True
    argv, kwargs = calls[0]
    assert argv[1] == "--aviso"
    assert json.loads(argv[2]) == payload
    assert kwargs["timeout"] == 8
    # Sem permissão (3): quem chama cai no osascript.
    assert system._app_notify("/x/MÊTIS.app/Contents/MacOS/harness", payload, run=run) is False


def test_mac_notify_falls_back_to_osascript(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(system, "_app_notify", lambda exe, payload: sent.append(("app", payload["alvo"])) or False)
    monkeypatch.setattr(system, "_osascript_notify", lambda title, text, sound: sent.append(("osascript", title)))

    class Now:
        def __init__(self, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(system.threading, "Thread", Now)
    system.set_notifier(str(make_app(tmp_path)))
    system.mac_notify("Hermes espera você", "personal-harness", True, "sessao:s1", "s1")
    assert sent == [("app", "sessao:s1"), ("osascript", "Hermes espera você")]
    sent.clear()
    system.set_notifier("")
    system.mac_notify("Hermes terminou", "", False)
    assert sent == [("osascript", "Hermes terminou")]


def test_route_registers_the_app(tmp_path, settings, accounts):
    exe = make_app(tmp_path)
    auth = {"X-Harness-Token": TOKEN}
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        response = client.put("/avisos/app", json={"exe": str(exe)}, headers=auth)
        assert response.status_code == 200
        assert response.json() == {"ok": True, "exe": str(exe)}
        assert client.put("/avisos/app", json={"exe": ""}, headers=auth).json() == {"ok": False, "exe": ""}
        assert client.put("/avisos/app", json={"exe": str(exe)}).status_code == 401
