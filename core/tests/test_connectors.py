"""v0.6: conectores (Slack e ClickUp), central de MCP, aprovação, lembretes e Atividade."""

import asyncio
import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from harness_core.activity import ActivityLog
from harness_core.app import create_app
from harness_core.brain_index import BrainIndex
from harness_core.claude_settings import mcp_args
from harness_core.connectors import ConnectorError, ConnectorStore
from harness_core.kanban import Kanban
from harness_core.keychain import MemoryVault
from harness_core.mcp_hub import Hub
from harness_core.vault import Vault
from harness_core.when import WhenError, parse_when

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
CLICKUP = "https://mcp.clickup.com"


class FakeServices:
    """Slack e ClickUp de mentira, com o registro do que a MÊTIS pediu."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.sse = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://slack.com/api/"):
            method = url.rsplit("/", 1)[1]
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.calls.append((method, form))
            if request.headers.get("authorization") != "Bearer xoxb-bom":
                return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
            answers = {
                "auth.test": {"ok": True, "team": "Pedro", "team_id": "T1", "user": "metis", "url": "https://pedro.slack.com"},
                "users.lookupByEmail": {"ok": True, "user": {"id": "U9", "real_name": "Pedro Aquino", "tz": "America/Sao_Paulo"}},
                "conversations.open": {"ok": True, "channel": {"id": "D42"}},
                "chat.postMessage": {"ok": True, "channel": form.get("channel"), "ts": "1.2"},
                "chat.scheduleMessage": {"ok": True, "channel": form.get("channel"), "scheduled_message_id": "Q1", "post_at": int(form.get("post_at", 0))},
            }
            return httpx.Response(200, json=answers.get(method, {"ok": False, "error": "unknown_method"}))
        if url == f"{CLICKUP}/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(200, json={"resource": f"{CLICKUP}/mcp", "authorization_servers": [CLICKUP]})
        if url == f"{CLICKUP}/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": f"{CLICKUP}/oauth/authorize",
                    "token_endpoint": f"{CLICKUP}/oauth/token",
                    "registration_endpoint": f"{CLICKUP}/oauth/register",
                    "scopes_supported": ["read", "write"],
                },
            )
        if url == f"{CLICKUP}/oauth/register":
            self.calls.append(("register", json.loads(request.content)))
            return httpx.Response(201, json={"client_id": "cli-1"})
        if url == f"{CLICKUP}/oauth/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.calls.append(("token", form))
            return httpx.Response(200, json={"access_token": "tok-clickup", "token_type": "Bearer"})
        if url == f"{CLICKUP}/mcp":
            if request.headers.get("authorization") != "Bearer tok-clickup":
                return httpx.Response(401)
            message = json.loads(request.content)
            self.calls.append(("mcp", message))
            if "id" not in message:
                return httpx.Response(202)
            results = {
                "initialize": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "clickup"}},
                "tools/list": {
                    "tools": [
                        {"name": "search_tasks", "description": "Busca tarefas", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
                        {"name": "create_task", "description": "Cria tarefa", "inputSchema": {"type": "object"}},
                    ]
                },
                "tools/call": {"content": [{"type": "text", "text": f"feito: {message.get('params', {}).get('name')}"}]},
            }
            body = {"jsonrpc": "2.0", "id": message["id"], "result": results[message["method"]]}
            headers = {"mcp-session-id": "sess-1"}
            if self.sse:
                return httpx.Response(200, text=f"event: message\ndata: {json.dumps(body)}\n\n", headers={**headers, "content-type": "text/event-stream"})
            return httpx.Response(200, json=body, headers=headers)
        return httpx.Response(404)


@pytest.fixture
def fake() -> FakeServices:
    return FakeServices()


@pytest.fixture
def http(fake):
    return lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def store(settings, http) -> ConnectorStore:
    return ConnectorStore(settings.home, MemoryVault(), http)


# --- datas em português ------------------------------------------------------------------


def test_parse_when_in_portuguese():
    now = datetime(2026, 11, 8, 11, 30).astimezone()  # domingo
    assert parse_when("sexta 9h", now).strftime("%d/%m %H:%M") == "13/11 09:00"
    assert parse_when("amanhã 14:30", now).strftime("%d/%m %H:%M") == "09/11 14:30"
    assert parse_when("em 20 min", now).strftime("%H:%M") == "11:50"
    assert parse_when("13/11 às 9", now).strftime("%d/%m %H:%M") == "13/11 09:00"
    assert parse_when("10h", now).strftime("%d/%m %H:%M") == "09/11 10:00"  # hoje já passou
    assert parse_when("2026-11-13T09:30:00-03:00", now).hour in (9, 12)  # com fuso explícito
    with pytest.raises(WhenError):
        parse_when("hoje 10h", now)
    with pytest.raises(WhenError):
        parse_when("quando der", now)


# --- conectores ----------------------------------------------------------------------------


def test_slack_connect_stores_token_in_vault_not_in_file(store, fake, settings):
    account = store.add_slack("Slack pessoal", "xoxb-bom", "pedro@example.com")
    assert account.id == "slack-pessoal" and account.reminders
    assert account.meta["dm"] == "D42" and account.meta["user_id"] == "U9" and account.meta["team"] == "Pedro"
    assert store.vault.get("conector:slack-pessoal") == "xoxb-bom"
    assert "xoxb" not in (settings.home / "conectores.json").read_text()
    second = store.add_slack("Slack Seller Pro", "xoxb-bom", "pedro@example.com")
    assert second.id == "slack-seller-pro" and not second.reminders  # só a primeira recebe lembretes
    store.update("slack-seller-pro", reminders=True)
    assert [a.id for a in store.list() if a.reminders] == ["slack-seller-pro"]
    store.remove("slack-pessoal")
    assert store.vault.get("conector:slack-pessoal") is None


def test_slack_connect_rejects_bad_token(store):
    with pytest.raises(ConnectorError, match="xoxb"):
        store.add_slack("x", "xoxp-usuario", "a@b.c")
    with pytest.raises(ConnectorError, match="invalid_auth"):
        store.add_slack("x", "xoxb-ruim", "a@b.c")


def test_clickup_oauth_registers_client_with_pkce_and_lists_tools(store, fake):
    url = store.start_oauth("clickup", "ClickUp pessoal", "http://127.0.0.1:5555/conectores/oauth/retorno")
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith(f"{CLICKUP}/oauth/authorize?")
    assert query["client_id"] == "cli-1" and query["code_challenge_method"] == "S256" and query["resource"] == f"{CLICKUP}/mcp"
    assert query["redirect_uri"].startswith("http://127.0.0.1:")
    register = next(body for name, body in fake.calls if name == "register")
    assert register["token_endpoint_auth_method"] == "none"
    account = store.finish_oauth(query["state"], "codigo-1")
    token_call = next(body for name, body in fake.calls if name == "token")
    assert token_call["code_verifier"] and token_call["code"] == "codigo-1"
    assert account.id == "clickup-pessoal" and account.meta["tools"] == 2
    assert json.loads(store.vault.get("conector:clickup-pessoal"))["access_token"] == "tok-clickup"
    with pytest.raises(ConnectorError, match="expirou"):
        store.finish_oauth(query["state"], "codigo-1")  # o mesmo state não vale duas vezes


def test_mcp_client_reads_event_stream_answers(store, fake):
    fake.sse = True
    url = store.start_oauth("clickup", "ClickUp", "http://127.0.0.1:1/r")
    state = parse_qs(urlparse(url).query)["state"][0]
    account = store.finish_oauth(state, "c")
    assert account.meta["tools"] == 2
    assert store.mcp(account.id).call("search_tasks", {})["content"][0]["text"] == "feito: search_tasks"


# --- central de MCP ----------------------------------------------------------------------------


def make_hub(settings, store, events, allowed=None, cwd=None):
    vault = Vault(settings.brain)
    hub = Hub(
        connectors=store,
        brain=BrainIndex(vault, settings.home / "brain.db"),
        kanban=Kanban(vault),
        vault=vault,
        activity=ActivityLog(settings.home / "atividade.db"),
        publish=events.append,
        session_info=lambda _s: {"who": "Claude", "cwd": cwd, "allowed": allowed},
    )
    return hub, hub.register("sessao-1")


def rpc(hub, token, method, params=None, mid=1):
    return asyncio.run(hub.handle(token, {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}))


def test_hub_lists_builtin_and_account_tools(settings, store):
    store.add_slack("Slack pessoal", "xoxb-bom", "p@e.com")
    events: list[dict] = []
    hub, token = make_hub(settings, store, events)
    init = rpc(hub, token, "initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert init["serverInfo"]["name"] == "metis" and "tools" in init["capabilities"]
    names = {t["name"] for t in rpc(hub, token, "tools/list")["result"]["tools"]}
    assert {"brain_buscar", "tarefas", "tarefa_mover", "lembrete", "slack-pessoal__lembrete", "slack-pessoal__mensagem_no_canal"} <= names
    assert all(len(n) <= 52 for n in names)
    assert asyncio.run(hub.handle("token-falso", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))["error"]["code"] == -32001
    assert asyncio.run(hub.handle(token, {"jsonrpc": "2.0", "method": "notifications/initialized"})) is None


def test_hub_respects_agent_connector_list(settings, store):
    store.add_slack("Slack pessoal", "xoxb-bom", "p@e.com")
    hub, token = make_hub(settings, store, [], allowed=set())
    names = {t["name"] for t in rpc(hub, token, "tools/list")["result"]["tools"]}
    assert "lembrete" in names and not any(n.startswith("slack-") for n in names)
    result = rpc(hub, token, "tools/call", {"name": "slack-pessoal__lembrete", "arguments": {"texto": "x", "quando": "em 5 min"}})["result"]
    assert result["isError"] and "não liberada" in result["content"][0]["text"]


def test_reminder_tool_schedules_slack_message_in_the_dm(settings, store, fake):
    store.add_slack("Slack pessoal", "xoxb-bom", "p@e.com")
    hub, token = make_hub(settings, store, [])
    result = rpc(hub, token, "tools/call", {"name": "lembrete", "arguments": {"texto": "pagar o boleto", "quando": "em 30 min"}})["result"]
    assert not result.get("isError") and "Lembrete agendado" in result["content"][0]["text"]
    method, form = fake.calls[-1]
    assert method == "chat.scheduleMessage" and form["channel"] == "D42" and form["text"] == "⏰ pagar o boleto"
    assert int(form["post_at"]) > datetime.now().timestamp() + 25 * 60


def test_write_tool_waits_for_approval(settings, store, fake):
    store.add_slack("Slack pessoal", "xoxb-bom", "p@e.com")
    events: list[dict] = []
    hub, token = make_hub(settings, store, events)

    async def scenario(approve: bool) -> dict:
        call = asyncio.create_task(hub.handle(token, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "slack-pessoal__mensagem_no_canal", "arguments": {"canal": "#geral", "texto": "oi time"}}}))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if hub.pending:
                break
        pending = next(iter(hub.pending.values()))
        assert pending.summary == "mandar em #geral: “oi time”" and pending.who == "Claude"
        assert hub.decide(pending.id, approve)
        return (await call)["result"]

    approved = asyncio.run(scenario(True))
    assert not approved.get("isError") and fake.calls[-1][0] == "chat.postMessage"
    sent_before = len([c for c in fake.calls if c[0] == "chat.postMessage"])
    denied = asyncio.run(scenario(False))
    assert denied["isError"] and "recusou" in denied["content"][0]["text"]
    assert len([c for c in fake.calls if c[0] == "chat.postMessage"]) == sent_before
    kinds = [e["type"] for e in events]
    assert kinds.count("approval") == 2 and kinds.count("approval.done") == 2
    statuses = [row["status"] for row in hub.activity.recent(5)]
    assert statuses[:2] == ["recusado", "ok"]


def test_clickup_tools_are_prefixed_and_only_writes_need_approval(settings, store, fake):
    url = store.start_oauth("clickup", "ClickUp", "http://127.0.0.1:1/r")
    store.finish_oauth(parse_qs(urlparse(url).query)["state"][0], "c")
    hub, token = make_hub(settings, store, [])
    names = {t["name"] for t in rpc(hub, token, "tools/list")["result"]["tools"]}
    assert {"clickup__search_tasks", "clickup__create_task"} <= names
    result = rpc(hub, token, "tools/call", {"name": "clickup__search_tasks", "arguments": {}})["result"]
    assert result["content"][0]["text"] == "feito: search_tasks" and not hub.pending
    store.update("clickup", approve_writes=False)
    created = rpc(hub, token, "tools/call", {"name": "clickup__create_task", "arguments": {"name": "x"}})["result"]
    assert created["content"][0]["text"] == "feito: create_task"


def test_brain_tools_use_the_project_of_the_session_folder(settings, store, repo):
    root = settings.brain / "01-PROJETOS" / "Alfa"
    root.mkdir(parents=True)
    (root / "Alfa.md").write_text(f'---\ntipo: projeto\ndiretorio: "{repo}"\n---\n\n## ✅ Próximas ações\n\n- [ ] Primeira tarefa\n', encoding="utf-8")
    hub, token = make_hub(settings, store, [], cwd=str(repo))
    listed = rpc(hub, token, "tools/call", {"name": "tarefas", "arguments": {}})["result"]["content"][0]["text"]
    task_id = listed.split("] ", 1)[1].split(":", 1)[0]
    moved = rpc(hub, token, "tools/call", {"name": "tarefa_mover", "arguments": {"id": task_id, "estado": "em-teste"}})["result"]
    assert "em-teste" in moved["content"][0]["text"]
    assert "#em-teste" in (root / "Alfa.md").read_text(encoding="utf-8")


# --- integração com o app e as sessões --------------------------------------------------------


def test_mcp_args_for_claude_and_codex():
    claude = mcp_args("claude", "http://127.0.0.1:5000", "abc")
    config = json.loads(claude[1])["mcpServers"]["metis"]
    assert claude[0] == "--mcp-config" and config == {"type": "http", "url": "http://127.0.0.1:5000/mcp", "headers": {"Authorization": "Bearer abc"}}
    codex = mcp_args("codex", "http://127.0.0.1:5000", "abc")
    assert 'mcp_servers.metis.bearer_token_env_var="METIS_MCP_TOKEN"' in codex and "abc" not in " ".join(codex)


def test_app_routes_for_connectors_reminders_and_mcp(settings, accounts, http, fake):
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, keychain=MemoryVault(), http=http)) as client:
        assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
        created = client.post("/conectores/slack", json={"name": "Slack pessoal", "token": "xoxb-bom", "email": "p@e.com"}, headers=AUTH)
        assert created.status_code == 201 and created.json()["service"] == "Slack"
        assert client.get("/conectores", headers=AUTH).json()["accounts"][0]["id"] == "slack-pessoal"
        assert "chat:write" in client.get("/conectores/slack/manifesto", headers=AUTH).text
        reminder = client.post("/lembretes", json={"texto": "beber água", "quando": "em 15 min"}, headers=AUTH)
        assert reminder.status_code == 201 and "Lembrete agendado" in reminder.json()["message"]
        assert client.post("/lembretes", json={"texto": "x", "quando": "ontem"}, headers=AUTH).status_code == 400
        assert client.post("/conectores/slack-pessoal/teste", headers=AUTH).status_code == 200
        start = client.post("/conectores/oauth/clickup", json={"name": "ClickUp Seller Pro"}, headers=AUTH).json()["url"]
        state = parse_qs(urlparse(start).query)["state"][0]
        assert parse_qs(urlparse(start).query)["redirect_uri"][0] == f"{settings.url}/conectores/oauth/retorno"
        page = client.get("/conectores/oauth/retorno", params={"state": state, "code": "c"})
        assert page.status_code == 200 and "ClickUp Seller Pro conectado" in page.text
        assert client.get("/conectores/oauth/retorno", params={"state": state, "code": "c"}).status_code == 400
        assert client.patch("/conectores/clickup-seller-pro", json={"approve_writes": False}, headers=AUTH).json()["approve_writes"] is False
        assert client.get("/atividade", headers=AUTH).status_code == 200
        assert client.post("/aprovacoes/nada", json={"aprovar": True}, headers=AUTH).status_code == 404
        assert client.delete("/conectores/slack-pessoal", headers=AUTH).status_code == 204
