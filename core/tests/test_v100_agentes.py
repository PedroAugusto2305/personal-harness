"""v1.0, revisão da parte 1 da v0.9.8 (agentes e terminal): acordar não volta a hibernar na hora,
porta aberta não hiberna, linha de comando ruim não derruba rotina nem reiniciar, o pedido da CLI
"outra" entra digitado, a conversa do Codex é a do terminal certo, o /contexto não lê a conversa
e as variáveis do agente perdem as aspas e não trocam a conta."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.agents import AgentError, parse_env
from harness_core.app import create_app
from harness_core.routines import RoutineStore

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
MISSING = "cli-que-nao-existe-metis"


def waiting_argv(kind, settings):
    # Fica vivo com qualquer argumento que a MÊTIS acrescente (viram $0, $1… do sh).
    return ["/bin/sh", "-c", "exec sleep 300"]


@pytest.fixture
def core(settings, accounts, monkeypatch, tmp_path):
    monkeypatch.setattr(sessions_mod, "resolve_argv", waiting_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    app.state.cli_homes = {"claude": tmp_path / "homes" / "claude", "codex": tmp_path / "homes" / "codex"}
    with TestClient(app) as client:
        yield client, app
        for session_id in list(app.state.manager.sessions):
            client.delete(f"/sessions/{session_id}", headers=AUTH)


def idle_agent(client, app, minutes: float = 20) -> str:
    """Um Claude esperando há `minutes` minutos, com a hibernação ligada em 15."""
    assert client.put("/ajustes", json={"hibernar_min": 15}, headers=AUTH).status_code == 200
    sid = client.post("/sessions", json={"kind": "claude"}, headers=AUTH).json()["id"]
    session = app.state.manager.get(sid)
    session.status = "waiting"
    session.pty.last_input = session.pty.last_output = time.time() - minutes * 60
    return sid


# --- hibernar ---------------------------------------------------------------------------------


def test_waking_counts_as_activity(core):
    """Acordar pelo foco não pode ser desfeito na volta seguinte do hibernate_watch."""
    client, app = core
    manager = app.state.manager
    sid = idle_agent(client, app)
    assert manager.hibernate_idle() == [sid]
    assert client.post(f"/sessions/{sid}/acordar", headers=AUTH).json()["hibernando"] is False
    assert manager.hibernate_idle() == []  # antes: parado de novo, em laço a cada 30 s
    assert not manager.get(sid).pty.paused


def test_agent_with_open_port_does_not_hibernate(core):
    """O SIGSTOP vai para o grupo inteiro: o servidor de dev que o agente subiu pararia junto."""
    client, app = core
    manager = app.state.manager
    sid = idle_agent(client, app)
    manager.get(sid).ports = [5173]
    assert manager.hibernate_idle() == []
    manager.get(sid).ports = []
    assert manager.hibernate_idle() == [sid]


# --- linha de comando que não roda --------------------------------------------------------------


def test_routine_with_missing_cli_records_error(core, settings):
    """Rotina antiga (que ficou fora das automações) com agente "outra" fora do PATH: vira "erro"
    com o motivo, em vez de o CommandError subir pelo agendador e matar a task dele."""
    client, _ = core
    agent = client.post("/agents", json={"name": "Sumido", "cli": "outra", "command": f"{MISSING} --x"}, headers=AUTH).json()
    legacy = RoutineStore(settings.home)  # a mesma pasta que o núcleo usa
    routine = legacy.save({"name": "Testes", "agent": agent["id"], "days": [0, 1, 2, 3, 4, 5, 6], "time": "23:59", "notify": False, "prompt": "rode os testes"})
    run = client.post(f"/rotinas/{routine.id}/rodar", headers=AUTH)
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "erro" and MISSING in run.json()["detail"]


def test_restart_with_missing_cli_is_a_clear_error(core, tmp_path):
    client, app = core
    agent = client.post("/agents", json={"name": "Gato", "cli": "outra", "command": "cat"}, headers=AUTH).json()
    sid = client.post("/sessions", json={"kind": "shell", "agent": agent["id"]}, headers=AUTH).json()["id"]
    assert client.put(f"/agents/{agent['id']}", json={"name": "Gato", "cli": "outra", "command": MISSING}, headers=AUTH).status_code == 200
    restarted = client.post(f"/sessions/{sid}/reiniciar", json={}, headers=AUTH)
    assert restarted.status_code == 400 and restarted.json()["detail"] == f"não achei {MISSING} no PATH"


# --- pedido inicial da CLI "outra" -------------------------------------------------------------


def test_other_cli_gets_the_initial_prompt_typed(core, monkeypatch):
    """A CLI "outra" não tem flag para o pedido: ele entra digitado quando ela se acalma, numa linha
    só (sem a colagem ligada, cada quebra de linha viraria um Enter). Antes, sumia sem aviso."""
    client, app = core
    monkeypatch.setattr(sessions_mod, "OTHER_PROMPT_QUIET", 0.3)
    agent = client.post("/agents", json={"name": "Eco", "cli": "outra", "command": "sh", "args": "-c 'echo pronto; exec cat'"}, headers=AUTH).json()
    created = client.post("/sessions", json={"kind": "shell", "agent": agent["id"], "prompt": "rode\nos testes"}, headers=AUTH)
    assert created.status_code == 201, created.text
    pty = app.state.manager.get(created.json()["id"]).pty
    assert "rode" not in pty.argv  # nada de pedido na linha de comando de uma CLI desconhecida
    deadline = time.time() + 8
    while time.time() < deadline and b"rode os testes\r\n" not in bytes(pty._buffer):
        time.sleep(0.1)
    assert b"rode os testes" in bytes(pty._buffer)


# --- a conversa da sessão ------------------------------------------------------------------------


def rollout(folder: Path, codex_dir: Path, thread: str, text: str, mtime: float) -> Path:
    path = codex_dir / f"rollout-2026-11-10-{thread}.jsonl"
    path.write_text(
        "\n".join(json.dumps(x) for x in [
            {"type": "session_meta", "payload": {"id": thread, "cwd": str(folder), "timestamp": "2026-11-10T10:00:00Z"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}},
        ]) + "\n",
        encoding="utf-8",
    )  # fmt: skip
    os.utime(path, (mtime, mtime))
    return path


def test_codex_conversation_is_the_one_of_this_terminal(core, tmp_path):
    """Dois Codex na mesma pasta: o thread-id do notify diz qual conversa é de qual terminal."""
    client, app = core
    folder = tmp_path / "repo"
    folder.mkdir()
    first = client.post("/sessions", json={"kind": "codex", "cwd": str(folder)}, headers=AUTH).json()["id"]
    second = client.post("/sessions", json={"kind": "codex", "cwd": str(folder)}, headers=AUTH).json()["id"]
    codex_dir = tmp_path / "homes" / "codex" / "sessions" / "2026" / "11" / "10"
    codex_dir.mkdir(parents=True)
    now = time.time()
    rollout(folder, codex_dir, "thread-um", "pedido do primeiro", now + 1)
    rollout(folder, codex_dir, "thread-dois", "pedido do segundo", now + 30)  # a mais recente é do segundo
    notify = {"type": "agent-turn-complete", "thread-id": "thread-um", "turn-id": "1", "cwd": str(folder), "last-assistant-message": "feito"}
    assert client.post(f"/hooks/event?session={first}&name=Stop", json=notify, headers=AUTH).status_code == 204
    mine = client.get(f"/sessions/{first}/conversa", headers=AUTH).json()
    assert mine["id_conversa"] == "thread-um"  # antes: a mais recente da pasta, a do segundo
    # O segundo ainda não terminou turno: fica com a mais recente que não é de outro terminal.
    assert client.get(f"/sessions/{second}/conversa", headers=AUTH).json()["id_conversa"] == "thread-dois"


def test_context_window_does_not_read_the_conversation(core, tmp_path, monkeypatch):
    """O Inspector chama o /contexto a cada resposta: a conversa (até 400 KB do transcript) fica no /conversa."""
    client, app = core
    transcript = tmp_path / "conversa.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"content": "oi"}}) + "\n", encoding="utf-8")
    sid = client.post("/sessions", json={"kind": "claude"}, headers=AUTH).json()["id"]
    app.state.manager.record_statusline(sid, {"session_id": "conv-1", "transcript_path": str(transcript)})
    window = client.get(f"/sessions/{sid}/contexto", headers=AUTH).json()
    assert window["available"] is True and "id_conversa" not in window and "texto" not in window
    conversation = client.get(f"/sessions/{sid}/conversa", headers=AUTH).json()
    assert conversation["id_conversa"] == "conv-1" and conversation["texto"] == "você: oi"


# --- variáveis do agente ---------------------------------------------------------------------------


def test_agent_env_drops_quotes_and_keeps_the_account():
    assert parse_env("OPENAI_API_KEY=\"sk-abc\"\nNOME='dois nomes'\nMEIO=a\"b\"c\nSO_UMA=\"") == {
        "OPENAI_API_KEY": "sk-abc",
        "NOME": "dois nomes",
        "MEIO": 'a"b"c',
        "SO_UMA": '"',
    }
    for key in ("CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        with pytest.raises(AgentError, match="Conta"):
            parse_env(f"{key}=~/.claude-outra")


def test_agent_env_reaches_the_session_without_quotes_or_another_account(core):
    client, app = core
    refused = client.post("/agents", json={"name": "Fujão", "cli": "claude", "env": "CLAUDE_CONFIG_DIR=/tmp/outra"}, headers=AUTH)
    assert refused.status_code == 400 and "CLAUDE_CONFIG_DIR" in refused.json()["detail"]
    agent = client.post("/agents", json={"name": "Chave", "cli": "codex", "env": 'OPENAI_API_KEY="sk-abc"'}, headers=AUTH).json()
    sid = client.post("/sessions", json={"kind": "codex", "agent": agent["id"]}, headers=AUTH).json()["id"]
    assert app.state.manager.get(sid).pty.env["OPENAI_API_KEY"] == "sk-abc"
