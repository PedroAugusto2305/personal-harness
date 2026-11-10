"""Importar um workflow do n8n para uma automação da MÊTIS (v0.9.8, parte 4).

Lê o JSON exportado do n8n (ou o que o MCP do n8n devolve) e traduz nó a nó para os passos da
MÊTIS. O resultado é uma PROPOSTA (nada é salvo) com a lista do que o Pedro precisa revisar:
webhook não existe na MÊTIS, código e HTTP do n8n foram adaptados, nós de serviço viraram a
ferramenta mais parecida das contas ligadas. Credenciais nunca vêm junto: o n8n guarda só a
referência, e cabeçalho ou parâmetro com cara de segredo é trocado por um marcador.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from . import automations
from .automations import ID_RE, TRIGGER_ID, AutomationError, fold, slug

X_SCALE = 1.25  # o passo de agente da MÊTIS é mais largo que o nó do n8n

SECRET_NAME = re.compile(r"authorization|api[-_ ]?key|token|secret|senha|password|bearer|cookie", re.I)
SECRET_VALUE = re.compile(r"\b(sk-[A-Za-z0-9_-]{10,}|xox[abpr]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|pk_[A-Za-z0-9_]{10,}|Bearer\s+[A-Za-z0-9._-]{10,})")
SECRET_MARK = "<SEGREDO REMOVIDO>"

SERVICE_KIND = {
    "slack": "slack",
    "clickup": "clickup",
    "notion": "notion",
    "github": "github",
    "gmail": "google",
    "googlecalendar": "google",
    "googledrive": "google",
    "googlesheets": "google",
    "googledocs": "google",
}

# Palavras do n8n (recurso e operação) → palavras que aparecem nas ferramentas da central.
SYNONYMS = {
    "post": ["enviar", "mensagem", "send", "post", "message"],
    "send": ["enviar", "send", "mensagem", "rascunho"],
    "message": ["mensagem", "message", "chat"],
    "create": ["criar", "create", "nova", "novo", "add"],
    "update": ["atualizar", "update", "mudar", "editar"],
    "get": ["ler", "get", "buscar", "read", "fetch"],
    "getall": ["listar", "list", "buscar", "search"],
    "search": ["buscar", "search", "procurar"],
    "task": ["tarefa", "task"],
    "issue": ["issue"],
    "page": ["pagina", "page"],
    "database": ["banco", "database"],
    "event": ["evento", "agenda", "event"],
    "file": ["arquivo", "drive", "file"],
    "draft": ["rascunho", "draft"],
    "comment": ["comentario", "comment"],
}

AI_TYPES = ("agent", "openai", "chainllm", "chainsummarization", "chainretrievalqa", "lmchatopenai", "anthropic", "lmchatanthropic", "informationextractor", "textclassifier", "sentimentanalysis")
SUBNODE = re.compile(r"^(lmchat|lm|memory|tool|outputparser|embeddings|vectorstore|textsplitter|document|retriever)", re.I)
WEEKDAY_N8N_TO_METIS = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}


class ImportError_(ValueError):
    """Workflow que não dá para ler (vira 400)."""


def _short(node_type: str) -> str:
    return str(node_type or "").split(".")[-1]


def _number(value: Any) -> float | None:
    """O número de um parâmetro do n8n, ou None quando ele é uma expressão (={{ … }}) ou texto."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value) if isinstance(value, (int, float)) else float(str(value).strip().replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _clean_secrets(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        # Par {name, value} com nome de segredo (cabeçalho, parâmetro de consulta), esteja ele
        # dentro de outro objeto ou numa lista, como o n8n guarda os cabeçalhos.
        if "value" in value and SECRET_NAME.search(str(value.get("name", ""))):
            return {**value, "value": SECRET_MARK}
        return {k: _clean_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_secrets(v, key) for v in value]
    if isinstance(value, str):
        if key and SECRET_NAME.search(key) and value and not value.startswith("="):
            return SECRET_MARK
        return SECRET_VALUE.sub(SECRET_MARK, value)
    return value


# --- expressões do n8n → expressões da MÊTIS ---------------------------------------------------


