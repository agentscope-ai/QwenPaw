# -*- coding: utf-8 -*-
"""
QwenPaw ACP (Agent Communication Protocol) page object.

Wraps all interactions on the ACP configuration management page and exposes
business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class ACPPage(BasePage):
    """
    ACP configuration management page object.

    Wraps all user interactions on the ACP page:
    - Page navigation and loading
    - Filter tab switching (All/Builtin/Custom)
    - ACP card list interaction
    - Create/edit ACP configuration (drawer)
    - Delete custom ACP
    - Builtin ACP protection verification
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/acp"

    # ========== Selector definitions ==========

    # Page container
    PAGE_CONTAINER = 'div[class*="acp"], div[class*="ACP"], [class*="acpPage"]'
    BREADCRUMB_PARENT = 'span[class*="breadcrumbParent"]'
    BREADCRUMB_CURRENT = 'span[class*="breadcrumbCurrent"]'

    # Filter tabs
    FILTER_TABS = '.qwenpaw-tabs, .qwenpaw-segmented, [class*="filterTabs"]'
    TAB_ALL = '[class*="tab"]:has-text("All"), [class*="tab"]:has-text("全部"), .qwenpaw-segmented-item:has-text("All")'
    TAB_BUILTIN = '[class*="tab"]:has-text("Builtin"), [class*="tab"]:has-text("内置"), .qwenpaw-segmented-item:has-text("Builtin")'
    TAB_CUSTOM = '[class*="tab"]:has-text("Custom"), [class*="tab"]:has-text("自定义"), .qwenpaw-segmented-item:has-text("Custom")'

    # Create button
    CREATE_BUTTON = 'button:has-text("Create"), button:has-text("创建"), button:has-text("Add"), button:has-text("添加")'

    # ACP card list
    ACP_CARD = '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
    ACP_CARD_TITLE = '[class*="agentKey"], [class*="title"], .qwenpaw-card-meta-title'
    ACP_CARD_TAG = '.qwenpaw-tag'
    ACP_CARD_SWITCH = '.qwenpaw-switch'

    # ACP drawer (create/edit)
    DRAWER = '.qwenpaw-drawer'
    DRAWER_TITLE = '.qwenpaw-drawer-title'
    DRAWER_CLOSE = '.qwenpaw-drawer-close'

    # Drawer form fields
    FORM_AGENT_KEY = 'input[id*="agentKey"], input[name*="agentKey"], #agentKey'
    FORM_COMMAND = 'input[id*="command"], input[name*="command"], #command'
    FORM_ARGS = 'textarea[id*="args"], textarea[name*="args"], #argsText'
    FORM_ENV = 'textarea[id*="env"], textarea[name*="env"], #envText'
    FORM_ENABLED_SWITCH = '[class*="enabled"] .qwenpaw-switch, #enabled'
    FORM_TRUSTED_SWITCH = '[class*="trusted"] .qwenpaw-switch, #trusted'
    FORM_TOOL_PARSE_MODE = '.qwenpaw-select, select[id*="tool_parse_mode"]'
    FORM_BUFFER_LIMIT = 'input[id*="buffer"], input[name*="buffer"], input[type="number"]'

    # Drawer action buttons
    SAVE_BUTTON = '.qwenpaw-drawer button:has-text("Save"), .qwenpaw-drawer button:has-text("保存"), .qwenpaw-drawer button.qwenpaw-btn-primary'
    CANCEL_BUTTON = '.qwenpaw-drawer button:has-text("Cancel"), .qwenpaw-drawer button:has-text("取消")'
    DELETE_BUTTON_DRAWER = '.qwenpaw-drawer button:has-text("Delete"), .qwenpaw-drawer button:has-text("删除")'
    DOC_LINK = '.qwenpaw-drawer a[href*="doc"], .qwenpaw-drawer a[href*="integration"]'

    # Confirmation popups
    POPCONFIRM = '.qwenpaw-popconfirm, .qwenpaw-modal-confirm'
    POPCONFIRM_OK = '.qwenpaw-popconfirm button:has-text("OK"), .qwenpaw-popconfirm button:has-text("确定"), .qwenpaw-popconfirm .qwenpaw-btn-primary'
    POPCONFIRM_CANCEL = '.qwenpaw-popconfirm button:has-text("Cancel"), .qwenpaw-popconfirm button:has-text("取消")'

    # Toast messages
    SUCCESS_TOAST = '.qwenpaw-message-success, .qwenpaw-notification-success'
    ERROR_TOAST = '.qwenpaw-message-error, .qwenpaw-notification-error'

    # Builtin ACP names
    BUILTIN_ACP_NAMES = ["opencode", "qwen_code", "claude_code", "codex"]

    # ========== Initialization ==========

    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("ACPPage initialized")

    # ========== Page navigation ==========

    def open(self) -> "ACPPage":
        """Open the ACP configuration page."""
        logger.info("Opening ACP configuration management page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "ACPPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        self.page.wait_for_load_state("networkidle", timeout=timeout)
        self.page.wait_for_timeout(1000)
        return self

    # ========== Breadcrumb verification ==========

    def get_breadcrumb_text(self) -> str:
        """Return the breadcrumb text."""
        breadcrumb = self.page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
        if breadcrumb.is_visible(timeout=3000):
            return breadcrumb.inner_text().strip()
        return ""

    def verify_breadcrumb(self) -> bool:
        """Verify the breadcrumb contains Workspace and ACP."""
        text = self.get_breadcrumb_text()
        has_workspace = "Workspace" in text or "工作区" in text or "Agent" in text
        has_acp = "ACP" in text
        return has_workspace and has_acp

    # ========== Filter tabs ==========

    def click_tab_all(self) -> "ACPPage":
        """Click the All tab."""
        tab = self.page.locator(self.TAB_ALL).first
        if tab.is_visible(timeout=5000):
            tab.click()
            self.page.wait_for_timeout(500)
            logger.info("Clicked All tab")
        return self

    def click_tab_builtin(self) -> "ACPPage":
        """Click the Builtin tab."""
        tab = self.page.locator(self.TAB_BUILTIN).first
        if tab.is_visible(timeout=5000):
            tab.click()
            self.page.wait_for_timeout(500)
            logger.info("Clicked Builtin tab")
        return self

    def click_tab_custom(self) -> "ACPPage":
        """Click the Custom tab."""
        tab = self.page.locator(self.TAB_CUSTOM).first
        if tab.is_visible(timeout=5000):
            tab.click()
            self.page.wait_for_timeout(500)
            logger.info("Clicked Custom tab")
        return self

    def is_tab_visible(self, tab_name: str) -> bool:
        """Return whether the given tab is visible."""
        tab_selectors = {
            "all": self.TAB_ALL,
            "builtin": self.TAB_BUILTIN,
            "custom": self.TAB_CUSTOM,
        }
        selector = tab_selectors.get(tab_name.lower(), "")
        if selector:
            return self.page.locator(selector).first.is_visible(timeout=3000)
        return False

    # ========== ACP card list ==========

    def get_acp_cards(self) -> List[Locator]:
        """Return all ACP cards."""
        cards = self.page.locator(self.ACP_CARD).all()
        logger.info(f"Found {len(cards)} ACP cards")
        return cards

    def get_acp_card_count(self) -> int:
        """Return the number of ACP cards."""
        return len(self.get_acp_cards())

    def get_card_agent_key(self, card: Locator) -> str:
        """Return the agentKey of the given card."""
        title_el = card.locator(
            '[class*="agentKey"], [class*="title"], '
            '.qwenpaw-card-meta-title, h3, h4'
        ).first
        if title_el.is_visible(timeout=3000):
            return title_el.inner_text().strip()
        return card.inner_text().strip()[:50]

    def is_card_builtin(self, card: Locator) -> bool:
        """Return whether the card represents a builtin ACP."""
        card_text = card.inner_text().lower()
        return "builtin" in card_text or "内置" in card_text

    def is_card_enabled(self, card: Locator) -> bool:
        """Return whether the card is enabled."""
        switch = card.locator(self.ACP_CARD_SWITCH).first
        if switch.count() > 0:
            return switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
        return False

    def click_card(self, card: Locator) -> "ACPPage":
        """Click the card to open the edit drawer."""
        card.click()
        self.page.wait_for_timeout(500)
        logger.info("Clicked ACP card")
        return self

    def toggle_card_switch(self, card: Locator) -> "ACPPage":
        """Toggle the enable/disable switch on the card."""
        switch = card.locator(self.ACP_CARD_SWITCH).first
        if switch.count() > 0:
            switch.click()
            self.page.wait_for_timeout(500)
            logger.info("Toggled ACP card switch")
        return self

    # ========== Drawer operations ==========

    def click_create_button(self) -> "ACPPage":
        """Click the create button."""
        create_btn = self.page.locator(self.CREATE_BUTTON).first
        expect(create_btn).to_be_visible(timeout=5000)
        create_btn.click()
        self.page.wait_for_timeout(500)
        logger.info("Clicked create ACP button")
        return self

    def is_drawer_visible(self) -> bool:
        """Return whether the drawer is visible."""
        drawer = self.page.locator(self.DRAWER).first
        return drawer.is_visible(timeout=5000)

    def get_drawer_title(self) -> str:
        """Return the drawer title."""
        title = self.page.locator(self.DRAWER_TITLE).first
        if title.is_visible(timeout=3000):
            return title.inner_text().strip()
        return ""

    def fill_agent_key(self, key: str) -> "ACPPage":
        """Fill in the agentKey field."""
        key_input = self.page.locator(self.FORM_AGENT_KEY).first
        if key_input.is_visible(timeout=3000):
            key_input.fill(key)
            logger.info(f"Filled agentKey: {key}")
        return self

    def fill_command(self, command: str) -> "ACPPage":
        """Fill in the command field."""
        cmd_input = self.page.locator(self.FORM_COMMAND).first
        if cmd_input.is_visible(timeout=3000):
            cmd_input.fill(command)
            logger.info(f"Filled command: {command}")
        return self

    def fill_args(self, args_text: str) -> "ACPPage":
        """Fill in the args field (multi-line text)."""
        args_input = self.page.locator(self.FORM_ARGS).first
        if args_input.is_visible(timeout=3000):
            args_input.fill(args_text)
            logger.info(f"Filled args: {args_text[:50]}")
        return self

    def fill_env(self, env_text: str) -> "ACPPage":
        """Fill in the env field (KEY=VALUE format)."""
        env_input = self.page.locator(self.FORM_ENV).first
        if env_input.is_visible(timeout=3000):
            env_input.fill(env_text)
            logger.info(f"Filled env: {env_text[:50]}")
        return self

    def save_drawer(self) -> "ACPPage":
        """Click the save button."""
        save_btn = self.page.locator(self.SAVE_BUTTON).first
        if save_btn.is_visible(timeout=5000):
            save_btn.click()
            self.page.wait_for_timeout(1000)
            logger.info("Clicked save")
        return self

    def cancel_drawer(self) -> "ACPPage":
        """Click the cancel button."""
        cancel_btn = self.page.locator(self.CANCEL_BUTTON).first
        if cancel_btn.is_visible(timeout=3000):
            cancel_btn.click()
        else:
            close_btn = self.page.locator(self.DRAWER_CLOSE).first
            if close_btn.is_visible(timeout=3000):
                close_btn.click()
            else:
                self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(500)
        logger.info("Closed drawer")
        return self

    def click_delete_in_drawer(self) -> "ACPPage":
        """Click the delete button inside the drawer."""
        delete_btn = self.page.locator(self.DELETE_BUTTON_DRAWER).first
        if delete_btn.is_visible(timeout=3000):
            delete_btn.click()
            self.page.wait_for_timeout(500)
            logger.info("Clicked delete button in drawer")
        return self

    def confirm_delete(self) -> "ACPPage":
        """Confirm deletion."""
        ok_btn = self.page.locator(self.POPCONFIRM_OK).first
        if ok_btn.is_visible(timeout=5000):
            ok_btn.click()
            self.page.wait_for_timeout(1000)
            logger.info("Confirmed deletion")
        return self

    def cancel_delete(self) -> "ACPPage":
        """Cancel deletion."""
        cancel_btn = self.page.locator(self.POPCONFIRM_CANCEL).first
        if cancel_btn.is_visible(timeout=3000):
            cancel_btn.click()
            self.page.wait_for_timeout(500)
            logger.info("Cancelled deletion")
        return self

    def is_agent_key_editable(self) -> bool:
        """Return whether the agentKey input is editable."""
        key_input = self.page.locator(self.FORM_AGENT_KEY).first
        if key_input.is_visible(timeout=3000):
            return key_input.is_enabled()
        return False

    def is_delete_button_visible(self) -> bool:
        """Return whether the delete button in the drawer is visible."""
        delete_btn = self.page.locator(self.DELETE_BUTTON_DRAWER).first
        return delete_btn.is_visible(timeout=3000)

    # ========== Toast assertions ==========

    def wait_for_success_message(self, timeout: Optional[int] = None) -> bool:
        """Wait for the success toast message."""
        try:
            self.page.locator(self.SUCCESS_TOAST).first.wait_for(
                state="visible", timeout=timeout or 10000
            )
            return True
        except Exception:
            return False

    # ========== Assertion methods ==========

    def assert_page_loaded(self, timeout: Optional[int] = None) -> "ACPPage":
        """Assert that the page has loaded."""
        timeout = timeout or self.timeout
        indicator = self.page.locator(
            f'{self.CREATE_BUTTON}, {self.ACP_CARD}, {self.FILTER_TABS}'
        ).first
        expect(indicator).to_be_visible(timeout=timeout)
        return self

    def assert_card_count(self, expected: int, timeout: Optional[int] = None) -> "ACPPage":
        """Assert the ACP card count."""
        expect(self.page.locator(self.ACP_CARD)).to_have_count(
            expected, timeout=timeout or self.timeout
        )
        return self
