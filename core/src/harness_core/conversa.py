"""A conversa de uma sessão do Claude Code ou do Codex, desenhada a partir do transcript (v1.2.0).

O terminal interativo continua por baixo, pelo plano, como sempre: a tela da conversa só lê o
JSONL que a própria CLI grava e o transforma em itens.

- `voce`: o que você mandou, com as imagens coladas ou anexadas;
- `agente`: a resposta em Markdown (com as imagens que ele citou pelo caminho);
- `pensamento`: o raciocínio, quando a CLI o grava em texto;
- `ferramenta`: comando, leitura, edição (com o diff), busca, MCP, subagente…, com o resultado
  e as imagens que a ferramenta devolveu (print do navegador, imagem lida, imagem gerada);
- `plano`: a lista de passos (TodoWrite do Claude, update_plan do Codex);
- `evento`: marcos da conversa (compactação, duração do turno, comando de barra, interrupção).

A leitura é incremental: cada transcript guarda até onde foi lido, e cada consulta só lê as
linhas novas. Cada item tem `n` (a posição, que nunca muda) e `v` (a versão, que sobe quando o
item muda: o resultado de uma ferramenta chega depois da chamada). A tela pede o que mudou
depois da versão que já tem.

Imagem em base64 não vai no JSON: o item leva uma referência (onde começa a linha no arquivo e
o caminho até o bloco) e a imagem é servida à parte por `imagem()`. Imagem em arquivo (o anexo
da barra, o caminho citado pelo agente, o Write de um .png ou .svg) vai pelo caminho.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import threading
from collections import OrderedDict
from pathlib import Path

from .transcript import _short_path

IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".svg": "image/svg+xml", ".avif": "image/avif", ".bmp": "image/bmp",
}  # fmt: skip
#: Cortes do que vai para a tela (a conversa inteira continua no transcript).
TEXT_LIMIT = 60_000
INPUT_LIMIT = 3_000
OUTPUT_LIMIT = 4_000
IMAGES_PER_ITEM = 8
#: Transcripts lidos guardados na memória (um por conversa aberta, mais folga).
MAX_STATES = 24
CHUNK = 8 * 1024 * 1024

#: Linhas do Claude que nunca viram item: só registro interno da CLI.
CLAUDE_SKIP = (
    b'"type":"api-request', b'"type":"file-history', b'"type":"last-prompt"', b'"type":"mode"', b'"type":"session-owner"',
    b'"type":"atis-latch"', b'"type":"ai-title"', b'"type":"custom-title"', b'"type":"agent-name"', b'"type":"permission-mode"',
    b'"type":"tools-used"', b'"type":"cost-state"', b'"type":"pr-link"', b'"type":"queue-operation"',
)  # fmt: skip
CODEX_NOISE = ("# AGENTS.md", "The following is the Codex agent history", "<environment_context>", "<user_instructions>")
#: Caminho de imagem dentro do texto: absoluto, com ~ ou relativo com pasta (`saida/logo.png`).
IMAGE_PATH = re.compile(r"(?<![\w/~.-])((?:~|\.{1,2})?/?[\w@%+=,~.-]*(?:/[\w@%+=,~.-]+)*\.(?:png|jpe?g|gif|webp|svg|avif|bmp))(?![\w-])", re.IGNORECASE)
#: O mesmo caminho entre crases ou aspas, que pode ter espaço (o anexo da barra vem entre aspas simples).
QUOTED_IMAGE_PATH = re.compile(r"[`'\"]([^`'\"\n]+\.(?:png|jpe?g|gif|webp|svg|avif|bmp))[`'\"]", re.IGNORECASE)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")


class _State:
    """O que já foi lido de um transcript."""

    def __init__(self, path: Path, cli: str) -> None:
        self.path = path
        self.cli = cli
        self.epoch = secrets.token_hex(4)
        self.offset = 0
        self.inode = 0
        self.items: list[dict] = []
        self.by_id: dict[str, int] = {}
        self.seen: set[str] = set()
        self.seq = 0
        self.cwd = ""
        #: Codex: desde o primeiro item_completed, as ferramentas vêm dos itens (comando já
        #: separado em leitura, busca e listagem), e não das chamadas cruas do modelo.
        self.items_mode = False
        #: Claude: o último comando `!` (a saída dele chega na mensagem seguinte).
        self.last_bash: str | None = None
        self.lock = threading.Lock()

    @property
    def fonte(self) -> str:
        return f"{self.path}#{self.epoch}"

    # --- itens -----------------------------------------------------------------------------

    def add(self, item: dict) -> dict:
        self.seq += 1
        item["n"] = len(self.items)
        item["v"] = self.seq
        if not item.get("id"):
            item["id"] = f"i{item['n']}"
        if item["id"] in self.by_id:  # o mesmo id de novo (linha repetida): só atualiza
            return self.update(self.items[self.by_id[item["id"]]], {k: v for k, v in item.items() if k not in ("n", "v", "id")})
        self.by_id[item["id"]] = item["n"]
        self.items.append(item)
        return item

    def update(self, item: dict, changes: dict) -> dict:
        self.seq += 1
        item.update(changes)
        item["v"] = self.seq
        return item

    def get(self, item_id: str | None) -> dict | None:
        index = self.by_id.get(item_id or "")
        return None if index is None else self.items[index]


_states: OrderedDict[str, _State] = OrderedDict()
_lock = threading.Lock()


# --- leitura -----------------------------------------------------------------------------------


def read(transcript: str, cli: str) -> _State:
    """Lê o que o transcript ganhou desde a última vez (e do zero se ele foi trocado)."""
    path = Path(transcript).expanduser()
    key = str(path)
    with _lock:
        state = _states.get(key)
        if state is None or state.cli != cli:
            state = _State(path, cli)
            _states[key] = state
        _states.move_to_end(key)
        while len(_states) > MAX_STATES:
            _states.popitem(last=False)
    with state.lock:
        try:
            stat = path.stat()
        except OSError:
            return state
        if state.inode and (stat.st_ino != state.inode or stat.st_size < state.offset):
            fresh = _State(path, cli)  # arquivo novo no mesmo caminho: começa de novo
            state.__dict__.update({k: v for k, v in fresh.__dict__.items() if k != "lock"})
        state.inode = stat.st_ino
        if stat.st_size > state.offset:
            _consume(state)
    return state


def known(fonte_path: str) -> bool:
    """O transcript já foi lido para alguma conversa (só desses a imagem é servida)."""
    with _lock:
        return str(Path(fonte_path).expanduser()) in _states


def _consume(state: _State) -> None:
    with open(state.path, "rb") as handle:
        handle.seek(state.offset)
        rest = b""
        start = state.offset
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            data = rest + chunk
            cut = data.rfind(b"\n")
            if cut < 0:
                rest = data
                continue
            position = start
            for line in data[: cut + 1].splitlines(keepends=True):
                _line(state, line, position)
                position += len(line)
            start = position
            rest = data[cut + 1 :]
        state.offset = start  # a linha sem \n no fim ainda está sendo escrita: fica para depois


def _line(state: _State, raw: bytes, offset: int) -> None:
    head = raw[:160]
    if not raw.strip() or (state.cli == "claude" and any(mark in head for mark in CLAUDE_SKIP)):
        return
    try:
        entry = json.loads(raw)
    except ValueError:
        return
    if not isinstance(entry, dict):
        return
    try:
        if state.cli == "codex":
            _codex(state, entry, offset)
        else:
            _claude(state, entry, offset)
    except (TypeError, AttributeError, KeyError, ValueError):
        return  # formato que a CLI mudou: a linha fica de fora, o resto continua


# --- comum ------------------------------------------------------------------------------------


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (cortado: {len(text) - limit:,} caracteres a mais)".replace(",", ".")


def _abs(path: str, cwd: str) -> str:
    path = os.path.expanduser(path.strip())
    if not os.path.isabs(path) and cwd:
        path = os.path.normpath(os.path.join(cwd, path))
    return path


def _file_image(path: str, cwd: str, check: bool = True) -> dict | None:
    full = _abs(path, cwd)
    if Path(full).suffix.lower() not in IMAGE_TYPES:
        return None
    if check and not os.path.isfile(full):
        return None
    return {"arquivo": full, "nome": os.path.basename(full)}


def images_in_text(text: str, cwd: str) -> list[dict]:
    """As imagens que existem no disco citadas pelo caminho no texto (o anexo da barra, o arquivo
    que o agente gerou). As que já aparecem como ![](…) no Markdown ficam de fora."""
    inline = {_abs(m, cwd) for m in MARKDOWN_IMAGE.findall(text)}
    found: list[dict] = []
    seen: set[str] = set()
    candidates = [m.group(1) for m in QUOTED_IMAGE_PATH.finditer(text)] + [m.group(1) for m in IMAGE_PATH.finditer(text)]
    for candidate in candidates:
        candidate = candidate.strip()
        if "/" not in candidate and not candidate.startswith("~"):
            continue  # só o nome do arquivo, sem pasta: ambíguo demais
        image = _file_image(candidate, cwd)
        if image and image["arquivo"] not in seen and image["arquivo"] not in inline:
            seen.add(image["arquivo"])
            found.append(image)
        if len(found) >= IMAGES_PER_ITEM:
            break
    return found


def _ref(state: _State, offset: int, *path: str | int) -> dict:
    return {"ref": f"{offset}:" + ".".join(str(p) for p in path)}


def _when(entry: dict) -> str:
    return str(entry.get("timestamp") or "")


def _duration(ms: float) -> str:
    seconds = int(ms / 1000 + 0.5)  # 2,5 s vira 3 s (o round do Python iria para o par)
    if seconds < 60:
        return f"{max(seconds, 1)}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _event(state: _State, text: str, entry: dict, kind: str = "marco", detail: str | None = None) -> None:
    item = {"tipo": "evento", "evento": kind, "texto": text, "hora": _when(entry)}
    if detail:
        item["detalhe"] = detail
    state.add(item)


# --- Claude Code --------------------------------------------------------------------------------

COMMAND_NAME = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
COMMAND_ARGS = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)
TAG_TEXT = re.compile(r"<(local-command-stdout|bash-stdout|bash-stderr|bash-input)>(.*?)</\1>", re.S)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _tag(text: str, name: str) -> str:
    for found, value in TAG_TEXT.findall(text):
        if found == name:
            return ANSI.sub("", value).strip()
    return ""


def _claude(state: _State, entry: dict, offset: int) -> None:
    kind = entry.get("type")
    if entry.get("isSidechain"):
        return  # conversa de subagente: aparece como a ferramenta Task/Agent
    uuid = entry.get("uuid")
    if uuid:
        if uuid in state.seen:
            return
        state.seen.add(uuid)
    state.cwd = entry.get("cwd") or state.cwd
    if kind == "system":
        sub = entry.get("subtype")
        if sub == "compact_boundary":
            trigger = (entry.get("compactMetadata") or {}).get("trigger")
            _event(state, "Conversa compactada" + (" automaticamente" if trigger == "auto" else ""), entry, "compactada")
        elif sub == "turn_duration" and entry.get("durationMs"):
            _event(state, f"Trabalhou por {_duration(float(entry['durationMs']))}", entry, "duracao")
        elif sub == "local_command":
            run = entry.get("commandRun") or {}
            name = str(run.get("command") or "").strip()
            if name:
                out = _tag(str(entry.get("content") or ""), "local-command-stdout")
                _event(state, f"/{name} {run.get('args') or ''}".strip(), entry, "comando", out or None)
        return
    if kind == "attachment":
        attachment = entry.get("attachment") or {}
        prompt = attachment.get("prompt")
        if attachment.get("type") == "queued_command" and isinstance(prompt, str) and attachment.get("commandMode") in (None, "prompt"):
            if prompt.strip() and not prompt.lstrip().startswith("<"):
                state.add({"tipo": "voce", "texto": _cut(prompt.strip(), TEXT_LIMIT), "hora": _when(entry), "imagens": images_in_text(prompt, state.cwd), "fila": True})
        return
    message = entry.get("message") or {}
    content = message.get("content")
    if kind == "user":
        if entry.get("isMeta"):
            return
        if entry.get("isCompactSummary"):
            text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict))
            _event(state, "Resumo da compactação", entry, "resumo", _cut(str(text), INPUT_LIMIT))
            return
        if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    _claude_result(state, block, offset, i)
            return
        _claude_user(state, entry, content, offset)
        return
    if kind == "assistant" and isinstance(content, list):
        base = uuid or f"a{offset}"
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            b_type = block.get("type")
            if b_type == "text" and str(block.get("text", "")).strip():
                text = str(block["text"]).strip()
                state.add({"id": f"{base}:{i}", "tipo": "agente", "texto": _cut(text, TEXT_LIMIT), "hora": _when(entry), "imagens": images_in_text(text, state.cwd)})
            elif b_type == "thinking" and str(block.get("thinking", "")).strip():
                state.add({"id": f"{base}:{i}", "tipo": "pensamento", "texto": _cut(str(block["thinking"]).strip(), TEXT_LIMIT), "hora": _when(entry)})
            elif b_type == "tool_use":
                _claude_tool(state, block, entry)


def _claude_user(state: _State, entry: dict, content, offset: int) -> None:
    texts: list[str] = []
    images: list[dict] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif block.get("type") == "image" and len(images) < IMAGES_PER_ITEM:
                images.append({**_ref(state, offset, "message", "content", i), "nome": f"Imagem {len(images) + 1}"})
    text = "\n\n".join(t for t in texts if t.strip()).strip()
    if "<command-name>" in text:
        name = COMMAND_NAME.search(text)
        args = COMMAND_ARGS.search(text)
        if name:
            _event(state, f"{name.group(1)} {args.group(1) if args else ''}".strip(), entry, "comando")
        return
    if text.startswith("<bash-input>"):
        command = _tag(text, "bash-input")
        item = state.add({"tipo": "ferramenta", "nome": "Bash", "categoria": "comando", "rotulo": f"! {command.splitlines()[0][:90] if command else ''}",
                          "detalhe": _cut(command, INPUT_LIMIT), "lingua": "bash", "estado": "rodando", "hora": _when(entry), "voce": True})  # fmt: skip
        state.last_bash = item["id"]
        return
    if text.startswith(("<bash-stdout>", "<bash-stderr>")):
        out = "\n".join(p for p in (_tag(text, "bash-stdout"), _tag(text, "bash-stderr")) if p)
        target = state.get(state.last_bash)
        if target is not None:
            state.update(target, {"saida": _cut(out, OUTPUT_LIMIT), "estado": "erro" if _tag(text, "bash-stderr") else "ok"})
        return
    if text.startswith("<local-command-stdout>"):
        out = _tag(text, "local-command-stdout")
        if out:
            _event(state, "Saída do comando", entry, "comando", _cut(out, INPUT_LIMIT))
        return
    if text.startswith("[Request interrupted"):
        _event(state, "Interrompido por você", entry, "interrompido")
        return
    if not images and (not text or (text.startswith("<") and text.endswith(">")) or text.startswith("Caveat:")):
        return  # lembretes e avisos do Claude Code, não conversa
    known_files = {i.get("arquivo") for i in images}
    images += [i for i in images_in_text(text, state.cwd) if i["arquivo"] not in known_files][: max(0, IMAGES_PER_ITEM - len(images))]
    state.add({"id": entry.get("uuid") or None, "tipo": "voce", "texto": _cut(text, TEXT_LIMIT), "hora": _when(entry), "imagens": images})


TOOL_CATEGORY = {
    "Bash": "comando", "BashOutput": "comando", "KillShell": "comando", "Read": "leitura", "NotebookRead": "leitura",
    "Edit": "edicao", "MultiEdit": "edicao", "Write": "edicao", "NotebookEdit": "edicao", "Grep": "busca", "Glob": "busca",
    "LS": "busca", "WebFetch": "web", "WebSearch": "web", "Task": "agente", "Agent": "agente", "Skill": "skill",
    "AskUserQuestion": "pergunta", "ExitPlanMode": "plano",
}  # fmt: skip

LANG_BY_EXT = {
    ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".py": "python",
    ".sh": "shell", ".zsh": "shell", ".bash": "shell", ".json": "json", ".css": "css", ".scss": "scss", ".html": "html", ".md": "markdown",
    ".rs": "rust", ".go": "go", ".sql": "sql", ".yml": "yaml", ".yaml": "yaml", ".toml": "ini", ".svg": "xml", ".xml": "xml",
    ".swift": "swift", ".java": "java", ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".kt": "kotlin",
}  # fmt: skip


def _lang(path: str) -> str:
    return LANG_BY_EXT.get(Path(path).suffix.lower(), "")


def _claude_tool(state: _State, block: dict, entry: dict) -> None:
    name = str(block.get("name") or "ferramenta")
    data = block.get("input") if isinstance(block.get("input"), dict) else {}
    tool_id = str(block.get("id") or "") or None
    cwd = state.cwd
    item: dict = {"id": tool_id, "tipo": "ferramenta", "nome": name, "categoria": TOOL_CATEGORY.get(name, "outra"), "estado": "rodando", "hora": _when(entry)}
    path = str(data.get("file_path") or data.get("notebook_path") or "")
    short = _short_path(path, cwd) if path else ""
    if name == "TodoWrite":
        steps = [
            {"texto": str(t.get("content") or t.get("activeForm") or ""), "estado": {"in_progress": "andamento", "completed": "feito"}.get(str(t.get("status")), "pendente")}
            for t in data.get("todos") or [] if isinstance(t, dict)
        ]  # fmt: skip
        state.add({"id": tool_id, "tipo": "plano", "passos": steps, "hora": _when(entry)})
        return
    if name == "Bash":
        command = str(data.get("command") or "")
        label = data.get("description") or (command.splitlines()[0] if command else "comando")
        item.update(rotulo=str(label)[:120], detalhe=_cut(command, INPUT_LIMIT), lingua="bash")
    elif name in ("Read", "NotebookRead"):
        item.update(rotulo=f"Leu {short}", arquivo=path)
    elif name in ("Edit", "MultiEdit"):
        edits = data.get("edits") if name == "MultiEdit" else [data]
        diff = [{"antes": _cut(str(e.get("old_string") or ""), INPUT_LIMIT), "depois": _cut(str(e.get("new_string") or ""), INPUT_LIMIT)} for e in edits or [] if isinstance(e, dict)]
        item.update(rotulo=f"Editou {short}", arquivo=path, diff=diff[:20], lingua=_lang(path))
    elif name == "Write":
        item.update(rotulo=f"Escreveu {short}", arquivo=path, detalhe=_cut(str(data.get("content") or ""), INPUT_LIMIT), lingua=_lang(path))
    elif name == "NotebookEdit":
        item.update(rotulo=f"Editou {short}", arquivo=path, detalhe=_cut(str(data.get("new_source") or ""), INPUT_LIMIT))
    elif name in ("Grep", "Glob", "LS"):
        where = data.get("path")
        item.update(rotulo=f"Buscou {data.get('pattern') or where or ''}".strip() + (f" em {_short_path(str(where), cwd)}" if where and data.get("pattern") else ""))
    elif name == "WebFetch":
        item.update(rotulo=f"Abriu {data.get('url') or ''}", detalhe=_cut(str(data.get("prompt") or ""), INPUT_LIMIT), url=data.get("url"))
    elif name == "WebSearch":
        item.update(rotulo=f"Pesquisou {data.get('query') or ''}")
    elif name in ("Task", "Agent"):
        item.update(rotulo=f"Subagente: {data.get('description') or data.get('subagent_type') or ''}".strip(), detalhe=_cut(str(data.get("prompt") or ""), INPUT_LIMIT), lingua="markdown")
    elif name == "Skill":
        item.update(rotulo=f"Skill {data.get('skill') or data.get('command') or ''}".strip())
    elif name == "AskUserQuestion":
        questions = data.get("questions") or []
        first = questions[0] if questions and isinstance(questions[0], dict) else {}
        lines = []
        for q in questions:
            if isinstance(q, dict):
                lines.append(f"**{q.get('question', '')}**")
                lines += [f"- {o.get('label', '')}: {o.get('description', '')}" for o in q.get("options") or [] if isinstance(o, dict)]
        item.update(rotulo=f"Perguntou: {first.get('question') or ''}"[:160], detalhe="\n".join(lines), lingua="markdown")
    elif name == "ExitPlanMode":
        item.update(rotulo="Propôs um plano", detalhe=_cut(str(data.get("plan") or ""), TEXT_LIMIT), lingua="markdown")
    elif name.startswith("mcp__"):
        parts = name.split("__")
        server, tool = (parts[1], "__".join(parts[2:])) if len(parts) > 2 else (name, "")
        item.update(categoria="mcp", rotulo=f"{server} · {tool}", detalhe=_cut(json.dumps(data, ensure_ascii=False, indent=2), INPUT_LIMIT), lingua="json")
    else:
        hint = data.get("pattern") or data.get("url") or data.get("description") or data.get("query") or ""
        item.update(rotulo=f"{name}" + (f" · {str(hint)[:80]}" if hint else ""), detalhe=_cut(json.dumps(data, ensure_ascii=False, indent=2), INPUT_LIMIT) if data else None, lingua="json")
    state.add(item)


def _result_parts(state: _State, content, offset: int, *path: str | int) -> tuple[str, list[dict]]:
    """Texto e imagens do resultado de uma ferramenta (texto puro ou lista de blocos)."""
    if isinstance(content, str):
        return content, []
    texts: list[str] = []
    images: list[dict] = []
    for j, part in enumerate(content or []):
        if not isinstance(part, dict):
            continue
        if part.get("type") in ("text", "input_text", "output_text"):
            texts.append(str(part.get("text", "")))
        elif part.get("type") in ("image", "input_image") and len(images) < IMAGES_PER_ITEM:
            images.append({**_ref(state, offset, *path, j), "nome": "Imagem da ferramenta"})
    return "\n".join(texts), images


def _claude_result(state: _State, block: dict, offset: int, index: int) -> None:
    item = state.get(str(block.get("tool_use_id") or ""))
    if item is None or item.get("tipo") != "ferramenta":
        return  # resultado do TodoWrite (o plano já aparece) ou de ferramenta fora da janela
    text, images = _result_parts(state, block.get("content"), offset, "message", "content", index, "content")
    error = bool(block.get("is_error"))
    if item.get("nome") == "Write" and not error:
        written = _file_image(str(item.get("arquivo") or ""), state.cwd, check=False)
        if written:
            images.append({**written, "nome": f"{written['nome']} (gerada)"})
    changes: dict = {"saida": _cut(ANSI.sub("", text), OUTPUT_LIMIT), "estado": "erro" if error else "ok"}
    if images:
        changes["imagens"] = (item.get("imagens") or []) + images
    state.update(item, changes)


# --- Codex --------------------------------------------------------------------------------------


def _codex_noise(text: str) -> bool:
    t = text.strip()
    return not t or t.startswith(CODEX_NOISE) or (t.startswith("<") and t.endswith(">"))


def _codex(state: _State, entry: dict, offset: int) -> None:
    kind = entry.get("type")
    payload = entry.get("payload") or {}
    if kind in ("session_meta", "turn_context"):
        state.cwd = str(payload.get("cwd") or state.cwd)
        return
    if kind == "compacted":
        _event(state, "Conversa compactada", entry, "compactada")
        return
    if kind == "event_msg":
        e_type = payload.get("type")
        if e_type == "item_completed":
            state.items_mode = True
            item = payload.get("item")
            if isinstance(item, dict):
                _codex_item(state, item, entry, offset)
        elif e_type == "task_complete" and payload.get("duration_ms"):
            _event(state, f"Trabalhou por {_duration(float(payload['duration_ms']))}", entry, "duracao")
        elif e_type == "turn_aborted":
            _event(state, "Interrompido por você", entry, "interrompido")
        elif e_type == "context_compacted":
            _event(state, "Conversa compactada", entry, "compactada")
        return
    if kind != "response_item":
        return
    p_type = payload.get("type")
    if p_type == "message":
        role = payload.get("role")
        if role not in ("user", "assistant"):
            return
        texts: list[str] = []
        images: list[dict] = []
        for i, block in enumerate(payload.get("content") or []):
            if not isinstance(block, dict):
                continue
            b_type = block.get("type")
            if b_type in ("input_text", "output_text", "text"):
                value = str(block.get("text", ""))
                if not _codex_noise(value) and not re.fullmatch(r"\s*</?image[^>]*>\s*", value):
                    texts.append(value)
            elif b_type == "input_image" and len(images) < IMAGES_PER_ITEM:
                images.append({**_ref(state, offset, "payload", "content", i), "nome": f"Imagem {len(images) + 1}"})
        text = "\n\n".join(t.strip() for t in texts if t.strip())
        if not text and not images:
            return
        known_files = {i.get("arquivo") for i in images}
        images += [i for i in images_in_text(text, state.cwd) if i["arquivo"] not in known_files][: max(0, IMAGES_PER_ITEM - len(images))]
        state.add({"id": payload.get("id") or None, "tipo": "voce" if role == "user" else "agente", "texto": _cut(text, TEXT_LIMIT), "hora": _when(entry), "imagens": images})
        return
    if p_type == "reasoning":
        summary = "\n\n".join(str(s.get("text", "")) for s in payload.get("summary") or [] if isinstance(s, dict)).strip()
        if summary:
            state.add({"id": payload.get("id") or None, "tipo": "pensamento", "texto": _cut(summary, TEXT_LIMIT), "hora": _when(entry)})
        return
    if p_type in ("function_call", "custom_tool_call", "local_shell_call", "web_search_call", "image_generation_call"):
        _codex_call(state, payload, entry, offset)
        return
    if p_type in ("function_call_output", "custom_tool_call_output"):
        item = state.get(str(payload.get("call_id") or ""))
        if item is None or item.get("tipo") != "ferramenta":
            return
        output = payload.get("output")
        if isinstance(output, dict):  # {"content": "...", "success": bool}
            text, images = str(output.get("content") or ""), []
            error = output.get("success") is False
        else:
            text, images = _result_parts(state, output, offset, "payload", "output")
            error = False
        changes: dict = {"saida": _cut(text, OUTPUT_LIMIT), "estado": "erro" if error else "ok"}
        if images:
            changes["imagens"] = (item.get("imagens") or []) + images
        state.update(item, changes)


def _codex_call(state: _State, payload: dict, entry: dict, offset: int) -> None:
    p_type = payload.get("type")
    name = str(payload.get("name") or p_type)
    call_id = str(payload.get("call_id") or payload.get("id") or "") or None
    if p_type == "image_generation_call":
        image = None
        if isinstance(payload.get("result"), str) and payload["result"]:
            image = {**_ref(state, offset, "payload", "result"), "nome": "Imagem gerada"}
        item = {"id": payload.get("id") or call_id, "tipo": "ferramenta", "nome": "image_generation", "categoria": "imagem", "rotulo": "Gerou uma imagem",
                "detalhe": payload.get("revised_prompt"), "estado": "ok" if image else "rodando", "hora": _when(entry), "imagens": [image] if image else []}  # fmt: skip
        state.add(item)
        return
    args: dict = {}
    raw = payload.get("arguments")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            args = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            args = {}
    elif isinstance(raw, dict):
        args = raw
    if name == "update_plan":
        steps = [
            {"texto": str(s.get("step") or ""), "estado": {"in_progress": "andamento", "completed": "feito"}.get(str(s.get("status")), "pendente")}
            for s in args.get("plan") or [] if isinstance(s, dict)
        ]  # fmt: skip
        state.add({"id": call_id, "tipo": "plano", "passos": steps, "texto": args.get("explanation") or None, "hora": _when(entry)})
        return
    if state.items_mode:
        return  # as ferramentas chegam como itens prontos (CommandExecution, FileChange…)
    item: dict = {"id": call_id, "tipo": "ferramenta", "nome": name, "categoria": "outra", "estado": "rodando", "hora": _when(entry)}
    if p_type == "local_shell_call" or name in ("shell", "exec_command", "container.exec", "shell_command"):
        command = (payload.get("action") or {}).get("command") if p_type == "local_shell_call" else args.get("cmd") or args.get("command")
        if isinstance(command, list):
            command = command[-1] if len(command) >= 3 and command[1] in ("-lc", "-c") else " ".join(map(str, command))
        command = str(command or "")
        item.update(categoria="comando", rotulo=command.splitlines()[0][:120] if command else "comando", detalhe=_cut(command, INPUT_LIMIT), lingua="bash")
    elif name == "apply_patch":
        patch = str(payload.get("input") or args.get("input") or "")
        files = re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", patch, re.M)
        item.update(categoria="edicao", rotulo="Editou " + (", ".join(_short_path(f, state.cwd) for f in files[:3]) if files else "arquivos"), patch=_cut(patch, OUTPUT_LIMIT))
    elif name == "view_image":
        image = _file_image(str(args.get("path") or ""), state.cwd, check=False)
        item.update(categoria="imagem", rotulo=f"Viu {_short_path(str(args.get('path') or ''), state.cwd)}", imagens=[image] if image else [])
    elif p_type == "web_search_call":
        action = payload.get("action") or {}
        item.update(categoria="web", rotulo=f"Pesquisou {action.get('query') or ''}".strip(), estado="ok")
    elif "__" in name:
        server, _sep, tool = name.removeprefix("mcp__").partition("__")
        item.update(categoria="mcp", rotulo=f"{server} · {tool}", detalhe=_cut(json.dumps(args, ensure_ascii=False, indent=2), INPUT_LIMIT), lingua="json")
    else:
        body = payload.get("input") if isinstance(payload.get("input"), str) else (json.dumps(args, ensure_ascii=False, indent=2) if args else "")
        item.update(rotulo=name, detalhe=_cut(str(body), INPUT_LIMIT) or None)
    state.add(item)


def _codex_item(state: _State, item: dict, entry: dict, offset: int) -> None:
    """Item pronto do Codex (o mesmo formato do app-server): comando, edição, MCP, busca, imagem."""
    key = str(item.get("type") or "").replace("_", "").lower()
    item_id = str(item.get("id") or "") or None
    when = _when(entry)
    if key in ("usermessage", "agentmessage", "reasoning", "hookprompt"):
        return  # as mensagens vêm do response_item, que traz as imagens
    status = str(item.get("status") or "completed").lower()
    state_of = "erro" if status in ("failed", "declined", "error") else "ok"
    if key == "commandexecution":
        command = item.get("command")
        if isinstance(command, list):
            command = command[-1] if len(command) >= 3 and command[1] in ("-lc", "-c") else " ".join(map(str, command))
        command = str(command or "")
        actions = item.get("parsed_cmd") or item.get("commandActions") or []
        kinds = {str(a.get("type")) for a in actions if isinstance(a, dict)}
        if kinds == {"read"}:
            names = [str(a.get("name") or Path(str(a.get("path") or "")).name) for a in actions]
            category, label = "leitura", "Leu " + ", ".join(names[:4]) + (f" e mais {len(names) - 4}" if len(names) > 4 else "")
        elif kinds and kinds <= {"search", "list_files", "read"}:
            queries = [str(a.get("query") or a.get("path") or "") for a in actions if a.get("type") in ("search", "list_files")]
            category, label = "busca", "Explorou " + (", ".join(q for q in queries if q)[:100] or "a pasta")
        else:
            category, label = "comando", command.splitlines()[0][:120] if command else "comando"
        code = item.get("exit_code", item.get("exitCode"))
        output = item.get("aggregated_output") or item.get("aggregatedOutput") or item.get("formatted_output") or "\n".join(
            str(item.get(k) or "") for k in ("stdout", "stderr") if item.get(k)
        )
        failed = state_of == "erro" or (isinstance(code, int) and code != 0)
        state.add({"id": item_id, "tipo": "ferramenta", "nome": "exec_command", "categoria": category, "rotulo": label, "detalhe": _cut(command, INPUT_LIMIT),
                   "lingua": "bash", "saida": _cut(ANSI.sub("", str(output)), OUTPUT_LIMIT), "codigo": code, "estado": "erro" if failed else "ok", "hora": when})  # fmt: skip
    elif key == "filechange":
        changes = item.get("changes") or []
        if isinstance(changes, dict):
            changes = [{"path": p, **(c if isinstance(c, dict) else {})} for p, c in changes.items()]
        files: list[str] = []
        patches: list[str] = []
        for change in changes:
            if not isinstance(change, dict):
                continue
            path = str(change.get("path") or "")
            files.append(_short_path(path, state.cwd))
            diff = change.get("diff") or change.get("unified_diff") or change.get("content") or ""
            kind = change.get("kind") or change.get("type")
            kind = kind.get("type") if isinstance(kind, dict) else kind
            patches.append(f"*** {kind or 'update'}: {path}\n{diff}")
        state.add({"id": item_id, "tipo": "ferramenta", "nome": "apply_patch", "categoria": "edicao", "rotulo": "Editou " + (", ".join(files[:3]) or "arquivos"),
                   "patch": _cut("\n".join(patches), OUTPUT_LIMIT), "estado": state_of, "hora": when})  # fmt: skip
    elif key == "mcptoolcall":
        result = item.get("result") or {}
        text, images = ("", [])
        if isinstance(result, dict):
            text, images = _result_parts(state, result.get("content"), offset, "payload", "item", "result", "content")
            if not text and result.get("structured_content") is not None:
                text = json.dumps(result.get("structured_content"), ensure_ascii=False, indent=2)
        error = item.get("error")
        state.add({"id": item_id, "tipo": "ferramenta", "nome": f"{item.get('server')}__{item.get('tool')}", "categoria": "mcp",
                   "rotulo": f"{item.get('server') or 'mcp'} · {item.get('tool') or ''}", "lingua": "json",
                   "detalhe": _cut(json.dumps(item.get("arguments"), ensure_ascii=False, indent=2), INPUT_LIMIT) if item.get("arguments") is not None else None,
                   "saida": _cut(str((error or {}).get("message") if isinstance(error, dict) else error or text), OUTPUT_LIMIT),
                   "estado": "erro" if error else state_of, "imagens": images, "hora": when})  # fmt: skip
    elif key == "websearch" or (key == "extension" and str(item.get("kind") or "").startswith("web")):
        action = item.get("action") or {}
        queries = action.get("queries") or [action.get("query") or item.get("query") or ""]
        results = [r for r in item.get("results") or [] if isinstance(r, dict)]
        listing = "\n".join(f"- [{r.get('title') or r.get('url')}]({r.get('url')})" for r in results[:10] if r.get("url"))
        state.add({"id": item_id, "tipo": "ferramenta", "nome": "web_search", "categoria": "web", "rotulo": "Pesquisou " + " · ".join(str(q) for q in queries if q)[:140],
                   "saida": listing or None, "lingua": "markdown", "estado": state_of, "hora": when})  # fmt: skip
    elif key == "imageview":
        image = _file_image(str(item.get("path") or ""), state.cwd, check=False)
        state.add({"id": item_id, "tipo": "ferramenta", "nome": "view_image", "categoria": "imagem", "rotulo": f"Viu {_short_path(str(item.get('path') or ''), state.cwd)}",
                   "imagens": [image] if image else [], "estado": "ok", "hora": when})  # fmt: skip
    elif key == "imagegeneration":
        images: list[dict] = []
        saved = item.get("saved_path") or item.get("savedPath") or item.get("path")
        if isinstance(saved, str) and saved:
            found = _file_image(saved, state.cwd, check=False)
            if found:
                images.append({**found, "nome": f"{found['nome']} (gerada)"})
        elif isinstance(item.get("result"), str) and item["result"]:
            images.append({**_ref(state, offset, "payload", "item", "result"), "nome": "Imagem gerada"})
        state.add({"id": item_id, "tipo": "ferramenta", "nome": "image_generation", "categoria": "imagem", "rotulo": "Gerou uma imagem",
                   "detalhe": item.get("revised_prompt") or item.get("revisedPrompt"), "imagens": images, "estado": state_of, "hora": when})  # fmt: skip
    elif key == "contextcompaction":
        _event(state, "Conversa compactada", entry, "compactada")
    elif key in ("plan", "todolist"):
        steps = [
            {"texto": str(s.get("text") or s.get("step") or ""), "estado": "feito" if s.get("completed") or s.get("status") == "completed" else "pendente"}
            for s in item.get("items") or [] if isinstance(s, dict)
        ]  # fmt: skip
        state.add({"id": item_id, "tipo": "plano", "passos": steps, "texto": item.get("text") or None, "hora": when})
    else:
        state.add({"id": item_id, "tipo": "ferramenta", "nome": str(item.get("type")), "categoria": "outra", "rotulo": str(item.get("type") or "ferramenta"), "estado": state_of, "hora": when})


# --- consulta ----------------------------------------------------------------------------------


def page(state: _State, fonte: str = "", apos: int = 0, antes: int | None = None, limite: int = 300) -> dict:
    """O pedaço da conversa que a tela precisa.

    - sem `fonte` igual (primeira vez, transcript trocado, outra leitura): as últimas `limite`;
    - com `antes`: as `limite` anteriores a esse `n` (rolar para cima);
    - senão: só o que nasceu ou mudou depois da versão `apos`.
    """
    limite = max(1, min(limite, 1000))
    with state.lock:
        items = state.items
        answer = {"fonte": state.fonte, "seq": state.seq, "total": len(items), "cwd": state.cwd}
        if antes is not None:
            start = max(0, min(antes, len(items)) - limite)
            return {**answer, "reset": False, "inicio": start, "itens": items[start : max(start, antes)]}
        if fonte != state.fonte or apos <= 0 or apos > state.seq:
            start = max(0, len(items) - limite)
            return {**answer, "reset": True, "inicio": start, "itens": items[start:]}
        changed = [item for item in items if item["v"] > apos]
        return {**answer, "reset": False, "inicio": changed[0]["n"] if changed else len(items), "itens": changed}


def imagem(fonte_path: str, ref: str) -> tuple[bytes, str] | None:
    """Os bytes da imagem que mora dentro do transcript (base64), pela referência do item."""
    offset_text, _sep, dotted = ref.partition(":")
    try:
        offset = int(offset_text)
    except ValueError:
        return None
    path = Path(fonte_path).expanduser()
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            node = json.loads(handle.readline())
    except (OSError, ValueError):
        return None
    for part in dotted.split(".") if dotted else []:
        try:
            node = node[int(part)] if isinstance(node, list) else node[part]
        except (KeyError, IndexError, ValueError, TypeError):
            return None
    return _decode(node)


def _decode(node) -> tuple[bytes, str] | None:
    data, media = None, "image/png"
    if isinstance(node, dict):
        source = node.get("source")
        if isinstance(source, dict) and source.get("type") == "base64":
            data, media = source.get("data"), str(source.get("media_type") or media)
        elif isinstance(node.get("image_url"), str):
            data = node["image_url"]
        elif isinstance(node.get("image_url"), dict):
            data = node["image_url"].get("url")
        elif isinstance(node.get("data"), str):
            data, media = node["data"], str(node.get("mimeType") or node.get("mime_type") or media)
    elif isinstance(node, str):
        data = node
    if not isinstance(data, str) or not data:
        return None
    if data.startswith("data:"):
        header, _sep, data = data.partition(",")
        media = header[5:].split(";")[0] or media
    if not media.startswith("image/"):
        return None
    try:
        return base64.b64decode(data, validate=False), media
    except (binascii.Error, ValueError):
        return None


def image_file(path: str) -> tuple[Path, str] | None:
    """Arquivo de imagem no disco (só imagem: a rota não serve outro tipo de arquivo)."""
    target = Path(os.path.expanduser(path))
    media = IMAGE_TYPES.get(target.suffix.lower())
    if not media or not target.is_absolute() or not target.is_file():
        return None
    return target, media
