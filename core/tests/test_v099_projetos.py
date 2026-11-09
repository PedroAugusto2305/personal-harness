"""v0.9.9: adicionar projeto no jeito do Orca: repositórios do Mac, clonar de uma URL, criar."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core.app import create_app
from harness_core.projects import ProjectError, clone_repo, create_repo, default_parent, find_repos, repo_name_from_url

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


@pytest.fixture(autouse=True)
def git_identity(monkeypatch):
    for key, value in {"GIT_AUTHOR_NAME": "Teste", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "Teste", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(key, value)


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / "a.txt").write_text("a")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "a"], check=True)
    return path


def test_find_repos_skips_added_worktrees_and_deep_folders(tmp_path):
    home = tmp_path / "home"
    a = make_repo(home / "Documents" / "projetos" / "loja")
    b = make_repo(home / "orca" / "projects" / "site")
    make_repo(home / "Documents" / "projetos" / "x" / "y" / "fundo")  # 3 níveis: fora
    wt = home / "orca" / "workspaces"
    worktree = wt / "site" / "tarefa"
    worktree.parent.mkdir(parents=True)
    subprocess.run(["git", "-C", str(b), "worktree", "add", "-q", "-b", "tarefa", str(worktree)], check=True)
    (home / "Documents" / "node_modules" / "pkg" / ".git").mkdir(parents=True)
    found = find_repos([{"path": str(b)}], wt, home=home)
    paths = [f["path"] for f in found]
    assert str(a.resolve()) in paths
    assert str(b.resolve()) not in paths  # já é projeto
    assert all("workspaces" not in p and "node_modules" not in p and "fundo" not in p for p in paths)


def test_default_parent_follows_existing_projects(tmp_path):
    assert default_parent([], home=tmp_path) == tmp_path / "Documents" / "projetos"
    items = [{"path": "/x/projetos/a"}, {"path": "/x/projetos/b"}, {"path": "/y/c"}]
    assert default_parent(items, home=tmp_path) == Path("/x/projetos")


def test_repo_name_from_url():
    assert repo_name_from_url("https://github.com/dono/loja.git") == "loja"
    assert repo_name_from_url("git@github.com:dono/site.git") == "site"
    assert repo_name_from_url("https://gitlab.com/g/sub/app/") == "app"


def test_clone_and_create(tmp_path):
    origin = make_repo(tmp_path / "origem" / "loja")
    cloned = clone_repo(str(origin), tmp_path / "dest")
    assert cloned == tmp_path / "dest" / "loja" and (cloned / "a.txt").read_text() == "a"
    with pytest.raises(ProjectError, match="já existe"):
        clone_repo(str(origin), tmp_path / "dest")
    with pytest.raises(ProjectError, match="inválido"):
        clone_repo("--upload-pack=x", tmp_path / "dest")
    with pytest.raises(ProjectError, match="não clonou"):
        clone_repo(str(tmp_path / "nao-existe.git"), tmp_path / "dest2")

    made = create_repo("Meu Projeto Novo", tmp_path / "novos")
    assert made == tmp_path / "novos" / "meu-projeto-novo"
    assert (made / "README.md").read_text() == "# Meu Projeto Novo\n"
    log = subprocess.run(["git", "-C", str(made), "log", "--oneline"], capture_output=True, text=True).stdout
    assert "Início do projeto" in log
    with pytest.raises(ProjectError, match="já existe"):
        create_repo("Meu Projeto Novo", tmp_path / "novos")


def test_create_repo_cleans_up_when_git_fails(tmp_path, monkeypatch):
    from harness_core import projects as projects_mod

    real = projects_mod._git

    def slow_commit(args, cwd=None, timeout=30):
        if "commit" in args:
            raise subprocess.TimeoutExpired(["git", *args], timeout)
        return real(args, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(projects_mod, "_git", slow_commit)
    with pytest.raises(ProjectError, match="demorou demais"):
        create_repo("Travado", tmp_path / "novos")
    assert not (tmp_path / "novos" / "travado").exists()  # sem pasta pela metade


def test_routes(settings, accounts, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    origin = make_repo(tmp_path / "origem" / "blog")
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        made = client.post("/projects/criar", json={"nome": "Caderno", "pasta": str(tmp_path / "p")}, headers=AUTH)
        assert made.status_code == 201 and made.json()["name"] == "Caderno"
        cloned = client.post("/projects/clone", json={"url": str(origin), "pasta": str(tmp_path / "p")}, headers=AUTH)
        assert cloned.status_code == 201 and cloned.json()["name"] == "blog"
        names = {p["name"] for p in client.get("/projects", headers=AUTH).json()}
        assert {"Caderno", "blog"} <= names
        # Sem pasta: vai para onde os projetos já moram.
        again = client.post("/projects/criar", json={"nome": "Outro"}, headers=AUTH)
        assert again.status_code == 201 and Path(again.json()["path"]).parent == (tmp_path / "p").resolve()
        bad = client.post("/projects/clone", json={"url": str(origin), "pasta": str(tmp_path / "p")}, headers=AUTH)
        assert bad.status_code == 400 and "já existe" in bad.json()["detail"]
        sug = client.get("/projects/sugestoes", headers=AUTH).json()
        assert "pasta_padrao" in sug and isinstance(sug["repositorios"], list)
        assert client.get("/projects/sugestoes").status_code == 401
