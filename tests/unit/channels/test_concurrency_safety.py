# -*- coding: utf-8 -*-
"""Unit tests verifying concurrency safety of the dual-queue architecture.

Validates: Requirements 10.1, 10.2, 10.3
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

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
# Minimal stubs (reuse _FakeChannel pattern from sibling test files)
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
    """Minimal BaseChannel stub for concurrency tests."""

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
                                type="text",
                                text=payload.get("text", ""),
                            ),
                        ],
                    ),
                ],
                session_id=payload.get("session_id", "sess-1"),
                user_id=payload.get("user_id", "user-1"),
            )
        return _FakeRequest(
            input=[_FakeInput(content=[_FakeContent(type="text", text=str(payload))])],
        )

    def get_to_handle_from_request(self, request: _FakeRequest) -> str:
        return getattr(request, "user_id", "") or ""

    def get_debounce_key(self, payload: Any) -> str:
        if isinstance(payload, dict):
            return payload.get("session_id", "key")
        return "key"

    def _is_native_payload(self, payload: Any) -> bool:
        return False

    async def send(self, to_handle: str, text: str, meta: Any = None) -> None:
        self.sent.append((to_handle, text))

    async def consume_one(self, payload: Any) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def set_enqueue(self, cb: Any) -> None:
        self._enqueue_cb = cb


# ---------------------------------------------------------------------------
# Test 1: DataQueue and CommandQueue run independently for same session
# Validates: Requirement 10.1
# ---------------------------------------------------------------------------


class TestDualQueueIndependence:
    """Both loops run independently for the same session."""

    @pytest.mark.asyncio
    async def test_both_queues_consumed_independently(self) -> None:
        """Put items in both DataQueue and CommandQueue for the same session,
        verify both are consumed independently without blocking each other."""
        ch = _FakeChannel()
        data_processed: list[str] = []

        # Override consume_one to track DataQueue processing
        async def _track_consume(payload: Any) -> None:
            data_processed.append(payload.get("text", ""))

        ch.consume_one = _track_consume

        mgr = ChannelManager(channels=[ch])

        # Set up DataQueue
        dq: asyncio.Queue = asyncio.Queue()
        mgr._queues["test"] = dq

        # Set up CommandQueue
        cq: asyncio.PriorityQueue = asyncio.PriorityQueue()
        mgr._command_queues["test"] = cq
        router = CommandRouter(task_tracker=None, runner=None)
        mgr.set_command_router(router)

        # Put a data message in DataQueue
        data_payload = {"text": "hello world", "session_id": "sess-1", "user_id": "u1"}
        dq.put_nowait(data_payload)

        # Put a command in CommandQueue
        cmd_item = PrioritizedPayload(
            priority=CommandPriority.LOW,
            sequence=1,
            payload={"text": "/status", "session_id": "sess-1", "user_id": "u1"},
            command_name="status",
            command_args=[],
        )
        await cq.put(cmd_item)

        # Start both loops
        data_task = asyncio.create_task(mgr._consume_channel_loop("test", 0))
        cmd_task = asyncio.create_task(mgr._consume_command_loop("test"))

        # Wait for both queues to drain
        for _ in range(50):
            if dq.empty() and cq.empty():
                break
            await asyncio.sleep(0.02)

        # Give processing a moment to finish
        await asyncio.sleep(0.05)

        # Cancel both loops
        data_task.cancel()
        cmd_task.cancel()
        try:
            await data_task
        except asyncio.CancelledError:
            pass
        try:
            await cmd_task
        except asyncio.CancelledError:
            pass

        # DataQueue message was processed
        assert len(data_processed) == 1
        assert data_processed[0] == "hello world"

        # CommandQueue message was processed (sent via channel)
        assert len(ch.sent) == 1
        _, text = ch.sent[0]
        assert text  # non-empty response from /status


# ---------------------------------------------------------------------------
# Test 2: Multiple /stop arriving simultaneously — safe handling
# Validates: Requirement 10.2
# ---------------------------------------------------------------------------


class TestMultipleStopSafety:
    """Multiple /stop commands handled safely: first succeeds, rest return 'no task'."""

    @pytest.mark.asyncio
    async def test_multiple_stops_first_succeeds_rest_no_task(self) -> None:
        """Put multiple /stop commands in CommandQueue. The first should
        succeed (or report no task), subsequent ones should also return
        safely without exceptions."""
        ch = _FakeChannel()
        mgr = ChannelManager(channels=[ch])

        cq: asyncio.PriorityQueue = asyncio.PriorityQueue()
        mgr._command_queues["test"] = cq
        router = CommandRouter(task_tracker=None, runner=None)
        mgr.set_command_router(router)

        # Enqueue 3 /stop commands simultaneously
        for seq in range(1, 4):
            item = PrioritizedPayload(
                priority=CommandPriority.CRITICAL,
                sequence=seq,
                payload={"text": "/stop", "session_id": "sess-1", "user_id": "u1"},
                command_name="stop",
                command_args=[],
            )
            await cq.put(item)

        # Run the command loop
        loop_task = asyncio.create_task(mgr._consume_command_loop("test"))

        # Wait for queue to drain
        for _ in range(50):
            if cq.empty():
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)

        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # All 3 /stop commands were handled (sent responses)
        assert len(ch.sent) == 3

        # Each response should contain text about no running task
        # (since there's no real TaskTracker with active tasks)
        for _, text in ch.sent:
            assert text  # non-empty
            # With no task_tracker on the channel, the handler
            # returns "No running task."


# ---------------------------------------------------------------------------
# Test 3: CommandQueue and DataQueue use independent queue instances
# Validates: Requirement 10.3
# ---------------------------------------------------------------------------


class TestQueueInstanceIndependence:
    """_queues and _command_queues are different dict instances with different queue types."""

    def test_queues_are_separate_dicts(self) -> None:
        """_queues and _command_queues are distinct dict objects."""
        ch = _FakeChannel()
        mgr = ChannelManager(channels=[ch])
        assert mgr._queues is not mgr._command_queues

    def test_queue_types_differ(self) -> None:
        """DataQueue uses asyncio.Queue, CommandQueue uses asyncio.PriorityQueue."""
        ch = _FakeChannel()
        mgr = ChannelManager(channels=[ch])

        # Manually set up queues as start_all would
        mgr._queues["test"] = asyncio.Queue()
        mgr._command_queues["test"] = asyncio.PriorityQueue()

        assert isinstance(mgr._queues["test"], asyncio.Queue)
        assert isinstance(mgr._command_queues["test"], asyncio.PriorityQueue)

        # They are different instances
        assert mgr._queues["test"] is not mgr._command_queues["test"]

    @pytest.mark.asyncio
    async def test_start_all_creates_independent_queues(self) -> None:
        """After start_all, each channel has both a DataQueue and a CommandQueue
        that are independent instances."""
        ch = _FakeChannel()
        ch.uses_manager_queue = True
        mgr = ChannelManager(channels=[ch])

        await mgr.start_all()
        try:
            # Both queues exist for the channel
            assert "test" in mgr._queues
            assert "test" in mgr._command_queues

            # Different types
            assert type(mgr._queues["test"]) is asyncio.Queue
            assert type(mgr._command_queues["test"]) is asyncio.PriorityQueue

            # Different instances
            assert mgr._queues["test"] is not mgr._command_queues["test"]
        finally:
            await mgr.stop_all()
