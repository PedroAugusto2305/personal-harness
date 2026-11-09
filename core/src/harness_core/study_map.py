"""Estudo completo (v0.9.8): o mapa do que o Pedro sabe, o plano e as sessões com o Sócrates.

Decisão do Pedro: o mapa fica na PASTA DO PROJETO de estudo, uma nota por conceito em
`01-PROJETOS/<Projeto>/conceitos/<Conceito>.md` (nunca em 05-NOTAS/permanentes: nota
permanente só nasce pela destilação dele, com as palavras dele). Cada conceito guarda no
frontmatter o domínio (0 a 4), a confiança média, a calibração e a próxima revisão; no
corpo, o resumo, os [[conceitos relacionados]] (o grafo do Brain mostra a rede) e uma linha
por resposta registrada.

Revisão espaçada simples: acertou com confiança ≥ 4 → intervalo × 2,5; acertou com menos →
× 1,5; errou → 1 dia; primeiro registro → 1 dia; teto de 60 dias. O domínio sobe 1 com 3
acertos seguidos e desce 1 com 2 erros seguidos (entre 1 e 4; 0 só antes do primeiro
registro). A sequência corrente fica em `sequencia` (positiva = acertos, negativa = erros).

O plano é a primeira tabela da nota do projeto com as colunas da semana e das datas
("Sem.", "Datas", "Foco", "Entrega…"), como o cronograma do AI Engineer 2027.

Toda escrita relê a nota e troca só o frontmatter e as seções dela: o Pedro pode editar no
Obsidian ao mesmo tempo.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from .vault import Vault, VaultError, add_to_section, set_frontmatter, split_frontmatter, wikilinks, write_atomic

DEFAULT_PROJECT = "AI Engineer 2027"
CONCEPTS_DIR = "conceitos"
DOMAIN_LABEL = {0: "não vi", 1: "ouvi falar", 2: "entendo com ajuda", 3: "faço sozinho", 4: "consigo ensinar"}
MAX_INTERVAL = 60
BAD_TITLE = re.compile(r'[\[\]#^|/\\:*?"<>]')
SESSION_TYPES = ("medir", "aprender", "praticar", "revisar")
TUTOR = "socrates"


class StudyError(VaultError):
    pass


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(c)).strip()


def clean_title(name: str) -> str:
    title = " ".join(BAD_TITLE.sub(" ", str(name or "")).split()).strip(" .")
    if not title:
        raise StudyError("o conceito precisa de um nome")
    if len(title) > 120:
        raise StudyError("nome de conceito longo demais (até 120 caracteres)")
    return title


def _num(value: str | None, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _int(value: str | None, default: int = 0) -> int:
    return int(round(_num(value, default)))


def _half_up(value: float) -> int:
    return int(value + 0.5)


@dataclass
class Concept:
    titulo: str
    caminho: str
    dominio: int = 0
    confianca_media: float = 0.0
    calibracao: float = 0.0
    proxima_revisao: str = ""
    intervalo_dias: int = 0
    acertos: int = 0
    erros: int = 0
    sequencia: int = 0
    semana: int | None = None
    criado: str = ""
    atualizado: str = ""
    resumo: str = ""
    relacionados: list[str] = field(default_factory=list)
    vencido: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _sections(body: str) -> dict[str, str]:
    """Texto de cada seção `## …` do corpo (chave = título dobrado, sem emoji)."""
    out: dict[str, str] = {}
    current = None
    buffer: list[str] = []
    for line in body.split("\n"):
        if line.startswith("## "):
            if current is not None:
                out[current] = "\n".join(buffer)
            current = fold(re.sub(r"^[^\w]*", "", line[3:]))
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        out[current] = "\n".join(buffer)
    return out


def _summary(body: str) -> str:
    """O texto entre o título (# …) e a primeira seção."""
    lines = body.split("\n")
    out = []
    started = False
    for line in lines:
        if line.startswith("# "):
            started = True
            continue
        if line.startswith("## "):
            break
        if started:
            out.append(line)
    return "\n".join(out).strip()


def parse_concept(path: Path, rel: str, today: date) -> Concept:
    text = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    sections = _sections(body)
    related = wikilinks(sections.get("relacionados", ""))
    week = meta.get("semana", "").strip()
    due = meta.get("proxima_revisao", "").strip()
    concept = Concept(
        titulo=path.stem,
        caminho=rel,
        dominio=max(0, min(4, _int(meta.get("dominio"), 0))),
        confianca_media=round(_num(meta.get("confianca_media")), 2),
        calibracao=round(_num(meta.get("calibracao")), 3),
        proxima_revisao=due,
        intervalo_dias=_int(meta.get("intervalo_dias")),
        acertos=_int(meta.get("acertos")),
        erros=_int(meta.get("erros")),
        sequencia=_int(meta.get("sequencia")),
        semana=_int(week) if re.fullmatch(r"\d+", week) else None,
        criado=meta.get("criado", ""),
        atualizado=meta.get("atualizado", ""),
        resumo=_summary(body),
        relacionados=related,
    )
    concept.vencido = bool(due) and due <= today.isoformat()
    return concept


def schedule(concept: Concept, correct: bool, confidence: int, today: date) -> Concept:
    """A conta da revisão espaçada, do domínio e da calibração para uma resposta."""
    confidence = max(1, min(5, int(confidence)))
    answered = concept.acertos + concept.erros
    if answered == 0:
        interval = 1
    elif not correct:
        interval = 1
    else:
        factor = 2.5 if confidence >= 4 else 1.5
        interval = _half_up(max(1, concept.intervalo_dias) * factor)
    interval = max(1, min(MAX_INTERVAL, interval))

    level = max(1, concept.dominio)
    streak = concept.sequencia
    if correct:
        streak = streak + 1 if streak > 0 else 1
        if streak >= 3:
            level = min(4, level + 1)
            streak = 0
    else:
        streak = streak - 1 if streak < 0 else -1
        if streak <= -2:
            level = max(1, level - 1)
            streak = 0

    normalized = (confidence - 1) / 4
    diff = abs(normalized - (1.0 if correct else 0.0))
    concept.calibracao = round((concept.calibracao * answered + diff) / (answered + 1), 3)
    concept.confianca_media = round((concept.confianca_media * answered + confidence) / (answered + 1), 2)
    concept.acertos += 1 if correct else 0
    concept.erros += 0 if correct else 1
    concept.dominio = level
    concept.sequencia = streak
    concept.intervalo_dias = interval
    concept.proxima_revisao = (today + timedelta(days=interval)).isoformat()
    concept.atualizado = today.isoformat()
    concept.vencido = False
    return concept


# --- plano (a tabela do cronograma) ------------------------------------------------------

_DATE_FULL = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DATE_SHORT = re.compile(r"(?<!\d)(\d{1,2})[-/](\d{1,2})(?![-/]?\d)")


def _cells(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [c.strip() for c in raw.split("|")]


def _plain(cell: str) -> str:
    """Sem negrito, itálico e [[links]] (o texto do link fica)."""
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), cell)
    return re.sub(r"[*_`]", "", text).strip()


