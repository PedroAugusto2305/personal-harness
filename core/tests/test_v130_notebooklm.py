"""v1.3.0: NotebookLM e respostas visuais no Estudo (o CLI do notebooklm-py, as ferramentas
caderno_* e estudo_imagem da central, o agente de estudo conectado e o modo de estudo visual)."""

from __future__ import annotations

import json
import shutil
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.mcp_hub import Context, ToolError
from harness_core.notebooklm import MIN_VERSION, NotebookError, NotebookLM, NotLoggedIn, notebook_url, parse_version
from harness_core.prefs import Prefs, PrefsError
from harness_core.study_images import StudyImages
from harness_core.study_map import SESSION_TYPES, VISUAL, notebook_rule, session_rules

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
NB = "4f2a9c1e-aaaa-bbbb-cccc-1234567890ab"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

NOTEBOOKS = {
    "notebooks": [
        {"id": "old-1", "title": "Antigo", "is_owner": True, "created_at": "2026-01-01T00:00:00", "last_viewed_at": "2026-02-01T00:00:00"},
        {"id": NB, "title": "RAG e embeddings", "is_owner": True, "role": "owner", "created_at": "2026-10-01T00:00:00", "last_viewed_at": "2026-11-10T00:00:00"},
    ],
    "count": 2,
}
SOURCES = {"notebook_id": NB, "sources": [{"id": "src-1", "title": "Artigo RAG", "type": "pdf", "url": None, "status": "ready"}, {"id": "src-2", "title": "Vídeo", "type": "youtube", "url": "https://youtu.be/x"}], "count": 2}


class FakeCli:
    """O `notebooklm` de mentira: responde como o 0.8.6 com --json."""

    def __init__(self, version: str = "0.8.6", logged: bool = True) -> None:
        self.version = version
        self.logged = logged
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float) -> tuple[int, str, str]:
        args = argv[1:]
        self.calls.append(args)
        if args == ["--version"]:
            return 0, f"NotebookLM CLI, version {self.version} (956400aa)\n", ""
        if args[:2] == ["auth", "check"]:
            if self.logged:
                return 0, json.dumps({"status": "ok", "checks": {"token_fetch": True}}), ""
            return 1, json.dumps({"status": "error", "checks": {"token_fetch": False}, "details": {"error": "Authentication expired. Run 'notebooklm login'"}}), ""
        if not self.logged:
            return 1, json.dumps({"error": True, "code": "AUTH_ERROR", "message": "Authentication expired or invalid"}), ""
        if args[0] == "list":
            return 0, json.dumps(NOTEBOOKS), ""
        if args[:2] == ["source", "list"]:
            return 0, json.dumps(SOURCES), ""
        if args[0] == "summary":
            return 0, json.dumps({"notebook_id": NB, "summary": "Um caderno sobre RAG.", "suggested_topics": ["O que é chunking?"]}), ""
        if args[0] == "ask":
            question = args[args.index("--") + 1]
            refs = [
                {"source_id": "src-1", "citation_number": 1, "cited_text": "RAG busca  trechos\nantes de gerar."},
                {"source_id": "src-1", "citation_number": 1, "cited_text": "repetido"},
                {"source_id": "src-2", "citation_number": 2, "cited_text": "embeddings"},
            ]
            return 0, json.dumps({"answer": f"Resposta para {question} [1][2]", "conversation_id": "conv-1", "references": refs}), ""
        if args[:2] == ["source", "fulltext"]:
            return 0, "aviso qualquer\n" + json.dumps({"source_id": args[2], "title": "Artigo RAG", "content": "a" * 25_000 + "FIM"}), ""
        return 2, "", f"comando inesperado: {args}"


def make(cli: FakeCli | None = None, installed: bool = True) -> tuple[NotebookLM, FakeCli]:
    cli = cli or FakeCli()
    return NotebookLM(run=cli, which=lambda: "/fake/notebooklm" if installed else None), cli


# --- o CLI ----------------------------------------------------------------------------------


