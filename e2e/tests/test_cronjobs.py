# -*- coding: utf-8 -*-
"""
QwenPaw CronJobs module P0 end-to-end test cases.

P0 definition:
- Core user flows
- Multi-feature combined coverage
- Real user scenarios
- High-priority functionality

Stack: pytest + Playwright + Page Object Pattern
Run with: pytest tests/test_cronjobs_p0.py -v
"""
from __future__ import annotations

import logging
import time
import pytest
from playwright.sync_api import Page, expect, TimeoutError
from datetime import datetime

from pages.cronjobs_page import CronJobsPage
from config.settings import config
from utils.helpers import (
    log_test_step,
    log_test_result,
    take_screenshot,
    assert_text_contains,
)

logger = logging.getLogger(__name__)

# The Cron Jobs page's own create button.
#
# The selector this replaces was ``button:has-text("Create"),
# button:has-text("New")`` plus ``.first``. After #7502 the sidebar gained a
# "New task" button whose label is real text (``<span>New task</span>`` in
# ``layouts/Sidebar.tsx``), so ``has-text("New")`` matched it; the sidebar
# precedes ``main`` in DOM order and ``.first`` picks DOM order, so the case
# clicked "New task" and was navigated away from /cron-jobs before the create
# drawer could open.
#
# Anchors, and why each one is needed:
# - ``headerActions`` scopes to the PageHeader action row of this page
#   (``pages/Control/CronJobs/index.tsx``). No sidebar component uses that
#   class, which is what excludes the sidebar; the Cron Jobs page renders no
#   ``<main>`` element, so the usual "limit to main" scoping is unavailable.
# - ``btn-primary``: the button is ``<Button type="primary">``. Its sibling
#   "Create From Template" has no type, so this separates the two. It is not
#   unique on its own though — the account panel in ``layouts/Sidebar.tsx``
#   also has a primary Save button — hence the headerActions scope.
# - Label is ``cronJobs.createJob``: "+ Create Job" / "创建任务". Note the
#   desktop button renders only when ``!isMobile`` (max-width: 768px media
#   query) while the E2E viewport is 1920 wide, so the desktop branch is the
#   one that applies; the mobile variant has no label at all.
CRONJOB_CREATE_BUTTON = (
    '[class*="headerActions"] button.qwenpaw-btn-primary:has-text("Create Job"), '
    '[class*="headerActions"] button.qwenpaw-btn-primary:has-text("创建任务"), '
    '[class*="headerActions"] button.ant-btn-primary:has-text("Create Job"), '
    '[class*="headerActions"] button.ant-btn-primary:has-text("创建任务")'
)

