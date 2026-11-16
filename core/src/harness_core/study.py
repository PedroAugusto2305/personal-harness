"""Estudo: blocos de Pomodoro, placar da semana e a linha na nota do dia do Brain.

Cada bloco de foco terminado vai para ~/.harness/estudo.db e vira uma linha na seção
"📚 Estudo" da nota do dia (06-DIARIO), para a Aurora ler na cobrança das 20h50.
Regras do placar, do papel da Aurora: piso de 20 minutos em dia ruim, nunca dois dias
seguidos sem estudar, domingo é descanso.

v1.4.0: com vários planos de estudo, cada bloco guarda o plano (o que estava em foco quando o foco
começou) e a linha do dia ganha o [[plano]]. O piso e a sequência continuam do dia inteiro.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .vault import Vault, VaultError

FLOOR = 20  # minutos: o piso do dia ruim
DAILY_BEFORE = ("## 🛠️ Registro de trabalho", "## 📝 Log")


class StudyLog:
    def __init__(self, home: Path, vault: Vault) -> None:
        self.db = home / "estudo.db"
        self.vault = vault
        self._lock = threading.Lock()
        home.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("create table if not exists blocks(id integer primary key, started real, ended real, minutes real, subject text, day text)")
            columns = {row[1] for row in con.execute("pragma table_info(blocks)")}
            if "plano" not in columns:
                con.execute("alter table blocks add column plano text not null default ''")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def add(self, minutes: float, subject: str = "", ended: datetime | None = None, plano: str = "") -> dict:
        ended = (ended or datetime.now().astimezone()).replace(microsecond=0)
        minutes = max(1.0, round(float(minutes), 1))
        started = ended - timedelta(minutes=minutes)
        day = ended.date().isoformat()
        plano = " ".join(str(plano or "").split())[:120]
        with self._lock, self._connect() as con:
            row_id = con.execute(
                "insert into blocks(started, ended, minutes, subject, day, plano) values (?,?,?,?,?,?)",
                (started.timestamp(), ended.timestamp(), minutes, subject.strip()[:200], day, plano),
            ).lastrowid
        line = f"- {started:%H:%M}–{ended:%H:%M} · 🍅 {minutes:g} min" + (f" · {subject.strip()}" if subject.strip() else "")
        if plano:
            line += f" · [[{plano}]]"
        note = ""
        if self.vault.available:
            try:
                note = self.vault.rel(self.vault.append_daily(day, "📚 Estudo", line, DAILY_BEFORE))
            except (OSError, VaultError):
                note = ""
        return {"id": row_id, "minutes": minutes, "day": day, "note": note, "line": line, "plano": plano}

    def by_day(self, since: str) -> dict[str, float]:
        with self._connect() as con:
            rows = con.execute("select day, sum(minutes) m from blocks where day >= ? group by day", (since,)).fetchall()
        return {r["day"]: r["m"] for r in rows}

    def summary(self, now: datetime | None = None) -> dict:
        now = now or datetime.now().astimezone()
        monday = (now - timedelta(days=now.weekday())).date()
        totals = self.by_day((monday - timedelta(days=14)).isoformat())
        week = [{"day": (monday + timedelta(days=i)).isoformat(), "minutes": totals.get((monday + timedelta(days=i)).isoformat(), 0)} for i in range(7)]
        today = now.date()
        yesterday = today - timedelta(days=1)
        # Sequência: dias seguidos (sem contar domingo) com pelo menos o piso, terminando hoje ou ontem.
        streak, day = 0, today if totals.get(today.isoformat(), 0) >= FLOOR else yesterday
        while True:
            if day.weekday() == 6:
                day -= timedelta(days=1)
                continue
            if totals.get(day.isoformat(), 0) >= FLOOR:
                streak += 1
                day -= timedelta(days=1)
            else:
                break
        last_study_day = yesterday if yesterday.weekday() != 6 else yesterday - timedelta(days=1)
        risk = today.weekday() != 6 and totals.get(today.isoformat(), 0) < FLOOR and totals.get(last_study_day.isoformat(), 0) < FLOOR
        with self._connect() as con:
            recent = [dict(r) for r in con.execute("select * from blocks order by id desc limit 8").fetchall()]
            per_plan = {
                r["plano"]: r["m"]
                for r in con.execute("select plano, sum(minutes) m from blocks where day >= ? and plano != '' group by plano", (monday.isoformat(),)).fetchall()
            }
        return {
            "today": totals.get(today.isoformat(), 0),
            "floor": FLOOR,
            "week": week,
            "week_total": sum(d["minutes"] for d in week),
            "streak": streak,
            "rest_day": today.weekday() == 6,
            # Ontem (ou sábado, numa segunda) ficou abaixo do piso e hoje ainda não: a regra dos dois dias.
            "risk": risk,
            "recent": recent,
            # v1.4.0: minutos da semana em cada plano (os blocos sem plano, de antes, ficam só no total).
            "por_plano": per_plan,
            "updated": time.time(),
        }
