"""Projetos: repositórios git cadastrados no Harness. A lista começa vazia."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .accounts import slugify


class ProjectError(ValueError):
    pass


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: str


def repo_root(path: str | Path) -> Path:
    folder = Path(path).expanduser()
    if not folder.is_dir():
        raise ProjectError(f"pasta não encontrada: {folder}")
    out = subprocess.run(
        ["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10
    )
    if out.returncode != 0:
        raise ProjectError(f"não é um repositório git: {folder}")
    # Dentro de uma worktree, o projeto é o repositório principal.
    common = subprocess.run(
        ["git", "-C", str(folder), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if common.returncode == 0 and common.stdout.strip().endswith("/.git"):
        return Path(common.stdout.strip()).parent
    return Path(out.stdout.strip())


class ProjectStore:
    def __init__(self, home: Path) -> None:
        self.path = home / "projects.json"

    def _load(self, to_save: bool = False) -> list[dict]:
        """A lista gravada; sem o arquivo, vazia. Uma leitura que falha (o núcleo sem arquivos
        livres, na 1.3.2) também mostra vazia, mas quem vai gravar pede `to_save` e recebe o
        erro: gravar por cima de uma leitura que falhou trocaria os projetos pelo novo."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except OSError as exc:
            if to_save:
                raise ProjectError(f"não consegui ler a lista de projetos ({exc.strerror or exc}); nada foi gravado") from exc
            return []
        except json.JSONDecodeError:
            return []
        return [p for p in data if isinstance(p, dict) and {"id", "name", "path"} <= p.keys()]

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list(self) -> list[dict]:
        return self._load()

    def scripts(self, project_id: str) -> dict:
        """Scripts do projeto (v0.9.2): `setup` roda na worktree nova, `arquivar` antes de apagar."""
        for item in self._load():
            if item["id"] == project_id:
                return {"setup": item.get("setup", ""), "arquivar": item.get("arquivar", "")}
        raise ProjectError(f"projeto desconhecido: {project_id}")

    def set_scripts(self, project_id: str, setup: str | None = None, arquivar: str | None = None) -> dict:
        items = self._load(to_save=True)
        for item in items:
            if item["id"] == project_id:
                if setup is not None:
                    item["setup"] = setup.strip()
                if arquivar is not None:
                    item["arquivar"] = arquivar.strip()
                self._save(items)
                return {"setup": item.get("setup", ""), "arquivar": item.get("arquivar", "")}
        raise ProjectError(f"projeto desconhecido: {project_id}")

    def get(self, project_id: str) -> Project:
        for item in self._load():
            if item["id"] == project_id:
                return Project(item["id"], item["name"], item["path"])
        raise ProjectError(f"projeto desconhecido: {project_id}")

    def add(self, path: str, name: str | None = None) -> Project:
        root = repo_root(path)
        items = self._load(to_save=True)
        for item in items:
            if Path(item["path"]) == root:
                return Project(item["id"], item["name"], item["path"])
        label = (name or root.name).strip() or root.name
        taken = {i["id"] for i in items}
        base = slugify(label)
        project_id, n = base, 2
        while project_id in taken:
            project_id, n = f"{base}-{n}", n + 1
        project = Project(project_id, label, str(root))
        items.append(asdict(project))
        self._save(items)
        return project

    def remove(self, project_id: str) -> None:
        """Só tira da lista. O repositório e as worktrees continuam no disco."""
        items = self._load(to_save=True)
        kept = [i for i in items if i["id"] != project_id]
        if len(kept) == len(items):
            raise ProjectError(f"projeto desconhecido: {project_id}")
        self._save(kept)


# --- adicionar projeto, no jeito do Orca (v0.9.9) --------------------------------------------
# O diálogo "Adicionar projeto" tem três caminhos: abrir uma pasta (com os repositórios que já
# estão no Mac sugeridos), clonar de uma URL e criar um projeto novo.

SKIP_SCAN = {"node_modules", "Library", "Applications", ".Trash", "Pictures", "Movies", "Music", "Downloads"}
SCAN_ROOTS = ("orca/projects", "Documents/projetos", "Documents", "Developer", "Projects", "projects", "code", "src", "dev", "repos")


def default_parent(projects: list[dict], home: Path | None = None) -> Path:
    """Onde clonar ou criar: a pasta onde a maioria dos projetos já mora, senão ~/Documents/projetos."""
    home = home or Path.home()
    parents: dict[Path, int] = {}
    for item in projects:
        parent = Path(item["path"]).parent
        parents[parent] = parents.get(parent, 0) + 1
    if parents:
        return max(parents, key=lambda p: (parents[p], len(str(p))))
    return home / "Documents" / "projetos"


