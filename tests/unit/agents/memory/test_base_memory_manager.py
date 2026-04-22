# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Tests for BaseMemoryManager abstract base class."""
import asyncio
from unittest.mock import MagicMock

import pytest

# agentscope is installed — no sys.modules override needed.
# reme is TYPE_CHECKING only in base_memory_manager, also no mock needed.


# ---------------------------------------------------------------------------
# Concrete subclass for testing the abstract base
# ---------------------------------------------------------------------------


def _make_concrete_class():
    """Return a minimal concrete subclass of BaseMemoryManager."""
    from qwenpaw.agents.memory.base_memory_manager import (
        BaseMemoryManager,
    )

    class ConcreteMemoryManager(BaseMemoryManager):
        async def start(self):
            pass

        async def close(self):
            return True

        def get_memory_prompt(self, language: str = "zh") -> str:
            return ""

        def list_memory_tools(self):
            return []

        # Compat: older installed versions declare these as abstract too
        async def compact_tool_result(self, **_kwargs):
            pass

        async def check_context(self, **_kwargs):
            return ([], [], True)

        async def compact_memory(self, messages, **_kwargs):
            return ""

        async def summary_memory(self, messages, **_kwargs):
            return ""

        async def memory_search(self, query, **_kwargs):
            return None

        def get_in_memory_memory(self, **_kwargs):
            return None

    return ConcreteMemoryManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager_class():
    return _make_concrete_class()


@pytest.fixture
def manager(manager_class, tmp_path):
    return manager_class(
        working_dir=str(tmp_path),
        agent_id="test-agent",
    )


# ---------------------------------------------------------------------------
# TestBaseMemoryManagerInit
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerInit:
    """P0: Initialization tests for BaseMemoryManager."""

    def test_working_dir_is_stored(self, manager, tmp_path):
        assert manager.working_dir == str(tmp_path)

    def test_agent_id_is_stored(self, manager):
        assert manager.agent_id == "test-agent"

    def test_chat_model_is_none_initially(self, manager):
        assert manager.chat_model is None

    def test_formatter_is_none_initially(self, manager):
        assert manager.formatter is None

    def test_summary_tasks_starts_empty(self, manager):
        assert manager.summary_tasks == []


# ---------------------------------------------------------------------------
# TestBaseMemoryManagerAddAsyncSummaryTask
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerAddAsyncSummaryTask:
    """P1: Tests for add_async_summary_task."""

    async def test_adds_task_to_list(self, manager):
        """Adding a task appends it to summary_tasks."""
        msgs = [MagicMock()]
        manager.add_async_summary_task(msgs)
        assert len(manager.summary_tasks) == 1
        # Clean up the created task
        for t in manager.summary_tasks:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    async def test_completed_tasks_are_pruned(self, manager):
        """Done tasks are removed from the list before adding new one."""
        # Create a completed task
        done_task = asyncio.create_task(
            asyncio.sleep(0),
        )
        await done_task  # let it finish
        manager.summary_tasks = [done_task]

        msgs = [MagicMock()]
        manager.add_async_summary_task(msgs)

        # The done task is removed; only the new task remains
        assert len(manager.summary_tasks) == 1

    async def test_pending_tasks_are_kept(self, manager):
        """Pending tasks remain in the list."""

        async def never_done():
            await asyncio.sleep(9999)

        pending = asyncio.create_task(never_done())
        manager.summary_tasks = [pending]

        msgs = [MagicMock()]
        manager.add_async_summary_task(msgs)

        # pending kept + new task added
        assert len(manager.summary_tasks) == 2
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass

    async def test_failed_task_is_pruned_and_logged(
        self,
        manager,
        caplog,
    ):
        """Tasks that raised exceptions are pruned."""

        async def failing():
            raise ValueError("boom")

        failed = asyncio.create_task(failing())
        try:
            await failed
        except ValueError:
            pass

        import logging

        with caplog.at_level(logging.ERROR):
            manager.add_async_summary_task([MagicMock()])

        assert len(manager.summary_tasks) == 1

    async def test_cancelled_task_logs_warning(
        self,
        manager,
        caplog,
    ):
        """Cancelled tasks are pruned with a warning log."""

        async def sleeper():
            await asyncio.sleep(9999)

        task = asyncio.create_task(sleeper())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        import logging

        with caplog.at_level(logging.WARNING):
            manager.add_async_summary_task([MagicMock()])

        assert len(manager.summary_tasks) == 1


# ---------------------------------------------------------------------------
# TestBaseMemoryManagerAwaitSummaryTasks
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerAwaitSummaryTasks:
    """P1: Tests for await_summary_tasks."""

    async def test_returns_empty_string_when_no_tasks(
        self,
        manager,
    ):
        result = await manager.await_summary_tasks()
        assert result == ""
        assert manager.summary_tasks == []

    async def test_collects_result_of_completed_task(
        self,
        manager,
    ):
        """Successfully completed tasks yield 'completed' message."""

        async def quick():
            return "done"

        task = asyncio.create_task(quick())
        await task
        manager.summary_tasks = [task]

        result = await manager.await_summary_tasks()
        assert "Summary task completed: done" in result
        assert manager.summary_tasks == []

    async def test_collects_result_of_running_task(self, manager):
        """Pending tasks are awaited and result collected."""

        async def quick():
            return "pending_result"

        task = asyncio.create_task(quick())
        # Do NOT await — let await_summary_tasks do it
        manager.summary_tasks = [task]

        result = await manager.await_summary_tasks()
        assert "pending_result" in result
        assert manager.summary_tasks == []

    async def test_handles_cancelled_task_already_done(
        self,
        manager,
    ):
        """Already-cancelled done tasks produce cancellation message."""

        async def sleeper():
            await asyncio.sleep(9999)

        task = asyncio.create_task(sleeper())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        manager.summary_tasks = [task]
        result = await manager.await_summary_tasks()
        assert "cancelled" in result.lower()
        assert manager.summary_tasks == []

    async def test_handles_failed_task_already_done(self, manager):
        """Already-failed done tasks produce failure message."""

        async def boom():
            raise RuntimeError("failure")

        task = asyncio.create_task(boom())
        try:
            await task
        except RuntimeError:
            pass

        manager.summary_tasks = [task]
        result = await manager.await_summary_tasks()
        assert "failed" in result.lower()
        assert manager.summary_tasks == []

    async def test_handles_running_task_that_raises(self, manager):
        """Running tasks that raise an exception produce failure msg."""

        async def boom():
            raise ValueError("runtime error")

        task = asyncio.create_task(boom())
        manager.summary_tasks = [task]

        result = await manager.await_summary_tasks()
        assert "failed" in result.lower()
        assert manager.summary_tasks == []

    async def test_clears_tasks_after_await(self, manager):
        """summary_tasks is always cleared after await_summary_tasks."""

        async def quick():
            return "x"

        task = asyncio.create_task(quick())
        manager.summary_tasks = [task]
        await manager.await_summary_tasks()
        assert manager.summary_tasks == []

    async def test_multiple_tasks_all_collected(self, manager):
        """Multiple tasks are all awaited and results concatenated."""

        async def t1():
            return "r1"

        async def t2():
            return "r2"

        tasks = [
            asyncio.create_task(t1()),
            asyncio.create_task(t2()),
        ]
        manager.summary_tasks = tasks
        result = await manager.await_summary_tasks()
        assert "r1" in result
        assert "r2" in result
        assert manager.summary_tasks == []
