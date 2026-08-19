# -*- coding: utf-8 -*-
"""Tests for MemoryMiddleware automation-source skip logic."""

# pylint: disable=protected-access
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import (
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
)
from agentscope.state import AgentState

from qwenpaw.agents.middlewares import (
    MemoryMiddleware,
    auto_memory_turn_state,
)
from qwenpaw.constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    LOOP_CONTINUATION_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(*, source: str | None = None):
    """Build a minimal fake agent with optional request_context source."""
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.state = SimpleNamespace(
        context=[],
        summary=None,
        session_id="session-1",
        reply_id="reply-1",
        middle_context={},
    )
    agent._context_manager = None
    if source is not None:
        agent._request_context = {"source": source, "session_id": "session-1"}
    else:
        agent._request_context = {"session_id": "session-1"}
    return agent


def _user_msg(text: str = "hello", *, msg_id: str = "turn-1") -> Msg:
    msg = Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
        metadata={
            QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG,
        },
    )
    msg.id = msg_id
    return msg


def _make_memory_manager(*, interval: int = 1):
    mm = MagicMock()
    mm.agent_id = "test-agent"
    mm.get_auto_memory_interval.return_value = interval
    mm.auto_memory = AsyncMock()
    mm.auto_memory_search = AsyncMock(return_value=None)
    mm.get_memory_prompt.return_value = ""
    return mm


def _turn_state(agent):
    return auto_memory_turn_state(agent.state)


@pytest.mark.asyncio
async def test_system_prompt_getter_runs_in_worker_thread():
    """Memory prompt configuration must not load on the event loop."""
    event_loop_thread = threading.get_ident()
    getter_threads = []
    mm = _make_memory_manager()

    def get_memory_prompt():
        getter_threads.append(threading.get_ident())
        return "Memory guidance"

    mm.get_memory_prompt.side_effect = get_memory_prompt

    prompt = await MemoryMiddleware(memory_manager=mm).on_system_prompt(
        _make_agent(source="user"),
        "System prompt",
    )

    assert prompt == "System prompt\n\nMemory guidance"
    assert getter_threads[0] != event_loop_thread


# ---------------------------------------------------------------------------
# _is_automation_request unit tests
# ---------------------------------------------------------------------------


class TestIsAutomationRequest:
    def test_cron_source(self):
        agent = _make_agent(source="cron")
        assert MemoryMiddleware._is_automation_request(agent) is True

    def test_heartbeat_source(self):
        agent = _make_agent(source="heartbeat")
        assert MemoryMiddleware._is_automation_request(agent) is True

    def test_cron_uppercase(self):
        agent = _make_agent(source="CRON")
        assert MemoryMiddleware._is_automation_request(agent) is True

    def test_heartbeat_mixed_case(self):
        agent = _make_agent(source="HeartBeat")
        assert MemoryMiddleware._is_automation_request(agent) is True

    def test_user_source(self):
        agent = _make_agent(source="user")
        assert MemoryMiddleware._is_automation_request(agent) is False

    def test_empty_source(self):
        agent = _make_agent(source="")
        assert MemoryMiddleware._is_automation_request(agent) is False

    def test_no_source_key(self):
        agent = _make_agent(source=None)
        assert MemoryMiddleware._is_automation_request(agent) is False

    def test_no_request_context_attr(self):
        agent = MagicMock(spec=[])
        assert MemoryMiddleware._is_automation_request(agent) is False

    def test_request_context_not_dict(self):
        agent = MagicMock()
        agent._request_context = "not-a-dict"
        assert MemoryMiddleware._is_automation_request(agent) is False


# ---------------------------------------------------------------------------
# on_model_call integration tests
# ---------------------------------------------------------------------------


