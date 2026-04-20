# -*- coding: utf-8 -*-
"""Tests for MemoryCompactionHook.

Covers:
- Initialization
- _print_status_message
- __call__: threshold too low, no messages, tool-result compact toggle,
  summary task toggle, compact-memory toggle, invalid-message fallback,
  marks messages compressed, exception handling
"""
# pylint: disable=redefined-outer-name,protected-access
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    *,
    threshold=5000,
    reserve=500,
    trc_enabled=True,
    trc_recent_n=2,
    trc_old_max_bytes=3000,
    trc_recent_max_bytes=50000,
    trc_retention_days=7,
    summary_enabled=True,
    compact_enabled=True,
):
    """Build a minimal mock AgentProfileConfig."""
    cfg = MagicMock()
    r = cfg.running
    r.memory_compact_threshold = threshold
    r.memory_compact_reserve = reserve
    r.tool_result_compact.enabled = trc_enabled
    r.tool_result_compact.recent_n = trc_recent_n
    r.tool_result_compact.old_max_bytes = trc_old_max_bytes
    r.tool_result_compact.recent_max_bytes = trc_recent_max_bytes
    r.tool_result_compact.retention_days = trc_retention_days
    r.memory_summary.memory_summary_enabled = summary_enabled
    r.context_compact.context_compact_enabled = compact_enabled
    return cfg


_LOAD_CFG = "qwenpaw.agents.hooks.memory_compaction.load_agent_config"
_GET_TC = "qwenpaw.agents.hooks.memory_compaction.get_token_counter"
_CHECK_VALID = "qwenpaw.agents.hooks.memory_compaction.check_valid_messages"


def _token_counter(count: int = 100):
    tc = MagicMock()
    tc.count = AsyncMock(return_value=count)
    return tc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mm():
    """Mock BaseMemoryManager."""
    m = MagicMock()
    m.agent_id = "test-agent"
    m.compact_tool_result = AsyncMock()
    m.check_context = AsyncMock(return_value=([], None, True))
    m.compact_memory = AsyncMock(return_value="summary text")
    m.add_async_summary_task = MagicMock()
    return m


@pytest.fixture
def agent():
    """Mock ReActAgent."""
    a = MagicMock()
    a.name = "TestAgent"
    a.sys_prompt = "You are an assistant."
    a.memory.get_compressed_summary.return_value = ""
    a.memory.get_memory = AsyncMock(return_value=[MagicMock()])
    a.memory.mark_messages_compressed = AsyncMock(return_value=1)
    a.memory.update_compressed_summary = AsyncMock()
    a.print = AsyncMock()
    return a


@pytest.fixture
def hook(mm):
    from qwenpaw.agents.hooks.memory_compaction import (
        MemoryCompactionHook,
    )

    return MemoryCompactionHook(memory_manager=mm)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestMemoryCompactionHookInit:
    """P0: __init__ tests."""

    def test_stores_memory_manager(self):
        from qwenpaw.agents.hooks.memory_compaction import (
            MemoryCompactionHook,
        )

        mm = MagicMock()
        hook = MemoryCompactionHook(memory_manager=mm)
        assert hook.memory_manager is mm


# ---------------------------------------------------------------------------
# _print_status_message
# ---------------------------------------------------------------------------


class TestPrintStatusMessage:
    """P1: _print_status_message delegates to agent.print."""

    async def test_calls_agent_print_once(self, hook, agent):
        await hook._print_status_message(agent, "hello")
        agent.print.assert_called_once()

    async def test_message_text_included(self, hook, agent):
        """Msg passed to agent.print contains the text."""
        await hook._print_status_message(agent, "my status")
        call_args = agent.print.call_args
        msg = call_args[0][0]
        # TextBlock may be stored as dict or object; support both
        block = msg.content[0]
        text = block["text"] if isinstance(block, dict) else block.text
        assert text == "my status"


# ---------------------------------------------------------------------------
# __call__ — threshold guard
# ---------------------------------------------------------------------------


class TestMemoryCompactionHookThreshold:
    """P1: early return when sys_prompt + summary exceed threshold."""

    async def test_returns_none_when_threshold_too_low(
        self,
        hook,
        agent,
        mm,
    ):
        """token_count(100) >= threshold(50) → return early."""
        cfg = _make_config(threshold=50)
        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(count=100),
        ):
            result = await hook(agent, {})

        assert result is None
        mm.check_context.assert_not_called()