def test_status_installed_version_and_login():
    nlm, cli = make()
    status = nlm.status()
    assert status["instalado"] and status["versao"] == "0.8.6" and status["versao_ok"] and status["logado"] and status["erro"] is None
    calls = len(cli.calls)
    nlm.status()
    assert len(cli.calls) == calls  # guardado: o auth check vai à rede
    nlm.status(fresh=True)
    assert len(cli.calls) > calls

    missing, _ = make(installed=False)
    status = missing.status()
    assert not status["instalado"] and "uv tool install" in status["erro"]

    old, old_cli = make(FakeCli(version="0.7.3"))
    status = old.status()
    assert status["versao"] == "0.7.3" and not status["versao_ok"] and not status["logado"] and "uv tool upgrade" in status["erro"]
    assert not any(c[:2] == ["auth", "check"] for c in old_cli.calls)  # versão velha nem testa o login

    out, _ = make(FakeCli(logged=False))
    status = out.status()
    assert status["versao_ok"] and not status["logado"] and "Entrar" in status["erro"]
    assert parse_version("NotebookLM CLI, version 0.10.2 (x)") == (0, 10, 2) and MIN_VERSION == (0, 8, 0)


def test_notebooks_sources_summary_and_cache():
    nlm, cli = make()
    books = nlm.notebooks()
    assert [b["id"] for b in books] == [NB, "old-1"]  # o visto por último primeiro
    assert books[0]["titulo"] == "RAG e embeddings" and books[0]["url"] == f"https://notebook.google.com/notebook/{NB}"
    nlm.notebooks()
    assert sum(1 for c in cli.calls if c[0] == "list") == 1
    nlm.notebooks(fresh=True)
    assert sum(1 for c in cli.calls if c[0] == "list") == 2
    sources = nlm.sources(NB)
    assert sources[1] == {"id": "src-2", "titulo": "Vídeo", "tipo": "youtube", "url": "https://youtu.be/x", "status": None}
    assert ["source", "list", "-n", NB, "--json"] in cli.calls
    assert nlm.summary(NB) == {"resumo": "Um caderno sobre RAG.", "topicos": ["O que é chunking?"]}
    with pytest.raises(NotebookError):
        nlm.sources("../etc")
    assert notebook_url(None) == "https://notebook.google.com"


def test_ask_maps_citations_and_never_starts_a_new_conversation():
    nlm, cli = make()
    answer = nlm.ask(NB, "  -o que   é RAG? ", ["src-1"])
    ask = next(c for c in cli.calls if c[0] == "ask")
    assert ask[:4] == ["ask", "-n", NB, "--json"] and ["-s", "src-1"] == ask[4:6] and ask[-2:] == ["--", "-o que é RAG?"]
    assert "--new" not in ask  # o --new apagaria a conversa do caderno no servidor
    assert answer["resposta"].startswith("Resposta para -o que é RAG?") and answer["conversa"] == "conv-1"
    assert answer["citacoes"] == [
        {"n": 1, "fonte_id": "src-1", "fonte": "Artigo RAG", "trecho": "RAG busca trechos antes de gerar."},
        {"n": 2, "fonte_id": "src-2", "fonte": "Vídeo", "trecho": "embeddings"},
    ]
    with pytest.raises(NotebookError):
        nlm.ask(NB, "   ")


def test_fulltext_in_pieces_and_json_after_noise():
    nlm, cli = make()
    first = nlm.fulltext(NB, "src-1")
    assert first["titulo"] == "Artigo RAG" and first["inicio"] == 0 and first["fim"] == 20_000 and first["total"] == 25_003
    rest = nlm.fulltext(NB, "src-1", start=first["fim"])
    assert rest["texto"].endswith("FIM") and rest["fim"] == rest["total"]
    assert sum(1 for c in cli.calls if c[:2] == ["source", "fulltext"]) == 1  # o texto inteiro fica guardado
    assert ["source", "fulltext", "src-1", "-n", NB, "--json", "-f", "markdown"] in cli.calls


def test_expired_login_raises_and_forgets_status():
    cli = FakeCli()
    nlm, _ = make(cli)
    assert nlm.status()["logado"]
    cli.logged = False
    with pytest.raises(NotLoggedIn):
        nlm.notebooks()
    assert not nlm.status()["logado"]  # o status guardado caiu junto com o erro


def test_prefs_notebook_choice(tmp_path):
    prefs = Prefs(tmp_path)
    assert prefs.get()["estudo_caderno"] == {"id": "", "titulo": ""}
    assert prefs.update({"estudo_caderno": {"id": NB, "titulo": "  RAG   e embeddings "}})["estudo_caderno"] == {"id": NB, "titulo": "RAG e embeddings"}
    assert prefs.update({"estudo_caderno": {"id": "", "titulo": "sobra"}})["estudo_caderno"] == {"id": "", "titulo": ""}
    with pytest.raises(PrefsError):
        prefs.update({"estudo_caderno": {"id": "a/b"}})
    with pytest.raises(PrefsError):
        prefs.update({"estudo_caderno": "x"})


# --- imagens de estudo ----------------------------------------------------------------------


