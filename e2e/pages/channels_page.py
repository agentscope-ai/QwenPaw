# -*- coding: utf-8 -*-
"""
QwenPaw Channels page object.

Wraps all interactions on the Channels page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class ChannelsPage(BasePage):
    """
    Channels page object.

    Wraps all user interactions on the Channels page:
    - Channel list display
    - Channel filtering (All/Built-in/Custom)
    - Channel configuration editing
    - Enable/disable channel
    - Save/cancel channel configuration
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/channels"

    # ========== Selector definitions ==========
    # Based on console/src/pages/Control/Channels/index.tsx and index.module.less

    # Page load indicator (no h1 on the page; channel cards mark a fully loaded page)
    PAGE_LOAD_INDICATOR = '[class*=channelCard]'

    # Filter buttons (UI text is Chinese; use button[class*=filterTab] to match the button rather than the parent container)
    FILTER_ALL_BTN = 'button[class*=filterTab]:has-text("全部"), button:has-text("All")'
    FILTER_BUILTIN_BTN = 'button[class*=filterTab]:has-text("内置"), button:has-text("Built-in")'
    FILTER_CUSTOM_BTN = 'button[class*=filterTab]:has-text("自定义"), button:has-text("Custom")'

    # Channel cards
    CHANNEL_CARD = '[class*=channelCard]'
    CHANNEL_CARD_ENABLED = '[class*=channelCard][class*=enabled]'
    CHANNEL_CARD_DISABLED = '[class*=channelCard]:not([class*=enabled])'

    # Channel card content
    CHANNEL_ICON = '[class*=channelCard] [class*=icon]'
    CHANNEL_NAME = '[class*=channelCard] [class*=name]'
    CHANNEL_STATUS_DOT = '[class*=channelCard] [class*=statusDot]'
    CHANNEL_STATUS_TEXT = '[class*=channelCard] [class*=statusText]'
    CHANNEL_BUILTIN_TAG = '[class*=channelCard] [class*=builtinTag]'
    CHANNEL_CUSTOM_TAG = '[class*=channelCard] [class*=customTag]'
    CHANNEL_BOT_PREFIX = '[class*=channelCard] [class*=botPrefix]'

    # Edit drawer (match only the visible drawer to avoid strict mode violations)
    CHANNEL_DRAWER = '.qwenpaw-drawer:visible, .ant-drawer:visible'
    DRAWER_TITLE = '.qwenpaw-drawer-title, .ant-drawer-title'
    DRAWER_CLOSE_BTN = '.qwenpaw-drawer-close, .ant-drawer-close'

    # Form fields
    FORM_ITEM = '.ant-form-item, .qwenpaw-form-item'
    FORM_LABEL = '.ant-form-item-label, .qwenpaw-form-item-label'
    FORM_INPUT = 'input.ant-input, input.qwenpaw-input'
    FORM_SWITCH = '.ant-switch, .qwenpaw-switch'
    FORM_SELECT = '.ant-select-selector, .qwenpaw-select-selector'
    FORM_SUBMIT_BTN = '.qwenpaw-drawer button:has-text("保 存"), .qwenpaw-drawer button:has-text("保存"), .qwenpaw-drawer button:has-text("Save"), .ant-drawer button:has-text("Save")'
    FORM_CANCEL_BTN = '.qwenpaw-drawer button:has-text("取 消"), .qwenpaw-drawer button:has-text("取消"), .qwenpaw-drawer button:has-text("Cancel"), .ant-drawer button:has-text("Cancel")'

    # Channel-specific field selectors (composed dynamically per channel type)
    BOT_PREFIX_INPUT = '.qwenpaw-drawer input[placeholder*="@bot"], .qwenpaw-drawer input[placeholder*="bot prefix" i], input[placeholder*="Bot Prefix" i], input[placeholder*="机器人前缀" i]'
    ENABLE_TOGGLE = '.ant-switch, .qwenpaw-switch'

    # Toast messages and loading state (inherited from BasePage; no redefinition needed)

    # ========== Initialization ==========

    def __init__(self, page: Page):
        super().__init__(page)

    # ========== Navigation ==========

    def open(self) -> "ChannelsPage":
        """Open the Channels page."""
        logger.info("Opening Channels page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "ChannelsPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        logger.info("Waiting for Channels page to load")

        # Wait for channel cards to appear (page has no h1 tag)
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)

        return self

    # ========== Filter operations ==========

    def click_filter_all(self) -> "ChannelsPage":
        """Click the All filter button."""
        logger.info("Clicking 'All' filter")
        self.page.locator(self.FILTER_ALL_BTN).first.click()
        self.page.wait_for_timeout(500)  # Wait for DOM updates
        self.wait_for_loading()
        return self

    def click_filter_builtin(self) -> "ChannelsPage":
        """Click the Built-in filter button."""
        logger.info("Clicking 'Built-in' filter")
        self.page.locator(self.FILTER_BUILTIN_BTN).first.click()
        self.page.wait_for_timeout(500)  # Wait for DOM updates
        self.wait_for_loading()
        return self

    def click_filter_custom(self) -> "ChannelsPage":
        """Click the Custom filter button."""
        logger.info("Clicking 'Custom' filter")
        self.page.locator(self.FILTER_CUSTOM_BTN).first.click()
        self.page.wait_for_timeout(500)  # Wait for DOM updates
        self.wait_for_loading()
        return self

    # ========== Channel card operations ==========

    def get_channel_cards(self) -> List[Locator]:
        """Return all channel cards."""
        return self.page.locator(self.CHANNEL_CARD).all()

    def get_channel_card_count(self) -> int:
        """Return the channel card count."""
        return len(self.get_channel_cards())

    # Chinese-to-English channel name aliases: tests may use Chinese while the UI shows English (or vice versa).
    # Aliases are grouped here so find_channel_card can match across languages.
    _CHANNEL_NAME_ALIASES = {
        "钉钉": ["DingTalk", "Dingtalk", "dingtalk", "钉钉"],
        "DingTalk": ["DingTalk", "Dingtalk", "dingtalk", "钉钉"],
        "飞书": ["Feishu", "feishu", "Lark", "飞书"],
        "Feishu": ["Feishu", "feishu", "Lark", "飞书"],
        "微信": ["WeChat", "Wechat", "wechat", "微信"],
        "WeChat": ["WeChat", "Wechat", "wechat", "微信"],
        "企业微信": ["WeCom", "Wecom", "wecom", "企业微信", "WeChat Work"],
        "WeCom": ["WeCom", "Wecom", "wecom", "企业微信"],
        "控制台": ["Console", "console", "控制台"],
        "Console": ["Console", "console", "控制台"],
    }

    def _resolve_channel_aliases(self, channel_name: str) -> List[str]:
        """Expand the test-provided name into every candidate alias (original name included)."""
        aliases = self._CHANNEL_NAME_ALIASES.get(channel_name)
        if aliases:
            # Make sure the original name is first if it is not in the alias list
            if channel_name not in aliases:
                return [channel_name] + aliases
            return aliases
        return [channel_name]

    def find_channel_card(self, channel_name: str) -> Optional[Locator]:
        """
        Find a channel card by name (supports Chinese/English alias fallback).

        Args:
            channel_name: Channel name (e.g. DingTalk/钉钉, Feishu/飞书, Discord).

        Returns:
            Channel card Locator, or None if not found.
        """
        candidates = self._resolve_channel_aliases(channel_name)
        cards = self.get_channel_cards()
        for card in cards:
            try:
                # Read the full card text because the channel name may not live in a dedicated element
                card_text = card.inner_text()
                for cand in candidates:
                    if cand in card_text:
                        return card
            except Exception:
                continue
        return None

    def click_channel_card(self, channel_name: str) -> "ChannelsPage":
        """
        Click a channel card to open the edit drawer.

        Args:
            channel_name: Channel name.
        """
        logger.info(f"Clicking channel card: {channel_name}")
        card = self.find_channel_card(channel_name)
        if card:
            card.click()
            self.page.wait_for_timeout(1000)
        else:
            raise Exception(f"Channel card not found: {channel_name}")
        return self

    def get_channel_status(self, channel_name: str) -> str:
        """
        Return the channel status (enabled/disabled).

        Args:
            channel_name: Channel name.

        Returns:
            'enabled' or 'disabled'.
        """
        card = self.find_channel_card(channel_name)
        if not card:
            raise Exception(f"Channel card not found: {channel_name}")

        card_text = card.inner_text()
        if '已启用' in card_text or 'Enabled' in card_text:
            return 'enabled'
        return 'disabled'

    def get_channel_bot_prefix(self, channel_name: str) -> str:
        """
        Return the Bot Prefix configured for the channel.

        Args:
            channel_name: Channel name.

        Returns:
            Bot Prefix text.
        """
        card = self.find_channel_card(channel_name)
        if not card:
            raise Exception(f"Channel card not found: {channel_name}")

        try:
            card_text = card.inner_text()
            # Extract "Bot Prefix: xxx" / "机器人前缀: xxx" from the card text
            for line in card_text.split("\n"):
                line = line.strip()
                if "机器人前缀:" in line or "Bot Prefix:" in line or "bot prefix:" in line:
                    prefix = line.split(":")[-1].strip()
                    if prefix == "Not Set" or prefix == "未设置":
                        return ""
                    return prefix
            return ""
        except Exception:
            return ""

    def is_builtin_channel(self, channel_name: str) -> bool:
        """
        Return whether the channel is a built-in channel.

        Args:
            channel_name: Channel name.

        Returns:
            True if the channel is built-in.
        """
        card = self.find_channel_card(channel_name)
        if not card:
            raise Exception(f"Channel card not found: {channel_name}")

        try:
            # Check whether the card text contains "内置" or "Built-in"
            card_text = card.inner_text()
            return "内置" in card_text or "Built-in" in card_text
        except Exception:
            try:
                return not card.locator(self.CHANNEL_CUSTOM_TAG).first.is_visible()
            except Exception:
                return True  # Treat as built-in by default

    # ========== Edit dialog/drawer operations ==========

    def wait_for_drawer_open(self, timeout: Optional[int] = None) -> bool:
        """Wait for the edit drawer to open."""
        timeout = timeout or self.timeout
        logger.info("Waiting for drawer to open")
        try:
            self.page.locator('.qwenpaw-drawer, .ant-drawer').first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def wait_for_drawer_close(self, timeout: Optional[int] = None) -> "ChannelsPage":
        """Wait for the edit drawer to close."""
        timeout = timeout or self.timeout
        logger.info("Waiting for drawer to close")
        self.page.wait_for_timeout(500)
        return self

    def close_drawer(self) -> "ChannelsPage":
        """Close the edit drawer."""
        logger.info("Closing drawer")
        close_btn = self.page.locator(self.DRAWER_CLOSE_BTN)
        if close_btn.count() > 0 and close_btn.first.is_visible():
            close_btn.first.click()
            self.page.wait_for_timeout(500)
        return self

    def get_drawer_title(self) -> str:
        """Return the drawer title."""
        try:
            return self.page.locator(self.DRAWER_TITLE).first.inner_text()
        except Exception:
            return ""

    # ========== Form operations ==========

    def fill_bot_prefix(self, prefix: str) -> "ChannelsPage":
        """
        Fill in the Bot Prefix.

        Args:
            prefix: Bot Prefix value.
        """
        logger.info(f"Filling bot prefix: {prefix}")
        bot_input = self.page.locator('#bot_prefix, input[placeholder*="@bot"], input[placeholder*="bot prefix" i]')
        if bot_input.count() > 0:
            bot_input.first.clear()
            bot_input.first.fill(prefix)
        return self

    def toggle_enable(self, enable: bool = True) -> "ChannelsPage":
        """
        Toggle the enabled state.

        Args:
            enable: True to enable, False to disable.
        """
        logger.info(f"Toggling enable to: {enable}")
        # Locate the switch inside the drawer
        drawer = self.page.locator('.qwenpaw-drawer, .ant-drawer')
        switch = drawer.locator('.qwenpaw-switch, .ant-switch').first

        # Read the current state
        aria_checked = switch.get_attribute('aria-checked') or 'false'
        is_enabled = aria_checked == 'true'

        # Click only when the state needs to flip
        if is_enabled != enable:
            switch.click()
            self.page.wait_for_timeout(500)

        return self

    def fill_form_field(self, field_name: str, value: str) -> "ChannelsPage":
        """
        Fill in a form field.

        Args:
            field_name: Field name.
            value: Field value.
        """
        logger.info(f"Filling field '{field_name}' with value: {value}")
        # Choose the fill approach based on the field type
        try:
            input_elem = self.page.locator(f'input[placeholder*="{field_name}" i], input[label*="{field_name}" i]').first
            input_elem.fill(value)
        except Exception:
            # Fallback: use the generic input selector
            self.page.locator(self.FORM_INPUT).first.fill(value)
        return self

    def save_channel_config(self) -> "ChannelsPage":
        """Save the channel configuration (the drawer does not close automatically after saving)."""
        logger.info("Saving channel configuration")
        submit_btn = self.page.locator(self.FORM_SUBMIT_BTN).first
        # Wait for the save API request to complete via expect_response
        try:
            with self.page.expect_response(
                lambda resp: '/api/config/channel' in resp.url and resp.request.method in ('PUT', 'POST', 'PATCH'),
                timeout=10000
            ) as response_info:
                submit_btn.click()
            response = response_info.value
            logger.info(f"Save API response: status={response.status}")
            if not response.ok:
                logger.warning(f"Save API returned non-OK status: {response.status}")
        except Exception:
            # No save API response observed — likely blocked by client-side validation
            logger.warning("Save API response not captured; possible client-side validation error")
            self.page.wait_for_timeout(2000)
        return self

    def has_form_validation_errors(self) -> bool:
        """Check whether the form has validation errors."""
        errors = self.page.locator(
            '.qwenpaw-form-item-explain-error, .ant-form-item-explain-error'
        )
        count = errors.count()
        if count > 0:
            for i in range(count):
                logger.warning(f"Form validation error: {errors.nth(i).inner_text()}")
        return count > 0

    def cancel_channel_config(self) -> "ChannelsPage":
        """Cancel the channel configuration."""
        logger.info("Canceling channel configuration")
        self.page.locator(self.FORM_CANCEL_BTN).first.click()
        self.wait_for_drawer_close()
        return self

    # ========== Verification methods ==========

    def verify_channel_card_visible(self, channel_name: str) -> bool:
        """Verify that the channel card is visible."""
        card = self.find_channel_card(channel_name)
        return card is not None and card.is_visible()

    def verify_channel_count(self, expected_count: int) -> bool:
        """Verify the channel card count."""
        actual_count = self.get_channel_card_count()
        logger.info(f"Channel count: {actual_count}, expected: {expected_count}")
        return actual_count == expected_count

    def verify_filter_result(self, filter_type: str) -> bool:
        """
        Verify the filter result.

        Args:
            filter_type: 'all', 'builtin', or 'custom'.
        """
        cards = self.get_channel_cards()
        if filter_type == 'all':
            return len(cards) > 0
        elif filter_type == 'builtin':
            # Every card must be built-in
            for card in cards:
                try:
                    card_text = card.inner_text()
                    if "内置" not in card_text and "Built-in" not in card_text:
                        return False
                except Exception:
                    return False
            return len(cards) > 0
        elif filter_type == 'custom':
            # Every card must be custom
            for card in cards:
                try:
                    card_text = card.inner_text()
                    if "自定义" not in card_text and "Custom" not in card_text:
                        return False
                except Exception:
                    return False
            return len(cards) > 0
        return False

    def wait_for_success_message(self, timeout: int = 5000) -> bool:
        """Wait for the success message (no toast may appear after save, so not required)."""
        try:
            expect(self.page.locator(self.SUCCESS_MESSAGE)).to_be_visible(timeout=timeout)
            return True
        except Exception:
            logger.info("No success message displayed (may be normal)")
            return False

    def wait_for_error_message(self, timeout: int = 5000) -> bool:
        """Wait for the error message."""
        try:
            expect(self.page.locator(self.ERROR_MESSAGE)).to_be_visible(timeout=timeout)
            return True
        except TimeoutError:
            return False

    def wait_for_loading(self, timeout: int = 3000) -> "ChannelsPage":
        """Wait for loading to finish."""
        try:
            # Wait for the spinner to appear if present
            loading = self.page.locator(self.LOADING_SPINNER)
            if loading.count() > 0:
                expect(loading).to_be_hidden(timeout=timeout)
        except Exception:
            pass  # Missing spinner is also fine
        return self

    # ========== High-level operations ==========

    def enable_channel(self, channel_name: str) -> "ChannelsPage":
        """
        Enable a channel.

        Args:
            channel_name: Channel name.
        """
        logger.info(f"Enabling channel: {channel_name}")
        self.click_channel_card(channel_name)
        self.toggle_enable(True)
        self.save_channel_config()
        self.close_drawer()
        return self

    def disable_channel(self, channel_name: str) -> "ChannelsPage":
        """
        Disable a channel.

        Args:
            channel_name: Channel name.
        """
        logger.info(f"Disabling channel: {channel_name}")
        self.click_channel_card(channel_name)
        self.toggle_enable(False)
        self.save_channel_config()
        self.close_drawer()
        return self

    def update_bot_prefix(self, channel_name: str, prefix: str) -> "ChannelsPage":
        """
        Update the Bot Prefix for a channel.

        Args:
            channel_name: Channel name.
            prefix: New Bot Prefix.
        """
        logger.info(f"Updating bot prefix for {channel_name} to: {prefix}")
        self.click_channel_card(channel_name)
        self.fill_bot_prefix(prefix)
        self.save_channel_config()
        self.close_drawer()
        return self

    def refresh_and_verify_channel_status(self, channel_name: str, expected_status: str) -> bool:
        """
        Reload the page and verify the channel status.

        Args:
            channel_name: Channel name.
            expected_status: Expected status, 'enabled' or 'disabled'.
        """
        logger.info("Refreshing page and verifying channel status")
        self.refresh()
        self.wait_for_page_loaded()
        actual_status = self.get_channel_status(channel_name)
        return actual_status == expected_status