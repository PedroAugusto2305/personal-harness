"""Sprites dos agentes geradas por prompt: o Codex desenha, a MÊTIS pixeliza.

Fluxo (docs/DESIGN.md, seção 4):
1. `codex exec` com a ferramenta de imagem gera um PNG a partir do pedido, sempre no
   estilo greco-romano da MÊTIS. Num ajuste, a imagem anterior vai junto (`-i`).
2. A imagem original, em alta, passa pela pixelização: fundo transparente, recorte,
   paleta de até 24 cores tirada só do personagem, redução pela cor mais frequente de
   cada bloco (média deixa tudo marrom) e contorno escuro de 1 px, numa grade de 48 × 48.
   Modelo de imagem faz "pixel art falsa"; isso deixa todas as sprites do mesmo jogo.
3. Os rascunhos ficam em ~/.harness/agentes/sprites/rascunhos/<trabalho>/ até alguém
   escolher um ("Usar esta").
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

GRID = 48
MAX_COLORS = 24
OUTLINE = (28, 24, 40, 255)
TIMEOUT_SECONDS = 300

STYLE = (
    "Mandatory style for every MÊTIS agent sprite: a single character in pixel art, readable at 48x48, "
    "full body, front view, centered, in Ancient Greek or Roman style: chiton, peplos or toga, cloak (chlamys) "
    "with a fibula clasp, sandals, and when it fits a laurel wreath, Corinthian or Attic helmet, diadem, spear, "
    "shield, scroll or lyre; marble, bronze and gold details. Crisp square pixels, flat shading, limited palette "
    "(at most 16 colors), 1px dark outline, no text, no frame, no scenery, transparent background "
    "(if transparency is impossible, one flat plain background color)."
)


def build_prompt(request: str, name: str, description: str, color: str, editing: bool) -> str:
    """Instrução completa para o `codex exec`. O pedido do usuário vai no fim, como está."""
    who = name.strip() or "a new agent"
    role = f", whose role is: {description.strip()}" if description.strip() else ""
    task = (
        "Edit the attached sprite image according to the request below. Keep the same character, pose, "
        "framing and style; change only what is asked."
        if editing
        else "Create one sprite image for the character described below."
    )
    return "\n".join(
        [
            "Use the built-in image generation tool ($imagegen) exactly once.",
            task,
            STYLE,
            f"Main clothing or accent color: {color}.",
            f"Character: {who}{role}.",
            f"Request from the user (may be in Portuguese): {request.strip()}",
            "Copy the generated PNG to ./sprite.png exactly as generated: do not resize, crop, redraw or edit it "
            "(MÊTIS does the pixelization). Do not create or change any other file.",
            "When done, answer with one short sentence in Portuguese describing the sprite.",
        ]
    )


# --- pixelização --------------------------------------------------------------


def _background_mask(img, tolerance: int = 40):
    """Pixels ligados às bordas e parecidos com a cor dos cantos: é o fundo."""
    from PIL import Image

    rgb = img.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]

    def near(c, ref) -> bool:
        return sum(abs(a - b) for a, b in zip(c, ref)) <= tolerance

    mask = Image.new("L", (w, h), 0)
    seen = mask.load()
    stack = [(x, y) for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    while stack:
        x, y = stack.pop()
        if x < 0 or y < 0 or x >= w or y >= h or seen[x, y]:
            continue
        if not any(near(px[x, y], ref) for ref in corners):
            continue
        seen[x, y] = 255
        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return mask


def pixelize(data: bytes, grid: int = GRID, max_colors: int = MAX_COLORS) -> bytes:
    """Imagem qualquer → PNG grid × grid com fundo transparente, paleta curta e contorno."""
    import io

    import numpy as np
    from PIL import Image

    src = Image.open(io.BytesIO(data)).convert("RGBA")
    # Até 512 px: a pixel art "falsa" do gerador tem blocos grandes, nada se perde aqui.
    if max(src.size) > 512:
        src.thumbnail((512, 512), Image.Resampling.NEAREST)
    alpha = src.getchannel("A")
    if alpha.getextrema()[0] >= 200:  # sem transparência: tira o fundo liso pelas bordas
        alpha = Image.eval(_background_mask(src), lambda v: 0 if v else 255)
    alpha = alpha.point(lambda v: 255 if v >= 128 else 0)
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("a imagem não tem personagem visível")
    figure, mask = src.crop(bbox), alpha.crop(bbox)

    # Paleta tirada só dos pixels do personagem (o fundo não gasta vaga).
    rgb = np.asarray(figure.convert("RGB"))
    opaque = np.asarray(mask) > 0
    strip = Image.fromarray(rgb[opaque].reshape(1, -1, 3).astype("uint8"), "RGB")
    palette = strip.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT, kmeans=4, dither=Image.Dither.NONE)
    indices = np.asarray(figure.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE))
    colors = np.array(palette.getpalette()[: 3 * 256], dtype=np.uint8).reshape(-1, 3)

    # Cabe na grade (1 px de folga para o contorno), sem distorcer.
    h, w = indices.shape
    inner = grid - 2
    scale = min(inner / w, inner / h)
    tw, th = max(1, round(w * scale)), max(1, round(h * scale))
    cells = np.zeros((th, tw, 4), dtype=np.uint8)
    for ty in range(th):
        y0, y1 = int(ty * h / th), max(int(ty * h / th) + 1, int((ty + 1) * h / th))
        for tx in range(tw):
            x0, x1 = int(tx * w / tw), max(int(tx * w / tw) + 1, int((tx + 1) * w / tw))
            block_mask = opaque[y0:y1, x0:x1]
            if block_mask.sum() * 2 < block_mask.size:
                continue  # bloco mais vazio que cheio: fica transparente
            winner = np.bincount(indices[y0:y1, x0:x1][block_mask]).argmax()  # cor mais frequente
            cells[ty, tx] = (*colors[winner], 255)

    # Contorno escuro de 1 px em volta do personagem.
    padded = np.zeros((th + 2, tw + 2, 4), dtype=np.uint8)
    padded[1:-1, 1:-1] = cells
    filled = padded[..., 3] > 0
    near = np.zeros_like(filled)
    near[1:, :] |= filled[:-1, :]
    near[:-1, :] |= filled[1:, :]
    near[:, 1:] |= filled[:, :-1]
    near[:, :-1] |= filled[:, 1:]
    padded[near & ~filled] = OUTLINE

    # Centrado e apoiado no chão da grade.
    canvas = np.zeros((grid, grid, 4), dtype=np.uint8)
    ph, pw = padded.shape[:2]
    left = (grid - pw) // 2
    canvas[grid - ph :, left : left + pw] = padded
    out = io.BytesIO()
    Image.fromarray(canvas, "RGBA").save(out, format="PNG")
    return out.getvalue()


def newest_generated(codex_home: Path, since: float) -> Path | None:
    """A imagem original que o Codex guardou em $CODEX_HOME/generated_images."""
    folder = codex_home / "generated_images"
    if not folder.is_dir():
        return None
    found = [p for p in folder.rglob("*.png") if p.stat().st_mtime >= since]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


# --- trabalhos ---------------------------------------------------------------


@dataclass
class SpriteJob:
    id: str
    prompt: str
    base: str | None
    status: str = "running"  # running → done | error
    error: str | None = None
    note: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SpriteStudio:
    def __init__(self, home: Path, codex_env) -> None:
        """`codex_env()` devolve (executável, ambiente) da conta do Codex em uso."""
        self.dir = home / "agentes" / "sprites" / "rascunhos"
        self.codex_env = codex_env
        self.jobs: dict[str, SpriteJob] = {}
        self._order: deque[str] = deque(maxlen=200)
        self._tasks: set[asyncio.Task] = set()

    def job_dir(self, job_id: str) -> Path:
        if not job_id or not job_id.isalnum():
            raise KeyError(job_id)
        return self.dir / job_id

    def image(self, job_id: str) -> Path | None:
        job = self.jobs.get(job_id)
        path = self.job_dir(job_id) / "sprite-32.png"
        return path if job and job.status == "done" and path.is_file() else None

    def start(self, prompt: str, name: str, description: str, color: str, base: str | None, on_change) -> SpriteJob:
        if base and not self.image(base):
            raise KeyError(base)
        job = SpriteJob(id=uuid.uuid4().hex[:12], prompt=prompt.strip(), base=base)
        self.jobs[job.id] = job
        self._order.append(job.id)
        task = asyncio.create_task(self._run(job, name, description, color, on_change))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: SpriteJob, name: str, description: str, color: str, on_change) -> None:
        folder = self.job_dir(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "pedido.json").write_text(
            json.dumps({"prompt": job.prompt, "base": job.base, "name": name, "color": color}, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            executable, env = self.codex_env()
            if not executable:
                raise RuntimeError("o Codex não está instalado (comando codex não encontrado)")
            args = [
                executable,
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "workspace-write",
                "-c",
                'approval_policy="never"',
                "-C",
                str(folder),
                "-o",
                str(folder / "resposta.txt"),
            ]
            if job.base:
                args += ["-i", str(self.job_dir(job.base) / "original.png")]
            args.append(build_prompt(job.prompt, name, description, color, editing=bool(job.base)))
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), TIMEOUT_SECONDS)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError("o Codex demorou mais de 5 minutos") from None
            produced = folder / "sprite.png"
            # Se o Codex reduziu a imagem por conta própria, a original em alta vale mais.
            codex_home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
            original = newest_generated(codex_home, job.created_at - 1)
            if original is not None and (not produced.is_file() or produced.stat().st_size < original.stat().st_size):
                produced = original
            if not produced.is_file():
                reply = folder / "resposta.txt"
                detail = reply.read_text(encoding="utf-8").strip() if reply.is_file() else ""
                if not detail and err:
                    lines = err.decode("utf-8", "replace").strip().splitlines()
                    detail = lines[-1] if lines else ""
                raise RuntimeError(f"o Codex não entregou a imagem{': ' + detail[:300] if detail else ''}")
            raw = produced.read_bytes()
            (folder / "original.png").write_bytes(raw)
            (folder / "sprite-32.png").write_bytes(await asyncio.to_thread(pixelize, raw))
            reply = folder / "resposta.txt"
            job.note = reply.read_text(encoding="utf-8").strip()[:300] if reply.is_file() else ""
            job.status = "done"
        except Exception as exc:  # qualquer falha vira mensagem no chat
            job.status, job.error = "error", str(exc)
        finally:
            job.finished_at = time.time()
            on_change(job)