# ---------------------------------------------------------------------------
# __call__ — no messages to compact
# ---------------------------------------------------------------------------


class TestMemoryCompactionHookNoMessages:
    """P1: returns None when check_context yields empty list."""

    async def test_returns_none_when_no_messages_to_compact(
        self,
        hook,
        agent,
        mm,
    ):
        cfg = _make_config(threshold=5000)
        mm.check_context = AsyncMock(return_value=([], None, True))
        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            result = await hook(agent, {})

        assert result is None
        mm.compact_memory.assert_not_called()


# ---------------------------------------------------------------------------
# __call__ — tool-result compaction toggle
# ---------------------------------------------------------------------------


class TestToolResultCompaction:
    """P1: tool_result_compact.enabled controls compact_tool_result."""

    async def test_calls_compact_tool_result_when_enabled(
        self,
        hook,
        agent,
        mm,
    ):
        msgs = [MagicMock()]
        cfg = _make_config(
            threshold=5000,
            trc_enabled=True,
            trc_recent_n=2,
            trc_old_max_bytes=3000,
            trc_recent_max_bytes=50000,
            trc_retention_days=7,
        )
        mm.check_context = AsyncMock(return_value=([], None, True))
        agent.memory.get_memory = AsyncMock(return_value=msgs)

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            await hook(agent, {})

        mm.compact_tool_result.assert_called_once_with(
            messages=msgs,
            recent_n=2,
            old_max_bytes=3000,
            recent_max_bytes=50000,
            retention_days=7,
        )

    async def test_skips_compact_tool_result_when_disabled(
        self,
        hook,
        agent,
        mm,
    ):
        cfg = _make_config(threshold=5000, trc_enabled=False)
        mm.check_context = AsyncMock(return_value=([], None, True))

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            await hook(agent, {})

        mm.compact_tool_result.assert_not_called()


# ---------------------------------------------------------------------------
# __call__ — memory summary task toggle
# ---------------------------------------------------------------------------


class TestMemorySummaryTask:
    """P1: memory_summary_enabled controls add_async_summary_task."""

    async def test_adds_summary_task_when_enabled(
        self,
        hook,
        agent,
        mm,
    ):
        msgs_to_compact = [MagicMock()]
        cfg = _make_config(
            threshold=5000,
            summary_enabled=True,
            compact_enabled=False,
        )
        mm.check_context = AsyncMock(
            return_value=(msgs_to_compact, None, True),
        )

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            await hook(agent, {})

        mm.add_async_summary_task.assert_called_once_with(
            messages=msgs_to_compact,
        )

    async def test_skips_summary_task_when_disabled(
        self,
        hook,
        agent,
        mm,
    ):
        msgs_to_compact = [MagicMock()]
        cfg = _make_config(
            threshold=5000,
            summary_enabled=False,
            compact_enabled=False,
        )
        mm.check_context = AsyncMock(
            return_value=(msgs_to_compact, None, True),
        )

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            await hook(agent, {})

        mm.add_async_summary_task.assert_not_called()


# ---------------------------------------------------------------------------
# __call__ — context compaction toggle
# ---------------------------------------------------------------------------


class TestContextCompaction:
    """P1: context_compact_enabled controls compact_memory."""

    async def test_runs_compact_memory_when_enabled(
        self,
        hook,
        agent,
        mm,
    ):
        msgs_to_compact = [MagicMock()]
        cfg = _make_config(
            threshold=5000,
            summary_enabled=False,
            compact_enabled=True,
        )
        mm.check_context = AsyncMock(
            return_value=(msgs_to_compact, None, True),
        )
        mm.compact_memory = AsyncMock(return_value="compact summary")

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            await hook(agent, {})

        mm.compact_memory.assert_called_once_with(
            messages=msgs_to_compact,
            previous_summary="",
        )
        agent.memory.update_compressed_summary.assert_called_once_with(
            "compact summary",
        )

    async def test_skips_compact_memory_when_disabled(
        self,
        hook,
        agent,
        mm,
    ):
        msgs_to_compact = [MagicMock()]
        cfg = _make_config(
            threshold=5000,
            summary_enabled=False,
            compact_enabled=False,
        )
        mm.check_context = AsyncMock(
            return_value=(msgs_to_compact, None, True),
        )

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            await hook(agent, {})

        mm.compact_memory.assert_not_called()
        # update_compressed_summary still called with empty string
        agent.memory.update_compressed_summary.assert_called_once_with(
            "",
        )

    async def test_compact_memory_failure_prints_warning(
        self,
        hook,
        agent,
        mm,
    ):
        """compact_memory returning None triggers failure message."""
        msgs_to_compact = [MagicMock()]
        cfg = _make_config(
            threshold=5000,
            summary_enabled=False,
            compact_enabled=True,
        )
        mm.check_context = AsyncMock(
            return_value=(msgs_to_compact, None, True),
        )
        mm.compact_memory = AsyncMock(return_value=None)

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            result = await hook(agent, {})

        assert result is None
        # agent.print called twice: started + failed
        assert agent.print.call_count == 2


