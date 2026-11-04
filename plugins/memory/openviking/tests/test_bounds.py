# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Search-output budgets and bounded completed-state cache behavior."""

from dataclasses import replace
from math import ceil

import pytest
from agentscope.message import ToolResultState

from plugins.memory.openviking.backend import manager as manager_module
from plugins.memory.openviking.backend.client import OpenVikingServiceError
from plugins.memory.openviking.backend.config import OpenVikingMemoryConfig
from plugins.memory.openviking.backend.prompts import (
    OPENVIKING_UNTRUSTED_HISTORY_NOTICE,
)


@pytest.mark.parametrize(
    ("text", "max_bytes"),
    [
        ("记" * 100, -1),
        ("记" * 100, 0),
        ("记" * 100, len(manager_module.TRUNCATION_MARKER.encode("utf-8")) - 1),
        ("记" * 100, len(manager_module.TRUNCATION_MARKER.encode("utf-8"))),
        ("记" * 100, len(manager_module.TRUNCATION_MARKER.encode("utf-8")) + 2),
        (
            " \t\n" + "记" * 100,
            len(manager_module.TRUNCATION_MARKER.encode("utf-8")) + 3,
        ),
    ],
)
def test_clip_utf8_returns_empty_when_no_nonblank_body_fits(text, max_bytes):
    assert (
        manager_module.OpenVikingMemoryManager._clip_utf8(text, max_bytes)
        == ""
    )


@pytest.mark.parametrize("body", ["é", "记", "🧭"])
def test_clip_utf8_preserves_complete_body_at_truncation_boundary(body):
    marker = manager_module.TRUNCATION_MARKER
    max_bytes = len((body + marker).encode("utf-8"))
    result = manager_module.OpenVikingMemoryManager._clip_utf8(
        body * 100,
        max_bytes,
    )

    assert result == body + marker
    assert len(result.encode("utf-8")) <= max_bytes


def test_clip_utf8_preserves_untruncated_text():
    text = " 记忆🧭 "

    assert (
        manager_module.OpenVikingMemoryManager._clip_utf8(
            text,
            len(text.encode("utf-8")),
        )
        == text
    )


def _message_bytes(message):
    """Measure the actual synthetic content, including tool-result output."""
    return sum(
        len(str(getattr(block, attr, "")).encode("utf-8"))
        for block in message.content
        for attr in ("text", "thinking", "name", "input")
    ) + sum(
        len(output.text.encode("utf-8"))
        for block in message.content
        for output in getattr(block, "output", [])
    )


def _recall_overhead(manager, *, query="hi", max_results=3):
    """Measure host-authored content without using the budget helper."""
    message = manager._build_auto_memory_search_msg(
        query=query,
        max_results=max_results,
        text="",
        estimate_divisor=manager.context.token_estimate_divisor,
    )
    prefix = OPENVIKING_UNTRUSTED_HISTORY_NOTICE + "\n\n"
    return _message_bytes(message) + len(prefix.encode("utf-8"))