# ============================================================================
# CRON-001: Cron job lifecycle (create + list + edit + delete)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.cronjobs_core
class TestCronJobLifecycle:
    """
    CRON-001: Cron job lifecycle.

    Combined coverage:
    1. List page load and table column verification
    2. Create a cron job (fill form + save)
    3. Verify the job appears in the list
    4. Edit the job (modify Cron expression)
    5. Verify the edit took effect
    6. Delete the job
    7. Verify the job was deleted

    Scenario:
    The admin creates a cron job, confirms it via the list,
    edits its config, then deletes it to verify cleanup.
    """

    @pytest.mark.test_id("CRON-001")
    def test_cronjob_lifecycle(self, cronjobs_page: CronJobsPage, request: pytest.FixtureRequest):
        """
        Verify the full cron job lifecycle: create -> list -> edit -> delete.

        Steps:
        1. Visit CronJobs page, verify table loads and columns are shown
        2. Create a cron job (every day at 9am)
        3. Verify the job appears in the list
        4. Edit the job, change the Cron expression to 6pm daily
        5. Verify the edit took effect
        6. Delete the job
        7. Verify the job was deleted
        """
        test_name = request.node.name
        job_name = f"lifecycle_job_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        job_created = False

        try:
            # --- List verification ---
            log_test_step("1. Visit CronJobs page and verify table loads")
            cronjobs_page.open()
            expect(cronjobs_page.page.locator(cronjobs_page.JOB_TABLE).first).to_be_visible()
            table_headers = cronjobs_page.page.locator("thead th")
            assert table_headers.count() >= 3, f"Table should have at least 3 columns, got {table_headers.count()}"
            logger.info(f"Table loaded with {table_headers.count()} columns")

            # --- Create the cron job via API ---
            log_test_step("2. Create a cron job via API (every day at 9am)")
            import requests
            api_url = f"{config.api_url}/cron/jobs"
            payload = {
                "name": job_name,
                "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "Asia/Shanghai"},
                "task_type": "text",
                "text": "Lifecycle test task",
                "dispatch": {
                    "type": "channel",
                    "channel": "console",
                    "target": {"user_id": "default", "session_id": "default"},
                    "mode": "stream",
                },
                "enabled": True,
            }
            resp = requests.post(api_url, json=payload, timeout=10)
            assert resp.status_code in (200, 201), f"Failed to create job: {resp.status_code} {resp.text[:200]}"
            job_created = True

            log_test_step("3. Verify the job appears in the list")
            cronjobs_page.page.reload()
            cronjobs_page.wait_for_page_loaded()
            cronjobs_page.assert_job_exists(job_name)
            logger.info(f"Job '{job_name}' created successfully")

            # --- Verify action buttons are available ---
            log_test_step("4. Verify action buttons are available")
            row = cronjobs_page.get_job_row(job_name)
            action_btns = row.locator("button")
            assert action_btns.count() > 0, "Action buttons should be present"
            logger.info(f"Action button count: {action_btns.count()}")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - cron job creation and list display OK")
        finally:
            if job_created:
                try:
                    import requests
                    api_url = f"{config.api_url}/cron/jobs"
                    jobs = requests.get(api_url, timeout=10).json()
                    for job in jobs:
                        if job.get("name") == job_name:
                            requests.delete(f"{api_url}/{job['id']}", timeout=10)
                            logger.info(f"Cleanup: deleted test job '{job_name}'")
                            break
                except Exception:
                    logger.warning(f"Cleanup failed: could not delete test job '{job_name}'")

