# -*- coding: utf-8 -*-
"""Strict-stop lifecycle tests for workspace services."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.workspace.service_manager import (
    ServiceDescriptor,
    ServiceManager,
)


@pytest.mark.asyncio
async def test_headless_start_skips_background_services():
    manager = ServiceManager(SimpleNamespace(agent_id="agent-1"))
    started: list[str] = []

    class _Service:
        def __init__(self, name: str) -> None:
            self.name = name

        async def start(self) -> None:
            started.append(self.name)

    manager.register(
        ServiceDescriptor(
            name="core",
            post_init=lambda _workspace, _service: _Service("core"),
            start_method="start",
        ),
    )
    manager.register(
        ServiceDescriptor(
            name="background",
            post_init=lambda _workspace, _service: _Service("background"),
            start_method="start",
            enabled_in_headless=False,
        ),
    )

    await manager.start_all(headless=True)

    assert started == ["core"]
    assert "core" in manager.services
    assert "background" not in manager.services


@pytest.mark.asyncio
async def test_required_clean_stop_failure_is_propagated():
    manager = ServiceManager(SimpleNamespace(agent_id="agent-1"))

    class _StuckService:
        async def stop(self) -> None:
            raise RuntimeError("worker is still alive")

    descriptor = ServiceDescriptor(
        name="mail_monitor",
        stop_method="stop",
        require_clean_stop=True,
    )
    manager.register(descriptor)
    manager.services[descriptor.name] = _StuckService()

    with pytest.raises(RuntimeError, match="worker is still alive"):
        await manager.stop_all()
