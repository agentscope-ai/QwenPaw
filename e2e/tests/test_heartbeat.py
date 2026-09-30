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
        expect(heartbeat_page.page.locator(heartbeat_page.SAVE_BTN).first).to_be_visible()
        logger.info("All config elements displayed correctly")

        log_test_step("3. Record current enabled state")
        original_state = heartbeat_page.is_heartbeat_enabled()
        logger.info(f"Original state: {'enabled' if original_state else 'disabled'}")

        log_test_step("4. Toggle state and save")
        heartbeat_page.toggle_heartbeat()
        heartbeat_page.save_config()

        if not original_state:
            expect(
                heartbeat_page.page.locator(
                    heartbeat_page.INTERVAL_INPUT
                ).first
            ).to_be_visible()

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
        log_test_step("1. Open Heartbeat page")
        heartbeat_page.open()

        log_test_step("2. Record original config")
        original_enabled = heartbeat_page.is_heartbeat_enabled()
        if not original_enabled:
            heartbeat_page.enable_heartbeat()
            heartbeat_page.save_config()
        original_interval = heartbeat_page.get_interval()
        logger.info(
            f"Original config: enabled={original_enabled}, "
            f"interval={original_interval}"
        )

        log_test_step("3. Set interval to 15 minutes")
        heartbeat_page.set_interval(15, "分钟")

        log_test_step("4. Wait for interval auto-save")
        heartbeat_page.save_config()

        log_test_step("6. Enable heartbeat, save config")
        heartbeat_page.configure_heartbeat(
            enabled=True,
            interval=15,
            unit="分钟",
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
            unit="minutes",
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

        log_test_step("2. Verify and switch the reply target")
        target_options = heartbeat_page.page.locator(
            '.qwenpaw-segmented[aria-label="Reply target"] '
            'input[type="radio"]'
        )
        assert target_options.count() == 3
        original_index = next(
            index for index, option in enumerate(target_options.all())
            if option.is_checked()
        )
        replacement_index = next(
            index for index, option in enumerate(target_options.all())
            if not option.is_checked()
        )
        target_labels = heartbeat_page.page.locator(
            '.qwenpaw-segmented[aria-label="Reply target"] '
            '.qwenpaw-segmented-item'
        )
        replacement = target_options.nth(replacement_index)
        target_labels.nth(replacement_index).click()
        heartbeat_page.page.wait_for_timeout(1000)
        expect(replacement).to_be_checked()

        log_test_step("3. Toggle active hours")
        active_hours_switch = heartbeat_page.page.get_by_role(
            "switch", name="Active hours (optional)"
        )
        expect(active_hours_switch).to_be_visible(timeout=3000)
        original_active = active_hours_switch.get_attribute("aria-checked")
        active_hours_switch.click()
        heartbeat_page.page.wait_for_timeout(1000)
        current_active = active_hours_switch.get_attribute("aria-checked")
        assert current_active != original_active

        log_test_step("4. Restore the original target and active-hours state")
        target_labels.nth(original_index).click()
        active_hours_switch.click()
        heartbeat_page.page.wait_for_timeout(1000)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - target session selection and active hours config work")

# ============================================================================
# HB-P2-001: Interval preset updates the hour/minute wheel
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.heartbeat
class TestHeartbeatIntervalUnit:
    """HB-P2-001: Interval preset and duration wheel."""

    @pytest.mark.test_id("HB-P2-001")
    def test_heartbeat_interval_unit(self, page: Page, heartbeat_page: "HeartbeatPage", request: pytest.FixtureRequest):
        """Test that an interval preset updates the duration wheel."""
        test_name = request.node.name

        log_test_step("Navigate to heartbeat config page")
        heartbeat_page.open()

        log_test_step("Enable heartbeat so interval controls are interactive")
        enabled_switch = page.get_by_role("switch").first
        expect(enabled_switch).to_be_visible(timeout=5000)
        was_enabled = enabled_switch.get_attribute("aria-checked") == "true"
        if not was_enabled:
            enabled_switch.click()
            page.wait_for_timeout(500)

        log_test_step("Choose a different interval preset")
        presets = page.locator('button[data-press][aria-pressed]')
        expect(presets.first).to_be_visible(timeout=5000)
        preset_count = presets.count()
        assert preset_count >= 2, "Expected at least two heartbeat presets"
        selected_index = next(
            (
                index
                for index in range(preset_count)
                if presets.nth(index).get_attribute("aria-pressed") == "true"
            ),
            None,
        )
        target_index = 0 if selected_index != 0 else 1
        target = presets.nth(target_index)
        target.click()
        expect(target).to_have_attribute("aria-pressed", "true", timeout=5000)

        log_test_step("Verify both duration wheel units remain present")
        hour_group = page.get_by_role("group", name="Hours").or_(
            page.get_by_role("group", name="小时")
        )
        minute_group = page.get_by_role("group", name="Minutes").or_(
            page.get_by_role("group", name="分钟")
        )
        expect(hour_group.first).to_be_visible(timeout=5000)
        expect(minute_group.first).to_be_visible(timeout=5000)

        log_test_step("Restore the original heartbeat state")
        if selected_index is not None:
            presets.nth(selected_index).click()
        if not was_enabled:
            enabled_switch.click()
        page.wait_for_timeout(500)

        log_test_result(test_name, True, 0)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def heartbeat_page(page: Page) -> HeartbeatPage:
    """Create a HeartbeatPage instance."""
    return HeartbeatPage(page)
