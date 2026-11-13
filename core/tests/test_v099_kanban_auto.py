"""v0.9.9: coluna Auto do kanban (a fila que roda tarefa sozinha)."""

import asyncio

import pytest

from harness_core.kanban_auto import AutoError, AutoQueue, auto_prompt


class Harness:
    def __init__(self, tmp_path, fail: str = ""):
        self.started: list[str] = []
        self.moves: list[tuple[str, str, str]] = []
        self.events: list[dict] = []
        self.fail = fail
        self.n = 0

        async def start(item):
            if self.fail and self.fail in item.texto:
                raise RuntimeError("sem pasta")
            self.n += 1
            self.started.append(item.tarefa)
            return f"s{self.n}", f"/tmp/w{self.n}"

        self.queue = AutoQueue(tmp_path / "kanban-auto.json", start=start, move=lambda p, t, s: self.moves.append((p, t, s)), publish=self.events.append)


def run(coro):
    return asyncio.run(coro)


def test_queue_runs_one_at_a_time_and_stop_moves_to_testing(tmp_path):
    h = Harness(tmp_path)
    q = h.queue
    q.enqueue("Alfa", "t1", "Primeira tarefa")
    q.enqueue("Alfa", "t2", "Segunda tarefa", cli="codex", esforco="high")
    run(q.pump())
    assert h.started == ["t1"] and h.moves == [("Alfa", "t1", "em-andamento")]
    view = q.view()
    assert view["rodando"] == 1 and view["na_fila"] == 1
    # Notification (pergunta) não conta como fim.
    q.on_bus_event({"type": "session.status", "id": "s1", "status": "waiting", "atencao": "pergunta"})
    assert q.view()["rodando"] == 1
    q.on_bus_event({"type": "session.status", "id": "s1", "status": "waiting", "atencao": "terminou"})
    assert ("Alfa", "t1", "em-teste") in h.moves
    run(q.pump())
    assert h.started == ["t1", "t2"]
    assert [i["status"] for i in q.view()["itens"]] == ["feito", "rodando"]


def test_limit_lets_two_run_and_duplicate_is_refused(tmp_path):
    h = Harness(tmp_path)
    q = h.queue
    q.set_limit(2)
    q.enqueue("Alfa", "t1", "um")
    with pytest.raises(AutoError):
        q.enqueue("Alfa", "t1", "um de novo")
    q.enqueue("Alfa", "t2", "dois")
    q.enqueue("Alfa", "t3", "três")
    run(q.pump())
    assert h.started == ["t1", "t2"] and q.view()["na_fila"] == 1
    with pytest.raises(AutoError):
        q.set_limit(9)


def test_start_error_and_closed_terminal_become_errors(tmp_path):
    h = Harness(tmp_path, fail="quebra")
    q = h.queue
    q.enqueue("Alfa", "t1", "esta quebra")
    q.enqueue("Alfa", "t2", "esta roda")
    run(q.pump())
    items = {i["tarefa"]: i for i in q.view()["itens"]}
    assert items["t1"]["status"] == "erro" and "sem pasta" in items["t1"]["erro"]
    assert items["t2"]["status"] == "rodando"
    q.on_bus_event({"type": "session.status", "id": "s1", "status": "exited", "exit_code": 1})
    items = {i["tarefa"]: i for i in q.view()["itens"]}
    assert items["t2"]["status"] == "erro" and ("Alfa", "t2", "em-teste") not in h.moves


def test_cancel_only_queued_and_restart_turns_running_into_error(tmp_path):
    h = Harness(tmp_path)
    q = h.queue
    first = q.enqueue("Alfa", "t1", "um")
    second = q.enqueue("Alfa", "t2", "dois")
    run(q.pump())
    with pytest.raises(AutoError):
        q.cancel(first.id)
    assert q.cancel(second.id).status == "cancelado"
    again = Harness(tmp_path).queue  # o núcleo reiniciou com t1 rodando
    status = {i["tarefa"]: i["status"] for i in again.view()["itens"]}
    assert status == {"t1": "erro", "t2": "cancelado"}
    again.clear_done()
    assert again.view()["itens"] == []


