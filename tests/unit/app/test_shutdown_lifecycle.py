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
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from qwenpaw.app._app import _stop_workspaces_after_dependents
from qwenpaw.plugins.registry import PluginRegistry


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


@pytest.mark.asyncio
async def test_registry_hook_failures_are_reported_after_workspaces_stop(
    monkeypatch,
):
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    registry = PluginRegistry()
    order = []

    def checkpoint():
        order.append("checkpoint")
        raise OSError("checkpoint write failed")

    async def flush():
        order.append("flush")
        raise OSError("flush failed")

    async def stop_workspaces():
        order.append("workspaces")

    registry.register_shutdown_hook("writer", "checkpoint", checkpoint)
    registry.register_shutdown_hook("sender", "flush", flush)
    registry.register_shutdown_hook(
        "audit",
        "close",
        lambda: order.append("audit"),
    )
    app = FastAPI()
    app.state.plugin_registry = registry
    app.state.multi_agent_manager = SimpleNamespace(stop_all=stop_workspaces)
    imports = SimpleNamespace(shutdown=AsyncMock(return_value=True))

    with pytest.raises(RuntimeError) as error:
        await _stop_workspaces_after_dependents(app, imports)

    assert order == ["checkpoint", "flush", "audit", "workspaces"]
    assert str(error.value) == (
        "Plugin shutdown hooks failed: writer/checkpoint, sender/flush"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("hook_fails", [False, True])
async def test_plugin_resource_finishes_before_workspace_stop(
    monkeypatch,
    tmp_path,
    hook_fails,
):
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.architecture import (
        PluginEntryPoints,
        PluginManifest,
        PluginRecord,
    )
    from qwenpaw.plugins.loader import PluginLoader

    monkeypatch.setattr(PluginRegistry, "_instance", None)
    loader = PluginLoader(plugin_dirs=[])
    instance = loader.lifecycle.ensure_instance("test")
    api = PluginApi("test", {}, {})
    api.set_registry(loader.registry)
    api.bind_instance(instance)
    order = []
    stopping = asyncio.Event()
    release = asyncio.Event()

    async def hook():
        order.append("hook")
        if hook_fails:
            raise OSError("checkpoint failed")

    async def close_resource():
        order.append("closing")
        stopping.set()
        await release.wait()
        order.append("closed")

    with pytest.warns(DeprecationWarning):
        api.register_shutdown_hook("test", hook)
    instance.record_runtime("connection", close_resource, kind="custody")
    # Seed a loaded record without importing a real plugin.
    record = PluginRecord(
        manifest=PluginManifest(
            id="test",
            name="Test",
            version="1.0.0",
            entry=PluginEntryPoints(backend="plugin.py"),
        ),
        source_path=tmp_path,
        enabled=True,
        status="active",
    )
    monkeypatch.setattr(loader, "_loaded_plugins", {"test": record})

    async def stop_workspaces():
        order.append("workspaces")

    async def stop_imports():
        order.append("imports")
        return True

    app = FastAPI()
    app.state.plugin_loader = loader
    app.state.plugin_registry = loader.registry
    app.state.multi_agent_manager = SimpleNamespace(stop_all=stop_workspaces)
    task = asyncio.create_task(
        _stop_workspaces_after_dependents(
            app,
            SimpleNamespace(shutdown=stop_imports),
        ),
    )
    try:
        await asyncio.wait_for(stopping.wait(), timeout=1)
        assert order == ["imports", "hook", "closing"]
    finally:
        release.set()
        if hook_fails:
            with pytest.raises(RuntimeError, match="hooks failed: test/test"):
                await asyncio.wait_for(task, timeout=1)
        else:
            await asyncio.wait_for(task, timeout=1)
    assert order == ["imports", "hook", "closing", "closed", "workspaces"]
    assert loader.get_loaded_plugin("test") is not None


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(
            "pending",
            marks=pytest.mark.skipif(
                sys.platform == "win32",
                reason="POSIX direct SIGTERM",
            ),
        ),
        "failed",
        "completed",
    ],
)
def test_shutdown_deadline_tracks_completion(tmp_path, outcome):
    started = tmp_path / "started"
    workspace_stopped = tmp_path / "workspace_stopped"
    script = textwrap.dedent(
        """
        import asyncio
        import sys
        import threading
        from contextlib import asynccontextmanager
        from pathlib import Path
        from types import SimpleNamespace

        import uvicorn
        from fastapi import FastAPI

        from qwenpaw.app._app import _stop_workspaces_after_dependents

        started = Path(sys.argv[1])
        workspace_stopped = Path(sys.argv[2])
        outcome = sys.argv[3]

        class ImportJobs:
            async def shutdown(self):
                return outcome != "pending"

            async def drain(self):
                await asyncio.sleep(0.02)
                return False

        class WorkspaceManager:
            async def stop_all(self):
                workspace_stopped.write_text("stopped", encoding="utf-8")

        async def stop_installs():
            pass

        async def unload_plugins(_mode):
            return [SimpleNamespace(plugin_id="busy", quiescent=False)]

        @asynccontextmanager
        async def lifespan(app):
            app.state.multi_agent_manager = WorkspaceManager()
            if outcome == "failed":
                # A failed unload must retain the deadline while its worker lives.
                threading.Thread(target=threading.Event().wait).start()
                app.state.plugin_loader = SimpleNamespace(
                    stop_dependency_installs=stop_installs,
                    lifecycle=SimpleNamespace(unload_all=unload_plugins),
                )
            elif outcome == "completed":
                # Keep the process alive past the deadline to observe disarming.
                threading.Thread(target=threading.Event().wait, args=(1.5,)).start()
            started.write_text("started", encoding="utf-8")
            try:
                yield
            finally:
                await _stop_workspaces_after_dependents(
                    app, ImportJobs(), deadline_sec=0.5,
                )

        if outcome == "pending":
            uvicorn.run(FastAPI(lifespan=lifespan), host="127.0.0.1", port=0)
        else:
            async def close():
                async with lifespan(FastAPI()):
                    pass
            try:
                asyncio.run(close())
            except RuntimeError:
                # The watchdog must remain effective after lifespan unwinds.
                pass
        """,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path(__file__).resolve().parents[3] / "src"),
            env.get("PYTHONPATH", ""),
        ],
    )
    env["QWENPAW_WORKING_DIR"] = str(tmp_path / "data")
    env["QWENPAW_SECRET_DIR"] = str(tmp_path / "secrets")
    env["QWENPAW_RUNTIME_ID"] = "shutdown-test"
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            sys.executable,
            "-c",
            script,
            str(started),
            str(workspace_stopped),
            outcome,
        ],
        env=env,
        start_new_session=os.name != "nt",
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not started.exists():
            if proc.poll() is not None:
                pytest.fail(f"server exited early: {proc.returncode}")
            time.sleep(0.05)
        assert started.exists()

        shutdown_start = time.monotonic()
        if outcome == "pending":
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
        if outcome != "completed":
            assert time.monotonic() - shutdown_start < 3
        assert proc.returncode == (0 if outcome == "completed" else 1)
        assert workspace_stopped.exists() == (outcome == "completed")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