def fake_codex(tmp_path: Path, mode: str = "gpt"):
    codex_home = tmp_path / "codex-home"

    def run(args, **_kw):
        folder = Path(args[args.index("-C") + 1])
        reply = Path(args[args.index("-o") + 1])
        if mode == "gpt":
            generated = codex_home / "generated_images" / "sessao" / "ig_1.png"
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_bytes(PNG)
            shutil.copyfile(generated, folder / "imagem.png")
            reply.write_text("Um diagrama de RAG.", encoding="utf-8")
        elif mode == "code":
            (folder / "imagem.png").write_bytes(PNG + b"code")
        return types.SimpleNamespace(returncode=0, stderr="")

    return codex_home, run


def test_study_image_comes_from_the_gpt_generator(tmp_path):
    codex_home, run = fake_codex(tmp_path)
    claimed: set[str] = set()
    images = StudyImages(tmp_path / "home", lambda: ("/fake/codex", {"CODEX_HOME": str(codex_home)}), claimed, run=run)
    assert images.available()
    job = images.wait(images.start("Pipeline de RAG com rótulos").id, 10).id
    done = images.jobs[job]
    assert done.status == "done", done.erro
    path = Path(done.caminho)
    assert path.parent == tmp_path / "home" / "estudo" / "imagens" and path.read_bytes() == PNG and "pipeline-de-rag" in path.name
    assert done.descricao == "Um diagrama de RAG." and claimed  # a imagem fica marcada como usada (dividida com as sprites)
    assert not (tmp_path / "home" / "estudo" / "imagens" / ".trabalho" / job).exists()
    with pytest.raises(ValueError):
        images.start("   ")


def test_study_image_drawn_by_code_is_refused(tmp_path):
    codex_home, run = fake_codex(tmp_path, mode="code")
    images = StudyImages(tmp_path / "home", lambda: ("/fake/codex", {"CODEX_HOME": str(codex_home)}), run=run)
    job = images.wait(images.start("um gato").id, 10)
    assert job.status == "error" and "gerador de imagens do GPT" in job.erro
    no_codex = StudyImages(tmp_path / "home", lambda: (None, {}))
    assert not no_codex.available()


# --- núcleo: rotas, agente de estudo conectado e central -----------------------------------


def fake_argv(kind, _settings):
    return {"claude": ["/bin/cat"], "codex": ["/bin/cat"], "shell": ["/bin/cat"]}[kind]


@pytest.fixture
def core(settings, accounts, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", fake_argv)
    nlm, cli = make()
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False, notebooklm=nlm)
    with TestClient(app) as client:
        yield client, app, cli


def test_routes_status_notebooks_choice_and_ask(core):
    client, app, cli = core
    status = client.get("/estudo/notebooklm", headers=AUTH).json()
    assert status["logado"] and status["caderno"] == {"id": "", "titulo": "", "url": "https://notebook.google.com"}
    books = client.get("/estudo/notebooklm/cadernos", headers=AUTH).json()
    assert books[0]["id"] == NB
    one = client.get(f"/estudo/notebooklm/cadernos/{NB}", headers=AUTH).json()
    assert one["resumo"] == "Um caderno sobre RAG." and len(one["fontes"]) == 2 and one["url"].endswith(NB)
    assert client.post("/estudo/notebooklm/perguntar", json={"pergunta": "oi"}, headers=AUTH).status_code == 400  # sem caderno
    events = []
    app.state.manager.events.publish = events.append
    chosen = client.put("/estudo/notebooklm/caderno", json={"id": NB, "titulo": "RAG e embeddings"}, headers=AUTH).json()
    assert chosen == {"id": NB, "titulo": "RAG e embeddings", "url": f"https://notebook.google.com/notebook/{NB}"}
    assert events and events[-1]["type"] == "notebooklm.caderno"
    assert client.get("/estudo/notebooklm", headers=AUTH).json()["caderno"]["id"] == NB
    answer = client.post("/estudo/notebooklm/perguntar", json={"pergunta": "O que é RAG?"}, headers=AUTH).json()
    assert answer["citacoes"][0]["fonte"] == "Artigo RAG"
    assert client.put("/estudo/notebooklm/caderno", json={"id": "a b"}, headers=AUTH).status_code == 400
    cli.logged = False
    expired = client.get("/estudo/notebooklm/cadernos?fresh=true", headers=AUTH)
    assert expired.status_code == 409 and "Entrar" in expired.json()["detail"]


