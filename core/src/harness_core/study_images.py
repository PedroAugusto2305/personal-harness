"""Imagens de estudo (v1.3.0): o Sócrates pede uma ilustração e o GPT desenha, pelo Codex.

O Pedro estuda melhor com o GPT porque ele responde com imagens. O Claude não gera imagem;
o Codex tem o gerador de imagens do GPT, pelo plano do Pedro, e a MÊTIS já usa esse caminho
nas sprites (sprites.py). Aqui é o mesmo: `codex exec` com o pedido, e só vale a imagem que
saiu do gerador (`$CODEX_HOME/generated_images`): desenho feito por código não conta.

A imagem fica em ~/.harness/estudo/imagens/ e o caminho volta ao agente, que a mostra na
resposta com `![legenda](caminho)`: a conversa da MÊTIS desenha a imagem no lugar.

Um pedido por vez (a pasta de imagens do Codex é uma só, dividida com as sprites: as
imagens já usadas por um pedido ficam em `claimed`, o mesmo conjunto do estúdio de sprites).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from .sprites import generated_since, pick_generated

TIMEOUT_SECONDS = 360
MAX_REQUEST = 1500

PROMPT = (
    "Use your built-in image generation tool (the GPT image generator) to create ONE educational illustration "
    "for a student who is learning this subject, then save the generated image as imagem.png in the current folder. "
    "Do NOT draw it with code, SVG, HTML, Python or any other program: only the image generation tool counts. "
    "Style: a clean didactic figure like the best textbook or explainer illustrations; white or very light background; "
    "clear shapes and arrows; few colors with strong contrast; short labels in Brazilian Portuguese, spelled correctly "
    "and big enough to read; no watermark, no logos, no decorative clutter. Landscape 3:2 unless the request says otherwise. "
    "When you finish, reply with one short line describing what the image shows, in Portuguese.\n\n"
    "What to draw:\n"
)


def slug(text: str, size: int = 40) -> str:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:size].strip("-") or "imagem"


@dataclass
class ImageJob:
    id: str
    pedido: str
    #: Quem pediu (a sessão): uma sessão não abre um segundo desenho com o primeiro em andamento.
    dono: str = ""
    status: str = "running"  # running → done | error
    caminho: str | None = None
    descricao: str = ""
    erro: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class StudyImages:
    def __init__(self, home: Path, codex_env: Callable[[], tuple[str | None, dict[str, str]]], claimed: set[str] | None = None, run: Callable | None = None) -> None:
        """`codex_env()` devolve (executável, ambiente) da conta do Codex em uso; `run` troca o
        subprocess.run nos testes."""
        self.dir = home / "estudo" / "imagens"
        self.work = home / "estudo" / "imagens" / ".trabalho"
        self.codex_env = codex_env
        self.claimed = claimed if claimed is not None else set()
        self._run = run or subprocess.run
        self.jobs: dict[str, ImageJob] = {}
        self._events: dict[str, threading.Event] = {}
        self._turn = threading.Lock()
        self._lock = threading.Lock()

    def available(self) -> bool:
        executable, _env = self.codex_env()
        return bool(executable)

    def start(self, request: str, owner: str = "") -> ImageJob:
        """Um desenho novo. Se o mesmo dono já tem um desenho em andamento, devolve esse: o agente
        que repete o pedido depois de um corte de tempo não gasta uma imagem a mais."""
        request = " ".join(str(request or "").split()).strip()
        if not request:
            raise ValueError("diga o que a imagem deve mostrar")
        if len(request) > MAX_REQUEST:
            raise ValueError(f"pedido longo demais (até {MAX_REQUEST} caracteres)")
        job = ImageJob(id=uuid.uuid4().hex[:10], pedido=request, dono=owner)
        done = threading.Event()
        with self._lock:
            if owner:
                running = next((j for j in self.jobs.values() if j.dono == owner and j.status == "running"), None)
                if running is not None:
                    return running
            self.jobs[job.id] = job
            self._events[job.id] = done
            # Guarda só os últimos 50 pedidos na memória (as imagens ficam no disco).
            for old in list(self.jobs)[:-50]:
                self.jobs.pop(old, None)
                self._events.pop(old, None)
        threading.Thread(target=self._work, args=(job, done), daemon=True).start()
        return job

    def wait(self, job_id: str, timeout: float) -> ImageJob:
        with self._lock:
            job = self.jobs.get(job_id)
            done = self._events.get(job_id)
        if job is None or done is None:
            raise KeyError(f"pedido de imagem desconhecido: {job_id}")
        done.wait(max(0.0, timeout))
        return job

    def _work(self, job: ImageJob, done: threading.Event) -> None:
        try:
            with self._turn:
                path, note = self._draw(job)
            job.caminho, job.descricao, job.status = str(path), note, "done"
        except Exception as exc:  # qualquer falha volta ao agente como erro da ferramenta
            job.status, job.erro = "error", str(exc)
        finally:
            job.finished_at = time.time()
            done.set()

    def _draw(self, job: ImageJob) -> tuple[Path, str]:
        executable, env = self.codex_env()
        if not executable:
            raise RuntimeError("o Codex não está instalado (comando codex não encontrado): a imagem é desenhada pelo GPT através dele")
        folder = self.work / job.id
        folder.mkdir(parents=True, exist_ok=True)
        reply = folder / "resposta.txt"
        started = time.time()
        args = [
            executable, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "workspace-write",
            "-c", 'approval_policy="never"', "-C", str(folder), "-o", str(reply), "--", PROMPT + job.pedido,
        ]  # fmt: skip
        try:
            done = self._run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, env=env)
        except subprocess.TimeoutExpired:
            raise RuntimeError("o Codex demorou mais de 6 minutos para desenhar") from None
        codex_home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
        produced = pick_generated(generated_since(codex_home, started - 1), folder / "imagem.png", self.claimed)
        note = reply.read_text(encoding="utf-8").strip() if reply.is_file() else ""
        if produced is None:
            if (folder / "imagem.png").is_file():
                raise RuntimeError("o Codex não usou o gerador de imagens do GPT (a imagem foi feita de outro jeito); peça de novo")
            detail = note or ((getattr(done, "stderr", "") or "").strip().splitlines() or [""])[-1]
            raise RuntimeError(f"o Codex não entregou a imagem{': ' + detail[:300] if detail else ''}")
        self.claimed.add(str(produced))
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / f"{date.today().isoformat()}-{slug(job.pedido)}-{job.id}{produced.suffix.lower() or '.png'}"
        shutil.copyfile(produced, target)
        shutil.rmtree(folder, ignore_errors=True)
        return target, note[:300]
