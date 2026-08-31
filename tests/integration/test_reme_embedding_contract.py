# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Integration coverage for QwenPaw's pinned ReMe embedding contract."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from reme import ReMe
from reme.components.file_store import LocalFileStore

from qwenpaw.agents.memory.embedding_model import embedding_config_fingerprint
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
    _load_validated_reme_app,
)
from qwenpaw.config.config import EmbeddingModelConfig


def _embedding_config(model_name: str) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        backend="openai",
        api_key="key",
        base_url="https://example.com/v1",
        model_name=model_name,
        dimensions=3,
    )


@pytest.mark.integration
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
