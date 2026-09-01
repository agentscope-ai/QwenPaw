# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ReMe embedding object hot updates."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.embedding_model import (
    embedding_config_fingerprint,
)
from qwenpaw.agents.memory.reme_light_memory_manager import (
    EmbeddingReindexUnavailableError,
    ReMeLightMemoryManager,
    _to_reme_session_id,
)
from qwenpaw.config.config import AgentProfileConfig, EmbeddingModelConfig


class FakeReMe:
    """Minimal ReMe component updater used by the manager tests."""

    is_started = True

    def __init__(self, embedding_wrapper, embedding_store, file_store):
        self.embedding_wrapper = embedding_wrapper
        self.embedding_store = embedding_store
        self.file_store = file_store

    async def update_component(self, component_type, _name, **kwargs):
        component = {
            "as_embedding": self.embedding_wrapper,
            "embedding_store": self.embedding_store,
            "file_store": self.file_store,
        }[component_type]
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


def _manager(config: EmbeddingModelConfig):
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
        as_embedding=wrapper,
        enable_cache=True,
        max_cache_size=10,
        max_input_length=100,
        max_batch_size=2,
    )
    file_store = SimpleNamespace(
        resume_embedding=AsyncMock(return_value=True),
        require_embedding_rebuild=AsyncMock(),
    )
    manager._reme = FakeReMe(wrapper, store, file_store)
    manager._run_reme_job = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="ok"),
    )
    return manager, wrapper, store


@pytest.mark.asyncio
async def test_hot_update_reuses_tested_object_without_reindex() -> None:
    old_config = _config(api_key="old")
    new_config = _config(api_key="new", max_input_length=9000)
    manager, wrapper, store = _manager(old_config)
    tested_model = SimpleNamespace(context_size=old_config.max_input_length)
    manager._tested_embedding = (
        embedding_config_fingerprint(new_config),
        tested_model,
    )

    applied = await manager.apply_tested_embedding(new_config)

    assert applied is True
    assert wrapper.model is tested_model
    assert tested_model.context_size == new_config.max_input_length
    assert store.health_check_timeout == new_config.health_check_timeout
    manager._reme.file_store.resume_embedding.assert_awaited_once_with(
        verified=True,
    )
    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_change_disables_vectors_until_manual_reindex() -> None:
    old_config = _config(model_name="old-model")
    new_config = _config(model_name="new-model")
    manager, wrapper, _store = _manager(old_config)
    tested_model = object()
    manager._tested_embedding = (
        embedding_config_fingerprint(new_config),
        tested_model,
    )

    applied = await manager.apply_tested_embedding(new_config)

    assert applied is True
    require_rebuild = manager._reme.file_store.require_embedding_rebuild
    require_rebuild.assert_awaited_once_with()
    manager._reme.file_store.resume_embedding.assert_not_awaited()
    assert manager._active_embedding_config == old_config
    assert wrapper.model is not tested_model
    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_backend_change_keeps_indexed_provider_until_reindex() -> None:
    old_config = _config(backend="openai")
    new_config = _config(backend="dashscope")
    manager, old_wrapper, store = _manager(old_config)
    tested_model = object()
    manager._tested_embedding = (
        embedding_config_fingerprint(new_config),
        tested_model,
    )

    assert await manager.apply_tested_embedding(new_config) is True
    assert manager._reme.embedding_wrapper is old_wrapper
    assert store.as_embedding is old_wrapper
    assert old_wrapper.model is not tested_model
    require_rebuild = manager._reme.file_store.require_embedding_rebuild
    require_rebuild.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_manual_reindex_clears_persisted_requirement() -> None:
    config = _config()
    manager, _wrapper, _store = _manager(config)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = config.model_copy(deep=True)
    memory_config.needs_reindex = True

    async def update_config(_agent_id, updater):
        assert manager.is_reindexing is True
        updater(profile)
        return profile

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ) as update_config_mock,
    ):
        response = await manager.rebuild_index()

    assert response.success is True
    assert profile.running.reme_light_memory_config.needs_reindex is False
    manager._run_reme_job.assert_awaited_once_with(
        "reindex",
        raise_on_error=True,
        lifecycle_locked=True,
        scope="all",
    )
    assert update_config_mock.await_count == 2


