"""Uso dos modelos (v0.9.9, pedido do Pedro: "quero ver o tanto gasto"): tokens e custo
equivalente em API de cada modelo, por dia e por projeto, lidos dos registros que as próprias
CLIs gravam no Mac. Nada passa por rede e nenhuma credencial é lida.

- Claude Code: `<pasta da conta>/projects/**/*.jsonl` (também os subagentes). Cada resposta traz
  `message.model` e `message.usage` (entrada, saída, cache gravado de 5 min e de 1 h, cache lido);
  a mesma resposta aparece em várias linhas (uma por bloco) e às vezes em outro arquivo (sessão
  retomada), então conta uma vez só, por `message.id` + `requestId`.
- Codex: `<pasta da conta>/sessions/**/rollout-*.jsonl`. O evento `token_count` traz o total
  acumulado da sessão (a versão atual não separa entrada e saída); vale a diferença entre um
  evento e o anterior, no dia do evento. O modelo é o que aparece no arquivo.

O custo é o que essas respostas custariam na API (o plano não cobra por token): preço de entrada e
saída do modelo, leitura de cache pelo preço do modelo, gravação de cache a 1,25× (5 min) ou
2× (1 h) da entrada, e o dobro no modo rápido. Modelo sem preço conhecido fica só com tokens.

Arquivo sem mudança (tamanho e data iguais) não é relido: a primeira leitura de um mês de
Claude (uns 3 GB) leva ~10 s; as seguintes, só o que a sessão aberta acrescentou.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

from .history import sources

# Prefixo do id → US$ por milhão de tokens: entrada, saída, leitura de cache.
# Fonte: tabela de preços da API da Anthropic (2026-10). O prefixo mais longo vence.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-mythos-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-opus-4-7": (5.0, 25.0, 0.50),
    "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-opus-4-5": (5.0, 25.0, 0.50),
    "claude-opus-4-1": (15.0, 75.0, 1.50),
    "claude-opus-4": (15.0, 75.0, 1.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4": (3.0, 15.0, 0.30),
    "claude-3-7-sonnet": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
    "claude-3-5-haiku": (0.80, 4.0, 0.08),
}
_PREFIXES = sorted(PRICES, key=len, reverse=True)
WRITE_5M = 1.25
WRITE_1H = 2.0

# Campos de cada resposta: entrada, saída, cache gravado 5 min, cache gravado 1 h, cache lido.
FIELDS = ("entrada", "saida", "cache_5m", "cache_1h", "cache_lido")


def price_of(model: str) -> tuple[float, float, float] | None:
    for prefix in _PREFIXES:
        if model.startswith(prefix):
            return PRICES[prefix]
    return None


def cost_of(model: str, vec: tuple[int, int, int, int, int], fast: bool = False) -> float | None:
    price = price_of(model)
    if price is None:
        return None
    entrada, saida, leitura = price
    tin, tout, w5, w1, read = vec
    usd = (tin * entrada + tout * saida + w5 * entrada * WRITE_5M + w1 * entrada * WRITE_1H + read * leitura) / 1_000_000
    return usd * (2 if fast else 1)


_LABEL = re.compile(r"^claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d{1,2}))?(?:-|$)")


def model_label(model: str) -> str:
    """claude-opus-5-5 → Opus 5.5; claude-sonnet-4-20250514 → Sonnet 4; o resto fica como está."""
    match = _LABEL.match(model)
    if not match:
        return model
    family, major, minor = match.groups()
    return f"{family.capitalize()} {major}{'.' + minor if minor else ''}"


@dataclass(frozen=True, slots=True)
class Record:
    """Uma resposta (Claude) ou um trecho de sessão (Codex). Fica na memória do núcleo por até 90
    dias (por arquivo, para não reler): `slots` e textos repetidos compartilhados (`sys.intern`)."""

    key: str  # para não contar duas vezes ("" = não repete)
    ts: float
    provider: str  # claude | codex
    account: str
    model: str
    cwd: str
    session: str
    vec: tuple[int, int, int, int, int]
    total: int  # Codex: só o total; Claude: soma dos campos
    cost: float | None


def _int(value) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _ts(text: str | None) -> float:
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_claude(path: Path, account: str) -> list[Record]:
    out: list[Record] = []
    seen: set[str] = set()  # a mesma resposta aparece numa linha por bloco: uma vez só por arquivo
    account = sys.intern(account)
    with open(path, "rb") as handle:
        for raw in handle:
            # Só as linhas de resposta com uso: o resto (texto, ferramentas) nem é decodificado.
            if b'"usage"' not in raw or b'"assistant"' not in raw:
                continue
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(line, dict) or line.get("type") != "assistant":
                continue
            message = line.get("message") if isinstance(line.get("message"), dict) else {}
            usage = message.get("usage") if isinstance(message.get("usage"), dict) else None
            model = str(message.get("model") or "")
            if not usage or not model or model.startswith("<"):
                continue
            created = _int(usage.get("cache_creation_input_tokens"))
            split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
            one_hour = _int(split.get("ephemeral_1h_input_tokens"))
            five_min = _int(split.get("ephemeral_5m_input_tokens")) if split else created
            if split and five_min + one_hour < created:
                five_min = created - one_hour
            vec = (_int(usage.get("input_tokens")), _int(usage.get("output_tokens")), five_min, one_hour, _int(usage.get("cache_read_input_tokens")))
            key = f"{message.get('id') or ''}:{line.get('requestId') or ''}"
            if key != ":":
                if key in seen:
                    continue
                seen.add(key)
            out.append(
                Record(
                    key=key if key != ":" else "",
                    ts=_ts(line.get("timestamp")),
                    provider="claude",
                    account=account,
                    model=sys.intern(model),
                    cwd=sys.intern(str(line.get("cwd") or "")),
                    session=sys.intern(str(line.get("sessionId") or path.stem)),
                    vec=vec,
                    total=sum(vec),
                    cost=cost_of(model, vec, usage.get("speed") == "fast"),
                )
            )
    return out


_MODEL_RE = re.compile(rb'"model"\s*:\s*"([^"]{2,80})"')


def parse_codex(path: Path, account: str, fallback_model: str = "codex") -> list[Record]:
    out: list[Record] = []
    model = ""
    cwd = ""
    session = path.stem
    last_total = 0
    with open(path, "rb") as handle:
        for raw in handle:
            if not model:
                found = _MODEL_RE.search(raw)
                if found:
                    model = found.group(1).decode("utf-8", "replace")
            if b'"session_meta"' in raw and not cwd:
                try:
                    payload = json.loads(raw).get("payload") or {}
                    cwd = str(payload.get("cwd") or "")
                    session = str(payload.get("id") or payload.get("session_id") or session)
                except (ValueError, AttributeError):
                    pass
                continue
            if b'"token_count"' not in raw:
                continue
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            payload = line.get("payload") if isinstance(line, dict) else None
            info = payload.get("info") if isinstance(payload, dict) else None
            totals = info.get("total_token_usage") if isinstance(info, dict) else None
            if not isinstance(totals, dict):
                continue
            total = _int(totals.get("total_tokens"))
            if total <= last_total:
                continue
            delta = total - last_total
            last_total = total
            # Quando a versão do Codex separa entrada e saída, cada trecho leva a sua parte.
            tin = _int(totals.get("input_tokens"))
            tout = _int(totals.get("output_tokens")) + _int(totals.get("reasoning_output_tokens"))
            cached = _int(totals.get("cached_input_tokens"))
            vec = (0, 0, 0, 0, 0)
            if tin or tout:
                share = delta / max(1, total)
                vec = (round((tin - cached) * share), round(tout * share), 0, 0, round(cached * share))
            out.append(
                Record(
                    key="",
                    ts=_ts(line.get("timestamp")),
                    provider="codex",
                    account=account,
                    model=model or fallback_model,
                    cwd=cwd,
                    session=session,
                    vec=vec,
                    total=delta,
                    cost=None,
                )
            )
    return out


def codex_default_model(codex_home: Path) -> str:
    try:
        text = (codex_home / "config.toml").read_text(encoding="utf-8")
    except OSError:
        return "codex"
    match = re.search(r'^model\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else "codex"


class ModelUsage:
    """Lê os registros das CLIs e monta o relatório. Guarda o que já leu por arquivo."""

    def __init__(
        self,
        accounts: Callable[[], dict],
        projects: Callable[[], list[dict]],
        worktrees: Path,
        defaults: Callable[[], dict[str, Path] | None] = lambda: None,
    ) -> None:
        self.accounts = accounts
        self.projects = projects
        self.worktrees = worktrees
        self.defaults = defaults
        self._files: dict[str, tuple[float, int, list[Record]]] = {}
        self._lock = threading.Lock()
        self._report: dict[int, tuple[float, dict]] = {}

    # --- leitura -----------------------------------------------------------------------------

    def _candidates(self, since: float) -> Iterable[tuple[str, str, Path, str]]:
        for cli, (account, _name), folder in sources(self.accounts(), self.defaults()):
            if cli == "claude":
                root = folder / "projects"
                pattern = "*.jsonl"
                model = ""
            else:
                root = folder / "sessions"
                pattern = "rollout-*.jsonl"
                model = codex_default_model(folder)
            if not root.is_dir():
                continue
            for path in root.rglob(pattern):
                try:
                    if path.stat().st_mtime >= since:
                        yield cli, account, path, model
                except OSError:
                    continue

    def records(self, since: float) -> list[Record]:
        out: list[Record] = []
        alive: set[str] = set()
        for cli, account, path, model in self._candidates(since):
            key = str(path)
            alive.add(key)
            try:
                stat = path.stat()
            except OSError:
                continue
            cached = self._files.get(key)
            if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                rows = cached[2]
            else:
                try:
                    rows = parse_claude(path, account) if cli == "claude" else parse_codex(path, account, model)
                except OSError:
                    continue
                self._files[key] = (stat.st_mtime, stat.st_size, rows)
            out.extend(r for r in rows if r.ts >= since)
        # Só sai da memória o que foi apagado ou passou de 90 dias: a consulta de hoje (barra de
        # baixo) não pode desfazer o que o painel de 30 dias leu.
        horizon = time.time() - 91 * 86400
        for key in [k for k in self._files if k not in alive]:
            mtime = self._files[key][0]
            if mtime < horizon or not os.path.exists(key):
                self._files.pop(key, None)
        return out

    # --- relatório ---------------------------------------------------------------------------

    def project_of(self, cwd: str, known: list[tuple[str, str]]) -> str:
        if not cwd:
            return "—"
        path = Path(cwd)
        try:
            rel = path.relative_to(self.worktrees)
            if rel.parts:
                return rel.parts[0]
        except ValueError:
            pass
        best = ""
        name = ""
        for label, root in known:
            if (cwd == root or cwd.startswith(root.rstrip("/") + "/")) and len(root) > len(best):
                best, name = root, label
        if name:
            return name
        # Pastas de agentes dentro do repositório (Maestri: `<repo>/.maestri/roles/<id>`; Claude:
        # `<repo>/.claude/worktrees/<x>`) contam para o repositório; o andar do Maestri
        # (`.maestri/floors/<repo>--<fase>`) conta para o repositório do andar.
        parts = path.parts
        for i, part in enumerate(parts):
            if part.startswith(".") and i > 1:
                if part == ".maestri" and i + 2 < len(parts) and parts[i + 1] == "floors":
                    return parts[i + 2].split("--")[0]
                path = Path(*parts[:i])
                break
        if path == Path.home():
            return "~"
        return path.name or cwd

    def report(self, days: int = 30, now: float | None = None, max_age: float = 60.0) -> dict:
        days = max(1, min(int(days), 90))
        moment = now if now is not None else time.time()
        cached = self._report.get(days)
        if now is None and cached and moment - cached[0] < max_age:
            return cached[1]
        with self._lock:
            first = date.fromtimestamp(moment) - timedelta(days=days - 1)
            since = datetime.combine(first, datetime.min.time()).timestamp()
            rows = self.records(since)
            known = [(str(p.get("name") or ""), str(p.get("path") or "")) for p in self.projects() if p.get("path")]
            result = self._build(rows, first, days, moment, known)
        if now is None:
            self._report[days] = (moment, result)
        return result

    def _build(self, rows: list[Record], first: date, days: int, moment: float, known: list[tuple[str, str]]) -> dict:
        seen: set[str] = set()
        today = date.fromtimestamp(moment).isoformat()
        day_keys = [(first + timedelta(days=i)).isoformat() for i in range(days)]
        by_day = {d: {"dia": d, "custo": 0.0, "tokens": 0, "modelos": {}, "tokens_modelos": {}} for d in day_keys}
        by_model: dict[tuple[str, str], dict] = {}
        by_project: dict[str, dict] = {}
        totals = {"custo": 0.0, "tokens": 0, "respostas": 0, **{f: 0 for f in FIELDS}}
        today_totals = {"custo": 0.0, "tokens": 0, "respostas": 0}
        sessions: set[str] = set()
        no_price: set[str] = set()
        cwd_project: dict[str, str] = {}
        for row in rows:
            if row.key:
                if row.key in seen:
                    continue
                seen.add(row.key)
            day = date.fromtimestamp(row.ts).isoformat()
            if day not in by_day:
                continue
            cost = row.cost or 0.0
            if row.cost is None and row.provider == "claude":
                no_price.add(row.model)
            label = model_label(row.model)
            sessions.add(f"{row.provider}:{row.session}")
            # Por dia
            bucket = by_day[day]
            bucket["custo"] += cost
            bucket["tokens"] += row.total
            bucket["modelos"][label] = bucket["modelos"].get(label, 0.0) + (cost if row.provider == "claude" else 0.0)
            bucket["tokens_modelos"][label] = bucket["tokens_modelos"].get(label, 0) + row.total
            # Por modelo
            entry = by_model.setdefault(
                (row.provider, row.model),
                {"provedor": row.provider, "modelo": row.model, "nome": label, "custo": 0.0, "tokens": 0, "respostas": 0, "sessoes": set(), **{f: 0 for f in FIELDS}, "com_preco": row.cost is not None or row.provider == "codex"},
            )
            entry["custo"] += cost
            entry["tokens"] += row.total
            entry["respostas"] += 1
            entry["sessoes"].add(row.session)
            for name, value in zip(FIELDS, row.vec):
                entry[name] += value
                totals[name] += value
            # Por projeto
            if row.cwd not in cwd_project:
                cwd_project[row.cwd] = self.project_of(row.cwd, known)
            project = by_project.setdefault(cwd_project[row.cwd], {"projeto": cwd_project[row.cwd], "custo": 0.0, "tokens": 0, "respostas": 0, "modelos": {}})
            project["custo"] += cost
            project["tokens"] += row.total
            project["respostas"] += 1
            project["modelos"][label] = project["modelos"].get(label, 0) + row.total
            totals["custo"] += cost
            totals["tokens"] += row.total
            totals["respostas"] += 1
            if day == today:
                today_totals["custo"] += cost
                today_totals["tokens"] += row.total
                today_totals["respostas"] += 1
        models = sorted(by_model.values(), key=lambda m: (m["custo"], m["tokens"]), reverse=True)
        for model in models:
            model["sessoes"] = len(model["sessoes"])
            model["custo"] = round(model["custo"], 4)
        projects = sorted(by_project.values(), key=lambda p: (p["custo"], p["tokens"]), reverse=True)[:12]
        for project in projects:
            project["custo"] = round(project["custo"], 4)
        for bucket in by_day.values():
            bucket["custo"] = round(bucket["custo"], 4)
            bucket["modelos"] = {k: round(v, 4) for k, v in bucket["modelos"].items()}
        totals["custo"] = round(totals["custo"], 4)
        today_totals["custo"] = round(today_totals["custo"], 4)
        return {
            "dias": days,
            "desde": day_keys[0],
            "ate": day_keys[-1],
            "total": {**totals, "sessoes": len(sessions)},
            "hoje": today_totals,
            "por_dia": [by_day[d] for d in day_keys],
            "por_modelo": models,
            "por_projeto": projects,
            "sem_preco": sorted(no_price),
            "atualizado": moment,
        }


PLAN_FILE = "uso-planos.json"


def load_plan_usage(home: Path, now: float | None = None) -> dict[str, dict]:
    """Último limite do plano do Claude visto por conta, para não sumir quando o núcleo reinicia.
    Janela que já zerou (o reset passou) volta a 0%."""
    moment = now if now is not None else time.time()
    try:
        data = json.loads((home / PLAN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    for account, limits in (data.get("claude") or {}).items() if isinstance(data, dict) else []:
        if not isinstance(limits, dict):
            continue
        fixed = dict(limits)
        for window in ("five_hour", "seven_day"):
            item = limits.get(window)
            if isinstance(item, dict) and item.get("resets_at") and item["resets_at"] < moment:
                fixed[window] = {"used_pct": 0.0, "resets_at": None}
        out[str(account)] = fixed
    return out


def save_plan_usage(home: Path, claude: dict[str, dict]) -> None:
    """Grava num temporário próprio e troca de uma vez (duas sessões podem gravar juntas)."""
    path = home / PLAN_FILE
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".uso-planos-", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"claude": claude}, ensure_ascii=False))
        os.replace(tmp, path)
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
