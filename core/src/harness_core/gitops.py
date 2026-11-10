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


async def git_bytes(
    cwd: str | Path,
    *args: str,
    check: bool = True,
    timeout: float = 60.0,
    ok_codes: tuple[int, ...] = (0,),
    input: bytes | None = None,
    full_output: bool = False,
) -> bytes:
    """O git com a saída crua. `input` vai no stdin (patch do `git apply`); `full_output` põe
    stdout e stderr juntos na mensagem de erro (a saída de um hook de pre-commit sai nos dois)."""
    env = {**os.environ, **GIT_ENV}
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE if input is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(input), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise GitError(f"git {args[0]} demorou demais") from None
    if check and proc.returncode not in ok_codes:
        text_out = out.decode("utf-8", "replace").strip()
        text_err = err.decode("utf-8", "replace").strip()
        if full_output:
            message = "\n".join(part for part in (text_out, text_err) if part)
        else:
            message = text_err or text_out
        raise GitError(message or f"git {args[0]} falhou", proc.returncode)
    return out


async def git(
    cwd: str | Path,
    *args: str,
    check: bool = True,
    timeout: float = 60.0,
    ok_codes: tuple[int, ...] = (0,),
    input: bytes | None = None,
    full_output: bool = False,
) -> str:
    out = await git_bytes(cwd, *args, check=check, timeout=timeout, ok_codes=ok_codes, input=input, full_output=full_output)
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


WORKTREE_MODES = ("nova", "branch", "commit")


async def _ref_exists(repo: Path, ref: str) -> bool:
    out = await git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", ref, check=False)
    return bool(out.strip())


async def _resolve_branch(repo: Path, base: str) -> tuple[str, str | None]:
    """Branch existente → (branch local, ref remota a seguir ou None). origin/x sem x local segue a remota."""
    if await _ref_exists(repo, f"refs/heads/{base}"):
        return base, None
    remotes = (await git(repo, "remote")).split()
    for remote in remotes:
        prefix = f"{remote}/"
        if base.startswith(prefix) and len(base) > len(prefix):
            local = base[len(prefix) :]
            if await _ref_exists(repo, f"refs/heads/{local}"):
                return local, None
            if await _ref_exists(repo, f"refs/remotes/{base}"):
                return local, base
    if "origin" in remotes and await _ref_exists(repo, f"refs/remotes/origin/{base}"):
        return base, f"origin/{base}"
    raise GitError(f"o branch {base} não existe neste repositório")