class TestOnModelCallAutomationSkip:
    @pytest.mark.asyncio
    async def test_cron_skips_auto_memory_search(self):
        """Automation requests must skip auto_memory_search entirely."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="cron")
        agent.state.context = [_user_msg()]

        next_handler = AsyncMock(return_value="model_result")
        result = await mw.on_model_call(agent, {"messages": []}, next_handler)

        mm.auto_memory_search.assert_not_awaited()
        next_handler.assert_awaited_once()
        assert result == "model_result"

    @pytest.mark.asyncio
    async def test_user_calls_auto_memory_search(self):
        """Normal user requests should trigger auto_memory_search."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        agent.state.context = [_user_msg()]

        next_handler = AsyncMock(return_value="model_result")
        await mw.on_model_call(agent, {"messages": []}, next_handler)

        mm.auto_memory_search.assert_awaited_once()
        assert mm.auto_memory_search.await_args.args[0].id == "turn-1"

    @pytest.mark.asyncio
    async def test_search_result_only_updates_current_model_input(self):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        query = _user_msg()
        memory_msg = Msg(
            name="memory_search",
            role="assistant",
            content=[TextBlock(text="remembered fact")],
        )
        agent.state.context = [query]
        mm.auto_memory_search.return_value = {"msg": [query, memory_msg]}
        input_kwargs = {"messages": [query]}
        next_handler = AsyncMock(return_value="model_result")

        with patch.object(
            MemoryMiddleware,
            "_extract_memory_messages",
            return_value=[memory_msg],
        ):
            await mw.on_model_call(agent, input_kwargs, next_handler)

        assert input_kwargs["messages"] == [query, memory_msg]
        assert agent.state.context == [query]

    @pytest.mark.asyncio
    async def test_search_result_survives_follow_up_model_call(self):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        query = _user_msg()
        memory_msg = Msg(
            name="memory_search",
            role="assistant",
            content=[
                ToolCallBlock(
                    id="search-1",
                    name="memory_search",
                    input='{"query": "hello"}',
                    state=ToolCallState.FINISHED,
                ),
                ToolResultBlock(
                    id="search-1",
                    name="memory_search",
                    output=[TextBlock(text="remembered fact")],
                    state=ToolResultState.SUCCESS,
                ),
            ],
        )
        agent.state.context = [query]
        mm.auto_memory_search.return_value = {"msg": [query, memory_msg]}
        first_input = {"messages": [query]}
        tool_reply = Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(text="continued reasoning")],
        )
        second_input = {"messages": [query, tool_reply]}

        await mw.on_model_call(
            agent,
            first_input,
            AsyncMock(return_value="first"),
        )
        await mw.on_model_call(
            agent,
            second_input,
            AsyncMock(return_value="second"),
        )

        mm.auto_memory_search.assert_awaited_once()
        assert first_input["messages"][-1].id == memory_msg.id
        assert [msg.id for msg in second_input["messages"]] == [
            query.id,
            memory_msg.id,
            tool_reply.id,
        ]
        assert agent.state.context == [query]

    @pytest.mark.asyncio
    async def test_new_turn_replaces_search_cache(self):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        first = _user_msg("first", msg_id="turn-1")
        second = _user_msg("second", msg_id="turn-2")
        evidence = Msg(
            name="memory_search",
            role="assistant",
            content=[TextBlock(text="old evidence")],
        )
        mm.auto_memory_search.side_effect = [
            {"msg": [first, evidence]},
            None,
        ]

        agent.state.context = [first]
        with patch.object(
            MemoryMiddleware,
            "_extract_memory_messages",
            side_effect=[[evidence], []],
        ):
            await mw.on_model_call(
                agent,
                {"messages": [first]},
                AsyncMock(return_value="first"),
            )
            agent.state.context.extend([second])
            second_input = {"messages": [first, second]}
            await mw.on_model_call(
                agent,
                second_input,
                AsyncMock(return_value="second"),
            )

        assert mm.auto_memory_search.await_count == 2
        assert evidence not in second_input["messages"]

    @pytest.mark.asyncio
    async def test_untagged_user_message_does_not_search(self):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        agent.state.context = [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="internal prompt")],
            ),
        ]

        await mw.on_model_call(
            agent,
            {"messages": []},
            AsyncMock(return_value="model_result"),
        )

        mm.auto_memory_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_loop_continuation_does_not_retrigger_search(self):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        real_query = _user_msg("real query")
        agent.state.context = [real_query]
        next_handler = AsyncMock(return_value="model_result")

        await mw.on_model_call(agent, {"messages": []}, next_handler)
        continuation = Msg(
            name="user",
            role="user",
            content=[
                TextBlock(text="[WARNING] Repetitive pattern detected."),
            ],
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: LOOP_CONTINUATION_MESSAGE_TAG,
            },
        )
        agent.state.context.append(continuation)
        await mw.on_model_call(agent, {"messages": []}, next_handler)

        mm.auto_memory_search.assert_awaited_once()
        assert mm.auto_memory_search.await_args.args[0] is real_query

    @pytest.mark.asyncio
    async def test_model_call_search_state_survives_middleware_rebuild(self):
        """A rebuilt middleware must not search twice for the same turn."""
        mm = _make_memory_manager()
        agent = _make_agent(source="user")
        agent.state.context = [_user_msg(msg_id="turn-1")]

        next_handler = AsyncMock(return_value="model_result")
        await MemoryMiddleware(memory_manager=mm).on_model_call(
            agent,
            {"messages": []},
            next_handler,
        )
        await MemoryMiddleware(memory_manager=mm).on_model_call(
            agent,
            {"messages": []},
            next_handler,
        )

        mm.auto_memory_search.assert_awaited_once()
        assert _turn_state(agent)["search"]["turn_marker"] == "turn-1"

    @pytest.mark.asyncio
    async def test_search_state_survives_agent_state_round_trip(self):
        mm = _make_memory_manager()
        agent = _make_agent(source="user")
        agent.state = AgentState(session_id="session-1")
        agent.state.context = [_user_msg(msg_id="turn-1")]

        await MemoryMiddleware(memory_manager=mm).on_model_call(
            agent,
            {"messages": []},
            AsyncMock(return_value="model_result"),
        )
        agent.state = AgentState.model_validate(
            agent.state.model_dump(mode="json"),
        )
        await MemoryMiddleware(memory_manager=mm).on_model_call(
            agent,
            {"messages": []},
            AsyncMock(return_value="model_result"),
        )

        mm.auto_memory_search.assert_awaited_once()
        assert _turn_state(agent)["search"]["turn_marker"] == "turn-1"


