"""v0.9.8 parte 2 (tela): barra lateral (fixar, apelido, cor), renomear terminal, worktree a partir
de branch ou commit, e os temas da tela (por prompt e importados do VS Code e do Obsidian)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import app as app_module
from harness_core import app_themes, cli
from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.barra_lateral import BarraError, SidebarStore
from harness_core.claude_print import ClaudePrintError

from .conftest import TOKEN, run

AUTH = {"X-Harness-Token": TOKEN}


def fake_argv(kind, settings):
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app
        for session_id in list(app.state.manager.sessions):
            client.delete(f"/sessions/{session_id}", headers=AUTH)


# --- barra lateral ------------------------------------------------------------------------


def test_sidebar_store_actions_and_validation(tmp_path):
    store = SidebarStore(tmp_path)
    assert store.state() == {"fixados": [], "nomes": {}, "cores": {}}
    store.patch({"fixar": {"caminho": "/w/a", "fixo": True}})
    store.patch({"fixar": {"caminho": "/w/b", "fixo": True}})
    store.patch({"fixar": {"caminho": "/w/a", "fixo": True}})  # de novo: vai para o fim, sem repetir
    assert store.state()["fixados"] == ["/w/b", "/w/a"]
    store.patch({"fixar": {"caminho": "/w/b", "fixo": False}})
    store.patch({"nome": {"caminho": "/w/a", "nome": "  Login   novo "}})
    state = store.patch({"cor": {"projeto": "meu-repo", "cor": "#A1B2C3"}})
    assert state == {"fixados": ["/w/a"], "nomes": {"/w/a": "Login novo"}, "cores": {"meu-repo": "#a1b2c3"}}
    # gravado em disco: outra instância lê o mesmo
    assert SidebarStore(tmp_path).state() == state
    assert json.loads((tmp_path / "barra.json").read_text())["cores"] == {"meu-repo": "#a1b2c3"}
    store.patch({"nome": {"caminho": "/w/a", "nome": ""}})
    store.patch({"cor": {"projeto": "meu-repo", "cor": ""}})
    assert store.state() == {"fixados": ["/w/a"], "nomes": {}, "cores": {}}
    for bad in (
        {},
        {"fixar": {"caminho": "/w/a", "fixo": True}, "cor": {"projeto": "p", "cor": "#000000"}},
        {"fixar": {"caminho": "", "fixo": True}},
        {"fixar": {"caminho": "/w/a", "fixo": "sim"}},
        {"nome": {"caminho": "/w/a", "nome": "x" * 61}},
        {"cor": {"projeto": "p", "cor": "vermelho"}},
        {"cor": {"projeto": "p", "cor": "#abc"}},
        {"outra": {}},
        [],
    ):
        with pytest.raises(BarraError):
            store.patch(bad)


def test_sidebar_routes_publish_the_state(core):
    client, app = core
    assert client.get("/barra", headers=AUTH).json() == {"fixados": [], "nomes": {}, "cores": {}}
    events = app.state.manager.events.subscribe()
    answer = client.patch("/barra", json={"fixar": {"caminho": "/w/x", "fixo": True}}, headers=AUTH)
    assert answer.status_code == 200 and answer.json()["fixados"] == ["/w/x"]
    published = []
    while not events.empty():
        published.append(events.get_nowait())
    assert {"type": "barra", "barra": answer.json()} in published
    assert client.patch("/barra", json={"cor": {"projeto": "p", "cor": "azul"}}, headers=AUTH).status_code == 400
    assert client.patch("/barra", json={"nome": {"caminho": "/w/x", "nome": "Apelido"}}, headers=AUTH).json()["nomes"] == {"/w/x": "Apelido"}


# --- renomear terminal ---------------------------------------------------------------------


def test_rename_session(core):
    client, app = core
    session = client.post("/sessions", json={"kind": "shell"}, headers=AUTH).json()
    events = app.state.manager.events.subscribe()
    answer = client.patch(f"/sessions/{session['id']}", json={"titulo": "  Servidor   de dev "}, headers=AUTH)
    assert answer.status_code == 200 and answer.json()["title"] == "Servidor de dev"
    assert app.state.manager.get(session["id"]).title == "Servidor de dev"
    published = []
    while not events.empty():
        published.append(events.get_nowait())
    assert {"type": "session.renamed", "id": session["id"], "title": "Servidor de dev"} in published
    listed = client.get("/sessions", headers=AUTH).json()
    assert any(s["id"] == session["id"] and s["title"] == "Servidor de dev" for s in listed)
    assert client.patch(f"/sessions/{session['id']}", json={"titulo": "   "}, headers=AUTH).status_code == 400
    assert client.patch(f"/sessions/{session['id']}", json={"titulo": "x" * 81}, headers=AUTH).status_code == 400
    assert client.patch(f"/sessions/{session['id']}", json={}, headers=AUTH).status_code == 400
    assert client.patch("/sessions/nao-existe", json={"titulo": "oi"}, headers=AUTH).status_code == 404


# --- worktree a partir de branch ou commit ---------------------------------------------


@pytest.fixture
def remote_repo(repo, tmp_path):
    """O repo com um origin (bare local): main e remota-x lá; local-y só aqui; remota-x só lá."""
    origin = tmp_path / "origin.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    run("git", "remote", "add", "origin", str(origin), cwd=repo)
    run("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    run("git", "checkout", "-q", "-b", "remota-x", cwd=repo)
    (repo / "remoto.txt").write_text("remoto\n", encoding="utf-8")
    run("git", "add", "remoto.txt", cwd=repo)
    run("git", "commit", "-q", "-m", "commit da remota", cwd=repo)
    run("git", "push", "-q", "origin", "remota-x", cwd=repo)
    run("git", "checkout", "-q", "main", cwd=repo)
    run("git", "branch", "-q", "-D", "remota-x", cwd=repo)
    run("git", "branch", "-q", "local-y", cwd=repo)
    run("git", "remote", "set-head", "origin", "main", cwd=repo)
    return repo


def test_refs_list_branches_and_commits(core, remote_repo):
    client, _ = core
    project = client.post("/projects", json={"path": str(remote_repo)}, headers=AUTH).json()
    refs = client.get(f"/projects/{project['id']}/refs", headers=AUTH).json()
    names = {b["nome"]: b for b in refs["branches"]}
    assert set(names) == {"main", "local-y", "origin/remota-x"}  # sem origin/HEAD e sem origin/main (tem a local)
    assert names["main"]["atual"] is True and names["local-y"]["atual"] is False
    assert names["origin/remota-x"]["remoto"] is True and names["origin/remota-x"]["titulo"] == "commit da remota"
    assert names["main"]["em_uso"] == str(remote_repo) or names["main"]["em_uso"].endswith("meu-repo")
    assert names["local-y"]["em_uso"] is None
    assert refs["commits"][0]["titulo"] == "primeiro" and len(refs["commits"][0]["sha"]) == 40
    assert set(refs["commits"][0]) == {"sha", "curto", "titulo", "autor", "quando"}
    filtered = client.get(f"/projects/{project['id']}/refs", params={"q": "REMOTA"}, headers=AUTH).json()
    assert [b["nome"] for b in filtered["branches"]] == ["origin/remota-x"] and filtered["commits"] == []
    by_sha = client.get(f"/projects/{project['id']}/refs", params={"q": refs["commits"][0]["sha"][:7]}, headers=AUTH).json()
    assert [c["titulo"] for c in by_sha["commits"]] == ["primeiro"]


def test_worktree_modes(core, settings, remote_repo):
    client, _ = core
    project = client.post("/projects", json={"path": str(remote_repo)}, headers=AUTH).json()
    url = f"/projects/{project['id']}/worktrees"
    root = settings.worktrees / "meu-repo"

    # branch local que já existe, sem nome: a pasta vem do branch
    local = client.post(url, json={"modo": "branch", "base": "local-y"}, headers=AUTH)
    assert local.status_code == 201, local.text
    assert local.json()["branch"] == "local-y" and local.json()["path"] == str(root / "local-y")
    refs = client.get(f"/projects/{project['id']}/refs", headers=AUTH).json()
    assert next(b for b in refs["branches"] if b["nome"] == "local-y")["em_uso"] == str(root / "local-y")
    # o mesmo branch de novo: já está aberto
    again = client.post(url, json={"modo": "branch", "base": "local-y", "name": "outra pasta"}, headers=AUTH)
    assert again.status_code == 409 and "já está aberto em" in again.json()["detail"]

    # remota sem local: cria a local seguindo a remota
    remote = client.post(url, json={"modo": "branch", "base": "origin/remota-x", "name": "Revisar remota"}, headers=AUTH)
    assert remote.status_code == 201, remote.text
    assert remote.json()["branch"] == "remota-x" and remote.json()["path"] == str(root / "revisar-remota")
    upstream = run("git", "rev-parse", "--abbrev-ref", "remota-x@{upstream}", cwd=remote_repo).strip()
    assert upstream == "origin/remota-x"
    assert (root / "revisar-remota" / "remoto.txt").is_file()

    # commit: branch novo com o nome, nesse commit
    first = run("git", "rev-list", "--max-parents=0", "HEAD", cwd=remote_repo).strip()
    (remote_repo / "depois.txt").write_text("depois\n", encoding="utf-8")
    run("git", "add", "depois.txt", cwd=remote_repo)
    run("git", "commit", "-q", "-m", "depois", cwd=remote_repo)
    from_commit = client.post(url, json={"modo": "commit", "base": first[:10], "name": "Do Começo"}, headers=AUTH)
    assert from_commit.status_code == 201, from_commit.text
    assert from_commit.json()["branch"] == "do-comeco"
    assert run("git", "rev-parse", "do-comeco", cwd=remote_repo).strip() == first
    assert not (root / "do-comeco" / "depois.txt").exists()

    # erros claros
    bad = {
        "commit inexistente": ({"modo": "commit", "base": "naoexiste", "name": "x"}, 400, "não existe"),
        "commit sem base": ({"modo": "commit", "name": "x"}, 400, "commit"),
        "branch inexistente": ({"modo": "branch", "base": "fantasma"}, 400, "não existe"),
        "branch sem base": ({"modo": "branch"}, 400, "branch"),
        "nova sem nome": ({"modo": "nova", "name": "  "}, 400, "nome"),
        "base inexistente": ({"name": "y", "base": "nada-disso"}, 400, "não existe"),
        "modo estranho": ({"modo": "xyz", "name": "y"}, 400, "modo"),
    }
    for label, (body, status, text) in bad.items():
        answer = client.post(url, json=body, headers=AUTH)
        assert answer.status_code == status, (label, answer.text)
        assert text in answer.json()["detail"], label
    # o modo padrão continua igual
    plain = client.post(url, json={"name": "Normal"}, headers=AUTH)
    assert plain.status_code == 201 and plain.json()["branch"] == "normal"


class FakeCore:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, home, method, path, body=None):
        self.calls.append((method, path, body))
        return self.answers[(method, path.split("?")[0])]


def run_cli(monkeypatch, settings, fake, argv):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_core", fake)
    return cli.main(argv)


def test_cli_worktree_from_branch_and_commit(monkeypatch, settings, capsys):
    fake = FakeCore({
        ("GET", "/projects"): [{"id": "repo", "name": "Repo", "path": "/r"}],
        ("POST", "/projects/repo/worktrees"): {"path": "/w/repo/feat-x", "branch": "feat/x"},
    })  # fmt: skip
    assert run_cli(monkeypatch, settings, fake, ["worktree", "nova", "repo", "--branch", "origin/feat/x"]) == 0
    assert fake.calls[-1][2] == {"name": "", "base": "origin/feat/x", "copy_env": True, "modo": "branch"}
    assert "branch: feat/x" in capsys.readouterr().out
    assert run_cli(monkeypatch, settings, fake, ["worktree", "nova", "repo", "Volta", "--commit", "abc1234", "--sem-env"]) == 0
    assert fake.calls[-1][2] == {"name": "Volta", "base": "abc1234", "copy_env": False, "modo": "commit"}
    calls = len(fake.calls)
    assert run_cli(monkeypatch, settings, fake, ["worktree", "nova", "repo", "--commit", "abc1234"]) == 1
    assert "diga o nome" in capsys.readouterr().err
    assert all(call[0] == "GET" for call in fake.calls[calls:])
    with pytest.raises(SystemExit):
        cli.main(["worktree", "nova", "repo", "x", "--base", "main", "--branch", "b"])


# --- temas da tela: cores e contraste -------------------------------------------------------


def test_jsonc_comments_trailing_commas_and_strings():
    text = """
    // comentário de linha
    {
      /* bloco */
      "url": "http://exemplo.com/a//b", // a barra dupla dentro do texto fica
      "lista": [1, 2, 3,],
      "aspas": "dizia \\"oi\\" // não é comentário",
    }
    """
    assert app_themes.jsonc_loads(text) == {"url": "http://exemplo.com/a//b", "lista": [1, 2, 3], "aspas": 'dizia "oi" // não é comentário'}


def test_vscode_include_alpha_and_terminal(tmp_path):
    (tmp_path / "base.json").write_text(
        '{ // base\n "colors": {"editor.background": "#101010", "editor.foreground": "#e0e0e0", "sideBar.background": "#0a0a0a",}, }',
        encoding="utf-8",
    )
    (tmp_path / "tema.json").write_text(
        json.dumps({
            "include": "./base.json",
            "colors": {
                "editor.background": "#202020",
                "editor.selectionBackground": "#ffffff80",
                "button.background": "#3b82f6",
                "terminal.ansiRed": "#ff0000",
                "terminal.ansiBrightGreen": "#00ff00",
            },
            "tokenColors": [{"scope": "x", "settings": {"foreground": "#123456"}}],
        }),
        encoding="utf-8",
    )  # fmt: skip
    colors = app_themes.load_vscode_colors(tmp_path / "tema.json")
    assert colors["editor.background"] == "#202020" and colors["sideBar.background"] == "#0a0a0a"
    cores, terminal = app_themes.from_vscode(colors, "escuro")
    assert cores["bg"] == "#202020" and cores["side"] == "#0a0a0a" and cores["acc"] == "#3b82f6"
    assert cores["sel"] == "#909090"  # branco com 50% sobre o fundo
    assert terminal == {"red": "#ff0000", "brightGreen": "#00ff00", "background": "#202020", "foreground": "#e0e0e0", "cursor": "#e0e0e0"}
    no_terminal = app_themes.from_vscode({"editor.background": "#ffffff"}, "claro")
    assert no_terminal[1] is None and no_terminal[0]["bg"] == "#ffffff"


def test_obsidian_css_vars_hsl_and_calc():
    css = """
    /* tema de teste */
    @import url("x.css");
    body { --accent-h: 200; --accent-s: 50%; --accent-l: 50%; --base-l: 12%; }
    body.theme-dark, .theme-light.algo {
      --background-primary: hsl(0, 0%, calc(var(--base-l) - 2%));
      --text-normal: rgb(220 220 220);
      --interactive-accent: hsl(var(--accent-h), var(--accent-s), calc((var(--accent-l) + 10%) * 1));
      --text-selection: rgba(255, 255, 255, 0.5) !important;
      --text-muted: var(--nao-existe, #999999);
    }
    .theme-dark .markdown-rendered { --background-primary: #ff0000; }
    """
    blocks = app_themes.css_blocks(css)
    assert blocks["base"]["--accent-h"] == "200"
    assert "--background-primary" in blocks["escuro"] and "--background-primary" in blocks["claro"]
    assert blocks["escuro"]["--text-selection"] == "rgba(255, 255, 255, 0.5)"
    variables = app_themes.obsidian_variables(css, "escuro")
    assert app_themes.css_color("--background-primary", variables, None) == "#1a1a1a"  # 10% de luz
    assert app_themes.css_color("--interactive-accent", variables, None) == "#66aacc"  # hsl(200, 50%, 60%)
    assert app_themes.css_color("--text-selection", variables, "#1a1a1a") == "#8c8c8c"
    cores = app_themes.from_obsidian(variables, "escuro")
    assert cores["tx"] == "#dcdcdc" and cores["mut"] == "#999999" and cores["term"] == cores["bg"]
    # o que o tema não define vem do Obsidian padrão
    assert cores["err"] == "#fb464c"
    assert app_themes.eval_calcs("calc(calc(10% + 5%) * 2)") == "30%"
    assert app_themes.eval_calcs("calc(1 + )") == "calc(1 + )"


def test_adjust_fixes_only_what_fails():
    good = app_themes.build("Bom", "escuro", {"bg": "#282a36", "tx": "#f8f8f2", "acc": "#82a0ff", "onacc": "#191a21"}, origin="prompt", source="t")
    assert app_themes.adjust(good)["ajustes"] == []
    bad = app_themes.build(
        "Ruim",
        "escuro",
        {"bg": "#202020", "tx": "#505050", "mut": "#404040", "acc": "#303060", "onacc": "#2a2a2a", "err": "#401010"},
        origin="prompt",
        source="t",
    )
    fixed = app_themes.adjust(bad)
    cores = fixed["cores"]
    assert app_themes.contrast(cores["tx"], cores["bg"]) >= 7
    assert app_themes.contrast(cores["mut"], cores["bg"]) >= 4.5
    assert app_themes.contrast(cores["acc"], cores["bg"]) >= 3
    assert app_themes.contrast(cores["err"], cores["bg"]) >= 3
    assert app_themes.contrast(cores["onacc"], cores["acc"]) >= 4.5 or cores["onacc"] in ("#ffffff", cores["bar"], "#14151b")
    assert cores["bg"] == "#202020"  # o fundo nunca muda
    assert "texto clareado para dar contraste" in fixed["ajustes"]
    assert "cor de erro clareada para dar contraste" in fixed["ajustes"]
    assert "texto sobre o destaque trocado para dar contraste" in fixed["ajustes"]
    light = app_themes.adjust(app_themes.build("Claro", "claro", {"bg": "#ffffff", "tx": "#cccccc"}, origin="prompt", source="t"))
    assert "texto escurecido para dar contraste" in light["ajustes"]
    with pytest.raises(app_themes.ThemeError):
        app_themes.build("x", "escuro", {"tx": "#ffffff"}, origin="prompt", source="t")  # sem fundo
    with pytest.raises(app_themes.ThemeError):
        app_themes.build("x", "meio", {"bg": "#000000"}, origin="prompt", source="t")


def test_from_prompt_good_and_bad_answers():
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return {"nome": "Oceano", "base": "escuro", "cores": {"bg": "#0b1d2a", "tx": "#e6f1ff", "acc": "#3fb6ff", "side": "#08151f"}}

    theme = app_themes.from_prompt("azul do fundo do mar, calmo", ask)
    assert theme["nome"] == "Oceano" and theme["origem"] == "prompt" and theme["fonte"] == "azul do fundo do mar, calmo"
    assert set(theme["cores"]) == set(app_themes.TOKENS) and theme["cores"]["side"] == "#08151f"
    assert "azul do fundo do mar" in prompts[0] and '"onacc": "#rrggbb"' in prompts[0]
    # sem base: decide pelo fundo
    light = app_themes.from_prompt("papel", lambda _: {"nome": "Papel", "cores": {"bg": "#fbf8f1", "tx": "#222222"}})
    assert light["base"] == "claro"
    with pytest.raises(app_themes.ThemeGenError):
        app_themes.from_prompt("qualquer coisa", lambda _: {"nome": "sem cores"})
    with pytest.raises(app_themes.ThemeGenError):
        app_themes.from_prompt("qualquer coisa", lambda _: {"nome": "x", "cores": {"tx": "#ffffff"}})
    with pytest.raises(app_themes.ThemeError):
        app_themes.from_prompt("oi", lambda _: {})


def test_prompt_route_saves_lists_and_deletes(core, settings, monkeypatch):
    client, app = core
    monkeypatch.setattr(app_module, "ask_json", lambda prompt, env, cwd, **kw: {"nome": "Vinho", "base": "escuro", "cores": {"bg": "#2a1018", "tx": "#f5e6ea", "acc": "#e0567a"}})
    events = app.state.manager.events.subscribe()
    made = client.post("/temas-app/prompt", json={"descricao": "vinho tinto"}, headers=AUTH)
    assert made.status_code == 201, made.text
    theme = made.json()
    assert theme["id"].startswith("vinho-") and (settings.home / "temas" / f"{theme['id']}.json").is_file()
    assert client.get("/temas-app", headers=AUTH).json()["temas"][0]["id"] == theme["id"]
    published = []
    while not events.empty():
        published.append(events.get_nowait())
    assert {"type": "temas-app"} in published
    assert client.post("/temas-app/prompt", json={"descricao": "x"}, headers=AUTH).status_code == 400

    def broken(prompt, env, cwd, **kw):
        raise ClaudePrintError("o Claude não respondeu: sem rede")

    monkeypatch.setattr(app_module, "ask_json", broken)
    failed = client.post("/temas-app/prompt", json={"descricao": "vinho tinto"}, headers=AUTH)
    assert failed.status_code == 502 and "sem rede" in failed.json()["detail"]
    monkeypatch.setattr(app_module, "ask_json", lambda prompt, env, cwd, **kw: {"nome": "sem cores"})
    assert client.post("/temas-app/prompt", json={"descricao": "vinho tinto"}, headers=AUTH).status_code == 502
    assert client.delete(f"/temas-app/{theme['id']}", headers=AUTH).status_code == 204
    assert client.delete(f"/temas-app/{theme['id']}", headers=AUTH).status_code == 404
    assert client.delete("/temas-app/..%2Fbarra", headers=AUTH).status_code == 404
    assert client.get("/temas-app", headers=AUTH).json() == {"temas": []}


# --- temas da tela: importar --------------------------------------------------------------


@pytest.fixture
def theme_sources(tmp_path, monkeypatch):
    builtin = tmp_path / "vscode-app" / "extensions"
    user = tmp_path / "vscode-user"
    ext = builtin / "theme-claro"
    (ext / "themes").mkdir(parents=True)
    (ext / "package.json").write_text(
        json.dumps({"contributes": {"themes": [{"label": "%claro.label%", "uiTheme": "vs", "path": "./themes/claro.json"}]}}),
        encoding="utf-8",
    )
    (ext / "package.nls.json").write_text(json.dumps({"claro.label": "Claro Teste"}), encoding="utf-8")
    (ext / "themes" / "claro.json").write_text('{"colors": {"editor.background": "#fafafa", "editor.foreground": "#222222",}}', encoding="utf-8")
    mine = user / "fulano.tema-noite-1.0.0"
    (mine / "t").mkdir(parents=True)
    (mine / "package.json").write_text(
        json.dumps({"contributes": {"themes": [
            {"label": "Noite", "uiTheme": "vs-dark", "path": "./t/noite.json"},
            {"label": "Antigo", "uiTheme": "vs-dark", "path": "./t/antigo.tmTheme"},
        ]}}),
        encoding="utf-8",
    )  # fmt: skip
    (mine / "t" / "noite.json").write_text(json.dumps({"colors": {"editor.background": "#0d1117", "terminal.ansiBlue": "#58a6ff"}}), encoding="utf-8")
    (mine / "t" / "antigo.tmTheme").write_text("<plist/>", encoding="utf-8")
    settings_json = tmp_path / "settings.json"
    settings_json.write_text('{\n  // meu tema\n  "workbench.colorTheme": "Noite",\n}', encoding="utf-8")
    monkeypatch.setattr(app_themes, "VSCODE_APPS", [("VS Code", builtin, user, settings_json), ("Cursor", tmp_path / "nada", tmp_path / "nada2", tmp_path / "nada.json")])

    vault = tmp_path / "Cofre"
    themes_dir = vault / ".obsidian" / "themes"
    (themes_dir / "Meu").mkdir(parents=True)
    (themes_dir / "Meu" / "theme.css").write_text(".theme-dark { --background-primary: #101820; --text-normal: #e8e8e8; }", encoding="utf-8")
    (themes_dir / "Velho.css").write_text("body { --background-primary: #fdfdfd; }", encoding="utf-8")
    (vault / ".obsidian" / "appearance.json").write_text(json.dumps({"cssTheme": "Meu"}), encoding="utf-8")
    config = tmp_path / "obsidian.json"
    config.write_text(json.dumps({"vaults": {"a1": {"path": str(vault), "open": True}, "b2": {"path": str(tmp_path / "sumiu")}}}), encoding="utf-8")
    monkeypatch.setattr(app_themes, "OBSIDIAN_CONFIG", config)
    return tmp_path


def test_list_sources_vscode_and_obsidian(theme_sources):
    sources = {(s["origem"], s["nome"], s["base"]): s for s in app_themes.list_sources()}
    assert sources[("vscode", "Claro Teste", "claro")]["onde"] == "VS Code"
    noite = sources[("vscode", "Noite", "escuro")]
    assert noite["em_uso"] is True and noite["onde"] == "VS Code · fulano.tema-noite-1.0.0"
    assert not any(name == "Antigo" for _, name, _ in sources)  # .tmTheme fica de fora
    meu = sources[("obsidian", "Meu", "escuro")]
    assert meu["em_uso"] is True and meu["onde"] == "Obsidian · cofre Cofre"
    assert ("obsidian", "Meu", "claro") not in sources  # só tem a variante escura
    assert ("obsidian", "Velho", "escuro") in sources and ("obsidian", "Velho", "claro") in sources
    assert sources[("obsidian", "Obsidian (padrão)", "escuro")]["em_uso"] is False  # o cofre usa um tema
    assert set(next(iter(sources.values()))) == {"id", "origem", "nome", "base", "onde", "em_uso"}


def test_import_route(core, theme_sources):
    client, _ = core
    fontes = client.get("/temas-app/importar", headers=AUTH).json()["fontes"]
    noite = next(f for f in fontes if f["nome"] == "Noite")
    made = client.post("/temas-app/importar", json={"id": noite["id"]}, headers=AUTH)
    assert made.status_code == 201, made.text
    theme = made.json()
    assert theme["origem"] == "vscode" and theme["nome"] == "Noite" and theme["cores"]["bg"] == "#0d1117"
    assert theme["terminal"]["blue"] == "#58a6ff" and theme["fonte"] == "VS Code · fulano.tema-noite-1.0.0 · Noite"
    meu = next(f for f in fontes if f["nome"] == "Meu")
    obsidian = client.post("/temas-app/importar", json={"id": meu["id"]}, headers=AUTH).json()
    assert obsidian["origem"] == "obsidian" and obsidian["cores"]["bg"] == "#101820" and obsidian["terminal"] is None
    default = client.post("/temas-app/importar", json={"id": "obsidian:padrao#claro"}, headers=AUTH).json()
    assert default["base"] == "claro" and default["cores"]["bg"] == "#ffffff"
    assert len(client.get("/temas-app", headers=AUTH).json()["temas"]) == 3
    assert client.post("/temas-app/importar", json={"id": "vscode:/etc/passwd"}, headers=AUTH).status_code == 404
    assert client.post("/temas-app/importar", json={}, headers=AUTH).status_code == 400
