"""v0.9.1: Quadros (.canvas do Obsidian no vault), cartão da sessão e nota como contexto."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.boards import BoardConflict, BoardError, BoardStore, normalize
from harness_core.brain_index import BrainIndex
from harness_core.transcript import last_messages
from harness_core.vault import Vault

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
NOTE = "01-PROJETOS/Alfa/decisoes/Webhook passa por fila.md"


@pytest.fixture
def vault_root(settings) -> Path:
    alfa = settings.brain / "01-PROJETOS" / "Alfa"
    (alfa / "decisoes").mkdir(parents=True)
    (alfa / "Alfa.md").write_text("---\ntipo: projeto\n---\n\n# Alfa\n\n## ✅ Próximas ações\n\n- [ ] Revisar\n", encoding="utf-8")
    (settings.brain / NOTE).write_text(
        "---\ntipo: decisao\nstatus: aceita\nprojeto: \"[[Alfa]]\"\n---\n\n# Webhook passa por fila\n\n> [!abstract] A decisão\n> Todo webhook entra numa fila.\n",
        encoding="utf-8",
    )
    return settings.brain


@pytest.fixture
def store(settings, vault_root) -> BoardStore:
    vault = Vault(vault_root)
    return BoardStore(vault, BrainIndex(vault, settings.home / "brain.db"))


def test_board_lives_in_the_project_folder_as_obsidian_canvas(store, vault_root):
    made = store.create("Alfa", "go-live: semana 1")
    assert made == {**made, "path": "01-PROJETOS/Alfa/quadros/go-live semana 1.canvas", "projeto": "Alfa", "itens": 0}
    assert json.loads((vault_root / made["path"]).read_text(encoding="utf-8")) == {"nodes": [], "edges": []}
    with pytest.raises(BoardError, match="já existe"):
        store.create("Alfa", "go-live semana 1")
    with pytest.raises(BoardError, match="projeto não encontrado"):
        store.create("Beta", "x")
    assert [b["nome"] for b in store.list()] == ["go-live semana 1"]


def test_save_resolves_notes_keeps_obsidian_fields_and_refuses_stale_writes(store, vault_root):
    path = store.create("Alfa", "quadro")["path"]
    board = store.read(path)
    canvas = {
        "nodes": [
            {"id": "a1", "type": "file", "file": NOTE, "x": 0, "y": 0, "width": 300, "height": 180, "color": "4"},
            {"id": "a2", "type": "file", "file": "01-PROJETOS/Alfa/sumiu.md", "x": 400, "y": 0, "width": 300, "height": 180},
            {"id": "a3", "type": "text", "text": "Nota sua\n\n%%metis {\"tipo\":\"tarefa\",\"projeto\":\"Alfa\",\"id\":\"x\"}%%", "x": 0, "y": 300, "width": 260, "height": 120, "styleAttributes": {"shape": "pill"}},
            {"id": "a4", "type": "planilha", "x": 0, "y": 0, "width": 10, "height": 10},
        ],
        "edges": [
            {"id": "e1", "fromNode": "a1", "toNode": "a3", "label": "contexto", "toSide": "left", "fromEnd": "voando"},
            {"id": "e2", "fromNode": "a1", "toNode": "apagado"},
        ],
    }
    saved = store.save(path, canvas, board["alterado"])
    assert saved["notas"][NOTE]["title"] == "Webhook passa por fila" and saved["notas"]["01-PROJETOS/Alfa/sumiu.md"] is None
    data = json.loads((vault_root / path).read_text(encoding="utf-8"))
    assert [n["id"] for n in data["nodes"]] == ["a1", "a2", "a3"]  # tipo desconhecido fica de fora
    assert data["nodes"][2]["styleAttributes"] == {"shape": "pill"}  # o que o Obsidian guarda, a MÊTIS não apaga
    assert data["edges"] == [{"id": "e1", "fromNode": "a1", "toNode": "a3", "label": "contexto", "toSide": "left"}]
    # O Obsidian salvou depois que a tela abriu: a MÊTIS não passa por cima.
    file = vault_root / path
    os.utime(file, (time.time() + 5, time.time() + 5))
    with pytest.raises(BoardConflict):
        store.save(path, canvas, saved["alterado"])
    with pytest.raises(BoardError, match="fora do vault"):
        store.read("01-PROJETOS/../../fora.canvas")
    with pytest.raises(BoardError, match="01-PROJETOS"):
        store.read("06-DIARIO/x.canvas")
    with pytest.raises(BoardError, match="sem caminho"):
        normalize({"nodes": [{"id": "z", "type": "file", "x": 0, "y": 0, "width": 1, "height": 1}]})


def test_last_messages_reads_the_end_of_the_transcript(tmp_path):
    lines = [
        {"type": "user", "message": {"content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"content": "arruma o webhook"}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}, {"type": "text", "text": "Arrumei   a fila."}]}},
        {"type": "user", "isMeta": True, "message": {"content": "lembrete"}},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    assert last_messages(str(path)) == [{"role": "voce", "text": "arruma o webhook"}, {"role": "agente", "text": "Arrumei a fila."}]
    assert last_messages(str(tmp_path / "nao-existe.jsonl")) == []


def test_routes_session_card_message_and_note_as_context(settings, accounts, vault_root, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", lambda kind, s: ["/bin/cat"])
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        made = client.post("/quadros", json={"projeto": "Alfa", "nome": "Plano"}, headers=AUTH).json()
        board = client.get("/quadros/abrir", params={"path": made["path"]}, headers=AUTH).json()
        canvas = {"nodes": [{"id": "n", "type": "file", "file": NOTE, "x": 0, "y": 0, "width": 280, "height": 160}], "edges": []}
        saved = client.put("/quadros/salvar", json={"path": made["path"], "canvas": canvas, "base": board["alterado"]}, headers=AUTH).json()
        stale = client.put("/quadros/salvar", json={"path": made["path"], "canvas": canvas, "base": board["alterado"] - 10}, headers=AUTH)
        assert stale.status_code == 409 and saved["notas"][NOTE]["tipo"] == "decisao"
        assert client.get("/quadros", headers=AUTH).json()[0]["itens"] == 1

        sid = client.post("/sessions", json={"kind": "shell", "cwd": str(vault_root)}, headers=AUTH).json()["id"]
        assert client.post(f"/sessions/{sid}/mensagem", json={"texto": "oi do quadro"}, headers=AUTH).status_code == 204
        glance = {}
        for _ in range(60):
            glance = client.get(f"/sessions/{sid}/resumo", headers=AUTH).json()
            if any("oi do quadro" in line for line in glance["linhas"]):
                break
            time.sleep(0.05)
        assert any("oi do quadro" in line for line in glance["linhas"]) and glance["kind"] == "shell" and glance["ultimas"] == []
        refused = client.post("/quadros/ligar", json={"sessao": sid, "nota": NOTE}, headers=AUTH)
        assert refused.status_code == 400 and "Claude ou do Codex" in refused.json()["detail"]  # no shell viraria comando
        app.state.manager.get(sid).kind = "claude"  # o mesmo terminal fazendo papel de sessão do Claude
        linked = client.post("/quadros/ligar", json={"sessao": sid, "nota": NOTE}, headers=AUTH).json()
        assert "Webhook passa por fila" in linked["mensagem"]
        assert NOTE in app.state.hub.session_notes[sid] and app.state.hub.session_notes[sid][NOTE]["via"] == ["quadro"]
        assert client.post("/quadros/ligar", json={"sessao": "nada", "nota": NOTE}, headers=AUTH).status_code == 404
        client.delete(f"/sessions/{sid}", headers=AUTH)
        assert client.post(f"/sessions/{sid}/mensagem", json={"texto": "x"}, headers=AUTH).status_code == 404