# ---------------------------------------------------------------------------
# on_reply integration tests
# ---------------------------------------------------------------------------


class TestOnReplyAutomationSkip:
    @pytest.mark.asyncio
    async def test_cron_skips_marker_tracking(self):
        """Automation requests must not append to pending markers."""
        mm = _make_memory_manager(interval=1)
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="cron")
        agent.state.context = [_user_msg()]

        async def _next(**_kwargs):
            yield "done"

        gen = mw.on_reply(agent, {}, _next)
        async for _ in gen:
            pass

        state = _turn_state(agent)
        assert not state["pending"]
        assert not state["seen"]
        mm.auto_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_triggers_auto_memory(self):
        """Normal user requests should trigger auto_memory as usual."""
        mm = _make_memory_manager(interval=1)
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        agent.state.context = [_user_msg()]

        async def _next(**_kwargs):
            yield "done"

        gen = mw.on_reply(agent, {}, _next)
        async for _ in gen:
            pass

        mm.auto_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_internal_user_message_is_excluded_from_memory(self):
        """Internal user-role controls must not enter auto-memory."""
        mm = _make_memory_manager(interval=1)
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        query = _user_msg("real query")
        reply = Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(text="reply")],
        )
        continuation = Msg(
            name="user",
            role="user",
            content=[TextBlock(text="[WARNING] Repetitive pattern detected.")],
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: LOOP_CONTINUATION_MESSAGE_TAG,
            },
        )
        final_reply = Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(text="done")],
        )
        agent.state.context = [query, reply, continuation, final_reply]

        async def _next(**_kwargs):
            yield "done"

        async for _ in mw.on_reply(agent, {}, _next):
            pass

        mm.auto_memory.assert_awaited_once()
        assert mm.auto_memory.await_args.args[0] == [query, reply, final_reply]

    @pytest.mark.asyncio
    async def test_interval_state_survives_middleware_rebuild(self):
        """A rebuilt middleware restores interval state from AgentState."""
        mm = _make_memory_manager(interval=2)

        async def _next(**_kwargs):
            yield "done"

        agent1 = _make_agent(source="user")
        agent1.state = AgentState(session_id="session-1")
        agent1.state.context = [_user_msg(msg_id="turn-1")]
        gen1 = MemoryMiddleware(memory_manager=mm).on_reply(
            agent1,
            {},
            _next,
        )
        async for _ in gen1:
            pass

        mm.auto_memory.assert_not_awaited()
        assert _turn_state(agent1)["pending"] == ["turn-1"]

        agent2 = _make_agent(source="user")
        agent2.state = AgentState.model_validate(
            agent1.state.model_dump(mode="json"),
        )
        agent2.state.context = [
            _user_msg(msg_id="turn-1"),
            Msg(
                name="agent",
                role="assistant",
                content=[TextBlock(text="reply 1")],
            ),
            _user_msg(msg_id="turn-2"),
            Msg(
                name="agent",
                role="assistant",
                content=[TextBlock(text="reply 2")],
            ),
        ]
        gen2 = MemoryMiddleware(memory_manager=mm).on_reply(
            agent2,
            {},
            _next,
        )
        async for _ in gen2:
            pass

        mm.auto_memory.assert_awaited_once()
        assert not _turn_state(agent2)["pending"]

    @pytest.mark.asyncio
    async def test_stale_markers_do_not_bypass_interval(self):
        mm = _make_memory_manager(interval=5)
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        _turn_state(agent)["pending"] = [f"missing-{idx}" for idx in range(5)]

        async def _next(**_kwargs):
            yield "done"

        async def reply(turn_number: int) -> None:
            agent.state.context.append(
                _user_msg(msg_id=f"turn-{turn_number}"),
            )
            async for _ in mw.on_reply(agent, {}, _next):
                pass

        for turn_number in range(1, 5):
            await reply(turn_number)
            mm.auto_memory.assert_not_awaited()

        await reply(5)
        mm.auto_memory.assert_awaited_once()
        assert [msg.id for msg in mm.auto_memory.await_args.args[0]] == [
            f"turn-{idx}" for idx in range(1, 6)
        ]
        assert not _turn_state(agent)["pending"]

        await reply(6)
        mm.auto_memory.assert_awaited_once()
        assert _turn_state(agent)["pending"] == ["turn-6"]