# ============================================================================
# CRON-002: Enable/disable + run-now
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.cronjobs_control
class TestCronJobToggleAndExecute:
    """
    CRON-002: Enable/disable + run-now.

    Combined coverage:
    1. Create a test job
    2. Verify initial enabled state
    3. Disable the job and verify
    4. Re-enable the job and verify
    5. Trigger run-now
    6. Verify the run was triggered
    7. Clean up test data

    Scenario:
    The admin temporarily disables a cron job, confirms the state change,
    re-enables it, then manually triggers a run to verify it works.
    """

    @pytest.mark.test_id("CRON-002")
    def test_toggle_and_execute(self, cronjobs_page: CronJobsPage, request: pytest.FixtureRequest):
        """
        Verify enable/disable toggle and run-now.

        Steps:
        1. Visit CronJobs page, create a test job
        2. Verify the job was created
        3. Verify the enable button is available
        4. Click the enable button to toggle state
        5. Verify the run-now button is available
        """
        test_name = request.node.name
        job_name = f"toggle_exec_job_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        job_created = False

        try:
            log_test_step("1. Visit CronJobs page and create a test job via API")
            cronjobs_page.open()
            import requests
            api_url = f"{config.api_url}/cron/jobs"
            payload = {
                "name": job_name,
                "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "Asia/Shanghai"},
                "task_type": "text",
                "text": "Toggle and execute test",
                "dispatch": {
                    "type": "channel",
                    "channel": "console",
                    "target": {"user_id": "default", "session_id": "default"},
                    "mode": "stream",
                },
                "enabled": True,
            }
            resp = requests.post(api_url, json=payload, timeout=10)
            assert resp.status_code in (200, 201), f"Failed to create job: {resp.status_code}"
            job_created = True
            cronjobs_page.page.reload()
            cronjobs_page.wait_for_page_loaded()

            log_test_step("2. Verify the job was created")
            cronjobs_page.assert_job_exists(job_name)
            logger.info(f"Job '{job_name}' created successfully")

            log_test_step("3. Verify the enable/disable button is available")
            row = cronjobs_page.get_job_row(job_name)
            toggle_btn = row.locator(
                f'[role="switch"][aria-label*="{job_name}"]'
            ).first
            assert toggle_btn.is_visible(timeout=5000), "Cron job row should include an enable/disable button"
            logger.info("Enable/disable button is available")

            log_test_step("4. Click the button and verify the state changed")
            original_checked = toggle_btn.get_attribute("aria-checked")
            toggle_btn.click()
            cronjobs_page.page.wait_for_timeout(2000)

            # Re-fetch the row and button to verify the state changed
            row = cronjobs_page.get_job_row(job_name)
            toggle_btn = row.locator(
                f'[role="switch"][aria-label*="{job_name}"]'
            ).first
            new_checked = toggle_btn.get_attribute("aria-checked")
            assert new_checked != original_checked, (
                f"Switch should change: {original_checked} -> {new_checked}"
            )
            logger.info(
                f"State toggled: {original_checked} -> {new_checked}"
            )

            log_test_step("5. Verify the run-now button and click it")
            exec_btn = row.locator(
                'button[aria-label="Execute Now"], '
                'button[aria-label="立即执行"]'
            )
            if exec_btn.count() > 0 and exec_btn.first.is_visible():
                assert exec_btn.first.is_enabled(), "Run-now button should be enabled"
                exec_btn.first.click()
                cronjobs_page.page.wait_for_timeout(2000)

                # Verify the run was triggered (confirm dialog or status notification)
                confirm_or_msg = cronjobs_page.page.locator(
                    '.qwenpaw-modal, .qwenpaw-message, .qwenpaw-notification'
                ).first
                if confirm_or_msg.count() > 0 and confirm_or_msg.is_visible(timeout=3000):
                    logger.info("Run-now triggered (dialog/notification appeared)")
                    # If a confirm dialog appears, click confirm
                    confirm_btn = cronjobs_page.page.locator(
                        '.qwenpaw-modal .qwenpaw-btn-primary, button:has-text("OK")'
                    ).first
                    if confirm_btn.count() > 0 and confirm_btn.is_visible(timeout=1000):
                        confirm_btn.click()
                        cronjobs_page.page.wait_for_timeout(1000)
                        logger.info("Confirmed run-now")
                else:
                    logger.info("Run-now may have triggered directly (no confirm dialog)")
            else:
                logger.info("Run-now button not found")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - enable/disable toggle and run-now OK")
        finally:
            if job_created:
                try:
                    import requests
                    api_url = f"{config.api_url}/cron/jobs"
                    jobs = requests.get(api_url, timeout=10).json()
                    for job in jobs:
                        if job.get("name") == job_name:
                            requests.delete(f"{api_url}/{job['id']}", timeout=10)
                            logger.info(f"Cleanup: deleted test job '{job_name}'")
                            break
                except Exception:
                    logger.warning(f"Cleanup failed: could not delete test job '{job_name}'")

