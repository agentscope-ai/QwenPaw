# -*- coding: utf-8 -*-
"""
QwenPaw Long-term Memory end-to-end tests.

UI-driven only. Pure API contract tests for /api/workspace/memory and
/api/workspace/running-config live in ``tests/integration/``.

Cases:
- MEM-003 P1  test_memory_card_ui_renders
- MEM-004 P1  test_workspace_memory_md_visible
- MEM-005 P2  test_memory_search_recall_seeded         (xfail, requires_llm)
"""
from __future__ import annotations

import logging
import time

import pytest
from playwright.sync_api import expect

from pages.memory_page import MemoryPage
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


# ============================================================================
# MEM-003 P1 — Long-term Memory card renders on /agent-config
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.memory
class TestMemoryCardUI:
    """MEM-003: Tab is visible; switching to it shows the card body."""

    @pytest.mark.test_id("MEM-003")
    def test_memory_card_ui_renders(
        self,
        memory_page: MemoryPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Open /agent-config")
        memory_page.open_agent_config()

        log_test_step("2. 'Long-term Memory' tab is visible")
        expect(
            memory_page.page.locator(memory_page.MEMORY_TAB).first
        ).to_be_visible(timeout=memory_page.timeout)

        log_test_step("3. Click the tab and verify the dream_cron input")
        memory_page.click_memory_tab()
        # The dream_cron input is unique to this card and is the most
        # stable "card body rendered" signal; the card title text
        # collides with the Tab label and the className is design-system
        # specific.
        expect(
            memory_page.page.locator(memory_page.DREAM_CRON_INPUT).first
        ).to_be_visible(timeout=memory_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MEM-004 P1 — MEMORY.md is visible in the Workspace files panel
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.memory
class TestWorkspaceMemoryMd:
    """MEM-004: Workspace lists MEMORY.md in the file panel.

    Seeding via the workspace files API is a setup-only API call;
    the assertion itself is rendered in the Workspace UI panel.
    """

    @pytest.mark.test_id("MEM-004")
    def test_workspace_memory_md_visible(
        self,
        memory_page: MemoryPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Seed MEMORY.md via the workspace files API")
        # Isolated test backends start empty — MEMORY.md does not exist
        # by default. Seed one so the file panel has it to render.
        seed_resp = api_context.put(
            "/api/workspace/files/MEMORY.md",
            data={"content": "# Memory\n\ne2e seed\n"},
            headers=memory_page._agent_headers(),
        )
        assert seed_resp.ok, (
            f"Seed MEMORY.md failed [{seed_resp.status}]: {seed_resp.text()}"
        )

        log_test_step("2. Open /workspace")
        memory_page.open_workspace()

        log_test_step("3. MEMORY.md row is visible")
        # The file list renders each entry as a div with class
        # *fileItemName* — text-based locator is enough.
        expect(
            memory_page.page.locator('text="MEMORY.md"').first
        ).to_be_visible(timeout=memory_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MEM-005 P2 — Memory search recall (xfail when LLM unavailable)
# ============================================================================

@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p2
@pytest.mark.memory
class TestMemorySearchRecall:
    """
    MEM-005: With a seeded daily memory entry containing a unique
    keyword, asking the agent through the chat UI should produce a
    reply that mentions the keyword. Strongly LLM- and embedding-
    dependent; declared xfail strict=False so passes do not silently
    regress.
    """

    @pytest.mark.test_id("MEM-005")
    @pytest.mark.xfail(
        reason=(
            "Requires a configured LLM and may also need embedding "
            "infrastructure; environments without them will not recall "
            "the seeded keyword."
        ),
        strict=False,
    )
    def test_memory_search_recall_seeded(
        self,
        memory_page: MemoryPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        keyword = f"e2eKW{int(time.time())}"

        log_test_step(f"1. Seed memory with keyword {keyword}")
        memory_page.api_write_daily_memory(
            api_context,
            "2099-02-15.md",
            f"User mentioned the secret token {keyword} on this day.",
        )

        log_test_step("2. Open chat and ask about the keyword")
        memory_page.page.goto(
            f"{memory_page.WORKSPACE_URL.replace('/workspace', '/chat')}",
            wait_until="commit",
            timeout=memory_page.timeout,
        )
        chat_input = memory_page.page.locator(
            "textarea.qwenpaw-sender-input"
        ).first
        expect(chat_input).to_be_visible(timeout=memory_page.timeout)
        chat_input.fill(
            f"What did I previously say about {keyword}? Quote it."
        )
        send_btn = memory_page.page.locator(
            "button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary"
        ).first
        send_btn.click()

        log_test_step("3. Wait for AI bubble that mentions the keyword")
        expect(
            memory_page.page.locator(
                f'.qwenpaw-bubble.qwenpaw-bubble-start:has-text("{keyword}")'
            ).first
        ).to_be_visible(timeout=180000)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
