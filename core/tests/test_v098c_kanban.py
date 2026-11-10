"""v0.9.8 parte 3 (kanban e agentes): rótulos e subtarefas nas Próximas ações, o ClickUp no
kanban pela API REST, a atenção das sessões no painel de agentes e os eventos da Atividade."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.activity import ActivityLog
from harness_core.app import create_app
from harness_core.kanban import Kanban, labels_of, normalize_labels, parse_tasks, strip_labels
from harness_core.keychain import MemoryVault
from harness_core.vault import Vault

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
API = "https://api.clickup.com/api/v2"

NOTE = """---
tipo: projeto
---

# Alfa

Texto antes.

## ✅ Próximas ações

- [ ] Corrigir bug #123 #urgente
  - [x] reproduzir ✅ 2026-11-01
  - [ ] corrigir
- [ ] Revisar o PR #em-andamento
- [x] Feita #front ✅ 2026-11-02

## Depois

Fim da nota.
"""


def write_project(brain: Path, text: str = NOTE) -> Path:
    root = brain / "01-PROJETOS" / "Alfa"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "Alfa.md"
    path.write_text(text, encoding="utf-8")
    return path


FAKE_CLI: list[str] = []


def fake_argv(kind, settings):
    # Um "CLI" que ignora os argumentos e fica vivo (o cat com opção desconhecida sairia na hora).
    return list(FAKE_CLI)


# --- rótulos e subtarefas ------------------------------------------------------------------------


def test_labels_are_tags_with_a_letter_and_state_tags_are_not_labels():
    assert labels_of("Corrigir bug #123 #urgente #front-end #em-teste #a/b") == ["urgente", "front-end", "a/b"]
    assert strip_labels("Corrigir bug #123 #urgente #front") == "Corrigir bug #123"
    assert normalize_labels(["Urgente", "#Front End", "123", "em-andamento", "urgente", "a*b"]) == ["urgente", "front-end", "ab"]


def test_parse_keeps_the_old_fields_and_adds_labels_and_subtasks():
    tasks = parse_tasks(NOTE)
    first = tasks[0].to_dict()
    assert first["text"] == "Corrigir bug #123 #urgente"  # igual a antes: a tela antiga não quebra
    assert first["texto"] == "Corrigir bug #123" and first["rotulos"] == ["urgente"]
    assert first["subtarefas"] == [{"indice": 0, "texto": "reproduzir", "feita": True}, {"indice": 1, "texto": "corrigir", "feita": False}]
    assert (first["subtasks_done"], first["subtasks_total"]) == (1, 2)
    assert "sub_lines" not in first
    assert tasks[1].rotulos == [] and tasks[1].state == "em-andamento"
    assert tasks[2].rotulos == ["front"] and tasks[2].state == "concluida"


def test_set_labels_rewrites_only_that_line_and_keeps_the_state(settings):
    path = write_project(settings.brain)
    kanban = Kanban(Vault(settings.brain))
    before = path.read_text(encoding="utf-8").splitlines()
    revisar = next(t for t in kanban.tasks("Alfa") if t["texto"] == "Revisar o PR")
    task = kanban.set_labels("Alfa", revisar["id"], ["Back End", "#urgente"])
    assert task["rotulos"] == ["back-end", "urgente"] and task["state"] == "em-andamento"
    after = path.read_text(encoding="utf-8").splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(before) == len(after) and len(changed) == 1
    assert after[changed[0]] == "- [ ] Revisar o PR #back-end #urgente #em-andamento"
    # v1.0: o id é o hash do texto sem os rótulos, então trocar os rótulos não o muda.
    assert task["id"] == revisar["id"]
    assert kanban.move("Alfa", task["id"], "em-teste")["rotulos"] == ["back-end", "urgente"]
    cleared = kanban.set_labels("Alfa", kanban.tasks("Alfa")[1]["id"], [])
    assert cleared["rotulos"] == [] and cleared["state"] == "em-teste"


def test_subtasks_are_added_after_the_last_one_and_marked_with_the_date(settings):
    path = write_project(settings.brain)
    kanban = Kanban(Vault(settings.brain))
    first = kanban.tasks("Alfa")[0]
    task = kanban.add_subtask("Alfa", first["id"], "  escrever o teste ")
    assert [s["texto"] for s in task["subtarefas"]] == ["reproduzir", "corrigir", "escrever o teste"]
    assert task["id"] == first["id"]  # subtarefa não muda o id da tarefa
    text = path.read_text(encoding="utf-8")
    assert "  - [ ] corrigir\n  - [ ] escrever o teste\n- [ ] Revisar o PR" in text
    marked = kanban.mark_subtask("Alfa", first["id"], 2, True)
    assert marked["subtarefas"][2]["feita"] and marked["subtasks_done"] == 2
    assert "  - [x] escrever o teste ✅ " in path.read_text(encoding="utf-8")
    unmarked = kanban.mark_subtask("Alfa", first["id"], 0, False)
    assert not unmarked["subtarefas"][0]["feita"] and "  - [ ] reproduzir\n" in path.read_text(encoding="utf-8")
    with pytest.raises(Exception, match="não existe"):
        kanban.mark_subtask("Alfa", first["id"], 9, True)
    # Tarefa sem subtarefa: a primeira entra logo abaixo, com 2 espaços.
    revisar = kanban.tasks("Alfa")[1]
    kanban.add_subtask("Alfa", revisar["id"], "olhar os testes")
    assert "- [ ] Revisar o PR #em-andamento\n  - [ ] olhar os testes\n" in path.read_text(encoding="utf-8")
    assert path.read_text(encoding="utf-8").endswith("## Depois\n\nFim da nota.\n")


def test_add_with_labels_and_subtasks_and_the_project_labels(settings):
    write_project(settings.brain)
    kanban = Kanban(Vault(settings.brain))
    task = kanban.add("Alfa", "Nova tela", labels=["Front", "urgente"], subtasks=["desenhar", "  ", "codar"])
    assert task["rotulos"] == ["front", "urgente"] and [s["texto"] for s in task["subtarefas"]] == ["desenhar", "codar"]
    assert kanban.labels("Alfa") == [{"nome": "front", "quantas": 2}, {"nome": "urgente", "quantas": 2}]


@pytest.fixture
def core(settings, accounts, monkeypatch, tmp_path):
    script = tmp_path / "cli-falso"
    script.write_text("#!/bin/sh\nexec cat >/dev/null\n", encoding="utf-8")
    script.chmod(0o755)
    FAKE_CLI[:] = [str(script)]
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    vault = MemoryVault()
    clickup = FakeClickup()
    http = lambda: httpx.Client(transport=httpx.MockTransport(clickup.handler))  # noqa: E731
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False, keychain=vault, http=http)
    app.state.cli_homes = {"claude": tmp_path / "homes" / "claude", "codex": tmp_path / "homes" / "codex"}
    with TestClient(app) as client:
        yield client, app, vault, clickup
        for session_id in list(app.state.manager.sessions):
            client.delete(f"/sessions/{session_id}", headers=AUTH)


def test_label_and_subtask_routes(core, settings):
    client, *_ = core
    write_project(settings.brain)
    base = "/brain/projects/Alfa"
    first = client.get(f"{base}/tasks", headers=AUTH).json()[0]
    labeled = client.put(f"{base}/tasks/{first['id']}/rotulos", json={"rotulos": ["urgente", "Back End"]}, headers=AUTH)
    assert labeled.status_code == 200 and labeled.json()["rotulos"] == ["urgente", "back-end"]
    task_id = labeled.json()["id"]
    added = client.post(f"{base}/tasks/{task_id}/subtarefas", json={"texto": "deploy"}, headers=AUTH)
    assert added.status_code == 201 and added.json()["subtasks_total"] == 3
    marked = client.put(f"{base}/tasks/{task_id}/subtarefas/2", json={"feita": True}, headers=AUTH)
    assert marked.json()["subtarefas"][2] == {"indice": 2, "texto": "deploy", "feita": True}
    assert client.put(f"{base}/tasks/{task_id}/subtarefas/7", json={"feita": True}, headers=AUTH).status_code == 400
    assert client.put(f"{base}/tasks/zzz/rotulos", json={"rotulos": []}, headers=AUTH).status_code == 404
    created = client.post(f"{base}/tasks", json={"text": "Com tudo", "rotulos": ["novo"], "subtarefas": ["a", "b"]}, headers=AUTH)
    assert created.status_code == 201 and created.json()["rotulos"] == ["novo"] and created.json()["subtasks_total"] == 2
    labels = client.get(f"{base}/rotulos", headers=AUTH).json()["rotulos"]
    assert {"nome": "urgente", "quantas": 1} in labels and {"nome": "novo", "quantas": 1} in labels


def test_kanban_tools_of_the_central(core, settings):
    client, app, *_ = core
    write_project(settings.brain)
    hub = app.state.hub
    from harness_core.mcp_hub import Context

    ctx = Context(session="s1", who="teste", cwd=None, allowed=None)
    tools = {t.name: t for t in hub.tools_for(ctx)}
    assert {"tarefa_rotulos", "tarefa_subtarefa"} <= set(tools)
    made = tools["tarefa_nova"].run({"texto": "Deploy", "projeto": "Alfa", "rotulos": ["infra"], "subtarefas": ["build", "subir"]}, ctx)
    assert "rótulos: infra" in made and "2 subtarefa(s)" in made
    listed = tools["tarefas"].run({"projeto": "Alfa"}, ctx)
    assert "Deploy (#infra)" in listed and "    0. [ ] build" in listed and "Corrigir bug #123 (#urgente)" in listed
    task_id = next(t["id"] for t in app.state.hub.kanban.tasks("Alfa") if t["texto"] == "Deploy")
    relabeled = tools["tarefa_rotulos"].run({"id": task_id, "rotulos": ["infra", "noite"], "projeto": "Alfa"}, ctx)
    new_id = relabeled.rsplit(" ", 1)[1].rstrip(".")
    assert "infra, noite" in relabeled
    assert "1/2 feitas" in tools["tarefa_subtarefa"].run({"id": new_id, "indice": 0, "projeto": "Alfa"}, ctx)
    assert "1/3 feitas" in tools["tarefa_subtarefa"].run({"id": new_id, "texto": "avisar", "projeto": "Alfa"}, ctx)
    with pytest.raises(Exception, match="texto"):
        tools["tarefa_subtarefa"].run({"id": new_id, "projeto": "Alfa"}, ctx)


# --- ClickUp no kanban ----------------------------------------------------------------------


class FakeClickup:
    def __init__(self) -> None:
        self.good = {"pk_bom_de_verdade", "tok-login"}
        self.calls: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if not url.startswith(API):
            return httpx.Response(404)
        path = request.url.path.removeprefix("/api/v2")
        self.calls.append((request.method, path))
        if request.headers.get("authorization") not in self.good:
            return httpx.Response(401, json={"err": "Token invalid"})
        if path == "/user":
            return httpx.Response(200, json={"user": {"id": 1, "username": "Pedro"}})
        if path == "/team":
            return httpx.Response(200, json={"teams": [{"id": "T1", "name": "Seller Pro"}]})
        if path == "/team/T1/space":
            return httpx.Response(200, json={"spaces": [{"id": "S1", "name": "Marketing"}]})
        if path == "/space/S1/folder":
            return httpx.Response(200, json={"folders": [{"id": "F1", "name": "Lançamentos", "lists": [{"id": "L1", "name": "Campanhas"}]}]})
        if path == "/space/S1/list":
            return httpx.Response(200, json={"lists": [{"id": "L2", "name": "Avulsas"}]})
        if path == "/list/L1/task":
            tasks = [
                {"id": "a1", "name": "Velha", "status": {"status": "to do", "color": "#ccc"}, "url": "https://app.clickup.com/t/a1", "assignees": [], "due_date": None, "priority": None, "date_created": "1700000000000"},
                {"id": "a2", "name": "Nova", "status": {"status": "in progress", "color": "#5f55ee"}, "url": "https://app.clickup.com/t/a2", "assignees": [{"username": "Pedro"}], "due_date": "1800000000000", "priority": {"priority": "urgent"}, "date_created": "1790000000000"},
            ]
            return httpx.Response(200, json={"tasks": tasks})
        if path == "/list/L1":
            return httpx.Response(200, json={"statuses": [{"status": "in progress", "color": "#5f55ee", "type": "custom", "orderindex": 1}, {"status": "to do", "color": "#ccc", "type": "open", "orderindex": 0}]})
        if path == "/task/a2" and request.method == "PUT":
            body = json.loads(request.content)
            return httpx.Response(200, json={"id": "a2", "name": "Nova", "status": {"status": body["status"], "color": "#000"}, "url": "u", "assignees": [], "date_created": "1"})
        return httpx.Response(404, json={"err": "não achei"})


def add_clickup_account(settings, vault, account_id: str = "clickup-sp", token: str = "tok-login") -> None:
    settings.home.mkdir(parents=True, exist_ok=True)
    (settings.home / "conectores.json").write_text(
        json.dumps([{"id": account_id, "kind": "clickup", "name": "ClickUp SP", "created": 0, "meta": {}}]), encoding="utf-8"
    )
    vault.set(f"conector:{account_id}", json.dumps({"access_token": token}))


def test_clickup_lists_tasks_status_and_link(core, settings):
    client, _app, vault, fake = core
    add_clickup_account(settings, vault)
    listed = client.get("/clickup/clickup-sp/listas", headers=AUTH).json()["listas"]
    assert listed == [
        {"id": "L1", "nome": "Campanhas", "workspace": "Seller Pro", "espaco": "Marketing", "pasta": "Lançamentos"},
        {"id": "L2", "nome": "Avulsas", "workspace": "Seller Pro", "espaco": "Marketing", "pasta": ""},
    ]
    count = len(fake.calls)
    client.get("/clickup/clickup-sp/listas", headers=AUTH)
    assert len(fake.calls) == count  # cache de 5 minutos
    assert client.get("/kanban/Alfa/clickup", headers=AUTH).json() == {"ligacao": None, "tarefas": [], "status": []}
    link = client.put("/kanban/Alfa/clickup", json={"conta": "clickup-sp", "lista": "L1", "nome": "Campanhas"}, headers=AUTH)
    assert link.json() == {"conta": "clickup-sp", "lista": "L1", "nome": "Campanhas"}
    board = client.get("/kanban/Alfa/clickup", headers=AUTH).json()
    assert [t["nome"] for t in board["tarefas"]] == ["Nova", "Velha"]  # mais recentes primeiro
    assert board["tarefas"][0] == {
        "id": "a2", "nome": "Nova", "status": "in progress", "cor": "#5f55ee", "url": "https://app.clickup.com/t/a2",
        "responsaveis": ["Pedro"], "prazo": 1800000000.0, "prioridade": "urgent",
    }
    assert [s["nome"] for s in board["status"]] == ["to do", "in progress"]
    moved = client.patch("/clickup/clickup-sp/tarefas/a2", json={"status": "done"}, headers=AUTH)
    assert moved.json()["status"] == "done" and ("PUT", "/task/a2") in fake.calls
    assert json.loads((settings.home / "kanban.json").read_text())["projetos"]["Alfa"]["clickup"]["lista"] == "L1"
    assert client.delete("/kanban/Alfa/clickup", headers=AUTH).status_code == 204
    assert client.get("/kanban/Alfa/clickup", headers=AUTH).json()["ligacao"] is None
    assert client.get("/clickup/nada/listas", headers=AUTH).status_code == 404
    assert client.put("/kanban/Alfa/clickup", json={"conta": "nada", "lista": "L1"}, headers=AUTH).status_code == 404


def test_clickup_refused_login_asks_for_a_personal_token(core, settings):
    client, _app, vault, fake = core
    add_clickup_account(settings, vault, token="tok-que-o-rest-recusa")
    refused = client.get("/clickup/clickup-sp/listas", headers=AUTH)
    assert refused.status_code == 409 and "token pessoal (pk_" in refused.json()["detail"]
    assert client.get("/clickup/clickup-sp/token-api", headers=AUTH).json() == {"tem": False}
    assert client.put("/clickup/clickup-sp/token-api", json={"token": "pk_que_nao_vale"}, headers=AUTH).status_code == 400
    assert vault.get("conector:clickup-sp:api") is None
    assert client.put("/clickup/clickup-sp/token-api", json={"token": "pk_bom_de_verdade"}, headers=AUTH).status_code == 204
    assert client.get("/clickup/clickup-sp/token-api", headers=AUTH).json() == {"tem": True}
    assert len(client.get("/clickup/clickup-sp/listas", headers=AUTH).json()["listas"]) == 2
    assert client.delete("/clickup/clickup-sp/token-api", headers=AUTH).status_code == 204
    assert vault.get("conector:clickup-sp:api") is None


# --- painel de agentes e eventos da Atividade -----------------------------------------------------


def hook(client, session_id: str, name: str, payload: dict | None = None) -> None:
    response = client.post(f"/hooks/event?session={session_id}&name={name}", json=payload or {}, headers=AUTH)
    assert response.status_code == 204


def column(client, session_id: str) -> dict:
    return next(a for a in client.get("/agentes/painel", headers=AUTH).json()["agentes"] if a["id"] == session_id)


def test_attention_moves_the_agent_between_columns(core, tmp_path, statusline_payload):
    client, app, *_ = core
    session_id = client.post("/sessions", json={"kind": "claude"}, headers=AUTH).json()["id"]
    shell_id = client.post("/sessions", json={"kind": "shell"}, headers=AUTH).json()["id"]
    agents = client.get("/agentes/painel", headers=AUTH).json()["agentes"]
    assert [a["id"] for a in agents] == [session_id]  # só Claude e Codex
    assert column(client, session_id)["coluna"] == "parado"
    session = app.state.manager.get(session_id)
    assert session.to_dict()["atencao"] is None and session.to_dict()["status_desde"] > 0

    transcript = tmp_path / "conversa.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "faça o teste"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Pronto: os 12 testes passam."}]}}) + "\n",
        encoding="utf-8",
    )
    client.post(f"/hooks/statusline?session={session_id}", json={**statusline_payload, "transcript_path": str(transcript)}, headers=AUTH)

    hook(client, session_id, "UserPromptSubmit")
    assert column(client, session_id)["coluna"] == "trabalhando"
    hook(client, session_id, "Stop", {"transcript_path": str(transcript)})
    done = column(client, session_id)
    assert done["coluna"] == "feito" and done["previa"] == "Pronto: os 12 testes passam."
    assert done["custo_usd"] == 0.42 and done["cli"] == "claude" and done["duracao_s"] >= 0
    hook(client, session_id, "Notification", {"message": "Claude is waiting for your input"})
    assert column(client, session_id)["coluna"] == "feito"  # o aviso de inatividade não é pergunta
    hook(client, session_id, "Notification", {"message": "Claude needs your permission to use Bash"})
    assert column(client, session_id)["coluna"] == "precisa"
    assert app.state.manager.get(session_id).atencao == "pergunta"
    hook(client, session_id, "UserPromptSubmit")
    assert column(client, session_id)["coluna"] == "trabalhando" and app.state.manager.get(session_id).atencao is None
    session.hibernando = True
    assert column(client, session_id)["coluna"] == "parado"
    session.hibernando = False
    assert shell_id


def test_events_of_the_agents_are_recorded_and_published(core, settings):
    client, app, *_ = core
    manager = app.state.manager
    queue = manager.events.subscribe()
    session_id = client.post("/sessions", json={"kind": "codex"}, headers=AUTH).json()["id"]
    hook(client, session_id, "Stop", {"type": "agent-turn-complete", "last-assistant-message": "Terminei   a migração."})
    hook(client, session_id, "Notification", {"message": "Aprovar o comando rm?"})
    hook(client, session_id, "Notification", {"message": "Claude is waiting for your input"})
    hook(client, session_id, "UserPromptSubmit")
    events = client.get(f"/atividade/eventos?sessao={session_id}", headers=AUTH).json()["eventos"]
    assert [e["kind"] for e in events] == ["pergunta", "terminou", "inicio"]  # mais novos primeiro
    assert events[1]["preview"] == "Terminei a migração." and events[1]["title"] == "terminou o turno"
    assert events[0]["preview"] == "Aprovar o comando rm?" and events[0]["who"] == manager.get(session_id).title
    published = []
    while not queue.empty():
        item = queue.get_nowait()
        if item.get("type") == "activity.event":
            published.append(item["item"]["kind"])
    assert published[-2:] == ["terminou", "pergunta"]
    client.delete(f"/sessions/{session_id}", headers=AUTH)
    shell = client.post("/sessions", json={"kind": "shell"}, headers=AUTH).json()["id"]
    hook(client, shell, "Stop")
    assert client.get(f"/atividade/eventos?sessao={shell}", headers=AUTH).json()["eventos"] == []
    assert client.get("/atividade/eventos?limite=0", headers=AUTH).status_code == 422


def test_exit_and_hibernation_become_events(core):
    client, app, *_ = core
    manager = app.state.manager
    session_id = client.post("/sessions", json={"kind": "claude"}, headers=AUTH).json()["id"]
    session = manager.get(session_id)
    session.exit_code = 3
    manager._set_status(session, "exited")
    session.hibernando = True
    manager._woke(session_id)
    kinds = [(e["kind"], e["title"]) for e in client.get(f"/atividade/eventos?sessao={session_id}", headers=AUTH).json()["eventos"]]
    assert kinds[:2] == [("acordou", "acordou"), ("saiu", "saiu com o código 3")]
    assert column(client, session_id)["coluna"] == "parado"


def test_event_log_keeps_the_newest(tmp_path, monkeypatch):
    from harness_core import activity as activity_mod

    monkeypatch.setattr(activity_mod, "KEEP_EVENTS", 3)
    log = ActivityLog(tmp_path / "a.db")
    for n in range(5):
        log.event("s", "Agente", "terminou", "terminou o turno", f"msg {n}")
    assert [e["preview"] for e in log.events()] == ["msg 4", "msg 3", "msg 2"]
    with pytest.raises(ValueError):
        log.event("s", "Agente", "dançou", "x")
