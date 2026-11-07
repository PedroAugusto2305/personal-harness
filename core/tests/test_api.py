import json
import subprocess
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from harness_core.app import create_app
from harness_core.sessions import child_env

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


@pytest.fixture
def client(settings, accounts, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/sh")
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False)) as test_client:
        yield test_client


def test_health_is_open_but_everything_else_needs_the_token(client):
    assert client.get("/health").json()["ok"] is True
    assert client.get("/sessions").status_code == 401
    assert client.get("/sessions", headers={"X-Harness-Token": "errado"}).status_code == 401
    assert client.get("/sessions", headers=AUTH).json() == []


def test_shell_session_round_trip_over_websocket(client):
    created = client.post("/sessions", json={"kind": "shell", "cwd": "/tmp"}, headers=AUTH)
    assert created.status_code == 201
    session_id = created.json()["id"]

    with client.websocket_connect(f"/sessions/{session_id}/pty?token={TOKEN}") as ws:
        ws.send_text(json.dumps({"type": "resize", "cols": 90, "rows": 20}))
        ws.send_text(json.dumps({"type": "input", "data": "echo harness-$((40+2))\n"}))
        seen = b""
        deadline = time.time() + 5
        while b"harness-42" not in seen and time.time() < deadline:
            seen += ws.receive_bytes()
        assert b"harness-42" in seen

    assert client.delete(f"/sessions/{session_id}", headers=AUTH).status_code == 204
    assert client.get("/sessions", headers=AUTH).json() == []


def test_websocket_rejects_wrong_token(client):
    created = client.post("/sessions", json={"kind": "shell", "cwd": "/tmp"}, headers=AUTH).json()
    with pytest.raises(Exception):
        with client.websocket_connect(f"/sessions/{created['id']}/pty?token=errado") as ws:
            ws.receive_bytes()


def test_child_env_drops_orca_and_nested_claude_markers(settings, monkeypatch):
    monkeypatch.setenv("ORCA_AGENT_HOOK_PORT", "1234")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "segredo")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/teste/.claude-trabalho")
    monkeypatch.setenv("HARNESS_TOKEN", "vazado")
    env = child_env(settings, "s1")
    for leaked in ("ORCA_AGENT_HOOK_PORT", "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_TOKEN"):
        assert leaked not in env
    assert env["CLAUDE_CONFIG_DIR"] == "/Users/teste/.claude-trabalho"  # conta escolhida pelo usuário passa
    assert env["HARNESS_TOKEN"] == settings.token and env["HARNESS_SESSION_ID"] == "s1"


@pytest.fixture
def live_core(settings, accounts, monkeypatch):
    """Núcleo de verdade numa thread, para o relay.sh falar com ele por curl."""
    monkeypatch.setenv("SHELL", "/bin/sh")
    app = create_app(settings, accounts=accounts, poll_codex=False)
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield app
    server.should_exit = True
    thread.join(timeout=5)


def test_relay_script_delivers_statusline_and_hooks(live_core, settings, statusline_payload):
    with httpx.Client(base_url=settings.url, headers=AUTH) as http:
        session_id = http.post("/sessions", json={"kind": "shell", "cwd": "/tmp"}).json()["id"]
        env = {**child_env(settings, session_id), "PATH": "/usr/bin:/bin"}
        relay = str(settings.relay_path)

        out = subprocess.run(["/bin/sh", relay, "statusline"], input=json.dumps(statusline_payload), env=env, capture_output=True, text=True, timeout=10)
        assert out.returncode == 0
        assert out.stdout == "◆ harness · Opus 5.5 · contexto 38%"

        hook = subprocess.run(["/bin/sh", relay, "hook", "UserPromptSubmit"], input="{}", env=env, capture_output=True, text=True, timeout=10)
        assert hook.returncode == 0 and hook.stdout == ""

        session = next(s for s in http.get("/sessions").json() if s["id"] == session_id)
        assert session["status"] == "working"
        assert session["statusline"]["context"]["used_pct"] == 38.2
        # Os limites são da conta: sessão sem conta própria cai na conta ativa do Claude.
        assert http.get("/usage").json()["claude"]["padrao"]["five_hour"]["used_pct"] == 23.5
        http.delete(f"/sessions/{session_id}")


def test_relay_is_silent_and_harmless_without_a_core(settings, statusline_payload):
    from harness_core.relay import install_relay

    relay = install_relay(settings.relay_path)
    env = {"PATH": "/usr/bin:/bin"}  # sessão fora do Harness: sem variáveis do núcleo
    out = subprocess.run(["/bin/sh", str(relay), "statusline"], input=json.dumps(statusline_payload), env=env, capture_output=True, text=True, timeout=10)
    assert out.returncode == 0 and out.stdout == ""


def test_repeated_titles_get_a_number(client):
    titles = [client.post("/sessions", json={"kind": "shell", "cwd": "/tmp", "title": "Shell"}, headers=AUTH).json()["title"] for _ in range(3)]
    assert titles == ["Shell", "Shell 2", "Shell 3"]
