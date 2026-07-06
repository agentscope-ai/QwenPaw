# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Tests for BaseMemoryManager abstract base class."""
import asyncio
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


class TestAutoMemorySearchSanitization:
    """P1: auto_memory input should exclude auto-search blocks only."""

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
