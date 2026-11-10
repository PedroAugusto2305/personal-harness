"""v0.9.8 (parte 4): motor das automações — passo de código, gatilhos de evento e de
sondagem, troca de CLI por cota, agente sem saída combinada e as rotinas como automações."""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from harness_core.app import create_app
from harness_core.automations import AutomationError, validate
from harness_core.routines import RoutineStore, decide

from .conftest import TOKEN
from .test_automations import brain, core, wait_run  # noqa: F401 - fixtures e ajuda reaproveitados

AUTH = {"X-Harness-Token": TOKEN}


def code_flow(code: str, language: str = "python", gatilho: dict | None = None, **step) -> dict:
    return {
        "nome": "Com código",
        "gatilho": gatilho or {"tipo": "manual"},
        "passos": [{"id": "conta", "tipo": "codigo", "titulo": "Contar", "linguagem": language, "codigo": code, **step}],
        "ligacoes": [{"de": "gatilho", "para": "conta"}],
    }


def make(client: TestClient, flow: dict, publish: bool = False, active: bool = False) -> str:
    response = client.post("/automacoes", json={"nome": flow["nome"], "desenho": flow}, headers=AUTH)
    assert response.status_code == 201, response.text
    automation_id = response.json()["id"]
    if publish:
        assert client.post(f"/automacoes/{automation_id}/publicar", json={}, headers=AUTH).status_code == 200
    if active:
        assert client.put(f"/automacoes/{automation_id}/ativa", json={"ativa": True}, headers=AUTH).status_code == 200
    return automation_id


