"""Sobe o núcleo da MÊTIS em 127.0.0.1.

Desde a v0.9.2 a janela sobe o núcleo fora do grupo de processos dela e não o derruba ao
fechar: os agentes sobrevivem a fechar, recarregar ou recompilar o app. O endereço e o token
ficam em ~/.harness/runtime.json (0600), que a próxima janela e o comando `metis` leem.
HARNESS_PARENT_PID ainda vale para quem quiser o núcleo preso a um processo (testes)."""

from __future__ import annotations

import dataclasses
import json
import os
import resource
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from . import __version__
from .app import create_app
from .config import load_settings


def watch_parent(pid: int, interval: float = 2.0) -> None:
    """Se o app que abriu o núcleo morrer sem avisar, o núcleo sai também (e libera a porta)."""

    def loop() -> None:
        while True:
            time.sleep(interval)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                os.kill(os.getpid(), signal.SIGTERM)  # o uvicorn encerra as sessões direito
                time.sleep(5)
                os._exit(0)  # se o encerramento travar, sai assim mesmo: ninguém mais usa este núcleo
            except PermissionError:
                continue

    threading.Thread(target=loop, name="vigia-do-app", daemon=True).start()


def port_free(host: str, port: int) -> bool:
    """A porta está livre se ninguém estiver ouvindo nela. Com SO_REUSEADDR, como o próprio
    uvicorn faz: as conexões do núcleo que acabou de fechar (TIME_WAIT por até 30 s) não
    contam, senão o núcleo novo de um "Reiniciar" desiste achando que outro está no ar."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


OPEN_FILES = 8192


def raise_open_files(target: int = OPEN_FILES) -> int:
    """Aberto pelo Finder, o núcleo herda do launchd o limite de 256 arquivos abertos, e cada
    terminal, conexão da janela, banco e servidor MCP gasta alguns. Sobe o limite brando até
    `target` (sem passar do rígido) e devolve o que ficou valendo."""
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        wanted = target if hard == resource.RLIM_INFINITY else min(target, hard)
        if soft != resource.RLIM_INFINITY and soft < wanted:
            resource.setrlimit(resource.RLIMIT_NOFILE, (wanted, hard))
        return resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except (ValueError, OSError):
        return -1


def free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def main() -> None:
    raise_open_files()
    settings = load_settings()
    # O uvicorn só tenta a porta depois de subir tudo (sessões, consulta ao Codex), então
    # a porta é conferida antes. Aberto pelo app, o núcleo usa outra porta livre e avisa
    # o endereço no arquivo do app; aberto à mão, sai sem deixar um núcleo pela metade.
    app_file = os.environ.get("HARNESS_RUNTIME_FILE")
    if not port_free(settings.host, settings.port):
        if not app_file:
            print(f"porta {settings.port} ocupada: outro núcleo já está no ar", file=sys.stderr, flush=True)
            raise SystemExit(3)
        settings = dataclasses.replace(settings, port=free_port(settings.host))
    settings.home.mkdir(parents=True, exist_ok=True)
    info = json.dumps({"url": settings.url, "token": settings.token, "pid": os.getpid(), "version": __version__, "started": time.time()})
    for path in [settings.home / "runtime.json", *([Path(app_file)] if app_file else [])]:
        path.write_text(info, encoding="utf-8")
        path.chmod(0o600)
    parent = os.environ.get("HARNESS_PARENT_PID", "")
    if parent.isdigit():
        watch_parent(int(parent))
    print(f"Harness core {__version__} em {settings.url}", flush=True)
    # O encerramento espera as conexões abertas (a janela e os terminais) por 3 s no máximo.
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
