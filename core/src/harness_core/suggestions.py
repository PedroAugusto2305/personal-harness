"""Sugestões entre projetos (momento 3 dos precedentes): cada registro novo do Brain procura
outros projetos onde ele vale, e o Claude julga se vale mesmo.

1. A cada passada do agendador, os registros (decisão, incidente, aprendizado, entrega) que
   ainda não foram vistos são os novos. Na primeira passada, tudo o que já existe vira
   "visto": a MÊTIS não julga o vault inteiro de uma vez.
2. Para cada registro novo, os vetores acham os outros projetos com registros bem parecidos
   (z >= 3,3, no máximo dois projetos). Sem candidato, acaba aí, sem gastar nada.
3. Com candidato, um `claude -p` com o modelo leve (Haiku, pelo plano) lê o registro, o
   momento de cada projeto candidato (tarefas abertas, decisões recentes, os registros
   parecidos) e diz se aplica, por quê, e a decisão já escrita para o projeto alvo.
4. A sugestão fica pendente na MÊTIS (aba Brain do painel, Hoje, leitor de notas). Aceitar
   chama o `brain.py registrar` do Pedro: vira decisão aceita na pasta do projeto alvo,
   ligada à nota de origem. Recusar só arquiva.

Teto de chamadas do juiz por dia (DAILY_MAX), para nunca pesar na cota do plano.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .brain_index import RECORD_TYPES, TYPE_ICON, BrainIndex, fold
from .claude_print import ClaudePrintError
from .kanban import parse_tasks
from .vault import Vault, VaultError, split_frontmatter

Z_SUGGEST = 3.3
DAILY_MAX = 25
PER_SCAN = 4
BRAIN_SCRIPT = Path.home() / ".claude" / "skills" / "brain-registrar" / "scripts" / "brain.py"
BAD_TITLE = re.compile(r'[\[\]#^|/\\:*?"<>]')

JUDGE_PROMPT = """Você é o juiz de precedentes do Brain, o segundo cérebro do Pedro Aquino (vault Obsidian com um projeto por pasta e uma nota por decisão, incidente, aprendizado e entrega).
Um registro NOVO acabou de entrar no projeto de origem. A busca por significado achou projetos onde ele talvez valha. Decida, para cada projeto candidato, se o registro deveria virar uma DECISÃO no projeto candidato.

Seja exigente. "aplica": true só se o registro mudaria uma escolha concreta ou evitaria um erro concreto no projeto candidato, considerando o que ele faz agora (tarefas abertas, decisões recentes). Parecido no assunto não basta. Se o candidato já tem uma decisão que cobre isso, "aplica": false e diga qual. Na dúvida, false.

REGISTRO NOVO
Projeto de origem: {source_project}
Tipo: {source_tipo} · Data: {source_date}
Título: {source_title}
Resumo: {source_resumo}
Trecho:
{source_body}

PROJETOS CANDIDATOS
{candidates}

