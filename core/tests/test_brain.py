"""v0.5: Brain (índice, busca, leitura, precedentes) e kanban escrito nas notas."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core.app import create_app
from harness_core.brain_index import BrainIndex, fold, terms
from harness_core.claude_settings import build_claude_settings
from harness_core.kanban import Kanban, KanbanError, parse_tasks
from harness_core.relay import RELAY_SCRIPT
from harness_core.vault import Vault, abstract, set_frontmatter, split_frontmatter

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
TODAY = date.today().isoformat()

ALFA = """---
tipo: projeto
status: ativo
area: "[[Carreira]]"
prazo: 2026-12-15
diretorio: "{repo}"
atualizado: 2026-11-01
tags: [teste]
---

# 🎯 Alfa

## ✅ Próximas ações

**Retomar aqui:** texto solto que abre a seção.
- [ ] Deixar o webhook da Guru idempotente
- [ ] Revisar o painel #em-andamento
  - [x] subtarefa feita
  - [ ] subtarefa aberta
- [ ] Testes de privacidade #em-teste
- [x] Primeira entrega ✅ 2026-11-02
- [x] ~~Ideia descartada~~ cancelada

## 📎 Recursos

- [ ] isto não é tarefa: está fora da seção
"""

BETA = """---
tipo: projeto
status: ativo
---

# 🎯 Beta

Sem a seção de ações ainda.
"""

DECISAO_BETA = """---
tipo: decisao
data: 2026-10-20
status: aceita
projeto: "[[Beta]]"
---

# ⚖️ Webhook passa por fila com chave de idempotência

> [!abstract] A decisão
> Todo webhook entra numa fila e é processado uma vez só, pela chave de idempotência da Guru.

Ligada a [[Alfa]].
"""

ANTIGA_BETA = """---
tipo: decisao
data: 2026-09-01
status: substituida
projeto: "[[Beta]]"
---

# ⚖️ Webhook idempotente pelo id da transação

> [!abstract] A decisão
> Webhook da Guru idempotente pelo transaction_id (substituída).
"""

DECISAO_ALFA = """---
tipo: decisao
data: 2026-11-03
status: proposta
projeto: "[[Alfa]]"
---

# ⚖️ Painel lê os dados da Guru direto

