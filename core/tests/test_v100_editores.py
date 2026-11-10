"""v1.0.0: revisão dos editores da v0.9.7. O hash que o editor recebe é dos mesmos bytes do
texto (senão gravava por cima do que o agente mudou no meio da leitura), e arquivo ou nota fora
de UTF-8 nunca é gravado (o caractere de troca da leitura viraria o texto do arquivo, para sempre)."""

from __future__ import annotations

import codecs
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import files as fs
from harness_core.app import create_app

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
REPLACEMENT = chr(0xFFFD)  # o que a leitura põe no lugar de cada byte que não é UTF-8


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def core(settings, accounts):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        yield client


# --- o hash e o texto da mesma leitura ---------------------------------------------------


def test_read_text_hash_and_text_come_from_the_same_read(repo, monkeypatch):
    target = repo / "app.py"
    before = target.read_bytes()
    agent = b"print('o agente gravou no meio')\n"
    original = fs.file_hash

    def agent_writes_then_hash(path: Path) -> str:
        target.write_bytes(agent)  # o agente grava entre a leitura do texto e a do hash
        return original(path)

    monkeypatch.setattr(fs, "file_hash", agent_writes_then_hash)
    opened = fs.read_text(str(repo), "app.py")
    monkeypatch.setattr(fs, "file_hash", original)
    target.write_bytes(agent)  # se a leitura já não pegou, o agente grava logo depois dela
    assert opened["text"].encode("utf-8") == before
    assert opened["hash"] == sha(before)  # antes: o hash da versão do agente, com o texto antigo
    # Gravar com esse hash é recusado: a versão do agente fica.
    with pytest.raises(fs.FileConflict):
        fs.write_text(str(repo), "app.py", opened["text"] + "# meu\n", opened["hash"])
    assert target.read_bytes() == agent


def test_big_file_still_brings_the_hash_of_the_whole_file(repo):
    target = repo / "grande.log"
    data = b"linha\n" * (fs.MAX_TEXT_BYTES // 6 + 10)
    target.write_bytes(data)
    opened = fs.read_text(str(repo), "grande.log")
    assert opened["truncated"] and opened["size"] == len(data)
    assert len(opened["text"]) == fs.MAX_TEXT_BYTES
    assert opened["hash"] == sha(data)


# --- fora de UTF-8 não grava --------------------------------------------------------------


def test_file_outside_utf8_is_never_saved(core, repo):
    target = repo / "latin.txt"
    latin = "café com açúcar\n".encode("latin-1")
    target.write_bytes(latin)
    opened = core.get("/fs/text", params={"root": str(repo), "path": "latin.txt"}, headers=AUTH).json()
    assert REPLACEMENT in opened["text"] and opened["hash"] == sha(latin)
    saved = core.put("/fs/text", json={"root": str(repo), "path": "latin.txt", "text": opened["text"] + "mais\n", "hash": opened["hash"]}, headers=AUTH)
    assert target.read_bytes() == latin  # antes: cada acento virava EF BF BD
    assert saved.status_code == 400 and "UTF-8" in saved.json()["detail"]
    assert opened["utf8"] is False  # o editor abre só para leitura, com o aviso


def test_utf8_file_with_bom_still_saves_byte_for_byte(core, repo):
    target = repo / "bom.txt"
    target.write_bytes(codecs.BOM_UTF8 + "olá\r\n".encode("utf-8"))
    opened = core.get("/fs/text", params={"root": str(repo), "path": "bom.txt"}, headers=AUTH).json()
    assert opened["hash"] == sha(target.read_bytes())
    saved = core.put("/fs/text", json={"root": str(repo), "path": "bom.txt", "text": opened["text"] + "ação\r\n", "hash": opened["hash"]}, headers=AUTH)
    assert saved.status_code == 200, saved.text
    assert target.read_bytes() == codecs.BOM_UTF8 + "olá\r\nação\r\n".encode("utf-8")
    assert opened["utf8"] is True


def test_note_outside_utf8_is_never_saved(core, settings):
    folder = settings.brain / "02-AREAS"
    folder.mkdir(parents=True)
    note = folder / "Antiga.md"
    latin = "# Antiga\n\nAnotação de 2019.\n".encode("latin-1")
    note.write_bytes(latin)
    rel = "02-AREAS/Antiga.md"
    opened = core.get("/brain/note/texto", params={"path": rel}, headers=AUTH).json()
    saved = core.put("/brain/note/texto", json={"path": rel, "texto": opened["texto"] + "\nmais\n", "hash": opened["hash"]}, headers=AUTH)
    assert note.read_bytes() == latin  # antes: cada acento virava EF BF BD
    assert saved.status_code == 400 and "UTF-8" in saved.json()["detail"]
    assert opened["utf8"] is False  # o editor de nota abre só para leitura, com o aviso
    # A nota em UTF-8 continua gravando.
    (folder / "Nova.md").write_text("# Nova\n\nAcentuação.\n", encoding="utf-8")
    fresh = core.get("/brain/note/texto", params={"path": "02-AREAS/Nova.md"}, headers=AUTH).json()
    assert fresh["utf8"] is True
    ok = core.put("/brain/note/texto", json={"path": "02-AREAS/Nova.md", "texto": fresh["texto"] + "\nmais\n", "hash": fresh["hash"]}, headers=AUTH)
    assert ok.status_code == 200, ok.text
