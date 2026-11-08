"""Índice do Brain: busca por palavra (SQLite FTS5), leitura com backlinks e precedentes v1.

O índice mora em ~/.harness/brain.db e é só um cache: apagar o arquivo não perde nada, ele
é refeito do vault. A cada consulta, o núcleo confere a data das notas (uns 10 ms para o
vault inteiro) e reindexa só o que mudou.

Precedentes v1 = busca por palavra: os termos mais raros do contexto do projeto (tarefas
abertas e registros recentes) procuram decisões, incidentes, aprendizados e entregas de
OUTROS projetos. É um ponto de partida; a busca por significado e o julgamento do modelo
ficam para a v0.8 (docs/MAPA.md).
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from pathlib import Path

from .kanban import parse_tasks
from .vault import Vault, VaultError, abstract, iter_notes, link_target, split_frontmatter, wikilinks

SCHEMA = 3
RECORD_TYPES = ("decisao", "incidente", "aprendizado", "entrega")
TYPE_ICON = {"decisao": "⚖️", "incidente": "🔥", "aprendizado": "💡", "entrega": "🛠️", "projeto": "🎯"}
HIGHLIGHT = ("\x02", "\x03")
MAX_BODY = 200_000

# Palavras que não distinguem nota nenhuma: artigos, preposições e o vocabulário do próprio vault.
STOPWORDS = set(
    """
    a ao aos as ate com como da das de do dos e ela ele em entre essa esse esta este eu foi isso
    ja la mais mas me mesmo na nas nao no nos o os ou para pela pelas pelo pelos por pra que se sem
    ser seu sua so sobre sao tambem tem um uma uns umas ver vez via vai foi sera era estao esta
    antes depois ainda agora hoje ontem amanha cada todo toda todos todas tudo nada algo outro outra
    quando onde porque qual quais quem muito pouco bem fica ficar feito fazer faz deve pode precisa
    projeto projetos nota notas decisao decisoes incidente aprendizado entrega registro brain pedro
    voce voces lido lida lidos lidas conta contar vinha vem veio dia dias semana mes falta faltam usar usa
    uso novo nova novos novas primeiro primeira segundo certo sempre nunca aqui ali assim entao
    dentro fora junto parte vale ter tinha ficou passou passa volta voltar acho deu dar
    the and for with from that this are was not you
    """.split()
)


# Nuvens do grafo por área do projeto (docs/DESIGN.md): o grupo sai da `area:` da nota do projeto.
GRAPH_GROUPS = (
    ("carreira", "Carreira e estudo", ("carreira", "estudo")),
    ("trabalho", "Trabalho", ("crm", "marketing", "seller", "trabalho")),
    ("clientes", "Clientes", ("client",)),
    ("pessoal", "Pessoal", ("financ", "saude", "rotina", "pessoal")),
)
GROUP_LABEL = {key: label for key, label, _ in GRAPH_GROUPS} | {"brain": "Brain e conhecimento", "semarea": "Projeto sem área"}


def area_group(area: str) -> str:
    folded = fold(area)
    for key, _label, needles in GRAPH_GROUPS:
        if any(n in folded for n in needles):
            return key
    return "semarea"


def fold(text: str) -> str:
    """minúsculas e sem acento: 'Decisão' → 'decisao'."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def words(text: str) -> list[str]:
    """Palavras que contam, com repetição (a repetição pesa nos precedentes)."""
    return [w for w in re.findall(r"[a-z0-9]{3,}", fold(text)) if w not in STOPWORDS and not w.isdigit()]


def terms(text: str) -> list[str]:
    return list(dict.fromkeys(words(text)))


def _fts_term(word: str) -> str:
    # Plural e variações simples: "webhooks" acha "webhook" (prefixo a partir de 5 letras).
    if len(word) >= 6 and word.endswith("s"):
        word = word[:-1]
    return f'"{word}"*' if len(word) >= 5 else f'"{word}"'


