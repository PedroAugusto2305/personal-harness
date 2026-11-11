"""v1.1.4: excluir uma tarefa do kanban.

A tarefa sai da nota com a descrição e as subtarefas, sem deixar buraco; a atividade, os
comentários e os anexos dela saem do tarefas.db (e o arquivo guardado pela MÊTIS, do disco); a
fila do Auto esquece a tarefa. Só a janela exclui: um terminal (metis ou agente) é recusado."""

from __future__ import annotations

from pathlib import Path

from harness_core.kanban import Kanban, parse_tasks
from harness_core.kanban_auto import AutoItem, AutoQueue
from harness_core.task_log import TaskLog
from harness_core.vault import Vault

from .test_v098c_kanban import AUTH, core, write_project  # noqa: F401

NOTE = """---
tipo: projeto
---

# Alfa

## ✅ Próximas ações

- [ ] Preparar logins de Trial #melhorias 🔺 📅 2026-11-06 #em-andamento
  Contas de teste para o time comercial.

  Usar o domínio de homologação.
  - [x] criar a planilha ✅ 2026-11-05
  - [ ] mandar no Slack
- [ ] Revisar o PR
- [x] Feita ✅ 2026-11-02

## Depois

Fim.
"""


def make(settings, text: str = NOTE) -> tuple[Kanban, TaskLog]:
    write_project(settings.brain, text)
    kanban = Kanban(Vault(settings.brain))
    kanban.log = TaskLog(settings.home / "tarefas.db")
    return kanban, kanban.log


def note(settings) -> str:
    return (settings.brain / "01-PROJETOS" / "Alfa" / "Alfa.md").read_text(encoding="utf-8")


def test_delete_removes_the_line_the_description_and_the_subtasks(settings):
    kanban, _ = make(settings)
    first = kanban.tasks("Alfa")[0]
    result = kanban.delete("Alfa", first["id"])
    assert result["tarefa"]["id"] == first["id"]
    assert result["linhas"][0].startswith("- [ ] Preparar logins") and result["linhas"][-1] == "  - [ ] mandar no Slack"
    text = note(settings)
    assert "Preparar logins" not in text and "homologação" not in text and "mandar no Slack" not in text
    assert "## ✅ Próximas ações\n\n- [ ] Revisar o PR\n- [x] Feita ✅ 2026-11-02\n\n## Depois\n\nFim.\n" in text
    assert [t["texto"] for t in kanban.tasks("Alfa")] == ["Revisar o PR", "Feita"]


def test_delete_leaves_no_double_blank_line_nor_trailing_blanks(settings):
    kanban, _ = make(settings, "# Alfa\n\n## Próximas ações\n\n- [ ] Só ela\n\n## Depois\n")
    kanban.delete("Alfa", kanban.tasks("Alfa")[0]["id"])
    assert note(settings) == "# Alfa\n\n## Próximas ações\n\n## Depois\n"
    kanban, _ = make(settings, "# Alfa\n\n## Próximas ações\n\n- [ ] Uma\n- [ ] Última\n")
    kanban.delete("Alfa", kanban.tasks("Alfa")[1]["id"])
    assert note(settings) == "# Alfa\n\n## Próximas ações\n\n- [ ] Uma\n"


def test_delete_also_works_for_done_tasks_and_the_old_id(settings):
    kanban, _ = make(settings)
    done = kanban.tasks("Alfa")[2]
    kanban.delete("Alfa", done["id"])
    assert "Feita" not in note(settings)
    # O id de antes da v1.0 (com os rótulos) ainda acha a tarefa, como no mover.
    old = parse_tasks(note(settings))[0].old_id
    kanban.delete("Alfa", old)
    assert [t["texto"] for t in kanban.tasks("Alfa")] == ["Revisar o PR"]


def test_delete_forgets_activity_comments_attachments_and_the_auto_queue(settings, tmp_path):
    kanban, log = make(settings)
    first, second = kanban.tasks("Alfa")[:2]
    log.comment("Alfa", first["id"], "Pedro", "olhar o domínio")
    log.attach("Alfa", first["id"], "Pedro", "print.png", "/tmp/print.png", 3)
    log.comment("Alfa", second["id"], "Pedro", "fica")
    queue = AutoQueue(tmp_path / "auto.json", start=None, move=None, publish=lambda e: None)  # type: ignore[arg-type]
    queue.enqueue("Alfa", first["id"], first["texto"])
    queue.enqueue("Alfa", second["id"], second["texto"])
    kanban.on_delete = queue.forget_task
    result = kanban.delete("Alfa", first["id"])
    assert [a["nome"] for a in result["anexos"]] == ["print.png"]
    assert log.events("Alfa", first["id"]) == [] and log.attachments("Alfa", first["id"]) == []
    assert [e["texto"] for e in log.events("Alfa", second["id"])] == ["fica"]
    assert [i.tarefa for i in queue.items] == [second["id"]]


