"""Planos de estudo (v1.4.0): criar, editar, ativar, desativar e excluir na aba de Estudos.

Regras (decisão de 2026-11-16, no Brain):

- Um plano é um projeto do Brain (`01-PROJETOS/<Plano>/<Plano>.md`) com `plano_estudo: ativo` ou
  `inativo` no frontmatter, o `tema`, o período em `inicio` e `prazo` e o cronograma na primeira
  tabela com as colunas da semana e das datas (a mesma que o study_map lê). Os conceitos ficam na
  pasta dele (`conceitos/`), como já era.
- O plano que existia antes (o ajuste `estudo_projeto`, sem a chave) é adotado como ativo na
  primeira leitura: ganha `plano_estudo: ativo` e passa a ter as mesmas opções dos novos.
- Vários planos podem estar ativos. O "plano em foco" (o ajuste `estudo_projeto`) é o que o
  Pomodoro, o mapa e as sessões usam quando ninguém diz o plano. Desativar ou excluir o plano em
  foco passa o foco ao próximo ativo; criar ou ativar sem foco válido põe o plano em foco.
- Desativar só troca o estado: a nota fica onde está e volta com Ativar.
- Excluir arquiva: a pasta inteira do plano vai para `04-ARQUIVO/`, com `status: arquivado`, o
  aviso no topo e uma linha no Log. Nada é apagado (regra 1 do vault: "nunca deletar nota").
- Cada mudança fica na nota: o frontmatter, a tabela e uma linha no 📝 Log do dia. Antes de trocar
  o cronograma, a nota inteira vai para `~/.harness/estudo/versoes/<Plano>/` (as 20 últimas), para
  desfazer à mão se um agente gravar o que não devia.
"""

from __future__ import annotations

import re
import shutil
import threading
import time
from itertools import pairwise
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from .study_map import _DATE_FULL, BAD_TITLE, StudyError, StudyMap, _plain, current_week, fold, parse_plan, plan_table
from .vault import PROJECTS_DIR, ProjectNote, Vault, VaultError, iter_notes, set_frontmatter, split_frontmatter, write_atomic

PLAN_KEY = "plano_estudo"
ACTIVE, INACTIVE, DELETED = "ativo", "inativo", "excluido"
ARCHIVE_DIR = "04-ARQUIVO"
MAX_WEEKS = 106  # dois anos inteiros, com folga
MAX_DAYS = 2 * 366
TEXT_MAX = 300
GOAL_MAX = 8000
KEEP_VERSIONS = 20
SCHEDULE_HEADING = "## 🗓️ Cronograma"
STANDARD_HEADERS = ["Sem.", "Datas", "Foco", "Entrega"]
# Onde a seção do cronograma nasce numa nota que ainda não tem a tabela (antes da primeira que existir).
SCHEDULE_BEFORE = ("## ✅ Próximas ações", "## 🧩 Contexto", "## 🗂️ Notas do projeto", "## 📎 Recursos", "## 📝 Log")
WHO = "aba de Estudos da MÊTIS"


class PlanError(StudyError):
    pass


# --- validação ---------------------------------------------------------------------------


def clean_plan_name(name: str) -> str:
    title = " ".join(BAD_TITLE.sub(" ", str(name or "")).split()).strip(" .")
    if not title:
        raise PlanError("o plano precisa de um nome")
    if len(title) > 80:
        raise PlanError("nome de plano longo demais (até 80 caracteres)")
    return title


def clean_text(value: object, limit: int = TEXT_MAX) -> str:
    """Uma linha só, sem a barra que quebraria a tabela."""
    return " ".join(str(value or "").replace("|", "/").split())[:limit]


def parse_day(value: object, label: str) -> date:
    raw = str(value or "").strip()
    problem = PlanError(f"{label}: use a data no formato AAAA-MM-DD (veio «{raw}»)")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise problem
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise problem from None


def check_period(start: date, end: date) -> None:
    if end < start:
        raise PlanError("o fim do plano vem antes do início")
    if (end - start).days > MAX_DAYS:
        raise PlanError("o período do plano vai até 2 anos")