def connect_mentor(client) -> dict:
    agent = client.post("/agents", json={"name": "Mentor de Estudos", "cli": "claude", "prompt": "Você é o mentor de estudos do Pedro."}, headers=AUTH).json()
    assert client.put("/estudo/agente", json={"id": agent["id"]}, headers=AUTH).status_code == 200
    return agent


def test_study_tab_starts_without_agent_and_connects_one(core):
    client, app, _cli = core
    assert client.get("/estudo", headers=AUTH).json()["agente"] == ""
    refused = client.post("/estudo/sessao", json={"tipo": "conversa"}, headers=AUTH)
    assert refused.status_code == 400 and "aba Agentes" in refused.json()["detail"]
    assert client.put("/estudo/agente", json={"id": "nao-existe"}, headers=AUTH).status_code == 404
    other = client.post("/agents", json={"name": "Script", "cli": "outra", "command": "/bin/cat"}, headers=AUTH).json()
    assert client.put("/estudo/agente", json={"id": other["id"]}, headers=AUTH).status_code == 400  # só Claude ou Codex
    events = []
    app.state.manager.events.publish = events.append
    agent = connect_mentor(client)
    assert client.get("/estudo", headers=AUTH).json()["agente"] == agent["id"] and events[-1] == {"type": "estudo.agente", "agente": agent["id"]}
    assert client.put("/estudo/agente", json={"id": ""}, headers=AUTH).json() == {"agente": ""}  # desconectar
    assert client.post("/estudo/sessao", json={"tipo": "conversa"}, headers=AUTH).status_code == 400
    again = connect_mentor(client)
    client.delete(f"/agents/{again['id']}", headers=AUTH)
    assert client.get("/estudo", headers=AUTH).json()["agente"] == ""  # agente apagado conta como nenhum


def test_study_session_uses_connected_agent_visual_mode_and_notebook(core):
    client, app, _cli = core
    assert "conversa" in SESSION_TYPES
    agent = connect_mentor(client)
    plain = client.post("/estudo/sessao", json={"tipo": "conversa"}, headers=AUTH)
    assert plain.status_code == 201, plain.text
    session = app.state.manager.get(plain.json()["id"])
    argv = session.pty.argv
    prompt, system = argv[1], argv[argv.index("--append-system-prompt") + 1]
    assert session.agent == agent["id"] and session.tag == "estudo" and plain.json()["title"] == "Estudo · conversa"
    # O pedido fica curto (aparece na conversa como mensagem do Pedro); o jeito de explicar vai no papel de sistema.
    assert len(prompt) < 300 and "pergunte o que vamos estudar" in prompt and "mermaid" not in prompt
    assert system.startswith("Você é o mentor de estudos do Pedro.") and VISUAL in system and "estudo_registrar" in system and "NotebookLM deste estudo" not in system
    client.put("/estudo/notebooklm/caderno", json={"id": NB, "titulo": "RAG e embeddings"}, headers=AUTH)
    grounded = client.post("/estudo/sessao", json={"tipo": "conversa"}, headers=AUTH).json()
    argv = app.state.manager.get(grounded["id"]).pty.argv
    prompt, system = argv[1], argv[argv.index("--append-system-prompt") + 1]
    assert "panorama do caderno «RAG e embeddings»" in prompt
    assert NB in system and "caderno_perguntar" in system
    assert notebook_rule(None) == "" and NB in notebook_rule({"id": NB, "titulo": "x"})
    assert session_rules(None).count("estudo_registrar") == 1 and NB in session_rules({"id": NB, "titulo": "x"})


