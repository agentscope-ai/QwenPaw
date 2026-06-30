# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Tests for the stop hook mechanism in react_agent."""
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.loop.gates import (
    StopAction,
    StopHandlerRegistration,
    StopHandlerResult,
)


class TestStopHandlerResult:  # pylint: disable=too-few-public-methods
    """StopHandlerResult data class tests."""

    def test_default_stop(self):
        r = StopHandlerResult()
        assert r.action == StopAction.STOP
        assert r.continuation_message == ""
        assert r.reason == ""

    def test_continue_with_message(self):
        r = StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message="Keep going",
            reason="task incomplete",
        )
        assert r.action == StopAction.CONTINUE
        assert r.continuation_message == "Keep going"


class TestStopHandlerRegistration:  # pylint: disable=too-few-public-methods
    """StopHandlerRegistration tests."""

    def test_registration_fields(self):
        reg = StopHandlerRegistration(
            plugin_id="test-plugin",
            handler=lambda ctx: None,
            priority=50,
            name="test-handler",
        )
        assert reg.plugin_id == "test-plugin"
        assert reg.priority == 50
        assert reg.name == "test-handler"


class TestRunStopHandlers:
    """Test _run_stop_handlers method logic."""

    @pytest.fixture()
    def _mock_agent(self):
        """Create a minimal mock agent."""
        agent = MagicMock()
        agent.state = MagicMock()
        agent.state.cur_iter = 5
        agent.state.context = []
        return agent

    @pytest.mark.asyncio()
    async def test_no_handlers_returns_stop(
        self,
        _mock_agent,
    ):
        """No handlers -> STOP."""
        from qwenpaw.agents.react_agent import (
            QwenPawAgent,
        )

        with patch.object(
            QwenPawAgent,
            "_get_stop_handlers",
            return_value=[],
        ):
            agent = MagicMock(spec=QwenPawAgent)
            agent._get_stop_handlers = MagicMock(return_value=[])  # noqa

            result = await QwenPawAgent._run_stop_handlers(
                agent,
                MagicMock(),
            )
            assert result.action == StopAction.STOP

    @pytest.mark.asyncio()
    async def test_continue_handler(
        self,
    ):
        """A handler returning CONTINUE should continue."""
        from qwenpaw.agents.react_agent import (
            QwenPawAgent,
        )

        async def cont_handler(ctx):
            return StopHandlerResult(
                action=StopAction.CONTINUE,
                continuation_message="Continue!",
                reason="not done",
            )

        reg = StopHandlerRegistration(
            plugin_id="test",
            handler=cont_handler,
            priority=50,
            name="continuer",
        )

        agent = MagicMock(spec=QwenPawAgent)
        agent._get_stop_handlers = MagicMock(  # noqa
            return_value=[reg],
        )
        agent.state = MagicMock()
        agent.state.cur_iter = 3

        result = await QwenPawAgent._run_stop_handlers(
            agent,
            MagicMock(),
        )
        assert result.action == StopAction.CONTINUE
        assert result.continuation_message == "Continue!"

    @pytest.mark.asyncio()
    async def test_stop_handler_returns_stop(
        self,
    ):
        """All handlers returning STOP -> STOP."""
        from qwenpaw.agents.react_agent import (
            QwenPawAgent,
        )

        async def stop_handler(ctx):
            return StopHandlerResult(
                action=StopAction.STOP,
            )

        reg = StopHandlerRegistration(
            plugin_id="test",
            handler=stop_handler,
            priority=50,
            name="stopper",
        )

        agent = MagicMock(spec=QwenPawAgent)
        agent._get_stop_handlers = MagicMock(  # noqa
            return_value=[reg],
        )
        agent.state = MagicMock()
        agent.state.cur_iter = 1

        result = await QwenPawAgent._run_stop_handlers(
            agent,
            MagicMock(),
        )
        assert result.action == StopAction.STOP

    @pytest.mark.asyncio()
    async def test_priority_ordering(self):
        """Higher priority (lower number) checked first."""
        from qwenpaw.agents.react_agent import (
            QwenPawAgent,
        )

        call_order = []

        async def high_priority(ctx):
            call_order.append("high")
            return StopHandlerResult(
                action=StopAction.CONTINUE,
                continuation_message="high wins",
            )

        async def low_priority(ctx):
            call_order.append("low")
            return StopHandlerResult(
                action=StopAction.STOP,
            )

        regs = [
            StopHandlerRegistration(
                plugin_id="test",
                handler=low_priority,
                priority=100,
                name="low",
            ),
            StopHandlerRegistration(
                plugin_id="test",
                handler=high_priority,
                priority=10,
                name="high",
            ),
        ]

        agent = MagicMock(spec=QwenPawAgent)
        agent._get_stop_handlers = MagicMock(  # noqa
            return_value=regs,
        )
        agent.state = MagicMock()
        agent.state.cur_iter = 2

        result = await QwenPawAgent._run_stop_handlers(
            agent,
            MagicMock(),
        )
        assert result.action == StopAction.CONTINUE
        assert call_order == ["high"]

    @pytest.mark.asyncio()
    async def test_handler_exception_skipped(self):
        """Exceptions in handlers are caught, not raised."""
        from qwenpaw.agents.react_agent import (
            QwenPawAgent,
        )

        async def bad_handler(ctx):
            raise RuntimeError("boom")

        reg = StopHandlerRegistration(
            plugin_id="test",
            handler=bad_handler,
            priority=50,
            name="bad",
        )

        agent = MagicMock(spec=QwenPawAgent)
        agent._get_stop_handlers = MagicMock(  # noqa
            return_value=[reg],
        )
        agent.state = MagicMock()
        agent.state.cur_iter = 1

        result = await QwenPawAgent._run_stop_handlers(
            agent,
            MagicMock(),
        )
        assert result.action == StopAction.STOP
