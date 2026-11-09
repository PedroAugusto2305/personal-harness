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
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
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


# --- checks falhos e revisão de PR (v0.9.8, parte 5) -------------------------------------

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
LOG_LINES = 150
LOG_BUDGET = 12000
FAILED = {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED", "ERROR"}
JOB_LINK = re.compile(r"/actions/runs/(\d+)(?:/job/(\d+))?")


def _clean_log(raw: str) -> list[str]:
    """`gh run view --log-failed` traz "job<TAB>passo<TAB>hora texto": fica só o texto, sem
    cores, sem as linhas vazias e sem as marcas de grupo do Actions."""
    lines = []
    for line in ANSI.sub("", raw or "").splitlines():
        text = line.split("\t")[-1] if "\t" in line else line
        text = STAMP.sub("", text).rstrip()
        if not text.strip() or text.startswith(("##[group]", "##[endgroup]")):
            continue
        lines.append(text)
    return lines


def _job_log(cwd: str, link: str = "", run_id: str = "") -> str:
    match = JOB_LINK.search(link or "")
    run = (match.group(1) if match else "") or run_id
    job = match.group(2) if match else ""
    if not run and not job:
        return ""
    args = ["run", "view", "--job", job, "--log-failed"] if job else ["run", "view", run, "--log-failed"]
    code, out, _ = gh(cwd, *args, timeout=60)
    if code != 0:
        return ""
    return "\n".join(_clean_log(out)[-LOG_LINES:])


def _head_sha(cwd: str) -> str:
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def failed_checks(cwd: str) -> dict:
    """Os checks que falharam no PR do branch (ou no último commit, sem PR), com o fim do
    log de cada job do Actions. Os logs somam no máximo LOG_BUDGET caracteres."""
    pr = current_pr(cwd)
    found: list[dict] = []
    if pr:
        code, out, _ = gh(cwd, "pr", "checks", str(pr["numero"]), "--json", "name,state,bucket,link,description,workflow")
        try:
            items = json.loads(out or "[]")  # sai com código ≠ 0 quando algum falhou, mas o JSON vem
        except ValueError:
            items = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get("bucket") != "fail" and str(item.get("state") or "").upper() not in FAILED:
                continue
            name = item.get("name") or item.get("workflow") or "check"
            found.append({"nome": name, "url": item.get("link") or "", "resumo": item.get("description") or "", "_run": ""})
    else:
        sha = _head_sha(cwd)
        runs = _json(cwd, "run", "list", "--commit", sha, "--json", "databaseId,conclusion,workflowName,displayTitle,url", "--limit", "20") if sha else None
        for run in runs if isinstance(runs, list) else []:
            if str(run.get("conclusion") or "").upper() not in FAILED:
                continue
            name = run.get("workflowName") or run.get("displayTitle") or "workflow"
            found.append({"nome": name, "url": run.get("url") or "", "resumo": run.get("displayTitle") or "", "_run": str(run.get("databaseId") or "")})
    budget = LOG_BUDGET
    checks = []
    for item in found:
        log = _job_log(cwd, item["url"], item["_run"]) if budget > 0 else ""
        if len(log) > budget:
            log = log[-budget:]
        budget -= len(log)
        checks.append({"nome": item["nome"], "url": item["url"], "resumo": item["resumo"], "log": log})
    return {"pr": pr["numero"] if pr else None, "checks": checks}


def _names(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " e " + items[-1]


def checks_request(cwd: str) -> str:
    """O pedido pronto para o agente da worktree consertar os checks que falharam."""
    data = failed_checks(cwd)
    if not data["checks"]:
        raise GithubError("nenhum check falhou" + (f" no PR #{data['pr']}" if data["pr"] else " no último commit"))
    names = [c["nome"] for c in data["checks"]]
    plural = len(names) > 1
    where = f"do PR #{data['pr']}" if data["pr"] else f"do último commit ({_head_sha(cwd)[:7]})"
    lines = [f"O{'s' if plural else ''} check{'s' if plural else ''} {_names(names)} {where} falh{'aram' if plural else 'ou'}."]
    for check in data["checks"]:
        lines += ["", f"### {check['nome']}"]
        if check["url"]:
            lines.append(check["url"])
        if check["resumo"]:
            lines.append(check["resumo"])
        lines += ["```", check["log"], "```"] if check["log"] else ["(sem log: abra o link para ver o que falhou)"]
    lines += ["", "Ache a causa, corrija nesta worktree e rode o que der localmente antes de subir."]
    return "\n".join(lines)


def review_request(cwd: str, numero: int | None = None) -> tuple[int, str]:
    """O pedido de revisão só de leitura: o diff do PR fica num arquivo que o agente lê."""
    if numero is None:
        pr = current_pr(cwd)
        if not pr:
            raise GithubError("este branch não tem PR aberto: diga o número do PR para revisar")
        numero = int(pr["numero"])
    code, diff, err = gh(cwd, "pr", "diff", str(numero), timeout=60)
    if code != 0:
        raise GithubError(f"não consegui o diff do PR #{numero}: {(err or diff).strip()[:200]}")
    info = _json(cwd, "pr", "view", str(numero), "--json", "title,body,baseRefName,headRefName") or {}
    folder = Path(tempfile.gettempdir()) / "metis-revisoes"
    folder.mkdir(parents=True, exist_ok=True)
    repo = (repo_name(cwd) or Path(cwd).name).replace("/", "-")
    diff_file = folder / f"{repo}-pr-{numero}.diff"
    diff_file.write_text(diff, encoding="utf-8")
    title = info.get("title") if isinstance(info, dict) else ""
    body = (info.get("body") or "").strip() if isinstance(info, dict) else ""
    lines = [
        f"Revise o PR #{numero}{f' ({title})' if title else ''} deste repositório, só lendo.",
        f"O diff completo está em {diff_file} (leia com a ferramenta de leitura de arquivos); leia também os arquivos do repositório que precisar para entender o contexto.",
    ]
    if isinstance(info, dict) and info.get("baseRefName"):
        lines.append(f"Branch {info.get('headRefName')} → {info.get('baseRefName')}.")
    if body:
        lines += ["", "Descrição do PR:", body[:3000]]
    lines += [
        "",
        "Liste os problemas por gravidade (crítico, importante, menor), cada um com arquivo:linha, o porquê e a correção sugerida. "
        "Diga também o que está bom. Não edite arquivo, não faça commit e não comente no GitHub: a revisão fica só aqui no terminal.",
    ]
    return numero, "\n".join(lines)
