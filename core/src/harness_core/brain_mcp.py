"""O Brain para as sessões de FORA da MÊTIS (Claude Code e Codex abertos em qualquer terminal).

- `metis brain mcp`: servidor MCP por stdio, instalado no escopo de usuário do Claude Code e
  no ~/.codex/config.toml, com brain_buscar, brain_ler, brain_precedentes, brain_conflitos e
  brain_sugestoes. Funciona com a MÊTIS fechada. Dentro de uma sessão da MÊTIS
  (HARNESS_SESSION_ID no ambiente) ele não oferece nada: a central `metis` já tem tudo.
- `metis brain contexto`: hook SessionStart do ~/.claude/settings.json. Imprime os
  precedentes de outros projetos e as sugestões pendentes do projeto da pasta.

Nenhum dos dois carrega o modelo de significado (1,5 GB por processo): usam os vetores já
guardados no brain.db pelo núcleo e, para texto livre, pedem o vetor ao núcleo se ele
estiver aberto; senão, a busca fica só por palavra.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO

from . import __version__
from .brain_index import BrainIndex
from .brain_tools import DESCRIPTIONS, BrainTools
from .config import Settings
from .vault import Vault, VaultError

PROTOCOL = "2025-06-18"
INSTRUCTIONS_OUT = (
    "Brain do Pedro (vault Obsidian em ~/Documents/Brain), servido pela MÊTIS. Use brain_precedentes para ver o que "
    "outros projetos já decidiram, brain_conflitos ANTES de registrar uma decisão (acha repetição e contradição no "
    "próprio projeto) e brain_ler para ler uma nota. brain_sugestoes lista as sugestões esperando o Pedro."
)
INSTRUCTIONS_IN = "Dentro da MÊTIS este servidor fica vazio: use as ferramentas do servidor metis."


def inside_metis() -> bool:
    return bool(os.environ.get("HARNESS_SESSION_ID"))


class RemoteEncoder:
    """Vetores pelo núcleo da MÊTIS em execução (runtime.json). Fora do ar: None, e não insiste por 1 min."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self._down_until = 0.0

    def __call__(self, texts: list[str], wait: float) -> list | None:
        if time.monotonic() < self._down_until:
            return None
        try:
            info = json.loads((self.home / "runtime.json").read_text(encoding="utf-8"))
            request = urllib.request.Request(
                f"{info['url']}/brain/embed",
                data=json.dumps({"texts": texts[:64]}).encode(),
                method="POST",
                headers={"X-Harness-Token": info["token"], "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=max(3.0, wait + 3)) as response:
                vectors = json.loads(response.read().decode("utf-8"))["vectors"]
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            self._down_until = time.monotonic() + 60
            return None
        import numpy as np

        from .semantic import normalize

        return normalize(np.asarray(vectors, dtype=np.float32))


def pending_suggestions(home: Path, project: str) -> list[dict]:
    """As sugestões pendentes do projeto, lidas direto do banco do núcleo (sem criar nada)."""
    db = home / "sugestoes.db"
    if not db.exists() or not project:
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("select * from suggestions where status = 'pendente' and target_project = ? order by created desc limit 10", (project,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def make_index(settings: Settings, remote: bool = True) -> BrainIndex:
    return BrainIndex(Vault(settings.brain), settings.home / "brain.db", encode=RemoteEncoder(settings.home) if remote else None)


# --- hook de início de sessão ------------------------------------------------------------------


def session_hook(settings: Settings, payload: dict) -> str:
    if inside_metis():
        return ""
    cwd = str(payload.get("cwd") or os.getcwd())
    index = make_index(settings, remote=False)
    try:
        project, found = index.session_precedents(cwd)
    except (VaultError, OSError, sqlite3.Error):
        return ""
    if not project:
        return ""
    pending = pending_suggestions(settings.home, project)
    extra = []
    if pending:
        extra.append(f"Sugestões de precedente esperando o Pedro em [[{project}]] (ele aceita ou recusa na MÊTIS):")
        extra += [f"- 💡 #{p['id']} {p['title']} (de [[{p['source_title']}]], {p['source_project']})" for p in pending[:5]]
    return index.render_context(project, found, extra, inside_metis=False)


# --- servidor MCP por stdio --------------------------------------------------------------------------


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


PROJECT = {"type": "string", "description": "Nome do projeto no Brain. Vazio: o projeto da pasta desta sessão."}
TOOLS = [
    {"name": "brain_buscar", "description": DESCRIPTIONS["brain_buscar"], "inputSchema": _schema(
        {"termos": {"type": "string"}, "tipo": {"type": "string", "description": "decisao, incidente, aprendizado, entrega, projeto (vírgula para vários)"}, "projeto": {"type": "string"}}, ["termos"])},
    {"name": "brain_ler", "description": DESCRIPTIONS["brain_ler"], "inputSchema": _schema({"titulo": {"type": "string"}}, ["titulo"])},
    {"name": "brain_precedentes", "description": DESCRIPTIONS["brain_precedentes"], "inputSchema": _schema(
        {"termos": {"type": "string", "description": "Uma frase sobre o assunto. Vazio: o momento do projeto."}, "projeto": PROJECT}, [])},
    {"name": "brain_conflitos", "description": DESCRIPTIONS["brain_conflitos"], "inputSchema": _schema(
        {"decisao": {"type": "string", "description": "A decisão numa frase afirmada."}, "projeto": PROJECT}, ["decisao"])},
    {"name": "brain_sugestoes", "description": DESCRIPTIONS["brain_sugestoes"], "inputSchema": _schema({"projeto": PROJECT}, [])},
]  # fmt: skip


class StdioServer:
    def __init__(self, settings: Settings, cwd: str | None = None) -> None:
        self.settings = settings
        self.cwd = cwd or os.getcwd()
        self.index = make_index(settings)
        self.tools = BrainTools(self.index, pending=lambda project: pending_suggestions(settings.home, project))

    def _project(self, args: dict) -> str:
        name = str(args.get("projeto") or "").strip()
        if name:
            return name
        note = self.index.vault.project_for_dir(self.cwd)
        return note.name if note else ""

    def call(self, name: str, args: dict) -> dict:
        try:
            if name == "brain_buscar":
                text, _ = self.tools.buscar(str(args.get("termos", "")), str(args.get("tipo") or ""), str(args.get("projeto") or ""))
            elif name == "brain_ler":
                text, _ = self.tools.ler(str(args.get("titulo", "")))
            elif name == "brain_precedentes":
                text, _ = self.tools.precedentes(self._project(args), str(args.get("termos") or ""))
            elif name == "brain_conflitos":
                text, _ = self.tools.conflitos(str(args.get("decisao", "")), self._project(args))
            elif name == "brain_sugestoes":
                text, _ = self.tools.sugestoes(self._project(args))
            else:
                return {"content": [{"type": "text", "text": f"ferramenta desconhecida: {name}"}], "isError": True}
        except (VaultError, OSError, sqlite3.Error, ValueError) as exc:
            return {"content": [{"type": "text", "text": f"Erro: {exc}"}], "isError": True}
        return {"content": [{"type": "text", "text": text}]}

    def handle(self, message: dict) -> dict | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "mensagem JSON-RPC inválida"}}
        method, mid = message.get("method"), message.get("id")
        if mid is None:
            return None  # notificação
        params = message.get("params") or {}
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "metis-brain", "title": "Brain (MÊTIS)", "version": __version__},
                "instructions": INSTRUCTIONS_IN if inside_metis() else INSTRUCTIONS_OUT,
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [] if inside_metis() else TOOLS}
        elif method == "tools/call":
            result = self.call(str(params.get("name", "")), params.get("arguments") or {})
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"método desconhecido: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def serve(self, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> None:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}}
            else:
                if isinstance(message, list):
                    replies = [r for r in (self.handle(m) for m in message) if r is not None]
                    reply = replies or None
                else:
                    reply = self.handle(message)
            if reply is not None:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()
