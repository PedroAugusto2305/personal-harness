"""v0.9.8, parte 5 (código): checks falhos de volta ao agente, revisão de PR só de leitura,
o grafo do código (graphify) pela central de MCP e instalar e compartilhar Skills."""

from __future__ import annotations

import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import github, graphify_tools, skills_manager
from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.mcp_hub import Context

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def fake_argv(kind, settings):
    return {"claude": ["/bin/cat", "--claude"], "codex": ["/bin/cat", "--codex"]}.get(kind, ["/bin/cat"])


@pytest.fixture
def core(settings, accounts, monkeypatch, tmp_path):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    app.state.cli_homes = {"claude": tmp_path / "homes" / "claude", "codex": tmp_path / "homes" / "codex"}
    app.state.skills_downloads = tmp_path / "Downloads"
    app.state.skills_trash = tmp_path / "Lixeira"
    with TestClient(app) as client:
        yield client, app
        for session_id in list(app.state.manager.sessions):
            client.delete(f"/sessions/{session_id}", headers=AUTH)


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=env).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    folder = tmp_path / "repo"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "main")
    (folder / "app.py").write_text("print('oi')\n", encoding="utf-8")
    git(folder, "add", ".")
    git(folder, "commit", "-q", "-m", "início")
    return folder


class FakeGh:
    """Responde ao `gh` pelo começo dos argumentos; o que não está no mapa sai com erro."""

    def __init__(self, answers: dict[tuple, tuple[int, str, str]]):
        self.answers = answers
        self.calls: list[tuple] = []

    def __call__(self, cwd, *args, timeout=30):
        self.calls.append(args)
        for prefix, answer in self.answers.items():
            if args[: len(prefix)] == prefix:
                return answer
        return 1, "", f"inesperado: {args}"


@pytest.fixture
def fake_gh(monkeypatch):
    def install(answers) -> FakeGh:
        fake = FakeGh(answers)
        monkeypatch.setattr(github, "gh", fake)
        github.clear()
        return fake

    yield install
    github.clear()


PR = (0, json.dumps({"number": 12, "title": "Arruma o login", "url": "u12", "state": "OPEN", "headRefName": "arruma", "baseRefName": "main"}), "")
NO_PR = (1, "", "no pull requests found for branch")


def long_log(n: int = 200) -> str:
    return "\n".join(f"test\tRun pytest\t2026-11-09T10:00:{i % 60:02d}.0000000Z \x1b[31mlinha {i}\x1b[0m" for i in range(n)) + "\n##[group]Run x\n"


# --- 1. checks falhos -------------------------------------------------------------------------


def test_failed_checks_of_the_pr_with_and_without_log(core, repo, fake_gh):
    client, _ = core
    checks = [
        {"name": "test", "bucket": "fail", "state": "FAILURE", "link": "https://github.com/o/r/actions/runs/111/job/222", "description": "pytest falhou", "workflow": "CI"},
        {"name": "lint", "bucket": "pass", "state": "SUCCESS", "link": "https://github.com/o/r/actions/runs/111/job/223", "description": "", "workflow": "CI"},
        {"name": "deploy", "bucket": "fail", "state": "FAILURE", "link": "https://vercel.com/o/r/abc", "description": "Deploy falhou", "workflow": ""},
    ]
    fake = fake_gh({
        ("pr", "view"): PR,
        ("pr", "checks", "12"): (1, json.dumps(checks), ""),  # o gh sai com 1 quando algum falhou
        ("run", "view", "--job", "222", "--log-failed"): (0, long_log(), ""),
    })  # fmt: skip
    data = client.get("/github/checks-falhos", params={"root": str(repo)}, headers=AUTH).json()
    assert data["pr"] == 12
    assert [c["nome"] for c in data["checks"]] == ["test", "deploy"]
    log = data["checks"][0]["log"].splitlines()
    assert len(log) == github.LOG_LINES and log[-1] == "linha 199" and "\x1b" not in data["checks"][0]["log"]
    assert data["checks"][1] == {"nome": "deploy", "url": "https://vercel.com/o/r/abc", "resumo": "Deploy falhou", "log": ""}
    assert not any(call[:2] == ("run", "view") and "223" in call for call in fake.calls)

    asked = client.post("/github/checks-falhos/pedido", json={"root": str(repo)}, headers=AUTH).json()["pedido"]
    assert asked.startswith("Os checks test e deploy do PR #12 falharam.")
    assert "linha 199" in asked and "(sem log: abra o link" in asked
    assert asked.rstrip().endswith("Ache a causa, corrija nesta worktree e rode o que der localmente antes de subir.")


