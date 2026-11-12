"""Histórico de sessões (v0.9.2): as conversas do Claude Code e do Codex que ficaram no disco.

- Claude: <pasta da conta>/projects/<pasta codificada>/<id>.jsonl (a conta padrão é ~/.claude;
  as outras vêm do CLAUDE_CONFIG_DIR de cada conta da MÊTIS). Retomar: `claude --resume <id>`.
- Codex: <CODEX_HOME>/sessions/AAAA/MM/DD/rollout-*.jsonl, a primeira linha é o session_meta
  com id e pasta. Retomar: `codex resume <id>`. Sessões de subagente (o guardião que revisa
  ações) ficam de fora.

Ler o começo e o fim de cada arquivo basta (pasta, primeiro pedido e o título que o Claude
gera). O resultado fica em cache pelo tamanho e pela data do arquivo.
"""

from __future__ import annotations

import json
import os
import threading
import unicodedata
from pathlib import Path
from typing import Iterable

HEAD_BYTES = 64_000
#: Começo do rollout do Codex lido para achar a primeira mensagem (v1.2.0: ela passou dos 64 KB).
CODEX_HEAD_BYTES = 1_000_000
TAIL_BYTES = 48_000
MAX_FILES = 400

_cache: dict[str, tuple[tuple[int, float], dict | None]] = {}
_lock = threading.Lock()


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _lines(path: Path) -> tuple[list[str], list[str]]:
    """Linhas inteiras do começo e do fim do arquivo (sem ler o meio)."""
    with open(path, "rb") as handle:
        head = handle.read(HEAD_BYTES).decode("utf-8", errors="replace").splitlines()
        size = handle.seek(0, os.SEEK_END)
        if size <= HEAD_BYTES:
            return head, head
        handle.seek(max(0, size - TAIL_BYTES))
        tail = handle.read().decode("utf-8", errors="replace").splitlines()[1:]
    return head[:-1], tail


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") in ("text", "input_text"))
    return ""


def _is_noise(text: str) -> bool:
    t = text.strip()
    return not t or t.startswith("<") or t.startswith("# AGENTS.md") or t.startswith("Caveat:") or t.startswith("[Request interrupted")


def _claude(path: Path, account: str) -> dict | None:
    head, tail = _lines(path)
    cwd, first, title, started = "", "", "", ""
    for line in head:
        if '"cwd"' not in line and '"user"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        cwd = cwd or entry.get("cwd") or ""
        started = started or entry.get("timestamp") or ""
        if not first and entry.get("type") == "user" and not entry.get("isMeta") and not entry.get("isSidechain"):
            text = _text((entry.get("message") or {}).get("content"))
            if not _is_noise(text):
                first = " ".join(text.split())
        if cwd and first:
            break
    for line in reversed(tail):
        if '"ai-title"' in line or '"summary"' in line:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            title = entry.get("aiTitle") or entry.get("summary") or ""
            if title:
                break
    if not first and not title:
        return None  # sessão aberta e fechada sem conversa
    return {"cli": "claude", "id": path.stem, "cwd": cwd, "titulo": (title or first)[:120], "primeiro": first[:300], "conta": account, "inicio": started}


def _codex_head(path: Path):
    """As linhas do começo do rollout, uma a uma, até CODEX_HEAD_BYTES.

    v1.2.0: no Codex 0.154 a primeira mensagem sua vem depois de ~90 KB de instruções (lista de
    skills, AGENTS.md, estado do mundo); com só os 64 KB do começo, a conversa não era achada
    (histórico, continuar, passar o trabalho e a tela da conversa)."""
    read = 0
    with open(path, "rb") as handle:
        for raw in handle:
            read += len(raw)
            if read > CODEX_HEAD_BYTES:
                return
            yield raw.decode("utf-8", errors="replace")