def convert_expr(text: Any, prev_title: str | None) -> str:
    """'={{ $json.status }}' → '{{Passo anterior.status}}'; $('Nó').item.json.x → {{Nó.x}}."""
    raw = str(text if text is not None else "")
    if raw.startswith("="):
        raw = raw[1:]

    def field_path(path: str) -> str:
        path = re.sub(r"\[['\"]([^'\"]+)['\"]\]", r".\1", path)
        path = re.sub(r"\[(\d+)\]", r".\1", path)
        return path.strip(".")

    def inner(expr: str) -> str:
        expr = expr.strip()
        m = re.fullmatch(r"\$\(['\"](.+?)['\"]\)\.(?:item|first\(\)|last\(\)|all\(\)\[\d+\])\.json((?:\.[\w$]+|\[[^\]]+\])*)", expr)
        if m:
            path = field_path(m.group(2))
            return "{{" + m.group(1) + (f".{path}" if path else "") + "}}"
        m = re.fullmatch(r"\$node\[['\"](.+?)['\"]\]\.json((?:\.[\w$]+|\[[^\]]+\])*)", expr)
        if m:
            path = field_path(m.group(2))
            return "{{" + m.group(1) + (f".{path}" if path else "") + "}}"
        m = re.fullmatch(r"\$json((?:\.[\w$]+|\[[^\]]+\])*)", expr)
        if m:
            path = field_path(m.group(1))
            base = prev_title or "entrada"
            if base == "entrada":
                return "{{entrada" + (f".{path}" if path else "") + "}}"
            return "{{" + base + (f".{path}" if path else "") + "}}"
        if expr in ("$now", "$today", "$now.toISO()"):
            return "{{agora}}" if "now" in expr else "{{hoje}}"
        return "{{" + expr + "}}"

    return re.sub(r"\{\{\s*(.+?)\s*\}\}", lambda m: inner(m.group(1)), raw)


def _is_simple(converted: str) -> bool:
    return "$" not in converted and "=>" not in converted


# --- condição ----------------------------------------------------------------------------------

OPS = {
    "equals": "==", "equal": "==", "notequals": "!=", "notequal": "!=", "gt": ">", "larger": ">", "lt": "<", "smaller": "<",
    "gte": ">=", "largerequal": ">=", "lte": "<=", "smallerequal": "<=",
}  # fmt: skip


def _literal(value: Any, prev: str | None) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value if value is not None else "")
    if "{{" in text or text.startswith("="):
        converted = convert_expr(text, prev).strip()
        return converted if _is_simple(converted) and re.fullmatch(r"\{\{[^{}]+\}\}", converted) else None
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _one_condition(left: Any, op: str, right: Any, prev: str | None) -> str | None:
    a = _literal(left, prev)
    if a is None:
        return None
    op = re.sub(r"[^a-z]", "", str(op).lower())
    if op in ("isempty", "empty", "notexists"):
        return f"vazio({a})"
    if op in ("isnotempty", "notempty", "exists"):
        return f"não vazio({a})"
    if op in ("true",):
        return f"{a} == true"
    if op in ("false",):
        return f"{a} == false"
    b = _literal(right, prev)
    if b is None:
        return None
    if op in ("contains",):
        return f"contem({a}, {b})"
    if op in ("notcontains",):
        return f"não contem({a}, {b})"
    if op in OPS:
        return f"{a} {OPS[op]} {b}"
    return None


def translate_if(params: dict, prev: str | None) -> str | None:
    conditions = params.get("conditions")
    if not isinstance(conditions, dict):
        return None
    parts: list[str] = []
    if isinstance(conditions.get("conditions"), list):  # if v2
        joiner = " ou " if str(conditions.get("combinator", "and")).lower() == "or" else " e "
        for c in conditions["conditions"]:
            operator = c.get("operator") or {}
            part = _one_condition(c.get("leftValue"), operator.get("operation", ""), c.get("rightValue"), prev)
            if part is None:
                return None
            parts.append(part)
        return joiner.join(parts) if parts else None
    joiner = " ou " if str(params.get("combineOperation", "all")).lower() == "any" else " e "
    for group in ("string", "number", "boolean", "dateTime"):  # if v1
        for c in conditions.get(group) or []:
            part = _one_condition(c.get("value1"), c.get("operation", "equal"), c.get("value2"), prev)
            if part is None:
                return None
            parts.append(part)
    return joiner.join(parts) if parts else None


# --- gatilho agendado ----------------------------------------------------------------------------


def translate_schedule(node: dict) -> tuple[dict | None, str]:
    """A agenda do n8n como gatilho agendado, ou (None, o motivo) quando não traduz."""
    try:
        return _translate_schedule(node)
    except (ValueError, TypeError):  # hora, dia ou intervalo vindo de expressão, sem número fixo
        return None, "a agenda do n8n usa expressão (ou valor que não é número) na hora, no dia ou no intervalo"


