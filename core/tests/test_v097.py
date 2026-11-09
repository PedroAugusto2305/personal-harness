"""v0.9.7: editores dentro da MÊTIS. Gravar arquivo da worktree e nota do Brain conferindo o
hash (nada grava por cima do que o agente ou o Obsidian mudou) e títulos para o [[."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core.app import create_app

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def brain_vault(settings) -> Path:
    root = settings.brain
    folder = root / "01-PROJETOS" / "Ação Rápida"
    (folder / "decisoes").mkdir(parents=True)
    (folder / "Ação Rápida.md").write_text("---\ntipo: projeto\nstatus: ativo\n---\n\n# Ação Rápida\n\nCorpo do projeto.\n", encoding="utf-8")
    (folder / "decisoes" / "Webhook passa por fila.md").write_text(
        '---\ntipo: decisao\nprojeto: "[[Ação Rápida]]"\nstatus: aceita\n---\n\n# Webhook passa por fila\n\n> [!abstract] A decisão\n> Fila antes do CRM.\n',
        encoding="utf-8",
    )
    (folder / "decisoes" / "Ação de rollback manual.md").write_text("---\ntipo: decisao\n---\n\nRollback.\n", encoding="utf-8")
    (root / "02-AREAS").mkdir(parents=True)
    (root / "02-AREAS" / "Acentuação e busca.md").write_text("# Acentuação\n", encoding="utf-8")
    return root


@pytest.fixture
def core(settings, accounts, brain_vault):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client, app


# --- arquivos da worktree -----------------------------------------------------------------


def test_fs_text_brings_hash_and_mtime(core, repo):
    client, _ = core
    answer = client.get("/fs/text", params={"root": str(repo), "path": "app.py"}, headers=AUTH).json()
    assert answer["hash"] == sha((repo / "app.py").read_bytes())
    assert answer["mtime"] == pytest.approx((repo / "app.py").stat().st_mtime)


def test_fs_write_checks_the_hash_and_keeps_the_mode(core, repo):
    client, _ = core
    target = repo / "app.py"
    target.chmod(0o755)
    opened = client.get("/fs/text", params={"root": str(repo), "path": "app.py"}, headers=AUTH).json()
    text = "print('editado')\r\nsem quebra no fim"
    saved = client.put("/fs/text", json={"root": str(repo), "path": "app.py", "text": text, "hash": opened["hash"]}, headers=AUTH)
    assert saved.status_code == 200, saved.text
    assert target.read_bytes() == text.encode("utf-8")  # exatamente o que veio, com o \r\n
    assert saved.json()["hash"] == sha(text.encode("utf-8")) and saved.json()["size"] == len(text.encode("utf-8"))
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    # O agente mexeu depois: o hash antigo não grava mais por cima.
    target.write_text("print('o agente mudou')\n", encoding="utf-8")
    stale = client.put("/fs/text", json={"root": str(repo), "path": "app.py", "text": "meu", "hash": saved.json()["hash"]}, headers=AUTH)
    assert stale.status_code == 409
    assert stale.json()["detail"]["hash"] == sha(target.read_bytes())
    assert "mudou no disco" in stale.json()["detail"]["mensagem"]
    assert target.read_text(encoding="utf-8") == "print('o agente mudou')\n"
    assert not [p for p in repo.iterdir() if p.name.startswith(".metis-")]  # nenhum temporário largado


def test_fs_write_refusals(core, repo, tmp_path):
    client, _ = core
    zero = "0" * 64
    put = lambda path, text="x", h=zero: client.put("/fs/text", json={"root": str(repo), "path": path, "text": text, "hash": h}, headers=AUTH)  # noqa: E731
    outside = tmp_path / "fora.txt"
    outside.write_text("fora", encoding="utf-8")
    assert put("../fora.txt").status_code == 400
    assert put(".git/config").status_code == 400
    assert put("nao-existe.py").status_code == 400
    (repo / "pasta").mkdir()
    assert put("pasta").status_code == 400
    (repo / "imagem.bin").write_bytes(b"\x89PNG\0\0dados")
    assert put("imagem.bin", h=sha(b"\x89PNG\0\0dados")).status_code == 400
    big = "x" * (2 * 1024 * 1024 + 1)
    assert put("app.py", text=big, h=sha((repo / "app.py").read_bytes())).status_code == 413
    assert outside.read_text(encoding="utf-8") == "fora"


# --- notas do Brain ---------------------------------------------------------------------


def test_note_text_round_trip_conflict_and_index(core, brain_vault):
    client, app = core
    rel = "01-PROJETOS/Ação Rápida/decisoes/Webhook passa por fila.md"
    note = client.get("/brain/note/texto", params={"path": rel}, headers=AUTH).json()
    assert note["path"] == rel and note["texto"].startswith("---\ntipo: decisao")
    assert note["hash"] == sha((brain_vault / rel).read_bytes())
    events = app.state.manager.events.subscribe()
    novo = note["texto"].replace("Fila antes do CRM.", "Fila antes do CRM, com retentativa.")
    saved = client.put("/brain/note/texto", json={"path": rel, "texto": novo, "hash": note["hash"]}, headers=AUTH)
    assert saved.status_code == 200, saved.text
    assert (brain_vault / rel).read_text(encoding="utf-8") == novo
    assert saved.json()["hash"] == sha(novo.encode("utf-8"))
    changed = []
    while not events.empty():
        changed.append(events.get_nowait())
    assert {"type": "brain.changed", "project": "Ação Rápida"} in changed
    # O índice já vê o texto novo (o resumo vem do callout).
    assert "retentativa" in client.get("/brain/note", params={"path": rel}, headers=AUTH).json()["resumo"]
    # O Obsidian gravou depois: o hash antigo é recusado e a nota fica como o Obsidian deixou.
    time.sleep(0.01)
    (brain_vault / rel).write_text(novo + "\nlinha do Obsidian\n", encoding="utf-8")
    stale = client.put("/brain/note/texto", json={"path": rel, "texto": "meu texto", "hash": saved.json()["hash"]}, headers=AUTH)
    assert stale.status_code == 409 and stale.json()["detail"]["hash"] == sha((brain_vault / rel).read_bytes())
    assert (brain_vault / rel).read_text(encoding="utf-8").endswith("linha do Obsidian\n")


def test_note_text_refusals(core, brain_vault):
    client, _ = core
    rel = "01-PROJETOS/Ação Rápida/Ação Rápida.md"
    current = sha((brain_vault / rel).read_bytes())
    empty = client.put("/brain/note/texto", json={"path": rel, "texto": "  \n ", "hash": current}, headers=AUTH)
    assert empty.status_code == 400 and "nunca apaga" in empty.json()["detail"]
    assert client.get("/brain/note/texto", params={"path": "01-PROJETOS/Nova.md"}, headers=AUTH).status_code == 404
    assert client.put("/brain/note/texto", json={"path": "01-PROJETOS/Nova.md", "texto": "x", "hash": current}, headers=AUTH).status_code == 404
    assert client.get("/brain/note/texto", params={"path": "../fora.md"}, headers=AUTH).status_code in (400, 404)
    assert not (brain_vault / "01-PROJETOS" / "Nova.md").exists()


def test_titles_for_the_wikilink_autocomplete(core, brain_vault):
    client, _ = core
    titles = lambda q, **kw: [t["titulo"] for t in client.get("/brain/titulos", params={"q": q, **kw}, headers=AUTH).json()]  # noqa: E731
    # Sem acento e sem caixa; os que começam com o texto vêm antes, depois em ordem alfabética.
    # "Acentuação" contém "acao" sem acento, mas não começa com ele: vem depois.
    assert titles("acao") == ["Ação de rollback manual", "Ação Rápida", "Acentuação e busca"]
    assert titles("AÇÃO") == titles("acao")
    found = titles("ac")
    assert found[:3] == ["Ação de rollback manual", "Ação Rápida", "Acentuação e busca"]
    assert "Webhook passa por fila" not in found
    assert titles("fila") == ["Webhook passa por fila"]
    one = client.get("/brain/titulos", params={"q": "fila"}, headers=AUTH).json()[0]
    assert one["tipo"] == "decisao" and one["projeto"] == "Ação Rápida" and one["path"].endswith("Webhook passa por fila.md")
    # Sem texto: as mexidas mais recentemente primeiro.
    newest = brain_vault / "02-AREAS" / "Acentuação e busca.md"
    os.utime(newest, (time.time() + 60, time.time() + 60))
    assert titles("")[0] == "Acentuação e busca"
    assert len(titles("", limite=2)) == 2
    assert client.get("/brain/titulos", params={"q": "a", "limite": 99}, headers=AUTH).status_code == 422
    assert titles("100%_x") == []  # % e _ são texto, não curinga
