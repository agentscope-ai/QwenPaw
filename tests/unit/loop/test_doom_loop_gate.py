# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for DoomLoopGate reset behaviour and exempt-tools (#5906)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.loop.gates.base import StopAction
from qwenpaw.loop.gates.doom_loop import DoomLoopGate


def _stage(after, action="stop", prompt="stop"):
    return SimpleNamespace(
        after=after,
        action=action,
        prompt=prompt,
    )


@pytest.fixture(autouse=True)
def _force_session_id():
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="test-session",
    ):
        yield


@pytest.fixture()
def gate():
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[
            _stage(3, "modify_prompt", "warning"),
            _stage(6, "stop", "doom stop"),
        ],
    )
    g.activate(None)
    g._ensure_state()
    return g


@pytest.fixture()
def gate_with_exemptions():
    """Gate with read-only tools exempt from doom loop detection."""
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[
            _stage(3, "modify_prompt", "warning"),
            _stage(6, "stop", "doom stop"),
        ],
        exempt_tools={
            "recall_history",
            "recall_history_python",
            "read_file",
        },
    )
    g.activate(None)
    g._ensure_state()
    return g


def test_reset_clears_history(gate):
    """reset() empties the history deque."""
    gate.record("tool_a", "hash1")
    gate.record("tool_a", "hash1")
    assert len(gate._ensure_state().history) == 2
    gate.reset_turn()
    assert len(gate._ensure_state().history) == 0


def test_reset_clears_counters(gate):
    """reset() zeroes consecutive_hits and prompt."""
    state = gate._ensure_state()
    state.consecutive_hits = 5
    state.prompt = "some warning"
    state.last_recorded_iter = 10
    gate.reset_turn()
    state = gate._ensure_state()
    assert state.consecutive_hits == 0
    assert state.prompt == ""
    assert state.last_recorded_iter == -1


def test_reset_keeps_gate_active(gate):
    """reset() does NOT deactivate the gate."""
    gate.reset_turn()
    assert gate._state() is not None


@pytest.mark.asyncio
async def test_no_false_positive_after_reset(gate):
    """After reset, fresh calls don't trigger doom loop."""
    for _ in range(3):
        gate.record("tool_a", "hash1")
    gate.reset_turn()
    gate.record("tool_b", "hash2")
    result = await gate.check({"iteration": 0})
    assert result.action == StopAction.BYPASS


@pytest.mark.asyncio
async def test_cross_request_no_bleed(gate):
    """Simulates two user requests: reset prevents bleed."""
    for _ in range(3):
        gate.record("search", "abc")

    result = await gate.check({"iteration": 3})
    assert result is not None

    gate.reset_turn()
    gate.record("search", "abc")
    result = await gate.check({"iteration": 1})
    assert result.action == StopAction.BYPASS


def test_reset_when_no_state():
    """reset_turn() is a no-op when gate has no state."""
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[],
    )
    g.reset_turn()


@pytest.mark.asyncio
async def test_session_isolation():
    """reset() only affects current session."""
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[
            _stage(3, "stop", "doom"),
        ],
    )
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="s1",
    ):
        g._ensure_state()
        g.record("t", "h")
        g.record("t", "h")

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="s2",
    ):
        g._ensure_state()
        g.record("t", "h")

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="s1",
    ):
        g.reset_turn()
        assert len(g._state().history) == 0

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="s2",
    ):
        assert len(g._state().history) == 1


# ---------------------------------------------------------------------------
# #5906 — exempt read-only tools from doom loop detection
# ---------------------------------------------------------------------------

def test_exempt_tool_not_recorded(gate_with_exemptions):
    """recall_history calls are not added to doom loop history."""
    gate_with_exemptions.record("recall_history", "hash1")
    gate_with_exemptions.record("recall_history", "hash1")
    gate_with_exemptions.record("recall_history", "hash1")
    assert len(gate_with_exemptions._ensure_state().history) == 0


@pytest.mark.asyncio
async def test_exempt_tool_does_not_trigger_warning(gate_with_exemptions):
    """6 consecutive recall_history calls must NOT trigger doom loop."""
    for _ in range(6):
        gate_with_exemptions.record("recall_history", "same_args")
    result = await gate_with_exemptions.check({"iteration": 6})
    assert result.action == StopAction.BYPASS


@pytest.mark.asyncio
async def test_exempt_tool_does_not_trigger_terminate(gate_with_exemptions):
    """Even past the stop threshold, exempt tools must not terminate."""
    for _ in range(10):
        gate_with_exemptions.record("read_file", "same_args")
    result = await gate_with_exemptions.check({"iteration": 10})
    assert result.action == StopAction.BYPASS


