"""Projetos: repositórios git cadastrados no Harness. A lista começa vazia."""

from __future__ import annotations

import json
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

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
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
        items = self._load()
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
        items = self._load()
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
        items = self._load()
        kept = [i for i in items if i["id"] != project_id]
        if len(kept) == len(items):
            raise ProjectError(f"projeto desconhecido: {project_id}")
        self._save(kept)