def _assert_bounded_recall(result, manager, source_body):
    """Require actual recall and the intact notice within the whole budget."""
    assert result is not None
    text = result["text"]
    prefix = OPENVIKING_UNTRUSTED_HISTORY_NOTICE + "\n\n"
    assert text.startswith(prefix)
    recalled = text[len(prefix) :].removesuffix(
        manager_module.TRUNCATION_MARKER,
    )
    assert recalled.strip()
    assert source_body.startswith(recalled)
    assert "\ufffd" not in text
    assert _message_bytes(result["msg"][-1]) <= int(
        manager._config.retrieval_token_budget
        * manager.context.token_estimate_divisor,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "budget_case",
    [64, 96, 128, "below_minimum", "minimum", "above_minimum"],
)
async def test_auto_recall_reserves_overhead_before_request(
    budget_case,
    manager_factory,
    client_factory,
    user_message,
):
    manager = manager_factory()
    divisor = manager.context.token_estimate_divisor
    overhead = _recall_overhead(manager)
    minimum_budget = ceil(
        overhead / divisor + manager_module.MIN_CONTEXT_TOKEN_BUDGET,
    )
    offsets = {"below_minimum": -1, "minimum": 0, "above_minimum": 1}
    budget = (
        budget_case
        if isinstance(budget_case, int)
        else minimum_budget + offsets[budget_case]
    )
    manager._config.retrieval_token_budget = budget
    client = client_factory()
    body = "Launch on Friday."
    client.search_context.return_value = {"digest": body}
    manager._client = client

    result = await manager.auto_memory_search(
        user_message("hi"),
        session_id="chat-1",
    )

    remaining_bytes = int(budget * divisor) - overhead
    if remaining_bytes < manager_module.MIN_CONTEXT_TOKEN_BUDGET * divisor:
        assert result is None
        client.search_context.assert_not_awaited()
        client.resolve_identity.assert_not_awaited()
    else:
        _assert_bounded_recall(result, manager, body)
        assert result["text"] == (
            OPENVIKING_UNTRUSTED_HISTORY_NOTICE + "\n\n" + body
        )
        client.resolve_identity.assert_awaited_once()
        client.search_context.assert_awaited_once()
        request = client.search_context.await_args.kwargs
        assert request["query"] == "hi"
        assert request["session_id"] == manager._map_session_id("chat-1")
        assert request["max_results"] == 3
        assert (
            manager_module.MIN_CONTEXT_TOKEN_BUDGET
            <= request["token_budget"]
            <= remaining_bytes / divisor
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "max_results", "divisor"),
    [("hi", 3, 4.0), ("x" * 50, 3, 4.0), ("🧭" * 50, 20, 4.0), ("hi", 3, 2.0)],
)
async def test_auto_recall_request_budget_tracks_actual_message(
    query,
    max_results,
    divisor,
    manager_factory,
    client_factory,
    attach_client,
    user_message,
):
    manager = manager_factory(
        config=OpenVikingMemoryConfig(
            auto_memory_search_config={"max_results": max_results},
        ),
    )
    manager.context = replace(manager.context, token_estimate_divisor=divisor)
    client = client_factory()
    body = "Launch on Friday."
    client.search_context.return_value = {"digest": body}
    attach_client(manager, client)

    result = await manager.auto_memory_search(
        user_message(query),
        session_id="chat-1",
    )

    _assert_bounded_recall(result, manager, body)
    client.search_context.assert_awaited_once()
    request = client.search_context.await_args.kwargs
    assert request["query"] == query
    assert request["session_id"] == manager._map_session_id("chat-1")
    assert request["max_results"] == max_results
    remote_budget = request["token_budget"]
    assert remote_budget >= manager_module.MIN_CONTEXT_TOKEN_BUDGET
    overhead = _recall_overhead(manager, query=query, max_results=max_results)
    max_bytes = int(manager._config.retrieval_token_budget * divisor)
    # The remote budget fits the actual wrapper and notice, and leaves less
    # than one whole token unused. No expected prompt length is hard-coded.
    assert overhead + remote_budget * divisor <= max_bytes
    assert overhead + (remote_budget + 1) * divisor > max_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_result",
    [{"digest": ""}, {"rendered": " \n\t "}],
)
async def test_auto_recall_does_not_inject_empty_remote_results(
    remote_result,
    manager_factory,
    client_factory,
    attach_client,
    user_message,
):
    manager = manager_factory()
    client = client_factory()
    client.search_context.return_value = remote_result
    attach_client(manager, client)

    result = await manager.auto_memory_search(
        user_message("hi"),
        session_id="chat-1",
    )

    assert result is None
    client.search_context.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["digest", "rendered"])
