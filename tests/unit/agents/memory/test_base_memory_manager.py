# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Tests for BaseMemoryManager abstract base class."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.memory import base_memory_manager
from qwenpaw.constant import AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY

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

        def get_memory_prompt(self) -> str:
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

        async def auto_memory(self, messages, **_kwargs):
            return ""

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

    def test_auto_memory_task_info_starts_empty(self, manager):
        assert manager._auto_memory_task_info == {}

    def test_task_counter_starts_at_zero(self, manager):
        assert manager._task_counter == 0

    def test_auto_memory_worker_task_is_none_initially(self, manager):
        assert manager._auto_memory_worker_task is None

    async def test_close_stops_worker_before_backend(self, manager):
        manager._shutdown_auto_memory_worker = AsyncMock(return_value=True)
        manager._close_backend = AsyncMock(return_value=True)

        assert await manager.close() is True
        manager._shutdown_auto_memory_worker.assert_awaited_once_with()
        manager._close_backend.assert_awaited_once_with()


# ---------------------------------------------------------------------------
# TestBaseMemoryManagerSubmitAutoMemory
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerSubmitAutoMemory:
    """P1: Tests for submit_auto_memory."""

    async def test_adds_task_info_entry(self, manager):
        """Scheduling a task creates an entry in _auto_memory_task_info."""
        msgs = [MagicMock()]
        manager.submit_auto_memory(msgs)
        assert len(manager._auto_memory_task_info) == 1
        if manager._auto_memory_worker_task:
            manager._auto_memory_worker_task.cancel()
            try:
                await manager._auto_memory_worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_task_starts_as_pending(self, manager):
        """New task has status 'pending'."""
        manager.submit_auto_memory([MagicMock()])
        info = list(manager._auto_memory_task_info.values())[0]
        assert info["status"] == "pending"
        if manager._auto_memory_worker_task:
            manager._auto_memory_worker_task.cancel()
            try:
                await manager._auto_memory_worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_counter_increments_per_task(self, manager):
        """Each call increments the task counter."""
        manager.submit_auto_memory([MagicMock()])
        manager.submit_auto_memory([MagicMock()])
        assert manager._task_counter == 2
        if manager._auto_memory_worker_task:
            manager._auto_memory_worker_task.cancel()
            try:
                await manager._auto_memory_worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_auto_memory_worker_task_created(self, manager):
        """Scheduling a task starts the background worker."""
        manager.submit_auto_memory([MagicMock()])
        assert manager._auto_memory_worker_task is not None
        if manager._auto_memory_worker_task:
            manager._auto_memory_worker_task.cancel()
            try:
                await manager._auto_memory_worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_task_info_does_not_retain_worker(self, manager):
        manager.submit_auto_memory([MagicMock()])

        info = next(iter(manager._auto_memory_task_info.values()))
        assert "task" not in info

        await manager._shutdown_auto_memory_worker()

    async def test_keeps_only_latest_terminal_tasks(
        self,
        manager,
        monkeypatch,
    ):
        monkeypatch.setattr(
            base_memory_manager,
            "MAX_AUTO_MEMORY_TASK_HISTORY",
            2,
        )
        completed = asyncio.Event()
        calls = 0

        async def auto_memory(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                completed.set()
            return f"result-{calls}"

        manager.auto_memory = auto_memory
        for _ in range(3):
            manager.submit_auto_memory([MagicMock()])

        await asyncio.wait_for(completed.wait(), timeout=1)
        await asyncio.sleep(0)

        assert list(manager._auto_memory_task_info) == ["task_2", "task_3"]
        await manager._shutdown_auto_memory_worker()

    def test_pruning_keeps_non_terminal_tasks(self, manager, monkeypatch):
        monkeypatch.setattr(
            base_memory_manager,
            "MAX_AUTO_MEMORY_TASK_HISTORY",
            1,
        )
        manager._auto_memory_task_info = {
            "task_1": {"status": "completed"},
            "task_2": {"status": "running"},
            "task_3": {"status": "failed"},
            "task_4": {"status": "pending"},
        }

        manager._prune_auto_memory_task_info()

        assert list(manager._auto_memory_task_info) == [
            "task_2",
            "task_3",
            "task_4",
        ]

    async def test_shutdown_exits_when_nested_call_swallows_cancellation(
        self,
        manager,
    ):
        """A swallowed cancellation must not send the worker back to get()."""
        started = asyncio.Event()

        async def swallow_cancellation(*_args, **_kwargs):
            started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return "completed after cancellation"

        manager.auto_memory = swallow_cancellation
        manager.submit_auto_memory([MagicMock()])
        await started.wait()

        stopped = await manager._shutdown_auto_memory_worker(timeout=0.5)

        assert stopped is True
        assert manager._auto_memory_worker_task is None

    async def test_shutdown_drains_queued_work_before_stopping(self, manager):
        started = asyncio.Event()
        release = asyncio.Event()
        completed: list[str] = []

        async def auto_memory(messages, **_kwargs):
            started.set()
            await release.wait()
            completed.append(messages[0])
            return "saved"

        manager.auto_memory = auto_memory
        manager.submit_auto_memory(["first"])
        manager.submit_auto_memory(["second"])
        await started.wait()

        shutdown = asyncio.create_task(
            manager._shutdown_auto_memory_worker(timeout=0.5),
        )
        await asyncio.sleep(0)
        assert not shutdown.done()

        release.set()
        assert await shutdown is True
        assert completed == ["first", "second"]
        assert manager._auto_memory_worker_task is None

    async def test_submit_rejected_while_worker_is_shutting_down(
        self,
        manager,
    ):
        manager._auto_memory_worker_stopping = True

        with pytest.raises(RuntimeError, match="shutting down"):
            manager.submit_auto_memory([MagicMock()])

    async def test_shutdown_timeout_cancels_active_and_queued_work(
        self,
        manager,
    ):
        started = asyncio.Event()

        async def blocked_auto_memory(*_args, **_kwargs):
            started.set()
            await asyncio.sleep(3600)

        manager.auto_memory = blocked_auto_memory
        manager.submit_auto_memory([MagicMock()])
        manager.submit_auto_memory([MagicMock()])
        await started.wait()

        stopped = await manager._shutdown_auto_memory_worker(timeout=0.01)

        assert stopped is True
        assert manager._auto_memory_task_queue.empty()
        assert {
            info["status"] for info in manager._auto_memory_task_info.values()
        } == {"cancelled"}

    async def test_shutdown_timeout_is_bounded(self, manager):
        """Repeated cancellation suppression cannot hang close."""
        keep_running = asyncio.Event()
        started = asyncio.Event()

        async def ignore_cancellation():
            started.set()
            while not keep_running.is_set():
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    continue

        worker = asyncio.create_task(ignore_cancellation())
        manager._auto_memory_worker_task = worker
        await started.wait()

        stopped = await manager._shutdown_auto_memory_worker(timeout=0.01)

        assert stopped is False
        keep_running.set()
        worker.cancel()
        await asyncio.wait({worker}, timeout=0.5)

    def test_runtime_status_includes_bounded_auto_memory_tasks(
        self,
        manager,
    ):
        manager.get_auto_memory_interval = MagicMock(return_value=5)
        long_result = "r" * (base_memory_manager.MAX_RUNTIME_RESULT_CHARS + 10)
        manager._auto_memory_task_info = {
            "task_1": {
                "task_id": "task_1",
                "status": "completed",
                "start_time": base_memory_manager.datetime(
                    2026,
                    8,
                    9,
                    23,
                    59,
                    tzinfo=base_memory_manager.timezone.utc,
                ),
                "finished_at": base_memory_manager.datetime(
                    2026,
                    8,
                    10,
                    tzinfo=base_memory_manager.timezone.utc,
                ),
                "message_count": 4,
                "result": long_result,
            },
            "task_2": {
                "task_id": "task_2",
                "status": "failed",
                "start_time": base_memory_manager.datetime(
                    2026,
                    8,
                    10,
                    0,
                    59,
                    tzinfo=base_memory_manager.timezone.utc,
                ),
                "finished_at": base_memory_manager.datetime(
                    2026,
                    8,
                    10,
                    1,
                    tzinfo=base_memory_manager.timezone.utc,
                ),
                "error": "e" * 250,
                "message_count": 2,
            },
        }

        status = manager.get_runtime_status()

        assert status["worker"]["status"] == "idle"
        assert status["auto_memory"] == {
            "enabled": True,
            "interval": 5,
        }
        assert status["tasks"] == [
            {
                "task_id": "task_2",
                "status": "failed",
                "queued_at": "2026-08-10T00:59:00+00:00",
                "finished_at": "2026-08-10T01:00:00+00:00",
                "message_count": 2,
                "trigger": "manual",
                "result": None,
                "error": "e" * 240,
            },
            {
                "task_id": "task_1",
                "status": "completed",
                "queued_at": "2026-08-09T23:59:00+00:00",
                "finished_at": "2026-08-10T00:00:00+00:00",
                "message_count": 4,
                "trigger": "manual",
                "result": long_result[
                    : base_memory_manager.MAX_RUNTIME_RESULT_CHARS
                ],
                "error": None,
            },
        ]
        assert status["recent"]["last_error"] == "e" * 240


class TestAutoMemorySearchSanitization:
    """P1: auto_memory input should exclude auto-search blocks only."""

    def test_build_query_uses_latest_user_message_only(self, manager):
        messages = [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="NVDA 股价")],
            ),
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        text=("达股价查询：NVDA $195.93 (+0.56%)，" "市值 $4.746T"),
                    ),
                ],
            ),
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="台积电股价")],
            ),
        ]

        assert manager._build_query(messages) == "台积电股价"

    def test_build_query_truncates_long_user_message(self, manager):
        long_text = "a" * 60
        messages = [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text=long_text)],
            ),
        ]

        assert manager._build_query(messages) == "a" * 50

    def test_build_query_returns_empty_without_user_text(self, manager):
        messages = [
            Msg(
                name="assistant",
                role="assistant",
                content=[TextBlock(text="memory noise")],
            ),
        ]

        assert manager._build_query(messages) == ""

    def test_builds_mock_assistant_msg_with_configured_estimated_usage(
        self,
        manager,
    ):
        msg = manager._build_auto_memory_search_msg(
            query="hello",
            max_results=2,
            text="remembered fact",
            estimate_divisor=2,
        )

        assert msg.role == "assistant"
        assert msg.name == "memory_search"
        assert msg.usage is not None
        assert msg.usage.input_tokens > 0
        assert msg.usage.output_tokens == 0
        assert msg.metadata[AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY] == [
            block.id for block in msg.content
        ]
        assert msg.metadata["auto_memory_search_usage"] == {
            "estimated": True,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": 0,
            "estimate_divisor": 2,
        }

    def test_build_message_uses_in_memory_default_without_config_io(
        self,
        manager,
    ):
        manager._get_token_estimate_divisor = MagicMock(
            side_effect=AssertionError("must not read configuration"),
        )

        msg = manager._build_auto_memory_search_msg(
            query="hello",
            max_results=2,
            text="remembered fact",
        )

        assert (
            msg.metadata["auto_memory_search_usage"]["estimate_divisor"] == 4.0
        )
        manager._get_token_estimate_divisor.assert_not_called()

    def test_keeps_regular_reply_blocks(self, manager):
        auto_block = TextBlock(text="memory result")
        reply_block = TextBlock(text="actual reply")
        msg = Msg(
            name="agent",
            role="assistant",
            metadata={
                AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY: [auto_block.id],
            },
            content=[auto_block, reply_block],
        )

        result = manager._messages_without_auto_memory_search([msg])

        assert len(result) == 1
        assert result[0] is not msg
        assert result[0].content == [reply_block]
        assert AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY not in result[0].metadata
        assert msg.content == [auto_block, reply_block]

    def test_drops_message_when_only_auto_search_blocks_remain(self, manager):
        auto_block = TextBlock(text="memory result")
        msg = Msg(
            name="agent",
            role="assistant",
            metadata={
                AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY: [auto_block.id],
            },
            content=[auto_block],
        )

        assert manager._messages_without_auto_memory_search([msg]) == []


# ---------------------------------------------------------------------------
# TestBaseMemoryManagerListAutoMemoryTasks
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerListAutoMemoryTasks:
    """P1: Tests for list_auto_memory_tasks."""

    def test_returns_empty_when_no_tasks(self, manager):
        result = manager.list_auto_memory_tasks()
        assert result == []

    async def test_returns_status_for_pending_task(self, manager):
        manager.submit_auto_memory([MagicMock()])
        statuses = manager.list_auto_memory_tasks()
        assert len(statuses) == 1
        assert statuses[0]["status"] == "pending"
        if manager._auto_memory_worker_task:
            manager._auto_memory_worker_task.cancel()
            try:
                await manager._auto_memory_worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_status_dict_has_required_keys(self, manager):
        manager.submit_auto_memory([MagicMock()])
        status = manager.list_auto_memory_tasks()[0]
        for key in ("task_id", "start_time", "status", "result", "error"):
            assert key in status
        if manager._auto_memory_worker_task:
            manager._auto_memory_worker_task.cancel()
            try:
                await manager._auto_memory_worker_task
            except (asyncio.CancelledError, Exception):
                pass
