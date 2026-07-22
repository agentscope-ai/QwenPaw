# -*- coding: utf-8 -*-
"""
QwenPaw Environments page object.

Wraps all interactions on the environment variables configuration page and
exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class EnvironmentsPage(BasePage):
    """
    Environments page object.

    Wraps all user interactions on the environment variables configuration page:
    - Open the environment variables page
    - Get the list of environment variable rows
    - Get environment variable keys and values
    - Click the add button
    - Click the save button
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/environments"

    # ========== Selector definitions ==========

    # Page load indicator
    ENV_PAGE_CONTAINER = "div[class*=environmentsPage]"
    PAGE_LOAD_INDICATOR = ENV_PAGE_CONTAINER

    # Table-related selectors
    ENV_TABLE = ".qwenpaw-table"
    ENV_ROW = ".qwenpaw-table-tbody tr"
    ADD_BTN = 'button:has-text("添加"), button:has-text("Add")'
    SAVE_BTN = 'button.qwenpaw-btn-primary:has-text("保存"), button:has-text("Save")'

    # ========== Navigation ==========

    def open(self) -> "EnvironmentsPage":
        """Open the Environments page."""
        logger.info("Opening Environments page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== Environment variable operations ==========

    def get_env_rows(self) -> List[Locator]:
        """Return all environment variable rows."""
        rows = self.page.locator(self.ENV_ROW).all()
        logger.info(f"Found {len(rows)} environment variable rows")
        return rows

    def get_env_key(self, row: Locator) -> str:
        """Return the environment variable key."""
        # Try to get the key from the first column
        key_cell = row.locator("td").first
        if key_cell.count() > 0:
            return key_cell.inner_text().strip()
        return ""

    def get_env_value(self, row: Locator) -> str:
        """Return the environment variable value."""
        # Try to get the value from the second column
        value_cells = row.locator("td").all()
        if len(value_cells) > 1:
            return value_cells[1].inner_text().strip()
        return ""

    def click_add(self) -> "EnvironmentsPage":
        """Click the add button."""
        add_btn = self.page.locator(self.ADD_BTN).first
        if add_btn.count() > 0:
            add_btn.click()
            logger.info("Clicked add button")
        return self

    def click_save(self) -> "EnvironmentsPage":
        """Click the save button."""
        save_btn = self.page.locator(self.SAVE_BTN).first
        if save_btn.count() > 0:
            save_btn.click()
            logger.info("Clicked save button")
        return self

    # ========== Assertion methods ==========

    def assert_env_row_count(self, expected_count: int, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """Assert the environment variable row count."""
        expect(self.page.locator(self.ENV_ROW)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self

    def assert_env_exists(self, env_key: str, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """Assert that the environment variable exists."""
        env_row = self.page.locator(self.ENV_ROW).filter(
            has_text=env_key
        ).first
        expect(env_row).to_be_visible(timeout=timeout or self.timeout)
        return self
