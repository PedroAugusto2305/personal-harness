"""v0.9.8 parte 5: Estudo completo (mapa de conceitos, plano, sessões com o Sócrates e as
ferramentas estudo_* da central)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.mcp_hub import Context
from harness_core.study_map import StudyError, StudyMap, parse_plan, schedule
from harness_core.vault import Vault, split_frontmatter

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
PROJECT = "Estudo Teste"
TODAY = date(2026, 10, 14)  # quarta da semana 2

NOTE = """---
tipo: projeto
status: ativo
inicio: 2026-10-05
diretorio: {diretorio}
---

# 🎯 Estudo Teste

## 📊 Status

| Campo | Valor |
|---|---|
| Fase | Semana 2 |

## Cronograma

| Sem. | Datas | Foco | Entrega demonstrável | Origem |
|---|---|---|---|---|
| **1** | 10-05 a 10-10 | Ativação + esqueleto | Repositório | x |
| 2 | 10-12 a 10-17 | FastAPI e REST | CRUD de leads | y |
| 3 | 12-28 a 01-02 | [[RAG]] básico | Busca | z |
| 4 | 01-04 a 01-09 | Agentes | Demo | w |
"""


@pytest.fixture
def vault(settings, tmp_path) -> Vault:
    root = settings.brain
    folder = root / "01-PROJETOS" / PROJECT
    folder.mkdir(parents=True)
    repo = tmp_path / "repo-estudo"
    repo.mkdir()
    (folder / f"{PROJECT}.md").write_text(NOTE.format(diretorio=repo), encoding="utf-8")
    return Vault(root)


@pytest.fixture
def study(vault) -> StudyMap:
    return StudyMap(vault, project=lambda: PROJECT, today=lambda: TODAY)


def fake_argv(kind, settings):
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


@pytest.fixture
def core(settings, vault, accounts, monkeypatch, tmp_path):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    app.state.cli_homes = {"claude": tmp_path / "homes" / "claude", "codex": tmp_path / "homes" / "codex"}
    app.state.manager.prefs.update({"estudo_projeto": PROJECT})
    app.state.study_map._today = lambda: TODAY
    with TestClient(app) as client:
        yield client, app
        for session_id in list(app.state.manager.sessions):
            client.delete(f"/sessions/{session_id}", headers=AUTH)


# --- conceitos e a revisão espaçada ----------------------------------------------------------


def test_create_links_both_ways_and_note_format(study, vault):
    first = study.create("Embeddings", "Vetores que guardam o sentido do texto.", ["RAG"], week=3)
    assert first.dominio == 0 and first.semana == 3 and first.relacionados == ["RAG"]
    path = vault.root / "01-PROJETOS" / PROJECT / "conceitos" / "Embeddings.md"
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    assert meta["tipo"] == "conceito" and meta["projeto"] == f"[[{PROJECT}]]" and meta["criado"] == "2026-10-14"
    assert "# 🧠 Embeddings" in body and "Vetores que guardam" in body and "## Histórico" in body
    # O outro conceito nasce depois e a ligação passa a valer dos dois lados.
    study.create("RAG", related=["Embeddings"])
    assert study.get("Embeddings").relacionados == ["RAG"]
    assert study.get("rag").relacionados == ["Embeddings"]  # acha sem diferenciar maiúscula
    with pytest.raises(StudyError, match="já existe"):
        study.create("embeddings")
    with pytest.raises(StudyError):
        study.create("   ")
    assert study.create("A/B: teste?").titulo == "A B teste"  # sem caractere proibido no título


def test_record_intervals_domain_calibration_and_history(study, vault):
    study.create("Pydantic")
    path = vault.root / "01-PROJETOS" / PROJECT / "conceitos" / "Pydantic.md"
    # O Pedro escreveu algo no corpo pelo Obsidian: tem de continuar lá.
    path.write_text(path.read_text(encoding="utf-8").replace("## Relacionados", "Anotação do Pedro.\n\n## Relacionados"), encoding="utf-8")

    c = study.record("Pydantic", True, 5, "acertou de primeira")
    assert (c.dominio, c.intervalo_dias, c.proxima_revisao, c.acertos, c.calibracao) == (1, 1, "2026-10-15", 1, 0.0)
    c = study.record("Pydantic", True, 5)
    assert c.intervalo_dias == 3  # 1 × 2,5 arredondado para cima
    c = study.record("Pydantic", True, 3)
    assert c.intervalo_dias == 5 and c.dominio == 2  # × 1,5; 3 acertos seguidos sobem o domínio
    c = study.record("Pydantic", False, 4)
    assert c.intervalo_dias == 1 and c.dominio == 2 and c.proxima_revisao == "2026-10-15"
    c = study.record("Pydantic", False, 2)
    assert c.dominio == 1  # 2 erros seguidos descem
    assert (c.acertos, c.erros) == (3, 2)
    # Calibração: |conf normalizada − acerto| em média: 0, 0, 0,5, 0,75, 0,25 → 0,3.
    assert c.calibracao == pytest.approx(0.3)
    assert c.confianca_media == pytest.approx(3.8)
    text = path.read_text(encoding="utf-8")
    assert "Anotação do Pedro." in text
    history = [line for line in text.splitlines() if line.startswith("- 2026-10-14 ·")]
    assert len(history) == 5 and history[0].endswith("confiança 5 · acertou de primeira") and "errou" in history[-1]
    with pytest.raises(StudyError, match="1 a 5"):
        study.record("Pydantic", True, 7)


def test_record_creates_missing_concept_with_domain_one(study):
    c = study.record("Context window", False, 2)
    assert c.dominio == 1 and c.erros == 1 and c.intervalo_dias == 1


def test_interval_ceiling_and_domain_bounds():
    from harness_core.study_map import Concept

    c = Concept(titulo="x", caminho="x.md", dominio=4, intervalo_dias=50, acertos=5, sequencia=2)
    schedule(c, True, 5, TODAY)
    assert c.intervalo_dias == 60 and c.dominio == 4  # teto de 60 dias; domínio não passa de 4
    c = Concept(titulo="y", caminho="y.md", dominio=1, intervalo_dias=4, erros=3, sequencia=-1)
    schedule(c, False, 1, TODAY)
    assert c.dominio == 1  # não desce abaixo de 1


def test_update_domain_and_week(study):
    study.create("SQL")
    assert study.update("SQL", dominio=3, semana=2).dominio == 3
    assert study.get("SQL").semana == 2
    assert study.update("SQL", semana=None).semana is None
    with pytest.raises(StudyError):
        study.update("SQL", dominio=9)
    with pytest.raises(StudyError, match="não encontrado"):
        study.update("Nada")


# --- plano ----------------------------------------------------------------------------------


def test_plan_short_dates_year_turn_and_current_week(study):
    plan = study.plan()
    weeks = plan["semanas"]
    assert [w["numero"] for w in weeks] == [1, 2, 3, 4]  # a tabela de Status (antes) não conta
    assert (weeks[0]["inicio"], weeks[0]["fim"]) == ("2026-10-05", "2026-10-10")
    assert (weeks[2]["inicio"], weeks[2]["fim"]) == ("2026-12-28", "2027-01-02")  # vira o ano no meio
    assert (weeks[3]["inicio"], weeks[3]["fim"]) == ("2027-01-04", "2027-01-09")
    assert weeks[2]["foco"] == "RAG básico" and weeks[1]["entrega"] == "CRUD de leads"
    assert plan["semana_atual"] == 2 and weeks[1]["atual"] and plan["hoje"] == "2026-10-14"


def test_plan_full_dates_and_sunday_belongs_to_previous_week():
    text = "---\ninicio: 2026-10-05\n---\n\n| Semana | Datas | Foco | Entrega |\n|---|---|---|---|\n| 1 | 2026-10-05 a 2026-10-10 | A | a |\n| 2 | 2026-10-12 a 2026-10-17 | B | b |\n"
    weeks = parse_plan(text, date(2026, 10, 11))  # domingo entre as duas
    assert [w["atual"] for w in weeks] == [True, False]
    assert all(not w["atual"] for w in parse_plan(text, date(2026, 10, 20)))  # depois do fim
    assert parse_plan("sem tabela nenhuma", date(2026, 10, 11)) == []


def test_map_summary(study):
    study.create("A", week=2)
    study.record("B", True, 4)
    study.record("C", False, 5)
    study._today = lambda: date(2026, 10, 15)  # amanhã: B e C vencem
    data = study.map()
    assert data["projeto"] == PROJECT and data["resumo"]["total"] == 3
    assert data["resumo"]["por_dominio"] == {"0": 1, "1": 2, "2": 0, "3": 0, "4": 0}
    assert data["resumo"]["vencidos"] == 2
    assert data["resumo"]["calibracao_media"] == pytest.approx((0.25 + 1.0) / 2, abs=1e-3)
    a = next(c for c in data["conceitos"] if c["titulo"] == "A")
    assert a["vencido"] is False and a["semana"] == 2 and "sequencia" not in a


def test_missing_project_is_a_clear_error(vault):
    other = StudyMap(vault, project=lambda: "Projeto Que Não Existe", today=lambda: TODAY)
    with pytest.raises(StudyError, match="não está no Brain"):
        other.map()
    assert other.due_count() == 0 and other.current() is None


# --- rotas -----------------------------------------------------------------------------------


def test_routes_map_plan_concepts_and_summary(core):
    client, _app = core
    created = client.post("/estudo/conceitos", json={"nome": "FastAPI", "resumo": "Framework web.", "relacionados": ["Pydantic"], "semana": 2}, headers=AUTH)
    assert created.status_code == 201 and created.json()["titulo"] == "FastAPI"
    assert client.post("/estudo/conceitos", json={"nome": "fastapi"}, headers=AUTH).status_code == 409
    patched = client.patch("/estudo/conceitos", json={"titulo": "FastAPI", "dominio": 2}, headers=AUTH)
    assert patched.status_code == 200 and patched.json()["dominio"] == 2 and patched.json()["semana"] == 2  # semana fica
    assert client.patch("/estudo/conceitos", json={"titulo": "Nada"}, headers=AUTH).status_code == 404
    data = client.get("/estudo/mapa", headers=AUTH).json()
    assert data["resumo"]["total"] == 1 and data["conceitos"][0]["relacionados"] == ["Pydantic"]
    plan = client.get("/estudo/plano", headers=AUTH).json()
    assert plan["semana_atual"] == 2 and len(plan["semanas"]) == 4
    summary = client.get("/estudo", headers=AUTH).json()
    assert summary["semana_atual"] == {"numero": 2, "foco": "FastAPI e REST"} and summary["vencidos"] == 0
    assert "week" in summary and "streak" in summary  # o resumo de antes continua


def test_session_prompts_by_type_and_missing_tutor(core, vault):
    client, app = core
    refused = client.post("/estudo/sessao", json={"tipo": "medir"}, headers=AUTH)
    assert refused.status_code == 400 and "Sócrates" in refused.json()["detail"]
    agent = client.post("/agents", json={"name": "Socrates", "cli": "claude"}, headers=AUTH).json()
    assert agent["id"] == "socrates"
    assert client.post("/estudo/sessao", json={"tipo": "dancar"}, headers=AUTH).status_code == 400
    prompts = {}
    for kind in ("medir", "aprender", "praticar", "revisar"):
        r = client.post("/estudo/sessao", json={"tipo": kind, "conceito": "Pydantic" if kind == "aprender" else None}, headers=AUTH)
        assert r.status_code == 201, r.text
        session = r.json()
        argv = app.state.manager.get(session["id"]).pty.argv
        prompts[kind] = argv[1]
        assert session["title"].startswith("Estudo ·")
        if kind == "praticar":
            note = (vault.root / "01-PROJETOS" / PROJECT / f"{PROJECT}.md").read_text(encoding="utf-8")
            assert session["cwd"] in note  # no repositório do projeto (o `diretorio` da nota)
    assert "previsão" in prompts["medir"] and "estudo_registrar" in prompts["medir"] and "estudo_conceito_novo" in prompts["medir"]
    assert "Pydantic" in prompts["aprender"] and "FastAPI e REST" in prompts["aprender"]
    assert "exercício" in prompts["praticar"]
    assert "vencidos" in prompts["revisar"]


# --- ferramentas da central ------------------------------------------------------------------


def test_central_tools(core):
    _client, app = core
    hub = app.state.hub
    events = []
    hub.publish = events.append
    ctx = Context(session="s1", who="Sócrates", cwd=None, allowed=None)
    names = {t.name for t in hub.tools_for(ctx)}
    assert {"estudo_plano", "estudo_conceitos", "estudo_registrar", "estudo_conceito_novo"} <= names
    tool = {t.name: t for t in hub.tools_for(ctx)}
    assert "semana 2" in tool["estudo_plano"].run({}, ctx) and "FastAPI e REST" in tool["estudo_plano"].run({}, ctx)
    assert "criado" in tool["estudo_conceito_novo"].run({"nome": "Embeddings", "relacionados": ["RAG"]}, ctx).lower()
    assert "Já existia" in tool["estudo_conceito_novo"].run({"nome": "embeddings"}, ctx)
    text = tool["estudo_registrar"].run({"conceito": "Embeddings", "acertou": True, "confianca": 4, "nota": "explicou bem"}, ctx)
    assert "Registrado" in text and "domínio 1" in text
    assert events and all(e == {"type": "estudo.mudou"} for e in events)
    listing = tool["estudo_conceitos"].run({}, ctx)
    assert "Embeddings" in listing and "1 acertos" in listing
    assert "Nenhum conceito" in tool["estudo_conceitos"].run({"vencidos": True}, ctx)
    with pytest.raises(StudyError):
        tool["estudo_registrar"].run({"conceito": "Embeddings", "acertou": True, "confianca": 0}, ctx)


def test_central_tools_hidden_without_study_project(core):
    _client, app = core
    app.state.manager.prefs.update({"estudo_projeto": "Outro Projeto"})
    ctx = Context(session="s1", who="x", cwd=None, allowed=None)
    assert not any(t.name.startswith("estudo_") for t in app.state.hub.tools_for(ctx))


def test_prefs_validate_study_project(core):
    client, _app = core
    assert client.put("/ajustes", json={"estudo_projeto": "  "}, headers=AUTH).status_code == 400
    assert client.put("/ajustes", json={"estudo_projeto": PROJECT}, headers=AUTH).json()["estudo_projeto"] == PROJECT