> [!abstract] A decisão
> O painel consulta a Guru sem cache.
"""


@pytest.fixture
def vault(settings, repo) -> Path:
    root = settings.brain
    alfa = root / "01-PROJETOS" / "Alfa"
    beta = root / "01-PROJETOS" / "Beta"
    (alfa / "decisoes").mkdir(parents=True)
    (beta / "decisoes").mkdir(parents=True)
    (alfa / "Alfa.md").write_text(ALFA.format(repo=repo), encoding="utf-8")
    (beta / "Beta.md").write_text(BETA, encoding="utf-8")
    (beta / "decisoes" / "Webhook passa por fila com chave de idempotência.md").write_text(DECISAO_BETA, encoding="utf-8")
    (beta / "decisoes" / "Webhook idempotente pelo id da transação.md").write_text(ANTIGA_BETA, encoding="utf-8")
    (alfa / "decisoes" / "Painel lê os dados da Guru direto.md").write_text(DECISAO_ALFA, encoding="utf-8")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "lixo.md").write_text("não indexar", encoding="utf-8")
    return root


@pytest.fixture
def client(settings, accounts, vault):
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as test_client:
        yield test_client


# --- frontmatter e leitura -----------------------------------------------------


def test_frontmatter_set_keeps_other_lines():
    text = '---\ntipo: projeto\narea: "[[Carreira]]"\ntags: [a, b]\n---\n\ncorpo\n'
    changed = set_frontmatter(text, "estagio", "construindo")
    assert changed.startswith('---\ntipo: projeto\narea: "[[Carreira]]"\ntags: [a, b]\nestagio: construindo\n---\n')
    again = set_frontmatter(changed, "estagio", "pausado")
    assert again.count("estagio:") == 1 and "estagio: pausado" in again
    meta, body = split_frontmatter(again)
    assert meta["area"] == "[[Carreira]]" and body.strip() == "corpo"


def test_abstract_reads_first_callout():
    body = "# T\n\n> [!abstract] A decisão\n> Primeira linha\n> segunda.\n\n## Resto\n"
    assert abstract(body) == "Primeira linha segunda."


def test_terms_fold_accents_and_drop_stopwords():
    assert fold("Decisão Única") == "decisao unica"
    assert terms("O webhook da Guru não é idempotente para a fila") == ["webhook", "guru", "idempotente", "fila"]


# --- tarefas ----------------------------------------------------------------------


def test_parse_tasks_reads_states_subtasks_and_section(vault):
    tasks = parse_tasks((vault / "01-PROJETOS/Alfa/Alfa.md").read_text(encoding="utf-8"))
    assert [t.state for t in tasks] == ["pendente", "em-andamento", "em-teste", "concluida", "concluida"]
    assert tasks[1].text == "Revisar o painel" and (tasks[1].subtasks_done, tasks[1].subtasks_total) == (1, 2)
    assert tasks[3].done_on == "2026-11-02" and tasks[4].cancelled
    assert all("fora da seção" not in t.text for t in tasks)
    assert len({t.id for t in tasks}) == len(tasks)


def test_move_task_writes_tag_then_done_date_then_back(vault):
    kanban = Kanban(Vault(vault))
    note = vault / "01-PROJETOS/Alfa/Alfa.md"
    first = kanban.tasks("Alfa")[0]
    moved = kanban.move("Alfa", first["id"], "em-andamento")
    assert moved["state"] == "em-andamento" and moved["id"] == first["id"]
    assert "- [ ] Deixar o webhook da Guru idempotente #em-andamento\n" in note.read_text(encoding="utf-8")
    kanban.move("Alfa", first["id"], "concluida")
    assert f"- [x] Deixar o webhook da Guru idempotente ✅ {TODAY}\n" in note.read_text(encoding="utf-8")
    kanban.move("Alfa", first["id"], "pendente")
    text = note.read_text(encoding="utf-8")
    assert "- [ ] Deixar o webhook da Guru idempotente\n" in text
    # o resto da nota não mudou: subtarefas, linha fora da seção e frontmatter
    assert "  - [x] subtarefa feita" in text and "isto não é tarefa" in text and "prazo: 2026-12-15" in text


def test_move_unknown_task_or_state_fails(vault):
    kanban = Kanban(Vault(vault))
    with pytest.raises(KanbanError):
        kanban.move("Alfa", "naoexiste", "concluida")
    with pytest.raises(KanbanError):
        kanban.move("Alfa", kanban.tasks("Alfa")[0]["id"], "talvez")


def test_add_task_goes_after_last_open_task_and_its_subtasks(vault):
    kanban = Kanban(Vault(vault))
    task = kanban.add("Alfa", "  Nova tarefa\ncom quebra  ")
    assert task["text"] == "Nova tarefa com quebra" and task["state"] == "pendente"
    lines = (vault / "01-PROJETOS/Alfa/Alfa.md").read_text(encoding="utf-8").splitlines()
    at = lines.index("- [ ] Nova tarefa com quebra")
    assert lines[at - 1] == "- [ ] Testes de privacidade #em-teste"
    assert lines[at + 1].startswith("- [x] Primeira entrega")


def test_add_task_creates_section_when_missing(vault):
    kanban = Kanban(Vault(vault))
    kanban.add("Beta", "Começar", "em-andamento")
    text = (vault / "01-PROJETOS/Beta/Beta.md").read_text(encoding="utf-8")
    assert text.endswith("## ✅ Próximas ações\n\n- [ ] Começar #em-andamento\n")
    assert [t["state"] for t in kanban.tasks("Beta")] == ["em-andamento"]


def test_projects_board_and_stage(vault):
    kanban = Kanban(Vault(vault))
    board = {p["name"]: p for p in kanban.projects()}
    alfa = board["Alfa"]
    assert alfa["stage"] == "" and alfa["area"] == "Carreira" and alfa["deadline"] == "2026-12-15"
    assert alfa["tasks"] == {"pendente": 1, "em-andamento": 1, "em-teste": 1, "concluida": 2}
    assert alfa["records"]["decisoes"] == 1 and alfa["proposals"] == 1
    updated = kanban.set_stage("Alfa", "construindo")
    assert updated["stage"] == "construindo"
    meta, _ = split_frontmatter((vault / "01-PROJETOS/Alfa/Alfa.md").read_text(encoding="utf-8"))
    assert meta["estagio"] == "construindo" and meta["atualizado"] == TODAY and meta["tags"] == "[teste]"
    with pytest.raises(KanbanError):
        kanban.set_stage("Alfa", "voando")


# --- índice, busca e precedentes ----------------------------------------------------


def test_index_searches_without_accents_and_skips_system_folders(vault, settings):
    index = BrainIndex(Vault(vault), settings.home / "brain.db")
    result = index.refresh(max_age=0)
    assert result["total"] == 5  # 2 projetos + 3 decisões; .obsidian fica de fora
    found = index.search("idempotencia fila")
    assert found[0]["title"] == "Webhook passa por fila com chave de idempotência"
    assert "\x02" in found[0]["snippet"]
    assert {r["title"] for r in index.search("", tipos=["projeto"])} == {"Alfa", "Beta"}
    assert index.search("guru", projeto="Alfa")[0]["projeto"] == "Alfa"


def test_index_picks_up_edits_and_deletions(vault, settings):
    index = BrainIndex(Vault(vault), settings.home / "brain.db")
    index.refresh(max_age=0)
    extra = vault / "05-NOTAS" / "Nota nova sobre zebras.md"
    extra.parent.mkdir()
    extra.write_text("---\ntipo: permanente\n---\n\nZebras listradas.\n", encoding="utf-8")
    assert index.refresh(max_age=0)["indexed"] == 1
    assert index.search("zebras")[0]["title"] == "Nota nova sobre zebras"
    extra.unlink()
    assert index.refresh(max_age=0)["removed"] == 1
    assert index.search("zebras") == []


def test_note_has_body_meta_and_backlinks(vault, settings):
    index = BrainIndex(Vault(vault), settings.home / "brain.db")
    note = index.note(title="alfa")
    assert note["tipo"] == "projeto" and note["meta"]["status"] == "ativo"
    assert "Próximas ações" in note["body"]
    # o projeto: "[[Alfa]]" do frontmatter também é link; mais recente primeiro
    assert [b["title"] for b in note["backlinks"]] == ["Painel lê os dados da Guru direto", "Webhook passa por fila com chave de idempotência"]


def test_precedents_come_from_other_projects_and_skip_replaced(vault, settings):
    vault_obj = Vault(vault)
    index = BrainIndex(vault_obj, settings.home / "brain.db")
    found = index.precedents("Alfa", index.project_context("Alfa"))
    titles = [f["title"] for f in found]
    assert "Webhook passa por fila com chave de idempotência" in titles
    assert "Webhook idempotente pelo id da transação" not in titles  # substituída
    assert all(f["projeto"] != "Alfa" for f in found)


def test_session_context_resolves_project_from_repo_subfolder(vault, settings, repo):
    index = BrainIndex(Vault(vault), settings.home / "brain.db")
    (repo / "src").mkdir()
    text = index.session_context(str(repo / "src"))
    assert text.startswith("MÊTIS · precedentes do Brain para [[Alfa]]")
    assert "[[Webhook passa por fila com chave de idempotência]] (Beta · aceita)" in text
    assert "metis tarefas" in text
    assert index.session_context(str(settings.home)) == ""


# --- API, hook e CLI -------------------------------------------------------------


def test_api_board_stage_and_tasks(client):
    projects = client.get("/brain/projects", headers=AUTH).json()
    assert [p["name"] for p in projects] == ["Alfa", "Beta"]
    assert client.put("/brain/projects/Alfa/stage", json={"stage": "planejando"}, headers=AUTH).json()["stage"] == "planejando"
    assert client.put("/brain/projects/Alfa/stage", json={"stage": "voando"}, headers=AUTH).status_code == 422
    assert client.put("/brain/projects/Zeta/stage", json={"stage": "ideia"}, headers=AUTH).status_code == 404
    created = client.post("/brain/projects/Alfa/tasks", json={"text": "Pela API"}, headers=AUTH)
    assert created.status_code == 201
    task_id = created.json()["id"]
    moved = client.put(f"/brain/projects/Alfa/tasks/{task_id}", json={"state": "em-teste"}, headers=AUTH)
    assert moved.json()["state"] == "em-teste"
    assert client.get("/brain/projects/Alfa/tasks", headers=AUTH).status_code == 200
    assert client.get("/brain/projects", headers={}).status_code == 401


def test_api_search_note_place_and_session_context(client, repo):
    assert client.get("/brain/search", params={"q": "painel guru"}, headers=AUTH).json()[0]["title"] == "Painel lê os dados da Guru direto"
    note = client.get("/brain/note", params={"title": "Beta"}, headers=AUTH).json()
    assert note["title"] == "Beta"
    assert client.get("/brain/note", params={"title": "Ninguém"}, headers=AUTH).status_code == 404
    assert client.get("/brain/note", params={"path": "../fora.md"}, headers=AUTH).status_code == 404
    place = client.get("/brain/place", params={"cwd": str(repo)}, headers=AUTH).json()
    assert place["project"]["name"] == "Alfa" and len(place["tasks"]) == 5 and place["precedents"]
    text = client.get("/brain/session-context", params={"cwd": str(repo)}, headers=AUTH).text
    assert "[[Alfa]]" in text
    assert client.post("/brain/known", json={"titles": ["alfa", "Inexistente"]}, headers=AUTH).json() == ["alfa"]
    assert client.get("/brain/status", headers=AUTH).json()["total"] == 5


def test_claude_settings_inject_brain_context_on_session_start(tmp_path):
    hooks = build_claude_settings(tmp_path / "relay.sh")["hooks"]["SessionStart"][0]["hooks"]
    assert [h["command"].split()[-1] for h in hooks] == ["SessionStart", "context"]
    assert 'kind" = "context"' in RELAY_SCRIPT and "/brain/session-context?session=" in RELAY_SCRIPT