async def create_worktree(
    repo: str | Path,
    root: Path,
    name: str,
    base: str | None = None,
    copy_env: bool = True,
    mode: str = "nova",
) -> dict:
    """Worktree nova. modo "nova": branch novo com o nome, a partir de `base` (ou do HEAD);
    "branch": abre um branch que já existe (local, ou remoto seguido por um local);
    "commit": branch novo com o nome, a partir de um commit."""
    if mode not in WORKTREE_MODES:
        raise GitError(f"modo de worktree desconhecido: {mode}")
    repo_path = await toplevel(repo)
    name = (name or "").strip()
    base = (base or "").strip() or None
    remote: str | None = None
    if mode == "branch":
        if not base:
            raise GitError("diga qual branch abrir")
        branch, remote = await _resolve_branch(repo_path, base)
        busy = next((w for w in await list_worktrees(repo_path) if w["branch"] == branch), None)
        if busy:
            raise GitError(f"o branch {branch} já está aberto em {busy['path']}", 409)
        slug = slugify(name or branch)
    else:
        if not name:
            raise GitError("diga o nome da worktree")
        slug = slugify(name)
        branch = slug
        if mode == "commit" and not base:
            raise GitError("diga de qual commit partir")
        if base and not await _ref_exists(repo_path, f"{base}^{{commit}}"):
            raise GitError(f"{'o commit' if mode == 'commit' else 'a base'} {base} não existe neste repositório")
    target = root / repo_path.name / slug
    if target.exists():
        raise GitError(f"já existe uma pasta em {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "branch":
        if remote:
            await git(repo_path, "worktree", "add", "--track", "-b", branch, str(target), remote)
        else:
            await git(repo_path, "worktree", "add", str(target), branch)
    else:
        branch_exists = await _ref_exists(repo_path, f"refs/heads/{slug}")
        if branch_exists and mode == "commit":
            raise GitError(f"já existe um branch {slug}: escolha outro nome", 409)
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
    return {"path": str(target), "branch": branch, "copied": copied}


async def list_refs(repo: str | Path, query: str = "") -> dict:
    """Branches (locais e remotas, mais recentes primeiro) e commits recentes, para abrir worktree."""
    repo_path = await toplevel(repo)
    needle = query.strip().casefold()
    raw = await git(
        repo_path,
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname)%00%(refname:short)%00%(committerdate:iso-strict)%00%(subject)%00%(HEAD)",
        "refs/heads",
        "refs/remotes",
        check=False,
    )
    in_use = {w["branch"]: w["path"] for w in await list_worktrees(repo_path) if w["branch"]}
    rows = [line.split("\0") for line in raw.splitlines() if line.count("\0") == 4]
    locals_ = {short for ref, short, *_ in rows if ref.startswith("refs/heads/")}
    remotes = set((await git(repo_path, "remote", check=False)).split())
    branches: list[dict] = []
    for ref, short, when, subject, head in rows:
        remote = ref.startswith("refs/remotes/")
        if remote:
            if ref.endswith("/HEAD"):
                continue
            owner, _, local = short.partition("/")
            if owner in remotes and local in locals_:
                continue
        if needle and needle not in short.casefold() and needle not in subject.casefold():
            continue
        branches.append({
            "nome": short,
            "remoto": remote,
            "atual": head.strip() == "*",
            "em_uso": None if remote else in_use.get(short),
            "quando": when,
            "titulo": subject,
        })  # fmt: skip
        if len(branches) >= 50:
            break
    log = await git(repo_path, "log", f"-{300 if needle else 30}", "--format=%H%x00%h%x00%s%x00%an%x00%aI", "HEAD", check=False)
    commits: list[dict] = []
    for line in log.splitlines():
        parts = line.split("\0")
        if len(parts) != 5:
            continue
        sha, short, subject, author, when = parts
        if needle and not sha.startswith(needle) and needle not in subject.casefold():
            continue
        commits.append({"sha": sha, "curto": short, "titulo": subject, "autor": author, "quando": when})
        if len(commits) >= 30:
            break
    return {"branches": branches, "commits": commits}


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


async def operation(path: str | Path) -> str | None:
    """Merge, rebase, cherry-pick ou revert em andamento (pelos arquivos na pasta do git, que
    o `--absolute-git-dir` acha também numa worktree)."""
    try:
        git_dir = Path((await git(path, "rev-parse", "--absolute-git-dir")).strip())
    except GitError:
        return None
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "rebase"
    if (git_dir / "MERGE_HEAD").exists():
        return "merge"
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return "cherry-pick"
    if (git_dir / "REVERT_HEAD").exists():
        return "revert"
    return None


_subjects: dict[str, tuple[str, str]] = {}


async def last_commit(path: str | Path, oid: str | None) -> tuple[str, str] | None:
    """O SHA curto e o assunto do commit `oid`. Um commit nunca muda, então fica guardado:
    o painel pergunta o status a cada 3 s e só precisa do `git log` quando o HEAD anda."""
    if not oid:
        return None  # repositório sem commit
    if oid not in _subjects:
        try:
            raw = await git(path, "log", "-1", "--format=%h%x00%s", oid)
        except GitError:
            return None
        sha, _, subject = raw.strip().partition("\0")
        if not sha:
            return None
        if len(_subjects) > 2000:
            _subjects.clear()
        _subjects[oid] = (sha, subject)
    return _subjects[oid]


