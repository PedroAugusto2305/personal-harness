"""Núcleo da MÊTIS (antes Personal Harness)."""

from importlib.metadata import PackageNotFoundError, version

# A versão mora só no core/pyproject.toml (v1.0.1). Escrita aqui também, ela ficou em 0.9.9
# quando a 1.0.0 subiu só no pyproject, e o app 1.0.0 pedia para reiniciar um núcleo que,
# reiniciado, continuava se dizendo 0.9.9. O `uv run` e o `uv sync` do instalar.sh refazem
# o pacote quando o pyproject muda, então o número lido aqui acompanha.
try:
    __version__ = version("harness-core")
except PackageNotFoundError:  # código fora de um ambiente com o pacote instalado
    __version__ = "0.0.0"
