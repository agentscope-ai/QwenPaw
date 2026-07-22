# -*- coding: utf-8 -*-
"""
QwenPaw Skills page object.

Wraps all interactions on the Skills page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class SkillsPage(BasePage):
    """
    Skills page object.

    Wraps all user actions on the Skills page:
    - Open the Skills page
    - Get the list of skill cards
    - Read a skill's name
    - Toggle the skill switch
    - Check whether a skill is enabled
    - Search skills
    """

    PAGE_TITLE = "QwenPaw Console"
    SKILLS_URL = f"{config.base_url}/skills"
    PAGE_URL = SKILLS_URL

    # ========== Selector definitions ==========

    # Page load indicator
    SKILL_PAGE_CONTAINER = "div[class*=skillsPage]"
    PAGE_LOAD_INDICATOR = SKILL_PAGE_CONTAINER

    # Skill card selectors
    SKILL_CARD_SELECTOR = ".qwenpaw-card"
    SWITCH_SELECTOR = '.qwenpaw-switch'

    # Search input
    SEARCH_INPUT = 'input[placeholder*="搜索"], input[placeholder*="Search"], .ant-input-search input, .qwenpaw-input-search input'

    # ========== Navigation methods ==========

    def open(self) -> "SkillsPage":
        """Open the Skills page."""
        logger.info("Open the Skills page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "SkillsPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== Skill list methods ==========

    def get_skill_cards(self) -> List[Locator]:
        """Return all skill cards."""
        cards = self.page.locator(self.SKILL_CARD_SELECTOR).all()
        logger.info(f"Found {len(cards)} skill card(s)")
        return cards

    def get_skill_name(self, card: Locator) -> str:
        """Return the skill name for a card."""
        # Try to read the title from the card
        title_element = card.locator('.ant-card-meta-title, .qwenpaw-card-meta-title, h3, h4, [class*="title"]').first
        if title_element.count() > 0:
            return title_element.inner_text()

        # If no title, fall back to the card's text content
        return card.inner_text().strip()[:50]

    def toggle_skill(self, card: Locator) -> "SkillsPage":
        """Toggle the skill switch on a card."""
        switch = card.locator(self.SWITCH_SELECTOR).first
        if switch.count() > 0:
            switch.click()
            logger.info("Toggled skill switch")
        return self

    def is_skill_enabled(self, card: Locator) -> bool:
        """Return whether the skill is enabled."""
        switch = card.locator(self.SWITCH_SELECTOR).first
        if switch.count() > 0:
            return switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.classList.contains('ant-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
        return False

    def search_skills(self, keyword: str) -> "SkillsPage":
        """Search for skills."""
        search_input = self.page.locator(self.SEARCH_INPUT).first
        if search_input.count() > 0:
            search_input.fill(keyword)
            logger.info(f"Searching skills: {keyword}")
            # Wait for search results to load
            self.page.wait_for_timeout(500)
        return self

    # ========== Assertion methods ==========

    def assert_skill_count(self, expected_count: int, timeout: Optional[int] = None) -> "SkillsPage":
        """Assert the number of skill cards."""
        expect(self.page.locator(self.SKILL_CARD_SELECTOR)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self

    def assert_skill_exists(self, skill_name: str, timeout: Optional[int] = None) -> "SkillsPage":
        """Assert that a skill exists."""
        skill_card = self.page.locator(self.SKILL_CARD_SELECTOR).filter(
            has_text=skill_name
        ).first
        expect(skill_card).to_be_visible(timeout=timeout or self.timeout)
        return self
