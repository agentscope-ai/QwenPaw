# -*- coding: utf-8 -*-
"""Tests for transient Driver scope isolation and lifecycle."""

from __future__ import annotations

# Tests verify managed cleanup ownership directly.
# pylint: disable=protected-access

import asyncio
from pathlib import Path
from typing import ClassVar

import pytest

from qwenpaw.drivers.capabilities import (
    CapabilityExposure,
    DriverCapability,
    DriverInvocation,
    DriverInvocationResult,
    format_capability_id,
)
from qwenpaw.drivers.constants import DRIVER_SCOPE_CONTEXT_KEY
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.handler import DriverHandler
from qwenpaw.drivers.manager import DriverManager


class _FakeHandler(DriverHandler):
    shutdown_names: ClassVar[list[str]] = []

    async def _setup(self) -> None:
        if self.card.endpoint.get("fail"):
            raise RuntimeError(f"Failed to initialize {self.name}")

    async def _teardown(self) -> None:
        self.shutdown_names.append(self.name)

    async def list_capabilities(
        self,
        request_context: dict[str, str] | None = None,
    ) -> list[DriverCapability]:
        del request_context
        capability_id = format_capability_id(
            "fake",
            self.name,
            "tool",
            "invoke",
            "echo",
        )
        return [
            DriverCapability(
                capability_id=capability_id,
                driver_name=self.name,
                protocol="fake",
                kind="tool",
                action="invoke",
                name="echo",
                exposure=CapabilityExposure(
                    as_tool=True,
                    tool_name=f"{self.name}__echo",
                ),
            ),
        ]

    async def invoke_capability(
        self,
        invocation: DriverInvocation,
    ) -> DriverInvocationResult:
        return DriverInvocationResult(
            ok=True,
            value={
                "driver": self.name,
                "payload": invocation.payload,
            },
        )


def _card(
    name: str,
    *,
    fail: bool = False,
    enabled: bool = True,
) -> DriverCard:
    return DriverCard(
        name=name,
        protocol="fake",
        endpoint={"fail": fail},
        enabled=enabled,
    )


def _manager(tmp_path: Path) -> DriverManager:
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )
    manager.register_handler_type("fake", _FakeHandler)
    return manager


def _scope_context(scope_id: str) -> dict[str, str]:
    return {DRIVER_SCOPE_CONTEXT_KEY: scope_id}


@pytest.fixture(autouse=True)
def _reset_handler_state() -> None:
    _FakeHandler.shutdown_names = []


