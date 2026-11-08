"""Quando, em português: "sexta 9h", "amanhã 14:30", "em 20 min", "13/11 às 9", ISO.

Usado por `metis lembrete` e pela ferramenta lembrete dos agentes. Data sem hora vale 9h.
Hora sem data vale hoje, ou amanhã se já passou.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

WEEKDAYS = {
    "segunda": 0, "seg": 0, "terca": 1, "ter": 1, "quarta": 2, "qua": 2, "quinta": 3, "qui": 3,
    "sexta": 4, "sex": 4, "sabado": 5, "sab": 5, "domingo": 6, "dom": 6,
}  # fmt: skip
UNITS = {"min": 1, "minuto": 1, "minutos": 1, "m": 1, "h": 60, "hora": 60, "horas": 60, "dia": 1440, "dias": 1440, "d": 1440}
DEFAULT_HOUR = 9


class WhenError(ValueError):
    pass


def _fold(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.replace("-feira", "").replace(",", " ")).strip()


def _time(text: str) -> tuple[int, int] | None:
    """'9h', '9h30', '09:30', 'as 9', '18' → (hora, minuto)."""
    candidates = re.findall(r"\b(\d{1,2})(?:h(\d{2})?|:(\d{2}))", text)
    if candidates:
        hour, m1, m2 = candidates[-1]
        return int(hour), int(m1 or m2 or 0)
    match = re.search(r"\bas\s+(\d{1,2})\b", text)
    if match:
        return int(match.group(1)), 0
    return None


def parse_when(text: str, now: datetime | None = None) -> datetime:
    now = (now or datetime.now().astimezone()).replace(second=0, microsecond=0)
    raw = text.strip()
    if not raw:
        raise WhenError("diga quando: ex. \"sexta 9h\", \"amanhã 14:30\", \"em 20 min\"")
    # ISO: 2026-11-13, 2026-11-13 09:30, 2026-11-13T09:30(:00)(±03:00)
    try:
        iso = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if len(raw) <= 10:
            iso = iso.replace(hour=DEFAULT_HOUR)
        result = iso if iso.tzinfo else iso.replace(tzinfo=now.tzinfo)
        return _future(result, now)
    except ValueError:
        pass
    t = _fold(raw)

    relative = re.search(r"(?:em|daqui a|daqui|\+)\s*(\d+)\s*(minutos|minuto|min|m|horas|hora|h|dias|dia|d)\b", t)
    if relative:
        return now + timedelta(minutes=int(relative.group(1)) * UNITS[relative.group(2)])

    clock = _time(re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", " ", t))
    hour, minute = clock if clock else (DEFAULT_HOUR, 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise WhenError(f"hora inválida em \"{text}\"")

    date = None
    explicit = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if explicit:
        day, month, year = int(explicit.group(1)), int(explicit.group(2)), explicit.group(3)
        year_n = int(year) + (2000 if year and len(year) == 2 else 0) if year else now.year
        try:
            date = now.replace(year=year_n, month=month, day=day, hour=hour, minute=minute)
        except ValueError as exc:
            raise WhenError(f"data inválida em \"{text}\"") from exc
        if not year and date < now:
            date = date.replace(year=now.year + 1)
    elif "depois de amanha" in t:
        date = (now + timedelta(days=2)).replace(hour=hour, minute=minute)
    elif "amanha" in t:
        date = (now + timedelta(days=1)).replace(hour=hour, minute=minute)
    elif "hoje" in t:
        date = now.replace(hour=hour, minute=minute)
    else:
        day_name = next((d for d in WEEKDAYS if re.search(rf"\b{d}\b", t)), None)
        if day_name is not None:
            ahead = (WEEKDAYS[day_name] - now.weekday()) % 7
            date = (now + timedelta(days=ahead)).replace(hour=hour, minute=minute)
            if date <= now:
                date += timedelta(days=7)
        elif clock:
            date = now.replace(hour=hour, minute=minute)
            if date <= now:
                date += timedelta(days=1)
    if date is None:
        raise WhenError(f"não entendi quando é \"{text}\": use \"sexta 9h\", \"amanhã 14:30\", \"13/11 9h\" ou \"em 20 min\"")
    return _future(date, now)


def _future(date: datetime, now: datetime) -> datetime:
    if date <= now:
        raise WhenError(f"{date:%d/%m %H:%M} já passou")
    return date