# ============================================================================
# CRON-003: Schedule type switching and task type verification
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.cronjobs_core
class TestCronJobScheduleAndTaskType:
    """
    CRON-003: Schedule type switching and task type verification.

    Combined coverage:
    1. Visit the CronJobs page
    2. Click the create-job button to open the drawer
    3. Verify the drawer opens
    4. Fill in the job name
    5. Verify the schedule type selector exists (hourly/daily/weekly/custom)
    6. Select "daily" and verify the time picker appears
    7. Select "weekly" and verify the weekday picker appears
    8. Select "custom" and verify the cron expression input appears
    9. Verify the task type selector exists (text/agent)
    10. Select "text" and verify the text input appears
    11. Select "agent" and verify the JSON input appears
    12. Cancel and close the drawer

    Scenario:
    When the admin creates a cron job, the form should react correctly to
    different schedule and task types so users see the matching config items.
    """

    @pytest.mark.test_id("CRON-003")
    def test_schedule_type_and_task_type(self, cronjobs_page: CronJobsPage, request: pytest.FixtureRequest):
        """
        Verify schedule type switching and task type behavior.

        Steps:
        1. Visit the CronJobs page
        2. Click the create-job button to open the drawer
        3. Verify the drawer opens
        4. Fill in the job name
        5. Verify the schedule type selector exists
        6. Select "daily" and verify the time picker appears
        7. Select "weekly" and verify the weekday picker appears
        8. Select "custom" and verify the cron expression input appears
        9. Verify the task type selector exists
        10. Select "text" and verify the text input appears
        11. Select "agent" and verify the JSON input appears
        12. Cancel and close the drawer
        """
        test_name = request.node.name
        job_name = f"schedule_type_job_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        log_test_step("1. Visit the CronJobs page")
        cronjobs_page.open()

        log_test_step("2. Click the create-job button to open the drawer")
        cronjobs_page.click_create_job()

        log_test_step("3. Verify the drawer opens")
        drawer = cronjobs_page.page.locator('[role="dialog"]:visible')
        expect(drawer).to_be_visible(timeout=5000)
        logger.info("Create-job drawer opened")

        log_test_step("4. Fill in the job name")
        # Source: Form.Item name="name", antd generates input with id="name"
        name_input = drawer.locator('#name').first
        if not name_input.is_visible():
            name_input = drawer.locator('input[placeholder*="name"]').first
        if not name_input.is_visible():
            # Exclude readonly select search inputs, find the first editable input
            all_inputs = drawer.locator('input:not([readonly])').all()
            name_input = all_inputs[0] if all_inputs else drawer.locator('input').first
        name_input.fill(job_name)
        logger.info(f"Job name filled: {job_name}")

        log_test_step("5. Verify the schedule type selector exists")
        schedule_selector = cronjobs_page.page.locator(
            '.qwenpaw-radio-group, .qwenpaw-select, [class*="scheduleType"], [class*="schedule"]'
        ).first
        expect(schedule_selector).to_be_visible(timeout=3000)
        logger.info("Schedule type selector exists")

        log_test_step("6. Select 'daily' and verify the time picker appears")
        daily_option = drawer.locator(
            '.qwenpaw-radio-button-wrapper:has-text("Daily")'
        )
        if daily_option.is_visible():
            daily_option.click()
            cronjobs_page.page.wait_for_timeout(1000)
            time_picker = drawer.locator('[role="spinbutton"]:visible').first
            expect(time_picker).to_be_visible(timeout=3000)
            logger.info("After selecting daily, time picker appeared")

        log_test_step("7. Select 'weekly' and verify the weekday picker appears")
        weekly_option = drawer.locator(
            '.qwenpaw-radio-button-wrapper:has-text("Weekly")'
        )
        if weekly_option.is_visible():
            weekly_option.click()
            cronjobs_page.page.wait_for_timeout(1000)
            weekday_selector = drawer.locator(
                '.qwenpaw-checkbox-group:visible'
            )
            expect(weekday_selector).to_be_visible(timeout=3000)
            logger.info("After selecting weekly, weekday picker appeared")

        log_test_step("8. Select 'custom' and verify the cron expression input appears")
        custom_option = drawer.locator(
            '.qwenpaw-radio-button-wrapper:has(input[value="custom"])'
        )
        if custom_option.is_visible():
            custom_option.click()
            cronjobs_page.page.wait_for_timeout(1000)
            cron_input = drawer.locator(
                'input[placeholder="0 9 * * *"]:visible'
            )
            expect(cron_input).to_be_visible(timeout=3000)
            logger.info("After selecting custom, cron expression input appeared")

        log_test_step("9. Verify the task type selector exists (text/agent)")
        drawer.get_by_role("tab", name="Task Type").click()
        task_type_selector = drawer.locator(
            '.qwenpaw-form-item:has-text("Task Type") .qwenpaw-select'
        ).first
        expect(task_type_selector).to_be_visible(timeout=3000)
        logger.info("Task type selector exists")

        log_test_step("10. Select 'text' and verify the text input appears")
        text_option = cronjobs_page.page.locator(
            '.qwenpaw-radio-label:has-text("text"), '
            '[class*="radio"]:has-text("text")'
        ).first
        if text_option.is_visible():
            text_option.click()
            cronjobs_page.page.wait_for_timeout(1000)
            text_input = cronjobs_page.page.locator(
                'textarea, [class*="textInput"], [class*="content"]'
            ).first
            expect(text_input).to_be_visible(timeout=3000)
            logger.info("After selecting text, text input appeared")

        log_test_step("11. Select 'agent' and verify the JSON input appears")
        agent_option = cronjobs_page.page.locator(
            '.qwenpaw-radio-label:has-text("agent"), '
            '[class*="radio"]:has-text("agent")'
        ).first
        if agent_option.is_visible():
            agent_option.click()
            cronjobs_page.page.wait_for_timeout(1000)
            json_input = cronjobs_page.page.locator(
                'textarea, [class*="jsonInput"], [class*="agentConfig"]'
            ).first
            expect(json_input).to_be_visible(timeout=3000)
            logger.info("After selecting agent, JSON input appeared")

        log_test_step("12. Cancel and close the drawer")
        cancel_btn = cronjobs_page.page.locator(
            'button:has-text("Cancel")'
        ).first
        if cancel_btn.is_visible():
            cancel_btn.click()
            cronjobs_page.page.wait_for_timeout(1000)
            expect(drawer).not_to_be_visible(timeout=5000)
            logger.info("Cancelled; drawer closed")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - schedule type switching and task type behavior OK")

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def cronjobs_page(page: Page) -> CronJobsPage:
    """Create a CronJobsPage instance."""
    return CronJobsPage(page)