def _codex(path: Path, account: str) -> dict | None:
    meta, first = None, ""
    for line in _codex_head(path):
        if '"session_meta"' not in line[:200] and '"user"' not in line:
            continue  # instruções e estado do mundo: grandes e sem nada a ver aqui
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        payload = entry.get("payload") or {}
        if entry.get("type") == "session_meta" and meta is None:
            meta = payload
            if isinstance(payload.get("source"), dict) and "subagent" in payload["source"]:
                return None  # o guardião e outros subagentes não são conversas suas
        elif entry.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
            text = _text(payload.get("content"))
            if not _is_noise(text) and not text.startswith("The following is the Codex agent history"):
                first = " ".join(text.split())
                break
    if not meta or not first:
        return None
    return {"cli": "codex", "id": meta.get("id", ""), "cwd": meta.get("cwd", ""), "titulo": first[:120], "primeiro": first[:300], "conta": account, "inicio": meta.get("timestamp", "")}


def _read(path: Path, cli: str, account: str) -> dict | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (stat.st_size, stat.st_mtime)
    with _lock:
        cached = _cache.get(str(path))
    if cached and cached[0] == key:
        item = cached[1]
    else:
        try:
            item = _claude(path, account) if cli == "claude" else _codex(path, account)
        except OSError:
            item = None
        with _lock:
            _cache[str(path)] = (key, item)
    if item is None:
        return None
    return {**item, "atualizado": stat.st_mtime, "tamanho": stat.st_size, "arquivo": str(path)}


def sources(accounts: dict, defaults: dict[str, Path] | None = None) -> list[tuple[str, tuple[str, str], Path]]:
    """(cli, conta, pasta) de cada conta: a padrão usa ~/.claude e ~/.codex."""
    out = []
    home = Path.home()
    defaults = defaults or {"claude": home / ".claude", "codex": home / ".codex"}
    for cli, default in (("claude", defaults["claude"]), ("codex", defaults["codex"])):
        seen = set()
        for account in (accounts.get(cli) or {}).get("accounts", []):
            folder = Path(account["dir"]).expanduser() if account.get("dir") else default
            if folder not in seen:
                seen.add(folder)
                out.append((cli, (account["id"], account.get("name") or account["id"]), folder))
        if default not in seen:
            out.append((cli, ("padrao", "padrão"), default))
    return out


def list_sessions(accounts: dict, query: str = "", limit: int = 80, cwd: str = "", defaults: dict[str, Path] | None = None) -> list[dict]:
    """As sessões mais recentes de todas as contas, com busca por título, pedido e pasta."""
    files: list[tuple[float, str, tuple[str, str], Path]] = []
    for cli, account, folder in sources(accounts, defaults):
        pattern: Iterable[Path] = (folder / "projects").glob("*/*.jsonl") if cli == "claude" else (folder / "sessions").rglob("rollout-*.jsonl")
        for path in pattern:
            try:
                files.append((path.stat().st_mtime, cli, account, path))
            except OSError:
                continue
    files.sort(key=lambda f: f[0], reverse=True)
    wanted = fold(query.strip())
    found = []
    for _mtime, cli, (account_id, account), path in files[:MAX_FILES]:
        item = _read(path, cli, account)
        if item is None:
            continue
        item["conta_id"] = account_id
        if cwd and not item["cwd"].startswith(cwd.rstrip("/")):
            continue
        if wanted and wanted not in fold(f"{item['titulo']} {item['primeiro']} {item['cwd']}"):
            continue
        found.append(item)
        if len(found) >= limit:
            break
    return found


def codex_rollout_for(
    accounts: dict,
    cwd: str,
    since: float,
    defaults: dict[str, Path] | None = None,
    conversation: str | None = None,
    skip: set[str] | frozenset[str] = frozenset(),
) -> dict | None:
    """A sessão do Codex que nasceu numa pasta depois de um instante (para retomar ou passar o trabalho).

    Com `conversation` (o thread-id que o Codex manda no notify, ou a conversa retomada), só serve
    a conversa com esse id, mesmo que o arquivo seja de antes do instante (v1.2.0: retomada pelo
    histórico, ela só seria achada depois do primeiro turno novo). Sem ele (antes do primeiro fim
    de turno), vale a mais recente, menos as de `skip`: as conversas que outros terminais abertos
    já sabem que são deles."""
    for item in list_sessions(accounts, limit=200 if conversation else 20, cwd=cwd, defaults=defaults):
        if item["cli"] != "codex":
            continue
        if conversation:
            if item["id"] == conversation:
                return item
            continue
        if item["atualizado"] < since or item["id"] in skip:
            continue
        return item
    return None
