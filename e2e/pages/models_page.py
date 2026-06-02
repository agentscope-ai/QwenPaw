# -*- coding: utf-8 -*-
"""
QwenPaw Models page object.

Wraps all interactions on the Models page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class ModelsPage(BasePage):
    """
    Models page object.

    Wraps all user interactions on the Models page:
    - Open the models page
    - Get the breadcrumb
    - Click the download model button
    - Get the model list
    """

    PAGE_TITLE = "QwenPaw Console"
    MODELS_URL = f"{config.base_url}/models"
    PAGE_URL = MODELS_URL

    # ========== Selector definitions ==========

    # Page load indicator
    PAGE_LOAD_INDICATOR = '.ant-breadcrumb, .qwenpaw-breadcrumb, h1, h2, [class*="breadcrumb"]'

    # Breadcrumb
    BREADCRUMB_SELECTOR = '.ant-breadcrumb, .qwenpaw-breadcrumb, nav[class*="breadcrumb"], [class*="Breadcrumb"]'

    # Download model button
    DOWNLOAD_MODEL_BTN = 'button:has-text("下载模型"), button:has-text("Download Model"), button:has-text("下载"), button:has-text("Download")'

    # Model list
    MODEL_LIST_SELECTOR = '.ant-list-item, .qwenpaw-list-item, [class*="modelItem"], [class*="model-item"], table tbody tr, .ant-table-row, .qwenpaw-table-row'

    # ========== Navigation ==========

    def open(self) -> "ModelsPage":
        """Open the Models page."""
        logger.info("Opening Models page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "ModelsPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== Page element operations ==========

    def get_breadcrumb(self) -> str:
        """Return the breadcrumb text."""
        breadcrumb = self.page.locator(self.BREADCRUMB_SELECTOR).first
        if breadcrumb.count() > 0:
            return breadcrumb.inner_text()
        return ""

    def click_download_model(self) -> "ModelsPage":
        """Click the download model button."""
        download_btn = self.page.locator(self.DOWNLOAD_MODEL_BTN).first
        if download_btn.count() > 0:
            download_btn.click()
            logger.info("Clicked download model button")
        else:
            logger.warning("Download model button not found")
        return self

    def get_model_list(self) -> List[Locator]:
        """Return the model list."""
        models = self.page.locator(self.MODEL_LIST_SELECTOR).all()
        logger.info(f"Found {len(models)} models")
        return models

    # ========== Assertion methods ==========

    def assert_breadcrumb_contains(self, expected_text: str, timeout: Optional[int] = None) -> "ModelsPage":
        """Assert the breadcrumb contains the given text."""
        breadcrumb = self.page.locator(self.BREADCRUMB_SELECTOR).first
        expect(breadcrumb).to_contain_text(expected_text, timeout=timeout or self.timeout)
        return self

    def assert_model_count(self, expected_count: int, timeout: Optional[int] = None) -> "ModelsPage":
        """Assert the model count."""
        expect(self.page.locator(self.MODEL_LIST_SELECTOR)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self

    def assert_download_button_visible(self, timeout: Optional[int] = None) -> "ModelsPage":
        """Assert the download button is visible."""
        download_btn = self.page.locator(self.DOWNLOAD_MODEL_BTN).first
        expect(download_btn).to_be_visible(timeout=timeout or self.timeout)
        return self
