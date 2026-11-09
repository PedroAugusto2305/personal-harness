"""v0.9.8 parte 3: renovar o login, Notion, GitHub, Google, MCP próprio (HTTP e stdio),
catálogo oficial de MCP, testar conexão e copiar MCP entre o Claude e o Codex."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from harness_core import google as google_api
from harness_core import mcp_configs
from harness_core.activity import ActivityLog
from harness_core.app import create_app
from harness_core.brain_index import BrainIndex
from harness_core.connectors import ConnectorError, ConnectorStore
from harness_core.kanban import Kanban
from harness_core.keychain import MemoryVault
from harness_core.mcp_hub import Hub, _is_read
from harness_core.mcp_registry import McpRegistry, RegistryError
from harness_core.vault import Vault

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
NOTION = "https://mcp.notion.com"
GITHUB_MCP = "https://api.githubcopilot.com/mcp/"
OWN = "https://meu-mcp.exemplo.com"


def _form(request: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def _mcp_answer(message: dict, tools: list[dict]) -> httpx.Response:
    if "id" not in message:
        return httpx.Response(202)
    results = {
        "initialize": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "servidor-falso"}},
        "tools/list": {"tools": tools},
        "tools/call": {"content": [{"type": "text", "text": f"feito: {message.get('params', {}).get('name')}"}]},
    }
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": results[message["method"]]}, headers={"mcp-session-id": "s1"})


class Fake:
    """Notion, GitHub, Google, um MCP próprio e o registro oficial, de mentira."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.valid = {"tok-1"}  # tokens que o MCP do Notion aceita
        self.refresh_ok = True
        self.registry_up = True
        self.google_tokens = {"g-1"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        auth = request.headers.get("authorization", "")
        # --- Notion: OAuth com descoberta e registro dinâmico ---
        if url == f"{NOTION}/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(200, json={"resource": f"{NOTION}/mcp", "authorization_servers": [NOTION]})
        if url == f"{NOTION}/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={"authorization_endpoint": f"{NOTION}/authorize", "token_endpoint": f"{NOTION}/token", "registration_endpoint": f"{NOTION}/register"})
        if url == f"{NOTION}/register":
            return httpx.Response(201, json={"client_id": "cli-notion"})
        if url == f"{NOTION}/token":
            form = _form(request)
            self.calls.append(("token", form))
            if form["grant_type"] == "authorization_code":
                return httpx.Response(200, json={"access_token": "tok-1", "refresh_token": "ref-1", "expires_in": 3600})
            if not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.valid.add("tok-2")
            return httpx.Response(200, json={"access_token": "tok-2", "refresh_token": "ref-2", "expires_in": 3600})
        if url == f"{NOTION}/mcp":
            if auth.removeprefix("Bearer ") not in self.valid:
                return httpx.Response(401)
            message = json.loads(request.content)
            self.calls.append(("notion", message.get("method")))
            return _mcp_answer(message, [{"name": "notion-search", "inputSchema": {"type": "object"}}, {"name": "notion-create-pages", "inputSchema": {"type": "object"}}])
        # --- GitHub ---
        if url == GITHUB_MCP:
            if auth != "Bearer gho-bom":
                return httpx.Response(401, text="Bad credentials")
            message = json.loads(request.content)
            return _mcp_answer(message, [{"name": "get_issue", "inputSchema": {"type": "object"}}, {"name": "create_issue", "inputSchema": {"type": "object"}}])
        if url == "https://api.github.com/user":
            return httpx.Response(200, json={"login": "pedroaugusto"}) if auth == "Bearer gho-bom" else httpx.Response(401)
        # --- MCP próprio por endereço ---
        if url.startswith(f"{OWN}/.well-known/"):
            if "oauth-protected-resource" in url:
                return httpx.Response(200, json={"resource": f"{OWN}/mcp", "authorization_servers": [OWN]})
            return httpx.Response(200, json={"authorization_endpoint": f"{OWN}/auth", "token_endpoint": f"{OWN}/token"})  # sem registro
        if url == f"{OWN}/mcp":
            self.calls.append(("own-auth", auth))
            message = json.loads(request.content)
            return _mcp_answer(message, [{"name": "ping", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}])
        # --- Google ---
        if url == google_api.TOKEN:
            form = _form(request)
            self.calls.append(("google-token", form))
            if form["grant_type"] == "authorization_code":
                return httpx.Response(200, json={"access_token": "g-1", "refresh_token": "g-ref", "expires_in": 3599})
            self.google_tokens.add("g-2")
            return httpx.Response(200, json={"access_token": "g-2", "expires_in": 3599})
        if url.startswith("https://") and "googleapis.com" in url:
            if auth.removeprefix("Bearer ") not in self.google_tokens:
                return httpx.Response(401, json={"error": {"message": "Invalid Credentials"}})
            return self.google(request)
        # --- registro oficial de MCP ---
        if url.startswith("https://registry.modelcontextprotocol.io/v0/servers"):
            self.calls.append(("registry", dict(request.url.params)))
            if not self.registry_up:
                return httpx.Response(503)
            return httpx.Response(200, json=REGISTRY_ANSWER)
        return httpx.Response(404)

    def google(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        params = dict(request.url.params)
        self.calls.append(("google", (request.method, url, params)))
        if url == google_api.USERINFO:
            return httpx.Response(200, json={"email": "pedro@gmail.com"})
        if url == f"{google_api.GMAIL}/messages" and request.method == "GET":
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if url == f"{google_api.GMAIL}/messages/m1":
            if params.get("format") == "full":
                body = base64.urlsafe_b64encode("Olá Pedro,\nsegue o relatório.".encode()).decode().rstrip("=")
                return httpx.Response(200, json={"payload": {"headers": [{"name": "From", "value": "Ana <ana@x.com>"}, {"name": "Subject", "value": "Relatório"}], "mimeType": "multipart/alternative", "parts": [{"mimeType": "text/plain", "body": {"data": body}}]}})
            return httpx.Response(200, json={"snippet": "segue o relat&oacute;rio", "payload": {"headers": [{"name": "From", "value": "Ana <ana@x.com>"}, {"name": "Subject", "value": "Relatório"}, {"name": "Date", "value": "Sun, 8 Nov 2026"}]}})
        if url == f"{google_api.GMAIL}/drafts":
            raw = json.loads(request.content)["message"]["raw"]
            self.calls.append(("draft", base64.urlsafe_b64decode(raw + "==").decode()))
            return httpx.Response(200, json={"id": "d1"})
        if url == f"{google_api.GMAIL}/profile":
            return httpx.Response(200, json={"emailAddress": "pedro@gmail.com"})
        if url == f"{google_api.CALENDAR}/calendars/primary/events":
            if request.method == "POST":
                self.calls.append(("event", json.loads(request.content)))
                return httpx.Response(200, json={"summary": "Reunião", "htmlLink": "https://calendar/1"})
            return httpx.Response(200, json={"items": [{"id": "e1", "summary": "Reunião", "start": {"dateTime": "2026-11-09T10:00:00-03:00"}, "end": {"dateTime": "2026-11-09T11:00:00-03:00"}}]})
        if url == f"{google_api.DRIVE}/files":
            return httpx.Response(403, json={"error": {"message": "Drive API desligada"}}) if params.get("pageSize") == "1" and getattr(self, "drive_off", False) else httpx.Response(200, json={"files": [{"id": "f1", "name": "Plano", "mimeType": "application/vnd.google-apps.document"}]})
        if url == f"{google_api.DRIVE}/files/f1":
            return httpx.Response(200, json={"id": "f1", "name": "Plano", "mimeType": "application/vnd.google-apps.document", "webViewLink": "https://docs/f1"})
        if url == f"{google_api.DRIVE}/files/f1/export":
            return httpx.Response(200, text="Texto do plano")
        return httpx.Response(404, json={"error": {"message": "não achei"}})


REGISTRY_ANSWER = {
    "servers": [
        {
            "server": {
                "name": "com.notion/mcp",
                "title": "Notion",
                "description": "MCP oficial do Notion",
                "version": "1.0.1",
                "websiteUrl": "https://developers.notion.com",
                "remotes": [{"type": "streamable-http", "url": "https://mcp.notion.com/mcp"}],
            }
        },
        {
            "server": {
                "name": "io.github.x/notion-mcp",
                "description": "Notion por stdio",
                "version": "3.3.1",
                "repository": {"url": "https://github.com/x/notion-mcp"},
                "packages": [
                    {"registryType": "npm", "identifier": "@x/notion-mcp", "version": "3.3.1", "transport": {"type": "stdio"}, "environmentVariables": [{"name": "NOTION_TOKEN", "description": "token", "isRequired": True, "isSecret": True}]},
                    {"registryType": "pypi", "identifier": "notion-mcp", "version": "3.3.1"},
                    {"registryType": "oci", "identifier": "docker.io/x/notion-mcp", "version": "3.3.1"},
                ],
            }
        },
        {"server": {"name": "io.github.x/notion-mcp", "version": "3.3.0"}},
    ],
    "metadata": {"count": 3},
}


@pytest.fixture
def fake() -> Fake:
    return Fake()


@pytest.fixture
def http(fake):
    return lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def store(settings, http) -> ConnectorStore:
    return ConnectorStore(settings.home, MemoryVault(), http, gh=lambda args: "gho-bom" if args == ["auth", "token"] else "")


def make_hub(settings, store):
    brain = BrainIndex(Vault(settings.brain), settings.home / "brain.db")
    hub = Hub(
        connectors=store,
        brain=brain,
        kanban=Kanban(Vault(settings.brain)),
        vault=Vault(settings.brain),
        activity=ActivityLog(settings.home / "atividade.db"),
        publish=lambda _e: None,
        session_info=lambda _s: {"who": "Teste", "cwd": None, "allowed": None},
    )
    return hub, hub.register("sessao-1")


def rpc(hub, token, method, params=None):
    return asyncio.run(hub.handle(token, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}))


def connect_notion(store) -> str:
    url = store.start_oauth("notion", "Notion pessoal", "http://127.0.0.1:1/conectores/oauth/retorno")
    state = parse_qs(urlparse(url).query)["state"][0]
    return store.finish_oauth(state, "codigo").id


# --- 1. renovar o login ------------------------------------------------------------------


def test_oauth_keeps_everything_needed_to_refresh_in_the_vault(store, settings):
    account_id = connect_notion(store)
    saved = json.loads(store.vault.get(f"conector:{account_id}"))
    assert saved["refresh_token"] == "ref-1" and saved["token_endpoint"] == f"{NOTION}/token" and saved["client_id"] == "cli-notion"
    assert saved["expires_at"] > time.time() + 3000
    on_disk = (settings.home / "conectores.json").read_text(encoding="utf-8")
    assert "tok-1" not in on_disk and "ref-1" not in on_disk


def test_token_close_to_expiring_is_renewed_before_the_call(store, fake):
    account_id = connect_notion(store)
    saved = json.loads(store.vault.get(f"conector:{account_id}"))
    store.vault.set(f"conector:{account_id}", json.dumps({**saved, "expires_at": time.time() + 10}))
    assert store.access_token(account_id) == "tok-2"
    renewed = json.loads(store.vault.get(f"conector:{account_id}"))
    assert renewed["refresh_token"] == "ref-2" and renewed["expires_at"] > time.time() + 3000
    refresh_call = [form for name, form in fake.calls if name == "token" and form["grant_type"] == "refresh_token"][0]
    assert refresh_call["client_id"] == "cli-notion" and refresh_call["refresh_token"] == "ref-1"


def test_401_renews_once_and_repeats(store, fake):
    account_id = connect_notion(store)
    fake.valid = {"tok-2"}  # o servidor deixou de aceitar o tok-1 antes da hora
    store._clients.clear()
    answer = store.mcp(account_id).call("notion-search", {})
    assert answer["content"][0]["text"] == "feito: notion-search"
    assert json.loads(store.vault.get(f"conector:{account_id}"))["access_token"] == "tok-2"


def test_401_without_refresh_token_asks_to_connect_again(store, fake):
    account_id = connect_notion(store)
    saved = json.loads(store.vault.get(f"conector:{account_id}"))
    store.vault.set(f"conector:{account_id}", json.dumps({"access_token": saved["access_token"]}))
    fake.valid = set()
    store._clients.clear()
    with pytest.raises(ConnectorError, match="o login de Notion pessoal expirou; conecte de novo"):
        store.mcp(account_id).tools()
    fake.valid, fake.refresh_ok = set(), False
    store.vault.set(f"conector:{account_id}", json.dumps(saved))
    store._clients.clear()
    with pytest.raises(ConnectorError, match="expirou"):
        store.mcp(account_id).tools()


def test_old_account_with_only_the_token_still_works(store, fake):
    account_id = connect_notion(store)
    store.vault.set(f"conector:{account_id}", "tok-1")  # como a v0.6 gravava
    store._clients.clear()
    assert len(store.mcp(account_id).tools()) == 2


# --- 2. galeria: Notion, GitHub, Google, MCP próprio ----------------------------------------


def test_notion_tools_need_approval_only_for_writes(settings, store):
    connect_notion(store)
    hub, token = make_hub(settings, store)
    tools = {t.name: t for t in hub.tools_for(hub.context(token))}
    assert tools["notion-pessoal__notion-search"].write is False
    assert tools["notion-pessoal__notion-create-pages"].write is True


def test_read_rule_by_annotation_and_by_name():
    assert _is_read({"name": "create_x", "annotations": {"readOnlyHint": True}})
    assert not _is_read({"name": "get_x", "annotations": {"readOnlyHint": False}})
    for name in ("get_issue", "list_pull_requests", "search_code", "read_file", "fetch", "query_db", "notion-search", "notion-fetch"):
        assert _is_read({"name": name}), name
    for name in ("create_issue", "update_page", "delete_x", "merge_pull_request", "notion-create-pages", "send", ""):
        assert not _is_read({"name": name}), name


def test_github_uses_the_gh_token_and_checks_it(store):
    account = store.add_github("")
    assert account.kind == "github" and account.meta["login"] == "pedroaugusto" and account.meta["ferramentas"] == 2
    assert account.name == "GitHub pedroaugusto"
    assert json.loads(store.vault.get(f"conector:{account.id}"))["access_token"] == "gho-bom"
    assert len(store.mcp(account.id).tools()) == 2
    with pytest.raises(ConnectorError) as bad:
        store.add_github("Outro", "gho-ruim-1234")
    assert "gho-ruim-1234" not in str(bad.value) and "recusou" in str(bad.value)


def test_github_401_without_refresh_says_the_token_was_refused(store, fake):
    account = store.add_github("GitHub")
    store.vault.set(f"conector:{account.id}", json.dumps({"access_token": "gho-velho"}))
    store._clients.clear()
    with pytest.raises(ConnectorError, match="recusou o token"):
        store.mcp(account.id).tools()


def test_own_mcp_by_url_without_auth_sends_no_header(store, fake):
    account = store.add_mcp_http("Meu MCP", f"{OWN}/mcp", "nenhuma", "", "http://127.0.0.1:1/r")
    assert account.kind == "mcp" and account.meta == {"transporte": "http", "url": f"{OWN}/mcp", "auth": "nenhuma", "servidor": "servidor-falso", "ferramentas": 1}
    assert all(header == "" for name, header in fake.calls if name == "own-auth")
    with_token = store.add_mcp_http("Com token", f"{OWN}/mcp", "token", "segredo-123", "http://127.0.0.1:1/r")
    assert ("own-auth", "Bearer segredo-123") in fake.calls
    assert "segredo-123" not in json.dumps(with_token.to_dict())
    with pytest.raises(ConnectorError, match="registro automático: use um token"):
        store.add_mcp_http("OAuth", f"{OWN}/mcp", "oauth", "", "http://127.0.0.1:1/r")
    with pytest.raises(ConnectorError, match="http"):
        store.add_mcp_http("X", "ftp://x", "nenhuma", "", "http://127.0.0.1:1/r")


def test_own_mcp_by_url_with_oauth_returns_the_login_page(store):
    url = store.add_mcp_http("Notion por fora", f"{NOTION}/mcp", "oauth", "", "http://127.0.0.1:1/conectores/oauth/retorno")
    assert isinstance(url, str) and url.startswith(f"{NOTION}/authorize?")
    account = store.finish_oauth(parse_qs(urlparse(url).query)["state"][0], "c")
    assert account.kind == "mcp" and account.meta["url"] == f"{NOTION}/mcp" and account.meta["auth"] == "oauth"
    assert len(store.mcp(account.id).tools()) == 2


STDIO_SERVER = r'''
import json, os, sys
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method = msg["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "stdio-falso"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "segredo_lido", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}, {"name": "sair", "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        if msg["params"]["name"] == "sair":
            sys.exit(3)
        result = {"content": [{"type": "text", "text": "tamanho " + str(len(os.environ.get("SEGREDO", "")))}]}
    print("log solto do servidor", flush=True)
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
'''


def test_own_mcp_by_command_keeps_env_in_the_vault_and_restarts(tmp_path, settings, store):
    script = tmp_path / "servidor.py"
    script.write_text(STDIO_SERVER, encoding="utf-8")
    command = f"{sys.executable} {script} --chave abc-segredo-xyz"
    account = store.add_mcp_stdio("Local", command, "SEGREDO=abc-segredo-xyz\n# comentário\n", "")
    assert account.meta["transporte"] == "stdio" and account.meta["env_chaves"] == ["SEGREDO"] and account.meta["ferramentas"] == 2
    assert "abc-segredo-xyz" not in json.dumps(account.to_dict()) and "***" in account.meta["comando"]
    assert "abc-segredo-xyz" not in (settings.home / "conectores.json").read_text(encoding="utf-8")
    assert json.loads(store.vault.get(f"conector:{account.id}"))["env"] == {"SEGREDO": "abc-segredo-xyz"}
    hub, token = make_hub(settings, store)
    answer = rpc(hub, token, "tools/call", {"name": f"{account.id}__segredo_lido", "arguments": {}})["result"]
    assert answer["content"][0]["text"] == "tamanho 15"
    client = store.mcp(account.id)
    with pytest.raises(Exception):
        client.call("sair", {})  # o processo morre no meio
    assert client.call("segredo_lido", {})["content"][0]["text"] == "tamanho 15"  # e sobe de novo
    process = client._proc
    store.remove(account.id)
    assert process.poll() is not None and store.vault.get(f"conector:{account.id}") is None


def test_own_mcp_by_command_that_fails_shows_stderr_without_secrets(tmp_path, store):
    script = tmp_path / "quebra.py"
    script.write_text("import os, sys\nsys.stderr.write('falhou com ' + os.environ['SEGREDO'] + '\\n')\nsys.exit(1)\n", encoding="utf-8")
    with pytest.raises(ConnectorError) as failed:
        store.add_mcp_stdio("Quebrado", f"{sys.executable} {script}", "SEGREDO=valor-secreto", "")
    assert "falhou com ***" in str(failed.value) and "valor-secreto" not in str(failed.value)
    with pytest.raises(ConnectorError, match="variável inválida"):
        store.add_mcp_stdio("X", "python3 x.py", "sem igual", "")


def connect_google(store) -> str:
    store.set_google_client("123-abc.apps.googleusercontent.com", "segredo-do-cliente")
    url = store.start_google("", "http://127.0.0.1:47830/conectores/oauth/retorno")
    return url


def test_google_client_login_and_account(store, fake, settings):
    with pytest.raises(ConnectorError, match="cliente OAuth"):
        store.start_google("", "http://127.0.0.1:1/r")
    url = connect_google(store)
    assert store.google_client_status() == {"configurado": True, "client_id_fim": "nt.com"}
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith(google_api.AUTHORIZE) and query["access_type"] == "offline" and query["prompt"] == "consent"
    assert query["code_challenge_method"] == "S256" and "gmail.readonly" in query["scope"] and "drive.readonly" in query["scope"]
    assert query["redirect_uri"] == "http://127.0.0.1:47830/conectores/oauth/retorno"
    account = store.finish_oauth(query["state"], "codigo-g")
    exchange = next(form for name, form in fake.calls if name == "google-token")
    assert exchange["client_secret"] == "segredo-do-cliente" and exchange["code_verifier"] and "resource" not in exchange
    assert account.kind == "google" and account.meta == {"email": "pedro@gmail.com"} and account.name == "Google pedro@gmail.com"
    assert "segredo-do-cliente" not in (settings.home / "conectores.json").read_text(encoding="utf-8")


def test_google_tools_read_and_writes_wait_for_approval(store, fake, settings):
    url = connect_google(store)
    account = store.finish_oauth(parse_qs(urlparse(url).query)["state"][0], "c")
    hub, token = make_hub(settings, store)
    tools = {t.name: t for t in hub.tools_for(hub.context(token))}
    prefix = f"{account.id}__"
    assert {n for n in tools if n.startswith(prefix)} == {prefix + n for n in ("gmail_buscar", "gmail_ler", "gmail_rascunho", "agenda_eventos", "agenda_criar", "drive_buscar", "drive_ler")}
    assert tools[prefix + "gmail_rascunho"].write and tools[prefix + "agenda_criar"].write and not tools[prefix + "gmail_buscar"].write
    found = json.loads(rpc(hub, token, "tools/call", {"name": prefix + "gmail_buscar", "arguments": {"consulta": "from:ana"}})["result"]["content"][0]["text"])
    assert found == [{"id": "m1", "de": "Ana <ana@x.com>", "assunto": "Relatório", "data": "Sun, 8 Nov 2026", "trecho": "segue o relatório"}]
    mail = rpc(hub, token, "tools/call", {"name": prefix + "gmail_ler", "arguments": {"id": "m1"}})["result"]["content"][0]["text"]
    assert "Assunto: Relatório" in mail and "segue o relatório" in mail
    events = rpc(hub, token, "tools/call", {"name": prefix + "agenda_eventos", "arguments": {}})["result"]["content"][0]["text"]
    assert "Reunião" in events
    doc = rpc(hub, token, "tools/call", {"name": prefix + "drive_ler", "arguments": {"id": "f1"}})["result"]["content"][0]["text"]
    assert "Texto do plano" in doc and "https://docs/f1" in doc
    store.update(account.id, approve_writes=False)
    draft = rpc(hub, token, "tools/call", {"name": prefix + "gmail_rascunho", "arguments": {"para": "ana@x.com", "assunto": "Oi", "corpo": "Tudo certo"}})["result"]
    assert "não foi enviado" in draft["content"][0]["text"]
    assert "To: ana@x.com" in next(text for name, text in fake.calls if name == "draft")
    rpc(hub, token, "tools/call", {"name": prefix + "agenda_criar", "arguments": {"titulo": "Reunião", "inicio": "2026-11-10T10:00", "fim": "2026-11-10", "convidados": ["ana@x.com"]}})
    event = next(body for name, body in fake.calls if name == "event")
    assert event["start"] == {"dateTime": "2026-11-10T10:00:00", "timeZone": "America/Sao_Paulo"} and event["end"] == {"date": "2026-11-10"}
    assert event["attendees"] == [{"email": "ana@x.com"}]


def test_google_renews_on_401(store, fake):
    url = connect_google(store)
    account = store.finish_oauth(parse_qs(urlparse(url).query)["state"][0], "c")
    fake.google_tokens = {"g-2"}
    assert store.google(account.id).userinfo()["email"] == "pedro@gmail.com"
    assert json.loads(store.vault.get(f"conector:{account.id}"))["access_token"] == "g-2"
    refreshed = [form for name, form in fake.calls if name == "google-token" and form["grant_type"] == "refresh_token"][0]
    assert refreshed["client_secret"] == "segredo-do-cliente" and refreshed["refresh_token"] == "g-ref"


# --- 3. catálogo oficial --------------------------------------------------------------------


def test_registry_maps_remotes_packages_and_caches(fake, http):
    registry = McpRegistry(http)
    found = registry.search("notion")
    assert [s["nome"] for s in found] == ["com.notion/mcp", "io.github.x/notion-mcp"]
    assert found[0]["remotos"] == [{"tipo": "streamable-http", "url": "https://mcp.notion.com/mcp"}] and found[0]["site"] == "https://developers.notion.com"
    packages = found[1]["pacotes"]
    assert [p["comando"] for p in packages] == ["npx -y @x/notion-mcp@3.3.1", "uvx notion-mcp==3.3.1", "docker run -i --rm docker.io/x/notion-mcp:3.3.1"]
    assert packages[0]["env"] == [{"nome": "NOTION_TOKEN", "descricao": "token", "obrigatoria": True, "secreta": True}]
    assert found[1]["site"] == "https://github.com/x/notion-mcp" and found[1]["titulo"] == "notion-mcp"
    params = next(p for name, p in fake.calls if name == "registry")
    assert params["search"] == "notion" and params["version"] == "latest"
    registry.search("Notion")  # mesma busca: vem do cache
    assert len([1 for name, _ in fake.calls if name == "registry"]) == 1
    fake.registry_up = False
    with pytest.raises(RegistryError, match="não respondeu"):
        registry.search("outra")


# --- 4 e rotas: testar conexão, catálogo, GitHub, Google, MCP --------------------------------


def test_routes(settings, accounts, http, fake, tmp_path):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, keychain=MemoryVault(), http=http, run_scheduler=False)
    with TestClient(app) as client:
        app.state.connectors.gh = lambda args: "gho-bom"
        github = client.post("/conectores/github", json={"nome": ""}, headers=AUTH)
        assert github.status_code == 201 and github.json()["meta"]["login"] == "pedroaugusto"
        tested = client.post(f"/conectores/{github.json()['id']}/testar", headers=AUTH).json()
        assert tested["ok"] is True and tested["ferramentas"] == 2 and isinstance(tested["ms"], int)
        assert client.post("/conectores/nao-existe/testar", headers=AUTH).json()["ok"] is False
        assert client.get("/conectores/google/cliente", headers=AUTH).json() == {"configurado": False, "client_id_fim": ""}
        assert client.post("/conectores/google/iniciar", json={"nome": ""}, headers=AUTH).status_code == 400
        assert client.put("/conectores/google/cliente", json={"client_id": "abc.apps.googleusercontent.com", "client_secret": "s3"}, headers=AUTH).json()["configurado"]
        start = client.post("/conectores/google/iniciar", json={"nome": "Google pessoal"}, headers=AUTH).json()["url"]
        assert parse_qs(urlparse(start).query)["redirect_uri"][0] == f"{settings.url}/conectores/oauth/retorno"
        page = client.get("/conectores/oauth/retorno", params={"state": parse_qs(urlparse(start).query)["state"][0], "code": "c"})
        assert page.status_code == 200 and "Google pessoal conectado" in page.text
        fake.drive_off = True
        google_test = client.post("/conectores/google-pessoal/testar", headers=AUTH).json()
        assert google_test["ok"] is False and "Drive" in google_test["detalhe"]
        own = client.post("/conectores/mcp", json={"nome": "Meu", "transporte": "http", "url": f"{OWN}/mcp", "auth": "nenhuma"}, headers=AUTH)
        assert own.status_code == 201 and own.json()["meta"]["ferramentas"] == 1
        login = client.post("/conectores/mcp", json={"nome": "Com login", "transporte": "http", "url": f"{NOTION}/mcp", "auth": "oauth"}, headers=AUTH)
        assert login.status_code == 200 and login.json()["url"].startswith(f"{NOTION}/authorize")
        assert client.post("/conectores/mcp", json={"transporte": "pombo"}, headers=AUTH).status_code == 400
        catalog = client.get("/conectores/catalogo-mcp", params={"q": "notion"}, headers=AUTH)
        assert catalog.status_code == 200 and len(catalog.json()["servidores"]) == 2
        fake.registry_up = False
        assert client.get("/conectores/catalogo-mcp", params={"q": "outra"}, headers=AUTH).status_code == 502
        ids = {a["id"] for a in client.get("/conectores", headers=AUTH).json()["accounts"]}
        assert {"github-pedroaugusto", "google-pessoal", "mcp-meu"} <= ids


