"""Anexos da barra de entrada: o arquivo vai para ~/.harness/anexos e o agente recebe o caminho.

As duas CLIs aceitam caminho de arquivo no prompt (imagem inclusive), então anexar é
salvar num lugar estável e colar o caminho. Arrastar do Finder no app já entrega o
caminho original; o upload só existe para o seletor de arquivos e para o navegador.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from datetime import date
from pathlib import Path

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
_run = subprocess.run


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
    # O macOS pode entregar um print/arquivo do clipboard em JPEG XL. Claude, Codex e o
    # WebKit da conversa não leem esse formato, embora o próprio macOS leia. Normalize no
    # ingresso: o caminho colado no terminal já aponta para um PNG que todos entendem.
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
