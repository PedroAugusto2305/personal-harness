"""Janela de contexto de uma sessão do Claude Code, lida do transcript (JSONL) da conversa.

O total é o que a API contou na última resposta (o mesmo número da statusline: entrada +
cache criado + cache lido). A divisão por categoria é estimativa pelo tamanho do texto
(~3,6 caracteres por token, mistura de português e código) desde a última compactação; o
que sobra é o fixo da sessão: prompt do Claude Code, definições de ferramentas e CLAUDE.md.
"""

from __future__ import annotations

import json
import re
import os
from pathlib import Path

CHARS_PER_TOKEN = 3.6
IMAGE_TOKENS = 1600
SKIP_TYPES = {
    "api-request", "api-request-blob", "api-request-shape", "mode", "session-owner", "atis-latch", "last-prompt",
    "ai-title", "pr-link", "file-history-delta", "file-history-snapshot", "tools-used", "queue-operation",
}  # fmt: skip
CATEGORIES = {
    "conversa": "Suas mensagens",
    "respostas": "Respostas do agente",
    "raciocinio": "Raciocínio",
    "leituras": "Arquivos lidos",
    "comandos": "Comandos no terminal",
    "edicoes": "Edições de arquivo",
    "mcp": "Ferramentas MCP (Brain, conectores)",
    "outras": "Outras ferramentas",
    "injetado": "Hooks, skills e lembretes",
    "resumo": "Resumo da compactação",
    "sistema": "Fixo da sessão (prompt, ferramentas, CLAUDE.md)",
}
ATTACHMENT_LABEL = {
    "skill_listing": "lista de skills",
    "environment": "ambiente (pasta, git, data)",
    "invoked_skills": "skills carregadas",
    "deferred_tools_delta": "ferramentas sob demanda",
    "agent_listing_delta": "lista de subagentes",
    "mcp_instructions_delta": "instruções dos servidores MCP",
    "edited_text_file": "avisos de arquivo editado",
    "hook_blocking_error": "hooks que barraram o fim do turno",
    "instructions": "CLAUDE.md",
    "hook_additional_context": "contexto de hooks (Brain, MÊTIS)",
    "session_context": "contexto da conta",
    "silent_turn_reminder": "lembretes do Claude Code",
    "remote_session_change": "regras de commit e PR",
    "auto_mode": "modo automático",
    "task_status": "tarefas em segundo plano",
}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "NotebookRead"}

_cache: dict[str, tuple[tuple[int, float], dict]] = {}


def _tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN)


def _size(content) -> tuple[int, int]:
    """(caracteres, imagens) de um conteúdo de mensagem ou de resultado de ferramenta."""
    if content is None:
        return 0, 0
    if isinstance(content, str):
        return len(content), 0
    if isinstance(content, list):
        chars = images = 0
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "image":
                images += 1
            elif kind == "text":
                chars += len(block.get("text", ""))
            elif kind == "tool_result":
                c, i = _size(block.get("content"))
                chars, images = chars + c, images + i
            else:
                chars += len(json.dumps(block, ensure_ascii=False))
        return chars, images
    return len(json.dumps(content, ensure_ascii=False)), 0


def _short_path(path: str, cwd: str) -> str:
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1 :]
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


def _tool_label(name: str, data: dict, cwd: str) -> tuple[str, str]:
    """(categoria, rótulo legível) de uma chamada de ferramenta."""
    if name in READ_TOOLS:
        return "leituras", "📄 " + _short_path(str(data.get("file_path") or data.get("notebook_path") or "?"), cwd)
    if name in EDIT_TOOLS:
        return "edicoes", "✏️ " + _short_path(str(data.get("file_path") or data.get("notebook_path") or "?"), cwd)
    if name == "Bash":
        what = str(data.get("description") or data.get("command") or "")
        return "comandos", "⌘ " + what[:70]
    if name.startswith("mcp__"):
        parts = name.split("__")
        server, tool = (parts[1], "__".join(parts[2:])) if len(parts) > 2 else (name, "")
        hint = data.get("titulo") or data.get("termos") or data.get("decisao") or ""
        return "mcp", f"🔌 {server} · {tool}" + (f" · {str(hint)[:50]}" if hint else "")
    hint = data.get("pattern") or data.get("url") or data.get("description") or data.get("skill") or data.get("query") or ""
    return "outras", f"🛠 {name}" + (f" · {str(hint)[:60]}" if hint else "")


def context_breakdown(transcript: str, context: dict | None = None) -> dict:
    path = Path(transcript).expanduser()
    try:
        stat = path.stat()
    except OSError:
        return {"available": False, "reason": "o transcript desta sessão não existe mais"}
    key = (stat.st_size, stat.st_mtime)
    cached = _cache.get(str(path))
    if cached and cached[0] == key:
        result = cached[1]
    else:
        result = _parse(path)
        _cache[str(path)] = (key, result)
    return _finish(result, context or {})