def find_repos(known: list[dict], worktrees: Path, home: Path | None = None, depth: int = 2, limit: int = 40) -> list[dict]:
    """Repositórios git no Mac que ainda não são projetos: nas pastas de costume e ao lado dos
    projetos que já existem, até `depth` níveis. Worktree (`.git` arquivo) não conta: ela é de um
    repositório principal. Os mais mexidos primeiro."""
    home = home or Path.home()
    added = {Path(item["path"]).resolve() for item in known}
    roots = [home / r for r in SCAN_ROOTS] + [Path(item["path"]).parent for item in known]
    seen: set[Path] = set()
    found: dict[Path, float] = {}
    skip_root = worktrees.resolve() if worktrees.exists() else worktrees

    def walk(folder: Path, level: int) -> None:
        try:
            resolved = folder.resolve()
        except OSError:
            return
        if resolved in seen or resolved == skip_root:
            return
        seen.add(resolved)
        git = folder / ".git"
        if git.is_dir():
            if resolved not in added:
                try:
                    found[resolved] = max(git.stat().st_mtime, (git / "index").stat().st_mtime if (git / "index").exists() else 0)
                except OSError:
                    pass
            return  # dentro de um repositório não se procura outro
        if level >= depth:
            return
        try:
            children = sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP_SCAN)
        except OSError:
            return
        for child in children[:400]:
            walk(child, level + 1)

    for root in roots:
        if root.is_dir():
            walk(root, 0)
    ordered = sorted(found.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"path": str(path), "name": path.name, "atualizado": mtime} for path, mtime in ordered]


def _git(args: list[str], cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout)


def repo_name_from_url(url: str) -> str:
    """https://github.com/dono/repo.git, git@github.com:dono/repo.git → repo."""
    tail = url.strip().rstrip("/").replace(":", "/").split("/")[-1]
    return tail[:-4] if tail.endswith(".git") else tail


def clone_repo(url: str, parent: Path, timeout: int = 600) -> Path:
    url = url.strip()
    if not url or url.startswith("-") or any(c.isspace() for c in url):
        raise ProjectError("endereço do repositório inválido")
    name = repo_name_from_url(url)
    if not name or name in (".", ".."):
        raise ProjectError("não deu para tirar o nome do repositório do endereço")
    parent = parent.expanduser()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / name
    if target.exists():
        raise ProjectError(f"já existe uma pasta {target}: abra ela pela opção Abrir pasta")
    try:
        out = _git(["clone", "--", url, str(target)], timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ProjectError("o clone passou de 10 minutos") from exc
    if out.returncode != 0:
        lines = (out.stderr or out.stdout).strip().splitlines()
        raise ProjectError(f"o git não clonou: {lines[-1] if lines else 'erro sem mensagem'}")
    return target


def create_repo(name: str, parent: Path) -> Path:
    """Pasta nova com git, um README e o primeiro commit (a worktree precisa de um commit)."""
    label = name.strip()
    if not label:
        raise ProjectError("dê um nome ao projeto")
    folder = slugify(label)
    if not folder:
        raise ProjectError("nome do projeto inválido")
    parent = parent.expanduser()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / folder
    if target.exists():
        raise ProjectError(f"já existe uma pasta {target}")
    target.mkdir()
    try:
        (target / "README.md").write_text(f"# {label}\n", encoding="utf-8")
        # Sem nome ou e-mail no git da máquina, o primeiro commit sai assinado pela MÊTIS.
        who = []
        if not _git(["config", "user.name"], cwd=parent).stdout.strip():
            who += ["-c", "user.name=MÊTIS"]
        if not _git(["config", "user.email"], cwd=parent).stdout.strip():
            who += ["-c", "user.email=metis@localhost"]
        for args in (["init", "-b", "main"], ["add", "README.md"], [*who, "commit", "-m", "Início do projeto"]):
            try:
                out = _git(args, cwd=target)
            except subprocess.TimeoutExpired as exc:
                step = next(a for a in args if not a.startswith("-") and "=" not in a)
                raise ProjectError(f"o git demorou demais em `git {step}` (assinatura de commit esperando senha?)") from exc
            if out.returncode != 0:
                lines = (out.stderr or out.stdout).strip().splitlines()
                raise ProjectError(f"o git não criou o projeto: {lines[-1] if lines else ' '.join(args)}")
    except BaseException:
        # Nada pela metade: a pasta nova sai, e tentar de novo não esbarra em "já existe".
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target
