"""Sprites dos agentes geradas por prompt: o GPT desenha (pelo Codex), a MÊTIS pixeliza.

Fluxo (docs/DESIGN.md, seção 4; modelo novo na v0.9.9, pedido do Pedro):
1. `codex exec` usa a ferramenta de imagem do Codex (o gerador de imagens do GPT) e gera um
   PNG a partir do pedido. Toda sprite segue o MODELO: a imagem de referência que o Pedro
   escolheu (`assets/sprite-modelo.png`, ou `~/.harness/agentes/sprites/modelo.png` se ele
   trocar) vai anexada como referência de estilo; do pedido vêm só as características do
   personagem. Num ajuste, a imagem anterior vai junto.
2. Só vale imagem saída do gerador do GPT (`$CODEX_HOME/generated_images`): desenho feito por
   código não serve e vira erro.
3. A pixelização acha a grade de pixels que o gerador usou (o GPT faz "pixel art falsa", com
   blocos de ~16 px e bordas borradas), reduz para essa grade pela cor mais frequente de cada
   bloco, com paleta de até 32 cores tirada só do personagem, fundo transparente, e só põe
   contorno escuro se o desenho ainda não tiver. O resultado fica num quadrado, com o
   personagem de corpo inteiro centrado e apoiado no chão.
4. Os rascunhos ficam em ~/.harness/agentes/sprites/rascunhos/<trabalho>/ até alguém
   escolher um ("Usar esta").
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_COLORS = 32
MAX_CELLS = 96  # o personagem nunca passa disso de altura
OUTLINE = (24, 16, 16, 255)
TIMEOUT_SECONDS = 360
MODEL = Path(__file__).parent / "assets" / "sprite-modelo.png"

STYLE = (
    "STYLE REFERENCE: the first attached image is the MÊTIS sprite model. Match it exactly in art style, "
    "not in identity: chunky pixel art with a coarse visible pixel grid (about 64 pixels wide by 96 tall on "
    "the whole canvas), cute chibi proportions (big head, about 2.5 heads tall), full body standing, slight "
    "three-quarter front view, thick black 1-pixel outline around every shape, flat cel shading with one "
    "shadow tone per color, warm saturated palette, gold accents, simple dot eyes and a small smile. "
    "Ancient Greek or Roman clothing (chiton, peplos, himation or toga, cloak with a round fibula clasp, "
    "Greek key meander trim, sandals), holding one object that symbolizes the character's role. "
    "Transparent background, no text, no frame, no scenery, no shadow on the ground. "
    "Do NOT copy the reference character's hair, face, colors or object unless the request asks for them. "
    "The character will stand at its desk in the MÊTIS office scene (a cozy Greco-Roman library in the same warm "
    "pixel art: wood, marble, gold, candlelight, seen from a slightly high three-quarter angle), so it must fit there: "
    "same light coming from the front-left, both feet visible and planted on the ground in a relaxed idle standing "
    "pose, nothing touching the ground besides the feet, and the held object small and close to the body."
)


def model_image(home: Path | None = None) -> Path:
    """O modelo em uso: o que o Pedro trocou em ~/.harness, senão o que vem com a MÊTIS."""
    if home is not None:
        custom = home / "agentes" / "sprites" / "modelo.png"
        if custom.is_file():
            return custom
    return MODEL


SHEET = (
    "Draw it as a 2x2 sprite sheet on a portrait 1024x1536 canvas: four frames of this same character in an "
    "idle loop, one per equal quadrant, in reading order (top-left, top-right, bottom-left, bottom-right): "
    "1 neutral standing pose; 2 breathing in (chest and shoulders one pixel higher, hair and cloak sway slightly); "
    "3 neutral again, exactly like frame 1; 4 blink (eyes closed, everything else exactly like frame 1). "
    "The character stays still (no walking, no turning): same size, same position and same feet baseline in every "
    "quadrant, centered in each quadrant and filling most of its height, with empty space between quadrants and "
    "nothing crossing into another one."
)
SINGLE = "Portrait canvas 2:3 (1024x1536), the character centered and filling most of the height."


def build_prompt(request: str, name: str, description: str, color: str, editing: bool, animated: bool = True) -> str:
    """Instrução completa para o `codex exec`. O pedido do usuário vai no fim, como está. Por
    padrão (v0.9.9) sai a folha do movimento parado: 4 quadros que a MÊTIS anima na sala."""
    who = name.strip() or "a new agent"
    role = f", whose role is: {description.strip()}" if description.strip() else ""
    task = (
        "The second attached image is this character's current sprite (a single frame or a sheet). Edit it according "
        "to the request below: keep the same character, pose and the model's style; change only what is asked."
        if editing
        else "Create one new character sprite in the model's style for the character described below."
    )
    return "\n".join(
        [
            "Use the built-in image generation tool ($imagegen, GPT image generation) exactly once. "
            "Never draw the image with code or any other program; if the image tool is not available, "
            "stop and say so in one sentence.",
            task,
            STYLE,
            SHEET if animated else SINGLE,
            f"Main clothing or accent color, unless the request says otherwise: {color}.",
            f"Character: {who}{role}.",
            f"Characteristics requested by the user (may be in Portuguese; follow them closely): {request.strip()}",
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


def cell_size(opaque, rgb) -> float:
    """Tamanho do bloco da pixel art "falsa" do gerador. Em linhas e colunas do personagem, as
    trocas de cor vizinhas (a borda borrada tem 1 a 3 px) viram uma borda só, no centro delas; o
    bloco é a distância mais comum entre duas bordas seguidas. A grade do GPT não é exata, então
    vale a média em volta do pico, e não o pico só."""
    import numpy as np

    color = rgb.astype(int)
    gaps: Counter[int] = Counter()
    h, w = opaque.shape
    lines = [(rgb_line, mask) for i in range(0, h, max(1, h // 200)) for rgb_line, mask in [(color[i], opaque[i])]]
    lines += [(color[:, j], opaque[:, j]) for j in range(0, w, max(1, w // 200))]
    for line, mask in lines:
        edge = (np.abs(np.diff(line, axis=0)).sum(axis=1) > 48) & mask[1:] & mask[:-1]
        positions = np.flatnonzero(edge)
        if positions.size < 2:
            continue
        centers = []
        group = [positions[0]]
        for pos in positions[1:]:
            if pos - group[-1] <= 3:
                group.append(pos)
            else:
                centers.append(sum(group) / len(group))
                group = [pos]
        centers.append(sum(group) / len(group))
        for a, b in zip(centers, centers[1:]):
            gap = round(b - a)
            if gap >= 4:
                gaps[gap] += 1
    if not gaps:
        return 1.0
    peak = max(range(4, 64), key=lambda g: gaps[g - 1] + gaps[g] * 2 + gaps[g + 1])
    near = {g: gaps[g] for g in range(peak - 2, peak + 3)}
    total = sum(near.values())
    return sum(g * c for g, c in near.items()) / total if total else float(peak)


def _alpha_of(src):
    """Máscara do personagem: a transparência da imagem ou, sem ela, tudo menos o fundo liso."""
    from PIL import Image

    alpha = src.getchannel("A")
    if alpha.getextrema()[0] >= 200:  # sem transparência: tira o fundo liso pelas bordas
        alpha = Image.eval(_background_mask(src), lambda v: 0 if v else 255)
    return alpha.point(lambda v: 255 if v >= 128 else 0)


def _palette(pixels, max_colors: int):
    """Paleta tirada só dos pixels do personagem (o fundo não gasta vaga)."""
    import numpy as np
    from PIL import Image

    strip = Image.fromarray(pixels.reshape(1, -1, 3).astype("uint8"), "RGB")
    palette = strip.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT, kmeans=4, dither=Image.Dither.NONE)
    return palette, np.array(palette.getpalette()[: 3 * 256], dtype=np.uint8).reshape(-1, 3)


def _reduce(figure, opaque, palette, colors, th: int, tw: int):
    """Recorte do personagem → th × tw blocos, cada um com a cor mais frequente do miolo."""
    import numpy as np
    from PIL import Image

    indices = np.asarray(figure.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE))
    h, w = opaque.shape
    cells = np.zeros((th, tw, 4), dtype=np.uint8)
    for ty in range(th):
        y0, y1 = int(ty * h / th), max(int(ty * h / th) + 1, int((ty + 1) * h / th))
        # O miolo do bloco: as bordas borradas do gerador ficam de fora da votação.
        cy0, cy1 = y0 + (y1 - y0) // 4, y1 - (y1 - y0) // 4
        for tx in range(tw):
            x0, x1 = int(tx * w / tw), max(int(tx * w / tw) + 1, int((tx + 1) * w / tw))
            cx0, cx1 = x0 + (x1 - x0) // 4, x1 - (x1 - x0) // 4
            block_mask = opaque[y0:y1, x0:x1]
            if block_mask.sum() * 2 < block_mask.size:
                continue  # bloco mais vazio que cheio: fica transparente
            core_mask = opaque[cy0:max(cy1, cy0 + 1), cx0:max(cx1, cx0 + 1)]
            core = indices[cy0:max(cy1, cy0 + 1), cx0:max(cx1, cx0 + 1)][core_mask]
            if core.size == 0:
                core = indices[y0:y1, x0:x1][block_mask]
            winner = np.bincount(core).argmax()  # cor mais frequente
            cells[ty, tx] = (*colors[winner], 255)
    return cells


def _has_dark_edge(cells) -> bool:
    """A borda do personagem já é escura (o modelo tem contorno preto)?"""
    import numpy as np

    filled = cells[..., 3] > 0
    padded = np.pad(filled, 1)
    inside = padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    edge = filled & ~inside
    if not edge.any():
        return True
    lum = cells[..., :3].astype(int) @ np.array([299, 587, 114]) // 1000
    return (lum[edge] < 70).mean() >= 0.6


def _outline(cells, add: bool):
    """Contorno escuro de 1 px em volta (só quando o desenho ainda não tem)."""
    import numpy as np

    if not add:
        return cells
    th, tw = cells.shape[:2]
    padded = np.zeros((th + 2, tw + 2, 4), dtype=np.uint8)
    padded[1:-1, 1:-1] = cells
    filled = padded[..., 3] > 0
    near = np.zeros_like(filled)
    near[1:, :] |= filled[:-1, :]
    near[:-1, :] |= filled[1:, :]
    near[:, 1:] |= filled[:, :-1]
    near[:, :-1] |= filled[:, 1:]
    padded[near & ~filled] = OUTLINE
    return padded


def _square(padded, side: int):
    """Quadrado, com o personagem centrado e apoiado no chão."""
    import numpy as np

    ph, pw = padded.shape[:2]
    canvas = np.zeros((side, side, 4), dtype=np.uint8)
    left = (side - pw) // 2
    canvas[side - ph :, left : left + pw] = padded
    return canvas


def _png(array) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.fromarray(array, "RGBA").save(out, format="PNG")
    return out.getvalue()


def _open(data: bytes):
    import io

    from PIL import Image

    src = Image.open(io.BytesIO(data)).convert("RGBA")
    if max(src.size) > 1536:
        src.thumbnail((1536, 1536), Image.Resampling.NEAREST)
    return src


def pixelize(data: bytes, max_colors: int = MAX_COLORS, max_cells: int = MAX_CELLS) -> bytes:
    """Imagem do gerador → PNG quadrado com o personagem na grade de pixels dele, fundo
    transparente, paleta curta e contorno escuro (só se ainda não tiver)."""
    import numpy as np

    src = _open(data)
    alpha = _alpha_of(src)
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("a imagem não tem personagem visível")
    figure, mask = src.crop(bbox), alpha.crop(bbox)
    rgb = np.asarray(figure.convert("RGB"))
    opaque = np.asarray(mask) > 0
    # A grade do gerador, limitada para o personagem não passar de max_cells de altura.
    h, w = opaque.shape
    size = cell_size(opaque, rgb)
    th = max(8, min(max_cells, round(h / size)))
    tw = max(4, round(w * th / h))
    palette, colors = _palette(rgb[opaque], max_colors)
    cells = _reduce(figure, opaque, palette, colors, th, tw)
    padded = _outline(cells, not _has_dark_edge(cells))
    return _png(_square(padded, max(padded.shape[:2])))


FRAMES = 4  # a folha do movimento parado: 2 × 2 quadros


def pixelize_sheet(data: bytes, cols: int = 2, rows: int = 2, max_colors: int = MAX_COLORS, max_cells: int = MAX_CELLS) -> tuple[bytes, bytes, int] | None:
    """Folha de quadros do gerador (o mesmo personagem parado, respirando e piscando, um por
    quadrante) → (a sprite parada, a tira com os quadros lado a lado, quantos quadros). Todos os
    quadros usam a mesma grade, a mesma paleta, o mesmo recorte e o mesmo contorno, e ficam
    apoiados no mesmo chão: na animação o personagem não treme. Sem personagem em algum quadrante
    (o gerador fez uma figura só), devolve None e quem chamou usa a sprite única."""
    import numpy as np

    src = _open(data)
    alpha = _alpha_of(src)
    width, height = src.size
    cw, ch = width // cols, height // rows
    frames = []
    for r in range(rows):
        for c in range(cols):
            box = (c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)
            frames.append((src.crop(box), alpha.crop(box)))
    if any(np.asarray(m).mean() / 255 < 0.02 for _, m in frames):
        return None
    # O mesmo recorte para todos: a união das caixas de cada quadro, na posição do quadrante.
    boxes = [m.getbbox() for _, m in frames]
    if any(b is None for b in boxes):
        return None
    union = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    cut = [(f.crop(union), m.crop(union)) for f, m in frames]
    first_rgb = np.asarray(cut[0][0].convert("RGB"))
    first_opaque = np.asarray(cut[0][1]) > 0
    h, w = first_opaque.shape
    size = cell_size(first_opaque, first_rgb)
    th = max(8, min(max_cells, round(h / size)))
    tw = max(4, round(w * th / h))
    pixels = np.concatenate([np.asarray(f.convert("RGB"))[np.asarray(m) > 0] for f, m in cut])
    palette, colors = _palette(pixels, max_colors)
    reduced = [_reduce(f, np.asarray(m) > 0, palette, colors, th, tw) for f, m in cut]
    add = not _has_dark_edge(reduced[0])
    padded = [_outline(cells, add) for cells in reduced]
    side = max(max(p.shape[:2]) for p in padded)
    squares = [_square(p, side) for p in padded]
    return _png(squares[0]), _png(np.concatenate(squares, axis=1)), len(squares)


def generated_since(codex_home: Path, since: float) -> list[Path]:
    """As imagens que o Codex guardou em $CODEX_HOME/generated_images desde um instante."""
    folder = codex_home / "generated_images"
    if not folder.is_dir():
        return []
    found = []
    for path in folder.rglob("*.png"):
        try:
            if path.stat().st_mtime >= since:
                found.append(path)
        except OSError:
            continue
    return sorted(found, key=lambda p: p.stat().st_mtime)


def pick_generated(candidates: list[Path], copy: Path | None, claimed: set[str]) -> Path | None:
    """Qual imagem do gerador é deste pedido. A pasta é dividida com outros usos do Codex: vale a
    idêntica à cópia que o Codex pôs no pedido; sem cópia igual (ele reduziu), a mais nova que
    nenhum outro pedido usou. Desenho que não está na pasta não serve (não saiu do GPT)."""
    free = [p for p in candidates if str(p) not in claimed]
    if copy is not None and copy.is_file():
        digest = hashlib.sha256(copy.read_bytes()).hexdigest()
        for path in reversed(free):
            if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                return path
    return free[-1] if free else None


# --- trabalhos ---------------------------------------------------------------


@dataclass
class SpriteJob:
    id: str
    prompt: str
    base: str | None
    status: str = "running"  # running → done | error
    #: v0.9.9: quadros do movimento parado (0 = só a sprite parada).
    frames: int = 0
    error: str | None = None
    note: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SpriteStudio:
    def __init__(self, home: Path, codex_env) -> None:
        """`codex_env()` devolve (executável, ambiente) da conta do Codex em uso."""
        self.home = home
        self.dir = home / "agentes" / "sprites" / "rascunhos"
        self.codex_env = codex_env
        self.jobs: dict[str, SpriteJob] = {}
        self._order: deque[str] = deque(maxlen=200)
        self._tasks: set[asyncio.Task] = set()
        # Um pedido de cada vez: a pasta de imagens do Codex é uma só, e dois juntos trocariam as imagens.
        self._turn: asyncio.Lock | None = None
        self._claimed: set[str] = set()

    def job_dir(self, job_id: str) -> Path:
        if not job_id or not job_id.isalnum():
            raise KeyError(job_id)
        return self.dir / job_id

    def image(self, job_id: str, anim: bool = False) -> Path | None:
        """A sprite parada (ou, com `anim`, a tira do movimento parado) de um trabalho pronto."""
        job = self.jobs.get(job_id)
        path = self.job_dir(job_id) / ("sprite-parado.png" if anim else "sprite-32.png")
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
        if self._turn is None:
            self._turn = asyncio.Lock()
        try:
            async with self._turn:
                await self._draw(job, folder, name, description, color)
            job.status = "done"
        except Exception as exc:  # qualquer falha vira mensagem no chat
            job.status, job.error = "error", str(exc)
        finally:
            job.finished_at = time.time()
            on_change(job)

    async def _draw(self, job: SpriteJob, folder: Path, name: str, description: str, color: str) -> None:
        started = time.time()
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
        # O modelo vai sempre; no ajuste, a sprite anterior vai em segundo.
        args += ["-i", str(model_image(self.home))]
        if job.base:
            args += ["-i", str(self.job_dir(job.base) / "original.png")]
        # "--": as imagens aceitam vários valores, e o pedido não pode virar mais uma.
        args += ["--", build_prompt(job.prompt, name, description, color, editing=bool(job.base))]
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
            raise RuntimeError("o Codex demorou mais de 6 minutos") from None
        # Só vale a imagem que saiu do gerador do GPT (a original em alta, guardada pelo Codex):
        # um sprite.png sem ela foi desenhado por código e não segue o modelo.
        codex_home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
        produced = pick_generated(generated_since(codex_home, started - 1), folder / "sprite.png", self._claimed) or folder / "nao-gerada.png"
        if not produced.is_file() and (folder / "sprite.png").is_file():
            raise RuntimeError("o Codex não usou o gerador de imagens do GPT (a imagem foi feita de outro jeito); tente de novo")
        if not produced.is_file():
            reply = folder / "resposta.txt"
            detail = reply.read_text(encoding="utf-8").strip() if reply.is_file() else ""
            if not detail and err:
                lines = err.decode("utf-8", "replace").strip().splitlines()
                detail = lines[-1] if lines else ""
            raise RuntimeError(f"o Codex não entregou a imagem{': ' + detail[:300] if detail else ''}")
        self._claimed.add(str(produced))
        raw = produced.read_bytes()
        (folder / "original.png").write_bytes(raw)
        # A folha do movimento parado vira a tira animada; se o gerador fez uma figura só, fica a parada.
        sheet = await asyncio.to_thread(pixelize_sheet, raw)
        if sheet is not None:
            still, strip, job.frames = sheet
            (folder / "sprite-32.png").write_bytes(still)
            (folder / "sprite-parado.png").write_bytes(strip)
        else:
            (folder / "sprite-32.png").write_bytes(await asyncio.to_thread(pixelize, raw))
            (folder / "sprite-parado.png").unlink(missing_ok=True)
        reply = folder / "resposta.txt"
        job.note = reply.read_text(encoding="utf-8").strip()[:300] if reply.is_file() else ""