async def test_transient_drivers_are_additive_and_scope_isolated(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.register_driver(_card("persistent"))
    await manager.replace_transient_drivers(
        "scope-a",
        [_card("transient-a")],
    )
    await manager.replace_transient_drivers(
        "scope-b",
        [_card("transient-b")],
    )

    names_without_scope = {
        item.driver_name for item in await manager.list_capabilities()
    }
    names_in_a = {
        item.driver_name
        for item in await manager.list_capabilities(
            request_context=_scope_context("scope-a"),
        )
    }
    names_in_b = {
        item.driver_name
        for item in await manager.list_capabilities(
            request_context=_scope_context("scope-b"),
        )
    }

    assert names_without_scope == {"persistent"}
    assert names_in_a == {"persistent", "transient-a"}
    assert names_in_b == {"persistent", "transient-b"}


async def test_transient_invocation_rejects_another_scope(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.replace_transient_drivers(
        "scope-a",
        [_card("transient-a")],
    )
    capability = (
        await manager.list_capabilities(
            request_context=_scope_context("scope-a"),
        )
    )[0]

    result = await manager.invoke_capability(
        DriverInvocation(
            capability_id=capability.capability_id,
            payload={"value": "hello"},
            request_context=_scope_context("scope-b"),
        ),
    )

    assert result.ok is False
    assert result.error_type == "driver_scope_mismatch"


async def test_transient_replace_is_atomic_on_init_failure(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.replace_transient_drivers(
        "scope-a",
        [_card("old")],
    )

    with pytest.raises(RuntimeError, match="Failed to initialize broken"):
        await manager.replace_transient_drivers(
            "scope-a",
            [_card("new"), _card("broken", fail=True)],
        )

    names = {
        item.driver_name
        for item in await manager.list_capabilities(
            request_context=_scope_context("scope-a"),
        )
    }
    assert names == {"old"}
    assert "new" in _FakeHandler.shutdown_names
    assert "broken" in _FakeHandler.shutdown_names


async def test_transient_replace_commits_before_retired_cleanup(
    tmp_path: Path,
) -> None:
    teardown_started = asyncio.Event()
    allow_teardown = asyncio.Event()

    class _BlockingHandler(_FakeHandler):
        async def _teardown(self) -> None:
            if self.name == "old":
                teardown_started.set()
                await allow_teardown.wait()
            await super()._teardown()

    manager = _manager(tmp_path)
    manager.register_handler_type("fake", _BlockingHandler)
    await manager.replace_transient_drivers(
        "scope-a",
        [_card("old")],
    )

    replace_task = asyncio.create_task(
        manager.replace_transient_drivers(
            "scope-a",
            [_card("new")],
        ),
    )
    try:
        await asyncio.wait_for(teardown_started.wait(), timeout=1)

        assert replace_task.done()
        replace_task.cancel()
        await replace_task
        names = {
            item.driver_name
            for item in await manager.list_capabilities(
                request_context=_scope_context("scope-a"),
            )
        }
        assert names == {"new"}
    finally:
        allow_teardown.set()
        await manager.shutdown_all()


async def test_transient_remove_shuts_down_without_persisting(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.replace_transient_drivers(
        "scope-a",
        [_card("transient-a")],
    )

    assert await manager.card_store.list_paths() == []

    await manager.remove_transient_drivers("scope-a")

    assert (
        await manager.list_capabilities(
            request_context=_scope_context("scope-a"),
        )
        == []
    )
    await manager.shutdown_all()
    assert _FakeHandler.shutdown_names == ["transient-a"]


async def test_transient_remove_commits_before_handler_cleanup(
    tmp_path: Path,
) -> None:
    teardown_started = asyncio.Event()
    allow_teardown = asyncio.Event()

    class _BlockingHandler(_FakeHandler):
        async def _teardown(self) -> None:
            teardown_started.set()
            await allow_teardown.wait()
            await super()._teardown()

    manager = _manager(tmp_path)
    manager.register_handler_type("fake", _BlockingHandler)
    await manager.replace_transient_drivers(
        "scope-a",
        [_card("transient-a")],
    )
    handler = manager._handlers["transient-a"]

    remove_task = asyncio.create_task(
        manager.remove_transient_drivers("scope-a"),
    )
    try:
        await asyncio.wait_for(teardown_started.wait(), timeout=1)

        assert not remove_task.done()
        assert (
            manager._schedule_handler_cleanup(
                [handler],
            )
            is None
        )
        remove_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await remove_task
        assert (
            await manager.list_capabilities(
                request_context=_scope_context("scope-a"),
            )
            == []
        )
    finally:
        allow_teardown.set()
        await manager.shutdown_all()
    assert _FakeHandler.shutdown_names == ["transient-a"]


async def test_persistent_registration_rejects_transient_name(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.replace_transient_drivers(
        "scope-a",
        [_card("shared")],
    )

    with pytest.raises(ValueError, match="collides with a transient"):
        await manager.register_driver(_card("shared"))

    assert await manager.card_store.stored_path("shared") is None
    capabilities = await manager.list_capabilities(
        request_context=_scope_context("scope-a"),
    )
    assert [item.driver_name for item in capabilities] == ["shared"]


async def test_transient_registration_rejects_disabled_persistent_name(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.register_driver(_card("shared", enabled=False))

    with pytest.raises(ValueError, match="already exist"):
        await manager.replace_transient_drivers(
            "scope-a",
            [_card("shared")],
        )

    assert await manager.card_store.stored_path("shared") is not None
    assert (
        await manager.list_capabilities(
            request_context=_scope_context("scope-a"),
        )
        == []
    )
