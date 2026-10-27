# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Focused tests for the embedded ReMe startup lifecycle."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
    _load_validated_reme_app,
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


def test_reme_rejects_build_without_watch_mode(monkeypatch) -> None:
    """The unpatched package must not silently ignore watch_mode in kwargs."""
    import reme
    from reme.steps.index.watch_changes import WatchChangesStep

    monkeypatch.setattr(reme, "__version__", "0.4.2.0")

    def old_init(_self, **_kwargs):
        pass

    monkeypatch.setattr(WatchChangesStep, "__init__", old_init)
    with pytest.raises(RuntimeError, match="requires ReMe with watch_mode"):
        _load_validated_reme_app()
