"""v0.9.6: git (trechos, comparar com ref, conflitos, push, sync, amend) e GitHub pelo gh."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import github, gitops, system
from harness_core.app import create_app

from .conftest import TOKEN, run

AUTH = {"X-Harness-Token": TOKEN}


@pytest.fixture
def core(settings, accounts):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


def commit_all(path: Path, message: str) -> None:
    run("git", "add", "-A", cwd=path)
    run("git", "commit", "-q", "-m", message, cwd=path)


@pytest.fixture
def remote(repo: Path, tmp_path: Path) -> Path:
    """Um remoto de verdade (bare) para o repositório de teste, ainda sem upstream."""
    bare = tmp_path / "remoto.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    run("git", "remote", "add", "origin", str(bare), cwd=repo)
    return bare


def clone(bare: Path, where: Path) -> Path:
    run("git", "clone", "-q", str(bare), str(where), cwd=bare.parent)
    run("git", "config", "user.email", "outro@example.com", cwd=where)
    run("git", "config", "user.name", "Outro", cwd=where)
    return where


# --- status, refs e comparar com uma ref --------------------------------------------------------


def test_status_tells_the_last_commit_and_whether_it_went_up(core, repo, remote):
    client, _ = core
    info = client.get("/git/status", params={"path": str(repo)}, headers=AUTH).json()
    assert info["operacao"] is None
    assert info["ultimo_commit"]["assunto"] == "primeiro" and info["ultimo_commit"]["subiu"] is False
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).json()["feito"] == "push"
    assert client.get("/git/status", params={"path": str(repo)}, headers=AUTH).json()["ultimo_commit"]["subiu"] is True
    (repo / "app.py").write_text("print('dois')\n", encoding="utf-8")
    commit_all(repo, "segundo")
    info = client.get("/git/status", params={"path": str(repo)}, headers=AUTH).json()
    assert info["ultimo_commit"]["assunto"] == "segundo" and info["ultimo_commit"]["subiu"] is False and info["ahead"] == 1


def test_compare_with_a_ref_shows_only_what_this_branch_changed(core, repo):
    client, _ = core
    run("git", "checkout", "-q", "-b", "feature", cwd=repo)
    (repo / "novo.txt").write_text("um\n", encoding="utf-8")
    (repo / "app.py").write_text("print('mudou')\n", encoding="utf-8")
    commit_all(repo, "feature")
    (repo / "solto.txt").write_text("não rastreado\n", encoding="utf-8")
    refs = client.get("/git/refs", params={"path": str(repo)}, headers=AUTH).json()
    assert refs["atual"] == "feature" and set(refs["branches"]) == {"main", "feature"} and refs["padrao"] == "main"
    changed = client.get("/git/changed", params={"path": str(repo), "ref": "main"}, headers=AUTH).json()
    assert {(f["path"], f["status"]) for f in changed["files"]} == {("app.py", "M"), ("novo.txt", "A"), ("solto.txt", "A")}
    assert changed["ref"] == "main" and changed["base"]
    diff = client.get("/git/diff", params={"path": str(repo), "file": "app.py", "mode": "ref", "ref": "main"}, headers=AUTH)
    assert diff.status_code == 200 and "+print('mudou')" in diff.text and "-print('oi')" in diff.text
    for bad in ("nao-existe", "--output=/tmp/x", "main dois"):
        answer = client.get("/git/changed", params={"path": str(repo), "ref": bad}, headers=AUTH)
        assert answer.status_code == 400, bad


# --- marcar, desmarcar e descartar por trecho -----------------------------------------------------


def two_hunks(repo: Path) -> Path:
    target = repo / "longo.txt"
    target.write_text("".join(f"linha {n}\n" for n in range(1, 41)), encoding="utf-8")
    commit_all(repo, "longo")
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[1] = "linha 2 mudada\n"
    lines[35] = "linha 36 mudada\n"
    target.write_text("".join(lines), encoding="utf-8")
    return target


def first_hunk(patch: str) -> str:
    """Cabeçalho do diff e só o primeiro @@ (como a tela monta para "marcar trecho")."""
    head, _, rest = patch.partition("\n@@")
    hunks = ("@@" + rest).split("\n@@")
    return (head + "\n" + hunks[0]).rstrip("\n") + "\n"


def test_stage_unstage_and_discard_one_hunk(core, repo):
    client, _ = core
    target = two_hunks(repo)
    patch = run("git", "diff", "--", "longo.txt", cwd=repo)
    piece = first_hunk(patch)
    assert client.post("/git/apply", json={"path": str(repo), "patch": piece}, headers=AUTH).json() == {"ok": True}
    staged = run("git", "diff", "--cached", cwd=repo)
    assert "linha 2 mudada" in staged and "linha 36 mudada" not in staged
    # Desmarcar o mesmo trecho: o diff marcado ao contrário.
    staged_piece = first_hunk(run("git", "diff", "--cached", "--", "longo.txt", cwd=repo))
    assert client.post("/git/apply", json={"path": str(repo), "patch": staged_piece, "reverse": True}, headers=AUTH).status_code == 200
    assert run("git", "diff", "--cached", cwd=repo) == ""
    # Descartar o primeiro trecho da árvore de trabalho; o segundo fica.
    answer = client.post("/git/apply", json={"path": str(repo), "patch": piece, "cached": False, "reverse": True}, headers=AUTH)
    assert answer.status_code == 200
    text = target.read_text(encoding="utf-8")
    assert "linha 2\n" in text and "linha 36 mudada" in text
    bad = client.post("/git/apply", json={"path": str(repo), "patch": "isto não é um patch\n"}, headers=AUTH)
    assert bad.status_code == 400


def test_discard_restores_tracked_and_moves_new_files_to_the_trash(core, repo, tmp_path, monkeypatch):
    client, _ = core
    trash = tmp_path / "Lixeira"
    monkeypatch.setattr(gitops, "TRASH", trash)
    (repo / "app.py").write_text("print('estragado')\n", encoding="utf-8")
    (repo / "rascunho.md").write_text("um\n", encoding="utf-8")
    trash.mkdir()
    (trash / "rascunho.md").write_text("já estava na lixeira\n", encoding="utf-8")
    answer = client.post("/git/discard", json={"path": str(repo), "files": ["app.py", "rascunho.md"]}, headers=AUTH).json()
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('oi')\n"
    assert not (repo / "rascunho.md").exists()
    assert answer["lixeira"] == [str(trash / "rascunho 2.md")] and (trash / "rascunho 2.md").read_text(encoding="utf-8") == "um\n"
    outside = client.post("/git/discard", json={"path": str(repo), "files": ["../fora.txt"]}, headers=AUTH)
    assert outside.status_code == 400


# --- commit, amend e o hook de pre-commit ---------------------------------------------------------


def test_commit_amend_and_the_hook_output(core, repo):
    client, _ = core
    assert client.post("/git/commit", json={"path": str(repo), "message": "  "}, headers=AUTH).status_code == 400
    (repo / "app.py").write_text("print('três')\n", encoding="utf-8")
    run("git", "add", "app.py", cwd=repo)
    assert client.post("/git/commit", json={"path": str(repo), "message": "terceiro"}, headers=AUTH).status_code == 200
    (repo / "extra.txt").write_text("esqueci\n", encoding="utf-8")
    run("git", "add", "extra.txt", cwd=repo)
    assert client.post("/git/commit", json={"path": str(repo), "amend": True}, headers=AUTH).status_code == 200
    assert run("git", "log", "-1", "--format=%s", cwd=repo).strip() == "terceiro"
    assert "extra.txt" in run("git", "show", "--name-only", "--format=", "HEAD", cwd=repo)
    client.post("/git/commit", json={"path": str(repo), "message": "", "amend": True}, headers=AUTH)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'lint: faltou ponto e vírgula em app.py'\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    (repo / "app.py").write_text("print('quatro')\n", encoding="utf-8")
    run("git", "add", "app.py", cwd=repo)
    failed = client.post("/git/commit", json={"path": str(repo), "message": "quarto"}, headers=AUTH)
    assert failed.status_code == 400 and "faltou ponto e vírgula" in failed.json()["detail"]


# --- push, fetch e sincronizar --------------------------------------------------------------------


def test_sync_pulls_with_rebase_and_pushes(core, repo, remote, tmp_path):
    client, _ = core
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).json()["feito"] == "push"
    other = clone(remote, tmp_path / "outro")
    (other / "deles.txt").write_text("de lá\n", encoding="utf-8")
    commit_all(other, "de lá")
    run("git", "push", "-q", cwd=other)
    (repo / "nosso.txt").write_text("daqui\n", encoding="utf-8")
    commit_all(repo, "daqui")
    (repo / "app.py").write_text("print('sujo')\n", encoding="utf-8")  # o autostash guarda e devolve
    assert client.post("/git/fetch", json={"path": str(repo)}, headers=AUTH).status_code == 200
    behind = client.get("/git/status", params={"path": str(repo)}, headers=AUTH).json()
    assert behind["ahead"] == 1 and behind["behind"] == 1
    done = client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).json()
    assert done["feito"] == "sync"
    after = client.get("/git/status", params={"path": str(repo)}, headers=AUTH).json()
    assert after["ahead"] == 0 and after["behind"] == 0 and (repo / "deles.txt").exists()
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('sujo')\n"
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).json()["feito"] == "nada"
    # Histórico reescrito: o push normal é recusado e o com garantia passa.
    run("git", "commit", "-q", "--amend", "-m", "daqui de novo", cwd=repo)
    refused = client.post("/git/push", json={"path": str(repo)}, headers=AUTH)
    assert refused.status_code == 400 and "rejected" in refused.json()["detail"]
    assert client.post("/git/push", json={"path": str(repo), "force": True}, headers=AUTH).status_code == 200


# --- conflitos e operações em andamento -----------------------------------------------------------


def conflict_setup(repo: Path) -> None:
    run("git", "checkout", "-q", "-b", "outro", cwd=repo)
    (repo / "app.py").write_text("print('deles')\ncomum\n", encoding="utf-8")
    commit_all(repo, "deles")
    run("git", "checkout", "-q", "main", cwd=repo)
    (repo / "app.py").write_text("print('nosso')\ncomum\n", encoding="utf-8")
    commit_all(repo, "nosso")
    subprocess.run(["git", "merge", "outro"], cwd=repo, capture_output=True)  # sai com 1: o conflito é o esperado


def test_conflict_blocks_choices_and_continue(core, repo):
    client, _ = core
    conflict_setup(repo)
    info = client.get("/git/status", params={"path": str(repo)}, headers=AUTH).json()
    assert info["operacao"] == "merge" and any(f["conflict"] for f in info["files"])
    data = client.get("/git/conflito", params={"path": str(repo), "file": "app.py"}, headers=AUTH).json()
    assert len(data["blocos"]) == 1
    block = data["blocos"][0]
    assert block["nosso"] == "print('nosso')\n" and block["deles"] == "print('deles')\n" and block["base"] is None
    assert block["rotulo_nosso"] == "HEAD" and block["rotulo_deles"] == "outro"
    wrong = client.post("/git/conflito", json={"path": str(repo), "file": "app.py", "escolhas": ["nosso", "deles"]}, headers=AUTH)
    assert wrong.status_code == 400
    done = client.post("/git/conflito", json={"path": str(repo), "file": "app.py", "escolhas": ["ambos"]}, headers=AUTH).json()
    assert done == {"resolvido": True}
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('nosso')\nprint('deles')\ncomum\n"
    assert client.post("/git/operacao", json={"path": str(repo), "acao": "continuar"}, headers=AUTH).status_code == 200
    assert client.get("/git/status", params={"path": str(repo)}, headers=AUTH).json()["operacao"] is None
    assert client.post("/git/operacao", json={"path": str(repo), "acao": "abortar"}, headers=AUTH).status_code == 409


def test_conflict_whole_side_and_abort(core, repo):
    client, _ = core
    conflict_setup(repo)
    assert client.post("/git/conflito", json={"path": str(repo), "file": "app.py", "lado": "deles"}, headers=AUTH).json() == {"resolvido": True}
    assert (repo / "app.py").read_text(encoding="utf-8").startswith("print('deles')")
    assert client.post("/git/operacao", json={"path": str(repo), "acao": "abortar"}, headers=AUTH).status_code == 200
    assert (repo / "app.py").read_text(encoding="utf-8").startswith("print('nosso')")


def test_parse_conflicts_with_base_section():
    text = "a\n<<<<<<< HEAD\nnosso\n||||||| base\nantes\n=======\ndeles\n>>>>>>> outro\nz\n"
    blocks = gitops.parse_conflicts(text)
    assert blocks[0]["base"] == "antes\n" and blocks[0]["rotulo_deles"] == "outro"
    assert gitops.resolve_conflicts(text, ["base"]) == "a\nantes\nz\n"
    assert gitops.parse_conflicts("só texto\n=======\nsem marcador de abertura\n") == []


# --- o lado antigo do diff de imagem ----------------------------------------------------------------


def test_blob_returns_the_file_at_a_ref(core, repo):
    client, _ = core
    (repo / "app.py").write_text("print('novo')\n", encoding="utf-8")
    answer = client.get("/git/blob", params={"path": str(repo), "file": "app.py", "ref": "HEAD", "token": TOKEN})
    assert answer.status_code == 200 and answer.content == b"print('oi')\n"
    assert client.get("/git/blob", params={"path": str(repo), "file": "nao.txt", "token": TOKEN}).status_code == 404
    assert client.get("/git/blob", params={"path": str(repo), "file": "app.py"}).status_code == 401


# --- GitHub pelo gh (falso) ---------------------------------------------------------------------------


class FakeGh:
    def __init__(self, logged: bool = True, repo: str | None = "pedro/metis", pr: dict | None = None):
        self.logged, self.repo, self.pr = logged, repo, pr
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cwd, *args, timeout=30):
        self.calls.append(args)
        if args[:2] == ("auth", "status"):
            return (0, "", "") if self.logged else (1, "", "not logged in")
        if args[:2] == ("repo", "view"):
            return (0, json.dumps({"nameWithOwner": self.repo}), "") if self.repo else (1, "", "no git remotes")
        if args[:2] == ("pr", "view"):
            return (0, json.dumps(self.pr), "") if self.pr else (1, "", "no pull requests found for branch")
        if args[:2] == ("pr", "create"):
            self.pr = {"number": 7, "title": args[args.index("--title") + 1], "url": "https://github.com/pedro/metis/pull/7", "state": "OPEN", "isDraft": "--draft" in args, "baseRefName": args[args.index("--base") + 1], "headRefName": "feature"}
            return 0, "https://github.com/pedro/metis/pull/7\n", ""
        if args[:2] == ("pr", "merge"):
            self.pr = {**(self.pr or {}), "state": "MERGED"}
            return 0, "", ""
        if args[:2] == ("pr", "ready"):
            self.pr = {**(self.pr or {}), "isDraft": False}
            return 0, "", ""
        if args[:2] == ("issue", "list"):
            return 0, json.dumps([{"number": 3, "title": "Bug no kanban", "url": "u3", "labels": [{"name": "bug"}], "author": {"login": "pedro"}, "updatedAt": "2026-11-08"}]), ""
        if args[:2] == ("pr", "list"):
            return 0, json.dumps([{"number": 7, "title": "v0.9.6", "url": "u7", "isDraft": False, "headRefName": "release/v0.9.6", "author": {"login": "pedro"}, "statusCheckRollup": [{"conclusion": "SUCCESS"}]}]), ""
        return 1, "", f"inesperado: {args}"


@pytest.fixture
def fake_gh(monkeypatch):
    def install(**kwargs) -> FakeGh:
        fake = FakeGh(**kwargs)
        monkeypatch.setattr(github, "gh", fake)
        github.clear()
        return fake

    yield install
    github.clear()


def test_github_state_without_gh_or_pr(core, repo, fake_gh):
    client, _ = core
    fake_gh(logged=False)
    assert client.get("/github/estado", params={"path": str(repo)}, headers=AUTH).json() == {"gh": False, "repo": None, "pr": None}
    fake_gh(repo=None)
    assert client.get("/github/estado", params={"path": str(repo)}, headers=AUTH).json() == {"gh": True, "repo": None, "pr": None}
    fake_gh()
    state = client.get("/github/estado", params={"path": str(repo)}, headers=AUTH).json()
    assert state == {"gh": True, "repo": "pedro/metis", "pr": None}
    assert client.get("/github/itens", params={"path": str(repo)}, headers=AUTH).json()["issues"][0] == {
        "numero": 3, "titulo": "Bug no kanban", "url": "u3", "rotulos": ["bug"], "autor": "pedro", "atualizado": "2026-11-08"
    }  # fmt: skip


def test_github_pr_state_checks_and_cache(core, repo, fake_gh):
    client, _ = core
    rollup = [
        {"conclusion": "SUCCESS"}, {"conclusion": "SKIPPED"}, {"conclusion": "FAILURE"},
        {"status": "IN_PROGRESS", "conclusion": ""}, {"state": "PENDING"}, {"state": "SUCCESS"},
    ]  # fmt: skip
    fake = fake_gh(pr={"number": 5, "title": "PR", "url": "u", "state": "OPEN", "isDraft": True, "baseRefName": "main", "headRefName": "f", "statusCheckRollup": rollup, "reviewDecision": "APPROVED", "mergeable": "MERGEABLE"})
    pr = client.get("/github/estado", params={"path": str(repo)}, headers=AUTH).json()["pr"]
    assert pr["numero"] == 5 and pr["rascunho"] is True and pr["revisao"] == "APPROVED" and pr["mesclavel"] == "MERGEABLE"
    assert pr["checks"] == {"ok": 3, "falhou": 1, "pendente": 2}
    calls = len(fake.calls)
    client.get("/github/estado", params={"path": str(repo)}, headers=AUTH)
    assert len(fake.calls) == calls  # 60 s de cache
    ready = client.post("/github/pr/pronto", json={"path": str(repo), "numero": 5}, headers=AUTH).json()
    assert ready["rascunho"] is False
    merged = client.post("/github/pr/juntar", json={"path": str(repo), "numero": 5, "metodo": "squash"}, headers=AUTH).json()
    assert merged["estado"] == "MERGED" and ("pr", "merge", "5", "--squash") in fake.calls
    assert client.post("/github/pr/juntar", json={"path": str(repo), "numero": 5, "metodo": "fast"}, headers=AUTH).status_code == 422


def test_github_create_pr_pushes_the_branch_first(core, repo, remote, fake_gh):
    client, _ = core
    fake = fake_gh()
    run("git", "checkout", "-q", "-b", "feature", cwd=repo)
    (repo / "f.txt").write_text("f\n", encoding="utf-8")
    commit_all(repo, "feature")
    pr = client.post("/github/pr", json={"path": str(repo), "titulo": "Feature", "corpo": "o porquê", "base": "main", "rascunho": True}, headers=AUTH).json()
    assert pr["numero"] == 7 and pr["rascunho"] is True and pr["base"] == "main"
    assert "feature" in run("git", "branch", "-r", cwd=repo)  # subiu antes do gh
    create = next(c for c in fake.calls if c[:2] == ("pr", "create"))
    assert "--draft" in create and create[create.index("--body") + 1] == "o porquê"
    bad = client.post("/github/pr", json={"path": str(repo), "titulo": "x", "base": "-main"}, headers=AUTH)
    assert bad.status_code == 400


# --- receitas, assinatura e editores -------------------------------------------------------------------


def test_recipes_live_in_the_prefs(core):
    client, _ = core
    prefs = client.get("/ajustes", headers=AUTH).json()
    assert prefs["agente_git"] == "claude" and "{base}" in prefs["receita_pr"] and "git diff --cached" in prefs["receita_commit_marcado"]
    changed = client.put("/ajustes", json={"receita_pr": "PR curto para o {base}", "agente_git": "codex"}, headers=AUTH).json()
    assert changed["receita_pr"] == "PR curto para o {base}" and changed["agente_git"] == "codex"
    reset = client.put("/ajustes", json={"receita_pr": "   "}, headers=AUTH).json()
    assert reset["receita_pr"] == prefs["receita_pr"]
    assert client.put("/ajustes", json={"agente_git": "gemini"}, headers=AUTH).status_code == 400
    assert client.put("/ajustes", json={"receita_commit": "x" * 5000}, headers=AUTH).status_code == 400


def test_git_signing_config_uses_the_global_file(core, tmp_path, monkeypatch):
    client, _ = core
    global_file = tmp_path / "gitconfig"
    global_file.write_text("[user]\n\tname = Pedro\n\temail = p@example.com\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_file))
    config = client.get("/git/config", headers=AUTH).json()
    assert config == {"assinar": False, "formato": "openpgp", "tem_chave": False, "nome": "Pedro", "email": "p@example.com"}
    assert client.put("/git/config", json={"assinar": True}, headers=AUTH).json()["assinar"] is True
    assert "gpgsign = true" in global_file.read_text(encoding="utf-8")


def test_external_editors(tmp_path, monkeypatch, core):
    apps = tmp_path / "Applications"
    (apps / "Cursor.app").mkdir(parents=True)
    (apps / "Zed.app").mkdir()
    assert system.list_editors([apps]) == [{"id": "cursor", "nome": "Cursor"}, {"id": "zed", "nome": "Zed"}]
    ran: list[list[str]] = []
    system.open_in("zed", str(tmp_path), [apps], run=ran.append)
    assert ran == [["open", "-a", str(apps / "Zed.app"), str(tmp_path)]]
    with pytest.raises(ValueError):
        system.open_in("code", str(tmp_path), [apps], run=ran.append)
    with pytest.raises(ValueError):
        system.open_in("zed", str(tmp_path / "nao-existe"), [apps], run=ran.append)
    monkeypatch.setattr(system, "app_dirs", lambda: [apps])
    client, _ = core
    assert client.get("/sistema/editores", headers=AUTH).json() == [{"id": "cursor", "nome": "Cursor"}, {"id": "zed", "nome": "Zed"}]
    assert client.post("/sistema/abrir-em", json={"editor": "code", "path": str(tmp_path)}, headers=AUTH).status_code == 400
