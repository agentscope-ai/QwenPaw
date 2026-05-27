# -*- coding: utf-8 -*-
"""
QwenPaw AgentStats agent statistics page object.

Wraps all interactions on the agent statistics dashboard page and exposes
business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class AgentStatsPage(BasePage):
    """
    AgentStats agent statistics page object.

    Wraps all user interactions on the statistics dashboard page:
    - Page navigation and loading
    - Date range filtering
    - Summary card data retrieval
    - Trend chart verification
    - Channel distribution pie chart verification
    - Empty and loading state handling
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/agent-stats"

    # ========== Selector definitions ==========

    # Page container and loading marker
    PAGE_CONTAINER = 'div[class*="agentStats"], div[class*="AgentStats"], [class*="agent-stats"]'
    BREADCRUMB_PARENT = 'span[class*="breadcrumbParent"]'
    BREADCRUMB_CURRENT = 'span[class*="breadcrumbCurrent"]'

    # Date range picker
    DATE_RANGE_PICKER = ".qwenpaw-picker-range, .qwenpaw-picker"
    DATE_RANGE_INPUT = ".qwenpaw-picker-range input, .qwenpaw-picker input"
    DATE_PICKER_PANEL = ".qwenpaw-picker-panel, .qwenpaw-picker-dropdown"

    # Summary cards
    SUMMARY_CARD = '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-card'
    SUMMARY_CARD_TITLE = '[class*="cardTitle"], [class*="title"], .qwenpaw-statistic-title'
    SUMMARY_CARD_VALUE = '[class*="cardValue"], [class*="value"], .qwenpaw-statistic-content-value'

    # Chart container
    CHART_CONTAINER = '[class*="chartContainer"], [class*="chart"], canvas'
    COLUMN_CHART = '[class*="column"], [class*="bar"]'
    PIE_CHART = '[class*="pie"], [class*="donut"]'

    # Empty and loading states
    EMPTY_STATE = ".qwenpaw-empty, [class*='empty']"
    LOADING_SPIN = ".qwenpaw-spin, [class*='loading']"
    ERROR_STATE = '[class*="error"]'
    RETRY_BUTTON = 'button:has-text("Retry"), button:has-text("重试")'

    # Tooltip
    TOOLTIP = '.qwenpaw-tooltip, [class*="tooltip"]'

    # ========== Initialization ==========

    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("AgentStatsPage initialized")

    # ========== Page navigation ==========

    def open(self) -> "AgentStatsPage":
        """Open the agent statistics page."""
        logger.info("Opening AgentStats agent statistics page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "AgentStatsPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        self.page.wait_for_load_state("networkidle", timeout=timeout)
        self.page.wait_for_timeout(1500)
        return self

    # ========== Breadcrumb verification ==========

    def get_breadcrumb_text(self) -> str:
        """Return the breadcrumb text."""
        breadcrumb = self.page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
        if breadcrumb.is_visible(timeout=3000):
            return breadcrumb.inner_text().strip()
        return ""

    def verify_breadcrumb(self) -> bool:
        """Verify the breadcrumb contains Settings and Agent Stats."""
        text = self.get_breadcrumb_text()
        has_settings = "Settings" in text or "设置" in text
        has_stats = "Agent Stats" in text or "统计" in text or "Stats" in text
        return has_settings and has_stats

    # ========== Date range filter ==========

    def is_date_picker_visible(self) -> bool:
        """Return whether the date range picker is visible."""
        picker = self.page.locator(self.DATE_RANGE_PICKER).first
        return picker.is_visible(timeout=5000)

    def click_date_picker(self) -> "AgentStatsPage":
        """Click the date range picker."""
        picker = self.page.locator(self.DATE_RANGE_PICKER).first
        if picker.is_visible(timeout=5000):
            picker.click()
            self.page.wait_for_timeout(500)
            logger.info("Clicked date range picker")
        return self

    def is_date_panel_visible(self) -> bool:
        """Return whether the date panel popup is visible."""
        panel = self.page.locator(self.DATE_PICKER_PANEL).first
        return panel.is_visible(timeout=3000)

    # ========== Summary cards ==========

    def get_summary_cards(self) -> List[Locator]:
        """Return all summary cards."""
        cards = self.page.locator(self.SUMMARY_CARD).all()
        logger.info(f"Found {len(cards)} summary cards")
        return cards

    def get_summary_card_count(self) -> int:
        """Return the summary card count."""
        return len(self.get_summary_cards())

    def get_card_title(self, card: Locator) -> str:
        """Return the card title."""
        title_el = card.locator(
            '[class*="title"], .qwenpaw-statistic-title, h3, h4, span'
        ).first
        if title_el.is_visible(timeout=3000):
            return title_el.inner_text().strip()
        return ""

    def get_card_value(self, card: Locator) -> str:
        """Return the card value."""
        value_el = card.locator(
            '[class*="value"], .qwenpaw-statistic-content-value, '
            '[class*="number"], [class*="count"]'
        ).first
        if value_el.is_visible(timeout=3000):
            return value_el.inner_text().strip()
        return ""

    def get_all_card_data(self) -> List[dict]:
        """Return the title and value for every card."""
        cards = self.get_summary_cards()
        result = []
        for card in cards:
            title = self.get_card_title(card)
            value = self.get_card_value(card)
            if title:
                result.append({"title": title, "value": value})
        return result

    # ========== Chart verification ==========

    def get_chart_containers(self) -> List[Locator]:
        """Return all chart containers."""
        charts = self.page.locator(self.CHART_CONTAINER).all()
        logger.info(f"Found {len(charts)} chart containers")
        return charts

    def get_chart_count(self) -> int:
        """Return the chart count."""
        return len(self.get_chart_containers())

    def has_canvas_elements(self) -> bool:
        """Check whether any canvas chart elements exist."""
        canvases = self.page.locator("canvas").all()
        return len(canvases) > 0

    # ========== State checks ==========

    def is_loading(self) -> bool:
        """Return whether the page is currently loading."""
        spin = self.page.locator(self.LOADING_SPIN).first
        return spin.is_visible(timeout=2000)

    def is_empty_state(self) -> bool:
        """Return whether the empty state is displayed."""
        empty = self.page.locator(self.EMPTY_STATE).first
        return empty.is_visible(timeout=3000)

    def has_error(self) -> bool:
        """Return whether an error state is shown."""
        error = self.page.locator(self.ERROR_STATE).first
        return error.is_visible(timeout=2000)

    def click_retry(self) -> "AgentStatsPage":
        """Click the retry button."""
        retry_btn = self.page.locator(self.RETRY_BUTTON).first
        if retry_btn.is_visible(timeout=3000):
            retry_btn.click()
            self.page.wait_for_timeout(1000)
            logger.info("Clicked retry button")
        return self

    # ========== Assertion methods ==========

    def assert_page_loaded(self, timeout: Optional[int] = None) -> "AgentStatsPage":
        """Assert that the page has loaded."""
        timeout = timeout or self.timeout
        page_indicator = self.page.locator(
            f'{self.SUMMARY_CARD}, {self.EMPTY_STATE}, {self.DATE_RANGE_PICKER}'
        ).first
        expect(page_indicator).to_be_visible(timeout=timeout)
        return self

    def assert_card_count(self, expected: int, timeout: Optional[int] = None) -> "AgentStatsPage":
        """Assert the summary card count."""
        expect(self.page.locator(self.SUMMARY_CARD)).to_have_count(
            expected, timeout=timeout or self.timeout
        )
        return self
