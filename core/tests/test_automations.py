"""v0.9.0: automações (arquivo e versões, expressões, regra, motor com ensaio, aprovação,
agente pela `saida`, reexecutar daqui e agendador)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from harness_core.app import create_app
from harness_core.automations import AutomationError, AutomationStore, evaluate_rule, layers, make_scope, render, validate
from harness_core.keychain import MemoryVault
from harness_core.mcp_hub import Context

from .conftest import TOKEN
from .test_connectors import FakeServices

AUTH = {"X-Harness-Token": TOKEN}


def flow(**extra) -> dict:
    base = {
        "nome": "Briefing da manhã",
        "gatilho": {"tipo": "manual", "x": 0, "y": 0},
        "passos": [
            {"id": "tarefas", "tipo": "ferramenta", "titulo": "Tarefas do Alfa", "ferramenta": "tarefas", "argumentos": {"projeto": "Alfa"}, "x": 200, "y": 0},
            {"id": "tem", "tipo": "condicao", "titulo": "Tem a primeira?", "regra": "contem({{Tarefas do Alfa.texto}}, 'Primeira') e não vazio({{hoje}})", "x": 400, "y": 0},
            {"id": "canal", "tipo": "ferramenta", "titulo": "Avisar o canal", "ferramenta": "slack-pessoal__mensagem_no_canal",
             "argumentos": {"canal": "#time", "texto": "Bom dia! {{Tarefas do Alfa.texto}}"}, "x": 600, "y": -80},
            {"id": "diario", "tipo": "brain", "titulo": "Linha no diário", "acao": "diario", "texto": "nada hoje", "x": 600, "y": 80},
        ],
        "ligacoes": [
            {"de": "gatilho", "para": "tarefas"},
            {"de": "tarefas", "para": "tem"},
            {"de": "tem", "para": "canal", "ramo": "sim"},
            {"de": "tem", "para": "diario", "ramo": "não"},
        ],
        "notas": [{"id": "n1", "titulo": "Por quê", "texto": "teste", "x": 0, "y": 200, "w": 200}],
    }
    base.update(extra)
    return base


# --- desenho, expressões e regra ---------------------------------------------------------------


def test_validate_normalizes_and_refuses_bad_drawings():
    data = validate(flow())
    assert data["ligacoes"][2] == {"de": "tem", "para": "canal", "ramo": "sim"}
    assert [len(layer) for layer in layers(data)] == [1, 1, 1, 2]
    bad = flow()
    bad["ligacoes"][2] = {"de": "tem", "para": "canal"}
    with pytest.raises(AutomationError, match="ramo"):
        validate(bad)
    loop = flow()
    loop["ligacoes"].append({"de": "canal", "para": "tarefas"})
    with pytest.raises(AutomationError, match="ciclo"):
        validate(loop)
    twins = flow()
    twins["passos"][3]["titulo"] = "tarefas do alfa"
    with pytest.raises(AutomationError, match="mesmo nome"):
        validate(twins)
    with pytest.raises(AutomationError, match="hora"):
        validate(flow(gatilho={"tipo": "agendado", "dias": [0]}))


def test_draft_accepts_half_done_steps_but_running_does_not(core):
    client = core.client
    data = flow()
    data["passos"].append({"id": "novo", "tipo": "agente", "titulo": "Escrever", "x": 800, "y": 0})
    data["ligacoes"].append({"de": "canal", "para": "novo"})
    automation_id = client.post("/automacoes", json={"nome": "Pela metade", "desenho": data}, headers=AUTH).json()["id"]
    data["passos"][0]["x"] = 260  # mover um bloco salva, mesmo com o agente ainda sem pedido
    assert client.put(f"/automacoes/{automation_id}", json={"desenho": data}, headers=AUTH).status_code == 200
    refused = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH)
    assert refused.status_code == 400 and refused.json()["detail"] == "o passo Escrever precisa do pedido ao agente"
    assert client.post(f"/automacoes/{automation_id}/publicar", json={}, headers=AUTH).status_code == 400
    assert client.get("/automacoes", headers=AUTH).json()[0]["alterado"] > 0


def test_render_by_step_name_with_accents_and_paths():
    data = validate(flow())
    scope = make_scope(data, {"tarefas": {"texto": "- Primeira", "itens": [{"nome": "Café"}]}, "tem": {"ramo": "sim"}}, now=datetime(2026, 11, 9, 7, 30).astimezone())
    assert render("{{Tarefas do Alfa.itens}}", scope) == [{"nome": "Café"}]
    assert render("Hoje {{hoje}}: {{tarefas do alfa.itens[0].nome}} ({{Tem a primeira?.ramo}})", scope) == "Hoje 2026-11-09: Café (sim)"
    assert render({"a": ["{{Tarefas do Alfa.itens.length}}"]}, scope) == {"a": [1]}
    assert render("{{Passo que não existe.x}}!", scope) == "!"


def test_rule_language():
    scope = {"tarefas": {"total": 3, "nomes": ["a", "b"], "texto": "pão e café"}}
    assert evaluate_rule("{{tarefas.total}} > 2 e len({{tarefas.nomes}}) == 2", scope)
    assert not evaluate_rule("{{tarefas.total}} > 5 ou vazio({{tarefas.nomes}})", scope)
    assert evaluate_rule("contem({{tarefas.texto}}, 'pão e café')", scope)  # o "e" dentro do texto não vira and
    assert evaluate_rule("não ({{tarefas.total}} == 0)", scope)
    with pytest.raises(AutomationError):
        evaluate_rule("__import__('os').system('true')", scope)


def test_store_drafts_versions_and_archive(tmp_path):
    store = AutomationStore(tmp_path)
    automation_id = store.create("Briefing da manhã", flow())
    assert automation_id == "briefing-da-manha" and store.published(automation_id) is None
    assert store.publish(automation_id) == 1
    changed = flow()
    changed["passos"][3]["texto"] = "outra coisa"
    store.save(automation_id, changed)
    assert store.published(automation_id)["passos"][3]["texto"] == "nada hoje"  # editar só mexe no rascunho
    assert "+  texto: outra coisa" in store.diff(automation_id)
    assert store.publish(automation_id) == 2
    versions = store.versions(automation_id)
    assert [v["number"] for v in versions] == [2, 1]
    old = store.version_content(automation_id, versions[1]["hash"])
    assert store.publish(automation_id, old) == 3 and store.published(automation_id)["passos"][3]["texto"] == "nada hoje"
    assert store.create("Briefing da manhã") == "briefing-da-manha-2"
    store.archive(automation_id)
    assert automation_id not in store.ids() and (tmp_path / "automacoes" / "arquivadas" / f"{automation_id}.yaml").exists()


# --- motor --------------------------------------------------------------------------------------------


@pytest.fixture
def brain(settings) -> Path:
    alfa = settings.brain / "01-PROJETOS" / "Alfa"
    alfa.mkdir(parents=True)
    (alfa / "Alfa.md").write_text("---\ntipo: projeto\n---\n\n## ✅ Próximas ações\n\n- [ ] Primeira coisa\n", encoding="utf-8")
    (settings.brain / "_templates").mkdir()
    (settings.brain / "_templates" / "T-daily.md").write_text("---\ntipo: daily\n---\n\n# {{date:YYYY-MM-DD}}\n\n## 🛠️ Registro de trabalho\n\n- \n", encoding="utf-8")
    return settings.brain


@pytest.fixture
def core(settings, accounts, brain):
    fake = FakeServices()
    http = lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))  # noqa: E731
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, keychain=MemoryVault(), http=http, run_scheduler=False)
    with TestClient(app) as client:
        client.post("/conectores/slack", json={"name": "Slack pessoal", "token": "xoxb-bom", "email": "p@e.com"}, headers=AUTH)
        yield SimpleNamespace(client=client, app=app, fake=fake)


def wait_run(client: TestClient, run_id: int, until=lambda run: run["status"] not in ("rodando",), timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/execucoes/{run_id}", headers=AUTH).json()
        if until(run):
            return run
        time.sleep(0.05)
    raise AssertionError(f"execução {run_id} não terminou: {run}")


def test_test_run_uses_draft_with_rehearsal_then_production_asks_approval(core):
    client, fake = core.client, core.fake
    created = client.post("/automacoes", json={"nome": "Briefing da manhã", "desenho": flow()}, headers=AUTH).json()
    automation_id = created["id"]
    assert created["publicada"] is None and created["conectores"] == ["slack-pessoal", "brain"]
    catalog = client.get("/automacoes/catalogo", headers=AUTH).json()
    tools = {t["nome"]: t for t in catalog["ferramentas"]}
    assert tools["slack-pessoal__mensagem_no_canal"]["pessoas"] and not tools["tarefas"]["pessoas"]

    run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
    run = wait_run(client, run_id)
    steps = run["steps"]
    assert run["status"] == "ok" and run["mode"] == "teste" and run["versao"] == "rascunho"
    assert steps["tarefas"]["status"] == "ok" and "Primeira coisa" in steps["tarefas"]["saida"]["texto"]
    assert steps["tem"]["saida"]["ramo"] == "sim"
    assert steps["canal"]["saida"]["ensaio"] is True and steps["canal"]["nota"].startswith("ensaio")
    assert steps["diario"]["status"] == "pulado"
    sent = [form for method, form in fake.calls if method == "chat.postMessage"]
    assert sent[-1]["channel"] == "D42" and "Ensaio" in sent[-1]["text"]  # foi para a DM do Pedro, não para #time

    assert client.post(f"/automacoes/{automation_id}/rodar", headers=AUTH).status_code == 400  # sem publicar não roda
    assert client.put(f"/automacoes/{automation_id}/ativa", json={"ativa": True}, headers=AUTH).status_code == 400
    assert client.post(f"/automacoes/{automation_id}/publicar", json={}, headers=AUTH).json()["publicada"] == 1
    run_id = client.post(f"/automacoes/{automation_id}/rodar", headers=AUTH).json()["execucao"]
    pending = wait_run(client, run_id, until=lambda r: r["steps"].get("canal", {}).get("status") == "esperando")
    assert pending["mode"] == "producao"
    for _ in range(100):
        approvals = client.get("/aprovacoes", headers=AUTH).json()
        if approvals:
            break
        time.sleep(0.05)
    assert approvals[0]["tool"] == "slack-pessoal__mensagem_no_canal"
    client.post(f"/aprovacoes/{approvals[0]['id']}", json={"aprovar": True}, headers=AUTH)
    run = wait_run(client, run_id)
    assert run["status"] == "ok" and run["versao"] == "v1"
    assert any(method == "chat.postMessage" and form["channel"] == "#time" for method, form in fake.calls)

    listing = client.get("/automacoes", headers=AUTH).json()
    assert listing[0]["ultima"]["status"] == "ok" and listing[0]["mudou"] is False


def test_approval_step_refused_stops_the_branch_and_rerun_from_a_step(core):
    client = core.client
    data = flow()
    data["passos"].insert(1, {"id": "ok", "tipo": "aprovacao", "titulo": "Posso seguir?", "mensagem": "Vou olhar {{Tarefas do Alfa.texto}}", "x": 300, "y": 0})
    data["ligacoes"] = [
        {"de": "gatilho", "para": "tarefas"}, {"de": "tarefas", "para": "ok"}, {"de": "ok", "para": "tem"},
        {"de": "tem", "para": "canal", "ramo": "sim"}, {"de": "tem", "para": "diario", "ramo": "não"},
    ]  # fmt: skip
    automation_id = client.post("/automacoes", json={"nome": "Com aprovação", "desenho": data}, headers=AUTH).json()["id"]
    run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
    wait_run(client, run_id, until=lambda r: r["steps"].get("ok", {}).get("status") == "esperando")
    approval = client.get("/aprovacoes", headers=AUTH).json()[0]
    assert approval["tool"] == "aprovação" and "Primeira coisa" in approval["summary"]
    client.post(f"/aprovacoes/{approval['id']}", json={"aprovar": False}, headers=AUTH)
    run = wait_run(client, run_id)
    assert run["status"] == "recusada" and run["steps"]["ok"]["status"] == "recusado"
    assert run["steps"]["tem"]["status"] == "pulado" and run["steps"]["canal"]["status"] == "pulado"

    # Reexecutar daqui: a condição roda de novo com as entradas guardadas; a aprovação não volta.
    data["passos"][1] = {**data["passos"][1], "desligado": True}
    client.put(f"/automacoes/{automation_id}", json={"desenho": data}, headers=AUTH)
    first = wait_run(client, client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"])
    assert first["steps"]["ok"]["nota"].startswith("desligado") and first["status"] == "ok"
    again = client.post(f"/execucoes/{first['id']}/reexecutar", json={"desde": "tem"}, headers=AUTH).json()["execucao"]
    rerun = wait_run(client, again)
    assert rerun["steps"]["tarefas"]["nota"] == "guardado da execução anterior" and rerun["steps"]["tem"]["status"] == "ok"
    assert rerun["origem"] == "reexecução"


def test_agent_step_returns_through_saida_with_format_check(core, monkeypatch):
    client, app = core.client, core.app
    engine, hub, manager = app.state.engine, app.state.hub, app.state.manager
    written: list[bytes] = []
    created = {}

    def fake_create(kind, cwd=None, cols=120, rows=32, title=None, account_id=None, tag=None, agent=None, prompt=None):
        created.update(kind=kind, tag=tag, prompt=prompt, agent=agent)
        session = SimpleNamespace(id="ag1", title=title, pty=SimpleNamespace(write=written.append), statusline=None)
        manager.sessions["ag1"] = session
        return session

    monkeypatch.setattr(manager, "create", fake_create)

    async def no_close(session_id):
        manager.sessions.pop(session_id, None)
        return True

    monkeypatch.setattr(manager, "close", no_close)
    data = {
        "nome": "Escrever",
        "gatilho": {"tipo": "manual"},
        "passos": [{"id": "escrever", "tipo": "agente", "titulo": "Escrever o resumo", "cli": "claude", "pedido": "Resuma o dia {{hoje}}.",
                    "ferramentas": ["brain_buscar"], "saida": {"resumo": "texto", "itens": "lista"}}],  # fmt: skip
        "ligacoes": [{"de": "gatilho", "para": "escrever"}],
    }
    automation_id = client.post("/automacoes", json={"nome": "Escrever", "desenho": data}, headers=AUTH).json()["id"]
    run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
    for _ in range(100):
        if "ag1" in engine.waiters:
            break
        time.sleep(0.05)
    assert created["tag"] == "automacao" and "Resuma o dia 2" in created["prompt"] and "`saida`" in created["prompt"]
    names = {t.name for t in hub.tools_for(Context(session="ag1", who="x", cwd=None, allowed=None))}
    assert names == {"brain_buscar", "saida"}  # só o que o passo liberou, mais a saída
    engine.on_stop("ag1")  # terminou o turno sem devolver: a MÊTIS pede de novo no terminal
    assert b"saida" in written[0]
    assert "faltou o campo itens" in engine.receive_output("ag1", {"resumo": "ok"})
    assert "Recebido" in engine.receive_output("ag1", {"resumo": "Dia tranquilo", "itens": ["a"]})
    run = wait_run(client, run_id)
    assert run["status"] == "ok" and run["steps"]["escrever"]["saida"] == {"resumo": "Dia tranquilo", "itens": ["a"]}
    assert run["steps"]["escrever"]["itens"] == 1 and "terminal" in run["steps"]["escrever"]["nota"] and run["steps"]["escrever"]["sessao"] == "ag1"
    manager.sessions.pop("ag1", None)  # a sessão de mentira não passa pelo fechamento de verdade


def test_scheduler_runs_published_on_time_and_skips_when_the_mac_slept(core):
    client, engine = core.client, core.app.state.engine
    data = flow(gatilho={"tipo": "agendado", "dias": [0, 1, 2, 3, 4, 5, 6], "hora": "07:30", "recupera_min": 30})
    automation_id = client.post("/automacoes", json={"nome": "Agendada", "desenho": data}, headers=AUTH).json()["id"]
    client.post(f"/automacoes/{automation_id}/publicar", json={}, headers=AUTH)
    client.put(f"/automacoes/{automation_id}/ativa", json={"ativa": True}, headers=AUTH)
    with engine._connect() as con:  # ativada ontem, para a hora de hoje valer
        con.execute("update estado set desde = ? where automation = ?", (time.time() - 2 * 86400, automation_id))
    today = datetime.now().astimezone().replace(hour=7, minute=30, second=0, microsecond=0)
    started = client.portal.call(engine.tick, today + timedelta(seconds=40))
    assert len(started) == 1 and client.portal.call(engine.tick, today + timedelta(minutes=1)) == []
    run = wait_run(client, started[0], until=lambda r: r["steps"].get("canal", {}).get("status") == "esperando")
    assert run["origem"] == "agendado" and run["mode"] == "producao"  # e para na aprovação do envio ao canal
    assert client.post(f"/execucoes/{started[0]}/parar", headers=AUTH).status_code == 204
    assert wait_run(client, started[0])["status"] == "cancelada"
    late = client.portal.call(engine.tick, today + timedelta(days=1, hours=3))
    assert late == [] and engine.list_runs(automation_id, 1)[0]["status"] == "pulada"
