# -*- coding: utf-8 -*-
"""
QwenPaw MCP page object.

Wraps all interactions on the MCP page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class McpPage(BasePage):
    """
    MCP page object.

    Wraps all user actions on the MCP page:
    - Display the MCP client list
    - Enable/disable MCP clients
    - Create a new MCP client
    - View MCP configuration
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/mcp"

    # ========== Selector definitions ==========

    # Page load indicator
    PAGE_LOAD_INDICATOR = MCP_CARD_SELECTOR = 'div[class*="mcpCard"]'

    # MCP card selectors
    MCP_CARD_SELECTOR = 'div[class*="mcpCard"]'
    TOGGLE_BTN_SELECTOR = 'button[class*="toggleButton"]'
    CREATE_BTN_SELECTOR = 'button.qwenpaw-btn-primary:has-text("创建客户端")'

    # Inner card elements
    CARD_TITLE_SELECTOR = 'h3[class*="mcpTitle"]'
    TYPE_BADGE_SELECTOR = 'span[class*="typeBadge"]'
    STATUS_TEXT_SELECTOR = 'span[class*="statusText"]'

    # Breadcrumb
    BREADCRUMB_SELECTOR = 'span[class*="breadcrumbCurrent"]:has-text("MCP")'

    # Create dialog
    MODAL_CONTENT_SELECTOR = '.qwenpaw-modal-content'
    MODAL_TITLE_SELECTOR = '.qwenpaw-spark-modal-title'

    # ========== Navigation methods ==========

    def open(self) -> "McpPage":
        """Open the MCP page."""
        logger.info("Open the MCP page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "McpPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== MCP card methods ==========

    def get_mcp_cards(self) -> List[Locator]:
        """Return all MCP cards."""
        cards = self.page.locator(self.MCP_CARD_SELECTOR).all()
        logger.info(f"Found {len(cards)} MCP client card(s)")
        return cards

    def get_card_name(self, card: Locator) -> str:
        """Return the card's display name."""
        title_el = card.locator(self.CARD_TITLE_SELECTOR).first
        expect(title_el).to_be_visible(timeout=5000)
        name = title_el.inner_text()
        logger.debug(f"Card name: {name}")
        return name

    def toggle_mcp(self, card: Locator) -> "McpPage":
        """Toggle the MCP switch on a card."""
        toggle_btn = card.locator(self.TOGGLE_BTN_SELECTOR).first
        expect(toggle_btn).to_be_visible(timeout=5000)
        toggle_btn.click()
        logger.info("Toggled MCP switch")
        return self

    def is_mcp_enabled(self, card: Locator) -> bool:
        """Return whether the MCP client is enabled."""
        status_el = card.locator(self.STATUS_TEXT_SELECTOR).first
        expect(status_el).to_be_visible(timeout=3000)
        status_text = status_el.inner_text()
        is_enabled = status_text == "已启用"
        logger.debug(f"MCP status: {'enabled' if is_enabled else 'disabled'}")
        return is_enabled

    def click_create_client(self) -> "McpPage":
        """Click the Create Client button."""
        create_btn = self.page.locator(self.CREATE_BTN_SELECTOR).first
        expect(create_btn).to_be_visible(timeout=5000)
        assert not create_btn.is_disabled(), "Create Client button should not be disabled"
        create_btn.click()
        logger.info("Clicked Create Client button")
        return self

    def get_breadcrumb(self) -> str:
        """Return the breadcrumb text."""
        breadcrumb = self.page.locator(self.BREADCRUMB_SELECTOR).first
        expect(breadcrumb).to_be_visible(timeout=5000)
        breadcrumb_text = breadcrumb.inner_text()
        logger.debug(f"Breadcrumb: {breadcrumb_text}")
        return breadcrumb_text

    # ========== Assertion methods ==========

    def assert_mcp_cards_exist(self, min_count: int = 1) -> "McpPage":
        """Assert that MCP cards are present."""
        cards = self.get_mcp_cards()
        assert len(cards) >= min_count, f"Expected at least {min_count} MCP client(s), got {len(cards)}"
        return self

    def assert_create_button_visible(self) -> "McpPage":
        """Assert that the Create button is visible."""
        create_btn = self.page.locator(self.CREATE_BTN_SELECTOR).first
        expect(create_btn).to_be_visible(timeout=5000)
        assert not create_btn.is_disabled(), "Create Client button should not be disabled"
        return self

    def assert_breadcrumb(self, expected_text: str = "MCP") -> "McpPage":
        """Assert the breadcrumb text."""
        breadcrumb_text = self.get_breadcrumb()
        assert expected_text in breadcrumb_text, f"Breadcrumb should contain '{expected_text}', got '{breadcrumb_text}'"
        return self