def test_failed_checks_without_pr_use_the_last_commit(core, repo, fake_gh):
    client, _ = core
    sha = git(repo, "rev-parse", "HEAD")
    fake_gh({
        ("pr", "view"): NO_PR,
        ("run", "list", "--commit", sha): (0, json.dumps([{"databaseId": 5, "conclusion": "failure", "workflowName": "CI", "displayTitle": "início", "url": "u5"},
                                                          {"databaseId": 6, "conclusion": "success", "workflowName": "Docs", "displayTitle": "início", "url": "u6"}]), ""),
        ("run", "view", "5", "--log-failed"): (0, long_log(3), ""),
    })  # fmt: skip
    data = client.get("/github/checks-falhos", params={"root": str(repo)}, headers=AUTH).json()
    assert data == {"pr": None, "checks": [{"nome": "CI", "url": "u5", "resumo": "início", "log": "linha 0\nlinha 1\nlinha 2"}]}
    asked = client.post("/github/checks-falhos/pedido", json={"root": str(repo)}, headers=AUTH).json()["pedido"]
    assert asked.startswith(f"O check CI do último commit ({sha[:7]}) falhou.")


def test_no_failed_check_is_a_clear_400(core, repo, fake_gh):
    client, _ = core
    fake_gh({("pr", "view"): PR, ("pr", "checks", "12"): (0, json.dumps([{"name": "test", "bucket": "pass", "state": "SUCCESS"}]), "")})
    answer = client.post("/github/checks-falhos/pedido", json={"root": str(repo)}, headers=AUTH)
    assert answer.status_code == 400 and "nenhum check falhou no PR #12" in answer.json()["detail"]


def test_logs_share_one_budget(monkeypatch, repo, fake_gh):
    monkeypatch.setattr(github, "LOG_BUDGET", 50)
    checks = [{"name": f"job{i}", "bucket": "fail", "link": f"https://github.com/o/r/actions/runs/1/job/{i}"} for i in (1, 2)]
    fake_gh({("pr", "view"): PR, ("pr", "checks", "12"): (1, json.dumps(checks), ""), ("run", "view", "--job"): (0, long_log(40), "")})
    data = github.failed_checks(str(repo))
    assert sum(len(c["log"]) for c in data["checks"]) <= 50
    assert data["checks"][0]["log"].endswith("linha 39")


# --- 2. revisão de PR, só de leitura ---------------------------------------------------------


def review_gh(fake_gh):
    return fake_gh({
        ("pr", "view", "--json"): PR,
        ("pr", "diff", "12"): (0, "diff --git a/app.py b/app.py\n+print('tchau')\n", ""),
        ("pr", "view", "12", "--json"): (0, json.dumps({"title": "Arruma o login", "body": "Troca o fluxo.", "baseRefName": "main", "headRefName": "arruma"}), ""),
        ("repo", "view"): (0, json.dumps({"nameWithOwner": "pedro/metis"}), ""),
    })  # fmt: skip


def test_review_is_read_only_on_claude_and_codex(core, repo, fake_gh):
    client, app = core
    review_gh(fake_gh)
    saved = client.put("/ajustes", json={"permissao_claude": "yolo", "permissao_codex": "yolo"}, headers=AUTH)
    assert saved.status_code == 200 and saved.json()["permissao_claude"] == "yolo"
    plain = client.post("/sessions", json={"kind": "claude", "cwd": str(repo)}, headers=AUTH).json()
    assert "--dangerously-skip-permissions" in app.state.manager.get(plain["id"]).pty.argv  # o yolo vale fora da revisão
    session = client.post("/github/revisao", json={"root": str(repo)}, headers=AUTH).json()
    argv = app.state.manager.get(session["id"]).pty.argv
    assert session["title"] == "Revisão do PR #12"
    assert argv[argv.index("--permission-mode") + 1] == "plan"
    assert "--dangerously-skip-permissions" not in argv
    prompt = argv[1]
    assert "Revise o PR #12 (Arruma o login)" in prompt and "Não edite arquivo" in prompt and "Troca o fluxo." in prompt
    diff_file = Path(prompt.split("O diff completo está em ")[1].split(" (leia")[0])
    assert diff_file.read_text(encoding="utf-8").startswith("diff --git")

    codex = client.post("/github/revisao", json={"root": str(repo), "cli": "codex", "numero": 12}, headers=AUTH).json()
    argv = app.state.manager.get(codex["id"]).pty.argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv


