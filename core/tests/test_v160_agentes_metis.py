"""v1.6.0: a MÊTIS trabalha só com os agentes dela.

O importado do Maestri que não foi migrado (`origem: maestri:<id>`) não aparece em lista nenhuma
e nada o abre; o migrado (sem a origem, com `migrado: maestri:<id>`) funciona como qualquer outro;
a importação do Maestri saiu; e as skills do Maestri ficam desligadas nas sessões da MÊTIS."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import barra, maestri
from harness_core import sessions as sessions_mod
from harness_core.agents import AgentError, AgentStore, agent_args, parse_agent
from harness_core.app import create_app
from harness_core.claude_settings import build_claude_settings, claude_argv

from .conftest import TOKEN
from .test_brain import client, vault  # noqa: F401 (fixtures do Brain com os projetos Alfa e Beta)

AUTH = {"X-Harness-Token": TOKEN}
RELAY = Path("/Users/teste/Harness Home/bin/relay.sh")
LEFTOVER = 'nome: Vitrine\ncli: claude\norigem: "maestri:AAA-111"\n'
MIGRATED = 'nome: Aurora\ntipo: estudo\ncli: claude\norigem:\nmigrado: "maestri:BBB-222"\n'


def write_agent(home: Path, agent_id: str, header: str, body: str) -> Path:
    folder = home / "agentes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{agent_id}.md"
    path.write_text(f"---\n{header}---\n\n{body}\n", encoding="utf-8")
    return path


def skill(folder: Path, name: str) -> Path:
    (folder / name).mkdir(parents=True, exist_ok=True)
    (folder / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}\n---\n", encoding="utf-8")
    return folder / name / "SKILL.md"


def fake_argv(kind, _settings):
    return {"claude": ["/bin/cat"], "codex": ["/bin/cat"], "shell": ["/bin/cat"]}[kind]


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as test_client:
        yield test_client, app


# --- os arquivos dos agentes ---------------------------------------------------------------


def test_leftover_from_maestri_is_out_and_migrated_one_is_a_metis_agent(settings):
    leftover = write_agent(settings.home, "vitrine", LEFTOVER, "Você é a Vitrine.")
    write_agent(settings.home, "aurora", MIGRATED, "Você é a coach.")
    store = AgentStore(settings.home)
    created = store.save({"name": "Platão", "cli": "codex", "prompt": "Professor.", "tipo": "estudo"})

    # A lista é só da MÊTIS: o criado nela e o migrado; o importado e não migrado fica de fora.
    assert [a["id"] for a in store.list()] == ["aurora", created.id]
    with pytest.raises(AgentError, match="Maestri"):
        store.get("vitrine")

    # O migrado funciona como os outros: papel, tipo e de onde veio.
    aurora = store.get("aurora")
    assert aurora.origin == "" and aurora.migrated == "maestri:BBB-222" and aurora.tipo == "estudo"
    assert agent_args(aurora)[-2:] == ["--append-system-prompt", "Você é a coach."]
    # Editar (o pedido não traz origem nem migração) não perde o registro de onde ele veio.
    edited = store.save({"name": "Aurora", "cli": "claude", "prompt": "Outro papel."}, "aurora")
    assert edited.migrated == "maestri:BBB-222" and edited.origin == "" and edited.prompt == "Outro papel."
    meta = parse_agent((store.dir / "aurora.md").read_text(encoding="utf-8"))[0]
    assert meta["migrado"] == "maestri:BBB-222" and meta["origem"] == ""

    # A MÊTIS não importa mais: nem o pedido consegue gravar uma origem do Maestri num agente novo.
    sneaky = store.save({"name": "Babel", "cli": "claude", "origin": "maestri:CCC-333"})
    assert sneaky.origin == "" and sneaky.id in {a["id"] for a in store.list()}
    assert not hasattr(store, "import_maestri")

    # O arquivo do importado não é apagado nem mexido; um agente novo com o mesmo nome ganha outro id.
    before = leftover.read_text(encoding="utf-8")
    assert store.save({"name": "Vitrine", "cli": "claude"}).id == "vitrine-2"
    assert leftover.read_text(encoding="utf-8") == before


def test_agent_created_in_metis_keeps_working_as_before(settings):
    store = AgentStore(settings.home)
    agent = store.save({"name": "Revisor", "cli": "claude", "prompt": "Revise."})
    assert agent.origin == "" and agent.migrated == ""
    assert store.get(agent.id).prompt == "Revise." and [a["id"] for a in store.list()] == [agent.id]


# --- rotas: lista, sessões, Estudo, catálogo e coluna Auto -----------------------------------


def test_routes_list_and_open_only_metis_agents(core, settings):
    api, app = core
    leftover = write_agent(settings.home, "vitrine", LEFTOVER, "Você é a Vitrine.")
    write_agent(settings.home, "aurora", MIGRATED, "Você é a coach.")
    own = api.post("/agents", json={"name": "Revisor", "cli": "claude", "prompt": "Revise."}, headers=AUTH).json()

    listed = {a["id"]: a for a in api.get("/agents", headers=AUTH).json()}
    assert set(listed) == {"aurora", own["id"]}
    assert listed["aurora"]["migrated"] == "maestri:BBB-222" and listed["aurora"]["origin"] == ""
    catalog = api.get("/automacoes/catalogo", headers=AUTH).json()["agentes"]
    assert {a["id"] for a in catalog} == {"aurora", own["id"]}

    # O importado e não migrado não abre por nenhum caminho, nem pelo id.
    refused = api.put("/agents/vitrine", json={"name": "Vitrine", "cli": "claude"}, headers=AUTH)
    assert refused.status_code == 404 and "Maestri" in refused.json()["detail"]
    assert api.post("/sessions", json={"kind": "claude", "agent": "vitrine"}, headers=AUTH).status_code == 404
    assert api.post("/estudo/sessao", json={"tipo": "conversa", "agente": "vitrine"}, headers=AUTH).status_code == 404
    assert api.put("/estudo/agente", json={"id": "vitrine"}, headers=AUTH).status_code == 404
    assert api.get("/agents/vitrine/sprite", params={"token": TOKEN}).status_code == 404
    # A importação do Maestri saiu.
    assert api.post("/agents/import/maestri", headers=AUTH).status_code in (404, 405)
    assert leftover.exists()  # nada do Maestri é apagado

    # O migrado e o criado na MÊTIS abrem como sempre, com o papel deles.
    for agent_id, role in (("aurora", "Você é a coach."), (own["id"], "Revise.")):
        opened = api.post("/sessions", json={"kind": "claude", "agent": agent_id}, headers=AUTH)
        assert opened.status_code == 201, opened.text
        argv = app.state.manager.get(opened.json()["id"]).pty.argv
        assert argv[argv.index("--append-system-prompt") + 1] == role
    # A migrada de estudo conversa no Estudo e pode ser a conectada.
    assert api.post("/estudo/sessao", json={"tipo": "conversa", "agente": "aurora"}, headers=AUTH).status_code == 201
    assert api.put("/estudo/agente", json={"id": "aurora"}, headers=AUTH).status_code == 200


def test_auto_column_refuses_agent_not_migrated_from_maestri(client, settings):  # noqa: F811
    write_agent(settings.home, "vitrine", LEFTOVER, "Você é a Vitrine.")
    write_agent(settings.home, "aurora", MIGRATED, "Você é a coach.")
    task = client.post("/brain/projects/Alfa/tasks", json={"text": "Rodar sozinha"}, headers=AUTH).json()
    refused = client.post("/kanban/auto", json={"projeto": "Alfa", "tarefa": task["id"], "agente": "vitrine"}, headers=AUTH)
    assert refused.status_code == 400 and "não existe" in refused.json()["detail"]
    assert client.get("/kanban/auto", headers=AUTH).json()["itens"] == []


# --- skills do Maestri nas sessões -----------------------------------------------------------


def test_claude_sessions_deny_every_maestri_skill(tmp_path, monkeypatch):
    home = tmp_path / "casa"
    skills = home / ".claude" / "skills"
    skill(skills, "maestri-novo")  # uma que o Maestri ponha depois
    skill(skills, "maestria")  # nome parecido, mas não é dele
    skill(skills, "brain-registrar")
    monkeypatch.setenv("HOME", str(home))

    assert "permissions" not in build_claude_settings(RELAY)  # sem bloqueio pedido, nada muda
    deny = json.loads(claude_argv("/usr/local/bin/claude", RELAY)[2])["permissions"]["deny"]
    assert {f"Skill({name})" for name in maestri.SKILLS} <= set(deny)
    assert "Skill(maestri-novo)" in deny and "Skill(maestria)" not in deny and "Skill(brain-registrar)" not in deny
    # Os hooks e a statusline continuam lá.
    settings = json.loads(claude_argv("/usr/local/bin/claude", RELAY, blocked_skills=())[2])
    assert settings == build_claude_settings(RELAY)


def test_codex_args_disable_maestri_skills_and_keep_the_users_entries(tmp_path):
    agents_skills = tmp_path / ".agents" / "skills"
    codex_home = tmp_path / ".codex"
    ours = [skill(agents_skills, "maestri"), skill(codex_home / "skills", "maestri-chat")]
    skill(agents_skills, "graphify")
    config = codex_home / "config.toml"
    config.write_text(
        f'model = "gpt"\n\n[[skills.config]]\npath = "/x/minha/SKILL.md"\nenabled = false\n\n[[skills.config]]\npath = "{ours[0]}"\nenabled = true\n',
        encoding="utf-8",
    )
    args = maestri.codex_args([agents_skills, codex_home / "skills"], config)
    assert args[0] == "-c" and args[1].startswith("skills.config=")
    entries = tomllib.loads(args[1])["skills"]["config"]
    # A do Pedro vem junto; a do Maestri que estava ligada no config.toml passa a desligada, uma vez só.
    assert entries[0] == {"path": "/x/minha/SKILL.md", "enabled": False}
    assert {e["path"]: e["enabled"] for e in entries[1:]} == {str(p): False for p in ours}
    assert len(entries) == 3
    # Sem skill do Maestri instalada, nada vai para a linha de comando.
    assert maestri.codex_args([tmp_path / "vazio"], config) == []


def test_codex_session_gets_the_maestri_skills_off(core, tmp_path, monkeypatch):
    api, app = core
    home = tmp_path / "casa"
    path = skill(home / ".agents" / "skills", "maestri-manager")
    monkeypatch.setenv("HOME", str(home))
    opened = api.post("/sessions", json={"kind": "codex"}, headers=AUTH)
    assert opened.status_code == 201, opened.text
    argv = app.state.manager.get(opened.json()["id"]).pty.argv
    value = next(a for a in argv if a.startswith("skills.config="))
    assert tomllib.loads(value)["skills"]["config"] == [{"path": str(path), "enabled": False}]


def test_slash_bar_does_not_suggest_maestri_skills(tmp_path):
    home = tmp_path / ".claude"
    for name in ("maestri", "maestri-portal", "brain-registrar"):
        skill(home / "skills", name)
    names = {item["nome"] for item in barra.slash_commands("claude", home, str(tmp_path))}
    assert "/brain-registrar" in names and not any(name.startswith("/maestri") for name in names)