def skeleton(start: date, end: date) -> list[dict]:
    """As semanas do período, de 7 em 7 dias a partir do início, sem foco: o agente (ou o Pedro) preenche."""
    weeks = []
    day = start
    while day <= end and len(weeks) < MAX_WEEKS:
        last = min(day + timedelta(days=6), end)
        weeks.append({"numero": len(weeks) + 1, "inicio": day.isoformat(), "fim": last.isoformat(), "foco": "", "entrega": ""})
        day += timedelta(days=7)
    return weeks


def clean_weeks(raw: object) -> list[dict]:
    """As semanas que chegam da tela ou do agente: datas válidas, em ordem, sem sobreposição,
    numeradas de 1 em diante (o número que veio não vale: a ordem é a das datas)."""
    if not isinstance(raw, list):
        raise PlanError("semanas é uma lista de {inicio, fim, foco, entrega}")
    if len(raw) > MAX_WEEKS:
        raise PlanError(f"o cronograma vai até {MAX_WEEKS} semanas")
    weeks = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise PlanError(f"a semana {i} não é um objeto {{inicio, fim, foco, entrega}}")
        start = parse_day(item.get("inicio"), f"início da semana {i}")
        end = parse_day(item.get("fim") or item.get("inicio"), f"fim da semana {i}")
        if end < start:
            raise PlanError(f"a semana {i} termina antes de começar")
        if (end - start).days > 31:
            raise PlanError(f"a semana {i} passa de um mês")
        weeks.append({"inicio": start, "fim": end, "foco": clean_text(item.get("foco")), "entrega": clean_text(item.get("entrega"))})
    weeks.sort(key=lambda w: w["inicio"])
    for prev, week in pairwise(weeks):
        if week["inicio"] <= prev["fim"]:
            raise PlanError(f"a semana que começa em {week['inicio']} cruza com a de {prev['inicio']} a {prev['fim']}")
    return [{"numero": n, "inicio": w["inicio"].isoformat(), "fim": w["fim"].isoformat(), "foco": w["foco"], "entrega": w["entrega"]} for n, w in enumerate(weeks, start=1)]


# --- escrita na nota ---------------------------------------------------------------------


def _short(day: str) -> str:
    return f"{day[5:7]}-{day[8:10]}"


def _dates_text(week: dict, short: bool) -> str:
    if short:
        return f"{_short(week['inicio'])} a {_short(week['fim'])}"
    return f"{week['inicio']} a {week['fim']}"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _render(text: str, weeks: list[dict], today: date, full: bool) -> str:
    lines = text.split("\n")
    table = plan_table(text, today)
    if table is None:
        headers = list(STANDARD_HEADERS)
        cols = {"week": 0, "dates": 1, "focus": 2, "deliver": 3}
        separator = _row(["---"] * 4).replace(" ", "")
        old: list[tuple[list[str], dict]] = []
        short = False
    else:
        headers = list(table.headers)
        cols = {"week": table.week, "dates": table.dates, "focus": table.focus, "deliver": table.deliver}
        separator = table.separator
        # Sem as colunas de foco ou de entrega, elas entram no fim (a tela e o agente escrevem as duas).
        for key, title in (("focus", "Foco"), ("deliver", "Entrega")):
            if cols[key] is None:
                cols[key] = len(headers)
                headers.append(title)
                separator = ""
        if not separator:
            separator = _row(["---"] * len(headers)).replace(" ", "")
        old = [(cells, week) for cells, week in table.rows if week is not None]
        # Tabela com datas curtas (10-05 a 10-10) continua curta; a conferência abaixo volta para a data cheia se a leitura mudar.
        short = not full and bool(old) and not any(_DATE_FULL.search(cells[table.dates]) for cells, _w in old)
    by_start = {w["inicio"]: (cells, w) for cells, w in old}
    by_number = {w["numero"]: (cells, w) for cells, w in old}
    starts = {w["inicio"] for w in weeks}
    rows = []
    for week in weeks:
        match = by_start.get(week["inicio"])
        if match is None:
            candidate = by_number.get(week["numero"])
            # A linha de mesmo número só serve se a semana dela não foi para outro lugar.
            if candidate is not None and candidate[1]["inicio"] not in starts:
                match = candidate
        cells = [""] * len(headers)
        if match is not None:
            for i, value in enumerate(match[0][: len(headers)]):
                cells[i] = value
        prev = match[1] if match is not None else None
        # A célula crua (negrito, [[link]]) fica quando o valor não mudou.
        cells[cols["week"]] = cells[cols["week"]] if prev is not None and prev["numero"] == week["numero"] else str(week["numero"])
        dates_same = prev is not None and prev["inicio"] == week["inicio"] and prev["fim"] == week["fim"] and not full
        cells[cols["dates"]] = cells[cols["dates"]] if dates_same else _dates_text(week, short)
        for key, col in (("foco", cols["focus"]), ("entrega", cols["deliver"])):
            cells[col] = cells[col] if cells[col] and _plain(cells[col]) == week[key] else week[key]
        rows.append(_row(cells))
    # Linha da tabela que não é semana (um total, uma observação) não se perde: vai para o fim.
    if table is not None:
        for cells, week in table.rows:
            if week is None:
                rows.append(_row((cells + [""] * len(headers))[: max(len(headers), len(cells))]))
    block = [_row(headers), separator, *rows]
    if table is None:
        at = next((i for i, l in enumerate(lines) if any(l.startswith(b) for b in SCHEDULE_BEFORE)), None)
        section = [SCHEDULE_HEADING, "", *block, ""]
        if at is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", *section]
        else:
            lines[at:at] = section
    else:
        lines[table.start : table.end] = block
    return "\n".join(lines)


