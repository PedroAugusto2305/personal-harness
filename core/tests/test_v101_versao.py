"""v1.0.1: a versão é uma só no núcleo e no app.

Na 1.0.0 o pyproject e os pacotes do app subiram, mas o `__version__` do núcleo ficou em
0.9.9: o app mostrava a faixa "o núcleo em execução é a v0.9.9" e reiniciar não adiantava.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import harness_core

ROOT = Path(__file__).resolve().parents[2]


def pyproject_version() -> str:
    return tomllib.loads((ROOT / "core/pyproject.toml").read_text())["project"]["version"]


def test_nucleo_diz_a_versao_do_pyproject():
    assert harness_core.__version__ == pyproject_version()


def test_app_e_nucleo_na_mesma_versao():
    """A faixa do app compara o package.json com o núcleo; Tauri e Cargo vão juntos."""
    expected = pyproject_version()
    app = ROOT / "app"
    found = {
        "app/package.json": json.loads((app / "package.json").read_text())["version"],
        "app/package-lock.json": json.loads((app / "package-lock.json").read_text())["version"],
        "app/src-tauri/tauri.conf.json": json.loads((app / "src-tauri/tauri.conf.json").read_text())["version"],
        "app/src-tauri/Cargo.toml": tomllib.loads((app / "src-tauri/Cargo.toml").read_text())["package"]["version"],
    }
    assert found == {name: expected for name in found}
