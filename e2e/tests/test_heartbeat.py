# -*- coding: utf-8 -*-
"""
QwenPaw Heartbeat module P0 end-to-end tests

P0 definition:
- Core user operation flows
- Combined coverage of multiple features
- Real user scenario simulation
- High-priority functionality validation

Test framework: pytest + Playwright + Page Object Pattern
Run command: pytest tests/test_heartbeat_p0.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect, TimeoutError

from pages.heartbeat_page import HeartbeatPage
from config.settings import config
from utils.helpers import (
    log_test_step,
    log_test_result,
    take_screenshot,
    assert_text_contains,
)

logger = logging.getLogger(__name__)

# ============================================================================
# HEART-001: Page display + enable/disable
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.heartbeat_core
class TestHeartbeatDisplayAndToggle:
    """
    HEART-001: Page display + enable/disable

    Combined coverage:
    1. Heartbeat page access and load
    2. Page title validation
    3. Config card and form elements display (switch, interval, time, save button)
    4. Toggle enable/disable state
    5. Save and verify state change
    6. Restore original state

    Business scenario:
    Admin opens the heartbeat config page, confirms all config items render
    correctly, then toggles enable/disable and verifies the change took effect.
    """

    @pytest.mark.test_id("HEART-001")
    def test_heartbeat_display_and_toggle(self, heartbeat_page: HeartbeatPage, request: pytest.FixtureRequest):
        """
        Verify page display and enable/disable toggle.

        Steps:
        1. Open Heartbeat page, verify title
        2. Verify config card and form elements (switch, interval, time, save button)
        3. Record current enabled state
        4. Toggle state and save
        5. Verify state change
        6. Restore original state
        """
        test_name = request.node.name

        log_test_step("1. Open Heartbeat page, verify title")
        heartbeat_page.open()

        log_test_step("2. Verify config card and form elements")
        expect(heartbeat_page.page.locator(heartbeat_page.ENABLED_SWITCH).first).to_be_visible()
        expect(heartbeat_page.page.locator(heartbeat_page.INTERVAL_INPUT).first).to_be_visible()
        expect(heartbeat_page.page.locator(heartbeat_page.SAVE_BTN).first).to_be_visible()
        logger.info("All config elements displayed correctly")

        log_test_step("3. Record current enabled state")
        original_state = heartbeat_page.is_heartbeat_enabled()
        logger.info(f"Original state: {'enabled' if original_state else 'disabled'}")

        log_test_step("4. Toggle state and save")
        heartbeat_page.toggle_heartbeat()
        heartbeat_page.save_config()

        log_test_step("5. Verify state change")
        new_state = heartbeat_page.is_heartbeat_enabled()
        assert new_state != original_state, \
            f"State should change from {'enabled' if original_state else 'disabled'} to {'disabled' if original_state else 'enabled'}"
        logger.info(f"State changed to {'enabled' if new_state else 'disabled'}")

        log_test_step("6. Restore original state")
        if heartbeat_page.is_heartbeat_enabled() != original_state:
            heartbeat_page.toggle_heartbeat()
            heartbeat_page.save_config()

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - page display and enable/disable toggle work")

# ============================================================================
# HEART-002: Full config flow (interval + time + skill + save verification)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.heartbeat_config
class TestHeartbeatFullConfig:
    """
    HEART-002: Full config flow

    Combined coverage:
    1. Record original config
    2. Set heartbeat interval (value + unit)
    3. Set scheduled time
    4. Choose skill
    5. Enable heartbeat
    6. Save and verify all config took effect
    7. Restore original config

    Business scenario:
    Admin completes full heartbeat config in one go: set interval to 30 minutes,
    scheduled time to 09:00, choose a skill, enable heartbeat, then save and
    verify all config items took effect.
    """

    @pytest.mark.test_id("HEART-002")
    def test_full_heartbeat_configuration(self, heartbeat_page: HeartbeatPage, request: pytest.FixtureRequest):
        """
        Verify full heartbeat config flow.

        Steps:
        1. Open Heartbeat page
        2. Record original config (enabled state, interval, time)
        3. Set interval to 15 minutes
        4. Set scheduled time to 09:00
        5. Choose a skill (if any available)
        6. Enable heartbeat, save config
        7. Verify all config took effect
        8. Restore original config
        """
        test_name = request.node.name
        test_time = "09:00"

        log_test_step("1. Open Heartbeat page")
        heartbeat_page.open()

        log_test_step("2. Record original config")
        original_enabled = heartbeat_page.is_heartbeat_enabled()
        original_interval = heartbeat_page.get_interval()
        original_time = heartbeat_page.get_scheduled_time()
        logger.info(f"Original config: enabled={original_enabled}, interval={original_interval}, time={original_time}")

        log_test_step("3. Set interval to 15 minutes")
        heartbeat_page.set_interval(15, "分钟")

        log_test_step("4. Set scheduled time to 09:00")
        heartbeat_page.set_scheduled_time(test_time)

        log_test_step("5. Choose a skill (if any available)")
        skill_select = heartbeat_page.page.locator(heartbeat_page.SKILL_SELECT)
        if skill_select.count() > 0:
            skill_select.click()
            options = heartbeat_page.page.locator('.ant-select-option')
            if options.count() > 0:
                options.first.click()
                logger.info("Skill selected")

        log_test_step("6. Enable heartbeat, save config")
        heartbeat_page.configure_heartbeat(
            enabled=True,
            interval=15,
            unit="分钟",
            scheduled_time=test_time,
        )

        log_test_step("7. Verify config took effect")
        heartbeat_page.assert_heartbeat_enabled()
        heartbeat_page.assert_interval(15, "分钟")
        heartbeat_page.assert_config_saved()
        logger.info("All config took effect")

        log_test_step("8. Restore original config")
        heartbeat_page.configure_heartbeat(
            enabled=original_enabled,
            interval=int(original_interval.get("value", 30)),
            unit=original_interval.get("unit", "分钟") or "分钟",
            scheduled_time=original_time,
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - full heartbeat config flow works, original config restored")

# ============================================================================
# HEART-003: Target session selection and active hours config
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.heartbeat_config
class TestHeartbeatTargetAndActiveHours:
    """
    HEART-003: Target session selection and active hours config

    Combined coverage:
    1. Open Heartbeat page
    2. Record original config
    3. Find target session selector (main/last)
    4. Verify selector exists and record current value
    5. Switch target session option
    6. Find active hours toggle
    7. Enable active hours
    8. Set start time
    9. Set end time
    10. Save config
    11. Verify config saved
    12. Restore original config

    Business scenario:
    Admin configures heartbeat target session and active hours, verifies that
    different target session options and active hours config are saved correctly.
    """

    @pytest.mark.test_id("HEART-003")
    def test_target_session_and_active_hours(self, heartbeat_page: HeartbeatPage, request: pytest.FixtureRequest):
        """
        Verify target session selection and active hours config.

        Steps:
        1. Open Heartbeat page
        2. Record original config
        3. Find target session selector (main/last)
        4. Verify selector exists and record current value
        5. Switch target session option
        6. Find active hours toggle
        7. Enable active hours
        8. Set start time
        9. Set end time
        10. Save config
        11. Verify config saved
        12. Restore original config
        """
        test_name = request.node.name

        log_test_step("1. Open Heartbeat page")
        heartbeat_page.open()

        log_test_step("2. Record original config")
        original_enabled = heartbeat_page.is_heartbeat_enabled()
        original_interval = heartbeat_page.get_interval()
        original_time = heartbeat_page.get_scheduled_time()
        logger.info(f"Original config: enabled={original_enabled}, interval={original_interval}, time={original_time}")

        log_test_step("3. Find target session selector (main/last)")
        target_session_selector = heartbeat_page.page.locator(
            '.qwenpaw-radio-group, .qwenpaw-select, [class*="targetSession"], [class*="target"]'
        ).first
        expect(target_session_selector).to_be_visible(timeout=3000)
        logger.info("Target session selector exists")

        log_test_step("4. Verify selector exists and record current value")
        current_target = ""
        main_option = heartbeat_page.page.locator(
            '.qwenpaw-radio-label:has-text("main"), .qwenpaw-radio-label:has-text("主会话"), '
            '[class*="radio"]:has-text("main"), [class*="radio"]:has-text("主")'
        ).first
        last_option = heartbeat_page.page.locator(
            '.qwenpaw-radio-label:has-text("last"), .qwenpaw-radio-label:has-text("最近"), '
            '[class*="radio"]:has-text("last"), [class*="radio"]:has-text("最近")'
        ).first

        if main_option.is_visible():
            current_target = "main" if main_option.get_attribute('aria-checked') == 'true' else "last"
        elif last_option.is_visible():
            current_target = "last" if last_option.get_attribute('aria-checked') == 'true' else "main"
        logger.info(f"Current target session: {current_target}")

        log_test_step("5. Switch target session option")
        if current_target == "main" and last_option.is_visible():
            last_option.click()
            heartbeat_page.page.wait_for_timeout(1000)
            logger.info("Switched to last session")
        elif current_target == "last" and main_option.is_visible():
            main_option.click()
            heartbeat_page.page.wait_for_timeout(1000)
            logger.info("Switched to main session")

        log_test_step("6. Find active hours toggle")
        active_hours_switch = heartbeat_page.page.locator(
            '.qwenpaw-switch, [class*="activeHours"], [class*="active"]'
        ).first
        expect(active_hours_switch).to_be_visible(timeout=3000)
        logger.info("Active hours toggle exists")

        log_test_step("7. Enable active hours")
        active_hours_checked = active_hours_switch.get_attribute('aria-checked')
        if active_hours_checked != 'true':
            active_hours_switch.click()
            heartbeat_page.page.wait_for_timeout(1000)
            logger.info("Active hours enabled")

        log_test_step("8. Set start time")
        start_time_picker = heartbeat_page.page.locator(
            '.qwenpaw-picker, .qwenpaw-time-picker, [class*="startTime"], [class*="start"]'
        ).first
        if start_time_picker.is_visible():
            start_time_picker.click()
            heartbeat_page.page.wait_for_timeout(500)
            # Select 09:00
            time_option = heartbeat_page.page.locator('.qwenpaw-picker-panel li, .ant-picker-panel li').filter(has_text="09").first
            if time_option.is_visible():
                time_option.click()
                heartbeat_page.page.wait_for_timeout(500)
            logger.info("Start time set")

        log_test_step("9. Set end time")
        end_time_picker = heartbeat_page.page.locator(
            '.qwenpaw-picker, .qwenpaw-time-picker, [class*="endTime"], [class*="end"]'
        ).first
        if end_time_picker.is_visible():
            end_time_picker.click()
            heartbeat_page.page.wait_for_timeout(500)
            # Select 18:00
            time_option = heartbeat_page.page.locator('.qwenpaw-picker-panel li, .ant-picker-panel li').filter(has_text="18").first
            if time_option.is_visible():
                time_option.click()
                heartbeat_page.page.wait_for_timeout(500)
            logger.info("End time set")

        log_test_step("10. Save config")
        save_btn = heartbeat_page.page.locator(heartbeat_page.SAVE_BTN).first
        if save_btn.is_visible():
            save_btn.click()
            heartbeat_page.page.wait_for_timeout(2000)
            logger.info("Save button clicked")

        log_test_step("11. Verify config saved")
        heartbeat_page.assert_config_saved()
        logger.info("Config saved")

        log_test_step("12. Restore original config")
        heartbeat_page.configure_heartbeat(
            enabled=original_enabled,
            interval=int(original_interval.get("value", 30)),
            unit=original_interval.get("unit", "分钟") or "分钟",
            scheduled_time=original_time,
        )
        logger.info("Original config restored")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - target session selection and active hours config work")

# ============================================================================
# HB-P2-001: Interval unit switch (minute/hour combinations)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.heartbeat
class TestHeartbeatIntervalUnit:
    """HB-P2-001: Interval unit switch"""

    @pytest.mark.test_id("HB-P2-001")
    def test_heartbeat_interval_unit(self, page: Page, heartbeat_page: "HeartbeatPage", request: pytest.FixtureRequest):
        """Test heartbeat interval unit switching."""
        test_name = request.node.name

        log_test_step("Navigate to heartbeat config page")
        heartbeat_page.open()

        log_test_step("Find interval unit selector")
        # The unit selector on the page has input id=everyUnit and class containing everyUnit
        # Need to locate the .qwenpaw-select container that wraps this input
        unit_select = page.locator('.qwenpaw-select:has(#everyUnit)').first

        if unit_select.count() > 0:
            # Get currently selected unit text (use selection-item to avoid duplicate text)
            selection_item = unit_select.locator('.qwenpaw-select-selection-item')
            if selection_item.count() > 0:
                current_unit = selection_item.get_attribute('title') or selection_item.inner_text().strip()
            else:
                current_unit = unit_select.inner_text().strip().split('\n')[0]
            logger.info(f"Current interval unit: {current_unit}")

            log_test_step("Click unit selector to expand options")
            unit_select.click()
            page.wait_for_timeout(500)

            options = page.locator('.qwenpaw-select-item-option').all()
            assert len(options) > 0, "Unit dropdown options should not be empty"
            logger.info(f"Found {len(options)} unit options")

            option_texts = []
            for opt in options:
                opt_title = opt.get_attribute('title') or opt.inner_text().strip()
                option_texts.append(opt_title)
                logger.info(f"  Unit option: {opt_title}")

            log_test_step("Switch to another unit")
            # Pick a unit different from the current one
            target_option = None
            target_text = None
            for opt in options:
                opt_title = opt.get_attribute('title') or opt.inner_text().strip()
                if opt_title != current_unit:
                    target_option = opt
                    target_text = opt_title
                    break

            if target_option:
                target_option.click()
                page.wait_for_timeout(500)

                # Re-read selected value
                if selection_item.count() > 0:
                    new_unit = selection_item.get_attribute('title') or selection_item.inner_text().strip()
                else:
                    new_unit = unit_select.inner_text().strip().split('\n')[0]
                logger.info(f"Unit after switch: {new_unit}")
                assert new_unit == target_text, f"Unit should switch to {target_text}, actual: {new_unit}"
                logger.info(f"Unit switched from '{current_unit}' to '{new_unit}'")

                log_test_step("Restore original unit")
                unit_select.click()
                page.wait_for_timeout(500)
                restore_option = page.locator(f'.qwenpaw-select-item-option:has-text("{current_unit}")').first
                if restore_option.count() > 0:
                    restore_option.click()
                    page.wait_for_timeout(500)
                    logger.info(f"Restored to original unit: {current_unit}")
                else:
                    page.keyboard.press("Escape")
            else:
                logger.info("Only one unit option available, cannot switch")
                page.keyboard.press("Escape")
        else:
            pytest.skip("Interval unit selector not found, skipping test")

        log_test_result(test_name, True, 0)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def heartbeat_page(page: Page) -> HeartbeatPage:
    """Create a HeartbeatPage instance."""
    return HeartbeatPage(page)
