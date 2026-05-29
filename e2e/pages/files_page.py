# -*- coding: utf-8 -*-
"""
QwenPaw Files page object.

Wraps all interactions on the Files page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class FilesPage(BasePage):
    """
    Files page object.

    Wraps all user interactions on the Files page:
    - Open the files page
    - Get the file list
    - Get file names and metadata
    - Click a file to open the editor
    - Toggle the file switch
    - Check whether a file is enabled
    """

    PAGE_TITLE = "QwenPaw Console"
    WORKSPACE_URL = f"{config.base_url}/workspace"
    PAGE_URL = WORKSPACE_URL

    # ========== Selector definitions ==========

    # Page load indicator
    PAGE_LOAD_INDICATOR = 'div[class*="fileItem"]'

    # File item selectors
    FILE_ITEM_SELECTOR = 'div[class*="fileItem"]'
    FILE_NAME_SELECTOR = 'div[class*="fileItemName"]'
    FILE_META_SELECTOR = 'div[class*="fileItemMeta"]'
    SWITCH_SELECTOR = 'button.qwenpaw-switch[role="switch"]'
    DRAG_HANDLE_SELECTOR = 'div[class*="dragHandle"]'

    # ========== Navigation ==========

    def open(self) -> "FilesPage":
        """Open the Files page."""
        logger.info("Opening Files page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "FilesPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== File list operations ==========

    def get_file_items(self) -> List[Locator]:
        """Return all file items."""
        items = self.page.locator(self.FILE_ITEM_SELECTOR).all()
        logger.info(f"Found {len(items)} file items")
        return items

    def get_file_name(self, item: Locator) -> str:
        """Return the file name."""
        name_element = item.locator(self.FILE_NAME_SELECTOR).first
        if name_element.count() > 0:
            return name_element.inner_text()
        return ""

    def get_file_meta(self, item: Locator) -> str:
        """Return the file metadata."""
        meta_element = item.locator(self.FILE_META_SELECTOR).first
        if meta_element.count() > 0:
            return meta_element.inner_text()
        return ""

    def click_file(self, item: Locator) -> "FilesPage":
        """Click a file to open the editor."""
        item.click()
        logger.info("Clicked file to open editor")
        return self

    def toggle_file_switch(self, item: Locator) -> "FilesPage":
        """Toggle the file switch."""
        switch = item.locator(self.SWITCH_SELECTOR).first
        if switch.count() > 0:
            switch.click()
            logger.info("Toggled file switch")
        return self

    def is_file_enabled(self, item: Locator) -> bool:
        """Return whether the file is enabled."""
        switch = item.locator(self.SWITCH_SELECTOR).first
        if switch.count() > 0:
            return switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
        return False

    # ========== Assertion methods ==========

    def assert_file_count(self, expected_count: int, timeout: Optional[int] = None) -> "FilesPage":
        """Assert the file count."""
        expect(self.page.locator(self.FILE_ITEM_SELECTOR)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self

    def assert_file_exists(self, file_name: str, timeout: Optional[int] = None) -> "FilesPage":
        """Assert that the file exists."""
        file_item = self.page.locator(self.FILE_ITEM_SELECTOR).filter(
            has=self.page.locator(self.FILE_NAME_SELECTOR).filter(has_text=file_name)
        ).first
        expect(file_item).to_be_visible(timeout=timeout or self.timeout)
        return self
