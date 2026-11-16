"""v1.4.0: planos de estudo (criar, editar, ativar, desativar e excluir, vários ativos, o plano em
foco e o agente de estudo montando o cronograma)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.mcp_hub import Context
from harness_core.study_map import StudyError, StudyMap, parse_plan
from harness_core.study_plans import PlanError, StudyPlans, add_log, clean_weeks, render_schedule, skeleton
from harness_core.vault import Vault, split_frontmatter

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
LEGACY = "AI Teste"
TODAY = date(2026, 10, 14)  # quarta da semana 2 do plano antigo

NOTE = """---
tipo: projeto
status: ativo
inicio: 2026-09-21
prazo: 2027-01-04
---

# 🎯 AI Teste

> [!abstract] Objetivo
> Chegar a **2027-01-04** com um projeto público.

## 🔁 Replanejamento

| Sem. | Datas | Foco | Entrega demonstrável | Origem |
|---|---|---|---|---|
| **1** | 10-05 a 10-10 | Ativação + esqueleto | Repositório | Fusão |
| 2 | 10-12 a 10-17 | [[FastAPI]] e REST | CRUD de leads | Semana 3 |
| 3 | 10-19 a 10-24 | Testes e CI | pytest | Semana 4 |

## ✅ Próximas ações

## 📝 Log

