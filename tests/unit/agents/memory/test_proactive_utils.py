# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unnecessary-lambda,unused-import
"""Unit tests for the proactive idle-detection helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from qwenpaw.agents.memory.proactive import proactive_utils as pu


# ---------------------------------------------------------------------------
# ensure_tz_aware
# ---------------------------------------------------------------------------


class TestEnsureTzAware:
    def test_naive_becomes_utc(self):
        naive = datetime(2026, 1, 1, 12, 0)
        aware = pu.ensure_tz_aware(naive)
        assert aware.tzinfo == timezone.utc

    def test_aware_unchanged(self):
        aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert pu.ensure_tz_aware(aware) == aware


# ---------------------------------------------------------------------------
# is_agent_busy
# ---------------------------------------------------------------------------


class TestIsAgentBusy:
    async def test_busy_when_active_tasks(self):
        tracker = SimpleNamespace(
            has_active_tasks=lambda: _async_true(),
        )
        workspace = SimpleNamespace(task_tracker=tracker)
        assert await pu.is_agent_busy(workspace) is True

    async def test_not_busy_without_tracker(self):
        workspace = SimpleNamespace(task_tracker=None)
        assert await pu.is_agent_busy(workspace) is False

    async def test_error_returns_false(self):
        async def boom():
            raise RuntimeError("tracker down")

        workspace = SimpleNamespace(
            task_tracker=SimpleNamespace(has_active_tasks=boom),
        )
        assert await pu.is_agent_busy(workspace) is False


async def _async_true():
    return True


# ---------------------------------------------------------------------------
# get_last_message_ts
# ---------------------------------------------------------------------------


class TestGetLastMessageTs:
    async def test_none_workspace(self):
        assert await pu.get_last_message_ts(None) is None

    async def test_returns_latest_timestamp(self):
        older = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 6, 1, tzinfo=timezone.utc)

        async def list_chats():
            return [
                SimpleNamespace(updated_at=older),
                SimpleNamespace(updated_at=newer),
            ]

        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(list_chats=list_chats),
        )
        ts = await pu.get_last_message_ts(workspace)
        assert ts == newer.timestamp()

    async def test_naive_updated_at_handled(self):
        async def list_chats():
            return [SimpleNamespace(updated_at=datetime(2026, 1, 1, 12))]

        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(list_chats=list_chats),
        )
        ts = await pu.get_last_message_ts(workspace)
        assert ts is not None

    async def test_error_returns_none(self):
        async def boom():
            raise RuntimeError("down")

        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(list_chats=boom),
        )
        assert await pu.get_last_message_ts(workspace) is None
