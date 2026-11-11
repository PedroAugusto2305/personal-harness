"""Kanban de projetos e tarefas, lido e escrito direto nas notas do Brain.

- Estágio do projeto: chave `estagio:` no frontmatter da nota do projeto.
- Tarefas: as linhas `- [ ]` da seção "Próximas ações". O estado intermediário fica numa
  etiqueta no fim da linha (`#em-andamento`, `#em-teste`), assim a tarefa continua aberta
  para o Obsidian e para o `brain.py`; concluir marca `[x]` com a data (`✅ AAAA-MM-DD`,
  o formato do plugin Tasks que o vault já usa). Decisão de 2026-11-08 no Brain.
- Rótulos (v0.9.8): as outras etiquetas `#assim` do texto (com pelo menos uma letra, então
  `#123` continua sendo texto). Subtarefas: as linhas `- [ ]` recuadas logo abaixo.
- Prioridade e datas (v1.1): os campos do plugin Tasks no fim da linha (🔺 ⏫ 🔼 🔽 ⏬,
  🛫 início, 📅 entrega, ⏳, ➕, ❌), fora do título e do id. Descrição (v1.1): as linhas
  recuadas que não são `- [ ]`, entre a tarefa e a primeira subtarefa. O Obsidian mostra as
  duas coisas como parte do item da lista, e o agente lê tudo na nota.

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

# v1.1: campos do plugin Tasks (a variação \ufe0f do emoji é aceita e some ao regravar).
PRIORITIES = {"🔺": "urgente", "⏫": "alta", "🔼": "media", "🔽": "baixa", "⏬": "minima"}
PRIORITY_EMOJI = {name: emoji for emoji, name in PRIORITIES.items()}
DATE_FIELDS = {"🛫": "inicio", "⏳": "agendada", "⌛": "agendada", "📅": "entrega", "📆": "entrega", "🗓": "entrega", "➕": "criada", "❌": "cancelada"}
#: Ordem dos campos ao regravar a linha (a de cada campo só tem um emoji).
DATE_ORDER = (("inicio", "🛫"), ("agendada", "⏳"), ("entrega", "📅"), ("criada", "➕"), ("cancelada", "❌"))
EDITABLE_DATES = ("inicio", "entrega")
_PRIORITY = re.compile(r"\s*(" + "|".join(PRIORITIES) + r")\ufe0f?")
_DATE_FIELD = re.compile(r"\s*(" + "|".join(DATE_FIELDS) + r")\ufe0f?\s*(\d{4}-\d{2}-\d{2})")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
    #: v1.1: prioridade e datas (campos do plugin Tasks) e a descrição.
    prioridade: str = ""
    inicio: str = ""
    entrega: str = ""
    criada: str = ""
    descricao: str = ""
    #: Linhas da descrição, todos os campos lidos e a última linha da tarefa (fora do to_dict).
    desc_lines: list[int] = field(default_factory=list)
    fields: dict = field(default_factory=dict)
    end_line: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        for internal in ("sub_lines", "old_id", "desc_lines", "fields", "end_line"):
            data.pop(internal, None)
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


def split_fields(text: str) -> tuple[str, dict]:
    """O texto sem os campos do plugin Tasks e os campos (o primeiro de cada tipo vale)."""
    found: dict[str, str] = {}

    def date_field(match: re.Match) -> str:
        found.setdefault(DATE_FIELDS[match.group(1)], match.group(2))
        return ""

    def priority(match: re.Match) -> str:
        found.setdefault("prioridade", PRIORITIES[match.group(1)])
        return ""

    rest = _PRIORITY.sub(priority, _DATE_FIELD.sub(date_field, text))
    return " ".join(rest.split()), found


def _fields_text(fields: dict) -> list[str]:
    out = [PRIORITY_EMOJI[fields["prioridade"]]] if fields.get("prioridade") in PRIORITY_EMOJI else []
    return out + [f"{emoji} {fields[name]}" for name, emoji in DATE_ORDER if fields.get(name)]


def _dedent(raw: list[str]) -> str:
    """O texto da descrição: sem o recuo comum e sem linhas vazias nas pontas."""
    filled = [line for line in raw if line.strip()]
    cut = min((len(line) - len(line.lstrip()) for line in filled), default=0)
    lines = [line[cut:].rstrip() if line.strip() else "" for line in raw]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


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
    # Descrição aberta: depois da linha da tarefa, até a primeira subtarefa ou texto sem recuo.
    desc_open = False
    blanks: list[int] = []
    closed = False
    for i in range(bounds[0] + 1, bounds[1]):
        line = lines[i]
        match = _TASK.match(line)
        if match and match.group("indent"):
            desc_open, blanks = False, []
            if parent is not None:
                done_mark = match.group("mark").lower() == "x"
                parent.subtasks_total += 1
                parent.subtasks_done += done_mark
                parent.subtarefas.append(
                    {"indice": len(parent.subtarefas), "texto": _DONE_DATE.sub("", match.group("text")).strip(), "feita": done_mark}
                )
                parent.sub_lines.append(i)
                parent.end_line = i
                closed = False
            continue
        if match:
            raw = match.group("text")
            clean = _clean(raw)
            rest, fields = split_fields(clean)
            done = _DONE_DATE.search(raw)
            parent = Task(
                id=_numbered(seen, _digest(strip_labels(rest))),
                old_id=_numbered(seen_old, _digest(clean)),
                text=rest,
                state=_state(match.group("mark"), raw),
                line=i,
                cancelled=rest.startswith("~~") or match.group("mark") == "-",
                done_on=done.group(0).replace("✅", "").strip() if done else "",
                rotulos=labels_of(rest),
                texto=strip_labels(rest),
                prioridade=fields.get("prioridade", ""),
                inicio=fields.get("inicio", ""),
                entrega=fields.get("entrega", ""),
                criada=fields.get("criada", ""),
                fields=fields,
                end_line=i,
            )
            tasks.append(parent)
            desc_open, blanks, closed = True, [], False
            continue
        if not line.strip():
            if desc_open:
                blanks.append(i)
            continue
        if line[:1] in (" ", "\t"):
            if parent is not None and not closed:
                if desc_open:
                    parent.desc_lines += [*blanks, i]
                    blanks = []
                parent.end_line = i
            continue
        # Texto solto sem recuo ("Retomar aqui…"): a tarefa de cima acabou.
        desc_open, blanks, closed = False, [], True
    for task in tasks:
        if task.desc_lines:
            task.descricao = _dedent([lines[i] for i in task.desc_lines])
    return tasks


PRIORITY_LABEL = {"urgente": "urgente", "alta": "alta", "media": "média", "baixa": "baixa", "minima": "mínima"}


def task_brief(task: dict, anexos: list[dict] | None = None) -> str:
    """v1.1: o que o cartão aberto tem além do título, para o pedido do agente (Auto e
    Executar agora): prioridade e datas, descrição, checklist e os caminhos dos anexos."""
    out: list[str] = []
    meta = []
    if task.get("prioridade"):
        meta.append(f"prioridade {PRIORITY_LABEL.get(task['prioridade'], task['prioridade'])}")
    if task.get("inicio"):
        meta.append(f"início {task['inicio']}")
    if task.get("entrega"):
        meta.append(f"entrega {task['entrega']}")
    if task.get("rotulos"):
        meta.append("rótulos " + " ".join(f"#{label}" for label in task["rotulos"]))
    if meta:
        out.append(" · ".join(meta))
    if task.get("descricao"):
        out += ["", "Descrição:", task["descricao"]]
    subs = task.get("subtarefas") or []
    if subs:
        out += ["", "Checklist (marque cada item que terminar com a ferramenta tarefa_subtarefa da central metis, pelo índice):"]
        out += [f"{s['indice']}. [{'x' if s['feita'] else ' '}] {s['texto']}" for s in subs]
    if anexos:
        out += ["", "Anexos (arquivos no disco; abra os que ajudarem):"]
        out += [f"- {a['nome']}: {a['caminho']}" for a in anexos]
    return "\n".join(out).strip()


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
        #: v1.1: a atividade de cada tarefa (TaskLog). Sem ele, nada é registrado.
        self.log = None
        #: v1.1: avisado quando o título muda e, com ele, o id: (projeto, id de antes, id novo).
        self.on_rename = None

    def _record(self, name: str, task_id: str, quem: str, tipo: str, dados: dict | None = None, texto: str = "") -> None:
        if self.log is None:
            return
        try:
            self.log.add(name, task_id, quem or "Pedro", tipo, texto=texto, dados=dados or {})
        except Exception:  # noqa: BLE001 - registrar nunca atrapalha a escrita na nota
            pass

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

    def move(self, name: str, task_id: str, state: str, quem: str = "Pedro") -> dict:
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
        if task.state != state:
            self._record(name, moved["id"], quem, "moveu", {"de": task.state, "para": state})
        if task.state != state and self.on_move is not None:
            try:
                self.on_move({"projeto": name, "id": moved["id"], "texto": moved.get("texto") or moved["text"], "de": task.state, "para": state})
            except Exception:  # noqa: BLE001 - o gatilho nunca atrapalha mover a tarefa
                pass
        return moved

    def add(self, name: str, text: str, state: str = "pendente", labels: list[str] | None = None, subtasks: list[str] | None = None,
            quem: str = "Pedro", *, descricao: str | None = None, prioridade: str | None = None, inicio: str | None = None,
            entrega: str | None = None) -> dict:  # fmt: skip
        """v1.1.3: a tarefa já nasce inteira, como o cartão aberto a deixaria: prioridade e datas
        na linha (campos do plugin Tasks) e a descrição nas linhas recuadas logo abaixo. Tudo é
        conferido antes de gravar, para um campo errado não deixar meia tarefa na nota."""
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
        asked: dict[str, str] = {}
        if prioridade is not None and prioridade.strip().lower() not in ("", "normal"):
            wanted = prioridade.strip().lower().replace("média", "media").replace("mínima", "minima")
            if wanted not in PRIORITY_EMOJI:
                raise KanbanError(f"prioridade desconhecida: {prioridade} (urgente, alta, media, normal, baixa ou minima)")
            asked["prioridade"] = wanted
        for key, value in (("inicio", inicio), ("entrega", entrega)):
            if value is not None and value.strip():
                if not _ISO_DATE.match(value.strip()):
                    raise KanbanError(f"data inválida em {key}: {value} (use AAAA-MM-DD)")
                asked[key] = value.strip()
        if asked:
            rest, typed = split_fields(body)
            body = " ".join([rest, *_fields_text({**typed, **asked})])
        desc_lines: list[str] = []
        if descricao is not None and descricao.strip():
            wanted_desc = _dedent(str(descricao).replace("\r\n", "\n").split("\n"))
            if any(_TASK.match(line) for line in wanted_desc.split("\n")):
                # Uma linha "- [ ]" recuada vira subtarefa e corta a descrição ao meio.
                raise KanbanError("a descrição não pode ter linhas '- [ ]': as etapas vão em subtarefas")
            desc_lines = [f"  {line}" if line.strip() else "" for line in wanted_desc.split("\n")]
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
            lines += ["", "## ✅ Próximas ações", "", line, *desc_lines]
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
                at = anchor.end_line + 1  # depois da descrição e das subtarefas da âncora
            lines[at:at] = [line, *desc_lines]
        write_atomic(note.path, nl.join(lines) + nl)
        added = parse_tasks(nl.join(lines))
        digest = _digest(strip_labels(split_fields(_clean(body))[0]))
        task = next(t for t in reversed(added) if t.id.split("-")[0] == digest)
        result = task.to_dict()
        self._record(name, task.id, quem, "criou", {"estado": state})
        for sub in subtasks or []:
            if str(sub).strip():
                result = self.add_subtask(name, task.id, str(sub), quem=quem)
        return result

    # --- rótulos e subtarefas (v0.9.8) -----------------------------------------------

    def _write(self, path: Path, text: str, lines: list[str]) -> None:
        nl = _newline(text)
        write_atomic(path, nl.join(lines) + (nl if text.endswith(("\n", "\r\n")) else ""))

    def _line(self, match: re.Match, base: str, labels: list[str], fields: dict) -> str:
        """A linha da tarefa: título, rótulos, campos do plugin Tasks e, no fim, a etiqueta de
        estado e a data de conclusão como estavam. A marca ([x], [-] cancelada, [/]…) também
        fica (o _render reescreveria [-] como [x] e [/] como [ ])."""
        raw = match.group("text")
        tag = _STATE_TAG.search(raw)
        done = _DONE_DATE.search(raw)
        body = " ".join([base, *(f"#{label}" for label in labels), *_fields_text(fields)]).strip()
        suffix = (f" #{tag.group(1)}" if tag else "") + (f" {done.group(0).strip()}" if done else "")
        return f"{match.group('indent')}- [{match.group('mark')}] {body}{suffix}"

    def set_labels(self, name: str, task_id: str, labels: list[str], quem: str = "Pedro") -> dict:
        """Troca os rótulos da tarefa: ficam no fim do texto, antes dos campos e da etiqueta de
        estado. O id é o hash do texto sem os rótulos, então ele não muda."""
        note = self.vault.project(name)
        text, lines, task = self._find(note.path, task_id)
        match = _TASK.match(lines[task.line])
        assert match is not None
        rest, fields = split_fields(_clean(match.group("text")))
        wanted = normalize_labels(labels)
        lines[task.line] = self._line(match, strip_labels(rest), wanted, fields)
        self._write(note.path, text, lines)
        if wanted != task.rotulos:
            self._record(name, task.id, quem, "rotulos", {"antes": task.rotulos, "depois": wanted})
        return self._task_at(note.path, task.line)

    def update(self, name: str, task_id: str, *, titulo: str | None = None, descricao: str | None = None, prioridade: str | None = None,
               inicio: str | None = None, entrega: str | None = None, quem: str = "Pedro") -> dict:  # fmt: skip
        """v1.1: o que o cartão aberto edita. None deixa como está; texto vazio limpa (o título
        não pode ficar vazio). Mudar o título muda o id da tarefa: a resposta traz o novo, e
        `id_antes` diz o de antes para quem guarda o id (atividade, fila do Auto)."""
        note = self.vault.project(name)
        text, lines, task = self._find(note.path, task_id)
        match = _TASK.match(lines[task.line])
        assert match is not None
        rest, fields = split_fields(_clean(match.group("text")))
        base, labels = strip_labels(rest), labels_of(rest)
        changes: list[tuple[str, dict]] = []
        if titulo is not None:
            typed = re.sub(r"^- \[.\]\s*", "", " ".join(str(titulo).split()))
            typed_rest, typed_fields = split_fields(_STATE_TAG.sub("", typed))
            new_base = strip_labels(typed_rest)
            if not new_base:
                raise KanbanError("o título da tarefa não pode ficar vazio")
            labels = normalize_labels([*labels, *labels_of(typed_rest)])  # #rótulo escrito no título vira rótulo
            fields = {**fields, **typed_fields}
            if new_base != base:
                changes.append(("titulo", {"de": base, "para": new_base}))
                base = new_base
        if prioridade is not None:
            wanted = prioridade.strip().lower()
            if wanted in ("", "normal"):
                wanted = ""
            elif wanted not in PRIORITY_EMOJI:
                raise KanbanError(f"prioridade desconhecida: {prioridade} (urgente, alta, media, normal, baixa ou minima)")
            if wanted != fields.get("prioridade", ""):
                changes.append(("prioridade", {"de": fields.get("prioridade", ""), "para": wanted}))
            fields = {k: v for k, v in fields.items() if k != "prioridade"} | ({"prioridade": wanted} if wanted else {})
        for key, value in (("inicio", inicio), ("entrega", entrega)):
            if value is None:
                continue
            wanted = value.strip()
            if wanted and not _ISO_DATE.match(wanted):
                raise KanbanError(f"data inválida em {key}: {value} (use AAAA-MM-DD)")
            if wanted != fields.get(key, ""):
                changes.append(("data", {"campo": key, "de": fields.get(key, ""), "para": wanted}))
            fields = {k: v for k, v in fields.items() if k != key} | ({key: wanted} if wanted else {})
        if labels != task.rotulos:
            changes.append(("rotulos", {"antes": task.rotulos, "depois": labels}))
        # A linha só é regravada quando algo dela mudou: editar só a descrição não reordena
        # rótulos e campos que o Pedro escreveu à mão no Obsidian.
        line_changed = any(tipo != "descricao" for tipo, _ in changes) or fields != split_fields(_clean(match.group("text")))[1]
        if line_changed:
            lines[task.line] = self._line(match, base, labels, fields)
        if descricao is not None:
            wanted_desc = _dedent(str(descricao).replace("\r\n", "\n").split("\n"))
            if wanted_desc != task.descricao:
                changes.append(("descricao", {"antes": bool(task.descricao), "depois": bool(wanted_desc)}))
                new_lines = [f"  {line}" if line.strip() else "" for line in wanted_desc.split("\n")] if wanted_desc else []
                if task.desc_lines:
                    lines[task.line + 1 : task.desc_lines[-1] + 1] = new_lines
                else:
                    lines[task.line + 1 : task.line + 1] = new_lines
        if changes:
            self._write(note.path, text, lines)
        result = self._task_at(note.path, task.line) if changes else task.to_dict()
        if result["id"] != task.id:
            # A atividade, os anexos e a fila do Auto seguem a tarefa no id novo.
            if self.log is not None:
                try:
                    self.log.rename(name, task.id, result["id"])
                except Exception:  # noqa: BLE001
                    pass
            if self.on_rename is not None:
                try:
                    self.on_rename(name, task.id, result["id"])
                except Exception:  # noqa: BLE001
                    pass
        for tipo, dados in changes:
            self._record(name, result["id"], quem, tipo, dados)
        return {**result, "id_antes": task.id}

    def add_subtask(self, name: str, task_id: str, text: str, quem: str = "Pedro") -> dict:
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
            at = (task.desc_lines[-1] if task.desc_lines else task.line) + 1  # depois da descrição
        lines.insert(at, f"{indent}- [ ] {body}")
        self._write(note.path, raw, lines)
        self._record(name, task.id, quem, "subtarefa", {"acao": "criou", "texto": body})
        return self._task_at(note.path, task.line)

    def mark_subtask(self, name: str, task_id: str, index: int, done: bool, quem: str = "Pedro") -> dict:
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
        self._record(name, task.id, quem, "subtarefa", {"acao": "marcou" if done else "desmarcou", "texto": body})
        return self._task_at(note.path, task.line)

    def _subtask(self, lines: list[str], task: Task, index: int) -> tuple[int, int, re.Match]:
        """(primeira linha, fim exclusivo, linha casada) da subtarefa, com as linhas mais recuadas
        que continuam o texto dela."""
        if not 0 <= index < len(task.sub_lines):
            raise KanbanError(f"subtarefa {index} não existe (a tarefa tem {len(task.sub_lines)})")
        at = task.sub_lines[index]
        match = _TASK.match(lines[at])
        assert match is not None
        depth = len(match.group("indent").expandtabs(4))
        end = at + 1
        while end <= task.end_line and lines[end].strip() and not _TASK.match(lines[end]) and len(lines[end]) - len(lines[end].lstrip()) > depth:
            end += 1
        return at, end, match

    def edit_subtask(self, name: str, task_id: str, index: int, text: str, quem: str = "Pedro") -> dict:
        body = re.sub(r"^- \[.\]\s*", "", " ".join(str(text).split()).strip())
        if not body:
            raise KanbanError("a subtarefa está vazia")
        note = self.vault.project(name)
        raw, lines, task = self._find(note.path, task_id)
        at, _, match = self._subtask(lines, task, index)
        done = _DONE_DATE.search(match.group("text"))
        before = _DONE_DATE.sub("", match.group("text")).strip()
        if body != before:
            lines[at] = f"{match.group('indent')}- [{match.group('mark')}] {body}" + (f" {done.group(0).strip()}" if done else "")
            self._write(note.path, raw, lines)
            self._record(name, task.id, quem, "subtarefa", {"acao": "editou", "texto": body, "antes": before})
        return self._task_at(note.path, task.line)

    def remove_subtask(self, name: str, task_id: str, index: int, quem: str = "Pedro") -> dict:
        note = self.vault.project(name)
        raw, lines, task = self._find(note.path, task_id)
        at, end, match = self._subtask(lines, task, index)
        del lines[at:end]
        self._write(note.path, raw, lines)
        self._record(name, task.id, quem, "subtarefa", {"acao": "apagou", "texto": _DONE_DATE.sub("", match.group("text")).strip()})
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
