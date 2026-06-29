# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for GoalMode."""
import pytest

from qwenpaw.loop.stop_handler import (
    StopAction,
    StopHandlerResult,
)
from qwenpaw.modes.goal.goal_mode import (
    GoalMode,
    GoalSession,
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
        result = await _mode._activate_handler(  # noqa
            {},
            "",
        )
        text = result.get_text_content()
        assert "Usage" in text

    @pytest.mark.asyncio()
    async def test_activate_with_task(self, _mode):
        result = await _mode._activate_handler(  # noqa
            {"session_id": "s1"},
            "fix all tests",
        )
        text = result.get_text_content()
        assert "activated" in text.lower()
        session = _mode.get_session("s1")
        assert session is not None
        assert session.goal == "fix all tests"
        assert session.active is True


class TestGoalModeCancel:
    """Test /cancel handler."""

    @pytest.fixture()
    def _mode(self):
        m = GoalMode()
        m._sessions["s1"] = GoalSession(  # noqa
            goal="test",
        )
        return m

    @pytest.mark.asyncio()
    async def test_cancel_active(self, _mode):
        result = await _mode._cancel_handler(  # noqa
            {"session_id": "s1"},
            "",
        )
        text = result.get_text_content()
        assert "cancelled" in text.lower()
        assert not _mode._sessions["s1"].active  # noqa

    @pytest.mark.asyncio()
    async def test_cancel_none_active(self):
        m = GoalMode()
        result = await m._cancel_handler(  # noqa
            {},
            "",
        )
        text = result.get_text_content()
        assert "no active" in text.lower()


class TestGoalModeStopHandler:
    """Test the stop handler logic."""

    @pytest.fixture()
    def _mode(self):
        m = GoalMode()
        m._sessions["default"] = GoalSession(  # noqa
            goal="fix tests",
            max_iterations=5,
        )
        return m

    @pytest.mark.asyncio()
    async def test_inactive_session_allows(self):
        m = GoalMode()
        result = await m._stop_handler(  # noqa
            {"agent": None},
        )
        assert isinstance(result, StopHandlerResult)
        assert result.action == StopAction.ALLOW

    @pytest.mark.asyncio()
    async def test_max_iterations_allows(
        self,
        _mode,
    ):
        session = _mode._sessions["default"]  # noqa
        session.iteration = 4  # next will be 5

        result = await _mode._stop_handler(  # noqa
            {"agent": None},
        )
        assert result.action == StopAction.ALLOW
        assert "max iterations" in result.reason.lower()

    @pytest.mark.asyncio()
    async def test_budget_exceeded_allows(
        self,
        _mode,
    ):
        session = _mode._sessions["default"]  # noqa
        session.tokens_used = 999999
        session.max_tokens = 100000

        result = await _mode._stop_handler(  # noqa
            {"agent": None},
        )
        assert result.action == StopAction.ALLOW
        assert "budget" in result.reason.lower()

    @pytest.mark.asyncio()
    async def test_normal_blocks(self, _mode):
        """Without GOAL COMPLETE, handler blocks."""
        from unittest.mock import MagicMock

        mock_msg = MagicMock()
        mock_msg.get_text_content.return_value = "Working on the task..."

        result = await _mode._stop_handler(  # noqa
            {
                "agent": None,
                "final_msg": mock_msg,
            },
        )
        assert result.action == StopAction.BLOCK
        assert "goal incomplete" in (result.reason.lower())
        assert "Continue working" in (result.continuation_message)