def _translate_schedule(node: dict) -> tuple[dict | None, str]:
    params = node.get("parameters") or {}
    short = _short(node.get("type", "")).lower()
    if short == "cron":
        items = ((params.get("triggerTimes") or {}).get("item")) or []
        days: set[int] = set()
        times: set[str] = set()
        for item in items:
            mode = item.get("mode")
            hour, minute = int(item.get("hour", 14)), int(item.get("minute", 0))
            times.add(f"{hour:02d}:{minute:02d}")
            if mode == "everyDay":
                days.update(range(7))
            elif mode == "everyWeek":
                days.add(WEEKDAY_N8N_TO_METIS.get(int(item.get("weekday", 1)), 0))
            else:
                return None, f"agenda do n8n no modo {mode} não tem igual na MÊTIS"
        if len(times) == 1 and days:
            return {"tipo": "agendado", "dias": sorted(days), "hora": times.pop(), "recupera_min": 60}, ""
        return None, "agenda com mais de um horário: a MÊTIS agenda um horário por automação"
    rules = ((params.get("rule") or {}).get("interval")) or [{}]
    rule = rules[0] if rules else {}
    if len(rules) > 1:
        return None, "agenda com mais de uma regra"
    field = rule.get("field", "days")
    hour, minute = int(rule.get("triggerAtHour", 0)), int(rule.get("triggerAtMinute", 0))
    if field == "days" and int(rule.get("daysInterval", 1)) == 1:
        return {"tipo": "agendado", "dias": list(range(7)), "hora": f"{hour:02d}:{minute:02d}", "recupera_min": 60}, ""
    if field == "weeks" and int(rule.get("weeksInterval", 1)) == 1:
        days = sorted({WEEKDAY_N8N_TO_METIS.get(int(d), 0) for d in rule.get("triggerAtDay") or [1]})
        return {"tipo": "agendado", "dias": days, "hora": f"{hour:02d}:{minute:02d}", "recupera_min": 60}, ""
    if field == "cronExpression":
        parts = str(rule.get("expression", "")).split()
        if len(parts) == 6:
            parts = parts[1:]  # segundos na frente
        if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit() and parts[2] == "*" and parts[3] == "*":
            dow = parts[4]
            if dow == "*":
                days = list(range(7))
            else:
                try:
                    days = sorted({WEEKDAY_N8N_TO_METIS[int(d)] for d in _expand(dow)})
                except (ValueError, KeyError):
                    return None, f"cron {rule.get('expression')} não traduz"
            return {"tipo": "agendado", "dias": days, "hora": f"{int(parts[1]):02d}:{int(parts[0]):02d}", "recupera_min": 60}, ""
        return None, f"cron {rule.get('expression')} não traduz para um horário fixo"
    return None, f"o n8n roda de tempos em tempos ({field}); a MÊTIS agenda por horário: escolha um horário ou use sondagem"


def _expand(dow: str) -> list[int]:
    out: list[int] = []
    for piece in dow.split(","):
        if "-" in piece:
            a, b = piece.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(piece))
    return out


# --- código ------------------------------------------------------------------------------------


def code_from_node(node: dict) -> tuple[str, str]:
    """(linguagem, código na convenção da MÊTIS) a partir de um nó Code/Function do n8n."""
    params = node.get("parameters") or {}
    short = _short(node.get("type", "")).lower()
    if params.get("language") in ("python", "pythonNative"):
        body = str(params.get("pythonCode") or "")
        code = (
            f"# Código do nó \"{node.get('name')}\" do n8n, adaptado: _input.all() vira a lista de entrada.\n"
            "class _Item(dict):\n    @property\n    def json(self):\n        return self\n"
            "_itens = [_Item(i) if isinstance(i, dict) else _Item({'valor': i}) for i in (entrada if isinstance(entrada, list) else [entrada])]\n"
            "class _Entrada:\n    def all(self):\n        return _itens\n    def first(self):\n        return _itens[0] if _itens else None\n"
            "_input = _Entrada()\n"
            "def _n8n():\n" + "\n".join("    " + line for line in body.splitlines()) + "\n"
            "_resultado = _n8n()\n"
            "saida = [dict(i.get('json', i)) if isinstance(i, dict) else i for i in _resultado] if isinstance(_resultado, list) else _resultado\n"
        )  # fmt: skip
        return "python", code
    body = str(params.get("jsCode") or params.get("functionCode") or params.get("code") or "")
    per_item = short == "functionitem" or params.get("mode") == "runOnceForEachItem"
    head = (
        f"// Código do nó \"{node.get('name')}\" do n8n, adaptado: $input, items e $json vêm da entrada.\n"
        "const items = (Array.isArray(entrada) ? entrada : [entrada]).map((json) => ({ json }));\n"
        "const $input = { all: () => items, first: () => items[0], last: () => items[items.length - 1], item: items[0] };\n"
    )
    if per_item:
        code = head + (
            "const resultado = [];\n"
            "for (const item of items) {\n  const $json = item.json;\n"
            "  const $input = { all: () => items, first: () => items[0], last: () => items[items.length - 1], item };\n"
            "  const r = await (async () => {\n" + "\n".join("    " + line for line in body.splitlines()) + "\n  })();\n"
            "  resultado.push(r && r.json ? r.json : r ?? $json);\n}\n"
            "saida = resultado;\n"
        )  # fmt: skip
    else:
        code = head + (
            "const $json = items[0] ? items[0].json : {};\n"
            "const resultado = await (async () => {\n" + "\n".join("  " + line for line in body.splitlines()) + "\n})();\n"
            "saida = Array.isArray(resultado) ? resultado.map((i) => (i && i.json ? i.json : i)) : resultado;\n"
        )  # fmt: skip
    return "javascript", code


