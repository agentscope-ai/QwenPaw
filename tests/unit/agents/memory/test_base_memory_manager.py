# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Tests for BaseMemoryManager abstract base class."""
import asyncio
from unittest.mock import MagicMock

import pytest


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

    def test_summary_task_info_starts_empty(self, manager):
        assert manager._summary_task_info == {}

    def test_task_counter_starts_at_zero(self, manager):
        assert manager._task_counter == 0

    def test_worker_task_is_none_initially(self, manager):
        assert manager._worker_task is None


# ---------------------------------------------------------------------------
# TestBaseMemoryManagerAddSummarizeTask
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerAddSummarizeTask:
    """P1: Tests for add_summarize_task."""

    def _make_msg(self, text="hello"):
        """Create a mock message with get_text_content."""
        msg = MagicMock()
        msg.get_text_content.return_value = text
        return msg

    async def test_adds_task_info_entry(self, manager):
        """Scheduling a task creates an entry in _summary_task_info."""
        manager._summarize_threshold = 0
        await manager.add_summarize_task([self._make_msg()])
        assert len(manager._summary_task_info) == 1
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_task_starts_as_pending(self, manager):
        """New task has status 'pending'."""
        manager._summarize_threshold = 0
        await manager.add_summarize_task([self._make_msg()])
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
        manager._summarize_threshold = 0
        await manager.add_summarize_task([self._make_msg()])
        await manager.add_summarize_task([self._make_msg()])
        assert manager._task_counter == 2
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_worker_task_created(self, manager):
        """Scheduling a task starts the background worker."""
        manager._summarize_threshold = 0
        await manager.add_summarize_task([self._make_msg()])
        assert manager._worker_task is not None
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass


# ---------------------------------------------------------------------------
# TestBaseMemoryManagerListSummarizeStatus
# ---------------------------------------------------------------------------


class TestBaseMemoryManagerListSummarizeStatus:
    """P1: Tests for list_summarize_status."""

    def _make_msg(self, text="hello"):
        """Create a mock message with get_text_content."""
        msg = MagicMock()
        msg.get_text_content.return_value = text
        return msg

    def test_returns_empty_when_no_tasks(self, manager):
        result = manager.list_summarize_status()
        assert result == []

    async def test_returns_status_for_pending_task(self, manager):
        manager._summarize_threshold = 0
        await manager.add_summarize_task([self._make_msg()])
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
        manager._summarize_threshold = 0
        await manager.add_summarize_task([self._make_msg()])
        status = manager.list_summarize_status()[0]
        for key in ("task_id", "start_time", "status", "result", "error"):
            assert key in status
        if manager._worker_task:
            manager._worker_task.cancel()
            try:
                await manager._worker_task
            except (asyncio.CancelledError, Exception):
                pass