def render_schedule(text: str, weeks: list[dict], today: date, *, full: bool = False) -> str:
    """Troca a tabela do cronograma (ou cria a seção 🗓️ Cronograma) pelas semanas dadas.

    Mantém as colunas que a MÊTIS não conhece (a "Origem" do AI Engineer 2027) e a célula crua
    (negrito, [[link]]) quando o valor não mudou. Se as datas curtas lerem diferente do pedido (o
    ano vem do `inicio` da nota), reescreve com a data cheia."""
    new = _render(text, weeks, today, full)
    wanted = [(w["inicio"], w["fim"]) for w in weeks]
    if not full and [(w["inicio"], w["fim"]) for w in parse_plan(new, today)] != wanted:
        new = _render(text, weeks, today, True)
    return new


def goal_of(body: str) -> str:
    """O texto do primeiro callout > [!abstract] (o objetivo do projeto), com as quebras de linha.
    O `> [!todo] preencher` do modelo conta como objetivo vazio."""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"\s*>\s*\[!abstract\]", line, re.I):
            out = []
            for follow in lines[i + 1 :]:
                if not follow.lstrip().startswith(">"):
                    break
                out.append(re.sub(r"^\s*>\s?", "", follow))
            text = "\n".join(out).strip()
            return "" if re.fullmatch(r">\s*\[!todo\][^\n]*", text) else text
    return ""


def set_goal(text: str, goal: str) -> str:
    """Troca o conteúdo do primeiro > [!abstract] (ou cria o callout logo abaixo do título)."""
    body_lines = [f"> {line}".rstrip() for line in goal.strip().split("\n")] if goal.strip() else ["> > [!todo] preencher"]
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"\s*>\s*\[!abstract\]", line, re.I):
            end = i + 1
            while end < len(lines) and lines[end].lstrip().startswith(">"):
                end += 1
            lines[i + 1 : end] = body_lines
            return "\n".join(lines)
    title = next((i for i, l in enumerate(lines) if l.startswith("# ")), None)
    block = ["> [!abstract] Objetivo", *body_lines, ""]
    if title is None:
        start = 0
        if lines and lines[0].strip() == "---":
            start = next((j + 1 for j in range(1, len(lines)) if lines[j].strip() == "---"), 0)
        lines[start:start] = ["", *block]
    else:
        lines[title + 1 : title + 1] = ["", *block[:-1]]
    return "\n".join(lines)


