"""Sobe o núcleo do Harness em 127.0.0.1."""

from __future__ import annotations

import json
import os

import uvicorn

from . import __version__
from .app import create_app
from .config import load_settings


def main() -> None:
    settings = load_settings()
    settings.home.mkdir(parents=True, exist_ok=True)
    runtime = settings.home / "runtime.json"
    runtime.write_text(json.dumps({"url": settings.url, "token": settings.token, "pid": os.getpid()}), encoding="utf-8")
    runtime.chmod(0o600)
    print(f"Harness core {__version__} em {settings.url}", flush=True)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