def code_from_set(node: dict, prev: str | None) -> str:
    params = node.get("parameters") or {}
    fields: list[tuple[str, Any]] = []
    for a in ((params.get("assignments") or {}).get("assignments")) or []:
        fields.append((str(a.get("name", "")), a.get("value")))
    for group in ("string", "number", "boolean"):
        for v in ((params.get("values") or {}).get(group)) or []:
            fields.append((str(v.get("name", "")), v.get("value")))
    # Set v3 (assignments) só mantém os outros campos se pedir; o Set antigo mantém, a não ser "keepOnlySet".
    keep = bool(params.get("includeOtherFields")) if "assignments" in params else not params.get("keepOnlySet")
    lines = [f"// Campos do nó \"{node.get('name')}\" do n8n.", "const base = entrada && typeof entrada === 'object' && !Array.isArray(entrada) ? entrada : {};"]
    lines.append("saida = {" + (" ...base," if keep else "") + "};")
    for name, value in fields:
        if not name:
            continue
        if isinstance(value, str) and (value.startswith("=") or "{{" in value):
            js = _js_expr(value)
        else:
            js = json.dumps(value, ensure_ascii=False)
        lines.append(f"saida[{json.dumps(name, ensure_ascii=False)}] = {js};")
    return "\n".join(lines) + "\n"


def _js_expr(value: str) -> str:
    """'={{ $json.x }}' → entrada?.x; texto com expressões → template string."""
    raw = value[1:] if value.startswith("=") else value

    def piece(expr: str) -> str:
        expr = expr.strip()
        expr = re.sub(r"\$json", "entrada", expr)
        expr = re.sub(r"\$\(['\"](.+?)['\"]\)\.(?:item|first\(\))\.json", lambda m: f"passos[{json.dumps(m.group(1), ensure_ascii=False)}]", expr)
        return expr

    whole = re.fullmatch(r"\s*\{\{\s*(.+?)\s*\}\}\s*", raw)
    if whole:
        return piece(whole.group(1))
    parts = re.split(r"\{\{\s*(.+?)\s*\}\}", raw)
    out = []
    for i, part in enumerate(parts):
        out.append("${" + piece(part) + "}" if i % 2 else part.replace("`", "\\`").replace("${", "\\${"))
    return "`" + "".join(out) + "`"


def code_from_http(node: dict) -> str:
    params = _clean_secrets(node.get("parameters") or {})
    method = str(params.get("method") or params.get("requestMethod") or "GET").upper()
    url = params.get("url") or ""
    url_js = _js_expr(url) if isinstance(url, str) and (url.startswith("=") or "{{" in url) else json.dumps(url, ensure_ascii=False)
    headers: dict[str, Any] = {}
    for h in ((params.get("headerParameters") or {}).get("parameters")) or []:
        headers[str(h.get("name", ""))] = h.get("value", "")
    query: dict[str, Any] = {}
    for q in ((params.get("queryParameters") or {}).get("parameters")) or []:
        query[str(q.get("name", ""))] = q.get("value", "")
    body: Any = None
    if params.get("jsonBody"):
        body = params.get("jsonBody")
    elif (params.get("bodyParameters") or {}).get("parameters"):
        body = {str(p.get("name", "")): p.get("value", "") for p in params["bodyParameters"]["parameters"]}
    lines = [
        f"// Requisição do nó \"{node.get('name')}\" do n8n. Confira a URL, os cabeçalhos e a autenticação:",
        "// credenciais e segredos do n8n não vêm junto (estão como <SEGREDO REMOVIDO>).",
        f"const url = new URL({url_js});",
    ]
    for k, v in query.items():
        value = _js_expr(v) if isinstance(v, str) and (v.startswith("=") or "{{" in v) else json.dumps(v, ensure_ascii=False)
        lines.append(f"url.searchParams.set({json.dumps(k, ensure_ascii=False)}, {value});")
    lines.append(f"const headers = {json.dumps({**headers, **({'content-type': 'application/json'} if body is not None else {})}, ensure_ascii=False)};")
    if body is not None:
        if isinstance(body, str) and (body.startswith("=") or "{{" in body):
            lines.append(f"const body = {_js_expr(body)};")
        else:
            lines.append(f"const body = JSON.stringify({json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body});")
    lines.append(f"const resposta = await fetch(url, {{ method: {json.dumps(method)}, headers{', body' if body is not None else ''} }});")
    lines.append("const texto = await resposta.text();")
    lines.append("let dados;\ntry {\n  dados = JSON.parse(texto);\n} catch {\n  dados = texto;\n}")
    lines.append("if (!resposta.ok) throw new Error(`HTTP ${resposta.status}: ${String(texto).slice(0, 300)}`);")
    lines.append("saida = dados;")
    return "\n".join(lines) + "\n"