# --- 5. copiar MCP entre o Claude e o Codex --------------------------------------------------


def write_configs(settings, tmp_path) -> Path:
    settings.claude_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "n8n": {"command": "npx", "args": ["-y", "n8n-mcp"], "env": {"N8N_API_KEY": "chave-n8n-secreta"}},
                    "remoto": {"type": "http", "url": "https://x.com/mcp", "headers": {"Authorization": "Bearer ${X_TOKEN}"}},
                    "fixo": {"type": "http", "url": "https://y.com/mcp", "headers": {"Authorization": "Bearer literal-secreto"}},
                    "antigo": {"type": "sse", "url": "https://z.com/sse"},
                },
                "projects": {"/repo": {"mcpServers": {"clickup": {"type": "http", "url": "https://mcp.clickup.com/mcp"}}}},
            }
        ),
        encoding="utf-8",
    )
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt"\n\n[mcp_servers.rea]\ncommand = "rea"\nargs = ["mcp"]\nenv_vars = ["HOME_REA"]\n\n'
        '[mcp_servers.web]\nurl = "https://w.com/mcp"\nbearer_token_env_var = "W_TOKEN"\n\n'
        '[mcp_servers.n8n]\ncommand = "npx"\nargs = ["n8n-mcp"]\nenv = { N8N_API_KEY = "outra-chave" }\n',
        encoding="utf-8",
    )
    return codex_home


