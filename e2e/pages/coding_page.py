# -*- coding: utf-8 -*-
"""
QwenPaw Coding Mode page object.

Wraps the Coding Mode entry / exit toggle and the project-select modal.
Designed for the two P0 cases:

- CODE-001 ``test_enter_and_exit_coding_mode``
- CODE-002 ``test_create_empty_project_and_open``

Notes
-----
- The browser context locale is ``en-US`` (see ``fixtures/__init__.py``),
  so we anchor on English UI copy from ``console/src/locales/en.json``.
- First-time activation triggers an "Experimental Feature" confirmation
  modal gated by ``localStorage["qwenpaw-coding-mode-confirmed"]``. To
  keep tests deterministic we always pre-set that key before toggling.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from playwright.sync_api import Page, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class CodingPage(BasePage):
    """Page object for QwenPaw Coding Mode."""

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/chat"
    CODING_URL = f"{config.base_url}/coding"

    # ========== Selectors ==========

    # Toggle button — aria-label is i18n driven. The browser context is
    # forced to ``en-US`` in fixtures, but the QwenPaw frontend keeps a
    # user-preference language that overrides locale, so both Chinese and
    # English copy show up in real envs. Match either.
    TOGGLE_ENTER = (
        'button[aria-label="Enter Coding Mode"], '
        'button[aria-label="进入编程模式"]'
    )
    TOGGLE_EXIT = (
        'button[aria-label="Exit Coding Mode"], '
        'button[aria-label="退出编程模式"]'
    )

    # Experimental confirmation modal (first activation only)
    EXPERIMENTAL_MODAL_TITLE = (
        '.ant-modal-title:has-text("Experimental Feature"), '
        '.ant-modal-title:has-text("实验性功能")'
    )
    EXPERIMENTAL_CONFIRM_BTN = (
        '.ant-modal-footer button.ant-btn-primary:has-text("Confirm"), '
        '.ant-modal-footer button.ant-btn-primary:has-text("确认")'
    )

    # Project select modal
    PROJECT_MODAL_TITLE = (
        '.ant-modal-title:has-text("Select Coding Project"), '
        '.ant-modal-title:has-text("选择编程项目")'
    )
    PROJECT_TAB_NEW = (
        '.ant-tabs-tab:has-text("New Project"), '
        '.ant-tabs-tab:has-text("新建项目")'
    )
    PROJECT_NEW_NAME_INPUT = '.ant-modal-content input.ant-input'
    PROJECT_NEW_CREATE_BTN = (
        '.ant-modal-content button.ant-btn-primary:has-text("Create Project"), '
        '.ant-modal-content button.ant-btn-primary:has-text("创建项目")'
    )
    PROJECT_MODAL_CLOSE = '.ant-modal-close'

    # Coding Mode IDE shell — class names are CSS Modules hashed, so we
    # anchor on the always-present "Chat" header (also bilingual).
    IDE_CHAT_HEADER_TEXT = 'text=/^(Chat|聊天)$/'
    IDE_TOOLTIP_EXPLORER = '[role="tooltip"]:has-text("Explorer")'

    # localStorage key used by the toggle to remember the confirm dialog.
    LS_KEY_CONFIRMED = "qwenpaw-coding-mode-confirmed"

    # Agent identity helpers — see ``console/src/stores/agentStore.ts``.
    # The frontend remembers the last-used agent across browser sessions
    # via ``qwenpaw-last-used-agent`` (localStorage) and the persisted
    # zustand state under ``qwenpaw-agent-storage`` (both local and
    # session). On a developer machine these can carry an unrelated
    # agent (e.g. ``cloud-orchestrator``) into the e2e browser context,
    # which then disagrees with our API calls that use ``default``.
    AGENT_ID_DEFAULT = "default"

    # ========== Lifecycle ==========

    def open_chat(self, force_default_agent: bool = True) -> "CodingPage":
        """Navigate to /chat where the Coding Mode toggle lives.

        Args:
            force_default_agent: When True (default), inject a context
                init-script that pins ``selectedAgent`` to ``"default"``
                in every page of the context, so the chat page renders
                bound to the agent our backend API calls target.
        """
        if force_default_agent:
            self._install_default_agent_init_script()
        logger.info("Open chat page (Coding toggle host)")
        self.page.goto(self.PAGE_URL, wait_until="commit", timeout=self.timeout)
        self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout)
        return self

    _init_script_installed = False

    def _install_default_agent_init_script(self) -> None:
        """Install a context-wide init script that pins selectedAgent.

        zustand's ``persist`` middleware re-hydrates from storage on
        every fresh document load. To pin the agent to ``default`` we
        register an init-script (runs *before* any page script) that
        rewrites both the legacy ``qwenpaw-last-used-agent`` key and the
        persisted ``qwenpaw-agent-storage`` blob in localStorage and
        sessionStorage. The script is idempotent and installed once per
        Page instance.
        """
        if self._init_script_installed:
            return
        agent = self.AGENT_ID_DEFAULT
        script = (
            "(() => {"
            "  try {"
            f"    const a = '{agent}';"
            "    const blob = JSON.stringify({"
            "      state: { selectedAgent: a, agents: [], lastChatIdByAgent: {} },"
            "      version: 0"
            "    });"
            "    try { localStorage.setItem('qwenpaw-last-used-agent', a); } catch (e) {}"
            "    try { localStorage.setItem('qwenpaw-agent-storage', blob); } catch (e) {}"
            "    try { sessionStorage.setItem('qwenpaw-agent-storage', blob); } catch (e) {}"
            "  } catch (e) {}"
            "})();"
        )
        try:
            self.page.context.add_init_script(script=script)
            self._init_script_installed = True
            logger.info("Installed default-agent init script")
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Could not install init script: %s", exc)

    def force_default_agent(self) -> None:
        """Backwards-compatible no-op wrapper kept for direct callers.

        New code should rely on :meth:`open_chat` which installs the
        init-script automatically.
        """
        self._install_default_agent_init_script()

    def prime_experimental_confirmed(self) -> None:
        """Pre-set the localStorage flag so the experimental modal is skipped.

        Must be called *after* navigation (localStorage is per-origin and
        only addressable once a document is loaded).
        """
        try:
            self.page.evaluate(
                "key => window.localStorage.setItem(key, '1')",
                self.LS_KEY_CONFIRMED,
            )
            logger.info("Primed localStorage[%s]=1", self.LS_KEY_CONFIRMED)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Could not prime localStorage: %s", exc)

    # ========== Toggle ==========

    def is_in_coding_mode(self) -> bool:
        """Return True iff the URL is currently on /coding."""
        return "/coding" in self.page.url

    def click_enter_toggle(self) -> None:
        """Click the "Code" button to start entering Coding Mode."""
        logger.info("Click 'Enter Coding Mode' toggle")
        self.page.locator(self.TOGGLE_ENTER).first.click(timeout=self.timeout)

    def click_exit_toggle(self) -> None:
        """Click the "Chat" button to leave Coding Mode."""
        logger.info("Click 'Exit Coding Mode' toggle")
        self.page.locator(self.TOGGLE_EXIT).first.click(timeout=self.timeout)

    # ========== Project select modal ==========

    def wait_for_project_modal(self) -> None:
        """Wait until the project-select modal is visible."""
        expect(self.page.locator(self.PROJECT_MODAL_TITLE)).to_be_visible(
            timeout=self.timeout,
        )

    def open_new_project_tab(self) -> None:
        """Switch the project-select modal to the 'New Project' tab."""
        logger.info("Switch project modal to 'New Project' tab")
        self.page.locator(self.PROJECT_TAB_NEW).first.click(timeout=self.timeout)

    def fill_new_project_name(self, name: str) -> None:
        """Type a project name into the 'New Project' tab."""
        logger.info("Fill new project name: %s", name)
        # Each tab has its own input mounted; using .last is fragile when
        # the tab order changes. The 'New Project' tab is currently the
        # last entry (workspace / clone / opendir / local / new), but
        # filtering by visibility is more robust.
        inputs = self.page.locator(self.PROJECT_NEW_NAME_INPUT)
        target = None
        for i in range(inputs.count()):
            cand = inputs.nth(i)
            if cand.is_visible():
                target = cand
                break
        if target is None:
            raise AssertionError("No visible project name input found")
        target.fill(name)

    def click_create_project(self) -> None:
        """Click the 'Create Project' submit button."""
        logger.info("Click 'Create Project'")
        self.page.locator(self.PROJECT_NEW_CREATE_BTN).first.click(
            timeout=self.timeout,
        )

    def close_project_modal_if_open(self) -> None:
        """Close the project-select modal if it is currently visible."""
        close_btn = self.page.locator(self.PROJECT_MODAL_CLOSE).first
        try:
            if close_btn.is_visible(timeout=2000):
                close_btn.click()
        except TimeoutError:
            pass

    # ========== High-level flows ==========

    def enter_coding_mode_with_workspace_default(
        self,
        timeout_ms: Optional[int] = None,
    ) -> None:
        """Enter Coding Mode using the default workspace project.

        Skips both the experimental warning (via localStorage prime) and
        the project-select modal (by dismissing it, which the toggle
        treats as 'use workspace default' per the toggle source).
        """
        timeout = timeout_ms or self.timeout

        if self.is_in_coding_mode():
            logger.info("Already in Coding Mode; nothing to do")
            return

        self.prime_experimental_confirmed()
        self.click_enter_toggle()

        # If the project-select modal pops up (project_dir undefined),
        # close it — the toggle then activates with workspace default.
        try:
            self.page.locator(self.PROJECT_MODAL_TITLE).wait_for(
                state="visible",
                timeout=3000,
            )
            self.close_project_modal_if_open()
        except TimeoutError:
            # No modal — already activated directly.
            pass

        self.page.wait_for_url("**/coding", timeout=timeout)

    def exit_coding_mode(self, timeout_ms: Optional[int] = None) -> None:
        """Exit Coding Mode and wait until we're back on /chat."""
        timeout = timeout_ms or self.timeout
        if not self.is_in_coding_mode():
            logger.info("Not in Coding Mode; nothing to do")
            return
        self.click_exit_toggle()
        self.page.wait_for_url("**/chat", timeout=timeout)

    def create_empty_project_and_enter(
        self,
        name: str,
        timeout_ms: Optional[int] = None,
    ) -> None:
        """Create a brand-new empty project from the toggle modal and enter.

        Steps:
            1. Prime localStorage to skip experimental warning.
            2. Click toggle.
            3. Wait for project modal, switch to 'New Project' tab.
            4. Fill name + click Create Project.
            5. Wait for /coding URL.
        """
        timeout = timeout_ms or self.timeout

        if self.is_in_coding_mode():
            self.exit_coding_mode(timeout_ms=timeout)

        self.prime_experimental_confirmed()
        self.click_enter_toggle()
        self.wait_for_project_modal()
        self.open_new_project_tab()
        self.fill_new_project_name(name)
        self.click_create_project()
        self.page.wait_for_url("**/coding", timeout=timeout)

    # ========== Assertions ==========

    def verify_ide_layout_visible(self) -> bool:
        """Soft-check that the IDE three-column layout has rendered.

        We look for the always-on "Chat" panel header. Returns True on
        match within ~5s, False otherwise.
        """
        try:
            expect(self.page.locator(self.IDE_CHAT_HEADER_TEXT).first).to_be_visible(
                timeout=5000,
            )
            return True
        except (TimeoutError, AssertionError):
            return False
