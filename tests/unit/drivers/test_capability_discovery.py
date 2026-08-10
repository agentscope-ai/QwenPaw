# -*- coding: utf-8 -*-
# pylint: disable=invalid-name,protected-access
"""Latency-sensitive Driver capability discovery behavior."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.drivers.capabilities import (
    CapabilityExposure,
    DriverCapability,
)
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.drivers.manager import DriverManager


@dataclass
class _Tool:
    name: str
    description: str = ""
    inputSchema: dict[str, object] | None = None


class _RefreshingClient:
    """Return one tool immediately, then block the refresh until released."""

    def __init__(self) -> None:
        self.calls = 0
        self.closed = False
        self.refresh_started = asyncio.Event()
        self.release_refresh = asyncio.Event()

    async def list_tools(self) -> list[_Tool]:
        self.calls += 1
        if self.calls == 1:
            return [_Tool("old_tool")]
        self.refresh_started.set()
        await self.release_refresh.wait()
        return [_Tool("new_tool")]

    async def close(self) -> None:
        self.closed = True


def _mcp_handler(client: Any) -> MCPDriverHandler:
    handler = MCPDriverHandler.__new__(MCPDriverHandler)
    handler._card = DriverCard(
        name="slow_mcp",
        protocol="mcp",
        endpoint={},
    )
    handler._client = client
    handler._capability_cache = None
    handler._capability_refresh_task = None
    return handler


@pytest.mark.asyncio
async def test_expired_mcp_snapshot_does_not_block_current_request() -> None:
    client = _RefreshingClient()
    handler = _mcp_handler(client)
    initial = await handler.list_capabilities()
    handler._capability_cache = (
        time.monotonic() - 60,
        initial,
    )

    try:
        cached = await asyncio.wait_for(
            handler.list_capabilities(),
            timeout=1.0,
        )

        assert [item.name for item in cached] == ["old_tool"]
        await asyncio.wait_for(client.refresh_started.wait(), timeout=1.0)

        refresh_task = handler._capability_refresh_task
        assert refresh_task is not None
        client.release_refresh.set()
        await asyncio.wait_for(asyncio.shield(refresh_task), timeout=1.0)
        refreshed = await handler.list_capabilities()

        assert [item.name for item in refreshed] == ["new_tool"]
        assert client.calls == 2
    finally:
        client.release_refresh.set()
        await handler._teardown()


@pytest.mark.asyncio
async def test_expired_mcp_snapshot_refresh_is_single_flight() -> None:
    client = _RefreshingClient()
    handler = _mcp_handler(client)
    initial = await handler.list_capabilities()
    handler._capability_cache = (
        time.monotonic() - 60,
        initial,
    )

    try:
        first, second = await asyncio.gather(
            handler.list_capabilities(),
            handler.list_capabilities(),
        )
        await asyncio.wait_for(client.refresh_started.wait(), timeout=1.0)

        assert [item.name for item in first] == ["old_tool"]
        assert [item.name for item in second] == ["old_tool"]
        assert client.calls == 2
    finally:
        client.release_refresh.set()
        await handler._teardown()


@pytest.mark.asyncio
async def test_mcp_teardown_cancels_in_progress_capability_refresh() -> None:
    client = _RefreshingClient()
    handler = _mcp_handler(client)
    initial = await handler.list_capabilities()
    handler._capability_cache = (
        time.monotonic() - 60,
        initial,
    )

    assert [item.name for item in await handler.list_capabilities()] == [
        "old_tool",
    ]
    await asyncio.wait_for(client.refresh_started.wait(), timeout=1.0)

    await asyncio.wait_for(handler._teardown(), timeout=1.0)

    assert client.closed is True
    assert handler._capability_cache is None
    assert handler._capability_refresh_task is None


class _ColdClient:
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def list_tools(self) -> list[_Tool]:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return [_Tool("cold_tool")]

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_cold_mcp_capability_refresh_is_single_flight() -> None:
    client = _ColdClient()
    handler = _mcp_handler(client)

    first_task = asyncio.create_task(handler.list_capabilities())
    second_task = asyncio.create_task(handler.list_capabilities())
    try:
        await asyncio.wait_for(client.started.wait(), timeout=1.0)
        await asyncio.sleep(0)
        assert client.calls == 1

        client.release.set()
        first, second = await asyncio.gather(first_task, second_task)
        assert [item.name for item in first] == ["cold_tool"]
        assert [item.name for item in second] == ["cold_tool"]
    finally:
        client.release.set()
        await handler._teardown()


def _capability(driver_name: str) -> DriverCapability:
    return DriverCapability(
        capability_id=f"driver://fake/{driver_name}/tools/ping#invoke",
        driver_name=driver_name,
        protocol="fake",
        kind="tool",
        action="invoke",
        name=f"{driver_name}_tool",
        exposure=CapabilityExposure(
            as_tool=True,
            tool_name=f"{driver_name}_tool",
        ),
    )


class _SlowHandler:
    def __init__(
        self,
        name: str,
        started: list[str],
        all_started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        self.name = name
        self.card = SimpleNamespace(protocol="fake")
        self._started = started
        self._all_started = all_started
        self._release = release

    async def list_capabilities(
        self,
        request_context: dict[str, str] | None = None,
    ) -> list[DriverCapability]:
        del request_context
        self._started.append(self.name)
        if len(self._started) == 2:
            self._all_started.set()
        await self._release.wait()
        return [_capability(self.name)]


class _FailingHandler:
    def __init__(self, peer_started: asyncio.Event) -> None:
        self.name = "failing"
        self.card = SimpleNamespace(protocol="fake")
        self._peer_started = peer_started

    async def list_capabilities(
        self,
        request_context: dict[str, str] | None = None,
    ) -> list[DriverCapability]:
        del request_context
        await self._peer_started.wait()
        raise RuntimeError("capability discovery failed")


class _CancellableHandler:
    def __init__(
        self,
        started: asyncio.Event,
        cancelled: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        self.name = "slow"
        self.card = SimpleNamespace(protocol="fake")
        self._started = started
        self._cancelled = cancelled
        self._release = release

    async def list_capabilities(
        self,
        request_context: dict[str, str] | None = None,
    ) -> list[DriverCapability]:
        del request_context
        self._started.set()
        try:
            await self._release.wait()
        except asyncio.CancelledError:
            self._cancelled.set()
            raise
        return [_capability(self.name)]


@pytest.mark.asyncio
async def test_manager_collects_independent_driver_capabilities_concurrently(
    tmp_path: Path,
) -> None:
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )
    started: list[str] = []
    all_started = asyncio.Event()
    release = asyncio.Event()
    manager._handlers = {  # type: ignore[assignment]
        name: _SlowHandler(name, started, all_started, release)
        for name in ("alpha", "beta")
    }

    collect_task = asyncio.create_task(manager.list_capabilities())
    try:
        await asyncio.wait_for(all_started.wait(), timeout=1.0)
    finally:
        release.set()
        capabilities = await collect_task

    assert [item.name for item in capabilities] == [
        "alpha_tool",
        "beta_tool",
    ]


@pytest.mark.asyncio
async def test_manager_cancels_other_discovery_when_one_driver_fails(
    tmp_path: Path,
) -> None:
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )
    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()
    release_slow = asyncio.Event()
    manager._handlers = {  # type: ignore[assignment]
        "failing": _FailingHandler(slow_started),
        "slow": _CancellableHandler(
            slow_started,
            slow_cancelled,
            release_slow,
        ),
    }

    try:
        with pytest.raises(RuntimeError, match="capability discovery failed"):
            await manager.list_capabilities()
        await asyncio.wait_for(slow_cancelled.wait(), timeout=1.0)
    finally:
        release_slow.set()
        await asyncio.sleep(0)
