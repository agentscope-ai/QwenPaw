# -*- coding: utf-8 -*-
"""Unit tests for MissionGate lifecycle and PRD evaluation.

Exercises the stop-gate check paths (tool-call bypass, inactive bypass,
deleted-state terminate, terminal phase, exec-phase PRD evaluation),
the lazy state restore, the persistence snapshot, and the remaining
story summary builder.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import json
from pathlib import Path


from qwenpaw.loop.gates.base import StopAction
from qwenpaw.modes.mission.gates import MissionGate


def _make_gate(loop_dir: Path | None = None) -> MissionGate:
    gate = MissionGate()
    if loop_dir is not None:
        gate.activate_for_mission(loop_dir)
    return gate


def _write_loop_config(loop_dir: Path, phase: str, **extra) -> None:
    loop_dir.mkdir(parents=True, exist_ok=True)
    (loop_dir / "loop_config.json").write_text(
        json.dumps({"current_phase": phase, **extra}),
        encoding="utf-8",
    )


def _write_prd(loop_dir: Path, stories: list[dict]) -> None:
    loop_dir.mkdir(parents=True, exist_ok=True)
    (loop_dir / "prd.json").write_text(
        json.dumps({"userStories": stories}),
        encoding="utf-8",
    )


class TestGateIdentity:
    def test_name_and_priority(self):
        gate = MissionGate()
        assert gate.name == "mission"
        assert gate.priority == 50


# ---------------------------------------------------------------------------
# check() early exits
# ---------------------------------------------------------------------------


class TestCheckEarlyExits:
    async def test_tool_calls_bypass(self, tmp_path):
        gate = _make_gate(tmp_path)
        result = await gate.check({"has_tool_calls": True})
        assert result.action == StopAction.BYPASS

    async def test_no_state_bypass(self):
        gate = MissionGate()
        result = await gate.check({"has_tool_calls": False})
        assert result.action == StopAction.BYPASS

    async def test_saved_active_state_but_missing_dir_terminates(self):
        gate = MissionGate()
        ctx = {
            "mode_state": {
                "mission": {
                    "active": True,
                    "loop_dir": "/nonexistent/qwenpaw/mission/dir",
                },
            },
        }
        result = await gate.check(ctx)
        assert result.action == StopAction.TERMINATE
        assert "deleted" in result.reason

    async def test_inactive_state_bypass(self, tmp_path):
        gate = _make_gate(tmp_path)
        state = gate._state()
        state.active = False
        result = await gate.check({})
        assert result.action == StopAction.BYPASS


# ---------------------------------------------------------------------------
# check() with active state + loop config phases
# ---------------------------------------------------------------------------


class TestCheckPhases:
    async def test_terminal_phase_terminates(self, tmp_path):
        _write_loop_config(tmp_path, "completed")
        gate = _make_gate(tmp_path)

        result = await gate.check({})

        assert result.action == StopAction.TERMINATE
        assert "completed" in result.reason
        # Gate deactivated after terminal phase.
        assert gate._state() is None

    async def test_max_iterations_phase_terminates(self, tmp_path):
        _write_loop_config(tmp_path, "max_iterations_reached")
        gate = _make_gate(tmp_path)

        result = await gate.check({})

        assert result.action == StopAction.TERMINATE

    async def test_non_exec_phase_bypass(self, tmp_path):
        _write_loop_config(tmp_path, "prd_generation")
        gate = _make_gate(tmp_path)

        result = await gate.check({})

        assert result.action == StopAction.BYPASS
        assert gate._state().phase == "prd_generation"

    async def test_exec_phase_empty_prd_bypass(self, tmp_path):
        _write_loop_config(tmp_path, "execution_confirmed")
        gate = _make_gate(tmp_path)

        result = await gate.check({})

        assert result.action == StopAction.BYPASS

    async def test_exec_phase_all_stories_passed_terminates(self, tmp_path):
        _write_loop_config(tmp_path, "execution")
        _write_prd(
            tmp_path,
            [{"id": "s1", "title": "a", "passes": True}],
        )
        gate = _make_gate(tmp_path)

        result = await gate.check({})

        assert result.action == StopAction.TERMINATE
        assert "All stories passed" in result.reason
        assert gate._state() is None

    async def test_exec_phase_no_stories_terminates(self, tmp_path):
        _write_loop_config(tmp_path, "execution")
        _write_prd(tmp_path, [])
        gate = _make_gate(tmp_path)

        result = await gate.check({})

        assert result.action == StopAction.TERMINATE
        assert "No user stories" in result.reason

    async def test_exec_phase_remaining_stories_continue(self, tmp_path):
        _write_loop_config(tmp_path, "execution")
        _write_prd(
            tmp_path,
            [
                {"id": "s1", "title": "done", "passes": True},
                {"id": "s2", "title": "todo", "passes": False},
            ],
        )
        gate = _make_gate(tmp_path)

        result = await gate.check({})

        assert result.action == StopAction.INTERRUPT_AND_CONTINUE
        state = gate._state()
        assert state.last_prd is not None
        assert state.last_cfg is not None


# ---------------------------------------------------------------------------
# _eval_prd direct
# ---------------------------------------------------------------------------


class TestEvalPrd:
    def test_empty_prd_bypass(self):
        gate = MissionGate()
        result = gate._eval_prd({}, {})
        assert result.action == StopAction.BYPASS

    def test_all_passed_terminates_and_deactivates(self, tmp_path):
        gate = _make_gate(tmp_path)
        prd = {"userStories": [{"id": "s1", "passes": True}]}
        result = gate._eval_prd(prd, {})
        assert result.action == StopAction.TERMINATE
        assert gate._state() is None

    def test_in_progress_stores_last_snapshot(self, tmp_path):
        gate = _make_gate(tmp_path)
        prd = {"userStories": [{"id": "s1", "passes": False}]}
        cfg = {"max_iterations": 5}
        result = gate._eval_prd(prd, cfg)
        assert result.action == StopAction.INTERRUPT_AND_CONTINUE
        assert gate._state().last_prd == prd
        assert gate._state().last_cfg == cfg


# ---------------------------------------------------------------------------
# build_continuation / _remaining_summary
# ---------------------------------------------------------------------------


class TestContinuation:
    def test_no_state_returns_empty(self):
        gate = MissionGate()
        assert gate.build_continuation() == ""

    def test_state_without_prd_returns_empty(self, tmp_path):
        gate = _make_gate(tmp_path)
        assert gate.build_continuation() == ""

    def test_summary_lists_remaining_stories(self, tmp_path):
        gate = _make_gate(tmp_path)
        gate._eval_prd(
            {
                "userStories": [
                    {"id": "s1", "title": "done", "passes": True},
                    {"id": "s2", "title": "left", "passes": False},
                ],
            },
            {"max_iterations": 7},
        )

        summary = gate.build_continuation()

        assert "1/2 stories passed" in summary
        assert "s2: left" in summary
        assert "Max iterations: 7" in summary

    def test_summary_defaults_max_iterations(self):
        summary = MissionGate._remaining_summary(
            {"userStories": [{"id": "x", "title": "t"}]},
            {},
        )
        assert "Max iterations: 20" in summary

    def test_summary_missing_story_fields_use_placeholders(self):
        summary = MissionGate._remaining_summary(
            {"userStories": [{}]},
            {},
        )
        assert "?: ?" in summary


# ---------------------------------------------------------------------------
# restore / _try_restore / _saved_state
# ---------------------------------------------------------------------------


class TestRestore:
    def test_saved_state_returns_none_without_mode_state(self):
        assert MissionGate._saved_state({}) is None
        assert MissionGate._saved_state(object()) is None

    def test_saved_state_returns_mission_dict(self):
        saved = {"active": True, "loop_dir": "/x"}
        ctx = {"mode_state": {"mission": saved}}
        assert MissionGate._saved_state(ctx) == saved

    def test_saved_state_non_dict_returns_none(self):
        ctx = {"mode_state": {"mission": "junk"}}
        assert MissionGate._saved_state(ctx) is None

    def test_try_restore_without_saved_returns_none(self):
        gate = MissionGate()
        assert gate._try_restore({}) is None

    def test_try_restore_inactive_saved_returns_none(self):
        gate = MissionGate()
        ctx = {
            "mode_state": {
                "mission": {"active": False, "loop_dir": "/x"},
            },
        }
        assert gate._try_restore(ctx) is None

    def test_try_restore_missing_loop_dir_returns_none(self):
        gate = MissionGate()
        ctx = {
            "mode_state": {
                "mission": {
                    "active": True,
                    "loop_dir": "/nonexistent/qwenpaw/mission",
                },
            },
        }
        assert gate._try_restore(ctx) is None

    def test_try_restore_valid_dir_activates(self, tmp_path):
        gate = MissionGate()
        ctx = {
            "mode_state": {
                "mission": {
                    "active": True,
                    "loop_dir": str(tmp_path),
                    "phase": "execution",
                },
            },
        }
        restored = gate._try_restore(ctx)
        assert restored is not None
        assert restored.loop_dir == tmp_path
        assert restored.phase == "execution"
        assert gate._state() is restored

    def test_restore_noop_when_state_present(self, tmp_path):
        gate = _make_gate(tmp_path)
        before = gate._state()
        ctx = {
            "mode_state": {
                "mission": {
                    "active": True,
                    "loop_dir": str(tmp_path),
                },
            },
        }
        gate.restore(ctx)
        assert gate._state() is before

    def test_restore_lazy_activates_from_ctx(self, tmp_path):
        gate = MissionGate()
        ctx = {
            "mode_state": {
                "mission": {
                    "active": True,
                    "loop_dir": str(tmp_path),
                },
            },
        }
        gate.restore(ctx)
        assert gate._state() is not None

    def test_try_restore_accepts_object_ctx(self, tmp_path):
        gate = MissionGate()

        class Ctx:
            mode_state = {
                "mission": {
                    "active": True,
                    "loop_dir": str(tmp_path),
                },
            }

        assert gate._try_restore(Ctx()) is not None


# ---------------------------------------------------------------------------
# persistence_snapshot
# ---------------------------------------------------------------------------


class TestPersistenceSnapshot:
    async def test_no_state_returns_none(self):
        gate = MissionGate()
        assert await gate.persistence_snapshot() is None

    async def test_inactive_state_returns_none(self, tmp_path):
        gate = _make_gate(tmp_path)
        gate._state().active = False
        assert await gate.persistence_snapshot() is None

    async def test_snapshot_refreshes_phase_from_config(self, tmp_path):
        _write_loop_config(tmp_path, "execution_confirmed")
        gate = _make_gate(tmp_path)

        snapshot = await gate.persistence_snapshot()

        assert snapshot == {
            "active": True,
            "loop_dir": str(tmp_path),
            "phase": "execution_confirmed",
        }

    async def test_snapshot_keeps_phase_when_config_missing(
        self,
        tmp_path,
    ):
        gate = _make_gate(tmp_path)
        gate._state().phase = "execution"

        snapshot = await gate.persistence_snapshot()

        assert snapshot["phase"] == "execution"
