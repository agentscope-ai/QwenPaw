# -*- coding: utf-8 -*-
"""Tests for the proactive trigger logic.

Covers enable/disable session lifecycle (workspace-required guard, task
cleanup), the pure _should_trigger_proactive decision function, and the
cooldown/running-task guards of _handle_proactive_trigger.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.agents.memory.proactive import proactive_trigger as pt
from qwenpaw.agents.memory.proactive.proactive_types import ProactiveConfig


@pytest.fixture(autouse=True)
def _clear_globals():
    pt.proactive_configs.clear()
    pt.proactive_tasks.clear()
    pt.proactive_workspaces.clear()
    yield
    pt.proactive_configs.clear()
    pt.proactive_tasks.clear()
    pt.proactive_workspaces.clear()


def _utc(minutes_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


# ---------------------------------------------------------------------------
# enable/disable lifecycle
# ---------------------------------------------------------------------------


class TestEnableDisable:
    def test_enable_requires_workspace(self):
        with pytest.raises(ValueError, match="workspace must be provided"):
            pt.enable_proactive_for_session("s1", workspace=None)

    def test_enable_stores_config_and_workspace(self):
        workspace = SimpleNamespace()
        fake_task = SimpleNamespace(done=lambda: False)
        with patch.object(asyncio, "create_task", return_value=fake_task):
            result = pt.enable_proactive_for_session(
                "s1",
                idle_minutes=15,
                workspace=workspace,
            )
        assert "15 minute" in result
        config = pt.proactive_configs["s1"]
        assert config.enabled is True
        assert config.idle_minutes == 15
        assert pt.proactive_workspaces["s1"] is workspace
        assert pt.proactive_tasks["s1"] is fake_task

    async def test_disable_cancels_task_and_cleans_up(self):
        workspace = SimpleNamespace()

        async def long_loop(session_id):
            await asyncio.sleep(30)

        with patch.object(pt, "proactive_trigger_loop", long_loop):
            pt.enable_proactive_for_session("s1", workspace=workspace)
            task = pt.proactive_tasks["s1"]
            assert not task.done()

            result = await pt.disable_proactive_for_session("s1")
            assert result == "Proactive mode disabled."
            assert task.cancelled()
            assert "s1" not in pt.proactive_tasks
            assert "s1" not in pt.proactive_configs
            assert "s1" not in pt.proactive_workspaces

    async def test_disable_unknown_session_is_safe(self):
        result = await pt.disable_proactive_for_session("never-enabled")
        assert result == "Proactive mode disabled."

    async def test_enable_reuses_finished_task_slot(self):
        workspace = SimpleNamespace()

        async def instant(_session_id):
            return None

        with patch.object(pt, "proactive_trigger_loop", instant):
            pt.enable_proactive_for_session("s1", workspace=workspace)
            first_task = pt.proactive_tasks["s1"]
            await asyncio.sleep(0.05)
            assert first_task.done()
            # Re-enable must create a fresh task, not reuse the dead one.
            pt.enable_proactive_for_session("s1", workspace=workspace)
            assert pt.proactive_tasks["s1"] is not first_task


# ---------------------------------------------------------------------------
# _should_trigger_proactive
# ---------------------------------------------------------------------------


class TestShouldTriggerProactive:
    def test_idle_below_threshold_no_trigger(self):
        config = ProactiveConfig(
            idle_minutes=30,
            mode_enabled_time=_utc(60),
        )
        result = pt._should_trigger_proactive(
            config,
            last_interaction_tz_aware=_utc(10),
            current_time=datetime.now(timezone.utc),
        )
        assert result is False

    def test_idle_above_threshold_triggers(self):
        config = ProactiveConfig(
            idle_minutes=30,
            mode_enabled_time=_utc(60),
        )
        result = pt._should_trigger_proactive(
            config,
            last_interaction_tz_aware=_utc(45),
            current_time=datetime.now(timezone.utc),
        )
        assert result is True

    def test_no_mode_enabled_time_triggers_when_idle(self):
        config = ProactiveConfig(
            idle_minutes=30,
            mode_enabled_time=None,
        )
        result = pt._should_trigger_proactive(
            config,
            last_interaction_tz_aware=_utc(45),
            current_time=datetime.now(timezone.utc),
        )
        assert result is True

    def test_mode_enabled_too_recently_blocks(self):
        """Idle exceeds threshold but mode was enabled only minutes ago."""
        now = datetime.now(timezone.utc)
        config = ProactiveConfig(
            idle_minutes=30,
            mode_enabled_time=now - timedelta(minutes=5),
        )
        result = pt._should_trigger_proactive(
            config,
            last_interaction_tz_aware=now - timedelta(minutes=45),
            current_time=now,
        )
        assert result is False

    def test_naive_mode_enabled_time_handled(self):
        """Naive datetimes are coerced to UTC via ensure_tz_aware."""
        now = datetime.now(timezone.utc)
        config = ProactiveConfig(
            idle_minutes=30,
            mode_enabled_time=(now - timedelta(minutes=60)).replace(
                tzinfo=None,
            ),
        )
        result = pt._should_trigger_proactive(
            config,
            last_interaction_tz_aware=now - timedelta(minutes=45),
            current_time=now,
        )
        assert result is True


# ---------------------------------------------------------------------------
# _handle_proactive_trigger guards
# ---------------------------------------------------------------------------


class TestHandleProactiveTriggerGuards:
    async def test_running_task_blocks_trigger(self):
        config = ProactiveConfig(
            enabled=True,
            idle_minutes=1,
            last_user_interaction=_utc(10),
            mode_enabled_time=_utc(20),
            running_task_id="task-1",
        )
        result = await pt._handle_proactive_trigger(
            "s1",
            config,
            None,
            SimpleNamespace(),
        )
        assert result is None  # unchanged last_attempt passthrough

    async def test_cooldown_blocks_within_60s(self):
        config = ProactiveConfig(
            enabled=True,
            idle_minutes=1,
            last_user_interaction=_utc(10),
            mode_enabled_time=_utc(20),
        )
        recent_attempt = datetime.now(timezone.utc) - timedelta(seconds=30)
        result = await pt._handle_proactive_trigger(
            "s1",
            config,
            recent_attempt,
            SimpleNamespace(),
        )
        assert result == recent_attempt

    async def test_missing_last_interaction_blocks(self):
        config = ProactiveConfig(
            enabled=True,
            idle_minutes=1,
            last_user_interaction=None,
            mode_enabled_time=_utc(20),
        )
        old_attempt = datetime.now(timezone.utc) - timedelta(minutes=5)
        result = await pt._handle_proactive_trigger(
            "s1",
            config,
            old_attempt,
            SimpleNamespace(),
        )
        assert result == old_attempt

    async def test_missing_mode_enabled_time_blocks(self):
        config = ProactiveConfig(
            enabled=True,
            idle_minutes=1,
            last_user_interaction=_utc(10),
            mode_enabled_time=None,
        )
        old_attempt = datetime.now(timezone.utc) - timedelta(minutes=5)
        result = await pt._handle_proactive_trigger(
            "s1",
            config,
            old_attempt,
            SimpleNamespace(),
        )
        assert result == old_attempt
