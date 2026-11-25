"""Anexos da barra de entrada: o arquivo vai para ~/.harness/anexos e o agente recebe o caminho.

As duas CLIs aceitam caminho de arquivo no prompt (imagem inclusive), então anexar é
salvar num lugar estável e colar o caminho. Arrastar do Finder no app já entrega o
caminho original; o upload só existe para o seletor de arquivos e para o navegador.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import tempfile
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


# --- prévia dos anexos (v1.7.0) ------------------------------------------------------------------
#
# A barra mostra cada anexo como prévia, no lugar do caminho: a miniatura da imagem, um quadro do
# vídeo, a primeira página do PDF, e ícone com nome e tamanho quando não há desenho possível. O
# agente continua recebendo o caminho, como antes. A miniatura da imagem sai do Pillow; a dos
# outros tipos, do QuickLook do macOS (`qlmanage -t`), que desenha vídeo, PDF, texto e documentos.

KIND_BY_EXT: dict[str, str] = {}
for _kind, _exts in {
    "imagem": "png jpg jpeg gif webp svg avif bmp heic heif tif tiff ico",
    "video": "mp4 mov m4v webm mkv avi mpg mpeg 3gp",
    "audio": "mp3 m4a wav aac ogg oga flac aiff aif opus",
    "pdf": "pdf",
    "planilha": "xlsx xls csv tsv numbers ods",
    "apresentacao": "ppt pptx key odp",
    "documento": "doc docx pages rtf odt md markdown txt",
    "compactado": "zip tar gz tgz bz2 xz rar 7z dmg",
    "codigo": "py ts tsx js jsx mjs json html css scss sh zsh rs go java rb swift kt c cc cpp h hpp yaml yml toml sql ipynb",
}.items():
    for _ext in _exts.split():
        KIND_BY_EXT[_ext] = _kind

MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".avif": "image/avif", ".bmp": "image/bmp", ".svg": "image/svg+xml", ".heic": "image/heic",
    ".mp4": "video/mp4", ".m4v": "video/x-m4v", ".mov": "video/quicktime", ".webm": "video/webm",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".aac": "audio/aac", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".flac": "audio/flac", ".opus": "audio/ogg",
}  # fmt: skip
#: Acima disso a prévia nem é tentada: ícone, nome e tamanho (o anexo vai do mesmo jeito).
MAX_PREVIEW_BYTES = 2 * 1024 * 1024 * 1024
#: O QuickLook que demora mais que isso (arquivo enorme, formato estranho) fica sem desenho.
PREVIEW_TIMEOUT = 8
THUMB_SIZES = (96, 192, 384, 768)


def kind_of(name: str) -> str:
    """imagem, video, audio, pdf, planilha, apresentacao, documento, compactado, codigo ou arquivo."""
    return KIND_BY_EXT.get(Path(name).suffix.lower().lstrip("."), "arquivo")


def local_file(path: str) -> Path | None:
    """O arquivo comum (não pasta, não link para pasta) num caminho absoluto, ou None."""
    target = Path(os.path.expanduser(path or ""))
    if not target.is_absolute() or not target.is_file():
        return None
    return target


def describe(path: Path) -> dict:
    """O que a barra mostra de um anexo: nome, tamanho e tipo."""
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    return {"caminho": str(path), "nome": path.name, "tamanho": size, "tipo": kind_of(path.name)}


def _image_thumbnail(path: Path, px: int) -> bytes | None:
    try:
        with Image.open(path) as source:
            source.seek(0)  # GIF e WebP animados: o primeiro quadro
            image = ImageOps.exif_transpose(source)
            image.thumbnail((px, px))
            if image.mode not in ("RGB", "RGBA", "L", "LA"):
                image = image.convert("RGBA")
            out = io.BytesIO()
            image.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def _quicklook_thumbnail(path: Path, px: int) -> bytes | None:
    with tempfile.TemporaryDirectory(prefix="metis-ql-") as folder:
        try:
            _run(["/usr/bin/qlmanage", "-t", "-s", str(px), "-o", folder, str(path)],
                 capture_output=True, timeout=PREVIEW_TIMEOUT, check=False)  # fmt: skip
        except (OSError, subprocess.SubprocessError):
            return None
        made = sorted(Path(folder).glob("*.png"))
        return made[0].read_bytes() if made else None


def thumbnail(home: Path, path: Path, px: int = 192) -> bytes | None:
    """PNG da prévia de um arquivo, guardado em <home>/cache/miniaturas (a chave muda quando o
    arquivo muda). None quando não há desenho possível: a barra mostra ícone, nome e tamanho."""
    px = min(THUMB_SIZES, key=lambda size: abs(size - px))
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_size == 0 or stat.st_size > MAX_PREVIEW_BYTES:
        return None
    key = hashlib.sha256(f"{path}\0{stat.st_mtime_ns}\0{stat.st_size}\0{px}".encode()).hexdigest()[:32]
    cache = home / "cache" / "miniaturas"
    cached = cache / f"{key}.png"
    if cached.is_file():
        return cached.read_bytes()
    data = _image_thumbnail(path, px) if kind_of(path.name) == "imagem" and path.suffix.lower() not in (".svg", ".heic", ".heif") else None
    if data is None:
        data = _quicklook_thumbnail(path, px)
    if data is None:
        return None
    cache.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def media_type(path: Path) -> str | None:
    """O tipo de mídia que o <img>, o <video> e o <audio> da barra abrem (só esses saem inteiros)."""
    return MEDIA_TYPES.get(path.suffix.lower())
