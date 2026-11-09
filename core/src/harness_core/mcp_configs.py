"""Os MCPs do Claude Code e do Codex, e copiar um de uma CLI para a outra (v0.9.8).

Lê do arquivo de cada CLI (o `.claude.json` e o `config.toml` da conta ativa) e grava SEMPRE
pela CLI de destino (`claude mcp add-json` e `codex mcp add`), nunca editando o arquivo dela
à mão: as duas reescrevem esses arquivos o tempo todo. Os valores das variáveis de ambiente
nunca saem daqui: a lista mostra só os nomes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CLIS = ("claude", "codex")
Runner = Callable[[list[str], dict[str, str]], tuple[int, str, str]]


class McpConfigError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = status


@dataclass
class Places:
    """Onde mora a configuração da conta ativa de cada CLI, e o ambiente para chamá-la."""

    claude_json: Path
    codex_config: Path
    claude_env: dict[str, str]
    codex_env: dict[str, str]


def run_cli(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    exe = shutil.which(argv[0])
    if exe is None:
        raise McpConfigError(f"o {argv[0]} não está no PATH")
    try:
        done = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=60, env={**os.environ, **env})
    except subprocess.TimeoutExpired as exc:
        raise McpConfigError(f"o {argv[0]} não respondeu em 60 s") from exc
    return done.returncode, done.stdout, done.stderr


# --- leitura -----------------------------------------------------------------------------


def _kind(spec: dict) -> str:
    declared = str(spec.get("type") or "").lower()
    if declared in ("stdio", "http", "sse"):
        return declared
    if declared == "streamable-http":
        return "http"
    return "http" if spec.get("url") else "stdio"


def _public(name: str, spec: dict, scope: str) -> dict:
    """O que a tela pode ver: sem nenhum valor de variável nem cabeçalho."""
    item: dict = {"nome": name, "tipo": _kind(spec), "escopo": scope}
    if spec.get("command"):
        item["comando"] = str(spec["command"])
        item["args"] = [str(a) for a in spec.get("args") or []]
    keys = sorted(set((spec.get("env") or {}).keys()) | set(spec.get("env_vars") or []))
    if keys:
        item["env_chaves"] = keys
    if spec.get("url"):
        item["url"] = str(spec["url"])
    return item


def _claude_data(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _codex_data(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def claude_servers(path: Path, *, raw: bool = False) -> list[dict] | dict[str, dict]:
    data = _claude_data(path)
    user = {k: v for k, v in (data.get("mcpServers") or {}).items() if isinstance(v, dict)}
    if raw:
        return user
    out = [_public(name, spec, "usuario") for name, spec in sorted(user.items())]
    for folder, project in sorted((data.get("projects") or {}).items()):
        for name, spec in sorted(((project or {}).get("mcpServers") or {}).items()):
            if isinstance(spec, dict):
                out.append(_public(name, spec, f"projeto:{folder}"))
    return out


def codex_servers(path: Path, *, raw: bool = False) -> list[dict] | dict[str, dict]:
    servers = {k: v for k, v in (_codex_data(path).get("mcp_servers") or {}).items() if isinstance(v, dict)}
    if raw:
        return servers
    return [_public(name, spec, "usuario") for name, spec in sorted(servers.items())]


def listing(places: Places) -> dict:
    return {"claude": claude_servers(places.claude_json), "codex": codex_servers(places.codex_config)}


# --- cópia -------------------------------------------------------------------------------

_BEARER_VAR = re.compile(r"^Bearer\s+\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")


def _scrub(text: str, spec: dict) -> str:
    for value in (spec.get("env") or {}).values():
        if isinstance(value, str) and len(value) >= 3:
            text = text.replace(value, "***")
    for value in (spec.get("headers") or {}).values():
        if isinstance(value, str) and len(value) >= 3:
            text = text.replace(value, "***")
    return text.strip()[-400:]


def _to_claude(spec: dict) -> dict:
    kind = _kind(spec)
    if kind == "stdio":
        out: dict = {"type": "stdio", "command": spec["command"], "args": [str(a) for a in spec.get("args") or []]}
        env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
        for name in spec.get("env_vars") or []:
            env.setdefault(str(name), f"${{{name}}}")  # o Codex repassa a do ambiente; o Claude lê ${VAR}
        if env:
            out["env"] = env
        return out
    out = {"type": "http", "url": spec["url"]}
    if spec.get("bearer_token_env_var"):
        out["headers"] = {"Authorization": f"Bearer ${{{spec['bearer_token_env_var']}}}"}
    return out


def _to_codex(name: str, spec: dict) -> tuple[list[str], list[str]]:
    """(argumentos do `codex mcp add`, avisos)."""
    kind = _kind(spec)
    notes: list[str] = []
    if kind == "sse":
        raise McpConfigError("o Codex não usa MCP por SSE (só stdio e HTTP)")
    if kind == "http":
        argv = ["codex", "mcp", "add", name, "--url", str(spec["url"])]
        headers = spec.get("headers") or {}
        auth = next((str(v) for k, v in headers.items() if str(k).lower() == "authorization"), "")
        match = _BEARER_VAR.match(auth.strip())
        if match:
            argv += ["--bearer-token-env-var", match.group(1)]
        elif headers:
            notes.append("os cabeçalhos não foram (o Codex só lê o token de uma variável de ambiente)")
        return argv, notes
    argv = ["codex", "mcp", "add", name]
    for key, value in (spec.get("env") or {}).items():
        argv += ["--env", f"{key}={value}"]
    argv += ["--", str(spec["command"]), *[str(a) for a in spec.get("args") or []]]
    return argv, notes


def copy(places: Places, source: str, target: str, name: str, runner: Runner | None = None) -> dict:
    """Copia o MCP `name` (escopo do usuário) de uma CLI para a outra. Devolve a lista nova."""
    if source not in CLIS or target not in CLIS or source == target:
        raise McpConfigError("copie do claude para o codex ou do codex para o claude")
    run = runner or run_cli
    sources = claude_servers(places.claude_json, raw=True) if source == "claude" else codex_servers(places.codex_config, raw=True)
    assert isinstance(sources, dict)
    spec = sources.get(name)
    if spec is None:
        raise McpConfigError(f"o {source} não tem o MCP {name} no escopo do usuário (os de projeto não são copiados)", 404)
    existing = claude_servers(places.claude_json, raw=True) if target == "claude" else codex_servers(places.codex_config, raw=True)
    assert isinstance(existing, dict)
    if name in existing:
        raise McpConfigError(f"o {target} já tem um MCP chamado {name}", 409)
    notes: list[str] = []
    if target == "claude":
        argv = ["claude", "mcp", "add-json", name, json.dumps(_to_claude(spec), ensure_ascii=False), "--scope", "user"]
        env = places.claude_env
    else:
        argv, notes = _to_codex(name, spec)
        env = places.codex_env
    code, out, err = run(argv, env)
    if code != 0:
        raise McpConfigError(f"o {target} recusou: {_scrub(err or out, spec) or f'saiu com {code}'}")
    return {**listing(places), "avisos": notes}