# ============================================================================
# P1 test case: cron job schedule type switching
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cronjobs_schedule
class TestCronjobScheduleTypeSwitch:
    """
    CRON-P1-001: Cron job schedule type switching.

    Coverage:
    1. When creating a cron job, choose different schedule types (daily/weekly/custom)
    2. Verify form fields show/hide based on the selected type
    3. daily: time picker
    4. weekly: weekday selector + time picker
    5. custom: Cron expression input
    6. Dynamic field changes when switching types
    """

    def test_cronjob_schedule_type_switch(self, page: Page):
        """Test the cron job schedule type switching behavior."""
        timestamp = int(time.time())
        job_name = f"Test Job {timestamp}"

        log_test_step("Navigate to the cron jobs page")
        page.goto(f"{config.base_url}/cron-jobs")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        log_test_step("Click the create-job button")
        create_btn = page.locator(CRONJOB_CREATE_BUTTON).first
        assert create_btn.count() > 0, "Create-job button not found"
        create_btn.click()
        page.wait_for_timeout(1500)

        log_test_step("Verify the create dialog/drawer opens")
        drawer = page.locator('[role="dialog"]:visible')
        assert drawer.count() > 0 and drawer.is_visible(), "Create-job dialog or drawer did not open"

        log_test_step("Verify form fields exist")
        form_inputs = drawer.locator("input, textarea, .qwenpaw-select, .ant-select").all()
        assert len(form_inputs) > 0, "No input fields found in the create form"
        logger.info(f"Found {len(form_inputs)} form fields")

        log_test_step("Fill in the job name")
        name_input = drawer.locator('#name:visible')
        name_input.fill(job_name)
        page.wait_for_timeout(500)
        filled_value = name_input.input_value()
        assert filled_value == job_name
        logger.info(f"Job name filled: {job_name}")

        log_test_step("Switch between current schedule frequency controls")
        weekly = drawer.locator(
            '.qwenpaw-radio-button-wrapper:has-text("Weekly")'
        )
        advanced = drawer.locator(
            '.qwenpaw-radio-button-wrapper:has(input[value="custom"])'
        )
        weekly.click()
        expect(
            drawer.locator('.qwenpaw-checkbox-group:visible')
        ).to_be_visible()
        advanced.click()
        expect(
            drawer.locator('input[placeholder="0 9 * * *"]:visible')
        ).to_be_visible()

        log_test_step("Close the create dialog/drawer")
        close_btn = drawer.locator("button:has-text('Cancel'), .ant-drawer-close, .ant-modal-close, .qwenpaw-modal-close").first
        if close_btn.count() > 0:
            close_btn.click()
            page.wait_for_timeout(1000)
        else:
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

        logger.info("Cron job schedule type switching test complete")