class BrainIndex:
    def __init__(self, vault: Vault, db_path: Path) -> None:
        self.vault = vault
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._checked = 0.0

    # --- infraestrutura -----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("pragma journal_mode=wal")
        if con.execute("pragma user_version").fetchone()[0] != SCHEMA:
            for table in ("vocab", "fts", "links", "notes"):
                con.execute(f"drop table if exists {table}")
            con.executescript(
                """
                create table notes(id integer primary key, path text unique, title text, folded text,
                                   tipo text, projeto text, status text, data text, resumo text, mtime real);
                create index notes_folded on notes(folded);
                create table links(src integer, dst text);
                create index links_dst on links(dst);
                create virtual table fts using fts5(title, resumo, body, tokenize='unicode61 remove_diacritics 2');
                create virtual table vocab using fts5vocab(fts, row);
                """
            )
            con.execute(f"pragma user_version={SCHEMA}")
        return con

    def refresh(self, max_age: float = 2.0) -> dict:
        """Reindexa o que mudou no vault. Consultas seguidas dentro de max_age não reconferem."""
        if not self.vault.available:
            return {"indexed": 0, "removed": 0, "total": 0}
        now = time.monotonic()
        if max_age and now - self._checked < max_age:
            return {"indexed": 0, "removed": 0, "total": None}
        with self._lock:
            con = self._connect()
            try:
                known = {row["path"]: (row["id"], row["mtime"]) for row in con.execute("select id, path, mtime from notes")}
                seen: set[str] = set()
                changed = 0
                for path in iter_notes(self.vault.root):
                    rel = self.vault.rel(path)
                    seen.add(rel)
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    if rel in known and known[rel][1] == mtime:
                        continue
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    self._store(con, rel, path.stem, text, mtime, known.get(rel, (None,))[0])
                    changed += 1
                gone = [known[rel][0] for rel in known.keys() - seen]
                for note_id in gone:
                    con.execute("delete from notes where id = ?", (note_id,))
                    con.execute("delete from fts where rowid = ?", (note_id,))
                    con.execute("delete from links where src = ?", (note_id,))
                con.commit()
                total = con.execute("select count(*) from notes").fetchone()[0]
            finally:
                con.close()
            self._checked = time.monotonic()
            return {"indexed": changed, "removed": len(gone), "total": total}

    def _store(self, con: sqlite3.Connection, rel: str, title: str, text: str, mtime: float, note_id: int | None) -> None:
        meta, body = split_frontmatter(text)
        tipo = meta.get("tipo", "")
        projeto = title if tipo == "projeto" else link_target(meta.get("projeto", ""))
        row = (rel, title, fold(title), tipo, projeto, meta.get("status", ""), meta.get("data", ""), abstract(body), mtime)
        if note_id is None:
            note_id = con.execute(
                "insert into notes(path, title, folded, tipo, projeto, status, data, resumo, mtime) values (?,?,?,?,?,?,?,?,?)", row
            ).lastrowid
        else:
            con.execute(
                "update notes set path=?, title=?, folded=?, tipo=?, projeto=?, status=?, data=?, resumo=?, mtime=? where id=?",
                (*row, note_id),
            )
            con.execute("delete from fts where rowid = ?", (note_id,))
            con.execute("delete from links where src = ?", (note_id,))
        con.execute("insert into fts(rowid, title, resumo, body) values (?, ?, ?, ?)", (note_id, title, row[7], body[:MAX_BODY]))
        targets = {fold(t) for t in wikilinks(text)}
        con.executemany("insert into links(src, dst) values (?, ?)", [(note_id, t) for t in targets])

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        item = {k: row[k] for k in ("path", "title", "tipo", "projeto", "status", "data", "resumo")}
        if "trecho" in row.keys():
            item["snippet"] = row["trecho"]
        return item

    # --- consultas ----------------------------------------------------------------

    def status(self) -> dict:
        self.refresh()
        con = self._connect()
        try:
            counts = {r["tipo"] or "": r["n"] for r in con.execute("select tipo, count(*) n from notes group by tipo")}
        finally:
            con.close()
        return {"vault": str(self.vault.root), "available": self.vault.available, "total": sum(counts.values()), "types": counts}

    def search(self, query: str, tipos: list[str] | None = None, projeto: str | None = None, limit: int = 40) -> list[dict]:
        self.refresh()
        words = terms(query)
        where, params = [], []
        if tipos:
            where.append(f"n.tipo in ({','.join('?' * len(tipos))})")
            params += tipos
        if projeto:
            where.append("n.projeto = ?")
            params.append(projeto)
        con = self._connect()
        try:
            if not words:
                sql = "select n.* from notes n" + (" where " + " and ".join(where) if where else "")
                sql += " order by n.data desc, n.mtime desc limit ?"
                return [self._row(r) for r in con.execute(sql, (*params, limit))]
            match = " ".join(_fts_term(w) if len(w) >= 5 else f'"{w}"*' for w in words)
            sql = (
                "select n.*, snippet(fts, 2, ?, ?, '…', 14) as trecho from fts join notes n on n.id = fts.rowid "
                "where fts match ?" + "".join(f" and {w}" for w in where) + " order by bm25(fts, 8.0, 3.0, 1.0) limit ?"
            )
            return [self._row(r) for r in con.execute(sql, (*HIGHLIGHT, match, *params, limit))]
        except sqlite3.OperationalError:
            return []
        finally:
            con.close()

    def note(self, path: str | None = None, title: str | None = None) -> dict:
        self.refresh()
        con = self._connect()
        try:
            row = None
            if path:
                row = con.execute("select * from notes where path = ?", (path,)).fetchone()
            elif title:
                key = fold(title.split("|")[0].split("#")[0].strip())
                row = con.execute("select * from notes where folded = ? order by length(path) limit 1", (key,)).fetchone()
            if row is None:
                raise VaultError(f"nota não encontrada: {path or title}")
            backlinks = [
                self._row(r)
                for r in con.execute(
                    "select n.* from links l join notes n on n.id = l.src where l.dst = ? and n.id != ? order by n.data desc, n.title",
                    (row["folded"], row["id"]),
                )
            ]
        finally:
            con.close()
        meta, body = split_frontmatter(self.vault.resolve(row["path"]).read_text(encoding="utf-8"))
        return {**self._row(row), "meta": meta, "body": body, "backlinks": backlinks}

    def graph(self) -> dict:
        """Notas e ligações do vault para o grafo: [[links]] resolvidos para notas que existem."""
        self.refresh()
        areas = {p.name: link_target(p.meta.get("area", "")) for p in self.vault.projects()}
        con = self._connect()
        try:
            rows = con.execute("select id, path, title, folded, tipo, projeto, status, data from notes order by length(path)").fetchall()
            position: dict[int, int] = {}
            by_title: dict[str, int] = {}
            nodes: list[dict] = []
            for r in rows:
                position[r["id"]] = len(nodes)
                by_title.setdefault(r["folded"], r["id"])
                projeto = r["projeto"] or ""
                group = area_group(areas.get(projeto, "")) if projeto else "brain"
                nodes.append(
                    {
                        "path": r["path"],
                        "title": r["title"],
                        "tipo": r["tipo"] or "",
                        "projeto": projeto,
                        "status": r["status"] or "",
                        "data": r["data"] or "",
                        "group": group,
                        "degree": 0,
                    }
                )
            edges: set[tuple[int, int]] = set()
            for src, dst in con.execute("select src, dst from links"):
                target = by_title.get(dst)
                if target is None or target == src or src not in position:
                    continue
                a, b = position[src], position[target]
                edges.add((a, b) if a < b else (b, a))
        finally:
            con.close()
        for a, b in edges:
            nodes[a]["degree"] += 1
            nodes[b]["degree"] += 1
        counts: dict[str, int] = {}
        for node in nodes:
            counts[node["group"]] = counts.get(node["group"], 0) + 1
        groups = [{"key": k, "label": GROUP_LABEL[k], "count": counts[k]} for k in [*(g[0] for g in GRAPH_GROUPS), "brain", "semarea"] if counts.get(k)]
        return {"nodes": nodes, "edges": sorted(edges), "groups": groups}

    def known_titles(self, titles: list[str]) -> list[str]:
        """Quais destes títulos existem no vault (para a tela marcar link quebrado)."""
        if not titles:
            return []
        self.refresh()
        con = self._connect()
        try:
            folded = {fold(t): t for t in titles}
            found = set()
            keys = list(folded)
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                found |= {r[0] for r in con.execute(f"select folded from notes where folded in ({','.join('?' * len(chunk))})", chunk)}
            return [folded[k] for k in folded if k in found]
        finally:
            con.close()

    def precedents(self, projeto: str | None, context: str, limit: int = 5) -> list[dict]:
        """Registros de outros projetos que batem com os termos mais raros do contexto."""
        self.refresh()
        counts = Counter(w[:-1] if len(w) >= 6 and w.endswith("s") else w for w in words(context))
        if not counts:
            return []
        con = self._connect()
        try:
            total = max(1, con.execute("select count(*) from notes").fetchone()[0])
            keys = list(counts)
            df = {}
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                for r in con.execute(f"select term, doc from vocab where term in ({','.join('?' * len(chunk))})", chunk):
                    df[r["term"]] = r["doc"]
            # Palavra de uma nota só costuma ser ruído (nome próprio, erro de digitação); palavra
            # de muitas notas não distingue nada. Peso = vezes no contexto x raridade no vault.
            ceiling = max(6, total // 8)
            usable = [w for w in counts if 2 <= df.get(w, 0) <= ceiling]
            chosen = sorted(usable, key=lambda w: counts[w] * math.log(total / df[w]), reverse=True)[:12]
            if not chosen:
                return []
            # Precedente é o que o registro afirma: só título e resumo contam, não o corpo inteiro.
            match = "{title resumo} : (" + " OR ".join(_fts_term(w) for w in chosen) + ")"
            sql = (
                "select n.*, snippet(fts, 1, ?, ?, '…', 12) as trecho from fts join notes n on n.id = fts.rowid "
                f"where fts match ? and n.tipo in ({','.join('?' * len(RECORD_TYPES))}) "
                "and coalesce(n.status, '') != 'substituida' and coalesce(n.projeto, '') != ? "
                "order by bm25(fts, 4.0, 2.0, 0.0) limit ?"
            )
            rows = con.execute(sql, (*HIGHLIGHT, match, *RECORD_TYPES, projeto or "", limit)).fetchall()
            return [{**self._row(r), "terms": [w for w in chosen if w in fold(r["title"] + " " + (r["resumo"] or ""))][:5]} for r in rows]
        except sqlite3.OperationalError:
            return []
        finally:
            con.close()

    def project_context(self, name: str) -> str:
        """Texto que descreve o momento do projeto: tarefas abertas e registros recentes."""
        note = self.vault.project(name)
        open_tasks = [t.text for t in parse_tasks(note.path.read_text(encoding="utf-8")) if t.state != "concluida"]
        con = self._connect()
        try:
            recent = [
                f"{r['title']} {r['resumo'] or ''}"
                for r in con.execute(
                    f"select title, resumo from notes where projeto = ? and tipo in ({','.join('?' * len(RECORD_TYPES))}) "
                    "order by data desc, mtime desc limit 6",
                    (name, *RECORD_TYPES),
                )
            ]
        finally:
            con.close()
        return "\n".join(open_tasks[:12] + recent)

    def session_context(self, cwd: str, limit: int = 5) -> str:
        """O que a MÊTIS acrescenta no início de uma sessão do Claude dentro de um projeto do Brain."""
        note = self.vault.project_for_dir(cwd)
        if note is None:
            return ""
        self.refresh()
        found = self.precedents(note.name, self.project_context(note.name), limit)
        lines = [f"MÊTIS · precedentes do Brain para [[{note.name}]] (outros projetos, achados por palavra; confira antes de seguir):"]
        if found:
            for item in found:
                where = f"{item['projeto']} · {item['status']}" if item["status"] else item["projeto"]
                summary = (item["resumo"] or "").replace("\n", " ")
                summary = summary[:220] + ("…" if len(summary) > 220 else "")
                lines.append(f"- {TYPE_ICON.get(item['tipo'], '·')} [[{item['title']}]] ({where}): {summary}")
        else:
            lines.append("- nenhum registro de outro projeto bateu com as tarefas abertas agora.")
        lines.append(
            "Comandos: `metis brain buscar <termos>`, `metis brain ler \"<título>\"`, `metis brain precedentes [termos]`, "
            "`metis tarefas` (Próximas ações deste projeto) e `metis tarefa mover <id> em-andamento|em-teste|concluida`."
        )
        return "\n".join(lines)