def test_review_without_pr_is_400(core, repo, fake_gh):
    client, _ = core
    fake_gh({("pr", "view"): NO_PR})
    answer = client.post("/github/revisao", json={"root": str(repo)}, headers=AUTH)
    assert answer.status_code == 400 and "não tem PR aberto" in answer.json()["detail"]


# --- 3. graphify pela central ----------------------------------------------------------------


@pytest.fixture
def graph_repo(repo) -> Path:
    out = repo / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(json.dumps({"nodes": [{"id": "a"}, {"id": "b"}], "links": []}), encoding="utf-8")
    (out / "GRAPH_REPORT.md").write_text("# Relatório\n", encoding="utf-8")
    (repo / "src" / "mod").mkdir(parents=True)
    return repo


@pytest.fixture
def fake_graphify(monkeypatch):
    calls: list[list[str]] = []
    answer = {"value": (0, "resposta do grafo", "")}

    def run(args, cwd, timeout=60):
        calls.append(list(args))
        return answer["value"]

    monkeypatch.setattr(graphify_tools, "run", run)
    monkeypatch.setattr(graphify_tools, "executable", lambda: "/fake/graphify")
    return calls, answer


def test_graph_tools_only_inside_a_repo_with_graph(core, graph_repo, tmp_path, fake_graphify):
    _, app = core
    calls, answer = fake_graphify
    hub = app.state.hub
    ctx = Context(session="s1", who="Claude", cwd=str(graph_repo / "src" / "mod"), allowed=None)
    tools = {t.name: t for t in hub.tools_for(ctx) if t.name.startswith("codigo_grafo_")}
    assert set(tools) == {"codigo_grafo_consultar", "codigo_grafo_caminho", "codigo_grafo_explicar"}
    assert "repo" in tools["codigo_grafo_consultar"].description

    assert tools["codigo_grafo_consultar"].run({"pergunta": "como o login funciona"}, ctx) == "resposta do grafo"
    assert calls[-1] == ["query", "como o login funciona", "--budget", "1500", "--graph", str(graph_repo / "graphify-out" / "graph.json")]
    tools["codigo_grafo_caminho"].run({"de": "Auth", "para": "Banco"}, ctx)
    assert calls[-1][:3] == ["path", "Auth", "Banco"]
    tools["codigo_grafo_explicar"].run({"conceito": "Auth"}, ctx)
    assert calls[-1][:2] == ["explain", "Auth"]

    answer["value"] = (1, "", "graph.json corrompido")
    with pytest.raises(graphify_tools.GraphifyError, match="corrompido"):
        tools["codigo_grafo_explicar"].run({"conceito": "Auth"}, ctx)

    other = tmp_path / "outro"
    other.mkdir()
    git(other, "init", "-q")
    for cwd in (str(other), None):
        assert not [t for t in hub.tools_for(Context(session="s2", who="x", cwd=cwd, allowed=None)) if t.name.startswith("codigo_grafo_")]


