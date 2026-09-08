# -*- coding: utf-8 -*-
"""Contract tests for third-party memory backend registration."""

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
