"""Rotinas: um agente que abre sozinho num terminal, na hora marcada, com um pedido.

Cada rotina é um .md em ~/.harness/rotinas (campos no topo, o pedido no corpo), como os
agentes. Na hora, a MÊTIS abre o Claude (ou o Codex) interativo com o pedido como primeira
mensagem (`claude "<pedido>"`), pelo plano normal, e pode avisar o Pedro no Slack.

A MÊTIS só roda com o Mac acordado. Se ele dormia na hora, a rotina tem uma janela de
recuperação: acordou dentro dela, roda (marcada como recuperada); depois, pula e fica
registrado. Assim a Aurora das 20h50 não aparece às 3h da manhã.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .accounts import slugify
from .agents import CLIS, parse_agent

DAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
FIELDS = ("nome", "agente", "cli", "pasta", "dias", "hora", "recuperar", "avisar", "ativa")
ON_TIME = timedelta(minutes=2)  # até 2 min depois da hora ainda é "na hora"


class RoutineError(ValueError):
    pass


@dataclass
class Routine:
    id: str
    name: str
    agent: str = ""
    cli: str = "claude"
    folder: str = ""
    days: list[int] = field(default_factory=lambda: list(range(6)))
    time: str = "09:00"
    catchup: int = 60  # minutos de recuperação depois da hora
    notify: bool = True
    active: bool = True
    prompt: str = ""
    created: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def parse_days(value: str) -> list[int]:
    """'seg,ter,qua' ou 'seg-sab' ou 'todos' → [0, 1, 2…] (0 = segunda)."""
    text = value.strip().lower().replace("á", "a").replace("ç", "c").replace(" ", "")
    if text in ("todos", "todososdias", "diario"):
        return list(range(7))
    out: set[int] = set()
    for part in filter(None, text.split(",")):
        if "-" in part:
            a, b = part.split("-", 1)
            if a[:3] not in DAYS or b[:3] not in DAYS:
                raise RoutineError(f"dia desconhecido: {part}")
            i, j = DAYS.index(a[:3]), DAYS.index(b[:3])
            out.update(range(i, j + 1) if i <= j else [*range(i, 7), *range(0, j + 1)])
        elif part[:3] in DAYS:
            out.add(DAYS.index(part[:3]))
        else:
            raise RoutineError(f"dia desconhecido: {part}")
    return sorted(out)


def render_days(days: list[int]) -> str:
    return ",".join(DAYS[d] for d in sorted(set(days)))


def _clock(value: str) -> tuple[int, int]:
    """'20:50', '20h50', '20h', '9' → (hora, minuto)."""
    match = re.fullmatch(r"\s*(\d{1,2})(?:\s*[:h]\s*(\d{2})?)?\s*", str(value))
    if not match:
        raise RoutineError(f"hora inválida: {value}")
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise RoutineError(f"hora inválida: {value}")
    return hour, minute


def slot_on(routine: Routine, day: datetime) -> datetime | None:
    """A hora marcada da rotina naquele dia, se ela roda nele."""
    if day.weekday() not in routine.days:
        return None
    hour, minute = _clock(routine.time)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def last_slot(routine: Routine, now: datetime) -> datetime | None:
    """A última hora marcada da rotina que já chegou (até 8 dias para trás)."""
    if not routine.days:
        return None
    hour, minute = _clock(routine.time)
    for back in range(0, 9):
        day = now - timedelta(days=back)
        slot = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot.weekday() in routine.days and slot <= now:
            return slot
    return None


def next_slot(routine: Routine, now: datetime) -> datetime | None:
    if not routine.days:
        return None
    hour, minute = _clock(routine.time)
    for ahead in range(0, 8):
        slot = (now + timedelta(days=ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot.weekday() in routine.days and slot > now:
            return slot
    return None


def decide(routine: Routine, now: datetime, last_handled: datetime | None) -> tuple[str, datetime] | None:
    """('rodar' | 'recuperar' | 'pular', hora marcada) ou None se não há nada a fazer."""
    if not routine.active:
        return None
    slot = last_slot(routine, now)
    if slot is None or (last_handled is not None and last_handled >= slot):
        return None
    if routine.created and slot.timestamp() < routine.created:
        return None  # rotina criada depois desta hora: começa na próxima
    late = now - slot
    if late <= ON_TIME:
        return "rodar", slot
    if late <= timedelta(minutes=max(routine.catchup, 2)):
        return "recuperar", slot
    return "pular", slot


class RoutineStore:
    def __init__(self, home: Path) -> None:
        self.dir = home / "rotinas"
        self.db = home / "rotinas.db"
        self._lock = threading.Lock()
        home.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                "create table if not exists runs(id integer primary key, routine text, slot real, ts real, status text, session text, detail text)"
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def _file(self, routine_id: str) -> Path:
        if not routine_id or routine_id != slugify(routine_id):
            raise RoutineError(f"id de rotina inválido: {routine_id}")
        return self.dir / f"{routine_id}.md"

    def _read(self, path: Path) -> Routine:
        meta, body = parse_agent(path.read_text(encoding="utf-8"))
        cli = meta.get("cli", "claude")
        try:
            catchup = int(meta.get("recuperar") or 60)
        except ValueError:
            catchup = 60
        stat = path.stat()
        created_raw = meta.get("criada", "")
        try:
            created = float(created_raw) if created_raw else float(getattr(stat, "st_birthtime", stat.st_mtime))
        except ValueError:
            created = stat.st_mtime
        return Routine(
            id=path.stem,
            name=meta.get("nome") or path.stem,
            agent=meta.get("agente", ""),
            cli=cli if cli in CLIS else "claude",
            folder=meta.get("pasta", ""),
            days=parse_days(meta.get("dias") or "seg-sab"),
            time=meta.get("hora") or "09:00",
            catchup=max(0, catchup),
            notify=meta.get("avisar", "sim").lower() not in ("nao", "não", "false", "0"),
            active=meta.get("ativa", "sim").lower() not in ("nao", "não", "false", "0"),
            prompt=body.strip(),
            created=created,
            updated_at=stat.st_mtime,
        )

    def list(self) -> list[Routine]:
        if not self.dir.is_dir():
            return []
        out = []
        for path in sorted(self.dir.glob("*.md")):
            try:
                out.append(self._read(path))
            except (OSError, RoutineError, UnicodeDecodeError):
                continue
        return sorted(out, key=lambda r: (r.time, r.name.lower()))

    def get(self, routine_id: str) -> Routine:
        path = self._file(routine_id)
        if not path.is_file():
            raise RoutineError(f"rotina não encontrada: {routine_id}")
        return self._read(path)

    def save(self, data: dict, routine_id: str | None = None) -> Routine:
        name = str(data.get("name", "")).strip()
        if not name:
            raise RoutineError("a rotina precisa de um nome")
        prompt = str(data.get("prompt", "")).strip()
        if not prompt:
            raise RoutineError("a rotina precisa de um pedido (a primeira mensagem para o agente)")
        days = data.get("days")
        days = parse_days(days) if isinstance(days, str) else sorted({int(d) for d in (days or []) if 0 <= int(d) <= 6})
        if not days:
            raise RoutineError("escolha pelo menos um dia")
        hour, minute = _clock(str(data.get("time", "")))
        cli = data.get("cli", "claude")
        if cli not in CLIS:
            raise RoutineError(f"CLI desconhecida: {cli}")
        if routine_id is None:
            base = slugify(name)
            routine_id, n = base, 2
            while self._file(routine_id).exists():
                routine_id, n = f"{base}-{n}", n + 1
        path = self._file(routine_id)
        previous = parse_agent(path.read_text(encoding="utf-8"))[0] if path.exists() else {}
        meta = {
            "nome": name,
            "agente": str(data.get("agent", "") or "").strip(),
            "cli": cli,
            "pasta": str(data.get("folder", "") or "").strip(),
            "dias": render_days(days),
            "hora": f"{hour:02d}:{minute:02d}",
            "recuperar": str(max(0, int(data.get("catchup", 60) or 0))),
            "avisar": "sim" if data.get("notify", True) else "nao",
            "ativa": "sim" if data.get("active", True) else "nao",
            "criada": previous.get("criada") or f"{time.time():.0f}",
        }
        lines = ["---", *(f"{k}: {json.dumps(meta[k], ensure_ascii=False) if k == 'hora' else meta[k]}" for k in (*FIELDS, "criada")), "---"]
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n\n" + prompt + "\n", encoding="utf-8")
        tmp.replace(path)
        return self._read(path)

    def delete(self, routine_id: str) -> None:
        path = self._file(routine_id)
        if not path.is_file():
            raise RoutineError(f"rotina não encontrada: {routine_id}")
        trash = self.dir / ".lixeira"
        trash.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), trash / f"{routine_id}-{time.strftime('%Y%m%d-%H%M%S')}.md")

    # --- execuções -------------------------------------------------------------------

    def last_handled(self, routine_id: str) -> datetime | None:
        with self._connect() as con:
            row = con.execute("select max(slot) from runs where routine = ? and slot > 0", (routine_id,)).fetchone()
        return datetime.fromtimestamp(row[0]).astimezone() if row and row[0] else None

    def record(self, routine_id: str, slot: datetime | None, status: str, session: str = "", detail: str = "") -> dict:
        with self._lock, self._connect() as con:
            row_id = con.execute(
                "insert into runs(routine, slot, ts, status, session, detail) values (?,?,?,?,?,?)",
                (routine_id, slot.timestamp() if slot else 0, time.time(), status, session, detail[:500]),
            ).lastrowid
            row = con.execute("select * from runs where id = ?", (row_id,)).fetchone()
        return dict(row)

    def runs(self, limit: int = 50, since: float = 0) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("select * from runs where ts >= ? order by id desc limit ?", (since, limit)).fetchall()
        return [dict(r) for r in rows]
