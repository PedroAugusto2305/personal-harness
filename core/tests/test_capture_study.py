"""v0.7.1: captura rápida (ações diretas e concierge), Estudo com Pomodoro e agente por descrição."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from harness_core import app as app_mod
from harness_core import sessions as sessions_mod
from harness_core.agent_draft import DraftError, draft_agent
from harness_core.app import create_app
from harness_core.capture import interpret, split_when
from harness_core.keychain import MemoryVault
from harness_core.study import StudyLog
from harness_core.vault import Vault, add_to_section

from .conftest import TOKEN
from .test_connectors import FakeServices

AUTH = {"X-Harness-Token": TOKEN}
NOW = datetime(2026, 11, 8, 11, 30).astimezone()  # domingo
TEMPLATE = "---\ntipo: daily\ndata: {{date:YYYY-MM-DD}}\n---\n\n# 📅 {{date:YYYY-MM-DD}}\n\n## 📥 Capturas do dia\n\n- \n\n## 🛠️ Registro de trabalho\n\n- 10:00 · algo\n"


@pytest.fixture
def brain(settings) -> Path:
    root = settings.brain
    (root / "_templates").mkdir(parents=True)
    (root / "_templates" / "T-daily.md").write_text(TEMPLATE, encoding="utf-8")
    alfa = root / "01-PROJETOS" / "Alfa"
    alfa.mkdir(parents=True)
    (alfa / "Alfa.md").write_text("---\ntipo: projeto\n---\n\n## ✅ Próximas ações\n\n- [ ] Primeira\n", encoding="utf-8")
    return root


# --- interpretação -------------------------------------------------------------------------


def test_interpret_reminder_task_note_and_concierge():
    projects = ["Alfa", "Plataforma Funis"]
    r = interpret("me lembra de pagar o boleto sexta às 9h", projects, NOW)
    assert (r.kind, r.text, r.when.strftime("%d/%m %H:%M")) == ("lembrete", "pagar o boleto", "13/11 09:00")
    assert interpret("lembrete: ligar para a mãe amanhã 18h", projects, NOW).text == "ligar para a mãe"
    assert interpret("me lembra de pagar o boleto", projects, NOW).kind == "concierge"  # sem hora: o Hermes pergunta
    t = interpret("tarefa testar o webhook na Plataforma Funis", projects, NOW)
    assert (t.kind, t.text, t.project) == ("tarefa", "testar o webhook", "Plataforma Funis")
    assert interpret("anota tarefa comprar café", projects, NOW).project == ""
    assert interpret("anota ideia de post", projects, NOW).kind == "nota"
    assert interpret("cria no ClickUp uma tarefa para revisar a LP", projects, NOW).kind == "concierge"
    with pytest.raises(ValueError):
        interpret("   ", projects, NOW)


def test_split_when_never_eats_words_of_the_text():
    assert split_when("comprar boleto sexta 9h", NOW)[0] == "comprar boleto"
    assert split_when("dentista dia 13/11 às 10h", NOW)[0] == "dentista"
    assert split_when("sem hora nenhuma", NOW) is None


# --- nota do dia ------------------------------------------------------------------------------


def test_add_to_section_fills_placeholder_appends_and_creates():
    text = "# Dia\n\n## 📥 Capturas do dia\n\n- \n\n## 🛠️ Registro de trabalho\n\n- x\n"
    once = add_to_section(text, "📥 Capturas do dia", "- [ ] café")
    assert "- [ ] café\n\n## 🛠️" in once and "\n- \n" not in once
    twice = add_to_section(once, "📥 Capturas do dia", "- nota")
    assert "- [ ] café\n- nota\n\n## 🛠️" in twice
    created = add_to_section(twice, "📚 Estudo", "- 21:00 · 🍅 25 min", ("## 🛠️ Registro de trabalho",))
    assert created.index("## 📚 Estudo") < created.index("## 🛠️ Registro de trabalho")


def test_daily_note_is_created_from_the_vault_template(brain):
    vault = Vault(brain)
    path = vault.append_daily("2026-11-08", "📥 Capturas do dia", "- [ ] café", ("## 🛠️",))
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\ntipo: daily\ndata: 2026-11-08") and "# 📅 2026-11-08" in text
    assert "- [ ] café" in text and "- 10:00 · algo" in text


# --- estudo -------------------------------------------------------------------------------------


def test_study_block_goes_to_db_and_daily_note(settings, brain):
    log = StudyLog(settings.home, Vault(brain))
    block = log.add(25, "RAG com pgvector", ended=datetime(2026, 11, 9, 21, 30).astimezone())
    assert block["line"] == "- 21:05–21:30 · 🍅 25 min · RAG com pgvector" and block["note"] == "06-DIARIO/2026-11-09.md"
    text = (brain / "06-DIARIO" / "2026-11-09.md").read_text(encoding="utf-8")
    assert "## 📚 Estudo\n\n- 21:05–21:30 · 🍅 25 min · RAG com pgvector" in text


def test_study_summary_streak_floor_and_two_day_rule(settings, brain):
    log = StudyLog(settings.home, Vault(brain))
    base = datetime(2026, 11, 12, 21, 0).astimezone()  # quinta
    for back, minutes in ((3, 30), (2, 25), (1, 10)):  # seg 30, ter 25, qua 10 (abaixo do piso)
        log.add(minutes, ended=base - timedelta(days=back))
    s = log.summary(base)
    assert s["today"] == 0 and s["floor"] == 20 and s["week_total"] == 65
    assert s["streak"] == 0 and s["risk"]  # quarta abaixo do piso e quinta ainda sem estudo
    log.add(20, ended=base)
    s = log.summary(base)
    assert s["today"] == 20 and not s["risk"] and s["streak"] == 1


# --- agente por descrição ---------------------------------------------------------------------------


def test_draft_agent_parses_the_claude_answer(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "claude").write_text("#!/bin/sh\n", encoding="utf-8")
    (fake_bin / "claude").chmod(0o755)
    seen = {}

    def run(argv, env, cwd):
        seen["argv"] = argv
        answer = {"name": "Hermes", "description": "Concierge", "pain": "capturas soltas", "cli": "claude", "color": "#f0b", "prompt": "Você é o Hermes.", "sprite": "mensageiro"}
        return json.dumps({"type": "result", "result": "Aqui está:\n" + json.dumps(answer)})

    draft = draft_agent("um concierge que recebe as capturas", ["Aurora"], {"PATH": str(fake_bin)}, run)
    assert draft["name"] == "Hermes" and draft["color"] == "#82a0ff"  # cor inválida volta ao padrão
    assert seen["argv"][1:4] == ["-p", "--output-format", "json"] and "Aurora" in seen["argv"][4]
    with pytest.raises(DraftError):
        draft_agent("curto", [], {"PATH": str(fake_bin)}, run)
    with pytest.raises(DraftError):
        draft_agent("um agente qualquer de teste", [], {"PATH": str(fake_bin)}, lambda a, e, c: json.dumps({"result": "não sei"}))


# --- rotas -------------------------------------------------------------------------------------------


def test_capture_route_does_each_action(settings, accounts, brain, monkeypatch):
    fake = FakeServices()
    http = lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))  # noqa: E731
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, keychain=MemoryVault(), http=http, run_scheduler=False)
    created = []

    def fake_create(kind, cwd=None, cols=120, rows=32, title=None, account_id=None, tag=None, agent=None, prompt=None):
        created.append({"kind": kind, "tag": tag, "agent": agent.name if agent else None, "prompt": prompt})
        return SimpleNamespace(id="h1", title=agent.name if agent else (title or "Claude"))

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.manager, "create", fake_create)
        client.post("/conectores/slack", json={"name": "Slack pessoal", "token": "xoxb-bom", "email": "p@e.com"}, headers=AUTH)
        done = client.post("/captura", json={"texto": "me lembra de beber água em 20 min"}, headers=AUTH).json()
        assert done["acao"] == "lembrete" and fake.calls[-1][0] == "chat.scheduleMessage"
        done = client.post("/captura", json={"texto": "tarefa revisar o PR no Alfa"}, headers=AUTH).json()
        assert done["acao"] == "tarefa" and "- [ ] revisar o PR" in (brain / "01-PROJETOS/Alfa/Alfa.md").read_text(encoding="utf-8")
        assert client.post("/captura", json={"texto": "anota ideia de post"}, headers=AUTH).json()["acao"] == "nota"
        today = datetime.now().astimezone().date().isoformat()
        assert "- ideia de post" in (brain / "06-DIARIO" / f"{today}.md").read_text(encoding="utf-8")
        client.post("/agents", json={"name": "Hermes", "prompt": "Você é o Hermes."}, headers=AUTH)
        done = client.post("/captura", json={"texto": "organiza minha semana no ClickUp"}, headers=AUTH).json()
        assert done["acao"] == "concierge" and created[-1] == {"kind": "claude", "tag": "concierge", "agent": "Hermes", "prompt": "organiza minha semana no ClickUp"}
        summary = client.post("/estudo/blocos", json={"minutos": 25, "assunto": "SQL"}, headers=AUTH)
        assert summary.status_code == 201 and client.get("/estudo", headers=AUTH).json()["today"] == 25
        assert client.get("/hoje", headers=AUTH).json()["study"]["today"] == 25


def test_draft_route_and_test_session_from_draft(settings, accounts, monkeypatch):
    monkeypatch.setattr(app_mod, "draft_agent", lambda description, existing, env: {"name": "Minerva", "prompt": "Você é a Minerva."})
    monkeypatch.setattr(sessions_mod, "resolve_argv", lambda kind, s: ["/bin/echo", "--settings", "{}"])
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)) as client:
        assert client.post("/agents/rascunho", json={"descricao": "uma estrategista"}, headers=AUTH).json()["name"] == "Minerva"
        session = client.post("/sessions", json={"kind": "claude", "draft": {"name": "Minerva", "prompt": "Você é a Minerva."}}, headers=AUTH).json()
        argv = client.app.state.manager.get(session["id"]).pty.argv
        assert argv[argv.index("--append-system-prompt") + 1] == "Você é a Minerva." and "Minerva" in argv
        client.delete(f"/sessions/{session['id']}", headers=AUTH)
