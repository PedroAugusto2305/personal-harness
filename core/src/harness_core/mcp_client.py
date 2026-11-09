"""Cliente MCP mínimo por HTTP (streamable HTTP): initialize, tools/list e tools/call.

É o lado da central que fala com os MCPs de fora (o oficial do ClickUp). A resposta pode
vir como JSON ou como eventos (text/event-stream); os dois são aceitos.
"""

from __future__ import annotations

import json
import threading

import httpx

PROTOCOL = "2025-06-18"


class McpError(RuntimeError):
    pass


class McpAuthError(McpError):
    """Token recusado (401): a conta precisa conectar de novo."""


def _from_events(body: str, wanted: int) -> dict | None:
    data: list[str] = []
    for line in body.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                message = json.loads("\n".join(data))
            except json.JSONDecodeError:
                message = None
            data = []
            if isinstance(message, dict) and message.get("id") == wanted:
                return message
    return None


class McpClient:
    def __init__(self, url: str, token: str, client: httpx.Client | None = None, name: str = "MÊTIS") -> None:
        self.url = url
        self.token = token
        self.http = client or httpx.Client(timeout=httpx.Timeout(60, connect=10))
        self.name = name
        self.session: str | None = None
        self.server: dict = {}
        self._next = 0
        self._lock = threading.Lock()
        self._ready = False

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self.token:  # MCP próprio sem autenticação não manda o cabeçalho
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        return headers

    def _send(self, payload: dict) -> dict | None:
        response = self.http.post(self.url, json=payload, headers=self._headers())
        if response.status_code == 401:
            raise McpAuthError("o serviço recusou o token; conecte a conta de novo")
        if response.status_code == 404 and self.session:
            raise McpError("sessão expirada")
        if response.status_code >= 400:
            raise McpError(f"{response.status_code}: {response.text[:300]}")
        if response.headers.get("mcp-session-id"):
            self.session = response.headers["mcp-session-id"]
        if "id" not in payload:
            return None
        if "text/event-stream" in response.headers.get("content-type", ""):
            message = _from_events(response.text, payload["id"])
        else:
            message = response.json() if response.content else None
        if not isinstance(message, dict):
            raise McpError("resposta vazia do servidor MCP")
        if "error" in message:
            error = message["error"]
            raise McpError(str(error.get("message") if isinstance(error, dict) else error))
        return message.get("result") or {}

    def _request(self, method: str, params: dict | None = None) -> dict:
        self._next += 1
        result = self._send({"jsonrpc": "2.0", "id": self._next, "method": method, "params": params or {}})
        return result or {}

    def _initialize(self) -> None:
        result = self._request(
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": self.name, "version": "1"}},
        )
        self.server = result.get("serverInfo", {})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._ready = True

    def _with_session(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            if not self._ready:
                self._initialize()
            try:
                return self._request(method, params)
            except McpError as exc:
                if isinstance(exc, McpAuthError) or "sessão expirada" not in str(exc):
                    raise
                # O servidor esqueceu a sessão: recomeça uma vez.
                self.session, self._ready = None, False
                self._initialize()
                return self._request(method, params)

    def tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor = None
        for _ in range(20):
            result = self._with_session("tools/list", {"cursor": cursor} if cursor else {})
            tools += result.get("tools", [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call(self, name: str, arguments: dict) -> dict:
        return self._with_session("tools/call", {"name": name, "arguments": arguments})
