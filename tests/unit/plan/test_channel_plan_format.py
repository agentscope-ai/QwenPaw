# -*- coding: utf-8 -*-
"""Tests for BaseChannel.format_plan_status()."""
from __future__ import annotations

from copaw.app.channels.base import BaseChannel


class _DummyChannel(BaseChannel):
    """Concrete subclass for testing the base format method."""

    channel = "test"

    def __init__(self):
        pass

    async def consume_one(self, payload):
        pass


class TestFormatPlanStatus:
    """BaseChannel.format_plan_status with various plan states."""

    def _make_channel(self) -> _DummyChannel:
        return _DummyChannel()

    def test_none_plan_returns_empty(self):
        ch = self._make_channel()
        assert ch.format_plan_status(None) == ""

    def test_done_plan_returns_empty(self):
        ch = self._make_channel()
        plan = {
            "name": "Test",
            "state": "done",
            "subtasks": [],
        }
        assert ch.format_plan_status(plan) == ""

    def test_abandoned_plan_returns_empty(self):
        ch = self._make_channel()
        plan = {
            "name": "Test",
            "state": "abandoned",
            "subtasks": [],
        }
        assert ch.format_plan_status(plan) == ""

    def test_in_progress_plan(self):
        ch = self._make_channel()
        plan = {
            "name": "My Plan",
            "state": "in_progress",
            "subtasks": [
                {"name": "Task 1", "state": "done"},
                {"name": "Task 2", "state": "in_progress"},
                {"name": "Task 3", "state": "todo"},
            ],
        }
        result = ch.format_plan_status(plan)
        assert "My Plan" in result
        assert "[1/3]" in result
        assert "Task 2" in result

    def test_todo_plan_no_current(self):
        ch = self._make_channel()
        plan = {
            "name": "New Plan",
            "state": "todo",
            "subtasks": [
                {"name": "Task 1", "state": "todo"},
                {"name": "Task 2", "state": "todo"},
            ],
        }
        result = ch.format_plan_status(plan)
        assert "New Plan" in result
        assert "[0/2]" in result

    def test_all_done_in_progress_state(self):
        ch = self._make_channel()
        plan = {
            "name": "Almost Done",
            "state": "in_progress",
            "subtasks": [
                {"name": "Task 1", "state": "done"},
                {"name": "Task 2", "state": "done"},
            ],
        }
        result = ch.format_plan_status(plan)
        assert "[2/2]" in result
