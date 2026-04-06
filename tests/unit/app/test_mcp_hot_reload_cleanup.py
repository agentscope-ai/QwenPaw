# -*- coding: utf-8 -*-
"""Regression tests for MCP hot-reload cleanup."""
from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

google_module = sys.modules.setdefault("google", types.ModuleType("google"))
google_module.__path__ = []
genai_module = sys.modules.setdefault(
    "google.genai",
    types.ModuleType("google.genai"),
)
genai_module.Client = object
genai_module.errors = types.SimpleNamespace(APIError=Exception)
genai_module.types = types.SimpleNamespace(HttpOptions=object)
google_module.genai = genai_module
sys.modules.setdefault("google.genai.errors", genai_module.errors)
sys.modules.setdefault("google.genai.types", genai_module.types)

from copaw.app.mcp.manager import MCPClientManager


class _TaskBoundClient:
    """Fake client that fails if close runs on a different task."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.connect_task_id = None
        self.close_task_id = None

    async def connect(self) -> None:
        self.connect_task_id = id(asyncio.current_task())

    async def close(self) -> None:
        self.close_task_id = id(asyncio.current_task())
        if self.close_task_id != self.connect_task_id:
            raise RuntimeError(
                "Attempted to exit cancel scope in a different task than it was entered in",
            )


async def test_mcp_manager_keeps_replace_and_close_on_owner_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace/close should stay on the same internal lifecycle task."""
    created_clients: list[_TaskBoundClient] = []

    def _build_client(config) -> _TaskBoundClient:
        client = _TaskBoundClient(config.name)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        MCPClientManager,
        "_build_client",
        staticmethod(_build_client),
    )

    manager = MCPClientManager()
    cfg1 = SimpleNamespace(name="primary")
    cfg2 = SimpleNamespace(name="replacement")

    await asyncio.create_task(manager.replace_client("huggingface", cfg1))
    await asyncio.create_task(manager.replace_client("huggingface", cfg2))
    await asyncio.create_task(manager.close_all())

    assert [client.name for client in created_clients] == [
        "primary",
        "replacement",
    ]
    for client in created_clients:
        assert client.connect_task_id is not None
        assert client.close_task_id == client.connect_task_id

    assert await manager.get_clients() == []


async def test_mcp_manager_keeps_remove_on_owner_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing a client from another task should still clean up safely."""
    created_clients: list[_TaskBoundClient] = []

    def _build_client(config) -> _TaskBoundClient:
        client = _TaskBoundClient(config.name)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        MCPClientManager,
        "_build_client",
        staticmethod(_build_client),
    )

    manager = MCPClientManager()
    cfg = SimpleNamespace(name="single")

    await asyncio.create_task(manager.replace_client("huggingface", cfg))
    await asyncio.create_task(manager.remove_client("huggingface"))

    assert len(created_clients) == 1
    assert created_clients[0].close_task_id == created_clients[0].connect_task_id
    assert await manager.get_clients() == []


async def test_mcp_manager_restarts_owner_task_after_close_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drained manager should lazily create a fresh owner task later."""
    created_clients: list[_TaskBoundClient] = []

    def _build_client(config) -> _TaskBoundClient:
        client = _TaskBoundClient(config.name)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        MCPClientManager,
        "_build_client",
        staticmethod(_build_client),
    )

    manager = MCPClientManager()

    await manager.replace_client("huggingface", SimpleNamespace(name="first"))
    first_owner_task = manager._owner_task
    await manager.close_all()

    assert manager._owner_task is None

    await manager.replace_client("huggingface", SimpleNamespace(name="second"))

    assert manager._owner_task is not None
    assert manager._owner_task is not first_owner_task
    assert [client.name for client in created_clients] == ["first", "second"]