# ---------------------------------------------------------------------------
# on_compress_context integration tests
# ---------------------------------------------------------------------------


class TestOnCompressContextAutomationSkip:
    @pytest.mark.asyncio
    async def test_heartbeat_skips_memory_flush_but_compresses(self):
        """Automation skips memory flush; compression still runs."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="heartbeat")
        next_handler = AsyncMock()

        await mw.on_compress_context(agent, {}, next_handler)

        next_handler.assert_awaited_once_with()
        mm.auto_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_heartbeat_does_not_inspect_compression(self):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="heartbeat")
        next_handler = AsyncMock()

        with patch.object(
            MemoryMiddleware,
            "_did_compress_context",
        ) as inspect_result:
            await mw.on_compress_context(agent, {}, next_handler)
            inspect_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_automation_eviction_preserves_without_flushing_user_turn(
        self,
    ):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="heartbeat")
        agent.state.context = [_user_msg("pending user turn")]
        _turn_state(agent)["pending"] = ["turn-1"]
        agent._context_manager = SimpleNamespace(
            last_compress={"evicted": 0, "folded": 0},
        )

        async def evict(**_kwargs):
            agent.state.context.clear()
            agent._context_manager.last_compress["evicted"] = 1

        await mw.on_compress_context(agent, {}, evict)

        assert "turn-1" in _turn_state(agent)["snapshots"]
        assert _turn_state(agent)["pending"] == ["turn-1"]
        mm.auto_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_normal_request_may_flush_on_compress(self):
        """Non-automation requests follow the normal compress path."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        _turn_state(agent)["pending"] = ["turn-1"]
        agent.state.context = [_user_msg()]

        async def next_handler(**_kwargs):
            agent.state.summary = "compressed"

        await mw.on_compress_context(agent, {}, next_handler)

        mm.auto_memory.assert_awaited_once()
        assert mm.auto_memory.await_args.args[0][0].id == "turn-1"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failing_step",
        [
            "turn_state",
            "compression_result",
            "flush",
        ],
    )
    async def test_memory_failure_does_not_block_compression(
        self,
        failing_step,
    ):
        """Memory failures must not disable the context safety valve."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        next_handler = AsyncMock()

        _turn_state(agent)["pending"] = ["turn-1"]
        agent.state.context = [_user_msg()]

        if failing_step == "turn_state":
            turn_state = MagicMock(side_effect=RuntimeError("bad state"))
        else:
            turn_state = MagicMock(wraps=mw._auto_memory_turn_state)

        did_compress = MagicMock(return_value=True)
        flush = AsyncMock()
        if failing_step == "compression_result":
            did_compress.side_effect = RuntimeError("result unavailable")
        if failing_step == "flush":
            flush.side_effect = RuntimeError("memory flush failed")

        with (
            patch.object(
                mw,
                "_auto_memory_turn_state",
                turn_state,
            ),
            patch.object(
                MemoryMiddleware,
                "_did_compress_context",
                did_compress,
            ),
            patch.object(
                MemoryMiddleware,
                "_flush_auto_memory",
                flush,
            ),
        ):
            await mw.on_compress_context(agent, {}, next_handler)

        next_handler.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_compression_failure_is_not_swallowed(self):
        """Only memory failures are fail-open; compression still fails loud."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        next_handler = AsyncMock(
            side_effect=RuntimeError("scroll compression failed"),
        )

        with pytest.raises(RuntimeError, match="scroll compression failed"):
            await mw.on_compress_context(agent, {}, next_handler)

    @pytest.mark.asyncio
    async def test_partial_compression_failure_preserves_turn_snapshot(self):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        query = _user_msg("remember me")
        agent.state.context = [query]
        _turn_state(agent)["pending"] = ["turn-1"]
        agent._context_manager = SimpleNamespace(
            last_compress={"evicted": 0, "folded": 0},
        )

        async def fail_after_eviction(**_kwargs):
            agent.state.context.clear()
            agent._context_manager.last_compress["evicted"] = 1
            raise RuntimeError("context remains too large")

        with pytest.raises(RuntimeError, match="context remains too large"):
            await mw.on_compress_context(agent, {}, fail_after_eviction)

        raw_snapshot = _turn_state(agent)["snapshots"]["turn-1"]
        assert Msg.model_validate(raw_snapshot[0]).get_text_content() == (
            "remember me"
        )
        mm.auto_memory.assert_not_awaited()

        await mw._flush_auto_memory(agent)
        assert mm.auto_memory.await_args.args[0][0].get_text_content() == (
            "remember me"
        )


