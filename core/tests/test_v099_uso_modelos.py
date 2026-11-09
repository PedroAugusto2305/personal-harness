"""v0.9.9: uso dos modelos (tokens e custo equivalente em API) e o limite do plano guardado."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_core.app import create_app
from harness_core.model_usage import ModelUsage, cost_of, load_plan_usage, model_label, save_plan_usage

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat()


def answer(msg: str, ts: float, model="claude-opus-5-5", cwd="/repo/app", tin=10, tout=100, w5=0, w1=0, read=0, speed="standard", request="r1"):
    usage = {
        "input_tokens": tin,
        "output_tokens": tout,
        "cache_creation_input_tokens": w5 + w1,
        "cache_read_input_tokens": read,
        "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1},
        "speed": speed,
    }
    return json.dumps({"type": "assistant", "timestamp": iso(ts), "cwd": cwd, "sessionId": "s-" + cwd.split("/")[-1], "requestId": request, "message": {"id": msg, "model": model, "usage": usage, "content": []}})


def write(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def homes(tmp_path):
    return {"claude": tmp_path / "claude", "codex": tmp_path / "codex"}


def test_prices_and_labels():
    # Opus 5.5: 1M de entrada US$ 4, 1M de saída US$ 20, 1M de cache lido US$ 0,20,
    # gravação de 5 min a 1,25× e de 1 h a 2× da entrada.
    assert cost_of("claude-opus-5-5", (1_000_000, 1_000_000, 1_000_000, 1_000_000, 1_000_000)) == pytest.approx(4 + 20 + 5 + 8 + 0.2)
    assert cost_of("claude-opus-5-5", (1_000_000, 0, 0, 0, 0), fast=True) == pytest.approx(8)
    assert cost_of("claude-opus-4-1-20250805", (1_000_000, 0, 0, 0, 0)) == pytest.approx(15)
    assert cost_of("claude-opus-4-8", (1_000_000, 0, 0, 0, 0)) == pytest.approx(5)
    assert cost_of("gpt-5.6-sol", (1, 1, 1, 1, 1)) is None
    assert model_label("claude-opus-5-5") == "Opus 5.5"
    assert model_label("claude-sonnet-4-20250514") == "Sonnet 4"
    assert model_label("claude-haiku-4-5-20251001") == "Haiku 4.5"
    assert model_label("gpt-5.6-sol") == "gpt-5.6-sol"


def test_report_dedupes_counts_days_projects_and_codex(homes, tmp_path):
    now = time.time()
    yesterday = now - 86400
    projects = homes["claude"] / "projects"
    write(
        projects / "-repo-app" / "a.jsonl",
        [
            '{"type":"user","message":{"content":"oi"}}',
            answer("m1", now, tout=100, w5=1000, read=5000),
            answer("m1", now, tout=100, w5=1000, read=5000),  # o mesmo bloco de novo
            answer("m2", yesterday, model="claude-sonnet-5-5", tin=1_000_000, tout=0, request="r2"),
            answer("m3", now, model="<synthetic>", request="r3"),
            "linha quebrada {",
        ],
    )
    # Sessão retomada (outro arquivo) repete m1; subagente em subpasta conta.
    write(projects / "-repo-app" / "b.jsonl", [answer("m1", now, tout=100, w5=1000, read=5000)])
    write(projects / "-repo-app" / "s1" / "subagents" / "agent-1.jsonl", [answer("m4", now, cwd="/x/repo/.maestri/roles/0b1c", tout=50, request="r4")])
    rollout = homes["codex"] / "sessions" / "2026" / "11" / "09" / "rollout-1.jsonl"
    write(
        rollout,
        [
            json.dumps({"type": "session_meta", "timestamp": iso(now), "payload": {"id": "cx1", "cwd": "/repo/app"}}),
            json.dumps({"type": "response_item", "payload": {"model": "gpt-5.6-sol"}}),
            json.dumps({"type": "event_msg", "timestamp": iso(now), "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 300}}}}),
            json.dumps({"type": "event_msg", "timestamp": iso(now), "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 300}}}}),
            json.dumps({"type": "event_msg", "timestamp": iso(now), "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 1000}}}}),
        ],
    )
    usage = ModelUsage(lambda: {}, lambda: [{"name": "App", "path": "/repo/app"}], tmp_path / "worktrees", lambda: homes)
    report = usage.report(7, now=now)

    assert [m["nome"] for m in report["por_modelo"]] == ["Sonnet 5.5", "Opus 5.5", "gpt-5.6-sol"]
    opus = next(m for m in report["por_modelo"] if m["nome"] == "Opus 5.5")
    assert opus["respostas"] == 2  # m1 uma vez só (três linhas, dois arquivos) e m4
    assert opus["saida"] == 150 and opus["cache_5m"] == 1000 and opus["cache_lido"] == 5000
    expected = (10 * 4 + 100 * 20 + 1000 * 4 * 1.25 + 5000 * 0.2) / 1e6 + (10 * 4 + 50 * 20) / 1e6
    assert opus["custo"] == pytest.approx(expected, abs=1e-4)
    codex = next(m for m in report["por_modelo"] if m["provedor"] == "codex")
    assert codex["tokens"] == 1000 and codex["respostas"] == 2 and codex["custo"] == 0
    assert report["sem_preco"] == []
    assert len(report["por_dia"]) == 7 and report["por_dia"][-1]["dia"] == datetime.fromtimestamp(now).date().isoformat()
    assert report["por_dia"][-2]["custo"] == pytest.approx(2.0)  # 1M de entrada no Sonnet 5.5, ontem
    assert report["por_dia"][-2]["tokens_modelos"] == {"Sonnet 5.5": 1_000_000}
    assert report["por_dia"][-1]["tokens_modelos"]["gpt-5.6-sol"] == 1000
    assert report["hoje"]["respostas"] == 4
    names = {p["projeto"] for p in report["por_projeto"]}
    assert names == {"App", "repo"}  # projeto da MÊTIS pela pasta; .maestri/roles conta para o repositório
    assert report["total"]["sessoes"] == 3  # s-app (m1 e m2), s-0b1c (m4) e a do Codex


def test_unchanged_files_are_not_read_again(homes, tmp_path, monkeypatch):
    now = time.time()
    path = write(homes["claude"] / "projects" / "p" / "a.jsonl", [answer("m1", now)])
    usage = ModelUsage(lambda: {}, lambda: [], tmp_path, lambda: homes)
    usage.report(1, now=now)
    from harness_core import model_usage

    calls = []
    original = model_usage.parse_claude
    monkeypatch.setattr(model_usage, "parse_claude", lambda p, a: calls.append(p) or original(p, a))
    usage.report(1, now=now)
    assert calls == []
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(answer("m2", now, request="r2") + "\n")
    assert usage.report(1, now=now)["hoje"]["respostas"] == 2
    assert calls == [path]


def test_short_window_keeps_older_files_in_memory(homes, tmp_path, monkeypatch):
    now = time.time()
    old = write(homes["claude"] / "projects" / "p" / "velho.jsonl", [answer("m1", now - 5 * 86400)])
    os.utime(old, (now - 5 * 86400, now - 5 * 86400))
    write(homes["claude"] / "projects" / "p" / "hoje.jsonl", [answer("m2", now, request="r2")])
    usage = ModelUsage(lambda: {}, lambda: [], tmp_path, lambda: homes)
    assert usage.report(7, now=now)["total"]["respostas"] == 2
    assert usage.report(1, now=now)["total"]["respostas"] == 1
    from harness_core import model_usage

    calls = []
    original = model_usage.parse_claude
    monkeypatch.setattr(model_usage, "parse_claude", lambda p, a: calls.append(p) or original(p, a))
    assert usage.report(7, now=now)["total"]["respostas"] == 2
    assert calls == []  # o de 5 dias atrás continuou na memória


def test_project_names(tmp_path):
    usage = ModelUsage(lambda: {}, lambda: [], tmp_path / "wt")
    known = [("Personal Harness", "/code/personal-harness")]
    assert usage.project_of(str(tmp_path / "wt" / "repo" / "branch"), known) == "repo"
    assert usage.project_of("/code/personal-harness/app", known) == "Personal Harness"
    assert usage.project_of("/docs/agente-ia-sdr/.maestri/roles/9f2a", known) == "agente-ia-sdr"
    assert usage.project_of("/docs/.maestri/floors/agente-ia-sdr--fase-2/.maestri/roles/1", known) == "agente-ia-sdr"
    assert usage.project_of(str(Path.home()), known) == "~"
    assert usage.project_of("", known) == "—"


def test_plan_usage_survives_restart_and_resets(tmp_path):
    now = time.time()
    save_plan_usage(tmp_path, {"padrao": {"five_hour": {"used_pct": 40.0, "resets_at": now - 10}, "seven_day": {"used_pct": 12.0, "resets_at": now + 3600}, "updated_at": now - 60}})
    loaded = load_plan_usage(tmp_path, now=now)
    assert loaded["padrao"]["five_hour"] == {"used_pct": 0.0, "resets_at": None}  # a janela já zerou
    assert loaded["padrao"]["seven_day"]["used_pct"] == 12.0
    assert load_plan_usage(tmp_path / "nada") == {}


def test_route(settings, accounts, homes):
    now = time.time()
    write(homes["claude"] / "projects" / "p" / "a.jsonl", [answer("m1", now)])
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    with TestClient(app) as client:
        app.state.cli_homes = homes
        body = client.get("/uso/modelos", params={"dias": 7}, headers=AUTH).json()
        assert body["dias"] == 7 and body["total"]["respostas"] == 1
        assert client.get("/uso/modelos", params={"dias": 0}, headers=AUTH).status_code == 422
        assert client.get("/uso/modelos").status_code == 401


def test_statusline_limits_are_saved(settings, accounts):
    app = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    manager = app.state.manager
    manager.usage.claude["padrao"] = {"five_hour": {"used_pct": 5.0, "resets_at": time.time() + 600}}
    save_plan_usage(settings.home, manager.usage.claude)
    again = create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False, run_scheduler=False)
    assert again.state.manager.usage.claude["padrao"]["five_hour"]["used_pct"] == 5.0
