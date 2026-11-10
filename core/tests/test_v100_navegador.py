"""v1.0, revisão do navegador (PR #21): aprovação do navegador_js e do digitar com enviar, a
espera sem alvo, a ponte com mais de uma janela ligada e, no script injetado nas páginas, as refs
dentro de shadow DOM e o navegador_js que o CSP da página não bloqueia."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core.activity import ActivityLog
from harness_core.app import create_app
from harness_core.brain_index import BrainIndex
from harness_core.browser_bridge import BridgeError, BrowserBridge
from harness_core.connectors import ConnectorStore
from harness_core.kanban import Kanban
from harness_core.keychain import MemoryVault
from harness_core.mcp_hub import Hub
from harness_core.vault import Vault

from .conftest import TOKEN
from .test_v098b_navegador import FakeBridge, FakeEvents, call, text_of

AUTH = {"X-Harness-Token": TOKEN}
REPO = Path(__file__).resolve().parents[2]


# --- aprovação ----------------------------------------------------------------------------------


@pytest.fixture
def hub(settings, tmp_path):
    """Central com o navegador falso; `answer` diz o que o Pedro responde no cartão."""
    vault = Vault(settings.brain)
    bridge = FakeBridge()
    state = {"answer": True, "approvals": []}

    def publish(event: dict) -> None:
        if event.get("type") == "approval":
            state["approvals"].append(event["approval"])
            central.decide(event["approval"]["id"], state["answer"])

    central = Hub(
        connectors=ConnectorStore(settings.home, MemoryVault()),
        brain=BrainIndex(vault, settings.home / "brain.db"),
        kanban=Kanban(vault),
        vault=vault,
        activity=ActivityLog(settings.home / "atividade.db"),
        publish=publish,
        session_info=lambda _s: {"who": "Claude", "cwd": str(tmp_path), "allowed": None},
        browser=bridge,
    )
    return central, central.register("sessao-1"), bridge, state


def test_js_asks_approval_and_refusal_does_not_touch_the_page(hub):
    central, token, bridge, state = hub
    state["answer"] = False
    refused = call(central, token, "navegador_js", {"codigo": "document.forms[0].submit()"})
    assert refused["isError"] and "recusou" in text_of(refused)
    assert bridge.calls == []  # a página não recebeu nada
    card = state["approvals"][-1]
    assert card["tool"] == "navegador_js" and card["account"] == "MÊTIS"
    assert "document.forms[0].submit()" in card["summary"]

    state["answer"] = True
    assert json.loads(text_of(call(central, token, "navegador_js", {"codigo": "1+1"}))) == {"n": 2}
    assert bridge.calls[-1][0] == "js" and len(state["approvals"]) == 2


def test_typing_asks_approval_only_when_it_sends(hub):
    central, token, bridge, state = hub
    state["answer"] = False
    call(central, token, "navegador_digitar", {"ref": "e3", "texto": "rascunho"})
    assert bridge.calls[-1] == ("digitar", {"ref": "e3", "texto": "rascunho", "enviar": False, "limpar": True}, 30)
    assert state["approvals"] == []

    sent = call(central, token, "navegador_digitar", {"ref": "e3", "texto": "Oi, tudo certo?", "enviar": True})
    assert sent["isError"] and "recusou" in text_of(sent)
    assert len(bridge.calls) == 1  # o envio não chegou à página
    card = state["approvals"][-1]
    assert card["tool"] == "navegador_digitar" and "Oi, tudo certo?" in card["summary"] and "Enter" in card["summary"]

    state["answer"] = True
    call(central, token, "navegador_digitar", {"ref": "e3", "texto": "Oi, tudo certo?", "enviar": True})
    assert bridge.calls[-1][1]["enviar"] is True


def test_reading_opening_and_clicking_stay_free(hub):
    central, token, bridge, state = hub
    state["answer"] = False  # se algum pedisse aprovação, viria recusado
    assert not call(central, token, "navegador_abrir", {"url": "exemplo.com"}).get("isError")
    assert not call(central, token, "navegador_ler").get("isError")
    assert not call(central, token, "navegador_clicar", {"ref": "e3"}).get("isError")
    assert not call(central, token, "navegador_tecla", {"tecla": "Enter"}).get("isError")
    assert state["approvals"] == []
    assert [c[0] for c in bridge.calls] == ["abrir", "ler", "clicar", "tecla"]


def test_catalog_marks_js_as_write_and_rehearsal_skips_sending(settings, accounts):
    def flow(enviar: bool) -> dict:
        return {
            "nome": f"Mandar no navegador {enviar}",
            "gatilho": {"tipo": "manual", "x": 0, "y": 0},
            "passos": [{"id": "digitar", "tipo": "ferramenta", "titulo": "Digitar", "ferramenta": "navegador_digitar",
                        "argumentos": {"seletor": "#msg", "texto": "oi", "enviar": enviar}, "x": 200, "y": 0}],
            "ligacoes": [{"de": "gatilho", "para": "digitar"}],
        }  # fmt: skip

    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, keychain=MemoryVault(), run_scheduler=False)
    with TestClient(app) as client:
        tools = {t["nome"]: t for t in client.get("/automacoes/catalogo", headers=AUTH).json()["ferramentas"]}
        assert tools["navegador_js"]["pessoas"] and not tools["navegador_ler"]["pessoas"]

        def rehearse(enviar: bool) -> dict:
            automation_id = client.post("/automacoes", json={"nome": f"x{enviar}", "desenho": flow(enviar)}, headers=AUTH).json()["id"]
            run_id = client.post(f"/automacoes/{automation_id}/testar", json={}, headers=AUTH).json()["execucao"]
            deadline = time.time() + 8
            while time.time() < deadline:
                run = client.get(f"/execucoes/{run_id}", headers=AUTH).json()
                if run["status"] != "rodando":
                    return run["steps"]["digitar"]
                time.sleep(0.05)
            raise AssertionError("o ensaio não terminou")

        # No ensaio, digitar e mandar não chega à página; só digitar chega (e aqui não há janela).
        assert rehearse(True)["saida"]["ensaio"] is True
        assert rehearse(False)["status"] == "erro"


# --- esperar ------------------------------------------------------------------------------------


def test_wait_without_text_or_selector_is_refused(hub):
    central, token, bridge, _ = hub
    missing = call(central, token, "navegador_esperar", {"segundos": 30})
    assert missing["isError"] and "texto ou um seletor" in text_of(missing)
    assert call(central, token, "navegador_esperar", {"texto": "  ", "seletor": ""})["isError"]
    assert bridge.calls == []  # nada de esperar 30 s à toa
    assert text_of(call(central, token, "navegador_esperar", {"texto": "Pronto"})).startswith("achou")


# --- ponte com duas janelas -----------------------------------------------------------------------


def answer_later(bridge: BrowserBridge, *answers: tuple[float, bool, object, str | None]):
    def on_publish(event: dict) -> None:
        for delay, ok, result, error in answers:
            threading.Timer(delay, bridge.resolve, (event["id"], ok, result, error)).start()

    return on_publish


def test_instant_refusal_from_a_window_without_browser_does_not_win():
    events = FakeEvents(listeners=2)
    bridge = BrowserBridge(events)
    events.on_publish = answer_later(
        bridge,
        (0.0, False, None, "o navegador da MÊTIS só funciona no app (não na versão de desenvolvimento no Chrome)"),
        (0.15, True, {"aba": "browser-1"}, None),
    )
    assert bridge.request("s1", "Claude", None, "ler", {}, timeout=3) == {"aba": "browser-1"}


def test_error_counts_when_every_window_refused_or_the_other_stayed_silent():
    events = FakeEvents(listeners=2)
    bridge = BrowserBridge(events)
    events.on_publish = answer_later(
        bridge,
        (0.0, False, None, "só funciona no app"),
        (0.1, False, None, "a ref e12 não existe mais: leia a página de novo (navegador_ler)"),
    )
    started = time.time()
    with pytest.raises(BridgeError, match="a ref e12 não existe mais"):
        bridge.request("s1", "Claude", None, "clicar", {"ref": "e12"}, timeout=5)
    assert time.time() - started < 3  # não esperou o tempo todo

    events.on_publish = answer_later(bridge, (0.0, False, None, "só funciona no app"))
    with pytest.raises(BridgeError, match="só funciona no app"):  # o erro, não "não respondeu"
        bridge.request("s1", "Claude", None, "ler", {}, timeout=0.4)
    assert bridge.waiting == 0

    alone = FakeEvents(listeners=1)
    single = BrowserBridge(alone)
    alone.on_publish = lambda e: single.resolve(e["id"], False, None, "não há aba de navegador nesta worktree")
    started = time.time()
    with pytest.raises(BridgeError, match="não há aba"):
        single.request("s1", "Claude", None, "ler", {}, timeout=5)
    assert time.time() - started < 1  # com uma janela só, o erro vale na hora


# --- o script das páginas (browser.js), num DOM de mentira no node ------------------------------

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const [source, ts] = process.argv.slice(2).map((p) => fs.readFileSync(p, "utf8"));

function matches(el, selector) {
  return selector.split(",").some((part) => {
    const m = /^([a-z0-9]*)(?:\[([\w-]+)(?:="([^"]*)")?\])?$/i.exec(part.trim());
    if (!m || !(m[1] || m[2])) return false;
    if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
    if (m[2] && !(m[2] in el.attrs)) return false;
    return m[3] === undefined || el.attrs[m[2]] === m[3];
  });
}
class El {
  constructor(tag, text = "", children = [], display = "block") {
    Object.assign(this, { tagName: tag.toUpperCase(), nodeType: 1, attrs: {}, kids: [], text, display, parentElement: null, shadowRoot: null, isConnected: true });
    children.forEach((c) => this.add(c));
  }
  add(child, shadow) {
    child.parentElement = shadow ? null : this;
    child.siblings = shadow ? this.shadowRoot.kids : this.kids;
    child.siblings.push(child);
  }
  attach(children) {
    this.shadowRoot = { kids: [], get firstElementChild() { return this.kids[0] || null; } };
    children.forEach((c) => this.add(c, true));
  }
  get firstChild() { return this.kids[0] || null; }
  get firstElementChild() { return this.kids[0] || null; }
  get nextSibling() { return this.siblings[this.siblings.indexOf(this) + 1] || null; }
  get nextElementSibling() { return this.nextSibling; }
  get innerText() { return this.text; }
  get textContent() { return this.text; }
  get isContentEditable() { return false; }
  hasAttribute(n) { return n in this.attrs; }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  removeAttribute(n) { delete this.attrs[n]; }
  getClientRects() { return [1]; }
  getBoundingClientRect() { return { top: 10, bottom: 30, left: 10, right: 90, width: 80, height: 20 }; }
  scrollIntoView() {}
  all() { return this.kids.flatMap((k) => [k, ...k.all()]); }  // só o DOM de luz, como o de verdade
  querySelectorAll(selector) { return this.all().filter((el) => matches(el, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const shadowSave = new El("button", "Salvar");
const card = new El("metis-card", "", [], "inline");
card.attach([shadowSave]);
const body = new El("body", "", [new El("h1", "Painel"), new El("button", "Abrir"), card]);
const html = new El("html", "", [body]);
html.scrollTop = 0;
html.scrollHeight = 800;
const document = { body, documentElement: html, title: "Painel" };
["querySelector", "querySelectorAll"].forEach((k) => (document[k] = html[k].bind(html)));

const page = {
  document, console: { log() {}, info() {}, warn() {}, error() {}, debug() {} }, setTimeout, clearTimeout, URL,
  location: { href: "https://exemplo.com/", origin: "https://exemplo.com" }, innerHeight: 800, innerWidth: 1200,
  addEventListener() {}, getComputedStyle: (el) => ({ display: el.display, visibility: "visible" }),
};
page.window = page;
page.top = page;
vm.createContext(page);
vm.runInContext(source, page);
// O CSP de um site sem 'unsafe-eval': o eval de dentro da página é recusado.
vm.runInContext("eval = function () { throw new EvalError(\"Refused to evaluate a string as JavaScript because 'unsafe-eval' is not an allowed source of script\"); };", page);

// O script que a MÊTIS manda ao evaluateJavaScript no navegador_js (agentJs, em app/src/lib/browser.ts).
const template = /const script = `([^`]*)`;/.exec(ts.slice(ts.indexOf("export async function agentJs")));
const script = (code) => template[1].replace(/\\n/g, "\n").replace("${expression}", () => code);

const out = {};
const agent = (action, args) => JSON.parse(page.__metis.agent(action, args));
out.ler = agent("ler", {});
const ref = (/\[(e\d+)\] botão "Salvar"/.exec(out.ler.v) || [])[1];
out.ref = ref || null;
out.rolar = ref ? agent("rolar", { ref }) : null;
out.template = !!template;
out.evalDireto = agent("js", { codigo: "document.title" });
if (template) {
  out.titulo = JSON.parse(vm.runInContext(script("document.title"), page));
  out.objeto = JSON.parse(vm.runInContext(script("{ a: 1, b: [document.title] }"), page));
  out.erro = JSON.parse(vm.runInContext(script("naoExiste.x"), page));
  const pending = JSON.parse(vm.runInContext(script("Promise.resolve(41 + 1)"), page));
  setTimeout(() => {
    out.promessa = pending.pendente ? JSON.parse(page.__metis.result(pending.pendente)) : pending;
    console.log(JSON.stringify(out));
  }, 30);
} else console.log(JSON.stringify(out));
"""


