"""Google na MÊTIS (v0.9.8): Gmail, Agenda e Drive pelas APIs públicas, como o Slack.

Os MCPs oficiais do Google Workspace ainda estão em prévia fechada, então a MÊTIS fala direto
com as APIs, com o login do cliente OAuth "App para computador" que o Pedro cria uma vez no
Google Cloud. O token é renovado pelo refresh_token (ConnectorStore.access_token).
"""

from __future__ import annotations

import base64
import html
import re
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from typing import Callable
from urllib.parse import quote

import httpx

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3"
DRIVE = "https://www.googleapis.com/drive/v3"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
LIMIT = 20000
#: Busca do Drive já escrita na sintaxe dele: campo, operador e valor ("name = 'x'",
#: "mimeType != 'y'", "trashed = false") ou "'id' in parents". Texto solto (até com a
#: palavra contains no meio) vira busca por nome e conteúdo.
_DRIVE_QUERY = re.compile(
    r"\b(?:name|fullText|mimeType|modifiedTime|viewedByMeTime|createdTime|trashed|starred|sharedWithMe|visibility|properties|appProperties)"
    r"\s*(?:contains|!=|<=|>=|=|<|>|has)\s*(?:'|\{|true\b|false\b)"
    r"|'[^']*'\s+in\s+(?:parents|owners|writers|readers)\b"
)


class GoogleError(RuntimeError):
    pass