# ---------------------------------------------------------------------------
# __call__ — marks messages compressed
# ---------------------------------------------------------------------------


class TestMarkMessagesCompressed:
    """P1: mark_messages_compressed is always called with compacted msgs."""

    async def test_marks_messages_compressed(self, hook, agent, mm):
        msgs_to_compact = [MagicMock()]
        cfg = _make_config(
            threshold=5000,
            summary_enabled=False,
            compact_enabled=False,
        )
        mm.check_context = AsyncMock(
            return_value=(msgs_to_compact, None, True),
        )

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            await hook(agent, {})

        agent.memory.mark_messages_compressed.assert_called_once_with(
            msgs_to_compact,
        )


# ---------------------------------------------------------------------------
# __call__ — invalid messages fallback
# ---------------------------------------------------------------------------


class TestInvalidMessagesFallback:
    """P1: is_valid=False triggers keep_length fallback logic."""

    async def test_fallback_finds_valid_slice(
        self,
        hook,
        agent,
        mm,
    ):
        """check_valid_messages returns True → valid slice used."""
        # 10 messages; MEMORY_COMPACT_KEEP_RECENT=3 default
        # → messages_to_compact = messages[:7] (non-empty → proceeds)
        msgs = [MagicMock() for _ in range(10)]
        cfg = _make_config(
            threshold=5000,
            summary_enabled=False,
            compact_enabled=False,
        )
        mm.check_context = AsyncMock(
            return_value=(msgs, None, False),
        )
        agent.memory.get_memory = AsyncMock(return_value=msgs)

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ), patch(_CHECK_VALID, return_value=True):
            result = await hook(agent, {})

        assert result is None
        agent.memory.mark_messages_compressed.assert_called_once()

    async def test_fallback_all_invalid_uses_full_messages(
        self,
        hook,
        agent,
        mm,
    ):
        """check_valid_messages always False → keep_length=0 → all msgs."""
        msgs = [MagicMock() for _ in range(5)]
        cfg = _make_config(
            threshold=5000,
            summary_enabled=False,
            compact_enabled=False,
        )
        mm.check_context = AsyncMock(
            return_value=(msgs, None, False),
        )
        agent.memory.get_memory = AsyncMock(return_value=msgs)

        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ), patch(_CHECK_VALID, return_value=False):
            result = await hook(agent, {})

        assert result is None
        agent.memory.mark_messages_compressed.assert_called_once_with(
            msgs,
        )


# ---------------------------------------------------------------------------
# __call__ — exception handling
# ---------------------------------------------------------------------------


class TestMemoryCompactionHookException:
    """P2: exceptions are caught, None is returned."""

    async def test_handles_config_load_error_gracefully(
        self,
        hook,
        agent,
    ):
        with patch(
            _LOAD_CFG,
            side_effect=RuntimeError("config error"),
        ):
            result = await hook(agent, {})

        assert result is None

    async def test_always_returns_none(
        self,
        hook,
        agent,
        mm,
    ):  # pylint: disable=unused-argument
        """Return value is always None regardless of kwargs."""
        cfg = _make_config(threshold=5000)
        with patch(_LOAD_CFG, return_value=cfg), patch(
            _GET_TC,
            return_value=_token_counter(),
        ):
            result = await hook(agent, {"key": "value"})

        assert result is None