@pytest.mark.asyncio
async def test_non_exempt_tool_still_triggers(gate_with_exemptions):
    """Non-exempt tools are still subject to doom loop detection."""
    for _ in range(3):
        gate_with_exemptions.record("search_web", "same_query")
    result = await gate_with_exemptions.check({"iteration": 3})
    assert result.action == StopAction.INTERRUPT_AND_CONTINUE


def test_exempt_mixed_with_normal_only_counts_normal(gate_with_exemptions):
    """Exempt calls interspersed with normal calls only count normal ones."""
    gate_with_exemptions.record("recall_history", "h1")
    gate_with_exemptions.record("search_web", "q1")
    gate_with_exemptions.record("recall_history", "h2")
    gate_with_exemptions.record("search_web", "q1")
    gate_with_exemptions.record("recall_history", "h3")
    # Only 2 search_web calls in history — below window_size=3
    assert len(gate_with_exemptions._ensure_state().history) == 2


def test_no_exempt_tools_by_default():
    """Without exempt_tools, all tool calls are recorded (backward compat)."""
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[_stage(3, "stop", "doom")],
    )
    g.activate(None)
    g._ensure_state()
    g.record("recall_history", "h1")
    g.record("recall_history", "h1")
    assert len(g._ensure_state().history) == 2


def test_exempt_tools_via_auto_record(gate_with_exemptions):
    """_auto_record_from_ctx skips exempt tools when extracting from context."""
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            name="recall_history",
                            input={"query": "test"},
                        ),
                    ],
                ),
            ],
        ),
    )
    ctx = {"agent": agent, "iteration": 1}
    state = gate_with_exemptions._ensure_state()
    gate_with_exemptions._auto_record_from_ctx(ctx, state)
    assert len(state.history) == 0


def test_non_exempt_via_auto_record(gate_with_exemptions):
    """_auto_record_from_ctx records non-exempt tools normally."""
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            name="search_web",
                            input={"q": "test"},
                        ),
                    ],
                ),
            ],
        ),
    )
    ctx = {"agent": agent, "iteration": 1}
    state = gate_with_exemptions._ensure_state()
    gate_with_exemptions._auto_record_from_ctx(ctx, state)
    assert len(state.history) == 1


def test_exempt_does_not_swallow_non_exempt_same_iter(gate_with_exemptions):
    """P1: exempt tool after non-exempt in same context must not skip the
    non-exempt call.  reversed(content) hits recall_history first (exempt),
    but search_web before it must still be recorded.
    """
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            name="search_web",
                            input={"q": "dangerous"},
                        ),
                        SimpleNamespace(
                            type="tool_use",
                            name="recall_history",
                            input={"query": "what did I do"},
                        ),
                    ],
                ),
            ],
        ),
    )
    ctx = {"agent": agent, "iteration": 1}
    state = gate_with_exemptions._ensure_state()
    gate_with_exemptions._auto_record_from_ctx(ctx, state)
    assert len(state.history) == 1
    assert state.history[0].tool_name == "search_web"


def test_all_exempt_in_iter_advances_recorded_iter(gate_with_exemptions):
    """If all tool calls in an iteration are exempt, last_recorded_iter
    advances so the iteration is not re-scanned."""
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            name="recall_history",
                            input={},
                        ),
                    ],
                ),
            ],
        ),
    )
    ctx = {"agent": agent, "iteration": 5}
    state = gate_with_exemptions._ensure_state()
    gate_with_exemptions._auto_record_from_ctx(ctx, state)
    assert len(state.history) == 0
    assert state.last_recorded_iter == 5


@pytest.mark.asyncio
async def test_recall_history_python_exempt(gate_with_exemptions):
    """recall_history_python (sandboxed REPL, default scroll tool) is
    exempt — repeated calls must not trigger doom loop (#5906 main path).
    """
    for _ in range(6):
        gate_with_exemptions.record("recall_history_python", "same")
    result = await gate_with_exemptions.check({"iteration": 6})
    assert result.action == StopAction.BYPASS


def test_recall_history_python_via_auto_record(gate_with_exemptions):
    """_auto_record_from_ctx skips recall_history_python."""
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            name="recall_history_python",
                            input={"code": "df.head()"},
                        ),
                    ],
                ),
            ],
        ),
    )
    ctx = {"agent": agent, "iteration": 1}
    state = gate_with_exemptions._ensure_state()
    gate_with_exemptions._auto_record_from_ctx(ctx, state)
    assert len(state.history) == 0
