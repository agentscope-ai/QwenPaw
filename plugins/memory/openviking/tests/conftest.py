# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Plugin test fixtures, including its runtime governance declaration."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from agentscope.message import Msg, TextBlock

from plugins.memory.openviking.backend.client import OpenVikingIdentity
from plugins.memory.openviking.backend.config import OpenVikingMemoryConfig
from plugins.memory.openviking.backend.manager import OpenVikingMemoryManager
from qwenpaw.memory import MemoryBackendContext


@pytest_asyncio.fixture
async def manager_factory(tmp_path):
    """Create managers sharing a test host and close them after the test."""
    managers = []

    def create(
        *,
        agent_id: str = "agent-1",
        config: OpenVikingMemoryConfig | None = None,
        expected_close_result: bool = True,
    ) -> OpenVikingMemoryManager:
        resolved_config = config or OpenVikingMemoryConfig()
        manager = OpenVikingMemoryManager(
            MemoryBackendContext(
                agent_id=agent_id,
                working_dir=tmp_path / "workspace",
                host_working_dir=tmp_path / "host",
                backend_config=resolved_config.model_dump(),
                language="en",
            ),
        )
        # Most tests attach a mock client without calling start().
        manager._config = resolved_config
        managers.append((manager, expected_close_result))
        return manager

    try:
        yield create
    finally:
        for manager, expected_close_result in reversed(managers):
            assert (
                await manager.close() is expected_close_result
            ), "Unexpected test manager close result"


@pytest.fixture
def client_factory():
    """Create independent mock clients without network connections."""

    def create(*, api_key="test-key"):
        return SimpleNamespace(
            config=SimpleNamespace(api_key=api_key),
            resolve_identity=AsyncMock(
                return_value=OpenVikingIdentity("account", "user"),
            ),
            ensure_session=AsyncMock(),
            add_messages=AsyncMock(),
            commit=AsyncMock(),
            search_context=AsyncMock(return_value={}),
            search_memories=AsyncMock(return_value=[]),
            close=AsyncMock(),
        )

    return create


@pytest.fixture
def attach_client():
    """Attach a mock client with an already resolved identity."""

    def attach(manager, client):
        manager._client = client
        manager._identity = OpenVikingIdentity("account", "user")

    return attach


@pytest.fixture
def user_message():
    """Build user messages with fresh source IDs."""

    def create(text):
        return Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text=text)],
        )

    return create


@pytest.fixture
def assistant_message():
    """Build assistant messages with fresh source IDs."""

    def create(text):
        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )

    return create


@pytest.fixture(autouse=True)
def capture_qwenpaw_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let caplog observe records emitted through the app logger tree."""
    monkeypatch.setattr(logging.getLogger("qwenpaw"), "propagate", True)


@pytest.fixture(scope="session", autouse=True)
def register_plugin_contract():
    """Install the metadata normally registered when this plugin starts."""
    from qwenpaw.governance.tool_registry import (
        DEFAULT_REGISTRY,
        register_tool_governance,
    )
    from qwenpaw.plugins.api import release_tool_ownership_for_plugin

    plugin_id = "memory-openviking"
    register_tool_governance(
        DEFAULT_REGISTRY,
        python_name="openviking_memory_search",
        policy_name="OpenVikingMemorySearch",
        tool_type="network",
        target_param="query",
        owner=plugin_id,
    )
    try:
        yield
    finally:
        release_tool_ownership_for_plugin(plugin_id)
