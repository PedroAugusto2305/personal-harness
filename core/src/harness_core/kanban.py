"""Kanban de projetos e tarefas, lido e escrito direto nas notas do Brain.

- Estágio do projeto: chave `estagio:` no frontmatter da nota do projeto.
- Tarefas: as linhas `- [ ]` da seção "Próximas ações". O estado intermediário fica numa
  etiqueta no fim da linha (`#em-andamento`, `#em-teste`), assim a tarefa continua aberta
  para o Obsidian e para o `brain.py`; concluir marca `[x]` com a data (`✅ AAAA-MM-DD`,
  o formato do plugin Tasks que o vault já usa). Decisão de 2026-11-08 no Brain.
- Rótulos (v0.9.8): as outras etiquetas `#assim` do texto (com pelo menos uma letra, então
  `#123` continua sendo texto). Subtarefas: as linhas `- [ ]` recuadas logo abaixo.

Toda escrita relê a nota, acha a linha pelo id e troca só ela, para não atropelar o que o
Obsidian ou outro agente gravou no meio tempo. O id é o hash do texto sem a etiqueta de
estado e sem os rótulos (v1.0), então mudar os rótulos não muda o id. O id de antes (que
contava os rótulos) continua achando a tarefa: a fila do Auto e os pedidos já entregues aos
agentes guardam ids desse tempo.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
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
_LABEL = re.compile(r"(?<!\S)#([\w\-/]+)")
_STATE_NAMES = {"em-andamento", "em-teste"}


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
    #: v0.9.8: rótulos (sem o #), o texto sem eles e as subtarefas.
    rotulos: list[str] = field(default_factory=list)
    texto: str = ""
    subtarefas: list[dict] = field(default_factory=list)
    #: Linha de cada subtarefa na nota (fica fora do to_dict).
    sub_lines: list[int] = field(default_factory=list)
    #: Id da v0.9.8 e da v0.9.9, que contava os rótulos (fica fora do to_dict).
    old_id: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("sub_lines", None)
        data.pop("old_id", None)
        return data


def labels_of(text: str) -> list[str]:
    """Os rótulos do texto, na ordem, sem repetir (etiqueta só de número não conta)."""
    out: list[str] = []
    for match in _LABEL.finditer(text):
        name = match.group(1)
        if name.lower() in _STATE_NAMES or not any(ch.isalpha() for ch in name):
            continue
        if name not in out:
            out.append(name)
    return out


def strip_labels(text: str) -> str:
    def drop(match: re.Match) -> str:
        name = match.group(1)
        return match.group(0) if name.lower() in _STATE_NAMES or not any(ch.isalpha() for ch in name) else ""

    return " ".join(_LABEL.sub(drop, text).split())


def normalize_labels(labels: list[str]) -> list[str]:
    """Minúsculas, sem o #, espaço vira hífen; só letras, números, hífen, sublinhado e barra."""
    out: list[str] = []
    for raw in labels:
        name = "-".join(str(raw).strip().lstrip("#").lower().split())
        name = re.sub(r"[^\w\-/]", "", name)
        if not name or name in _STATE_NAMES or not any(ch.isalpha() for ch in name):
            continue
        if name not in out:
            out.append(name)
    return out


def _clean(text: str) -> str:
    return _DONE_DATE.sub("", _STATE_TAG.sub("", text)).strip()


def _digest(text: str) -> str:
    return hashlib.sha1(text.lower().encode("utf-8")).hexdigest()[:8]


