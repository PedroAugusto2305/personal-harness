"""Automações da MÊTIS (v0.9.0): o arquivo, as versões e a linguagem dos passos.

Cada automação é um YAML legível em ~/.harness/automacoes/<id>.yaml (o RASCUNHO) e, depois
de publicada, em ~/.harness/automacoes/publicadas/<id>.yaml. O motor só roda a publicada;
editar, pela tela ou por um agente, só mexe no rascunho. A pasta é um git local: cada
rascunho salvo e cada publicação viram commit, e as versões são os commits da publicada.

Formato (as chaves são em português, o Pedro edita à mão se quiser):

    nome: Briefing da manhã
    gatilho: {tipo: agendado, dias: [0, 1, 2, 3, 4], hora: "07:30", recupera_min: 120, x: 0, y: 0}
    passos:
      - {id: tarefas, tipo: ferramenta, titulo: Tarefas do dia, x: 220, y: 0,
         ferramenta: clickup-pessoal__get_tasks, argumentos: {list_id: "123"}}
      - {id: escrever, tipo: agente, titulo: Escrever o briefing, cli: claude,
         pedido: "Com {{Tarefas do dia}}, escreva…", saida: {resumo: texto}}
    ligacoes: [{de: gatilho, para: tarefas}, {de: tarefas, para: escrever}]
    notas: [{id: n1, titulo: Por quê, texto: "…", x: 0, y: 200, w: 220}]

Expressões: {{Nome do passo.campo}} (ou {{id.campo}}), {{hoje}}, {{agora}}, {{entrada}}.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

TRIGGER_ID = "gatilho"
STEP_TYPES = ("ferramenta", "agente", "condicao", "aprovacao", "brain", "esperar")
TRIGGER_TYPES = ("manual", "agendado")
BRAIN_ACTIONS = ("buscar", "ler", "precedentes", "tarefas", "diario")
OUTPUT_TYPES = ("texto", "numero", "lista", "objeto", "sim/nao")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
EXPR_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")


class AutomationError(ValueError):
    pass


def slug(text: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:60] or "automacao"


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(c)).strip()


# --- o desenho -------------------------------------------------------------------------------


def blank(name: str) -> dict:
    return {
        "nome": name.strip() or "Nova automação",
        "descricao": "",
        "gatilho": {"tipo": "manual", "x": 0, "y": 0},
        "passos": [],
        "ligacoes": [],
        "notas": [],
    }


def validate(flow: Any, strict: bool = False) -> dict:
    """Confere e normaliza o desenho; levanta AutomationError com o motivo em português.

    O rascunho aceita passo pela metade (ferramenta ainda sem escolher, agente sem pedido):
    a forma (ids, tipos, ligações, ciclos) vale sempre, e o que falta para rodar só é
    cobrado com strict=True, ao testar e ao publicar."""
    if not isinstance(flow, dict):
        raise AutomationError("a automação precisa ser um objeto (nome, gatilho, passos, ligações)")
    name = str(flow.get("nome") or "").strip()
    if not name:
        raise AutomationError("a automação precisa de um nome")
    trigger = dict(flow.get("gatilho") or {"tipo": "manual"})
    if trigger.get("tipo") not in TRIGGER_TYPES:
        raise AutomationError(f"gatilho desconhecido: {trigger.get('tipo')} (use manual ou agendado)")
    if trigger["tipo"] == "agendado":
        if not re.fullmatch(r"\d{1,2}:\d{2}", str(trigger.get("hora") or "")):
            raise AutomationError("o gatilho agendado precisa da hora no formato 07:30")
        days = trigger.get("dias")
        if not isinstance(days, list) or not days or not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
            raise AutomationError("o gatilho agendado precisa dos dias (0 = segunda … 6 = domingo)")
        trigger["recupera_min"] = int(trigger.get("recupera_min") or 60)
    steps = flow.get("passos") or []
    if not isinstance(steps, list):
        raise AutomationError("passos precisa ser uma lista")
    seen: set[str] = {TRIGGER_ID}
    titles: set[str] = set()
    clean_steps = []
    for raw in steps:
        if not isinstance(raw, dict):
            raise AutomationError("cada passo precisa ser um objeto")
        step = dict(raw)
        sid = str(step.get("id") or "")
        if not ID_RE.fullmatch(sid) or sid in seen:
            raise AutomationError(f"id de passo inválido ou repetido: {sid!r}")
        seen.add(sid)
        if step.get("tipo") not in STEP_TYPES:
            raise AutomationError(f"o passo {sid} tem tipo desconhecido: {step.get('tipo')}")
        title = str(step.get("titulo") or "").strip() or sid
        if fold(title) in titles:
            raise AutomationError(f"dois passos com o mesmo nome: {title} (as expressões usam o nome)")
        titles.add(fold(title))
        step["titulo"] = title
        kind = step["tipo"]
        shape = step.get("saida") or {}
        if kind == "agente" and step.get("cli", "claude") not in ("claude", "codex"):
            raise AutomationError(f"o passo {title}: cli é claude ou codex")
        if kind == "agente" and (not isinstance(shape, dict) or any(v not in OUTPUT_TYPES for v in shape.values())):
            raise AutomationError(f"o passo {title}: saída é campo → {', '.join(OUTPUT_TYPES)}")
        if kind == "brain" and step.get("acao") not in (None, "", *BRAIN_ACTIONS):
            raise AutomationError(f"o passo {title}: ação do Brain é {', '.join(BRAIN_ACTIONS)}")
        if strict:
            missing = {
                "ferramenta": not str(step.get("ferramenta") or "").strip() and "da ferramenta",
                "agente": not str(step.get("pedido") or "").strip() and "do pedido ao agente",
                "condicao": not str(step.get("regra") or "").strip() and "da regra",
                "brain": step.get("acao") not in BRAIN_ACTIONS and "da ação do Brain",
            }.get(kind)
            if missing:
                raise AutomationError(f"o passo {title} precisa {missing}")
        if kind == "esperar":
            step["minutos"] = max(0.0, min(float(step.get("minutos") or 1), 24 * 60))
        clean_steps.append(step)
    kinds = {s["id"]: s["tipo"] for s in clean_steps}
    edges = []
    pairs = set()
    for raw in flow.get("ligacoes") or []:
        src, dst = str(raw.get("de") or ""), str(raw.get("para") or "")
        if src not in seen or dst not in kinds:
            raise AutomationError(f"ligação com passo que não existe: {src} → {dst}")
        branch = raw.get("ramo")
        if kinds.get(src) == "condicao":
            if branch not in ("sim", "não", "nao"):
                raise AutomationError(f"a saída da condição {src} precisa do ramo sim ou não")
            branch = "não" if branch == "nao" else branch
        elif branch:
            branch = None
        if (src, dst, branch) in pairs:
            continue
        pairs.add((src, dst, branch))
        edges.append({"de": src, "para": dst, **({"ramo": branch} if branch else {})})
    if _has_cycle(edges):
        raise AutomationError("as ligações formam um ciclo; automação anda sempre para a frente")
    notes = [dict(n) for n in flow.get("notas") or [] if isinstance(n, dict)]
    return {
        "nome": name,
        "descricao": str(flow.get("descricao") or ""),
        "gatilho": trigger,
        "passos": clean_steps,
        "ligacoes": edges,
        "notas": notes,
    }


def _has_cycle(edges: list[dict]) -> bool:
    graph: dict[str, list[str]] = {}
    for e in edges:
        graph.setdefault(e["de"], []).append(e["para"])
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        state[node] = 1
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1 or (state.get(nxt) is None and visit(nxt)):
                return True
        state[node] = 2
        return False

    return any(state.get(n) is None and visit(n) for n in list(graph))


def layers(flow: dict) -> list[list[str]]:
    """Camadas pelo caminho mais longo a partir do gatilho: o que está na mesma camada roda junto."""
    depth = {TRIGGER_ID: 0}
    changed = True
    edges = flow["ligacoes"]
    while changed:
        changed = False
        for e in edges:
            if e["de"] in depth and depth.get(e["para"], -1) < depth[e["de"]] + 1:
                depth[e["para"]] = depth[e["de"]] + 1
                changed = True
    out: dict[int, list[str]] = {}
    for node, d in depth.items():
        out.setdefault(d, []).append(node)
    return [out[d] for d in sorted(out)]


def downstream(flow: dict, start: str) -> set[str]:
    found, todo = {start}, [start]
    while todo:
        node = todo.pop()
        for e in flow["ligacoes"]:
            if e["de"] == node and e["para"] not in found:
                found.add(e["para"])
                todo.append(e["para"])
    return found


def connectors_used(flow: dict) -> list[str]:
    """Contas de conector que a automação usa (o prefixo antes de __ na ferramenta)."""
    used = []
    for step in flow["passos"]:
        names = [step.get("ferramenta", "")] if step["tipo"] == "ferramenta" else list(step.get("ferramentas") or [])
        for name in names:
            if "__" in str(name):
                account = str(name).split("__", 1)[0]
                if account not in used:
                    used.append(account)
        if step["tipo"] == "brain" and "brain" not in used:
            used.append("brain")
    return used


# --- expressões ---------------------------------------------------------------------------------


def _walk(value: Any, path: str) -> Any:
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            index = int(part[1:-1])
            value = value[index] if isinstance(value, list) and -len(value) <= index < len(value) else None
        elif isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part == "length":
            value = len(value)
        else:
            return None
        if value is None:
            return None
    return value


def lookup(expr: str, scope: dict[str, Any]) -> Any:
    """'Tarefas do dia.itens[0].nome' → o valor. O nome do passo pode ter espaço e acento."""
    folded = fold(expr)
    keys = sorted(scope, key=len, reverse=True)
    for key in keys:
        if folded == key:
            return scope[key]
        if folded.startswith(key + ".") or folded.startswith(key + "["):
            rest = expr.strip()[len(key):].lstrip(".")
            return _walk(scope[key], rest)
    return None


def render(value: Any, scope: dict[str, Any]) -> Any:
    """Troca as expressões. Texto que é só uma expressão vira o valor cru (lista, objeto)."""
    if isinstance(value, dict):
        return {k: render(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, scope) for v in value]
    if not isinstance(value, str) or "{{" not in value:
        return value
    whole = EXPR_RE.fullmatch(value.strip())
    if whole:
        return lookup(whole.group(1), scope)

    def text(match: re.Match) -> str:
        found = lookup(match.group(1), scope)
        if found is None:
            return ""
        return found if isinstance(found, str) else json.dumps(found, ensure_ascii=False)

    return EXPR_RE.sub(text, value)


def make_scope(flow: dict, outputs: dict[str, Any], now: datetime | None = None, entrada: Any = None) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    scope: dict[str, Any] = {"hoje": now.date().isoformat(), "agora": now.isoformat(timespec="minutes"), "entrada": entrada}
    titles = {TRIGGER_ID: "gatilho"} | {s["id"]: s["titulo"] for s in flow["passos"]}
    for sid, value in outputs.items():
        scope[fold(sid)] = value
        if sid in titles:
            scope[fold(titles[sid])] = value
    return scope


# --- condição: uma regra de uma linha, avaliada sem eval ------------------------------------------

_ALLOWED_CMP = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
                ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
                ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}  # fmt: skip
_NAMES = {"true": True, "false": False, "null": None, "verdadeiro": True, "falso": False, "nulo": None, "None": None, "True": True, "False": False}


def _literal(value: Any) -> str:
    return repr(value)


def evaluate_rule(rule: str, scope: dict[str, Any]) -> bool:
    """'{{Tarefas.total}} > 0 and not vazio({{Leads}})' → True/False. Só comparação, e/ou/não,
    números, textos, listas e as funções len, vazio e contem."""
    # e/ou/não viram and/or/not só fora de texto entre aspas e fora das expressões.
    parts = re.split(r"(\{\{.+?\}\}|'[^']*'|\"[^\"]*\")", rule)
    for i, part in enumerate(parts):
        if i % 2:
            if part.startswith("{{"):
                parts[i] = _literal(lookup(part[2:-2].strip(), scope))
            continue
        part = re.sub(r"\be\b", " and ", part)
        part = re.sub(r"\bou\b", " or ", part)
        parts[i] = re.sub(r"\bnão\b|\bnao\b", " not ", part)
    text = "".join(parts)
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise AutomationError(f"regra inválida: {rule}") from exc

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in _NAMES:
                return _NAMES[node.id]
            raise AutomationError(f"nome desconhecido na regra: {node.id} (use {{{{Passo.campo}}}})")
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(e) for e in node.elts]
        if isinstance(node, ast.Dict):
            return {ev(k): ev(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.BoolOp):
            values = [ev(v) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, right_node in zip(node.ops, node.comparators):
                right = ev(right_node)
                fn = _ALLOWED_CMP.get(type(op))
                if fn is None:
                    raise AutomationError("operador não permitido na regra")
                try:
                    if not fn(left, right):
                        return False
                except TypeError:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            args = [ev(a) for a in node.args]
            if node.func.id == "len" and len(args) == 1:
                return len(args[0]) if args[0] is not None else 0
            if node.func.id == "vazio" and len(args) == 1:
                return args[0] in (None, "", [], {})
            if node.func.id == "contem" and len(args) == 2:
                return args[1] in (args[0] or "")
        raise AutomationError("a regra só aceita comparações, e/ou/não, len(), vazio() e contem()")

    return bool(ev(tree))


def check_output(data: Any, shape: dict[str, str]) -> list[str]:
    """Campos que faltam ou vieram no tipo errado, contra o formato combinado do passo de agente."""
    if not shape:
        return []
    if not isinstance(data, dict):
        return ["a saída precisa ser um objeto JSON com " + ", ".join(shape)]
    problems = []
    checks = {"texto": lambda v: isinstance(v, str), "numero": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
              "lista": lambda v: isinstance(v, list), "objeto": lambda v: isinstance(v, dict), "sim/nao": lambda v: isinstance(v, bool)}  # fmt: skip
    for field, kind in shape.items():
        if field not in data:
            problems.append(f"faltou o campo {field} ({kind})")
        elif not checks[kind](data[field]):
            problems.append(f"o campo {field} precisa ser {kind}")
    return problems


def count_items(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        lists = [v for v in value.values() if isinstance(v, list)]
        return len(lists[0]) if len(lists) == 1 else 1
    return 1


# --- o arquivo e as versões ---------------------------------------------------------------------


def dump(flow: dict) -> str:
    return yaml.safe_dump(flow, allow_unicode=True, sort_keys=False, width=110)


class AutomationStore:
    def __init__(self, home: Path) -> None:
        self.dir = home / "automacoes"
        self.published_dir = self.dir / "publicadas"
        self.archive_dir = self.dir / "arquivadas"
        self._lock = threading.Lock()
        self.published_dir.mkdir(parents=True, exist_ok=True)
        self._git_ok = shutil.which("git") is not None
        if self._git_ok and not (self.dir / ".git").exists():
            self._git("init", "-q")
            self._git("config", "user.name", "MÊTIS")
            self._git("config", "user.email", "metis@localhost")

    # git local: histórico do rascunho e versões da publicada
    def _git(self, *args: str) -> str:
        if not self._git_ok:
            return ""
        done = subprocess.run(["git", *args], cwd=self.dir, capture_output=True, text=True, timeout=20)
        return done.stdout if done.returncode == 0 else ""

    def _commit(self, path: Path, message: str) -> None:
        if not self._git_ok:
            return
        rel = str(path.relative_to(self.dir))
        self._git("add", "--", rel)
        if self._git("diff", "--cached", "--name-only", "--", rel).strip():
            self._git("commit", "-q", "-m", message, "--", rel)

    def path(self, automation_id: str) -> Path:
        if not ID_RE.fullmatch(automation_id):
            raise AutomationError("automação não encontrada")
        return self.dir / f"{automation_id}.yaml"

    def published_path(self, automation_id: str) -> Path:
        return self.published_dir / f"{automation_id}.yaml"

    def _read(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (yaml.YAMLError, AutomationError) as exc:
            raise AutomationError(f"{path.name} não abre: {exc}") from exc

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.yaml") if ID_RE.fullmatch(p.stem))

    def draft(self, automation_id: str) -> dict:
        flow = self._read(self.path(automation_id))
        if flow is None:
            raise AutomationError("automação não encontrada")
        return flow

    def mtime(self, automation_id: str) -> float:
        try:
            return self.path(automation_id).stat().st_mtime
        except OSError:
            return 0.0

    def published(self, automation_id: str) -> dict | None:
        return self._read(self.published_path(automation_id))

    def create(self, name: str, flow: dict | None = None) -> str:
        with self._lock:
            base = slug(name)
            automation_id, n = base, 2
            while self.path(automation_id).exists() or (self.archive_dir / f"{automation_id}.yaml").exists():
                automation_id, n = f"{base}-{n}"[:60], n + 1
            data = validate(flow or blank(name))
            path = self.path(automation_id)
            path.write_text(dump(data), encoding="utf-8")
            self._commit(path, f"cria {automation_id}")
            return automation_id

    def save(self, automation_id: str, flow: dict) -> dict:
        data = validate(flow)
        with self._lock:
            path = self.path(automation_id)
            if not path.exists():
                raise AutomationError("automação não encontrada")
            path.write_text(dump(data), encoding="utf-8")
            self._commit(path, f"rascunho {automation_id}")
        return data

    def publish(self, automation_id: str, content: str | None = None) -> int:
        """Grava a publicada (o rascunho, ou o conteúdo de uma versão antiga) e devolve o número da versão."""
        with self._lock:
            text = content if content is not None else dump(self.draft(automation_id))
            validate(yaml.safe_load(text), strict=True)  # publicada é a que roda: nada pela metade
            target = self.published_path(automation_id)
            target.write_text(text, encoding="utf-8")
            number = len(self.versions(automation_id, _locked=True)) + 1
            self._commit(target, f"publica {automation_id} v{number}")
            return number

    def versions(self, automation_id: str, _locked: bool = False) -> list[dict]:
        rel = str(self.published_path(automation_id).relative_to(self.dir))
        raw = self._git("log", "--format=%H|%ct|%s", "--", rel)
        rows = [line.split("|", 2) for line in raw.splitlines() if line.count("|") >= 2]
        total = len(rows)
        return [{"hash": h, "when": float(t), "message": m, "number": total - i} for i, (h, t, m) in enumerate(rows)]

    def version_content(self, automation_id: str, commit: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            raise AutomationError("versão inválida")
        rel = str(self.published_path(automation_id).relative_to(self.dir))
        text = self._git("show", f"{commit}:{rel}")
        if not text:
            raise AutomationError("versão não encontrada")
        return text

    def diff(self, automation_id: str) -> str:
        """Diferença entre a publicada e o rascunho, em linhas do YAML."""
        draft = dump(self.draft(automation_id)).splitlines()
        published = self.published(automation_id)
        before = dump(published).splitlines() if published else []
        return "\n".join(difflib.unified_diff(before, draft, "publicada", "rascunho", lineterm="", n=1))

    def archive(self, automation_id: str) -> None:
        """Tirar da lista sem apagar: rascunho e publicada vão para arquivadas/."""
        with self._lock:
            self.archive_dir.mkdir(exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for src, name in ((self.path(automation_id), f"{automation_id}.yaml"), (self.published_path(automation_id), f"{automation_id}.publicada-{stamp}.yaml")):
                if src.exists():
                    src.rename(self.archive_dir / name)
            self._git("add", "-A")
            self._git("commit", "-q", "-m", f"arquiva {automation_id}")
