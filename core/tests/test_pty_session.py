import asyncio
import os

from harness_core.pty_session import PtySession


async def _collect(session: PtySession, timeout: float = 5.0) -> bytes:
    backlog, queue = session.subscribe()
    output = bytearray(backlog)
    async with asyncio.timeout(timeout):
        while (chunk := await queue.get()) is not None:
            output.extend(chunk)
    return bytes(output)


def test_runs_command_and_reports_exit_code():
    exits: list[int | None] = []

    async def scenario() -> bytes:
        session = PtySession(["/bin/sh", "-c", "echo oi-harness; exit 3"], cwd="/tmp", env=dict(os.environ), on_exit=exits.append)
        session.start()
        return await _collect(session)

    output = asyncio.run(scenario())
    assert b"oi-harness" in output
    assert exits == [3]


def test_pty_is_the_controlling_terminal():
    # Sem terminal de controle o `ps` mostra "??"; com ele, o nome do tty (ex.: ttys012).
    async def scenario() -> bytes:
        session = PtySession(["/bin/sh", "-c", "echo TTY=$(ps -o tty= -p $$)"], cwd="/tmp", env=dict(os.environ))
        session.start()
        return await _collect(session)

    output = asyncio.run(scenario()).decode()
    line = next(l for l in output.splitlines() if l.startswith("TTY="))
    assert line.strip() not in ("TTY=??", "TTY=")


def test_input_reaches_the_process_and_resize_applies():
    async def scenario() -> bytes:
        session = PtySession(["/bin/cat"], cwd="/tmp", env=dict(os.environ), cols=80, rows=24)
        session.start()
        session.resize(100, 30)
        session.write(b"ola do teclado\n")
        await asyncio.sleep(0.3)
        backlog, _ = session.subscribe()
        await session.terminate()
        return backlog

    assert b"ola do teclado" in asyncio.run(scenario())
