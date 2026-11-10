"""v1.0: correções da revisão da v0.9.8 parte 3 (conectores e kanban).

GitHub com o campo do token vazio, aprovação das ferramentas de MCP de fora, MCP por stdio que
não termina o aperto de mão, clientes HTTP fechados, Agenda e Drive do Google, rótulos e id das
tarefas, a fila do Auto gravada com o id antigo, a prévia do Stop fora do loop e as listas do
ClickUp ao mesmo tempo."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from harness_core import app as app_mod
from harness_core import connectors as connectors_mod
from harness_core import google as google_api
from harness_core.app import create_app
from harness_core.clickup_rest import ClickupBoard
from harness_core.connectors import ConnectorAccount, ConnectorStore, tool_mode
from harness_core.kanban import Kanban
from harness_core.kanban_auto import AutoQueue
from harness_core.keychain import MemoryVault
from harness_core.mcp_client import McpError
from harness_core.mcp_registry import McpRegistry
from harness_core.stdio_client import StdioClient
from harness_core.vault import Vault

from .test_v098c_conectores import _mcp_answer, connect_google, fake, http, make_hub, rpc  # noqa: F401
from .test_v098c_kanban import AUTH, core, hook, write_project  # noqa: F401


def old_id(text: str) -> str:
    """O id da v0.9.8 e da v0.9.9: hash do texto com os rótulos."""
    return hashlib.sha1(text.lower().encode("utf-8")).hexdigest()[:8]


# --- GitHub: o campo do token vazio ------------------------------------------------------------


def test_github_route_accepts_the_empty_token_as_null(settings, accounts, http):  # noqa: F811
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, keychain=MemoryVault(), http=http, run_scheduler=False)
    with TestClient(app) as client:
        app.state.connectors.gh = lambda args: "gho-bom"
        # A tela da v0.9.8 mandava null com o campo vazio, e o núcleo respondia 422.
        answer = client.post("/conectores/github", json={"nome": "", "token": None}, headers=AUTH)
        assert answer.status_code == 201 and answer.json()["meta"]["login"] == "pedroaugusto"


# --- MCP de fora: sem readOnlyHint, pede aprovação --------------------------------------------

DB = "https://banco.exemplo.com/mcp"
DB_TOOLS = [
    {"name": "query", "inputSchema": {"type": "object"}},  # roda qualquer SQL, até DELETE
    {"name": "list_tables", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
]


def test_external_tool_without_annotation_waits_for_approval_unless_its_mode_says_free(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return _mcp_answer(json.loads(request.content), DB_TOOLS)

    db_store = ConnectorStore(settings.home, MemoryVault(), lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    account = db_store.add_mcp_http("Banco", DB, "nenhuma", "", "")
    hub, token = make_hub(settings, db_store)
    tools = {t.name: t for t in hub.tools_for(hub.context(token))}
    query, tables = tools[f"{account.id}__query"], tools[f"{account.id}__list_tables"]
    assert query.write and not tables.write
    assert tool_mode(db_store.get(account.id), query.name, query.write) == "aprovacao"
    assert rpc(hub, token, "tools/call", {"name": tables.name, "arguments": {}})["result"]["content"][0]["text"] == "feito: list_tables"

    async def refuse_query() -> dict:
        call = asyncio.create_task(hub.handle(token, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": query.name, "arguments": {}}}))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if hub.pending:
                break
        assert hub.pending, "o query de um MCP de fora sem anotação precisa esperar a aprovação"
        hub.decide(next(iter(hub.pending)), False)
        return await call

    assert "recusou" in asyncio.run(refuse_query())["result"]["content"][0]["text"]
    # O modo escolhido na tela (v0.9.9) vale antes da regra: livre roda sem perguntar.
    db_store.update(account.id, tool_modes={query.name: "livre"})
    free = rpc(hub, token, "tools/call", {"name": query.name, "arguments": {}})["result"]
    assert free["content"][0]["text"] == "feito: query" and not hub.pending


# --- MCP por stdio --------------------------------------------------------------------------

SILENT_FIRST = r'''
import json, os, sys
marker = sys.argv[1]
first = not os.path.exists(marker)
open(marker, "a").close()
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg or first:
        continue  # o primeiro processo nunca responde, nem o initialize
    if msg["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "lento"}}
    else:
        result = {"tools": [{"name": "eco", "inputSchema": {"type": "object"}}]}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
'''


def test_stdio_handshake_that_fails_closes_the_process_and_the_next_call_starts_again(tmp_path):
    script = tmp_path / "servidor.py"
    script.write_text(SILENT_FIRST, encoding="utf-8")
    client = StdioClient(f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {shlex.quote(str(tmp_path / 'ja-subiu'))}", timeout=1)
    try:
        with pytest.raises(McpError, match="initialize"):
            client.tools()
        assert client._proc is None  # o processo que não respondeu foi fechado
        assert [t["name"] for t in client.tools()] == ["eco"] and client.server["name"] == "lento"
    finally:
        client.close()


LEFTOVER = r'''
import json, subprocess, sys, time
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    if msg["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "neto"}}
    elif msg["method"] == "tools/list":
        result = {"tools": []}
    elif msg["params"]["name"] == "sair":
        # Um neto herda o stdout e o segura aberto por 1,5 s depois que este processo sai.
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])
        sys.exit(3)
    else:
        time.sleep(2.5)  # "lento": responde depois que o stdout do processo anterior fecha
        result = {"content": [{"type": "text", "text": "ok"}]}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
'''


def test_stdio_end_of_the_old_process_does_not_reach_the_new_one(tmp_path):
    script = tmp_path / "servidor.py"
    script.write_text(LEFTOVER, encoding="utf-8")
    client = StdioClient(f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}", timeout=0.5)
    try:
        client.tools()
        with pytest.raises(McpError):
            client.call("sair", {})  # o processo sai, mas o stdout dele segue aberto pelo neto
        client.timeout = 6
        # Sobe outro processo; o fim do stdout do anterior chega no meio desta chamada e não a derruba.
        assert client.call("lento", {})["content"][0]["text"] == "ok"
    finally:
        client.close()


def test_two_first_calls_at_once_share_one_stdio_client(settings, monkeypatch):
    made: list[object] = []

    class SlowStdio:
        def __init__(self, *_args, **_kwargs) -> None:
            time.sleep(0.2)  # tempo para a outra chamada chegar no meio
            made.append(self)

        def close(self) -> None:
            pass

    monkeypatch.setattr(connectors_mod, "StdioClient", SlowStdio)
    local = ConnectorStore(settings.home, MemoryVault())
    local._save([ConnectorAccount(id="mcp-local", kind="mcp", name="Local", created=0, meta={"transporte": "stdio"})])
    local.vault.set("conector:mcp-local", json.dumps({"comando": "servidor-mcp", "env": {}, "pasta": ""}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(lambda _: local.mcp("mcp-local"), range(2))
    assert first is second and len(made) == 1


# --- clientes HTTP fechados ------------------------------------------------------------------


class Counting:
    """Fábrica de clientes HTTP que lembra de todos, para ver se foram fechados."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.made: list[httpx.Client] = []

    def __call__(self) -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(self.handler))
        self.made.append(client)
        return client


