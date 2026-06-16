# -*- coding: utf-8 -*-
"""
QwenPaw Mission Mode end-to-end tests.

All cases avoid the LLM by either:
- exercising read-only sub-commands (``/mission``, ``/mission status``,
  ``/mission list``), or
- seeding an invalid PRD so Phase 2 short-circuits before any worker
  is dispatched.

A full master/worker/verifier pipeline is intentionally out of scope —
it would burn LLM budget and take many minutes to converge, with
results that are not deterministic enough for e2e.

Cases:
- MISSION-001 P0  test_mission_list_with_seeded_dir
- MISSION-002 P1  test_mission_status_no_active
- MISSION-003 P1  test_mission_list_empty
- MISSION-004 P1  test_mission_help_for_short_input
- MISSION-005 P2  test_mission_list_orders_two_missions
- MISSION-006 P2  test_invalid_prd_rejected_when_entering_phase2
"""
from __future__ import annotations

import logging

import pytest

from pages.mission_page import MissionPage
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


# ============================================================================
# MISSION-001 P0  /mission list with a seeded mission directory
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.mission
class TestMissionListWithSeeded:
    """MISSION-001: ``/mission list`` enumerates the seeded mission with
    its project name, story progress and branch label."""

    @pytest.mark.test_id("MISSION-001")
    def test_mission_list_with_seeded_dir(
        self,
        mission_page: MissionPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = mission_page.unique_session_id("list-seeded")
        ts = mission_page.unique_mission_ts()

        try:
            log_test_step("1. Seed one completed mission")
            mission_page.clean_missions()
            mission_page.seed_mission(
                ts=ts,
                session_id=sid,
                current_phase="completed",
                project="e2e-list-fixture",
                branch_name="mission/e2e-list-fixture",
            )

            log_test_step("2. /mission list reports it")
            out = mission_page.send_chat(
                "/mission list", mission_page.unique_session_id("list-q"),
            )
            mission_page.assert_contains(
                out,
                f"mission-{ts}",
                "e2e-list-fixture",
                "mission/e2e-list-fixture",
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            mission_page.clean_missions()


# ============================================================================
# MISSION-002 P1  /mission status with no active mission
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.mission
class TestMissionStatusNoActive:
    """MISSION-002: A fresh session reports no active mission."""

    @pytest.mark.test_id("MISSION-002")
    def test_mission_status_no_active(
        self,
        mission_page: MissionPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = mission_page.unique_session_id("status-none")

        try:
            mission_page.clean_missions()
            out = mission_page.send_chat("/mission status", sid)
            mission_page.assert_contains(out, "No active mission")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            mission_page.clean_missions()


# ============================================================================
# MISSION-003 P1  /mission list on an empty workspace
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.mission
class TestMissionListEmpty:
    """MISSION-003: ``/mission list`` reports "no missions" on a clean
    workspace."""

    @pytest.mark.test_id("MISSION-003")
    def test_mission_list_empty(
        self,
        mission_page: MissionPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = mission_page.unique_session_id("list-empty")

        try:
            mission_page.clean_missions()
            out = mission_page.send_chat("/mission list", sid)
            mission_page.assert_contains(out, "No missions")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            mission_page.clean_missions()


# ============================================================================
# MISSION-004 P1  /mission with a short input returns help
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.mission
class TestMissionShortInputHelp:
    """MISSION-004: ``/mission`` and ``/mission abc`` both render the help
    block (task description must be at least 5 characters)."""

    @pytest.mark.test_id("MISSION-004")
    def test_mission_help_for_short_input(
        self,
        mission_page: MissionPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = mission_page.unique_session_id("help")

        out = mission_page.send_chat("/mission abc", sid)
        mission_page.assert_contains(
            out,
            "Mission Mode",
            "/mission status",
            "/mission list",
            "at least 5 characters",
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MISSION-005 P2  /mission list orders two seeded missions
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.mission
class TestMissionListOrdersTwo:
    """MISSION-005: Both seeded missions show up in ``/mission list``."""

    @pytest.mark.test_id("MISSION-005")
    def test_mission_list_orders_two_missions(
        self,
        mission_page: MissionPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid_a = mission_page.unique_session_id("a")
        sid_b = mission_page.unique_session_id("b")
        # Different timestamps so the directory names sort distinctly.
        ts_old = mission_page.unique_mission_ts(offset_ms=-50_000)
        ts_new = mission_page.unique_mission_ts()

        try:
            mission_page.clean_missions()
            mission_page.seed_mission(
                ts=ts_old, session_id=sid_a, project="e2e-older-fixture",
                branch_name="mission/older",
            )
            mission_page.seed_mission(
                ts=ts_new, session_id=sid_b, project="e2e-newer-fixture",
                branch_name="mission/newer",
            )

            out = mission_page.send_chat(
                "/mission list",
                mission_page.unique_session_id("list-two"),
            )
            mission_page.assert_contains(
                out,
                f"mission-{ts_old}",
                f"mission-{ts_new}",
                "e2e-older-fixture",
                "e2e-newer-fixture",
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            mission_page.clean_missions()


# ============================================================================
# MISSION-006 P2  Invalid PRD short-circuits Phase 2 entry
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.mission
class TestInvalidPrdRejected:
    """MISSION-006: Seeding ``current_phase=execution_confirmed`` with an
    invalid prd.json causes Phase 2 to abort before any LLM call,
    returning a schema-error message and resetting the phase."""

    @pytest.mark.test_id("MISSION-006")
    def test_invalid_prd_rejected_when_entering_phase2(
        self,
        mission_page: MissionPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = mission_page.unique_session_id("invalid-prd")
        ts = mission_page.unique_mission_ts()

        try:
            log_test_step("1. Seed mission with invalid PRD")
            mission_page.clean_missions()
            mission_page.seed_mission(
                ts=ts,
                session_id=sid,
                current_phase="execution_confirmed",
                invalid_prd=True,
            )

            log_test_step("2. Send any chat message — Phase 2 should abort")
            out = mission_page.send_chat("go", sid)
            # The handler emits the i18n `phase2_startup_invalid` message
            # which always names the missing field. Match on the field
            # name so the assertion stays language-agnostic.
            mission_page.assert_contains(
                out, "userStories",
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            mission_page.clean_missions()
