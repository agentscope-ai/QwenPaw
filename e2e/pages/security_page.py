# -*- coding: utf-8 -*-
"""
QwenPaw Security page object.

Wraps all interactions on the Security page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class SecurityPage(BasePage):
    """
    Security page object.

    Wraps all user actions on the Security page:
    - Tool Guard tab
    - File Guard tab
    - Toggle guard switches
    - Save configuration
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/security"

    # ========== Selector definitions ==========

    # Page load indicator
    PAGE_LOAD_INDICATOR = '.qwenpaw-tabs-tab-btn'

    # Tabs
    TOOL_GUARD_TAB = '[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn'
    FILE_GUARD_TAB = '[data-node-key="fileGuard"] .qwenpaw-tabs-tab-btn'

    # Active panel
    ACTIVE_PANEL = '.qwenpaw-tabs-tabpane-active'

    # Guard switch
    GUARD_SWITCH = 'button.qwenpaw-switch[role="switch"]'

    # Save button
    SAVE_BTN = 'button.qwenpaw-btn-primary:has-text("保存"), button:has-text("保 存")'

    # Protected tools select
    PROTECTED_TOOLS_SELECT = '.qwenpaw-select'

    # File guard path input
    PATH_INPUT = 'input[placeholder*="文件或目录路径"]'

    # ========== Navigation methods ==========

    def open(self) -> "SecurityPage":
        """Open the Security page."""
        logger.info("Open the Security page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "SecurityPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== Tab methods ==========

    def get_tool_guard_tab(self) -> Locator:
        """Return the Tool Guard tab locator."""
        return self.page.locator(self.TOOL_GUARD_TAB).first

    def get_file_guard_tab(self) -> Locator:
        """Return the File Guard tab locator."""
        return self.page.locator(self.FILE_GUARD_TAB).first

    def switch_to_tab(self, tab_name: str) -> "SecurityPage":
        """
        Switch to the given tab.

        Args:
            tab_name: Tab name, one of "toolGuard" or "fileGuard".

        Returns:
            self
        """
        if tab_name == "toolGuard":
            tab_locator = self.get_tool_guard_tab()
        elif tab_name == "fileGuard":
            tab_locator = self.get_file_guard_tab()
        else:
            raise ValueError(f"Unsupported tab name: {tab_name}")

        expect(tab_locator).to_be_visible(timeout=self.timeout)
        tab_locator.click()
        self.page.wait_for_timeout(1500)

        # Verify the panel is active
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info(f"Switched to {tab_name} tab")
        return self

    # ========== Guard switch methods ==========

    def get_guard_toggle(self) -> Locator:
        """Return the guard switch in the active panel."""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.GUARD_SWITCH).first

    def is_guard_enabled(self) -> bool:
        """Return whether the guard is enabled."""
        switch = self.get_guard_toggle()
        if switch.count() > 0:
            aria_checked = switch.get_attribute('aria-checked')
            return aria_checked == 'true'
        return False

    def toggle_guard(self) -> "SecurityPage":
        """Toggle the guard switch."""
        switch = self.get_guard_toggle()
        expect(switch).to_be_visible(timeout=self.timeout)
        switch.click()
        self.page.wait_for_timeout(1000)
        logger.info("Guard switch toggled")
        return self

    def enable_guard(self) -> "SecurityPage":
        """Enable the guard."""
        if not self.is_guard_enabled():
            self.toggle_guard()
        return self

    def disable_guard(self) -> "SecurityPage":
        """Disable the guard."""
        if self.is_guard_enabled():
            self.toggle_guard()
        return self

    # ========== Save action ==========

    def click_save(self) -> "SecurityPage":
        """Click the Save button."""
        save_btn = self.page.locator(self.SAVE_BTN).first
        if not save_btn.is_visible():
            # Fall back to the footer
            save_btn = self.page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first

        expect(save_btn).to_be_visible(timeout=self.timeout)
        save_btn.click()
        self.page.wait_for_timeout(2000)
        logger.info("Save button clicked")
        return self

    # ========== Misc helpers ==========

    def get_protected_tools_select(self) -> Locator:
        """Return the protected-tools select."""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.PROTECTED_TOOLS_SELECT).first

    def get_path_input(self) -> Locator:
        """Return the file-guard path input."""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.PATH_INPUT).first

    # ========== Assertion methods ==========

    def assert_guard_enabled(self) -> "SecurityPage":
        """Assert that the guard is enabled."""
        assert self.is_guard_enabled(), "Guard should be enabled"
        return self

    def assert_guard_disabled(self) -> "SecurityPage":
        """Assert that the guard is disabled."""
        assert not self.is_guard_enabled(), "Guard should be disabled"
        return self

    def assert_config_saved(self) -> "SecurityPage":
        """Assert that the configuration was saved."""
        error_msg = self.page.locator('.qwenpaw-message-error')
        assert error_msg.count() == 0, "Error message appeared after save"
        return self