def test_google_reuses_one_client_and_one_off_checks_close_theirs(settings, fake):  # noqa: F811
    factory = Counting(fake.handler)
    counted = ConnectorStore(settings.home, MemoryVault(), factory, gh=lambda args: "gho-bom")
    url = connect_google(counted)
    account = counted.finish_oauth(parse_qs(urlparse(url).query)["state"][0], "c")
    assert factory.made[-1].is_closed  # a conferência do e-mail da conta
    api = counted.google(account.id)
    assert counted.google(account.id) is api  # cada ferramenta usa o mesmo cliente
    api.userinfo()
    assert not api.http.is_closed
    counted.remove(account.id)
    assert api.http.is_closed
    before = len(factory.made)
    counted.add_github("")
    McpRegistry(factory).search("notion")
    later = factory.made[before:]
    assert len(later) == 2 and all(c.is_closed for c in later)  # a conferência do GitHub e a busca no catálogo


# --- Google: Agenda e Drive ----------------------------------------------------------------------


def google_with(seen: list[httpx.Request], answer: dict) -> google_api.Google:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=answer)

    return google_api.Google(lambda: "t", lambda: "t", httpx.Client(transport=httpx.MockTransport(handler)))


def test_calendar_range_includes_the_last_day_and_holiday_calendar_ids_are_encoded():
    seen: list[httpx.Request] = []
    api = google_with(seen, {"items": []})
    api.events("2026-11-10", "2026-11-10", calendar="pt-br.brazilian#holiday@group.v.calendar.google.com")
    params = dict(seen[-1].url.params)
    assert params["timeMin"].startswith("2026-11-10T00:00:00") and params["timeMax"].startswith("2026-11-11T00:00:00")
    assert seen[-1].url.raw_path.decode().startswith("/calendar/v3/calendars/pt-br.brazilian%23holiday%40group.v.calendar.google.com/events")
    api.events("2026-11-10T09:00", "2026-11-10T18:00")  # com hora: como veio
    params = dict(seen[-1].url.params)
    assert params["timeMin"].startswith("2026-11-10T09:00:00") and params["timeMax"].startswith("2026-11-10T18:00:00")


