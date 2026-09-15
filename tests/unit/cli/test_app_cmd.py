# -*- coding: utf-8 -*-
"""Unit tests for app-process signal setup."""

import signal
import subprocess
import sys
import textwrap
import time

import pytest

from qwenpaw.cli import windows_shutdown
from qwenpaw.cli.windows_shutdown import (
    _sigbreak_to_sigint,
    install_shutdown_handlers,
)


def test_install_windows_sigbreak_handler(monkeypatch) -> None:
    sigbreak = object()
    registrations: list[tuple[object, object]] = []
    monkeypatch.setattr(windows_shutdown.sys, "platform", "win32")
    monkeypatch.setattr(windows_shutdown.os, "getpid", lambda: 1234)
    monkeypatch.setattr(
        windows_shutdown,
        "_handlers_installed_pid",
        None,
    )
    monkeypatch.setattr(
        windows_shutdown.signal,
        "SIGBREAK",
        sigbreak,
        raising=False,
    )
    monkeypatch.setattr(
        windows_shutdown.signal,
        "signal",
        lambda sig, handler: registrations.append((sig, handler)),
    )
    monkeypatch.setattr(
        windows_shutdown,
        "create_shutdown_event",
        lambda: None,
    )

    install_shutdown_handlers()
    install_shutdown_handlers()

    assert registrations == [
        (sigbreak, _sigbreak_to_sigint),
    ]


def test_sigbreak_handler_routes_to_sigint(monkeypatch) -> None:
    raised: list[signal.Signals] = []
    monkeypatch.setattr(windows_shutdown.signal, "raise_signal", raised.append)

    _sigbreak_to_sigint(0, None)

    assert raised == [signal.SIGINT]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows signal behavior")
def test_named_event_runs_uvicorn_lifespan_shutdown(tmp_path) -> None:
    started = tmp_path / "started"
    stopped = tmp_path / "stopped"
    script = textwrap.dedent(
        """
        import sys
        from contextlib import asynccontextmanager
        from pathlib import Path

        import uvicorn
        from fastapi import FastAPI

        from qwenpaw.cli.windows_shutdown import install_shutdown_handlers

        started = Path(sys.argv[1])
        stopped = Path(sys.argv[2])

        @asynccontextmanager
        async def lifespan(_app):
            started.write_text("started", encoding="utf-8")
            try:
                yield
            finally:
                stopped.write_text("stopped", encoding="utf-8")

        install_shutdown_handlers()
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reload behavior")
def test_reload_child_exposes_graceful_shutdown_event(tmp_path) -> None:
    reload_dir = tmp_path / "reload"
    reload_dir.mkdir()
    started = tmp_path / "started"
    stopped = tmp_path / "stopped"
    runner = tmp_path / "runner.py"
    app_module = reload_dir / "reload_app.py"
    runner.write_text(
        textwrap.dedent(
            """
            import sys

            import uvicorn

            from qwenpaw.cli.windows_shutdown import (
                install_shutdown_handlers,
            )

            if __name__ == "__main__":
                install_shutdown_handlers()
                uvicorn.run(
                    "reload_app:app",
                    host="127.0.0.1",
                    port=0,
                    reload=True,
                    reload_dirs=[sys.argv[1]],
                )
            """,
        ),
        encoding="utf-8",
    )
    app_module.write_text(
        textwrap.dedent(
            """
            import os
            import sys
            from contextlib import asynccontextmanager
            from pathlib import Path

            from fastapi import FastAPI

            from qwenpaw.cli.windows_shutdown import install_shutdown_handlers

            started = Path(sys.argv[2])
            stopped = Path(sys.argv[3])

            install_shutdown_handlers()

            @asynccontextmanager
            async def lifespan(_app):
                started.write_text(str(os.getpid()), encoding="utf-8")
                try:
                    yield
                finally:
                    stopped.write_text("stopped", encoding="utf-8")

            app = FastAPI(lifespan=lifespan)
            """,
        ),
        encoding="utf-8",
    )
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            sys.executable,
            str(runner),
            str(reload_dir),
            str(started),
            str(stopped),
        ],
        cwd=reload_dir,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not started.exists():
            if proc.poll() is not None:
                pytest.fail(
                    "Uvicorn reloader exited early with code "
                    f"{proc.returncode}",
                )
            time.sleep(0.1)
        assert started.exists()

        from qwenpaw.cli.windows_shutdown import signal_shutdown_event

        server_pid = int(started.read_text(encoding="utf-8"))
        assert server_pid != proc.pid
        assert signal_shutdown_event(server_pid)

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not stopped.exists():
            time.sleep(0.1)
        assert stopped.read_text(encoding="utf-8") == "stopped"

        assert signal_shutdown_event(proc.pid)
        proc.wait(timeout=15.0)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)
