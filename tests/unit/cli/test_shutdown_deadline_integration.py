# -*- coding: utf-8 -*-
"""Process-level coverage for the composed CLI and Uvicorn shutdown budget."""

# pylint: disable=protected-access

import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from qwenpaw.cli import shutdown_cmd


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal behavior")
def test_cli_waits_for_request_import_and_workspace_drains(
    tmp_path,
    monkeypatch,
):
    ready = tmp_path / "ready"
    request_started = tmp_path / "request_started"
    workspace_stopped = tmp_path / "workspace_stopped"
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]

    script = textwrap.dedent(
        """
        import asyncio
        import sys
        from contextlib import asynccontextmanager
        from pathlib import Path

        import uvicorn
        from fastapi import FastAPI

        from qwenpaw.app._app import _stop_workspaces_after_dependents

        ready = Path(sys.argv[1])
        request_started = Path(sys.argv[2])
        workspace_stopped = Path(sys.argv[3])
        port = int(sys.argv[4])

        class ImportJobs:
            async def shutdown(self):
                await asyncio.sleep(0.7)
                return True

        class WorkspaceManager:
            async def stop_all(self):
                await asyncio.sleep(0.7)
                workspace_stopped.write_text("stopped", encoding="utf-8")

        @asynccontextmanager
        async def lifespan(app):
            app.state.multi_agent_manager = WorkspaceManager()
            ready.write_text("ready", encoding="utf-8")
            try:
                yield
            finally:
                await _stop_workspaces_after_dependents(
                    app, ImportJobs(), deadline_sec=2.0,
                )

        app = FastAPI(lifespan=lifespan)

        @app.get("/hold")
        async def hold():
            request_started.write_text("started", encoding="utf-8")
            await asyncio.Event().wait()

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            timeout_graceful_shutdown=0.7,
        )
        """,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path(__file__).resolve().parents[3] / "src"),
            env.get("PYTHONPATH", ""),
        ],
    )
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            sys.executable,
            "-c",
            script,
            str(ready),
            str(request_started),
            str(workspace_stopped),
            str(port),
        ],
        env=env,
        start_new_session=True,
    )
    held_socket = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not ready.exists():
            if proc.poll() is not None:
                pytest.fail(f"server exited early: {proc.returncode}")
            time.sleep(0.05)
        assert ready.exists()

        while time.monotonic() < deadline:
            try:
                held_socket = socket.create_connection(
                    ("127.0.0.1", port),
                    timeout=0.2,
                )
                break
            except OSError:
                time.sleep(0.05)
        assert held_socket is not None
        held_socket.sendall(b"GET /hold HTTP/1.1\r\nHost: localhost\r\n\r\n")
        while time.monotonic() < deadline and not request_started.exists():
            time.sleep(0.05)
        assert request_started.exists()

        original_signal = shutdown_cmd._signal_process_tree_unix
        signals = []

        def record_signal(pid, sig):
            signals.append(sig)
            original_signal(pid, sig)

        monkeypatch.setattr(
            shutdown_cmd,
            "_signal_process_tree_unix",
            record_signal,
        )
        reaper = threading.Thread(target=proc.wait, daemon=True)
        reaper.start()

        assert shutdown_cmd._terminate_pid(proc.pid, timeout_sec=3.0)
        reaper.join(timeout=1)
        assert proc.returncode in (0, -signal.SIGTERM)
        assert workspace_stopped.read_text(encoding="utf-8") == "stopped"
        assert signals == [signal.SIGTERM]
    finally:
        if held_socket is not None:
            held_socket.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
