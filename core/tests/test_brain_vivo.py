"""v0.8.0, Brain vivo: significado, conflitos, sugestões entre projetos, MCP de fora,
mini-mapa da sessão e janela de contexto."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core import suggestions as suggestions_mod
from harness_core.app import create_app
from harness_core.brain_index import BrainIndex, words
from harness_core.brain_mcp import StdioServer, session_hook
from harness_core.semantic import Embedder, normalize
from harness_core.sessions import EventBus
from harness_core.suggestions import SuggestionError, Suggestions, clean_title
from harness_core.transcript import context_breakdown
from harness_core.vault import Vault

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


FAKE_DIM = 2048


def fake_encode(texts: list[str], wait: float = 0.0) -> np.ndarray:
    """Saco de palavras espalhado em 2048 posições: textos com palavras em comum ficam perto."""
    out = np.zeros((len(texts), FAKE_DIM), dtype=np.float32)
    for i, text in enumerate(texts):
        for word in words(text):
            out[i, zlib.crc32(word.encode()) % FAKE_DIM] += 1.0
        out[i, FAKE_DIM - 1] += 0.01  # nenhum vetor zerado
    return normalize(out)


class FakeEmbedder:
    def __init__(self) -> None:
        self.ticks = 0

    def encode(self, texts, wait=0.0):
        return fake_encode(texts, wait)

    def status(self) -> dict:
        return {"state": "pronto", "model": "fake", "url": "", "error": "", "disk_mb": 0, "loads": 1}

    def download(self) -> None:
        pass

    def tick(self) -> None:
        self.ticks += 1


def record(tipo: str, project: str, title: str, resumo: str, data: str = "2026-11-01", status: str = "") -> str:
    lines = ["---", f"tipo: {tipo}", f"data: {data}"]
    if status:
        lines.append(f"status: {status}")
    lines += [f'projeto: "[[{project}]]"', "---", "", f"# {title}", "", "> [!abstract] Resumo", f"> {resumo}", ""]
    return "\n".join(lines)


FILLER = [
    ("Gama", "Planilha de custos fecha no último dia útil", "O fechamento mensal da planilha de custos acontece no último dia útil."),
    ("Gama", "Fotos do catálogo saem em fundo branco", "Catálogo de produtos usa fotos com fundo branco e luz difusa."),
    ("Gama", "Reunião semanal acontece na segunda cedo", "Alinhamento do time na segunda às oito com pauta curta."),
    ("Beta", "Logo novo usa a paleta azul petróleo", "Identidade visual troca o laranja pelo azul petróleo."),
    ("Beta", "Contrato do fornecedor renova em janeiro", "Renovação anual do contrato com o fornecedor de embalagens."),
    ("Gama", "Treino de força três vezes por semana", "Rotina de academia com treino de força segunda quarta e sexta."),
    ("Beta", "Newsletter sai toda quinta às dez", "Envio da newsletter quinzenal às quintas pela manhã."),
    ("Gama", "Senha do roteador fica no cofre", "Credenciais da rede de casa ficam guardadas no cofre."),
] + [
    # Um vault de verdade tem centenas de registros: a régua do z precisa de população.
    ("Gama" if k % 2 else "Beta", f"Assunto{k} trata do item{k}", f"Detalhe{k} sobre o tema{k} e a parte{k}.")
    for k in range(40)
]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repos" / "alfa"
    (path / "src").mkdir(parents=True)
    return path


@pytest.fixture
def brain_root(settings, repo) -> Path:
    root = settings.brain
    for name in ("Alfa", "Beta", "Gama"):
        folder = root / "01-PROJETOS" / name
        folder.mkdir(parents=True)
        extra = f'diretorio: "{repo}"\n' if name == "Alfa" else ""
        (folder / f"{name}.md").write_text(
            f"---\ntipo: projeto\nstatus: ativo\n{extra}---\n\n# 🎯 {name}\n\n> [!abstract] Projeto {name}.\n\n## ✅ Próximas ações\n\n- [ ] Revisar o webhook da Guru\n",
            encoding="utf-8",
        )
    beta = root / "01-PROJETOS" / "Beta" / "decisoes"
    beta.mkdir()
    (beta / "Webhook da Guru passa por fila com chave de idempotência.md").write_text(
        record("decisao", "Beta", "Webhook da Guru passa por fila com chave de idempotência",
               "Todo webhook da Guru entra numa fila e é processado uma vez só pela chave de idempotência.", status="aceita"),
        encoding="utf-8",
    )  # fmt: skip
    (beta / "Webhook da Guru era processado direto.md").write_text(
        record("decisao", "Beta", "Webhook da Guru era processado direto", "Webhook da Guru processado direto, sem fila.", "2026-09-01", "substituida"),
        encoding="utf-8",
    )
    for i, (project, title, resumo) in enumerate(FILLER):
        folder = root / "01-PROJETOS" / project / "aprendizados"
        folder.mkdir(exist_ok=True)
        (folder / f"{title}.md").write_text(record("aprendizado", project, title, resumo, f"2026-10-{1 + i % 28:02d}"), encoding="utf-8")
    alfa = root / "01-PROJETOS" / "Alfa" / "decisoes"
    alfa.mkdir()
    (alfa / "Painel do Alfa mostra a fila de webhooks.md").write_text(
        record("decisao", "Alfa", "Painel do Alfa mostra a fila de webhooks", "O painel lista os webhooks da Guru na fila com o estado de cada um.", status="aceita"),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def index(settings, brain_root) -> BrainIndex:
    return BrainIndex(Vault(brain_root), settings.home / "brain.db", encode=fake_encode)


# --- vetores e busca por significado -------------------------------------------------------


def test_vectors_follow_the_notes(index, brain_root):
    index.refresh(max_age=0)
    total = index.vector_status()["notes"]
    assert index.sync_vectors() == total and index.vector_status() == {"notes": total, "vectors": total}
    assert index.sync_vectors() == 0
    note = brain_root / "01-PROJETOS" / "Gama" / "aprendizados" / "Fotos do catálogo saem em fundo branco.md"
    note.write_text(note.read_text(encoding="utf-8") + "\nMais um parágrafo.\n", encoding="utf-8")
    project = brain_root / "01-PROJETOS" / "Gama" / "Gama.md"
    project.write_text(project.read_text(encoding="utf-8") + "\n- [ ] Outra tarefa\n", encoding="utf-8")
    import os

    for path in (note, project):
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    index.refresh(max_age=0)
    assert index.vector_status()["vectors"] == total - 1
    assert index.sync_vectors() == 1  # a nota de projeto mudou, mas só registro ganha vetor


def test_hybrid_precedents_skip_own_project_and_replaced(index):
    index.sync_vectors()
    found = index.precedents("Alfa", "webhook da Guru na fila com idempotência", 5, free_text=True)
    titles = [f["title"] for f in found]
    assert titles[0] == "Webhook da Guru passa por fila com chave de idempotência"
    assert "significado" in found[0]["via"] and "palavra" in found[0]["via"] and found[0]["z"] >= 2
    assert "Painel do Alfa mostra a fila de webhooks" not in titles  # o próprio projeto não é precedente
    assert "Webhook da Guru era processado direto" not in titles  # substituída nunca volta
    # Sem consulta escrita: o momento do Alfa vem dos vetores guardados dos registros dele.
    moment = index.precedents("Alfa", index.project_context("Alfa"), 5)
    assert moment and moment[0]["title"] == "Webhook da Guru passa por fila com chave de idempotência"


def test_conflicts_same_project_and_word_fallback(index, settings, brain_root):
    index.sync_vectors()
    found = index.conflicts("webhook da Guru entra numa fila com idempotência", "Beta")
    assert found["via"] == "significado"
    assert [s["title"] for s in found["same"]] == ["Webhook da Guru passa por fila com chave de idempotência"]
    assert all(o["projeto"] != "Beta" for o in found["other"])
    words_only = BrainIndex(Vault(brain_root), settings.home / "brain.db", encode=None).conflicts("fila idempotência webhook", "Beta")
    assert words_only["via"] == "palavra" and words_only["same"][0]["title"].startswith("Webhook da Guru passa por fila")


def test_neighbor_projects_groups_by_project(index):
    index.sync_vectors()
    groups = index.neighbor_projects("01-PROJETOS/Alfa/decisoes/Painel do Alfa mostra a fila de webhooks.md", z_min=2.0)
    assert groups and groups[0]["project"] == "Beta"
    assert groups[0]["matches"][0]["title"] == "Webhook da Guru passa por fila com chave de idempotência"


def test_embedder_loads_on_demand_and_unloads(tmp_path):
    class Model:
        def encode(self, texts):
            return np.ones((len(texts), 4), dtype=np.float32)

    embedder = Embedder(tmp_path, idle_unload=0, loader=lambda path: Model())
    assert embedder.status()["state"] == "ausente" and embedder.encode(["x"], 0.1) is None
    embedder.local.mkdir(parents=True)
    (embedder.local / "model.safetensors").write_bytes(b"0")
    assert embedder.status()["state"] == "parado"
    vectors = embedder.encode(["um", "dois"], 5)
    assert vectors.shape == (2, 4) and abs(float(np.linalg.norm(vectors[0])) - 1) < 1e-5
    assert embedder.status()["state"] == "pronto" and embedder.loads == 1
    embedder.tick()
    assert not embedder.loaded and embedder.status()["state"] == "parado"


# --- sugestões entre projetos ----------------------------------------------------------------------


def fake_registrar(brain_root: Path, calls: list):
    def run(args: list[str], env: dict[str, str]) -> str:
        calls.append(args)
        opts = dict(zip(args[1::2], args[2::2]))
        folder = brain_root / "01-PROJETOS" / opts["--projeto"] / "decisoes"
        folder.mkdir(exist_ok=True)
        (folder / f"{opts['--nota']}.md").write_text(
            record("decisao", opts["--projeto"], opts["--nota"], opts["--resumo"], status=opts["--status"])
            + "\n## 🌍 Contexto\n\n<!-- preencher -->\n\n## ✅ Escolha e porquê\n\n<!-- preencher -->\n",
            encoding="utf-8",
        )
        return "✅ registrado · nota nova"

    return run


def test_suggestion_flow_from_new_record_to_accepted_decision(settings, index, brain_root):
    prompts, calls = [], []

    def judge(prompt: str) -> dict:
        prompts.append(prompt)
        return {"projetos": [{"projeto": "Beta", "aplica": True, "motivo": "a fila do Beta não reprocessa o reenvio",
                              "titulo": "Beta: reenvio da Guru vira o mesmo evento?", "resumo": "Reenvio da Guru usa o id do evento, como no Alfa."}]}  # fmt: skip

    events = []
    sug = Suggestions(settings.home, index, index.vault, judge=judge, registrar=fake_registrar(brain_root, calls), publish=events.append)
    first = sug.scan(wait=0)
    assert first["baseline"] > 0 and not prompts  # o vault que já existe não é julgado
    new = brain_root / "01-PROJETOS" / "Alfa" / "aprendizados"
    new.mkdir()
    (new / "Reenvio do webhook da Guru repete o evento.md").write_text(
        record("aprendizado", "Alfa", "Reenvio do webhook da Guru repete o evento", "O webhook da Guru reenvia o evento e a fila com idempotência evita venda em dobro.", "2026-11-08"),
        encoding="utf-8",
    )
    (new / "Café do escritório acabou.md").write_text(record("aprendizado", "Alfa", "Café do escritório acabou", "Comprar café torrado.", "2026-11-08"), encoding="utf-8")
    report = sug.scan(wait=0)
    assert report["new"] == 2 and report["judged"] == 1 and len(prompts) == 1  # o do café não tem candidato: não gasta o juiz
    assert "Reenvio do webhook da Guru repete o evento" in prompts[0] and "### Beta" in prompts[0]
    pending = sug.list("Beta")
    assert len(pending) == 1 and pending[0]["title"] == "Beta reenvio da Guru vira o mesmo evento"
    assert events[-1] == {"type": "suggestions", "created": [pending[0]["id"]]}
    assert sug.scan(wait=0)["new"] == 0  # os dois já foram vistos

    done = sug.accept(pending[0]["id"], title="Reenvio da Guru no Beta usa o id do evento")
    opts = dict(zip(calls[0][1::2], calls[0][2::2]))
    assert calls[0][0] == "registrar" and opts["--projeto"] == "Beta" and opts["--status"] == "aceita"
    assert opts["--liga"] == "Reenvio do webhook da Guru repete o evento" and opts["--tipo"] == "decisao"
    assert done["status"] == "aceita" and done["note"].endswith("Reenvio da Guru no Beta usa o id do evento.md")
    text = (brain_root / done["note"]).read_text(encoding="utf-8")
    assert "Veio de uma sugestão de precedente da MÊTIS" in text and "a fila do Beta não reprocessa o reenvio" in text
    assert "Aceita pelo Pedro na MÊTIS" in text
    with pytest.raises(SuggestionError):
        sug.accept(pending[0]["id"])
    assert sug.for_note(done["note"])[0]["id"] == pending[0]["id"]


def test_suggestions_respect_daily_cap_and_reject(settings, index, brain_root, monkeypatch):
    judged = []
    sug = Suggestions(settings.home, index, index.vault, judge=lambda p: judged.append(p) or {"projetos": [{"projeto": "Beta", "aplica": True, "motivo": "m", "titulo": "Fila no Beta", "resumo": "r"}]})
    sug.scan(wait=0)
    monkeypatch.setattr(suggestions_mod, "DAILY_MAX", 0)
    folder = brain_root / "01-PROJETOS" / "Alfa" / "aprendizados"
    folder.mkdir()
    (folder / "Fila do webhook da Guru precisa de idempotência.md").write_text(
        record("aprendizado", "Alfa", "Fila do webhook da Guru precisa de idempotência", "Webhook da Guru na fila com chave de idempotência.", "2026-11-08"), encoding="utf-8"
    )
    report = sug.scan(wait=0)
    assert report["candidates"] == 1 and not judged  # teto do dia: fica para amanhã, sem marcar como visto
    monkeypatch.setattr(suggestions_mod, "DAILY_MAX", 5)
    assert sug.scan(wait=0)["judged"] == 1
    item = sug.list("Beta")[0]
    assert sug.reject(item["id"])["status"] == "recusada" and sug.list("Beta") == []


def test_clean_title_drops_characters_the_vault_forbids():
    assert clean_title(' Beta: usa "fila" / [idempotência]? ') == "Beta usa fila idempotência"


# --- rotas, central de MCP e mini-mapa --------------------------------------------------------------------


def test_routes_session_context_minimap_and_conflicts(settings, accounts, brain_root, repo, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", lambda kind, s: ["/bin/echo", "--settings", "{}"])
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False, embedder=FakeEmbedder())
    with TestClient(app) as client:
        app.state.brain.sync_vectors()
        status = client.get("/brain/semantica", headers=AUTH).json()
        assert status["model"]["state"] == "pronto" and status["index"]["vectors"] == status["index"]["notes"]
        conflicts = client.get("/brain/conflitos", params={"q": "fila de webhook com idempotência", "project": "Beta"}, headers=AUTH).json()
        assert conflicts["same"][0]["title"].startswith("Webhook da Guru passa por fila")
        assert client.post("/brain/embed", json={"texts": ["fila"]}, headers=AUTH).json()["vectors"][0].__len__() == FAKE_DIM

        sid = client.post("/sessions", json={"kind": "claude", "cwd": str(repo)}, headers=AUTH).json()["id"]
        sug = app.state.suggestions
        with sug._connect() as con:
            con.execute(
                "insert into suggestions(created, source_path, source_title, source_tipo, source_project, target_project, title, resumo, motivo, matches, z) "
                "values (1, 'x.md', 'Origem', 'aprendizado', 'Beta', 'Alfa', 'Alfa usa fila', 'r', 'porque sim', '[]', 3.2)"
            )
        text = client.get("/brain/session-context", params={"session": sid}, headers=AUTH).text
        assert "precedentes do Brain para [[Alfa]]" in text and "Webhook da Guru passa por fila" in text
        assert "Sugestões de precedente esperando o Pedro" in text and "Alfa usa fila" in text and "brain_conflitos" in text
        minimap = client.get(f"/brain/sessao/{sid}", headers=AUTH).json()
        assert minimap["project"] == "Alfa" and any(n["via"] == ["início"] for n in minimap["nodes"])

        token = app.state.hub.register(sid)
        reply = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": "brain_conflitos", "arguments": {"decisao": "painel mostra a fila de webhooks"}}},
                            headers={"Authorization": f"Bearer {token}"}).json()  # fmt: skip
        assert "Decisões parecidas em Alfa" in reply["result"]["content"][0]["text"] and "Painel do Alfa" in reply["result"]["content"][0]["text"]
        listing = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers={"Authorization": f"Bearer {token}"}).json()
        assert {"brain_conflitos", "brain_sugestoes"} <= {t["name"] for t in listing["result"]["tools"]}
        nodes = client.get(f"/brain/sessao/{sid}", headers=AUTH).json()["nodes"]
        assert any("conflito" in n["via"] for n in nodes)

        pending = client.get("/brain/sugestoes", params={"project": "Alfa"}, headers=AUTH).json()
        assert client.post(f"/brain/sugestoes/{pending[0]['id']}/recusar", headers=AUTH).json()["status"] == "recusada"
        assert client.post(f"/brain/sugestoes/{pending[0]['id']}/recusar", headers=AUTH).status_code == 400
        assert client.get(f"/sessions/{sid}/contexto", headers=AUTH).json()["available"] is False
        client.delete(f"/sessions/{sid}", headers=AUTH)


# --- fora da MÊTIS: MCP por stdio e hook de início ------------------------------------------------------


def test_stdio_server_outside_and_inside_metis(settings, brain_root, repo, monkeypatch):
    BrainIndex(Vault(brain_root), settings.home / "brain.db", encode=fake_encode).sync_vectors()
    monkeypatch.delenv("HARNESS_SESSION_ID", raising=False)
    server = StdioServer(settings, cwd=str(repo / "src"))
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "brain_precedentes", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "brain_ler", "arguments": {"titulo": "Webhook da Guru passa por fila com chave de idempotência"}}},
    ]
    out = io.StringIO()
    server.serve(io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n"), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3, 4]  # a notificação não tem resposta
    assert replies[0]["result"]["serverInfo"]["name"] == "metis-brain"
    assert len(replies[1]["result"]["tools"]) == 5
    assert "Webhook da Guru passa por fila" in replies[2]["result"]["content"][0]["text"]  # MÊTIS fechada: vetores guardados
    assert replies[3]["result"]["content"][0]["text"].startswith("# Webhook da Guru passa por fila")
    monkeypatch.setenv("HARNESS_SESSION_ID", "h1")
    out = io.StringIO()
    server.serve(io.StringIO(json.dumps(lines[2]) + "\n"), out)
    assert json.loads(out.getvalue())["result"]["tools"] == []


def test_session_hook_outside_metis(settings, brain_root, repo, monkeypatch):
    BrainIndex(Vault(brain_root), settings.home / "brain.db", encode=fake_encode).sync_vectors()
    monkeypatch.delenv("HARNESS_SESSION_ID", raising=False)
    text = session_hook(settings, {"cwd": str(repo), "session_id": "x", "source": "startup"})
    assert "precedentes do Brain para [[Alfa]]" in text and "metis-brain" in text
    assert session_hook(settings, {"cwd": str(settings.home)}) == ""
    monkeypatch.setenv("HARNESS_SESSION_ID", "h1")
    assert session_hook(settings, {"cwd": str(repo)}) == ""


# --- janela de contexto ------------------------------------------------------------------------------------


def test_context_breakdown_counts_only_after_the_last_compaction(tmp_path):
    lines = [
        {"type": "user", "message": {"role": "user", "content": "x" * 36000}, "cwd": "/repo"},
        {"type": "system", "subtype": "compact_boundary"},
        {"type": "user", "isCompactSummary": True, "message": {"content": "resumo " * 100}},
        {"type": "attachment", "attachment": {"type": "hook_additional_context"}, "rendered": [{"type": "text", "text": "b" * 3600}]},
        {"type": "attachment", "attachment": {"type": "hook_success"}},
        {"type": "user", "message": {"content": "arruma o webhook"}, "cwd": "/repo"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Vou ler."},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/repo/src/app.py"}},
        ], "usage": {"input_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 9000}}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "y" * 7200}]}},
        {"type": "api-request-blob", "message": {"content": "z" * 99999}},
    ]  # fmt: skip
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    result = context_breakdown(str(path), {"size": 200000})
    cats = {c["key"]: c["tokens"] for c in result["categories"]}
    assert result["used"] == 10010 and result["size"] == 200000 and result["compacted"]
    assert cats["leituras"] > 1900 and cats["injetado"] == 1000 and cats["conversa"] < 10  # os 36 mil caracteres antes da compactação não contam
    assert result["top"][0]["label"] == "📄 src/app.py" and result["top"][0]["times"] == 1
    assert cats["sistema"] == 10010 - sum(v for k, v in cats.items() if k != "sistema")


# --- eventos vindos de threads ---------------------------------------------------------------------------------


def test_event_bus_accepts_events_from_threads():
    async def main() -> dict:
        bus = EventBus()
        queue = bus.subscribe()
        thread = threading.Thread(target=bus.publish, args=({"type": "brain.session"},))
        thread.start()
        thread.join()
        return await asyncio.wait_for(queue.get(), 2)

    assert asyncio.run(main()) == {"type": "brain.session"}
