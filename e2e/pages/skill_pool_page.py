# -*- coding: utf-8 -*-
"""
QwenPaw Skill Pool page object.

Wraps interactions on the Skill Pool page (``/skill-pool``), including the
skill auto-sync affordances added in upstream #5639:

- the per-card sync status badge (colored dot + status label),
- the hover-revealed single automation quick action,
- the independent built-in Auto Update and Auto Sync detail settings.

Selectors target the real post-#5639 DOM: antd ``prefixCls`` is ``qwenpaw``
and component-local styles are CSS-Module hashed class names, matched via
``[class*=basename]`` substrings (never the stale ``.qwenpaw-card`` stub).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from playwright.sync_api import Page, Locator

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class SkillPoolPage(BasePage):
    """Skill Pool page object (card grid + edit drawer + auto-sync)."""

    PAGE_TITLE = "Skill Pool"
    PAGE_URL = f"{config.base_url}/skill-pool"

    # ========== Selectors ==========
    # Page + card grid (SkillPool/index.module.less, PoolSkillCard.tsx)
    PAGE_CONTAINER = '[class*="skillsPage"]'
    SKILL_GRID = '[class*="skillsGrid"]'
    SKILL_CARD = '[class*="skillCard"]'
    SKILL_TITLE = '[class*="skillTitle"]'
    # Sync status badge (rendered for every card) + its colored dot.
    STATUS_BADGE = '[class*="statusBadge"]'
    STATUS_DOT = '[class*="statusDot"]'
    # Automation chip in the title row (Auto Sync, Auto Update, or both).
    AUTOMATION_TAG = '[class*="automationTag"]'
    BUILTIN_TAG = '[class*="builtinTag"]'
    CUSTOM_TAG = '[class*="customTag"]'
    # Card footer is only mounted on hover / batch / mobile; the single
    # automation quick action (SyncOutlined) lives inside it.
    CARD_FOOTER = '[class*="cardFooter"]'
    AUTOMATION_BUTTON = '[class*="automationButton"]'

    # Edit drawer (PoolSkillDrawer.tsx)
    DRAWER = '.qwenpaw-drawer'
    DRAWER_TITLE = '.qwenpaw-drawer-title'
    AUTO_SYNC_SWITCH = '.qwenpaw-drawer [data-testid="auto-sync-switch"]'
    # Target-agent multi-select is rendered ONLY after the switch is ON; anchor
    # on its placeholder text (unique) so we don't match other selects.
    TARGET_SELECT_PLACEHOLDER = (
        '.qwenpaw-drawer [class*="select-selection-placeholder"]'
        ':has-text("All agents that have this skill"), '
        '.qwenpaw-drawer [class*="select-selection-placeholder"]'
        ':has-text("所有已安装该技能的智能体")'
    )
    SAVE_BTN = (
        '.qwenpaw-drawer button:has-text("Save"), '
        '.qwenpaw-drawer button:has-text("保存")'
    )
    CANCEL_BTN = (
        '.qwenpaw-drawer button:has-text("Cancel"), '
        '.qwenpaw-drawer button:has-text("取消")'
    )

    # ========== Initialization ==========

    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("SkillPoolPage initialized")

    # ========== Navigation ==========

    def open(self) -> "SkillPoolPage":
        """Open the Skill Pool page and wait for the card grid container."""
        logger.info("Opening Skill Pool page")
        self.goto()
        try:
            self.page.locator(self.PAGE_CONTAINER).first.wait_for(
                state="visible", timeout=self.timeout
            )
        except Exception:
            logger.warning("skillsPage container not visible within timeout")
        self.wait(500)
        return self

    # ========== Card queries ==========

    def get_skill_cards(self) -> List[Locator]:
        """Return all skill cards currently rendered in the grid."""
        return self.page.locator(self.SKILL_CARD).all()

    def find_card_by_name(self, name: str) -> Optional[Locator]:
        """Return the skill card whose text contains ``name`` (or None)."""
        card = self.page.locator(
            f'{self.SKILL_CARD}:has-text("{name}")'
        ).first
        return card if card.count() > 0 else None

    def hover_card(self, card: Locator) -> "SkillPoolPage":
        """Hover a card so its footer automation action is mounted."""
        card.scroll_into_view_if_needed(timeout=5000)
        card.hover(timeout=5000)
        self.wait(300)
        return self

    def open_edit_drawer(self, name: str) -> "SkillPoolPage":
        """Click a skill card (non-batch mode) to open its edit drawer."""
        card = self.find_card_by_name(name)
        if card is None:
            raise ValueError(f"Skill card not found: {name}")
        card.scroll_into_view_if_needed(timeout=5000)
        card.click()
        self.page.locator(self.DRAWER).first.wait_for(
            state="visible", timeout=self.timeout
        )
        self.wait(400)
        return self

    def toggle_auto_sync_switch(self) -> "SkillPoolPage":
        """Click the Auto Sync switch inside the open edit drawer."""
        switch = self.page.locator(self.AUTO_SYNC_SWITCH).first
        switch.wait_for(state="visible", timeout=self.timeout)
        switch.click()
        self.wait(400)
        return self

    def save_drawer(self) -> "SkillPoolPage":
        """Click the drawer's Save button."""
        self.page.locator(self.SAVE_BTN).first.click()
        self.wait(800)
        return self

    # ========== Seeding (API — pool endpoints in app/routers/skills.py) ==========

    @staticmethod
    def seed_pool_skill(api_context, name: str, content: str = "") -> bool:
        """Create a pool skill via ``POST /api/skills/pool/create``.

        A freshly-created pool skill has ``auto_sync=false`` (the create
        schema has no auto_sync field). Returns True on success; a 4xx
        (already exists) is treated as a soft success so re-runs don't break
        setup.
        """
        body = content or (
            f"---\nname: {name}\n"
            "description: e2e seeded pool skill for auto-sync tests\n---\n"
            f"# {name}\n\nSeeded by e2e; no LLM required.\n"
        )
        resp = api_context.post(
            "/api/skills/pool/create",
            data={"name": name, "content": body, "enable": True},
        )
        ok = resp.ok or resp.status in (400, 409)
        logger.info("seed_pool_skill(%s) -> HTTP %s (ok=%s)", name, resp.status, ok)
        return ok

    @staticmethod
    def delete_pool_skill(api_context, name: str) -> None:
        """Delete a pool skill (best-effort cleanup)."""
        try:
            resp = api_context.delete(f"/api/skills/pool/{name}")
            logger.info("delete_pool_skill(%s) -> HTTP %s", name, resp.status)
        except Exception as exc:  # noqa: BLE001 - cleanup must never raise
            logger.warning("delete_pool_skill(%s) failed: %s", name, exc)
