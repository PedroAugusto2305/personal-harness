"""Sprites por prompt: o GPT desenha pelo Codex, sempre no modelo do Pedro (v0.9.9), e a MÊTIS
reduz para a grade de pixels do gerador."""

import io
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter

from harness_core.app import create_app
from harness_core.sprites import MODEL, build_prompt, cell_size, model_image, pick_generated, pixelize, pixelize_sheet

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def fake_pixel_art(background=(240, 236, 228, 255), cell=16, cols=20, rows=40, outline=False, blur=True) -> bytes:
    """Imitação do que o gerador devolve: pixel art "falsa" de blocos de ~16 px, com bordas
    borradas, num fundo liso ou transparente, retrato 2:3."""
    width, height = 64 * cell, 96 * cell
    img = Image.new("RGBA", (width, height), background)
    draw = ImageDraw.Draw(img)
    colors = [(175, 82, 222), (226, 178, 74), (241, 199, 161), (236, 230, 216), (120, 40, 40)]
    x0, y0 = 22, 96 - rows - 4
    for y in range(rows):
        for x in range(cols):
            edge = x in (0, cols - 1) or y in (0, rows - 1)
            color = (16, 12, 12) if outline and edge else colors[(x * 7 + y * 3) % len(colors)]
            px, py = (x0 + x) * cell, (y0 + y) * cell
            draw.rectangle([px, py, px + cell - 1, py + cell - 1], fill=color + (255,))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(0.8))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_prompt_follows_the_model_uses_gpt_and_keeps_the_request():
    prompt = build_prompt("cabelo ruivo, segura uma lira dourada", "Aurora", "Coach de Estudo", "#AF52DE", editing=False)
    assert "STYLE REFERENCE" in prompt and "chibi" in prompt and "Transparent background" in prompt
    assert "$imagegen" in prompt and "Never draw the image with code" in prompt
    assert "Do NOT copy the reference character" in prompt
    assert "stand at its desk in the MÊTIS office scene" in prompt and "both feet visible" in prompt
    assert "2x2 sprite sheet" in prompt and "idle loop" in prompt and "blink" in prompt
    assert "Portrait canvas 2:3" in build_prompt("x", "A", "", "#fff", editing=False, animated=False)
    assert "do not resize" in prompt
    assert "#AF52DE" in prompt and "Aurora" in prompt and "Coach de Estudo" in prompt
    assert "cabelo ruivo, segura uma lira dourada" in prompt
    assert prompt.rstrip().endswith("describing the sprite.")
    edit = build_prompt("elmo mais dourado", "Aurora", "", "#AF52DE", editing=True)
    assert "second attached image" in edit and "STYLE REFERENCE" in edit


def test_model_ships_with_metis_and_can_be_replaced(tmp_path):
    assert MODEL.is_file() and Image.open(MODEL).size == (1024, 1536)
    assert model_image(tmp_path) == MODEL
    custom = tmp_path / "agentes" / "sprites" / "modelo.png"
    custom.parent.mkdir(parents=True)
    custom.write_bytes(MODEL.read_bytes())
    assert model_image(tmp_path) == custom


def test_cell_size_finds_the_generator_grid():
    import numpy as np

    img = Image.open(io.BytesIO(fake_pixel_art(background=(0, 0, 0, 0)))).convert("RGBA")
    a = np.asarray(img)
    assert 15 <= cell_size(a[..., 3] > 128, a[..., :3]) <= 17


