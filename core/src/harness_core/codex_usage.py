"""Cota do plano do Codex, lida do `codex app-server` (JSON-RPC por stdin/stdout).

É o mesmo caminho que o Orca usa: `initialize` e depois `account/rateLimits/read`.
Usa o login da própria CLI (não lê token) e não chama o modelo.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from . import __version__

WINDOW_BY_MINUTES = {300: "five_hour", 10080: "seven_day"}


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_codex_limits(result: dict) -> dict:
    limits = result.get("rateLimits") if isinstance(result.get("rateLimits"), dict) else {}
    parsed: dict = {}
    for slot, fallback in (("primary", "five_hour"), ("secondary", "seven_day")):
        window = limits.get(slot) if isinstance(limits.get(slot), dict) else {}
        pct = _num(window.get("usedPercent"))
        if pct is None:
            continue
        name = WINDOW_BY_MINUTES.get(window.get("windowDurationMins"), fallback)
        resets = _num(window.get("resetsAt"))
        parsed[name] = {"used_pct": pct, "resets_at": int(resets) if resets is not None else None}
    if limits.get("planType"):
        parsed["plan"] = limits["planType"]
    return parsed


async def read_codex_limits(executable: str, env: dict[str, str], timeout: float = 25.0) -> dict | None:
    proc = await asyncio.create_subprocess_exec(
        executable,
        "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None

    async def send(message: dict) -> None:
        proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()

    async def reply(message_id: int) -> dict:
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise ConnectionError("app-server encerrou")
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("id") == message_id:
                return data

    try:
        async with asyncio.timeout(timeout):
            await send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "harness", "title": "Harness", "version": __version__}}})
            await reply(1)
            await send({"jsonrpc": "2.0", "method": "initialized"})
            await send({"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"})
            answer = await reply(2)
        result = answer.get("result")
        return parse_codex_limits(result) if isinstance(result, dict) else None
    except (TimeoutError, ConnectionError, OSError):
        return None
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
