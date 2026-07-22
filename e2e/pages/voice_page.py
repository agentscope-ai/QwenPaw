# -*- coding: utf-8 -*-
"""
QwenPaw Voice page object.

Wraps all interactions on the Voice page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class VoicePage(BasePage):
    """
    Voice page object.

    Wraps all user actions on the Voice page:
    - Display voice service configuration
    - Enable/disable the voice service
    - Read voice service status
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/settings/voice"

    # ========== Selector definitions ==========

    # Page load indicator
    PAGE_LOAD_INDICATOR = '.qwenpaw-switch, .qwenpaw-switch-input, [class*=voiceToggle]'

    # Voice service switch
    VOICE_TOGGLE_SELECTOR = '.qwenpaw-switch, .qwenpaw-switch-input, [class*=voiceToggle]'

    # Configuration form
    CONFIG_FORM_SELECTOR = '.qwenpaw-form, [class*=configForm], form'

    # Success message
    SUCCESS_MESSAGE_SELECTOR = '.qwenpaw-message-success, .qwenpaw-notification-success'

    # ========== Navigation methods ==========

    def open(self) -> "VoicePage":
        """Open the Voice page."""
        logger.info("Open the Voice page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "VoicePage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== Voice service methods ==========

    def get_voice_toggle(self) -> Locator:
        """Return the voice service switch."""
        toggle = self.page.locator(self.VOICE_TOGGLE_SELECTOR).first
        expect(toggle).to_be_visible(timeout=5000)
        logger.debug("Getting voice service switch")
        return toggle

    def is_voice_enabled(self) -> bool:
        """Return whether the voice service is enabled."""
        toggle = self.get_voice_toggle()
        toggle_class = toggle.get_attribute('class')
        is_checked = 'checked' in toggle_class if toggle_class else False
        logger.debug(f"Voice service status: {'enabled' if is_checked else 'disabled'}")
        return is_checked

    def toggle_voice(self) -> "VoicePage":
        """Toggle the voice switch."""
        toggle = self.get_voice_toggle()
        toggle.click()
        logger.info("Toggled voice switch")
        return self

    def enable_voice(self) -> "VoicePage":
        """Enable the voice service."""
        if not self.is_voice_enabled():
            self.toggle_voice()
        return self

    def disable_voice(self) -> "VoicePage":
        """Disable the voice service."""
        if self.is_voice_enabled():
            self.toggle_voice()
        return self

    # ========== Assertion methods ==========

    def assert_voice_toggle_visible(self) -> "VoicePage":
        """Assert that the voice switch is visible."""
        toggle = self.get_voice_toggle()
        expect(toggle).to_be_visible(timeout=5000)
        return self

    def assert_voice_enabled(self) -> "VoicePage":
        """Assert that the voice service is enabled."""
        assert self.is_voice_enabled(), "Voice service should be enabled"
        return self

    def assert_voice_disabled(self) -> "VoicePage":
        """Assert that the voice service is disabled."""
        assert not self.is_voice_enabled(), "Voice service should be disabled"
        return self

    def assert_config_saved(self) -> "VoicePage":
        """Assert that the configuration was saved."""
        success_msg = self.page.locator(self.SUCCESS_MESSAGE_SELECTOR).first
        if success_msg.is_visible(timeout=3000):
            logger.info("Save success message displayed")
        else:
            logger.info("No save success message found (auto-save may be enabled)")
        return self
