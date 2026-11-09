"""v0.9.8 parte 4 (IA e importação): automação por frase, código escrito pelo Claude, importar do
n8n (JSON e pela conta do MCP do n8n) e as estratégias de orquestração."""

from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from harness_core import automation_ai, automation_templates, n8n_import
from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.automation_engine import Engine
from harness_core.automations import TRIGGER_ID, dump, layers, validate
from harness_core.claude_print import ClaudePrintError

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def fake_argv(kind, settings):
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


class Asker:
    """O Claude falso: devolve as respostas na ordem e guarda os prompts."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


GOOD = {
    "fluxo": {
        "nome": "Decisões da semana",
        "gatilho": {"tipo": "agendado", "dias": [4], "hora": "18:00"},
        "passos": [
            {"id": "buscar", "titulo": "Buscar decisões", "tipo": "ferramenta", "ferramenta": "brain_buscar", "argumentos": {"termos": "decisão"}},
            {"id": "resumir", "titulo": "Resumir", "tipo": "agente", "cli": "claude", "pedido": "Resuma {{Buscar decisões}}", "saida": {"resumo": "texto"}, "ferramentas": ["brain_ler", "nao_existe", "*"]},
            {"id": "tem", "titulo": "Tem algo?", "tipo": "condicao", "regra": "not vazio({{Resumir.resumo}})"},
            {"id": "avisar", "titulo": "Avisar", "tipo": "ferramenta", "ferramenta": "slack-inventado__mensagem", "argumentos": {"texto": "{{Resumir.resumo}}"}},
        ],
        "ligacoes": [
            {"de": "gatilho", "para": "buscar"},
            {"de": "buscar", "para": "resumir"},
            {"de": "resumir", "para": "tem"},
            {"de": "tem", "para": "avisar", "ramo": "sim"},
        ],
    },
    "explicacao": "Toda sexta às 18h busca as decisões e resume.",
}


# --- criar e ajustar por frase ------------------------------------------------------------------


def test_proposal_from_scratch_is_checked_laid_out_and_not_saved(core):
    client, app = core
    ask = Asker(GOOD)
    app.state.automation_ask = ask
    before = client.get("/automacoes", headers=AUTH).json()
    answer = client.post("/automacoes/proposta", headers=AUTH, json={"descricao": "toda sexta, resuma as decisões da semana e me avise"})
    assert answer.status_code == 200, answer.text
    flow = answer.json()["proposta"]
    assert validate(flow) == flow
    assert flow["gatilho"]["tipo"] == "agendado" and (flow["gatilho"]["x"], flow["gatilho"]["y"]) == (0, 0)
    steps = {s["id"]: s for s in flow["passos"]}
    # camadas de 260 px a partir do gatilho
    assert steps["buscar"]["x"] == 260 and steps["resumir"]["x"] == 520 and steps["tem"]["x"] == 780 and steps["avisar"]["x"] == 1040
    # ferramenta inexistente vira agente, com a nota Revisar
    assert steps["avisar"]["tipo"] == "agente" and "slack-inventado__mensagem" in steps["avisar"]["pedido"]
    assert any(n["titulo"] == "Revisar" and "slack-inventado__mensagem" in n["texto"] for n in flow["notas"])
    # ferramentas liberadas: só as que existem (e o curinga)
    assert steps["resumir"]["ferramentas"] == ["brain_ler", "*"]
    assert "Revisar" in answer.json()["explicacao"] or "revisar" in answer.json()["explicacao"].lower()
    # o catálogo foi no prompt: ferramentas da central e os tipos de passo
    assert "brain_buscar" in ask.prompts[0] and "codigo:" in ask.prompts[0] and "sondagem" in ask.prompts[0]
    # nada foi salvo
    assert client.get("/automacoes", headers=AUTH).json() == before


def test_proposal_adjusts_the_current_flow_keeping_positions(core):
    client, app = core
    current = {
        "nome": "Atual",
        "gatilho": {"tipo": "manual", "x": 10, "y": 20},
        "passos": [{"id": "ler", "titulo": "Ler", "tipo": "brain", "acao": "buscar", "termos": "x", "x": 400, "y": 300}],
        "ligacoes": [{"de": "gatilho", "para": "ler"}],
    }
    adjusted = {
        "fluxo": {
            **current,
            "passos": current["passos"] + [{"id": "contar", "titulo": "Contar", "tipo": "codigo", "linguagem": "python", "codigo": "saida = len(entrada)"}],
            "ligacoes": current["ligacoes"] + [{"de": "ler", "para": "contar"}],
        },
        "explicacao": "Acrescentei a contagem.",
    }
    ask = Asker(adjusted)
    app.state.automation_ask = ask
    answer = client.post("/automacoes/proposta", headers=AUTH, json={"descricao": "conte quantas notas vieram", "atual": current})
    assert answer.status_code == 200, answer.text
    flow = answer.json()["proposta"]
    steps = {s["id"]: s for s in flow["passos"]}
    assert (steps["ler"]["x"], steps["ler"]["y"]) == (400, 300)
    assert (flow["gatilho"]["x"], flow["gatilho"]["y"]) == (10, 20)
    assert steps["contar"]["tipo"] == "codigo" and steps["contar"]["x"] == 520
    assert "Desenho atual" in ask.prompts[0] and '"ler"' in ask.prompts[0]


def test_proposal_errors(core):
    client, app = core
    app.state.automation_ask = Asker(ClaudePrintError("o Claude devolveu JSON quebrado"))
    answer = client.post("/automacoes/proposta", headers=AUTH, json={"descricao": "qualquer coisa útil"})
    assert answer.status_code == 502 and "JSON quebrado" in answer.json()["detail"]
    # desenho que não fecha duas vezes (ciclo) → 502 com o motivo
    cyc = {"fluxo": {"nome": "X", "passos": [{"id": "a", "tipo": "esperar"}, {"id": "b", "tipo": "esperar"}], "ligacoes": [{"de": "a", "para": "b"}, {"de": "b", "para": "a"}]}}
    ask = Asker(cyc, cyc)
    app.state.automation_ask = ask
    answer = client.post("/automacoes/proposta", headers=AUTH, json={"descricao": "duas esperas"})
    assert answer.status_code == 502 and "ciclo" in answer.json()["detail"]
    assert "não fechou" in ask.prompts[1]
    assert client.post("/automacoes/proposta", headers=AUTH, json={"descricao": "x"}).status_code == 400
    bad_current = client.post("/automacoes/proposta", headers=AUTH, json={"descricao": "ajuste isso", "atual": {"passos": []}})
    assert bad_current.status_code == 400


def test_repair_renames_repeated_ids_and_titles():
    flow, review = automation_ai.repair(
        {
            "nome": "R",
            "passos": [
                {"id": "Passo Um", "titulo": "Igual", "tipo": "esperar"},
                {"id": "passo-um", "titulo": "igual", "tipo": "esperar"},
                {"id": "x", "tipo": "agente", "cli": "gpt", "agente": "sumiu"},
            ],
            "ligacoes": [{"de": "gatilho", "para": "Passo Um"}, {"de": "fantasma", "para": "x"}],
        },
        set(),
        set(),
    )
    ids = [s["id"] for s in flow["passos"]]
    assert ids == ["passo-um", "passo-um-2", "x"]
    assert [s["titulo"] for s in flow["passos"]][:2] == ["Igual", "igual 2"]
    assert flow["passos"][2]["cli"] == "claude" and "agente" not in flow["passos"][2]
    assert flow["ligacoes"] == [{"de": "gatilho", "para": "passo-um"}]
    assert review == []


# --- escrever código ------------------------------------------------------------------------------


def test_write_code_python_and_retry_on_syntax(core):
    client, app = core
    app.state.automation_ask = Asker({"codigo": "```python\nsaida = sorted(entrada)\n```"})
    answer = client.post("/automacoes/codigo/escrever", headers=AUTH, json={"descricao": "ordene a lista", "linguagem": "python", "entrada_exemplo": [3, 1]})
    assert answer.status_code == 200 and answer.json()["codigo"] == "saida = sorted(entrada)"
    ask = Asker({"codigo": "saida = ("}, {"codigo": "saida = list(entrada)"})
    app.state.automation_ask = ask
    answer = client.post("/automacoes/codigo/escrever", headers=AUTH, json={"descricao": "copie a lista", "linguagem": "python"})
    assert answer.json()["codigo"] == "saida = list(entrada)" and "erro de sintaxe" in ask.prompts[1]
    app.state.automation_ask = Asker({"codigo": "saida = ("}, {"codigo": "saida = ["})
    assert client.post("/automacoes/codigo/escrever", headers=AUTH, json={"descricao": "quebrado", "linguagem": "python"}).status_code == 502
    assert client.post("/automacoes/codigo/escrever", headers=AUTH, json={"descricao": "x", "linguagem": "python"}).status_code == 400
    assert client.post("/automacoes/codigo/escrever", headers=AUTH, json={"descricao": "faça algo", "linguagem": "ruby"}).status_code == 400


@pytest.mark.skipif(shutil.which("node") is None, reason="sem Node")
def test_write_code_javascript_checks_like_the_engine(core):
    client, app = core
    app.state.automation_ask = Asker({"codigo": "const r = await Promise.resolve(entrada);\nsaida = r.length;"})
    answer = client.post("/automacoes/codigo/escrever", headers=AUTH, json={"descricao": "conte", "linguagem": "javascript"})
    assert answer.status_code == 200
    assert "await" in answer.json()["codigo"]
    assert "convenção" not in answer.json()["codigo"]


# --- importar do n8n ------------------------------------------------------------------------------

WF_SCHEDULE = {
    "name": "Relatório diário",
    "nodes": [
        {"id": "1", "name": "Todo dia", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [100, 300],
         "parameters": {"rule": {"interval": [{"field": "days", "triggerAtHour": 7, "triggerAtMinute": 30}]}}},
        {"id": "2", "name": "Buscar dados", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [320, 300],
         "parameters": {"method": "GET", "url": "https://api.exemplo.com/vendas", "sendHeaders": True,
                        "headerParameters": {"parameters": [{"name": "Authorization", "value": "Bearer abcdefghijkl1234567890"}, {"name": "X-Cliente", "value": "metis"}]}},
         "credentials": {"httpHeaderAuth": {"id": "9", "name": "Chave da API"}}},
        {"id": "3", "name": "Teve venda?", "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [540, 300],
         "parameters": {"conditions": {"combinator": "and", "conditions": [{"leftValue": "={{ $json.total }}", "rightValue": 0, "operator": {"type": "number", "operation": "gt"}}]}}},
        {"id": "4", "name": "Avisar no Slack", "type": "n8n-nodes-base.slack", "typeVersion": 2.2, "position": [760, 200],
         "parameters": {"resource": "message", "operation": "post", "channel": "#vendas", "text": "={{ $json.total }} vendas"}},
        {"id": "5", "name": "Nada", "type": "n8n-nodes-base.noOp", "typeVersion": 1, "position": [760, 400], "parameters": {}},
        {"id": "6", "name": "Nota", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": [100, 600], "parameters": {"content": "Roda às 7h30"}},
    ],
    "connections": {
        "Todo dia": {"main": [[{"node": "Buscar dados", "type": "main", "index": 0}]]},
        "Buscar dados": {"main": [[{"node": "Teve venda?", "type": "main", "index": 0}]]},
        "Teve venda?": {"main": [[{"node": "Avisar no Slack", "type": "main", "index": 0}], [{"node": "Nada", "type": "main", "index": 0}]]},
    },
}

WF_WEBHOOK = {
    "name": "Webhook de pedido",
    "nodes": [
        {"name": "Webhook", "type": "n8n-nodes-base.webhook", "position": [0, 0], "parameters": {"path": "pedido"}},
        {"name": "Marcar", "type": "n8n-nodes-base.code", "position": [220, 0],
         "parameters": {"jsCode": "return $input.all().map(item => ({ json: { ...item.json, ok: true } }));"}},
        {"name": "Campos", "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [440, 0],
         "parameters": {"assignments": {"assignments": [{"name": "origem", "value": "n8n", "type": "string"}, {"name": "primeiro", "value": "={{ $json.ok }}", "type": "boolean"}]}}},
    ],
    "connections": {
        "Webhook": {"main": [[{"node": "Marcar", "type": "main", "index": 0}]]},
        "Marcar": {"main": [[{"node": "Campos", "type": "main", "index": 0}]]},
    },
}

WF_AI = {
    "name": "Resumo com IA",
    "nodes": [
        {"name": "Manual", "type": "n8n-nodes-base.manualTrigger", "position": [0, 0], "parameters": {}},
        {"name": "Resumir", "type": "@n8n/n8n-nodes-langchain.agent", "position": [220, 0],
         "parameters": {"promptType": "define", "text": "=Resuma em 3 linhas: {{ $json.texto }}", "options": {"systemMessage": "Você é conciso."}}},
        {"name": "Modelo", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "position": [220, 200], "parameters": {"model": "gpt-4o-mini"}},
        {"name": "Mandar e-mail", "type": "n8n-nodes-base.gmail", "position": [440, 0], "parameters": {"resource": "message", "operation": "send", "sendTo": "a@b.com"}},
        {"name": "Esperar", "type": "n8n-nodes-base.wait", "position": [660, 0], "parameters": {"amount": 2, "unit": "hours"}},
    ],
    "connections": {
        "Manual": {"main": [[{"node": "Resumir", "type": "main", "index": 0}]]},
        "Modelo": {"ai_languageModel": [[{"node": "Resumir", "type": "ai_languageModel", "index": 0}]]},
        "Resumir": {"main": [[{"node": "Mandar e-mail", "type": "main", "index": 0}]]},
        "Mandar e-mail": {"main": [[{"node": "Esperar", "type": "main", "index": 0}]]},
    },
}


def _steps(result):
    return {s["titulo"]: s for s in result["proposta"]["passos"]}


def test_import_schedule_http_if_slack():
    tools = [
        {"nome": "slack-pessoal__mensagem", "descricao": "Manda uma mensagem num canal do Slack", "conta": "slack-pessoal"},
        {"nome": "slack-pessoal__ler_canal", "descricao": "Lê as mensagens de um canal", "conta": "slack-pessoal"},
    ]
    result = n8n_import.translate(WF_SCHEDULE, tools, {"slack-pessoal": "slack"})
    flow = result["proposta"]
    assert result["nome"] == "Relatório diário"
    assert flow["gatilho"]["tipo"] == "agendado" and flow["gatilho"]["hora"] == "07:30" and flow["gatilho"]["dias"] == list(range(7))
    steps = _steps(result)
    assert set(steps) == {"Buscar dados", "Teve venda?", "Avisar no Slack"}  # noOp e nota não viram passo
    http = steps["Buscar dados"]
    assert http["tipo"] == "codigo" and http["linguagem"] == "javascript" and "fetch(url" in http["codigo"]
    assert "abcdefghijkl1234567890" not in dump(flow) and "<SEGREDO REMOVIDO>" in http["codigo"] and "Chave da API" not in dump(flow)
    assert steps["Teve venda?"]["regra"] == "{{Buscar dados.total}} > 0"
    assert steps["Avisar no Slack"]["tipo"] == "ferramenta" and steps["Avisar no Slack"]["ferramenta"] == "slack-pessoal__mensagem"
    by = {(e["de"], e["para"]): e.get("ramo") for e in flow["ligacoes"]}
    cond = steps["Teve venda?"]["id"]
    assert by[(cond, steps["Avisar no Slack"]["id"])] == "sim"
    assert (TRIGGER_ID, steps["Buscar dados"]["id"]) in by
    assert any(n["titulo"] == "Nota do n8n" and "7h30" in n["texto"] for n in flow["notas"])
    motivos = {r["passo"]: r["motivo"] for r in result["revisar"]}
    assert "Buscar dados" in motivos and "Avisar no Slack" in motivos and "Teve venda?" not in motivos


def test_import_webhook_code_set_and_the_code_runs():
    result = n8n_import.translate(json.dumps(WF_WEBHOOK))
    flow = result["proposta"]
    assert flow["gatilho"]["tipo"] == "manual"
    assert any("webhook" in r["motivo"] for r in result["revisar"])
    steps = _steps(result)
    assert steps["Marcar"]["tipo"] == "codigo" and steps["Campos"]["tipo"] == "codigo"
    assert any(r["passo"] == "Marcar" for r in result["revisar"])
    if shutil.which("node"):
        engine = Engine.__new__(Engine)
        out, _ = Engine._code(engine, steps["Marcar"], [{"pedido": 7}], {})
        assert out == [{"pedido": 7, "ok": True}]
        out, _ = Engine._code(engine, steps["Campos"], {"ok": True, "outro": 1}, {})
        assert out == {"origem": "n8n", "primeiro": True}


def test_import_ai_agent_service_without_account_and_wait():
    result = n8n_import.translate(WF_AI)
    steps = _steps(result)
    assert "Modelo" not in steps  # sub-nó do agente não vira passo
    agent = steps["Resumir"]
    assert agent["tipo"] == "agente" and agent["cli"] == "claude" and agent["troca_cota"] is True
    assert agent["pedido"].startswith("Você é conciso.") and "{{entrada.texto}}" in agent["pedido"]
    assert steps["Mandar e-mail"]["tipo"] == "agente"
    assert steps["Esperar"]["tipo"] == "esperar" and steps["Esperar"]["minutos"] == 120
    motivos = {r["passo"] for r in result["revisar"]}
    assert {"Resumir", "Mandar e-mail"} <= motivos


def test_import_old_cron_and_conversions():
    wf = {
        "name": "Cron antigo",
        "nodes": [
            {"name": "Cron", "type": "n8n-nodes-base.cron", "position": [0, 0], "parameters": {"triggerTimes": {"item": [{"mode": "everyWeek", "weekday": 1, "hour": 9, "minute": 5}]}}},
            {"name": "Filtrar", "type": "n8n-nodes-base.if", "position": [200, 0], "parameters": {"conditions": {"string": [{"value1": "={{$node[\"Cron\"].json[\"x\"]}}", "operation": "contains", "value2": "a"}]}}},
            {"name": "Desconhecido", "type": "n8n-nodes-base.spreadsheetFile", "position": [400, 0], "parameters": {}},
        ],
        "connections": {"Cron": {"main": [[{"node": "Filtrar"}]]}, "Filtrar": {"main": [[], [{"node": "Desconhecido"}]]}},
    }
    result = n8n_import.translate(wf)
    flow = result["proposta"]
    assert flow["gatilho"] == {**flow["gatilho"], "tipo": "agendado", "dias": [0], "hora": "09:05"}
    steps = _steps(result)
    assert steps["Filtrar"]["regra"] == 'contem({{Cron.x}}, "a")'
    assert steps["Desconhecido"]["tipo"] == "agente"
    assert {"de": steps["Filtrar"]["id"], "para": steps["Desconhecido"]["id"], "ramo": "não"} in flow["ligacoes"]
    assert n8n_import.convert_expr("={{ $('Busca').item.json.lista[0].id }}", None) == "{{Busca.lista.0.id}}"


def test_import_route_and_bad_input(core):
    client, _ = core
    answer = client.post("/automacoes/importar-n8n", headers=AUTH, json={"fluxo": WF_WEBHOOK})
    assert answer.status_code == 200 and answer.json()["proposta"]["nome"] == "Webhook de pedido"
    assert client.post("/automacoes/importar-n8n", headers=AUTH, json={"fluxo": "não é json"}).status_code == 400
    assert client.post("/automacoes/importar-n8n", headers=AUTH, json={"fluxo": {"nada": 1}}).status_code == 400
    assert client.post("/automacoes/importar-n8n", headers=AUTH, json={}).status_code == 400


class FakeN8n:
    def __init__(self, tools):
        self._tools = tools
        self.calls = []

    def tools(self):
        return [{"name": n} for n in self._tools]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "n8n_list_workflows":
            data = {"success": True, "data": {"workflows": [{"id": "w1", "name": "Relatório diário", "active": True}, {"id": "w2", "name": "Outro", "active": False}]}}
        else:
            data = {"success": True, "data": WF_SCHEDULE}
        return {"content": [{"type": "text", "text": json.dumps(data)}]}


def test_n8n_through_a_connected_account(core, monkeypatch):
    client, app = core
    fake = FakeN8n(["n8n_list_workflows", "n8n_get_workflow", "n8n_health_check"])
    monkeypatch.setattr(app.state.connectors, "mcp", lambda account_id: fake)
    answer = client.get("/automacoes/n8n/fluxos?conta=mcp-n8n", headers=AUTH)
    assert answer.status_code == 200
    assert answer.json()["fluxos"] == [{"id": "w1", "nome": "Relatório diário", "ativo": True}, {"id": "w2", "nome": "Outro", "ativo": False}]
    answer = client.post("/automacoes/importar-n8n", headers=AUTH, json={"conta": "mcp-n8n", "workflow_id": "w1"})
    assert answer.status_code == 200 and answer.json()["nome"] == "Relatório diário"
    assert ("n8n_get_workflow", {"id": "w1"}) in fake.calls
    monkeypatch.setattr(app.state.connectors, "mcp", lambda account_id: FakeN8n(["outra_coisa"]))
    answer = client.get("/automacoes/n8n/fluxos?conta=mcp-x", headers=AUTH)
    assert answer.status_code == 400 and "listar workflows" in answer.json()["detail"]


# --- estratégias de orquestração ----------------------------------------------------------------


def test_strategies_create_valid_drafts(core):
    client, _ = core
    listed = client.get("/automacoes/estrategias", headers=AUTH).json()["estrategias"]
    assert [s["id"] for s in listed] == ["explorar-e-construir", "planejar-e-executar", "melhor-de-n", "portao-de-revisao"]
    assert all(any(p["nome"] == "tarefa" for p in s["parametros"]) for s in listed)
    for strategy in listed:
        answer = client.post(f"/automacoes/estrategias/{strategy['id']}", headers=AUTH, json={"parametros": {"tarefa": "Arrumar o login", "pasta": "~/repo", "n": 4}})
        assert answer.status_code == 201, answer.text
        draft = client.get(f"/automacoes/{answer.json()['id']}", headers=AUTH).json()["rascunho"]
        validate(draft, strict=True)
        agents = [s for s in draft["passos"] if s["tipo"] == "agente"]
        assert agents and all(s["troca_cota"] is True and s["pasta"] == "~/repo" for s in agents)
        assert draft["gatilho"]["tipo"] == "manual"
    assert client.post("/automacoes/estrategias/nao-existe", headers=AUTH, json={"parametros": {"tarefa": "x"}}).status_code == 404
    assert client.post("/automacoes/estrategias/melhor-de-n", headers=AUTH, json={"parametros": {}}).status_code == 400


def test_best_of_n_runs_proposals_together_and_the_gate_branches():
    flow = automation_templates.build("melhor-de-n", {"tarefa": "x", "n": 9})
    groups = layers(flow)
    proposals = [s["id"] for s in flow["passos"] if s["id"].startswith("proposta-")]
    assert len(proposals) == 5 and set(proposals) == set(groups[1])  # limitado a 5, todos na mesma camada
    clis = [s["cli"] for s in flow["passos"] if s["id"] in proposals]
    assert clis == ["claude", "codex", "claude", "codex", "claude"]
    assert "{{Proposta 5.proposta}}" in next(s for s in flow["passos"] if s["id"] == "juiz")["pedido"]
    gate = automation_templates.build("portao-de-revisao", {"tarefa": "x", "cli": "codex"})
    ramos = {(e["de"], e["para"]): e.get("ramo") for e in gate["ligacoes"]}
    assert ramos[("aprovado", "pedro")] == "sim" and ramos[("aprovado", "corrigir")] == "não"
    by = {s["id"]: s for s in gate["passos"]}
    assert by["construir"]["cli"] == "codex" and by["revisar"]["cli"] == "claude" and by["pedro"]["tipo"] == "aprovacao"


def test_n8n_header_list_secret_is_removed_even_when_short():
    """Cabeçalho do n8n vem numa lista de {name, value}: o valor sai mesmo sem cara de token."""
    from harness_core import n8n_import

    params = {"headerParameters": {"parameters": [{"name": "Authorization", "value": "Bearer sk-abc123"}, {"name": "Accept", "value": "application/json"}]}}
    clean = n8n_import._clean_secrets(params)
    items = clean["headerParameters"]["parameters"]
    assert items[0]["value"] == n8n_import.SECRET_MARK
    assert items[1]["value"] == "application/json"
    assert "sk-abc123" not in str(clean)
