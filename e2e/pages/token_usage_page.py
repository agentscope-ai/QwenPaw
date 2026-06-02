# -*- coding: utf-8 -*-
"""
QwenPaw Token Usage page object.

Wraps all interactions on the token usage statistics page and exposes
business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class TokenUsagePage(BasePage):
    """
    Token Usage page object.

    Wraps all user interactions on the token usage statistics page:
    - Page navigation
    - Fetching usage data
    - Viewing charts
    """

    PAGE_TITLE = "Token Usage"
    PAGE_URL = f"{config.base_url}/token-usage"

    # ========== Selector definitions ==========

    # Table-related selectors
    USAGE_TABLE = ".qwenpaw-table"
    USAGE_ROW = ".qwenpaw-table-tbody tr"

    # Date picker
    DATE_PICKER = ".qwenpaw-picker"

    # Chart container
    CHART_CONTAINER = 'div[class*="chart"], canvas'

    # ========== Initialization ==========

    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("TokenUsagePage initialized")

    # ========== Page navigation ==========

    def open(self) -> "TokenUsagePage":
        """Open the Token Usage page."""
        logger.info("Opening Token Usage page")
        self.goto()
        self.wait_for_loading()
        return self

    def wait_for_page_loaded(self) -> bool:
        """
        Wait for the page to finish loading.

        Returns:
            True if the page loaded successfully.
        """
        try:
            self.wait_for_element(self.USAGE_TABLE, timeout=10000)
            return True
        except Exception as e:
            logger.error(f"Page load failed: {e}")
            return False

    # ========== Data retrieval ==========

    def get_usage_rows(self) -> List[Locator]:
        """
        Return all usage rows.

        Returns:
            List of Locator objects.
        """
        logger.info("Getting usage rows")
        return self.find_all(self.USAGE_ROW)

    def get_chart(self) -> Optional[Locator]:
        """
        Return the chart element.

        Returns:
            Chart Locator, or None if not found.
        """
        logger.info("Getting chart element")
        try:
            chart = self.find(self.CHART_CONTAINER)
            if chart.count() > 0:
                return chart
            return None
        except Exception as e:
            logger.warning(f"Chart not found: {e}")
            return None

    def has_usage_data(self) -> bool:
        """
        Check whether usage data is present.

        Returns:
            True if usage data exists.
        """
        logger.info("Checking if usage data exists")
        try:
            rows = self.get_usage_rows()
            return len(rows) > 0
        except Exception:
            return False
