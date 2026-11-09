"""Índice do Brain: busca por palavra (SQLite FTS5), por significado (vetores) e precedentes.

O índice mora em ~/.harness/brain.db e é só um cache: apagar o arquivo não perde nada, ele
é refeito do vault. A cada consulta, o núcleo confere a data das notas (uns 10 ms para o
vault inteiro) e reindexa só o que mudou. O núcleo, o MCP de fora (`metis brain mcp`) e o
hook de início de sessão usam o mesmo arquivo: a reindexação pega a trava de escrita antes
de ler o que já conhece, para dois processos nunca gravarem a mesma nota.

Precedentes (v0.8) = híbrido: os termos mais raros do contexto procuram por palavra, e os
vetores (semantic.py) procuram por significado; as duas listas se juntam por posição
(reciprocal rank fusion). Só entram decisões, incidentes, aprendizados e entregas de OUTROS
projetos, nunca as substituídas.
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
from typing import Callable

import numpy as np

from .kanban import parse_tasks
from .semantic import from_blobs, to_blob, zscores
from .vault import Vault, VaultError, abstract, iter_notes, link_target, split_frontmatter, wikilinks

SCHEMA = 4
RECORD_TYPES = ("decisao", "incidente", "aprendizado", "entrega")
TYPE_ICON = {"decisao": "⚖️", "incidente": "🔥", "aprendizado": "💡", "entrega": "🛠️", "projeto": "🎯"}
HIGHLIGHT = ("\x02", "\x03")
MAX_BODY = 200_000

# Réguas da busca por significado (desvios-padrão acima da média da consulta; ver semantic.py).
Z_FREE = 2.0  # uma consulta só, escrita pelo agente ou pelo Pedro
Z_PROJECT = 2.4  # várias consultas (os registros recentes do projeto): o melhor de N infla o z
Z_SAME = 1.8  # decisões do mesmo projeto, para o aviso de repetição ou contradição
RRF_K = 4

Encoder = Callable[[list[str], float], "np.ndarray | None"]

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


def vector_text(title: str, resumo: str | None) -> str:
    return f"{title}. {resumo or ''}".strip()


class BrainIndex:
    def __init__(self, vault: Vault, db_path: Path, encode: Encoder | None = None) -> None:
        self.vault = vault
        self.db_path = Path(db_path)
        self.encode = encode  # texto → vetores; None = só por palavra
        self._lock = threading.Lock()
        self._checked = 0.0

    # --- infraestrutura -----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("pragma journal_mode=wal")
        if con.execute("pragma user_version").fetchone()[0] != SCHEMA:
            for table in ("vocab", "fts", "links", "vectors", "notes"):
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
                create table vectors(id integer primary key, mtime real, vec blob);
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
            on_disk: dict[str, tuple[Path, float]] = {}
            for path in iter_notes(self.vault.root):
                try:
                    on_disk[self.vault.rel(path)] = (path, path.stat().st_mtime)
                except OSError:
                    continue
            con = self._connect()
            try:
                known = {row["path"]: (row["id"], row["mtime"]) for row in con.execute("select id, path, mtime from notes")}
                if known.keys() == on_disk.keys() and all(known[rel][1] == m for rel, (_p, m) in on_disk.items()):
                    self._checked = time.monotonic()
                    return {"indexed": 0, "removed": 0, "total": len(known)}
                # Trava de escrita e releitura: outro processo (o MCP de fora, o hook) pode ter
                # acabado de reindexar o mesmo arquivo.
                con.execute("begin immediate")
                known = {row["path"]: (row["id"], row["mtime"]) for row in con.execute("select id, path, mtime from notes")}
                changed = 0
                for rel, (path, mtime) in on_disk.items():
                    if rel in known and known[rel][1] == mtime:
                        continue
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    self._store(con, rel, path.stem, text, mtime, known.get(rel, (None,))[0])
                    changed += 1
                gone = [known[rel][0] for rel in known.keys() - on_disk.keys()]
                for note_id in gone:
                    con.execute("delete from notes where id = ?", (note_id,))
                    con.execute("delete from fts where rowid = ?", (note_id,))
                    con.execute("delete from links where src = ?", (note_id,))
                    con.execute("delete from vectors where id = ?", (note_id,))
                con.commit()
                total = con.execute("select count(*) from notes").fetchone()[0]
            except sqlite3.OperationalError:
                # Banco ocupado por outro processo por mais de 10 s: fica para a próxima consulta.
                con.rollback()
                return {"indexed": 0, "removed": 0, "total": None}
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

    def titles(self, query: str = "", limit: int = 20) -> list[dict]:
        """Títulos para o autocompletar de [[ (v0.9.7): os que contêm o texto, sem acento e sem
        caixa, os que começam com ele primeiro e depois em ordem alfabética; sem texto, as notas
        mexidas mais recentemente."""
        self.refresh()
        key = fold(query.strip())
        con = self._connect()
        try:
            if not key:
                rows = con.execute("select path, title, tipo, projeto from notes order by mtime desc limit ?", (limit,))
            else:
                like = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                rows = con.execute(
                    "select path, title, tipo, projeto from notes where folded like ? escape '\\' "
                    "order by case when folded like ? escape '\\' then 0 else 1 end, folded, length(path) limit ?",
                    (f"%{like}%", f"{like}%", limit),
                )
            return [{"titulo": r["title"], "tipo": r["tipo"] or "", "projeto": r["projeto"] or "", "path": r["path"]} for r in rows]
        finally:
            con.close()

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

    def lexical_precedents(self, projeto: str | None, context: str, limit: int = 5) -> list[dict]:
        """Por palavra: registros de outros projetos que batem com os termos mais raros do contexto."""
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

    # --- significado ----------------------------------------------------------------

    def sync_vectors(self, wait: float = 0.0) -> int:
        """Calcula o vetor das notas novas ou mudadas. Devolve quantas; 0 se o modelo não está pronto."""
        if self.encode is None:
            return 0
        self.refresh()
        con = self._connect()
        try:
            # Só os registros: são a população da régua, e a nota do dia (que muda a toda hora)
            # nunca obriga o modelo a voltar para a memória.
            rows = con.execute(
                "select n.id, n.title, n.resumo, n.mtime from notes n left join vectors v on v.id = n.id "
                f"where (v.id is null or v.mtime != n.mtime) and n.tipo in ({','.join('?' * len(RECORD_TYPES))})",
                RECORD_TYPES,
            ).fetchall()
        finally:
            con.close()
        if not rows:
            return 0
        done = 0
        for i in range(0, len(rows), 512):
            chunk = rows[i : i + 512]
            vectors = self.encode([vector_text(r["title"], r["resumo"]) for r in chunk], wait)
            if vectors is None:
                break
            con = self._connect()
            try:
                con.executemany(
                    "insert or replace into vectors(id, mtime, vec) values (?, ?, ?)",
                    [(r["id"], r["mtime"], to_blob(v)) for r, v in zip(chunk, vectors)],
                )
                con.commit()
            finally:
                con.close()
            done += len(chunk)
        return done

    def vector_status(self) -> dict:
        con = self._connect()
        try:
            types = ",".join("?" * len(RECORD_TYPES))
            total = con.execute(f"select count(*) from notes where tipo in ({types})", RECORD_TYPES).fetchone()[0]
            ready = con.execute(
                f"select count(*) from vectors v join notes n on n.id = v.id and n.mtime = v.mtime where n.tipo in ({types})", RECORD_TYPES
            ).fetchone()[0]
        finally:
            con.close()
        return {"notes": total, "vectors": ready}

    def _vector_rows(self) -> tuple[list[sqlite3.Row], np.ndarray]:
        """Os registros com vetor em dia (sem os substituídos) e a matriz: a população da régua."""
        con = self._connect()
        try:
            rows = con.execute(
                "select n.*, v.vec from notes n join vectors v on v.id = n.id and v.mtime = n.mtime "
                f"where coalesce(n.status, '') != 'substituida' and n.tipo in ({','.join('?' * len(RECORD_TYPES))})",
                RECORD_TYPES,
            ).fetchall()
        finally:
            con.close()
        return rows, from_blobs([r["vec"] for r in rows])

    def _project_vectors(self, projeto: str, limit: int = 8) -> np.ndarray:
        """Os vetores dos registros mais recentes do projeto: o "momento" dele, sem carregar o modelo."""
        con = self._connect()
        try:
            rows = con.execute(
                f"select v.vec from notes n join vectors v on v.id = n.id and v.mtime = n.mtime "
                f"where n.projeto = ? and n.tipo in ({','.join('?' * len(RECORD_TYPES))}) "
                "order by n.data desc, n.mtime desc limit ?",
                (projeto, *RECORD_TYPES, limit),
            ).fetchall()
        finally:
            con.close()
        return from_blobs([r["vec"] for r in rows])

    def note_vector(self, path: str) -> np.ndarray | None:
        con = self._connect()
        try:
            row = con.execute("select v.vec from notes n join vectors v on v.id = n.id and v.mtime = n.mtime where n.path = ?", (path,)).fetchone()
        finally:
            con.close()
        return from_blobs([row["vec"]]) if row else None

    def semantic(
        self,
        queries: np.ndarray,
        *,
        tipos: tuple[str, ...] | None = RECORD_TYPES,
        exclude_project: str | None = None,
        only_project: str | None = None,
        z_min: float = Z_FREE,
        limit: int = 8,
        skip_paths: set[str] | None = None,
    ) -> list[dict]:
        """Notas mais próximas no sentido de qualquer uma das consultas, pela régua do z."""
        if queries is None or len(queries) == 0:
            return []
        rows, matrix = self._vector_rows()
        if skip_paths:  # a própria nota sai da população antes da régua (senão infla o desvio)
            keep = [i for i, r in enumerate(rows) if r["path"] not in skip_paths]
            rows, matrix = [rows[i] for i in keep], matrix[keep]
        if len(rows) < 5:
            return []
        sims = matrix @ queries.T  # nota x consulta
        z = zscores(sims)  # a régua é sobre todos os registros; o filtro vem depois
        best, which = z.max(axis=1), z.argmax(axis=1)
        found = []
        for i in np.argsort(-best):
            if best[i] < z_min:
                break
            r = rows[i]
            if tipos and r["tipo"] not in tipos:
                continue
            if exclude_project is not None and (r["projeto"] or "") == exclude_project:
                continue
            if only_project is not None and (r["projeto"] or "") != only_project:
                continue
            found.append({**self._row(r), "z": round(float(best[i]), 2), "sim": round(float(sims[i, which[i]]), 3), "query": int(which[i])})
            if len(found) >= limit:
                break
        return found

    def _encode(self, texts: list[str], wait: float) -> np.ndarray | None:
        if self.encode is None or not any(t.strip() for t in texts):
            return None
        try:
            return self.encode(texts, wait)
        except Exception:  # o modelo ou o núcleo fora do ar: fica só a busca por palavra
            return None

    def precedents(self, projeto: str | None, context: str, limit: int = 5, *, free_text: bool = False, wait: float = 0.0) -> list[dict]:
        """Registros de OUTROS projetos parecidos, por palavra e por significado.

        free_text=True: o contexto é o que o agente ou o Pedro escreveu (vira um vetor só).
        Senão é o momento do projeto, e as consultas são os vetores já guardados dos registros
        recentes dele (não precisa do modelo carregado).
        """
        self.refresh()
        lexical = self.lexical_precedents(projeto, context, limit * 2)
        queries, z_min = None, Z_FREE
        if free_text:
            queries = self._encode([context], wait)
        elif projeto:
            queries, z_min = self._project_vectors(projeto), Z_PROJECT
            if len(queries) == 0:
                queries, z_min = self._encode([context], wait), Z_FREE
        semantic = self.semantic(queries, exclude_project=projeto or "", z_min=z_min, limit=limit * 2) if queries is not None else []
        merged: dict[str, dict] = {}
        for via, items in (("significado", semantic), ("palavra", lexical)):
            for rank, item in enumerate(items):
                entry = merged.setdefault(item["path"], {**item, "via": [], "score": 0.0})
                entry["via"].append(via)
                entry["score"] += 1.0 / (RRF_K + rank)
                for key in ("z", "sim", "terms", "snippet"):
                    if key in item and key not in entry:
                        entry[key] = item[key]
        ranked = sorted(merged.values(), key=lambda e: -e["score"])[:limit]
        for entry in ranked:
            entry["score"] = round(entry["score"], 3)
        return ranked

    def conflicts(self, text: str, projeto: str | None, limit: int = 4, wait: float = 20.0) -> dict:
        """Momento 2, antes de decidir: decisões parecidas no mesmo projeto (repetição ou
        contradição) e registros parecidos nos outros (precedente)."""
        self.refresh()
        queries = self._encode([text], wait)
        if queries is not None:
            same = self.semantic(queries, tipos=("decisao",), only_project=projeto or "", z_min=Z_SAME, limit=limit) if projeto else []
            other = self.semantic(queries, exclude_project=projeto or "", z_min=Z_FREE, limit=limit)
            return {"via": "significado", "same": same, "other": other}
        same = self.search(text, ["decisao"], projeto, limit) if projeto else []
        same = [s for s in same if s["status"] != "substituida"]
        other = self.lexical_precedents(projeto, text, limit)
        return {"via": "palavra", "same": same, "other": other}

    def neighbor_projects(self, path: str, z_min: float = Z_PROJECT, projects: int = 2, per_project: int = 3) -> list[dict]:
        """Momento 3: para um registro novo, os outros projetos com registros bem parecidos."""
        vector = self.note_vector(path)
        con = self._connect()
        try:
            row = con.execute("select projeto from notes where path = ?", (path,)).fetchone()
        finally:
            con.close()
        if vector is None or row is None:
            return []
        own = row["projeto"] or ""
        hits = self.semantic(vector, exclude_project=own, z_min=z_min, limit=30, skip_paths={path})
        groups: dict[str, dict] = {}
        for hit in hits:
            if not hit["projeto"]:
                continue
            group = groups.setdefault(hit["projeto"], {"project": hit["projeto"], "z": hit["z"], "matches": []})
            if len(group["matches"]) < per_project:
                group["matches"].append(hit)
        return sorted(groups.values(), key=lambda g: -g["z"])[:projects]

    def notes_by_path(self, paths: list[str]) -> dict[str, dict | None]:
        """As notas do índice pelos caminhos dados (None para o que não existe mais)."""
        if not paths:
            return {}
        self.refresh()
        found: dict[str, dict | None] = dict.fromkeys(paths)
        con = self._connect()
        try:
            unique = list(dict.fromkeys(paths))
            for i in range(0, len(unique), 500):
                chunk = unique[i : i + 500]
                for row in con.execute(f"select * from notes where path in ({','.join('?' * len(chunk))})", chunk):
                    found[row["path"]] = self._row(row)
        finally:
            con.close()
        return found

    def records_since(self, projeto: str, since: float) -> list[dict]:
        """Registros do projeto escritos depois de `since` (time.time()): o que uma sessão deixou."""
        self.refresh()
        day = time.strftime("%Y-%m-%d", time.localtime(since))
        con = self._connect()
        try:
            rows = con.execute(
                f"select * from notes where projeto = ? and tipo in ({','.join('?' * len(RECORD_TYPES))}) and mtime >= ? and coalesce(data, '') >= ? "
                "order by mtime desc limit 12",
                (projeto, *RECORD_TYPES, since, day),
            ).fetchall()
        finally:
            con.close()
        return [self._row(r) for r in rows]

    def edges_among(self, paths: list[str]) -> list[list[int]]:
        """Ligações [[...]] entre as notas dadas, como pares de posições na lista."""
        if len(paths) < 2:
            return []
        con = self._connect()
        try:
            rows = con.execute(f"select id, path, folded from notes where path in ({','.join('?' * len(paths))})", paths).fetchall()
            by_id = {r["id"]: r["path"] for r in rows}
            by_folded = {r["folded"]: r["path"] for r in rows}
            links = con.execute(f"select src, dst from links where src in ({','.join('?' * len(by_id))})", list(by_id)).fetchall() if by_id else []
        finally:
            con.close()
        position = {path: i for i, path in enumerate(paths)}
        edges = set()
        for link in links:
            a, b = by_id.get(link["src"]), by_folded.get(link["dst"])
            if a and b and a != b:
                i, j = position[a], position[b]
                edges.add((min(i, j), max(i, j)))
        return [list(e) for e in sorted(edges)]

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

    def session_precedents(self, cwd: str, limit: int = 5) -> tuple[str | None, list[dict]]:
        """O projeto do Brain da pasta e os precedentes do momento dele."""
        note = self.vault.project_for_dir(cwd)
        if note is None:
            return None, []
        self.refresh()
        return note.name, self.precedents(note.name, self.project_context(note.name), limit)

    @staticmethod
    def render_context(project: str, found: list[dict], extra: list[str] | None = None, inside_metis: bool = True) -> str:
        """O texto do início de sessão: precedentes (e o que vier em extra, como sugestões pendentes)."""
        lines = [f"MÊTIS · precedentes do Brain para [[{project}]] (outros projetos, achados por significado e por palavra; confira antes de seguir):"]
        if found:
            for item in found:
                where = f"{item['projeto']} · {item['status']}" if item["status"] else item["projeto"]
                summary = (item["resumo"] or "").replace("\n", " ")
                summary = summary[:220] + ("…" if len(summary) > 220 else "")
                lines.append(f"- {TYPE_ICON.get(item['tipo'], '·')} [[{item['title']}]] ({where}): {summary}")
        else:
            lines.append("- nenhum registro de outro projeto bateu com o momento do projeto agora.")
        if extra:
            lines += extra
        if inside_metis:
            lines.append(
                "Antes de registrar uma decisão, chame brain_conflitos (MCP metis) com a decisão numa frase. "
                "Comandos: `metis brain buscar <termos>`, `metis brain ler \"<título>\"`, `metis brain precedentes [termos]`, "
                "`metis tarefas` (Próximas ações deste projeto) e `metis tarefa mover <id> em-andamento|em-teste|concluida`."
            )
        else:
            lines.append("Antes de registrar uma decisão, chame brain_conflitos (MCP metis-brain) com a decisão numa frase; brain_ler lê uma nota.")
        return "\n".join(lines)

    def session_context(self, cwd: str, limit: int = 5) -> str:
        """O que a MÊTIS acrescenta no início de uma sessão do Claude dentro de um projeto do Brain."""
        project, found = self.session_precedents(cwd, limit)
        return self.render_context(project, found) if project else ""
