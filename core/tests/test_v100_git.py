"""v1.0.0: a revisão do Git e GitHub da v0.9.6 (lados do conflito no rebase, arquivo resolvido
byte a byte, força com garantia de verdade, comparar arquivo não rastreado, PR por branch,
linhas de arquivo novo e o status sem processos à toa)."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness_core import gitops

from .conftest import run
from .test_v096 import AUTH, clone, commit_all, core, fake_gh, remote  # noqa: F401 (fixtures)

PATCH_TS = Path(__file__).resolve().parents[2] / "app" / "src" / "lib" / "patch.ts"


def plain_conflicts(repo: Path) -> None:
    """Sem diff3 nem conversão de fim de linha, seja qual for o ~/.gitconfig da máquina."""
    run("git", "config", "merge.conflictStyle", "merge", cwd=repo)
    run("git", "config", "core.autocrlf", "false", cwd=repo)


# --- conflito no rebase: nosso é sempre o deste branch ---------------------------------------------


def rebase_conflict(client, repo: Path, bare: Path, tmp_path: Path) -> None:
    """O Sincronizar (pull --rebase) para num conflito: aqui mudou para nosso, lá para deles."""
    plain_conflicts(repo)
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).json()["feito"] == "push"
    other = clone(bare, tmp_path / "outro")
    (other / "app.py").write_text("print('deles')\n", encoding="utf-8")
    commit_all(other, "deles")
    run("git", "push", "-q", cwd=other)
    (repo / "app.py").write_text("print('nosso')\n", encoding="utf-8")
    commit_all(repo, "nosso")
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).status_code == 400
    assert client.get("/git/status", params={"path": str(repo)}, headers=AUTH).json()["operacao"] == "rebase"


def test_rebase_whole_file_nosso_keeps_this_branch(core, repo, remote, tmp_path):
    client, _ = core
    rebase_conflict(client, repo, remote, tmp_path)
    done = client.post("/git/conflito", json={"path": str(repo), "file": "app.py", "lado": "nosso"}, headers=AUTH)
    assert done.json() == {"resolvido": True}
    # No rebase o --ours do git é o remoto: antes, "nosso" jogava fora a mudança daqui.
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('nosso')\n"
    assert client.post("/git/operacao", json={"path": str(repo), "acao": "continuar"}, headers=AUTH).status_code == 200
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('nosso')\n"
    assert run("git", "log", "--format=%s", "-2", cwd=repo).split() == ["nosso", "deles"]


def test_rebase_blocks_show_and_pick_this_branch_as_nosso(core, repo, remote, tmp_path):
    client, _ = core
    rebase_conflict(client, repo, remote, tmp_path)
    block = client.get("/git/conflito", params={"path": str(repo), "file": "app.py"}, headers=AUTH).json()["blocos"][0]
    assert block["nosso"] == "print('nosso')\n" and block["deles"] == "print('deles')\n"
    assert "nosso" in block["rotulo_nosso"] and block["rotulo_deles"] == "HEAD"
    done = client.post("/git/conflito", json={"path": str(repo), "file": "app.py", "escolhas": ["nosso"]}, headers=AUTH)
    assert done.json() == {"resolvido": True}
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('nosso')\n"
    # Lado inteiro "deles" no rebase: fica o que veio do remoto.
    assert client.post("/git/operacao", json={"path": str(repo), "acao": "abortar"}, headers=AUTH).status_code == 200
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).status_code == 400
    assert client.post("/git/conflito", json={"path": str(repo), "file": "app.py", "lado": "deles"}, headers=AUTH).status_code == 200
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('deles')\n"


def test_merge_sides_stay_as_they_were(core, repo):
    """No merge o --ours já é este branch: nada muda."""
    client, _ = core
    plain_conflicts(repo)
    run("git", "checkout", "-q", "-b", "outro", cwd=repo)
    (repo / "app.py").write_text("print('deles')\n", encoding="utf-8")
    commit_all(repo, "deles")
    run("git", "checkout", "-q", "main", cwd=repo)
    (repo / "app.py").write_text("print('nosso')\n", encoding="utf-8")
    commit_all(repo, "nosso")
    subprocess.run(["git", "merge", "outro"], cwd=repo, capture_output=True)
    block = client.get("/git/conflito", params={"path": str(repo), "file": "app.py"}, headers=AUTH).json()["blocos"][0]
    assert block["nosso"] == "print('nosso')\n" and block["rotulo_nosso"] == "HEAD"
    assert client.post("/git/conflito", json={"path": str(repo), "file": "app.py", "lado": "nosso"}, headers=AUTH).status_code == 200
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('nosso')\n"


# --- resolver bloco a bloco não reescreve o resto do arquivo ------------------------------------------


def test_block_resolution_keeps_crlf_and_bytes_that_are_not_utf8(core, repo):
    client, _ = core
    plain_conflicts(repo)
    target = repo / "windows.txt"
    target.write_bytes(b"caf\xe9\r\nmeio\r\nfim\r\n")
    commit_all(repo, "latin-1 com CRLF")
    run("git", "checkout", "-q", "-b", "outro", cwd=repo)
    target.write_bytes(b"caf\xe9\r\ndeles\r\nfim\r\n")
    commit_all(repo, "deles")
    run("git", "checkout", "-q", "main", cwd=repo)
    target.write_bytes(b"caf\xe9\r\nnosso\r\nfim\r\n")
    commit_all(repo, "nosso")
    subprocess.run(["git", "merge", "outro"], cwd=repo, capture_output=True)
    assert b"<<<<<<< HEAD\r\n" in target.read_bytes()
    done = client.post("/git/conflito", json={"path": str(repo), "file": "windows.txt", "escolhas": ["deles"]}, headers=AUTH)
    assert done.json() == {"resolvido": True}
    # Antes: b"caf\xef\xbf\xbd\ndeles\nfim\n" (CRLF virava LF e o é do Latin-1 virava �).
    assert target.read_bytes() == b"caf\xe9\r\ndeles\r\nfim\r\n"


# --- forçar a subida depois do fetch automático -----------------------------------------------------


def test_force_push_does_not_overwrite_a_commit_brought_only_by_the_fetch(core, repo, remote, tmp_path):
    client, _ = core
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).json()["feito"] == "push"
    (repo / "app.py").write_text("print('meu')\n", encoding="utf-8")
    commit_all(repo, "meu")
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).json()["feito"] == "push"
    other = clone(remote, tmp_path / "colega")
    (other / "colega.txt").write_text("do colega\n", encoding="utf-8")
    commit_all(other, "do colega")
    run("git", "push", "-q", cwd=other)
    run("git", "commit", "-q", "--amend", "-m", "meu emendado", cwd=repo)
    # O painel busca o remoto sozinho ao abrir: o origin/main passa a ser o commit do colega.
    assert client.post("/git/fetch", json={"path": str(repo)}, headers=AUTH).status_code == 200
    assert client.post("/git/push", json={"path": str(repo)}, headers=AUTH).status_code == 400
    forced = client.post("/git/push", json={"path": str(repo), "force": True}, headers=AUTH)
    assert forced.status_code == 400
    assert "do colega" in run("git", "log", "--format=%s", "main", cwd=remote)
    # Depois de puxar o do colega (Sincronizar), o histórico daqui já o inclui: forçar volta a valer.
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).status_code == 200
    (repo / "app.py").write_text("print('outro')\n", encoding="utf-8")
    commit_all(repo, "outro")
    assert client.post("/git/sync", json={"path": str(repo)}, headers=AUTH).json()["feito"] == "push"
    run("git", "commit", "-q", "--amend", "-m", "outro emendado", cwd=repo)
    assert client.post("/git/push", json={"path": str(repo), "force": True}, headers=AUTH).status_code == 200
    pushed = run("git", "log", "--format=%s", "main", cwd=remote).split("\n")
    assert pushed[0] == "outro emendado" and "do colega" in pushed


# --- comparar com outro branch: arquivo não rastreado ------------------------------------------------


def test_compare_diff_of_an_untracked_file_shows_the_whole_file(core, repo):
    client, _ = core
    run("git", "checkout", "-q", "-b", "feature", cwd=repo)
    (repo / "solto.txt").write_text("não rastreado\n", encoding="utf-8")
    changed = client.get("/git/changed", params={"path": str(repo), "ref": "main"}, headers=AUTH).json()
    assert ("solto.txt", "A") in {(f["path"], f["status"]) for f in changed["files"]}
    diff = client.get("/git/diff", params={"path": str(repo), "file": "solto.txt", "mode": "ref", "ref": "main"}, headers=AUTH)
    assert diff.status_code == 200 and "+não rastreado" in diff.text
    same = client.get("/git/diff", params={"path": str(repo), "file": "app.py", "mode": "ref", "ref": "main"}, headers=AUTH)
    assert same.status_code == 200 and same.text == ""


# --- o PR do GitHub é do branch, não só da pasta ------------------------------------------------------


def test_github_pr_cache_follows_the_branch(core, repo, fake_gh):
    client, _ = core
    run("git", "checkout", "-q", "-b", "feature", cwd=repo)
    fake = fake_gh(pr={"number": 5, "title": "Feature", "url": "u5", "state": "OPEN", "isDraft": False, "baseRefName": "main", "headRefName": "feature"})

    def pr():
        return client.get("/github/estado", params={"path": str(repo)}, headers=AUTH).json()["pr"]

    assert pr()["numero"] == 5
    run("git", "checkout", "-q", "-b", "outro", cwd=repo)
    fake.pr = None  # o gh deste branch não acha PR
    assert pr() is None
    run("git", "checkout", "-q", "feature", cwd=repo)
    calls = len(fake.calls)
    assert pr()["numero"] == 5 and len(fake.calls) == calls  # o do feature segue no cache


# --- marcar e desmarcar linhas de arquivo novo ou apagado ----------------------------------------------

RUNNER = """
import { readFileSync } from "node:fs";
const { buildPatch, splitPatch } = await import(process.argv[2]);
const { raw, picks, reverse } = JSON.parse(readFileSync(0, "utf8"));
const chosen = new Set(picks.map(([h, i]) => `${h}:${i}`));
process.stdout.write(buildPatch(splitPatch(raw), (h, i) => chosen.has(`${h}:${i}`), reverse) ?? "");
"""


def build_patch(tmp_path: Path, raw: str, picks: list[tuple[int, int]], reverse: bool) -> str:
    """O patch que a tela monta (app/src/lib/patch.ts), rodando o próprio TypeScript no Node."""
    if shutil.which("node") is None:
        pytest.skip("sem Node")
    runner = tmp_path / "patch-runner.mjs"
    runner.write_text(RUNNER, encoding="utf-8")
    done = subprocess.run(
        ["node", str(runner), PATCH_TS.as_uri()],
        input=json.dumps({"raw": raw, "picks": picks, "reverse": reverse}),
        capture_output=True,
        text=True,
    )
    if "ERR_UNKNOWN_FILE_EXTENSION" in done.stderr:
        pytest.skip("este Node não lê TypeScript")
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_unstage_some_lines_of_a_new_file(core, repo, tmp_path):
    client, _ = core
    (repo / "novo.txt").write_text("um\ndois\ntres\nquatro\n", encoding="utf-8")
    run("git", "add", "novo.txt", cwd=repo)
    raw = run("git", "diff", "--cached", "--", "novo.txt", cwd=repo)
    patch = build_patch(tmp_path, raw, [(0, 1)], reverse=True)  # só a linha "dois"
    answer = client.post("/git/apply", json={"path": str(repo), "patch": patch, "cached": True, "reverse": True}, headers=AUTH)
    assert answer.status_code == 200, answer.text  # antes: "new file novo.txt depends on old contents"
    assert run("git", "show", ":novo.txt", cwd=repo) == "um\ntres\nquatro\n"
    # Todas as linhas: aí desmarca o arquivo novo inteiro, como antes.
    raw = run("git", "diff", "--cached", "--", "novo.txt", cwd=repo)
    patch = build_patch(tmp_path, raw, [(0, 0), (0, 1), (0, 2)], reverse=True)
    assert client.post("/git/apply", json={"path": str(repo), "patch": patch, "cached": True, "reverse": True}, headers=AUTH).status_code == 200
    assert "novo.txt" not in run("git", "ls-files", cwd=repo)


def test_stage_some_lines_of_a_deleted_file(core, repo, tmp_path):
    client, _ = core
    target = repo / "lista.txt"
    target.write_text("um\ndois\ntres\n", encoding="utf-8")
    commit_all(repo, "lista")
    target.unlink()
    raw = run("git", "diff", "--", "lista.txt", cwd=repo)
    patch = build_patch(tmp_path, raw, [(0, 1)], reverse=False)  # marca só a remoção do "dois"
    answer = client.post("/git/apply", json={"path": str(repo), "patch": patch, "cached": True}, headers=AUTH)
    assert answer.status_code == 200, answer.text
    assert run("git", "show", ":lista.txt", cwd=repo) == "um\ntres\n"


# --- o status do painel (a cada 3 s) sem processos à toa -------------------------------------------------


def test_status_runs_only_status_and_rev_parse_while_head_stays(repo, remote, monkeypatch):
    run("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    calls: list[str] = []
    real = gitops.git

    async def counting(cwd, *args, **kwargs):
        calls.append(args[0])
        return await real(cwd, *args, **kwargs)

    monkeypatch.setattr(gitops, "git", counting)
    first = asyncio.run(gitops.status(repo))
    assert first["ultimo_commit"]["assunto"] == "primeiro" and first["ultimo_commit"]["subiu"] is True
    calls.clear()
    second = asyncio.run(gitops.status(repo))
    assert second["ultimo_commit"] == first["ultimo_commit"]
    assert sorted(calls) == ["rev-parse", "status"]  # antes: também log e merge-base, toda vez
    (repo / "app.py").write_text("print('dois')\n", encoding="utf-8")
    commit_all(repo, "segundo")
    after = asyncio.run(gitops.status(repo))
    assert after["ultimo_commit"]["assunto"] == "segundo" and after["ultimo_commit"]["subiu"] is False
    # Upstream que sumiu do remoto: não dá para dizer que subiu.
    run("git", "checkout", "-q", "-b", "feature", cwd=repo)
    run("git", "push", "-q", "-u", "origin", "feature", cwd=repo)
    run("git", "push", "-q", "origin", "--delete", "feature", cwd=repo)
    gone = asyncio.run(gitops.status(repo))
    assert gone["upstream"] == "origin/feature" and gone["ultimo_commit"]["subiu"] is False