class TestDidCompressContext:
    def test_scroll_reports_real_change(self):
        agent = _make_agent(source="user")
        agent._context_manager = SimpleNamespace(
            last_compress={"evicted": 1, "folded": 0},
        )
        before = MemoryMiddleware._compression_state(agent)
        assert MemoryMiddleware._did_compress_context(agent, before) is True

    def test_scroll_reports_no_change(self):
        agent = _make_agent(source="user")
        agent._context_manager = SimpleNamespace(
            last_compress={"evicted": 0, "folded": 0},
        )
        before = MemoryMiddleware._compression_state(agent)
        assert MemoryMiddleware._did_compress_context(agent, before) is False

    def test_scroll_reports_fold_only_change(self):
        agent = _make_agent(source="user")
        agent._context_manager = SimpleNamespace(
            last_compress={"evicted": 0, "folded": 1},
        )
        before = MemoryMiddleware._compression_state(agent)
        assert MemoryMiddleware._did_compress_context(agent, before) is True

    def test_native_reports_state_change(self):
        agent = _make_agent(source="user")
        before = MemoryMiddleware._compression_state(agent)
        agent.state.summary = "compressed"
        assert MemoryMiddleware._did_compress_context(agent, before) is True


# ---------------------------------------------------------------------------
# _flush_auto_memory defensive guard
# ---------------------------------------------------------------------------


