# -*- coding: utf-8 -*-
"""
QwenPaw Skill Pool page object.

Wraps all interactions on the Skill Pool page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class SkillPoolPage(BasePage):
    """
    Skill Pool page object.

    Wraps all user actions on the Skill Pool page:
    - Page navigation
    - Get skill cards
    - Search skills
    - Upload and install skills
    """

    PAGE_TITLE = "Skill Pool"
    PAGE_URL = f"{config.base_url}/skill-pool"

    # ========== Selector definitions ==========

    # Skill card
    SKILL_CARD = ".qwenpaw-card"

    # Search input
    SEARCH_INPUT = 'input[placeholder*="搜索"], input[placeholder*="Search"]'

    # Upload button
    UPLOAD_BTN = 'button:has-text("上传"), button:has-text("Upload")'

    # Install button
    INSTALL_BTN = 'button:has-text("安装"), button:has-text("Install")'

    # ========== Initialization ==========

    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("SkillPoolPage initialized")

    # ========== Page navigation ==========

    def open(self) -> "SkillPoolPage":
        """Open the Skill Pool page."""
        logger.info("Opening Skill Pool page")
        self.goto()
        self.wait_for_loading()
        return self

    def wait_for_page_loaded(self) -> bool:
        """
        Wait for the page to finish loading.

        Returns:
            True if loaded, False otherwise.
        """
        try:
            self.wait_for_element(self.SKILL_CARD, timeout=10000)
            return True
        except Exception as e:
            logger.error(f"Page load failed: {e}")
            return False

    # ========== Skill card methods ==========

    def get_skill_cards(self) -> List[Locator]:
        """
        Return all skill cards.

        Returns:
            List of Locator instances.
        """
        logger.info("Getting skill cards")
        return self.find_all(self.SKILL_CARD)

    def get_skill_name(self, card: Locator) -> str:
        """
        Read the skill name from a card.

        Args:
            card: Skill card Locator.

        Returns:
            The skill name.
        """
        logger.info("Getting skill name from card")
        try:
            # Try to read the card title or its text content
            return card.inner_text().strip().split('\n')[0]
        except Exception as e:
            logger.warning(f"Failed to get skill name: {e}")
            return ""

    # ========== Search ==========

    def search_skills(self, keyword: str) -> "SkillPoolPage":
        """
        Search for skills.

        Args:
            keyword: Search keyword.

        Returns:
            self
        """
        logger.info(f"Searching skills with keyword: {keyword}")
        search_input = self.find(self.SEARCH_INPUT)
        search_input.fill(keyword)
        self.wait(500)
        return self

    # ========== Upload and install ==========

    def click_upload(self) -> "SkillPoolPage":
        """
        Click the Upload button.

        Returns:
            self
        """
        logger.info("Clicking upload button")
        upload_btn = self.find(self.UPLOAD_BTN)
        upload_btn.click()
        self.wait(500)
        return self

    def click_install(self, card: Locator) -> "SkillPoolPage":
        """
        Click the Install button on a given skill card.

        Args:
            card: Skill card Locator.

        Returns:
            self
        """
        logger.info("Clicking install button on skill card")
        # Find the install button inside the card
        install_btn = card.locator(self.INSTALL_BTN).first
        if install_btn.count() > 0:
            install_btn.click()
            self.wait(500)
        else:
            logger.warning("Install button not found in card")
        return self
