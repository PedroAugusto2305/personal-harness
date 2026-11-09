"""v0.9.9: modo por ferramenta de conector (livre, pede aprovação, desligada)."""

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from harness_core.app import create_app
from harness_core.connectors import ConnectorError
from harness_core.keychain import MemoryVault

from .conftest import TOKEN
from .test_connectors import fake, http, make_hub, rpc, store  # noqa: F401 (fixtures)

AUTH = {"X-Harness-Token": TOKEN}


def _clickup(store):
    url = store.start_oauth("clickup", "ClickUp", "http://127.0.0.1:1/r")
    store.finish_oauth(parse_qs(urlparse(url).query)["state"][0], "c")


def test_disabled_tool_disappears_and_free_write_runs_without_approval(settings, store, fake):
    _clickup(store)
    hub, token = make_hub(settings, store, [])
    store.update("clickup", tool_modes={"clickup__search_tasks": "desligada", "clickup__create_task": "livre"})
    names = {t["name"] for t in rpc(hub, token, "tools/list")["result"]["tools"]}
    assert "clickup__search_tasks" not in names and "clickup__create_task" in names
    created = rpc(hub, token, "tools/call", {"name": "clickup__create_task", "arguments": {"name": "x"}})["result"]
    assert created["content"][0]["text"] == "feito: create_task" and not hub.pending
    blocked = rpc(hub, token, "tools/call", {"name": "clickup__search_tasks", "arguments": {}})["result"]
    assert blocked["isError"]


def test_padrao_removes_the_choice_and_unknown_mode_is_refused(settings, store, fake):
    _clickup(store)
    store.update("clickup", tool_modes={"clickup__create_task": "livre"})
    assert store.get("clickup").tool_modes == {"clickup__create_task": "livre"}
    store.update("clickup", tool_modes={"clickup__create_task": "padrao"})
    assert store.get("clickup").tool_modes == {}
    with pytest.raises(ConnectorError):
        store.update("clickup", tool_modes={"clickup__create_task": "talvez"})


def test_tools_route_lists_every_tool_with_its_mode(settings, accounts, http, fake):
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, keychain=MemoryVault(), http=http)) as client:
        assert client.post("/conectores/slack", json={"name": "Slack pessoal", "token": "xoxb-bom", "email": "p@e.com"}, headers=AUTH).status_code == 201
        listed = client.get("/conectores/slack-pessoal/ferramentas", headers=AUTH).json()["ferramentas"]
        modes = {t["nome"]: t["modo"] for t in listed}
        assert modes["slack-pessoal__mensagem_no_canal"] == "aprovacao"
        assert any(m == "livre" for m in modes.values())
        patched = client.patch("/conectores/slack-pessoal", json={"tool_modes": {"slack-pessoal__mensagem_no_canal": "desligada"}}, headers=AUTH)
        assert patched.json()["tool_modes"] == {"slack-pessoal__mensagem_no_canal": "desligada"}
        again = {t["nome"]: (t["modo"], t["escolhido"]) for t in client.get("/conectores/slack-pessoal/ferramentas", headers=AUTH).json()["ferramentas"]}
        assert again["slack-pessoal__mensagem_no_canal"] == ("desligada", True)
