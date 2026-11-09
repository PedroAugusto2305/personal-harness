"""v0.9.8 parte 2, núcleo do navegador: a ponte com a janela, as ferramentas navegador_* da
central de MCP, o histórico, os perfis e os cookies importados do Chrome."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import browser_bridge as bb
from harness_core import chrome_cookies as cc
from harness_core import sessions as sessions_mod
from harness_core.activity import ActivityLog
from harness_core.app import create_app
from harness_core.brain_index import BrainIndex
from harness_core.browser_bridge import BridgeError, BrowserBridge, BrowserHistory, BrowserProfiles, ProfileError, normalize_url
from harness_core.connectors import ConnectorStore
from harness_core.kanban import Kanban
from harness_core.keychain import MemoryVault
from harness_core.mcp_hub import Hub
from harness_core.vault import Vault

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


# --- ponte ------------------------------------------------------------------------------------


class FakeEvents:
    def __init__(self, listeners: int = 1) -> None:
        self.listeners = listeners
        self.published: list[dict] = []
        self.on_publish = None

    def publish(self, event: dict) -> None:
        self.published.append(event)
        if self.on_publish:
            self.on_publish(event)


def test_bridge_publishes_and_returns_the_answer():
    events = FakeEvents()
    bridge = BrowserBridge(events)
    events.on_publish = lambda e: threading.Timer(0.02, bridge.resolve, (e["id"], True, {"aba": "browser-1"})).start()
    result = bridge.request("s1", "Claude", "/repo", "ler", {"aba": "browser-1"}, timeout=2)
    assert result == {"aba": "browser-1"}
    event = events.published[0]
    assert event["type"] == "browser.command" and event["action"] == "ler" and event["args"] == {"aba": "browser-1"}
    assert (event["session"], event["who"], event["cwd"]) == ("s1", "Claude", "/repo") and len(event["id"]) == 12
    assert bridge.waiting == 0
    assert bridge.resolve(event["id"], True, {}) is False  # já respondido e removido


def test_bridge_timeout_closed_window_and_refusal():
    events = FakeEvents()
    bridge = BrowserBridge(events)
    with pytest.raises(BridgeError, match="não respondeu em 0.2 s"):
        bridge.request("s1", "Claude", None, "foto", {}, timeout=0.2)
    assert bridge.waiting == 0

    closed = FakeEvents(listeners=0)
    with pytest.raises(BridgeError, match="janela da MÊTIS está fechada"):
        BrowserBridge(closed).request("s1", "Claude", None, "ler", {})
    assert closed.published == []

    events.on_publish = lambda e: bridge.resolve(e["id"], False, None, "não há aba de navegador nesta worktree")
    with pytest.raises(BridgeError, match="não há aba de navegador"):
        bridge.request("s1", "Claude", None, "ler", {}, timeout=2)
    assert bridge.resolve("nao-existe", True) is False


# --- endereço -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, url",
    [
        ("localhost:3000", "http://localhost:3000"),
        (":5173/rota", "http://localhost:5173/rota"),
        ("8080", "http://localhost:8080"),
        ("127.0.0.1:8000/x", "http://127.0.0.1:8000/x"),
        ("app.localhost", "http://app.localhost"),
        ("exemplo.com", "https://exemplo.com"),
        ("exemplo.com.br/caminho?a=1", "https://exemplo.com.br/caminho?a=1"),
        ("https://x.dev", "https://x.dev"),
        ("HTTP://X.DEV", "HTTP://X.DEV"),
        ("about:blank", "about:blank"),
    ],
)
def test_normalize_url(typed, url):
    assert normalize_url(typed) == url


@pytest.mark.parametrize("typed", ["", "javascript:alert(1)", "file:///etc/passwd", "uma frase solta", "data:text/html,oi"])
def test_normalize_url_refuses(typed):
    with pytest.raises(ValueError):
        normalize_url(typed)


# --- ferramentas da central -----------------------------------------------------------------------

PAGE = {"aba": "browser-1", "url": "http://localhost:3000/", "titulo": "Painel"}


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, float]] = []
        self.fail: str | None = None

    def request(self, session, who, cwd, action, args, timeout=30):
        self.calls.append((action, args, timeout))
        if self.fail:
            raise BridgeError(self.fail)
        if action == "abas":
            return [{**PAGE, "ativa": True, "perfil": "Padrão"}, {"aba": "browser-2", "url": "https://x.dev", "titulo": "X", "ativa": False, "perfil": "Trabalho"}]
        if action == "ler":
            return {**PAGE, "texto": "heading \"Painel\"\nbutton \"Salvar\" [e3]"}
        if action == "foto":
            return {**PAGE, "mime": "image/jpeg", "base64": "QUJD" * 50}
        if action == "esperar":
            return {**PAGE, "achou": args.get("texto") == "Pronto"}
        if action == "console":
            return {"aba": "browser-1", "entradas": [{"nivel": "error", "texto": "falhou", "quando": 1.0}]}
        if action == "rede":
            return {"aba": "browser-1", "pedidos": []}
        if action == "js":
            return {"aba": "browser-1", "valor": {"n": 2}}
        if action == "fechar":
            return {"aba": args["aba"]}
        return {**PAGE, "feito": f"{action} ok"}


@pytest.fixture
def hub(settings, tmp_path):
    vault = Vault(settings.brain)
    bridge = FakeBridge()
    hub = Hub(
        connectors=ConnectorStore(settings.home, MemoryVault()),
        brain=BrainIndex(vault, settings.home / "brain.db"),
        kanban=Kanban(vault),
        vault=vault,
        activity=ActivityLog(settings.home / "atividade.db"),
        publish=lambda _e: None,
        session_info=lambda _s: {"who": "Claude", "cwd": str(tmp_path), "allowed": None},
        browser=bridge,
    )
    return hub, hub.register("sessao-1"), bridge


def call(hub, token, name, args=None):
    reply = asyncio.run(hub.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}))
    return reply["result"]


def text_of(result) -> str:
    return "\n".join(c.get("text", "") for c in result["content"])


NAMES = {
    "navegador_abrir", "navegador_abas", "navegador_ler", "navegador_clicar", "navegador_digitar", "navegador_tecla",
    "navegador_escolher", "navegador_passar", "navegador_rolar", "navegador_ir", "navegador_esperar", "navegador_foto",
    "navegador_console", "navegador_rede", "navegador_js", "navegador_fechar",
}  # fmt: skip


def test_browser_tools_are_listed_and_follow_the_automation_limit(hub):
    central, token, _ = hub
    listing = asyncio.run(central.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))["result"]["tools"]
    names = {t["name"] for t in listing}
    assert NAMES <= names and all(len(n) <= 52 for n in names)
    assert "refs" in next(t for t in listing if t["name"] == "navegador_ler")["description"]
    central.session_tools["sessao-1"] = {"brain_buscar"}
    limited = {t["name"] for t in asyncio.run(central.handle(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))["result"]["tools"]}
    assert not (NAMES & limited)


def test_browser_tools_send_the_contract_and_format_answers(hub):
    central, token, bridge = hub
    result = call(central, token, "navegador_abrir", {"url": ":3000"})
    assert bridge.calls[-1] == ("abrir", {"url": "http://localhost:3000", "nova_aba": False}, 30)
    assert "browser-1" in text_of(result) and "Painel" in text_of(result)
    assert call(central, token, "navegador_abrir", {"url": "javascript:alert(1)"})["isError"]

    abas = text_of(call(central, token, "navegador_abas"))
    assert "browser-1 (ativa) [Padrão]" in abas and "browser-2 [Trabalho]" in abas

    lido = text_of(call(central, token, "navegador_ler"))
    assert lido.startswith("Aba browser-1 · Painel · http://localhost:3000/\n\n") and "[e3]" in lido

    assert "feito: clicar ok; página: Painel (http://localhost:3000/)" == text_of(call(central, token, "navegador_clicar", {"ref": "[e3]"}))
    assert bridge.calls[-1][1] == {"ref": "e3"}
    call(central, token, "navegador_clicar", {"texto": "Salvar", "aba": "browser-2"})
    assert bridge.calls[-1][1] == {"texto": "Salvar", "aba": "browser-2"}
    missing = call(central, token, "navegador_clicar", {})
    assert missing["isError"] and "ref, seletor ou texto" in text_of(missing)

    call(central, token, "navegador_digitar", {"seletor": "#nome", "texto": ""})
    assert bridge.calls[-1][1] == {"seletor": "#nome", "texto": "", "enviar": False, "limpar": True}
    assert call(central, token, "navegador_digitar", {"texto": "oi"})["isError"]
    assert call(central, token, "navegador_escolher", {"valor": "SP"})["isError"]
    call(central, token, "navegador_escolher", {"ref": "e9", "valor": "SP"})
    assert bridge.calls[-1][:2] == ("escolher", {"ref": "e9", "valor": "SP"})
    call(central, token, "navegador_passar", {"seletor": "nav a"})
    call(central, token, "navegador_tecla", {"tecla": "Enter"})
    assert bridge.calls[-1][1] == {"tecla": "Enter"}
    assert call(central, token, "navegador_tecla", {"tecla": " "})["isError"]
    call(central, token, "navegador_rolar", {"pixels": 400})
    assert bridge.calls[-1][1] == {"direcao": "baixo", "pixels": 400}
    assert call(central, token, "navegador_rolar", {"direcao": "lado"})["isError"]
    call(central, token, "navegador_ir", {"acao": "recarregar"})
    assert call(central, token, "navegador_ir", {"acao": "pular"})["isError"]


def test_wait_photo_console_js_and_close(hub, settings):
    central, token, bridge = hub
    assert text_of(call(central, token, "navegador_esperar", {"texto": "Pronto", "segundos": 99})).startswith("achou")
    assert bridge.calls[-1] == ("esperar", {"texto": "Pronto", "segundos": 30}, 40)
    assert text_of(call(central, token, "navegador_esperar", {"seletor": "#x"})).startswith("não apareceu em 5 s")

    photo = call(central, token, "navegador_foto")
    assert photo["content"][0] == {"type": "text", "text": "Aba browser-1 · Painel · http://localhost:3000/"}
    assert photo["content"][1] == {"type": "image", "data": "QUJD" * 50, "mimeType": "image/jpeg"}
    rows = sqlite3.connect(settings.home / "atividade.db").execute("SELECT * FROM sqlite_master WHERE type = 'table'").fetchall()
    dump = "\n".join(str(r) for r in sqlite3.connect(settings.home / "atividade.db").execute(f"SELECT * FROM {rows[0][1]}").fetchall())
    assert "QUJDQUJD" not in dump  # a foto não vai para a Atividade

    assert json.loads(text_of(call(central, token, "navegador_console", {"limpar": True})))[0]["texto"] == "falhou"
    assert bridge.calls[-1][1] == {"limpar": True}
    assert "Nenhum pedido" in text_of(call(central, token, "navegador_rede", {"filtro": "api"}))
    assert json.loads(text_of(call(central, token, "navegador_js", {"codigo": "1+1"}))) == {"n": 2}
    assert call(central, token, "navegador_js", {"codigo": ""})["isError"]
    assert text_of(call(central, token, "navegador_fechar", {"aba": "browser-2"})) == "Aba browser-2 fechada."
    assert call(central, token, "navegador_fechar", {})["isError"]

    bridge.fail = "A janela da MÊTIS está fechada: o navegador só funciona com ela aberta. Peça ao Pedro para abrir a MÊTIS."
    closed = call(central, token, "navegador_ler")
    assert closed["isError"] and "janela da MÊTIS está fechada" in text_of(closed)


# --- histórico ---------------------------------------------------------------------------------


def test_history_upsert_search_order_and_cap(tmp_path, monkeypatch):
    history = BrowserHistory(tmp_path / "navegador.db")
    assert history.visit("https://exemplo.com/a", "Página Inicial", now=100)
    assert history.visit("https://exemplo.com/a", "", now=200)  # título vazio não apaga o anterior
    assert not history.visit("about:blank") and not history.visit("file:///x") and not history.visit("javascript:1")
    history.visit("http://localhost:3000/", "Painel", now=150)
    history.visit("https://docs.exemplo.com/guia", "Guia", now=300)
    history.visit("https://outra.dev/exemplo", "Outra", now=400)

    first = history.search()[0]
    assert first["url"] == "https://outra.dev/exemplo"
    item = next(i for i in history.search() if i["url"] == "https://exemplo.com/a")
    assert item == {"url": "https://exemplo.com/a", "titulo": "Página Inicial", "visitas": 2, "ultima": 200}

    assert [i["url"] for i in history.search("PAGINA")] == ["https://exemplo.com/a"]  # sem acento e sem maiúscula
    found = [i["url"] for i in history.search("exemplo")]
    # o host que começa com "exemplo" vem antes do que só tem a palavra no caminho
    assert found == ["https://exemplo.com/a", "https://outra.dev/exemplo", "https://docs.exemplo.com/guia"]
    assert len(history.search(limit=2)) == 2
    assert history.search("50%_") == []

    monkeypatch.setattr(bb, "HISTORY_MAX", 3)
    history.visit("https://nova.dev", "Nova", now=500)
    assert len(history.search(limit=100)) == 3
    assert "http://localhost:3000/" not in {i["url"] for i in history.search(limit=100)}  # a mais velha saiu
    history.clear()
    assert history.search() == []


# --- perfis -------------------------------------------------------------------------------------


def test_profiles_store(tmp_path):
    events: list[dict] = []
    profiles = BrowserProfiles(tmp_path, publish=events.append)
    assert profiles.list() == [{"id": "padrao", "nome": "Padrão", "identificador": None, "criado": None}]
    work = profiles.create("  Trabalho  Seller ")
    assert work["id"] == "trabalho-seller" and work["nome"] == "Trabalho Seller" and len(work["identificador"]) == 32
    int(work["identificador"], 16)
    again = profiles.create("Trabalho-Seller")  # nome diferente, mesmo slug
    assert again["id"] == "trabalho-seller-2"
    with pytest.raises(ProfileError) as dup:
        profiles.create("trabalho seller")
    assert dup.value.status == 409
    with pytest.raises(ProfileError) as default:
        profiles.create("padrão")
    assert default.value.status == 409
    with pytest.raises(ProfileError):
        profiles.create("x" * 41)
    assert profiles.rename("trabalho-seller-2", "Pessoal")["nome"] == "Pessoal"
    with pytest.raises(ProfileError) as clash:
        profiles.rename("trabalho-seller-2", "Trabalho Seller")
    assert clash.value.status == 409
    with pytest.raises(ProfileError) as fixed:
        profiles.rename("padrao", "Outro")
    assert fixed.value.status == 400
    profiles.delete("trabalho-seller")
    with pytest.raises(ProfileError) as gone:
        profiles.delete("trabalho-seller")
    assert gone.value.status == 404
    with pytest.raises(ProfileError):
        profiles.delete("padrao")
    assert [p["id"] for p in BrowserProfiles(tmp_path).list()] == ["padrao", "trabalho-seller-2"]
    assert events and all(e == {"type": "navegador.perfis"} for e in events)


# --- cookies do Chrome --------------------------------------------------------------------------

PASSWORD = "senha-do-keychain"
FUTURE = 4102444800  # 2100-01-01
EPOCH_1601 = 11644473600


def chrome_time(epoch: float) -> int:
    return int((epoch + EPOCH_1601) * 1_000_000)


def encrypt(value: str, host: str, version: int) -> bytes:
    key = cc.derive_key(PASSWORD)
    plain = (hashlib.sha256(host.encode()).digest() if version >= 24 else b"") + value.encode()
    return b"v10" + cc.aes_cbc(cc._ENCRYPT, key, plain)


def make_profile(folder: Path, version: int, rows: list[tuple]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "Cookies")
    db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('version', ?)", (str(version),))
    db.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, path TEXT, expires_utc INTEGER,"
        " is_secure INTEGER, is_httponly INTEGER, samesite INTEGER)"
    )
    db.executemany("INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    db.commit()
    db.close()


@pytest.fixture
def support(tmp_path) -> Path:
    base = tmp_path / "Application Support"
    chrome = base / "Google" / "Chrome"
    make_profile(
        chrome / "Default" / "Network",
        24,
        [
            (".exemplo.com", "sessao", "", encrypt("valor-secreto", ".exemplo.com", 24), "/", chrome_time(FUTURE), 1, 1, 1),
            ("exemplo.com", "tema", "escuro", b"", "/", 0, 0, 0, -1),
            (".exemplo.com", "velho", "", encrypt("x", ".exemplo.com", 24), "/", chrome_time(1000), 0, 0, 0),
            ("api.outro.com", "token", "", encrypt("outro", "api.outro.com", 24), "/v1", chrome_time(FUTURE), 1, 0, 2),
            (".exemplo.com", "quebrado", "", b"v10" + b"lixo" * 4, "/", 0, 0, 0, 0),
        ],
    )
    make_profile(chrome / "Profile 1", 18, [(".antigo.com", "id", "", encrypt("sem-prefixo", ".antigo.com", 18), "/", 0, 0, 0, 0)])
    (chrome / "Sem Cookies").mkdir()
    (chrome / "Local State").write_text(json.dumps({"profile": {"info_cache": {"Default": {"name": "Pessoa 1"}, "Profile 1": {"name": "Trabalho"}}}}))
    return base


def test_chrome_sources(support):
    assert cc.list_sources(support) == [
        {"id": "chrome:Default", "navegador": "Chrome", "perfil": "Pessoa 1", "caminho": str(support / "Google/Chrome/Default/Network/Cookies")},
        {"id": "chrome:Profile 1", "navegador": "Chrome", "perfil": "Trabalho", "caminho": str(support / "Google/Chrome/Profile 1/Cookies")},
    ]
    assert cc.list_sources(support / "nada") == []


def test_chrome_cookies_decrypt_filter_and_expire(support):
    asked: list[tuple[str, str]] = []

    def reader(service: str, account: str) -> str:
        asked.append((service, account))
        return PASSWORD

    got = cc.read_cookies("chrome:Default", None, support, reader, now=time.time())
    assert asked == [("Chrome Safe Storage", "Chrome")]
    by_name = {c["nome"]: c for c in got["cookies"]}
    assert set(by_name) == {"sessao", "tema", "token"} and got["ignorados"] == 1  # o "velho" expirou; o "quebrado" não decifra
    assert by_name["sessao"] == {
        "nome": "sessao", "valor": "valor-secreto", "dominio": ".exemplo.com", "caminho": "/", "expira": pytest.approx(FUTURE, abs=1),
        "seguro": True, "http_only": True, "same_site": "lax",
    }  # fmt: skip
    assert by_name["tema"]["valor"] == "escuro" and by_name["tema"]["expira"] is None and by_name["tema"]["same_site"] is None
    assert by_name["token"]["same_site"] == "strict" and by_name["token"]["caminho"] == "/v1"

    only = cc.read_cookies("chrome:Default", ["exemplo.com"], support, reader)
    assert {c["nome"] for c in only["cookies"]} == {"sessao", "tema"}
    assert {c["nome"] for c in cc.read_cookies("chrome:Default", [".outro.com"], support, reader)["cookies"]} == {"token"}

    old = cc.read_cookies("chrome:Profile 1", None, support, reader)
    assert old["cookies"][0]["valor"] == "sem-prefixo"


def test_chrome_cookies_refusals(support):
    def refuse(_service: str, _account: str) -> str:
        raise cc.ChromeCookieError("o Keychain recusou")

    with pytest.raises(cc.ChromeCookieError, match="o macOS não liberou a chave do Chrome"):
        cc.read_cookies("chrome:Default", None, support, refuse)
    for bad in ("safari:Default", "chrome:", "chrome:../x", "chrome:Sem Cookies"):
        with pytest.raises(cc.ChromeCookieError):
            cc.read_cookies(bad, None, support, lambda *_: PASSWORD)
    wrong = cc.read_cookies("chrome:Default", None, support, lambda *_: "senha-errada")
    assert {c["nome"] for c in wrong["cookies"]} == {"tema"}  # só o que não era cifrado


# --- rotas ---------------------------------------------------------------------------------------


def fake_argv(kind, settings):
    return ["/bin/cat"]


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


def test_answer_route_wakes_the_waiting_tool(core):
    client, app = core
    events = app.state.manager.events
    queue = events.subscribe()  # uma "janela" ligada
    out: dict = {}
    worker = threading.Thread(target=lambda: out.update(r=app.state.hub.browser.request("s1", "Claude", "/repo", "ler", {}, timeout=5)))
    worker.start()
    event = None
    for _ in range(200):
        try:
            event = queue.get_nowait()
        except asyncio.QueueEmpty:
            time.sleep(0.01)
            continue
        if event.get("type") == "browser.command":
            break
    assert event and event["type"] == "browser.command"
    answer = {"ok": True, "resultado": {"aba": "browser-1", "texto": "oi"}}
    assert client.post(f"/navegador/resposta/{event['id']}", json=answer, headers=AUTH).status_code == 204
    worker.join(5)
    assert out["r"] == {"aba": "browser-1", "texto": "oi"}
    assert client.post(f"/navegador/resposta/{event['id']}", json=answer, headers=AUTH).status_code == 404
    assert client.post("/navegador/resposta/abc", json={"ok": True}).status_code == 401
    events.unsubscribe(queue)


def test_history_and_profile_routes(core):
    client, _ = core
    assert client.post("/navegador/historico", json={"url": "https://exemplo.com", "titulo": "Exemplo"}, headers=AUTH).status_code == 204
    assert client.post("/navegador/historico", json={"url": "about:blank"}, headers=AUTH).status_code == 204
    items = client.get("/navegador/historico", params={"q": "exem"}, headers=AUTH).json()["itens"]
    assert [i["url"] for i in items] == ["https://exemplo.com"] and items[0]["visitas"] == 1
    assert client.get("/navegador/historico", params={"limite": 0}, headers=AUTH).status_code == 422
    assert client.delete("/navegador/historico", headers=AUTH).status_code == 204
    assert client.get("/navegador/historico", headers=AUTH).json() == {"itens": []}

    assert client.get("/navegador/perfis", headers=AUTH).json()["perfis"][0]["id"] == "padrao"
    created = client.post("/navegador/perfis", json={"nome": "Clientes"}, headers=AUTH).json()
    assert created["id"] == "clientes" and len(created["identificador"]) == 32
    assert client.post("/navegador/perfis", json={"nome": "clientes"}, headers=AUTH).status_code == 409
    assert client.post("/navegador/perfis", json={"nome": " "}, headers=AUTH).status_code == 400
    assert client.patch("/navegador/perfis/clientes", json={"nome": "Clientes 2"}, headers=AUTH).json()["nome"] == "Clientes 2"
    assert client.patch("/navegador/perfis/padrao", json={"nome": "X"}, headers=AUTH).status_code == 400
    assert client.patch("/navegador/perfis/nada", json={"nome": "X"}, headers=AUTH).status_code == 404
    assert client.delete("/navegador/perfis/padrao", headers=AUTH).status_code == 400
    assert client.delete("/navegador/perfis/clientes", headers=AUTH).status_code == 204
    assert [p["id"] for p in client.get("/navegador/perfis", headers=AUTH).json()["perfis"]] == ["padrao"]


def test_import_routes(core, support):
    client, app = core
    app.state.chrome_support = support
    app.state.chrome_password = lambda _s, _a: PASSWORD
    sources = client.get("/navegador/importar", headers=AUTH).json()["fontes"]
    assert [s["id"] for s in sources] == ["chrome:Default", "chrome:Profile 1"]
    got = client.post("/navegador/importar", json={"fonte": "chrome:Default", "dominios": ["exemplo.com"]}, headers=AUTH).json()
    assert {c["nome"] for c in got["cookies"]} == {"sessao", "tema"} and got["ignorados"] == 1

    def refuse(_s, _a):
        raise cc.ChromeCookieError("o Keychain recusou")

    app.state.chrome_password = refuse
    refused = client.post("/navegador/importar", json={"fonte": "chrome:Default"}, headers=AUTH)
    assert refused.status_code == 400 and refused.json()["detail"] == "o macOS não liberou a chave do Chrome"
    assert "valor-secreto" not in refused.text
    assert client.post("/navegador/importar", json={"fonte": "safari:x"}, headers=AUTH).status_code == 400