def _numbered(seen: dict[str, int], digest: str) -> str:
    seen[digest] = seen.get(digest, 0) + 1
    return digest if seen[digest] == 1 else f"{digest}-{seen[digest]}"


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
    seen_old: dict[str, int] = {}
    parent: Task | None = None
    for i in range(bounds[0] + 1, bounds[1]):
        match = _TASK.match(lines[i])
        if not match:
            continue
        if match.group("indent"):
            if parent is not None:
                done_mark = match.group("mark").lower() == "x"
                parent.subtasks_total += 1
                parent.subtasks_done += done_mark
                parent.subtarefas.append(
                    {"indice": len(parent.subtarefas), "texto": _DONE_DATE.sub("", match.group("text")).strip(), "feita": done_mark}
                )
                parent.sub_lines.append(i)
            continue
        raw = match.group("text")
        clean = _clean(raw)
        done = _DONE_DATE.search(raw)
        parent = Task(
            id=_numbered(seen, _digest(strip_labels(clean))),
            old_id=_numbered(seen_old, _digest(clean)),
            text=clean,
            state=_state(match.group("mark"), raw),
            line=i,
            cancelled=clean.startswith("~~") or match.group("mark") == "-",
            done_on=done.group(0).replace("✅", "").strip() if done else "",
            rotulos=labels_of(clean),
            texto=strip_labels(clean),
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
        #: v0.9.8: avisado a cada tarefa que muda de coluna (gatilho "tarefa.moveu" das automações).
        self.on_move = None

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
        tasks = parse_tasks(text)
        # O id de agora vale primeiro; o de antes da v1.0 (com os rótulos) só se nenhum bater.
        task = next((t for t in tasks if t.id == task_id), None) or next((t for t in tasks if t.old_id == task_id), None)
        if task is None:
            raise KanbanError(f"tarefa não encontrada (a nota mudou?): {task_id}")
        return text, text.splitlines(), task

    def current_ids(self, name: str) -> dict[str, str]:
        """Id de agora de cada tarefa do projeto, pelo id de agora e pelo de antes da v1.0
        (como no _find, o de agora vale primeiro)."""
        tasks = parse_tasks(self.vault.project(name).path.read_text(encoding="utf-8"))
        return {**{t.old_id: t.id for t in tasks}, **{t.id: t.id for t in tasks}}

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
        # Pela linha (só ela mudou): o id pedido pode ser o de antes da v1.0.
        moved = self._task_at(note.path, task.line)
        if task.state != state and self.on_move is not None:
            try:
                self.on_move({"projeto": name, "id": moved["id"], "texto": moved.get("texto") or moved["text"], "de": task.state, "para": state})
            except Exception:  # noqa: BLE001 - o gatilho nunca atrapalha mover a tarefa
                pass
        return moved

    def add(self, name: str, text: str, state: str = "pendente", labels: list[str] | None = None, subtasks: list[str] | None = None) -> dict:
        body = " ".join(text.split()).strip()
        body = re.sub(r"^- \[.\]\s*", "", body)
        if labels:
            # Os rótulos escritos no texto ficam, somados aos pedidos à parte (sem repetir).
            merged = normalize_labels([*labels_of(body), *labels])
            body = " ".join([strip_labels(body), *(f"#{label}" for label in merged)]).strip()
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
        digest = _digest(strip_labels(_clean(body)))
        task = next(t for t in reversed(added) if t.id.split("-")[0] == digest)
        result = task.to_dict()
        for sub in subtasks or []:
            if str(sub).strip():
                result = self.add_subtask(name, task.id, str(sub))
        return result

    # --- rótulos e subtarefas (v0.9.8) -----------------------------------------------

    def _write(self, path: Path, text: str, lines: list[str]) -> None:
        nl = _newline(text)
        write_atomic(path, nl.join(lines) + (nl if text.endswith(("\n", "\r\n")) else ""))

    def set_labels(self, name: str, task_id: str, labels: list[str]) -> dict:
        """Troca os rótulos da tarefa: ficam no fim do texto, antes da etiqueta de estado.
        O id é o hash do texto sem os rótulos, então ele não muda."""
        note = self.vault.project(name)
        text, lines, task = self._find(note.path, task_id)
        match = _TASK.match(lines[task.line])
        assert match is not None
        raw = match.group("text")
        base = strip_labels(_clean(raw))
        wanted = normalize_labels(labels)
        body = " ".join([base, *(f"#{label}" for label in wanted)]).strip()
        # Só os rótulos mudam: a marca ([x], [-] cancelada, [/]…), a etiqueta de estado e a
        # data ficam como estavam (o _render reescreveria [-] como [x] e [/] como [ ]).
        tag = _STATE_TAG.search(raw)
        done = _DONE_DATE.search(raw)
        suffix = (f" #{tag.group(1)}" if tag else "") + (f" {done.group(0).strip()}" if done else "")
        lines[task.line] = f"{match.group('indent')}- [{match.group('mark')}] {body}{suffix}"
        self._write(note.path, text, lines)
        return self._task_at(note.path, task.line)

    def add_subtask(self, name: str, task_id: str, text: str) -> dict:
        body = " ".join(str(text).split()).strip()
        body = re.sub(r"^- \[.\]\s*", "", body)
        if not body:
            raise KanbanError("a subtarefa está vazia")
        note = self.vault.project(name)
        raw, lines, task = self._find(note.path, task_id)
        if task.sub_lines:
            last = task.sub_lines[-1]
            indent = _TASK.match(lines[task.sub_lines[0]]).group("indent")  # type: ignore[union-attr]
            at = last + 1
        else:
            indent = "  "
            at = task.line + 1
        lines.insert(at, f"{indent}- [ ] {body}")
        self._write(note.path, raw, lines)
        return self._task_at(note.path, task.line)

    def mark_subtask(self, name: str, task_id: str, index: int, done: bool) -> dict:
        note = self.vault.project(name)
        raw, lines, task = self._find(note.path, task_id)
        if not 0 <= index < len(task.sub_lines):
            raise KanbanError(f"subtarefa {index} não existe (a tarefa tem {len(task.sub_lines)})")
        at = task.sub_lines[index]
        match = _TASK.match(lines[at])
        assert match is not None
        body = _DONE_DATE.sub("", match.group("text")).strip()
        lines[at] = f"{match.group('indent')}- [{'x' if done else ' '}] {body}" + (f" ✅ {date.today().isoformat()}" if done else "")
        self._write(note.path, raw, lines)
        return self._task_at(note.path, task.line)

    def _task_at(self, path: Path, line: int) -> dict:
        for task in parse_tasks(path.read_text(encoding="utf-8")):
            if task.line == line:
                return task.to_dict()
        raise KanbanError("a tarefa mudou de lugar na nota; recarregue")

    def labels(self, name: str) -> list[dict]:
        """Os rótulos usados nas tarefas do projeto, com quantas tarefas têm cada um."""
        counts: dict[str, int] = {}
        for task in parse_tasks(self.vault.project(name).path.read_text(encoding="utf-8")):
            for label in task.rotulos:
                counts[label] = counts.get(label, 0) + 1
        return [{"nome": n, "quantas": c} for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
