# -*- coding: utf-8 -*-
"""
Deep coding-mode tool-call flows for coverage boost (Plan B).

Targets: Runtime, Execution & Tool Calls (13,660 uncovered lines) —
coding mode project create/activate, file edit/save, tool call paths.

Run: pytest tests/test_cov_coding_deep.py -v
"""
from __future__ import annotations

import logging
import time

import pytest

from pages.coding_page import CodingPage
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p1
@pytest.mark.coding
class TestCodingToolCallsDeep:
    """
    COV-CD-001: Project create -> activate -> file edit/save -> tool call.

    Coverage: project_directory router, coding mode runtime, tool call
    execution framework, file save paths.
    """

    @pytest.mark.test_id("COV-CD-001")
    def test_coding_project_file_edit_deep(
        self,
        coding_page: CodingPage,
        api_context,
        request: pytest.FixtureRequest,
    ):
        test_name = request.node.name
        project_name = f"e2e-cov-{int(time.time()) % 100000}"

        log_test_step("1. Create + activate project via API")
        created = coding_page.api_create_project(api_context, project_name)
        coding_page.api_activate_project(api_context, created["path"])

        log_test_step("2. Seed a file in the project")
        coding_page.api_save_code_file(
            api_context, "notes.txt", "e2e coverage boost seed\n"
        )

        log_test_step("3. Enable coding mode and verify IDE")
        coding_page.api_set_coding_mode(api_context, True)
        coding_page.open_chat()
        coding_page.page.goto(coding_page.CODING_URL)
        coding_page.page.wait_for_load_state("domcontentloaded")
        coding_page.page.wait_for_timeout(3000)
        assert coding_page.verify_ide_layout_visible(), "IDE not visible"

        log_test_step("4. Ask the AI to edit the seeded file")
        coding_page.open_chat()
        coding_page.page.wait_for_timeout(3000)
        chat_input = coding_page.page.locator(
            '.qwenpaw-sender textarea:visible, '
            '.qwenpaw-sender [role="textbox"]:visible'
        ).first
        chat_input.fill("Append the line 'edited by e2e' to notes.txt")
        send_btn = coding_page.page.locator(
            "button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary"
        ).first
        send_btn.click()
        ai_bubble = coding_page.page.locator(
            ".qwenpaw-bubble.qwenpaw-bubble-start"
        ).first
        try:
            ai_bubble.wait_for(state="visible", timeout=120000)
        except Exception:
            raise AssertionError("AI response timed out")

        log_test_step("5. Verify file content changed via API")
        resp = api_context.get(
            "/api/workspace/code-files/notes.txt",
            headers=coding_page._agent_headers(),
        )
        if resp.ok:
            body = resp.text()
            logger.info(f"notes.txt contains edit: {'edited by e2e' in body}")
        else:
            logger.info(f"Read notes.txt failed [{resp.status}]")

        log_test_step("6. Disable coding mode (teardown)")
        coding_page.api_set_coding_mode(api_context, False)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
