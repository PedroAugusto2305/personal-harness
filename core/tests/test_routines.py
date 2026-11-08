"""v0.7: rotinas (rodar, recuperar ou pular com o Mac dormindo), Hoje e o pedido inicial da sessão."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from harness_core import sessions as sessions_mod
from harness_core.app import create_app
from harness_core.routines import Routine, RoutineError, RoutineStore, decide, last_slot, next_slot, parse_days, render_days
from harness_core.sessions import SessionManager

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}
MON_2050 = datetime(2026, 11, 9, 20, 50).astimezone()  # segunda-feira


def aurora(**changes) -> Routine:
    base = dict(id="aurora", name="Check-in de estudo", days=parse_days("seg-sab"), time="20:50", catchup=60, created=0)
    return Routine(**{**base, **changes})


def test_parse_days():
    assert parse_days("seg-sab") == [0, 1, 2, 3, 4, 5]
    assert parse_days("sexta") == [4]
    assert parse_days("sáb,dom") == [5, 6]
    assert parse_days("sex-seg") == [0, 4, 5, 6]
    assert parse_days("todos") == list(range(7))
    assert render_days([5, 0, 1]) == "seg,ter,sab"
    with pytest.raises(RoutineError):
        parse_days("feriado")


def test_decide_runs_on_time_recovers_in_window_and_skips_after():
    r = aurora()
    assert decide(r, MON_2050 + timedelta(seconds=30), None) == ("rodar", MON_2050)
    assert decide(r, MON_2050 + timedelta(minutes=40), None) == ("recuperar", MON_2050)  # Mac acordou 21h30
    assert decide(r, MON_2050 + timedelta(hours=3), None) == ("pular", MON_2050)  # acordou 23h50
    assert decide(r, MON_2050 + timedelta(minutes=5), MON_2050) is None  # já tratada
    assert decide(r, MON_2050 - timedelta(minutes=1), MON_2050 - timedelta(days=1)) is None  # ainda não chegou
    assert decide(aurora(active=False), MON_2050, None) is None
    assert decide(aurora(created=MON_2050.timestamp() + 60), MON_2050 + timedelta(minutes=1), None) is None  # criada depois


def test_sunday_is_rest_and_slots_skip_it():
    r = aurora()
    sunday_night = datetime(2026, 11, 8, 21, 0).astimezone()
    assert last_slot(r, sunday_night) == datetime(2026, 11, 7, 20, 50).astimezone()  # sábado
    assert next_slot(r, sunday_night) == MON_2050
    assert decide(r, sunday_night, datetime(2026, 11, 7, 20, 50).astimezone()) is None


def test_store_round_trip_and_trash(settings):
    store = RoutineStore(settings.home)
    saved = store.save(
        {"name": "Check-in de estudo", "agent": "aurora", "days": "seg-sab", "time": "20h50", "catchup": 60, "notify": True, "prompt": "São 20h50."}
    )
    assert saved.id == "check-in-de-estudo" and saved.time == "20:50" and saved.days == [0, 1, 2, 3, 4, 5]
    text = (settings.home / "rotinas" / "check-in-de-estudo.md").read_text(encoding="utf-8")
    assert "dias: seg,ter,qua,qui,sex,sab" in text and 'hora: "20:50"' in text and text.rstrip().endswith("São 20h50.")
    again = store.save({**saved.to_dict(), "active": False}, saved.id)
    assert not again.active and again.created == saved.created
    with pytest.raises(RoutineError):
        store.save({"name": "x", "days": [], "time": "9", "prompt": "y"})
    with pytest.raises(RoutineError):
        store.save({"name": "x", "days": [1], "time": "25:00", "prompt": "y"})
    store.record(saved.id, MON_2050, "rodou", "abc")
    assert store.last_handled(saved.id) == MON_2050
    store.delete(saved.id)
    assert not store.list() and list((settings.home / "rotinas" / ".lixeira").glob("*.md"))


def test_initial_prompt_goes_right_after_the_executable(settings, monkeypatch):
    monkeypatch.setattr(sessions_mod, "resolve_argv", lambda kind, s: ["/bin/echo", "--settings", "{}"])
    manager = SessionManager(settings)
    manager.mcp_token = lambda sid: "tok"

    async def scenario():
        session = manager.create("claude", str(settings.home.parent), prompt="Oi, Aurora")
        argv = session.pty.argv
        await manager.close(session.id)
        return argv

    argv = asyncio.run(scenario())
    assert argv[:2] == ["/bin/echo", "Oi, Aurora"]
    assert argv.index("--mcp-config") > 1  # o --mcp-config aceita vários valores: o pedido não pode vir depois


def test_routine_api_run_now_and_today(settings, accounts, monkeypatch):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    created: list[dict] = []

    def fake_create(kind, cwd=None, cols=120, rows=32, title=None, account_id=None, tag=None, agent=None, prompt=None):
        created.append({"kind": kind, "cwd": cwd, "title": title, "tag": tag, "prompt": prompt})
        return SimpleNamespace(id="s1", title=title or "Claude")

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.manager, "create", fake_create)
        body = {"name": "Revisão", "days": [0, 1, 2, 3, 4, 5, 6], "time": "23:59", "catchup": 30, "notify": False, "prompt": "Faça a revisão."}
        made = client.post("/rotinas", json=body, headers=AUTH)
        assert made.status_code == 201 and made.json()["next"]
        assert client.post("/rotinas", json={**body, "time": "99:00"}, headers=AUTH).status_code == 400
        run = client.post("/rotinas/revisao/rodar", headers=AUTH).json()
        assert run["status"] == "manual" and created[-1] == {"kind": "claude", "cwd": None, "title": "Revisão", "tag": "rotina", "prompt": "Faça a revisão."}
        listed = client.get("/rotinas", headers=AUTH).json()
        assert listed["routines"][0]["id"] == "revisao" and listed["runs"][0]["status"] == "manual"
        today = client.get("/hoje", headers=AUTH).json()
        assert today["slots"][0]["routine"]["id"] == "revisao" and today["manual"][0]["session"] == "s1"
        assert client.put("/rotinas/revisao", json={**body, "active": False}, headers=AUTH).json()["active"] is False
        assert client.get("/hoje", headers=AUTH).json()["slots"] == []
        assert client.delete("/rotinas/revisao", headers=AUTH).status_code == 204
        assert client.post("/rotinas/revisao/rodar", headers=AUTH).status_code == 404
