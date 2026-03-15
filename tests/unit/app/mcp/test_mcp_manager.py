# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

import pytest

from copaw.app.mcp.manager import MCPClientManager


class _HealthyClient:
    is_connected = True

    def __init__(self) -> None:
        self.closed = False

    async def list_tools(self):
        return ["ok"]

    async def close(self):
        self.closed = True


class _BrokenClient:
    is_connected = True

    def __init__(self) -> None:
        self.closed = False

    async def list_tools(self):
        raise RuntimeError("broken")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_refresh_client_status_probe_success_without_replace() -> None:
    manager = MCPClientManager()
    manager._clients["demo"] = _HealthyClient()

    async def _replace_should_not_be_called(*args, **kwargs):
        raise AssertionError("replace_client should not be called")

    manager.replace_client = (
        _replace_should_not_be_called  # type: ignore[assignment]
    )

    cfg = SimpleNamespace(enabled=True)
    result = await manager.refresh_client_status("demo", cfg)

    assert result is True
    assert manager.is_active("demo") is True
    assert "demo" not in manager.failed_keys()


@pytest.mark.asyncio
async def test_refresh_status_probe_failed_then_replace_success() -> None:
    manager = MCPClientManager()
    broken = _BrokenClient()
    manager._clients["demo"] = broken

    called = {"replace": False}

    async def _replace_success(_key, _client_config, _timeout=15.0):
        called["replace"] = True

    manager.replace_client = _replace_success  # type: ignore[assignment]

    cfg = SimpleNamespace(enabled=True)
    result = await manager.refresh_client_status("demo", cfg)

    assert result is True
    assert called["replace"] is True
    assert broken.closed is True
    assert "demo" not in manager.failed_keys()


@pytest.mark.asyncio
async def test_refresh_client_status_replace_failed_marks_failed_key() -> None:
    manager = MCPClientManager()

    async def _replace_fail(_key, _client_config, _timeout=15.0):
        raise RuntimeError("connect failed")

    manager.replace_client = _replace_fail  # type: ignore[assignment]

    cfg = SimpleNamespace(enabled=True)
    result = await manager.refresh_client_status("demo", cfg)

    assert result is False
    assert "demo" in manager.failed_keys()
