# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for GoalMode gates and session."""
import pytest

from qwenpaw.app.agent_context import (
    set_current_session_id,
)
from qwenpaw.loop.rubric_grader import GoalStatusRubric
from qwenpaw.loop.stop_handler import (
    StopAction,
    StopHandler,
)
from qwenpaw.modes.goal.goal_mode import (
    BudgetGate,
    GoalMode,
    GoalSession,
    IterationGate,
    RubricGate,
)


class TestGoalSession:  # pylint: disable=too-few-public-methods
    """GoalSession dataclass tests."""

    def test_defaults(self):
        s = GoalSession(goal="fix tests")
        assert s.goal == "fix tests"
        assert s.active is True
        assert s.iteration == 0
        assert s.max_iterations == 20
        assert s.tokens_used == 0

    def test_custom_limits(self):
        s = GoalSession(
            goal="big task",
            max_iterations=50,
            max_tokens=500000,
        )
        assert s.max_iterations == 50
        assert s.max_tokens == 500000
        assert not hasattr(s, "max_cost_usd")


class TestGoalModeActivation:
    """Test /goal activation handler."""

    @pytest.fixture()
    def _mode(self):
        return GoalMode()

    @pytest.mark.asyncio()
    async def test_activate_empty_args(self, _mode):
        result = await _mode._activate_handler(
            {},
            "",
        )
        text = result.get_text_content()
        assert "Usage" in text

    @pytest.mark.asyncio()
    async def test_activate_with_task(self, _mode):
        result = await _mode._activate_handler(
            {"session_id": "s1"},
            "fix all tests",
        )
        assert result is None
        session = _mode.get_session("s1")
        assert session is not None
        assert session.goal == "fix all tests"
        assert session.active is True


class TestGoalModeCancel:
    """Test /cancel handler."""

    @pytest.fixture()
    def _mode(self):
        m = GoalMode()
        m._sessions["s1"] = GoalSession(
            goal="test",
        )
        return m

    @pytest.mark.asyncio()
    async def test_cancel_active(self, _mode):
        result = await _mode._cancel_handler(
            {"session_id": "s1"},
            "",
        )
        text = result.get_text_content()
        assert "cancelled" in text.lower()
        assert not _mode._sessions["s1"].active

    @pytest.mark.asyncio()
    async def test_cancel_none_active(self):
        m = GoalMode()
        result = await m._cancel_handler(
            {},
            "",
        )
        text = result.get_text_content()
        assert "no active" in text.lower()


# ---- Gate tests ----


def _make_mode_with_session(
    key="default",
    **kwargs,
):
    """Create GoalMode + session + set ContextVar."""
    m = GoalMode()
    m._sessions[key] = GoalSession(
        goal="fix tests",
        **kwargs,
    )
    set_current_session_id(key)
    return m


class TestIterationGate:
    """Test IterationGate."""

    @pytest.mark.asyncio()
    async def test_under_limit_returns_none(self):
        m = _make_mode_with_session(
            max_iterations=5,
        )
        gate = IterationGate(m)
        result = await gate.check({"agent": None})
        assert result is None
        assert m._sessions["default"].iteration == 1

    @pytest.mark.asyncio()
    async def test_at_limit_returns_stop(self):
        m = _make_mode_with_session(
            max_iterations=5,
        )
        m._sessions["default"].iteration = 4
        gate = IterationGate(m)
        result = await gate.check({"agent": None})
        assert result is not None
        assert result.action == StopAction.STOP
        assert not m._sessions["default"].active

    @pytest.mark.asyncio()
    async def test_no_session_returns_none(self):
        m = GoalMode()
        set_current_session_id(None)
        gate = IterationGate(m)
        result = await gate.check({"agent": None})
        assert result is None


class TestBudgetGate:
    """Test BudgetGate."""

    @pytest.mark.asyncio()
    async def test_under_budget_returns_none(self):
        m = _make_mode_with_session(
            max_tokens=100000,
        )
        m._sessions["default"].tokens_used = 50000
        gate = BudgetGate(m)
        result = await gate.check({"agent": None})
        assert result is None

    @pytest.mark.asyncio()
    async def test_over_budget_returns_stop(self):
        m = _make_mode_with_session(
            max_tokens=100000,
        )
        m._sessions["default"].tokens_used = 999999
        gate = BudgetGate(m)
        result = await gate.check({"agent": None})
        assert result is not None
        assert result.action == StopAction.STOP
        assert not m._sessions["default"].active


class TestRubricGate:
    """Test RubricGate."""

    @pytest.mark.asyncio()
    async def test_active_session_returns_none(self):
        m = _make_mode_with_session()
        rubric = GoalStatusRubric(
            get_session_fn=m.session_by_ctx_var,
        )
        gate = RubricGate(m, rubric)
        result = await gate.check({"agent": None})
        assert result is None

    @pytest.mark.asyncio()
    async def test_completed_session_returns_stop(
        self,
    ):
        m = _make_mode_with_session()
        m._sessions["default"].active = False
        rubric = GoalStatusRubric(
            get_session_fn=m.session_by_ctx_var,
        )
        gate = RubricGate(m, rubric)
        result = await gate.check({"agent": None})
        assert result is not None
        assert result.action == StopAction.STOP


class TestStopHandlerComposition:
    """Test full StopHandler with GoalMode gates."""

    @pytest.mark.asyncio()
    async def test_no_gates_returns_stop(self):
        handler = StopHandler()
        result = await handler({})
        assert result.action == StopAction.STOP

    @pytest.mark.asyncio()
    async def test_all_pass_returns_continue(self):
        m = _make_mode_with_session(
            max_iterations=99,
            max_tokens=999999,
        )
        rubric = GoalStatusRubric(
            get_session_fn=m.session_by_ctx_var,
        )
        handler = StopHandler()
        handler.register(IterationGate(m))
        handler.register(BudgetGate(m))
        handler.register(RubricGate(m, rubric))
        handler.set_continuation(
            lambda ctx: "Keep going",
        )

        result = await handler({"agent": None})
        assert result.action == StopAction.CONTINUE
        assert result.continuation_message == "Keep going"

    @pytest.mark.asyncio()
    async def test_iter_gate_stops_first(self):
        m = _make_mode_with_session(
            max_iterations=1,
        )
        rubric = GoalStatusRubric(
            get_session_fn=m.session_by_ctx_var,
        )
        handler = StopHandler()
        handler.register(IterationGate(m))
        handler.register(BudgetGate(m))
        handler.register(RubricGate(m, rubric))

        result = await handler({"agent": None})
        assert result.action == StopAction.STOP
        assert "iterations" in result.reason.lower()
