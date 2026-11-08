"""Captura rápida: o que o Pedro escreve na caixinha do ⌥Espaço vira ação na hora.

- "me lembra de pagar o boleto sexta às 9h" → lembrete no Slack (bot na DM), sem gastar o plano;
- "tarefa revisar o PR no Personal Harness" → linha nas Próximas ações do projeto;
- "tarefa comprar café" / "anota ideia de post" → nas Capturas do dia do Brain (06-DIARIO);
- o resto vai para o Hermes, o concierge, num terminal: ele decide (ClickUp, Brain, Slack).

A hora do lembrete é o maior trecho do fim da frase feito só de palavras de tempo
("sexta às 9h", "amanhã 14:30", "em 20 min"), para "boleto" nunca virar parte da data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .brain_index import fold
from .when import WhenError, parse_when

_REMIND = re.compile(r"^(?:me\s+)?lembr(?:a|e|ar|ete)(?:\s*[:,-])?(?:\s+(?:me|de|que|pra|para))*\s+(.+)$", re.I)
_TASK = re.compile(r"^(?:anota(?:r)?\s+(?:a\s+)?tarefa|tarefa|todo|to-do|fazer)\s*[:\-]?\s+(.+)$", re.I)
_NOTE = re.compile(r"^(?:anota(?:r)?|nota|captura)\s*[:\-]?\s+(?:que\s+)?(.+)$", re.I)
_TIME_WORD = re.compile(
    r"^(hoje|amanha|depois|de|as|a|em|daqui|dentro|no|na|dia|min|mins|minuto|minutos|h|hora|horas|dias?|"
    r"segunda|terca|quarta|quinta|sexta|sabado|domingo|seg|ter|qua|qui|sex|sab|dom|feira|"
    r"\d{1,2}(h\d{0,2}|:\d{2})?|\d{1,2}/\d{1,2}(/\d{2,4})?|\d+(min|m|h|d)?|\+\d+\w*)$"
)
_TRAILING = {"as", "às", "a", "na", "no", "em", "para", "pra", "de", "do", "da", "dia", ","}


@dataclass
class Capture:
    kind: str  # lembrete | tarefa | nota | concierge
    text: str
    when: datetime | None = None
    project: str = ""


def split_when(sentence: str, now: datetime | None = None) -> tuple[str, datetime] | None:
    """('pagar o boleto', sexta 9h) a partir de 'pagar o boleto sexta às 9h'."""
    words = sentence.strip().rstrip(".!").split()
    for start in range(len(words)):
        tail = words[start:]
        if not tail or not all(_TIME_WORD.match(fold(w).strip(",.")) for w in tail):
            continue
        try:
            when = parse_when(" ".join(tail), now)
        except WhenError:
            continue
        head = words[:start]
        while head and fold(head[-1]).strip(",") in _TRAILING:
            head.pop()
        text = " ".join(head).strip(" ,:-")
        if text:
            return text, when
    return None


def interpret(raw: str, projects: list[str], now: datetime | None = None) -> Capture:
    text = " ".join(raw.split())
    if not text:
        raise ValueError("a captura está vazia")
    remind = _REMIND.match(text)
    if remind:
        found = split_when(remind.group(1), now)
        if found:
            return Capture("lembrete", found[0], found[1])
        return Capture("concierge", text)  # lembrete sem hora: o Hermes pergunta quando
    task = _TASK.match(text)
    if task:
        body = task.group(1).strip()
        # "… no Personal Harness" / "… em Plataforma Funis" no fim: tarefa do projeto
        by_fold = {fold(p): p for p in projects}
        match = re.search(r"\s+(?:no|na|em|pro|pra|para\s+o|para\s+a)\s+(?:projeto\s+)?(.+)$", body, re.I)
        if match and fold(match.group(1).strip(" .")) in by_fold:
            return Capture("tarefa", body[: match.start()].strip(), project=by_fold[fold(match.group(1).strip(" ."))])
        return Capture("tarefa", body)
    note = _NOTE.match(text)
    if note:
        return Capture("nota", note.group(1).strip())
    return Capture("concierge", text)
