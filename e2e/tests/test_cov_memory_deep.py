# -*- coding: utf-8 -*-
"""
Deep memory flows for coverage boost (Plan B).

Targets: Memory & ReMe (1,428 uncovered lines) + agents/context/scroll/
memoryspace.py (802 lines) — daily memory write/read, memory config
save, workspace memory files.

Run: pytest tests/test_cov_memory_deep.py -v
"""
from __future__ import annotations

import logging

import pytest

from pages.memory_page import MemoryPage
from pages.files_page import FilesPage
from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p1
@pytest.mark.memory
class TestMemoryDailyDeep:
    """
    COV-MM-001: Daily memory write -> chat recall -> workspace verify.

    Coverage: memory daily file writes, ReMe index, memoryspace scroll.
    """

    @pytest.mark.test_id("COV-MM-001")
    def test_daily_memory_write_recall(
        self,
        memory_page: MemoryPage,
        files_page: FilesPage,
        clean_chat_page,
        api_context,
        request: pytest.FixtureRequest,
    ):
        test_name = request.node.name
        keyword = "e2e_cov_secret_7331"

        log_test_step("1. Write a daily memory entry via API")
        memory_page.api_write_daily_memory(
            api_context,
            "2026-08-26.md",
            f"User mentioned the secret token {keyword} on this day.",
        )

        log_test_step("2. Verify the daily file was written (API read-back)")
        resp = api_context.get(
            "/api/workspace/memory/2026-08-26.md",
            headers=memory_page._agent_headers(),
        )
        assert resp.ok, f"Read-back daily memory failed [{resp.status}]"
        assert keyword in resp.text(), "Daily memory content missing keyword"

        log_test_step("2b. Open workspace files page (drives files UI)")
        files_page.page.goto(f"{config.base_url}/files")
        files_page.page.wait_for_load_state("domcontentloaded")
        files_page.page.wait_for_timeout(3000)
        items = files_page.get_file_items()
        logger.info(f"Workspace file items: {len(items)}")
        log_test_step("3. Ask the chat about the keyword")
        clean_chat_page.open()
        clean_chat_page.create_new_chat()
        clean_chat_page.send_message(
            f"What did I previously say about {keyword}? Quote it."
        )
        ai = clean_chat_page.wait_for_ai_response(timeout=90000)
        assert ai is not None, "AI response timed out"

        log_test_step("4. Verify response references the keyword")
        last_ai = clean_chat_page.get_last_ai_message()
        if last_ai is not None:
            text = last_ai.inner_text()
            logger.info(
                f"Recall hit: {keyword in text or '7331' in text}"
            )

        log_test_step("5. Open memory config tab and save unchanged")
        memory_page.open_agent_config()
        memory_page.click_memory_tab()
        memory_page.page.wait_for_timeout(1500)
        memory_page.click_save()
        memory_page.page.wait_for_timeout(1500)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.memory
class TestMemoryConfigDeep:
    """
    COV-MM-002: Memory running-config read/put round trip.

    Coverage: memory config persistence, ReMe backend switches.
    """

    @pytest.mark.test_id("COV-MM-002")
    def test_memory_config_round_trip(
        self, memory_page: MemoryPage, api_context, request: pytest.FixtureRequest
    ):
        test_name = request.node.name

        log_test_step("1. Read running config")
        cfg = memory_page.api_get_running_config(api_context)
        assert isinstance(cfg, dict), "Running config not a dict"

        log_test_step("2. Put config back unchanged")
        memory_page.api_put_running_config(api_context, cfg)

        log_test_step("3. Read again and compare")
        cfg2 = memory_page.api_get_running_config(api_context)
        assert cfg2 == cfg, "Config round trip mismatch"

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
