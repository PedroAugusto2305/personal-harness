"""Anexos da barra de entrada: o arquivo vai para ~/.harness/anexos e o agente recebe o caminho.

As duas CLIs aceitam caminho de arquivo no prompt (imagem inclusive), então anexar é
salvar num lugar estável e colar o caminho. Arrastar do Finder no app já entrega o
caminho original; o upload só existe para o seletor de arquivos e para o navegador.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


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
    return target