def _column(headers: list[str], *starts: str) -> int | None:
    for i, header in enumerate(headers):
        key = fold(_plain(header)).rstrip(".")
        if any(key.startswith(s) for s in starts):
            return i
    return None


def _dates(text: str, year: int, last_month: int) -> tuple[date, date, int, int] | None:
    """('10-05 a 10-10' ou '2026-10-05 a 2026-10-10', ano corrente, último mês visto) →
    (início, fim, ano, mês) — o ano vira quando o mês volta."""
    full = _DATE_FULL.findall(text)
    if len(full) >= 2:
        start = date(int(full[0][0]), int(full[0][1]), int(full[0][2]))
        end = date(int(full[1][0]), int(full[1][1]), int(full[1][2]))
        return start, end, end.year, end.month
    if len(full) == 1:
        start = date(int(full[0][0]), int(full[0][1]), int(full[0][2]))
        return start, start, start.year, start.month
    short = _DATE_SHORT.findall(_DATE_FULL.sub(" ", text))
    if not short:
        return None
    (m1, d1), (m2, d2) = short[0], short[-1]
    m1, d1, m2, d2 = int(m1), int(d1), int(m2), int(d2)
    start_year = year + 1 if last_month and m1 < last_month else year
    end_year = start_year + 1 if m2 < m1 else start_year
    try:
        start = date(start_year, m1, d1)
        end = date(end_year, m2, d2)
    except ValueError:
        return None
    return start, end, end.year, end.month


