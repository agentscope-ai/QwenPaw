# -*- coding: utf-8 -*-
"""
QwenPaw Coding Mode end-to-end tests.

Cases:
    - CODE-001 P0  test_enter_and_exit_coding_mode
    - CODE-002 P0  test_create_empty_project_and_open
    - CODE-003 P1  test_open_existing_directory
    - CODE-004 P1  test_chat_in_coding_mode_with_file_reference  (requires_llm)
    - CODE-005 P1  test_file_tree_open_and_edit_tab

Coding Mode is an opt-in IDE-style workspace. Most cases drive backend
APIs to set up state deterministically and then assert the UI renders
the expected pieces — the project-select modal's auto-open path is too
state-dependent for reliable e2e (see CODE-002 docstring). Pure-API
checks (tool registration, project switching, etc.) belong in
``tests/integration/``.
"""
from __future__ import annotations

import logging
import time

import pytest
from playwright.sync_api import expect

from pages.coding_page import CodingPage
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


# ============================================================================
# CODE-001: Enter and exit Coding Mode (URL round-trip)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.coding
class TestEnterAndExitCodingMode:
    """CODE-001: Toggle Coding Mode on and off via the header button."""

    @pytest.mark.test_id("CODE-001")
    def test_enter_and_exit_coding_mode(
        self,
        coding_page: CodingPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("0. Reset agent to Chat mode (defensive)")
        coding_page.api_set_coding_mode(api_context, False)

        log_test_step("1. Open /chat and verify the Code toggle is visible")
        coding_page.open_chat()
        expect(
            coding_page.page.locator(coding_page.TOGGLE_ENTER).first
        ).to_be_visible(timeout=coding_page.timeout)

        log_test_step("2. Enter Coding Mode (workspace default)")
        coding_page.enter_coding_mode_with_workspace_default()
        assert coding_page.is_in_coding_mode(), (
            f"Expected URL to contain /coding, got {coding_page.page.url}"
        )

        log_test_step("3. Verify IDE shell rendered")
        assert coding_page.verify_ide_layout_visible(), (
            "Coding Mode IDE shell did not render the Chat panel"
        )

        log_test_step("4. Exit Coding Mode and verify route back to /chat")
        coding_page.exit_coding_mode()
        assert not coding_page.is_in_coding_mode(), (
            f"Expected URL to leave /coding, got {coding_page.page.url}"
        )
        expect(
            coding_page.page.locator(coding_page.TOGGLE_ENTER).first
        ).to_be_visible(timeout=coding_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# CODE-002: Create empty project and open
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.coding
class TestCreateEmptyProjectAndOpen:
    """CODE-002: Create a brand-new empty project via API and assert IDE."""

    @pytest.mark.test_id("CODE-002")
    def test_create_empty_project_and_open(
        self,
        coding_page: CodingPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        project_name = f"e2e-coding-{int(time.time())}"

        log_test_step("1. Create + activate empty project, enable Coding Mode")
        # The toggle's project-select modal only auto-opens when
        # projectDir is undefined in the in-memory zustand store, which
        # only holds on a fresh first browser session. Driving the
        # APIs directly keeps this case deterministic.
        created = coding_page.api_create_project(api_context, project_name)
        coding_page.api_activate_project(api_context, created["path"])
        coding_page.api_set_coding_mode(api_context, True)

        try:
            log_test_step("2. Navigate directly to /coding and verify IDE")
            coding_page.open_chat()
            coding_page.page.goto(
                coding_page.CODING_URL,
                wait_until="commit",
                timeout=coding_page.timeout,
            )
            coding_page.page.wait_for_url(
                "**/coding",
                timeout=coding_page.timeout,
            )
            assert coding_page.verify_ide_layout_visible(), (
                "IDE shell did not render after creating project"
            )

            log_test_result(test_name, True, 0)
            logger.info(
                f"Test {test_name} passed (project: {project_name})"
            )
        finally:
            coding_page.api_set_coding_mode(api_context, False)


# ============================================================================
# CODE-003: Open existing directory (no copy)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.coding
class TestOpenExistingDirectory:
    """
    CODE-003: Bind the agent's coding project to an already-existing
    directory on disk via the activation API (the "Open Existing
    Directory" tab in the UI ultimately funnels into the same endpoint).

    The native folder-picker UI flow can't be driven from Playwright
    reliably, so we exercise the equivalent backend path: create a
    project (which lives at a real on-disk path), then re-bind the
    agent to that path with PUT /api/workspace/coding-project.
    """

    @pytest.mark.test_id("CODE-003")
    def test_open_existing_directory(
        self,
        coding_page: CodingPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        # Create a project up-front to give us a real existing path.
        seed_name = f"e2e-existing-{int(time.time())}"
        seed = coding_page.api_create_project(api_context, seed_name)

        log_test_step("1. Bind the agent to the existing path")
        bound = coding_page.api_activate_project(api_context, seed["path"])
        # Backends differ on the response shape; we only require that
        # the active path matches what we asked for.
        active_path = bound.get("path") or coding_page.api_get_coding_project(
            api_context,
        ).get("path")
        assert active_path == seed["path"], (
            f"Expected active path {seed['path']}, got {active_path}"
        )

        log_test_step("2. Enable Coding Mode and assert IDE renders")
        coding_page.api_set_coding_mode(api_context, True)
        try:
            coding_page.open_chat()
            coding_page.page.goto(
                coding_page.CODING_URL,
                wait_until="commit",
                timeout=coding_page.timeout,
            )
            coding_page.page.wait_for_url(
                "**/coding",
                timeout=coding_page.timeout,
            )
            assert coding_page.verify_ide_layout_visible(), (
                "IDE shell did not render after opening existing directory"
            )
            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed (path: {active_path})")
        finally:
            coding_page.api_set_coding_mode(api_context, False)


# ============================================================================
# CODE-004: Chat in Coding Mode (LLM round-trip, requires_llm)
# ============================================================================

@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p1
@pytest.mark.coding
class TestChatInCodingMode:
    """
    CODE-004: Send a chat message inside Coding Mode and confirm the
    embedded chat panel works end-to-end with an LLM. We don't assert
    on the response text content — only that an AI bubble appears.

    Skipped when ``QWENPAW_DASHSCOPE_API_KEY`` is unset (handled by
    ``conftest.pytest_collection_modifyitems``).
    """

    @pytest.mark.test_id("CODE-004")
    def test_chat_in_coding_mode_with_file_reference(
        self,
        coding_page: CodingPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        project_name = f"e2e-coding-chat-{int(time.time())}"

        log_test_step("1. Provision project, write a referenceable file")
        created = coding_page.api_create_project(api_context, project_name)
        coding_page.api_activate_project(api_context, created["path"])
        coding_page.api_save_code_file(
            api_context,
            "README.md",
            "# Sample\n\nHello from CODE-004 e2e.\n",
        )
        coding_page.api_set_coding_mode(api_context, True)

        try:
            log_test_step("2. Open IDE and locate the embedded chat input")
            coding_page.open_chat()
            coding_page.page.goto(
                coding_page.CODING_URL,
                wait_until="commit",
                timeout=coding_page.timeout,
            )
            coding_page.page.wait_for_url(
                "**/coding",
                timeout=coding_page.timeout,
            )
            assert coding_page.verify_ide_layout_visible(), (
                "IDE shell did not render"
            )

            log_test_step("3. Send a question that mentions README.md")
            chat_input = coding_page.page.locator(
                "textarea.qwenpaw-sender-input"
            ).first
            expect(chat_input).to_be_visible(timeout=coding_page.timeout)
            chat_input.fill(
                "What does README.md say in this project? "
                "Reply in one short sentence."
            )
            send_btn = coding_page.page.locator(
                "button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary"
            ).first
            send_btn.click()

            log_test_step("4. Wait for at least one AI bubble to appear")
            ai_bubble = coding_page.page.locator(
                ".qwenpaw-bubble.qwenpaw-bubble-start"
            ).first
            expect(ai_bubble).to_be_visible(timeout=120000)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            coding_page.api_set_coding_mode(api_context, False)


# ============================================================================
# CODE-005: File tree click → editor tab
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.coding
class TestFileTreeOpenTab:
    """
    CODE-005: Clicking a file in the IDE file tree opens it in the
    TabbedEditor. We seed a file via API so the project tree always has
    something to click — newly-created projects only contain ``.git``
    which is hidden.
    """

    @pytest.mark.test_id("CODE-005")
    def test_file_tree_open_and_edit_tab(
        self,
        coding_page: CodingPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        project_name = f"e2e-coding-tree-{int(time.time())}"
        seed_filename = "hello.txt"

        log_test_step("1. Provision project + seed a file")
        created = coding_page.api_create_project(api_context, project_name)
        coding_page.api_activate_project(api_context, created["path"])
        coding_page.api_save_code_file(
            api_context,
            seed_filename,
            "hello world\n",
        )
        coding_page.api_set_coding_mode(api_context, True)

        try:
            log_test_step("2. Open IDE")
            coding_page.open_chat()
            coding_page.page.goto(
                coding_page.CODING_URL,
                wait_until="commit",
                timeout=coding_page.timeout,
            )
            coding_page.page.wait_for_url(
                "**/coding",
                timeout=coding_page.timeout,
            )
            assert coding_page.verify_ide_layout_visible(), (
                "IDE shell did not render"
            )

            log_test_step("3. Editor empty hint should be visible initially")
            empty_hint = coding_page.page.locator(
                coding_page.EDITOR_EMPTY_HINT
            )
            try:
                expect(empty_hint.first).to_be_visible(timeout=10000)
            except (AssertionError, Exception):
                # Some environments preload a tab from prior session;
                # don't hard-fail here — the click below is the real
                # assertion.
                logger.info("Editor empty hint not visible; continuing")

            log_test_step(
                f"4. Click '{seed_filename}' in the file tree"
            )
            tree_node = coding_page.page.locator(
                f'div[role="button"]:has(span:text-is("{seed_filename}"))'
            ).first
            expect(tree_node).to_be_visible(timeout=15000)
            tree_node.click()

            log_test_step("5. A tab matching the file name should open")
            tab = coding_page.page.locator(
                f'{coding_page.EDITOR_TAB}:has-text("{seed_filename}")'
            ).first
            expect(tab).to_be_visible(timeout=15000)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            coding_page.api_set_coding_mode(api_context, False)
