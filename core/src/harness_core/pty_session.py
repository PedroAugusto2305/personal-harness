"""Um terminal real (PTY) por sessão, lido pelo loop do asyncio.

O núcleo é dono do processo: fechar a janela do app não mata o agente. A saída fica
num histórico em memória para quem se conectar depois.

O processo nasce com `subprocess` (fork e exec em C, seguro com várias threads) e
passa pelo `ptyexec`, que faz do PTY o terminal de controle antes de executar o comando.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import struct
import subprocess
import sys
import termios
from collections.abc import Callable

SCROLLBACK_BYTES = 2 * 1024 * 1024


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class PtySession:
    def __init__(
        self,
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        cols: int = 120,
        rows: int = 32,
        on_exit: Callable[[int | None], None] | None = None,
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.cols = cols
        self.rows = rows
        self.on_exit = on_exit
        self.alive = False
        self.exit_code: int | None = None
        self._proc: subprocess.Popen | None = None
        self._fd: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._buffer = bytearray()
        self._pending = bytearray()
        self._subscribers: set[asyncio.Queue[bytes | None]] = set()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        master, slave = os.openpty()
        try:
            _set_winsize(slave, self.cols, self.rows)
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "harness_core.ptyexec", *self.argv],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=self.cwd,
                env=self.env,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self._fd = master
        os.set_blocking(master, False)
        self.alive = True
        self._loop.add_reader(master, self._on_readable)

    def _on_readable(self) -> None:
        assert self._fd is not None
        try:
            data = os.read(self._fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""  # EIO: o último processo do terminal saiu
        if not data:
            self._finish()
            return
        self._buffer.extend(data)
        if len(self._buffer) > SCROLLBACK_BYTES:
            del self._buffer[: len(self._buffer) - SCROLLBACK_BYTES]
        for queue in list(self._subscribers):
            queue.put_nowait(data)

    def _finish(self) -> None:
        if not self.alive or self._fd is None or self._loop is None:
            return
        self.alive = False
        self._loop.remove_reader(self._fd)
        if self._pending:
            self._loop.remove_writer(self._fd)
            self._pending.clear()
        self._loop.create_task(self._reap())

    async def _reap(self) -> None:
        assert self._proc is not None
        for _ in range(100):
            if self._proc.poll() is not None:
                break
            await asyncio.sleep(0.05)
        self.exit_code = self._proc.returncode
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        for queue in list(self._subscribers):
            queue.put_nowait(None)
        if self.on_exit:
            self.on_exit(self.exit_code)

    def write(self, data: bytes) -> None:
        if not self.alive or self._fd is None or self._loop is None:
            return
        if self._pending:
            self._pending.extend(data)
            return
        try:
            written = os.write(self._fd, data)
        except BlockingIOError:
            written = 0
        except OSError:
            return
        if written < len(data):
            self._pending.extend(data[written:])
            self._loop.add_writer(self._fd, self._flush)

    def _flush(self) -> None:
        assert self._fd is not None and self._loop is not None
        try:
            written = os.write(self._fd, bytes(self._pending))
        except BlockingIOError:
            return
        except OSError:
            self._pending.clear()
            self._loop.remove_writer(self._fd)
            return
        del self._pending[:written]
        if not self._pending:
            self._loop.remove_writer(self._fd)

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        if self.alive and self._fd is not None:
            _set_winsize(self._fd, cols, rows)

    def subscribe(self) -> tuple[bytes, asyncio.Queue[bytes | None]]:
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._subscribers.add(queue)
        if not self.alive:
            queue.put_nowait(None)
        return bytes(self._buffer), queue

    def unsubscribe(self, queue: asyncio.Queue[bytes | None]) -> None:
        self._subscribers.discard(queue)

    async def terminate(self, grace: float = 1.0) -> None:
        """SIGHUP no grupo do processo (como fechar um terminal); SIGKILL se não sair."""
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            os.killpg(self._proc.pid, signal.SIGHUP)
        except ProcessLookupError:
            return
        for _ in range(int(grace / 0.05)):
            if self._proc.poll() is not None:
                return
            await asyncio.sleep(0.05)
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