def parse_plan(text: str, today: date) -> list[dict]:
    """As semanas da primeira tabela com as colunas da semana e das datas."""
    meta, body = split_frontmatter(text)
    match = re.match(r"(\d{4})-\d{2}-\d{2}", meta.get("inicio", ""))
    year = int(match.group(1)) if match else today.year
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            headers = _cells(line)
            col_week = _column(headers, "sem")
            col_dates = _column(headers, "data")
            if col_week is not None and col_dates is not None:
                col_focus = _column(headers, "foco", "tema")
                col_deliver = _column(headers, "entrega", "meta")
                weeks: list[dict] = []
                last_month = 0
                j = i + 2
                while j < len(lines) and lines[j].strip().startswith("|"):
                    cells = _cells(lines[j])
                    j += 1
                    if len(cells) <= max(col_week, col_dates):
                        continue
                    number = re.sub(r"\D", "", _plain(cells[col_week]))
                    parsed = _dates(_plain(cells[col_dates]), year, last_month)
                    if not number or parsed is None:
                        continue
                    start, end, year, last_month = parsed
                    weeks.append({
                        "numero": int(number),
                        "inicio": start.isoformat(),
                        "fim": end.isoformat(),
                        "foco": _plain(cells[col_focus]) if col_focus is not None and col_focus < len(cells) else "",
                        "entrega": _plain(cells[col_deliver]) if col_deliver is not None and col_deliver < len(cells) else "",
                        "atual": False,
                    })  # fmt: skip
                current = current_week(weeks, today)
                for week in weeks:
                    week["atual"] = week["numero"] == current
                return weeks
            i += 2
            continue
        i += 1
    return []


def current_week(weeks: list[dict], today: date) -> int | None:
    """A semana de hoje; o dia entre duas semanas (o domingo) fica com a anterior."""
    iso = today.isoformat()
    for k, week in enumerate(weeks):
        following = weeks[k + 1]["inicio"] if k + 1 < len(weeks) else None
        if week["inicio"] <= iso and (iso <= week["fim"] or (following is not None and iso < following)):
            return week["numero"]
    return None


# --- o mapa no vault ---------------------------------------------------------------------