async def status(path: str | Path) -> dict:
    raw = await git(path, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all")
    info = parse_status(raw)
    op, last = await asyncio.gather(operation(path), last_commit(path, info["head"]))
    info["operacao"] = op
    # Já subiu = o HEAD está no upstream, ou seja, nada à frente dele. Sem a linha branch.ab
    # (o branch remoto sumiu), não dá para saber, e conta como não subiu.
    pushed = bool(info["upstream"]) and "# branch.ab " in raw and info["ahead"] == 0
    info["ultimo_commit"] = {"sha": last[0], "assunto": last[1], "subiu": pushed} if last else None
    return info


# --- refs ---------------------------------------------------------------------


def check_ref(ref: str) -> str:
    """Ref vinda da tela: sem traço na frente (viraria opção), sem espaço nem controle."""
    ref = (ref or "").strip()
    if not ref or ref.startswith("-") or len(ref) > 200 or any(ch.isspace() or ord(ch) < 32 for ch in ref):
        raise GitError(f"referência inválida: {ref or '(vazia)'}", 400)
    return ref


async def resolve_ref(path: str | Path, ref: str) -> str:
    """O commit de uma ref (branch, tag, SHA, HEAD~2); 400 se não existir."""
    ref = check_ref(ref)
    try:
        return (await git(path, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")).strip()
    except GitError:
        raise GitError(f"referência não encontrada: {ref}", 400) from None


async def merge_base(path: str | Path, ref: str) -> str:
    """Onde este branch saiu da ref: comparar com ele mostra só o que este branch mudou."""
    sha = await resolve_ref(path, ref)
    try:
        return (await git(path, "merge-base", sha, "HEAD")).strip()
    except GitError:
        raise GitError(f"{ref} não tem história em comum com este branch", 400) from None


async def refs(path: str | Path) -> dict:
    heads = (await git(path, "for-each-ref", "--format=%(refname:short)", "refs/heads")).split()
    remote_full = (await git(path, "for-each-ref", "--format=%(refname)", "refs/remotes")).split()
    remotes = [r.removeprefix("refs/remotes/") for r in remote_full if not r.endswith("/HEAD")]
    tags = (await git(path, "for-each-ref", "--sort=-creatordate", "--count=50", "--format=%(refname:short)", "refs/tags")).split()
    current = (await git(path, "branch", "--show-current")).strip() or None
    default = None
    try:
        origin_head = (await git(path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")).strip()
        default = origin_head.split("/", 1)[1] if "/" in origin_head else origin_head
    except GitError:
        pass
    if not default:
        default = "main" if "main" in heads else "master" if "master" in heads else current
    return {"branches": heads, "remotos": remotes, "tags": tags, "padrao": default, "atual": current}


async def changed(path: str | Path, ref: str) -> dict:
    """Arquivos que mudaram desde onde este branch saiu da ref, inclusive o que não foi commitado."""
    base = await merge_base(path, ref)
    raw = await git(path, "diff", "--name-status", "-z", "-M", base)
    fields = [f for f in raw.split("\0")]
    files: list[dict] = []
    i = 0
    while i < len(fields):
        code = fields[i]
        i += 1
        if not code:
            continue
        kind = code[0]
        if kind in ("R", "C"):
            orig, new = fields[i], fields[i + 1]
            i += 2
            files.append({"path": new, "status": kind, "orig": orig})
        else:
            files.append({"path": fields[i], "status": kind, "orig": None})
            i += 1
    seen = {f["path"] for f in files}
    untracked = await git(path, "ls-files", "--others", "--exclude-standard", "-z")
    for rel in untracked.split("\0"):
        if rel and rel not in seen:
            files.append({"path": rel, "status": "A", "orig": None})
    short = (await git(path, "rev-parse", "--short", base)).strip()
    return {"ref": check_ref(ref), "base": short, "files": files}


async def diff(path: str | Path, file: str, mode: str = "head", untracked: bool = False, ref: str | None = None) -> str:
    """mode: "head" (tudo desde o último commit), "staged", "worktree" (só o que não foi marcado)
    ou "ref" (desde onde este branch saiu da `ref`, inclusive o que não foi commitado)."""
    if untracked:
        return await git(path, "diff", "--no-color", "--no-index", "--", "/dev/null", file, ok_codes=(0, 1))
    if mode == "ref":
        base = await merge_base(path, ref or "")
        out = await git(path, "diff", "--no-color", base, "--", file)
        # O `git diff <ref>` não vê arquivo não rastreado, mas o comparar lista esses como
        # novos (A): o diff deles é o arquivo inteiro.
        if not out and (await git(path, "ls-files", "--others", "--exclude-standard", "--", file)).strip():
            return await git(path, "diff", "--no-color", "--no-index", "--", "/dev/null", file, ok_codes=(0, 1))
        return out
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


async def commit(path: str | Path, message: str, amend: bool = False) -> str:
    """Commit (ou amend). Se um hook recusar, o erro traz a saída inteira dele."""
    message = message.strip()
    if amend:
        args = ["commit", "--amend", *(["-m", message] if message else ["--no-edit"])]
    else:
        if not message:
            raise GitError("escreva a mensagem do commit", 400)
        args = ["commit", "-m", message]
    await git(path, *args, full_output=True, timeout=300)
    return (await git(path, "rev-parse", "--short", "HEAD")).strip()


async def _upstream(path: str | Path) -> str | None:
    try:
        return (await git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")).strip() or None
    except GitError:
        return None


async def push(path: str | Path, force: bool = False) -> str:
    """Sobe o branch; sem upstream, publica (`-u origin HEAD`). `force` é sempre o com garantia.

    O `--force-with-lease` sozinho compara o remoto com o origin/<branch> local, que o fetch
    automático do painel atualiza sem o Pedro ver: a garantia sumiria. O `--force-if-includes`
    só deixa forçar se o que está no origin/<branch> já passou por este branch (pelo reflog),
    então um commit de outra pessoa trazido só pelo fetch faz a subida ser recusada."""
    lease = ["--force-with-lease", "--force-if-includes"] if force else []
    if await _upstream(path) is None:
        return await git(path, "push", *lease, "-u", "origin", "HEAD", timeout=120, full_output=True)
    return await git(path, "push", *lease, timeout=120, full_output=True)


async def pull(path: str | Path) -> str:
    return await git(path, "pull", "--ff-only", timeout=120)


async def fetch(path: str | Path) -> str:
    return await git(path, "fetch", "--prune", "--quiet", timeout=60)


async def _head(path: str | Path) -> str | None:
    try:
        return (await git(path, "rev-parse", "HEAD")).strip()
    except GitError:
        return None


async def sync(path: str | Path) -> dict:
    """O botão que muda com o estado: sem upstream, publica; com upstream, puxa com rebase
    (guardando o que não foi commitado) e sobe o que sobrar à frente."""
    if await _upstream(path) is None:
        return {"feito": "push", "saida": await push(path)}
    before = await _head(path)
    out = await git(path, "pull", "--rebase", "--autostash", timeout=180, full_output=True)
    pulled = await _head(path) != before
    info = parse_status(await git(path, "status", "--porcelain=v2", "--branch", "-z"))
    if info["ahead"] > 0:
        out += await git(path, "push", timeout=120, full_output=True)
        return {"feito": "sync" if pulled else "push", "saida": out}
    return {"feito": "pull" if pulled else "nada", "saida": out}


# --- trechos, descarte e operações ----------------------------------------------


async def apply_patch(path: str | Path, patch: str, cached: bool = True, reverse: bool = False) -> None:
    """Marca, desmarca ou descarta um trecho: o patch montado pela tela, com as contagens refeitas."""
    if not patch.endswith("\n"):
        patch += "\n"
    args = ["apply", *(["--cached"] if cached else []), *(["--reverse"] if reverse else []), "--recount", "--whitespace=nowarn", "-"]
    await git(path, *args, input=patch.encode("utf-8"), full_output=True)


TRASH = Path.home() / ".Trash"


def _trash_target(trash: Path, name: str) -> Path:
    target = trash / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while target.exists():
        target = trash / f"{stem} {n}{suffix}"
        n += 1
    return target


async def discard(path: str | Path, files: list[str], trash: Path | None = None) -> list[str]:
    """Descarta o que não foi marcado: rastreados voltam ao que está marcado (ou ao HEAD);
    os não rastreados vão para a Lixeira, nunca são apagados de vez. Devolve onde foram parar."""
    from . import files as fs

    if not files:
        return []
    info = parse_status(await git(path, "status", "--porcelain=v2", "-z", "--untracked-files=all"))
    untracked = {f["path"] for f in info["files"] if f["untracked"]}
    tracked = [f for f in files if f not in untracked]
    loose = [f for f in files if f in untracked]
    for rel in files:
        fs.inside(str(path), rel)
    if tracked:
        await git(path, "restore", "--worktree", "--", *tracked)
    moved: list[str] = []
    bin_dir = trash or TRASH
    bin_dir.mkdir(parents=True, exist_ok=True)
    for rel in loose:
        source = fs.inside(str(path), rel)
        if not source.exists():
            continue
        target = _trash_target(bin_dir, source.name)
        shutil.move(str(source), str(target))
        moved.append(str(target))
    return moved


async def finish_operation(path: str | Path, action: str) -> str:
    """Abortar ou continuar o merge, rebase, cherry-pick ou revert em andamento."""
    op = await operation(path)
    if op is None:
        raise GitError("nenhum merge, rebase, cherry-pick ou revert em andamento", 409)
    if action == "abortar":
        return await git(path, op, "--abort", full_output=True)
    if op == "merge":
        return await git(path, "commit", "--no-edit", full_output=True)
    return await git(path, "-c", "core.editor=true", op, "--continue", full_output=True)


# --- conflitos ---------------------------------------------------------------------


def parse_conflicts(text: str) -> list[dict]:
    """Blocos de conflito pelos marcadores do git, só no começo da linha (com a seção base do diff3, se houver)."""
    lines = text.splitlines(keepends=True)
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("<<<<<<<"):
            i += 1
            continue
        start = i
        label_ours = lines[i][7:].strip()
        parts: dict[str, list[str]] = {"nosso": [], "base": [], "deles": []}
        has_base = False
        section = "nosso"
        j = i + 1
        closed = False
        label_theirs = ""
        while j < len(lines):
            line = lines[j]
            bare = line.rstrip("\r\n")
            if line.startswith("|||||||") and section == "nosso":
                section, has_base = "base", True
            elif bare == "=======" and section in ("nosso", "base"):
                section = "deles"
            elif line.startswith(">>>>>>>") and section == "deles":
                label_theirs = line[7:].strip()
                closed = True
                break
            else:
                parts[section].append(line)
            j += 1
        if not closed:
            break
        blocks.append(
            {
                "indice": len(blocks),
                "nosso": "".join(parts["nosso"]),
                "deles": "".join(parts["deles"]),
                "base": "".join(parts["base"]) if has_base else None,
                "rotulo_nosso": label_ours,
                "rotulo_deles": label_theirs,
                "inicio": start,
                "fim": j,
            }
        )
        i = j + 1
    return blocks


def _swapped(block: dict) -> dict:
    """No rebase o git chama de "ours" o branch de cima (onde os commits são reaplicados) e de
    "theirs" o commit deste branch. A tela fala sempre do ponto de vista deste branch: nosso é
    o que o Pedro fez aqui, deles é o que está entrando."""
    return {
        **block,
        "nosso": block["deles"],
        "deles": block["nosso"],
        "rotulo_nosso": block["rotulo_deles"],
        "rotulo_deles": block["rotulo_nosso"],
    }


def resolve_conflicts(text: str, choices: list[str], rebase: bool = False) -> str:
    """O texto com cada bloco trocado pela escolha: nosso, deles, ambos (o nosso e depois o deles) ou base."""
    blocks = parse_conflicts(text)
    if rebase:
        blocks = [_swapped(b) for b in blocks]
    if len(choices) != len(blocks):
        raise GitError(f"são {len(blocks)} conflito(s) e vieram {len(choices)} escolha(s)", 400)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    cursor = 0
    for block, choice in zip(blocks, choices):
        out.extend(lines[cursor : block["inicio"]])
        if choice == "nosso":
            out.append(block["nosso"])
        elif choice == "deles":
            out.append(block["deles"])
        elif choice == "ambos":
            out.append(block["nosso"] + block["deles"])
        elif choice == "base":
            if block["base"] is None:
                raise GitError("esse conflito não tem a versão base (falta o merge.conflictStyle diff3)", 400)
            out.append(block["base"])
        else:
            raise GitError(f"escolha inválida: {choice}", 400)
        cursor = block["fim"] + 1
    out.extend(lines[cursor:])
    return "".join(out)


async def conflict(path: str | Path, file: str) -> dict:
    from . import files as fs

    target = fs.inside(str(path), file)
    text = target.read_text(encoding="utf-8", errors="replace")
    blocks = parse_conflicts(text)
    if await operation(path) == "rebase":
        blocks = [_swapped(b) for b in blocks]
    blocks = [{k: v for k, v in b.items() if k not in ("inicio", "fim")} for b in blocks]
    return {"blocos": blocks, "texto": text}


async def resolve(path: str | Path, file: str, choices: list[str] | None = None, side: str | None = None) -> bool:
    """Resolve um arquivo em conflito: por bloco (escolhas) ou inteiro de um lado (lado). Marca se acabou."""
    from . import files as fs

    target = fs.inside(str(path), file)
    rebase = await operation(path) == "rebase"
    if side is not None:
        if side not in ("nosso", "deles"):
            raise GitError(f"lado inválido: {side}", 400)
        # No rebase o --ours é o branch de cima e o --theirs é o commit deste branch (veja _swapped).
        ours = (side == "nosso") != rebase
        await git(path, "checkout", "--ours" if ours else "--theirs", "--", file)
        await git(path, "add", "--", file)
        return True
    # Em bytes e sem traduzir o fim de linha: fora dos blocos o arquivo volta exatamente como
    # estava (CRLF continua CRLF, e o que não é UTF-8 não vira "�").
    text = target.read_bytes().decode("utf-8", "surrogateescape")
    fixed = resolve_conflicts(text, choices or [], rebase=rebase)
    target.write_bytes(fixed.encode("utf-8", "surrogateescape"))
    if parse_conflicts(fixed):
        return False
    await git(path, "add", "--", file)
    return True


async def blob(path: str | Path, file: str, ref: str = "HEAD") -> bytes:
    """O arquivo como está numa ref (o lado antigo do diff de imagem)."""
    from . import files as fs

    base = Path(path).expanduser().resolve()
    target = fs.inside(str(path), file)
    sha = await resolve_ref(path, ref)
    rel = target.relative_to(base).as_posix()
    try:
        return await git_bytes(path, "show", f"{sha}:./{rel}")
    except GitError as exc:
        raise FileNotFoundError(f"{file} não existe em {ref}") from exc


# --- configuração global ------------------------------------------------------------


async def _global(key: str) -> str | None:
    out = await git(Path.home(), "config", "--global", "--get", key, ok_codes=(0, 1))
    return out.strip() or None


async def global_config() -> dict:
    sign, fmt, key, name, email = await asyncio.gather(
        _global("commit.gpgsign"), _global("gpg.format"), _global("user.signingkey"), _global("user.name"), _global("user.email")
    )
    return {
        "assinar": (sign or "").lower() == "true",
        "formato": fmt or "openpgp",
        "tem_chave": bool(key),
        "nome": name,
        "email": email,
    }


async def set_signing(on: bool) -> dict:
    await git(Path.home(), "config", "--global", "commit.gpgsign", "true" if on else "false")
    return await global_config()


async def list_files(path: str | Path, limit: int = 20000) -> list[str]:
    """Arquivos do projeto sem os ignorados pelo git (node_modules, build...)."""
    raw = await git(path, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    files = sorted({f for f in raw.split("\0") if f})
    return files[:limit]
