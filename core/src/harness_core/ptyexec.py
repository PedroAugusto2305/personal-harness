"""Lançador mínimo: torna o PTY o terminal de controle e executa o comando.

O núcleo cria o processo com `subprocess` (fork e exec feitos em C, seguros num
processo com várias threads) e passa por aqui antes do agente. Sem o TIOCSCTTY o
terminal não teria sessão, e o Ctrl+C e o controle de jobs dos shells não funcionariam.

Uso: python -m harness_core.ptyexec <comando> [argumentos...]
"""

from __future__ import annotations

import fcntl
import os
import sys
import termios


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        sys.exit("uso: python -m harness_core.ptyexec <comando> [argumentos...]")
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