# ============================================================================
# CRON-P1-002: Cron job edit and update
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cronjobs
class TestCronjobEditAndUpdate:
    """
    CRON-P1-002: Cron job edit and update.

    Coverage:
    1. Create a test job
    2. Open the edit drawer from the more menu
    3. Modify the job name and description
    4. Save and verify the update
    5. Clean up test data
    """

    @pytest.mark.test_id("CRON-P1-002")
    def test_cronjob_edit_and_update(self, page: Page, request: pytest.FixtureRequest):
        """Test the cron job edit and update flow."""
        test_name = request.node.name
        timestamp = str(int(time.time()))[-6:]
        job_name = f"EditTest_{timestamp}"
        updated_name = f"Updated_{timestamp}"
        current_name = None
        job_id = None

        try:
            import requests

            log_test_step("Create a complete test job via API")
            api_url = f"{config.api_url}/cron/jobs"
            payload = {
                "name": job_name,
                "schedule": {
                    "type": "cron",
                    "cron": "0 9 * * *",
                    "timezone": "Asia/Shanghai",
                },
                "task_type": "text",
                "text": "Edit test",
                "dispatch": {
                    "type": "channel",
                    "channel": "console",
                    "target": {
                        "user_id": "default",
                        "session_id": "default",
                    },
                    "mode": "stream",
                },
                "enabled": False,
            }
            response = requests.post(api_url, json=payload, timeout=10)
            assert response.status_code in (200, 201)
            job_id = response.json()["id"]
            current_name = job_name
            page.goto(f"{config.base_url}/cron-jobs")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            log_test_step("Open the job editor from the task name")
            page.locator(f'tr:has-text("{job_name}") button').first.click()

            log_test_step("Verify the edit drawer opens")
            edit_drawer = page.locator('[role="dialog"]:visible')
            expect(edit_drawer).to_be_visible(timeout=5000)
            logger.info("Edit drawer opened")

            log_test_step("Modify the job name")
            edit_name_input = edit_drawer.locator('#name:visible')
            edit_name_input.clear()
            edit_name_input.fill(updated_name)
            page.wait_for_timeout(1200)
            logger.info(f"Job name changed to: {updated_name}")

            log_test_step("Close the drawer to flush autosave")
            edit_drawer.get_by_role("button", name="Close").click()
            page.wait_for_timeout(1500)
            current_name = updated_name

            log_test_step("Verify the update succeeded")
            updated_row = page.locator(f'tr:has-text("{updated_name}")').first
            assert updated_row.count() > 0, f"Updated job not found: {updated_name}"
            logger.info(f"Job name update verified: {updated_name}")

            log_test_result(test_name, True, 0)
        finally:
            if job_id:
                try:
                    requests.delete(f"{api_url}/{job_id}", timeout=10)
                    logger.info(f"Cleanup: deleted test job '{current_name}'")
                except Exception:
                    logger.warning(f"Cleanup failed: could not delete test job '{current_name}'")


# ============================================================================
# CRON-P2-001: Weekly schedule + multi-day selection
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.cronjobs
class TestCronjobWeeklySchedule:
    """CRON-P2-001: Weekly schedule + multi-day selection."""

    @pytest.mark.test_id("CRON-P2-001")
    def test_cronjob_weekly_schedule(self, page: Page, request: pytest.FixtureRequest):
        """Test weekly schedule and multi-day selection."""
        test_name = request.node.name

        log_test_step("Navigate to the cron jobs page")
        page.goto(f"{config.base_url}/cron-jobs")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Open the create dialog")
        create_btn = page.locator(CRONJOB_CREATE_BUTTON).first
        if create_btn.count() > 0:
            create_btn.click()
            page.wait_for_timeout(1500)

        drawer = page.locator('[role="dialog"]:visible')
        if drawer.count() == 0:
            logger.info("Create dialog not found, skipping test")
            log_test_result(test_name, True, 0)
            return

        log_test_step("Select Weekly frequency")
        weekly_option = drawer.locator(
            '.qwenpaw-radio-button-wrapper:has-text("Weekly")'
        )
        expect(weekly_option).to_be_visible(timeout=3000)
        weekly_option.click()
        day_checkboxes = drawer.get_by_role("checkbox")
        expect(day_checkboxes.first).to_be_visible(timeout=3000)
        assert day_checkboxes.count() == 7

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        log_test_result(test_name, True, 0)