@pytest.mark.parametrize("body", ["é" * 1000, "记忆🧭" * 1000])
async def test_auto_recall_bounds_oversized_body_without_clipping_notice(
    field,
    body,
    manager_factory,
    client_factory,
    attach_client,
    user_message,
):
    manager = manager_factory()
    divisor = manager.context.token_estimate_divisor
    manager._config.retrieval_token_budget = ceil(
        _recall_overhead(manager) / divisor
        + manager_module.MIN_CONTEXT_TOKEN_BUDGET,
    )
    client = client_factory()
    client.search_context.return_value = {field: body}
    attach_client(manager, client)

    result = await manager.auto_memory_search(
        user_message("hi"),
        session_id="chat-1",
    )

    _assert_bounded_recall(result, manager, body)
    assert result["text"].endswith(manager_module.TRUNCATION_MARKER)
    client.search_context.assert_awaited_once_with(
        query="hi",
        session_id=manager._map_session_id("chat-1"),
        max_results=3,
        token_budget=manager_module.MIN_CONTEXT_TOKEN_BUDGET,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body_space", "has_body"),
    [
        ("minimum", False),
        ("marker", False),
        ("partial_character", False),
        ("one_character", True),
    ],
)
async def test_auto_recall_never_injects_a_marker_without_body(
    body_space,
    has_body,
    manager_factory,
    client_factory,
    attach_client,
    user_message,
):
    manager = manager_factory()
    divisor = 0.5
    manager.context = replace(manager.context, token_estimate_divisor=divisor)
    marker_bytes = len(manager_module.TRUNCATION_MARKER.encode("utf-8"))
    character_bytes = len("记".encode("utf-8"))
    body_bytes = {
        "minimum": int(manager_module.MIN_CONTEXT_TOKEN_BUDGET * divisor),
        "marker": marker_bytes,
        "partial_character": marker_bytes + character_bytes - 1,
        "one_character": marker_bytes + character_bytes,
    }[body_space]
    manager._config.retrieval_token_budget = ceil(
        (_recall_overhead(manager) + body_bytes) / divisor,
    )
    client = client_factory()
    body = "记" * 100
    client.search_context.return_value = {"digest": body}
    attach_client(manager, client)

    result = await manager.auto_memory_search(
        user_message("hi"),
        session_id="chat-1",
    )

    client.search_context.assert_awaited_once()
    if has_body:
        _assert_bounded_recall(result, manager, body)
        assert result["text"] == (
            OPENVIKING_UNTRUSTED_HISTORY_NOTICE
            + "\n\n记"
            + manager_module.TRUNCATION_MARKER
        )
    else:
        assert result is None


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
    result_count,
    large_field,
    manager_factory,
    client_factory,
    attach_client,
):
    manager = manager_factory()
    client = client_factory()
    results = []
    for index in range(result_count):
        item = {
            "uri": f"viking://user/memories/device-{index}.md",
            "score": 0.9,
        }
        item[large_field] = "设备维护记录🧭" * 10000
        results.append(item)
    client.search_memories.return_value = results
    attach_client(manager, client)

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


