# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Focused tests for the embedded ReMe startup lifecycle."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.exceptions import ProviderError


@pytest.mark.asyncio
async def test_start_without_active_model_keeps_provider_free_reme() -> None:
    """A fresh install must retain ReMe before model onboarding completes."""
    reme = SimpleNamespace(start=AsyncMock())
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager._reme = reme
    manager._update_qwenpaw_model = AsyncMock(
        side_effect=ProviderError("No active model configured."),
    )

    await manager.start()

    manager._update_qwenpaw_model.assert_awaited_once_with()
    reme.start.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_start_propagates_unexpected_model_injection_failure() -> None:
    """Only expected provider configuration failures may be degraded."""
    reme = SimpleNamespace(start=AsyncMock())
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager._reme = reme
    manager._update_qwenpaw_model = AsyncMock(
        side_effect=RuntimeError("unexpected injection failure"),
    )

    with pytest.raises(RuntimeError, match="unexpected injection failure"):
        await manager.start()

    reme.start.assert_not_awaited()
