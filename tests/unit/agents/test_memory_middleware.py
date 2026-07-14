# -*- coding: utf-8 -*-
"""Tests for MemoryMiddleware automation-source skip logic."""
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.middlewares import MemoryMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(*, source: str | None = None):
    """Build a minimal fake agent with optional request_context source."""
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.state = SimpleNamespace(
        context=[],
        session_id="session-1",
        reply_id="reply-1",
    )
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
    mm._auto_memory_turn_states = {}

    def _get_auto_memory_turn_state(session_id: str):
        return mm._auto_memory_turn_states.setdefault(
            session_id or "__default__",
            {
                "pending": [],
                "seen": {},
                "touched_at": 0,
            },
        )

    mm.get_auto_memory_turn_state.side_effect = _get_auto_memory_turn_state
    return mm


def _auto_memory_turn_state(mm, session_id: str = "session-1"):
    return mm.get_auto_memory_turn_state(session_id)


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
        assert _auto_memory_turn_state(mm)["searched_turn"] == "turn-1"


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

        state = _auto_memory_turn_state(mm)
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
    async def test_interval_state_survives_middleware_rebuild(self):
        """A rebuilt middleware must keep interval state on the manager."""
        mm = _make_memory_manager(interval=2)

        async def _next(**_kwargs):
            yield "done"

        agent1 = _make_agent(source="user")
        agent1.state.context = [_user_msg(msg_id="turn-1")]
        gen1 = MemoryMiddleware(memory_manager=mm).on_reply(
            agent1,
            {},
            _next,
        )
        async for _ in gen1:
            pass

        mm.auto_memory.assert_not_awaited()
        assert _auto_memory_turn_state(mm)["pending"] == ["turn-1"]

        agent2 = _make_agent(source="user")
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
        assert not _auto_memory_turn_state(mm)["pending"]


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
    async def test_heartbeat_does_not_call_will_compress(self):
        """_will_compress_context must NOT be called for automation."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="heartbeat")
        next_handler = AsyncMock()

        with patch.object(
            MemoryMiddleware,
            "_will_compress_context",
        ) as mock_wc:
            await mw.on_compress_context(agent, {}, next_handler)
            mock_wc.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_request_may_flush_on_compress(self):
        """Non-automation requests follow the normal compress path."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        _auto_memory_turn_state(mm)["pending"] = ["m1"]
        next_handler = AsyncMock()

        with patch.object(
            MemoryMiddleware,
            "_memory_config",
        ) as mock_cfg, patch.object(
            MemoryMiddleware,
            "_will_compress_context",
            return_value=True,
        ) as mock_wc:
            cfg = MagicMock()
            cfg.summarize_when_compact = True
            mock_cfg.return_value = cfg

            agent.state.context = [_user_msg()]

            await mw.on_compress_context(agent, {}, next_handler)

            mock_wc.assert_awaited_once()
            next_handler.assert_awaited_once()


# ---------------------------------------------------------------------------
# _flush_auto_memory defensive guard
# ---------------------------------------------------------------------------


class TestFlushAutoMemoryDefensiveGuard:
    @pytest.mark.asyncio
    async def test_automation_clears_pending_and_skips(self):
        """Defensive guard in _flush_auto_memory clears markers."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="cron")
        _auto_memory_turn_state(mm)["pending"] = ["m1", "m2"]

        await mw._flush_auto_memory(agent)

        assert not _auto_memory_turn_state(mm)["pending"]
        mm.auto_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_normal_request_flushes(self):
        """Non-automation requests proceed with auto_memory."""
        mm = _make_memory_manager()
        mw = MemoryMiddleware(memory_manager=mm)
        agent = _make_agent(source="user")
        _auto_memory_turn_state(mm)["pending"] = ["turn-1"]
        agent.state.context = [_user_msg()]

        await mw._flush_auto_memory(agent)

        mm.auto_memory.assert_awaited_once()
