# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Integration coverage for QwenPaw's pinned ReMe embedding contract."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from reme import ReMe
from reme.components.file_store import LocalFileStore
from reme.components.file_store.local_file_store import FileChunk

from qwenpaw.agents.memory.embedding_model import embedding_config_fingerprint
from qwenpaw.agents.memory.reme_light_memory_manager import (
    EmbeddingReindexUnavailableError,
    ReMeLightMemoryManager,
    _load_validated_reme_app,
)
from qwenpaw.config.config import AgentProfileConfig, EmbeddingModelConfig


def _embedding_config(model_name: str) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        backend="openai",
        api_key="key",
        base_url="https://example.com/v1",
        model_name=model_name,
        dimensions=3,
    )


@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.asyncio
async def test_vector_space_gate_uses_real_reme_without_blocking_loop(
    tmp_path,
    monkeypatch,
) -> None:
    """Exercise the host gate and checkpoint threading with real ReMe code."""
    assert _load_validated_reme_app() is ReMe
    monkeypatch.chdir(tmp_path)
    file_store = LocalFileStore(
        name="qwenpaw_embedding_contract",
        embedding_store="",
    )
    await file_store.start()
    original_dump = file_store._dump_chunks_sync

    try:
        old_config = _embedding_config("old-model")
        new_config = _embedding_config("new-model")
        manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
        manager._reindex_lock = asyncio.Lock()
        manager._lifecycle_writer_lock = asyncio.Lock()
        manager._lifecycle_condition = asyncio.Condition()
        manager._active_reme_jobs = 0
        manager._lifecycle_operation = None
        manager._active_embedding_config = old_config
        manager._tested_embedding = (
            embedding_config_fingerprint(new_config),
            object(),
        )
        manager.agent_id = "bot"

        async def update_component(component_type, name, **_kwargs):
            assert (component_type, name) == ("file_store", "default")
            return file_store

        manager._reme = SimpleNamespace(
            is_started=True,
            update_component=update_component,
        )

        assert await manager.apply_tested_embedding(new_config) is True
        assert file_store._embedding_rebuild_pending is True

        entered = threading.Event()
        release = threading.Event()

        def blocking_dump(chunks):
            entered.set()
            assert release.wait(timeout=2)
            original_dump(chunks)

        file_store._dump_chunks_sync = blocking_dump
        dump_task = asyncio.create_task(file_store._dump_owned_state())
        assert await asyncio.to_thread(entered.wait, 1)

        ticks = 0
        for _ in range(5):
            await asyncio.sleep(0)
            ticks += 1
        assert ticks == 5
        assert not dump_task.done()

        release.set()
        await dump_task
    finally:
        file_store._dump_chunks_sync = original_dump
        await file_store.close()


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.asyncio
async def test_disabled_embedding_reindex_preserves_real_reme_vectors(
    tmp_path,
    monkeypatch,
) -> None:
    """Reject before ReMe can clear vectors or publish host state changes."""
    assert _load_validated_reme_app() is ReMe
    monkeypatch.chdir(tmp_path)
    file_store = LocalFileStore(
        name="qwenpaw_disabled_embedding_reindex",
        embedding_store="",
    )
    await file_store.start()
    vector = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)
    chunk = FileChunk(
        id="existing-vector",
        text="existing memory",
        embedding=vector.copy(),
        path="memory/existing.md",
        start_line=1,
        end_line=1,
    )
    assert chunk.embedding is not None
    original_embedding = chunk.embedding.copy()
    file_store.file_chunks[chunk.id] = chunk

    try:
        disabled = EmbeddingModelConfig(
            backend="openai",
            api_key="",
            model_name="",
            dimensions=3,
        )
        indexed = _embedding_config("indexed-model")
        profile = AgentProfileConfig(id="bot", name="Bot")
        memory_config = profile.running.reme_light_memory_config
        memory_config.embedding_model_config = disabled
        memory_config.needs_reindex = True
        memory_config.pending_reindex_embedding_config = indexed

        manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
        manager._reindex_lock = asyncio.Lock()
        manager._lifecycle_writer_lock = asyncio.Lock()
        manager._lifecycle_condition = asyncio.Condition()
        manager._active_reme_jobs = 0
        manager._lifecycle_operation = None
        manager._active_embedding_config = disabled
        manager.agent_id = "bot"

        async def update_component(component_type, name, **_kwargs):
            assert (component_type, name) == ("file_store", "default")
            return file_store

        manager._reme = SimpleNamespace(
            is_started=True,
            update_component=update_component,
        )

        async def destructive_reindex(*_args, **_kwargs):
            result = await file_store.reindex(_kwargs["scope"])
            return SimpleNamespace(success=True, answer=result)

        manager._run_reme_job = AsyncMock(side_effect=destructive_reindex)
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
            pytest.raises(EmbeddingReindexUnavailableError),
        ):
            await manager.rebuild_index("embedding")

        np.testing.assert_array_equal(chunk.embedding, original_embedding)
        assert file_store._embedding_rebuild_pending is False
        assert memory_config.needs_reindex is True
        assert memory_config.pending_reindex_embedding_config == indexed
        update_config.assert_not_awaited()
        manager._run_reme_job.assert_not_awaited()
    finally:
        await file_store.close()
