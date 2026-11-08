"""Versão instalada da MÊTIS e atualização (v0.9.4).

A MÊTIS de uso é uma cópia de uma versão marcada (tag `v*`) do repositório em
`<home>/versoes/<tag>`, montada pelo `scripts/instalar.sh`: o app em /Applications roda o
núcleo dessa pasta. Atualizar é rodar o script de novo com a tag nova. Cada versão tem a
própria pasta, então o núcleo em uso nunca troca de arquivo enquanto roda; ele só passa
para a versão nova quando o Pedro o reinicia (a janela nova oferece).

A MÊTIS de desenvolvimento (`scripts/dev.sh`) não é instalada: roda do repositório, com os
dados em ~/.harness-dev, e não se atualiza sozinha.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from . import __version__

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
# core/src/harness_core/updates.py → core/
CORE_DIR = Path(__file__).resolve().parents[2]


def version_key(tag: str) -> tuple[int, int, int] | None:
    match = TAG.match(tag or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def git(cwd: str | Path, *args: str, timeout: float = 20) -> str | None:
    """Saída do git, ou None se falhar (sem rede, pasta que não é repositório, tempo esgotado)."""
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def install_info(home: Path, core_dir: Path = CORE_DIR) -> dict:
    """De onde roda este núcleo: uma versão instalada (`<home>/versoes/<tag>/core`) ou um repositório de trabalho."""
    root = core_dir.resolve().parent
    installed = root.parent == (home / "versoes").resolve() and version_key(root.name) is not None
    if installed:
        # A cópia instalada nasce de um clone do repositório de trabalho: a origem dela é ele.
        repo = git(root, "remote", "get-url", "origin")
    else:
        repo = str(root) if (root / ".git").exists() else None
    return {
        "versao": __version__,
        "instalada": installed,
        "tag": root.name if installed else None,
        "pasta": str(root),
        "repositorio": repo,
    }


def tags(repo: str | Path, fetch: bool = False) -> list[str]:
    """Tags de versão do repositório, da mais nova para a mais velha. `fetch` busca as do GitHub antes."""
    if fetch:
        git(repo, "fetch", "--quiet", "--tags", timeout=30)
    out = git(repo, "tag", "--list", "v*") or ""
    found = [t for t in out.split() if version_key(t)]
    return sorted(found, key=lambda t: version_key(t) or (0, 0, 0), reverse=True)


def check(home: Path, fetch: bool = True, core_dir: Path = CORE_DIR) -> dict:
    """A versão em uso e, na instalada, a versão nova que houver no repositório."""
    info = install_info(home, core_dir)
    available = tags(info["repositorio"], fetch=fetch) if info["repositorio"] else []
    current = version_key(info["tag"] or f"v{__version__}") or (0, 0, 0)
    newest = available[0] if available else None
    info["ultima"] = newest
    info["nova"] = newest if info["instalada"] and newest and (version_key(newest) or (0, 0, 0)) > current else None
    return info


def update_command(repo: str, tag: str) -> str:
    """O que o terminal de atualização roda: o instalar.sh da própria versão nova.

    O script vai para um arquivo temporário antes de rodar (lido pelo stdin, o npm ou o uv
    poderiam comer o resto dele)."""
    if not version_key(tag):
        raise ValueError(f"versão inválida: {tag}")
    r, t = shlex.quote(repo), shlex.quote(tag)
    return (
        f'f="$(mktemp -t metis-instalar)" && git -C {r} show {t}:scripts/instalar.sh > "$f" '
        f'&& METIS_REPO={r} sh "$f" {t}; rm -f "$f"'
    )
