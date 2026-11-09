"""O grafo do código pelo graphify (v0.9.8, parte 5), para os agentes pela central de MCP.

O graphify (o CLI da skill /graphify, em ~/.local/bin) guarda o grafo de um repositório em
`<repo>/graphify-out/graph.json`. Consultar não usa IA: `graphify query`, `graphify path` e
`graphify explain` leem o graph.json, e `graphify update <pasta>` reextrai o código sem IA.
Gerar do zero precisa de IA e fica com o Claude, pela skill /graphify.

Tudo passa por `run()`, que os testes trocam.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

TIMEOUT = 60
GRAPH = Path("graphify-out") / "graph.json"
REPORT = Path("graphify-out") / "GRAPH_REPORT.md"


class GraphifyError(RuntimeError):
    pass


def executable() -> str | None:
    """O CLI pelo PATH do núcleo, ou o lugar de sempre (~/.local/bin)."""
    found = shutil.which("graphify")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "graphify"
    return str(fallback) if fallback.is_file() and os.access(fallback, os.X_OK) else None


def run(args: list[str], cwd: str, timeout: float = TIMEOUT) -> tuple[int, str, str]:
    exe = executable()
    if not exe:
        return 127, "", "o graphify não está instalado (pip install graphify, ou a skill /graphify)"
    env = {**os.environ, "NO_COLOR": "1"}
    try:
        done = subprocess.run([exe, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, "", f"o graphify não respondeu em {int(timeout)} s"
    except OSError as exc:
        return 1, "", f"graphify: {exc}"
    return done.returncode, done.stdout, done.stderr


def find_root(cwd: str | None) -> Path | None:
    """O repositório com grafo que contém a pasta: sobe a partir dela até achar graphify-out/graph.json."""
    if not cwd:
        return None
    here = Path(cwd).expanduser()
    for folder in [here, *here.parents]:
        if (folder / GRAPH).is_file():
            return folder
        if (folder / ".git").exists():
            return None  # chegou na raiz do repositório e não há grafo
    return None


def _answer(code: int, out: str, err: str, what: str) -> str:
    if code != 0:
        raise GraphifyError(f"{what}: {(err or out).strip()[:400] or f'código {code}'}")
    return out.strip() or "(o graphify não devolveu nada)"


def query(root: Path, question: str, budget: int = 1500) -> str:
    question = question.strip()
    if not question:
        raise GraphifyError("diga a pergunta")
    budget = max(200, min(int(budget or 1500), 8000))
    return _answer(*run(["query", question, "--budget", str(budget), "--graph", str(root / GRAPH)], str(root)), "o graphify não respondeu à consulta")


def path(root: Path, source: str, target: str) -> str:
    if not source.strip() or not target.strip():
        raise GraphifyError("diga os dois conceitos (de e para)")
    return _answer(*run(["path", source.strip(), target.strip(), "--graph", str(root / GRAPH)], str(root)), "o graphify não achou o caminho")


def explain(root: Path, concept: str) -> str:
    if not concept.strip():
        raise GraphifyError("diga o conceito")
    return _answer(*run(["explain", concept.strip(), "--graph", str(root / GRAPH)], str(root)), "o graphify não explicou o conceito")


def state(root: str) -> dict:
    """O que a tela mostra do grafo de um repositório."""
    folder = Path(root).expanduser()
    graph = folder / GRAPH
    report = folder / REPORT
    nodes = None
    updated = None
    if graph.is_file():
        updated = graph.stat().st_mtime
        try:
            data = json.loads(graph.read_text(encoding="utf-8"))
            items = data.get("nodes") if isinstance(data, dict) else None
            nodes = len(items) if isinstance(items, list) else None
        except (OSError, ValueError):
            nodes = None
    return {
        "existe": graph.is_file(),
        "atualizado": updated,
        "nos": nodes,
        "relatorio": str(report) if report.is_file() else None,
        "graphify": executable() is not None,
    }


def update(root: str) -> str:
    """`graphify update <pasta>`: reextrai o código sem IA. Pode demorar em repositório grande."""
    return _answer(*run(["update", str(Path(root).expanduser())], str(Path(root).expanduser()), timeout=600), "o graphify não atualizou o grafo")
