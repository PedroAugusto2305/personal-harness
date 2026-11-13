"""Cota do plano do Codex, lida do `codex app-server` (JSON-RPC por stdin/stdout).

É o mesmo caminho que o Orca usa: `initialize` e depois `account/rateLimits/read`.
Usa o login da própria CLI (não lê token) e não chama o modelo.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from typing import Any

from . import __version__

WINDOW_BY_MINUTES = {300: "five_hour", 10080: "seven_day"}


async def end_codex(proc: asyncio.subprocess.Process, grace: float = 3.0) -> None:
    """Encerra um `codex` aberto com start_new_session=True, com o grupo inteiro.

    O `codex` do npm é um lançador (codex.js) que roda o binário nativo como filho e só
    repassa SIGINT, SIGTERM e SIGHUP. Um SIGKILL só no lançador deixava o binário órfão,
    preso aos canais do núcleo: da 1.2.0 à 1.3.2 sobrava um `codex app-server` a cada
    consulta da cota (de 3 em 3 min), e em ~5 h o núcleo batia no limite de 256 arquivos
    abertos que o macOS dá ao app aberto pelo Finder (a lista de projetos sumia, a conversa
    dizia que o transcript não existia mais e o resto da janela falhava junto).

    Fecha a entrada (o app-server sai sozinho ao ver o fim dela), espera `grace` segundos
    e mata o grupo do mesmo jeito, para não sobrar nem o binário nativo."""
    if proc.stdin is not None and not proc.stdin.is_closing():
        proc.stdin.close()
    if proc.returncode is None:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(grace):
                await proc.wait()
    # O grupo continua existindo enquanto o binário nativo viver, mesmo com o lançador já
    # recolhido, então o pid do lançador ainda o identifica; grupo vazio dá ProcessLookupError.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    await proc.wait()
    # Rede de segurança: um neto que fugiu do grupo (com sessão própria) e herdou a saída
    # seguraria o transporte do asyncio, e com ele os dois canais, até o núcleo fechar.
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        transport.close()


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
        start_new_session=True,  # o lançador e o binário nativo num grupo só (ver end_codex)
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
        await end_codex(proc)