Responda SÓ com um objeto JSON, sem texto antes ou depois:
{{"projetos": [{{"projeto": "<nome exato do candidato>", "aplica": true ou false, "motivo": "<uma frase: por que aplica ou não>", "titulo": "<se aplica: a decisão para o projeto candidato, como frase afirmada, sem data e sem os caracteres [ ] # ^ | / \\\\ : * ? \\" < >>", "resumo": "<se aplica: uma ou duas frases com o porquê, citando o projeto de origem>"}}]}}
Português do Brasil, direto. Nunca invente fato que não está no texto."""


class SuggestionError(RuntimeError):
    pass


Judge = Callable[[str], dict]
Registrar = Callable[[list[str], dict[str, str]], str]


def clean_title(title: str) -> str:
    title = BAD_TITLE.sub(" ", title)
    title = " ".join(title.split()).strip(" .-")
    return title[:150]


def run_registrar(args: list[str], env: dict[str, str]) -> str:
    done = subprocess.run([sys.executable, str(BRAIN_SCRIPT), *args],
                          env=env, cwd=str(Path.home()), capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise SuggestionError(f"o brain.py recusou: {(done.stderr or done.stdout).strip()[:400]}")
    return done.stdout


class Suggestions:
    def __init__(
        self,
        home: Path,
        brain: BrainIndex,
        vault: Vault,
        judge: Judge | None = None,
        registrar: Registrar = run_registrar,
        publish: Callable[[dict], None] = lambda _event: None,
    ) -> None:
        self.db = home / "sugestoes.db"
        self.brain = brain
        self.vault = vault
        self.judge = judge
        self.registrar = registrar
        self.publish = publish
        self._lock = threading.Lock()
        self.last_scan: dict = {}
        home.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(
                """
                create table if not exists meta(key text primary key, value text);
                create table if not exists seen(key text primary key, path text, at real);
                create table if not exists judged(at real, day text, source text, ok integer);
                create table if not exists suggestions(
                    id integer primary key, created real, source_path text, source_title text, source_tipo text,
                    source_project text, target_project text, title text, resumo text, motivo text,
                    matches text, z real, status text default 'pendente', decided real, note text);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    # --- leitura -------------------------------------------------------------------

    @staticmethod
    def _dict(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["matches"] = json.loads(item.get("matches") or "[]")
        return item

    def list(self, project: str | None = None, status: str | None = "pendente", limit: int = 50) -> list[dict]:
        where, params = [], []
        if project:
            where.append("target_project = ?")
            params.append(project)
        if status:
            where.append("status = ?")
            params.append(status)
        sql = "select * from suggestions" + (" where " + " and ".join(where) if where else "") + " order by created desc limit ?"
        with self._connect() as con:
            return [self._dict(r) for r in con.execute(sql, (*params, limit))]

    def get(self, suggestion_id: int) -> dict:
        with self._connect() as con:
            row = con.execute("select * from suggestions where id = ?", (suggestion_id,)).fetchone()
        if row is None:
            raise SuggestionError("sugestão não encontrada")
        return self._dict(row)

    def for_note(self, path: str) -> list[dict]:
        """Sugestões que nasceram desta nota ou que viraram esta nota."""
        with self._connect() as con:
            rows = con.execute("select * from suggestions where source_path = ? or note = ? order by created desc", (path, path)).fetchall()
        return [self._dict(r) for r in rows]

    def judged_today(self, now: datetime | None = None) -> int:
        day = (now or datetime.now().astimezone()).date().isoformat()
        with self._connect() as con:
            return con.execute("select count(*) from judged where day = ?", (day,)).fetchone()[0]

    def status(self) -> dict:
        with self._connect() as con:
            counts = {r["status"]: r["n"] for r in con.execute("select status, count(*) n from suggestions group by status")}
            baseline = con.execute("select value from meta where key = 'baseline'").fetchone()
        return {
            "counts": counts,
            "judged_today": self.judged_today(),
            "daily_max": DAILY_MAX,
            "watching_since": baseline["value"] if baseline else None,
            "last_scan": self.last_scan,
            "judge": self.judge is not None,
        }

    # --- varredura ------------------------------------------------------------------

    def _records(self) -> list[dict]:
        con = self.brain._connect()
        try:
            rows = con.execute(
                f"select path, title, tipo, projeto, status, data, resumo from notes where tipo in ({','.join('?' * len(RECORD_TYPES))}) "
                "and coalesce(status, '') != 'substituida' order by data, mtime",
                RECORD_TYPES,
            ).fetchall()
        finally:
            con.close()
        return [dict(r) for r in rows]

    def _mark(self, con: sqlite3.Connection, record: dict) -> None:
        con.execute("insert or replace into seen(key, path, at) values (?, ?, ?)", (fold(record["title"]), record["path"], time.time()))

    def _project_moment(self, name: str) -> str:
        try:
            note = self.vault.project(name)
            text = note.path.read_text(encoding="utf-8")
        except (VaultError, OSError):
            return f"Projeto: {name} (sem nota de projeto)"
        meta, body = split_frontmatter(text)
        tasks = [t.text for t in parse_tasks(text) if t.state != "concluida"][:8]
        con = self.brain._connect()
        try:
            decisions = [
                f"{r['title']} ({r['status'] or 'aceita'})"
                for r in con.execute(
                    "select title, status from notes where projeto = ? and tipo = 'decisao' and coalesce(status, '') != 'substituida' "
                    "order by data desc, mtime desc limit 6",
                    (name,),
                )
            ]
            resumo = con.execute("select resumo from notes where path = ?", (self.vault.rel(note.path),)).fetchone()
        finally:
            con.close()
        lines = [f"Projeto: {name}", f"Sobre: {(resumo['resumo'] if resumo else '') or meta.get('descricao', '') or '(sem resumo)'}"]
        lines.append("Tarefas abertas: " + ("; ".join(tasks) if tasks else "nenhuma"))
        lines.append("Decisões recentes: " + ("; ".join(decisions) if decisions else "nenhuma"))
        return "\n".join(lines)

    def _prompt(self, record: dict, groups: list[dict]) -> str:
        try:
            _meta, body = split_frontmatter(self.vault.resolve(record["path"]).read_text(encoding="utf-8"))
        except (VaultError, OSError):
            body = ""
        blocks = []
        for group in groups:
            similar = "\n".join(f"  - {TYPE_ICON.get(m['tipo'], '·')} {m['title']}: {(m['resumo'] or '')[:220]}" for m in group["matches"])
            blocks.append(f"### {group['project']}\n{self._project_moment(group['project'])}\nRegistros parecidos já existentes nele:\n{similar}")
        return JUDGE_PROMPT.format(
            source_project=record["projeto"] or "(sem projeto)",
            source_tipo=record["tipo"],
            source_date=record["data"] or "?",
            source_title=record["title"],
            source_resumo=record["resumo"] or "",
            source_body=body.strip()[:1800],
            candidates="\n\n".join(blocks),
        )

    def scan(self, now: datetime | None = None, wait: float = 60.0) -> dict:
        """Uma passada: devolve o que fez (para a tela e para os testes)."""
        if not self._lock.acquire(blocking=False):
            return {"skipped": "outra varredura em andamento"}
        try:
            return self._scan(now, wait)
        finally:
            self._lock.release()

    def _scan(self, now: datetime | None, wait: float) -> dict:
        now = now or datetime.now().astimezone()
        report = {"at": time.time(), "new": 0, "candidates": 0, "judged": 0, "created": [], "errors": []}
        if not self.vault.available:
            return report
        self.brain.refresh(max_age=0)
        records = self._records()
        with self._connect() as con:
            baseline = con.execute("select value from meta where key = 'baseline'").fetchone()
            if baseline is None:
                for record in records:
                    self._mark(con, record)
                con.execute("insert into meta(key, value) values ('baseline', ?)", (now.isoformat(timespec="seconds"),))
                report["baseline"] = len(records)
                self.last_scan = report
                return report
            seen = {r["key"] for r in con.execute("select key from seen")}
        new = [r for r in records if fold(r["title"]) not in seen]
        report["new"] = len(new)
        if not new:
            self.last_scan = report
            return report
        self.brain.sync_vectors(wait=wait)
        for record in new[:PER_SCAN]:
            if self.brain.note_vector(record["path"]) is None:
                continue  # modelo ainda não carregou: fica para a próxima passada
            groups = self.brain.neighbor_projects(record["path"], z_min=Z_SUGGEST)
            if not groups:
                with self._connect() as con:
                    self._mark(con, record)
                continue
            report["candidates"] += 1
            if self.judge is None or self.judged_today(now) >= DAILY_MAX:
                continue  # sem juiz ou teto do dia: tenta de novo amanhã
            try:
                verdict = self.judge(self._prompt(record, groups))
                ok = True
            except (ClaudePrintError, OSError, ValueError) as exc:
                report["errors"].append(f"{record['title']}: {exc}")
                verdict, ok = {}, False
            with self._connect() as con:
                con.execute("insert into judged(at, day, source, ok) values (?, ?, ?, ?)", (time.time(), now.date().isoformat(), record["path"], int(ok)))
                if not ok:
                    continue
                report["judged"] += 1
                by_name = {g["project"]: g for g in groups}
                for item in verdict.get("projetos") or []:
                    if not isinstance(item, dict) or not item.get("aplica"):
                        continue
                    group = by_name.get(str(item.get("projeto", "")).strip())
                    title = clean_title(str(item.get("titulo") or ""))
                    if group is None or not title:
                        continue
                    matches = [{"title": m["title"], "path": m["path"], "tipo": m["tipo"], "z": m["z"]} for m in group["matches"]]
                    sid = con.execute(
                        "insert into suggestions(created, source_path, source_title, source_tipo, source_project, target_project, "
                        "title, resumo, motivo, matches, z) values (?,?,?,?,?,?,?,?,?,?,?)",
                        (time.time(), record["path"], record["title"], record["tipo"], record["projeto"] or "", group["project"],
                         title, str(item.get("resumo") or "").strip(), str(item.get("motivo") or "").strip(), json.dumps(matches, ensure_ascii=False), group["z"]),
                    ).lastrowid
                    report["created"].append(sid)
                self._mark(con, record)
        self.last_scan = report
        if report["created"]:
            self.publish({"type": "suggestions", "created": report["created"]})
        return report

    # --- decisão do Pedro --------------------------------------------------------------

    def accept(self, suggestion_id: int, title: str | None = None, resumo: str | None = None) -> dict:
        item = self.get(suggestion_id)
        if item["status"] != "pendente":
            raise SuggestionError(f"esta sugestão já foi {item['status']}")
        title = clean_title(title or item["title"])
        resumo = " ".join((resumo or item["resumo"] or "").split())
        if not title or not resumo:
            raise SuggestionError("a decisão precisa de título e resumo")
        if self.brain.known_titles([title]):
            raise SuggestionError("já existe uma nota com esse título no Brain; mude o título")
        args = ["registrar", "--tipo", "decisao", "--nota", title, "--resumo", resumo, "--projeto", item["target_project"],
                "--liga", item["source_title"], "--status", "aceita"]  # fmt: skip
        env = {**os.environ, "BRAIN_VAULT": str(self.vault.root), "BRAIN_REGISTRAR": "off"}
        output = self.registrar(args, env)
        self.brain.refresh(max_age=0)
        path = ""
        try:
            path = self.brain.note(title=title)["path"]
            self._fill(path, item)
        except (VaultError, OSError):
            path = ""
        with self._connect() as con:
            con.execute("update suggestions set status = 'aceita', decided = ?, note = ?, title = ?, resumo = ? where id = ?",
                        (time.time(), path, title, resumo, suggestion_id))
        self.publish({"type": "suggestions", "decided": suggestion_id})
        return {**self.get(suggestion_id), "output": output.strip()}

    def _fill(self, path: str, item: dict) -> None:
        """Completa as seções da nota nova com o que a sugestão sabe (o resto fica para preencher)."""
        file = self.vault.resolve(path)
        text = file.read_text(encoding="utf-8")
        today = datetime.now().astimezone().date().isoformat()
        context = (
            f"Veio de uma sugestão de precedente da MÊTIS em {today}: [[{item['source_title']}]], de [[{item['source_project']}]]. "
            f"A busca por significado achou registros parecidos neste projeto e o juiz (Claude) avaliou: {item['motivo']}"
        )
        choice = f"{item['resumo']}\n\nAceita pelo Pedro na MÊTIS em {today}."
        text = text.replace("## 🌍 Contexto\n\n<!-- preencher -->", f"## 🌍 Contexto\n\n{context}", 1)
        text = text.replace("## ✅ Escolha e porquê\n\n<!-- preencher -->", f"## ✅ Escolha e porquê\n\n{choice}", 1)
        file.write_text(text, encoding="utf-8")

    def reject(self, suggestion_id: int) -> dict:
        item = self.get(suggestion_id)
        if item["status"] != "pendente":
            raise SuggestionError(f"esta sugestão já foi {item['status']}")
        with self._connect() as con:
            con.execute("update suggestions set status = 'recusada', decided = ? where id = ?", (time.time(), suggestion_id))
        self.publish({"type": "suggestions", "decided": suggestion_id})
        return self.get(suggestion_id)


def render_pending(items: list[dict]) -> list[str]:
    """Linhas para o início de sessão: sugestões esperando o Pedro neste projeto."""
    lines = []
    for item in items[:5]:
        lines.append(f"- 💡 sugestão #{item['id']}: {item['title']} (de [[{item['source_title']}]], {item['source_project']}): {item['motivo'][:200]}")
    return lines
