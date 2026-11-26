# -*- coding: utf-8 -*-
"""Tests for the workspace publish/plugin-provisioning race."""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.app.agent_startup import AgentStartupStatus
from qwenpaw.app.multi_agent_manager import (
    _AGENT_PUBLISH_READY_TIMEOUT_SECONDS,
    MultiAgentManager,
)
from qwenpaw.exceptions import ConfigurationException


def _published_but_provisioning(
    manager: MultiAgentManager,
    *,
    owner: asyncio.Task | None,
) -> asyncio.Event:
    """Set up the exact window between publish and startup-event set."""
    workspace = object()
    event = asyncio.Event()
    manager.agents["default"] = workspace
    manager._agent_startup_statuses[
        "default"
    ] = AgentStartupStatus.RUNNING  # pylint: disable=protected-access
    manager._pending_starts[
        "default"
    ] = event  # pylint: disable=protected-access
    if owner is not None:
        manager._pending_start_owners[
            "default"
        ] = owner  # pylint: disable=protected-access
    return event


def _cleanup(manager: MultiAgentManager) -> None:
    manager.agents.clear()
    manager._pending_starts.clear()  # pylint: disable=protected-access
    manager._pending_start_owners.clear()  # pylint: disable=protected-access
    manager._agent_startup_statuses.clear()  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_fast_path_waits_for_workspace_provisioning() -> None:
    manager = MultiAgentManager()
    owner = asyncio.create_task(asyncio.sleep(60))
    event = _published_but_provisioning(manager, owner=owner)
    waiter = asyncio.create_task(manager.get_agent("default"))
    try:
        await asyncio.sleep(0.02)
        assert waiter.done() is False

        event.set()
        workspace = await asyncio.wait_for(waiter, timeout=1)
        assert workspace is manager.agents["default"]
    finally:
        owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
        _cleanup(manager)


@pytest.mark.asyncio
async def test_provisioning_timeout_is_a_configuration_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager."
        "_AGENT_PUBLISH_READY_TIMEOUT_SECONDS",
        0.05,
    )
    manager = MultiAgentManager()
    owner = asyncio.create_task(asyncio.sleep(60))
    _published_but_provisioning(manager, owner=owner)
    try:
        with pytest.raises(ConfigurationException) as exc_info:
            await manager.get_agent("default")
        assert "did not finish in time" in exc_info.value.message
    finally:
        owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
        _cleanup(manager)


@pytest.mark.asyncio
async def test_startup_owner_does_not_deadlock_its_own_workspace() -> None:
    manager = MultiAgentManager()
    _published_but_provisioning(
        manager,
        owner=asyncio.current_task(),
    )
    try:
        async with asyncio.timeout(1):
            workspace = await manager.get_agent("default")
        assert workspace is manager.agents["default"]
    finally:
        _cleanup(manager)


@pytest.mark.asyncio
async def test_post_wait_failure_is_visible() -> None:
    manager = MultiAgentManager()
    owner = asyncio.create_task(asyncio.sleep(60))
    event = _published_but_provisioning(manager, owner=owner)
    waiter = asyncio.create_task(manager.get_agent("default"))
    try:
        await asyncio.sleep(0.02)
        manager._agent_startup_statuses[
            "default"
        ] = AgentStartupStatus.FAILED  # pylint: disable=protected-access
        event.set()
        with pytest.raises(ConfigurationException):
            await asyncio.wait_for(waiter, timeout=1)
    finally:
        owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
        _cleanup(manager)


def test_publish_ready_timeout_is_positive() -> None:
    assert _AGENT_PUBLISH_READY_TIMEOUT_SECONDS > 0
