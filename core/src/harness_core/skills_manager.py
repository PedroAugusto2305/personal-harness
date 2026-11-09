"""Instalar, atualizar, exportar, copiar e tirar Skills (v0.9.8, parte 5).

Destinos: "claude" e "codex" (a pasta `skills` da conta ativa de cada CLI) e "projeto"
(`<repositório>/.claude/skills`). A origem pode ser um repositório git (clone raso), uma pasta
ou um .zip. Só arquivos são copiados (atalhos simbólicos ficam de fora) e nada é executado.
Cada skill instalada guarda de onde veio em `.metis-origem.json`, para atualizar depois.
Tirar uma skill a manda para a Lixeira; nunca apaga de vez.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from .system import frontmatter

ORIGIN_FILE = ".metis-origem.json"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SKIP = {".git", "__pycache__", "node_modules", ".DS_Store"}
MAX_DEPTH = 3
GIT_PREFIXES = ("https://", "file://", "git@")


class SkillError(ValueError):
    pass


class SkillConflict(SkillError):
    """Já existe uma skill com esse nome no destino (409)."""


class SkillMissing(SkillError):
    """A skill não existe no destino (404)."""


Git = Callable[..., subprocess.CompletedProcess]


def run_git(*args: str, cwd: str | None = None, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


# --- achar skills ------------------------------------------------------------------------


def find_skills(root: Path, depth: int = MAX_DEPTH) -> list[Path]:
    """As pastas com SKILL.md, na raiz ou em subpastas até `depth` níveis."""
    found: list[Path] = []

    def walk(folder: Path, level: int) -> None:
        if (folder / "SKILL.md").is_file():
            found.append(folder)
            return
        if level >= depth:
            return
        try:
            children = sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and p.name not in SKIP)
        except OSError:
            return
        for child in children:
            walk(child, level + 1)

    walk(root, 0)
    return found


def skill_name(folder: Path, fallback: str = "", use_folder: bool = True) -> str:
    """O `name` do frontmatter do SKILL.md, se for um nome de pasta válido; senão o nome da
    pasta (ou o da origem, quando a skill é a raiz de um clone ou de um zip)."""
    try:
        meta = frontmatter((folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")[:6000])
    except OSError:
        meta = {}
    for candidate in (meta.get("name", ""), folder.name if use_folder else "", fallback):
        candidate = (candidate or "").strip()
        if NAME_RE.fullmatch(candidate):
            return candidate
    return ""


def read_origin(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / ORIGIN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# --- copiar com segurança ----------------------------------------------------------------


def _ignore(folder: str, names: list[str]) -> set[str]:
    """Fora: .git, caches e qualquer atalho simbólico (podia apontar para fora da skill)."""
    base = Path(folder)
    return {n for n in names if n in SKIP or (base / n).is_symlink()}


def _copy(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=_ignore, symlinks=False)


def _place(source: Path, target: Path, replace: bool, origin: dict) -> None:
    """Copia a skill para o destino; ao substituir, a antiga só sai depois de a nova entrar."""
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists():
        if not replace:
            raise SkillConflict(f"já existe {target.name} em {target.parent}")
        backup = target.with_name(f".{target.name}.antiga")
        if backup.exists():
            shutil.rmtree(backup)
        target.rename(backup)
    try:
        _copy(source, target)
        (target / ORIGIN_FILE).write_text(json.dumps(origin, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup is not None:
            backup.rename(target)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def safe_extract(archive: Path, folder: Path) -> None:
    """Abre o .zip conferindo que nenhum caminho sai da pasta (zip slip) nem é atalho."""
    root = folder.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            target = (folder / name).resolve()
            if name.startswith("/") or ".." in Path(name).parts or (target != root and root not in target.parents):
                raise SkillError(f"o zip tenta escrever fora da pasta: {name}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise SkillError(f"o zip traz um atalho simbólico: {name}")
        zf.extractall(folder)


def _is_git(origem: str) -> bool:
    return origem.startswith(GIT_PREFIXES)


def _clone(url: str, into: Path, git: Git) -> str:
    done = git("clone", "--depth", "1", url, str(into))
    if done.returncode != 0:
        raise SkillError(f"não consegui clonar {url}: {(done.stderr or done.stdout).strip()[:300]}")
    head = git("rev-parse", "HEAD", cwd=str(into))
    return head.stdout.strip() if head.returncode == 0 else ""


# --- as ações ----------------------------------------------------------------------------


def install(origem: str, target_dir: Path, replace: bool = False, git: Git = run_git) -> dict:
    """Instala as skills achadas na origem em `target_dir` (a pasta skills do destino)."""
    origem = (origem or "").strip()
    if not origem:
        raise SkillError("diga de onde instalar: um repositório git (https), uma pasta ou um .zip")
    with tempfile.TemporaryDirectory(prefix="metis-skill-") as tmp:
        work = Path(tmp) / "fonte"
        info: dict = {"instalada": datetime.now().astimezone().isoformat(timespec="seconds")}
        if _is_git(origem):
            commit = _clone(origem, work, git)
            info.update({"tipo": "git", "origem": origem, "commit": commit})
            fallback = origem.rstrip("/").split("/")[-1].removesuffix(".git")
        else:
            path = Path(origem).expanduser()
            if path.is_file() and path.suffix.lower() == ".zip":
                work.mkdir()
                try:
                    safe_extract(path, work)
                except zipfile.BadZipFile as exc:
                    raise SkillError(f"o arquivo não é um zip válido: {path.name}") from exc
                info.update({"tipo": "zip", "origem": str(path)})
                fallback = path.stem.removesuffix("-skill")
            elif path.is_dir():
                work = path
                info.update({"tipo": "pasta", "origem": str(path)})
                fallback = path.name
            else:
                raise SkillError(f"não achei {origem}: use um repositório git (https), uma pasta ou um .zip")
        folders = find_skills(work)
        if not folders:
            raise SkillError("nenhuma pasta com SKILL.md na origem (procurei até 3 níveis)")
        plan: list[tuple[str, Path]] = []
        skipped: list[dict] = []
        for folder in folders:
            root_of_temp = folder == work and info["tipo"] != "pasta"
            name = skill_name(folder, fallback if folder == work else "", use_folder=not root_of_temp)
            if not name:
                skipped.append({"nome": folder.name, "motivo": "nome inválido para pasta de skill"})
                continue
            if any(n == name for n, _ in plan):
                skipped.append({"nome": name, "motivo": "repetida na origem"})
                continue
            plan.append((name, folder))
        conflicts = [n for n, _ in plan if (target_dir / n).exists()]
        if conflicts and not replace:
            raise SkillConflict(f"já existe no destino: {', '.join(conflicts)} (marque substituir para trocar)")
        installed = []
        for name, folder in plan:
            origin = {**info, "subpasta": str(folder.relative_to(work)) if folder != work else "."}
            _place(folder, target_dir / name, replace, origin)
            installed.append(name)
        return {"instaladas": installed, "ignoradas": skipped}


def update(name: str, target_dir: Path, git: Git = run_git) -> dict:
    """Busca de novo no git de onde a skill veio e substitui."""
    folder = target_dir / name
    if not folder.is_dir():
        raise SkillMissing(f"a skill {name} não está em {target_dir}")
    origin = read_origin(folder)
    if not origin or origin.get("tipo") != "git":
        raise SkillError(f"{name} não veio de um repositório git: instale de novo para atualizar")
    with tempfile.TemporaryDirectory(prefix="metis-skill-") as tmp:
        work = Path(tmp) / "fonte"
        commit = _clone(str(origin["origem"]), work, git)
        source = work / str(origin.get("subpasta") or ".")
        if not (source / "SKILL.md").is_file():
            found = [f for f in find_skills(work) if skill_name(f) == name]
            if not found:
                raise SkillError(f"o repositório não tem mais a skill {name}")
            source = found[0]
        new_origin = {**origin, "commit": commit, "instalada": datetime.now().astimezone().isoformat(timespec="seconds")}
        _place(source, folder, True, new_origin)
    return {"nome": name, "commit": commit, "antes": origin.get("commit") or ""}


def export(name: str, target_dir: Path, downloads: Path | None = None) -> Path:
    """Grava `<nome>-skill.zip` em ~/Downloads (sem sobrescrever) com a pasta da skill."""
    folder = target_dir / name
    if not folder.is_dir():
        raise SkillMissing(f"a skill {name} não está em {target_dir}")
    out_dir = downloads or Path.home() / "Downloads"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}-skill.zip"
    n = 2
    while target.exists():
        target = out_dir / f"{name}-skill ({n}).zip"
        n += 1
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(folder.rglob("*")):
            rel = item.relative_to(folder)
            if item.is_symlink() or any(part in SKIP for part in rel.parts) or item.name == ORIGIN_FILE:
                continue
            if item.is_file():
                zf.write(item, Path(name) / rel)
    return target


def copy(name: str, source_dir: Path, target_dir: Path) -> Path:
    folder = source_dir / name
    if not folder.is_dir():
        raise SkillMissing(f"a skill {name} não está em {source_dir}")
    target = target_dir / name
    if target.exists():
        raise SkillConflict(f"já existe {name} em {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    _copy(folder, target)
    return target


TRASH = Path.home() / ".Trash"


def trash(name: str, target_dir: Path, bin_dir: Path | None = None) -> Path:
    """Manda a pasta da skill para a Lixeira (com número se já houver uma de mesmo nome)."""
    folder = target_dir / name
    if not folder.is_dir():
        raise SkillMissing(f"a skill {name} não está em {target_dir}")
    trash_dir = bin_dir or TRASH
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / name
    n = 2
    while target.exists():
        target = trash_dir / f"{name} {n}"
        n += 1
    shutil.move(str(folder), str(target))
    return target


def annotate(items: list[dict], dirs: dict[str, Path]) -> list[dict]:
    """A listagem de /skills ganha `destino` (claude, codex ou projeto) e `fonte` (de onde veio)."""
    resolved = {key: path.expanduser().resolve() for key, path in dirs.items()}
    for item in items:
        folder = Path(item.get("pasta") or "")
        parent = folder.parent.resolve() if item.get("pasta") else None
        item["destino"] = next((key for key, path in resolved.items() if parent == path), None)
        origin = read_origin(folder) if item.get("pasta") else None
        item["fonte"] = {k: origin.get(k) for k in ("tipo", "origem", "commit", "instalada")} if origin else None
    return items
