"""v0.9.8 parte 1 (agentes e terminal): argumentos, variáveis e CLI "outra" nos agentes; modelo,
esforço e pedido na sessão nova; hibernar o agente parado; temas do Kitty e do Warp; o "/" da
barra; o contexto da sessão; a skill da MÊTIS; e os comandos `metis worktree nova` e `metis agente`."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import barra, cli, ghostty, themes
from harness_core import sessions as sessions_mod
from harness_core.agents import AgentError, AgentStore, parse_env, split_args
from harness_core.app import create_app
from harness_core.prefs import Prefs, PrefsError

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def fake_argv(kind, settings):
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


@pytest.fixture
def core(settings, accounts, monkeypatch, tmp_path):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    app.state.cli_homes = {"claude": tmp_path / "homes" / "claude", "codex": tmp_path / "homes" / "codex"}
    with TestClient(app) as client:
        yield client, app
        for session_id in list(app.state.manager.sessions):
            client.delete(f"/sessions/{session_id}", headers=AUTH)


def argv_of(app, session_id: str) -> list[str]:
    return app.state.manager.get(session_id).pty.argv


def agent_body(**extra) -> dict:
    return {"name": "Revisor", "cli": "claude", **extra}


# --- agentes: argumentos, variáveis e a CLI "outra" ------------------------------------------


def test_env_and_args_validation():
    assert parse_env("# comentário\n\nAPI_URL=http://x?a=1\n DEBUG = 1 \n") == {"API_URL": "http://x?a=1", "DEBUG": "1"}
    for bad in ("api_url=1", "SEM_IGUAL", "1X=2", "PATH=/tmp", "HARNESS_TOKEN=x", "METIS_MCP_TOKEN=x"):
        with pytest.raises(AgentError):
            parse_env(bad)
    assert split_args('--verbose --nome "dois nomes"') == ["--verbose", "--nome", "dois nomes"]
    with pytest.raises(AgentError, match="aspas"):
        split_args('--nome "sem fechar')


def test_agent_fields_are_saved_and_checked(tmp_path):
    store = AgentStore(tmp_path / "agents")
    saved = store.save({"name": "Revisor", "cli": "codex", "args": "--search", "env": "FOO=bar\n# nota\nBAZ=1", "command": "ignorado"})
    again = store.get(saved.id)
    assert (again.args, again.env, again.command) == ("--search", "FOO=bar\n# nota\nBAZ=1", "")  # comando só na "outra"
    other = store.save({"name": "Aider", "cli": "outra", "command": "aider --model sonnet", "args": "--no-git"})
    assert store.get(other.id).command == "aider --model sonnet"
    with pytest.raises(AgentError, match="outra"):
        store.save({"name": "Vazia", "cli": "outra"})
    with pytest.raises(AgentError):
        store.save({"name": "Ruim", "cli": "claude", "env": "PATH=/x"})
    with pytest.raises(AgentError):
        store.save({"name": "Ruim", "cli": "claude", "args": "'aberta"})


def test_agent_routes_accept_new_fields_and_refuse_bad_ones(core):
    client, _ = core
    created = client.post("/agents", json=agent_body(args="--verbose", env="FOO=1"), headers=AUTH)
    assert created.status_code == 201, created.text
    agent = created.json()
    assert (agent["args"], agent["env"]) == ("--verbose", "FOO=1")
    bad = client.put(f"/agents/{agent['id']}", json=agent_body(env="METIS_X=1"), headers=AUTH)
    assert bad.status_code == 400 and "METIS_X" in bad.json()["detail"]
    assert client.put("/agents/nao-existe", json=agent_body(), headers=AUTH).status_code == 404
    assert client.post("/agents", json=agent_body(cli="outra"), headers=AUTH).status_code == 400
    assert client.post("/agents", json=agent_body(cli="gemini"), headers=AUTH).status_code == 422


def test_claude_and_codex_sessions_get_agent_args_and_env(core):
    client, app = core
    claude = client.post("/agents", json=agent_body(args='--add-dir "/tmp/duas pastas"', env="FOO=bar"), headers=AUTH).json()
    session = client.post("/sessions", json={"kind": "claude", "agent": claude["id"]}, headers=AUTH).json()
    argv = argv_of(app, session["id"])
    assert argv[argv.index("--add-dir") + 1] == "/tmp/duas pastas"
    assert app.state.manager.get(session["id"]).pty.env["FOO"] == "bar"
    codex = client.post("/agents", json={"name": "Codexeiro", "cli": "codex", "args": "--search"}, headers=AUTH).json()
    session = client.post("/sessions", json={"kind": "codex", "agent": codex["id"]}, headers=AUTH).json()
    assert "--search" in argv_of(app, session["id"])


def test_other_cli_agent_becomes_a_shell_session(core, tmp_path):
    client, app = core
    folder = tmp_path / "pasta"
    folder.mkdir()
    agent = client.post("/agents", json={"name": "Gato", "cli": "outra", "command": "cat -u", "args": "-", "env": "GATO=1", "folder": str(folder)}, headers=AUTH).json()
    session = client.post("/sessions", json={"kind": "claude", "agent": agent["id"]}, headers=AUTH)
    assert session.status_code == 201, session.text
    data = session.json()
    assert data["kind"] == "shell" and data["title"] == "Gato" and data["agent"] == agent["id"] and data["cwd"] == str(folder)
    pty = app.state.manager.get(data["id"]).pty
    assert Path(pty.argv[0]).name == "cat" and pty.argv[1:] == ["-u", "-"]
    assert pty.env["GATO"] == "1" and "METIS_MCP_TOKEN" not in pty.env  # sem a central de MCP
    missing = client.post("/agents", json={"name": "Sumido", "cli": "outra", "command": "cli-que-nao-existe-metis --x"}, headers=AUTH).json()
    refused = client.post("/sessions", json={"kind": "claude", "agent": missing["id"]}, headers=AUTH)
    assert refused.status_code == 400 and refused.json()["detail"] == "não achei cli-que-nao-existe-metis no PATH"
    draft = client.post("/sessions", json={"kind": "claude", "draft": {"name": "Rascunho", "cli": "outra", "command": 'cat "sem fechar'}}, headers=AUTH)
    assert draft.status_code == 400 and "aspas" in draft.json()["detail"]


# --- sessão nova: modelo, esforço e pedido ---------------------------------------------------


def test_model_effort_and_prompt_on_new_session(core):
    client, app = core
    claude = client.post("/sessions", json={"kind": "claude", "model": "opus", "effort": "high", "prompt": "rode os testes"}, headers=AUTH).json()
    argv = argv_of(app, claude["id"])
    assert argv[argv.index("--model") + 1] == "opus" and argv[1] == "rode os testes"
    assert not any("model_reasoning_effort" in a for a in argv)  # esforço é só do Codex
    codex = client.post("/sessions", json={"kind": "codex", "model": "gpt-5.5-codex", "effort": "xhigh"}, headers=AUTH).json()
    argv = argv_of(app, codex["id"])
    assert argv[argv.index("-m") + 1] == "gpt-5.5-codex"
    assert argv[argv.index('model_reasoning_effort="xhigh"') - 1] == "-c"
    # O modelo do pedido vence o do agente, sem repetir a flag.
    agent = client.post("/agents", json=agent_body(model="sonnet"), headers=AUTH).json()
    chosen = client.post("/sessions", json={"kind": "claude", "agent": agent["id"], "model": "haiku"}, headers=AUTH).json()
    argv = argv_of(app, chosen["id"])
    assert argv.count("--model") == 1 and argv[argv.index("--model") + 1] == "haiku"
    for bad in ({"model": "rm -rf /"}, {"effort": "max"}, {"prompt": "x" * 8001}):
        assert client.post("/sessions", json={"kind": "codex", **bad}, headers=AUTH).status_code == 422


# --- hibernar ----------------------------------------------------------------------------------


def test_hibernate_pref_is_validated(tmp_path):
    prefs = Prefs(tmp_path)
    assert prefs.get()["hibernar_min"] == 0
    assert prefs.update({"hibernar_min": 30})["hibernar_min"] == 30
    for bad in (10, "15", True, -1):
        with pytest.raises(PrefsError):
            prefs.update({"hibernar_min": bad})


def waiting_argv(kind, settings):
    # Fica vivo de verdade com qualquer argumento que a MÊTIS acrescente (viram $0, $1… do sh).
    return ["/bin/sh", "-c", "exec sleep 300"]


def test_idle_agent_hibernates_and_wakes(core, monkeypatch):
    client, app = core
    monkeypatch.setattr(sessions_mod, "resolve_argv", waiting_argv)
    manager = app.state.manager
    published: list[dict] = []
    original = manager.events.publish
    manager.events.publish = lambda event: (published.append(event), original(event))[1]
    agent = client.post("/sessions", json={"kind": "claude"}, headers=AUTH).json()
    routine = client.post("/sessions", json={"kind": "claude", "tag": "rotina"}, headers=AUTH).json()
    shell = client.post("/sessions", json={"kind": "shell"}, headers=AUTH).json()
    busy = client.post("/sessions", json={"kind": "codex"}, headers=AUTH).json()
    for sid in (agent["id"], routine["id"], shell["id"], busy["id"]):
        assert manager.get(sid).pty.alive
        manager.get(sid).status = "waiting"
    manager.get(busy["id"]).status = "working"
    later = time.time() + 3600
    assert manager.hibernate_idle(now=later) == []  # padrão: nunca
    client.put("/ajustes", json={"hibernar_min": 15}, headers=AUTH)
    assert manager.hibernate_idle(now=time.time()) == []  # ainda não deu o tempo
    assert manager.hibernate_idle(now=later) == [agent["id"]]  # rotina, shell e quem trabalha ficam
    session = manager.get(agent["id"])
    assert session.hibernando and session.pty.paused
    assert next(s for s in client.get("/sessions", headers=AUTH).json() if s["id"] == agent["id"])["hibernando"] is True
    assert {"type": "session.hibernate", "id": agent["id"], "hibernando": True} in published
    assert manager.hibernate_idle(now=later) == []  # já hiberna: não para de novo

    # Qualquer escrita no terminal acorda.
    session.pty.write(b"oi\n")
    assert not session.hibernando and not session.pty.paused
    assert {"type": "session.hibernate", "id": agent["id"], "hibernando": False} in published

    # O botão Acordar devolve a sessão.
    assert manager.hibernate_idle(now=later) == [agent["id"]]
    woke = client.post(f"/sessions/{agent['id']}/acordar", headers=AUTH)
    assert woke.status_code == 200 and woke.json()["hibernando"] is False and not session.pty.paused
    assert client.post("/sessions/naoexiste/acordar", headers=AUTH).status_code == 404

    # Fechar uma sessão hibernando não trava (o SIGHUP chega depois do SIGCONT).
    assert manager.hibernate_idle(now=later) == [agent["id"]]
    assert client.delete(f"/sessions/{agent['id']}", headers=AUTH).status_code == 204
    assert manager.get(agent["id"]) is None


# --- temas do Kitty e do Warp ------------------------------------------------------------------

KITTY = """\
# Dracula para o Kitty
foreground            #f8f8f2
background            #282a36
selection_background  #44475a
cursor                #f8f8f2
cursor_text_color     background
color0  #21222c
color9  #ff6e6e
"""

WARP = """\
accent: '#ff79c6'
background: "#282a36"
foreground: '#f8f8f2'  # texto
details: darker
terminal_colors:
  normal:
    black: '#21222c'
    red: '#ff5555'
  bright:
    black: '#6272a4'
    red: '#ff6e6e'