def add_log(text: str, day: str, line: str) -> str:
    """Uma linha no 📝 Log, embaixo do ### do dia (que nasce no fim do Log se faltar). A mesma
    linha no mesmo dia não se repete (editar o cronograma cinco vezes rende uma linha só)."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") and "Log" in l), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "## 📝 Log", "", f"### {day}", line, ""]
        return "\n".join(lines)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    head = next((i for i in range(start + 1, end) if lines[i].strip() == f"### {day}"), None)
    if head is None:
        at = end
        while at > start + 1 and not lines[at - 1].strip():
            at -= 1
        lines[at:at] = ["", f"### {day}", line]
        return "\n".join(lines)
    stop = next((i for i in range(head + 1, end) if lines[i].startswith("### ")), end)
    if any(lines[i].strip() == line.strip() for i in range(head + 1, stop)):
        return text
    at = stop
    while at > head + 1 and not lines[at - 1].strip():
        at -= 1
    # O "- " vazio do modelo vira a linha.
    if at > head + 1 and lines[at - 1].strip() == "-":
        lines[at - 1] = line
    else:
        lines.insert(at, line)
    return "\n".join(lines)


def _yaml(value: str) -> str:
    value = " ".join(str(value or "").split())
    return f'"{value.replace(chr(34), chr(39))}"' if value else ""


def _with_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def new_note(name: str, tema: str, start: date, end: date, goal: str, today: date) -> str:
    """A nota de um plano novo, no formato do T-projeto do vault, com a seção do cronograma."""
    goal_lines = [f"> {line}".rstrip() for line in goal.strip().split("\n")] if goal.strip() else ["> > [!todo] preencher"]
    lines = [
        "---",
        "tipo: projeto",
        "status: ativo",
        f"{PLAN_KEY}: {ACTIVE}",
        f"tema: {_yaml(tema)}",
        "area: ",
        f"inicio: {start.isoformat()}",
        f"prazo: {end.isoformat()}",
        "cliente: ",
        "diretorio: ",
        "workspace: ",
        f"atualizado: {today.isoformat()}",
        "tags: [estudo, plano-de-estudos]",
        "---",
        "",
        f"# 🎯 {name}",
        "",
        "> [!abstract] Objetivo",
        *goal_lines,
        "",
        "> [!info] Plano de estudos",
        f"> Criado pela {WHO} em {today.isoformat()}. A MÊTIS lê o cronograma abaixo (colunas Sem., Datas, Foco e Entrega) e guarda os conceitos em `conceitos/`.",
        "",
        SCHEDULE_HEADING,
        "",
        _row(STANDARD_HEADERS),
        "|---|---|---|---|",
        *(_row([str(w["numero"]), _dates_text(w, False), "", ""]) for w in skeleton(start, end)),
        "",
        "## ✅ Próximas ações",
        "",
        "## 🧩 Contexto e decisões",
        "",
        "## 🗂️ Notas do projeto",
        "",
        "<!-- notas:inicio (gerado por brain.py, não editar à mão) -->",
        "*Nenhuma nota ainda: cada decisão, incidente, entrega ou aprendizado registrado vira nota nesta pasta.*",
        "<!-- notas:fim -->",
        "",
        "## 📎 Recursos",
        "",
        "- ",
        "",
        "## 📝 Log",
        "",
        f"### {today.isoformat()}",
        f"- Plano de estudos criado pela {WHO}.",
        "",
    ]
    return "\n".join(lines)


# --- os planos ---------------------------------------------------------------------------


class StudyPlans:
    def __init__(
        self,
        vault: Vault,
        study_map: StudyMap,
        get_focus: Callable[[], str],
        set_focus: Callable[[str], None],
        versions: Path | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self.vault = vault
        self.study_map = study_map
        self._get_focus = get_focus
        self._set_focus = set_focus
        self.versions = versions
        self._today = today or (lambda: study_map._today())
        self._lock = threading.RLock()

    # leitura

    def _adopt(self) -> None:
        """O plano de antes da v1.4.0 (o projeto do ajuste, sem a chave) vira um plano ativo."""
        name = str(self._get_focus() or "").strip()
        if not name or not self.vault.available:
            return
        try:
            note = self.vault.project(name)
        except VaultError:
            return
        if note.meta.get(PLAN_KEY, "").strip():
            return
        with self._lock:
            text = note.path.read_text(encoding="utf-8")
            if split_frontmatter(text)[0].get(PLAN_KEY, "").strip():
                return
            write_atomic(note.path, set_frontmatter(text, PLAN_KEY, ACTIVE))

    def _notes(self) -> list[ProjectNote]:
        if not self.vault.available:
            return []
        self._adopt()
        return [n for n in self.vault.projects() if n.meta.get(PLAN_KEY, "").strip() in (ACTIVE, INACTIVE)]

    def find(self, name: str) -> ProjectNote | None:
        """O plano pelo nome (sem diferença de maiúscula e acento), ativo ou inativo."""
        wanted = fold(name)
        if not wanted:
            return None
        return next((n for n in self._notes() if fold(n.name) == wanted), None)

    def _need(self, name: str) -> ProjectNote:
        note = self.find(name)
        if note is None:
            raise PlanError(f"plano de estudos não encontrado: {name}")
        return note

    def active_names(self) -> list[str]:
        return [n.name for n in self._notes() if n.meta.get(PLAN_KEY, "").strip() == ACTIVE]

    def focus(self) -> str | None:
        """O plano em foco, se ele existir e estiver ativo."""
        name = str(self._get_focus() or "").strip()
        note = self.find(name) if name else None
        return note.name if note is not None and note.meta.get(PLAN_KEY, "").strip() == ACTIVE else None

    def _info(self, note: ProjectNote, focus: str | None, detail: bool) -> dict:
        today = self._today()
        meta = note.meta
        text = note.path.read_text(encoding="utf-8")
        weeks = parse_plan(text, today)
        week = next((w for w in weeks if w["atual"]), None)
        info = {
            "nome": note.name,
            "caminho": self.vault.rel(note.path),
            "estado": meta.get(PLAN_KEY, "").strip(),
            "em_foco": note.name == focus,
            "tema": meta.get("tema", "").strip(),
            "inicio": meta.get("inicio", "").strip(),
            "fim": meta.get("prazo", "").strip(),
            "atualizado": meta.get("atualizado", "").strip(),
            "semanas": len(weeks),
            "semanas_com_foco": sum(1 for w in weeks if w["foco"]),
            "semana_atual": {k: week[k] for k in ("numero", "inicio", "fim", "foco", "entrega")} if week else None,
        }
        if detail:
            concepts = self.study_map.bound(note.name).concepts()
            info["objetivo"] = goal_of(split_frontmatter(text)[1])
            info["conceitos"] = len(concepts)
            info["vencidos"] = sum(1 for c in concepts if c.vencido)
        return info

    def list(self, detail: bool = True) -> list[dict]:
        """Os planos, os ativos primeiro (o em foco na frente), depois os inativos, por nome."""
        notes = self._notes()
        focus = self.focus()
        items = [self._info(n, focus, detail) for n in notes]
        items.sort(key=lambda p: (p["estado"] != ACTIVE, not p["em_foco"], fold(p["nome"])))
        return items

    def get(self, name: str) -> dict:
        note = self._need(name)
        info = self._info(note, self.focus(), True)
        today = self._today()
        weeks = parse_plan(note.path.read_text(encoding="utf-8"), today)
        return {**info, "cronograma": weeks, "hoje": today.isoformat(), "semana_atual_numero": current_week(weeks, today)}

    # escrita

    def _log(self, text: str, line: str) -> str:
        return add_log(text, self._today().isoformat(), line)

    def _touch(self, text: str) -> str:
        return set_frontmatter(text, "atualizado", self._today().isoformat())

    def _keep_version(self, note: ProjectNote, text: str) -> None:
        if self.versions is None:
            return
        try:
            folder = self.versions / note.name
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            path = folder / f"{stamp}-{time.time_ns() % 1_000_000:06d}.md"
            path.write_text(text, encoding="utf-8")
            for old in sorted(folder.glob("*.md"))[:-KEEP_VERSIONS]:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # a cópia é seguro extra; não impede a gravação

    def _refocus(self, leaving: str) -> None:
        """Saiu o plano em foco: o foco vai para o próximo ativo (se houver)."""
        if fold(str(self._get_focus() or "")) != fold(leaving):
            return
        rest = [n for n in self.active_names() if fold(n) != fold(leaving)]
        if rest:
            self._set_focus(min(rest, key=fold))

    def set_focus(self, name: str) -> str:
        note = self._need(name)
        if note.meta.get(PLAN_KEY, "").strip() != ACTIVE:
            raise PlanError(f"o plano «{note.name}» está desativado: ative antes de pôr em foco")
        self._set_focus(note.name)
        return note.name

    def create(self, name: str, tema: str = "", inicio: str = "", fim: str = "", objetivo: str = "") -> dict:
        title = clean_plan_name(name)
        start = parse_day(inicio, "início do plano")
        end = parse_day(fim, "fim do plano")
        check_period(start, end)
        tema = clean_text(tema, 160)
        goal = "\n".join(" ".join(line.split()) for line in str(objetivo or "").strip().split("\n"))[:GOAL_MAX]
        if not self.vault.available:
            raise PlanError("o Brain não está disponível")
        with self._lock:
            folder = self.vault.root / PROJECTS_DIR / title
            if folder.exists():
                raise PlanError(f"já existe um projeto «{title}» no Brain (escolha outro nome)")
            wanted = fold(title)
            same = next((p for p in iter_notes(self.vault.root) if fold(p.stem) == wanted), None)
            if same is not None:
                raise PlanError(f"já existe uma nota «{same.stem}» no Brain ({self.vault.rel(same)}): o título é o identificador, escolha outro nome")
            folder.mkdir(parents=True)
            write_atomic(folder / f"{title}.md", new_note(title, tema, start, end, goal, self._today()))
            if self.focus() is None:
                self._set_focus(title)
        return self.get(title)

    def update(self, name: str, *, tema: str | None = None, inicio: str | None = None, fim: str | None = None, objetivo: str | None = None) -> dict:
        with self._lock:
            note = self._need(name)
            text = note.path.read_text(encoding="utf-8")
            meta = note.meta
            today = self._today()
            changed = []
            start_raw = meta.get("inicio", "").strip() if inicio is None else inicio
            end_raw = meta.get("prazo", "").strip() if fim is None else fim
            if inicio is not None or fim is not None:
                start = parse_day(start_raw, "início do plano")
                end = parse_day(end_raw, "fim do plano")
                check_period(start, end)
                before = parse_plan(text, today)
                if start.isoformat() != meta.get("inicio", "").strip() or end.isoformat() != meta.get("prazo", "").strip():
                    text = set_frontmatter(text, "inicio", start.isoformat())
                    text = set_frontmatter(text, "prazo", end.isoformat())
                    # O ano das datas curtas da tabela vem do início: se a leitura mudar, a tabela passa à data cheia.
                    if [(w["inicio"], w["fim"]) for w in parse_plan(text, today)] != [(w["inicio"], w["fim"]) for w in before]:
                        text = render_schedule(text, before, today, full=True)
                    changed.append("período")
            if tema is not None and clean_text(tema, 160) != meta.get("tema", "").strip():
                text = set_frontmatter(text, "tema", _yaml(clean_text(tema, 160)))
                changed.append("tema")
            if objetivo is not None:
                goal = "\n".join(" ".join(line.split()) for line in str(objetivo).strip().split("\n"))[:GOAL_MAX]
                if goal != goal_of(split_frontmatter(text)[1]):
                    text = set_goal(text, goal)
                    changed.append("objetivo")
            if changed:
                text = self._log(self._touch(text), f"- Plano de estudos editado pela {WHO} ({', '.join(changed)}).")
                write_atomic(note.path, _with_newline(text))
        return self.get(note.name)

    def set_state(self, name: str, active: bool) -> dict:
        with self._lock:
            note = self._need(name)
            state = ACTIVE if active else INACTIVE
            if note.meta.get(PLAN_KEY, "").strip() != state:
                text = note.path.read_text(encoding="utf-8")
                text = set_frontmatter(text, PLAN_KEY, state)
                verb = "reativado" if active else "desativado"
                text = self._log(self._touch(text), f"- Plano de estudos {verb} pela {WHO}.")
                write_atomic(note.path, _with_newline(text))
            if active:
                if self.focus() is None:
                    self._set_focus(note.name)
            else:
                self._refocus(note.name)
        return self.get(note.name)

    def write_schedule(self, name: str, weeks: object, quem: str = "Pedro") -> dict:
        clean = clean_weeks(weeks)
        with self._lock:
            note = self._need(name)
            text = note.path.read_text(encoding="utf-8")
            new = render_schedule(text, clean, self._today())
            if new != text:
                self._keep_version(note, text)
                who = " ".join(str(quem or "Pedro").split())[:60] or "Pedro"
                author = f"pela {WHO}" if who == "Pedro" else f"por {who}, o agente de estudo"
                new = self._log(self._touch(new), f"- Cronograma do plano atualizado {author} ({len(clean)} semanas).")
                write_atomic(note.path, _with_newline(new))
        return self.get(note.name)

    def archive(self, name: str) -> dict:
        """Excluir: a pasta do plano vai inteira para 04-ARQUIVO (o vault não apaga nota)."""
        with self._lock:
            note = self._need(name)
            source = note.path.parent
            if source.parent != self.vault.root / PROJECTS_DIR:
                raise PlanError("o plano não está numa pasta própria em 01-PROJETOS")
            today = self._today().isoformat()
            base = self.vault.root / ARCHIVE_DIR
            base.mkdir(parents=True, exist_ok=True)
            target = base / note.name
            n = 1
            while target.exists():
                target = base / (f"{note.name} (arquivado {today})" + (f" {n}" if n > 1 else ""))
                n += 1
            files = [p for p in source.rglob("*.md") if not p.name.startswith(".")]
            concepts = [p for p in (source / "conceitos").glob("*.md")] if (source / "conceitos").is_dir() else []
            shutil.move(str(source), str(target))
            moved = target / note.path.name
            text = moved.read_text(encoding="utf-8")
            for key, value in ((PLAN_KEY, DELETED), ("status", "arquivado"), ("arquivado", today), ("atualizado", today)):
                text = set_frontmatter(text, key, value)
            lines = text.split("\n")
            at = 0
            if lines and lines[0].strip() == "---":
                at = next((j + 1 for j in range(1, len(lines)) if lines[j].strip() == "---"), 0)
            notice = [
                "",
                f"> [!warning] Arquivado em {today}",
                f"> Plano de estudos excluído pela {WHO}. A pasta saiu de {PROJECTS_DIR} e ficou aqui, com os conceitos, porque o vault não apaga nota. Para voltar, mova a pasta de volta para {PROJECTS_DIR} e troque `{PLAN_KEY}` para `{INACTIVE}`.",
            ]
            lines[at:at] = notice
            text = self._log("\n".join(lines), f"- Plano de estudos excluído pela {WHO}: a pasta foi para {ARCHIVE_DIR}.")
            write_atomic(moved, _with_newline(text))
            self._refocus(note.name)
        return {
            "nome": note.name,
            "de": self.vault.rel(source),
            "para": self.vault.rel(target),
            "notas": len(files),
            "conceitos": len(concepts),
        }


def describe(plan: dict) -> str:
    """Uma linha do plano para o agente: nome, estado, tema, período e a semana de hoje."""
    parts = [f"«{plan['nome']}»", plan["estado"] + (" · em foco" if plan.get("em_foco") else "")]
    if plan.get("tema"):
        parts.append(f"tema {plan['tema']}")
    if plan.get("inicio") or plan.get("fim"):
        parts.append(f"{plan.get('inicio') or '?'} a {plan.get('fim') or '?'}")
    week = plan.get("semana_atual")
    parts.append(f"semana {week['numero']}: {week['foco'] or 'sem foco escrito'}" if week else "fora do cronograma hoje")
    return " · ".join(parts)