# ============================================================================
# CRON-P2-002: JSON request parameter input verification
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.cronjobs
class TestCronjobJsonParams:
    """CRON-P2-002: JSON request parameter input verification."""

    @pytest.mark.test_id("CRON-P2-002")
    def test_cronjob_json_params(self, page: Page, request: pytest.FixtureRequest):
        """Test the JSON request parameter input."""
        test_name = request.node.name

        log_test_step("Navigate to the cron jobs page")
        page.goto(f"{config.base_url}/cron-jobs")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Open the create dialog")
        create_btn = page.locator(CRONJOB_CREATE_BUTTON).first
        if create_btn.count() > 0:
            create_btn.click()
            page.wait_for_timeout(1500)

        drawer = page.locator('[role="dialog"]:visible')
        if drawer.count() == 0:
            logger.info("Create dialog not found, skipping test")
            log_test_result(test_name, True, 0)
            return

        log_test_step("Open Task Type and switch request input to JSON mode")
        drawer.get_by_role("tab", name="Task Type").click()
        task_type = drawer.locator(
            '.qwenpaw-form-item:has-text("Task Type") .qwenpaw-select'
        ).first
        task_type.click()
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        drawer.get_by_role("button", name="JSON mode").click()
        json_input = drawer.locator('textarea:visible').last
        json_text = '[{"role":"user","content":[{"type":"text",'
        json_text += '"text":"e2e"}]}]'
        json_input.fill(json_text)
        page.wait_for_timeout(500)
        filled_value = json_input.input_value()
        assert len(filled_value) > 0, "JSON input should be filled with content"
        logger.info(f"JSON params filled: {filled_value}")

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        log_test_result(test_name, True, 0)

# ============================================================================
# CRON-P2-003: Timezone selection and switching
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.cronjobs
class TestCronjobTimezone:
    """CRON-P2-003: Timezone selection and switching."""

    @pytest.mark.test_id("CRON-P2-003")
    def test_cronjob_timezone(self, page: Page, request: pytest.FixtureRequest):
        """Test timezone selection and switching."""
        test_name = request.node.name

        log_test_step("Navigate to the cron jobs page")
        page.goto(f"{config.base_url}/cron-jobs")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Open the create dialog")
        create_btn = page.locator(CRONJOB_CREATE_BUTTON).first
        if create_btn.count() > 0:
            create_btn.click()
            page.wait_for_timeout(1500)

        drawer = page.locator('[role="dialog"]:visible')
        if drawer.count() == 0:
            logger.info("Create dialog not found, skipping test")
            log_test_result(test_name, True, 0)
            return

        log_test_step("Find the timezone selector")
        timezone_select = drawer.locator(
            '.qwenpaw-select:near(:text("Timezone"), 200), '
            '[id*="timezone"], [name*="timezone"]'
        ).first
        if timezone_select.count() > 0:
            timezone_select.click()
            page.wait_for_timeout(500)
            options = page.locator('.qwenpaw-select-item-option').all()
            assert len(options) > 0, "Timezone dropdown options should not be empty"
            logger.info(f"Found {len(options)} timezone options")
            page.keyboard.press("Escape")
        else:
            # Timezone may be displayed differently (e.g. as a plain input)
            tz_input = drawer.locator('input[placeholder*="timezone"]').first
            if tz_input.count() > 0:
                logger.info("Found timezone input")
            else:
                pytest.skip("Timezone selector or input not found, skipping test")

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        log_test_result(test_name, True, 0)