def test_all_day_event_ending_on_the_same_day_becomes_one_day():
    seen: list[httpx.Request] = []
    api = google_with(seen, {"summary": "Feriado"})
    api.create_event("Feriado", "2026-11-10", "2026-11-10")
    assert json.loads(seen[-1].content)["end"] == {"date": "2026-11-11"}
    api.create_event("Viagem", "2026-11-10", "2026-11-13")  # fim depois do início: como veio
    assert json.loads(seen[-1].content)["end"] == {"date": "2026-11-13"}


def test_drive_search_tells_raw_queries_from_plain_text():
    seen: list[httpx.Request] = []
    api = google_with(seen, {"files": []})
    api.drive_search("name = 'Relatório'")
    assert dict(seen[-1].url.params)["q"] == "name = 'Relatório'"
    api.drive_search("'pasta1' in parents and trashed = false")
    assert dict(seen[-1].url.params)["q"] == "'pasta1' in parents and trashed = false"
    api.drive_search("contrato contains cláusula")
    assert dict(seen[-1].url.params)["q"] == "(name contains 'contrato contains cláusula' or fullText contains 'contrato contains cláusula') and trashed = false"


# --- kanban: rótulos, marca da linha e id ----------------------------------------------------------

MARKS = """---
tipo: projeto
---

# Alfa

## ✅ Próximas ações

- [ ] Corrigir bug #123 #urgente
- [-] ~~ideia velha~~ ✅ 2026-10-01
- [/] Escrevendo o texto
- [x] Feita sem data
"""


def test_set_labels_keeps_the_mark_the_state_tag_and_the_date(settings):
    path = write_project(settings.brain, MARKS)
    kanban = Kanban(Vault(settings.brain))
    tasks = {t["texto"]: t for t in kanban.tasks("Alfa")}
    kanban.set_labels("Alfa", tasks["~~ideia velha~~"]["id"], ["front"])
    kanban.set_labels("Alfa", tasks["Escrevendo o texto"]["id"], ["texto"])
    kanban.set_labels("Alfa", tasks["Feita sem data"]["id"], ["back"])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "- [-] ~~ideia velha~~ #front ✅ 2026-10-01" in lines  # continua cancelada, não vira feita
    assert "- [/] Escrevendo o texto #texto" in lines
    assert "- [x] Feita sem data #back" in lines  # sem ganhar a data de hoje


def test_add_keeps_the_labels_typed_in_the_text(settings):
    path = write_project(settings.brain, MARKS)
    kanban = Kanban(Vault(settings.brain))
    task = kanban.add("Alfa", "corrigir login #bug", labels=["front", "Bug"])
    assert task["rotulos"] == ["bug", "front"] and task["texto"] == "corrigir login"
    assert "- [ ] corrigir login #bug #front" in path.read_text(encoding="utf-8").splitlines()


def test_task_id_survives_label_changes_and_the_old_id_still_finds_the_task(settings):
    write_project(settings.brain, MARKS)
    kanban = Kanban(Vault(settings.brain))
    first = kanban.tasks("Alfa")[0]
    assert first["id"] == old_id("Corrigir bug #123")  # o #123 é texto, não rótulo
    relabeled = kanban.set_labels("Alfa", first["id"], ["urgente", "noite"])
    assert relabeled["id"] == first["id"] and relabeled["rotulos"] == ["urgente", "noite"]
    # Id gravado antes da v1.0 (com os rótulos daquele tempo), como na fila do Auto.
    legacy = old_id("Corrigir bug #123 #urgente #noite")
    moved = kanban.move("Alfa", legacy, "em-teste")
    assert moved["id"] == first["id"] and moved["state"] == "em-teste"
    assert kanban.add_subtask("Alfa", legacy, "rodar os testes")["subtasks_total"] == 1
    assert kanban.current_ids("Alfa")[legacy] == first["id"]
    with pytest.raises(Exception, match="não encontrada"):
        kanban.move("Alfa", "zzzzzzzz", "em-teste")