# --- nós de serviço → ferramenta mais parecida ----------------------------------------------------


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", fold(text)) if len(w) > 1}


def best_tool(node: dict, kind: str, tools: list[dict], accounts: dict[str, str]) -> str | None:
    params = node.get("parameters") or {}
    wanted: set[str] = set()
    for key in ("resource", "operation"):
        value = fold(str(params.get(key) or ""))
        if not value:
            continue
        wanted.add(value)
        for w in _words(value):
            wanted.update(SYNONYMS.get(w, [w]))
        wanted.update(SYNONYMS.get(value.replace(" ", ""), []))
    if not wanted:
        wanted = {"buscar", "search", "list", "listar"}
    best, score = None, 0
    for tool in tools:
        account = str(tool.get("conta") or "")
        if accounts.get(account) != kind:
            continue
        hay = _words(f"{tool['nome']} {tool.get('descricao', '')}")
        hits = len(hay & wanted)
        if hits > score:
            best, score = str(tool["nome"]), hits
    return best


# --- a tradução --------------------------------------------------------------------------------


def load_workflow(raw: Any) -> dict:
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ImportError_("o texto não é um JSON de workflow do n8n") from exc
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    found = find_workflow(data)
    if found is None:
        raise ImportError_("isso não parece um workflow do n8n (faltam nodes e connections)")
    return found


def find_workflow(data: Any) -> dict | None:
    """O workflow dentro da resposta (o MCP do n8n devolve {success, data: {...}})."""
    todo = [data]
    while todo:
        item = todo.pop(0)
        if isinstance(item, dict):
            if isinstance(item.get("nodes"), list) and isinstance(item.get("connections"), dict):
                return item
            todo.extend(item.values())
        elif isinstance(item, list):
            todo.extend(item)
        elif isinstance(item, str) and item.lstrip().startswith("{") and "nodes" in item:
            try:
                todo.append(json.loads(item))
            except json.JSONDecodeError:
                pass
    return None


