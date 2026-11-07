"""v0.3: projetos, worktrees, revisão (git), arquivos e portas."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import files as fs
from harness_core import gitops
from harness_core.app import create_app
from harness_core.ports import descendants, parse_lsof, ports_by_session
from harness_core.projects import ProjectError, ProjectStore

from .conftest import TOKEN, run

AUTH = {"X-Harness-Token": TOKEN}


@pytest.fixture
def client(settings, accounts):
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as test_client:
        yield test_client


# --- leitura das saídas do git ---------------------------------------------------


def test_parse_worktrees_marks_main_and_branches():
    porcelain = (
        "worktree /r/main\nHEAD aaa\nbranch refs/heads/main\n\n"
        "worktree /w/r/fix-x\nHEAD bbb\nbranch refs/heads/fix-x\nlocked\n\n"
        "worktree /w/r/solto\nHEAD ccc\ndetached\nprunable gitdir file points to non-existent location\n"
    )
    items = gitops.parse_worktrees(porcelain)
    assert [i["path"] for i in items] == ["/r/main", "/w/r/fix-x", "/w/r/solto"]
    assert items[0]["main"] and not items[1]["main"]
    assert items[1]["branch"] == "fix-x" and items[1]["locked"]
    assert items[2]["branch"] is None and items[2]["detached"] and items[2]["prunable"]


def test_parse_status_reads_branch_renames_untracked_and_conflicts():
    raw = "\0".join(
        [
            "# branch.oid abc",
            "# branch.head feat/x",
            "# branch.upstream origin/feat/x",
            "# branch.ab +2 -1",
            "1 M. N... 100644 100644 100644 h1 h2 src/app com espaço.py",
            "1 .M N... 100644 100644 100644 h1 h2 README.md",
            "2 R. N... 100644 100644 100644 h1 h2 R100 novo.py",
            "velho.py",
            "u UU N... 100644 100644 100644 100644 h1 h2 h3 briga.txt",
            "? notas/rascunho.md",
            "",
        ]
    )
    info = gitops.parse_status(raw)
    assert (info["branch"], info["upstream"], info["ahead"], info["behind"]) == ("feat/x", "origin/feat/x", 2, 1)
    by_path = {f["path"]: f for f in info["files"]}
    assert by_path["src/app com espaço.py"]["staged"] and not by_path["src/app com espaço.py"]["unstaged"]
    assert by_path["README.md"]["unstaged"] and not by_path["README.md"]["staged"]
    assert by_path["novo.py"]["orig"] == "velho.py"
    assert by_path["briga.txt"]["conflict"]
    assert by_path["notas/rascunho.md"]["untracked"] and not by_path["notas/rascunho.md"]["staged"]


# --- projetos ------------------------------------------------------------------


def test_projects_start_empty_and_resolve_to_the_main_repo(settings, repo):
    store = ProjectStore(settings.home)
    assert store.list() == []
    (repo / "src").mkdir()
    project = store.add(str(repo / "src"))  # subpasta vale pelo repositório inteiro
    assert project.path == str(repo) and project.name == "meu-repo"
    assert store.add(str(repo)).id == project.id  # sem duplicar
    with pytest.raises(ProjectError):
        store.add(str(repo.parent))  # não é repositório
    store.remove(project.id)
    assert store.list() == []


# --- worktrees, revisão e commit pela API -----------------------------------------


def test_worktree_review_and_commit_flow(client, settings, repo):
    project = client.post("/projects", json={"path": str(repo)}, headers=AUTH).json()
    assert client.get("/projects", headers=AUTH).json()[0]["id"] == project["id"]

    created = client.post(f"/projects/{project['id']}/worktrees", json={"name": "Corrige Login"}, headers=AUTH)
    assert created.status_code == 201, created.text
    wt = created.json()
    assert wt["branch"] == "corrige-login"
    assert wt["path"] == str(settings.worktrees / "meu-repo" / "corrige-login")
    assert wt["copied"] == [".env"]  # o .env fora do git vai junto
    wt_path = Path(wt["path"])

    listed = client.get(f"/projects/{project['id']}/worktrees", headers=AUTH).json()
    assert [w["main"] for w in listed] == [True, False]
    assert listed[1]["branch"] == "corrige-login" and listed[1]["changes"] == 0

    (wt_path / "app.py").write_text("print('oi, mundo')\n", encoding="utf-8")
    (wt_path / "novo.md").write_text("# novo\n", encoding="utf-8")
    status = client.get("/git/status", params={"path": str(wt_path)}, headers=AUTH).json()
    assert status["branch"] == "corrige-login"
    assert {f["path"] for f in status["files"]} == {"app.py", "novo.md"}

    diff = client.get("/git/diff", params={"path": str(wt_path), "file": "app.py"}, headers=AUTH).text
    assert "-print('oi')" in diff and "+print('oi, mundo')" in diff
    new_diff = client.get("/git/diff", params={"path": str(wt_path), "file": "novo.md", "untracked": True}, headers=AUTH).text
    assert "+# novo" in new_diff
    assert client.get("/git/diff", params={"path": str(wt_path), "file": "../fora.txt"}, headers=AUTH).status_code == 400

    assert client.post("/git/stage", json={"path": str(wt_path), "files": ["app.py"]}, headers=AUTH).json()["ok"]
    staged = {f["path"]: f for f in client.get("/git/status", params={"path": str(wt_path)}, headers=AUTH).json()["files"]}
    assert staged["app.py"]["staged"] and not staged["novo.md"]["staged"]
    client.post("/git/unstage", json={"path": str(wt_path), "files": ["app.py"]}, headers=AUTH)
    client.post("/git/stage", json={"path": str(wt_path), "files": ["app.py", "novo.md"]}, headers=AUTH)
    committed = client.post("/git/commit", json={"path": str(wt_path), "message": "fix: saudação"}, headers=AUTH)
    assert committed.status_code == 200, committed.text
    assert "fix: saudação" in run("git", "log", "-1", "--format=%s", cwd=wt_path)

    # Mudança sem commit trava a remoção; à força, a pasta sai e o branch não juntado fica.
    (wt_path / "app.py").write_text("sujo\n", encoding="utf-8")
    refused = client.delete(f"/projects/{project['id']}/worktrees", params={"path": str(wt_path)}, headers=AUTH)
    assert refused.status_code == 409 and "mudança" in refused.json()["detail"]
    gone = client.delete(f"/projects/{project['id']}/worktrees", params={"path": str(wt_path), "force": True}, headers=AUTH).json()
    assert not wt_path.exists()
    assert gone["branch_deleted"] is False and gone["branch_kept"]  # o commit "fix: saudação" não se perde
    assert "corrige-login" in run("git", "branch", "--list", "corrige-login", cwd=repo)
    assert client.delete(f"/projects/{project['id']}/worktrees", params={"path": str(repo)}, headers=AUTH).status_code == 400


def test_clean_worktree_keeps_unmerged_branch(client, repo):
    project = client.post("/projects", json={"path": str(repo)}, headers=AUTH).json()
    wt = Path(client.post(f"/projects/{project['id']}/worktrees", json={"name": "ideia"}, headers=AUTH).json()["path"])
    (wt / "ideia.txt").write_text("x\n", encoding="utf-8")
    run("git", "add", ".", cwd=wt)
    run("git", "commit", "-q", "-m", "ideia", cwd=wt)
    result = client.delete(f"/projects/{project['id']}/worktrees", params={"path": str(wt)}, headers=AUTH).json()
    assert not wt.exists()
    assert result["branch_deleted"] is False and result["branch_kept"]  # o commit não se perde
    assert "ideia" in run("git", "branch", "--list", "ideia", cwd=repo)


def test_worktree_with_open_terminal_needs_closing_first(client, repo, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/sh")
    project = client.post("/projects", json={"path": str(repo)}, headers=AUTH).json()
    wt = client.post(f"/projects/{project['id']}/worktrees", json={"name": "ocupada"}, headers=AUTH).json()["path"]
    client.post("/sessions", json={"kind": "shell", "cwd": wt}, headers=AUTH)
    refused = client.delete(f"/projects/{project['id']}/worktrees", params={"path": wt}, headers=AUTH)
    assert refused.status_code == 409 and "terminais" in refused.json()["detail"]


# --- arquivos ------------------------------------------------------------------


def test_files_listing_text_raw_and_traversal(client, repo):
    (repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 20)
    listed = client.get("/fs/files", params={"root": str(repo)}, headers=AUTH).json()["files"]
    assert "app.py" in listed and "logo.png" in listed and ".env" not in listed  # ignorados ficam fora

    text = client.get("/fs/text", params={"root": str(repo), "path": "app.py"}, headers=AUTH).json()
    assert text["text"] == "print('oi')\n" and not text["binary"]
    assert client.get("/fs/text", params={"root": str(repo), "path": "logo.png"}, headers=AUTH).json()["binary"]

    raw = client.get("/fs/raw", params={"root": str(repo), "path": "logo.png", "token": TOKEN})
    assert raw.status_code == 200 and raw.headers["content-type"] == "image/png"
    assert client.get("/fs/raw", params={"root": str(repo), "path": "logo.png"}).status_code == 401
    assert client.get("/fs/text", params={"root": str(repo), "path": "../../etc/passwd"}, headers=AUTH).status_code == 404
    with pytest.raises(fs.FileError):
        fs.inside(str(repo), "/etc/passwd")


def test_open_only_accepts_local_urls(client):
    assert client.post("/open", json={"url": "https://exemplo.com"}, headers=AUTH).status_code == 400
    assert client.post("/open", json={"url": "http://localhost.exemplo.com"}, headers=AUTH).status_code == 400


# --- portas ----------------------------------------------------------------------


def test_parse_lsof_and_descendants():
    assert parse_lsof("p10\nn*:3000\nn127.0.0.1:5173\np11\nn[::1]:1420\n") == {10: {3000, 5173}, 11: {1420}}
    assert descendants(1, {1: [2, 3], 3: [4], 9: [10]}) == {1, 2, 3, 4}


def test_ports_of_a_server_started_inside_a_terminal(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Um "terminal" (sh) que sobe um servidor filho, como o npm run dev faria.
    shell = subprocess.Popen(["/bin/sh", "-c", f"{sys.executable} -m http.server {port} --bind 127.0.0.1 >/dev/null 2>&1"])
    try:
        found = {}
        for _ in range(50):
            found = ports_by_session({"s1": shell.pid})
            if found["s1"]:
                break
            time.sleep(0.1)
        assert found == {"s1": [port]}
    finally:
        subprocess.run(["pkill", "-P", str(shell.pid)])
        shell.terminate()
        shell.wait()
