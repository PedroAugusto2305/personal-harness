"""Pedido pontual ao Claude sem tela (`claude -p`), pela conta ativa e pelo plano.

Usado pelo rascunho de agente e pelo juiz das sugestões do Brain. O prompt vai logo depois
do executável: opções como `--tools` são variádicas e engoliriam um prompt deixado no fim.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable


class ClaudePrintError(RuntimeError):
    pass


Runner = Callable[[list[str], dict[str, str], str], str]


def run_cli(argv: list[str], env: dict[str, str], cwd: str, timeout: float = 240) -> str:
    try:
        done = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ClaudePrintError(f"o Claude demorou demais para responder ({int(timeout)} s)") from exc
    if done.returncode != 0:
        raise ClaudePrintError(f"o Claude não respondeu: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout


def json_object(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ClaudePrintError("o Claude não devolveu JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ClaudePrintError("o Claude devolveu JSON quebrado") from exc
    if not isinstance(data, dict):
        raise ClaudePrintError("a resposta não é um objeto JSON")
    return data


def result_text(raw: str) -> str:
    """O texto da resposta dentro do envelope de `--output-format json`."""
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return str(envelope.get("result", "")) if isinstance(envelope, dict) else raw


def ask_json(prompt: str, env: dict[str, str], cwd: Path, run: Runner = run_cli, model: str | None = None, bare: bool = False) -> dict:
    """Manda o prompt e devolve o objeto JSON da resposta.

    bare=True: sem ferramentas, sem MCP, sem as configurações do usuário (hooks, plugins) e
    sem guardar a sessão; serve para um julgamento curto que só lê o prompt.
    """
    executable = shutil.which("claude", path=env.get("PATH"))
    if not executable:
        raise ClaudePrintError("claude não encontrado no PATH")
    argv = [executable, prompt, "-p", "--output-format", "json"]
    if model:
        argv += ["--model", model]
    if bare:
        argv += ["--strict-mcp-config", "--setting-sources", "local", "--no-session-persistence", "--tools", ""]
    cwd.mkdir(parents=True, exist_ok=True)
    return json_object(result_text(run(argv, env, str(cwd))))
