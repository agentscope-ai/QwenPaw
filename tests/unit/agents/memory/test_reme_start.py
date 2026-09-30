# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Focused tests for the embedded ReMe startup lifecycle."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.embedding_model import (
    PerItemFallbackEmbeddingModel,
)
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.config.config import EmbeddingModelConfig
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


@pytest.mark.asyncio
async def test_start_injects_embedding_model_with_fallback() -> None:
    """ReMe must embed through a model that survives one bad chunk."""
    reme = SimpleNamespace(start=AsyncMock(), update_component=AsyncMock())
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager._reme = reme
    manager._update_qwenpaw_model = AsyncMock()
    manager._active_embedding_config = EmbeddingModelConfig(
        backend="openai",
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="embedding-model",
        dimensions=3,
    )

    await manager.start()

    reme.update_component.assert_awaited_once()
    assert reme.update_component.await_args.args == (
        "as_embedding",
        "default",
    )
    injected = reme.update_component.await_args.kwargs["model"]
    assert isinstance(injected, PerItemFallbackEmbeddingModel)
    assert injected.model == "embedding-model"
    reme.start.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_start_skips_embedding_injection_when_disabled() -> None:
    """A disabled embedding backend has no ReMe component to update."""
    reme = SimpleNamespace(start=AsyncMock(), update_component=AsyncMock())
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager._reme = reme
    manager._update_qwenpaw_model = AsyncMock()
    manager._active_embedding_config = EmbeddingModelConfig(model_name="")

    await manager.start()

    reme.update_component.assert_not_awaited()
    reme.start.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_start_survives_embedding_injection_failure() -> None:
    """ReMe can build its own provider when injection is impossible."""
    reme = SimpleNamespace(
        start=AsyncMock(),
        update_component=AsyncMock(
            side_effect=KeyError("Component 'default' not found"),
        ),
    )
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager._reme = reme
    manager._update_qwenpaw_model = AsyncMock()
    manager._active_embedding_config = EmbeddingModelConfig(
        backend="openai",
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="embedding-model",
        dimensions=3,
    )

    await manager.start()

    reme.start.assert_awaited_once_with()
