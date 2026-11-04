# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Startup, shutdown and session identity regression tests."""

import asyncio
import threading
from dataclasses import replace
from unittest.mock import Mock

import pytest
from agentscope.message import ToolResultState

from plugins.memory.openviking.backend import manager as manager_module
from plugins.memory.openviking.backend.client import (
    OpenVikingConfigurationError,
    OpenVikingIdentity,
    OpenVikingServiceError,
)
from plugins.memory.openviking.backend.config import OpenVikingMemoryConfig


@pytest.mark.asyncio
async def test_unconfigured_start_performs_no_identity_or_network_io(
    monkeypatch,
    manager_factory,
):
    manager = manager_factory()
    installation_id = Mock(side_effect=AssertionError("Unexpected file I/O"))
    constructor = Mock(side_effect=AssertionError("Unexpected HTTP client"))
    monkeypatch.setattr(
        manager_module,
        "get_or_create_installation_id",
        installation_id,
    )
    monkeypatch.setattr(manager_module, "OpenVikingClient", constructor)

    try:
        await manager.start()
        assert not manager.list_memory_tools()
        assert manager.get_memory_prompt() == ""
        assert manager.get_auto_memory_interval() == 0
        assert await manager.get_auto_memory_search_options() is None
        result = await manager.memory_search("tea")
        assert result.state == ToolResultState.ERROR
        installation_id.assert_not_called()
        constructor.assert_not_called()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_invalid_startup_credentials_close_and_disable_backend(
    monkeypatch,
    manager_factory,
    client_factory,
    user_message,
):
    manager = manager_factory(
        config=OpenVikingMemoryConfig(api_key="test-key"),
    )
    client = client_factory()
    client.resolve_identity.side_effect = OpenVikingConfigurationError(
        "Invalid credentials",
    )
    monkeypatch.setattr(
        manager_module,
        "OpenVikingClient",
        Mock(return_value=client),
    )

    try:
        await manager.start()
        client.close.assert_awaited_once()
        assert not manager.list_memory_tools()
        assert manager.get_memory_prompt() == ""
        assert manager.get_auto_memory_interval() == 0
        assert await manager.get_auto_memory_search_options() is None
        assert (
            await manager.auto_memory_search(
                user_message("tea"),
                session_id="chat",
            )
            is None
        )
        client.search_context.assert_not_awaited()
    finally:
        await manager.close()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["recall", "persist"])
