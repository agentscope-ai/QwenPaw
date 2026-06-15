# -*- coding: utf-8 -*-
"""
QwenPaw Long-term Memory page object.

Wraps backend API helpers for daily memory file CRUD and the running
config (which holds ``reme_light_memory_config``), plus locator
anchors for the Long-term Memory card on /agent-config.

Cases covered:
- MEM-001 P0  test_daily_memory_crud
- MEM-002 P1  test_running_config_persistence
- MEM-003 P1  test_memory_card_ui_renders
- MEM-004 P1  test_workspace_memory_md_expand
- MEM-005 P2  test_memory_search_recall_seeded         (xfail, requires_llm)
- MEM-006 P2  test_daily_memory_path_traversal_blocked
"""
from __future__ import annotations

import logging
from typing import Optional

from playwright.sync_api import Page, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class MemoryPage(BasePage):
    """Page object for Long-term Memory."""

    AGENT_CONFIG_URL = f"{config.base_url}/agent-config"
    WORKSPACE_URL = f"{config.base_url}/workspace"

    # ========== Selectors ==========

    # Long-term Memory tab on /agent-config
    MEMORY_TAB = (
        '.qwenpaw-tabs-tab:has-text("Long-term Memory"), '
        '.qwenpaw-tabs-tab:has-text("长期记忆")'
    )
    # Switches and inputs use stable form-item names (Form.Item name=[...]).
    # The dream_cron input is unique to this card and serves as a
    # reliable "card content rendered" signal.
    DREAM_CRON_INPUT = (
        'input[id$="reme_light_memory_config_dream_cron"]'
    )
    SUMMARIZE_SWITCH = (
        'button[role="switch"][id$="reme_light_memory_config_summarize_when_compact"]'
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

    # ========== API helpers ==========

    def _agent_headers(self) -> dict:
        return {"X-Agent-Id": self.AGENT_ID_DEFAULT}

    def api_list_daily_memory(self, api_context) -> list:
        """GET /api/workspace/memory."""
        resp = api_context.get(
            "/api/workspace/memory",
            headers=self._agent_headers(),
        )
        assert resp.ok, (
            f"List memory failed [{resp.status}]: {resp.text()}"
        )
        body = resp.json()
        if isinstance(body, list):
            return body
        return body.get("files", []) if isinstance(body, dict) else []

    def api_read_daily_memory(self, api_context, name: str) -> str:
        """GET /api/workspace/memory/{name}."""
        resp = api_context.get(
            f"/api/workspace/memory/{name}",
            headers=self._agent_headers(),
        )
        assert resp.ok, (
            f"Read memory failed [{resp.status}]: {resp.text()}"
        )
        body = resp.json()
        return body.get("content", "")

    def api_write_daily_memory(
        self, api_context, name: str, content: str,
    ) -> dict:
        """PUT /api/workspace/memory/{name}."""
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
        resp = api_context.get(
            "/api/workspace/running-config",
            headers=self._agent_headers(),
        )
        assert resp.ok, (
            f"Get running-config failed [{resp.status}]: {resp.text()}"
        )
        return resp.json()

    def api_put_running_config(self, api_context, payload: dict) -> dict:
        resp = api_context.put(
            "/api/workspace/running-config",
            data=payload,
            headers=self._agent_headers(),
        )
        assert resp.ok, (
            f"PUT running-config failed [{resp.status}]: {resp.text()}"
        )
        return resp.json()