@pytest.mark.asyncio
async def test_reindex_rejects_disabled_target_without_mutation() -> None:
    disabled = _config(model_name="")
    indexed = _config(model_name="indexed-model")
    manager, _wrapper, _store = _manager(disabled)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = disabled
    memory_config.needs_reindex = True
    memory_config.pending_reindex_embedding_config = indexed

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
        ) as update_config,
        pytest.raises(
            EmbeddingReindexUnavailableError,
            match="requires an enabled embedding configuration",
        ),
    ):
        await manager.rebuild_index("embedding")

    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config == indexed
    update_config.assert_not_awaited()
    manager._run_reme_job.assert_not_awaited()
    manager._reme.file_store.require_embedding_rebuild.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_reindex_rejects_disabled_embedding() -> None:
    disabled = _config(model_name="")
    manager, _wrapper, _store = _manager(disabled)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = disabled
    memory_config.needs_reindex = True
    indexed = _config(model_name="indexed-model")
    memory_config.pending_reindex_embedding_config = indexed

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
        ) as update_config,
        pytest.raises(
            EmbeddingReindexUnavailableError,
            match="all-scope index rebuild requires an enabled",
        ),
    ):
        await manager.rebuild_index("all")

    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config == indexed
    update_config.assert_not_awaited()
    manager._run_reme_job.assert_not_awaited()
    manager._reme.file_store.require_embedding_rebuild.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reme", [None, SimpleNamespace(is_started=False)])
async def test_reindex_returns_unavailable_when_reme_is_not_started(
    reme,
) -> None:
    config = _config()
    manager, _wrapper, _store = _manager(config)
    manager._reme = reme

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager."
        "load_agent_config_async",
    ) as load_config:
        response = await manager.rebuild_index("embedding")

    assert response is None
    load_config.assert_not_awaited()
    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_reindex_cancellation_after_persist_still_closes_live_gate() -> (
    None
):
    config = _config(model_name="new-model")
    manager, _wrapper, _store = _manager(config)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = config.model_copy(deep=True)
    caller = asyncio.current_task()
    assert caller is not None
    update_count = 0

    async def update_config(_agent_id, updater):
        nonlocal update_count
        updater(profile)
        update_count += 1
        if update_count == 1:
            caller.cancel()
        return profile

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await manager.rebuild_index("embedding")

    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config is None
    assert manager._active_embedding_config == config
    assert manager._reme.is_started is True
    manager._reme.file_store.require_embedding_rebuild.assert_awaited_once()
    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_reindex_does_not_clear_a_new_vector_space_requirement() -> None:
    new_config = _config(model_name="new-model")
    manager, _wrapper, _store = _manager(new_config)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = new_config
    memory_config.needs_reindex = True

    newer_config = _config(model_name="newer-model")
    update_count = 0

    async def update_config(_agent_id, updater):
        nonlocal update_count
        update_count += 1
        if update_count == 2:
            memory_config.embedding_model_config = newer_config
        updater(profile)
        return profile

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
    ):
        response = await manager.rebuild_index()

    assert response.success is True
    assert memory_config.needs_reindex is True


@pytest.mark.asyncio
async def test_reindex_cancel_regates_newer_vector_space() -> None:
    indexed = _config(model_name="indexed-model")
    target = _config(model_name="target-model")
    newer = _config(model_name="newer-model")
    manager, _wrapper, _store = _manager(target)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = target
    memory_config.needs_reindex = True
    memory_config.pending_reindex_embedding_config = indexed
    caller = asyncio.current_task()
    assert caller is not None
    update_count = 0

    async def update_config(_agent_id, updater):
        nonlocal update_count
        update_count += 1
        if update_count == 2:
            memory_config.embedding_model_config = newer
        updater(profile)
        if update_count == 2:
            caller.cancel()
        return profile

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await manager.rebuild_index("embedding")

    assert memory_config.embedding_model_config == newer
    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config == indexed
    assert manager._active_embedding_config == target
    assert manager._reme.is_started is True
    assert manager._reme.file_store.require_embedding_rebuild.await_count == 2


@pytest.mark.asyncio
async def test_reindex_regates_vectors_when_state_persistence_fails() -> None:
    config = _config()
    manager, _wrapper, _store = _manager(config)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = config
    memory_config.needs_reindex = True

    update_count = 0

    async def update_config(_agent_id, updater):
        nonlocal update_count
        update_count += 1
        if update_count == 2:
            raise OSError("disk full")
        updater(profile)
        return profile

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await manager.rebuild_index("embedding")

    assert memory_config.needs_reindex is True
    require_rebuild = manager._reme.file_store.require_embedding_rebuild
    assert require_rebuild.await_count == 2
    manager._run_reme_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_embedding_reindex_keeps_vector_search_disabled() -> None:
    config = _config()
    manager, _wrapper, _store = _manager(config)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = config
    manager._run_reme_job.return_value = SimpleNamespace(
        success=False,
        answer="failed",
    )

    async def update_config(_agent_id, updater):
        updater(profile)
        return profile

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
    ):
        response = await manager.rebuild_index("embedding")

    assert response.success is False
    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config is None
    require_rebuild = manager._reme.file_store.require_embedding_rebuild
    require_rebuild.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cancelled_embedding_reindex_keeps_restart_gate_persisted() -> (
    None
):
    config = _config()
    manager, _wrapper, _store = _manager(config)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = config
    manager._run_reme_job.side_effect = asyncio.CancelledError()

    async def update_config(_agent_id, updater):
        updater(profile)
        return profile

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await manager.rebuild_index("embedding")

    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config is None


