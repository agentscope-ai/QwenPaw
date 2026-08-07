# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ReMe embedding object hot updates."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.embedding_model import (
    embedding_config_fingerprint,
)
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.config.config import EmbeddingModelConfig


class FakeReMe:
    """Minimal ReMe component updater used by the manager tests."""

    is_started = True

    def __init__(self, embedding_wrapper, embedding_store):
        self.embedding_wrapper = embedding_wrapper
        self.embedding_store = embedding_store

    async def update_component(self, component_type, _name, **kwargs):
        component = (
            self.embedding_wrapper
            if component_type == "as_embedding"
            else self.embedding_store
        )
        for key, value in kwargs.items():
            setattr(component, key, value)
        return component


def _config(**overrides) -> EmbeddingModelConfig:
    values = {
        "backend": "openai",
        "api_key": "key",
        "base_url": "https://example.com/v1",
        "model_name": "embedding-model",
        "dimensions": 3,
    }
    values.update(overrides)
    return EmbeddingModelConfig(**values)


def _manager(tmp_path: Path, config: EmbeddingModelConfig):
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._embedding_update_lock = asyncio.Lock()
    manager._reindex_lock = asyncio.Lock()
    manager._active_embedding_config = config.model_copy(deep=True)
    wrapper = SimpleNamespace(model=object())
    store = SimpleNamespace(
        enable_cache=True,
        max_cache_size=10,
        max_input_length=100,
        max_batch_size=2,
        _cache={"old": [1, 2, 3]},
        _key_suffix=b"|3",
        cache_path=tmp_path / "embedding-cache.npz",
    )
    manager._reme = FakeReMe(wrapper, store)
    manager.rebuild_index = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="ok"),
    )
    return manager, wrapper, store


@pytest.mark.asyncio
async def test_hot_update_reuses_tested_object_without_reindex(
    tmp_path,
) -> None:
    old_config = _config(api_key="old")
    new_config = _config(api_key="new", max_input_length=9000)
    manager, wrapper, store = _manager(tmp_path, old_config)
    tested_model = SimpleNamespace(context_size=old_config.max_input_length)
    manager._tested_embedding = (
        embedding_config_fingerprint(new_config),
        tested_model,
    )

    applied = await manager.apply_tested_embedding(new_config)

    assert applied is True
    assert wrapper.model is tested_model
    assert tested_model.context_size == new_config.max_input_length
    assert store._cache == {"old": [1, 2, 3]}
    manager.rebuild_index.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_change_invalidates_cache_and_reindexes(tmp_path) -> None:
    old_config = _config(model_name="old-model")
    new_config = _config(model_name="new-model")
    manager, _wrapper, store = _manager(tmp_path, old_config)
    store.cache_path.write_bytes(b"old cache")
    manager._tested_embedding = (
        embedding_config_fingerprint(new_config),
        object(),
    )

    applied = await manager.apply_tested_embedding(new_config)

    assert applied is True
    assert store._cache == {}
    assert not store.cache_path.exists()
    manager.rebuild_index.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_untested_config_falls_back_to_reload(tmp_path) -> None:
    config = _config()
    manager, _wrapper, _store = _manager(tmp_path, config)
    manager._tested_embedding = None

    assert await manager.apply_tested_embedding(config) is False