def _parse(path: Path) -> dict:
    entries: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"type":"api-request' in line[:200] or not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") in SKIP_TYPES or entry.get("isSidechain"):
                continue
            if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
                entries = []  # só o que veio depois da última compactação está no contexto
            entries.append(entry)
    cats = dict.fromkeys(CATEGORIES, 0)
    items: dict[str, dict] = {}
    names: dict[str, tuple[str, str]] = {}
    usage = None
    turns = 0
    compacted = False
    cwd = ""

    def add(category: str, chars: int, images: int = 0, label: str | None = None, count: bool = True) -> None:
        tokens = _tokens(chars) + images * IMAGE_TOKENS
        cats[category] += tokens
        if label:
            item = items.setdefault(label, {"label": label, "category": category, "tokens": 0, "times": 0})
            item["tokens"] += tokens
            item["times"] += int(count)

    for entry in entries:
        kind = entry.get("type")
        cwd = entry.get("cwd") or cwd
        if kind == "system":
            if entry.get("subtype") == "compact_boundary":
                compacted = True
            continue
        if kind == "attachment":
            attachment = entry.get("attachment") or {}
            a_type = str(attachment.get("type", ""))
            # `rendered` é o texto que entrou de fato no contexto (versões novas do Claude Code);
            # sem ele, a anotação é só registro interno (hook_success, prompt_snapshot…).
            rendered = entry.get("rendered")
            if not rendered:
                continue
            chars, images = _size(rendered)
            if a_type == "file":
                name = attachment.get("displayPath") or attachment.get("filename") or "arquivo"
                add("leituras", chars, images, "📎 " + _short_path(str(name), cwd))
            elif a_type == "queued_command":
                add("conversa", chars, images)
            else:
                add("injetado", chars, images, "🧩 " + ATTACHMENT_LABEL.get(a_type, a_type or "anexo"))
            continue
        message = entry.get("message") or {}
        content = message.get("content")
        if kind == "assistant":
            usage = message.get("usage") or usage
            if not isinstance(content, list):
                continue
            for block in content:
                b_type = block.get("type")
                if b_type == "text":
                    add("respostas", len(block.get("text", "")))
                elif b_type == "thinking":
                    add("raciocinio", len(block.get("thinking", "")))
                elif b_type == "tool_use":
                    data = block.get("input") or {}
                    category, label = _tool_label(str(block.get("name", "")), data if isinstance(data, dict) else {}, cwd)
                    names[block.get("id", "")] = (category, label)
                    add(category, len(json.dumps(data, ensure_ascii=False)), label=label)
            continue
        if kind != "user":
            continue
        if entry.get("isCompactSummary"):
            add("resumo", _size(content)[0])
            continue
        if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                category, label = names.get(block.get("tool_use_id", ""), ("outras", "🛠 ferramenta"))
                chars, images = _size(block.get("content"))
                add(category, chars, images, label, count=False)
            continue
        chars, images = _size(content)
        if entry.get("isMeta"):
            add("injetado", chars, images, "🧩 instruções injetadas (skills, comandos)")
        else:
            turns += 1
            add("conversa", chars, images)
    return {"cats": cats, "items": items, "usage": usage, "turns": turns, "compacted": compacted, "mtime": path.stat().st_mtime}


def _finish(parsed: dict, context: dict) -> dict:
    usage = parsed["usage"] or {}
    measured = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    used = int(context.get("used_tokens") or measured or 0)
    size = int(context.get("size") or 0) or 200_000
    cats = dict(parsed["cats"])
    estimated = sum(cats.values())
    scale = 1.0
    if used and estimated > used * 0.9:
        scale = used * 0.9 / estimated  # a estimativa passou do real: encolhe tudo por igual
    for key in cats:
        cats[key] = int(cats[key] * scale)
    cats["sistema"] = max(0, used - sum(v for k, v in cats.items() if k != "sistema")) if used else 0
    total = used or sum(cats.values())
    categories = [
        {"key": k, "label": CATEGORIES[k], "tokens": v, "pct": round(100 * v / size, 1)}
        for k, v in sorted(cats.items(), key=lambda kv: -kv[1])
        if v > 0
    ]
    top = sorted(parsed["items"].values(), key=lambda i: -i["tokens"])[:12]
    return {
        "available": True,
        "used": total,
        "size": size,
        "pct": round(100 * total / size, 1) if size else None,
        "free": max(0, size - total),
        "categories": categories,
        "top": [{**i, "tokens": int(i["tokens"] * scale)} for i in top],
        "turns": parsed["turns"],
        "compacted": parsed["compacted"],
        "estimated": True,
        "updated": parsed["mtime"],
    }


MESSAGE_LINE = re.compile(r'"type":\s*"(?:user|assistant|response_item)"')
CODEX_NOISE = ("# AGENTS.md", "The following is the Codex agent history")


def last_messages(transcript: str, count: int = 2, limit: int = 400) -> list[dict]:
    """As últimas mensagens da conversa (você e o agente), lidas do fim do transcript."""
    path = Path(transcript).expanduser()
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 400_000))
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    found: list[dict] = []
    for line in chunk.splitlines()[1:] if len(chunk) >= 400_000 else chunk.splitlines():
        if not MESSAGE_LINE.search(line):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("isSidechain") or entry.get("isMeta") or entry.get("isCompactSummary"):
            continue
        content = (entry.get("message") or {}).get("content")
        if entry.get("type") == "response_item":  # rollout do Codex (v0.9.8)
            payload = entry.get("payload") or {}
            if payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
                continue
            blocks = payload.get("content") or []
            text = " ".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text"))
            role = "voce" if payload["role"] == "user" else "agente"
            if text.lstrip().startswith(CODEX_NOISE):
                continue
        elif entry.get("type") == "user":
            text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            role = "voce"
        else:
            text = " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            role = "agente"
        text = " ".join(str(text).split())
        if not text or text.startswith("<") and text.endswith(">"):
            continue  # comandos e lembretes do Claude Code, não conversa
        found.append({"role": role, "text": text[:limit] + ("…" if len(text) > limit else "")})
    return found[-count:]
