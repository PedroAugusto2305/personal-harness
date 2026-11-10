"""Leitura de arquivos para o explorador e os visualizadores. Sempre dentro da pasta pedida."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

MAX_TEXT_BYTES = 2 * 1024 * 1024
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class FileError(ValueError):
    pass


class FileConflict(FileError):
    """O arquivo mudou no disco desde que o editor o abriu (o agente, outro editor)."""

    def __init__(self, message: str, current: str) -> None:
        super().__init__(message)
        self.hash = current


class TooLarge(FileError):
    pass


def file_hash(path: Path) -> str:
    """sha256 do arquivo inteiro, lido aos pedaços."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_utf8(data: bytes) -> bool:
    """Texto em UTF-8 válido. Outra codificação (Latin-1, Windows-1252) abre com � no lugar dos
    acentos, e gravar de volta trocaria cada acento por esse � para sempre."""
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


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
    with target.open("rb") as handle:
        info = os.fstat(handle.fileno())
        data = handle.read(MAX_TEXT_BYTES + 1)
    truncated = len(data) > MAX_TEXT_BYTES
    data = data[:MAX_TEXT_BYTES]
    binary = b"\0" in data[:8192]
    utf8 = not binary and is_utf8(data)
    return {
        "path": rel,
        "size": info.st_size if truncated else len(data),
        "binary": binary,
        "truncated": truncated,
        "text": "" if binary else data.decode("utf-8", "replace"),
        # v1.0.0: fora de UTF-8 o editor abre só para leitura (gravar estragaria os acentos).
        "utf8": utf8,
        "mime": mimetypes.guess_type(target.name)[0] or "",
        # v0.9.7: o editor guarda o hash e o manda de volta ao salvar (conferência de mudança no disco).
        # v1.0.0: o hash sai dos mesmos bytes do texto. Uma segunda leitura podia pegar outra versão
        # (o agente gravou no meio), e o editor gravaria por cima dela sem conflito. Só o arquivo
        # grande demais, que o editor não grava, é lido inteiro de novo para o hash.
        "hash": file_hash(target) if truncated else hashlib.sha256(data).hexdigest(),
        "mtime": info.st_mtime,
    }


def write_text(root: str, rel: str, text: str, expected_hash: str) -> dict:
    """Grava o que o editor mandou, exatamente como veio, só se o arquivo ainda for o que ele abriu.

    O editor não cria arquivo nem mexe em .git, binário, arquivo fora de UTF-8 ou arquivo grande
    demais para abrir. A gravação é atômica (temporário na mesma pasta e troca) e mantém as
    permissões do original."""
    target = inside(root, rel)
    base = Path(root).expanduser().resolve()
    if ".git" in target.relative_to(base).parts:
        raise FileError("o editor não grava dentro de .git")
    if target.is_dir():
        raise FileError(f"é uma pasta: {rel}")
    if not target.is_file():
        raise FileError(f"arquivo não existe: {rel} (o editor não cria arquivo)")
    if target.stat().st_size > MAX_TEXT_BYTES:
        raise FileError(f"arquivo grande demais para o editor: {rel}")
    on_disk = target.read_bytes()
    if b"\0" in on_disk[:8192]:
        raise FileError(f"arquivo binário: {rel}")
    if not is_utf8(on_disk):
        raise FileError(f"o arquivo não está em UTF-8: {rel}. O editor não grava por cima para não estragar os acentos.")
    data = text.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise TooLarge(f"texto grande demais para gravar ({len(data)} bytes)")
    current = hashlib.sha256(on_disk).hexdigest()
    if current != expected_hash:
        raise FileConflict("o arquivo mudou no disco desde que foi aberto", current)
    mode = stat.S_IMODE(target.stat().st_mode)
    fd, tmp = tempfile.mkstemp(prefix=".metis-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return {"hash": hashlib.sha256(data).hexdigest(), "mtime": target.stat().st_mtime, "size": len(data)}


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