@pytest.mark.asyncio
@pytest.mark.parametrize("body_field", ["abstract", "content", "text"])
async def test_explicit_search_preserves_short_results(
    body_field,
    manager_factory,
    client_factory,
    attach_client,
):
    manager = manager_factory()
    client = client_factory()
    uri = "viking://user/memories/device.md"
    body = "青鹭探针编号 QL-927 🧭"
    client.search_memories.return_value = [
        {"uri": uri, body_field: body, "score": 0.9},
    ]
    attach_client(manager, client)

    result = await manager.memory_search("设备编号")

    assert result.state is ToolResultState.SUCCESS
    assert result.content[0].text == (
        OPENVIKING_UNTRUSTED_HISTORY_NOTICE
        + f"\n\n[1] {uri}, score=0.900\n{body}"
    )
    assert manager_module.TRUNCATION_MARKER not in result.content[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body_budget",
    [
        -1,
        0,
        len(manager_module.TRUNCATION_MARKER.encode("utf-8")) - 1,
        len(manager_module.TRUNCATION_MARKER.encode("utf-8")),
    ],
)
async def test_explicit_search_rejects_reduced_budget_without_recalled_body(
    body_budget,
    monkeypatch,
    manager_factory,
    client_factory,
    attach_client,
):
    prefix = OPENVIKING_UNTRUSTED_HISTORY_NOTICE + "\n\n"
    monkeypatch.setattr(
        manager_module,
        "MAX_MEMORY_SEARCH_OUTPUT_BYTES",
        len(prefix.encode("utf-8")) + body_budget,
    )
    manager = manager_factory()
    client = client_factory()
    client.search_memories.return_value = [{"uri": "v", "abstract": "记" * 100}]
    attach_client(manager, client)

    result = await manager.memory_search("设备编号")

    assert result.state is ToolResultState.ERROR
    assert "budget is too small" in result.content[0].text
    assert prefix not in result.content[0].text
    assert manager_module.TRUNCATION_MARKER not in result.content[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("needs_clipping", [False, True])
async def test_explicit_search_preserves_body_with_reduced_output_limit(
    needs_clipping,
    monkeypatch,
    manager_factory,
    client_factory,
    attach_client,
):
    prefix = OPENVIKING_UNTRUSTED_HISTORY_NOTICE + "\n\n"
    expected_body = "[1] v\n记"
    if needs_clipping:
        expected_body += manager_module.TRUNCATION_MARKER
    output_limit = len((prefix + expected_body).encode("utf-8"))
    monkeypatch.setattr(
        manager_module,
        "MAX_MEMORY_SEARCH_OUTPUT_BYTES",
        output_limit,
    )
    manager = manager_factory()
    client = client_factory()
    client.search_memories.return_value = [
        {"uri": "v", "abstract": "记" * (100 if needs_clipping else 1)},
    ]
    attach_client(manager, client)

    result = await manager.memory_search("设备编号")

    assert result.state is ToolResultState.SUCCESS
    assert result.content[0].text == prefix + expected_body
    assert len(result.content[0].text.encode("utf-8")) <= output_limit


def test_completed_message_cache_evicts_oldest_record(
    monkeypatch,
    manager_factory,
):
    monkeypatch.setattr(manager_module, "MAX_PERSISTED_MESSAGE_IDS", 3)
    manager = manager_factory()

    manager._remember_persisted_message_ids(["first", "second", "third"])
    manager._remember_persisted_message_ids(["second"])
    manager._remember_persisted_message_ids(["fourth"])

    assert list(manager._persisted_msg_ids) == ["third", "second", "fourth"]
    assert all(value is None for value in manager._persisted_msg_ids.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_policy", ["auto", "every_turn"])
async def test_completed_message_deduplication_has_a_bounded_window(
    monkeypatch,
    commit_policy,
    manager_factory,
    client_factory,
    attach_client,
    user_message,
):
    """Retained IDs suppress replay; evicted IDs no longer guarantee dedup."""
    monkeypatch.setattr(manager_module, "MAX_PERSISTED_MESSAGE_IDS", 2)
    manager = manager_factory(
        config=OpenVikingMemoryConfig(commit_policy=commit_policy),
    )
    client = client_factory()
    attach_client(manager, client)
    first, second, third = [
        user_message(text) for text in ("first", "second", "third")
    ]

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


@pytest.mark.asyncio
async def test_ready_session_lru_rechecks_evicted_sessions(
    monkeypatch,
    manager_factory,
    client_factory,
    attach_client,
):
    monkeypatch.setattr(manager_module, "MAX_READY_SESSIONS", 2)
    manager = manager_factory()
    client = client_factory()
    attach_client(manager, client)

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


@pytest.mark.asyncio
async def test_cache_eviction_keeps_pending_commit_progress(
    monkeypatch,
    manager_factory,
    client_factory,
    attach_client,
    user_message,
    assistant_message,
):
    monkeypatch.setattr(manager_module, "MAX_READY_SESSIONS", 1)
    monkeypatch.setattr(manager_module, "MAX_PERSISTED_MESSAGE_IDS", 2)
    manager = manager_factory(
        config=OpenVikingMemoryConfig(commit_policy="every_turn"),
    )
    client = client_factory()
    attach_client(manager, client)
    messages = [
        user_message("pending request"),
        assistant_message("pending reply"),
    ]
    pending_session_id = manager._map_session_id("pending-chat")
    pending_ids = {message.id for message in messages}
    client.commit.side_effect = OpenVikingServiceError("temporary failure")

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
            [
                user_message(f"other request {index}"),
                assistant_message("other reply"),
            ],
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


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_policy", ["auto", "every_turn"])
async def test_empty_turn_does_not_leave_pending_session_entries(
    commit_policy,
    manager_factory,
    client_factory,
    attach_client,
):
    manager = manager_factory(
        config=OpenVikingMemoryConfig(commit_policy=commit_policy),
    )
    client = client_factory()
    attach_client(manager, client)

    for index in range(3):
        await manager.auto_memory([], session_id=f"empty-chat-{index}")

    assert not manager._pending_commit_msg_ids
    assert not manager._persisted_msg_ids
    client.add_messages.assert_not_awaited()
    client.commit.assert_not_awaited()