class TestFlushAutoMemoryDefensiveGuard:
    @pytest.mark.asyncio
    async def test_automation_preserves_pending_and_skips(self):
        """Automation must not mutate pending user memory state."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="cron")
        _turn_state(agent)["pending"] = ["m1", "m2"]

        await mw._flush_auto_memory(agent)

        assert _turn_state(agent)["pending"] == ["m1", "m2"]
        mm.auto_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_normal_request_flushes(self):
        """Non-automation requests proceed with auto_memory."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        _turn_state(agent)["pending"] = ["turn-1"]
        agent.state.context = [_user_msg()]

        await mw._flush_auto_memory(agent)

        mm.auto_memory.assert_awaited_once()
        assert not _turn_state(agent)["pending"]

    @pytest.mark.asyncio
    async def test_failed_submission_keeps_pending_for_next_turn_retry(self):
        mm = _make_memory_manager()
        mm.auto_memory.side_effect = [RuntimeError("submit failed"), None]
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        agent.state = AgentState(session_id="session-1")
        agent.state.context = [_user_msg()]
        _turn_state(agent)["pending"] = ["turn-1"]

        await mw._flush_auto_memory(agent)
        assert _turn_state(agent)["pending"] == ["turn-1"]
        assert "turn-1" in _turn_state(agent)["snapshots"]

        # Scroll may already have evicted the source turn. The retry payload
        # must therefore survive the same AgentState round trip as the marker.
        agent.state.context.clear()
        agent.state = AgentState.model_validate(
            agent.state.model_dump(mode="json"),
        )
        await mw._flush_auto_memory(agent)
        assert mm.auto_memory.await_count == 2
        assert mm.auto_memory.await_args.args[0][0].id == "turn-1"
        assert not _turn_state(agent)["pending"]
        assert not _turn_state(agent)["snapshots"]

    @pytest.mark.asyncio
    async def test_unresolved_markers_are_discarded_after_submission(self):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        agent.state.context = [_user_msg(msg_id="turn-2")]
        _turn_state(agent)["pending"] = ["turn-1", "turn-2"]

        await mw._flush_auto_memory(agent)

        assert [msg.id for msg in mm.auto_memory.await_args.args[0]] == [
            "turn-2",
        ]
        assert not _turn_state(agent)["pending"]

    @pytest.mark.asyncio
    async def test_unresolved_marker_is_discarded_and_does_not_consume_limit(
        self,
    ):
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        agent.state.context = [_user_msg(msg_id="turn-2")]
        _turn_state(agent)["pending"] = ["missing", "turn-2"]

        await mw._flush_auto_memory(agent, count=1)

        assert [msg.id for msg in mm.auto_memory.await_args.args[0]] == [
            "turn-2",
        ]
        assert not _turn_state(agent)["pending"]
