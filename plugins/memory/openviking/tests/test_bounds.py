# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Search-output budgets and bounded completed-state cache behavior."""

import pytest
from agentscope.message import ToolResultState

from plugins.memory.openviking.backend import manager as manager_module
from plugins.memory.openviking.backend.client import OpenVikingServiceError
from plugins.memory.openviking.backend.config import OpenVikingMemoryConfig
from plugins.memory.openviking.backend.prompts import (
    OPENVIKING_UNTRUSTED_HISTORY_NOTICE,
)

from .test_manager import _assistant, _attach, _client, _manager, _user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result_count", "large_field"),
    [
        (1, "abstract"),
        (1, "content"),
        (1, "text"),
        (1, "uri"),
        (20, "abstract"),
    ],
)
async def test_explicit_search_clips_large_remote_fields(
    tmp_path,
    result_count,
    large_field,
):
    manager = _manager(tmp_path)
    client = _client()
    results = []
    for index in range(result_count):
        item = {
            "uri": f"viking://user/memories/device-{index}.md",
            "score": 0.9,
        }
        item[large_field] = "设备维护记录🧭" * 10000
        results.append(item)
    client.search_memories.return_value = results
    _attach(manager, client)

    try:
        result = await manager.memory_search(
            "青鹭探针的编号",
            max_results=result_count,
        )
        text = result.content[0].text
        prefix = OPENVIKING_UNTRUSTED_HISTORY_NOTICE + "\n\n"

        assert result.state is ToolResultState.SUCCESS
        assert text.startswith(prefix)
        assert (
            len(text.encode("utf-8"))
            <= manager_module.MAX_MEMORY_SEARCH_OUTPUT_BYTES
        )
        assert manager_module.TRUNCATION_MARKER in text
        assert "\ufffd" not in text
        if result_count == 1:
            assert (
                len(text[len(prefix) :].encode("utf-8"))
                <= manager_module.MAX_MEMORY_SEARCH_ITEM_BYTES
            )
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("body_field", ["abstract", "content", "text"])
async def test_explicit_search_preserves_short_results(tmp_path, body_field):
    manager = _manager(tmp_path)
    client = _client()
    uri = "viking://user/memories/device.md"
    body = "青鹭探针编号 QL-927 🧭"
    client.search_memories.return_value = [
        {"uri": uri, body_field: body, "score": 0.9},
    ]
    _attach(manager, client)

    try:
        result = await manager.memory_search("设备编号")

        assert result.state is ToolResultState.SUCCESS
        assert result.content[0].text == (
            OPENVIKING_UNTRUSTED_HISTORY_NOTICE
            + f"\n\n[1] {uri}, score=0.900\n{body}"
        )
        assert manager_module.TRUNCATION_MARKER not in result.content[0].text
    finally:
        await manager.close()


