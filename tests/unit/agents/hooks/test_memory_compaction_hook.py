# -*- coding: utf-8 -*-
"""Tests for MemoryCompactionHook.

Covers:
- Initialization
- _print_status_message
- __call__: threshold too low, no messages, tool-result compact toggle,
  summary task toggle, compact-memory toggle, invalid-message fallback,
  marks messages compressed, exception handling

NOTE: Tests are written as top-level async functions (not class methods)
to avoid a pytest-asyncio issue on Linux where async class methods receive
duplicate fixture instances, making assertions on the 'mm' mock unreliable.
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


def test_stores_memory_manager():
    """P0: __init__ stores the memory manager."""
    from qwenpaw.agents.hooks.memory_compaction import (
        MemoryCompactionHook,
    )

    mm = MagicMock()
    h = MemoryCompactionHook(memory_manager=mm)
    assert h.memory_manager is mm


# ---------------------------------------------------------------------------
# _print_status_message
# ---------------------------------------------------------------------------


async def test_print_status_message_calls_agent_print(hook, agent):
    """P1: _print_status_message delegates to agent.print."""
    await hook._print_status_message(agent, "hello")
    agent.print.assert_called_once()


async def test_print_status_message_text_included(hook, agent):
    """P1: Msg passed to agent.print contains the text."""
    await hook._print_status_message(agent, "my status")
    call_args = agent.print.call_args
    msg = call_args[0][0]
    block = msg.content[0]
    text = block["text"] if isinstance(block, dict) else block.text
    assert text == "my status"


# ---------------------------------------------------------------------------
# __call__ — threshold guard
# ---------------------------------------------------------------------------


async def test_returns_none_when_threshold_too_low(hook, agent, mm):
    """P1: token_count(100) >= threshold(50) → return early."""
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


async def test_returns_none_when_no_messages_to_compact(hook, agent, mm):
    """P1: returns None when check_context yields empty list."""
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


async def test_calls_compact_tool_result_when_enabled(hook, agent, mm):
    """P1: compact_tool_result called when trc.enabled=True."""
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

    # Diagnostic: verify fixture identity before asserting
    assert hook.memory_manager is mm, (
        f"Fixture duplication detected: "
        f"hook.memory_manager id={id(hook.memory_manager)}, "
        f"mm id={id(mm)}"
    )
    mm.compact_tool_result.assert_called_once_with(
        messages=msgs,
        recent_n=2,
        old_max_bytes=3000,
        recent_max_bytes=50000,
        retention_days=7,
    )


async def test_skips_compact_tool_result_when_disabled(hook, agent, mm):
    """P1: compact_tool_result not called when trc.enabled=False."""
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


async def test_adds_summary_task_when_enabled(hook, agent, mm):
    """P1: add_async_summary_task called when summary_enabled=True."""
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


async def test_skips_summary_task_when_disabled(hook, agent, mm):
    """P1: add_async_summary_task not called when summary_enabled=False."""
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


async def test_runs_compact_memory_when_enabled(hook, agent, mm):
    """P1: compact_memory called when compact_enabled=True."""
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


async def test_skips_compact_memory_when_disabled(hook, agent, mm):
    """P1: compact_memory not called when compact_enabled=False."""
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
    agent.memory.update_compressed_summary.assert_called_once_with(
        "",
    )


async def test_compact_memory_failure_prints_warning(hook, agent, mm):
    """P1: compact_memory returning None triggers failure message."""
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
    assert agent.print.call_count == 2


# ---------------------------------------------------------------------------
# __call__ — marks messages compressed
# ---------------------------------------------------------------------------


async def test_marks_messages_compressed(hook, agent, mm):
    """P1: mark_messages_compressed always called with compacted msgs."""
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


async def test_fallback_finds_valid_slice(hook, agent, mm):
    """P1: is_valid=False with check_valid=True → valid slice used."""
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


async def test_fallback_all_invalid_uses_full_messages(hook, agent, mm):
    """P1: check_valid always False → keep_length=0 → all msgs used."""
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


async def test_handles_config_load_error_gracefully(hook, agent):
    """P2: config load exception is caught, None returned."""
    with patch(
        _LOAD_CFG,
        side_effect=RuntimeError("config error"),
    ):
        result = await hook(agent, {})

    assert result is None


async def test_always_returns_none(
    hook,
    agent,
    mm,
):  # pylint: disable=unused-argument
    """P2: return value is always None regardless of kwargs."""
    cfg = _make_config(threshold=5000)
    with patch(_LOAD_CFG, return_value=cfg), patch(
        _GET_TC,
        return_value=_token_counter(),
    ):
        result = await hook(agent, {"key": "value"})

    assert result is None
