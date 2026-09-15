# -*- coding: utf-8 -*-
"""Unit tests for app-process signal setup."""

import signal
import subprocess
import sys
import textwrap
import time

import pytest

from qwenpaw.cli import app_cmd
from qwenpaw.cli.app_cmd import (
    _install_windows_sigbreak_handler,
    _sigbreak_to_sigint,
)


def test_install_windows_sigbreak_handler(monkeypatch) -> None:
    sigbreak = object()
    registrations: list[tuple[object, object]] = []
    monkeypatch.setattr(app_cmd.sys, "platform", "win32")
    monkeypatch.setattr(app_cmd.signal, "SIGBREAK", sigbreak, raising=False)
    monkeypatch.setattr(
        app_cmd.signal,
        "signal",
        lambda sig, handler: registrations.append((sig, handler)),
    )

    _install_windows_sigbreak_handler()

    assert registrations == [
        (sigbreak, _sigbreak_to_sigint),
    ]


def test_sigbreak_handler_routes_to_sigint(monkeypatch) -> None:
    raised: list[signal.Signals] = []
    monkeypatch.setattr(app_cmd.signal, "raise_signal", raised.append)

    _sigbreak_to_sigint(0, None)

    assert raised == [signal.SIGINT]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows signal behavior")
def test_ctrl_break_runs_uvicorn_lifespan_shutdown(tmp_path) -> None:
    started = tmp_path / "started"
    stopped = tmp_path / "stopped"
    script = textwrap.dedent(
        """
        import sys
        from contextlib import asynccontextmanager
        from pathlib import Path

        import uvicorn
        from fastapi import FastAPI

        from qwenpaw.cli.app_cmd import _install_windows_shutdown_handlers

        started = Path(sys.argv[1])
        stopped = Path(sys.argv[2])

        @asynccontextmanager
        async def lifespan(_app):
            started.write_text("started", encoding="utf-8")
            try:
                yield
            finally:
                stopped.write_text("stopped", encoding="utf-8")

        _install_windows_shutdown_handlers()
        uvicorn.run(FastAPI(lifespan=lifespan), host="127.0.0.1", port=0)
        """,
    )
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-c", script, str(started), str(stopped)],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not started.exists():
            if proc.poll() is not None:
                pytest.fail(
                    f"Uvicorn exited early with code {proc.returncode}",
                )
            time.sleep(0.1)
        assert started.exists()

        from qwenpaw.cli.windows_shutdown import signal_shutdown_event

        assert signal_shutdown_event(proc.pid)
        proc.wait(timeout=15.0)

        assert proc.returncode == 0
        assert stopped.read_text(encoding="utf-8") == "stopped"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)
