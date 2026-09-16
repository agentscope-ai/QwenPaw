# -*- coding: utf-8 -*-
"""Shutdown ordering keeps workspace dependencies alive until quiescent."""

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from qwenpaw.app._app import _stop_workspaces_after_dependents


@pytest.mark.asyncio
async def test_import_worker_and_plugin_hook_finish_before_workspace_stop():
    order: list[str] = []
    release_worker = asyncio.Event()
    worker_finished = asyncio.Event()

    async def worker() -> None:
        await release_worker.wait()
        order.append("worker")
        worker_finished.set()

    worker_task = asyncio.create_task(worker())

    class ImportJobs:
        async def shutdown(self) -> bool:
            order.append("cancel_imports")
            return False

        async def drain(self) -> bool:
            await worker_finished.wait()
            return True

    async def plugin_hook() -> None:
        order.append("plugin_hook")

    class WorkspaceManager:
        async def stop_all(self) -> None:
            order.append("stop_workspaces")

    app = FastAPI()
    app.state.plugin_registry = SimpleNamespace(
        get_shutdown_hooks=lambda: [
            SimpleNamespace(
                hook_name="test",
                plugin_id="test",
                priority=0,
                callback=plugin_hook,
            ),
        ],
    )
    app.state.multi_agent_manager = WorkspaceManager()

    shutdown_task = asyncio.create_task(
        _stop_workspaces_after_dependents(app, ImportJobs()),
    )
    await asyncio.sleep(0)
    assert order == ["cancel_imports"]
    release_worker.set()
    await asyncio.wait_for(shutdown_task, timeout=1)
    await worker_task

    assert order == [
        "cancel_imports",
        "worker",
        "plugin_hook",
        "stop_workspaces",
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX direct SIGTERM")
def test_direct_signal_hard_exits_when_import_never_quiesces(tmp_path):
    started = tmp_path / "started"
    workspace_stopped = tmp_path / "workspace_stopped"
    script = textwrap.dedent(
        """
        import asyncio
        import sys
        from contextlib import asynccontextmanager
        from pathlib import Path

        import uvicorn
        from fastapi import FastAPI

        from qwenpaw.app._app import _stop_workspaces_after_dependents

        started = Path(sys.argv[1])
        workspace_stopped = Path(sys.argv[2])

        class ImportJobs:
            async def shutdown(self):
                return False

            async def drain(self):
                await asyncio.sleep(0.02)
                return False

        class WorkspaceManager:
            async def stop_all(self):
                workspace_stopped.write_text("stopped", encoding="utf-8")

        @asynccontextmanager
        async def lifespan(app):
            app.state.multi_agent_manager = WorkspaceManager()
            started.write_text("started", encoding="utf-8")
            try:
                yield
            finally:
                await _stop_workspaces_after_dependents(
                    app, ImportJobs(), deadline_sec=0.5,
                )

        uvicorn.run(FastAPI(lifespan=lifespan), host="127.0.0.1", port=0)
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
        [sys.executable, "-c", script, str(started), str(workspace_stopped)],
        env=env,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not started.exists():
            if proc.poll() is not None:
                pytest.fail(f"server exited early: {proc.returncode}")
            time.sleep(0.05)
        assert started.exists()

        shutdown_start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
        assert time.monotonic() - shutdown_start < 3
        assert proc.returncode == 1
        assert not workspace_stopped.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