def test_repeated_task_below_inherits_the_id_with_its_history(settings, tmp_path):
    kanban, log = make(settings, "## Próximas ações\n\n- [ ] Igual\n- [ ] Igual\n  - [ ] sub da segunda\n- [ ] Igual\n")
    ids = [t["id"] for t in kanban.tasks("Alfa")]
    base = ids[0]
    assert ids == [base, f"{base}-2", f"{base}-3"]
    log.comment("Alfa", base, "Pedro", "da primeira")
    log.comment("Alfa", f"{base}-2", "Pedro", "da segunda")
    log.comment("Alfa", f"{base}-3", "Pedro", "da terceira")
    queue = AutoQueue(tmp_path / "auto.json", start=None, move=None, publish=lambda e: None)  # type: ignore[arg-type]
    queue.enqueue("Alfa", f"{base}-2", "Igual")
    kanban.on_delete = queue.forget_task
    kanban.on_rename = queue.rename_task
    result = kanban.delete("Alfa", base)
    assert result["ids"] == {f"{base}-2": base, f"{base}-3": f"{base}-2"}
    left = kanban.tasks("Alfa")
    assert [t["id"] for t in left] == [base, f"{base}-2"] and left[0]["subtasks_total"] == 1
    assert [e["texto"] for e in log.events("Alfa", base)] == ["da segunda"]
    assert [e["texto"] for e in log.events("Alfa", f"{base}-2")] == ["da terceira"]
    assert log.events("Alfa", f"{base}-3") == []
    assert [i.tarefa for i in queue.items] == [base]


def test_route_deletes_the_task_and_the_saved_attachment_file(core, settings):  # noqa: F811
    client, app, *_ = core
    write_project(settings.brain, NOTE)
    first = client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()[0]
    base = f"/brain/projects/Alfa/tasks/{first['id']}"
    assert client.post(f"{base}/comentarios", json={"texto": "vai sumir"}, headers=AUTH).status_code == 201
    anexo = client.post(f"{base}/anexos?nome=print.png", content=b"\x89PNG-fake", headers=AUTH).json()
    assert Path(anexo["caminho"]).exists()

    answer = client.delete(base, headers=AUTH)
    assert answer.status_code == 200
    body = answer.json()
    assert (body["id"], body["texto"], body["anexos"]) == (first["id"], "Preparar logins de Trial", 1)
    assert not Path(anexo["caminho"]).exists()  # o arquivo guardado pela MÊTIS sai junto
    assert [t["texto"] for t in client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()] == ["Revisar o PR", "Feita"]
    assert client.get(f"{base}/atividade", headers=AUTH).status_code == 404
    assert client.delete(base, headers=AUTH).status_code == 404  # já saiu
    assert client.delete("/brain/projects/Nenhum/tasks/abc", headers=AUTH).status_code == 404


def test_route_keeps_attachment_files_the_metis_did_not_save(core, settings, tmp_path):  # noqa: F811
    client, app, *_ = core
    write_project(settings.brain, NOTE)
    first = client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()[0]
    outside = tmp_path / "fora.txt"
    outside.write_text("meu", encoding="utf-8")
    log = TaskLog(settings.home / "tarefas.db")
    log.attach("Alfa", first["id"], "Pedro", "fora.txt", str(outside), 3)
    assert client.delete(f"/brain/projects/Alfa/tasks/{first['id']}", headers=AUTH).status_code == 200
    assert outside.exists()


def test_terminal_cannot_delete_and_a_running_auto_task_is_refused(core, settings):  # noqa: F811
    client, app, *_ = core
    write_project(settings.brain, NOTE)
    first, second = client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()[:2]
    session = client.post("/sessions", json={"kind": "claude", "title": "Agente"}, headers=AUTH).json()
    refused = client.delete(f"/brain/projects/Alfa/tasks/{first['id']}", headers={**AUTH, "X-Harness-Session": session["id"]})
    assert refused.status_code == 403 and "Pedro" in refused.json()["detail"]

    auto: AutoQueue = app.state.auto
    # Direto na lista: pelo enqueue, a fila abriria o terminal de verdade.
    item = AutoItem(id="x1", projeto="Alfa", tarefa=second["id"], texto=second["texto"], criado=0.0, status="rodando")
    auto.items.append(item)
    busy = client.delete(f"/brain/projects/Alfa/tasks/{second['id']}", headers=AUTH)
    assert busy.status_code == 409 and "Auto" in busy.json()["detail"]
    item.status = "erro"
    assert client.delete(f"/brain/projects/Alfa/tasks/{second['id']}", headers=AUTH).status_code == 200
    assert all(i.tarefa != second["id"] for i in auto.items)
    assert len(client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()) == 2
