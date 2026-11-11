"""Coluna Auto do kanban (v0.9.9): tarefa na fila roda sozinha.

A tarefa entra na fila com o jeito de rodar (CLI ou agente, modelo, esforço, permissão e se
abre numa worktree nova ou na pasta do projeto). Até `limite` rodam ao mesmo tempo: a fila
abre o terminal com o pedido, move a tarefa para Em andamento e, quando o agente termina o
primeiro turno (o hook Stop), move para Em teste, onde o trabalho espera a revisão do Pedro.
A fila mora em `<HARNESS_HOME>/kanban-auto.json`; o que rodava quando o núcleo caiu volta
como erro (o terminal morreu junto), nada roda duas vezes sozinho.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Awaitable, Callable

CLIS = ("claude", "codex")
PERMISSIONS = ("padrao", "manual", "auto", "yolo")
EFFORTS = ("", "low", "medium", "high", "xhigh")
PLACES = ("worktree", "pasta")
#: Quantos itens terminados ficam na lista (o resto sai do arquivo).
KEEP_DONE = 40
MAX_LIMIT = 4


class AutoError(ValueError):
    pass


@dataclass
class AutoItem:
    id: str
    projeto: str
    tarefa: str
    texto: str
    criado: float
    cli: str = "claude"
    agente: str = ""
    modelo: str = ""
    esforco: str = ""
    permissao: str = "auto"
    onde: str = "worktree"
    #: fila, rodando, feito, erro ou cancelado
    status: str = "fila"
    sessao: str = ""
    pasta: str = ""
    erro: str = ""
    inicio: float = 0.0
    fim: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


Starter = Callable[[AutoItem], Awaitable[tuple[str, str]]]
Mover = Callable[[str, str, str], None]


class AutoQueue:
    def __init__(self, path: Path, *, start: Starter, move: Mover, publish: Callable[[dict], None]) -> None:
        self.path = path
        self.start = start
        self.move = move
        self.publish = publish
        self.loop: asyncio.AbstractEventLoop | None = None
        # Reentrante: _changed (que grava e monta a vista) roda com o lock já pego.
        self._lock = threading.RLock()
        # O asyncio guarda tarefas só por referência fraca: as voltas da fila ficam aqui até acabar.
        self._tasks: set[asyncio.Task] = set()
        self._pumping = False
        self.limit, self.items = self._load()

    # --- arquivo --------------------------------------------------------------------

    def _load(self) -> tuple[int, list[AutoItem]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 1, []
        names = {f.name for f in fields(AutoItem)}
        items = []
        for raw in data.get("itens", []) if isinstance(data, dict) else []:
            try:
                item = AutoItem(**{k: v for k, v in raw.items() if k in names})
            except TypeError:
                continue
            if item.status == "rodando":
                # O núcleo caiu com ela rodando: o terminal foi junto. Volta como erro, sem repetir sozinha.
                item.status, item.erro, item.fim = "erro", "o núcleo reiniciou com a tarefa rodando", time.time()
            items.append(item)
        limit = data.get("limite", 1) if isinstance(data, dict) else 1
        return max(1, min(MAX_LIMIT, int(limit) if isinstance(limit, int) else 1)), items

    def _save(self) -> None:
        """Chamado com o lock pego: a rota (thread do servidor), a fila (loop) e o hook (outra
        thread) gravam um de cada vez, cada um no próprio arquivo temporário."""
        done = [i for i in self.items if i.status in ("feito", "erro", "cancelado")]
        keep = {i.id for i in sorted(done, key=lambda i: i.fim or i.criado, reverse=True)[:KEEP_DONE]}
        self.items = [i for i in self.items if i.status in ("fila", "rodando") or i.id in keep]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"limite": self.limit, "itens": [i.to_dict() for i in self.items]}, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(prefix=".kanban-auto-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _changed(self) -> None:
        with self._lock:
            try:
                self._save()
            except OSError:
                pass  # disco cheio ou pasta sumiu: a fila segue em memória e grava na próxima mudança
            view = self.view()
        self.publish({"type": "kanban.auto", **view})

    # --- leitura --------------------------------------------------------------------

    def view(self) -> dict:
        with self._lock:
            return {
                "limite": self.limit,
                "rodando": sum(i.status == "rodando" for i in self.items),
                "na_fila": sum(i.status == "fila" for i in self.items),
                "itens": [i.to_dict() for i in self.items],
            }

    # --- escrita --------------------------------------------------------------------

    def enqueue(self, projeto: str, tarefa: str, texto: str, *, cli: str = "claude", agente: str = "", modelo: str = "", esforco: str = "",
                permissao: str = "auto", onde: str = "worktree") -> AutoItem:  # fmt: skip
        if cli not in CLIS:
            raise AutoError(f"CLI desconhecida: {cli} (claude ou codex)")
        if permissao not in PERMISSIONS:
            raise AutoError(f"permissão desconhecida: {permissao}")
        if esforco not in EFFORTS:
            raise AutoError(f"esforço desconhecido: {esforco}")
        if onde not in PLACES:
            raise AutoError("onde: worktree ou pasta")
        if not projeto or not tarefa:
            raise AutoError("falta o projeto ou a tarefa")
        with self._lock:
            if any(i.projeto == projeto and i.tarefa == tarefa and i.status in ("fila", "rodando") for i in self.items):
                raise AutoError("esta tarefa já está na fila do Auto")
            item = AutoItem(id=secrets.token_hex(5), projeto=projeto, tarefa=tarefa, texto=" ".join(texto.split())[:2000], criado=time.time(),
                            cli=cli, agente=agente, modelo=modelo, esforco=esforco, permissao=permissao, onde=onde)  # fmt: skip
            self.items.append(item)
        self._changed()
        self.kick()
        return item

    def cancel(self, item_id: str) -> AutoItem:
        with self._lock:
            item = next((i for i in self.items if i.id == item_id), None)
            if item is None:
                raise AutoError("item desconhecido na fila do Auto")
            if item.status != "fila":
                raise AutoError("só sai da fila o que ainda não começou (o que roda, feche o terminal)")
            item.status, item.fim = "cancelado", time.time()
        self._changed()
        return item

    def update_task_ids(self, ids_of: Callable[[str], dict[str, str]]) -> None:
        """v1.0: o id da tarefa deixou de contar os rótulos. Os itens gravados com o id de
        antes passam para o de agora, e a tela volta a achar o cartão de cada um. `ids_of`
        dá, para um projeto, id (de agora ou de antes) → id de agora; a nota de cada projeto
        é lida uma vez. Projeto ou tarefa que sumiu fica como estava."""
        changed = False
        known: dict[str, dict[str, str]] = {}
        with self._lock:
            for item in self.items:
                if item.projeto not in known:
                    try:
                        known[item.projeto] = ids_of(item.projeto)
                    except Exception:  # noqa: BLE001 - o projeto saiu do Brain: os itens dele ficam
                        known[item.projeto] = {}
                task_id = known[item.projeto].get(item.tarefa)
                if task_id and task_id != item.tarefa:
                    item.tarefa, changed = task_id, True
        if changed:
            self._changed()

    def rename_task(self, projeto: str, antes: str, depois: str) -> None:
        """v1.1: o título da tarefa mudou no cartão e, com ele, o id."""
        changed = False
        with self._lock:
            for item in self.items:
                if item.projeto == projeto and item.tarefa == antes:
                    item.tarefa, changed = depois, True
        if changed:
            self._changed()

    def running(self, projeto: str, tarefa: str) -> AutoItem | None:
        with self._lock:
            return next((i for i in self.items if i.projeto == projeto and i.tarefa == tarefa and i.status == "rodando"), None)

    def forget_task(self, projeto: str, tarefa: str) -> None:
        """v1.1.4: a tarefa foi excluída: os itens dela saem da fila e da lista dos terminados
        (o que está rodando fica; a rota de excluir recusa antes)."""
        with self._lock:
            kept = [i for i in self.items if not (i.projeto == projeto and i.tarefa == tarefa and i.status != "rodando")]
            changed = len(kept) != len(self.items)
            self.items = kept
        if changed:
            self._changed()

    def clear_done(self) -> None:
        with self._lock:
            self.items = [i for i in self.items if i.status in ("fila", "rodando")]
        self._changed()

    def set_limit(self, limit: int) -> None:
        if not 1 <= limit <= MAX_LIMIT:
            raise AutoError(f"de 1 a {MAX_LIMIT} ao mesmo tempo")
        with self._lock:
            self.limit = limit
        self._changed()
        self.kick()

    # --- rodar ----------------------------------------------------------------------

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.kick()

    def kick(self) -> None:
        """Pede uma volta da fila no loop do núcleo (pode vir de outra thread)."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._spawn()
        else:
            loop.call_soon_threadsafe(self._spawn)

    def _spawn(self) -> None:
        task = self.loop.create_task(self.pump()) if self.loop else None
        if task is not None:
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def pump(self) -> None:
        if self._pumping:
            return
        self._pumping = True
        try:
            while True:
                with self._lock:
                    busy = sum(i.status == "rodando" for i in self.items)
                    nxt = next((i for i in self.items if i.status == "fila"), None) if busy < self.limit else None
                    if nxt is None:
                        return
                    nxt.status, nxt.inicio = "rodando", time.time()
                self._changed()
                try:
                    session, folder = await self.start(nxt)
                except Exception as exc:  # noqa: BLE001 - o erro vira o estado do item, a fila segue
                    with self._lock:
                        nxt.status, nxt.erro, nxt.fim = "erro", str(exc)[:400] or exc.__class__.__name__, time.time()
                    self._changed()
                    continue
                with self._lock:
                    nxt.sessao, nxt.pasta = session, folder
                try:
                    self.move(nxt.projeto, nxt.tarefa, "em-andamento")
                except Exception:  # noqa: BLE001 - a nota mudou: o agente roda mesmo assim
                    pass
                self._changed()
        finally:
            self._pumping = False

    def on_bus_event(self, event: dict) -> None:
        """Turno terminado (Stop) vira Em teste; terminal fechado antes disso vira erro."""
        if event.get("type") != "session.status":
            return
        session_id = str(event.get("id") or "")
        status = event.get("status")
        finished = status == "waiting" and event.get("atencao") == "terminou"
        if not finished and status != "exited":
            return
        with self._lock:
            item = next((i for i in self.items if i.status == "rodando" and i.sessao == session_id), None)
            if item is None:
                return
            item.fim = time.time()
            if finished:
                item.status = "feito"
            else:
                item.status, item.erro = "erro", f"o terminal fechou antes de terminar (código {event.get('exit_code')})"
        if finished:
            try:
                self.move(item.projeto, item.tarefa, "em-teste")
            except Exception:  # noqa: BLE001
                pass
        self._changed()
        self.kick()


def auto_prompt(item: AutoItem, detalhes: str = "") -> str:
    """O pedido que entra no agente. `detalhes` (v1.1) é o resto do cartão: descrição,
    checklist, datas e anexos, lido da nota na hora de começar."""
    return "\n".join(
        [
            f"Tarefa do kanban da MÊTIS (coluna Auto) · projeto {item.projeto} · id {item.tarefa}",
            "",
            item.texto,
            *(["", detalhes] if detalhes.strip() else []),
            "",
            "Você está rodando sozinho, sem o Pedro olhando: faça a tarefa de ponta a ponta nesta pasta, rode os testes que houver e "
            "deixe tudo pronto para ele revisar. Não faça push nem abra PR. Quando terminar, resuma em poucas linhas o que mudou e "
            f"o que ele precisa conferir; a MÊTIS move a tarefa para Em teste (ou rode `metis tarefa mover {item.tarefa} em-teste`).",
        ]
    )
