"""Galeria de conectores: Slack, ClickUp, Notion, GitHub, Google e MCP próprio, várias contas
por ferramenta.

O arquivo ~/.harness/conectores.json guarda só o que não é segredo (nome, workspace, quem é
o Pedro em cada conta); token, refresh_token, segredo do cliente e as variáveis de um MCP por
stdio vão para o Keychain. Decisão no Brain: "Personal Harness liga ferramentas por uma
galeria de conectores com várias contas".

v0.9.8: o login OAuth guarda o token inteiro (com refresh_token, validade e onde renovar) e
se renova sozinho; um 401 do servidor renova uma vez e repete a chamada.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from . import google as google_api
from .accounts import slugify
from .keychain import Vault
from .mcp_client import McpAuthError, McpClient, McpError
from .oauth import OAuthError, OAuthStart, begin, begin_with_client, discover, finish, refresh
from .slack import Slack, SlackError
from .stdio_client import StdioClient

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
    "notion": {
        "name": "Notion",
        "auth": "oauth",
        "url": "https://mcp.notion.com/mcp",
        "description": "Páginas, bancos de dados e comentários pelo MCP oficial do Notion.",
    },
    "github": {
        "name": "GitHub",
        "auth": "token",
        "url": "https://api.githubcopilot.com/mcp/",
        "description": "Repositórios, issues, PRs e Actions pelo MCP oficial do GitHub, com o login do gh (ou um token).",
    },
    "google": {
        "name": "Google",
        "auth": "google",
        "description": "Gmail, Agenda e Drive da sua conta Google, pelo cliente OAuth que você cria uma vez no Google Cloud.",
    },
    "mcp": {
        "name": "MCP próprio",
        "auth": "mcp",
        "description": "Qualquer servidor MCP: por endereço (HTTP, com ou sem login) ou por comando no Mac (stdio).",
    },
}
OAUTH_TTL = 15 * 60
GOOGLE_CLIENT = "conector:google-cliente"
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env(text: str) -> dict[str, str]:
    """Variáveis de um MCP por stdio, uma por linha (CHAVE=valor); vazias e # são ignoradas."""
    env: dict[str, str] = {}
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _ENV_KEY.match(key):
            raise ConnectorError(f"variável inválida na linha {number}: use CHAVE=valor")
        env[key] = value.strip()
    return env


def _scrub(text: str, *secrets: str) -> str:
    """Tira de uma mensagem qualquer segredo que o servidor tenha devolvido no texto."""
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "***")
    return text


def _mask(command: str, env: dict[str, str]) -> str:
    return _scrub(command, *env.values())


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class ConnectorError(ValueError):
    pass


#: Modos de uma ferramenta de conector (v0.9.9).
TOOL_MODES = ("livre", "aprovacao", "desligada")


def tool_mode(account: "ConnectorAccount | None", name: str, write: bool) -> str:
    """O modo em vigor: o escolhido na tela, senão escrita pede aprovação (se a conta pede)."""
    chosen = (account.tool_modes or {}).get(name) if account else None
    if chosen in TOOL_MODES:
        return chosen
    if write and (account.approve_writes if account else True):
        return "aprovacao"
    return "livre"


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
    #: v0.9.9: modo por ferramenta ("livre", "aprovacao" ou "desligada"); sem entrada, vale o
    #: padrão (escrita pede aprovação quando approve_writes, leitura é livre).
    tool_modes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {**asdict(self), "service": CATALOG[self.kind]["name"]}


def _run_gh(args: list[str]) -> str:
    """O `gh` já logado (10 s). Erro vira ConnectorError sem nada do token."""
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=10)
    except FileNotFoundError as exc:
        raise ConnectorError("o gh não está instalado: cole um token do GitHub") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConnectorError("o gh não respondeu em 10 s") from exc
    if done.returncode != 0:
        raise ConnectorError(f"o gh não deu o token (gh auth status?): {done.stderr.strip()[:200]}")
    return done.stdout.strip()


class _Remote:
    """MCP de fora com o token em dia: renova antes de vencer e, num 401, renova e repete uma vez."""

    def __init__(self, store: "ConnectorStore", account_id: str, url: str) -> None:
        self.store = store
        self.account_id = account_id
        self.client = McpClient(url, store.access_token(account_id), store.http())

    @property
    def server(self) -> dict:
        return self.client.server

    def _run(self, work: Callable[[], Any]) -> Any:
        self.client.token = self.store.access_token(self.account_id)
        try:
            return work()
        except McpAuthError:
            self.client.token = self.store.refresh_login(self.account_id)
            self.client.session, self.client._ready = None, False
            return work()

    def tools(self) -> list[dict]:
        return self._run(self.client.tools)

    def call(self, name: str, arguments: dict) -> dict:
        return self._run(lambda: self.client.call(name, arguments))