class StudyMap:
    def __init__(self, vault: Vault, project: Callable[[], str] = lambda: DEFAULT_PROJECT, today: Callable[[], date] | None = None) -> None:
        self.vault = vault
        self._project = project
        self._today = today or (lambda: datetime.now().astimezone().date())
        self._lock = threading.Lock()

    # projeto e pastas

    @property
    def project_name(self) -> str:
        return str(self._project() or DEFAULT_PROJECT)

    def project_note(self):
        try:
            return self.vault.project(self.project_name)
        except VaultError as exc:
            raise StudyError(f"o projeto de estudo «{self.project_name}» não está no Brain (Ajustes: estudo_projeto)") from exc

    def folder(self) -> Path:
        return self.project_note().path.parent / CONCEPTS_DIR

    def _path(self, title: str) -> Path:
        return self.folder() / f"{title}.md"

    def _find(self, name: str) -> Path | None:
        folder = self.folder()
        if not folder.is_dir():
            return None
        wanted = fold(name)
        for path in sorted(folder.glob("*.md")):
            if fold(path.stem) == wanted:
                return path
        return None

    # leitura

    def concepts(self) -> list[Concept]:
        folder = self.folder()
        if not folder.is_dir():
            return []
        today = self._today()
        out = []
        for path in sorted(folder.glob("*.md"), key=lambda p: fold(p.stem)):
            if path.name.startswith("."):
                continue
            try:
                out.append(parse_concept(path, self.vault.rel(path), today))
            except (OSError, UnicodeDecodeError):
                continue
        return out

    def get(self, name: str) -> Concept:
        path = self._find(name)
        if path is None:
            raise StudyError(f"conceito não encontrado: {name}")
        return parse_concept(path, self.vault.rel(path), self._today())

    def map(self) -> dict:
        concepts = self.concepts()
        answered = [c for c in concepts if c.acertos + c.erros]
        return {
            "projeto": self.project_name,
            "conceitos": [
                {k: v for k, v in c.to_dict().items() if k not in ("sequencia", "intervalo_dias", "criado", "atualizado", "resumo")}
                for c in concepts
            ],
            "resumo": {
                "total": len(concepts),
                "por_dominio": {str(level): sum(1 for c in concepts if c.dominio == level) for level in range(5)},
                "vencidos": sum(1 for c in concepts if c.vencido),
                "calibracao_media": round(sum(c.calibracao for c in answered) / len(answered), 3) if answered else None,
            },
        }

    def plan(self) -> dict:
        note = self.project_note()
        today = self._today()
        weeks = parse_plan(note.path.read_text(encoding="utf-8"), today)
        return {
            "projeto": self.project_name,
            "semanas": weeks,
            "hoje": today.isoformat(),
            "semana_atual": current_week(weeks, today),
        }

    def current(self) -> dict | None:
        """{numero, foco} da semana de hoje, ou None (sem projeto ou sem plano)."""
        try:
            plan = self.plan()
        except (StudyError, OSError):
            return None
        week = next((w for w in plan["semanas"] if w["atual"]), None)
        return {"numero": week["numero"], "foco": week["foco"]} if week else None

    def due_count(self) -> int:
        try:
            return sum(1 for c in self.concepts() if c.vencido)
        except (StudyError, OSError):
            return 0

    # escrita

    def _render_new(self, title: str, summary: str, related: list[str], week: int | None) -> str:
        today = self._today().isoformat()
        lines = [
            "---",
            "tipo: conceito",
            f'projeto: "[[{self.project_name}]]"',
            "dominio: 0",
            "proxima_revisao: ",
            "intervalo_dias: 0",
            "acertos: 0",
            "erros: 0",
            "sequencia: 0",
            "confianca_media: 0",
            "calibracao: 0",
            f"semana: {week if week is not None else ''}",
            f"criado: {today}",
            f"atualizado: {today}",
            "tags: [conceito, estudo]",
            "---",
            "",
            f"# 🧠 {title}",
            "",
            summary.strip() or f"> [!todo] Resumo do conceito em poucas linhas, com as palavras do Pedro.",
            "",
            "## Relacionados",
            "",
            *([f"- [[{r}]]" for r in related] or ["-"]),
            "",
            "## Histórico",
            "",
            "-",
            "",
        ]
        return "\n".join(lines)

    def _link(self, path: Path, other: str) -> None:
        """Acrescenta [[other]] em Relacionados, se ainda não estiver lá."""
        text = path.read_text(encoding="utf-8")
        _meta, body = split_frontmatter(text)
        current = {fold(t) for t in wikilinks(_sections(body).get("relacionados", ""))}
        if fold(other) in current or fold(other) == fold(path.stem):
            return
        write_atomic(path, add_to_section(text, "Relacionados", f"- [[{other}]]", ("## Histórico",)))

    def create(self, name: str, summary: str = "", related: list[str] | None = None, week: int | None = None, *, exist_ok: bool = False) -> Concept:
        title = clean_title(name)
        related = [clean_title(r) for r in (related or []) if str(r).strip()]
        with self._lock:
            existing = self._find(title)
            if existing is not None:
                if exist_ok:
                    return parse_concept(existing, self.vault.rel(existing), self._today())
                raise StudyError(f"o conceito «{existing.stem}» já existe")
            folder = self.folder()
            folder.mkdir(parents=True, exist_ok=True)
            path = self._path(title)
            write_atomic(path, self._render_new(title, summary, related, week))
            # A ligação vale dos dois lados quando o outro conceito já existe.
            for other in related:
                other_path = self._find(other)
                if other_path is not None:
                    self._link(other_path, title)
        return self.get(title)

    def _write_meta(self, path: Path, concept: Concept) -> None:
        text = path.read_text(encoding="utf-8")
        values = {
            "dominio": str(concept.dominio),
            "proxima_revisao": concept.proxima_revisao,
            "intervalo_dias": str(concept.intervalo_dias),
            "acertos": str(concept.acertos),
            "erros": str(concept.erros),
            "sequencia": str(concept.sequencia),
            "confianca_media": f"{concept.confianca_media:g}",
            "calibracao": f"{concept.calibracao:g}",
            "semana": "" if concept.semana is None else str(concept.semana),
            "atualizado": concept.atualizado or self._today().isoformat(),
        }
        for key, value in values.items():
            text = set_frontmatter(text, key, value)
        write_atomic(path, text)

    def update(self, name: str, dominio: int | None = None, semana: int | None | str = "keep") -> Concept:
        with self._lock:
            path = self._find(name)
            if path is None:
                raise StudyError(f"conceito não encontrado: {name}")
            concept = parse_concept(path, self.vault.rel(path), self._today())
            if dominio is not None:
                if not 0 <= int(dominio) <= 4:
                    raise StudyError("domínio vai de 0 (não vi) a 4 (consigo ensinar)")
                concept.dominio = int(dominio)
            if semana != "keep":
                concept.semana = None if semana in (None, "") else int(semana)
            concept.atualizado = self._today().isoformat()
            self._write_meta(path, concept)
        return self.get(name)

    def record(self, name: str, correct: bool, confidence: int, note: str = "") -> Concept:
        """Uma resposta do Pedro: cria o conceito (domínio 1) se ainda não existir."""
        if not 1 <= int(confidence) <= 5:
            raise StudyError("a confiança vai de 1 a 5")
        title = clean_title(name)
        if self._find(title) is None:
            self.create(title, exist_ok=True)
        with self._lock:
            path = self._find(title)
            assert path is not None
            today = self._today()
            concept = parse_concept(path, self.vault.rel(path), today)
            schedule(concept, bool(correct), int(confidence), today)
            self._write_meta(path, concept)
            text = path.read_text(encoding="utf-8")
            line = f"- {today.isoformat()} · {'acertou' if correct else 'errou'} · confiança {int(confidence)}"
            clean_note = " ".join(str(note or "").split())[:200]
            if clean_note:
                line += f" · {clean_note}"
            write_atomic(path, add_to_section(text, "Histórico", line))
        return self.get(title)

    # sessões com o Sócrates

    def add_question(self, name: str, question: str, options: list[str], kind: str = "previsão") -> dict:
        """v0.9.9: a pergunta do Sócrates vira um bloco na nota do conceito (cria o conceito se
        faltar). A tela do Estudo mostra o bloco com as opções, a confiança e o raciocínio, e a
        resposta do Pedro volta ao terminal do Sócrates."""
        question = " ".join(str(question).split()).strip()
        opts = [" ".join(str(o).split()).strip() for o in options if str(o).strip()][:6]
        if not question:
            raise StudyError("a pergunta está vazia")
        if len(opts) < 2:
            raise StudyError("dê ao menos duas opções (a última pode ser 'Não sei')")
        concept = self.create(name, exist_ok=True)
        with self._lock:
            path = self.vault.root / concept.caminho
            text = path.read_text(encoding="utf-8")
            block = [f"> [!pergunta] Pergunta de {kind} · Sócrates", f"> {question}", *(f"> - [ ] {o}" for o in opts)]
            heading = "## Perguntas"
            if heading not in text:
                text = text.rstrip("\n") + f"\n\n{heading}\n"
            text = text.rstrip("\n") + "\n\n" + "\n".join(block) + "\n"
            write_atomic(path, text)
        return {"conceito": concept.titulo, "caminho": concept.caminho}

    def session_prompt(self, kind: str, concept: str | None = None) -> str:
        if kind not in SESSION_TYPES:
            raise StudyError(f"tipo de sessão é {', '.join(SESSION_TYPES)}")
        project = self.project_name
        week = self.current()
        week_text = f"semana {week['numero']} do cronograma (foco: {week['foco']})" if week else "a semana atual do cronograma (veja com estudo_plano)"
        record = (
            "Antes de explicar qualquer coisa, peça a minha previsão (o que eu acho que acontece ou a resposta) e a minha confiança de 1 a 5. "
            "Quando a pergunta tiver alternativas, escreva-a também na nota do conceito com a ferramenta estudo_pergunta (conceito, pergunta, opcoes; "
            "a última opção pode ser 'Não sei'): eu respondo pela tela do Estudo, com a confiança e o meu raciocínio, e a resposta chega aqui. "
            "Depois de cada resposta, registre com a ferramenta estudo_registrar (conceito, acertou, confianca, nota curta)."
        )
        if kind == "medir":
            return (
                f"Sessão de diagnóstico do estudo ({project}). Use estudo_plano e estudo_conceitos para ver a {week_text} e os conceitos que ainda não têm registro. "
                f"Faça uma pergunta por vez sobre esses conceitos para medir o que eu sei. {record} "
                "Conceito que aparecer e ainda não existir no mapa: crie com estudo_conceito_novo, ligando aos relacionados. No fim, um resumo curto do que eu sei e do que falta."
            )
        if kind == "aprender":
            target = concept or "o conceito mais fraco da semana (veja estudo_conceitos)"
            return (
                f"Sessão de aprender: {target} ({project}, {week_text}). Ensine com perguntas de previsão primeiro e explicação curta depois, um passo por vez. "
                f"{record} Ligue o conceito aos relacionados com estudo_conceito_novo quando surgir um novo. Pare quando eu acertar com confiança alta duas vezes seguidas."
            )
        if kind == "praticar":
            return (
                f"Sessão de prática ({project}, {week_text}). Proponha um exercício prático do foco da semana, feito aqui no repositório, do tamanho de 25 a 50 minutos. "
                "Eu faço; você só dá dicas quando eu pedir. No fim, corrija junto comigo e registre o resultado em cada conceito envolvido com estudo_registrar (com a minha confiança de 1 a 5 antes da correção)."
            )
        return (
            f"Sessão de revisão ({project}). Pegue só os conceitos vencidos hoje (estudo_conceitos com vencidos verdadeiro). "
            f"Uma pergunta por conceito, sem explicar antes. {record} No fim, diga quantos foram e quando volta cada um."
        )

    def session_cwd(self, kind: str) -> str | None:
        """Praticar roda no repositório do projeto de estudo (o `diretorio` da nota), se houver."""
        if kind != "praticar":
            return None
        raw = self.project_note().meta.get("diretorio", "").strip()
        if not raw:
            return None
        folder = Path(raw).expanduser()
        return str(folder) if folder.is_dir() else None
