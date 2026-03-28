# -*- coding: utf-8 -*-
"""Structural verification tests: DataQueue processing
flow has not been modified.

These tests use ``inspect.getsource`` to verify that the core DataQueue path
(``_consume_channel_loop``, ``attach_or_start``, ``TaskTracker.request_stop``)
was not accidentally modified during the dual-queue refactoring.

Validates: Requirements 8.1, 8.2, 8.3
"""
from __future__ import annotations

import inspect

import pytest

from copaw.app.channels.manager import ChannelManager
from copaw.app.runner.task_tracker import TaskTracker


class TestConsumeChannelLoopZeroIntrusion:
    """Verify ``_consume_channel_loop`` core logic is unchanged."""

    def _get_source(self) -> str:
        return inspect.getsource(ChannelManager._consume_channel_loop)

    def test_calls_drain_same_key(self) -> None:
        """_consume_channel_loop still calls _drain_same_key."""
        src = self._get_source()
        assert "_drain_same_key" in src

    def test_calls_process_batch(self) -> None:
        """_consume_channel_loop still calls _process_batch."""
        src = self._get_source()
        assert "_process_batch" in src

    def test_uses_in_progress(self) -> None:
        """_consume_channel_loop still uses _in_progress set."""
        src = self._get_source()
        assert "_in_progress" in src

    def test_uses_pending(self) -> None:
        """_consume_channel_loop still uses _pending dict."""
        src = self._get_source()
        assert "_pending" in src

    def test_does_not_reference_command_queue(self) -> None:
        """_consume_channel_loop must NOT reference CommandQueue concepts."""
        src = self._get_source()
        assert "CommandQueue" not in src
        assert "_command_queues" not in src

    def test_does_not_reference_command_router(self) -> None:
        """_consume_channel_loop must NOT reference CommandRouter."""
        src = self._get_source()
        assert "CommandRouter" not in src
        assert "_command_router" not in src

    def test_does_not_reference_classify_command(self) -> None:
        """_consume_channel_loop must NOT call _classify_command."""
        src = self._get_source()
        assert "_classify_command" not in src

    def test_uses_queues_dict(self) -> None:
        """_consume_channel_loop reads from self._queues (DataQueue)."""
        src = self._get_source()
        assert "_queues" in src

    def test_has_cancelled_error_handling(self) -> None:
        """_consume_channel_loop handles CancelledError for graceful exit."""
        src = self._get_source()
        assert "CancelledError" in src


class TestAttachOrStartZeroIntrusion:
    """Verify ``TaskTracker.attach_or_start`` is unchanged."""

    def _get_source(self) -> str:
        return inspect.getsource(TaskTracker.attach_or_start)

    def test_returns_queue_and_is_new_run(self) -> None:
        """attach_or_start still returns (queue, is_new_run) tuple."""
        src = self._get_source()
        assert "is_new_run" in src or "return" in src
        # Verify it creates a queue and returns it
        assert "asyncio.Queue" in src

    def test_checks_existing_run(self) -> None:
        """attach_or_start checks for existing run before starting new one."""
        src = self._get_source()
        assert "_runs" in src

    def test_creates_producer_task(self) -> None:
        """attach_or_start creates a _producer coroutine."""
        src = self._get_source()
        assert "_producer" in src
        assert "create_task" in src

    def test_uses_lock(self) -> None:
        """attach_or_start uses the tracker lock for thread safety."""
        src = self._get_source()
        assert "_lock" in src

    def test_does_not_reference_command_queue(self) -> None:
        """attach_or_start must NOT reference CommandQueue."""
        src = self._get_source()
        assert "CommandQueue" not in src
        assert "command" not in src.lower() or "command" not in src

    def test_replays_buffer_for_reconnect(self) -> None:
        """attach_or_start replays buffer events for reconnects."""
        src = self._get_source()
        assert "buffer" in src


class TestRequestStopZeroIntrusion:
    """Verify ``TaskTracker.request_stop`` is unchanged."""

    def _get_source(self) -> str:
        return inspect.getsource(TaskTracker.request_stop)

    def test_cancels_task(self) -> None:
        """request_stop cancels the task via task.cancel()."""
        src = self._get_source()
        assert ".cancel()" in src

    def test_returns_bool(self) -> None:
        """request_stop returns True/False based on whether
        task was running."""
        src = self._get_source()
        assert "return True" in src
        assert "return False" in src

    def test_checks_task_done(self) -> None:
        """request_stop checks if task is already done before cancelling."""
        src = self._get_source()
        assert ".done()" in src

    def test_uses_lock(self) -> None:
        """request_stop uses the tracker lock."""
        src = self._get_source()
        assert "_lock" in src

    def test_accesses_runs_dict(self) -> None:
        """request_stop looks up the run in _runs."""
        src = self._get_source()
        assert "_runs" in src

    def test_does_not_reference_command_router(self) -> None:
        """request_stop must NOT reference CommandRouter."""
        src = self._get_source()
        assert "CommandRouter" not in src
        assert "command_router" not in src
