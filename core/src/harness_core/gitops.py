"""Git para a revisão e as worktrees: sempre o `git` da máquina, chamado com argumentos fixos.

Nada aqui passa por shell. Caminhos de arquivo vão sempre depois de `--`.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path

from .accounts import slugify

GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
ENV_FILES = (".env", ".env.local", ".env.development", ".env.development.local")


class GitError(RuntimeError):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


async def git(cwd: str | Path, *args: str, check: bool = True, timeout: float = 60.0, ok_codes: tuple[int, ...] = (0,)) -> str:
    env = {**os.environ, **GIT_ENV}
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise GitError(f"git {args[0]} demorou demais") from None
    if check and proc.returncode not in ok_codes:
        message = err.decode("utf-8", "replace").strip() or out.decode("utf-8", "replace").strip()
        raise GitError(message or f"git {args[0]} falhou", proc.returncode)
    return out.decode("utf-8", "replace")


async def toplevel(path: str | Path) -> Path:
    return Path((await git(path, "rev-parse", "--show-toplevel")).strip())


# --- worktrees ---------------------------------------------------------------


def parse_worktrees(porcelain: str) -> list[dict]:
    """Saída de `git worktree list --porcelain` → lista; a primeira é a pasta principal."""
    result: list[dict] = []
    for block in porcelain.strip().split("\n\n"):
        if not block.strip():
            continue
        item: dict = {"path": "", "head": None, "branch": None, "detached": False, "locked": False, "prunable": False, "bare": False}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                item["path"] = value
            elif key == "HEAD":
                item["head"] = value
            elif key == "branch":
                item["branch"] = value.removeprefix("refs/heads/")
            elif key in ("detached", "locked", "prunable", "bare"):
                item[key] = True
        result.append(item)
    for index, item in enumerate(result):
        item["main"] = index == 0
    return result


async def list_worktrees(repo: str | Path) -> list[dict]:
    return parse_worktrees(await git(repo, "worktree", "list", "--porcelain"))


async def create_worktree(repo: str | Path, root: Path, name: str, base: str | None = None, copy_env: bool = True) -> dict:
    repo_path = await toplevel(repo)
    slug = slugify(name)
    target = root / repo_path.name / slug
    if target.exists():
        raise GitError(f"já existe uma pasta em {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    branch_exists = (await git(repo_path, "branch", "--list", slug)).strip() != ""
    if branch_exists:
        await git(repo_path, "worktree", "add", str(target), slug)
    else:
        await git(repo_path, "worktree", "add", "-b", slug, str(target), base or "HEAD")
    copied: list[str] = []
    if copy_env:
        # .env não vai para o git; sem ele o app da worktree nem sobe.
        for env_name in ENV_FILES:
            source = repo_path / env_name
            if source.is_file() and not (target / env_name).exists():
                shutil.copy2(source, target / env_name)
                copied.append(env_name)
    return {"path": str(target), "branch": slug, "copied": copied}


async def remove_worktree(repo: str | Path, path: str, force: bool = False) -> dict:
    worktrees = await list_worktrees(repo)
    match = next((w for w in worktrees if os.path.realpath(w["path"]) == os.path.realpath(path)), None)
    if match is None:
        raise GitError("essa pasta não é uma worktree deste projeto")
    if match["main"]:
        raise GitError("a pasta principal do repositório não se apaga por aqui")
    if not force:
        changes = (await status(path))["files"]
        if changes:
            raise GitError(f"a worktree tem {len(changes)} mudança(s) sem commit", 409)
    args = ["worktree", "remove", path] + (["--force", "--force"] if force else [])
    await git(repo, *args)
    branch = match["branch"]
    result = {"removed": path, "branch": branch, "branch_deleted": False, "branch_kept": None}
    if branch:
        try:
            # Sempre -d: "forçar" vale para as mudanças da pasta, nunca para commits do branch.
            await git(repo, "branch", "-d", branch)
            result["branch_deleted"] = True
        except GitError as exc:
            # Branch com commits que não foram para lugar nenhum fica guardado.
            result["branch_kept"] = str(exc).splitlines()[0]
    return result


# --- status e diff ---------------------------------------------------------------


def parse_status(raw: str) -> dict:
    """`git status --porcelain=v2 --branch -z`."""
    info: dict = {"branch": None, "head": None, "upstream": None, "ahead": 0, "behind": 0, "files": []}
    fields = raw.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry:
            continue
        if entry.startswith("# "):
            key, _, value = entry[2:].partition(" ")
            if key == "branch.head":
                info["branch"] = None if value == "(detached)" else value
            elif key == "branch.oid":
                info["head"] = None if value == "(initial)" else value
            elif key == "branch.upstream":
                info["upstream"] = value
            elif key == "branch.ab":
                match = re.match(r"\+(\d+) -(\d+)", value)
                if match:
                    info["ahead"], info["behind"] = int(match[1]), int(match[2])
            continue
        kind = entry[0]
        if kind == "?":
            info["files"].append(_file(entry[2:], "?", "?", untracked=True))
        elif kind in ("1", "2", "u"):
            parts = entry.split(" ")
            xy = parts[1]
            if kind == "1":
                path = " ".join(parts[8:])
                info["files"].append(_file(path, xy[0], xy[1]))
            elif kind == "2":
                path = " ".join(parts[9:])
                orig = fields[i] if i < len(fields) else None
                i += 1
                info["files"].append(_file(path, xy[0], xy[1], orig=orig))
            else:
                path = " ".join(parts[10:])
                info["files"].append(_file(path, xy[0], xy[1], conflict=True))
    return info


def _file(path: str, x: str, y: str, orig: str | None = None, untracked: bool = False, conflict: bool = False) -> dict:
    return {
        "path": path,
        "orig": orig,
        "x": x,
        "y": y,
        "staged": not untracked and x not in ".?",
        "unstaged": untracked or y not in ".",
        "untracked": untracked,
        "conflict": conflict,
    }


async def status(path: str | Path) -> dict:
    raw = await git(path, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all")
    return parse_status(raw)


async def diff(path: str | Path, file: str, mode: str = "head", untracked: bool = False) -> str:
    """mode: "head" (tudo desde o último commit), "staged" ou "worktree" (só o que não foi marcado)."""
    if untracked:
        return await git(path, "diff", "--no-color", "--no-index", "--", "/dev/null", file, ok_codes=(0, 1))
    if mode == "staged":
        return await git(path, "diff", "--no-color", "--cached", "--", file)
    if mode == "worktree":
        return await git(path, "diff", "--no-color", "--", file)
    try:
        return await git(path, "diff", "--no-color", "HEAD", "--", file)
    except GitError:
        return await git(path, "diff", "--no-color", "--cached", "--", file)  # repositório sem commit ainda


async def stage(path: str | Path, files: list[str]) -> None:
    if files:
        await git(path, "add", "--", *files)


async def unstage(path: str | Path, files: list[str]) -> None:
    if not files:
        return
    try:
        await git(path, "restore", "--staged", "--", *files)
    except GitError:
        await git(path, "rm", "--cached", "-r", "--quiet", "--", *files)  # sem HEAD ainda


async def commit(path: str | Path, message: str) -> str:
    await git(path, "commit", "-m", message)
    return (await git(path, "rev-parse", "--short", "HEAD")).strip()


async def push(path: str | Path) -> str:
    return await git(path, "push", "-u", "origin", "HEAD", timeout=120)


async def pull(path: str | Path) -> str:
    return await git(path, "pull", "--ff-only", timeout=120)


async def list_files(path: str | Path, limit: int = 20000) -> list[str]:
    """Arquivos do projeto sem os ignorados pelo git (node_modules, build...)."""
    raw = await git(path, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    files = sorted({f for f in raw.split("\0") if f})
    return files[:limit]