async def test_startup_outage_recovers_on_later_use(
    monkeypatch,
    operation,
    manager_factory,
    client_factory,
    user_message,
):
    manager = manager_factory(
        config=OpenVikingMemoryConfig(api_key="test-key"),
    )
    client = client_factory()
    identity = OpenVikingIdentity("account", "user")
    client.resolve_identity.side_effect = [
        OpenVikingServiceError("Temporarily offline"),
        identity,
    ]
    client.search_context.return_value = {"rendered": "Prefers tea."}
    monkeypatch.setattr(
        manager_module,
        "OpenVikingClient",
        Mock(return_value=client),
    )

    try:
        await manager.start()
        client.close.assert_not_awaited()
        if operation == "recall":
            result = await manager.auto_memory_search(
                user_message("drink preference"),
                session_id="chat",
            )
            assert result is not None
            assert "Prefers tea." in result["text"]
            request = client.search_context.await_args.kwargs
            assert request["session_id"] == manager._map_session_id("chat")
        else:
            message = user_message("I prefer tea.")
            await manager.auto_memory([message], session_id="chat")
            client.add_messages.assert_awaited_once()
            session_id, payload = client.add_messages.await_args.args
            assert session_id == manager._map_session_id("chat")
            assert payload[0]["content"] == "I prefer tea."
            assert message.id in manager._persisted_msg_ids
        assert client.resolve_identity.await_count == 2
        assert manager._identity == identity
    finally:
        await manager.close()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_installation_file_io_runs_off_event_loop(
    monkeypatch,
    manager_factory,
    client_factory,
):
    manager = manager_factory(
        config=OpenVikingMemoryConfig(api_key="test-key"),
    )
    client = client_factory()
    original = manager_module.get_or_create_installation_id
    threads = []
    loop_thread = threading.get_ident()

    def create_id(host_working_dir):
        threads.append(threading.get_ident())
        return original(host_working_dir)

    monkeypatch.setattr(
        manager_module,
        "get_or_create_installation_id",
        create_id,
    )
    monkeypatch.setattr(
        manager_module,
        "OpenVikingClient",
        Mock(return_value=client),
    )
    try:
        await manager.start()
        assert len(threads) == 1
        assert threads[0] != loop_thread
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_close_failure_is_reported_with_redacted_key(
    caplog,
    manager_factory,
    client_factory,
    attach_client,
):
    key = "close-secret-key"
    manager = manager_factory()
    client = client_factory(api_key=key)
    client.close.side_effect = RuntimeError(f"Closing failed with {key}")
    attach_client(manager, client)

    try:
        assert await manager.close() is False
        client.close.assert_awaited_once()
        assert key not in caplog.text
        assert "<redacted>" in caplog.text
        assert not manager.list_memory_tools()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_restart_with_custom_workspace_preserves_host_session_identity(
    tmp_path,
    monkeypatch,
    manager_factory,
    client_factory,
):
    first = manager_factory(
        config=OpenVikingMemoryConfig(api_key="test-key"),
    )
    second = manager_factory(
        config=OpenVikingMemoryConfig(api_key="test-key"),
    )
    second.context = replace(
        second.context,
        working_dir=tmp_path / "external" / "custom-workspace",
    )
    monkeypatch.setattr(
        manager_module,
        "OpenVikingClient",
        Mock(side_effect=[client_factory(), client_factory()]),
    )

    try:
        await first.start()
        session_id = first._map_session_id("chat")
        await first.close()
        await second.start()
        assert second._map_session_id("chat") == session_id
        assert first._installation_id == second._installation_id
        marker = (
            tmp_path
            / "host"
            / "plugin-state"
            / "memory-openviking"
            / "installation-id"
        )
        assert marker.read_text(encoding="utf-8") == second._installation_id
        assert not (tmp_path / "external" / "plugin-state").exists()
    finally:
        await asyncio.gather(first.close(), second.close())


@pytest.mark.parametrize(
    "dimension",
    ["account", "user", "installation", "agent", "chat"],
)
def test_session_mapping_separates_identity_dimensions(
    dimension,
    manager_factory,
):
    first = manager_factory()
    second = manager_factory()
    for manager in (first, second):
        manager._identity = OpenVikingIdentity("account", "user")
        manager._installation_id = "a" * 32
    chat = "chat"
    if dimension == "account":
        second._identity = OpenVikingIdentity("other-account", "user")
    elif dimension == "user":
        second._identity = OpenVikingIdentity("account", "other-user")
    elif dimension == "installation":
        second._installation_id = "b" * 32
    elif dimension == "agent":
        second.agent_id = "other-agent"
    else:
        chat = "other-chat"

    original = first._map_session_id("chat")
    assert first._map_session_id("chat") == original
    assert second._map_session_id(chat) != original


@pytest.mark.asyncio
async def test_disabled_auto_recall_preserves_explicit_search(
    manager_factory,
    client_factory,
    attach_client,
    user_message,
):
    manager = manager_factory(
        config=OpenVikingMemoryConfig(
            auto_memory_search_config={"enabled": False},
        ),
    )
    client = client_factory()
    attach_client(manager, client)
    try:
        assert (
            await manager.auto_memory_search(
                user_message("tea"),
                session_id="chat",
            )
            is None
        )
        client.search_context.assert_not_awaited()
        result = await manager.memory_search("tea")
        assert result.state == ToolResultState.SUCCESS
        client.search_memories.assert_awaited_once_with(
            query="tea",
            max_results=5,
        )
    finally:
        await manager.close()