### 2026-10-05
- Projeto criado.
"""


@pytest.fixture
def vault(settings) -> Vault:
    folder = settings.brain / "01-PROJETOS" / LEGACY
    folder.mkdir(parents=True)
    (folder / f"{LEGACY}.md").write_text(NOTE, encoding="utf-8")
    (folder / "conceitos").mkdir()
    (folder / "conceitos" / "RAG.md").write_text("---\ntipo: conceito\ndominio: 1\n---\n\n# 🧠 RAG\n", encoding="utf-8")
    other = settings.brain / "01-PROJETOS" / "Outro Projeto"
    other.mkdir(parents=True)
    (other / "Outro Projeto.md").write_text("---\ntipo: projeto\nstatus: ativo\n---\n\n# Outro\n", encoding="utf-8")
    return Vault(settings.brain)


@pytest.fixture
def plans(vault, tmp_path):
    state = {"foco": LEGACY}
    study = StudyMap(vault, project=lambda: state["foco"], today=lambda: TODAY)
    store = StudyPlans(vault, study, get_focus=lambda: state["foco"], set_focus=lambda n: state.update(foco=n), versions=tmp_path / "versoes")
    store.state = state  # para o teste olhar o foco
    return store


def note_text(vault: Vault, name: str) -> str:
    return (vault.root / "01-PROJETOS" / name / f"{name}.md").read_text(encoding="utf-8")


# --- o plano de antes ------------------------------------------------------------------------


def test_legacy_plan_is_adopted_as_active_and_in_focus(plans, vault):
    items = plans.list()
    assert [p["nome"] for p in items] == [LEGACY]  # o "Outro Projeto" não é plano
    plan = items[0]
    assert plan["estado"] == "ativo" and plan["em_foco"] and plan["semanas"] == 3
    assert plan["semana_atual"]["numero"] == 2 and plan["semana_atual"]["foco"] == "FastAPI e REST"
    assert plan["conceitos"] == 1 and plan["inicio"] == "2026-09-21" and plan["fim"] == "2027-01-04"
    assert "projeto público" in plan["objetivo"]
    assert split_frontmatter(note_text(vault, LEGACY))[0]["plano_estudo"] == "ativo"


# --- criar -----------------------------------------------------------------------------------


def test_create_writes_the_plan_note_with_the_weeks_of_the_period(plans, vault):
    plan = plans.create("Inglês para entrevistas", "inglês técnico: oral", "2026-11-16", "2026-12-12", "Responder 10 perguntas\nsem travar")
    assert plan["estado"] == "ativo" and not plan["em_foco"]  # o foco continua no plano de antes
    assert plan["caminho"] == "01-PROJETOS/Inglês para entrevistas/Inglês para entrevistas.md"
    assert [(w["inicio"], w["fim"]) for w in plan["cronograma"]] == [
        ("2026-11-16", "2026-11-22"), ("2026-11-23", "2026-11-29"), ("2026-11-30", "2026-12-06"), ("2026-12-07", "2026-12-12"),
    ]  # fmt: skip
    text = note_text(vault, "Inglês para entrevistas")
    meta, body = split_frontmatter(text)
    assert meta["tipo"] == "projeto" and meta["plano_estudo"] == "ativo" and meta["tema"] == "inglês técnico: oral"
    assert meta["inicio"] == "2026-11-16" and meta["prazo"] == "2026-12-12"
    assert "> Responder 10 perguntas\n> sem travar" in body and "## 🗓️ Cronograma" in body
    assert "- Plano de estudos criado pela aba de Estudos da MÊTIS." in body
    assert body.index("## 🗓️ Cronograma") < body.index("## ✅ Próximas ações")
    # Dois planos ativos ao mesmo tempo.
    assert plans.active_names() == [LEGACY, "Inglês para entrevistas"]
    # O nome é o identificador: projeto ou nota com o mesmo título não pode.
    with pytest.raises(PlanError, match="já existe um projeto"):
        plans.create("Inglês para entrevistas", "", "2026-11-16", "2026-12-12")
    with pytest.raises(PlanError, match="já existe uma nota"):
        plans.create("rag", "", "2026-11-16", "2026-12-12")
    with pytest.raises(PlanError, match="fim do plano vem antes"):
        plans.create("Outro", "", "2026-12-16", "2026-12-12")
    with pytest.raises(PlanError, match="AAAA-MM-DD"):
        plans.create("Outro", "", "16/12/2026", "2026-12-20")


def test_create_without_a_valid_focus_takes_the_focus(plans):
    plans.state["foco"] = "Projeto Arquivado"
    plan = plans.create("Matemática", "", "2026-11-16", "2026-11-30")
    assert plans.state["foco"] == "Matemática" and plan["em_foco"]


def test_skeleton_and_week_validation():
    assert len(skeleton(date(2026, 1, 1), date(2026, 12, 31))) == 53
    weeks = clean_weeks([{"inicio": "2026-11-23", "fim": "2026-11-28", "foco": "B | C"}, {"inicio": "2026-11-16", "fim": "2026-11-21", "foco": "A\nlinha"}])
    assert [(w["numero"], w["foco"]) for w in weeks] == [(1, "A linha"), (2, "B / C")]
    with pytest.raises(PlanError, match="cruza"):
        clean_weeks([{"inicio": "2026-11-16", "fim": "2026-11-23"}, {"inicio": "2026-11-23", "fim": "2026-11-28"}])
    with pytest.raises(PlanError, match="termina antes"):
        clean_weeks([{"inicio": "2026-11-16", "fim": "2026-11-10"}])
    with pytest.raises(PlanError, match="AAAA-MM-DD"):
        clean_weeks([{"inicio": "amanhã"}])


# --- editar o cronograma ---------------------------------------------------------------------


def test_schedule_rewrite_keeps_unknown_columns_raw_cells_and_short_dates(plans, vault, tmp_path):
    weeks = plans.get(LEGACY)["cronograma"]
    # Tira a semana 2 e acrescenta uma no fim: a semana 3 vira a 2 e leva a "Origem" dela.
    new = [weeks[0], {**weeks[2]}, {"inicio": "2026-10-26", "fim": "2026-10-31", "foco": "PostgreSQL", "entrega": "Banco"}]
    plan = plans.write_schedule(LEGACY, new)
    assert [(w["numero"], w["foco"]) for w in plan["cronograma"]] == [(1, "Ativação + esqueleto"), (2, "Testes e CI"), (3, "PostgreSQL")]
    text = note_text(vault, LEGACY)
    assert "| **1** | 10-05 a 10-10 | Ativação + esqueleto | Repositório | Fusão |" in text  # negrito e data curta ficam
    assert "| 2 | 10-19 a 10-24 | Testes e CI | pytest | Semana 4 |" in text
    assert "| 3 | 10-26 a 10-31 | PostgreSQL | Banco |  |" in text
    assert "FastAPI e REST" not in text
    assert text.count("- Cronograma do plano atualizado pela aba de Estudos da MÊTIS (3 semanas).") == 1
    # A nota de antes ficou guardada fora do vault.
    saved = list((tmp_path / "versoes" / LEGACY).glob("*.md"))
    assert len(saved) == 1 and "FastAPI" in saved[0].read_text(encoding="utf-8")
    # Gravar de novo no mesmo dia não repete a linha do Log.
    plans.write_schedule(LEGACY, [*new[:2], {**new[2], "foco": "PostgreSQL e Docker"}])
    assert note_text(vault, LEGACY).count("- Cronograma do plano atualizado") == 1


def test_schedule_link_cells_stay_when_unchanged(plans, vault):
    weeks = plans.get(LEGACY)["cronograma"]
    plans.write_schedule(LEGACY, [*weeks[:2], {**weeks[2], "entrega": "pytest e Actions"}])
    text = note_text(vault, LEGACY)
    assert "| 2 | 10-12 a 10-17 | [[FastAPI]] e REST | CRUD de leads | Semana 3 |" in text
    assert "| 3 | 10-19 a 10-24 | Testes e CI | pytest e Actions | Semana 4 |" in text


def test_schedule_falls_back_to_full_dates_when_short_ones_would_read_wrong(plans, vault):
    weeks = plans.get(LEGACY)["cronograma"]
    # Uma semana do ano seguinte depois de um buraco de mais de um ano: a data curta não sabe.
    far = {"inicio": "2028-02-07", "fim": "2028-02-12", "foco": "Revisão", "entrega": ""}
    plan = plans.write_schedule(LEGACY, [*weeks, far])
    assert plan["cronograma"][-1]["inicio"] == "2028-02-07"
    assert "2028-02-07 a 2028-02-12" in note_text(vault, LEGACY)


def test_render_creates_the_section_when_the_note_has_no_table(plans):
    text = "---\ntipo: projeto\n---\n\n# X\n\n## ✅ Próximas ações\n\n## 📝 Log\n"
    new = render_schedule(text, [{"numero": 1, "inicio": "2026-11-16", "fim": "2026-11-21", "foco": "A", "entrega": "B"}], TODAY)
    assert "## 🗓️ Cronograma\n\n| Sem. | Datas | Foco | Entrega |\n|---|---|---|---|\n| 1 | 2026-11-16 a 2026-11-21 | A | B |\n\n## ✅ Próximas ações" in new
    assert parse_plan(new, TODAY)[0]["foco"] == "A"


def test_rows_that_are_not_weeks_survive_a_rewrite(plans, vault):
    path = vault.root / "01-PROJETOS" / LEGACY / f"{LEGACY}.md"
    path.write_text(path.read_text(encoding="utf-8").replace("| 3 | 10-19 a 10-24 | Testes e CI | pytest | Semana 4 |", "| 3 | 10-19 a 10-24 | Testes e CI | pytest | Semana 4 |\n| — | folga | Revisão livre |  |  |"), encoding="utf-8")
    weeks = plans.get(LEGACY)["cronograma"]
    plans.write_schedule(LEGACY, weeks[:2])
    text = note_text(vault, LEGACY)
    assert "Testes e CI" not in text and "| — | folga | Revisão livre |  |  |" in text


def test_empty_goal_and_long_goal(plans):
    plan = plans.create("Vazio", "", "2026-11-16", "2026-11-30")
    assert plan["objetivo"] == ""  # o "> [!todo] preencher" do modelo não conta
    long = "x" * 3000
    assert len(plans.update("Vazio", objetivo=long)["objetivo"]) == 3000
    # Editar outra coisa não corta o objetivo longo.
    assert len(plans.update("Vazio", tema="t")["objetivo"]) == 3000
    with pytest.raises(PlanError, match="2 anos"):
        plans.create("Longo", "", "2026-01-01", "2028-02-01")
    assert len(plans.create("Dois anos", "", "2026-01-01", "2027-12-31")["cronograma"]) == 105


def test_log_lines_go_under_the_day():
    text = "# X\n\n## 📝 Log\n\n### 2026-10-05\n- velho\n"
    once = add_log(text, "2026-11-16", "- novo")
    assert once.endswith("### 2026-10-05\n- velho\n\n### 2026-11-16\n- novo\n")
    assert add_log(once, "2026-11-16", "- novo") == once
    assert add_log(once, "2026-11-16", "- outro").endswith("### 2026-11-16\n- novo\n- outro\n")


# --- editar o plano, ativar, desativar -------------------------------------------------------


def test_update_theme_period_and_goal(plans, vault):
    plan = plans.update(LEGACY, tema="AI Engineer", fim="2027-02-01", objetivo="Novo objetivo")
    assert plan["tema"] == "AI Engineer" and plan["fim"] == "2027-02-01" and plan["objetivo"] == "Novo objetivo"
    text = note_text(vault, LEGACY)
    assert "> [!abstract] Objetivo\n> Novo objetivo\n\n## 🔁" in text
    assert "- Plano de estudos editado pela aba de Estudos da MÊTIS (período, tema, objetivo)." in text
    # Trocar o ano do início mudaria a leitura das datas curtas: a tabela passa à data cheia.
    plan = plans.update(LEGACY, inicio="2025-09-21")
    assert [w["inicio"] for w in plan["cronograma"]] == ["2026-10-05", "2026-10-12", "2026-10-19"]
    assert "| **1** | 2026-10-05 a 2026-10-10 |" in note_text(vault, LEGACY)
    with pytest.raises(PlanError, match="antes do início"):
        plans.update(LEGACY, fim="2025-01-01")


def test_deactivate_keeps_the_note_and_moves_the_focus(plans, vault):
    plans.create("Inglês", "", "2026-11-16", "2026-12-12")
    plan = plans.set_state(LEGACY, False)
    assert plan["estado"] == "inativo" and plans.state["foco"] == "Inglês"
    assert plans.active_names() == ["Inglês"] and [p["nome"] for p in plans.list()] == ["Inglês", LEGACY]
    text = note_text(vault, LEGACY)
    assert "plano_estudo: inativo" in text and "- Plano de estudos desativado pela aba de Estudos da MÊTIS." in text
    with pytest.raises(PlanError, match="desativado"):
        plans.set_focus(LEGACY)
    # Reativar volta, sem roubar o foco de quem está nele.
    assert plans.set_state(LEGACY, True)["estado"] == "ativo" and plans.state["foco"] == "Inglês"
    assert plans.set_focus("ai teste") == LEGACY and plans.state["foco"] == LEGACY


# --- excluir ---------------------------------------------------------------------------------


def test_archive_moves_the_folder_to_04_arquivo_and_never_deletes(plans, vault):
    plans.create("Inglês", "", "2026-11-16", "2026-12-12")
    result = plans.archive(LEGACY)
    assert result == {"nome": LEGACY, "de": f"01-PROJETOS/{LEGACY}", "para": f"04-ARQUIVO/{LEGACY}", "notas": 2, "conceitos": 1}
    assert not (vault.root / "01-PROJETOS" / LEGACY).exists()
    archived = vault.root / "04-ARQUIVO" / LEGACY / f"{LEGACY}.md"
    assert (vault.root / "04-ARQUIVO" / LEGACY / "conceitos" / "RAG.md").is_file()
    text = archived.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    assert meta["plano_estudo"] == "excluido" and meta["status"] == "arquivado" and meta["arquivado"] == TODAY.isoformat()
    assert body.lstrip().startswith(f"> [!warning] Arquivado em {TODAY.isoformat()}")
    assert "- Plano de estudos excluído pela aba de Estudos da MÊTIS: a pasta foi para 04-ARQUIVO." in body
    assert [p["nome"] for p in plans.list()] == ["Inglês"] and plans.state["foco"] == "Inglês"
    with pytest.raises(PlanError, match="não encontrado"):
        plans.archive(LEGACY)
    # Outro plano com o mesmo nome arquivado depois não passa por cima do primeiro.
    (vault.root / "04-ARQUIVO" / LEGACY / f"{LEGACY}.md").rename(vault.root / "04-ARQUIVO" / LEGACY / "antigo.md")
    plans.create(LEGACY, "", "2026-11-16", "2026-11-30")
    assert plans.archive(LEGACY)["para"] == f"04-ARQUIVO/{LEGACY} (arquivado {TODAY.isoformat()})"


# --- rotas -----------------------------------------------------------------------------------


def fake_argv(kind, settings):
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


@pytest.fixture
def core(settings, vault, accounts, monkeypatch, tmp_path):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    app.state.cli_homes = {"claude": tmp_path / "homes" / "claude", "codex": tmp_path / "homes" / "codex"}
    app.state.manager.prefs.update({"estudo_projeto": LEGACY})
    app.state.study_map._today = lambda: TODAY
    with TestClient(app) as client:
        yield client, app
        for session_id in list(app.state.manager.sessions):
            client.delete(f"/sessions/{session_id}", headers=AUTH)


def test_routes_create_edit_state_schedule_focus_and_delete(core, vault):
    client, app = core
    listing = client.get("/estudo/planos", headers=AUTH).json()
    assert listing["foco"] == LEGACY and [p["nome"] for p in listing["planos"]] == [LEGACY]
    body = {"nome": "Inglês", "tema": "oral", "inicio": "2026-11-16", "fim": "2026-11-28", "objetivo": "Falar"}
    created = client.post("/estudo/planos", json=body, headers=AUTH)
    assert created.status_code == 201 and len(created.json()["cronograma"]) == 2
    assert client.post("/estudo/planos", json=body, headers=AUTH).status_code == 409
    assert client.post("/estudo/planos", json={**body, "nome": "X", "fim": "2026-11-01"}, headers=AUTH).status_code == 400
    assert client.get("/estudo/planos/Nada", headers=AUTH).status_code == 404
    patched = client.patch("/estudo/planos/Inglês", json={"tema": "inglês oral"}, headers=AUTH).json()
    assert patched["tema"] == "inglês oral"
    weeks = [{"inicio": "2026-11-16", "fim": "2026-11-21", "foco": "Apresentação", "entrega": "Vídeo de 1 min"}]
    scheduled = client.put("/estudo/planos/Inglês/cronograma", json={"semanas": weeks}, headers=AUTH)
    assert scheduled.status_code == 200 and scheduled.json()["cronograma"][0]["foco"] == "Apresentação"
    bad = client.put("/estudo/planos/Inglês/cronograma", json={"semanas": [{"inicio": "2026-11-16", "fim": "2026-11-01"}]}, headers=AUTH)
    assert bad.status_code == 400
    # Dois ativos: o resumo do Estudo mostra os dois e o em foco.
    summary = client.get("/estudo", headers=AUTH).json()
    assert summary["foco"] == LEGACY and [p["nome"] for p in summary["planos"]] == [LEGACY, "Inglês"]
    assert summary["semana_atual"] == {"numero": 2, "foco": "FastAPI e REST"}
    assert client.put("/estudo/foco", json={"plano": "Inglês"}, headers=AUTH).json() == {"foco": "Inglês"}
    assert app.state.manager.prefs.get()["estudo_projeto"] == "Inglês"
    assert client.get("/estudo/mapa", headers=AUTH).json()["projeto"] == "Inglês"
    assert client.get("/estudo/plano", params={"plano": LEGACY}, headers=AUTH).json()["projeto"] == LEGACY
    # Desativar o em foco devolve o foco ao outro ativo.
    off = client.put("/estudo/planos/Inglês/estado", json={"ativo": False}, headers=AUTH).json()
    assert off["estado"] == "inativo" and app.state.manager.prefs.get()["estudo_projeto"] == LEGACY
    assert client.put("/estudo/foco", json={"plano": "Inglês"}, headers=AUTH).status_code == 400
    # Excluir: só pela janela.
    refused = client.delete("/estudo/planos/Inglês", headers={**AUTH, "X-Harness-Session": "s1"})
    assert refused.status_code == 403
    gone = client.delete("/estudo/planos/Inglês", headers=AUTH)
    assert gone.status_code == 200 and gone.json()["para"] == "04-ARQUIVO/Inglês"
    assert [p["nome"] for p in client.get("/estudo/planos", headers=AUTH).json()["planos"]] == [LEGACY]
    assert (vault.root / "04-ARQUIVO" / "Inglês" / "Inglês.md").is_file()


def test_pomodoro_block_goes_to_the_plan(core, vault):
    client, _app = core
    client.post("/estudo/planos", json={"nome": "Inglês", "inicio": "2026-11-16", "fim": "2026-11-28"}, headers=AUTH)
    block = client.post("/estudo/blocos", json={"minutos": 25, "assunto": "pronúncia", "plano": "inglês"}, headers=AUTH).json()
    assert block["plano"] == "Inglês" and block["line"].endswith("· pronúncia · [[Inglês]]")
    daily = (vault.root / block["note"]).read_text(encoding="utf-8")
    assert "· pronúncia · [[Inglês]]" in daily
    # Sem plano, vai para o plano em foco.
    assert client.post("/estudo/blocos", json={"minutos": 10, "assunto": ""}, headers=AUTH).json()["plano"] == LEGACY
    planos = {p["nome"]: p for p in client.get("/estudo/planos", headers=AUTH).json()["planos"]}
    assert planos["Inglês"]["minutos_semana"] == 25 and planos[LEGACY]["minutos_semana"] == 10


def test_planning_session_and_session_plan(core):
    client, app = core
    client.post("/estudo/planos", json={"nome": "Inglês", "tema": "oral", "inicio": "2026-11-16", "fim": "2026-11-28"}, headers=AUTH)
    client.post("/agents", json={"name": "Platao", "cli": "claude"}, headers=AUTH)
    client.put("/estudo/agente", json={"id": "platao"}, headers=AUTH)
    r = client.post("/estudo/sessao", json={"tipo": "planejar", "plano": "Inglês"}, headers=AUTH)
    assert r.status_code == 201, r.text
    session = r.json()
    prompt = app.state.manager.get(session["id"]).pty.argv[1]
    assert session["title"] == "Estudo · planejar Inglês"
    assert "Montar o cronograma do plano de estudos «Inglês»" in prompt and "tema: oral" in prompt and "2026-11-16 a 2026-11-28" in prompt
    assert "estudo_cronograma" in prompt and "Não grave sem a minha aprovação" in prompt
    # A central sabe de qual plano é a sessão.
    token = next(t for t, s in app.state.hub.tokens.items() if s == session["id"]) if app.state.hub.tokens else None
    info = app.state.hub.session_info(session["id"])
    assert info["plano"] == "Inglês" and (token is None or app.state.hub.context(token).plano == "Inglês")
    # Uma sessão comum (no plano em foco) conta os outros planos ativos.
    aprender = client.post("/estudo/sessao", json={"tipo": "aprender", "conceito": "RAG"}, headers=AUTH).json()
    argv = app.state.manager.get(aprender["id"]).pty.argv
    system = argv[argv.index("--append-system-prompt") + 1]
    assert f"Esta sessão é do plano de estudos «{LEGACY}»" in system and "Outros planos ativos: «Inglês»" in system
    assert "Esta sessão é do plano" not in argv[1]  # o pedido fica curto
    assert client.post("/estudo/sessao", json={"tipo": "medir", "plano": "Nada"}, headers=AUTH).status_code == 404


def test_without_any_active_plan_only_the_free_chat_opens(core):
    client, app = core
    client.put(f"/estudo/planos/{LEGACY}/estado", json={"ativo": False}, headers=AUTH)
    client.post("/agents", json={"name": "Platao", "cli": "claude"}, headers=AUTH)
    client.put("/estudo/agente", json={"id": "platao"}, headers=AUTH)
    summary = client.get("/estudo", headers=AUTH).json()
    assert summary["foco"] == "" and summary["planos"] == [] and summary["semana_atual"] is None
    assert client.get("/estudo/mapa", headers=AUTH).status_code == 404
    assert client.post("/estudo/sessao", json={"tipo": "medir"}, headers=AUTH).status_code == 404
    chat = client.post("/estudo/sessao", json={"tipo": "conversa"}, headers=AUTH)
    assert chat.status_code == 201 and "Estudo livre" in app.state.manager.get(chat.json()["id"]).pty.argv[1]


# --- ferramentas do agente -------------------------------------------------------------------


def test_central_tools_take_the_plan(core, vault):
    client, app = core
    client.post("/estudo/planos", json={"nome": "Inglês", "inicio": "2026-11-16", "fim": "2026-11-28"}, headers=AUTH)
    hub = app.state.hub
    events = []
    hub.publish = events.append
    ctx = Context(session="s1", who="Platão", cwd=None, allowed=None, plano="Inglês")
    tool = {t.name: t for t in hub.tools_for(ctx)}
    assert "estudo_cronograma" in tool
    # Sem plano dito: o da sessão.
    assert "Registrado em Inglês" in tool["estudo_registrar"].run({"conceito": "Phrasal verbs", "acertou": True, "confianca": 3}, ctx)
    assert (vault.root / "01-PROJETOS" / "Inglês" / "conceitos" / "Phrasal verbs.md").is_file()
    # Com plano dito: aquele.
    assert "Conceito criado" in tool["estudo_conceito_novo"].run({"nome": "Embeddings", "plano": "ai teste"}, ctx)
    assert (vault.root / "01-PROJETOS" / LEGACY / "conceitos" / "Embeddings.md").is_file()
    with pytest.raises(StudyError, match="não encontrado"):
        tool["estudo_conceitos"].run({"plano": "Nada"}, ctx)
    # O cronograma montado com o agente.
    weeks = [{"inicio": "2026-11-16", "fim": "2026-11-21", "foco": "Apresentação", "entrega": "Vídeo"},
             {"inicio": "2026-11-23", "fim": "2026-11-28", "foco": "Entrevista", "entrega": "Simulação"}]  # fmt: skip
    said = tool["estudo_cronograma"].run({"plano": "Inglês", "semanas": weeks}, ctx)
    assert "2 semana(s)" in said and {"type": "estudo.mudou"} in events
    text = (vault.root / "01-PROJETOS" / "Inglês" / "Inglês.md").read_text(encoding="utf-8")
    assert "| 2 | 2026-11-23 a 2026-11-28 | Entrevista | Simulação |" in text
    assert "- Cronograma do plano atualizado por Platão, o agente de estudo (2 semanas)." in text
    listing = tool["estudo_plano"].run({}, ctx)
    assert listing.startswith("Plano de estudos «Inglês»") and "Entrevista" in listing and f"«{LEGACY}»" in listing.split("Outros planos:")[1]
    # Sessão de fora do Estudo (sem plano): o plano em foco.
    plain = Context(session="s2", who="x", cwd=None, allowed=None)
    assert f"em {LEGACY}" in tool["estudo_conceitos"].run({}, plain)


def test_central_tools_hidden_without_any_plan(core):
    client, app = core
    client.delete(f"/estudo/planos/{LEGACY}", headers=AUTH)
    ctx = Context(session="s1", who="x", cwd=None, allowed=None)
    assert not any(t.name.startswith("estudo_") for t in app.state.hub.tools_for(ctx))
