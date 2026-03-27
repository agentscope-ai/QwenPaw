# -*- coding: utf-8 -*-
"""Unit tests for ChannelManager._consume_command_loop."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from copaw.app.channels.manager import ChannelManager
from copaw.app.runner.command_router import (
    CommandContext,
    CommandPriority,
    CommandRouter,
    PrioritizedPayload,
)
from agentscope.message import Msg, TextBlock


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


@dataclass
class _FakeContent:
    type: str = "text"
    text: str = ""


@dataclass
class _FakeInput:
    content: list[Any] | None = None


@dataclass
class _FakeRequest:
    input: list[Any] | None = None
    session_id: str = "sess-1"
    user_id: str = "user-1"


class _FakeChannel:
    """Minimal BaseChannel stub for consume_command_loop tests."""

    channel = "test"
    _task_tracker = None

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def _payload_to_request(self, payload: Any) -> _FakeRequest:
        if isinstance(payload, dict):
            return _FakeRequest(
                input=[
                    _FakeInput(
                        content=[
                            _FakeContent(
                                type="text", text=payload.get("text", "")
                            )
                        ]
                    )
                ],
                session_id=payload.get("session_id", "sess-1"),
                user_id=payload.get("user_id", "user-1"),
            )
        return _FakeRequest(
            input=[
                _FakeInput(
                    content=[_FakeContent(type="text", text=str(payload))]
                )
            ],
        )

    def get_to_handle_from_request(self, request: _FakeRequest) -> str:
        return getattr(request, "user_id", "") or ""

    def get_debounce_key(self, payload: Any) -> str:
        return "key"

    async def send(self, to_handle: str, text: str, meta: Any = None) -> None:
        self.sent.append((to_handle, text))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result_msg(text: str) -> Msg:
    return Msg(
        name="Friday",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )


async def _run_loop_with_items(
    items: list[PrioritizedPayload],
    fake_ch: _FakeChannel,
    router: CommandRouter | None = None,
) -> _FakeChannel:
    """Put items into a PriorityQueue, run _consume_command_loop until all
    items are consumed, then cancel the loop task."""
    mgr = ChannelManager(channels=[fake_ch])
    cq: asyncio.PriorityQueue = asyncio.PriorityQueue()
    mgr._command_queues["test"] = cq
    if router is None:
        router = CommandRouter(task_tracker=None, runner=None)
    mgr.set_command_router(router)

    for item in items:
        await cq.put(item)

    # Run the loop; it will block on cq.get() after draining all items.
    loop_task = asyncio.create_task(mgr._consume_command_loop("test"))

    # Wait until queue is drained
    while not cq.empty():
        await asyncio.sleep(0.01)
    # Give the loop a moment to finish processing the last item
    await asyncio.sleep(0.05)

    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    return fake_ch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConsumeCommandLoopBasic:
    """Basic command consumption and dispatch."""

    @pytest.mark.asyncio
    async def test_dispatches_command_and_sends_result(self) -> None:
        """A single command is dispatched and result sent via channel."""
        ch = _FakeChannel()
        item = PrioritizedPayload(
            priority=CommandPriority.LOW,
            sequence=1,
            payload={"text": "/status", "session_id": "s1", "user_id": "u1"},
            command_name="status",
            command_args=[],
        )
        await _run_loop_with_items([item], ch)

        assert len(ch.sent) == 1
        to_handle, text = ch.sent[0]
        assert to_handle == "u1"
        # The default CommandRouter has a /status handler
        # that returns some text
        assert text  # non-empty response

    @pytest.mark.asyncio
    async def test_multiple_commands_processed_in_priority_order(self) -> None:
        """Commands are consumed in priority order (lower number first)."""
        ch = _FakeChannel()
        processed_order: list[str] = []

        router = CommandRouter(task_tracker=None, runner=None)

        # Override dispatch to track order
        original_dispatch = router.dispatch

        async def tracking_dispatch(ctx: CommandContext) -> Msg:
            processed_order.append(ctx.command_name)
            return await original_dispatch(ctx)

        router.dispatch = tracking_dispatch

        items = [
            PrioritizedPayload(
                priority=CommandPriority.LOW,
                sequence=1,
                payload={
                    "text": "/status",
                    "session_id": "s1",
                    "user_id": "u1",
                },
                command_name="status",
                command_args=[],
            ),
            PrioritizedPayload(
                priority=CommandPriority.CRITICAL,
                sequence=2,
                payload={"text": "/stop", "session_id": "s1", "user_id": "u1"},
                command_name="stop",
                command_args=[],
            ),
        ]

        await _run_loop_with_items(items, ch, router)

        # /stop (CRITICAL=0) should be processed before /status (LOW=3)
        assert processed_order[0] == "stop"
        assert processed_order[1] == "status"


class TestConsumeCommandLoopErrorRecovery:
    """Error handling: exceptions logged, loop continues."""

    @pytest.mark.asyncio
    async def test_exception_in_dispatch_does_not_break_loop(self) -> None:
        """If dispatch raises, the loop logs and continues to next command."""
        ch = _FakeChannel()
        call_count = 0

        router = CommandRouter(task_tracker=None, runner=None)
        original_dispatch = router.dispatch

        async def failing_then_ok_dispatch(ctx: CommandContext) -> Msg:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated failure")
            return await original_dispatch(ctx)

        router.dispatch = failing_then_ok_dispatch

        items = [
            PrioritizedPayload(
                priority=CommandPriority.NORMAL,
                sequence=1,
                payload={
                    "text": "/restart",
                    "session_id": "s1",
                    "user_id": "u1",
                },
                command_name="restart",
                command_args=[],
            ),
            PrioritizedPayload(
                priority=CommandPriority.LOW,
                sequence=2,
                payload={
                    "text": "/version",
                    "session_id": "s1",
                    "user_id": "u1",
                },
                command_name="version",
                command_args=[],
            ),
        ]

        await _run_loop_with_items(items, ch, router)

        # First command failed (exception caught), second should still be sent
        assert call_count == 2
        # Only the second command's result should be sent
        # (first raised before send)
        assert len(ch.sent) == 1

    @pytest.mark.asyncio
    async def test_send_exception_does_not_break_loop(self) -> None:
        """If channel.send raises, the loop logs and continues."""
        ch = _FakeChannel()
        send_call_count = 0
        original_send = ch.send

        async def failing_send(
            to_handle: str, text: str, meta: Any = None
        ) -> None:
            nonlocal send_call_count
            send_call_count += 1
            if send_call_count == 1:
                raise RuntimeError("send failed")
            await original_send(to_handle, text, meta)

        ch.send = failing_send

        items = [
            PrioritizedPayload(
                priority=CommandPriority.LOW,
                sequence=1,
                payload={
                    "text": "/status",
                    "session_id": "s1",
                    "user_id": "u1",
                },
                command_name="status",
                command_args=[],
            ),
            PrioritizedPayload(
                priority=CommandPriority.LOW,
                sequence=2,
                payload={
                    "text": "/version",
                    "session_id": "s1",
                    "user_id": "u1",
                },
                command_name="version",
                command_args=[],
            ),
        ]

        await _run_loop_with_items(items, ch)

        assert send_call_count == 2
        # Second send succeeded
        assert len(ch.sent) == 1


class TestConsumeCommandLoopGracefulExit:
    """CancelledError causes graceful exit."""

    @pytest.mark.asyncio
    async def test_cancelled_error_exits_loop(self) -> None:
        """asyncio.CancelledError breaks the while loop cleanly."""
        ch = _FakeChannel()
        mgr = ChannelManager(channels=[ch])
        cq: asyncio.PriorityQueue = asyncio.PriorityQueue()
        mgr._command_queues["test"] = cq
        router = CommandRouter(task_tracker=None, runner=None)
        mgr.set_command_router(router)

        loop_task = asyncio.create_task(mgr._consume_command_loop("test"))
        # Let the loop start and block on cq.get()
        await asyncio.sleep(0.02)

        loop_task.cancel()
        # The loop catches CancelledError and breaks cleanly, so the task
        # should complete without raising.
        await loop_task
        assert loop_task.done()


class TestConsumeCommandLoopEdgeCases:
    """Edge cases: no queue, no router, missing channel."""

    @pytest.mark.asyncio
    async def test_no_command_queue_returns_immediately(self) -> None:
        """If no command queue exists for channel_id, loop returns."""
        ch = _FakeChannel()
        mgr = ChannelManager(channels=[ch])
        # Don't set up _command_queues for "test"
        # Should return immediately without error
        await mgr._consume_command_loop("test")

    @pytest.mark.asyncio
    async def test_no_router_logs_warning_and_continues(self) -> None:
        """If no command router is set, items are skipped."""
        ch = _FakeChannel()
        mgr = ChannelManager(channels=[ch])
        cq: asyncio.PriorityQueue = asyncio.PriorityQueue()
        mgr._command_queues["test"] = cq
        # No router set

        item = PrioritizedPayload(
            priority=CommandPriority.LOW,
            sequence=1,
            payload={"text": "/status"},
            command_name="status",
            command_args=[],
        )
        await cq.put(item)

        loop_task = asyncio.create_task(mgr._consume_command_loop("test"))
        await asyncio.sleep(0.05)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Nothing sent since no router
        assert len(ch.sent) == 0


class TestExtractMsgText:
    """Tests for the _extract_msg_text static helper."""

    def test_text_block_content(self) -> None:
        msg = Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text="hello")],
        )
        assert ChannelManager._extract_msg_text(msg) == "hello"

    def test_string_content(self) -> None:
        msg = MagicMock()
        msg.content = "plain string"
        assert ChannelManager._extract_msg_text(msg) == "plain string"

    def test_empty_content(self) -> None:
        msg = MagicMock()
        msg.content = None
        assert ChannelManager._extract_msg_text(msg) == ""

    def test_list_with_no_text_block(self) -> None:
        msg = MagicMock()
        msg.content = [{"type": "image", "url": "http://example.com"}]
        assert ChannelManager._extract_msg_text(msg) == ""
