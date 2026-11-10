"""Rotinas: um agente que abre sozinho num terminal, na hora marcada, com um pedido.

Cada rotina é um .md em ~/.harness/rotinas (campos no topo, o pedido no corpo), como os
agentes. Na hora, a MÊTIS abre o Claude (ou o Codex) interativo com o pedido como primeira
mensagem (`claude "<pedido>"`), pelo plano normal, e pode avisar o Pedro no Slack.

A MÊTIS só roda com o Mac acordado. Se ele dormia na hora, a rotina tem uma janela de
recuperação: acordou dentro dela, roda (marcada como recuperada); depois, pula e fica
registrado. Assim a Aurora das 20h50 não aparece às 3h da manhã.

v0.9.8: as rotinas passam a ser automações de um gatilho agendado e um agente (`rotina-<id>`
em ~/.harness/automacoes), com a mesma recuperação e o mesmo aviso. Na primeira subida, cada
.md vira automação e fica como cópia (`ativa: não`, `migrada: rotina-<id>`). As rotas
/rotinas continuam com o mesmo formato, agora por cima das automações (RoutineFlows).

v1.0.0: a rotina conta como rodada assim que o terminal abre com o pedido (como na v0.7: quem
conversa depois é o Pedro), sem vaga de agente e sem prazo. E rotina é a automação com o passo
marcado `etiqueta: rotina`, não qualquer id que comece com rotina-.
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
    #: v0.9.8: a automação para onde a rotina foi (o .md fica só como cópia).
    migrated: str = ""

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


def normalize(data: dict) -> dict:
    """Confere o que a tela (ou o metis) mandou para uma rotina e devolve no formato certo."""
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
    return {
        "name": name,
        "agent": str(data.get("agent", "") or "").strip(),
        "cli": cli,
        "folder": str(data.get("folder", "") or "").strip(),
        "days": days,
        "time": f"{hour:02d}:{minute:02d}",
        "catchup": max(0, int(data.get("catchup", 60) or 0)),
        "notify": bool(data.get("notify", True)),
        "active": bool(data.get("active", True)),
        "prompt": prompt,
    }


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
            migrated=meta.get("migrada", ""),
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
        clean = normalize(data)
        name, prompt, days, cli = clean["name"], clean["prompt"], clean["days"], clean["cli"]
        hour, minute = _clock(clean["time"])
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

    def mark_migrated(self, routine_id: str, automation_id: str) -> None:
        """O .md fica como cópia: desligado e com o nome da automação que tomou o lugar dele."""
        path = self._file(routine_id)
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        if not lines or lines[0].strip() != "---":
            return
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            return
        head = [line for line in lines[1:end] if not line.startswith(("ativa:", "migrada:"))]
        head += ["ativa: não", f"migrada: {automation_id}"]
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join([lines[0], *head, *lines[end:]]), encoding="utf-8")
        tmp.replace(path)

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


# --- v0.9.8: as rotinas como automações ------------------------------------------------------

PREFIX = "rotina-"
RUN_OFFSET = 1_000_000  # execuções vindas das automações não colidem com as antigas da rotinas.db
#: A marca da rotina no passo de agente (`etiqueta: rotina`). O id `rotina-<id>` só endereça as
#: rotas /rotinas: uma automação comum chamada "Rotina diária" também ganha o id rotina-diaria.
MARK = "rotina"


def routine_step(flow: dict) -> dict | None:
    """O passo de agente marcado como rotina, ou None se a automação não é uma rotina."""
    return next((s for s in flow.get("passos") or [] if s.get("tipo") == "agente" and s.get("etiqueta") == MARK), None)


class RoutineFlows:
    """As rotas /rotinas por cima das automações `rotina-<id>` (um gatilho agendado e um agente),
    no mesmo formato de sempre. Os .md antigos viram automação uma vez (migrate)."""

    def __init__(self, store, engine, legacy: RoutineStore) -> None:
        self.store = store
        self.engine = engine
        self.legacy = legacy

    @staticmethod
    def automation_id(routine_id: str) -> str:
        return PREFIX + routine_id

    @staticmethod
    def flow(data: dict, created: float) -> dict:
        clean = normalize(data)
        return {
            "nome": clean["name"],
            "descricao": "Rotina: abre o agente na hora marcada, com o pedido como primeira mensagem.",
            "gatilho": {
                "tipo": "agendado",
                "dias": clean["days"],
                "hora": clean["time"],
                # 0 de recuperação = só na hora (a regra das rotinas já trata até 2 min como na hora)
                "recupera_min": max(clean["catchup"], 2),
                "recuperar": clean["catchup"],
                "aviso": clean["notify"],
                "criada": created,
                "x": 0,
                "y": 0,
            },
            "passos": [
                {
                    "id": "agente",
                    "tipo": "agente",
                    "titulo": "Abrir o agente",
                    "agente": clean["agent"],
                    "cli": clean["cli"],
                    "pasta": clean["folder"],
                    "pedido": clean["prompt"],
                    "onde": "visivel",
                    "saida": {},
                    "ferramentas": ["*"],
                    "etiqueta": MARK,
                    "troca_cota": False,
                    "x": 260,
                    "y": 0,
                }
            ],
            "ligacoes": [{"de": "gatilho", "para": "agente"}],
        }

    def _exists(self, automation_id: str) -> bool:
        try:
            return self.store.path(automation_id).exists()
        except ValueError:
            return False

    def is_flow(self, routine_id: str) -> bool:
        """A rotina é uma automação (a rotina-<id> existe e tem a marca de rotina)."""
        return self.routine(self.automation_id(routine_id)) is not None

    def routine(self, automation_id: str) -> Routine | None:
        """A rotina no formato de sempre, lida da automação (a publicada, ou o rascunho). None
        quando a automação não é uma rotina: sem o prefixo ou sem o passo marcado."""
        if not automation_id.startswith(PREFIX):
            return None
        try:
            flow = self.store.published(automation_id) or self.store.draft(automation_id)
        except ValueError:
            return None
        trigger = flow["gatilho"]
        step = routine_step(flow)
        if trigger.get("tipo") != "agendado" or step is None:
            return None
        state = self.engine.state(automation_id)
        return Routine(
            id=automation_id[len(PREFIX):],
            name=flow["nome"],
            agent=str(step.get("agente") or ""),
            cli=str(step.get("cli") or "claude"),
            folder=str(step.get("pasta") or ""),
            days=list(trigger["dias"]),
            time=str(trigger["hora"]),
            catchup=int(trigger.get("recuperar", trigger.get("recupera_min", 60)) or 0),
            notify=bool(trigger.get("aviso")),
            active=bool(state["ativa"]),
            prompt=str(step.get("pedido") or ""),
            created=float(trigger.get("criada") or state.get("desde") or 0),
            updated_at=self.store.mtime(automation_id),
        )

    def list(self) -> list[Routine]:
        out = [r for aid in self.store.ids() if aid.startswith(PREFIX) for r in [self.routine(aid)] if r is not None]
        mine = {r.id for r in out}
        out += [r for r in self.legacy.list() if not r.migrated and r.id not in mine]
        return sorted(out, key=lambda r: (r.time, r.name.lower()))

    def get(self, routine_id: str) -> Routine:
        if self.is_flow(routine_id):
            found = self.routine(self.automation_id(routine_id))
            if found is not None:
                return found
        legacy = self.legacy.get(routine_id)
        if legacy.migrated:
            raise RoutineError(f"rotina não encontrada: {routine_id}")
        return legacy

    def save(self, data: dict, routine_id: str | None = None) -> Routine:
        clean = normalize(data)
        if routine_id is None:
            base = (slugify(clean["name"]) or "rotina")[:50].strip("-") or "rotina"
            taken = {r.id for r in self.list()} | {p.stem for p in self.legacy.dir.glob("*.md")} if self.legacy.dir.is_dir() else {r.id for r in self.list()}
            routine_id, n = base, 2
            while routine_id in taken or self._exists(self.automation_id(routine_id)) or (self.store.archive_dir / f"{self.automation_id(routine_id)}.yaml").exists():
                routine_id, n = f"{base}-{n}", n + 1
            automation_id = self.automation_id(routine_id)
            self.store.create(clean["name"], self.flow(clean, time.time()), automation_id=automation_id)
        else:
            automation_id = self.automation_id(routine_id)
            if not self.is_flow(routine_id):  # nunca troca o desenho de uma automação que não é rotina
                raise RoutineError(f"rotina não encontrada: {routine_id}")
            created = self.store.draft(automation_id)["gatilho"].get("criada") or time.time()
            self.store.save(automation_id, self.flow(clean, float(created)))
        self.store.publish(automation_id)
        self.engine.set_active(automation_id, clean["active"])
        found = self.routine(automation_id)
        assert found is not None
        return found

    def delete(self, routine_id: str) -> None:
        automation_id = self.automation_id(routine_id)
        if self.is_flow(routine_id):
            self.engine.set_active(automation_id, False)
            self.store.archive(automation_id)
            return
        self.legacy.delete(routine_id)

    @staticmethod
    def run_view(row: dict) -> dict:
        """Uma execução da automação no formato das execuções de rotina (a tela Hoje não muda)."""
        status = row["status"]
        if status == "pulada":
            mapped = "pulou"
        elif status in ("erro", "cancelada", "interrompida", "recusada"):
            mapped = "erro"
        else:
            mapped = {"agendado": "rodou", "recuperada": "recuperada"}.get(row.get("origem") or "", "manual")
        return {
            "id": RUN_OFFSET + int(row["id"]),
            "routine": str(row["automation"])[len(PREFIX):],
            "slot": row.get("slot") or 0,
            "ts": row["started"],
            "status": mapped,
            "session": row.get("sessao") or "",
            "detail": str(row.get("error") or row.get("nota") or "")[:500],
        }

    def runs(self, limit: int = 50, since: float = 0) -> list[dict]:
        # Execuções das automações rotina-* que não são rotina ficam de fora (as das rotinas
        # apagadas, que já não estão na lista, continuam no histórico).
        others = tuple(aid for aid in self.store.ids() if aid.startswith(PREFIX) and self.routine(aid) is None)
        new = [self.run_view(r) for r in self.engine.runs_with_prefix(PREFIX, limit, since, exclude=others)]
        old = self.legacy.runs(limit, since)
        return sorted([*new, *old], key=lambda r: r["ts"], reverse=True)[:limit]

    def migrate(self) -> list[str]:
        """Uma vez por rotina .md: vira a automação rotina-<id> (publicada, ativa se estava) e o
        arquivo fica como cópia desligada. Rodar de novo não faz nada (idempotente)."""
        done = []
        for routine in self.legacy.list():
            if routine.migrated:
                continue
            automation_id = self.automation_id(routine.id)
            if self._exists(automation_id) and self.routine(automation_id) is None:
                continue  # uma automação comum já usa este id: a rotina segue no .md (o agendador antigo cuida)
            try:
                if not self._exists(automation_id):
                    self.store.create(routine.name, self.flow(routine.to_dict(), routine.created or time.time()), automation_id=automation_id)
                if self.store.published(automation_id) is None:
                    self.store.publish(automation_id)
                last = self.legacy.last_handled(routine.id)
                self.engine.import_state(automation_id, routine.active, routine.created or time.time(), last.timestamp() if last else None)
                self.legacy.mark_migrated(routine.id, automation_id)
            except (ValueError, OSError):  # rotina que não abre fica como estava (o agendador antigo cuida)
                continue
            done.append(automation_id)
        return done
