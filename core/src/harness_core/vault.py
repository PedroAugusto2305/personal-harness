"""O vault Brain (Obsidian) visto pelo núcleo: notas, frontmatter, links e projetos.

Regras do vault que valem aqui (`~/Documents/Brain/CLAUDE.md`): nunca apagar nota, toda
nota tem frontmatter, o título é o nome do arquivo. A MÊTIS só muda o que precisa (uma
chave do frontmatter, uma linha de tarefa) e grava de forma atômica, para o Obsidian e o
`brain.py` continuarem donos do resto.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

PROJECTS_DIR = "01-PROJETOS"
# Pastas que não são conteúdo: configuração, modelos, anexos e o lixo do Obsidian.
SKIP_DIRS = {".obsidian", ".trash", ".git", ".maestri", ".claude", "_templates", "_anexos", "node_modules"}

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
_WIKILINK = re.compile(r"\[\[([^\]\|#\^]+)(?:[#\^][^\]\|]*)?(?:\|([^\]]*))?\]\]")


class VaultError(ValueError):
    pass


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """(chaves do frontmatter com o valor cru, corpo). Só o subconjunto de YAML que o vault usa."""
    match = _FM.match(text)
    if not match:
        return {}, text
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key and not key.startswith((" ", "\t", "-", "#")):
            data[key.strip()] = unquote(value.strip())
    return data, text[match.end() :]


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def set_frontmatter(text: str, key: str, value: str) -> str:
    """Troca (ou acrescenta) uma chave do frontmatter, sem mexer nas outras linhas."""
    rendered = f"{key}: {value}"
    match = _FM.match(text)
    if not match:
        return f"---\n{rendered}\n---\n\n{text}"
    lines = match.group(1).splitlines()
    for i, line in enumerate(lines):
        if line.split(":", 1)[0].strip() == key and not line.startswith((" ", "\t")):
            lines[i] = rendered
            break
    else:
        lines.append(rendered)
    newline = "\r\n" if "\r\n" in match.group(0) else "\n"
    head = f"---{newline}{newline.join(lines)}{newline}---{newline}"
    return head + text[match.end() :]


def wikilinks(text: str) -> list[str]:
    """Títulos ligados por [[…]], sem o #seção nem o |apelido."""
    return [m.group(1).strip() for m in _WIKILINK.finditer(text)]


def link_target(value: str) -> str:
    """'[[Personal Harness]]' → 'Personal Harness'."""
    found = wikilinks(value)
    return found[0] if found else value.strip()


def abstract(body: str, limit: int = 420) -> str:
    """Texto do primeiro callout > [!abstract] (o resumo das notas de registro)."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"\s*>\s*\[!abstract\]", line, re.I):
            out = []
            for follow in lines[i + 1 :]:
                if not follow.lstrip().startswith(">"):
                    break
                out.append(follow.lstrip()[1:].strip())
            text = " ".join(part for part in out if part)
            return text[:limit].rstrip() + ("…" if len(text) > limit else "")
    return ""


def write_atomic(path: Path, text: str) -> None:
    """Grava num arquivo temporário da mesma pasta e troca de uma vez: nunca meia nota."""
    fd, tmp = tempfile.mkstemp(prefix=".metis-", suffix=".md", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        _unlink_quiet(tmp)
        raise


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def iter_notes(root: Path):
    """Todas as notas .md do vault, pulando as pastas de sistema."""
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(".md") and not name.startswith("."):
                yield Path(folder) / name


def add_to_section(text: str, heading: str, line: str, before: tuple[str, ...] = ()) -> str:
    """Acrescenta `line` no fim da seção `## …heading` (troca o "- " vazio do modelo, se houver).
    Sem a seção, ela nasce antes do primeiro título de `before` que existir, ou no fim."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") and heading in l), None)
    if start is None:
        at = next((i for i, l in enumerate(lines) if any(l.startswith(b) for b in before)), None)
        block = [f"## {heading}", "", line, ""]
        if at is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", *block]
        else:
            lines[at:at] = block
        return "\n".join(lines)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    placeholder = next((i for i in range(start + 1, end) if lines[i].strip() in ("-", "- [ ]")), None)
    if placeholder is not None:
        lines[placeholder] = line
        return "\n".join(lines)
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    lines.insert(at, line)
    return "\n".join(lines)