@pytest.fixture
def page_script(tmp_path) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node não está instalado")
    harness = tmp_path / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    done = subprocess.run(
        [node, str(harness), str(REPO / "app/src-tauri/src/browser.js"), str(REPO / "app/src/lib/browser.ts")],
        capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_refs_inside_shadow_dom_are_found(page_script):
    assert page_script["ler"]["ok"] and '# Painel' in page_script["ler"]["v"]
    assert re.search(r'\[e1\] botão "Abrir"', page_script["ler"]["v"])
    assert page_script["ref"] == "e2"  # o botão de dentro do shadow DOM também ganhou ref
    assert page_script["rolar"] == {"ok": True, "v": 'rolou até botão "Salvar"'}


def test_js_runs_without_eval_so_the_page_csp_does_not_block_it(page_script):
    assert page_script["template"], "agentJs em app/src/lib/browser.ts mudou de forma; ajuste o teste"
    assert page_script["titulo"] == {"ok": True, "v": "Painel"}
    assert page_script["objeto"] == {"ok": True, "v": {"a": 1, "b": ["Painel"]}}
    assert page_script["erro"]["ok"] is False and "naoExiste" in page_script["erro"]["e"]
    assert page_script["promessa"] == {"ok": True, "v": 42}
    # O eval da página (o caminho que sobra para vários comandos) explica o bloqueio do CSP.
    assert page_script["evalDireto"]["ok"] is False and "bloqueia eval (CSP)" in page_script["evalDireto"]["e"]
