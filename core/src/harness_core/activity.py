"""Atividade: o que cada agente fez pela central de MCP, com aprovação e resultado."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

KEEP = 3000


class ActivityLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """create table if not exists calls(
                    id integer primary key, ts real, session text, who text, tool text, account text,
                    args text, status text, detail text, ms integer)"""
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def start(self, session: str, who: str, tool: str, account: str, args: dict, status: str = "rodando") -> int:
        text = json.dumps(args, ensure_ascii=False)
        with self._lock, self._connect() as con:
            row_id = con.execute(
                "insert into calls(ts, session, who, tool, account, args, status, detail, ms) values (?,?,?,?,?,?,?,?,?)",
                (time.time(), session, who, tool, account, text[:4000], status, "", 0),
            ).lastrowid
            con.execute("delete from calls where id <= ?", (row_id - KEEP,))
        return int(row_id)

    def finish(self, call_id: int, status: str, detail: str, started: float) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "update calls set status = ?, detail = ?, ms = ? where id = ?",
                (status, detail[:2000], int((time.time() - started) * 1000), call_id),
            )

    def get(self, call_id: int) -> dict | None:
        with self._connect() as con:
            row = con.execute("select * from calls where id = ?", (call_id,)).fetchone()
        return self._row(row) if row else None

    def recent(self, limit: int = 100) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("select * from calls order by id desc limit ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        item = dict(row)
        try:
            item["args"] = json.loads(item["args"] or "{}")
        except json.JSONDecodeError:
            pass
        return item
