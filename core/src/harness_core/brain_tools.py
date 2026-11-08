"""Ferramentas do Brain para agentes: as mesmas na central de MCP da MÊTIS e no MCP de fora.

Cada função devolve o texto para o agente e as notas que ele viu (a central usa essa lista
para o mini-mapa da sessão).
"""

from __future__ import annotations

from typing import Callable

from .brain_index import TYPE_ICON, BrainIndex

Notes = list[dict]

DESCRIPTIONS = {
    "brain_buscar": "Busca por palavra nas notas do Brain do Pedro (decisões, incidentes, aprendizados, entregas, projetos, notas).",
    "brain_ler": "Lê uma nota do Brain pelo título, com quem a cita.",
    "brain_precedentes": (
        "Decisões, incidentes, aprendizados e entregas de OUTROS projetos parecidos com o momento deste projeto "
        "(ou com o texto dado), achados por significado e por palavra."
    ),
    "brain_conflitos": (
        "Chame ANTES de registrar ou tomar uma decisão técnica relevante, com a decisão numa frase. Devolve decisões "
        "parecidas do MESMO projeto (possível repetição ou contradição: diga ao Pedro se contradiz) e registros parecidos "
        "de OUTROS projetos (precedente: leia com brain_ler os que parecem valer)."
    ),
    "brain_sugestoes": (
        "Sugestões de precedente esperando o Pedro neste projeto: registros novos de outros projetos que o juiz da MÊTIS "
        "achou que valem aqui. O Pedro aceita ou recusa na MÊTIS (aceitar vira decisão do projeto)."
    ),
}


def _where(item: dict) -> str:
    return " · ".join(x for x in (item.get("tipo"), item.get("projeto"), item.get("status"), item.get("data")) if x)


def _short(text: str | None, size: int = 240) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:size] + ("…" if len(text) > size else "")


class BrainTools:
    def __init__(self, brain: BrainIndex, pending: Callable[[str], list[dict]] | None = None) -> None:
        self.brain = brain
        self.pending = pending  # projeto → sugestões pendentes

    def buscar(self, termos: str, tipo: str = "", projeto: str = "") -> tuple[str, Notes]:
        hits = self.brain.search(termos, [t for t in tipo.split(",") if t] or None, projeto or None, 12)
        if not hits:
            return "Nada encontrado no Brain (a busca é por palavra, sem acento). Tente brain_precedentes com uma frase.", []
        text = "\n".join(f"- {h['title']} ({_where(h)})" + (f"\n  {_short(h.get('resumo'))}" if h.get("resumo") else "") for h in hits)
        return text, hits

    def ler(self, titulo: str) -> tuple[str, Notes]:
        note = self.brain.note(title=titulo)
        cited = "; ".join(b["title"] for b in note["backlinks"][:15])
        text = f"# {note['title']} ({note['path']})\n{note['body'].strip()}" + (f"\n\nCitada por: {cited}" if cited else "")
        return text, [note]

    def precedentes(self, projeto: str, termos: str = "", wait: float = 20.0) -> tuple[str, Notes]:
        context = termos or (self.brain.project_context(projeto) if projeto else "")
        found = self.brain.precedents(projeto or None, context, 8, free_text=bool(termos), wait=wait)
        if not found:
            return "Nenhum registro de outro projeto bateu.", []
        lines = []
        for h in found:
            how = "+".join(h.get("via", []))
            lines.append(f"- {TYPE_ICON.get(h['tipo'], '·')} {h['title']} ({h['projeto']}{' · ' + h['status'] if h['status'] else ''}; por {how}): {_short(h['resumo'])}")
        return "\n".join(lines), found

    def conflitos(self, decisao: str, projeto: str, wait: float = 20.0) -> tuple[str, Notes]:
        found = self.brain.conflicts(decisao, projeto or None, wait=wait)
        how = "por significado" if found["via"] == "significado" else "só por palavra (o modelo de significado não está disponível agora)"
        lines = [f"Busca {how}."]
        if projeto:
            lines.append(f"Decisões parecidas em {projeto} (repetição ou contradição?):")
            lines += [f"- ⚖️ {h['title']} ({h.get('status') or 'aceita'}, {h.get('data') or '?'}): {_short(h['resumo'])}" for h in found["same"]] or ["- nenhuma"]
        lines.append("Registros parecidos em outros projetos (precedente?):")
        lines += [f"- {TYPE_ICON.get(h['tipo'], '·')} {h['title']} ({h['projeto']}): {_short(h['resumo'])}" for h in found["other"]] or ["- nenhum"]
        lines.append("Se algo contradiz, diga ao Pedro antes de seguir; se a decisão substitui uma anterior, registre como substituição.")
        return "\n".join(lines), [*found["same"], *found["other"]]

    def sugestoes(self, projeto: str) -> tuple[str, Notes]:
        items = self.pending(projeto) if self.pending and projeto else []
        if not items:
            return f"Nenhuma sugestão pendente em {projeto or 'nenhum projeto'}.", []
        lines = [f"Sugestões pendentes em {projeto} (o Pedro aceita ou recusa na MÊTIS):"]
        for item in items:
            lines.append(f"- #{item['id']} {item['title']}\n  de [[{item['source_title']}]] ({item['source_project']}). Por quê: {item['motivo']}")
        return "\n".join(lines), [{"title": i["source_title"], "path": i["source_path"], "tipo": i["source_tipo"], "projeto": i["source_project"]} for i in items]