class ConnectorStore:
    def __init__(
        self,
        home: Path,
        vault: Vault,
        http: Callable[[], httpx.Client] | None = None,
        gh: Callable[[list[str]], str] | None = None,
    ) -> None:
        self.path = home / "conectores.json"
        self.vault = vault
        self.http = http or (lambda: httpx.Client(timeout=httpx.Timeout(30, connect=10)))
        self.gh = gh or _run_gh
        self._pending: dict[str, tuple[OAuthStart, str, str, float, dict]] = {}
        self._clients: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._token_lock = threading.RLock()

    # --- arquivo -------------------------------------------------------------

    def _load(self) -> list[ConnectorAccount]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out = []
        # Campo que a conta não conhece (o "reconectar" que o backup marca, ou um de versão mais
        # nova) fica de fora; antes, ele fazia a conta inteira sumir da lista.
        known = {f.name for f in fields(ConnectorAccount)}
        for item in data if isinstance(data, list) else []:
            try:
                out.append(ConnectorAccount(**{k: v for k, v in item.items() if k in known}))
            except (TypeError, AttributeError):
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
            modes = changes.get("tool_modes")
            if modes:
                merged = dict(target.tool_modes or {})
                for tool, mode in modes.items():
                    if mode in (None, "", "padrao"):
                        merged.pop(tool, None)
                    elif mode in TOOL_MODES:
                        merged[str(tool)[:120]] = mode
                    else:
                        raise ConnectorError(f"modo de ferramenta desconhecido: {mode} (livre, aprovacao ou desligada)")
                target.tool_modes = merged
            self._save(accounts)
            return target

    def remove(self, account_id: str) -> None:
        with self._lock:
            accounts = self._load()
            kept = [a for a in accounts if a.id != account_id]
            if len(kept) == len(accounts):
                raise ConnectorError(f"conta de conector desconhecida: {account_id}")
            self.vault.delete(f"conector:{account_id}")
            client = self._clients.pop(account_id, None)
            if isinstance(client, StdioClient):
                client.close()  # o processo do MCP por stdio não fica órfão
            self._save(kept)

    def close(self) -> None:
        """Encerra os MCPs por stdio (o núcleo vai desligar)."""
        for client in list(self._clients.values()):
            if isinstance(client, StdioClient):
                client.close()

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

    def _remember(self, start: OAuthStart, kind: str, name: str, extra: dict | None = None) -> str:
        now = time.time()
        self._pending = {s: p for s, p in self._pending.items() if now - p[3] < OAUTH_TTL}
        self._pending[start.state] = (start, kind, name, now, extra or {})
        return start.authorize_url

    def start_oauth(self, kind: str, name: str, redirect_uri: str) -> str:
        spec = CATALOG.get(kind)
        if not spec or spec["auth"] != "oauth":
            raise ConnectorError(f"{kind} não conecta por login no navegador")
        try:
            start = begin(self.http(), spec["url"], redirect_uri)
        except (OAuthError, httpx.HTTPError) as exc:
            raise ConnectorError(str(exc)) from exc
        return self._remember(start, kind, name.strip() or spec["name"])

    @staticmethod
    def _record(tokens: dict, start: OAuthStart) -> dict:
        """O que vai para o Keychain: o token e tudo o que a renovação precisa."""
        record = {k: tokens[k] for k in ("access_token", "refresh_token", "token_type", "scope") if tokens.get(k)}
        if tokens.get("expires_in"):
            record["expires_at"] = time.time() + float(tokens["expires_in"])
        record["token_endpoint"] = start.token_endpoint
        record["client_id"] = start.client_id
        if start.client_secret:
            record["client_secret"] = start.client_secret
        if start.resource:
            record["resource"] = start.resource
        return record

    def finish_oauth(self, state: str, code: str) -> ConnectorAccount:
        pending = self._pending.pop(state, None)
        if pending is None or time.time() - pending[3] > OAUTH_TTL:
            raise ConnectorError("este login expirou ou já foi usado; clique em Conectar de novo")
        start, kind, name, _, extra = pending
        try:
            tokens = finish(self.http(), start, code)
        except (OAuthError, httpx.HTTPError) as exc:
            raise ConnectorError(str(exc)) from exc
        record = self._record(tokens, start)
        if kind == "google":
            return self._finish_google(name, record)
        url = extra.get("url") or CATALOG[kind]["url"]
        try:
            client = McpClient(url, record["access_token"], self.http())
            tools = client.tools()
        except (httpx.HTTPError, RuntimeError) as exc:
            raise ConnectorError(str(exc)) from exc
        meta: dict = {"server": client.server.get("name", ""), "tools": len(tools), "client_id": start.client_id}
        if kind == "mcp":
            meta = {"transporte": "http", "url": url, "auth": "oauth", "servidor": client.server.get("name", ""), "ferramentas": len(tools), "client_id": start.client_id}
        account = ConnectorAccount(id=self._new_id(kind, name), kind=kind, name=name, created=time.time(), meta=meta)
        account = self._add(account, json.dumps(record))
        return account

    # --- tokens: renovação ------------------------------------------------------------

    def _tokens(self, account_id: str) -> dict:
        raw = self.secret(account_id)
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if isinstance(data, dict) and "access_token" in data:
            return data
        return {"access_token": raw}  # conta antiga: só o token

    def _url(self, account: ConnectorAccount) -> str:
        url = CATALOG.get(account.kind, {}).get("url") or account.meta.get("url")
        if not url:
            raise ConnectorError(f"{account.name} não tem endereço de MCP")
        return url

    def access_token(self, account_id: str) -> str:
        """O token em dia: renova se falta menos de 1 minuto para vencer."""
        with self._token_lock:
            tokens = self._tokens(account_id)
            expires = tokens.get("expires_at")
            if expires and float(expires) - time.time() < 60 and tokens.get("refresh_token"):
                tokens = self._refresh(account_id, tokens)
            return str(tokens.get("access_token") or "")

    def refresh_login(self, account_id: str) -> str:
        """Renova agora (o servidor recusou o token). Sem refresh_token, pede para conectar de novo."""
        with self._token_lock:
            account = self.get(account_id)
            tokens = self._tokens(account_id)
            if not tokens.get("refresh_token"):
                if account.kind == "github":
                    raise ConnectorError(f"o GitHub recusou o token de {account.name}; conecte de novo")
                raise ConnectorError(f"o login de {account.name} expirou; conecte de novo")
            return str(self._refresh(account_id, tokens)["access_token"])

    def _refresh(self, account_id: str, tokens: dict) -> dict:
        account = self.get(account_id)
        endpoint = tokens.get("token_endpoint")
        client_id = tokens.get("client_id") or account.meta.get("client_id") or ""
        try:
            if not endpoint:  # conta de antes da v0.9.8: descobre onde renovar
                _, meta = discover(self.http(), self._url(account))
                endpoint = meta["token_endpoint"]
            fresh = refresh(self.http(), endpoint, client_id, tokens.get("client_secret", ""), tokens["refresh_token"], tokens.get("resource", ""))
        except (OAuthError, httpx.HTTPError, ConnectorError) as exc:
            raise ConnectorError(f"o login de {account.name} expirou; conecte de novo") from exc
        merged = {**tokens, "access_token": fresh["access_token"], "token_endpoint": endpoint, "client_id": client_id}
        if fresh.get("refresh_token"):
            merged["refresh_token"] = fresh["refresh_token"]
        if fresh.get("expires_in"):
            merged["expires_at"] = time.time() + float(fresh["expires_in"])
        else:
            merged.pop("expires_at", None)
        self.vault.set(f"conector:{account_id}", json.dumps(merged))
        return merged

    # --- clientes ---------------------------------------------------------------------

    def _stdio_spec(self, account_id: str) -> dict:
        try:
            spec = json.loads(self.secret(account_id))
        except ValueError as exc:
            raise ConnectorError("a configuração deste MCP sumiu do Keychain; adicione de novo") from exc
        if not isinstance(spec, dict) or not spec.get("comando"):
            raise ConnectorError("a configuração deste MCP sumiu do Keychain; adicione de novo")
        return spec

    def mcp(self, account_id: str) -> Any:
        """Cliente do MCP da conta (HTTP com token em dia, ou o processo por stdio)."""
        client = self._clients.get(account_id)
        if client is None:
            account = self.get(account_id)
            if account.kind in ("slack", "google"):
                raise ConnectorError(f"{account.name} não é um servidor MCP")
            if account.kind == "mcp" and account.meta.get("transporte") == "stdio":
                spec = self._stdio_spec(account_id)
                client = StdioClient(spec["comando"], spec.get("env") or {}, spec.get("pasta") or None)
            else:
                client = _Remote(self, account_id, self._url(account))
            self._clients[account_id] = client
        return client

    # --- GitHub (token do gh) -----------------------------------------------------------

    def add_github(self, name: str, token: str = "") -> ConnectorAccount:
        token = (token or "").strip() or self.gh(["auth", "token"])
        if not token:
            raise ConnectorError("o gh não está logado (gh auth login) e nenhum token foi colado")
        client = McpClient(CATALOG["github"]["url"], token, self.http())
        try:
            tools = client.tools()
        except McpAuthError as exc:
            raise ConnectorError("o GitHub recusou o token (o gh está logado? gh auth status)") from exc
        except (McpError, httpx.HTTPError) as exc:
            raise ConnectorError(f"o MCP do GitHub não respondeu: {_scrub(str(exc), token)}") from exc
        login = ""
        try:
            response = self.http().get("https://api.github.com/user", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
            if response.status_code == 200:
                login = str(response.json().get("login") or "")
        except (httpx.HTTPError, ValueError):
            pass
        account = ConnectorAccount(
            id=self._new_id("github", name.strip() or f"GitHub {login}".strip()),
            kind="github",
            name=name.strip() or (f"GitHub {login}" if login else "GitHub"),
            created=time.time(),
            meta={"login": login, "ferramentas": len(tools), "servidor": client.server.get("name", "")},
        )
        return self._add(account, json.dumps({"access_token": token}))

    # --- MCP próprio ----------------------------------------------------------------------

    def add_mcp_http(self, name: str, url: str, auth: str, token: str, redirect_uri: str) -> ConnectorAccount | str:
        """Conta de um MCP por endereço. Com auth "oauth", devolve a página de login (str)."""
        url = url.strip()
        if not _is_url(url):
            raise ConnectorError("o endereço do MCP começa com http:// ou https://")
        name = name.strip() or (urlparse(url).netloc or "MCP")
        if auth == "oauth":
            try:
                start = begin(self.http(), url, redirect_uri)
            except (OAuthError, httpx.HTTPError) as exc:
                raise ConnectorError(str(exc)) from exc
            return self._remember(start, "mcp", name, {"url": url})
        if auth not in ("nenhuma", "token"):
            raise ConnectorError("autenticação: nenhuma, token ou oauth")
        token = (token or "").strip() if auth == "token" else ""
        if auth == "token" and not token:
            raise ConnectorError("cole o token do servidor MCP")
        client = McpClient(url, token, self.http())
        try:
            tools = client.tools()
        except McpAuthError as exc:
            raise ConnectorError("o servidor recusou o acesso: veja o token ou use o login (oauth)") from exc
        except (McpError, httpx.HTTPError) as exc:
            raise ConnectorError(f"o servidor MCP não respondeu: {_scrub(str(exc), token)}") from exc
        account = ConnectorAccount(
            id=self._new_id("mcp", name),
            kind="mcp",
            name=name,
            created=time.time(),
            meta={"transporte": "http", "url": url, "auth": auth, "servidor": client.server.get("name", ""), "ferramentas": len(tools)},
        )
        return self._add(account, json.dumps({"access_token": token}))

    def add_mcp_stdio(self, name: str, command: str, env_text: str = "", folder: str = "") -> ConnectorAccount:
        command = (command or "").strip()
        if not command:
            raise ConnectorError("diga o comando que sobe o servidor MCP (ex.: npx -y pacote)")
        env = parse_env(env_text)
        folder = (folder or "").strip()
        if folder and not Path(folder).expanduser().is_dir():
            raise ConnectorError(f"a pasta {folder} não existe")
        client = StdioClient(command, env, folder or None, timeout=30)
        try:
            tools = client.tools()
        except McpError as exc:
            client.close()
            raise ConnectorError(f"o servidor não respondeu: {_scrub(str(exc), *env.values())}") from exc
        client.timeout = 60
        name = name.strip() or command.split()[0]
        account = ConnectorAccount(
            id=self._new_id("mcp", name),
            kind="mcp",
            name=name,
            created=time.time(),
            meta={
                "transporte": "stdio",
                "comando": _mask(command, env),
                "env_chaves": sorted(env),
                "pasta": folder,
                "servidor": client.server.get("name", ""),
                "ferramentas": len(tools),
            },
        )
        account = self._add(account, json.dumps({"comando": command, "env": env, "pasta": folder}))
        self._clients[account.id] = client
        return account

    # --- Google (nativo) --------------------------------------------------------------------

    def set_google_client(self, client_id: str, client_secret: str) -> dict:
        client_id, client_secret = (client_id or "").strip(), (client_secret or "").strip()
        if not client_id or not client_secret or " " in client_id:
            raise ConnectorError("cole o ID e a chave secreta do cliente OAuth (App para computador)")
        self.vault.set(GOOGLE_CLIENT, json.dumps({"client_id": client_id, "client_secret": client_secret}))
        return self.google_client_status()

    def _google_client(self) -> dict | None:
        raw = self.vault.get(GOOGLE_CLIENT)
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        return data if isinstance(data, dict) and data.get("client_id") else None

    def google_client_status(self) -> dict:
        client = self._google_client()
        return {"configurado": bool(client), "client_id_fim": (client or {}).get("client_id", "")[-6:]}

    def start_google(self, name: str, redirect_uri: str) -> str:
        client = self._google_client()
        if not client:
            raise ConnectorError("configure antes o cliente OAuth do Google (ID e chave secreta)")
        start = begin_with_client(
            google_api.AUTHORIZE,
            google_api.TOKEN,
            client["client_id"],
            client["client_secret"],
            redirect_uri,
            google_api.SCOPES,
            {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
        )
        return self._remember(start, "google", name.strip() or "Google")

    def _finish_google(self, name: str, record: dict) -> ConnectorAccount:
        token = record["access_token"]
        api = google_api.Google(lambda: token, lambda: token, self.http())
        try:
            email = str(api.userinfo().get("email") or "")
        except (google_api.GoogleError, httpx.HTTPError) as exc:
            raise ConnectorError(f"o Google não disse de quem é a conta: {exc}") from exc
        account = ConnectorAccount(
            id=self._new_id("google", name if name != "Google" else f"google {email.split('@')[0]}"),
            kind="google",
            name=name if name != "Google" else (f"Google {email}" if email else "Google"),
            created=time.time(),
            meta={"email": email},
        )
        return self._add(account, json.dumps(record))

    def google(self, account_id: str) -> google_api.Google:
        account = self.get(account_id)
        if account.kind != "google":
            raise ConnectorError(f"{account.name} não é uma conta do Google")
        return google_api.Google(lambda: self.access_token(account_id), lambda: self.refresh_login(account_id), self.http())

    # --- testar conexão ------------------------------------------------------------------

    def test(self, account_id: str) -> dict:
        """Confere a conta sem mexer em nada (sem mandar mensagem). Nunca levanta erro."""
        started = time.monotonic()

        def answer(ok: bool, detail: str, tools: int | None = None) -> dict:
            return {"ok": ok, "ms": int((time.monotonic() - started) * 1000), "detalhe": detail, "ferramentas": tools}

        try:
            account = self.get(account_id)
        except ConnectorError as exc:
            return answer(False, str(exc))
        try:
            if account.kind == "slack":
                _, slack = self.slack(account_id)
                who = slack.identity()
                return answer(True, f"bot {who.get('bot', '')} no workspace {who.get('team', '')}")
            if account.kind == "google":
                api = self.google(account_id)
                email = api.userinfo().get("email", "")
                problems = api.check()
                if problems:
                    return answer(False, "; ".join(problems))
                return answer(True, f"{email}: Gmail, Agenda e Drive responderam")
            if account.kind == "mcp" and account.meta.get("transporte") == "stdio":
                spec = self._stdio_spec(account_id)
                client = StdioClient(spec["comando"], spec.get("env") or {}, spec.get("pasta") or None, timeout=30)
                try:
                    tools = client.tools()
                finally:
                    client.close()
                return answer(True, f"{client.server.get('name') or account.name} respondeu", len(tools))
            remote = _Remote(self, account_id, self._url(account))
            tools = remote.tools()
            return answer(True, f"{remote.server.get('name') or account.name} respondeu", len(tools))
        except Exception as exc:  # o teste nunca derruba a rota: o erro vira o detalhe
            secrets: list[str] = []
            try:
                secrets = [str(v) for v in self._tokens(account_id).values() if isinstance(v, str)]
            except ConnectorError:
                pass
            return answer(False, _scrub(str(exc) or exc.__class__.__name__, *secrets))
