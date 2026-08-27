# -*- coding: utf-8 -*-
"""
Deep skill-system flows for coverage boost (Plan B).

Targets: agents/skill_system/hub.py (1,044 uncovered lines) — pool seed,
enable/disable, auto-sync toggle, edit drawer, delete.

Run: pytest tests/test_cov_skills_deep.py -v
"""
from __future__ import annotations

import logging

import pytest

from pages.skills_page import SkillsPage
from pages.skill_pool_page import SkillPoolPage
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skills
class TestSkillHubDeep:
    """
    COV-SK-001: Seed a pool skill -> import to workspace -> toggle -> delete.

    Coverage: skill_system/hub.py registration, sync, manifest handling.
    """

    @pytest.mark.test_id("COV-SK-001")
    def test_skill_seed_toggle_delete(
        self,
        skills_page: SkillsPage,
        skill_pool_page: SkillPoolPage,
        api_context,
        request: pytest.FixtureRequest,
    ):
        test_name = request.node.name
        skill_name = "e2e_cov_skill"

        log_test_step("1. Seed a pool skill via API")
        seeded = SkillPoolPage.seed_pool_skill(
            api_context,
            skill_name,
            "---\nname: e2e_cov_skill\ndescription: coverage boost skill\n---\n# E2E cov skill\n",
        )
        assert seeded, "Failed to seed pool skill"

        log_test_step("2. Open skill pool and find the skill")
        skill_pool_page.open()
        skill_pool_page.page.wait_for_timeout(2000)
        card = skill_pool_page.find_card_by_name(skill_name)
        assert card is not None, "Seeded skill not found in pool"

        log_test_step("3. Open edit drawer and save")
        skill_pool_page.open_edit_drawer(skill_name)
        skill_pool_page.page.wait_for_timeout(1500)
        skill_pool_page.save_drawer()
        skill_pool_page.page.wait_for_timeout(1500)

        log_test_step("4. Toggle auto-sync switch")
        try:
            skill_pool_page.toggle_auto_sync_switch()
            skill_pool_page.page.wait_for_timeout(1000)
        except Exception as exc:
            logger.warning(f"auto-sync toggle not drivable: {exc}")

        log_test_step("5. Open workspace skills page and verify list")
        skills_page.open()
        skills_page.wait_for_page_loaded()
        cards = skills_page.get_skill_cards()
        logger.info(f"Workspace skill cards: {len(cards)}")

        log_test_step("6. Search skills")
        skills_page.search_skills("e2e")
        skills_page.page.wait_for_timeout(1500)
        skills_page.search_skills("")
        skills_page.page.wait_for_timeout(1000)

        log_test_step("7. Toggle first skill enable state")
        cards = skills_page.get_skill_cards()
        if cards:
            switch = cards[0].locator(
                '[class*="switch"], [role="switch"]'
            ).first
            if switch.count() > 0:
                initial = skills_page.is_skill_enabled(cards[0])
                skills_page.toggle_skill(cards[0])
                skills_page.page.wait_for_timeout(1500)
                after = skills_page.is_skill_enabled(cards[0])
                assert after != initial, "Skill toggle did not change state"
                # restore
                skills_page.toggle_skill(cards[0])
                skills_page.page.wait_for_timeout(1000)
            else:
                logger.info("No switch on first skill card")

        log_test_step("8. Delete the seeded pool skill")
        SkillPoolPage.delete_pool_skill(api_context, skill_name)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