def test_graph_state_and_update_publishes_the_event(core, graph_repo, fake_graphify, monkeypatch):
    client, app = core
    calls, _ = fake_graphify
    state = client.get("/codigo/grafo", params={"root": str(graph_repo)}, headers=AUTH).json()
    assert state["existe"] and state["nos"] == 2 and state["graphify"] is True
    assert state["relatorio"].endswith("GRAPH_REPORT.md") and state["atualizado"]
    empty = client.get("/codigo/grafo", params={"root": str(graph_repo / "src")}, headers=AUTH).json()
    assert empty == {"existe": False, "atualizado": None, "nos": None, "relatorio": None, "graphify": True}

    seen: list[dict] = []
    original = app.state.manager.events.publish
    monkeypatch.setattr(app.state.manager.events, "publish", lambda event: (seen.append(event), original(event)))
    assert client.post("/codigo/grafo/atualizar", json={"root": str(graph_repo)}, headers=AUTH).status_code == 202
    deadline = time.time() + 5
    while not any(e.get("type") == "codigo.grafo" for e in seen) and time.time() < deadline:
        time.sleep(0.05)
    event = next(e for e in seen if e.get("type") == "codigo.grafo")
    assert event["status"] == "ok" and event["root"] == str(graph_repo)
    assert calls[-1] == ["update", str(graph_repo)]
    assert client.post("/codigo/grafo/atualizar", json={"root": str(graph_repo / "nao-existe")}, headers=AUTH).status_code == 400


def test_metis_skill_mentions_the_graph_tools():
    from harness_core.barra import METIS_SKILL

    assert "codigo_grafo_consultar" in METIS_SKILL


# --- 4. Skills: instalar, atualizar, exportar, copiar, tirar ----------------------------------


def make_skill(folder: Path, name: str, description: str = "faz algo") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8")
    return folder


def test_install_from_folder_skips_symlinks_and_conflicts(core, tmp_path):
    client, _ = core
    source = make_skill(tmp_path / "fonte" / "minha-skill", "minha-skill")
    (source / "refs").mkdir()
    (source / "refs" / "guia.md").write_text("guia\n", encoding="utf-8")
    secret = tmp_path / "segredo.txt"
    secret.write_text("não copia\n", encoding="utf-8")
    (source / "atalho.txt").symlink_to(secret)

    done = client.post("/skills/instalar", json={"origem": str(tmp_path / "fonte"), "destino": "claude"}, headers=AUTH).json()
    assert done == {"instaladas": ["minha-skill"], "ignoradas": []}
    target = tmp_path / "homes" / "claude" / "skills" / "minha-skill"
    assert (target / "refs" / "guia.md").read_text(encoding="utf-8") == "guia\n"
    assert not (target / "atalho.txt").exists()
    origin = json.loads((target / ".metis-origem.json").read_text(encoding="utf-8"))
    assert origin["tipo"] == "pasta" and origin["origem"] == str(tmp_path / "fonte")

    again = client.post("/skills/instalar", json={"origem": str(tmp_path / "fonte"), "destino": "claude"}, headers=AUTH)
    assert again.status_code == 409 and "minha-skill" in again.json()["detail"]
    replaced = client.post("/skills/instalar", json={"origem": str(tmp_path / "fonte"), "destino": "claude", "substituir": True}, headers=AUTH)
    assert replaced.status_code == 200 and (target / "SKILL.md").exists()
    assert client.post("/skills/instalar", json={"origem": str(tmp_path / "nada"), "destino": "claude"}, headers=AUTH).status_code == 400


def test_install_from_zip_and_zip_slip_is_refused(core, tmp_path):
    client, _ = core
    good = tmp_path / "skills.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("pacote/outra/SKILL.md", "---\nname: outra\ndescription: x\n---\n")
        zf.writestr("pacote/outra/script.py", "print(1)\n")
    done = client.post("/skills/instalar", json={"origem": str(good), "destino": "codex"}, headers=AUTH).json()
    assert done["instaladas"] == ["outra"]
    assert (tmp_path / "homes" / "codex" / "skills" / "outra" / "script.py").exists()

    evil = tmp_path / "mal.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("boa/SKILL.md", "---\nname: boa\n---\n")
        zf.writestr("../../fora.txt", "escapou\n")
    answer = client.post("/skills/instalar", json={"origem": str(evil), "destino": "codex"}, headers=AUTH)
    assert answer.status_code == 400 and "fora da pasta" in answer.json()["detail"]
    assert not (tmp_path / "homes" / "codex" / "skills" / "boa").exists()
    assert not list(tmp_path.rglob("fora.txt"))


