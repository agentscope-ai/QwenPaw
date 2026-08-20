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