def runs_of(engine, automation_id: str, count: int = 1, timeout: float = 6.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = engine.list_runs(automation_id)
        if len(found) >= count:
            return found
        time.sleep(0.05)
    return engine.list_runs(automation_id)


# --- passo de código ----------------------------------------------------------------------------


def test_code_step_validation():
    flow = validate(code_flow("saida = 1", tempo_limite_s=9999))
    assert flow["passos"][0]["tempo_limite_s"] == 300 and flow["passos"][0]["linguagem"] == "python"
    with pytest.raises(AutomationError, match="python ou javascript"):
        validate(code_flow("x", language="ruby"))
    with pytest.raises(AutomationError, match="precisa do código"):
        validate(code_flow("   "), strict=True)
    validate(code_flow("   "))  # o rascunho aceita pela metade


def test_python_code_gets_input_and_steps_returns_saida_and_logs(core):
    client = core.client
    code = "print('olá do log')\nsaida = {'dobro': entrada['n'] * 2, 'origem': passos['gatilho']['origem']}"
    flow = {
        "nome": "Dobro",
        "gatilho": {"tipo": "manual"},
        "passos": [
            {"id": "base", "tipo": "codigo", "titulo": "Base", "codigo": "saida = {'n': 21}"},
            {"id": "dobro", "tipo": "codigo", "titulo": "Dobro", "codigo": code},
        ],
        "ligacoes": [{"de": "gatilho", "para": "base"}, {"de": "base", "para": "dobro"}],
    }
    automation_id = make(client, flow)
    run = wait_run(client, client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"])
    assert run["status"] == "ok", run
    assert run["steps"]["dobro"]["saida"] == {"dobro": 42, "origem": "teste"}
    assert "olá do log" in run["steps"]["dobro"]["nota"]


def test_python_code_error_and_timeout(core):
    client = core.client
    broken = make(client, code_flow("raise ValueError('quebrou de propósito')"))
    run = wait_run(client, client.post(f"/automacoes/{broken}/testar", json={}, headers=AUTH).json()["execucao"])
    assert run["status"] == "erro" and "quebrou de propósito" in run["steps"]["conta"]["erro"]
    slow = make(client, {**code_flow("import time\ntime.sleep(5)\nsaida = 1", tempo_limite_s=1), "nome": "Lenta"})
    run = wait_run(client, client.post(f"/automacoes/{slow}/testar", json={}, headers=AUTH).json()["execucao"], timeout=10)
    assert run["status"] == "erro" and "passou de 1 s" in run["steps"]["conta"]["erro"]


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node neste Mac")
def test_javascript_code_with_await(core):
    client = core.client
    code = "console.log('log do js');\nconst valor = await Promise.resolve(entrada.origem);\nsaida = { visto: valor, total: [1, 2, 3].length };"
    automation_id = make(client, {**code_flow(code, language="javascript"), "nome": "Em JS"})
    run = wait_run(client, client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"])
    assert run["status"] == "ok", run
    assert run["steps"]["conta"]["saida"] == {"visto": "teste", "total": 3} and "log do js" in run["steps"]["conta"]["nota"]


def test_javascript_without_node_is_a_clear_error(core, monkeypatch):
    import harness_core.automation_engine as engine_mod

    monkeypatch.setattr(engine_mod.shutil, "which", lambda _name: None)
    client = core.client
    automation_id = make(client, {**code_flow("saida = 1", language="javascript"), "nome": "Sem node"})
    run = wait_run(client, client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"])
    assert run["status"] == "erro" and "Node não está instalado" in run["steps"]["conta"]["erro"]


# --- gatilho de evento ------------------------------------------------------------------------------


def event_flow(event: str, filtro: dict | None = None, nome: str | None = None) -> dict:
    return {
        **code_flow("saida = {'visto': entrada}", gatilho={"tipo": "evento", "evento": event, "filtro": filtro or {}}),
        "nome": nome or f"Quando {event}",
    }


def test_event_trigger_validation():
    with pytest.raises(AutomationError, match="evento"):
        validate(event_flow("chuva"))
    flow = validate(event_flow("captura", {"texto": "oi"}))
    assert flow["gatilho"]["filtro"] == {"texto": "oi"}


def test_capture_event_with_filter_and_debounce(core):
    client, engine = core.client, core.app.state.engine
    match = make(client, event_flow("captura", {"texto": "Revisar o PR"}, "Só a revisão"), publish=True, active=True)
    other = make(client, event_flow("captura", {"texto": "outra coisa"}, "Outra"), publish=True, active=True)
    off = make(client, event_flow("captura", nome="Desligada"), publish=True)
    client.post("/captura", json={"texto": "revisar o pr"}, headers=AUTH)
    client.post("/captura", json={"texto": "revisar o pr"}, headers=AUTH)  # 30 s: não dispara de novo
    runs = runs_of(engine, match)
    run = wait_run(client, runs[0]["id"])
    assert run["origem"] == "evento" and run["mode"] == "producao"
    assert run["steps"]["gatilho"]["saida"]["texto"] == "revisar o pr" and run["steps"]["gatilho"]["saida"]["evento"] == "captura"
    time.sleep(0.5)
    assert len(engine.list_runs(match)) == 1 and engine.list_runs(other) == [] and engine.list_runs(off) == []


def test_task_moved_event(core):
    client, engine = core.client, core.app.state.engine
    automation_id = make(client, event_flow("tarefa.moveu", {"para": "em-andamento"}), publish=True, active=True)
    task = client.get("/brain/projects/Alfa/tasks", headers=AUTH).json()[0]
    assert client.put(f"/brain/projects/Alfa/tasks/{task['id']}", json={"state": "em-andamento"}, headers=AUTH).status_code == 200
    run = wait_run(client, runs_of(engine, automation_id)[0]["id"])
    out = run["steps"]["gatilho"]["saida"]
    assert out["projeto"] == "Alfa" and out["de"] == "pendente" and out["para"] == "em-andamento" and out["id"] == task["id"]


def test_brain_note_event_after_the_first_index(core, settings):
    client, engine, brain_index = core.client, core.app.state.engine, core.app.state.brain
    automation_id = make(client, event_flow("brain.nota", {"tipo": "decisao"}), publish=True, active=True)
    brain_index.refresh(max_age=0)  # a primeira leitura (o vault como estava) não dispara nada
    folder = settings.brain / "01-PROJETOS" / "Alfa" / "decisoes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Fila no webhook.md").write_text('---\ntipo: decisao\nprojeto: "[[Alfa]]"\n---\n\n# Fila\n', encoding="utf-8")
    brain_index.refresh(max_age=0)
    run = wait_run(client, runs_of(engine, automation_id)[0]["id"])
    out = run["steps"]["gatilho"]["saida"]
    assert out["titulo"] == "Fila no webhook" and out["tipo"] == "decisao" and out["projeto"] == "Alfa" and out["caminho"].endswith("Fila no webhook.md")


def fake_agent_session(manager, session_id: str, kind: str = "claude") -> SimpleNamespace:
    session = SimpleNamespace(
        id=session_id, kind=kind, title="Claude 1", cwd="/tmp/projeto", status="working", atencao=None, status_desde=time.time(),
        exit_code=None, statusline=None, created_at=time.time(), account=None, tag=None, hibernando=False, agent=None,
    )  # fmt: skip
    manager.sessions[session_id] = session
    return session


def test_agent_finished_and_failed_events(core):
    client, engine, manager = core.client, core.app.state.engine, core.app.state.manager
    done = make(client, event_flow("agente.terminou", nome="Terminou"), publish=True, active=True)
    failed = make(client, event_flow("agente.errou", nome="Errou"), publish=True, active=True)
    session = fake_agent_session(manager, "ag-ev")
    try:
        response = client.post("/hooks/event?session=ag-ev&name=Stop", json={"last_assistant_message": "Pronto, testes verdes."}, headers=AUTH)
        assert response.status_code == 204
        run = wait_run(client, runs_of(engine, done)[0]["id"])
        out = run["steps"]["gatilho"]["saida"]
        assert out["sessao"] == "ag-ev" and out["cli"] == "claude" and out["previa"] == "Pronto, testes verdes."
        session.exit_code = 2
        manager._set_status(session, "exited")
        run = wait_run(client, runs_of(engine, failed)[0]["id"])
        assert run["steps"]["gatilho"]["saida"]["codigo"] == 2
    finally:
        manager.sessions.pop("ag-ev", None)


def test_worktree_created_event(core, repo):
    client, engine = core.client, core.app.state.engine
    automation_id = make(client, event_flow("worktree.criada"), publish=True, active=True)
    project = client.post("/projects", json={"path": str(repo)}, headers=AUTH).json()
    created = client.post(f"/projects/{project['id']}/worktrees", json={"name": "corrige-login", "copy_env": False}, headers=AUTH)
    assert created.status_code in (200, 201), created.text
    run = wait_run(client, runs_of(engine, automation_id)[0]["id"])
    out = run["steps"]["gatilho"]["saida"]
    assert out["projeto"] == project["name"] and out["branch"] == "corrige-login" and out["caminho"] == created.json()["path"]


# --- gatilho de sondagem ------------------------------------------------------------------------------


def poll_flow(tool: str = "tarefas", **trigger) -> dict:
    return {
        **code_flow(
            "saida = {'quantos': len(entrada['novos']), 'ids': [i.get('id') for i in entrada['novos']]}",
            gatilho={"tipo": "sondagem", "ferramenta": tool, "argumentos": {"projeto": "Alfa"}, "cada_min": 1, **trigger},
        ),
        "nome": "Novidades",
    }


def test_poll_validation_and_write_tool_refused(core):
    client = core.client
    flow = validate(poll_flow())
    assert flow["gatilho"]["cada_min"] == 5 and flow["gatilho"]["chave"] == "id" and flow["gatilho"]["caminho"] == ""
    with pytest.raises(AutomationError, match="ferramenta"):
        validate({**poll_flow(), "gatilho": {"tipo": "sondagem"}}, strict=True)
    writer = make(client, {**poll_flow("slack-pessoal__mensagem_no_canal"), "nome": "Escreve"})
    refused = client.post(f"/automacoes/{writer}/publicar", json={}, headers=AUTH)
    assert refused.status_code == 400 and "só usa ferramentas de leitura" in refused.json()["detail"]


def test_poll_baseline_then_new_items_with_key_and_path(core, monkeypatch):
    client, engine = core.client, core.app.state.engine
    automation_id = make(client, poll_flow(chave="id", caminho="dados.itens"), publish=True, active=True)
    replies = [
        {"dados": {"itens": [{"id": 1}, {"id": 2}]}},
        {"dados": {"itens": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]}},
        {"dados": {"itens": [{"id": 3}, {"id": 4}]}},
    ]
    calls: list[tuple] = []

    async def fake_call(ctx, name, args, read_only=False):
        calls.append((name, args, read_only))
        return replies[len(calls) - 1]

    monkeypatch.setattr(engine, "_call_tool", fake_call)
    base = datetime.now().astimezone()
    assert client.portal.call(engine.tick, base) == []  # primeira: só anota o que já existe
    state = engine.state(automation_id)
    assert state["ultima_sondagem"] and state["proxima_sondagem"] == pytest.approx(state["ultima_sondagem"] + 300)
    assert client.portal.call(engine.tick, base + timedelta(seconds=30)) == []  # ainda não venceu
    started = client.portal.call(engine.tick, base + timedelta(minutes=6))
    assert len(started) == 1 and calls[-1] == ("tarefas", {"projeto": "Alfa"}, True)
    run = wait_run(client, started[0])
    assert run["origem"] == "sondagem" and run["steps"]["conta"]["saida"] == {"quantos": 2, "ids": [3, 4]}
    assert client.portal.call(engine.tick, base + timedelta(minutes=12)) == []  # nada novo


def test_poll_without_key_uses_a_hash_and_finds_the_first_list(core, monkeypatch):
    client, engine = core.client, core.app.state.engine
    automation_id = make(client, poll_flow(chave=""), publish=True, active=True)
    replies = [{"total": 1, "lista": ["a"]}, {"total": 2, "lista": ["a", "b"]}]

    async def fake_call(ctx, name, args, read_only=False):
        return replies.pop(0)

    monkeypatch.setattr(engine, "_call_tool", fake_call)
    base = datetime.now().astimezone()
    client.portal.call(engine.tick, base)
    started = client.portal.call(engine.tick, base + timedelta(minutes=6))
    assert len(started) == 1
    run = wait_run(client, started[0])
    assert run["steps"]["gatilho"]["saida"]["novos"] == ["b"]
    assert engine.state(automation_id)["sondagem_base"] == 1


# --- passo de agente: troca por cota e sem saída combinada ------------------------------------------


@pytest.fixture
def agent_spy(core, monkeypatch):
    manager = core.app.state.manager
    created: list[dict] = []

    def fake_create(kind, cwd=None, cols=120, rows=32, title=None, account_id=None, tag=None, agent=None, prompt=None, extra_args=None, **_rest):
        session_id = f"ag{len(created) + 1}"
        created.append({"id": session_id, "kind": kind, "cwd": cwd, "title": title, "tag": tag, "agent": agent, "prompt": prompt, "extra": extra_args})
        session = SimpleNamespace(
            id=session_id, title=title or "Agente", pty=SimpleNamespace(write=lambda _b: None), statusline=None, kind=kind, cwd=cwd or "/tmp",
            status="working", atencao=None, status_desde=time.time(), exit_code=None, created_at=time.time(), account=None, tag=tag,
            hibernando=False, agent=None,
        )  # fmt: skip
        manager.sessions[session_id] = session
        return session

    async def no_close(session_id):
        manager.sessions.pop(session_id, None)
        return True

    monkeypatch.setattr(manager, "create", fake_create)
    monkeypatch.setattr(manager, "close", no_close)
    yield created
    for item in created:
        manager.sessions.pop(item["id"], None)


def agent_flow(**step) -> dict:
    return {
        "nome": "Com agente",
        "gatilho": {"tipo": "manual"},
        "passos": [{"id": "fazer", "tipo": "agente", "titulo": "Fazer", "cli": "claude", "pedido": "Faça o resumo de {{hoje}}.", **step}],
        "ligacoes": [{"de": "gatilho", "para": "fazer"}],
    }


def wait_waiter(engine, session_id: str) -> None:
    for _ in range(100):
        if session_id in engine.waiters:
            return
        time.sleep(0.05)
    raise AssertionError("o passo de agente não começou")


def set_five_hour(manager, provider: str, pct: float) -> None:
    account = manager.accounts.active(provider).id
    getattr(manager.usage, provider)[account] = {"five_hour": {"used_pct": pct, "resets_at": None}}


def test_agent_switches_cli_when_the_5h_window_is_over_80(core, agent_spy):
    client, engine, manager = core.client, core.app.state.engine, core.app.state.manager
    set_five_hour(manager, "claude", 86)
    set_five_hour(manager, "codex", 40)
    automation_id = make(client, agent_flow(saida={"resumo": "texto"}))
    run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
    wait_waiter(engine, "ag1")
    assert agent_spy[0]["kind"] == "codex" and agent_spy[0]["extra"] is None  # --allowedTools é só do Claude
    engine.receive_output("ag1", {"resumo": "ok"})
    run = wait_run(client, run_id)
    step = run["steps"]["fazer"]
    assert step["saida"] == {"resumo": "ok", "cli_usado": "codex"}
    assert "rodou no Codex: Claude a 86% da janela de 5 h" in step["nota"]


def test_agent_does_not_switch_when_both_are_hot_or_switch_is_off(core, agent_spy):
    client, engine, manager = core.client, core.app.state.engine, core.app.state.manager
    set_five_hour(manager, "claude", 90)
    set_five_hour(manager, "codex", 85)
    hot = make(client, agent_flow(saida={"resumo": "texto"}))
    run_id = client.post(f"/automacoes/{hot}/testar", json={}, headers=AUTH).json()["execucao"]
    wait_waiter(engine, "ag1")
    assert agent_spy[0]["kind"] == "claude"
    engine.receive_output("ag1", {"resumo": "ok"})
    assert "cli_usado" not in wait_run(client, run_id)["steps"]["fazer"]["saida"]
    set_five_hour(manager, "codex", 10)
    off = make(client, {**agent_flow(saida={"resumo": "texto"}, troca_cota=False), "nome": "Sem troca"})
    run_id = client.post(f"/automacoes/{off}/testar", json={}, headers=AUTH).json()["execucao"]
    wait_waiter(engine, "ag2")
    assert agent_spy[1]["kind"] == "claude"
    engine.receive_output("ag2", {"resumo": "ok"})
    wait_run(client, run_id)


def test_agent_without_output_shape_ends_on_stop_with_last_message(core, agent_spy):
    client, engine = core.client, core.app.state.engine
    automation_id = make(client, agent_flow(saida={}, onde="visivel", ferramentas=["*"]))
    run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
    wait_waiter(engine, "ag1")
    spy = agent_spy[0]
    assert spy["prompt"].startswith("Faça o resumo de 2") and "`saida`" not in spy["prompt"]  # o pedido vai como está
    # ["*"]: todas as ferramentas da central, que também não pedem licença (v1.0.0: o passo não trava)
    assert spy["extra"] == ["--allowedTools", "mcp__metis"] and "ag1" not in engine.hub.session_tools
    response = client.post("/hooks/event?session=ag1&name=Stop", json={"last_assistant_message": "Resumo feito."}, headers=AUTH)
    assert response.status_code == 204
    run = wait_run(client, run_id)
    assert run["status"] == "ok" and run["steps"]["fazer"]["saida"] == {"texto": "Resumo feito."}
    assert "ag1" in core.app.state.manager.sessions  # visível: o terminal fica aberto


# --- rotinas como automações ---------------------------------------------------------------------------


def legacy_routine(settings, **changes) -> str:
    store = RoutineStore(settings.home)
    data = {"name": "Check-in de estudo", "agent": "", "cli": "claude", "days": "todos", "time": "20:50", "catchup": 45,
            "notify": True, "active": True, "prompt": "São 20h50: como foi o estudo?", **changes}  # fmt: skip
    routine = store.save(data)
    return routine.id


def test_migration_turns_routines_into_automations_once(settings, accounts):
    routine_id = legacy_routine(settings)
    store = RoutineStore(settings.home)
    slot = datetime.now().astimezone().replace(hour=7, minute=0, second=0, microsecond=0)
    store.record(routine_id, slot, "rodou", "s0")
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    automations, engine = app.state.automations, app.state.engine
    automation_id = f"rotina-{routine_id}"
    assert automations.ids() == [automation_id]
    flow = automations.published(automation_id)
    assert flow["gatilho"]["tipo"] == "agendado" and flow["gatilho"]["hora"] == "20:50" and flow["gatilho"]["aviso"] is True
    assert flow["gatilho"]["recupera_min"] == 45 and flow["gatilho"]["dias"] == list(range(7))
    step = flow["passos"][0]
    assert step["tipo"] == "agente" and step["pedido"] == "São 20h50: como foi o estudo?" and step["onde"] == "visivel" and step["saida"] == {}
    state = engine.state(automation_id)
    assert state["ativa"] == 1 and state["ultima_hora"] == pytest.approx(slot.timestamp())
    text = (settings.home / "rotinas" / f"{routine_id}.md").read_text(encoding="utf-8")
    assert "ativa: não" in text and f"migrada: {automation_id}" in text and text.rstrip().endswith("como foi o estudo?")
    legacy = RoutineStore(settings.home).get(routine_id)
    assert not legacy.active and legacy.migrated == automation_id
    assert decide(legacy, datetime.now().astimezone(), None) is None  # o agendador antigo não roda de novo
    # Subir de novo não cria outra automação.
    create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    assert automations.ids() == [automation_id]


def test_migrated_routine_runs_once_on_the_engine(settings, accounts, monkeypatch):
    legacy_routine(settings, time="23:58", notify=False)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    engine, manager = app.state.engine, app.state.manager
    created: list[dict] = []

    def fake_create(kind, cwd=None, title=None, tag=None, agent=None, prompt=None, **_rest):
        created.append({"kind": kind, "title": title, "tag": tag, "prompt": prompt})
        return SimpleNamespace(id=f"r{len(created)}", title=title or "Claude", statusline=None)

    with TestClient(app) as client:
        monkeypatch.setattr(manager, "create", fake_create)
        with engine._connect() as con:
            con.execute("update estado set desde = ?, ultima_hora = null", (time.time() - 3 * 86400,))
        slot = datetime.now().astimezone().replace(hour=23, minute=58, second=0, microsecond=0)
        started = client.portal.call(engine.tick, slot + timedelta(seconds=30))
        assert len(started) == 1 and client.portal.call(engine.tick, slot + timedelta(minutes=1)) == []
        for _ in range(100):
            if created:
                break
            time.sleep(0.05)
        assert created[0] == {"kind": "claude", "title": "Check-in de estudo", "tag": "rotina", "prompt": "São 20h50: como foi o estudo?"}
        runs = client.get("/rotinas", headers=AUTH).json()["runs"]
        assert runs[0]["status"] == "rodou" and runs[0]["slot"] == pytest.approx(slot.timestamp()) and runs[0]["session"] == "r1"


def test_routine_routes_keep_the_old_format_on_top_of_automations(settings, accounts, monkeypatch):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    created: list[dict] = []

    def fake_create(kind, cwd=None, title=None, tag=None, agent=None, prompt=None, **_rest):
        created.append({"kind": kind, "cwd": cwd, "title": title, "tag": tag, "prompt": prompt})
        return SimpleNamespace(id="s9", title=title or "Claude", statusline=None)

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.manager, "create", fake_create)
        body = {"name": "Revisão da noite", "days": [0, 1, 2, 3, 4, 5, 6], "time": "23:59", "catchup": 0, "notify": False, "prompt": "Revise o dia.", "folder": "/tmp"}
        made = client.post("/rotinas", json=body, headers=AUTH)
        assert made.status_code == 201
        routine = made.json()
        assert routine["id"] == "revisao-da-noite" and routine["catchup"] == 0 and routine["active"] is True and routine["next"]
        assert set(routine) >= {"id", "name", "agent", "cli", "folder", "days", "time", "catchup", "notify", "active", "prompt", "created", "updated_at", "next"}
        listing = client.get("/automacoes", headers=AUTH).json()
        assert [a["id"] for a in listing] == ["rotina-revisao-da-noite"] and listing[0]["ativa"] is True  # aparece nas Automações
        again = client.post("/rotinas", json=body, headers=AUTH).json()
        assert again["id"] == "revisao-da-noite-2"
        run = client.post("/rotinas/revisao-da-noite/rodar", headers=AUTH).json()
        assert run["status"] == "manual" and run["session"] == "s9" and run["routine"] == "revisao-da-noite"
        assert created[0] == {"kind": "claude", "cwd": "/tmp", "title": "Revisão da noite", "tag": "rotina", "prompt": "Revise o dia."}
        updated = client.put("/rotinas/revisao-da-noite", json={**body, "prompt": "Revise a semana.", "active": False}, headers=AUTH).json()
        assert updated["prompt"] == "Revise a semana." and updated["active"] is False
        assert app.state.automations.published("rotina-revisao-da-noite")["passos"][0]["pedido"] == "Revise a semana."
        assert client.put("/rotinas/nao-existe", json=body, headers=AUTH).status_code == 404
        today = client.get("/hoje", headers=AUTH).json()
        assert [s["routine"]["id"] for s in today["slots"]] == ["revisao-da-noite-2"] and today["manual"][0]["session"] == "s9"
        assert client.delete("/rotinas/revisao-da-noite", headers=AUTH).status_code == 204
        assert client.post("/rotinas/revisao-da-noite/rodar", headers=AUTH).status_code == 404
        assert [r["id"] for r in client.get("/rotinas", headers=AUTH).json()["routines"]] == ["revisao-da-noite-2"]