def test_install_from_git_and_update(core, tmp_path):
    client, _ = core
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-q", "-b", "main")
    make_skill(upstream, "git-skill", "versão 1")
    git(upstream, "add", ".")
    git(upstream, "commit", "-q", "-m", "v1")
    project = tmp_path / "projeto"
    project.mkdir()

    done = client.post("/skills/instalar", json={"origem": f"file://{upstream}", "destino": "projeto", "root": str(project)}, headers=AUTH).json()
    assert done["instaladas"] == ["git-skill"]
    target = project / ".claude" / "skills" / "git-skill"
    first = json.loads((target / ".metis-origem.json").read_text(encoding="utf-8"))
    assert first["tipo"] == "git" and first["commit"] == git(upstream, "rev-parse", "HEAD")
    assert not (target / ".git").exists()

    make_skill(upstream, "git-skill", "versão 2")
    git(upstream, "commit", "-q", "-am", "v2")
    updated = client.post("/skills/git-skill/atualizar", json={"destino": "projeto", "root": str(project)}, headers=AUTH).json()
    assert updated["commit"] == git(upstream, "rev-parse", "HEAD") and updated["antes"] == first["commit"]
    assert "versão 2" in (target / "SKILL.md").read_text(encoding="utf-8")

    listed = client.get("/skills", params={"cwd": str(project)}, headers=AUTH).json()
    mine = next(s for s in listed if s["nome"] == "git-skill")
    assert mine["destino"] == "projeto" and mine["fonte"]["tipo"] == "git" and mine["origem"] == "projeto"

    # Instalada de uma pasta: não tem de onde atualizar.
    make_skill(tmp_path / "solta" / "solta", "solta")
    client.post("/skills/instalar", json={"origem": str(tmp_path / "solta"), "destino": "claude"}, headers=AUTH)
    answer = client.post("/skills/solta/atualizar", json={"destino": "claude"}, headers=AUTH)
    assert answer.status_code == 400 and "não veio de um repositório git" in answer.json()["detail"]
    assert client.post("/skills/instalar", json={"origem": "file:///nao/existe", "destino": "claude"}, headers=AUTH).status_code == 400


def test_export_copy_and_trash(core, tmp_path):
    client, _ = core
    make_skill(tmp_path / "fonte" / "levar", "levar")
    client.post("/skills/instalar", json={"origem": str(tmp_path / "fonte"), "destino": "claude"}, headers=AUTH)

    first = client.post("/skills/levar/exportar", json={"destino": "claude"}, headers=AUTH).json()["arquivo"]
    second = client.post("/skills/levar/exportar", json={"destino": "claude"}, headers=AUTH).json()["arquivo"]
    assert Path(first).name == "levar-skill.zip" and Path(second).name == "levar-skill (2).zip"
    with zipfile.ZipFile(first) as zf:
        names = zf.namelist()
    assert "levar/SKILL.md" in names and not any(".metis-origem" in n for n in names)

    assert client.post("/skills/levar/copiar", json={"de": "claude", "para": "codex"}, headers=AUTH).status_code == 200
    assert (tmp_path / "homes" / "codex" / "skills" / "levar" / "SKILL.md").exists()
    assert client.post("/skills/levar/copiar", json={"de": "claude", "para": "codex"}, headers=AUTH).status_code == 409
    assert client.post("/skills/levar/copiar", json={"de": "claude", "para": "claude"}, headers=AUTH).status_code == 400
    assert client.post("/skills/levar/copiar", json={"de": "claude", "para": "projeto"}, headers=AUTH).status_code == 400  # sem root

    gone = client.delete("/skills/levar", params={"destino": "codex"}, headers=AUTH).json()["lixeira"]
    assert Path(gone).parent == tmp_path / "Lixeira" and (Path(gone) / "SKILL.md").exists()
    assert not (tmp_path / "homes" / "codex" / "skills" / "levar").exists()
    assert client.delete("/skills/levar", params={"destino": "codex"}, headers=AUTH).status_code == 404
    assert client.post("/skills/nada/exportar", json={"destino": "claude"}, headers=AUTH).status_code == 404


def test_skill_name_from_repository_root_uses_frontmatter_or_url(tmp_path):
    root = tmp_path / "fonte"
    (root).mkdir()
    (root / "SKILL.md").write_text("---\ndescription: sem nome\n---\n", encoding="utf-8")
    assert skills_manager.skill_name(root, "do-repo", use_folder=False) == "do-repo"
    assert skills_manager.skill_name(root, "do-repo") == "fonte"
