"""v1.0.0: revisão das automações da v0.9.8 (parte 4) — rotina conta como rodada quando o
terminal abre, pedido da rotina como foi escrito, rotina pela marca e não pelo id, saída inteira
do agente sem formato, código que escreve em ensaio, n8n (item da vez e número de expressão),
sondagem lenta que não atrasa a hora marcada e o Claude da automação que não pede licença."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from datetime import datetime, timedelta

import pytest

import harness_core.automation_engine as engine_mod
from harness_core import n8n_import
from harness_core.automation_engine import AGENT_SLOTS
from harness_core.routines import RoutineFlows

from .conftest import TOKEN
from .test_automations import brain, core, wait_run  # noqa: F401 - fixtures e ajuda reaproveitados
from .test_v098d_motor import agent_flow, agent_spy, code_flow, make, poll_flow, wait_waiter  # noqa: F401

AUTH = {"X-Harness-Token": TOKEN}
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


def routine_body(name: str, prompt: str = "Como foi o estudo hoje?", **changes) -> dict:
    return {"name": name, "days": EVERY_DAY, "time": "20:50", "catchup": 0, "notify": False, "prompt": prompt, **changes}


# --- rotina: o terminal abriu com o pedido, a rotina rodou ---------------------------------------------


def test_routine_is_ok_when_the_terminal_opens_without_holding_a_slot(core, agent_spy, monkeypatch):
    client, app = core.client, core.app
    engine, automations = app.state.engine, app.state.automations
    dms: list[str] = []
    monkeypatch.setattr(engine, "notify", lambda text: dms.append(text) or "")
    # A Aurora como a v0.9.8 gravou em disco (com os 120 min de prazo no passo).
    old = RoutineFlows.flow(routine_body("Aurora"), time.time())
    old["passos"][0]["tempo_limite_min"] = 120
    automations.create("Aurora", old, automation_id="rotina-aurora")
    automations.publish("rotina-aurora")
    engine.set_active("rotina-aurora", True)
    ids = ["aurora"] + [client.post("/rotinas", json=routine_body(f"Rotina {n}"), headers=AUTH).json()["id"] for n in range(AGENT_SLOTS)]
    for routine_id in ids:  # mais rotinas abertas que vagas de agente: todas abrem
        assert client.post(f"/rotinas/{routine_id}/rodar", headers=AUTH).json()["session"]
    assert len(agent_spy) == AGENT_SLOTS + 1
    for routine_id in ids:
        run = wait_run(client, engine.list_runs(f"rotina-{routine_id}", 1)[0]["id"])
        step = run["steps"]["agente"]
        assert run["status"] == "ok" and step["status"] == "ok" and step["sessao"], run
        assert "aberto com o pedido" in step["nota"] and step["saida"]["sessao"] == step["sessao"]
    assert engine.waiters == {} and not any("falhou" in text for text in dms)
    assert all(s["tag"] == "rotina" and s["extra"] is None for s in agent_spy)  # conversa comum, como antes
    # Na hora marcada: rodou, e continua rodou (nada de erro duas horas depois).
    with engine._connect() as con:
        con.execute("update estado set desde = ?, ultima_hora = null where automation = 'rotina-aurora'", (time.time() - 3 * 86400,))
    slot = datetime.now().astimezone().replace(hour=20, minute=50, second=0, microsecond=0)
    started = [r for r in client.portal.call(engine.tick, slot + timedelta(seconds=30)) if engine.run(r)["automation"] == "rotina-aurora"]
    assert len(started) == 1 and wait_run(client, started[0])["status"] == "ok"
    views = [r for r in client.get("/rotinas", headers=AUTH).json()["runs"] if r["routine"] == "aurora"]
    assert views[0]["status"] == "rodou" and views[0]["slot"] == pytest.approx(slot.timestamp())


def test_routine_prompt_goes_exactly_as_written(core, agent_spy):
    client = core.client
    texts = ["Use o template {{nome}} no e-mail de {{hoje}}.", "{{x}}"]
    for n, prompt in enumerate(texts):
        routine_id = client.post("/rotinas", json=routine_body(f"Modelo {n}", prompt), headers=AUTH).json()["id"]
        client.post(f"/rotinas/{routine_id}/rodar", headers=AUTH)
    assert [s["prompt"] for s in agent_spy] == texts


# --- rotina pela marca, não pelo começo do id ---------------------------------------------------------


def test_automation_named_rotina_is_not_taken_by_the_routines_screen(core, agent_spy):
    client, app = core.client, core.app
    engine, automations = app.state.engine, app.state.automations
    flow = {
        "nome": "Rotina diária",
        "gatilho": {"tipo": "agendado", "dias": EVERY_DAY, "hora": "07:00"},
        "passos": [{"id": "fazer", "tipo": "agente", "titulo": "Fazer", "cli": "claude", "pedido": "Resuma.", "saida": {"resumo": "texto"}}],
        "ligacoes": [{"de": "gatilho", "para": "fazer"}],
    }
    automation_id = make(client, flow, publish=True, active=True)
    assert automation_id == "rotina-diaria"
    before = automations.draft(automation_id)
    run_id = client.post(f"/automacoes/{automation_id}/rodar", headers=AUTH).json()["execucao"]
    wait_waiter(engine, "ag1")
    engine.receive_output("ag1", {"resumo": "ok"})
    assert wait_run(client, run_id)["status"] == "ok"
    listing = client.get("/rotinas", headers=AUTH).json()
    assert "diaria" not in [r["id"] for r in listing["routines"]]
    assert all(r["routine"] != "diaria" for r in listing["runs"])
    assert "diaria" not in [s["routine"]["id"] for s in client.get("/hoje", headers=AUTH).json()["slots"]]
    body = routine_body("Diária")
    assert client.put("/rotinas/diaria", json=body, headers=AUTH).status_code == 404
    assert client.post("/rotinas/diaria/rodar", headers=AUTH).status_code == 404
    assert client.delete("/rotinas/diaria", headers=AUTH).status_code == 404
    assert automations.draft(automation_id) == before and automation_id in automations.ids()
    # Uma rotina nova com o mesmo nome não pega o id da automação.
    made = client.post("/rotinas", json=body, headers=AUTH).json()
    assert made["id"] == "diaria-2" and [r["id"] for r in client.get("/rotinas", headers=AUTH).json()["routines"]] == ["diaria-2"]


# --- agente sem formato combinado: a última mensagem inteira --------------------------------------------


def test_agent_without_output_shape_returns_the_whole_last_message(core, agent_spy, tmp_path):
    client, engine = core.client, core.app.state.engine
    report = "# Relatório\n\n" + "\n".join(f"- item {n}: " + " ".join(["detalhe"] * 20) for n in range(20))
    assert len(report) > 3000
    automation_id = make(client, agent_flow(saida={}, onde="visivel", ferramentas=["*"]))
    run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
    wait_waiter(engine, "ag1")
    client.post("/hooks/event?session=ag1&name=Stop", json={"last_assistant_message": report + "\n"}, headers=AUTH)
    assert wait_run(client, run_id)["steps"]["fazer"]["saida"] == {"texto": report}
    # Sem a mensagem no aviso do Claude: vem do transcript, também inteira e com as quebras de linha.
    transcript = tmp_path / "conversa.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Faça o resumo."}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": report}]}},
    ]
    transcript.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n", encoding="utf-8")
    run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
    wait_waiter(engine, "ag2")
    client.post("/hooks/event?session=ag2&name=Stop", json={"transcript_path": str(transcript)}, headers=AUTH)
    assert wait_run(client, run_id)["steps"]["fazer"]["saida"] == {"texto": report}


# --- o Claude de uma automação não para numa pergunta de licença ----------------------------------------


def test_unattended_agent_with_all_tools_does_not_ask_permission(core, agent_spy):
    client, engine = core.client, core.app.state.engine
    automation_id = make(client, agent_flow(saida={"resumo": "texto"}, ferramentas=["*"]))
    run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
    wait_waiter(engine, "ag1")
    assert agent_spy[0]["extra"] == ["--allowedTools", "mcp__metis"] and "ag1" not in engine.hub.session_tools
    engine.receive_output("ag1", {"resumo": "ok"})
    assert wait_run(client, run_id)["status"] == "ok"


# --- código que escreve: ensaio no teste ----------------------------------------------------------------


def test_code_that_writes_is_a_rehearsal_in_test_runs(core, tmp_path):
    client = core.client
    marker = tmp_path / "enviado.txt"
    code = f"open({str(marker)!r}, 'w').write('POST')\nsaida = {{'enviado': True}}"
    automation_id = make(client, {**code_flow(code, escreve=True), "nome": "Manda o POST"}, publish=True)
    run = wait_run(client, client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"])
    step = run["steps"]["conta"]
    assert run["status"] == "ok" and step["saida"]["ensaio"] is True and step["nota"].startswith("ensaio") and not marker.exists()
    sent = [form for method, form in core.fake.calls if method == "chat.postMessage"]
    assert sent[-1]["channel"] == "D42" and "Ensaio de Manda o POST · Contar" in sent[-1]["text"]
    run = wait_run(client, client.post(f"/automacoes/{automation_id}/rodar", headers=AUTH).json()["execucao"])
    assert run["status"] == "ok" and run["steps"]["conta"]["saida"] == {"enviado": True} and marker.read_text() == "POST"
    # Sem a marca, o teste roda o código como sempre.
    plain = make(client, {**code_flow("saida = 7"), "nome": "Só conta"})
    run = wait_run(client, client.post(f"/automacoes/{plain}/testar", json={}, headers=AUTH).json()["execucao"])
    assert run["steps"]["conta"]["saida"] == 7


def n8n_workflow(*nodes: dict) -> dict:
    """Workflow do n8n com um gatilho manual na frente e os nós em fila."""
    chain = [{"name": "Início", "type": "n8n-nodes-base.manualTrigger", "position": [0, 0], "parameters": {}}, *nodes]
    for n, node in enumerate(chain):
        node.setdefault("position", [200 * n, 0])
    connections = {a["name"]: {"main": [[{"node": b["name"], "type": "main", "index": 0}]]} for a, b in zip(chain, chain[1:])}
    return {"name": "Do n8n", "nodes": chain, "connections": connections}


def test_n8n_http_that_sends_is_marked_as_writing():
    workflow = n8n_workflow(
        {"name": "Ler", "type": "n8n-nodes-base.httpRequest", "parameters": {"url": "https://exemplo.com/itens"}},
        {"name": "Enviar", "type": "n8n-nodes-base.httpRequest", "parameters": {"method": "POST", "url": "https://exemplo.com/novo", "jsonBody": "{\"a\": 1}"}},
    )
    result = n8n_import.translate(workflow)
    steps = {s["titulo"]: s for s in result["proposta"]["passos"]}
    assert "escreve" not in steps["Ler"] and steps["Enviar"]["escreve"] is True
    assert any(r["passo"] == "Enviar" and "no teste não roda" in r["motivo"] for r in result["revisar"])


# --- n8n: o item da vez e o número que vem de expressão -------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node neste Mac")
def test_n8n_per_item_code_sees_each_item(core):
    workflow = n8n_workflow(
        {"name": "Dobrar", "type": "n8n-nodes-base.code", "parameters": {"mode": "runOnceForEachItem", "jsCode": "return { json: { total: $input.item.json.price * 2 } };"}},
    )
    step = n8n_import.translate(workflow)["proposta"]["passos"][0]
    value, _note = core.app.state.engine._code(step, [{"price": 1}, {"price": 2}, {"price": 5}], {})
    assert value == [{"total": 2}, {"total": 4}, {"total": 10}]


def test_n8n_numbers_from_expressions_become_review_notes(core):
    workflow = n8n_workflow({"name": "Esperar", "type": "n8n-nodes-base.wait", "parameters": {"amount": "={{ $json.delay }}", "unit": "minutes"}})
    workflow["nodes"][0] = {
        "name": "Todo dia",
        "type": "n8n-nodes-base.scheduleTrigger",
        "position": [0, 0],
        "parameters": {"rule": {"interval": [{"field": "days", "triggerAtHour": "={{ $json.hora }}"}]}},
    }
    workflow["connections"] = {"Todo dia": workflow["connections"]["Início"]}
    response = core.client.post("/automacoes/importar-n8n", json={"fluxo": workflow}, headers=AUTH)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["proposta"]["gatilho"]["tipo"] == "manual" and data["proposta"]["passos"][0]["minutos"] == 1
    reasons = {r["passo"]: r["motivo"] for r in data["revisar"]}
    assert "expressão" in reasons["Todo dia"] and "expressão" in reasons["Esperar"]
    cron = {"type": "n8n-nodes-base.cron", "parameters": {"triggerTimes": {"item": [{"mode": "everyDay", "hour": "={{ 7 }}", "minute": 0}]}}}
    trigger, why = n8n_import.translate_schedule(cron)
    assert trigger is None and "expressão" in why


# --- sondagem lenta não atrasa a hora marcada -----------------------------------------------------------


def test_slow_poll_does_not_hold_the_scheduled_automations(core, monkeypatch):
    client, engine = core.client, core.app.state.engine
    monkeypatch.setattr(engine_mod, "POLL_WAIT", 0.1, raising=False)
    poll_id = make(client, poll_flow(), publish=True, active=True)
    scheduled = make(client, {**code_flow("saida = 1", gatilho={"tipo": "agendado", "dias": EVERY_DAY, "hora": "07:30", "recupera_min": 2}), "nome": "Z agendada"},
                     publish=True, active=True)  # fmt: skip
    assert poll_id < scheduled  # a sondagem vem antes na volta do agendador
    with engine._connect() as con:
        con.execute("update estado set desde = ? where automation = ?", (time.time() - 2 * 86400, scheduled))

    async def slow_call(ctx, name, args, read_only=False):
        await asyncio.sleep(1.0)  # um conector que demora a responder
        return {"itens": []}

    monkeypatch.setattr(engine, "_call_tool", slow_call)
    slot = datetime.now().astimezone().replace(hour=7, minute=30, second=0, microsecond=0)
    begin = time.monotonic()
    started = client.portal.call(engine.tick, slot + timedelta(seconds=40))
    assert time.monotonic() - begin < 0.8
    assert len(started) == 1 and engine.run(started[0])["automation"] == scheduled
    assert wait_run(client, started[0])["status"] == "ok"
    deadline = time.time() + 5
    while time.time() < deadline and not engine.state(poll_id)["sondagem_base"]:
        time.sleep(0.05)
    assert engine.state(poll_id)["sondagem_base"] == 1  # a sondagem terminou sozinha, depois