def test_pixelize_keeps_the_generator_grid_and_adds_outline_only_when_missing():
    out = Image.open(io.BytesIO(pixelize(fake_pixel_art())))
    # 20 × 40 blocos + 1 px de contorno em volta → 42 de altura, num quadrado.
    assert out.size == (42, 42) and out.mode == "RGBA"
    pixels = [out.getpixel((x, y)) for y in range(42) for x in range(42)]
    assert out.getpixel((0, 0))[3] == 0  # fundo liso virou transparente
    assert all(p[3] in (0, 255) for p in pixels)  # sem meio-transparente
    opaque = {p[:3] for p in pixels if p[3] == 255}
    assert (24, 16, 16) in opaque and len(opaque) <= 33  # até 32 cores + o contorno
    assert out.getbbox()[3] == 42  # apoiado no chão

    # O modelo já vem com contorno preto: não ganha outro.
    framed = Image.open(io.BytesIO(pixelize(fake_pixel_art(background=(0, 0, 0, 0), outline=True))))
    assert framed.size == (40, 40)


def test_pixelize_handles_the_real_model():
    out = Image.open(io.BytesIO(pixelize(MODEL.read_bytes())))
    w, h = out.size
    assert w == h and 70 <= h <= 96  # a grade do modelo (~80 de altura), não os 48 de antes
    bbox = out.getbbox()
    assert bbox[3] == h and (bbox[2] - bbox[0]) < h  # corpo inteiro, mais alto que largo


