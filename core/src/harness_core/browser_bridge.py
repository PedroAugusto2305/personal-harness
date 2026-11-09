"""Navegador da MÊTIS do lado do núcleo (v0.9.8): a ponte com a janela, o histórico e os perfis.

O navegador é um WebKit nativo de cada aba, que só a janela alcança. Quando um agente pede
pela central de MCP (navegador_ler, navegador_clicar…), o núcleo publica
`{"type": "browser.command", …}` e espera a janela responder em
`POST /navegador/resposta/{id}`. As ferramentas do MCP rodam numa thread
(`asyncio.to_thread`), então a espera é bloqueante e segura para thread; a resposta chega
pelo loop do servidor.

Histórico: as páginas que a janela carregou, para o ⌘K sugerir endereços. Perfis: cada um
é um cofre de cookies do WebKit (o identificador de 16 bytes vai ao `data_store_identifier`);
o "Padrão" é o cofre de sempre e não se apaga.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from pydantic import BaseModel

CLOSED = "A janela da MÊTIS está fechada: o navegador só funciona com ela aberta. Peça ao Pedro para abrir a MÊTIS."
HISTORY_MAX = 5000
PROFILE_NAME_MAX = 40


class BridgeError(RuntimeError):
    pass


# --- corpo das rotas -----------------------------------------------------------------------


class BrowserAnswer(BaseModel):
    ok: bool
    resultado: Any = None
    erro: str | None = None


class HistoryVisit(BaseModel):
    url: str
    titulo: str | None = None


class ProfileBody(BaseModel):
    nome: str


class ImportBody(BaseModel):
    fonte: str
    dominios: list[str] | None = None


# --- endereço ------------------------------------------------------------------------------

LOCAL_HOST = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0|[\w.-]+\.local|[\w.-]+\.localhost)(:\d+)?([/?#].*)?$", re.I)
BARE_HOST = re.compile(r"^[\w-]+(\.[\w-]+)+(:\d+)?([/?#].*)?$")


def normalize_url(text: str) -> str:
    """"localhost:3000" e ":3000" → http://localhost…; "exemplo.com" → https://…. Só http, https e about:blank."""
    value = (text or "").strip()
    if not value:
        raise ValueError("diga o endereço (url)")
    if value.lower() == "about:blank":
        return "about:blank"
    if re.match(r"^https?://", value, re.I):
        return value
    if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", value, re.I):
        raise ValueError("só abro http, https ou about:blank")
    if re.fullmatch(r":\d{2,5}([/?#].*)?", value):
        return f"http://localhost{value}"
    if re.fullmatch(r"\d{2,5}", value):
        return f"http://localhost:{value}"
    if LOCAL_HOST.match(value):
        return f"http://{value}"
    if " " not in value and BARE_HOST.match(value):
        return f"https://{value}"
    raise ValueError(f"endereço inválido: {value}")


# --- ponte -----------------------------------------------------------------------------------


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    resultado: Any = None
    erro: str | None = None


class BrowserBridge:
    """Pedido do agente → janela → resposta. `events` é o EventBus do núcleo."""

    def __init__(self, events: Any) -> None:
        self.events = events
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()

    def request(self, session: str, who: str, cwd: str | None, action: str, args: dict, timeout: float = 30) -> Any:
        """Bloqueia até a janela responder (não chame do loop do servidor)."""
        if self.events.listeners == 0:
            raise BridgeError(CLOSED)
        request_id = secrets.token_hex(6)
        pending = _Pending()
        with self._lock:
            self._pending[request_id] = pending
        try:
            self.events.publish(
                {"type": "browser.command", "id": request_id, "session": session, "who": who, "cwd": cwd, "action": action, "args": args}
            )
            if not pending.event.wait(timeout):
                seconds = int(timeout) if float(timeout).is_integer() else round(timeout, 1)
                raise BridgeError(f"A janela não respondeu em {seconds} s.")
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        if not pending.ok:
            raise BridgeError(pending.erro or "a janela não conseguiu fazer isso")
        return pending.resultado

    def resolve(self, request_id: str, ok: bool, resultado: Any = None, erro: str | None = None) -> bool:
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None or pending.event.is_set():
                return False
            pending.ok, pending.resultado, pending.erro = bool(ok), resultado, erro
            pending.event.set()
        return True

    @property
    def waiting(self) -> int:
        with self._lock:
            return len(self._pending)


# --- histórico -------------------------------------------------------------------------------