def test_auto_queue_saved_with_old_ids_moves_to_the_new_ones(settings):
    write_project(settings.brain, MARKS)
    kanban = Kanban(Vault(settings.brain))
    current = kanban.tasks("Alfa")[0]["id"]
    legacy = old_id("Corrigir bug #123 #urgente")
    assert legacy != current
    queue_file = settings.home / "kanban-auto.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    items = [
        {"id": "a1", "projeto": "Alfa", "tarefa": legacy, "texto": "Corrigir bug", "criado": 1.0, "status": "fila"},
        {"id": "a2", "projeto": "Sumiu", "tarefa": "abcd1234", "texto": "Outra", "criado": 2.0, "status": "feito", "fim": 3.0},
    ]
    queue_file.write_text(json.dumps({"limite": 1, "itens": items}), encoding="utf-8")
    published: list[dict] = []

    async def never(_item):  # pragma: no cover - a fila não roda neste teste
        raise AssertionError

    auto = AutoQueue(queue_file, start=never, move=lambda *_: None, publish=published.append)
    auto.update_task_ids(kanban.current_ids)
    assert [i.tarefa for i in auto.items] == [current, "abcd1234"]
    saved = json.loads(queue_file.read_text(encoding="utf-8"))["itens"]
    assert [i["tarefa"] for i in saved] == [current, "abcd1234"] and published


# --- a prévia do Stop fora do loop, uma leitura só --------------------------------------------------


def test_stop_preview_is_read_off_the_loop_and_reused_by_the_board(core, tmp_path, monkeypatch, statusline_payload):  # noqa: F811
    client, app, *_ = core
    reads: list[str] = []
    real = app_mod.last_messages

    def spy(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            reads.append("loop")
        except RuntimeError:
            reads.append("thread")
        return real(*args, **kwargs)

    monkeypatch.setattr(app_mod, "last_messages", spy)
    session_id = client.post("/sessions", json={"kind": "claude"}, headers=AUTH).json()["id"]
    transcript = tmp_path / "conversa.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Pronto, terminei."}]}}) + "\n",
        encoding="utf-8",
    )
    client.post(f"/hooks/statusline?session={session_id}", json={**statusline_payload, "transcript_path": str(transcript)}, headers=AUTH)
    hook(client, session_id, "Stop", {"transcript_path": str(transcript)})
    events = client.get(f"/atividade/eventos?sessao={session_id}", headers=AUTH).json()["eventos"]
    assert events[0]["kind"] == "terminou" and events[0]["preview"] == "Pronto, terminei."
    assert reads == ["thread"]  # lida uma vez, numa thread, e não no loop do núcleo
    for _ in range(2):  # o painel relê a cada 4 s: com o transcript igual, vem da memória
        agent = next(a for a in client.get("/agentes/painel", headers=AUTH).json()["agentes"] if a["id"] == session_id)
        assert agent["previa"] == "Pronto, terminei."
    assert reads == ["thread"]


# --- ClickUp: as listas dos espaços ao mesmo tempo -----------------------------------------------------


def test_clickup_lists_of_each_space_load_at_the_same_time(settings):
    both = threading.Barrier(2, timeout=3)  # só passa se os dois espaços pedirem juntos

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v2")
        if path == "/team":
            return httpx.Response(200, json={"teams": [{"id": "T1", "name": "Seller Pro"}]})
        if path == "/team/T1/space":
            return httpx.Response(200, json={"spaces": [{"id": "S1", "name": "Marketing"}, {"id": "S2", "name": "Produto"}]})
        if path.endswith("/folder"):
            try:
                both.wait()
            except threading.BrokenBarrierError:
                return httpx.Response(500, json={"err": "os espaços vieram um depois do outro"})
            space = path.split("/")[2]
            return httpx.Response(200, json={"folders": [{"id": f"F{space}", "name": "Pasta", "lists": [{"id": f"L{space}", "name": f"Lista {space}"}]}]})
        if path.endswith("/list"):
            return httpx.Response(200, json={"lists": []})
        return httpx.Response(404, json={"err": "não achei"})

    vault = MemoryVault()
    settings.home.mkdir(parents=True, exist_ok=True)
    (settings.home / "conectores.json").write_text(json.dumps([{"id": "clickup-sp", "kind": "clickup", "name": "ClickUp SP", "created": 0, "meta": {}}]), encoding="utf-8")
    vault.set("conector:clickup-sp:api", "pk_bom")
    board = ClickupBoard(settings.home, ConnectorStore(settings.home, vault), lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    found = board.lists("clickup-sp")
    assert [(item["id"], item["espaco"]) for item in found] == [("LS1", "Marketing"), ("LS2", "Produto")]  # a ordem dos espaços fica
