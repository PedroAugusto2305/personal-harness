"""Anexos da barra de entrada: o arquivo vai para ~/.harness/anexos e o agente recebe o caminho.

As duas CLIs aceitam caminho de arquivo no prompt (imagem inclusive), então anexar é
salvar num lugar estável e colar o caminho. Arrastar do Finder no app já entrega o
caminho original; o upload só existe para o seletor de arquivos e para o navegador.
"""

from __future__ import annotations

import io
import re
import subprocess
import uuid
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
_run = subprocess.run


def _is_avif(data: bytes) -> bool:
    """Reconhece AVIF pelo box ``ftyp``, mesmo com uma extensão enganosa.

    O WebKit entrega alguns arquivos do clipboard como AVIF chamado ``.png``. O nome,
    portanto, não serve para decidir se o agente conseguirá abrir o anexo.
    """
    if len(data) < 16 or data[4:8] != b"ftyp":
        return False
    brands = [data[8:12], *(data[i : i + 4] for i in range(16, min(len(data), 64), 4))]
    return b"avif" in brands or b"avis" in brands


def _avif_to_png(data: bytes, target: Path) -> None:
    """Decodifica de memória para poder sobrescrever um AVIF chamado ``.png``."""
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source)
        image.save(target, format="PNG")


def safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    cleaned = re.sub(r"[^\w.\-]+", "-", base).strip("-.")
    return cleaned[:120] or "anexo"


def save_attachment(home: Path, name: str, data: bytes) -> Path:
    folder = home / "anexos" / date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    (home / "anexos").chmod(0o700)
    target = folder / f"{uuid.uuid4().hex[:8]}-{safe_name(name)}"
    target.write_bytes(data)
    target.chmod(0o600)
    # O macOS pode entregar um print/arquivo do clipboard em AVIF chamado `.png`, ou em
    # JPEG XL. Claude, Codex e a conversa não leem esses formatos de modo consistente.
    # Normalize no ingresso: o caminho colado no terminal aponta para um PNG de verdade.
    if _is_avif(data):
        png = target if target.suffix.lower() == ".png" else target.with_suffix(".png")
        try:
            _avif_to_png(data, png)
            png.chmod(0o600)
            if png != target:
                target.unlink()
            return png
        except (OSError, ValueError, Image.DecompressionBombError):
            if png != target:
                png.unlink(missing_ok=True)
            else:
                target.write_bytes(data)  # a gravação do PNG pode ter truncado o original
                target.chmod(0o600)
    if target.suffix.lower() == ".jxl":
        png = target.with_suffix(".png")
        try:
            converted = _run(
                ["/usr/bin/sips", "-s", "format", "png", str(target), "--out", str(png)],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if converted.returncode == 0 and png.is_file():
                png.chmod(0o600)
                target.unlink()
                return png
            png.unlink(missing_ok=True)
        except (OSError, subprocess.SubprocessError):
            png.unlink(missing_ok=True)
    return target
