"""GitHub pela CLI `gh` (v0.9.6): o PR do branch, criar, juntar e marcar pronto, e as issues
e os PRs abertos do repositório para o kanban.

A MÊTIS não guarda token: usa o login do próprio `gh` (`gh auth login`, feito pelo Pedro).
Tudo passa pela função `gh()`, que os testes trocam; sem `gh` ou sem login, as consultas
voltam vazias e nunca derrubam a tela. Listas e estado ficam 60 s em cache por pasta, porque
o painel pergunta a cada poucos segundos e o GitHub tem limite de chamadas.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from typing import Any

TIMEOUT = 30
CACHE_SECONDS = 60
PR_FIELDS = "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup,reviewDecision,mergeable"

_cache: dict[tuple[str, str], tuple[float, Any]] = {}
_lock = threading.Lock()


class GithubError(RuntimeError):
    pass


def gh(cwd: str, *args: str, timeout: float = TIMEOUT) -> tuple[int, str, str]:
    """Roda o `gh` na pasta, sem perguntas nem cores. Devolve (código, stdout, stderr)."""
    exe = shutil.which("gh")
    if not exe:
        return 127, "", "o gh não está instalado"
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1", "GH_PAGER": "cat"}
    try:
        done = subprocess.run([exe, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", f"gh: {exc}"
    return done.returncode, done.stdout, done.stderr


def clear(cwd: str | None = None) -> None:
    with _lock:
        for key in [k for k in _cache if cwd is None or k[0] == cwd]:
            _cache.pop(key, None)


def _cached(cwd: str, name: str, compute):
    now = time.monotonic()
    with _lock:
        hit = _cache.get((cwd, name))
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = compute()
    with _lock:
        _cache[(cwd, name)] = (now, value)
    return value


def _json(cwd: str, *args: str) -> Any | None:
    code, out, _ = gh(cwd, *args)
    if code != 0:
        return None
    try:
        return json.loads(out or "null")
    except ValueError:
        return None


def checks_summary(rollup: list | None) -> dict:
    """statusCheckRollup → quantos passaram, falharam e estão rodando."""
    summary = {"ok": 0, "falhou": 0, "pendente": 0}
    for item in rollup or []:
        if not isinstance(item, dict):
            continue
        # CheckRun traz conclusion/status; StatusContext traz state.
        result = (item.get("conclusion") or item.get("state") or "").upper()
        if result in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            summary["ok"] += 1
        elif result in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "ERROR", "STARTUP_FAILURE"):
            summary["falhou"] += 1
        else:
            summary["pendente"] += 1
    return summary


def pr_from(data: dict) -> dict:
    return {
        "numero": data.get("number"),
        "titulo": data.get("title") or "",
        "url": data.get("url") or "",
        "estado": data.get("state") or "OPEN",
        "rascunho": bool(data.get("isDraft")),
        "base": data.get("baseRefName") or "",
        "cabeca": data.get("headRefName") or "",
        "checks": checks_summary(data.get("statusCheckRollup")),
        "revisao": data.get("reviewDecision") or None,
        "mesclavel": data.get("mergeable") or "UNKNOWN",
    }


def logged_in(cwd: str) -> bool:
    return _cached(cwd, "auth", lambda: gh(cwd, "auth", "status")[0] == 0)


def repo_name(cwd: str) -> str | None:
    def compute():
        data = _json(cwd, "repo", "view", "--json", "nameWithOwner")
        return data.get("nameWithOwner") if isinstance(data, dict) else None

    return _cached(cwd, "repo", compute)


def current_pr(cwd: str) -> dict | None:
    """O PR do branch atual; sem PR (o gh sai com "no pull requests found"), None."""
    data = _json(cwd, "pr", "view", "--json", PR_FIELDS)
    return pr_from(data) if isinstance(data, dict) and data.get("number") else None


def state(cwd: str) -> dict:
    """O que o painel de Mudanças mostra: há gh logado, qual o repositório e o PR do branch."""
    if not logged_in(cwd):
        return {"gh": False, "repo": None, "pr": None}
    repo = repo_name(cwd)
    if not repo:
        return {"gh": True, "repo": None, "pr": None}
    pr = _cached(cwd, "pr", lambda: current_pr(cwd))
    return {"gh": True, "repo": repo, "pr": pr}


def _fail(code: int, out: str, err: str, what: str) -> None:
    if code != 0:
        raise GithubError((err.strip() or out.strip() or f"o gh falhou ao {what}")[:4000])


def create_pr(cwd: str, title: str, body: str, base: str, draft: bool) -> dict:
    args = ["pr", "create", "--title", title, "--body", body, "--base", base]
    if draft:
        args.append("--draft")
    code, out, err = gh(cwd, *args, timeout=60)
    _fail(code, out, err, "criar o PR")
    clear(cwd)
    pr = current_pr(cwd)
    return pr or {"ok": True, "url": out.strip().splitlines()[-1] if out.strip() else ""}


def merge_pr(cwd: str, number: int, method: str) -> dict:
    if method not in ("rebase", "squash", "merge"):
        raise GithubError(f"jeito de juntar inválido: {method}")
    # Sem --delete-branch: numa worktree, o gh tentaria trocar de branch e falharia.
    code, out, err = gh(cwd, "pr", "merge", str(number), f"--{method}", timeout=90)
    _fail(code, out, err, "juntar o PR")
    clear(cwd)
    return current_pr(cwd) or {"ok": True}


def mark_ready(cwd: str, number: int) -> dict:
    code, out, err = gh(cwd, "pr", "ready", str(number))
    _fail(code, out, err, "marcar o PR como pronto")
    clear(cwd)
    return current_pr(cwd) or {"ok": True}


def items(cwd: str) -> dict:
    """Issues e PRs abertos do repositório da pasta, para o kanban."""
    if not logged_in(cwd):
        return {"gh": False, "issues": [], "prs": []}
    if not repo_name(cwd):
        return {"gh": True, "issues": [], "prs": []}

    def compute():
        issues = _json(cwd, "issue", "list", "--state", "open", "--limit", "50", "--json", "number,title,url,labels,author,updatedAt") or []
        prs = _json(cwd, "pr", "list", "--state", "open", "--limit", "30", "--json", "number,title,url,isDraft,headRefName,author,statusCheckRollup") or []
        return {
            "gh": True,
            "issues": [
                {
                    "numero": i.get("number"),
                    "titulo": i.get("title") or "",
                    "url": i.get("url") or "",
                    "rotulos": [label.get("name", "") for label in i.get("labels") or [] if isinstance(label, dict)],
                    "autor": (i.get("author") or {}).get("login", ""),
                    "atualizado": i.get("updatedAt") or "",
                }
                for i in issues
                if isinstance(i, dict)
            ],
            "prs": [
                {
                    "numero": p.get("number"),
                    "titulo": p.get("title") or "",
                    "url": p.get("url") or "",
                    "rascunho": bool(p.get("isDraft")),
                    "cabeca": p.get("headRefName") or "",
                    "autor": (p.get("author") or {}).get("login", ""),
                    "checks": checks_summary(p.get("statusCheckRollup")),
                }
                for p in prs
                if isinstance(p, dict)
            ],
        }

    return _cached(cwd, "itens", compute)
