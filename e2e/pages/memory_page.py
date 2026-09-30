# -*- coding: utf-8 -*-
"""
QwenPaw Long-term Memory page object.

Wraps backend API helpers for daily memory file CRUD and the running
config (which holds ``reme_light_memory_config``), plus locator
anchors for the Long-term Memory card on /agent-config.

Cases covered:
- MEM-001 P1  test_auto_memory_interval_persistence
- MEM-002 P1  test_dream_cron_persistence
- MEM-003 P1  test_memory_card_ui_renders
- MEM-004 P1  test_workspace_memory_md_expand
- MEM-005 P2  test_memory_search_recall_seeded         (xfail, requires_llm)
- MEM-007 P2  test_auto_memory_search_toggle_and_max_results
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class MemoryPage(BasePage):
    """Page object for Long-term Memory."""

    AGENT_CONFIG_URL = f"{config.base_url}/agent-config"
    WORKSPACE_URL = f"{config.base_url}/files"

    # ========== Selectors ==========

    # Memory group tab rendered by RuntimeWorkbench on /agent-config.
    MEMORY_TAB = (
        '[role="tab"]:has-text("Memory"), '
        '[role="tab"]:has-text("记忆与检索")'
    )
    MEMORY_CARD_HEADING = (
        'h3:has-text("Long-term memory hub"), '
        'h3:has-text("长期记忆中心")'
    )
    DREAM_CRON_INPUT = (
        'section[class*="memoryConfigPanel"]:'
        'has-text("Dream Schedule") '
        'input[aria-label="Cron expression"], '
        'section[class*="memoryConfigPanel"]:'
        'has-text("梦境定时") input[aria-label="Cron 表达式"]'
    )
    AUTO_MEMORY_INTERVAL_INPUT = (
        'section[class*="memoryConfigPanel"]:'
        'has(h3:has-text("Auto-memory")) input[role="spinbutton"], '
        'section[class*="memoryConfigPanel"]:'
        'has(h3:has-text("自动记忆")) input[role="spinbutton"]'
    )
    DREAM_CRON_ENABLED_SWITCH = (
        'section[class*="memoryConfigPanel"]:'
        'has-text("Dream Schedule") button[role="switch"], '
        'section[class*="memoryConfigPanel"]:'
        'has-text("梦境定时") button[role="switch"]'
    )
    DREAM_ADVANCED_OPTION = (
        'section[class*="memoryConfigPanel"]:'
        'has-text("Dream Schedule") label:has-text("Advanced"), '
        'section[class*="memoryConfigPanel"]:'
        'has-text("梦境定时") label:has-text("高级")'
    )
    AUTO_SEARCH_SWITCH = (
        'section[class*="memoryRecallPanel"]:'
        'has(h3:has-text("Memory search")) '
        'div[class*="memoryToggleRow"]:'
        'has(strong:has-text("Enable automatic memory search")) '
        'button[role="switch"], '
        'section[class*="memoryRecallPanel"]:'
        'has(h3:has-text("记忆搜索")) '
        'div[class*="memoryToggleRow"]:'
        'has(strong:has-text("启用自动记忆搜索")) '
        'button[role="switch"]'
    )
    AUTO_SEARCH_MAX_RESULTS_INPUT = (
        'section[class*="memoryRecallPanel"]:'
        'has(h3:has-text("Memory search")) input[role="spinbutton"], '
        'section[class*="memoryRecallPanel"]:'
        'has(h3:has-text("记忆搜索")) input[role="spinbutton"]'
    )

    # localStorage agent storage — see CodingPage for the rationale.
    AGENT_ID_DEFAULT = "default"

    _init_script_installed = False

    # ========== Lifecycle ==========

    def _install_default_agent_init_script(self) -> None:
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
            logger.info("Installed default-agent init script (memory)")
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not install init script: %s", exc)

    def open_agent_config(self) -> "MemoryPage":
        self._install_default_agent_init_script()
        self.page.goto(
            self.AGENT_CONFIG_URL,
            wait_until="commit",
            timeout=self.timeout,
        )
        try:
            self.page.wait_for_load_state(
                "networkidle", timeout=self.timeout
            )
        except TimeoutError:
            pass
        return self

    def open_workspace(self) -> "MemoryPage":
        self._install_default_agent_init_script()
        self.page.goto(
            self.WORKSPACE_URL,
            wait_until="commit",
            timeout=self.timeout,
        )
        try:
            self.page.wait_for_load_state(
                "networkidle", timeout=self.timeout
            )
        except TimeoutError:
            pass
        return self

    def click_memory_tab(self) -> None:
        self.page.locator(self.MEMORY_TAB).first.click(timeout=self.timeout)

    def wait_for_config_value(
        self,
        api_context,
        path: tuple[str, ...],
        expected,
    ) -> None:
        """Wait until the debounced auto-save persists one config value."""
        deadline = time.monotonic() + self.timeout / 1000
        actual = None
        while time.monotonic() < deadline:
            value = self.api_get_running_config(api_context)
            try:
                for key in path:
                    value = value[key]
                actual = value
            except (KeyError, TypeError):
                actual = None
            if actual == expected:
                return
            self.page.wait_for_timeout(250)
        raise AssertionError(
            f"Config {'.'.join(path)} was not auto-saved: "
            f"expected {expected!r}, got {actual!r}"
        )

    # ========== API helpers (UI test setup only) ==========
    #
    # Pure API contract tests for /api/workspace/memory live in
    # ``tests/integration/``; this page object only exposes the helper
    # used to seed memory state for UI-driven cases.

    def _agent_headers(self) -> dict:
        return {"X-Agent-Id": self.AGENT_ID_DEFAULT}

    def api_write_daily_memory(
        self, api_context, name: str, content: str,
    ) -> dict:
        """PUT /api/workspace/memory/{name} — used as test setup."""
        resp = api_context.put(
            f"/api/workspace/memory/{name}",
            data={"content": content},
            headers=self._agent_headers(),
        )
        assert resp.ok, (
            f"Write memory failed [{resp.status}]: {resp.text()}"
        )
        return resp.json()

    def api_get_running_config(self, api_context) -> dict:
        """GET /api/workspace/running-config — snapshot for restore."""
        resp = api_context.get(
            "/api/workspace/running-config",
            headers=self._agent_headers(),
        )
        assert resp.ok, (
            f"Get running config failed [{resp.status}]: {resp.text()}"
        )
        return resp.json()

    def api_put_running_config(self, api_context, cfg: dict) -> None:
        """PUT /api/workspace/running-config — restore snapshot.

        Best-effort teardown helper: partial PUTs are unsupported, so
        callers must pass the full config object captured beforehand.
        """
        try:
            resp = api_context.put(
                "/api/workspace/running-config",
                data=cfg,
                headers=self._agent_headers(),
            )
            if not resp.ok:
                logger.warning(
                    "Restore running config failed [%s]: %s",
                    resp.status,
                    resp.text(),
                )
        except Exception as exc:  # pragma: no cover — teardown only
            logger.warning("Restore running config errored: %s", exc)
