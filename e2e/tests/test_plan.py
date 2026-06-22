# -*- coding: utf-8 -*-
"""
QwenPaw Plan Mode end-to-end tests.

UI-driven only. Pure API contract tests for /api/agents/{id}/plan/*
live in ``tests/integration/``. Here we exercise the user-visible
surface: the agent-config Plan Mode toggle, the chat-toolbar Plan
button (visible only when enabled), and the PlanPanel Drawer rendered
with seeded session-state data.

Cases:
- PLAN-001 P0  test_plan_mode_toggle_in_agent_config
- PLAN-002 P1  test_plan_button_appears_when_enabled
- PLAN-003 P1  test_plan_panel_drawer_opens_with_empty_state
- PLAN-004 P0  test_plan_panel_renders_seeded_plan
"""
from __future__ import annotations

import logging
import time

import pytest
from playwright.sync_api import expect

from pages.plan_page import PlanPage
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


# ============================================================================
# PLAN-001 P0 — Plan Mode toggle in Agent Config persists across reload
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.plan
class TestPlanModeToggleUI:
    """PLAN-001: From the user's view, Plan Mode is opted-in by flipping
    the Switch on /agent-config (ReAct Agent tab). The change must
    survive Save + page reload."""

    @pytest.mark.test_id("PLAN-001")
    def test_plan_mode_toggle_in_agent_config(
        self,
        plan_page: PlanPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        # Snapshot the original state via API so we can restore it.
        original_enabled = plan_page.api_get_plan_enabled(api_context)
        # Force the starting state to disabled so the toggle action is
        # observable.
        plan_page.api_set_plan_enabled(api_context, False)

        try:
            log_test_step("1. Open /agent-config")
            plan_page.open_agent_config()

            log_test_step("2. Scroll to Plan Mode and confirm initial state")
            plan_page.scroll_plan_mode_into_view()
            assert plan_page.get_plan_mode_switch_state() is False, (
                "Plan Mode should be off after the API reset"
            )

            log_test_step("3. Click the switch and Save")
            plan_page.click_plan_mode_switch()
            assert plan_page.get_plan_mode_switch_state() is True, (
                "Switch should report on immediately after click"
            )
            plan_page.click_save()

            log_test_step("4. Reload the page; switch must still be on")
            plan_page.page.reload(
                wait_until="commit", timeout=plan_page.timeout,
            )
            try:
                plan_page.page.wait_for_load_state(
                    "networkidle", timeout=plan_page.timeout,
                )
            except Exception:
                pass
            plan_page.scroll_plan_mode_into_view()
            assert plan_page.get_plan_mode_switch_state() is True, (
                "Plan Mode should still be on after reload"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            plan_page.api_set_plan_enabled(api_context, original_enabled)


# ============================================================================
# PLAN-002 P1 — Plan button only appears in Chat when Plan Mode is enabled
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.plan
class TestPlanButtonVisibility:
    """PLAN-002: The Chat toolbar Plan IconButton is gated by the
    ``planEnabled`` prop. Toggling Plan Mode through the API (test
    setup only) must be reflected in the Chat header."""

    @pytest.mark.test_id("PLAN-002")
    def test_plan_button_appears_when_enabled(
        self,
        plan_page: PlanPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        original_enabled = plan_page.api_get_plan_enabled(api_context)

        try:
            log_test_step("1. Enable Plan Mode (test setup)")
            plan_page.api_set_plan_enabled(api_context, True)

            log_test_step("2. Open /chat and wait for the toolbar")
            plan_page.open_chat()

            log_test_step("3. Plan icon button is visible")
            expect(
                plan_page.page.locator(plan_page.CHAT_PLAN_BUTTON).first
            ).to_be_visible(timeout=plan_page.timeout)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            plan_page.api_set_plan_enabled(api_context, original_enabled)


# ============================================================================
# PLAN-003 P1 — Clicking Plan opens the Drawer with empty-state copy
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.plan
class TestPlanDrawerEmpty:
    """PLAN-003: With no active plan the Drawer renders the
    ``No active plan`` empty state."""

    @pytest.mark.test_id("PLAN-003")
    def test_plan_panel_drawer_opens_with_empty_state(
        self,
        plan_page: PlanPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        original_enabled = plan_page.api_get_plan_enabled(api_context)

        try:
            log_test_step("1. Enable Plan Mode")
            plan_page.api_set_plan_enabled(api_context, True)

            log_test_step("2. Open /chat and click the Plan button")
            plan_page.open_chat()
            btn = plan_page.page.locator(plan_page.CHAT_PLAN_BUTTON).first
            expect(btn).to_be_visible(timeout=plan_page.timeout)
            btn.click()

            log_test_step("3. Drawer renders with the empty state")
            expect(
                plan_page.page.locator(plan_page.PLAN_DRAWER).first
            ).to_be_visible(timeout=plan_page.timeout)
            expect(
                plan_page.page.locator(plan_page.PLAN_EMPTY_STATE).first
            ).to_be_visible(timeout=plan_page.timeout)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            plan_page.api_set_plan_enabled(api_context, original_enabled)


# ============================================================================
# PLAN-004 P0 — Drawer renders a seeded plan with subtasks
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.plan
class TestPlanDrawerWithSeededPlan:
    """PLAN-004: When session state on disk carries a plan_notebook
    with a current_plan, opening the Drawer renders the plan name and
    its subtasks. This proves the data path
    file -> /plan/current -> PlanPanel works end-to-end without ever
    invoking the LLM."""

    @pytest.mark.test_id("PLAN-004")
    def test_plan_panel_renders_seeded_plan(
        self,
        plan_page: PlanPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        original_enabled = plan_page.api_get_plan_enabled(api_context)
        plan_name = "E2E Seeded Plan"
        session_id = None

        try:
            log_test_step("1. Enable Plan Mode")
            plan_page.api_set_plan_enabled(api_context, True)

            log_test_step("2. Open /chat and let frontend create a session")
            plan_page.open_chat()

            log_test_step("3. Read the real session_id assigned by frontend")
            session_id = plan_page.wait_and_read_session_id()

            log_test_step("4. Write plan seed to this session's state file")
            plan_page.seed_plan_session_state(
                session_id=session_id,
                plan_name=plan_name,
            )

            log_test_step(
                "5. Reload to make PlanPanel re-fetch from disk"
            )
            plan_page.page.reload(wait_until="load", timeout=30000)
            plan_page.page.wait_for_timeout(3000)
            # After reload the frontend may re-select the same session
            # or a different one. Ensure the seed covers the current id.
            new_sid = plan_page.wait_and_read_session_id()
            if new_sid != session_id:
                logger.info(
                    "Session id changed after reload: %s -> %s, "
                    "copying seed",
                    session_id,
                    new_sid,
                )
                plan_page.seed_plan_session_state(
                    session_id=new_sid,
                    plan_name=plan_name,
                )
                session_id = new_sid

            log_test_step("6. Click the Plan button")
            btn = plan_page.page.locator(plan_page.CHAT_PLAN_BUTTON).first
            expect(btn).to_be_visible(timeout=plan_page.timeout)
            btn.click()

            log_test_step("7. Drawer shows the plan name")
            expect(
                plan_page.page.locator(plan_page.PLAN_DRAWER).first
            ).to_be_visible(timeout=plan_page.timeout)
            expect(
                plan_page.page.locator(
                    f'{plan_page.PLAN_DRAWER} >> text="{plan_name}"'
                ).first
            ).to_be_visible(timeout=plan_page.timeout)

            log_test_step("8. All three seeded subtasks are visible")
            for needle in (
                "Subtask alpha",
                "Subtask bravo",
                "Subtask charlie",
            ):
                expect(
                    plan_page.page.locator(
                        f'{plan_page.PLAN_DRAWER} >> text="{needle}"'
                    ).first
                ).to_be_visible(timeout=plan_page.timeout)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed (session={session_id})")
        finally:
            if session_id:
                plan_page.remove_plan_session_state(session_id)
            plan_page.api_set_plan_enabled(api_context, original_enabled)
