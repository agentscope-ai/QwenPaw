# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ReMe embedding object hot updates."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.embedding_model import (
    embedding_config_fingerprint,
)
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
    _to_reme_session_id,
)
from qwenpaw.config.config import AgentProfileConfig, EmbeddingModelConfig


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
    manager._reindex_lock = asyncio.Lock()
    manager._lifecycle_writer_lock = asyncio.Lock()
    manager._lifecycle_condition = asyncio.Condition()
    manager._active_reme_jobs = 0
    manager._lifecycle_operation = None
    manager.agent_id = "bot"
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
    manager._run_reme_job = AsyncMock(
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
    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_change_invalidates_cache_without_auto_reindex(
    tmp_path,
) -> None:
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
    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_reindex_clears_persisted_requirement(tmp_path) -> None:
    config = _config()
    manager, _wrapper, _store = _manager(tmp_path, config)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = config.model_copy(deep=True)
    memory_config.needs_reindex = True

    async def update_config(_agent_id, updater):
        assert manager.is_reindexing is True
        updater(profile)
        return profile

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager."
        "update_agent_config_async",
        side_effect=update_config,
    ) as update_config_mock:
        response = await manager.rebuild_index()

    assert response.success is True
    assert profile.running.reme_light_memory_config.needs_reindex is False
    update_config_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_reindex_does_not_clear_a_new_vector_space_requirement(
    tmp_path,
) -> None:
    old_config = _config(model_name="old-model")
    new_config = _config(model_name="new-model")
    manager, _wrapper, _store = _manager(tmp_path, old_config)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = new_config
    memory_config.needs_reindex = True

    async def update_config(_agent_id, updater):
        updater(profile)
        return profile

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager."
        "update_agent_config_async",
        side_effect=update_config,
    ):
        response = await manager.rebuild_index()

    assert response.success is True
    assert memory_config.needs_reindex is True


@pytest.mark.asyncio
async def test_untested_config_falls_back_to_reload(tmp_path) -> None:
    config = _config()
    manager, _wrapper, _store = _manager(tmp_path, config)
    manager._tested_embedding = None

    assert await manager.apply_tested_embedding(config) is False


@pytest.mark.asyncio
async def test_embedding_update_waits_for_inflight_reme_job(tmp_path) -> None:
    config = _config(model_name="old-model")
    new_config = _config(model_name="new-model")
    manager, wrapper, _store = _manager(tmp_path, config)
    del manager._run_reme_job
    job_started = asyncio.Event()
    finish_job = asyncio.Event()

    async def run_job(_name, **_kwargs):
        job_started.set()
        await finish_job.wait()
        return SimpleNamespace(success=True, answer="ok")

    manager._reme.run_job = run_job
    manager._append_reme_job_result_to_inbox = AsyncMock()
    manager._tested_embedding = (
        embedding_config_fingerprint(new_config),
        object(),
    )

    job = asyncio.create_task(manager._run_reme_job("search"))
    await job_started.wait()
    update = asyncio.create_task(manager.apply_tested_embedding(new_config))
    await asyncio.sleep(0)

    assert not update.done()
    assert wrapper.model is not manager._tested_embedding[1]

    finish_job.set()
    await job
    assert await update is True


@pytest.mark.asyncio
async def test_reindex_and_embedding_update_share_lifecycle_boundary(
    tmp_path,
) -> None:
    config = _config(model_name="old-model")
    new_config = _config(model_name="new-model")
    manager, _wrapper, _store = _manager(tmp_path, config)
    del manager._run_reme_job
    reindex_started = asyncio.Event()
    finish_reindex = asyncio.Event()
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = new_config.model_copy(deep=True)
    memory_config.needs_reindex = True

    async def run_job(name, **_kwargs):
        assert name == "reindex"
        reindex_started.set()
        await finish_reindex.wait()
        return SimpleNamespace(success=True, answer="ok")

    async def update_config(_agent_id, updater):
        updater(profile)
        return profile

    manager._reme.run_job = run_job
    manager._append_reme_job_result_to_inbox = AsyncMock()
    manager._tested_embedding = (
        embedding_config_fingerprint(new_config),
        object(),
    )

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager."
        "update_agent_config_async",
        side_effect=update_config,
    ):
        reindex = asyncio.create_task(manager.rebuild_index())
        await reindex_started.wait()
        update = asyncio.create_task(
            manager.apply_tested_embedding(new_config),
        )
        await asyncio.sleep(0)

        assert not update.done()
        finish_reindex.set()
        await reindex
        assert await update is True

    assert manager._active_embedding_config == new_config
    assert memory_config.needs_reindex is True


def test_reme_session_ids_are_fixed_length_and_collision_resistant() -> None:
    identifiers = [
        "Foo",
        "foo",
        "é",
        "e\N{COMBINING ACUTE ACCENT}",
        "CON",
        "telegram:123",
        "x" * 10_000,
    ]
    mapped = [_to_reme_session_id(value) for value in identifiers]

    assert len(set(mapped)) == len(identifiers)
    assert all(value.startswith("qpsid_sha256_") for value in mapped)
    assert all(len(value) == len("qpsid_sha256_") + 64 for value in mapped)
