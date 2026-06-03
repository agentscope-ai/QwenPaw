# -*- coding: utf-8 -*-
"""
QwenPaw Tools page object.

Wraps all interactions on the tool management page and exposes business-level
methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class ToolsPage(BasePage):
    """
    Tools page object.

    Wraps all user interactions on the tool management page:
    - Open the tools page
    - Get the list of tool cards
    - Get tool names
    - Toggle the tool switch
    - Check whether a tool is enabled
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/tools"

    # ========== Selector definitions ==========

    # Page load indicator
    TOOL_PAGE_CONTAINER = "div[class*=toolsPage]"
    PAGE_LOAD_INDICATOR = TOOL_PAGE_CONTAINER

    # Tool card selectors
    TOOL_CARD = ".qwenpaw-card"
    SWITCH = ".qwenpaw-switch"
    BREADCRUMB = 'span[class*="breadcrumbCurrent"]'

    # ========== Navigation ==========

    def open(self) -> "ToolsPage":
        """Open the Tools page."""
        logger.info("Opening Tools page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "ToolsPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== Tool list operations ==========

    def get_tool_cards(self) -> List[Locator]:
        """Return all tool cards."""
        cards = self.page.locator(self.TOOL_CARD).all()
        logger.info(f"Found {len(cards)} tool cards")
        return cards

    def get_tool_name(self, card: Locator) -> str:
        """Return the tool name."""
        # Try to get the tool name from the card title
        title_element = card.locator('.ant-card-meta-title, .qwenpaw-card-meta-title, h3, h4, [class*="title"]').first
        if title_element.count() > 0:
            return title_element.inner_text()

        # Fall back to the card text content if no title is found
        return card.inner_text().strip()[:50]

    def toggle_tool(self, card: Locator) -> "ToolsPage":
        """Toggle the tool switch."""
        switch = card.locator(self.SWITCH).first
        if switch.count() > 0:
            switch.click()
            logger.info("Toggled tool switch")
        return self

    def is_tool_enabled(self, card: Locator) -> bool:
        """Return whether the tool is enabled."""
        switch = card.locator(self.SWITCH).first
        if switch.count() > 0:
            return switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.classList.contains('ant-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
        return False

    # ========== Assertion methods ==========

    def assert_tool_count(self, expected_count: int, timeout: Optional[int] = None) -> "ToolsPage":
        """Assert the tool card count."""
        expect(self.page.locator(self.TOOL_CARD)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self

    def assert_tool_exists(self, tool_name: str, timeout: Optional[int] = None) -> "ToolsPage":
        """Assert the tool exists."""
        tool_card = self.page.locator(self.TOOL_CARD).filter(
            has_text=tool_name
        ).first
        expect(tool_card).to_be_visible(timeout=timeout or self.timeout)
        return self