def test_cli_mcps_list_without_values_and_copy_through_the_cli(settings, accounts, http, tmp_path):
    codex_home = write_configs(settings, tmp_path)
    ran: list[tuple[list[str], dict]] = []
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, keychain=MemoryVault(), http=http, run_scheduler=False)
    with TestClient(app) as client:
        app.state.cli_homes = {"claude": str(tmp_path / "claude-home"), "codex": str(codex_home)}
        app.state.mcp_cli_runner = lambda argv, env: (ran.append((argv, env)) or (0, "", ""))
        listed = client.get("/mcps-cli", headers=AUTH)
        text = listed.text
        assert listed.status_code == 200 and "chave-n8n-secreta" not in text and "outra-chave" not in text and "literal-secreto" not in text
        claude = {(m["nome"], m["escopo"]): m for m in listed.json()["claude"]}
        assert claude[("n8n", "usuario")] == {"nome": "n8n", "tipo": "stdio", "escopo": "usuario", "comando": "npx", "args": ["-y", "n8n-mcp"], "env_chaves": ["N8N_API_KEY"]}
        assert claude[("clickup", "projeto:/repo")]["tipo"] == "http"
        codex = {m["nome"]: m for m in listed.json()["codex"]}
        assert codex["rea"]["env_chaves"] == ["HOME_REA"] and codex["web"] == {"nome": "web", "tipo": "http", "escopo": "usuario", "url": "https://w.com/mcp"}
        # Claude → Codex, por stdio: o valor vai só para a CLI, nunca na resposta.
        assert client.post("/mcps-cli/copiar", json={"de": "claude", "para": "codex", "nome": "n8n"}, headers=AUTH).status_code == 409
        ran.clear()
        (codex_home / "config.toml").write_text('model = "gpt"\n', encoding="utf-8")
        copied = client.post("/mcps-cli/copiar", json={"de": "claude", "para": "codex", "nome": "n8n"}, headers=AUTH)
        assert copied.status_code == 200 and "chave-n8n-secreta" not in copied.text
        argv, env = ran[-1]
        assert argv == ["codex", "mcp", "add", "n8n", "--env", "N8N_API_KEY=chave-n8n-secreta", "--", "npx", "-y", "n8n-mcp"]
        assert env == {"CODEX_HOME": str(codex_home)}
        client.post("/mcps-cli/copiar", json={"de": "claude", "para": "codex", "nome": "remoto"}, headers=AUTH)
        assert ran[-1][0] == ["codex", "mcp", "add", "remoto", "--url", "https://x.com/mcp", "--bearer-token-env-var", "X_TOKEN"]
        fixed = client.post("/mcps-cli/copiar", json={"de": "claude", "para": "codex", "nome": "fixo"}, headers=AUTH).json()
        assert "--bearer-token-env-var" not in ran[-1][0] and fixed["avisos"]
        assert client.post("/mcps-cli/copiar", json={"de": "claude", "para": "codex", "nome": "antigo"}, headers=AUTH).status_code == 400
        assert client.post("/mcps-cli/copiar", json={"de": "claude", "para": "codex", "nome": "clickup"}, headers=AUTH).status_code == 404
        # Codex → Claude: a variável do token vira ${VAR} no cabeçalho.
        (codex_home / "config.toml").write_text('[mcp_servers.web]\nurl = "https://w.com/mcp"\nbearer_token_env_var = "W_TOKEN"\n\n[mcp_servers.rea]\ncommand = "rea"\nargs = ["mcp"]\nenv_vars = ["HOME_REA"]\n', encoding="utf-8")
        client.post("/mcps-cli/copiar", json={"de": "codex", "para": "claude", "nome": "web"}, headers=AUTH)
        argv, env = ran[-1]
        assert argv[:4] == ["claude", "mcp", "add-json", "web"] and argv[-2:] == ["--scope", "user"]
        assert json.loads(argv[4]) == {"type": "http", "url": "https://w.com/mcp", "headers": {"Authorization": "Bearer ${W_TOKEN}"}}
        client.post("/mcps-cli/copiar", json={"de": "codex", "para": "claude", "nome": "rea"}, headers=AUTH)
        assert json.loads(ran[-1][0][4]) == {"type": "stdio", "command": "rea", "args": ["mcp"], "env": {"HOME_REA": "${HOME_REA}"}}
        app.state.mcp_cli_runner = lambda argv, env: (1, "", "erro com outra-chave no meio")
        (codex_home / "config.toml").write_text('[mcp_servers.n9]\ncommand = "npx"\nenv = { K = "outra-chave" }\n', encoding="utf-8")
        refused = client.post("/mcps-cli/copiar", json={"de": "codex", "para": "claude", "nome": "n9"}, headers=AUTH)
        assert refused.status_code == 400 and "outra-chave" not in refused.text and "***" in refused.text


def test_copy_rejects_same_cli(tmp_path):
    places = mcp_configs.Places(tmp_path / "c.json", tmp_path / "x.toml", {}, {})
    with pytest.raises(mcp_configs.McpConfigError):
        mcp_configs.copy(places, "claude", "claude", "x")
