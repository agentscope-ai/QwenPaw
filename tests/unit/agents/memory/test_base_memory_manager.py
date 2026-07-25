# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Tests for BaseMemoryManager abstract base class."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

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

        async def close(self):
            return True

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

    def test_summary_task_info_starts_empty(self, manager):
        assert manager._summary_task_info == {}

    def test_task_counter_starts_at_zero(self, manager):
        assert manager._task_counter == 0

    def test_worker_task_is_none_initially(self, manager):
        assert manager._worker_task is None


class TestBaseMemoryManagerAutoMemoryTurnState:
    """P1: Auto-memory interval state is kept per session with TTL cleanup."""

    def test_returns_same_state_for_same_session(self, manager):
        state = manager.get_auto_memory_turn_state("session-1")
        state["pending"].append("turn-1")

        assert manager.get_auto_memory_turn_state("session-1") is state
        assert manager.get_auto_memory_turn_state("session-1")["pending"] == [
            "turn-1",
        ]

    def test_separates_sessions(self, manager):
        manager.get_auto_memory_turn_state("session-1")["pending"].append(
            "turn-1",
        )

        assert manager.get_auto_memory_turn_state("session-2")["pending"] == []

    def test_cleans_expired_sessions_on_access(self, manager, monkeypatch):
        monkeypatch.setattr(base_memory_manager.time, "monotonic", lambda: 0)
        manager.get_auto_memory_turn_state("old-session")

        now = base_memory_manager.AUTO_MEMORY_TURN_STATE_TTL_SECONDS + 1
        monkeypatch.setattr(
            base_memory_manager.time,
            "monotonic",
            lambda: now,
        )
        manager.get_auto_memory_turn_state("new-session")

        assert "old-session" not in manager._auto_memory_turn_states
        assert "new-session" in manager._auto_memory_turn_states


# ---------------------------------------------------------------------------
# TestBaseMemoryManagerAddSummarizeTask
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerAddSummarizeTask:
    """P1: Tests for add_summarize_task."""

    async def test_adds_task_info_entry(self, manager):
        """Scheduling a task creates an entry in _summary_task_info."""
        msgs = [MagicMock()]
        manager.add_summarize_task(msgs)
        assert len(manager._summary_task_info) == 1
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_task_starts_as_pending(self, manager):
        """New task has status 'pending'."""
        manager.add_summarize_task([MagicMock()])
        info = list(manager._summary_task_info.values())[0]
        assert info["status"] == "pending"
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_counter_increments_per_task(self, manager):
        """Each call increments the task counter."""
        manager.add_summarize_task([MagicMock()])
        manager.add_summarize_task([MagicMock()])
        assert manager._task_counter == 2
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_worker_task_created(self, manager):
        """Scheduling a task starts the background worker."""
        manager.add_summarize_task([MagicMock()])
        assert manager._worker_task is not None
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_task_info_does_not_retain_worker(self, manager):
        manager.add_summarize_task([MagicMock()])

        info = next(iter(manager._summary_task_info.values()))
        assert "task" not in info

        await manager._shutdown_summarize_worker()

    async def test_keeps_only_latest_terminal_tasks(
        self,
        manager,
        monkeypatch,
    ):
        monkeypatch.setattr(
            base_memory_manager,
            "MAX_SUMMARY_TASK_HISTORY",
            2,
        )
        completed = asyncio.Event()
        calls = 0

        async def summarize(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                completed.set()
            return f"result-{calls}"

        manager.summarize = summarize
        for _ in range(3):
            manager.add_summarize_task([MagicMock()])

        await asyncio.wait_for(completed.wait(), timeout=1)
        await asyncio.sleep(0)

        assert list(manager._summary_task_info) == ["task_2", "task_3"]
        await manager._shutdown_summarize_worker()

    def test_pruning_keeps_non_terminal_tasks(self, manager, monkeypatch):
        monkeypatch.setattr(
            base_memory_manager,
            "MAX_SUMMARY_TASK_HISTORY",
            1,
        )
        manager._summary_task_info = {
            "task_1": {"status": "completed"},
            "task_2": {"status": "running"},
            "task_3": {"status": "failed"},
            "task_4": {"status": "pending"},
        }

        manager._prune_summary_task_info()

        assert list(manager._summary_task_info) == [
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

        manager.summarize = swallow_cancellation
        manager.add_summarize_task([MagicMock()])
        await started.wait()

        stopped = await manager._shutdown_summarize_worker(timeout=0.5)

        assert stopped is True
        assert manager._worker_task is None

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
        manager._worker_task = worker
        await started.wait()

        stopped = await manager._shutdown_summarize_worker(timeout=0.01)

        assert stopped is False
        keep_running.set()
        worker.cancel()
        await asyncio.wait({worker}, timeout=0.5)


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
        monkeypatch,
    ):
        def fake_load_agent_config(agent_id):
            assert agent_id == "test-agent"
            return SimpleNamespace(
                running=SimpleNamespace(
                    light_context_config=SimpleNamespace(
                        token_count_estimate_divisor=2,
                    ),
                ),
            )

        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            fake_load_agent_config,
        )

        msg = manager._build_auto_memory_search_msg(
            query="hello",
            max_results=2,
            text="remembered fact",
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
# TestBaseMemoryManagerListSummarizeStatus
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerListSummarizeStatus:
    """P1: Tests for list_summarize_status."""

    def test_returns_empty_when_no_tasks(self, manager):
        result = manager.list_summarize_status()
        assert result == []

    async def test_returns_status_for_pending_task(self, manager):
        manager.add_summarize_task([MagicMock()])
        statuses = manager.list_summarize_status()
        assert len(statuses) == 1
        assert statuses[0]["status"] == "pending"
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_status_dict_has_required_keys(self, manager):
        manager.add_summarize_task([MagicMock()])
        status = manager.list_summarize_status()[0]
        for key in ("task_id", "start_time", "status", "result", "error"):
            assert key in status
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass
