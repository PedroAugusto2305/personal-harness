"""v0.9.3 (bloco B da paridade): comandos salvos, atalhos remapeáveis e temas do Ghostty."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import ghostty
from harness_core.app import create_app
from harness_core.commands import CommandError, CommandStore, Keymap, valid_combo

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


@pytest.fixture
def fake_ghostty(tmp_path, monkeypatch):
    """Pastas do Ghostty de mentira: nunca o ~ de verdade."""
    user = tmp_path / "gh-user" / "themes"
    app_dir = tmp_path / "gh-app" / "themes"
    user.mkdir(parents=True)
    app_dir.mkdir(parents=True)
    config = tmp_path / "gh-user" / "config"
    monkeypatch.setattr(ghostty, "theme_dirs", lambda: [(user, "usuario"), (app_dir, "ghostty")])
    monkeypatch.setattr(ghostty, "config_files", lambda: [config, tmp_path / "gh-user" / "config.ghostty"])
    return user, app_dir, config


@pytest.fixture
def core(settings, accounts, fake_ghostty):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


# --- comandos salvos ------------------------------------------------------------------------------


def test_command_store_validates_and_persists(tmp_path):
    store = CommandStore(tmp_path)
    assert store.list() == []
    first = store.add({"nome": " Testes ", "texto": "uv run pytest -q", "tipo": "comando"})
    second = store.add({"nome": "Revisar", "texto": "Revise o diff", "tipo": "prompt", "projeto": "/repo"})
    assert first["nome"] == "Testes" and first["projeto"] is None and len(first["id"]) == 8
    assert second["projeto"] == "/repo"
    for bad in ({"nome": "", "texto": "x", "tipo": "comando"}, {"nome": "x", "texto": "x", "tipo": "macro"}, {"nome": "x", "tipo": "comando"}, {"nome": "x" * 81, "texto": "x", "tipo": "prompt"}):
        with pytest.raises(CommandError):
            store.add(bad)
    store.update(first["id"], {"texto": "uv run pytest", "projeto": ""})
    again = CommandStore(tmp_path)  # relê do arquivo
    assert [c["id"] for c in again.list()] == [first["id"], second["id"]]
    assert again.list()[0]["texto"] == "uv run pytest" and again.list()[0]["projeto"] is None
    with pytest.raises(KeyError):
        again.update("nada", {"nome": "x"})
    again.delete(second["id"])
    assert [c["id"] for c in CommandStore(tmp_path).list()] == [first["id"]]
    (tmp_path / "comandos.json").write_text("{lixo", encoding="utf-8")
    assert CommandStore(tmp_path).list() == []


def test_command_routes(core, settings):
    client, _app = core
    assert client.get("/comandos", headers=AUTH).json() == {"comandos": []}
    created = client.post("/comandos", json={"nome": "Build", "texto": "npm run build", "tipo": "comando"}, headers=AUTH)
    assert created.status_code == 200, created.text
    item = created.json()
    assert set(item) == {"id", "nome", "texto", "tipo", "projeto"}
    bad = client.post("/comandos", json={"nome": "x", "texto": "", "tipo": "comando"}, headers=AUTH)
    assert bad.status_code == 400 and "texto" in bad.json()["detail"]
    changed = client.put(f"/comandos/{item['id']}", json={"tipo": "prompt"}, headers=AUTH).json()
    assert changed["tipo"] == "prompt" and changed["texto"] == "npm run build"
    assert client.put("/comandos/zzz", json={"nome": "y"}, headers=AUTH).status_code == 404
    assert client.put(f"/comandos/{item['id']}", json={"tipo": "macro"}, headers=AUTH).status_code == 400
    assert json.loads((settings.home / "comandos.json").read_text(encoding="utf-8"))["comandos"][0]["tipo"] == "prompt"
    assert client.delete(f"/comandos/{item['id']}", headers=AUTH).json() == {"ok": True}
    assert client.delete(f"/comandos/{item['id']}", headers=AUTH).status_code == 404
    assert client.get("/comandos").status_code == 401


# --- atalhos -------------------------------------------------------------------------------------


def test_combo_format():
    for good in ("", "Meta+KeyK", "Meta+Shift+KeyD", "Ctrl+Backquote", "Meta+Alt+ArrowLeft", "F5", "Meta+Ctrl+Alt+Shift+Digit1"):
        assert valid_combo(good), good
    for bad in ("Shift+Meta+KeyK", "Meta+Meta+KeyK", "Cmd+KeyK", "Meta+", "Meta+Shift", "Meta+Key K", "Meta+Shift+" + "K" * 25):
        assert not valid_combo(bad), bad


def test_keymap_routes_and_bad_file(core, settings):
    client, _app = core
    empty = client.get("/atalhos", headers=AUTH).json()
    assert empty["atalhos"] == {} and empty["arquivo"].endswith("atalhos.json")
    saved = client.put("/atalhos", json={"atalhos": {"tela.dividir": "Meta+Shift+KeyD", "terminal.flutuante": ""}}, headers=AUTH)
    assert saved.status_code == 200 and saved.json()["atalhos"] == {"tela.dividir": "Meta+Shift+KeyD", "terminal.flutuante": ""}
    assert json.loads((settings.home / "atalhos.json").read_text(encoding="utf-8"))["tela.dividir"] == "Meta+Shift+KeyD"
    assert client.put("/atalhos", json={"atalhos": {"tela.dividir": "Shift+Meta+KeyD"}}, headers=AUTH).status_code == 400
    assert client.put("/atalhos", json={"atalhos": {"Tela Dividir": "Meta+KeyD"}}, headers=AUTH).status_code == 400
    assert client.put("/atalhos", json={"atalhos": ["x"]}, headers=AUTH).status_code == 400
    # substitui o mapa inteiro
    assert client.put("/atalhos", json={"atalhos": {"paleta": "Meta+KeyJ"}}, headers=AUTH).json()["atalhos"] == {"paleta": "Meta+KeyJ"}
    (settings.home / "atalhos.json").write_text("não é json", encoding="utf-8")
    assert client.get("/atalhos", headers=AUTH).json()["atalhos"] == {}


def test_keymap_drops_hand_typos(tmp_path):
    (tmp_path / "atalhos.json").write_text(json.dumps({"ok": "Meta+KeyK", "ruim": "Command+K", "Ruim": "Meta+KeyK"}), encoding="utf-8")
    assert Keymap(tmp_path).get()["atalhos"] == {"ok": "Meta+KeyK"}


# --- Ghostty -------------------------------------------------------------------------------------


def test_reader_maps_palette_and_derives_cursor():
    colors = ghostty.parse_theme(
        "# comentário\npalette = 0=#1D1F21\npalette = 15=eaeaea\npalette = 16=#ffffff\nbackground = 282c34\nforeground = #FFFFFF\nselection-background = #5a7898\nlixo sem igual\n"
    )
    assert colors == {
        "black": "#1d1f21",
        "brightWhite": "#eaeaea",
        "background": "#282c34",
        "foreground": "#ffffff",
        "selectionBackground": "#5a7898",
        "cursor": "#ffffff",
        "cursorAccent": "#282c34",
    }
    with pytest.raises(ghostty.GhosttyError):
        ghostty.parse_theme("font-size = 14\ntheme = Dracula\n")


def test_builtin_theme_is_complete():
    colors = ghostty.load_theme(ghostty.BUILTIN_NAME)
    assert colors["background"] == "#282c34" and colors["cursorAccent"] == "#282c34" and colors["selectionForeground"] == "#ffffff"
    assert all(colors[name] for name in ghostty.ANSI) and colors["brightCyan"] == "#70c0b1"


def test_pick_theme():
    assert ghostty.pick_theme("light:Ayu Light,dark:Ayu Dark") == "Ayu Dark"
    assert ghostty.pick_theme("dark:B, light:A") == "B"
    assert ghostty.pick_theme("light:Só Claro") == "Só Claro"
    assert ghostty.pick_theme("Dracula") == "Dracula"
    assert ghostty.pick_theme(None) is None


def test_list_and_config(fake_ghostty):
    user, app_dir, config = fake_ghostty
    (app_dir / "Dracula").write_text("background = #282a36\n", encoding="utf-8")
    (app_dir / "Ayu Dark").write_text("background = #0b0e14\n", encoding="utf-8")
    (user / "Dracula").write_text("background = #000000\n", encoding="utf-8")  # o do usuário ganha
    (user / ".escondido").write_text("background = #111111\n", encoding="utf-8")
    assert ghostty.config_info() is None
    themes = ghostty.list_themes()
    assert themes[0] == {"nome": ghostty.BUILTIN_NAME, "origem": "metis"}
    assert themes[1:] == [{"nome": "Ayu Dark", "origem": "ghostty"}, {"nome": "Dracula", "origem": "usuario"}]
    assert ghostty.load_theme("Dracula")["background"] == "#000000"
    config.write_text("font-size = 14\ntheme = light:Ayu Light,dark:Dracula\nforeground = #abcdef\n", encoding="utf-8")
    assert ghostty.config_info() == {"arquivo": str(config), "tema": "Dracula", "cores_proprias": True}
    assert [t["nome"] for t in ghostty.list_themes()][:2] == [ghostty.BUILTIN_NAME, ghostty.CONFIG_THEME]
    mixed = ghostty.load_theme(ghostty.CONFIG_THEME)
    assert mixed["background"] == "#000000" and mixed["foreground"] == "#abcdef" and mixed["cursor"] == "#abcdef"


def test_ghostty_routes(core, fake_ghostty):
    client, _app = core
    _user, app_dir, _config = fake_ghostty
    (app_dir / "Nord").write_text("palette = 4=#81a1c1\nbackground = #2e3440\n", encoding="utf-8")
    listing = client.get("/ghostty", headers=AUTH).json()
    assert listing["config"] is None and listing["temas"][0]["origem"] == "metis" and {"nome": "Nord", "origem": "ghostty"} in listing["temas"]
    nord = client.get("/ghostty/tema", params={"nome": "Nord"}, headers=AUTH).json()
    assert nord == {"nome": "Nord", "cores": {"blue": "#81a1c1", "background": "#2e3440", "cursorAccent": "#2e3440"}}
    assert client.get("/ghostty/tema", params={"nome": "Não Existe"}, headers=AUTH).status_code == 404
    assert client.get("/ghostty/tema", params={"nome": "../config"}, headers=AUTH).status_code == 400
    assert client.get("/ghostty/tema", params={"nome": "a/b"}, headers=AUTH).status_code == 400
    assert client.get("/ghostty/tema", params={"nome": ghostty.CONFIG_THEME}, headers=AUTH).status_code == 404
    read = client.post("/ghostty/ler", json={"texto": "foreground = #eeeeee\n"}, headers=AUTH).json()
    assert read == {"nome": "Tema colado", "cores": {"foreground": "#eeeeee", "cursor": "#eeeeee"}}
    named = client.post("/ghostty/ler", json={"texto": "background = #101010", "nome": " Meu "}, headers=AUTH).json()
    assert named["nome"] == "Meu"
    assert client.post("/ghostty/ler", json={"texto": "font-size = 12"}, headers=AUTH).status_code == 400