def _cut(text: str, limit: int = LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… (cortado em {limit} caracteres)"


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def _body(payload: dict) -> str:
    """O texto puro do e-mail: o text/plain, ou o HTML sem as etiquetas."""
    plain: list[str] = []
    rich: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64(data))
        elif data and mime == "text/html":
            rich.append(_b64(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    return _strip_html("\n".join(rich))


def _part(value: str) -> str:
    """Id dentro do endereço, codificado: o das agendas de feriados tem # (que cortaria a URL)."""
    return quote(str(value).strip(), safe="")


def _headers(message: dict) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in (message.get("payload") or {}).get("headers", [])}


def _when(value: str) -> dict:
    """"2026-11-10" vira dia inteiro; data e hora vira dateTime (sem fuso: o de São Paulo)."""
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return {"date": value}
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoogleError(f"data inválida: {value} (use AAAA-MM-DD ou AAAA-MM-DDTHH:MM)") from exc
    if moment.tzinfo is None:
        return {"dateTime": moment.isoformat(timespec="seconds"), "timeZone": "America/Sao_Paulo"}
    return {"dateTime": moment.isoformat(timespec="seconds")}


def _rfc3339(value: str | None, fallback: datetime, end: bool = False) -> str:
    """Instante para a API. Só a data, como fim (end), vale até o fim daquele dia: "até
    2026-11-10" inclui o dia 10 (o Google trata o fim como exclusivo)."""
    if value:
        value = value.strip()
        day_only = re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
        if day_only:
            value += "T00:00:00"
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GoogleError(f"data inválida: {value}") from exc
        if day_only and end:
            moment += timedelta(days=1)
    else:
        moment = fallback
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat(timespec="seconds")


class Google:
    def __init__(self, token: Callable[[], str], refresh: Callable[[], str], http: httpx.Client) -> None:
        self._token = token
        self._refresh = refresh
        self.http = http

    def close(self) -> None:
        self.http.close()

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        token = self._token()
        for attempt in range(2):
            response = self.http.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
            if response.status_code == 401 and attempt == 0:
                token = self._refresh()  # o access_token do Google vale cerca de 1 hora
                continue
            break
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
            except ValueError:
                message = response.text[:200]
            raise GoogleError(f"{response.status_code}: {message}")
        return response

    def _json(self, method: str, url: str, **kwargs) -> dict:
        data = self._send(method, url, **kwargs).json()
        return data if isinstance(data, dict) else {}

    # --- conta ---------------------------------------------------------------------

    def userinfo(self) -> dict:
        return self._json("GET", USERINFO)

    def check(self) -> list[str]:
        """Uma chamada barata em cada serviço; devolve os que falharam (com o motivo)."""
        problems = []
        for name, url, params in (
            ("Gmail", f"{GMAIL}/profile", None),
            ("Agenda", f"{CALENDAR}/calendars/primary/events", {"maxResults": 1}),
            ("Drive", f"{DRIVE}/files", {"pageSize": 1}),
        ):
            try:
                self._send("GET", url, params=params)
            except (GoogleError, httpx.HTTPError) as exc:
                problems.append(f"{name}: {exc}")
        return problems

    # --- Gmail ---------------------------------------------------------------------

    def gmail_search(self, query: str, limit: int = 10) -> list[dict]:
        found = self._json("GET", f"{GMAIL}/messages", params={"q": query, "maxResults": max(1, min(int(limit), 50))})
        out = []
        for item in found.get("messages", []):
            message = self._json(
                "GET",
                f"{GMAIL}/messages/{_part(item['id'])}",
                params=[("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject"), ("metadataHeaders", "Date")],
            )
            head = _headers(message)
            out.append({"id": item["id"], "de": head.get("from", ""), "assunto": head.get("subject", ""), "data": head.get("date", ""), "trecho": html.unescape(message.get("snippet", ""))})
        return out

    def gmail_read(self, message_id: str) -> str:
        message = self._json("GET", f"{GMAIL}/messages/{_part(message_id)}", params={"format": "full"})
        head = _headers(message)
        top = "\n".join(f"{label}: {head.get(key, '')}" for label, key in (("De", "from"), ("Para", "to"), ("Assunto", "subject"), ("Data", "date")) if head.get(key))
        return _cut(f"{top}\n\n{_body(message.get('payload') or {})}")

    def gmail_draft(self, to: str, subject: str, body: str) -> dict:
        mail = EmailMessage()
        mail["To"] = to
        mail["Subject"] = subject
        mail.set_content(body)
        raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
        return self._json("POST", f"{GMAIL}/drafts", json={"message": {"raw": raw}})

    # --- Agenda --------------------------------------------------------------------

    def events(self, start: str | None = None, end: str | None = None, limit: int = 20, calendar: str = "primary") -> list[dict]:
        today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        params = {
            "timeMin": _rfc3339(start, today),
            "timeMax": _rfc3339(end, today + timedelta(days=7), end=True),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max(1, min(int(limit), 100)),
        }
        data = self._json("GET", f"{CALENDAR}/calendars/{_part(calendar or 'primary')}/events", params=params)
        out = []
        for item in data.get("items", []):
            start_at = item.get("start") or {}
            end_at = item.get("end") or {}
            out.append(
                {
                    "id": item.get("id"),
                    "titulo": item.get("summary", "(sem título)"),
                    "inicio": start_at.get("dateTime") or start_at.get("date"),
                    "fim": end_at.get("dateTime") or end_at.get("date"),
                    "local": item.get("location", ""),
                    "link": item.get("htmlLink", ""),
                    "convidados": [a.get("email") for a in item.get("attendees", []) if a.get("email")],
                }
            )
        return out

    def create_event(self, title: str, start: str, end: str, description: str = "", guests: list[str] | None = None, calendar: str = "primary") -> dict:
        body: dict = {"summary": title, "start": _when(start), "end": _when(end)}
        # Dia inteiro: o Google quer o fim no dia seguinte ao último. Fim igual ao início (ou
        # antes dele) seria recusado; vira um dia só.
        if "date" in body["start"] and "date" in body["end"] and body["end"]["date"] <= body["start"]["date"]:
            body["end"] = {"date": (date.fromisoformat(body["start"]["date"]) + timedelta(days=1)).isoformat()}
        if description:
            body["description"] = description
        if guests:
            body["attendees"] = [{"email": g} for g in guests]
        return self._json("POST", f"{CALENDAR}/calendars/{_part(calendar or 'primary')}/events", json=body)

    # --- Drive ---------------------------------------------------------------------

    def drive_search(self, query: str, limit: int = 10) -> list[dict]:
        query = query.strip()
        if not _DRIVE_QUERY.search(query):
            safe = query.replace("\\", "\\\\").replace("'", "\\'")
            query = f"(name contains '{safe}' or fullText contains '{safe}') and trashed = false"
        data = self._json(
            "GET",
            f"{DRIVE}/files",
            params={"q": query, "pageSize": max(1, min(int(limit), 50)), "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"},
        )
        return [
            {"id": f.get("id"), "nome": f.get("name"), "tipo": f.get("mimeType"), "alterado": f.get("modifiedTime"), "link": f.get("webViewLink")}
            for f in data.get("files", [])
        ]

    def drive_read(self, file_id: str) -> str:
        file_id = _part(file_id)
        meta = self._json("GET", f"{DRIVE}/files/{file_id}", params={"fields": "id,name,mimeType,modifiedTime,webViewLink,size"})
        mime = meta.get("mimeType", "")
        exports = {
            "application/vnd.google-apps.document": "text/plain",
            "application/vnd.google-apps.spreadsheet": "text/csv",
            "application/vnd.google-apps.presentation": "text/plain",
        }
        head = f"{meta.get('name', '')} ({mime})\n{meta.get('webViewLink', '')}\n\n"
        if mime in exports:
            text = self._send("GET", f"{DRIVE}/files/{file_id}/export", params={"mimeType": exports[mime]}).text
            return _cut(head + text)
        if mime.startswith("text/") or mime in ("application/json", "application/xml"):
            return _cut(head + self._send("GET", f"{DRIVE}/files/{file_id}", params={"alt": "media"}).text)
        size = meta.get("size")
        return head + f"Arquivo {mime or 'sem tipo'}" + (f" de {int(size) // 1024} KB" if size else "") + ": abra pelo link (a MÊTIS só lê documentos, planilhas, apresentações e texto)."
