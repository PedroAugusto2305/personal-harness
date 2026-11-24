"""v1.5.0: cada agente é de estudo ou de trabalho (o campo `tipo` no arquivo dele). O de estudo,
aberto pela tela de Agentes, abre uma conversa de estudo com ele mesmo (POST /estudo/sessao com
`agente`), que aparece no painel do Estudo; o de trabalho continua abrindo em Terminais."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.agents import AgentError, AgentStore, parse_agent
from harness_core.app import create_app

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def fake_argv(kind, _settings):
    return {"claude": ["/bin/cat"], "codex": ["/bin/cat"], "shell": ["/bin/cat"]}[kind]


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


# --- arquivo do agente ---------------------------------------------------------------------


def test_old_agent_file_without_type_is_work_and_keeps_working(settings):
    store = AgentStore(settings.home)
    store.dir.mkdir(parents=True)
    (store.dir / "aurora.md").write_text("---\nnome: Aurora\ncli: claude\n---\n\nVocê é a coach.\n", encoding="utf-8")
    agent = store.get("aurora")
    assert agent.tipo == "trabalho" and agent.to_dict()["tipo"] == "trabalho"
    # Salvar sem dizer o tipo (cliente antigo) grava o padrão no arquivo, sem mexer no resto.
    saved = store.save({"name": "Aurora", "cli": "claude", "prompt": "Você é a coach."}, "aurora")
    assert saved.tipo == "trabalho" and saved.prompt == "Você é a coach."
    assert parse_agent((store.dir / "aurora.md").read_text(encoding="utf-8"))[0]["tipo"] == "trabalho"


def test_type_is_saved_in_the_file_and_survives_reopening(settings):
    store = AgentStore(settings.home)
    new = store.save({"name": "Sócrates", "cli": "claude", "prompt": "Tutor."})
    assert new.tipo == "trabalho"  # agente novo nasce de trabalho
    study = store.save({"name": "Sócrates", "cli": "claude", "prompt": "Tutor.", "tipo": "estudo"}, new.id)
    assert study.tipo == "estudo"
    # "Fechar e abrir o app": outro AgentStore lê do mesmo arquivo.
    again = AgentStore(settings.home)
    assert again.get(new.id).tipo == "estudo" and [a["tipo"] for a in again.list()] == ["estudo"]
    # Pedido sem o tipo mantém o que estava no arquivo.
    assert again.save({"name": "Sócrates", "cli": "codex", "prompt": "Tutor."}, new.id).tipo == "estudo"
    assert again.save({"name": "Sócrates", "cli": "codex", "prompt": "Tutor.", "tipo": "trabalho"}, new.id).tipo == "trabalho"


def test_study_type_is_only_for_claude_or_codex(settings):
    store = AgentStore(settings.home)
    with pytest.raises(AgentError, match="Claude ou do Codex"):
        store.save({"name": "Script", "cli": "outra", "command": "/bin/cat", "tipo": "estudo"})
    with pytest.raises(AgentError, match="tipo de agente desconhecido"):
        store.save({"name": "Script", "cli": "claude", "tipo": "lazer"})
    study = store.save({"name": "Tutor", "cli": "claude", "tipo": "estudo"})
    # Trocar a CLI para "outra" sem dizer o tipo volta para trabalho (em vez de travar o salvar).
    assert store.save({"name": "Tutor", "cli": "outra", "command": "/bin/cat"}, study.id).tipo == "trabalho"
    # Arquivo mexido à mão com estudo numa outra CLI é lido como trabalho.
    (store.dir / "mexido.md").write_text("---\nnome: Mexido\ntipo: estudo\ncli: outra\ncomando: /bin/cat\n---\n", encoding="utf-8")
    assert store.get("mexido").tipo == "trabalho"


# --- rotas ---------------------------------------------------------------------------------


def test_routes_create_and_update_type(core):
    client, _app = core
    created = client.post("/agents", json={"name": "Tutor", "cli": "claude", "prompt": "Tutor.", "tipo": "estudo"}, headers=AUTH)
    assert created.status_code == 201 and created.json()["tipo"] == "estudo"
    agent_id = created.json()["id"]
    plain = client.post("/agents", json={"name": "Revisor", "cli": "codex"}, headers=AUTH).json()
    assert plain["tipo"] == "trabalho"
    assert client.post("/agents", json={"name": "X", "tipo": "lazer"}, headers=AUTH).status_code == 422
    refused = client.post("/agents", json={"name": "Script", "cli": "outra", "command": "/bin/cat", "tipo": "estudo"}, headers=AUTH)
    assert refused.status_code == 400 and "Claude ou do Codex" in refused.json()["detail"]
    # Cliente antigo (sem o campo) não apaga o tipo.
    kept = client.put(f"/agents/{agent_id}", json={"name": "Tutor", "cli": "claude", "prompt": "Tutor."}, headers=AUTH).json()
    assert kept["tipo"] == "estudo"
    swapped = client.put(f"/agents/{agent_id}", json={"name": "Tutor", "cli": "claude", "prompt": "Tutor.", "tipo": "trabalho"}, headers=AUTH).json()
    assert swapped["tipo"] == "trabalho"
    assert {a["id"]: a["tipo"] for a in client.get("/agents", headers=AUTH).json()} == {agent_id: "trabalho", plain["id"]: "trabalho"}


def test_study_agent_opens_its_own_study_conversation(core):
    client, app = core
    tutor = client.post("/agents", json={"name": "Platão", "cli": "claude", "prompt": "Você é o Platão.", "tipo": "estudo"}, headers=AUTH).json()
    # Sem agente conectado ao Estudo, o agente de estudo abre a conversa dele mesmo assim.
    assert client.get("/estudo", headers=AUTH).json()["agente"] == ""
    r = client.post("/estudo/sessao", json={"tipo": "conversa", "agente": tutor["id"]}, headers=AUTH)
    assert r.status_code == 201, r.text
    session = app.state.manager.get(r.json()["id"])
    argv = session.pty.argv
    system = argv[argv.index("--append-system-prompt") + 1]
    # É uma conversa de estudo como a do Estudo: tag estudo (o painel do Estudo mostra) e o modo de estudo no papel.
    assert session.agent == tutor["id"] and session.tag == "estudo" and r.json()["title"] == "Estudo · conversa"
    assert system.startswith("Você é o Platão.") and "estudo_registrar" in system
    ctx = app.state.hub.context(app.state.hub.register(session.id))
    assert ctx.estudo and ctx.who == "Platão"


def test_study_conversation_refuses_work_agents_unless_connected(core):
    client, _app = core
    work = client.post("/agents", json={"name": "Revisor", "cli": "claude", "prompt": "Revise."}, headers=AUTH).json()
    refused = client.post("/estudo/sessao", json={"tipo": "conversa", "agente": work["id"]}, headers=AUTH)
    assert refused.status_code == 400 and "agente de trabalho" in refused.json()["detail"]
    assert client.post("/estudo/sessao", json={"tipo": "conversa", "agente": "nao-existe"}, headers=AUTH).status_code == 404
    # O conectado ao Estudo vale mesmo sendo de trabalho (como antes da v1.5.0).
    client.put("/estudo/agente", json={"id": work["id"]}, headers=AUTH)
    assert client.post("/estudo/sessao", json={"tipo": "conversa", "agente": work["id"]}, headers=AUTH).status_code == 201
    assert client.post("/estudo/sessao", json={"tipo": "conversa"}, headers=AUTH).status_code == 201


def test_terminal_of_study_agent_gets_study_tools_anywhere(core):
    client, app = core
    tutor = client.post("/agents", json={"name": "Platão", "cli": "claude", "prompt": "Tutor.", "tipo": "estudo"}, headers=AUTH).json()
    work = client.post("/agents", json={"name": "Revisor", "cli": "claude", "prompt": "Revise."}, headers=AUTH).json()
    hub = app.state.hub
    opened = client.post("/sessions", json={"kind": "claude", "agent": tutor["id"]}, headers=AUTH).json()
    assert hub.context(hub.register(opened["id"])).estudo  # terminal comum do agente de estudo
    other = client.post("/sessions", json={"kind": "claude", "agent": work["id"]}, headers=AUTH).json()
    assert not hub.context(hub.register(other["id"])).estudo
    # Trocar o tipo com o terminal aberto não move o terminal (a tag dele continua a mesma).
    client.put(f"/agents/{tutor['id']}", json={"name": "Platão", "cli": "claude", "prompt": "Tutor.", "tipo": "trabalho"}, headers=AUTH)
    assert app.state.manager.get(opened["id"]).tag is None