@pytest.mark.asyncio
async def test_undo_restores_indexed_config_under_reindex_lock() -> None:
    indexed = _config(model_name="indexed-model")
    pending = _config(model_name="pending-model")
    manager, _wrapper, _store = _manager(pending)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = pending
    memory_config.pending_reindex_embedding_config = indexed
    memory_config.needs_reindex = True

    async def update_config(_agent_id, updater):
        assert manager.is_reindexing is True
        updater(profile)
        return profile

    manager._reload_embedding_config_unlocked = AsyncMock(return_value=True)
    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager."
        "update_agent_config_async",
        side_effect=update_config,
    ):
        restored = await manager.undo_embedding_reindex()

    assert restored == indexed
    assert memory_config.embedding_model_config == indexed
    assert memory_config.needs_reindex is False
    assert memory_config.pending_reindex_embedding_config is None
    manager._reload_embedding_config_unlocked.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_undo_cancel_after_persist_reloads_runtime() -> (None):
    indexed = _config(model_name="indexed-model")
    pending = _config(model_name="pending-model")
    manager, _wrapper, _store = _manager(pending)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = pending
    memory_config.pending_reindex_embedding_config = indexed
    memory_config.needs_reindex = True
    caller = asyncio.current_task()
    assert caller is not None

    async def update_config(_agent_id, updater):
        updater(profile)
        caller.cancel()
        return profile

    async def reload_indexed_runtime():
        manager._active_embedding_config = indexed.model_copy(deep=True)
        manager._reme = SimpleNamespace(is_started=True)
        return True

    manager._reload_embedding_config_unlocked = AsyncMock(
        side_effect=reload_indexed_runtime,
    )
    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await manager.undo_embedding_reindex()

    assert memory_config.embedding_model_config == indexed
    assert memory_config.needs_reindex is False
    assert memory_config.pending_reindex_embedding_config is None
    assert manager._active_embedding_config == indexed
    assert manager._reme.is_started is True
    manager._reload_embedding_config_unlocked.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_failed_undo_restores_pending_config_and_runtime() -> None:
    indexed = _config(model_name="indexed-model")
    pending = _config(model_name="pending-model")
    manager, _wrapper, _store = _manager(pending)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = pending
    memory_config.pending_reindex_embedding_config = indexed
    memory_config.needs_reindex = True
    reload_count = 0

    async def update_config(_agent_id, updater):
        updater(profile)
        return profile

    async def reload_runtime():
        nonlocal reload_count
        reload_count += 1
        active = memory_config.embedding_model_config.model_copy(deep=True)
        manager._active_embedding_config = active
        manager._reme = SimpleNamespace(is_started=reload_count == 2)
        return manager._reme.is_started

    manager._reload_embedding_config_unlocked = AsyncMock(
        side_effect=reload_runtime,
    )
    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
        pytest.raises(
            RuntimeError,
            match="pending embedding runtime was restored",
        ),
    ):
        await manager.undo_embedding_reindex()

    assert memory_config.embedding_model_config == pending
    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config == indexed
    assert manager._active_embedding_config == pending
    assert manager._reme.is_started is True
    assert manager._reload_embedding_config_unlocked.await_count == 2


@pytest.mark.asyncio
async def test_failed_undo_reports_pending_runtime_recovery_failure() -> None:
    indexed = _config(model_name="indexed-model")
    pending = _config(model_name="pending-model")
    manager, _wrapper, _store = _manager(pending)
    profile = AgentProfileConfig(id="bot", name="Bot")
    memory_config = profile.running.reme_light_memory_config
    memory_config.embedding_model_config = pending
    memory_config.pending_reindex_embedding_config = indexed
    memory_config.needs_reindex = True

    async def update_config(_agent_id, updater):
        updater(profile)
        return profile

    manager._reload_embedding_config_unlocked = AsyncMock(
        side_effect=[RuntimeError("indexed reload failed"), False],
    )
    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
        pytest.raises(
            RuntimeError,
            match="pending embedding runtime could not be loaded",
        ),
    ):
        await manager.undo_embedding_reindex()

    assert memory_config.embedding_model_config == pending
    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config == indexed
    assert manager._reload_embedding_config_unlocked.await_count == 2


@pytest.mark.asyncio
async def test_untested_config_falls_back_to_reload() -> None:
    config = _config()
    manager, _wrapper, _store = _manager(config)
    manager._tested_embedding = None

    assert await manager.apply_tested_embedding(config) is False


@pytest.mark.asyncio
async def test_embedding_update_waits_for_inflight_reme_job() -> None:
    config = _config(model_name="old-model")
    new_config = _config(model_name="new-model")
    manager, wrapper, _store = _manager(config)
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
async def test_reindex_and_embedding_update_share_lifecycle_boundary() -> None:
    new_config = _config(model_name="new-model")
    manager, _wrapper, _store = _manager(new_config)
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

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "load_agent_config_async",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager."
            "update_agent_config_async",
            side_effect=update_config,
        ),
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
    assert memory_config.needs_reindex is False


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
