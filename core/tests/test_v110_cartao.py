"""v1.1: o cartão aberto do kanban, no jeito do ClickUp.

Título, prioridade e datas na linha da tarefa (campos do plugin Tasks, fora do id), descrição
nas linhas recuadas logo abaixo, checklist editável, e a atividade, os comentários e os anexos
de cada tarefa no tarefas.db do núcleo, que seguem a tarefa quando o título (e o id) muda."""

from __future__ import annotations

import hashlib

from harness_core.kanban import Kanban, parse_tasks, split_fields, task_brief
from harness_core.kanban_auto import AutoItem, AutoQueue, auto_prompt
from harness_core.task_log import TaskLog
from harness_core.vault import Vault

from .test_v098c_kanban import AUTH, core, write_project  # noqa: F401

NOTE = """---
tipo: projeto
---

# Alfa

## ✅ Próximas ações

- [ ] Preparar logins de Trial #melhorias 🔺 🛫 2026-11-04 📅 2026-11-06 #em-andamento
  Contas de teste para o time comercial.

  Usar o domínio de homologação.
  - [x] criar a planilha ✅ 2026-11-05
  - [ ] mandar no Slack
- [ ] Revisar o PR
- [x] Feita ✅ 2026-11-02

## Depois

Fim.
"""


def digest(text: str) -> str:
    return hashlib.sha1(text.lower().encode("utf-8")).hexdigest()[:8]


def make(settings, text: str = NOTE) -> tuple[Kanban, TaskLog]:
    write_project(settings.brain, text)
    kanban = Kanban(Vault(settings.brain))
    kanban.log = TaskLog(settings.home / "tarefas.db")
    return kanban, kanban.log


def note(settings) -> str:
    return (settings.brain / "01-PROJETOS" / "Alfa" / "Alfa.md").read_text(encoding="utf-8")


# --- leitura ----------------------------------------------------------------------------------


def test_fields_of_the_tasks_plugin_stay_out_of_the_title_and_the_id():
    rest, fields = split_fields("Preparar logins #melhorias ⏫ 🛫 2026-11-04 📅\ufe0f 2026-11-06 ➕ 2026-11-01")
    assert rest == "Preparar logins #melhorias"
    assert fields == {"prioridade": "alta", "inicio": "2026-11-04", "entrega": "2026-11-06", "criada": "2026-11-01"}
    first = parse_tasks(NOTE)[0].to_dict()
    assert first["id"] == digest("Preparar logins de Trial")  # o mesmo id de antes dos campos
    assert first["text"] == "Preparar logins de Trial #melhorias" and first["texto"] == "Preparar logins de Trial"
    assert (first["prioridade"], first["inicio"], first["entrega"], first["state"]) == ("urgente", "2026-11-04", "2026-11-06", "em-andamento")
    for internal in ("desc_lines", "fields", "end_line", "sub_lines", "old_id"):
        assert internal not in first


def test_indented_lines_before_the_first_subtask_are_the_description():
    tasks = parse_tasks(NOTE)
    assert tasks[0].descricao == "Contas de teste para o time comercial.\n\nUsar o domínio de homologação."
    assert tasks[0].subtasks_total == 2 and tasks[0].subtarefas[1]["texto"] == "mandar no Slack"
    assert tasks[1].descricao == "" and tasks[1].subtasks_total == 0
    # Texto solto sem recuo fecha a tarefa: o recuado depois dele não vira descrição de ninguém.
    loose = "## Próximas ações\n\n- [ ] Uma\nRetomar aqui\n  recuado solto\n- [ ] Duas\n"
    assert [t.descricao for t in parse_tasks(loose)] == ["", ""]


# --- edição -----------------------------------------------------------------------------------


