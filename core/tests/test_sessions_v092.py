"""v0.9.2: sessões e agentes (permissão, confiar na pasta, retomar, reiniciar, passar o
trabalho, histórico) e sistema (Mac acordado, recursos, Skills, scripts da worktree)."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.history import list_sessions
from harness_core.prefs import Prefs, PrefsError, permission_args, trust_claude_folder
from harness_core.system import list_skills, tree_usage, wants_awake

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def fake_argv(kind, settings):
    # Um "agente" que só espera: o argv montado pela MÊTIS fica guardado no PtySession.
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


# --- ajustes ------------------------------------------------------------------------------------


def test_prefs_validate_and_map_to_cli_flags(tmp_path):
    prefs = Prefs(tmp_path)
    assert prefs.get()["permissao_claude"] == "padrao" and prefs.get()["avisos"]["som"] is True
    saved = prefs.update({"permissao_codex": "yolo", "avisos": {"volume": 3, "som": False}})
    assert saved["permissao_codex"] == "yolo" and saved["avisos"] == {**saved["avisos"], "volume": 1.0, "som": False, "espera": True}
    with pytest.raises(PrefsError):
        prefs.update({"permissao_claude": "deus"})
    with pytest.raises(PrefsError):
        prefs.update({"qualquer": 1})
    assert permission_args("claude", "padrao") == []
    assert permission_args("claude", "yolo") == ["--dangerously-skip-permissions"]
    assert permission_args("codex", "auto") == ["--approve-for-me"]
    assert permission_args("shell", "yolo") == []


def test_trust_claude_folder_only_touches_that_folder(tmp_path):
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({"numStartups": 9, "projects": {"/a": {"allowedTools": ["x"]}}}), encoding="utf-8")
    assert trust_claude_folder(config, "/a") and not trust_claude_folder(config, "/a")
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data == {"numStartups": 9, "projects": {"/a": {"allowedTools": ["x"], "hasTrustDialogAccepted": True}}}
    assert trust_claude_folder(tmp_path / "nova.json", "/b")


# --- sessões ------------------------------------------------------------------------------------


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


def argv_of(app, session_id: str) -> list[str]:
    return app.state.manager.get(session_id).pty.argv


def test_permission_trust_and_resume_go_into_the_cli(core, settings):
    client, app = core
    worktree = settings.worktrees / "repo" / "tarefa"
    worktree.mkdir(parents=True)
    client.put("/ajustes", json={"permissao_claude": "auto"}, headers=AUTH)
    claude = client.post("/sessions", json={"kind": "claude", "cwd": str(worktree), "resume": "abc12345-0000"}, headers=AUTH).json()
    argv = argv_of(app, claude["id"])
    assert argv[argv.index("--permission-mode") + 1] == "auto" and argv[argv.index("--resume") + 1] == "abc12345-0000"
    trusted = json.loads(settings.claude_json.read_text(encoding="utf-8"))["projects"]
    assert trusted[str(worktree.resolve())]["hasTrustDialogAccepted"] is True  # worktree da MÊTIS: confiável
    codex = client.post("/sessions", json={"kind": "codex", "cwd": str(worktree), "permissao": "yolo", "resume": "01a1-codex-id"}, headers=AUTH).json()
    argv = argv_of(app, codex["id"])
    assert argv[1:3] == ["resume", "01a1-codex-id"] and "--dangerously-bypass-approvals-and-sandbox" in argv
    assert any(a.startswith(f'projects."{worktree.resolve()}".trust_level') for a in argv)
    outside = client.post("/sessions", json={"kind": "codex", "cwd": str(settings.home)}, headers=AUTH).json()
    assert not any("trust_level" in a for a in argv_of(app, outside["id"]))  # pasta qualquer não vira confiável
    for sid in (claude["id"], codex["id"], outside["id"]):
        client.delete(f"/sessions/{sid}", headers=AUTH)


def test_restart_continue_and_hand_off(core, settings, tmp_path):
    client, app = core
    folder = settings.worktrees / "r" / "w"
    folder.mkdir(parents=True)
    transcript = tmp_path / "conversa.jsonl"
    transcript.write_text(
        "\n".join(json.dumps(x) for x in [
            {"type": "user", "message": {"content": "arruma o login"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Arrumei o login e falta o teste."}]}},
        ]) + "\n",
        encoding="utf-8",
    )  # fmt: skip
    old = client.post("/sessions", json={"kind": "claude", "cwd": str(folder), "title": "Login"}, headers=AUTH).json()
    assert client.post(f"/sessions/{old['id']}/reiniciar", json={"continuar": True}, headers=AUTH).status_code == 409  # sem conversa ainda
    app.state.manager.record_statusline(old["id"], {"session_id": "conv-1234-5678", "transcript_path": str(transcript)})
    again = client.post(f"/sessions/{old['id']}/reiniciar", json={"continuar": True}, headers=AUTH).json()
    argv = argv_of(app, again["id"])
    assert argv[argv.index("--resume") + 1] == "conv-1234-5678" and again["cwd"] == str(folder) and again["title"] == "Login"
    assert app.state.manager.get(old["id"]) is None  # a antiga saiu do lugar
    app.state.manager.record_statusline(again["id"], {"session_id": "conv-1234-5678", "transcript_path": str(transcript)})
    handed = client.post(f"/sessions/{again['id']}/passar", json={"nota": "foca no teste"}, headers=AUTH).json()
    argv = argv_of(app, handed["id"])
    assert handed["kind"] == "codex" and handed["cwd"] == str(folder)
    prompt = argv[1]
    assert str(transcript) in prompt and "Arrumei o login e falta o teste." in prompt and "foca no teste" in prompt
    for sid in (again["id"], handed["id"]):
        client.delete(f"/sessions/{sid}", headers=AUTH)


def test_history_lists_claude_and_codex_and_skips_guardian(tmp_path):
    claude = tmp_path / "claude" / "projects" / "-repo"
    claude.mkdir(parents=True)
    (claude / "aaaa1111.jsonl").write_text(
        "\n".join(json.dumps(x) for x in [
            {"type": "user", "cwd": "/repo", "isMeta": True, "message": {"content": "<command-name>/clear</command-name>"}},
            {"type": "user", "cwd": "/repo", "timestamp": "2026-11-08T10:00:00Z", "message": {"content": "arruma o webhook de pagamento"}},
            {"type": "ai-title", "aiTitle": "Webhook de pagamento"},
        ]) + "\n",
        encoding="utf-8",
    )  # fmt: skip
    (claude / "vazia.jsonl").write_text(json.dumps({"type": "user", "cwd": "/repo", "isMeta": True, "message": {"content": "x"}}) + "\n", encoding="utf-8")
    codex = tmp_path / "codex" / "sessions" / "2026" / "11" / "08"
    codex.mkdir(parents=True)
    (codex / "rollout-1.jsonl").write_text(
        "\n".join(json.dumps(x) for x in [
            {"type": "session_meta", "payload": {"id": "cdx-1", "cwd": "/repo", "timestamp": "t"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "revisa o PR"}]}},
        ]) + "\n",
        encoding="utf-8",
    )  # fmt: skip
    (codex / "rollout-2.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {"id": "guard", "cwd": "/repo", "source": {"subagent": {"other": "guardian"}}}}) + "\n", encoding="utf-8")
    homes = {"claude": tmp_path / "claude", "codex": tmp_path / "codex"}
    items = list_sessions({}, defaults=homes)
    assert {(i["cli"], i["id"], i["titulo"]) for i in items} == {("claude", "aaaa1111", "Webhook de pagamento"), ("codex", "cdx-1", "revisa o PR")}
    assert [i["id"] for i in list_sessions({}, query="pagamento", defaults=homes)] == ["aaaa1111"]
    assert list_sessions({}, cwd="/outra", defaults=homes) == []


# --- sistema ------------------------------------------------------------------------------------


def test_awake_rule_resources_tree_and_skills(tmp_path):
    assert wants_awake("sempre", 0, 0) and wants_awake("agente", 1, 0) and wants_awake("agente", 0, 1)
    assert not wants_awake("agente", 0, 0) and not wants_awake("nunca", 3, 3)
    table = {10: (1, 100.0, 5.0, "/bin/zsh"), 11: (10, 300.0, 20.0, "node"), 12: (11, 50.0, 0.5, "git"), 20: (1, 999.0, 1.0, "outro")}
    assert tree_usage(table, 10) == {"mb": 450, "cpu": 25.5, "processos": 3, "comandos": ["zsh", "node", "git"]}
    user = tmp_path / "skills"
    (user / "brain").mkdir(parents=True)
    (user / "brain" / "SKILL.md").write_text("---\nname: brain-registrar\ndescription: Registra no Brain\n---\n\n# x\n", encoding="utf-8")
    project = tmp_path / "repo" / ".claude" / "skills" / "deploy"
    project.mkdir(parents=True)
    (project / "SKILL.md").write_text("# Deploy sem frontmatter\n", encoding="utf-8")
    (user / "gerar").mkdir()
    (user / "gerar" / "SKILL.md").write_text("---\nname: gerar\ndescription: >\n  Gera imagens\n  e vídeos.\nversion: 2\n---\n", encoding="utf-8")
    found = list_skills([user, tmp_path / "nao-existe"], str(tmp_path / "repo"))
    assert [(s["nome"], s["origem"], s["descricao"]) for s in found] == [
        ("brain-registrar", "usuário", "Registra no Brain"),
        ("gerar", "usuário", "Gera imagens e vídeos."),
        ("deploy", "projeto", ""),
    ]


def test_routes_resources_skills_prefs_and_worktree_scripts(core, settings, repo):
    client, app = core
    resources = client.get("/recursos", headers=AUTH).json()
    assert resources["nucleo"]["mb"] > 0 and resources["acordado"]["modo"] == "agente" and resources["janelas"] == 0
    assert client.put("/ajustes", json={"manter_acordado": "talvez"}, headers=AUTH).status_code == 400
    assert isinstance(client.get("/skills", headers=AUTH).json(), list)
    project = client.post("/projects", json={"path": str(repo)}, headers=AUTH).json()
    assert client.get(f"/projects/{project['id']}/scripts", headers=AUTH).json() == {"setup": "", "arquivar": ""}
    marker = settings.home / "arquivou.txt"
    client.put(f"/projects/{project['id']}/scripts", json={"setup": "echo setup-ok", "arquivar": f"echo fim > '{marker}'"}, headers=AUTH)
    created = client.post(f"/projects/{project['id']}/worktrees", json={"name": "Tarefa X"}, headers=AUTH).json()
    setup = app.state.manager.get(created["setup"])
    assert setup is not None and setup.title.startswith("Setup · ")
    client.delete(f"/sessions/{created['setup']}", headers=AUTH)
    time.sleep(0.2)
    done = client.delete(f"/projects/{project['id']}/worktrees", params={"path": created["path"]}, headers=AUTH)
    assert done.status_code == 200, done.text
    assert marker.read_text(encoding="utf-8").strip() == "fim"  # o script de arquivamento rodou antes de apagar


# --- consertos depois da revisão da tela ----------------------------------------------------------


def test_notices_follow_the_hook_name_and_restart_keeps_the_name(core, monkeypatch, settings):
    client, app = core
    from harness_core import app as app_mod

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(app_mod, "mac_notify", lambda title, text, sound=True, target="", group="": sent.append((title, text)))
    folder = settings.worktrees / "r" / "avisos"
    folder.mkdir(parents=True)
    session = client.post("/sessions", json={"kind": "claude", "cwd": str(folder), "title": "Claude"}, headers=AUTH).json()
    hook = lambda name, body=None: client.post("/hooks/event", params={"session": session["id"], "name": name}, json=body or {}, headers=AUTH)  # noqa: E731
    hook("UserPromptSubmit")
    hook("Stop")
    hook("Notification", {"message": "Claude needs your permission to use Bash"})
    hook("Notification", {"message": "Claude is waiting for your input"})  # o Stop já avisou
    assert sent == [("Claude terminou", "avisos"), ("Claude espera você", "Claude needs your permission to use Bash")]
    # Sessão que já saiu: reiniciar tira a antiga da lista e a nova fica com o mesmo nome.
    manager = app.state.manager
    old = manager.get(session["id"])
    os.killpg(old.pty._proc.pid, signal.SIGKILL)
    deadline = time.time() + 3
    while old.pty.alive and time.time() < deadline:
        time.sleep(0.05)
    if old.pty.alive:
        pytest.skip("o processo de teste não saiu a tempo")
    again = client.post(f"/sessions/{session['id']}/reiniciar", json={}, headers=AUTH).json()
    assert again["title"] == "Claude" and manager.get(session["id"]) is None
    client.delete(f"/sessions/{again['id']}", headers=AUTH)


def test_history_items_carry_the_account_id(tmp_path):
    folder = tmp_path / "trabalho" / "projects" / "-repo"
    folder.mkdir(parents=True)
    (folder / "bbbb2222.jsonl").write_text(json.dumps({"type": "user", "cwd": "/repo", "message": {"content": "oi"}}) + "\n", encoding="utf-8")
    accounts = {"claude": {"accounts": [{"id": "trabalho", "name": "Trabalho", "dir": str(tmp_path / "trabalho")}]}}
    items = list_sessions(accounts, defaults={"claude": tmp_path / "claude", "codex": tmp_path / "codex"})
    assert [(i["conta"], i["conta_id"]) for i in items] == [("Trabalho", "trabalho")]


def test_history_route_answers(core, tmp_path):
    client, app = core
    folder = tmp_path / "homes" / "claude" / "projects" / "-repo"
    folder.mkdir(parents=True)
    (folder / "cccc3333.jsonl").write_text(json.dumps({"type": "user", "cwd": "/repo", "message": {"content": "revisa a rota"}}) + "\n", encoding="utf-8")
    app.state.cli_homes = {"claude": tmp_path / "homes" / "claude", "codex": tmp_path / "homes" / "codex"}
    found = client.get("/historico", params={"q": "rota"}, headers=AUTH)
    assert found.status_code == 200, found.text
    assert [(i["id"], i["conta_id"]) for i in found.json()] == [("cccc3333", "padrao")]


def test_port_counts_as_busy_only_while_someone_listens():
    import socket

    from harness_core.__main__ import port_free

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    assert not port_free("127.0.0.1", port)  # outro núcleo no ar
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = server.accept()
    server.close()
    conn.close()
    client.close()
    time.sleep(0.1)
    assert port_free("127.0.0.1", port)  # só sobrou a conexão do núcleo que fechou (TIME_WAIT)
