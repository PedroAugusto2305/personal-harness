"""v1.1: a atividade, os comentários e os anexos de cada tarefa do kanban.

A tarefa continua sendo a linha da nota no Brain (título, rótulos, prioridade, datas,
descrição e subtarefas ficam lá). Aqui fica só o que não cabe numa nota sem sujá-la: quem
mudou o quê e quando, a conversa sobre a tarefa e os arquivos anexados (que moram em
~/.harness/anexos). A chave é (projeto, id da tarefa); quando o título muda pelo app, o id
muda e `rename` leva tudo junto. Editar o título direto no Obsidian solta o histórico.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

#: Eventos guardados por tarefa (os mais antigos saem primeiro).
KEEP_PER_TASK = 500
KINDS = ("criou", "moveu", "rotulos", "subtarefa", "titulo", "descricao", "prioridade", "data", "comentario", "anexo", "auto")


class TaskLogError(ValueError):
    pass


class TaskLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """create table if not exists eventos(
                    id integer primary key, ts real, projeto text, tarefa text, quem text, tipo text, texto text, dados text)"""
            )
            con.execute("create index if not exists eventos_tarefa on eventos(projeto, tarefa, id)")
            con.execute(
                """create table if not exists anexos(
                    id text primary key, ts real, projeto text, tarefa text, quem text, nome text, caminho text, tamanho integer)"""
            )
            con.execute("create index if not exists anexos_tarefa on anexos(projeto, tarefa)")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _event(row: sqlite3.Row) -> dict:
        item = dict(row)
        try:
            item["dados"] = json.loads(item["dados"] or "{}")
        except json.JSONDecodeError:
            item["dados"] = {}
        return item

    # --- eventos e comentários ----------------------------------------------------------

    def add(self, projeto: str, tarefa: str, quem: str, tipo: str, *, texto: str = "", dados: dict | None = None) -> dict:
        if tipo not in KINDS:
            raise TaskLogError(f"evento desconhecido: {tipo}")
        with self._lock, self._connect() as con:
            row_id = con.execute(
                "insert into eventos(ts, projeto, tarefa, quem, tipo, texto, dados) values (?,?,?,?,?,?,?)",
                (time.time(), projeto, tarefa, quem, tipo, texto[:20000], json.dumps(dados or {}, ensure_ascii=False)),
            ).lastrowid
            con.execute(
                """delete from eventos where projeto = ? and tarefa = ? and id not in (
                    select id from eventos where projeto = ? and tarefa = ? order by id desc limit ?)""",
                (projeto, tarefa, projeto, tarefa, KEEP_PER_TASK),
            )
            row = con.execute("select * from eventos where id = ?", (row_id,)).fetchone()
        return self._event(row)

    def comment(self, projeto: str, tarefa: str, quem: str, texto: str) -> dict:
        body = texto.strip()
        if not body:
            raise TaskLogError("o comentário está vazio")
        return self.add(projeto, tarefa, quem, "comentario", texto=body)

    def delete_comment(self, projeto: str, tarefa: str, event_id: int) -> None:
        with self._lock, self._connect() as con:
            done = con.execute(
                "delete from eventos where id = ? and projeto = ? and tarefa = ? and tipo = 'comentario'", (event_id, projeto, tarefa)
            ).rowcount
        if not done:
            raise TaskLogError("comentário não encontrado")

    def events(self, projeto: str, tarefa: str) -> list[dict]:
        """Do mais antigo ao mais novo."""
        with self._connect() as con:
            rows = con.execute("select * from eventos where projeto = ? and tarefa = ? order by id", (projeto, tarefa)).fetchall()
        return [self._event(r) for r in rows]

    # --- anexos -------------------------------------------------------------------------

    def attach(self, projeto: str, tarefa: str, quem: str, nome: str, caminho: str, tamanho: int) -> dict:
        item = {"id": secrets.token_hex(6), "ts": time.time(), "projeto": projeto, "tarefa": tarefa, "quem": quem, "nome": nome,
                "caminho": caminho, "tamanho": int(tamanho)}  # fmt: skip
        with self._lock, self._connect() as con:
            con.execute(
                "insert into anexos(id, ts, projeto, tarefa, quem, nome, caminho, tamanho) values (:id,:ts,:projeto,:tarefa,:quem,:nome,:caminho,:tamanho)",
                item,
            )
        self.add(projeto, tarefa, quem, "anexo", dados={"acao": "anexou", "nome": nome})
        return item

    def attachment(self, attachment_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute("select * from anexos where id = ?", (attachment_id,)).fetchone()
        return dict(row) if row else None

    def attachments(self, projeto: str, tarefa: str) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("select * from anexos where projeto = ? and tarefa = ? order by ts", (projeto, tarefa)).fetchall()
        return [dict(r) for r in rows]

    def detach(self, projeto: str, tarefa: str, attachment_id: str, quem: str) -> dict:
        found = self.attachment(attachment_id)
        if found is None or found["projeto"] != projeto or found["tarefa"] != tarefa:
            raise TaskLogError("anexo não encontrado")
        with self._lock, self._connect() as con:
            con.execute("delete from anexos where id = ?", (attachment_id,))
        self.add(projeto, tarefa, quem, "anexo", dados={"acao": "tirou", "nome": found["nome"]})
        return found

    # --- quadro e troca de id -----------------------------------------------------------

    def counts(self) -> dict[tuple[str, str], dict]:
        """Comentários e anexos de cada tarefa, para os cartões do quadro (uma consulta só)."""
        out: dict[tuple[str, str], dict] = {}
        with self._connect() as con:
            for row in con.execute("select projeto, tarefa, count(*) n from eventos where tipo = 'comentario' group by projeto, tarefa"):
                out.setdefault((row["projeto"], row["tarefa"]), {"comentarios": 0, "anexos": 0})["comentarios"] = row["n"]
            for row in con.execute("select projeto, tarefa, count(*) n from anexos group by projeto, tarefa"):
                out.setdefault((row["projeto"], row["tarefa"]), {"comentarios": 0, "anexos": 0})["anexos"] = row["n"]
        return out

    def rename(self, projeto: str, antes: str, depois: str) -> None:
        if antes == depois:
            return
        with self._lock, self._connect() as con:
            con.execute("update eventos set tarefa = ? where projeto = ? and tarefa = ?", (depois, projeto, antes))
            con.execute("update anexos set tarefa = ? where projeto = ? and tarefa = ?", (depois, projeto, antes))