@dataclass(frozen=True)
class ProjectNote:
    name: str
    path: Path
    meta: dict[str, str]
    body: str


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser()

    @property
    def available(self) -> bool:
        return (self.root / PROJECTS_DIR).is_dir()

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def tree(self, limit: int = 5000) -> list[dict]:
        """v0.9.9: as pastas e as notas do vault, como a barra de arquivos do Obsidian.

        Pastas primeiro, em ordem de nome; as de sistema (SKIP_DIRS) e as ocultas ficam de fora.
        """
        count = 0

        def walk(folder: Path) -> list[dict]:
            nonlocal count
            try:
                entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError:
                return []
            out: list[dict] = []
            for entry in entries:
                if count >= limit or entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    if entry.name in SKIP_DIRS:
                        continue
                    children = walk(entry)
                    if children:
                        out.append({"nome": entry.name, "caminho": self.rel(entry), "tipo": "pasta", "filhos": children})
                elif entry.suffix == ".md":
                    count += 1
                    out.append({"nome": entry.stem, "caminho": self.rel(entry), "tipo": "nota"})
            return out

        return walk(self.root) if self.root.is_dir() else []

    def resolve(self, rel_path: str) -> Path:
        """Caminho relativo ao vault → arquivo, sem deixar sair do vault."""
        target = (self.root / rel_path).resolve()
        if not str(target).startswith(str(self.root.resolve()) + os.sep) or target.suffix != ".md":
            raise VaultError(f"nota fora do vault: {rel_path}")
        if not target.is_file():
            raise VaultError(f"nota não encontrada: {rel_path}")
        return target

    # --- nota do dia (06-DIARIO) ----------------------------------------------

    def daily(self, day: str) -> Path:
        """A nota do dia, criada pelo modelo do vault se ainda não existir (como faz o brain.py)."""
        path = self.root / "06-DIARIO" / f"{day}.md"
        if not path.exists():
            template = self.root / "_templates" / "T-daily.md"
            text = (
                template.read_text(encoding="utf-8")
                if template.is_file()
                else f"---\ntipo: daily\ndata: {day}\ntags: [diario]\n---\n\n# 📅 {day}\n"
            )
            text = re.sub(r"\{\{date(:[^}]*)?\}\}", day, text).replace("{{title}}", day)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(path, text)
        return path

    def append_daily(self, day: str, heading: str, line: str, before: tuple[str, ...] = ()) -> Path:
        path = self.daily(day)
        text = path.read_text(encoding="utf-8")
        new = add_to_section(text, heading, line, before)
        write_atomic(path, new if new.endswith("\n") else new + "\n")
        return path

    # --- projetos -------------------------------------------------------------

    def projects(self) -> list[ProjectNote]:
        """Uma nota por pasta em 01-PROJETOS (`<Projeto>/<Projeto>.md`, tipo: projeto)."""
        base = self.root / PROJECTS_DIR
        out = []
        if not base.is_dir():
            return out
        for folder in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            note = folder / f"{folder.name}.md"
            if not folder.is_dir() or not note.is_file():
                continue
            meta, body = split_frontmatter(note.read_text(encoding="utf-8"))
            if meta.get("tipo", "projeto") != "projeto":
                continue
            out.append(ProjectNote(folder.name, note, meta, body))
        return out

    def project(self, name: str) -> ProjectNote:
        for item in self.projects():
            if item.name == name:
                return item
        raise VaultError(f"projeto não encontrado no Brain: {name}")

    def project_for_dir(self, cwd: str | Path) -> ProjectNote | None:
        """O projeto cujo `diretorio:` contém a pasta (ou o repositório principal dela, numa worktree)."""
        candidates = [Path(cwd).expanduser().resolve()]
        try:
            from .projects import repo_root

            candidates.append(repo_root(cwd).resolve())
        except Exception:  # pasta solta, sem git: vale só o caminho
            pass
        best: tuple[int, ProjectNote] | None = None
        for item in self.projects():
            raw = item.meta.get("diretorio", "").strip()
            if not raw:
                continue
            folder = Path(raw).expanduser().resolve()
            for candidate in candidates:
                if candidate == folder or folder in candidate.parents:
                    depth = len(folder.parts)
                    if best is None or depth > best[0]:
                        best = (depth, item)
        return best[1] if best else None
