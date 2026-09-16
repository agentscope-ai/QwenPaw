# -*- coding: utf-8 -*-
"""Shutdown ordering keeps workspace dependencies alive until quiescent."""

import asyncio
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