"""


def test_detect_and_parse_the_three_formats():
    assert themes.detect(KITTY) == "kitty" and themes.detect(WARP) == "warp"
    assert themes.detect("palette = 0=#000000\nbackground = 111111\n") == "ghostty"
    fmt, kitty = themes.parse(KITTY)
    assert fmt == "kitty"
    assert kitty == {"foreground": "#f8f8f2", "background": "#282a36", "selectionBackground": "#44475a", "cursor": "#f8f8f2",
                     "black": "#21222c", "brightRed": "#ff6e6e", "cursorAccent": "#282a36"}  # fmt: skip
    fmt, warp = themes.parse(WARP)
    assert fmt == "warp"
    assert warp == {"background": "#282a36", "foreground": "#f8f8f2", "cursor": "#ff79c6", "black": "#21222c", "red": "#ff5555",
                    "brightBlack": "#6272a4", "brightRed": "#ff6e6e", "cursorAccent": "#282a36"}  # fmt: skip
    with pytest.raises(ghostty.GhosttyError):
        themes.parse("nada aqui\n")


@pytest.fixture
def theme_folders(tmp_path, monkeypatch):
    gh = tmp_path / "gh-themes"
    gh.mkdir()
    (gh / "Dracula").write_text("background = 282a36\nforeground = f8f8f2\n", encoding="utf-8")
    kitty = tmp_path / "kitty" / "themes"
    kitty.mkdir(parents=True)
    (kitty / "Dracula.conf").write_text(KITTY, encoding="utf-8")
    (kitty / "Nord.conf").write_text("background #2e3440\nforeground #d8dee9\n", encoding="utf-8")
    current = tmp_path / "kitty" / "current-theme.conf"
    current.write_text("background #000000\n", encoding="utf-8")
    warp = tmp_path / "warp" / "themes" / "meus"
    warp.mkdir(parents=True)
    (warp / "Rosa.yaml").write_text(WARP, encoding="utf-8")
    monkeypatch.setattr(ghostty, "theme_dirs", lambda: [(gh, "usuario")])
    monkeypatch.setattr(ghostty, "config_files", lambda: [tmp_path / "sem-config"])
    monkeypatch.setattr(themes, "kitty_theme_dirs", lambda: [kitty])
    monkeypatch.setattr(themes, "kitty_current_files", lambda: [current])
    monkeypatch.setattr(themes, "warp_theme_dirs", lambda: [tmp_path / "warp" / "themes"])
    return tmp_path


def test_theme_routes(core, theme_folders):
    client, _ = core
    listed = client.get("/temas", headers=AUTH).json()["temas"]
    by_key = {(t["nome"], t["formato"]): t["origem"] for t in listed}
    assert by_key[("Dracula", "ghostty")] == "usuario"
    assert by_key[("Dracula (kitty)", "kitty")] == "usuario"  # nome repetido ganha o formato
    assert by_key[("Nord", "kitty")] == "usuario" and by_key[(themes.KITTY_CURRENT, "kitty")] == "usuario"
    assert by_key[("Rosa", "warp")] == "usuario"
    kitty = client.get("/temas/tema", params={"nome": "Dracula (kitty)", "formato": "kitty"}, headers=AUTH).json()
    assert kitty["formato"] == "kitty" and kitty["cores"]["brightRed"] == "#ff6e6e"
    warp = client.get("/temas/tema", params={"nome": "Rosa", "formato": "warp"}, headers=AUTH).json()
    assert warp["cores"]["cursor"] == "#ff79c6"
    gh = client.get("/temas/tema", params={"nome": "Dracula", "formato": "ghostty"}, headers=AUTH).json()
    assert gh["cores"]["background"] == "#282a36"
    assert client.get("/temas/tema", params={"nome": "Sumido", "formato": "warp"}, headers=AUTH).status_code == 404
    assert client.get("/temas/tema", params={"nome": "../x", "formato": "kitty"}, headers=AUTH).status_code == 400
    assert client.get("/temas/tema", params={"nome": "Nord", "formato": "iterm"}, headers=AUTH).status_code == 422
    read = client.post("/temas/ler", json={"texto": WARP, "nome": "Colado"}, headers=AUTH).json()
    assert read["nome"] == "Colado" and read["formato"] == "warp" and read["cores"]["red"] == "#ff5555"
    assert client.post("/temas/ler", json={"texto": KITTY}, headers=AUTH).json()["formato"] == "kitty"
    assert client.post("/temas/ler", json={"texto": "font-size = 14\n"}, headers=AUTH).status_code == 400
    assert client.get("/ghostty", headers=AUTH).status_code == 200  # a rota antiga continua


# --- a barra: comandos de "/" ------------------------------------------------------------------


def test_slash_commands_for_each_cli(core, tmp_path):
    client, app = core
    claude_home = tmp_path / "homes" / "claude"
    (claude_home / "commands" / "git").mkdir(parents=True)
    (claude_home / "commands" / "deploy.md").write_text("---\ndescription: sobe para produção\n---\nCorpo\n", encoding="utf-8")
    (claude_home / "commands" / "git" / "pr.md").write_text("# Abre o PR\n\nCorpo\n", encoding="utf-8")
    (claude_home / "skills" / "graphify").mkdir(parents=True)
    (claude_home / "skills" / "graphify" / "SKILL.md").write_text("---\nname: graphify\ndescription: grafo do código\n---\n", encoding="utf-8")
    project = tmp_path / "projeto"
    (project / ".claude" / "commands").mkdir(parents=True)
    (project / ".claude" / "commands" / "testar.md").write_text("Roda a suíte\n", encoding="utf-8")
    codex_home = tmp_path / "homes" / "codex"
    (codex_home / "prompts").mkdir(parents=True)
    (codex_home / "prompts" / "revisar.md").write_text("---\ndescription: revisão rápida\n---\n", encoding="utf-8")

    claude = client.post("/sessions", json={"kind": "claude", "cwd": str(project)}, headers=AUTH).json()
    items = client.get(f"/sessions/{claude['id']}/barra", headers=AUTH).json()["comandos"]
    names = [i["nome"] for i in items]
    assert names[:5] == ["/testar", "/deploy", "/git:pr", "/graphify", "/clear"]
    assert items[0] == {"nome": "/testar", "descricao": "Roda a suíte", "origem": "projeto"}
    assert items[1]["descricao"] == "sobe para produção" and items[1]["origem"] == "usuario"
    assert items[2]["descricao"] == "Abre o PR" and items[3] == {"nome": "/graphify", "descricao": "grafo do código", "origem": "skill"}
    assert {"/compact", "/context", "/model", "/mcp", "/help"} <= set(names)
    assert all(i["origem"] == "cli" and i["descricao"] for i in items[4:])

    codex = client.post("/sessions", json={"kind": "codex", "cwd": str(project)}, headers=AUTH).json()
    items = client.get(f"/sessions/{codex['id']}/barra", headers=AUTH).json()["comandos"]
    assert items[0] == {"nome": "/prompts:revisar", "descricao": "revisão rápida", "origem": "usuario"}
    assert {"/model", "/approvals", "/diff", "/quit"} <= {i["nome"] for i in items}

    shell = client.post("/sessions", json={"kind": "shell"}, headers=AUTH).json()
    assert client.get(f"/sessions/{shell['id']}/barra", headers=AUTH).json() == {"comandos": []}
    assert client.get("/sessions/naoexiste/barra", headers=AUTH).status_code == 404


def test_slash_commands_follow_the_account_folder(tmp_path):
    home = tmp_path / "conta"
    (home / "commands").mkdir(parents=True)
    (home / "commands" / "so-dela.md").write_text("Só da conta\n", encoding="utf-8")
    found = barra.slash_commands("claude", home, str(tmp_path / "nenhum"))
    assert found[0] == {"nome": "/so-dela", "descricao": "Só da conta", "origem": "usuario"}
    assert barra.slash_commands("shell", home, str(tmp_path)) == []


def test_skill_description_in_yaml_block(tmp_path):
    """description: | e > (várias linhas) viram uma frase só, nunca o "|" cru."""
    home = tmp_path / "conta"
    for name, head in {
        "literal": "description: |\n  Gera imagens\n  pelo Higgsfield.",
        "dobrada": "description: >\n  Especialista em\n  marketing.",
        "quebrada": "description: [sem fechar\nname: x",
    }.items():
        (home / "skills" / name).mkdir(parents=True)
        (home / "skills" / name / "SKILL.md").write_text(f"---\n{head}\n---\n\n# Título da {name}\n", encoding="utf-8")
    found = {item["nome"]: item["descricao"] for item in barra.slash_commands("claude", home, str(tmp_path))}
    assert found["/literal"] == "Gera imagens pelo Higgsfield."
    assert found["/dobrada"] == "Especialista em marketing."
    assert found["/quebrada"] == "[sem fechar"


# --- contexto da sessão ------------------------------------------------------------------------

CONVERSATION = ("cli", "id_conversa", "transcript", "cwd", "texto")


def test_session_context_for_claude_and_codex(core, tmp_path):
    client, app = core
    folder = tmp_path / "repo"
    folder.mkdir()
    transcript = tmp_path / "conversa.jsonl"
    transcript.write_text(
        "\n".join(json.dumps(x) for x in [
            {"type": "user", "message": {"content": "arruma o login"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Arrumei o login."}]}},
        ]) + "\n",
        encoding="utf-8",
    )  # fmt: skip
    claude = client.post("/sessions", json={"kind": "claude", "cwd": str(folder)}, headers=AUTH).json()
    app.state.manager.record_statusline(claude["id"], {"session_id": "conv-1234-5678", "transcript_path": str(transcript)})
    ctx = client.get(f"/sessions/{claude['id']}/contexto", headers=AUTH).json()
    assert ctx["available"] is True and "categories" in ctx  # a janela de contexto de antes continua na mesma rota
    assert {k: ctx[k] for k in CONVERSATION} == {"cli": "claude", "id_conversa": "conv-1234-5678", "transcript": str(transcript), "cwd": str(folder),
                   "texto": "você: arruma o login\n\nagente: Arrumei o login."}  # fmt: skip

    codex = client.post("/sessions", json={"kind": "codex", "cwd": str(folder)}, headers=AUTH).json()
    empty = client.get(f"/sessions/{codex['id']}/contexto", headers=AUTH).json()
    assert empty["id_conversa"] is None and empty["texto"] == ""
    rollouts = tmp_path / "homes" / "codex" / "sessions" / "2026" / "11" / "08"
    rollouts.mkdir(parents=True)
    rollout = rollouts / "rollout-2026-11-08-abc.jsonl"
    rollout.write_text(
        "\n".join(json.dumps(x) for x in [
            {"type": "session_meta", "payload": {"id": "019a-codex", "cwd": str(folder), "timestamp": "2026-11-08T10:00:00Z"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "roda os testes"}]}},
            {"type": "response_item", "payload": {"type": "reasoning", "summary": []}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Todos passaram."}]}},
        ]) + "\n",
        encoding="utf-8",
    )  # fmt: skip
    ctx = client.get(f"/sessions/{codex['id']}/contexto", headers=AUTH).json()
    assert ctx["cli"] == "codex" and ctx["id_conversa"] == "019a-codex" and ctx["transcript"] == str(rollout)
    assert ctx["texto"] == "você: roda os testes\n\nagente: Todos passaram."

    shell = client.post("/sessions", json={"kind": "shell", "cwd": str(folder)}, headers=AUTH).json()
    plain = client.get(f"/sessions/{shell['id']}/contexto", headers=AUTH).json()
    assert plain["available"] is False and {k: plain[k] for k in CONVERSATION} == {
        "cli": "shell", "id_conversa": None, "transcript": None, "cwd": str(folder), "texto": ""}  # fmt: skip
    assert client.get("/sessions/naoexiste/contexto", headers=AUTH).status_code == 404


# --- a skill da MÊTIS --------------------------------------------------------------------------


def test_metis_skill_text_and_install(core, tmp_path):
    client, _ = core
    state = client.get("/skills/metis", headers=AUTH).json()
    assert state["instalada"] == {"claude": False, "codex": False}
    text = state["texto"]
    assert text.startswith("---\nname: metis\ndescription: ")
    for needle in ("metis brain conflitos", "metis tarefa mover", "metis lembrete", "metis web", "metis sessao ler", "metis rodar",
                   "metis worktree nova", "metis agente", "metis versao", "brain_conflitos", "tarefa_nova", "saida", "aprovação"):  # fmt: skip
        assert needle in text, needle
    done = client.post("/skills/metis", json={"destino": "claude"}, headers=AUTH).json()
    assert done["instalada"] == {"claude": True, "codex": False}
    assert (tmp_path / "homes" / "claude" / "skills" / "metis" / "SKILL.md").read_text(encoding="utf-8") == text
    done = client.post("/skills/metis", json={"destino": "ambos"}, headers=AUTH).json()
    assert done["instalada"] == {"claude": True, "codex": True}
    assert (tmp_path / "homes" / "codex" / "skills" / "metis" / "SKILL.md").is_file()
    assert client.post("/skills/metis", json={"destino": "gemini"}, headers=AUTH).status_code == 422


def test_metis_skill_goes_to_extra_accounts_too(core, accounts):
    client, _ = core
    extra = accounts.add("claude", "Trabalho")
    client.post("/skills/metis", json={"destino": "claude"}, headers=AUTH)
    assert (Path(extra.dir) / "skills" / "metis" / "SKILL.md").is_file()


# --- comandos `metis worktree nova` e `metis agente` --------------------------------------------


class FakeCore:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, home, method, path, body=None):
        self.calls.append((method, path, body))
        answer = self.answers[(method, path.split("?")[0])]
        if isinstance(answer, Exception):
            raise answer
        return answer


def run_cli(monkeypatch, settings, fake, argv):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_core", fake)
    return cli.main(argv)


def test_cli_worktree_new(monkeypatch, settings, capsys):
    fake = FakeCore({
        ("GET", "/projects"): [{"id": "personal-harness", "name": "Personal Harness", "path": "/r"}],
        ("POST", "/projects/personal-harness/worktrees"): {"path": "/w/personal-harness/corrige-login", "branch": "corrige-login"},
    })  # fmt: skip
    assert run_cli(monkeypatch, settings, fake, ["worktree", "nova", "personal harness", "Corrige login", "--base", "main", "--sem-env"]) == 0
    assert fake.calls[-1] == ("POST", "/projects/personal-harness/worktrees", {"name": "Corrige login", "base": "main", "copy_env": False})
    out = capsys.readouterr().out
    assert "/w/personal-harness/corrige-login" in out and "branch: corrige-login" in out
    assert run_cli(monkeypatch, settings, fake, ["--json", "worktree", "nova", "personal-harness", "x"]) == 0
    assert json.loads(capsys.readouterr().out)["branch"] == "corrige-login"
    assert fake.calls[-1][2] == {"name": "x", "base": None, "copy_env": True}
    assert run_cli(monkeypatch, settings, fake, ["worktree", "nova", "outro", "x"]) == 1
    assert "projeto não encontrado" in capsys.readouterr().err


def test_cli_agent_opens_a_session(monkeypatch, settings, capsys, tmp_path):
    session = {"id": "ab12cd34", "title": "Revisor", "kind": "claude", "status": "starting", "cwd": str(tmp_path), "agent": "revisor"}
    fake = FakeCore({
        ("GET", "/agents"): [{"id": "revisor", "name": "Revisor", "cli": "claude"}, {"id": "aider", "name": "Aider", "cli": "outra"}],
        ("POST", "/sessions"): session,
    })  # fmt: skip
    monkeypatch.chdir(tmp_path)
    assert run_cli(monkeypatch, settings, fake, ["agente", "codex", "--modelo", "gpt-5.5", "--esforco", "high", "rode", "os", "testes"]) == 0
    assert fake.calls[-1] == ("POST", "/sessions", {"cwd": os.getcwd(), "kind": "codex", "model": "gpt-5.5", "effort": "high", "prompt": "rode os testes"})
    assert capsys.readouterr().out.strip() == "ab12cd34  Revisor"
    assert run_cli(monkeypatch, settings, fake, ["agente", "revisor", "--pasta", str(tmp_path / "sub"), "--titulo", "Revisão"]) == 0
    assert fake.calls[-1][2] == {"cwd": str(tmp_path / "sub"), "kind": "claude", "agent": "revisor", "title": "Revisão"}
    assert run_cli(monkeypatch, settings, fake, ["agente", "AIDER"]) == 0
    assert fake.calls[-1][2]["kind"] == "shell" and fake.calls[-1][2]["agent"] == "aider"
    capsys.readouterr()
    assert run_cli(monkeypatch, settings, fake, ["--json", "agente", "claude"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "ab12cd34"
    assert run_cli(monkeypatch, settings, fake, ["agente", "ninguem"]) == 1
    assert "agente não encontrado" in capsys.readouterr().err
    refused = FakeCore({("POST", "/sessions"): cli.CoreRefused("não achei aider no PATH")})
    assert run_cli(monkeypatch, settings, refused, ["agente", "claude"]) == 1
    assert "não achei aider no PATH" in capsys.readouterr().err
