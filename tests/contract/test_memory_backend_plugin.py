# -*- coding: utf-8 -*-
"""Contract tests for third-party memory backend registration."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from agentscope.message import Msg
from agentscope.tool import ToolChunk

from qwenpaw.memory import (
    BaseMemoryManager,
    MemoryBackendContext,
    MemoryBackendUnavailableError,
    get_memory_manager_backend,
    memory_registry,
)


class ContractBackend(BaseMemoryManager):
    def __init__(self, context: MemoryBackendContext) -> None:
        super().__init__(context=context)

    async def start(self) -> None:
        return None

    async def memory_search(self, query: str, max_results: int = 5, **kwargs):
        del query, max_results, kwargs
        return ToolChunk(is_last=True)

    async def auto_memory(self, messages: list[Msg], **kwargs) -> str:
        del messages, kwargs
        return ""


def test_plugin_registration_is_owned_and_unregistered(tmp_path: Path) -> None:
    backend_id = "contract-memory"
    owner = "contract-plugin"
    memory_registry.register_backend(
        plugin_id=owner,
        backend_id=backend_id.upper(),
        factory=ContractBackend,
        label="Contract Memory",
    )
    try:
        factory = get_memory_manager_backend(backend_id)
        instance = factory(
            MemoryBackendContext(
                agent_id="agent",
                working_dir=tmp_path,
                host_working_dir=tmp_path,
                backend_config={"opaque": True},
            ),
        )
        assert instance.context.backend_config == {"opaque": True}
        with pytest.raises(ValueError, match="already registered"):
            memory_registry.register_backend(
                plugin_id="other-plugin",
                backend_id=backend_id,
                factory=ContractBackend,
                label="Conflict",
            )
    finally:
        assert memory_registry.unregister_owner(owner) == [backend_id]


def test_unknown_backend_does_not_fallback() -> None:
    with pytest.raises(MemoryBackendUnavailableError) as caught:
        get_memory_manager_backend("missing-contract-backend")
    assert caught.value.reason == "plugin_not_installed"


def test_owner_unload_cannot_race_backend_construction(tmp_path: Path) -> None:
    backend_id = "concurrent-contract-memory"
    owner = "concurrent-contract-plugin"
    constructor_entered = threading.Event()
    release_constructor = threading.Event()
    unload_started = threading.Event()

    class BlockingBackend(ContractBackend):
        def __init__(self, context: MemoryBackendContext) -> None:
            constructor_entered.set()
            assert release_constructor.wait(timeout=2)
            super().__init__(context)

    context = MemoryBackendContext(
        agent_id="agent",
        working_dir=tmp_path,
        host_working_dir=tmp_path,
        backend_config={},
    )
    memory_registry.register_backend(
        plugin_id=owner,
        backend_id=backend_id,
        factory=BlockingBackend,
        label="Concurrent Contract Memory",
    )

    def begin_unload() -> list[str]:
        unload_started.set()
        return memory_registry.begin_owner_unload(owner)

    instance = None
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            construction = executor.submit(
                memory_registry.create,
                backend_id,
                context,
            )
            assert constructor_entered.wait(timeout=2)
            unloading = executor.submit(begin_unload)
            assert unload_started.wait(timeout=2)
            assert unloading.result(timeout=2) == ["agent"]
            release_constructor.set()
            instance = construction.result(timeout=2)

        assert memory_registry.begin_owner_unload(owner) == ["agent"]
        assert get_memory_manager_backend(backend_id) is BlockingBackend
    finally:
        release_constructor.set()
        if instance is not None:
            memory_registry.release_instance(instance)
        memory_registry.cancel_owner_unload(owner)
        memory_registry.unregister_owner(owner)


def test_reserved_owner_rejects_new_backend_construction(
    tmp_path: Path,
) -> None:
    backend_id = "unloading-contract-memory"
    owner = "unloading-contract-plugin"
    memory_registry.register_backend(
        plugin_id=owner,
        backend_id=backend_id,
        factory=ContractBackend,
        label="Unloading Contract Memory",
    )
    context = MemoryBackendContext(
        agent_id="agent",
        working_dir=tmp_path,
        host_working_dir=tmp_path,
        backend_config={},
    )
    try:
        assert memory_registry.begin_owner_unload(owner) == []
        with pytest.raises(MemoryBackendUnavailableError):
            memory_registry.create(backend_id, context)
    finally:
        memory_registry.unregister_owner(owner)


def test_failed_constructor_releases_owner_reservation(tmp_path: Path) -> None:
    backend_id = "failing-contract-memory"
    owner = "failing-contract-plugin"

    class FailingBackend(ContractBackend):
        def __init__(self, context: MemoryBackendContext) -> None:
            del context
            raise RuntimeError("construction failed")

    memory_registry.register_backend(
        plugin_id=owner,
        backend_id=backend_id,
        factory=FailingBackend,
        label="Failing Contract Memory",
    )
    context = MemoryBackendContext(
        agent_id="agent",
        working_dir=tmp_path,
        host_working_dir=tmp_path,
        backend_config={},
    )
    try:
        with pytest.raises(RuntimeError, match="construction failed"):
            memory_registry.create(backend_id, context)
        assert memory_registry.begin_owner_unload(owner) == []
    finally:
        memory_registry.unregister_owner(owner)
