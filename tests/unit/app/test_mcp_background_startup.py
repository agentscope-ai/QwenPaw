# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for non-blocking MCP startup."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from qwenpaw.app.mcp.manager import MCPClientManager
from qwenpaw.app.workspace.service_factories import create_mcp_service
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config.config import MCPClientConfig, MCPConfig


class _Runner:
    def __init__(self) -> None:
        self.mcp_manager = None

    def set_mcp_manager(self, manager) -> None:
        self.mcp_manager = manager


class _FakeMCP:
    def __init__(self) -> None:
        self.blocking_calls = 0
        self.background_calls = 0
        self.background_config = None

    async def init_from_config(self, _config) -> None:
        self.blocking_calls += 1

    def init_from_config_background(self, config) -> None:
        self.background_calls += 1
        self.background_config = config


class _SlowClient:
    started = asyncio.Event()
    closed = 0

    async def connect(self) -> None:
        _SlowClient.started.set()
        await asyncio.sleep(60)

    async def close(self, ignore_errors: bool = False) -> None:
        _ = ignore_errors
        _SlowClient.closed += 1


def _enabled_mcp_config(client_count: int = 1) -> MCPConfig:
    return MCPConfig(
        clients={
            f"slow_{index}": MCPClientConfig(
                name=f"slow_{index}",
                enabled=True,
                command="slow-mcp",
            )
            for index in range(client_count)
        },
    )


@pytest.mark.asyncio
async def test_deferred_mcp_service_uses_background_initialization(tmp_path):
    workspace = Workspace(
        agent_id="default",
        workspace_dir=str(tmp_path),
        defer_mcp_startup=True,
    )
    workspace._config = SimpleNamespace(mcp=_enabled_mcp_config())
    workspace._service_manager.services["runner"] = _Runner()
    mcp = _FakeMCP()

    await create_mcp_service(workspace, mcp)

    assert mcp.background_calls == 1
    assert mcp.blocking_calls == 0
    assert mcp.background_config is workspace._config.mcp
    assert workspace._service_manager.services["runner"].mcp_manager is mcp


@pytest.mark.asyncio
async def test_regular_mcp_service_still_blocks_for_initialization(tmp_path):
    workspace = Workspace(
        agent_id="default",
        workspace_dir=str(tmp_path),
    )
    workspace._config = SimpleNamespace(mcp=_enabled_mcp_config())
    workspace._service_manager.services["runner"] = _Runner()
    mcp = _FakeMCP()

    await create_mcp_service(workspace, mcp)

    assert mcp.background_calls == 0
    assert mcp.blocking_calls == 1
    assert workspace._service_manager.services["runner"].mcp_manager is mcp


@pytest.mark.asyncio
async def test_background_mcp_initialization_does_not_block(monkeypatch):
    _SlowClient.started = asyncio.Event()
    _SlowClient.closed = 0
    manager = MCPClientManager()
    monkeypatch.setattr(
        manager,
        "_build_client",
        lambda _client_config: _SlowClient(),
    )

    manager.init_from_config_background(_enabled_mcp_config(), timeout=60.0)
    await asyncio.wait_for(_SlowClient.started.wait(), timeout=1.0)

    assert await manager.get_clients() == []
    await manager.close_all()
    assert _SlowClient.closed == 1


@pytest.mark.asyncio
async def test_close_all_cancels_background_startup(monkeypatch):
    _SlowClient.started = asyncio.Event()
    _SlowClient.closed = 0
    manager = MCPClientManager()
    monkeypatch.setattr(
        manager,
        "_build_client",
        lambda _client_config: _SlowClient(),
    )

    manager.init_from_config_background(
        _enabled_mcp_config(client_count=2),
        timeout=60.0,
    )
    await asyncio.wait_for(_SlowClient.started.wait(), timeout=1.0)

    await asyncio.wait_for(manager.close_all(), timeout=1.0)
    assert _SlowClient.closed == 1