def test_prompt_names_the_task_and_forbids_push():
    h_item = type("I", (), {"projeto": "Alfa", "tarefa": "abc-1", "texto": "Arrumar o login"})()
    text = auto_prompt(h_item)
    assert "Arrumar o login" in text and "abc-1" in text and "push" in text


# --- rotas ----------------------------------------------------------------------------------

from .test_brain import AUTH, client, vault  # noqa: E402,F401 (fixtures)


def test_routes_list_all_tasks_and_validate_the_auto_queue(client):
    tasks = client.get("/kanban/tarefas", headers=AUTH).json()
    assert {t["projeto"] for t in tasks} <= {"Alfa", "Beta"} and all(t["n"] >= 1 for t in tasks)
    created = client.post("/brain/projects/Alfa/tasks", json={"text": "Rodar sozinha"}, headers=AUTH).json()
    assert client.post("/kanban/auto", json={"projeto": "Alfa", "tarefa": "nao-existe"}, headers=AUTH).status_code == 404
    assert client.post("/kanban/auto", json={"projeto": "Alfa", "tarefa": created["id"], "permissao": "tudo"}, headers=AUTH).status_code == 422
    # Agente que não existe (apagado depois de guardado no Rodar sozinha): recusa já na fila.
    gone = client.post("/kanban/auto", json={"projeto": "Alfa", "tarefa": created["id"], "agente": "nao-existe"}, headers=AUTH)
    assert gone.status_code == 400 and "não existe" in gone.json()["detail"]
    view = client.get("/kanban/auto", headers=AUTH).json()
    assert view["limite"] == 1 and view["itens"] == []
    assert client.put("/kanban/auto/limite", json={"limite": 2}, headers=AUTH).json()["limite"] == 2


def test_vault_tree_lists_folders_first_and_skips_system_dirs(client, vault):
    (vault / "_templates").mkdir(exist_ok=True)
    (vault / "_templates" / "T.md").write_text("x", encoding="utf-8")
    (vault / "HOME.md").write_text("# Home", encoding="utf-8")
    tree = client.get("/brain/arvore", headers=AUTH).json()
    names = [n["nome"] for n in tree]
    assert "_templates" not in names and ".obsidian" not in names
    assert names[-1] == "HOME" and tree[0]["tipo"] == "pasta"
    projetos = next(n for n in tree if n["nome"] == "01-PROJETOS")
    alfa = next(n for n in projetos["filhos"] if n["nome"] == "Alfa")
    assert any(f["caminho"] == "01-PROJETOS/Alfa/Alfa.md" for f in alfa["filhos"])


def test_study_question_becomes_a_block_in_the_concept_note(tmp_path):
    from harness_core.study_map import StudyError, StudyMap
    from harness_core.vault import Vault

    root = tmp_path / "Brain"
    (root / "01-PROJETOS" / "AI Engineer 2027").mkdir(parents=True)
    (root / "01-PROJETOS" / "AI Engineer 2027" / "AI Engineer 2027.md").write_text("---\ntipo: projeto\n---\n# AI\n", encoding="utf-8")
    study = StudyMap(Vault(root), project=lambda: "AI Engineer 2027")
    done = study.add_question("Atenção", "De onde vem a informação?", ["Da própria palavra", "Das outras palavras", "Não sei"])
    text = (root / done["caminho"]).read_text(encoding="utf-8")
    assert "## Perguntas" in text and "> [!pergunta] Pergunta de previsão · agente de estudo" in text  # v1.3.0: sem Sócrates fixo
    assert "> - [ ] Das outras palavras" in text
    study.add_question("Atenção", "Outra?", ["sim", "não"])
    assert (root / done["caminho"]).read_text(encoding="utf-8").count("[!pergunta]") == 2
    with pytest.raises(StudyError):
        study.add_question("Atenção", "Só uma opção", ["sim"])
