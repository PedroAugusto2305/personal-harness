"""v1.1.3: a tarefa nasce inteira, como o cartão aberto a deixaria.

Um agente (ou o `metis tarefa nova`) cria a tarefa já com descrição, prioridade, início e
entrega, além de rótulos e subtarefas: prioridade e datas vão na linha como campos do plugin
Tasks, e a descrição nas linhas recuadas logo abaixo, antes das subtarefas."""

from __future__ import annotations

import pytest

from harness_core.kanban import KanbanError, parse_tasks

from .test_v098a import FakeCore, run_cli
from .test_v098c_kanban import AUTH, core, write_project  # noqa: F401
from .test_v110_cartao import make, note

DESC = """**Contexto:** hoje só dá para conectar uma conta da Amazon no Portal.

**Escopo:**
- Permitir várias contas por aluno.
- Definir o limite de contas.

**Critérios de aceite:**
- Alunos com uma conta continuam funcionando."""


def test_task_is_born_whole(settings):
    kanban, log = make(settings)
    made = kanban.add(
        "Alfa", "Permitir mais de uma conta da Amazon", labels=["melhoria", "portal"], subtasks=["levantar", "implementar"],
        quem="Gerente de Projetos", descricao=DESC, prioridade="Alta", inicio="2026-11-12", entrega="2026-11-20",
    )  # fmt: skip
    assert (made["prioridade"], made["inicio"], made["entrega"]) == ("alta", "2026-11-12", "2026-11-20")
    assert made["rotulos"] == ["melhoria", "portal"] and made["descricao"] == DESC
    assert [s["texto"] for s in made["subtarefas"]] == ["levantar", "implementar"]
    text = note(settings)
    assert "- [ ] Permitir mais de uma conta da Amazon #melhoria #portal ⏫ 🛫 2026-11-12 📅 2026-11-20\n  **Contexto:**" in text
    assert "  - Definir o limite de contas.\n" in text
    assert "  - Alunos com uma conta continuam funcionando.\n  - [ ] levantar\n  - [ ] implementar\n" in text
    # A tarefa de cima e a de baixo seguem intactas; a nova entra depois da última aberta.
    tasks = parse_tasks(text)
    assert [t.texto for t in tasks][:3] == ["Preparar logins de Trial", "Revisar o PR", "Permitir mais de uma conta da Amazon"]
    assert tasks[0].subtasks_total == 2 and tasks[1].descricao == ""
    # Na atividade, só "criou" e as subtarefas: a descrição e os campos fazem parte da criação.
    kinds = [e["tipo"] for e in log.events("Alfa", made["id"])]
    assert "prioridade" not in kinds and "descricao" not in kinds and "data" not in kinds and "criou" in kinds


def test_normal_priority_and_empty_fields_leave_the_line_alone(settings):
    kanban, _ = make(settings)
    made = kanban.add("Alfa", "Sem extras", prioridade="Normal", descricao="  ", inicio="", entrega=None)
    assert (made["prioridade"], made["inicio"], made["entrega"], made["descricao"]) == ("", "", "", "")
    assert "- [ ] Sem extras\n" in note(settings)
    accented = kanban.add("Alfa", "Com acento", prioridade="média")
    assert accented["prioridade"] == "media"


def test_bad_fields_are_refused_before_anything_is_written(settings):
    kanban, _ = make(settings)
    before = note(settings)
    with pytest.raises(KanbanError, match="prioridade desconhecida"):
        kanban.add("Alfa", "X", prioridade="altíssima")
    with pytest.raises(KanbanError, match="data inválida em entrega"):
        kanban.add("Alfa", "X", entrega="20/11/2026")
    with pytest.raises(KanbanError, match="subtarefas"):
        kanban.add("Alfa", "X", descricao="Passos:\n- [ ] um\n- [ ] dois")
    assert note(settings) == before


def test_http_and_central_create_the_whole_task(core, settings):
    client, app, *_ = core
    write_project(settings.brain)
    base = "/brain/projects/Alfa/tasks"
    created = client.post(base, json={"text": "Pelo HTTP", "descricao": "Corpo.", "prioridade": "urgente", "entrega": "2026-11-21"}, headers=AUTH)
    assert created.status_code == 201
    assert (created.json()["prioridade"], created.json()["entrega"], created.json()["descricao"]) == ("urgente", "2026-11-21", "Corpo.")
    bad = client.post(base, json={"text": "Data ruim", "entrega": "amanhã"}, headers=AUTH)
    assert bad.status_code == 400 and "AAAA-MM-DD" in bad.json()["detail"]

    from harness_core.mcp_hub import Context

    ctx = Context(session="s1", who="Gerente de Projetos", cwd=None, allowed=None)
    tool = next(t for t in app.state.hub.tools_for(ctx) if t.name == "tarefa_nova")
    props = tool.schema["properties"]
    assert {"descricao", "prioridade", "inicio", "entrega"} <= set(props)
    said = tool.run({"texto": "Pela central", "projeto": "Alfa", "descricao": DESC, "prioridade": "baixa", "entrega": "2026-11-30",
                     "rotulos": ["ajuste"], "subtarefas": ["a", "b", "c"]}, ctx)  # fmt: skip
    assert "prioridade baixa" in said and "entrega 2026-11-30" in said and "com descrição" in said and "3 subtarefa(s)" in said
    task = next(t for t in app.state.hub.kanban.tasks("Alfa") if t["texto"] == "Pela central")
    assert task["descricao"] == DESC and task["subtasks_total"] == 3 and task["rotulos"] == ["ajuste"]


def test_cli_sends_the_fields(monkeypatch, settings, capsys):
    path = "/brain/projects/Alfa/tasks"
    fake = FakeCore({("POST", path): {"id": "abc12345", "state": "pendente"}})
    argv = ["tarefa", "nova", "Lançar", "o", "Trial", "--projeto", "Alfa", "--descricao", "Corpo", "--prioridade", "alta",
            "--entrega", "2026-11-20", "--rotulo", "melhoria", "--rotulo", "portal", "--subtarefa", "um", "--subtarefa", "dois"]  # fmt: skip
    assert run_cli(monkeypatch, settings, fake, argv) == 0
    assert fake.calls[-1] == ("POST", path, {
        "text": "Lançar o Trial", "state": "pendente", "rotulos": ["melhoria", "portal"], "subtarefas": ["um", "dois"],
        "descricao": "Corpo", "prioridade": "alta", "entrega": "2026-11-20",
    })  # fmt: skip
    assert "tarefa abc12345 criada em Alfa" in capsys.readouterr().out
    assert run_cli(monkeypatch, settings, fake, ["tarefa", "nova", "Simples", "--projeto", "Alfa"]) == 0
    assert fake.calls[-1][2] == {"text": "Simples", "state": "pendente", "rotulos": [], "subtarefas": []}
