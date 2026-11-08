"""Kanban de projetos e tarefas, lido e escrito direto nas notas do Brain.

- Estágio do projeto: chave `estagio:` no frontmatter da nota do projeto.
- Tarefas: as linhas `- [ ]` da seção "Próximas ações". O estado intermediário fica numa
  etiqueta no fim da linha (`#em-andamento`, `#em-teste`), assim a tarefa continua aberta
  para o Obsidian e para o `brain.py`; concluir marca `[x]` com a data (`✅ AAAA-MM-DD`,
  o formato do plugin Tasks que o vault já usa). Decisão de 2026-11-08 no Brain.

Toda escrita relê a nota, acha a linha pelo id (hash do texto sem etiquetas) e troca só
ela, para não atropelar o que o Obsidian ou outro agente gravou no meio tempo.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .vault import Vault, VaultError, link_target, set_frontmatter, split_frontmatter, write_atomic

STAGES = ("ideia", "planejando", "construindo", "em-producao", "pausado")
STATES = ("pendente", "em-andamento", "em-teste", "concluida")
RECORD_DIRS = {"decisoes": "decisoes", "incidentes": "incidentes", "entregas": "entregas", "aprendizados": "aprendizados"}

_SECTION = re.compile(r"^(#{1,6})\s+.*pr[oó]ximas a[cç][oõ]es", re.I)
_HEADING = re.compile(r"^(#{1,6})\s")
_TASK = re.compile(r"^(?P<indent>[ \t]*)- \[(?P<mark>.)\] ?(?P<text>.*)$")
_STATE_TAG = re.compile(r"\s*#(em-andamento|em-teste)\b")
_DONE_DATE = re.compile(r"\s*✅\s*\d{4}-\d{2}-\d{2}")


class KanbanError(VaultError):
    pass


@dataclass
class Task:
    id: str
    text: str
    state: str
    line: int
    subtasks_done: int = 0
    subtasks_total: int = 0
    cancelled: bool = False
    done_on: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(text: str) -> str:
    return _DONE_DATE.sub("", _STATE_TAG.sub("", text)).strip()


def _state(mark: str, text: str) -> str:
    # [x] feita, [-] cancelada (plugin Tasks), [/] em andamento (plugin Tasks); o resto é etiqueta.
    if mark.lower() == "x" or mark == "-":
        return "concluida"
    if mark == "/":
        return "em-andamento"
    tag = _STATE_TAG.search(text)
    return tag.group(1) if tag else "pendente"


def _section(lines: list[str]) -> tuple[int, int] | None:
    """(linha do título, fim exclusivo) da seção Próximas ações."""
    for i, line in enumerate(lines):
        match = _SECTION.match(line)
        if match:
            level = len(match.group(1))
            for j in range(i + 1, len(lines)):
                heading = _HEADING.match(lines[j])
                if heading and len(heading.group(1)) <= level:
                    return i, j
            return i, len(lines)
    return None


def parse_tasks(text: str) -> list[Task]:
    lines = text.splitlines()
    bounds = _section(lines)
    if not bounds:
        return []
    tasks: list[Task] = []
    seen: dict[str, int] = {}
    parent: Task | None = None
    for i in range(bounds[0] + 1, bounds[1]):
        match = _TASK.match(lines[i])
        if not match:
            continue
        if match.group("indent"):
            if parent is not None:
                parent.subtasks_total += 1
                parent.subtasks_done += match.group("mark").lower() == "x"
            continue
        raw = match.group("text")
        clean = _clean(raw)
        digest = hashlib.sha1(clean.lower().encode("utf-8")).hexdigest()[:8]
        seen[digest] = seen.get(digest, 0) + 1
        task_id = digest if seen[digest] == 1 else f"{digest}-{seen[digest]}"
        done = _DONE_DATE.search(raw)
        parent = Task(
            id=task_id,
            text=clean,
            state=_state(match.group("mark"), raw),
            line=i,
            cancelled=clean.startswith("~~") or match.group("mark") == "-",
            done_on=done.group(0).replace("✅", "").strip() if done else "",
        )
        tasks.append(parent)
    return tasks


def _render(indent: str, text: str, state: str, done_on: str = "") -> str:
    mark = "x" if state == "concluida" else " "
    suffix = ""
    if state in ("em-andamento", "em-teste"):
        suffix = f" #{state}"
    elif state == "concluida":
        suffix = f" ✅ {done_on or date.today().isoformat()}"
    return f"{indent}- [{mark}] {text}{suffix}"


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


class Kanban:
    def __init__(self, vault: Vault) -> None:
        self.vault = vault

    # --- projetos -------------------------------------------------------------

    def projects(self) -> list[dict]:
        out = []
        for note in self.vault.projects():
            meta = note.meta
            tasks = parse_tasks(note.path.read_text(encoding="utf-8"))
            counts = {state: sum(t.state == state for t in tasks) for state in STATES}
            records = {}
            proposals = 0
            for key, folder in RECORD_DIRS.items():
                files = list((note.path.parent / folder).glob("*.md"))
                records[key] = len(files)
                if key == "decisoes":
                    for f in files:
                        try:
                            if split_frontmatter(f.read_text(encoding="utf-8"))[0].get("status") == "proposta":
                                proposals += 1
                        except OSError:
                            pass
            stage = meta.get("estagio", "").strip()
            out.append(
                {
                    "name": note.name,
                    "path": self.vault.rel(note.path),
                    "stage": stage if stage in STAGES else "",
                    "status": meta.get("status", ""),
                    "area": link_target(meta.get("area", "")),
                    "deadline": meta.get("prazo", ""),
                    "started": meta.get("inicio", ""),
                    "updated": meta.get("atualizado", ""),
                    "directory": meta.get("diretorio", ""),
                    "tasks": counts,
                    "next": [t.text for t in tasks if t.state != "concluida"][:3],
                    "records": records,
                    "proposals": proposals,
                }
            )
        return out

    def set_stage(self, name: str, stage: str) -> dict:
        if stage and stage not in STAGES:
            raise KanbanError(f"estágio desconhecido: {stage}")
        note = self.vault.project(name)
        text = note.path.read_text(encoding="utf-8")
        text = set_frontmatter(text, "estagio", stage)
        text = set_frontmatter(text, "atualizado", date.today().isoformat())
        write_atomic(note.path, text)
        return next(p for p in self.projects() if p["name"] == name)

    # --- tarefas --------------------------------------------------------------

    def tasks(self, name: str) -> list[dict]:
        note = self.vault.project(name)
        return [t.to_dict() for t in parse_tasks(note.path.read_text(encoding="utf-8"))]

    def _find(self, path: Path, task_id: str) -> tuple[str, list[str], Task]:
        text = path.read_text(encoding="utf-8")
        for task in parse_tasks(text):
            if task.id == task_id:
                return text, text.splitlines(), task
        raise KanbanError(f"tarefa não encontrada (a nota mudou?): {task_id}")

    def move(self, name: str, task_id: str, state: str) -> dict:
        if state not in STATES:
            raise KanbanError(f"estado desconhecido: {state} (use {', '.join(STATES)})")
        note = self.vault.project(name)
        text, lines, task = self._find(note.path, task_id)
        if task.state != state:
            match = _TASK.match(lines[task.line])
            assert match is not None
            body = _clean(match.group("text"))
            lines[task.line] = _render(match.group("indent"), body, state, task.done_on if state == "concluida" else "")
            nl = _newline(text)
            write_atomic(note.path, nl.join(lines) + (nl if text.endswith(("\n", "\r\n")) else ""))
        return next(t for t in self.tasks(name) if t["id"] == task_id)

    def add(self, name: str, text: str, state: str = "pendente") -> dict:
        body = " ".join(text.split()).strip()
        body = re.sub(r"^- \[.\]\s*", "", body)
        if not body:
            raise KanbanError("a tarefa está vazia")
        if state not in STATES:
            raise KanbanError(f"estado desconhecido: {state}")
        note = self.vault.project(name)
        raw = note.path.read_text(encoding="utf-8")
        nl = _newline(raw)
        lines = raw.splitlines()
        line = _render("", body, state)
        bounds = _section(lines)
        if bounds is None:
            # Nota sem a seção: ela nasce no fim, no formato das outras.
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", "## ✅ Próximas ações", "", line]
        else:
            tasks = parse_tasks(raw)
            anchor = next((t for t in reversed(tasks) if t.state != "concluida"), None) or (tasks[-1] if tasks else None)
            if anchor is None:
                at = bounds[0] + 1
                while at < bounds[1] and not lines[at].strip():
                    at += 1
                # depois do texto solto que abre a seção (ex.: "Retomar aqui…")
                while at < bounds[1] and lines[at].strip() and not _TASK.match(lines[at]):
                    at += 1
            else:
                at = anchor.line + 1
                while at < bounds[1] and (m := _TASK.match(lines[at])) and m.group("indent"):
                    at += 1  # depois das subtarefas da âncora
            lines.insert(at, line)
        write_atomic(note.path, nl.join(lines) + nl)
        added = parse_tasks(nl.join(lines))
        digest = hashlib.sha1(_clean(body).lower().encode("utf-8")).hexdigest()[:8]
        return next(t.to_dict() for t in reversed(added) if t.id.split("-")[0] == digest)