def translate(workflow: Any, tools: list[dict] | None = None, accounts: dict[str, str] | None = None) -> dict:
    """{"proposta", "revisar": [{passo, motivo}], "nome"}; a proposta passa no validate."""
    wf = load_workflow(workflow)
    tools = tools or []
    accounts = accounts or {}
    name = " ".join(str(wf.get("name") or "Importado do n8n").split())[:110] or "Importado do n8n"
    nodes = [n for n in wf["nodes"] if isinstance(n, dict) and n.get("name")]
    by_name = {str(n["name"]): n for n in nodes}
    connections = wf.get("connections") or {}

    # Sub-nós de IA (modelo, memória, ferramenta) só se ligam ao agente: não viram passo.
    sub_of: dict[str, str] = {}
    for src, outputs in connections.items():
        for kind, groups in (outputs or {}).items():
            if kind == "main":
                continue
            for group in groups or []:
                for link in group or []:
                    if isinstance(link, dict) and link.get("node"):
                        sub_of[src] = str(link["node"])
    main_in: dict[str, list[tuple[str, int]]] = {}
    for src, outputs in connections.items():
        for index, group in enumerate((outputs or {}).get("main") or []):
            for link in group or []:
                if isinstance(link, dict) and link.get("node") in by_name:
                    main_in.setdefault(str(link["node"]), []).append((str(src), index))

    review: list[dict] = []
    taken_ids: set[str] = {TRIGGER_ID}
    taken_titles: set[str] = set()
    step_of: dict[str, str] = {}  # nome do nó → id do passo
    passthrough: set[str] = set()
    steps: list[dict] = []
    notes: list[dict] = []
    trigger: dict | None = None
    trigger_nodes: list[str] = [
        str(n["name"]) for n in nodes if _short(str(n.get("type") or "")).lower().endswith("trigger") or _short(str(n.get("type") or "")).lower() in ("cron", "webhook", "start", "interval")
    ]
    first_trigger: str | None = None
    xs = [float((n.get("position") or [0, 0])[0]) for n in nodes] or [0.0]
    ys = [float((n.get("position") or [0, 0])[1]) for n in nodes] or [0.0]
    x0, y0 = min(xs), min(ys)

    def pos(node: dict) -> tuple[float, float]:
        p = node.get("position") or [x0, y0]
        return round((float(p[0]) - x0) * X_SCALE), round(float(p[1]) - y0)

    def prev_title(node_name: str) -> str | None:
        for src, _ in main_in.get(node_name, []):
            if src in by_name and src not in trigger_nodes:
                return str(by_name[src]["name"])
        return None

    def new_step(node: dict, kind: str, **fields: Any) -> dict:
        sid = slug(str(node["name"]))[:50] or "passo"
        if not ID_RE.fullmatch(sid):
            sid = "passo"
        base, n = sid, 2
        while sid in taken_ids:
            sid, n = f"{base}-{n}", n + 1
        taken_ids.add(sid)
        title = " ".join(str(node["name"]).split())[:80]
        base_title, n = title, 2
        while fold(title) in taken_titles:
            title, n = f"{base_title} {n}", n + 1
        taken_titles.add(fold(title))
        x, y = pos(node)
        step = {"id": sid, "titulo": title, "tipo": kind, "x": x, "y": y, **fields}
        step_of[str(node["name"])] = sid
        steps.append(step)
        return step

    def flag(title: str, reason: str) -> None:
        review.append({"passo": title, "motivo": reason})

    for node in nodes:
        node_name = str(node["name"])
        node_type = str(node.get("type") or "")
        short = _short(node_type).lower()
        params = node.get("parameters") or {}
        prev = prev_title(node_name)
        if node_name in sub_of or SUBNODE.match(short) and short not in AI_TYPES:
            continue
        if short == "stickynote":
            x, y = pos(node)
            text = str(params.get("content") or "")
            notes.append({"id": f"n{len(notes) + 1}", "titulo": "Nota do n8n", "texto": SECRET_VALUE.sub(SECRET_MARK, text)[:2000], "x": x, "y": y, "w": int(_number(params.get("width")) or 240)})
            continue
        if short == "noop":
            passthrough.add(node_name)
            continue
        is_trigger = short.endswith("trigger") or short in ("cron", "webhook", "start", "interval")
        if is_trigger:
            if first_trigger is not None:
                flag(node_name, "o n8n tinha mais de um gatilho; a MÊTIS usa um só e este virou entrada do mesmo gatilho")
                continue
            first_trigger = node_name
            x, y = pos(node)
            if short in ("scheduletrigger", "cron"):
                translated, why = translate_schedule(node)
                trigger = {**(translated or {"tipo": "manual"}), "x": x, "y": y}
                if translated is None:
                    flag(node_name, why + "; ficou manual")
            elif short in ("manualtrigger", "start"):
                trigger = {"tipo": "manual", "x": x, "y": y}
            elif short in ("webhook", "formtrigger"):
                trigger = {"tipo": "manual", "x": x, "y": y}
                flag(node_name, "webhook não existe na MÊTIS (só roda com o Mac acordado): ficou manual; troque por agendado, evento ou sondagem")
            else:
                service = short.removesuffix("trigger")
                trigger = {"tipo": "manual", "x": x, "y": y}
                flag(node_name, f"gatilho do {service} ficou manual; uma sondagem numa ferramenta de leitura da conta faz o mesmo")
            continue
        if short in ("if", "switch", "filter"):
            rule = translate_if(params, prev)
            if short == "switch":
                rule = None
                rules = ((params.get("rules") or {}).get("values") or (params.get("rules") or {}).get("rules")) or []
                if rules:
                    first = rules[0]
                    conds = first.get("conditions") if isinstance(first, dict) else None
                    if isinstance(conds, dict):
                        rule = translate_if({"conditions": conds}, prev)
            step = new_step(node, "condicao", regra=rule or "")
            if short == "switch":
                flag(step["titulo"], "switch do n8n virou sim/não: a primeira saída é o sim, as outras vão pelo não")
            if short == "filter":
                flag(step["titulo"], "filtro do n8n virou condição: o que passa vai pelo sim")
            if not rule:
                flag(step["titulo"], "a condição do n8n não é uma comparação simples: escreva a regra")
            continue
        if short in ("code", "function", "functionitem"):
            language, code = code_from_node(node)
            step = new_step(node, "codigo", linguagem=language, descricao=f"Código do nó {node_name} do n8n", codigo=code, tempo_limite_s=30)
            flag(step["titulo"], "código do n8n adaptado ($input, items, $json): confira antes de publicar")
            continue
        if short == "set":
            step = new_step(node, "codigo", linguagem="javascript", descricao=f"Campos do nó {node_name} do n8n", codigo=code_from_set(node, prev), tempo_limite_s=30)
            continue
        if short == "httprequest":
            method = str(params.get("method") or params.get("requestMethod") or "GET").upper()
            # Requisição que manda ou muda algo fora (POST, PUT, DELETE…) fica marcada: no teste não roda.
            writes = {"escreve": True} if method not in ("GET", "HEAD", "OPTIONS") else {}
            step = new_step(node, "codigo", linguagem="javascript", descricao=f"Requisição HTTP do nó {node_name} do n8n", codigo=code_from_http(node), tempo_limite_s=60, **writes)
            flag(step["titulo"], "HTTP do n8n virou código com fetch: confira a URL e a autenticação (as credenciais não vêm do n8n)"
                 + (f"; como ele manda dados ({method}), no teste não roda e o que faria vai para a sua DM" if writes else ""))
            continue
        if short == "wait":
            raw = params.get("amount") or params.get("value") or 1
            amount = _number(raw)
            unit = str(params.get("unit") or "minutes")
            factor = {"seconds": 1 / 60, "minutes": 1, "hours": 60, "days": 1440}.get(unit, 1)
            step = new_step(node, "esperar", minutos=round(min((amount or 1) * factor, 1440), 2))
            if amount is None:
                flag(step["titulo"], f"o tempo da espera vinha de uma expressão do n8n ({str(raw)[:80]}): ficou um tempo fixo, ajuste")
            if params.get("resume") not in (None, "timeInterval"):
                flag(step["titulo"], "a espera do n8n era por webhook ou data: ficou um tempo fixo")
            continue
        if short in AI_TYPES or "langchain" in node_type and not SUBNODE.match(short):
            prompt = params.get("text") or params.get("prompt") or ""
            if not prompt and isinstance(params.get("messages"), dict):
                values = params["messages"].get("values") or params["messages"].get("messageValues") or []
                prompt = "\n".join(str(v.get("content") or v.get("message") or "") for v in values if isinstance(v, dict))
            system = ((params.get("options") or {}).get("systemMessage")) or ""
            request = convert_expr(prompt, prev).strip() or f"Faça o que o nó {node_name} do n8n fazia."
            if system:
                request = f"{convert_expr(system, prev).strip()}\n\n{request}"
            step = new_step(node, "agente", cli="claude", pedido=request, saida={"resposta": "texto"}, troca_cota=True)
            flag(step["titulo"], "agente de IA do n8n virou um Claude pelo plano: confira o pedido, as expressões e a saída")
            continue
        kind = SERVICE_KIND.get(short)
        if kind:
            tool = best_tool(node, kind, tools, accounts)
            if tool:
                step = new_step(node, "ferramenta", ferramenta=tool, argumentos={})
                keys = ", ".join(sorted(k for k in params if k not in ("resource", "operation", "authentication")))
                flag(step["titulo"], f"nó {short} virou a ferramenta {tool}: preencha os argumentos" + (f" (no n8n: {keys})" if keys else ""))
                continue
            step = new_step(node, "agente", cli="claude", pedido=f"Faça o que o nó {node_name} ({short}: {params.get('resource', '')} {params.get('operation', '')}) do n8n fazia, com a entrada {{{{entrada}}}}.", saida={})
            flag(step["titulo"], f"nenhuma conta do {short} ligada em Conectores com ferramenta parecida: virou agente")
            continue
        step = new_step(node, "agente", cli="claude", pedido=f"Faça o que o nó {node_name} ({short}) do n8n fazia, com a entrada {{{{entrada}}}}.", saida={})
        flag(step["titulo"], f"nó {short} do n8n não tem igual na MÊTIS: virou um agente")

    if trigger is None:
        trigger = {"tipo": "manual", "x": round(-260), "y": 0}
        if steps:
            flag(steps[0]["titulo"], "o workflow não tinha gatilho: a automação ficou manual")

    # Ligações: saída 0/1 da condição viram sim/não; noOp passa direto; gatilhos extras saem do gatilho.
    def resolve(node_name: str, seen: set[str] | None = None) -> list[str]:
        """Passos que o nó representa como destino (atravessa noOp)."""
        seen = seen or set()
        if node_name in step_of:
            return [step_of[node_name]]
        if node_name in passthrough and node_name not in seen:
            seen.add(node_name)
            out = []
            for group in (connections.get(node_name) or {}).get("main") or []:
                for link in group or []:
                    if isinstance(link, dict) and link.get("node"):
                        out.extend(resolve(str(link["node"]), seen))
            return out
        return []

    kinds = {s["id"]: s["tipo"] for s in steps}
    edges: list[dict] = []
    pairs: set[tuple] = set()

    def add(src: str, dst: str, branch: str | None) -> None:
        key = (src, dst, branch)
        if key in pairs or src == dst:
            return
        pairs.add(key)
        edges.append({"de": src, "para": dst, **({"ramo": branch} if branch else {})})

    for src_name, outputs in connections.items():
        groups = (outputs or {}).get("main") or []
        if src_name in trigger_nodes:
            src = TRIGGER_ID
        elif src_name in step_of:
            src = step_of[src_name]
        else:
            continue
        for index, group in enumerate(groups):
            branch = None
            if kinds.get(src) == "condicao":
                branch = "sim" if index == 0 else "não"
            for link in group or []:
                if not isinstance(link, dict) or not link.get("node"):
                    continue
                for dst in resolve(str(link["node"])):
                    add(src, dst, branch)
    # Passo sem ninguém antes começa pelo gatilho.
    has_input = {e["para"] for e in edges}
    for step in steps:
        if step["id"] not in has_input:
            add(TRIGGER_ID, step["id"], None)
    # Condição sem um dos ramos não quebra o desenho; ligação vinda de condição sem ramo ganha "sim".
    for edge in edges:
        if kinds.get(edge["de"]) == "condicao" and "ramo" not in edge:
            edge["ramo"] = "sim"

    flow = {
        "nome": name,
        "descricao": f"Importada do n8n ({len(nodes)} nós).",
        "gatilho": trigger,
        "passos": steps,
        "ligacoes": edges,
        "notas": notes,
    }
    if review:
        ys_steps = [float(s["y"]) for s in steps] or [0.0]
        flow["notas"].append(
            {"id": f"n{len(notes) + 1}", "titulo": "Revisar (importado do n8n)", "texto": "\n".join(f"- {r['passo']}: {r['motivo']}" for r in review)[:3000], "x": 0, "y": max(ys_steps) + 180, "w": 340}
        )  # fmt: skip
    try:
        checked = automations.validate(flow)
    except AutomationError as exc:
        raise ImportError_(f"a tradução não fechou: {exc}") from exc
    return {"proposta": checked, "revisar": review, "nome": name}


