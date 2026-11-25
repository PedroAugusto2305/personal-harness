"""Modelos e forças que a barra de entrada da conversa oferece (v1.7.0).

- **Claude Code:** os apelidos da CLI (fable, opus, sonnet, haiku), que sempre apontam para o
  mais novo de cada família, e as forças do `--effort`.
- **Codex:** a lista que o próprio Codex guarda em `models_cache.json` (na pasta da conta), na
  ordem dele, com as forças que cada modelo aceita.

A troca reabre a mesma conversa com as flags oficiais de cada CLI (`claude --resume <id> --model
--effort`, `codex resume <id> -m -c model_reasoning_effort=`), que valem só para a sessão. O
`/model <nome>` digitado no Claude interativo grava o modelo como padrão das sessões novas, e o do
Codex é um menu que não aceita o nome na linha: nenhum dos dois serve para "só esta conversa".
Nada é gravado no config.toml nem nas settings do Claude.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from .sessions import EFFORTS_BY_KIND, MODEL_RE

CLAUDE_MODELS: list[dict] = [
    {"id": "fable", "nome": "Fable"},
    {"id": "opus", "nome": "Opus"},
    {"id": "sonnet", "nome": "Sonnet"},
    {"id": "haiku", "nome": "Haiku"},
]

#: As forças do Codex que a barra mostra, na ordem (o cache traz as que cada modelo aceita).
CODEX_EFFORT_ORDER = EFFORTS_BY_KIND["codex"]


class AjusteError(ValueError):
    """Modelo ou força que a CLI desta sessão não aceita."""


def codex_models(codex_home: Path) -> list[dict]:
    """Os modelos que o Codex lista no /model, com as forças de cada um (vazio sem o cache)."""
    try:
        data = json.loads((codex_home / "models_cache.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get("models") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    found: list[tuple[int, dict]] = []
    for index, model in enumerate(raw):
        if not isinstance(model, dict):
            continue
        slug = model.get("slug")
        if not isinstance(slug, str) or not MODEL_RE.match(slug) or model.get("visibility", "list") != "list":
            continue
        levels = [lvl.get("effort") for lvl in model.get("supported_reasoning_levels") or [] if isinstance(lvl, dict)]
        efforts = [e for e in CODEX_EFFORT_ORDER if e in levels]
        default = model.get("default_reasoning_level")
        priority = model.get("priority")
        found.append((
            priority if isinstance(priority, int) else 10_000 + index,
            {
                "id": slug,
                "nome": str(model.get("display_name") or slug),
                "esforcos": efforts,
                "esforco_padrao": default if default in efforts else None,
            },
        ))  # fmt: skip
    return [model for _, model in sorted(found, key=lambda pair: pair[0])]


def codex_defaults(codex_home: Path) -> dict:
    """O modelo e a força padrão do config.toml da conta (o que vale sem escolha na barra)."""
    try:
        with (codex_home / "config.toml").open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {"modelo": None, "esforco": None}
    model, effort = config.get("model"), config.get("model_reasoning_effort")
    return {
        "modelo": model if isinstance(model, str) and model else None,
        "esforco": effort if isinstance(effort, str) and effort else None,
    }


def catalog(kind: str, codex_home: Path | None = None) -> dict:
    """Modelos e forças de uma CLI, e o padrão dela."""
    if kind == "claude":
        efforts = list(EFFORTS_BY_KIND["claude"])
        return {"modelos": [{**m, "esforcos": efforts, "esforco_padrao": None} for m in CLAUDE_MODELS],
                "esforcos": efforts, "padrao": {"modelo": None, "esforco": None}}  # fmt: skip
    if kind == "codex":
        home = codex_home or Path.home() / ".codex"
        models = codex_models(home)
        defaults = codex_defaults(home)
        efforts = [e for e in CODEX_EFFORT_ORDER if any(e in m["esforcos"] for m in models)] or ["low", "medium", "high", "xhigh"]
        # O padrão do config que não está na lista (um modelo novo, um nome antigo) também aparece.
        if defaults["modelo"] and MODEL_RE.match(defaults["modelo"]) and not any(m["id"] == defaults["modelo"] for m in models):
            models.append({"id": defaults["modelo"], "nome": defaults["modelo"], "esforcos": efforts, "esforco_padrao": None})
        return {"modelos": models, "esforcos": efforts, "padrao": defaults}
    raise AjusteError("só o Claude e o Codex têm modelo e força")


def validate(kind: str, modelo: str | None, esforco: str | None) -> tuple[str | None, str | None]:
    """Confere o pedido da barra; texto vazio volta ao padrão da CLI (None)."""
    modelo = (modelo or "").strip() or None
    esforco = (esforco or "").strip() or None
    if kind not in EFFORTS_BY_KIND:
        raise AjusteError("só o Claude e o Codex têm modelo e força")
    if modelo is not None and not MODEL_RE.match(modelo):
        raise AjusteError(f"modelo inválido: {modelo}")
    if esforco is not None and esforco not in EFFORTS_BY_KIND[kind]:
        raise AjusteError(f"força inválida para o {'Claude' if kind == 'claude' else 'Codex'}: {esforco}")
    return modelo, esforco