def fold(text: str) -> str:
    """Minúsculas e sem acento, para a busca."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


class BrowserHistory:
    """~/.harness/navegador.db: uma linha por endereço, com visitas e a última vez."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS historico (url TEXT PRIMARY KEY, titulo TEXT NOT NULL DEFAULT '', visitas INTEGER NOT NULL DEFAULT 0,"
                " ultima REAL NOT NULL, busca TEXT NOT NULL DEFAULT '')"
            )
            db.execute("CREATE INDEX IF NOT EXISTS historico_ultima ON historico (ultima)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def visit(self, url: str, titulo: str | None = None, now: float | None = None) -> bool:
        """Guarda a visita; False para o que não é http nem https."""
        url = (url or "").strip()
        if not re.match(r"^https?://", url, re.I) or len(url) > 4000:
            return False
        when = time.time() if now is None else now
        title = (titulo or "").strip()[:300]
        with self._lock, self._connect() as db:
            row = db.execute("SELECT titulo FROM historico WHERE url = ?", (url,)).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO historico (url, titulo, visitas, ultima, busca) VALUES (?, ?, 1, ?, ?)",
                    (url, title, when, fold(f"{url} {title}")),
                )
            else:
                title = title or row[0]
                db.execute(
                    "UPDATE historico SET titulo = ?, visitas = visitas + 1, ultima = ?, busca = ? WHERE url = ?",
                    (title, when, fold(f"{url} {title}"), url),
                )
            extra = db.execute("SELECT COUNT(*) FROM historico").fetchone()[0] - HISTORY_MAX
            if extra > 0:
                db.execute("DELETE FROM historico WHERE url IN (SELECT url FROM historico ORDER BY ultima ASC LIMIT ?)", (extra,))
        return True

    def search(self, q: str = "", limit: int = 20) -> list[dict]:
        limit = max(1, min(100, int(limit)))
        needle = fold(q).strip()
        with self._lock, self._connect() as db:
            if not needle:
                rows = db.execute("SELECT url, titulo, visitas, ultima FROM historico ORDER BY ultima DESC LIMIT ?", (limit,)).fetchall()
            else:
                pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                rows = db.execute(
                    "SELECT url, titulo, visitas, ultima FROM historico WHERE busca LIKE ? ESCAPE '\\' ORDER BY ultima DESC LIMIT 500",
                    (pattern,),
                ).fetchall()
        items = [{"url": r[0], "titulo": r[1], "visitas": r[2], "ultima": r[3]} for r in rows]
        if needle:
            # O host que começa com o que foi digitado vem primeiro (a ordem por data se mantém dentro de cada grupo).
            items.sort(key=lambda item: not (_host(item["url"]).startswith(needle) or fold(item["url"]).split("://", 1)[-1].startswith(needle)))
        return items[:limit]

    def clear(self) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM historico")


# --- perfis ----------------------------------------------------------------------------------

DEFAULT_PROFILE = {"id": "padrao", "nome": "Padrão", "identificador": None, "criado": None}


class ProfileError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-") or "perfil"


class BrowserProfiles:
    """~/.harness/navegador.json: os perfis criados (o Padrão é fixo e não fica no arquivo)."""

    def __init__(self, home: Path, publish: Callable[[dict], None] = lambda _e: None) -> None:
        self.path = home / "navegador.json"
        self.publish = publish
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("perfis") if isinstance(data, dict) else None
        return [p for p in items or [] if isinstance(p, dict) and p.get("id") and p.get("id") != "padrao"]

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".navegador-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"perfis": items}, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(DEFAULT_PROFILE)] + self._load()

    @staticmethod
    def _name(nome: str) -> str:
        name = " ".join((nome or "").split())
        if not name or len(name) > PROFILE_NAME_MAX:
            raise ProfileError(f"o nome do perfil tem de 1 a {PROFILE_NAME_MAX} caracteres")
        return name

    def create(self, nome: str) -> dict:
        name = self._name(nome)
        with self._lock:
            items = self._load()
            if fold(name) in {fold(p.get("nome", "")) for p in items} | {fold(DEFAULT_PROFILE["nome"])}:
                raise ProfileError(f"já existe um perfil chamado {name}", 409)
            base = _slug(name)
            taken = {p["id"] for p in items} | {"padrao"}
            profile_id, n = base, 2
            while profile_id in taken:
                profile_id, n = f"{base}-{n}", n + 1
            profile = {
                "id": profile_id,
                "nome": name,
                "identificador": secrets.token_bytes(16).hex(),
                "criado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            items.append(profile)
            self._save(items)
        self.publish({"type": "navegador.perfis"})
        return profile

    def rename(self, profile_id: str, nome: str) -> dict:
        if profile_id == "padrao":
            raise ProfileError("o perfil Padrão não muda de nome")
        name = self._name(nome)
        with self._lock:
            items = self._load()
            target = next((p for p in items if p["id"] == profile_id), None)
            if target is None:
                raise ProfileError("perfil não encontrado", 404)
            others = {fold(p.get("nome", "")) for p in items if p["id"] != profile_id} | {fold(DEFAULT_PROFILE["nome"])}
            if fold(name) in others:
                raise ProfileError(f"já existe um perfil chamado {name}", 409)
            target["nome"] = name
            self._save(items)
        self.publish({"type": "navegador.perfis"})
        return target

    def delete(self, profile_id: str) -> None:
        if profile_id == "padrao":
            raise ProfileError("o perfil Padrão não se apaga")
        with self._lock:
            items = self._load()
            kept = [p for p in items if p["id"] != profile_id]
            if len(kept) == len(items):
                raise ProfileError("perfil não encontrado", 404)
            self._save(kept)
        self.publish({"type": "navegador.perfis"})
