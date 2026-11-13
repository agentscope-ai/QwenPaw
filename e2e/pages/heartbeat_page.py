# -*- coding: utf-8 -*-
"""
QwenPaw Heartbeat page object.

Wraps all interactions on the Heartbeat page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class HeartbeatPage(BasePage):
    """
    Heartbeat page object.

    Wraps all user actions on the Heartbeat page:
    - Display heartbeat configuration
    - Enable/disable heartbeat
    - Configure heartbeat interval
    - Configure scheduled time
    - Configure heartbeat skill
    - Save configuration
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/heartbeat"
    PAGE_HEADER = "h1, h2, [class*=title], [class*=header]"
    
    # ========== Selector definitions ==========

    PAGE_LOAD_INDICATOR = '[role="switch"][aria-label]'

    # Configuration card
    CONFIG_CARD = ".ant-card, .qwenpaw-card, [class*=card]"
    CONFIG_FORM = ".ant-form, .qwenpaw-form"

    ENABLED_SWITCH = (
        '[role="switch"][aria-label="Enable heartbeat"], '
        '[role="switch"][aria-label="开启心跳"]'
    )
    ENABLED_LABEL = '.ant-form-item:has-text("Enable"), .ant-form-item:has-text("启用"), .qwenpaw-form-item:has-text("启用"), .qwenpaw-form-item:has-text("开启")'

    # Interval configuration.
    # v2.0.0 (PR #5557) added a sibling `#timeoutSeconds` InputNumber to the
    # same page, so the previous broad selector matched two elements and
    # Playwright strict-mode `.fill()` failed. Anchor on `#everyNumber` —
    # the id emitted by the frontend Form.Item name="everyNumber".
    INTERVAL_INPUT = (
        '[role="spinbutton"][aria-label="Hours"], '
        '[role="spinbutton"][aria-label="小时"]'
    )
    INTERVAL_UNIT_SELECT = (
        '[role="spinbutton"][aria-label="Minutes"], '
        '[role="spinbutton"][aria-label="分钟"]'
    )

    # Scheduled time
    TIME_PICKER = '.ant-picker-input > input, .qwenpaw-picker-input > input'
    TIME_PICKER_PANEL = '.ant-picker-panel, .qwenpaw-picker-panel'

    # Skill configuration
    SKILL_SELECT = '.ant-select[data-placeholder*="Skill" i], .ant-select:has-text("skill"), .qwenpaw-select[data-placeholder*="技能" i], .qwenpaw-select:has-text("技能")'

    # The redesigned form persists changes through useAutoSave.
    SAVE_BTN = 'form[class*="schedule"]'

    # Status indicator
    STATUS_INDICATOR = '.ant-badge-status, .qwenpaw-badge-status, .status-indicator'

    # ========== Navigation methods ==========
    
    def open(self) -> "HeartbeatPage":
        """Open the Heartbeat page.

        The Heartbeat page may keep polling, so waiting on networkidle can time out.
        We use domcontentloaded with a longer timeout instead.
        """
        logger.info("Open the Heartbeat page")
        target_url = self.PAGE_URL
        logger.info(f"Navigating to: {target_url}")
        try:
            self.page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            logger.warning(f"Heartbeat page navigation timed out, retry waiting for DOM: {e}")
            self.page.goto(target_url, wait_until="commit", timeout=30000)
        self.page.wait_for_timeout(2000)
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "HeartbeatPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        # Wait for a switch or input to appear (the page has no h1 tag)
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== Configuration getters ==========

    def is_heartbeat_enabled(self) -> bool:
        """Return whether the heartbeat is enabled."""
        switch = self.page.locator(self.ENABLED_SWITCH)
        if switch.count() > 0:
            return switch.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked') || el.getAttribute('aria-checked') === 'true'")
        return False
    
    def get_interval(self) -> Dict[str, Any]:
        """Return the heartbeat interval configuration."""
        hours = self.page.locator(self.INTERVAL_INPUT).first
        minutes = self.page.locator(self.INTERVAL_UNIT_SELECT).first
        hour_value = int(hours.get_attribute("aria-valuenow") or 0)
        minute_value = int(minutes.get_attribute("aria-valuenow") or 0)
        return {"value": hour_value * 60 + minute_value, "unit": "minutes"}

    def get_scheduled_time(self) -> Optional[str]:
        """Return the scheduled time."""
        time_picker = self.page.locator(self.TIME_PICKER)
        if time_picker.count() > 0:
            return time_picker.first.input_value()
        return None

    def get_skill(self) -> Optional[str]:
        """Return the configured skill."""
        skill_select = self.page.locator(self.SKILL_SELECT)
        if skill_select.count() > 0:
            return skill_select.first.inner_text()
        return None

    # ========== Configuration setters ==========

    def toggle_heartbeat(self) -> "HeartbeatPage":
        """Toggle the heartbeat enabled switch."""
        self.page.locator(self.ENABLED_SWITCH).click()
        return self

    def enable_heartbeat(self) -> "HeartbeatPage":
        """Enable the heartbeat."""
        if not self.is_heartbeat_enabled():
            self.toggle_heartbeat()
        return self

    def disable_heartbeat(self) -> "HeartbeatPage":
        """Disable the heartbeat."""
        if self.is_heartbeat_enabled():
            self.toggle_heartbeat()
        return self

    def set_interval(self, value: int, unit: str = "minutes") -> "HeartbeatPage":
        """Set the heartbeat interval (accepts Chinese or English units)."""
        total_minutes = (
            value * 60 if unit in ("小时", "Hours", "hours") else value
        )
        targets = (
            (
                self.page.locator(self.INTERVAL_INPUT).first,
                total_minutes // 60,
            ),
            (
                self.page.locator(self.INTERVAL_UNIT_SELECT).first,
                total_minutes % 60,
            ),
        )
        for control, target in targets:
            expect(control).to_be_visible(timeout=self.timeout)
            control.press("Home")
            for _ in range(target):
                control.press("ArrowDown")
        self.page.wait_for_timeout(800)

        return self

    def set_scheduled_time(self, time_str: str) -> "HeartbeatPage":
        """Set the scheduled time (HH:mm format)."""
        time_picker = self.page.locator(self.TIME_PICKER)
        if time_picker.count() > 0:
            time_picker.click()
            # Type the time directly
            time_picker.fill(time_str)
            # Close the time picker
            self.page.keyboard.press("Enter")
        return self

    def set_skill(self, skill_name: str) -> "HeartbeatPage":
        """Configure the heartbeat skill."""
        skill_select = self.page.locator(self.SKILL_SELECT)
        if skill_select.count() > 0:
            skill_select.click()
            self.page.locator(f'.ant-select-option:has-text("{skill_name}")').click()
        return self

    def save_config(self) -> "HeartbeatPage":
        """Wait for the form's debounced auto-save to finish."""
        self.page.wait_for_timeout(1000)
        return self

    # ========== Full configuration flow ==========

    def configure_heartbeat(
        self,
        enabled: bool = True,
        interval: int = 30,
        unit: str = "minutes",
        scheduled_time: Optional[str] = None,
        skill_name: Optional[str] = None,
    ) -> "HeartbeatPage":
        """End-to-end heartbeat configuration flow."""
        self.set_interval(interval, unit)

        if enabled:
            self.enable_heartbeat()
        else:
            self.disable_heartbeat()

        if scheduled_time:
            self.set_scheduled_time(scheduled_time)

        if skill_name:
            self.set_skill(skill_name)

        self.save_config()
        return self
    
    # ========== Assertion methods ==========

    def assert_heartbeat_enabled(self) -> "HeartbeatPage":
        """Assert that the heartbeat is enabled."""
        assert self.is_heartbeat_enabled(), "Heartbeat should be enabled"
        return self

    def assert_heartbeat_disabled(self) -> "HeartbeatPage":
        """Assert that the heartbeat is disabled."""
        assert not self.is_heartbeat_enabled(), "Heartbeat should be disabled"
        return self

    # Chinese-English unit alias map
    UNIT_ALIASES = {
        "分钟": ["分钟", "Minutes", "minutes", "min"],
        "小时": ["小时", "Hours", "hours", "hour", "hr"],
        "秒": ["秒", "Seconds", "seconds", "sec"],
        "Minutes": ["分钟", "Minutes", "minutes", "min"],
        "Hours": ["小时", "Hours", "hours", "hour", "hr"],
        "Seconds": ["秒", "Seconds", "seconds", "sec"],
    }

    def assert_interval(self, expected_value: int, expected_unit: str = "分钟") -> "HeartbeatPage":
        """Assert the interval configuration (accepts Chinese or English units)."""
        interval = self.get_interval()
        expected_minutes = (
            expected_value * 60
            if expected_unit in ("小时", "Hours", "hours")
            else expected_value
        )
        assert int(interval["value"]) == expected_minutes, (
            f"Interval should be {expected_minutes} minutes, got "
            f"{interval['value']}"
        )
        return self

    def assert_config_saved(self) -> "HeartbeatPage":
        """Assert the configuration was saved (no error message on the page)."""
        error_msg = self.page.locator('.ant-message-error, .qwenpaw-message-error')
        assert error_msg.count() == 0, "Error message appeared after save"
        return self
