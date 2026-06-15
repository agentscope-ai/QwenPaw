# -*- coding: utf-8 -*-
"""
QwenPaw Long-term Memory end-to-end tests.

Cases:
- MEM-001 P0  test_daily_memory_crud
- MEM-002 P1  test_running_config_persistence
- MEM-003 P1  test_memory_card_ui_renders
- MEM-004 P1  test_workspace_memory_md_visible
- MEM-005 P2  test_memory_search_recall_seeded         (xfail, requires_llm)
- MEM-006 P2  test_daily_memory_path_traversal_blocked
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
# MEM-001 P0 — Daily memory CRUD via API
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.memory
class TestDailyMemoryCRUD:
    """MEM-001: PUT then GET a daily memory file; list contains it."""

    @pytest.mark.test_id("MEM-001")
    def test_daily_memory_crud(
        self,
        memory_page: MemoryPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        # Use a far-future date so it doesn't collide with real entries.
        date_name = "2099-01-15.md"
        content = f"e2e-mem-{int(time.time())}"

        log_test_step("1. PUT daily memory file")
        memory_page.api_write_daily_memory(api_context, date_name, content)

        log_test_step("2. GET daily memory list contains the file")
        files = memory_page.api_list_daily_memory(api_context)
        names = [f.get("filename") or f.get("name") for f in files]
        assert date_name in names, (
            f"Expected {date_name} in list; got {names}"
        )

        log_test_step("3. GET single daily memory returns the content")
        got = memory_page.api_read_daily_memory(api_context, date_name)
        assert got == content, (
            f"Content mismatch: expected {content!r}, got {got!r}"
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MEM-002 P1 — Running config persistence (reme_light_memory_config)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.memory
class TestRunningConfigPersistence:
    """MEM-002: PUT new memory config, GET reads back the same values."""

    @pytest.mark.test_id("MEM-002")
    def test_running_config_persistence(
        self,
        memory_page: MemoryPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Snapshot the original reme_light_memory_config")
        original = memory_page.api_get_running_config(api_context)
        original_reme = dict(original.get("reme_light_memory_config") or {})

        log_test_step("2. PUT new values for the three observed fields")
        new_values = {
            "summarize_when_compact": not original_reme.get(
                "summarize_when_compact", True
            ),
            "auto_memory_interval": (
                (original_reme.get("auto_memory_interval") or 5) + 1
            ),
            "dream_cron": "30 21 * * *",
        }
        try:
            memory_page.api_put_running_config(
                api_context,
                {"reme_light_memory_config": new_values},
            )

            log_test_step("3. GET back and assert the fields persisted")
            current = memory_page.api_get_running_config(api_context)
            current_reme = current.get("reme_light_memory_config") or {}
            for k, v in new_values.items():
                assert current_reme.get(k) == v, (
                    f"Expected {k}={v}, got {current_reme.get(k)}"
                )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            log_test_step("Cleanup: restore original config")
            try:
                memory_page.api_put_running_config(
                    api_context,
                    {
                        "reme_light_memory_config": {
                            "summarize_when_compact": original_reme.get(
                                "summarize_when_compact", True,
                            ),
                            "auto_memory_interval": original_reme.get(
                                "auto_memory_interval", 5,
                            ),
                            "dream_cron": original_reme.get(
                                "dream_cron", "0 23 * * *",
                            ),
                        },
                    },
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("Restore failed: %s", exc)


# ============================================================================
# MEM-003 P1 — Long-term Memory card renders on /agent-config
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.memory
class TestMemoryCardUI:
    """MEM-003: Tab is visible; switching to it shows the card title."""

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
    """MEM-004: Workspace lists MEMORY.md in the file panel."""

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
    keyword, asking the agent should produce a reply that mentions the
    keyword. Strongly LLM- and embedding-dependent; declared xfail
    strict=False so passes do not silently regress.
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


# ============================================================================
# MEM-006 P2 — Daily memory path traversal blocked
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.memory
class TestDailyMemoryPathTraversal:
    """
    MEM-006: Attempts to write outside ``memory/`` via filename
    traversal must be rejected. The router uses path params so
    ``%2F`` in the name resolves to a 4xx (typically 405 from FastAPI's
    method routing or 400 from sanitization).
    """

    @pytest.mark.test_id("MEM-006")
    def test_daily_memory_path_traversal_blocked(
        self,
        memory_page: MemoryPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Encoded slash in the name → 4xx")
        # ``foo%2F..%2Fbar.md`` decodes to ``foo/../bar.md`` which is
        # not the simple {name} the router expects.
        resp = api_context.put(
            "/api/workspace/memory/foo%2F..%2Fbar.md",
            data={"content": "x"},
            headers=memory_page._agent_headers(),
        )
        assert 400 <= resp.status < 500, (
            f"Expected 4xx for traversal; got {resp.status}: {resp.text()}"
        )

        log_test_step("2. Leading dots resolve to a 4xx as well")
        resp2 = api_context.get(
            "/api/workspace/memory/..bad.md",
            headers=memory_page._agent_headers(),
        )
        assert 400 <= resp2.status < 500, (
            f"Expected 4xx for ..bad.md; got {resp2.status}: {resp2.text()}"
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
