"""ClickUp no kanban (v0.9.8): as tarefas de uma lista do ClickUp ao lado das Próximas ações.

Pela API REST v2 (`https://api.clickup.com/api/v2`), que tem formato documentado; o MCP do
ClickUp fica para os agentes. O token é o pessoal (pk_…) que o Pedro cola na conta, guardado
no Keychain como `conector:<conta>:api`, ou, sem ele, o `access_token` do login da conta.
A ligação projeto → lista mora em ~/.harness/kanban.json.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import httpx

API = "https://api.clickup.com/api/v2"
LISTS_TTL = 5 * 60
REFUSED_LOGIN = "o ClickUp recusou o token do login para o kanban: cole um token pessoal (pk_…) na conta"


class ClickupError(RuntimeError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _epoch(value: Any) -> float | None:
    """O ClickUp manda datas em milissegundos, como texto."""
    try:
        return int(value) / 1000 if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def task_view(task: dict) -> dict:
    status = task.get("status") or {}
    priority = task.get("priority") or {}
    return {
        "id": str(task.get("id", "")),
        "nome": task.get("name") or "",
        "status": status.get("status") or "",
        "cor": status.get("color") or "",
        "url": task.get("url") or "",
        "responsaveis": [a.get("username") or a.get("email") or "" for a in task.get("assignees") or [] if isinstance(a, dict)],
        "prazo": _epoch(task.get("due_date")),
        "prioridade": priority.get("priority") if isinstance(priority, dict) else None,
        "_criada": _epoch(task.get("date_created")) or 0,
    }


class ClickupBoard:
    """A API do ClickUp para o kanban e as ligações dos projetos."""

    def __init__(self, home: Path, connectors, http: Callable[[], httpx.Client] | None = None) -> None:
        self.path = home / "kanban.json"
        self.connectors = connectors
        self.http = http or connectors.http
        self._lists: dict[str, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()

    # --- credenciais ---------------------------------------------------------------

    def _account(self, account_id: str):
        account = self.connectors.get(account_id)  # ConnectorError se não existe
        if account.kind != "clickup":
            raise ClickupError(f"{account.name} não é uma conta do ClickUp")
        return account

    def has_personal(self, account_id: str) -> bool:
        self._account(account_id)
        return bool(self.connectors.vault.get(f"conector:{account_id}:api"))

    def _token(self, account_id: str) -> tuple[str, bool]:
        """(token, é o pessoal?)."""
        self._account(account_id)
        personal = self.connectors.vault.get(f"conector:{account_id}:api")
        if personal:
            return personal, True
        getter = getattr(self.connectors, "access_token", None)
        if callable(getter):
            return getter(account_id), False
        raw = self.connectors.secret(account_id)
        try:
            return json.loads(raw)["access_token"], False
        except (ValueError, KeyError, TypeError):
            return raw, False

    def _call(self, method: str, path: str, token: str, personal: bool, **kwargs) -> dict:
        try:
            with self.http() as client:
                response = client.request(method, f"{API}{path}", headers={"Authorization": token}, **kwargs)
        except httpx.HTTPError as exc:
            raise ClickupError(f"o ClickUp não respondeu: {exc}", 502) from exc
        if response.status_code == 401:
            raise ClickupError(REFUSED_LOGIN if not personal else "o ClickUp recusou o token pessoal desta conta; cole um novo", 409)
        if response.status_code >= 400:
            try:
                detail = response.json().get("err") or response.text
            except ValueError:
                detail = response.text
            raise ClickupError(f"ClickUp {response.status_code}: {str(detail)[:200]}", 404 if response.status_code == 404 else 400)
        try:
            return response.json()
        except ValueError as exc:
            raise ClickupError("o ClickUp respondeu algo que não é JSON", 502) from exc

    def _get(self, account_id: str, path: str, **params) -> dict:
        token, personal = self._token(account_id)
        return self._call("GET", path, token, personal, params=params or None)

    def set_personal(self, account_id: str, token: str) -> None:
        self._account(account_id)
        token = token.strip()
        self._call("GET", "/user", token, True)  # recusado: 409 com o motivo
        self.connectors.vault.set(f"conector:{account_id}:api", token)
        self._lists.pop(account_id, None)

    def drop_personal(self, account_id: str) -> None:
        self._account(account_id)
        self.connectors.vault.delete(f"conector:{account_id}:api")
        self._lists.pop(account_id, None)

    # --- listas, tarefas e status ---------------------------------------------------------

    def lists(self, account_id: str) -> list[dict]:
        cached = self._lists.get(account_id)
        if cached and time.time() - cached[0] < LISTS_TTL:
            return cached[1]
        token, personal = self._token(account_id)

        def get(path: str) -> dict:
            return self._call("GET", path, token, personal, params={"archived": "false"})

        teams = self._call("GET", "/team", token, personal).get("teams") or []
        spaces = [(team, space) for team in teams for space in get(f"/team/{team['id']}/space").get("spaces") or []]

        def of_space(pair: tuple[dict, dict]) -> list[dict]:
            team, space = pair
            found: list[dict] = []
            for folder in get(f"/space/{space['id']}/folder").get("folders") or []:
                for item in folder.get("lists") or []:
                    found.append({"id": str(item["id"]), "nome": item.get("name", ""), "workspace": team.get("name", ""), "espaco": space.get("name", ""), "pasta": folder.get("name", "")})
            for item in get(f"/space/{space['id']}/list").get("lists") or []:
                found.append({"id": str(item["id"]), "nome": item.get("name", ""), "workspace": team.get("name", ""), "espaco": space.get("name", ""), "pasta": ""})
            return found

        # Os espaços ao mesmo tempo (antes, uma requisição depois da outra); a ordem fica a mesma.
        with ThreadPoolExecutor(max_workers=6) as pool:
            out = [item for found in pool.map(of_space, spaces) for item in found]
        self._lists[account_id] = (time.time(), out)
        return out

    def tasks(self, account_id: str, list_id: str) -> list[dict]:
        raw = self._get(account_id, f"/list/{list_id}/task", archived="false", include_closed="false", page="0", subtasks="true").get("tasks") or []
        items = sorted((task_view(t) for t in raw), key=lambda t: t["_criada"], reverse=True)[:100]
        for item in items:
            item.pop("_criada", None)
        return items

    def statuses(self, account_id: str, list_id: str) -> list[dict]:
        data = self._get(account_id, f"/list/{list_id}")
        return [
            {"nome": s.get("status", ""), "cor": s.get("color", ""), "tipo": s.get("type", "")}
            for s in sorted(data.get("statuses") or [], key=lambda s: s.get("orderindex", 0))
        ]

    def set_status(self, account_id: str, task_id: str, status: str) -> dict:
        token, personal = self._token(account_id)
        data = self._call("PUT", f"/task/{task_id}", token, personal, json={"status": status})
        view = task_view(data)
        view.pop("_criada", None)
        return view

    # --- ligação projeto → lista ------------------------------------------------------

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"projetos": {}}
        if not isinstance(data, dict) or not isinstance(data.get("projetos"), dict):
            return {"projetos": {}}
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def link(self, project: str) -> dict | None:
        found = self._load()["projetos"].get(project, {}).get("clickup")
        return found if isinstance(found, dict) else None

    def set_link(self, project: str, account_id: str, list_id: str, name: str) -> dict:
        self._account(account_id)
        with self._lock:
            data = self._load()
            entry = data["projetos"].setdefault(project, {})
            entry["clickup"] = {"conta": account_id, "lista": str(list_id), "nome": name.strip()}
            self._save(data)
            return entry["clickup"]

    def drop_link(self, project: str) -> None:
        with self._lock:
            data = self._load()
            entry = data["projetos"].get(project)
            if entry and "clickup" in entry:
                entry.pop("clickup")
                if not entry:
                    data["projetos"].pop(project)
                self._save(data)

    def board(self, project: str) -> dict:
        link = self.link(project)
        if not link:
            return {"ligacao": None, "tarefas": [], "status": []}
        return {
            "ligacao": link,
            "tarefas": self.tasks(link["conta"], link["lista"]),
            "status": self.statuses(link["conta"], link["lista"]),
        }