def test_update_rewrites_the_line_and_keeps_mark_state_tag_and_done_date(settings):
    kanban, log = make(settings)
    first = kanban.tasks("Alfa")[0]
    edited = kanban.update("Alfa", first["id"], prioridade="baixa", entrega="2026-11-20", inicio="")
    assert edited["id"] == first["id"] == edited["id_antes"]
    assert "- [ ] Preparar logins de Trial #melhorias 🔽 📅 2026-11-20 #em-andamento" in note(settings).splitlines()
    done = kanban.tasks("Alfa")[2]
    kanban.update("Alfa", done["id"], prioridade="urgente")
    assert "- [x] Feita 🔺 ✅ 2026-11-02" in note(settings).splitlines()  # a data de conclusão continua no fim
    kinds = [(e["tipo"], e["dados"]) for e in log.events("Alfa", first["id"])]
    assert ("prioridade", {"de": "urgente", "para": "baixa"}) in kinds
    assert ("data", {"campo": "entrega", "de": "2026-11-06", "para": "2026-11-20"}) in kinds
    assert ("data", {"campo": "inicio", "de": "2026-11-04", "para": ""}) in kinds


def test_new_title_changes_the_id_and_the_activity_and_the_auto_queue_follow(settings, tmp_path):
    kanban, log = make(settings)
    first = kanban.tasks("Alfa")[0]
    log.comment("Alfa", first["id"], "Pedro", "olhar o domínio")
    queue = AutoQueue(tmp_path / "auto.json", start=None, move=None, publish=lambda e: None)  # type: ignore[arg-type]
    queue.enqueue("Alfa", first["id"], first["texto"])
    kanban.on_rename = queue.rename_task
    edited = kanban.update("Alfa", first["id"], titulo="Preparar logins de Trial e Demo #comercial")
    assert edited["id"] == digest("Preparar logins de Trial e Demo") and edited["id_antes"] == first["id"]
    assert edited["rotulos"] == ["melhorias", "comercial"]  # o #rótulo escrito no título vira rótulo
    assert edited["prioridade"] == "urgente" and edited["descricao"].startswith("Contas de teste")
    assert [e["tipo"] for e in log.events("Alfa", edited["id"])] == ["comentario", "titulo", "rotulos"]
    assert log.events("Alfa", first["id"]) == []
    assert queue.items[0].tarefa == edited["id"]


def test_empty_title_is_refused(settings):
    kanban, _ = make(settings)
    first = kanban.tasks("Alfa")[0]
    try:
        kanban.update("Alfa", first["id"], titulo="   #so-rotulo ")
    except Exception as exc:  # noqa: BLE001
        assert "vazio" in str(exc)
    else:
        raise AssertionError("aceitou título vazio")


def test_description_is_written_indented_before_the_subtasks_and_can_be_cleared(settings):
    kanban, _ = make(settings)
    first, second = kanban.tasks("Alfa")[:2]
    kanban.update("Alfa", second["id"], descricao="Ver os testes.\n\n- olhar o CI")
    lines = note(settings).splitlines()
    at = lines.index("- [ ] Revisar o PR")
    assert lines[at + 1 : at + 4] == ["  Ver os testes.", "", "  - olhar o CI"]
    assert kanban.tasks("Alfa")[1]["descricao"] == "Ver os testes.\n\n- olhar o CI"
    kanban.update("Alfa", first["id"], descricao="Só uma linha.")
    lines = note(settings).splitlines()
    at = lines.index("- [ ] Preparar logins de Trial #melhorias 🔺 🛫 2026-11-04 📅 2026-11-06 #em-andamento")
    assert lines[at + 1 : at + 3] == ["  Só uma linha.", "  - [x] criar a planilha ✅ 2026-11-05"]
    kanban.update("Alfa", first["id"], descricao="")
    assert kanban.tasks("Alfa")[0]["descricao"] == "" and kanban.tasks("Alfa")[0]["subtasks_total"] == 2


