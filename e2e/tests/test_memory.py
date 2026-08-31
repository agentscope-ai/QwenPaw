# -*- coding: utf-8 -*-
"""
QwenPaw Long-term Memory end-to-end tests.

UI-driven only. Pure API contract tests for /api/workspace/memory and
/api/workspace/running-config live in ``tests/integration/``.

Cases:
- MEM-001 P1  test_auto_memory_interval_persistence
- MEM-002 P1  test_dream_cron_persistence
- MEM-003 P1  test_memory_card_ui_renders
- MEM-004 P1  test_workspace_memory_md_visible
- MEM-005 P2  test_memory_search_recall_seeded         (xfail, requires_llm)
- MEM-006 P2  test_memory_backend_select_switches_tabs
- MEM-007 P2  test_auto_memory_search_toggle_and_max_results
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
        # Defensive reset: a prior coding-mode case may have bound a
        # project directory, which makes the files page show the project
        # tree instead of the workspace tree.
        api_context.post(
            "/api/coding-mode",
            data={"enabled": False},
            headers=memory_page._agent_headers(),
        )
        api_context.put(
            "/api/workspace/project-directory",
            data={"path": None},
            headers=memory_page._agent_headers(),
        )

        log_test_step("2. Open /files")
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
            f"{memory_page.WORKSPACE_URL.replace('/files', '/chat')}",
            wait_until="commit",
            timeout=memory_page.timeout,
        )
        chat_input = memory_page.page.locator(
            '.qwenpaw-sender textarea:visible, .qwenpaw-sender [role="textbox"]:visible'
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


# ============================================================================
# MEM-001 P1 — auto_memory_interval edit + save + reload persistence
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.memory
class TestAutoMemoryIntervalPersistence:
    """MEM-001: edit Auto Memory Interval, save, reload, value persists."""

    @pytest.mark.test_id("MEM-001")
    def test_auto_memory_interval_persistence(
        self,
        memory_page: MemoryPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("0. Snapshot running config for teardown restore")
        original_cfg = memory_page.api_get_running_config(api_context)

        try:
            log_test_step("1. Open /agent-config → Long-term Memory tab")
            memory_page.open_agent_config()
            memory_page.click_memory_tab()
            interval_input = memory_page.page.locator(
                memory_page.AUTO_MEMORY_INTERVAL_INPUT
            ).first
            expect(interval_input).to_be_visible(
                timeout=memory_page.timeout
            )

            log_test_step("2. Fill a distinct value and save")
            old_value = interval_input.input_value()
            new_value = "7" if old_value != "7" else "9"
            interval_input.fill(new_value)
            memory_page.click_save()

            log_test_step("3. Reload page, re-open tab, value persisted")
            memory_page.page.reload(wait_until="domcontentloaded")
            memory_page.page.wait_for_timeout(3000)
            memory_page.click_memory_tab()
            interval_after = memory_page.page.locator(
                memory_page.AUTO_MEMORY_INTERVAL_INPUT
            ).first
            expect(interval_after).to_be_visible(
                timeout=memory_page.timeout
            )
            assert interval_after.input_value() == new_value, (
                f"interval not persisted: expected {new_value}, "
                f"got {interval_after.input_value()!r}"
            )
        finally:
            memory_page.api_put_running_config(api_context, original_cfg)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MEM-002 P1 — dream_cron edit + save + reload persistence
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.memory
class TestDreamCronPersistence:
    """MEM-002: edit Dream Schedule cron, save, reload, value persists."""

    @pytest.mark.test_id("MEM-002")
    def test_dream_cron_persistence(
        self,
        memory_page: MemoryPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("0. Snapshot running config for teardown restore")
        original_cfg = memory_page.api_get_running_config(api_context)

        try:
            log_test_step("1. Open /agent-config → Long-term Memory tab")
            memory_page.open_agent_config()
            memory_page.click_memory_tab()
            cron_input = memory_page.page.locator(
                memory_page.DREAM_CRON_INPUT
            ).first
            expect(cron_input).to_be_visible(timeout=memory_page.timeout)

            log_test_step("2. Ensure dream cron is enabled (input editable)")
            if cron_input.is_disabled():
                memory_page.page.locator(
                    memory_page.DREAM_CRON_ENABLED_SWITCH
                ).first.click()
                memory_page.page.wait_for_timeout(300)

            log_test_step("3. Fill a valid 5-field cron and save")
            old_value = cron_input.input_value()
            new_value = "0 3 * * *" if old_value != "0 3 * * *" else "0 4 * * *"
            cron_input.fill(new_value)
            memory_page.click_save()

            log_test_step("4. Reload page, re-open tab, cron persisted")
            memory_page.page.reload(wait_until="domcontentloaded")
            memory_page.page.wait_for_timeout(3000)
            memory_page.click_memory_tab()
            cron_after = memory_page.page.locator(
                memory_page.DREAM_CRON_INPUT
            ).first
            expect(cron_after).to_be_visible(timeout=memory_page.timeout)
            assert cron_after.input_value() == new_value, (
                f"dream_cron not persisted: expected {new_value!r}, "
                f"got {cron_after.input_value()!r}"
            )
        finally:
            memory_page.api_put_running_config(api_context, original_cfg)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MEM-006 P2 — memory backend Select drives dynamic memory tabs (no save)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.memory
class TestMemoryBackendSelect:
    """MEM-006: backend Select options + dynamic tab swap (client-side).

    Intentionally never clicks Save: switching the backend is
    restart-gated on the server, so the case only asserts the
    client-side linkage (Select value -> which memory tab renders).
    """

    @pytest.mark.test_id("MEM-006")
    def test_memory_backend_select_switches_tabs(
        self,
        memory_page: MemoryPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = memory_page.page

        log_test_step("1. Open /agent-config on the ReAct Agent tab")
        memory_page.open_agent_config()
        memory_page.click_react_tab()
        backend_select = page.locator(
            memory_page.BACKEND_SELECT_TRIGGER
        ).first
        expect(backend_select).to_be_visible(timeout=memory_page.timeout)

        log_test_step("2. Baseline: remelight backend => Long-term Memory tab")
        expect(
            page.locator(memory_page.REME_MEMORY_TAB).first
        ).to_be_visible(timeout=memory_page.timeout)

        log_test_step("3. Open the Select; options include adbpg + none")
        backend_select.click()
        options = page.locator(memory_page.BACKEND_OPTION)
        options.first.wait_for(state="visible", timeout=memory_page.timeout)
        option_texts = " | ".join(
            o.inner_text() for o in options.all()
        )
        assert "adbpg" in option_texts, f"options: {option_texts}"
        assert "none" in option_texts, f"options: {option_texts}"

        log_test_step("4. Pick adbpg => adbpgMemory tab replaces remelight")
        options.filter(has_text="adbpg").first.click()
        page.wait_for_timeout(800)
        expect(
            page.locator(memory_page.ADBPG_MEMORY_TAB).first
        ).to_be_visible(timeout=memory_page.timeout)
        expect(
            page.locator(memory_page.REME_MEMORY_TAB).first
        ).not_to_be_visible(timeout=5000)

        log_test_step("5. Pick remelight back => Long-term Memory tab returns")
        backend_select.click()
        page.locator(memory_page.BACKEND_OPTION).filter(
            has_text="remelight"
        ).first.click()
        page.wait_for_timeout(800)
        expect(
            page.locator(memory_page.REME_MEMORY_TAB).first
        ).to_be_visible(timeout=memory_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MEM-007 P2 — Auto Memory Search switch + max_results field (no save)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.memory
class TestAutoMemorySearchControls:
    """MEM-007: expand the Auto Memory Search collapse, toggle the
    switch (aria-checked flips), and edit max_results in-form.

    Re-anchored from the original plan: v2.0.1 has no ``min_score``
    field and no conditional show/hide — the collapse children are
    forceRender'ed, so the assertions target switch state + editability.
    Nothing is saved; a reload discards the changes.
    """

    @pytest.mark.test_id("MEM-007")
    def test_auto_memory_search_toggle_and_max_results(
        self,
        memory_page: MemoryPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = memory_page.page

        log_test_step("1. Open /agent-config → Long-term Memory tab")
        memory_page.open_agent_config()
        memory_page.click_memory_tab()
        expect(
            page.locator(memory_page.DREAM_CRON_INPUT).first
        ).to_be_visible(timeout=memory_page.timeout)

        log_test_step("2. Locate the Auto Memory Search switch")
        # The redesigned card renders the switch inline (no collapse
        # panel anymore).
        switch = page.locator(memory_page.AUTO_SEARCH_SWITCH).first
        expect(switch).to_be_visible(timeout=memory_page.timeout)

        log_test_step("3. Toggle the switch and assert aria-checked flips")
        before = switch.get_attribute("aria-checked")
        switch.click()
        page.wait_for_timeout(300)
        after = switch.get_attribute("aria-checked")
        assert before != after, (
            f"auto search switch did not flip: {before} -> {after}"
        )

        log_test_step("4. max_results is editable (fill 5, value sticks)")
        max_results = page.locator(
            memory_page.AUTO_SEARCH_MAX_RESULTS_INPUT
        ).first
        expect(max_results).to_be_visible(timeout=memory_page.timeout)
        max_results.fill("5")
        assert max_results.input_value() == "5"

        log_test_step("5. Restore the switch (in-form only, never saved)")
        switch.click()
        page.wait_for_timeout(300)
        assert switch.get_attribute("aria-checked") == before

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
