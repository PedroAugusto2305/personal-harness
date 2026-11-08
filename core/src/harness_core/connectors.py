"""Galeria de conectores: contas do Slack e do ClickUp, várias por ferramenta.

O arquivo ~/.harness/conectores.json guarda só o que não é segredo (nome, workspace, quem é
o Pedro em cada conta); o token vai para o Keychain. Decisão no Brain: "Personal Harness
liga ferramentas por uma galeria de conectores com várias contas".
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from .accounts import slugify
from .keychain import Vault
from .mcp_client import McpClient
from .oauth import OAuthError, OAuthStart, begin, finish
from .slack import Slack, SlackError

CATALOG: dict[str, dict] = {
    "slack": {
        "name": "Slack",
        "auth": "token",
        "description": "Bot da MÊTIS no workspace: mensagens e lembretes na sua DM, que tocam no iPhone.",
    },
    "clickup": {
        "name": "ClickUp",
        "auth": "oauth",
        "url": "https://mcp.clickup.com/mcp",
        "description": "Tarefas, documentos e chat pelo MCP oficial do ClickUp.",
    },
}
OAUTH_TTL = 15 * 60


class ConnectorError(ValueError):
    pass


@dataclass
class ConnectorAccount:
    id: str
    kind: str
    name: str
    created: float
    meta: dict = field(default_factory=dict)
    #: Escrever nesta conta (mensagem a outras pessoas, criar ou mudar tarefa) pede aprovação.
    approve_writes: bool = True
    #: Conta usada por `metis lembrete` e pela ferramenta lembrete dos agentes.
    reminders: bool = False

    def to_dict(self) -> dict:
        return {**asdict(self), "service": CATALOG[self.kind]["name"]}


class ConnectorStore:
    def __init__(self, home: Path, vault: Vault, http: Callable[[], httpx.Client] | None = None) -> None:
        self.path = home / "conectores.json"
        self.vault = vault
        self.http = http or (lambda: httpx.Client(timeout=httpx.Timeout(30, connect=10)))
        self._pending: dict[str, tuple[OAuthStart, str, str, float]] = {}
        self._clients: dict[str, McpClient] = {}
        self._lock = threading.Lock()

    # --- arquivo -------------------------------------------------------------

    def _load(self) -> list[ConnectorAccount]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out = []
        for item in data if isinstance(data, list) else []:
            try:
                out.append(ConnectorAccount(**item))
            except TypeError:
                continue
        return [a for a in out if a.kind in CATALOG]

    def _save(self, accounts: list[ConnectorAccount]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(a) for a in accounts], ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list(self) -> list[ConnectorAccount]:
        return self._load()

    def get(self, account_id: str) -> ConnectorAccount:
        for account in self._load():
            if account.id == account_id:
                return account
        raise ConnectorError(f"conta de conector desconhecida: {account_id}")

    def _new_id(self, kind: str, name: str) -> str:
        taken = {a.id for a in self._load()}
        base = slugify(name)[:22] or kind
        if not base.startswith(kind):
            base = f"{kind}-{base}"[:22].rstrip("-")
        account_id, n = base, 2
        while account_id in taken:
            account_id, n = f"{base}-{n}", n + 1
        return account_id

    def _add(self, account: ConnectorAccount, secret: str) -> ConnectorAccount:
        with self._lock:
            accounts = self._load()
            if account.kind == "slack" and not any(a.reminders for a in accounts):
                account.reminders = True  # a primeira conta do Slack recebe os lembretes
            self.vault.set(f"conector:{account.id}", secret)
            accounts.append(account)
            self._save(accounts)
        return account

    def update(self, account_id: str, **changes) -> ConnectorAccount:
        with self._lock:
            accounts = self._load()
            target = next((a for a in accounts if a.id == account_id), None)
            if target is None:
                raise ConnectorError(f"conta de conector desconhecida: {account_id}")
            if changes.get("reminders"):
                for a in accounts:
                    a.reminders = False
            for key in ("name", "approve_writes", "reminders"):
                if key in changes and changes[key] is not None:
                    setattr(target, key, changes[key])
            self._save(accounts)
            return target

    def remove(self, account_id: str) -> None:
        with self._lock:
            accounts = self._load()
            kept = [a for a in accounts if a.id != account_id]
            if len(kept) == len(accounts):
                raise ConnectorError(f"conta de conector desconhecida: {account_id}")
            self.vault.delete(f"conector:{account_id}")
            self._clients.pop(account_id, None)
            self._save(kept)

    def secret(self, account_id: str) -> str:
        value = self.vault.get(f"conector:{account_id}")
        if not value:
            raise ConnectorError("o token desta conta sumiu do Keychain; conecte de novo")
        return value

    # --- Slack (token do bot colado pelo Pedro) ---------------------------------------

    def add_slack(self, name: str, token: str, email: str) -> ConnectorAccount:
        token, email = token.strip(), email.strip()
        if not token.startswith("xoxb-"):
            raise ConnectorError("o token do bot do Slack começa com xoxb- (OAuth & Permissions → Bot User OAuth Token)")
        slack = Slack(token, self.http())
        try:
            identity = slack.identity()
            person = slack.user_by_email(email)
            dm = slack.dm(person["id"])
        except SlackError as exc:
            raise ConnectorError(str(exc)) from exc
        account = ConnectorAccount(
            id=self._new_id("slack", name),
            kind="slack",
            name=name.strip() or f"Slack {identity['team']}",
            created=time.time(),
            meta={"team": identity["team"], "team_id": identity["team_id"], "bot": identity["bot"], "user_id": person["id"], "user_name": person["name"], "dm": dm, "email": email},
        )
        return self._add(account, token)

    def slack(self, account_id: str) -> tuple[ConnectorAccount, Slack]:
        account = self.get(account_id)
        if account.kind != "slack":
            raise ConnectorError(f"{account.name} não é uma conta do Slack")
        return account, Slack(self.secret(account_id), self.http())

    # --- MCP remoto com OAuth (ClickUp) -----------------------------------------------

    def start_oauth(self, kind: str, name: str, redirect_uri: str) -> str:
        spec = CATALOG.get(kind)
        if not spec or spec["auth"] != "oauth":
            raise ConnectorError(f"{kind} não conecta por login no navegador")
        now = time.time()
        self._pending = {s: p for s, p in self._pending.items() if now - p[3] < OAUTH_TTL}
        try:
            start = begin(self.http(), spec["url"], redirect_uri)
        except (OAuthError, httpx.HTTPError) as exc:
            raise ConnectorError(str(exc)) from exc
        self._pending[start.state] = (start, kind, name.strip() or spec["name"], now)
        return start.authorize_url

    def finish_oauth(self, state: str, code: str) -> ConnectorAccount:
        pending = self._pending.pop(state, None)
        if pending is None or time.time() - pending[3] > OAUTH_TTL:
            raise ConnectorError("este login expirou ou já foi usado; clique em Conectar de novo")
        start, kind, name, _ = pending
        try:
            tokens = finish(self.http(), start, code)
            client = McpClient(CATALOG[kind]["url"], tokens["access_token"], self.http())
            tools = client.tools()
        except (OAuthError, httpx.HTTPError, RuntimeError) as exc:
            raise ConnectorError(str(exc)) from exc
        account = ConnectorAccount(
            id=self._new_id(kind, name),
            kind=kind,
            name=name,
            created=time.time(),
            meta={"server": client.server.get("name", ""), "tools": len(tools), "client_id": start.client_id},
        )
        account = self._add(account, json.dumps(tokens))
        self._clients[account.id] = client
        return account

    def mcp(self, account_id: str) -> McpClient:
        client = self._clients.get(account_id)
        if client is None:
            account = self.get(account_id)
            raw = self.secret(account_id)
            try:
                token = json.loads(raw)["access_token"]
            except (ValueError, KeyError, TypeError):
                token = raw
            client = McpClient(CATALOG[account.kind]["url"], token, self.http())
            self._clients[account_id] = client
        return client