def test_completed_message_cache_evicts_oldest_record(tmp_path, monkeypatch):
    monkeypatch.setattr(manager_module, "MAX_PERSISTED_MESSAGE_IDS", 3)
    manager = _manager(tmp_path)

    manager._remember_persisted_message_ids(["first", "second", "third"])
    manager._remember_persisted_message_ids(["second"])
    manager._remember_persisted_message_ids(["fourth"])

    assert list(manager._persisted_msg_ids) == ["third", "second", "fourth"]
    assert all(value is None for value in manager._persisted_msg_ids.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_policy", ["auto", "every_turn"])
async def test_completed_message_deduplication_has_a_bounded_window(
    tmp_path,
    monkeypatch,
    commit_policy,
):
    """Retained IDs suppress replay; evicted IDs no longer guarantee dedup."""
    monkeypatch.setattr(manager_module, "MAX_PERSISTED_MESSAGE_IDS", 2)
    manager = _manager(
        tmp_path,
        config=OpenVikingMemoryConfig(commit_policy=commit_policy),
    )
    client = _client()
    _attach(manager, client)
    first, second, third = [
        _user(text) for text in ("first", "second", "third")
    ]

    try:
        await manager.auto_memory([first], session_id="chat-1")
        await manager.auto_memory([second], session_id="chat-1")
        await manager.auto_memory([second], session_id="chat-1")
        assert client.add_messages.await_count == 2

        await manager.auto_memory([third], session_id="chat-1")
        assert len(manager._persisted_msg_ids) == 2
        assert first.id not in manager._persisted_msg_ids
        assert second.id in manager._persisted_msg_ids
        assert third.id in manager._persisted_msg_ids

        # A replay outside the retained window can append again by design.
        await manager.auto_memory([first], session_id="chat-1")
        assert client.add_messages.await_count == 4
        assert client.add_messages.await_args_list[0].args == (
            client.add_messages.await_args_list[-1].args
        )
        assert len(manager._persisted_msg_ids) == 2
        assert not manager._pending_commit_msg_ids
        assert client.commit.await_count == (
            4 if commit_policy == "every_turn" else 0
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_ready_session_lru_rechecks_evicted_sessions(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(manager_module, "MAX_READY_SESSIONS", 2)
    manager = _manager(tmp_path)
    client = _client()
    _attach(manager, client)

    try:
        for session_id in ("session-a", "session-b", "session-a", "session-c"):
            await manager._ensure_session(session_id)

        assert list(manager._ready_sessions) == ["session-a", "session-c"]
        assert client.ensure_session.await_count == 3

        # Eviction only removes a local optimization, not a remote session.
        await manager._ensure_session("session-b")
        assert list(manager._ready_sessions) == ["session-c", "session-b"]
        assert [
            call.args[0] for call in client.ensure_session.await_args_list
        ] == ["session-a", "session-b", "session-c", "session-b"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_cache_eviction_keeps_pending_commit_progress(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(manager_module, "MAX_READY_SESSIONS", 1)
    monkeypatch.setattr(manager_module, "MAX_PERSISTED_MESSAGE_IDS", 2)
    manager = _manager(
        tmp_path,
        config=OpenVikingMemoryConfig(commit_policy="every_turn"),
    )
    client = _client()
    _attach(manager, client)
    messages = [_user("pending request"), _assistant("pending reply")]
    pending_session_id = manager._map_session_id("pending-chat")
    pending_ids = {message.id for message in messages}
    client.commit.side_effect = OpenVikingServiceError("temporary failure")

    try:
        # One failed attempt establishes real, confirmed append progress.
        with pytest.raises(OpenVikingServiceError):
            await manager._persist_turn_once(
                messages,
                session_id="pending-chat",
            )
        assert manager._pending_commit_msg_ids == {
            pending_session_id: pending_ids,
        }

        client.commit.side_effect = None
        for index in range(3):
            await manager.auto_memory(
                [_user(f"other request {index}"), _assistant("other reply")],
                session_id=f"other-chat-{index}",
            )

        assert pending_session_id not in manager._ready_sessions
        assert len(manager._ready_sessions) == 1
        assert len(manager._persisted_msg_ids) == 2
        assert manager._pending_commit_msg_ids == {
            pending_session_id: pending_ids,
        }

        append_count = client.add_messages.await_count
        commit_count = client.commit.await_count
        ensure_count = client.ensure_session.await_count
        await manager.auto_memory(messages, session_id="pending-chat")

        # Rechecking an evicted session must not re-append a pending batch.
        assert client.ensure_session.await_count == ensure_count + 1
        assert client.add_messages.await_count == append_count
        assert client.commit.await_count == commit_count + 1
        assert pending_ids == set(manager._persisted_msg_ids)
        assert not manager._pending_commit_msg_ids
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_policy", ["auto", "every_turn"])
async def test_empty_turn_does_not_leave_pending_session_entries(
    tmp_path,
    commit_policy,
):
    manager = _manager(
        tmp_path,
        config=OpenVikingMemoryConfig(commit_policy=commit_policy),
    )
    client = _client()
    _attach(manager, client)

    try:
        for index in range(3):
            await manager.auto_memory([], session_id=f"empty-chat-{index}")

        assert not manager._pending_commit_msg_ids
        assert not manager._persisted_msg_ids
        client.add_messages.assert_not_awaited()
        client.commit.assert_not_awaited()
    finally:
        await manager.close()
