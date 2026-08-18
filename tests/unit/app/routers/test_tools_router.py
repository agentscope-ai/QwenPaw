# -*- coding: utf-8 -*-
"""Tests for non-blocking tool configuration routes."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import qwenpaw.app.agent_context as agent_context_module
import qwenpaw.app.routers.tools as tools_router_module
import qwenpaw.browser.runtime.managed_playwright as managed_playwright_module
import qwenpaw.plugins.registry as registry_module
from qwenpaw.app.routers.tools import (
    ToolConfigUpdate,
    get_tool_config,
    update_tool_config,
)
from qwenpaw.utils.io_utils import run_sync_io


def _agent_config(tool_name: str, config: dict) -> SimpleNamespace:
    """Build the minimal agent config needed by the route updater."""
    tool = SimpleNamespace(config=dict(config))
    tools = SimpleNamespace(builtin_tools={tool_name: tool})
    return SimpleNamespace(tools=tools)


def _patch_workspace(monkeypatch, agent_id: str = "default") -> None:
    async def get_agent_for_request(_request):
        return SimpleNamespace(agent_id=agent_id)

    monkeypatch.setattr(
        agent_context_module,
        "get_agent_for_request",
        get_agent_for_request,
    )
    monkeypatch.setattr(
        tools_router_module,
        "schedule_agent_reload",
        lambda _request, _agent_id: None,
    )


@pytest.mark.asyncio
async def test_browser_config_starts_download_on_event_loop(
    monkeypatch,
) -> None:
    """Browser download task creation must stay on the event loop."""
    _patch_workspace(monkeypatch)
    loop_thread = threading.get_ident()
    update_threads = []
    mutate_threads = []
    start_threads = []
    download_tasks = []
    agent_config = _agent_config("browser", {})
    registry = SimpleNamespace(
        get_plugin_id_for_tool=lambda _tool_name: None,
    )
    application_config = SimpleNamespace(
        browser=SimpleNamespace(experimental=False),
    )

    async def update_config(_agent_id, updater):
        def update_sync():
            update_threads.append(threading.get_ident())
            updater(agent_config)
            return agent_config

        return await run_sync_io(update_sync)

    def mutate_config(mutator):
        mutate_threads.append(threading.get_ident())
        mutator(application_config)
        return application_config

    def start_download():
        start_threads.append(threading.get_ident())
        asyncio.get_running_loop()
        task = asyncio.create_task(asyncio.sleep(0))
        download_tasks.append(task)
        return False, ""

    monkeypatch.setattr(registry_module, "PluginRegistry", lambda: registry)
    monkeypatch.setattr(
        tools_router_module,
        "update_agent_config_async",
        update_config,
    )
    monkeypatch.setattr(tools_router_module, "mutate_config", mutate_config)
    monkeypatch.setattr(
        managed_playwright_module,
        "start_managed_chromium_download",
        start_download,
    )

    response = await update_tool_config(
        tool_name="browser",
        body=ToolConfigUpdate(config={"experimental": True}),
        request=SimpleNamespace(),
    )
    await download_tasks[0]

    assert response["status"] == "success"
    assert agent_config.tools.builtin_tools["browser"].config == {
        "experimental": True,
    }
    assert application_config.browser.experimental is True
    assert update_threads and update_threads[0] != loop_thread
    assert mutate_threads and mutate_threads[0] != loop_thread
    assert start_threads == [loop_thread]


@pytest.mark.asyncio
async def test_update_tool_config_preserves_password_off_event_loop(
    monkeypatch,
) -> None:
    """The locked worker transaction must retain masked passwords."""
    _patch_workspace(monkeypatch)
    loop_thread = threading.get_ident()
    update_threads = []
    agent_config = _agent_config(
        "secret_tool",
        {"token": "stored-secret", "region": "old"},
    )
    registry = SimpleNamespace(
        get_plugin_id_for_tool=lambda _tool_name: "secret-plugin",
        get_plugin_manifest=lambda _plugin_id: {
            "meta": {
                "tools": [
                    {
                        "name": "secret_tool",
                        "config_fields": [
                            {"name": "token", "type": "password"},
                        ],
                    },
                ],
            },
        },
        get_tool_config=MagicMock(
            side_effect=AssertionError("synchronous read used"),
        ),
        set_tool_config=MagicMock(
            side_effect=AssertionError("synchronous write used"),
        ),
    )

    async def update_config(_agent_id, updater):
        def update_sync():
            update_threads.append(threading.get_ident())
            time.sleep(0.1)
            updater(agent_config)
            return agent_config

        return await run_sync_io(update_sync)

    monkeypatch.setattr(registry_module, "PluginRegistry", lambda: registry)
    monkeypatch.setattr(
        tools_router_module,
        "update_agent_config_async",
        update_config,
    )

    update_task = asyncio.create_task(
        update_tool_config(
            tool_name="secret_tool",
            body=ToolConfigUpdate(
                config={"token": "***", "region": "new"},
            ),
            request=SimpleNamespace(),
        ),
    )
    await asyncio.sleep(0.02)

    assert update_task.done() is False
    response = await update_task
    saved = agent_config.tools.builtin_tools["secret_tool"].config
    assert response["status"] == "success"
    assert saved == {"token": "stored-secret", "region": "new"}
    assert update_threads and update_threads[0] != loop_thread
    registry.get_tool_config.assert_not_called()
    registry.set_tool_config.assert_not_called()


@pytest.mark.asyncio
async def test_get_tool_config_reads_off_event_loop(monkeypatch) -> None:
    """A slow tool config read must not block other coroutines."""
    _patch_workspace(monkeypatch)
    loop_thread = threading.get_ident()
    read_threads = []

    def read_config(_tool_name, _agent_id):
        read_threads.append(threading.get_ident())
        time.sleep(0.1)
        return {"region": "test"}

    registry = SimpleNamespace(
        get_tool_config=read_config,
        get_plugin_id_for_tool=lambda _tool_name: None,
    )
    monkeypatch.setattr(registry_module, "PluginRegistry", lambda: registry)

    read_task = asyncio.create_task(
        get_tool_config(
            tool_name="slow_tool",
            request=SimpleNamespace(),
        ),
    )
    await asyncio.sleep(0.02)

    assert read_task.done() is False
    assert await read_task == {"region": "test"}
    assert read_threads and read_threads[0] != loop_thread
