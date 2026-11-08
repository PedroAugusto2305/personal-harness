"""Leitura do JSON que o Claude Code manda para a statusline.

Campos usados (doc: code.claude.com/docs/en/statusline):
- model.display_name
- workspace.current_dir
- context_window.used_percentage, context_window_size, current_usage
- cost.total_cost_usd
- transcript_path (a janela de contexto lê o JSONL da conversa)
- rate_limits.five_hour / seven_day: used_percentage, resets_at (só para assinantes
  e só depois da primeira resposta; cada janela pode faltar)
"""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def parse_statusline(payload: dict) -> dict:
    model = _dict(payload.get("model"))
    workspace = _dict(payload.get("workspace"))
    context = _dict(payload.get("context_window"))
    current = _dict(context.get("current_usage"))
    cost = _dict(payload.get("cost"))
    limits = _dict(payload.get("rate_limits"))

    used_tokens: int | None = None
    parts = [current.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
    if any(isinstance(p, (int, float)) for p in parts):
        used_tokens = sum(int(p) for p in parts if isinstance(p, (int, float)))

    rate_limits = {}
    for window in ("five_hour", "seven_day"):
        data = _dict(limits.get(window))
        pct = _num(data.get("used_percentage"))
        if pct is not None:
            rate_limits[window] = {"used_pct": pct, "resets_at": _int(data.get("resets_at"))}

    return {
        "model": model.get("display_name") or model.get("id"),
        "cwd": workspace.get("current_dir") or payload.get("cwd"),
        "context": {
            "used_pct": _num(context.get("used_percentage")),
            "size": _int(context.get("context_window_size")),
            "used_tokens": used_tokens,
        },
        "cost_usd": _num(cost.get("total_cost_usd")),
        "transcript": payload.get("transcript_path") if isinstance(payload.get("transcript_path"), str) else None,
        # Id da conversa no Claude: serve para retomar (`claude --resume <id>`) e continuar depois de sair.
        "session_id": payload.get("session_id") if isinstance(payload.get("session_id"), str) else None,
        "rate_limits": rate_limits,
    }


def render_statusline(parsed: dict) -> str:
    """Texto curto que aparece na statusline dentro do terminal."""
    pieces = ["◆ metis"]
    if parsed.get("model"):
        pieces.append(str(parsed["model"]))
    pct = parsed.get("context", {}).get("used_pct")
    if pct is not None:
        pieces.append(f"contexto {round(pct)}%")
    return " · ".join(pieces)
