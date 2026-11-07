"""Leitura de arquivos para o explorador e os visualizadores. Sempre dentro da pasta pedida."""

from __future__ import annotations

import mimetypes
import subprocess
from pathlib import Path
from urllib.parse import urlparse

MAX_TEXT_BYTES = 2 * 1024 * 1024
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class FileError(ValueError):
    pass


def inside(root: str, rel: str) -> Path:
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise FileError(f"pasta não encontrada: {root}")
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        raise FileError("caminho fora da pasta")
    return target


def read_text(root: str, rel: str) -> dict:
    target = inside(root, rel)
    if not target.is_file():
        raise FileError(f"arquivo não encontrado: {rel}")
    size = target.stat().st_size
    with target.open("rb") as handle:
        data = handle.read(MAX_TEXT_BYTES)
    binary = b"\0" in data[:8192]
    return {
        "path": rel,
        "size": size,
        "binary": binary,
        "truncated": size > MAX_TEXT_BYTES,
        "text": "" if binary else data.decode("utf-8", "replace"),
        "mime": mimetypes.guess_type(target.name)[0] or "",
    }


def media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def open_url(url: str) -> None:
    """Abre no navegador do Mac. Só endereços locais: é para as portas dos terminais."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTS:
        raise FileError("só abro endereços locais")
    subprocess.run(["open", url], check=False, timeout=10)


def reveal(path: str) -> None:
    target = Path(path).expanduser()
    if not target.exists():
        raise FileError(f"não existe: {path}")
    subprocess.run(["open", "-R", str(target)], check=False, timeout=10)
