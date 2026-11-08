"""Sprites por prompt: pedido ao Codex no estilo greco-romano e pixelização em 32 × 32."""

import io
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from harness_core.app import create_app
from harness_core.sprites import GRID, build_prompt, pixelize

from .conftest import TOKEN

AUTH = {"X-Harness-Token": TOKEN}


def fake_pixel_art(background=(240, 236, 228, 255), size=768, noise=True) -> bytes:
    """Imitação do que o gerador devolve: pixel art "falsa" grande, num fundo liso."""
    img = Image.new("RGBA", (size, size), background)
    draw = ImageDraw.Draw(img)
    cell = size // 48
    colors = [(27, 23, 38), (175, 82, 222), (226, 178, 74), (241, 199, 161), (236, 230, 216)]
    for y in range(8, 44):
        for x in range(16, 32):
            color = colors[(x * 7 + y * 3) % len(colors)]
            if noise:
                color = tuple(min(255, c + ((x + y) % 3)) for c in color)
            draw.rectangle([x * cell, y * cell, (x + 1) * cell - 1, (y + 1) * cell - 1], fill=color + (255,))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_prompt_always_carries_the_greco_roman_style_and_the_request():
    prompt = build_prompt("guerreira espartana com lança", "Aurora", "Coach de Estudo", "#AF52DE", editing=False)
    assert "Ancient Greek or Roman" in prompt and "48x48" in prompt and "transparent background" in prompt
    assert "do not resize" in prompt
    assert "#AF52DE" in prompt and "Aurora" in prompt and "Coach de Estudo" in prompt
    assert prompt.rstrip().endswith("describing the sprite.")
    assert "guerreira espartana com lança" in prompt
    edit = build_prompt("elmo mais dourado", "Aurora", "", "#AF52DE", editing=True)
    assert "Edit the attached sprite" in edit and "Ancient Greek or Roman" in edit


def test_pixelize_makes_a_transparent_sprite_with_short_palette_and_outline():
    out = Image.open(io.BytesIO(pixelize(fake_pixel_art())))
    assert out.size == (GRID, GRID) and out.mode == "RGBA"
    pixels = [out.getpixel((x, y)) for y in range(GRID) for x in range(GRID)]
    assert out.getpixel((0, 0))[3] == 0 and out.getpixel((GRID - 1, 0))[3] == 0  # fundo liso virou transparente
    opaque = {p[:3] for p in pixels if p[3] == 255}
    assert opaque and len(opaque) <= 25  # até 24 cores + o contorno
    assert (28, 24, 40) in opaque  # contorno escuro
    assert all(p[3] in (0, 255) for p in pixels)  # sem meio-transparente
    assert out.getbbox()[3] == GRID  # apoiado no chão da grade


def test_pixelize_respects_real_transparency():
    out = Image.open(io.BytesIO(pixelize(fake_pixel_art(background=(0, 0, 0, 0)))))
    assert out.size == (GRID, GRID) and out.getpixel((0, 0))[3] == 0


def wait_job(client, job_id: str, timeout: float = 20) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/sprites/jobs/{job_id}", headers=AUTH).json()
        if job["status"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("o trabalho não terminou")


def test_sprite_job_runs_codex_pixelizes_and_becomes_the_agent_sprite(settings, accounts, tmp_path, monkeypatch):
    fixture = tmp_path / "gerada.png"
    fixture.write_bytes(fake_pixel_art())
    record = tmp_path / "codex-args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "codex"
    # Codex de mentira: grava os argumentos, copia a "imagem gerada" e responde.
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{record}"\n'
        'out=""; dir=""\n'
        'while [ $# -gt 0 ]; do case "$1" in -C) dir="$2"; shift;; -o) out="$2"; shift;; esac; shift; done\n'
        f'cp "{fixture}" "$dir/sprite.png"\n'
        'printf "Guerreira com elmo coríntio." > "$out"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        agent = client.post("/agents", json={"name": "Aurora", "color": "#AF52DE"}, headers=AUTH).json()
        started = client.post(
            "/sprites/jobs", json={"prompt": "guerreira espartana", "name": "Aurora", "color": "#AF52DE"}, headers=AUTH
        )
        assert started.status_code == 202
        job = wait_job(client, started.json()["id"])
        assert job["status"] == "done", job
        assert job["note"] == "Guerreira com elmo coríntio."
        args = record.read_text(encoding="utf-8").splitlines()
        assert args[0] == "exec" and "--ephemeral" in args and "workspace-write" in args
        assert any("Ancient Greek or Roman" in a for a in args) and "-i" not in args

        image = client.get(f"/sprites/jobs/{job['id']}/image", params={"token": TOKEN})
        assert image.status_code == 200 and Image.open(io.BytesIO(image.content)).size == (GRID, GRID)
        assert client.get(f"/sprites/jobs/{job['id']}/image").status_code == 401

        # Ajuste: a imagem anterior vai junto para o Codex editar.
        edit = wait_job(client, client.post("/sprites/jobs", json={"prompt": "elmo dourado", "base": job["id"]}, headers=AUTH).json()["id"])
        assert edit["status"] == "done"
        args = record.read_text(encoding="utf-8").splitlines()
        assert args[args.index("-i") + 1].endswith(f"{job['id']}/original.png")
        assert client.post("/sprites/jobs", json={"prompt": "x", "base": "naoexiste"}, headers=AUTH).status_code == 404

        assert client.post(f"/agents/{agent['id']}/sprite/from-job", json={"job": edit["id"]}, headers=AUTH).status_code == 204
        assert client.get("/agents", headers=AUTH).json()[0]["sprite"] is True
        saved = Path(settings.home / "agentes" / "sprites" / f"{agent['id']}.png").read_bytes()
        assert Image.open(io.BytesIO(saved)).size == (GRID, GRID)


def test_sprite_job_reports_when_codex_delivers_nothing(settings, accounts, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "codex"
    fake.write_text('#!/bin/sh\necho "limite de imagens atingido" >&2\nexit 1\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        job = wait_job(client, client.post("/sprites/jobs", json={"prompt": "filósofo"}, headers=AUTH).json()["id"])
        assert job["status"] == "error" and "limite de imagens atingido" in job["error"]


def test_job_prefers_the_full_size_original_over_a_shrunk_copy(settings, accounts, tmp_path, monkeypatch):
    """O Codex às vezes reduz a imagem antes de salvar; a MÊTIS pega a original em $CODEX_HOME."""
    codex_home = tmp_path / "codex-home"
    big = fake_pixel_art()
    small = io.BytesIO()
    Image.open(io.BytesIO(big)).resize((32, 32)).save(small, format="PNG")
    (tmp_path / "pequena.png").write_bytes(small.getvalue())
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
    (tmp_path / "grande.png").write_bytes(big)
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    with TestClient(create_app(settings, accounts=accounts, poll_codex=False, poll_ports=False)) as client:
        job = wait_job(client, client.post("/sprites/jobs", json={"prompt": "hoplita"}, headers=AUTH).json()["id"])
        assert job["status"] == "done"
        kept = settings.home / "agentes" / "sprites" / "rascunhos" / job["id"] / "original.png"
        assert Image.open(kept).size == (768, 768)  # guardou a original, não a miniatura
