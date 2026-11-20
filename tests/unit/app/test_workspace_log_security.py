# -*- coding: utf-8 -*-
"""Workspace lifecycle logs cannot forge records using agent IDs."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.app.workspace.service_manager import (
    ServiceDescriptor,
    ServiceManager,
)


@pytest.mark.parametrize(
    "reusable,reused",
    [(True, False), (False, True), (False, False)],
)
async def test_service_shutdown_escapes_agent_id(caplog, reusable, reused):
    agent_id = "agent\r\nFORGED"
    manager = ServiceManager(SimpleNamespace(agent_id=agent_id))
    service = SimpleNamespace(stop=AsyncMock())
    descriptor = ServiceDescriptor(
        name="test_service",
        stop_method="stop",
        reusable=reusable,
    )
    manager.services[descriptor.name] = service
    if reused:
        manager.reused_services.add(descriptor.name)
    with caplog.at_level(
        logging.DEBUG,
        logger="qwenpaw.app.workspace.service_manager",
    ):
        await manager._stop_service(descriptor)
    messages = [
        r.getMessage() for r in caplog.records if "agent" in r.getMessage()
    ]
    assert messages
    assert all("agent\\r\\nFORGED" in message for message in messages)
    assert all(
        "\r" not in message and "\n" not in message for message in messages
    )
    assert service.stop.await_count == (0 if reusable or reused else 1)


@pytest.mark.parametrize("reason", ["removed", "config_changed"])
async def test_discard_reload_escapes_agent_id(caplog, reason):
    candidate = SimpleNamespace(stop=AsyncMock())
    with caplog.at_level(logging.INFO):
        await MultiAgentManager._discard_reload_candidate(
            candidate,
            "agent\r\nFORGED",
            reason,
        )
    candidate.stop.assert_awaited_once_with(final=True, preserve_reused=True)
    messages = [
        r.getMessage() for r in caplog.records if "FORGED" in r.getMessage()
    ]
    assert messages
    assert all("agent\\r\\nFORGED" in message for message in messages)
    assert all(
        "\r" not in message and "\n" not in message for message in messages
    )
