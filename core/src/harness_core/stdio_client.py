"""Cliente MCP por stdio (v0.9.8): o "MCP próprio" que roda como programa local.

Mesma interface do McpClient (tools() e call()), para a central tratar os dois igual. O
processo fica vivo e é reaproveitado; se morrer, a próxima chamada o sobe de novo. Um pedido
por vez (JSON-RPC em linhas no stdin e no stdout); o stderr fica guardado para a mensagem de
erro, sem nunca mostrar os valores das variáveis de ambiente.
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
from collections import deque

from .mcp_client import PROTOCOL, McpError

CALL_TIMEOUT = 60.0


class StdioClient:
    def __init__(self, command: str, env: dict[str, str] | None = None, cwd: str | None = None, name: str = "MÊTIS", timeout: float = CALL_TIMEOUT) -> None:
        try:
            self.argv = shlex.split(command)
        except ValueError as exc:
            raise McpError(f"comando inválido: {exc}") from exc
        if not self.argv:
            raise McpError("diga o comando que sobe o servidor MCP")
        self.env = dict(env or {})
        self.cwd = os.path.expanduser(cwd) if cwd else None
        self.name = name
        self.timeout = timeout
        self.server: dict = {}
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=40)
        self._next = 0
        self._lock = threading.Lock()

    # --- processo ------------------------------------------------------------------

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _secret_free(self, text: str) -> str:
        for value in self.env.values():
            if value and len(value) >= 3:
                text = text.replace(value, "***")
        return text

    def stderr_tail(self, lines: int = 8) -> str:
        return self._secret_free("\n".join(list(self._stderr)[-lines:])).strip()

    def _start(self) -> None:
        self.close()
        # Fila e stderr novos, presos a este processo: o que o processo anterior ainda soltar
        # (linhas atrasadas, o fim do stdout) vai para as dele e não confunde o novo.
        lines: queue.Queue[str | None] = queue.Queue()
        errors: deque[str] = deque(maxlen=40)
        self._lines, self._stderr = lines, errors
        try:
            self._proc = subprocess.Popen(
                self.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                env={**os.environ, **self.env},  # o PATH do núcleo, mais as variáveis da conta
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            raise McpError(f"o comando não iniciou: {self._secret_free(str(exc))}") from exc
        proc = self._proc

        def read_out() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        def read_err() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                errors.append(line.rstrip())

        threading.Thread(target=read_out, daemon=True).start()
        threading.Thread(target=read_err, daemon=True).start()
        try:
            result = self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": self.name, "version": "1"}})
            self.server = result.get("serverInfo", {}) if isinstance(result, dict) else {}
            self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except McpError:
            # Sem o aperto de mão o processo não serve: fecha, e a próxima chamada sobe outro
            # (senão ela pularia o initialize e falaria com um servidor que nunca começou).
            self.close()
            raise

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()

    # --- JSON-RPC ------------------------------------------------------------------

    def _write(self, message: dict) -> None:
        if not self._alive() or self._proc is None or self._proc.stdin is None:
            raise McpError(self._died())
        try:
            self._proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise McpError(self._died()) from exc

    def _died(self) -> str:
        tail = self.stderr_tail()
        return "o servidor MCP parou" + (f": {tail}" if tail else "")

    def _request(self, method: str, params: dict | None = None) -> dict:
        self._next += 1
        wanted = self._next
        self._write({"jsonrpc": "2.0", "id": wanted, "method": method, "params": params or {}})
        while True:
            try:
                line = self._lines.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise McpError(f"o servidor MCP não respondeu {method} em {int(self.timeout)} s") from exc
            if line is None:
                raise McpError(self._died())
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # texto solto no stdout (log do servidor): ignora
            if not isinstance(message, dict) or message.get("id") != wanted:
                continue  # notificação ou pedido do servidor
            if "error" in message:
                error = message["error"]
                raise McpError(str(error.get("message") if isinstance(error, dict) else error))
            return message.get("result") or {}

    def _call(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            if not self._alive():
                self._start()
            return self._request(method, params)

    def tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor = None
        for _ in range(20):
            result = self._call("tools/list", {"cursor": cursor} if cursor else {})
            tools += result.get("tools", [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call(self, name: str, arguments: dict) -> dict:
        return self._call("tools/call", {"name": name, "arguments": arguments})