def test_new_task_and_new_subtask_land_after_the_description(settings):
    kanban, _ = make(settings, NOTE.replace("- [ ] Revisar o PR\n", "- [ ] Revisar o PR\n  descrição do PR\n"))
    kanban.add("Alfa", "Nova tarefa")
    lines = note(settings).splitlines()
    assert lines[lines.index("- [ ] Revisar o PR") + 1 : lines.index("- [ ] Revisar o PR") + 3] == ["  descrição do PR", "- [ ] Nova tarefa"]
    second = kanban.tasks("Alfa")[1]
    task = kanban.add_subtask("Alfa", second["id"], "rodar o lint")
    assert task["descricao"] == "descrição do PR" and task["subtarefas"] == [{"indice": 0, "texto": "rodar o lint", "feita": False}]


def test_checklist_items_can_be_renamed_and_removed(settings):
    kanban, log = make(settings)
    first = kanban.tasks("Alfa")[0]
    kanban.edit_subtask("Alfa", first["id"], 0, "criar a planilha de contas")
    assert "  - [x] criar a planilha de contas ✅ 2026-11-05" in note(settings).splitlines()
    task = kanban.remove_subtask("Alfa", first["id"], 1)
    assert [s["texto"] for s in task["subtarefas"]] == ["criar a planilha de contas"]
    assert "mandar no Slack" not in note(settings)
    actions = [e["dados"]["acao"] for e in log.events("Alfa", first["id"]) if e["tipo"] == "subtarefa"]
    assert actions == ["editou", "apagou"]


def test_brief_for_the_agent_has_description_checklist_dates_and_attachments(settings):
    kanban, _ = make(settings)
    first = kanban.tasks("Alfa")[0]
    text = task_brief(first, [{"nome": "print.png", "caminho": "/tmp/print.png"}])
    assert "prioridade urgente · início 2026-11-04 · entrega 2026-11-06 · rótulos #melhorias" in text
    assert "Descrição:\nContas de teste para o time comercial." in text
    assert "0. [x] criar a planilha" in text and "1. [ ] mandar no Slack" in text
    assert "- print.png: /tmp/print.png" in text
    item = AutoItem(id="x", projeto="Alfa", tarefa=first["id"], texto=first["texto"], criado=0)
    prompt = auto_prompt(item, text)
    assert prompt.index("Preparar logins de Trial") < prompt.index("Descrição:") < prompt.index("Você está rodando sozinho")
    assert "Descrição:" not in auto_prompt(item)


# --- rotas ------------------------------------------------------------------------------------


def test_routes_edit_the_task_and_keep_activity_comments_and_attachments(core, settings):  # noqa: F811
    client, app, *_ = core
    write_project(settings.brain, NOTE)
    first = client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()[0]
    base = f"/brain/projects/Alfa/tasks/{first['id']}"

    answer = client.patch(base, json={"prioridade": "alta", "descricao": "Nova descrição"}, headers=AUTH)
    assert answer.status_code == 200 and answer.json()["prioridade"] == "alta" and answer.json()["descricao"] == "Nova descrição"
    assert client.patch(base, json={"entrega": "06/11"}, headers=AUTH).status_code == 422
    assert client.put(f"{base}", json={"state": "em-teste"}, headers=AUTH).status_code == 200

    comment = client.post(f"{base}/comentarios", json={"texto": "falta o Slack"}, headers=AUTH)
    assert comment.status_code == 201 and comment.json()["quem"] == "Pedro"
    attached = client.post(f"{base}/anexos?nome=print.png", content=b"\x89PNG-fake", headers=AUTH)
    assert attached.status_code == 201
    anexo = attached.json()
    raw = client.get(f"/kanban/anexos/{anexo['id']}?token={AUTH['X-Harness-Token']}")
    assert raw.status_code == 200 and raw.content == b"\x89PNG-fake"

    board = next(t for t in client.get("/kanban/tarefas", headers=AUTH).json() if t["id"] == first["id"])
    assert (board["comentarios"], board["anexos"], board["prioridade"]) == (1, 1, "alta")

    activity = client.get(f"{base}/atividade", headers=AUTH).json()
    kinds = [e["tipo"] for e in activity["eventos"]]
    assert kinds == ["prioridade", "descricao", "moveu", "comentario", "anexo"]
    assert [a["nome"] for a in activity["anexos"]] == ["print.png"]
    detalhes = client.get(f"{base}/pedido", headers=AUTH).json()["detalhes"]
    assert "Nova descrição" in detalhes and anexo["caminho"] in detalhes

    assert client.delete(f"{base}/comentarios/{comment.json()['id']}", headers=AUTH).status_code == 204
    assert client.delete(f"{base}/anexos/{anexo['id']}", headers=AUTH).status_code == 204
    from pathlib import Path

    assert not Path(anexo["caminho"]).exists()  # o arquivo guardado pela MÊTIS sai junto
    left = client.get(f"{base}/atividade", headers=AUTH).json()
    assert "comentario" not in [e["tipo"] for e in left["eventos"]] and left["anexos"] == []

    renamed = client.patch(base, json={"titulo": "Preparar os logins"}, headers=AUTH).json()
    moved = client.get(f"/brain/projects/Alfa/tasks/{renamed['id']}/atividade", headers=AUTH).json()["eventos"]
    assert [e["tipo"] for e in moved] == ["prioridade", "descricao", "moveu", "anexo", "anexo", "titulo"]
    assert client.get(f"{base}/atividade", headers=AUTH).status_code == 404  # o id de antes não existe mais