def wait_job(client, job_id: str, timeout: float = 20) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/sprites/jobs/{job_id}", headers=AUTH).json()
        if job["status"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("o trabalho não terminou")


def fake_codex(bin_dir: Path, record: Path, fixture: Path, codex_home: Path, generate: bool = True) -> None:
    """Codex de mentira: grava os argumentos, põe a "imagem do GPT" onde o Codex guarda e responde."""
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "codex"
    lines = [
        "#!/bin/sh",
        f'printf "%s\\n" "$@" > "{record}"',
        'out=""; dir=""',
        'while [ $# -gt 0 ]; do case "$1" in -C) dir="$2"; shift;; -o) out="$2"; shift;; esac; shift; done',
        f'cp "{fixture}" "$dir/sprite.png"',
        'printf "Guerreira com elmo coríntio." > "$out"',
    ]
    if generate:
        lines.insert(-2, f'mkdir -p "{codex_home}/generated_images/t1" && cp "{fixture}" "{codex_home}/generated_images/t1/ig_$$.png"')
    fake.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fake.chmod(0o755)


def test_sprite_job_sends_the_model_to_gpt_pixelizes_and_becomes_the_agent_sprite(settings, accounts, tmp_path, monkeypatch):
    fixture = tmp_path / "gerada.png"
    fixture.write_bytes(fake_pixel_art())
    record = tmp_path / "codex-args.txt"
    codex_home = tmp_path / "codex-home"
    fake_codex(tmp_path / "bin", record, fixture, codex_home)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        agent = client.post("/agents", json={"name": "Aurora", "color": "#AF52DE"}, headers=AUTH).json()
        started = client.post("/sprites/jobs", json={"prompt": "guerreira espartana", "name": "Aurora", "color": "#AF52DE"}, headers=AUTH)
        assert started.status_code == 202
        job = wait_job(client, started.json()["id"])
        assert job["status"] == "done", job
        assert job["note"] == "Guerreira com elmo coríntio."
        args = record.read_text(encoding="utf-8").splitlines()
        assert args[0] == "exec" and "--ephemeral" in args and "workspace-write" in args
        # O modelo vai sempre como imagem, e o pedido vem depois do "--".
        assert args[args.index("-i") + 1] == str(MODEL)
        assert args[args.index("--") + 1].startswith("Use the built-in image generation tool")

        image = client.get(f"/sprites/jobs/{job['id']}/image", params={"token": TOKEN})
        assert image.status_code == 200 and Image.open(io.BytesIO(image.content)).size == (42, 42)
        assert client.get(f"/sprites/jobs/{job['id']}/image").status_code == 401

        # Ajuste: o modelo e a imagem anterior vão juntos.
        edit = wait_job(client, client.post("/sprites/jobs", json={"prompt": "elmo dourado", "base": job["id"]}, headers=AUTH).json()["id"])
        assert edit["status"] == "done"
        args = record.read_text(encoding="utf-8").splitlines()
        images = [args[i + 1] for i, a in enumerate(args) if a == "-i"]
        assert images[0] == str(MODEL) and images[1].endswith(f"{job['id']}/original.png")
        assert client.post("/sprites/jobs", json={"prompt": "x", "base": "naoexiste"}, headers=AUTH).status_code == 404

        assert client.post(f"/agents/{agent['id']}/sprite/from-job", json={"job": edit["id"]}, headers=AUTH).status_code == 204
        assert client.get("/agents", headers=AUTH).json()[0]["sprite"] is True
        saved = Path(settings.home / "agentes" / "sprites" / f"{agent['id']}.png").read_bytes()
        assert Image.open(io.BytesIO(saved)).size == (42, 42)


def test_image_not_from_the_gpt_generator_is_refused(settings, accounts, tmp_path, monkeypatch):
    """Sprite.png sem imagem do gerador = desenhada por código: não segue o modelo."""
    fixture = tmp_path / "gerada.png"
    fixture.write_bytes(fake_pixel_art())
    fake_codex(tmp_path / "bin", tmp_path / "args.txt", fixture, tmp_path / "codex-home", generate=False)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        job = wait_job(client, client.post("/sprites/jobs", json={"prompt": "filósofo"}, headers=AUTH).json()["id"])
        assert job["status"] == "error" and "gerador de imagens do GPT" in job["error"]


def test_sprite_job_reports_when_codex_delivers_nothing(settings, accounts, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "codex"
    fake.write_text('#!/bin/sh\necho "limite de imagens atingido" >&2\nexit 1\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        job = wait_job(client, client.post("/sprites/jobs", json={"prompt": "filósofo"}, headers=AUTH).json()["id"])
        assert job["status"] == "error" and "limite de imagens atingido" in job["error"]


def test_job_keeps_the_full_size_original_from_the_generator(settings, accounts, tmp_path, monkeypatch):
    """O Codex às vezes reduz a imagem antes de salvar; a MÊTIS pega a original em $CODEX_HOME."""
    codex_home = tmp_path / "codex-home"
    big = fake_pixel_art()
    small = io.BytesIO()
    Image.open(io.BytesIO(big)).resize((32, 48)).save(small, format="PNG")
    (tmp_path / "pequena.png").write_bytes(small.getvalue())
    (tmp_path / "grande.png").write_bytes(big)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "codex"
    fake.write_text(
        "#!/bin/sh\n"
        'dir=""; while [ $# -gt 0 ]; do case "$1" in -C) dir="$2"; shift;; esac; shift; done\n'
        f'mkdir -p "{codex_home}/generated_images/s1"\n'
        f'cp "{tmp_path / "grande.png"}" "{codex_home}/generated_images/s1/exec-1.png"\n'
        f'cp "{tmp_path / "pequena.png"}" "$dir/sprite.png"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        job = wait_job(client, client.post("/sprites/jobs", json={"prompt": "hoplita"}, headers=AUTH).json()["id"])
        assert job["status"] == "done"
        kept = settings.home / "agentes" / "sprites" / "rascunhos" / job["id"] / "original.png"
        assert Image.open(kept).size == (1024, 1536)  # guardou a original, não a miniatura


def test_pick_generated_takes_the_jobs_own_image(tmp_path):
    """A pasta do Codex é dividida: vale a imagem idêntica à cópia do pedido, nunca a de outro pedido."""
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"imagem-a")
    b.write_bytes(b"imagem-b")
    copy = tmp_path / "sprite.png"
    copy.write_bytes(b"imagem-a")
    assert pick_generated([a, b], copy, set()) == a  # b é mais nova, mas a cópia do pedido é a
    copy.unlink()
    assert pick_generated([a, b], copy, set()) == b  # sem cópia: a mais nova
    assert pick_generated([a, b], copy, {str(b)}) == a  # a mais nova já foi de outro pedido
    assert pick_generated([a], copy, {str(a)}) is None


def fake_sheet(cell=16, cols=20, rows=40) -> bytes:
    """Folha 2 × 2 de mentira: o mesmo personagem nos quatro quadrantes; no 2º ele sobe um bloco
    (respirando) e no 4º os "olhos" fecham (uma faixa escura)."""
    width, height = 1024, 1536
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    colors = [(175, 82, 222), (226, 178, 74), (241, 199, 161), (236, 230, 216)]
    for q in range(4):
        qx, qy = (q % 2) * 512, (q // 2) * 768
        lift = cell if q == 1 else 0
        for y in range(rows):
            for x in range(cols):
                color = colors[(x * 7 + y * 3) % len(colors)]
                if q == 3 and y == 5:
                    color = (20, 14, 14)
                px, py = qx + 96 + x * cell, qy + 80 + y * cell - lift
                draw.rectangle([px, py, px + cell - 1, py + cell - 1], fill=color + (255,))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_pixelize_sheet_makes_a_stable_idle_strip():
    still, strip, frames = pixelize_sheet(fake_sheet())
    assert frames == 4
    one = Image.open(io.BytesIO(still))
    band = Image.open(io.BytesIO(strip))
    side = one.size[0]
    assert one.size == (side, side) and band.size == (side * 4, side)
    # Mesmo recorte e mesmo chão: o quadro 3 é igual ao 1, o 2 está um bloco acima, o 4 pisca.
    f = [band.crop((i * side, 0, (i + 1) * side, side)) for i in range(4)]
    assert f[0].tobytes() == f[2].tobytes()
    assert f[0].getbbox()[3] == side and f[1].getbbox()[3] == side - 1
    assert f[0].tobytes() != f[3].tobytes()
    # Figura única (o gerador ignorou a folha): não é folha.
    assert pixelize_sheet(fake_pixel_art(background=(0, 0, 0, 0))) is None


def test_sheet_job_gives_the_agent_an_animated_sprite(settings, accounts, tmp_path, monkeypatch):
    fixture = tmp_path / "folha.png"
    fixture.write_bytes(fake_sheet())
    codex_home = tmp_path / "codex-home"
    fake_codex(tmp_path / "bin", tmp_path / "args.txt", fixture, codex_home)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        agent = client.post("/agents", json={"name": "Aurora"}, headers=AUTH).json()
        job = wait_job(client, client.post("/sprites/jobs", json={"prompt": "coach"}, headers=AUTH).json()["id"])
        assert job["status"] == "done" and job["frames"] == 4
        strip = client.get(f"/sprites/jobs/{job['id']}/image", params={"token": TOKEN, "anim": 1})
        size = Image.open(io.BytesIO(strip.content)).size
        assert strip.status_code == 200 and size[0] == size[1] * 4
        assert client.post(f"/agents/{agent['id']}/sprite/from-job", json={"job": job["id"]}, headers=AUTH).status_code == 204
        listed = client.get("/agents", headers=AUTH).json()[0]
        assert listed["sprite"] is True and listed["sprite_frames"] == 4
        assert client.get(f"/agents/{agent['id']}/sprite", params={"token": TOKEN, "anim": 1}).status_code == 200
        # Um PNG enviado à mão troca a sprite e tira a animação antiga (não é do mesmo desenho).
        png = io.BytesIO()
        Image.new("RGBA", (16, 16), (200, 0, 0, 255)).save(png, format="PNG")
        assert client.post(f"/agents/{agent['id']}/sprite", content=png.getvalue(), headers=AUTH).status_code == 204
        assert client.get("/agents", headers=AUTH).json()[0]["sprite_frames"] == 0
        assert client.get(f"/agents/{agent['id']}/sprite", params={"token": TOKEN, "anim": 1}).status_code == 404