# --- pelo MCP do n8n ligado como conector --------------------------------------------------------


def _pick_tool(names: list[str], kind: str) -> str | None:
    lowered = {n: fold(n) for n in names}
    if kind == "list":
        exact = [n for n, f in lowered.items() if f in ("n8n_list_workflows", "list_workflows")]
        loose = [n for n, f in lowered.items() if "workflow" in f and ("list" in f or "listar" in f or "search" in f)]
    else:
        exact = [n for n, f in lowered.items() if f in ("n8n_get_workflow", "get_workflow")]
        loose = [n for n, f in lowered.items() if "workflow" in f and ("get" in f or "ler" in f or "read" in f) and "list" not in f]
    return (exact or loose or [None])[0]


def _payload(result: Any) -> Any:
    if isinstance(result, dict):
        if result.get("structuredContent") is not None:
            return result["structuredContent"]
        texts = [c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
        text = "\n".join(texts).strip()
        try:
            return json.loads(text)
        except ValueError:
            return text
    return result


def list_from_account(client: Any) -> list[dict]:
    names = [str(t.get("name")) for t in client.tools()]
    tool = _pick_tool(names, "list")
    if tool is None:
        raise ImportError_("esta conta não tem uma ferramenta de listar workflows do n8n (ex.: n8n_list_workflows)")
    data = _payload(client.call(tool, {}))
    todo, found = [data], []
    while todo and not found:
        item = todo.pop(0)
        if isinstance(item, list) and item and all(isinstance(i, dict) and "id" in i and "name" in i for i in item):
            found = item
        elif isinstance(item, dict):
            todo.extend(item.values())
        elif isinstance(item, list):
            todo.extend(item)
    return [{"id": str(w["id"]), "nome": str(w["name"]), "ativo": bool(w.get("active"))} for w in found]


def fetch_from_account(client: Any, workflow_id: str) -> dict:
    names = [str(t.get("name")) for t in client.tools()]
    tool = _pick_tool(names, "get")
    if tool is None:
        raise ImportError_("esta conta não tem uma ferramenta de ler workflow do n8n (ex.: n8n_get_workflow)")
    result = client.call(tool, {"id": str(workflow_id)})
    if isinstance(result, dict) and result.get("isError"):
        raise ImportError_(f"o n8n não devolveu o workflow: {str(_payload(result))[:300]}")
    found = find_workflow(_payload(result))
    if found is None:
        raise ImportError_("o n8n não devolveu o workflow (sem nodes e connections)")
    return found
