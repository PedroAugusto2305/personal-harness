"""Sobe o núcleo do Harness em 127.0.0.1."""

from __future__ import annotations

import dataclasses
import json
import os
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def main() -> None:
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
    info = json.dumps({"url": settings.url, "token": settings.token, "pid": os.getpid()})
    for path in [settings.home / "runtime.json", *([Path(app_file)] if app_file else [])]:
        path.write_text(info, encoding="utf-8")
        path.chmod(0o600)
    parent = os.environ.get("HARNESS_PARENT_PID", "")
    if parent.isdigit():
        watch_parent(int(parent))
    print(f"Harness core {__version__} em {settings.url}", flush=True)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
