"""v0.3: agentes em arquivo, sprite, importação do Maestri e sessão com papel."""

import json
import os
import time
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core.agents import Agent, AgentError, AgentStore, agent_args, parse_agent, render_agent
from harness_core.app import create_app

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
PROMPT = 'Você é a coach do "Pedro".\nRegras:\n- # nada de spoiler: só perguntas\n- emoji 🚀 e acento ã'


def test_render_and_parse_round_trip_with_tricky_values():
    meta = {"nome": "Sócrates: tutor", "descricao": "Tutor # Python", "cli": "codex", "cor": "#007AFF", "pasta": "~/Documents/Brain"}
    parsed_meta, body = parse_agent(render_agent(meta, PROMPT))
    assert parsed_meta["nome"] == "Sócrates: tutor" and parsed_meta["descricao"] == "Tutor # Python"
    assert parsed_meta["cor"] == "#007AFF" and parsed_meta["cli"] == "codex"
    assert body.strip() == PROMPT


def test_store_create_edit_keep_id_and_delete_to_trash(settings):
    store = AgentStore(settings.home)
    assert store.list() == []
    created = store.save({"name": "Revisor de PR", "cli": "claude", "prompt": "Revise o diff."})
    assert created.id == "revisor-de-pr" and created.prompt == "Revise o diff."
    renamed = store.save({"name": "Revisor Chato", "cli": "codex", "prompt": "Mais rigor."}, created.id)
    assert renamed.id == "revisor-de-pr" and renamed.name == "Revisor Chato" and renamed.cli == "codex"
    assert store.save({"name": "Revisor de PR"}).id == "revisor-de-pr-2"
    store.delete("revisor-de-pr")
    assert [a["id"] for a in store.list()] == ["revisor-de-pr-2"]
    assert list((store.dir / ".lixeira").glob("revisor-de-pr-*.md"))  # nada some de vez
    with pytest.raises(AgentError):
        store.save({"name": "x", "cli": "gemini"})
    with pytest.raises(AgentError):
        store.get("../fora")


def test_sprite_must_be_png(settings):
    store = AgentStore(settings.home)
    agent = store.save({"name": "Aurora"})
    with pytest.raises(AgentError):
        store.set_sprite(agent.id, b"GIF89a")
    store.set_sprite(agent.id, PNG)
    assert store.get(agent.id).sprite and store.sprite_path(agent.id).read_bytes() == PNG
    store.clear_sprite(agent.id)
    assert not store.get(agent.id).sprite


def test_import_maestri_takes_codename_folder_and_cli_from_terminals(settings, tmp_path):
    roles = tmp_path / "Brain" / ".maestri" / "roles"
    for role_id, name, color in (("aaa-111", "Coach de Estudo", "#AF52DE"), ("bbb-222", "Bibliotecário", "#FF3B30")):
        (roles / role_id).mkdir(parents=True)
        (roles / role_id / "role.json").write_text(
            json.dumps({"id": role_id.upper(), "name": name, "color": color, "prompt": f"Você é o {name}."}), encoding="utf-8"
        )
    maestri = tmp_path / ".maestri"
    (maestri / "workspaces" / "w1").mkdir(parents=True)
    (maestri / "workspaces" / "w1" / "workspace.json").write_text(
        json.dumps({"canvas": {"items": [{"name": "Aurora", "assignedRoleId": "AAA-111", "command": "claude", "workingDirectory": "/Users/x/Brain"}]}}),
        encoding="utf-8",
    )
    store = AgentStore(settings.home)
    imported = store.import_maestri(roles, maestri)
    by_desc = {a.description: a for a in imported}
    assert by_desc["Coach de Estudo"].name == "Aurora" and by_desc["Coach de Estudo"].folder == "/Users/x/Brain"
    assert by_desc["Coach de Estudo"].color == "#AF52DE" and by_desc["Coach de Estudo"].origin == "maestri:AAA-111"
    assert by_desc["Bibliotecário"].name == "Bibliotecário"  # papel sem terminal: fica o nome do papel
    assert store.import_maestri(roles, maestri) == []  # importar de novo não duplica

    # Importado continua editável, e a origem não se perde.
    edited = store.save({"name": "Aurora Coach", "cli": "codex", "prompt": "outro"}, by_desc["Coach de Estudo"].id)
    assert edited.name == "Aurora Coach" and edited.origin == "maestri:AAA-111"


def test_agent_args_for_each_cli_carry_role_and_model():
    claude = agent_args(Agent(id="a", name="Aurora", cli="claude", model="sonnet", prompt=PROMPT))
    assert claude == ["--model", "sonnet", "-n", "Aurora", "--append-system-prompt", PROMPT]
    codex = agent_args(Agent(id="b", name="Farol", cli="codex", model="gpt-5", prompt=PROMPT))
    assert codex[:2] == ["-m", "gpt-5"] and codex[2] == "-c"
    key, _, value = codex[3].partition("=")
    assert key == "developer_instructions"
    assert tomllib.loads(f"v = {value}")["v"] == PROMPT  # o -c do Codex lê TOML
    assert agent_args(Agent(id="c", name="Vazio", cli="codex")) == []


def test_session_from_agent_runs_the_cli_with_its_role(settings, accounts, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "argv.txt"
    fake = bin_dir / "claude"
    fake.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a" >> "{record}"; done\npwd >> "{record}"\nsleep 5\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    workdir = tmp_path / "Brain"
    workdir.mkdir()

    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        agent = client.post(
            "/agents", json={"name": "Aurora", "cli": "claude", "folder": str(workdir), "prompt": "Você é a Aurora."}, headers=AUTH
        ).json()
        assert client.get("/agents", headers=AUTH).json()[0]["id"] == agent["id"]
        session = client.post("/sessions", json={"kind": "shell", "agent": agent["id"]}, headers=AUTH).json()
        assert session["kind"] == "claude" and session["title"] == "Aurora" and session["agent"] == agent["id"]
        for _ in range(50):
            if record.exists() and str(workdir) in record.read_text():
                break
            time.sleep(0.1)
        lines = record.read_text().splitlines()
        assert "--settings" in lines  # statusline e hooks do Harness continuam
        assert lines[lines.index("--append-system-prompt") + 1] == "Você é a Aurora."
        assert lines[-1] == str(workdir)  # abre na pasta do agente
        assert client.post("/sessions", json={"kind": "claude", "agent": "fantasma"}, headers=AUTH).status_code == 404

        # Sprite pela API, servida com token na URL para o <img>.
        assert client.post(f"/agents/{agent['id']}/sprite", content=b"nao-png", headers=AUTH).status_code == 400
        assert client.post(f"/agents/{agent['id']}/sprite", content=PNG, headers=AUTH).status_code == 204
        sprite = client.get(f"/agents/{agent['id']}/sprite", params={"token": TOKEN})
        assert sprite.status_code == 200 and sprite.content == PNG
        assert client.get(f"/agents/{agent['id']}/sprite").status_code == 401