def test_metis_command_in_a_terminal_signs_the_activity_with_the_session(core, settings):  # noqa: F811
    client, app, *_ = core
    write_project(settings.brain, NOTE)
    session = client.post("/sessions", json={"kind": "claude", "title": "Agente do PR"}, headers=AUTH).json()
    first = client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()[1]
    headers = {**AUTH, "X-Harness-Session": session["id"]}
    assert client.put(f"/brain/projects/Alfa/tasks/{first['id']}", json={"state": "em-andamento"}, headers=headers).status_code == 200
    events = client.get(f"/brain/projects/Alfa/tasks/{first['id']}/atividade", headers=AUTH).json()["eventos"]
    assert events[-1]["quem"] == session["title"] != "Pedro"


def test_file_dropped_from_finder_is_copied_into_the_attachments(core, settings, tmp_path):  # noqa: F811
    client, app, *_ = core
    write_project(settings.brain, NOTE)
    first = client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()[0]
    base = f"/brain/projects/Alfa/tasks/{first['id']}/anexos/caminho"
    original = tmp_path / "Captura de Tela.png"
    original.write_bytes(b"png")
    item = client.post(base, json={"caminho": str(original)}, headers=AUTH)
    assert item.status_code == 201 and item.json()["nome"] == "Captura de Tela.png"
    copy = item.json()["caminho"]
    assert copy != str(original) and str(settings.home / "anexos") in copy  # uma cópia, o original fica onde está
    assert client.post(base, json={"caminho": str(tmp_path)}, headers=AUTH).status_code == 400  # pasta não
    assert client.delete(f"/brain/projects/Alfa/tasks/{first['id']}/anexos/{item.json()['id']}", headers=AUTH).status_code == 204
    assert original.exists()  # tirar o anexo apaga só a cópia da MÊTIS


def test_editing_only_the_description_leaves_the_task_line_as_written(settings):
    hand = NOTE.replace("- [ ] Revisar o PR\n", "- [ ] Revisar #front o PR 📅 2026-11-09 #back\n")
    kanban, _ = make(settings, hand)
    second = kanban.tasks("Alfa")[1]
    kanban.update("Alfa", second["id"], descricao="Olhar o CI.")
    lines = note(settings).splitlines()
    assert "- [ ] Revisar #front o PR 📅 2026-11-09 #back" in lines  # nada reordenado
    assert lines[lines.index("- [ ] Revisar #front o PR 📅 2026-11-09 #back") + 1] == "  Olhar o CI."
    # Rótulo escrito no título, com o mesmo texto: grava o rótulo.
    task = kanban.update("Alfa", second["id"], titulo="Revisar o PR #urgente")
    assert task["rotulos"] == ["front", "back", "urgente"] and task["id"] == second["id"]
