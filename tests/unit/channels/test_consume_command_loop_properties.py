# -*- coding: utf-8 -*-
"""Property-based tests for _consume_command_loop ordering and error recovery.

Feature: dual-queue-messaging

Properties tested:
- Property 2: 优先级排序 (Priority Ordering)
- Property 3: 同优先级 FIFO (Same-Priority FIFO)
- Property 4: 命令消费循环错误恢复 (Command Consume Loop Error Recovery)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agentscope.message import Msg, TextBlock

from copaw.app.channels.manager import ChannelManager
from copaw.app.runner.command_router import (
    CommandContext,
    CommandPriority,
    CommandRouter,
    PrioritizedPayload,
)


# ---------------------------------------------------------------------------
# Minimal stubs (reuse _FakeChannel pattern from test_consume_command_loop.py)
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
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Priority values as integers (0-3)
priority_st = st.sampled_from(
    [
        CommandPriority.CRITICAL,
        CommandPriority.HIGH,
        CommandPriority.NORMAL,
        CommandPriority.LOW,
    ]
)

# Generate a list of (priority, command_name) tuples with 2-20 items
# Each item gets a unique command name to track ordering
commands_with_priorities_st = st.lists(
    st.tuples(
        priority_st,
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll",)),
            min_size=3,
            max_size=10,
        ),
    ),
    min_size=2,
    max_size=20,
    unique_by=lambda t: t[1],
)

# Same-priority commands: a single priority + list of unique command names
same_priority_commands_st = st.tuples(
    priority_st,
    st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll",)),
            min_size=3,
            max_size=10,
        ),
        min_size=2,
        max_size=20,
        unique=True,
    ),
)

# Error recovery: list of (command_name, should_fail) pairs
error_recovery_commands_st = st.lists(
    st.tuples(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll",)),
            min_size=3,
            max_size=10,
        ),
        st.booleans(),
    ),
    min_size=2,
    max_size=15,
    unique_by=lambda t: t[0],
)


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 2: 优先级排序
# ---------------------------------------------------------------------------
class TestPriorityOrdering:
    """Property 2: Priority Ordering.

    For any set of commands with different CommandPriority values placed
    simultaneously into the CommandQueue, _consume_command_loop SHALL
    process them in strictly ascending priority order (CRITICAL < HIGH
    < NORMAL < LOW).

    **Validates: Requirements 2.3, 5.2**
    """

    @given(commands=commands_with_priorities_st)
    @settings(max_examples=100)
    def test_priority_queue_ordering(
        self, commands: list[tuple[int, str]]
    ) -> None:
        """PrioritizedPayload items are dequeued in priority
        order (lowest number first).

        Label: Feature: dual-queue-messaging, Property 2: 优先级排序
        """
        q: asyncio.PriorityQueue = asyncio.PriorityQueue()

        # Put all items with sequential sequence numbers
        items = []
        for seq, (prio, name) in enumerate(commands):
            item = PrioritizedPayload(
                priority=prio,
                sequence=seq,
                payload={"text": f"/{name}"},
                command_name=name,
                command_args=[],
            )
            items.append(item)
            q.put_nowait(item)

        # Dequeue all items and verify ordering
        dequeued: list[PrioritizedPayload] = []
        while not q.empty():
            dequeued.append(q.get_nowait())

        # Verify strict priority ordering: each item's (priority, sequence)
        # must be <= the next item's (priority, sequence)
        for i in range(len(dequeued) - 1):
            curr = dequeued[i]
            nxt = dequeued[i + 1]
            assert (curr.priority, curr.sequence) <= (
                nxt.priority,
                nxt.sequence,
            ), (
                f"Item {i} (priority={curr.priority}, seq={curr.sequence}, "
                f"cmd={curr.command_name}) should come before item {i + 1} "
                f"(priority={nxt.priority}, seq={nxt.sequence}, "
                f"cmd={nxt.command_name})"
            )

    @given(commands=commands_with_priorities_st)
    @settings(max_examples=100)
    def test_consume_loop_processes_in_priority_order(
        self,
        commands: list[tuple[int, str]],
    ) -> None:
        """_consume_command_loop processes commands in priority
        order via the full loop.

        Label: Feature: dual-queue-messaging, Property 2: 优先级排序
        """
        processed_order: list[str] = []

        router = CommandRouter(task_tracker=None, runner=None)

        # Register all commands with a tracking handler
        for prio, name in commands:

            async def _handler(ctx: CommandContext, _n: str = name) -> Msg:
                processed_order.append(_n)
                return Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text=f"ok:{_n}")],
                )

            router.register_command(name, _handler, CommandPriority(prio))

        # Build PrioritizedPayload items with sequential sequence numbers
        items = []
        for seq, (prio, name) in enumerate(commands):
            items.append(
                PrioritizedPayload(
                    priority=prio,
                    sequence=seq,
                    payload={
                        "text": f"/{name}",
                        "session_id": "s1",
                        "user_id": "u1",
                    },
                    command_name=name,
                    command_args=[],
                )
            )

        ch = _FakeChannel()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_loop_with_items(items, ch, router))
        finally:
            loop.close()

        # Verify: processed order must be sorted by (priority, sequence)
        expected_order = [
            name
            for _, name in sorted(
                zip(
                    [(p, s) for s, (p, _) in enumerate(commands)],
                    [name for _, name in commands],
                ),
                key=lambda x: x[0],
            )
        ]
        # Simpler: just sort commands by (priority, original_index)
        indexed = [
            (prio, seq, name) for seq, (prio, name) in enumerate(commands)
        ]
        indexed.sort(key=lambda x: (x[0], x[1]))
        expected_order = [name for _, _, name in indexed]

        assert (
            processed_order == expected_order
        ), f"Expected order {expected_order}, got {processed_order}"


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 3: 同优先级 FIFO
# ---------------------------------------------------------------------------
class TestSamePriorityFIFO:
    """Property 3: Same-Priority FIFO.

    For any set of commands with the same CommandPriority placed into
    the CommandQueue in sequence, _consume_command_loop SHALL process
    them in the exact order they were enqueued (FIFO).

    **Validates: Requirements 2.7, 5.3**
    """

    @given(data=same_priority_commands_st)
    @settings(max_examples=100)
    def test_same_priority_fifo_at_queue_level(
        self,
        data: tuple[int, list[str]],
    ) -> None:
        """Same-priority items are dequeued in FIFO (sequence) order.

        Label: Feature: dual-queue-messaging, Property 3: 同优先级 FIFO
        """
        prio, names = data
        q: asyncio.PriorityQueue = asyncio.PriorityQueue()

        for seq, name in enumerate(names):
            item = PrioritizedPayload(
                priority=prio,
                sequence=seq,
                payload={"text": f"/{name}"},
                command_name=name,
                command_args=[],
            )
            q.put_nowait(item)

        dequeued_names: list[str] = []
        while not q.empty():
            item = q.get_nowait()
            dequeued_names.append(item.command_name)

        assert (
            dequeued_names == names
        ), f"Expected FIFO order {names}, got {dequeued_names}"

    @given(data=same_priority_commands_st)
    @settings(max_examples=100)
    def test_consume_loop_fifo_for_same_priority(
        self,
        data: tuple[int, list[str]],
    ) -> None:
        """_consume_command_loop preserves FIFO for same-priority commands.

        Label: Feature: dual-queue-messaging, Property 3: 同优先级 FIFO
        """
        prio, names = data
        processed_order: list[str] = []

        router = CommandRouter(task_tracker=None, runner=None)

        for name in names:

            async def _handler(ctx: CommandContext, _n: str = name) -> Msg:
                processed_order.append(_n)
                return Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text=f"ok:{_n}")],
                )

            router.register_command(name, _handler, CommandPriority(prio))

        items = []
        for seq, name in enumerate(names):
            items.append(
                PrioritizedPayload(
                    priority=prio,
                    sequence=seq,
                    payload={
                        "text": f"/{name}",
                        "session_id": "s1",
                        "user_id": "u1",
                    },
                    command_name=name,
                    command_args=[],
                )
            )

        ch = _FakeChannel()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_loop_with_items(items, ch, router))
        finally:
            loop.close()

        assert (
            processed_order == names
        ), f"Expected FIFO order {names}, got {processed_order}"


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 4: 命令消费循环错误恢复
# ---------------------------------------------------------------------------
class TestCommandConsumeLoopErrorRecovery:
    """Property 4: Command Consume Loop Error Recovery.

    For any command sequence where handlers at random positions throw
    exceptions, _consume_command_loop SHALL catch each exception, log
    the error, and continue processing subsequent commands without
    interrupting the consume loop.

    **Validates: Requirement 2.6**
    """

    @given(commands=error_recovery_commands_st)
    @settings(max_examples=100)
    def test_error_recovery_continues_processing(
        self,
        commands: list[tuple[str, bool]],
    ) -> None:
        """Commands after a failing handler are still processed.

        Label: Feature: dual-queue-messaging, Property 4: 命令消费循环错误恢复
        """
        processed: list[str] = []
        failed: list[str] = []

        router = CommandRouter(task_tracker=None, runner=None)

        for name, should_fail in commands:

            async def _handler(
                ctx: CommandContext,
                _n: str = name,
                _fail: bool = should_fail,
            ) -> Msg:
                if _fail:
                    failed.append(_n)
                    raise RuntimeError(f"simulated failure in /{_n}")
                processed.append(_n)
                return Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text=f"ok:{_n}")],
                )

            router.register_command(name, _handler, CommandPriority.NORMAL)

        items = []
        for seq, (name, _) in enumerate(commands):
            items.append(
                PrioritizedPayload(
                    priority=CommandPriority.NORMAL,
                    sequence=seq,
                    payload={
                        "text": f"/{name}",
                        "session_id": "s1",
                        "user_id": "u1",
                    },
                    command_name=name,
                    command_args=[],
                )
            )

        ch = _FakeChannel()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_loop_with_items(items, ch, router))
        finally:
            loop.close()

        # All non-failing commands should have been processed
        expected_processed = [name for name, fail in commands if not fail]
        expected_failed = [name for name, fail in commands if fail]

        assert (
            processed == expected_processed
        ), f"Expected processed {expected_processed}, got {processed}"
        assert (
            failed == expected_failed
        ), f"Expected failed {expected_failed}, got {failed}"

        # Total dispatched = processed + failed = all commands
        assert len(processed) + len(failed) == len(commands), (
            f"Not all commands were dispatched: "
            f"processed={len(processed)}, failed={len(failed)}, "
            f"total={len(commands)}"
        )

    @given(
        num_before=st.integers(min_value=0, max_value=5),
        num_after=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=100)
    def test_commands_after_failure_are_processed(
        self,
        num_before: int,
        num_after: int,
    ) -> None:
        """Commands enqueued after a failing command are still processed.

        Label: Feature: dual-queue-messaging, Property 4: 命令消费循环错误恢复
        """
        processed: list[str] = []

        router = CommandRouter(task_tracker=None, runner=None)

        all_names: list[str] = []
        fail_index = num_before  # The command at this index will fail

        for i in range(num_before + 1 + num_after):
            name = f"cmd{i}"
            all_names.append(name)
            if i == fail_index:

                async def _fail_handler(ctx: CommandContext) -> Msg:
                    raise RuntimeError("boom")

                router.register_command(
                    name, _fail_handler, CommandPriority.NORMAL
                )
            else:

                async def _ok_handler(
                    ctx: CommandContext, _n: str = name
                ) -> Msg:
                    processed.append(_n)
                    return Msg(
                        name="Friday",
                        role="assistant",
                        content=[TextBlock(type="text", text=f"ok:{_n}")],
                    )

                router.register_command(
                    name, _ok_handler, CommandPriority.NORMAL
                )

        items = []
        for seq, name in enumerate(all_names):
            items.append(
                PrioritizedPayload(
                    priority=CommandPriority.NORMAL,
                    sequence=seq,
                    payload={
                        "text": f"/{name}",
                        "session_id": "s1",
                        "user_id": "u1",
                    },
                    command_name=name,
                    command_args=[],
                )
            )

        ch = _FakeChannel()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_loop_with_items(items, ch, router))
        finally:
            loop.close()

        # All commands except the failing one should be processed
        expected = [n for i, n in enumerate(all_names) if i != fail_index]
        assert processed == expected, (
            f"Expected {expected}, got {processed}. "
            f"Failure at index {fail_index} should not block "
            f"subsequent commands."
        )