def test_central_gives_notebook_and_image_tools_only_to_study_sessions(core, tmp_path):
    client, app, cli = core
    hub = app.state.hub
    plain = Context(session="s1", who="Claude", cwd=None, allowed=None)
    names = {t.name for t in hub.tools_for(plain)}
    assert not names & {"cadernos", "caderno_fontes", "caderno_perguntar", "caderno_fonte", "estudo_imagem"}
    study = Context(session="s2", who="Sócrates", cwd=None, allowed=None, estudo=True)
    codex_home, run = fake_codex(tmp_path)
    hub.study_images = StudyImages(tmp_path / "home", lambda: ("/fake/codex", {"CODEX_HOME": str(codex_home)}), run=run)
    tool = {t.name: t for t in hub.tools_for(study)}
    assert {"cadernos", "caderno_fontes", "caderno_perguntar", "caderno_fonte", "estudo_imagem"} <= set(tool)
    assert all(not tool[n].write for n in ("cadernos", "caderno_perguntar", "estudo_imagem"))  # livres: sem aprovação
    with pytest.raises(ToolError):
        tool["caderno_perguntar"].run({"pergunta": "oi"}, study)  # nenhum caderno escolhido ainda
    assert NB in tool["cadernos"].run({}, study) and "o caderno do estudo" not in tool["cadernos"].run({}, study)
    client.put("/estudo/notebooklm/caderno", json={"id": NB, "titulo": "RAG e embeddings"}, headers=AUTH)
    assert "← o caderno do estudo" in tool["cadernos"].run({}, study)
    assert "Artigo RAG · id src-1 · pdf" in tool["caderno_fontes"].run({}, study)
    text = tool["caderno_perguntar"].run({"pergunta": "O que é RAG?"}, study)
    assert "caderno «RAG e embeddings»" in text and '[1] Artigo RAG: "RAG busca trechos antes de gerar."' in text
    piece = tool["caderno_fonte"].run({"fonte": "src-1"}, study)
    assert "caracteres 0 a 20000 de 25003" in piece and "inicio=20000" in piece
    image = tool["estudo_imagem"].run({"pedido": "o pipeline de RAG"}, study)
    assert image.startswith("Imagem pronta: ") and "![legenda curta](" in image and "Um diagrama de RAG." in image
    with pytest.raises(KeyError):
        tool["estudo_imagem"].run({"id": "naoexiste"}, study)
    # A sessão de estudo de verdade é reconhecida pelo núcleo (tag estudo ou o agente conectado).
    connect_mentor(client)
    created = client.post("/estudo/sessao", json={"tipo": "conversa"}, headers=AUTH).json()
    ctx = hub.context(hub.register(created["id"]))
    assert ctx.estudo and ctx.who == "Mentor de Estudos"


def test_login_opens_chrome_when_installed_and_reports_the_end():
    class Proc:
        def __init__(self, argv, **_kw):
            self.argv = argv
            self.returncode = 0

        def communicate(self, timeout=None):
            return "Authentication saved.", None

        def poll(self):
            return self.returncode

    spawned: list[list[str]] = []
    changes: list[dict] = []

    def spawn(argv, **kw):
        spawned.append(argv)
        return Proc(argv, **kw)

    cli = FakeCli()
    nlm = NotebookLM(run=cli, which=lambda: "/fake/notebooklm", on_change=changes.append, spawn=spawn, browser=lambda: "chrome")
    state = nlm.login()
    assert spawned[0] == ["/fake/notebooklm", "login", "--browser", "chrome"] and state["navegador"] == "chrome"
    for _ in range(100):
        if changes:
            break
        import time

        time.sleep(0.02)
    assert changes and changes[0]["logado"] and changes[0]["entrando"]["ok"] is True and not changes[0]["entrando"]["rodando"]
    plain = NotebookLM(run=cli, which=lambda: "/fake/notebooklm", spawn=spawn, browser=lambda: None)
    plain.login()
    assert spawned[1] == ["/fake/notebooklm", "login"]


def test_study_image_one_drawing_per_session_at_a_time(tmp_path):
    import threading

    gate = threading.Event()
    codex_home, run = fake_codex(tmp_path)

    def slow(args, **kw):
        gate.wait(5)
        return run(args, **kw)

    images = StudyImages(tmp_path / "home", lambda: ("/fake/codex", {"CODEX_HOME": str(codex_home)}), run=slow)
    first = images.start("um diagrama", owner="s1")
    again = images.start("o mesmo, com outras palavras", owner="s1")
    other = images.start("outra sessão", owner="s2")
    assert again.id == first.id and other.id != first.id
    assert images.wait(first.id, 0.05).status == "running"  # devolve na hora, sem esperar o GPT
    gate.set()
    assert images.wait(first.id, 5).status == "done"



def test_study_question_carries_the_agent_name(tmp_path):
    from harness_core.study_map import StudyMap
    from harness_core.vault import Vault

    root = tmp_path / "Brain"
    (root / "01-PROJETOS" / "AI Engineer 2027").mkdir(parents=True)
    (root / "01-PROJETOS" / "AI Engineer 2027" / "AI Engineer 2027.md").write_text("---\ntipo: projeto\n---\n# AI\n", encoding="utf-8")
    study = StudyMap(Vault(root), project=lambda: "AI Engineer 2027")
    done = study.add_question("Injeção de prompt", "Qual é a indireta?", ["A", "B"], who="Mentor de Estudos")
    assert "> [!pergunta] Pergunta de previsão · Mentor de Estudos" in (root / done["caminho"]).read_text(encoding="utf-8")
