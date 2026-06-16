# -*- coding: utf-8 -*-
"""
QwenPaw Plugin Manager page object.

Wraps:
- Navigation to ``/plugin-manager``
- Tab and selector anchors for the installed / official plugin lists

API-only contract testing for /api/plugins/* endpoints lives in
``tests/integration/`` — this page object intentionally exposes only
UI-driven helpers.

Cases covered:
- PLUGIN-001 P0  test_plugin_manager_page_loads
"""
from __future__ import annotations

import logging

from playwright.sync_api import TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class PluginPage(BasePage):
    """Page object for the Plugin Manager (``/plugin-manager``)."""

    PAGE_URL = f"{config.base_url}/plugin-manager"

    # ========== Selectors (bilingual where copy is i18n-driven) ==========

    # PageHeader breadcrumb / title
    # Robust against zh/en + DOM variations: match on either an h1 or
    # the breadcrumbCurrent span, in either language.
    PAGE_TITLE_TEXT = (
        'h1:has-text("Plugin Manager"), '
        'h1:has-text("插件管理"), '
        '[class*="breadcrumbCurrent"]:has-text("Plugin Manager"), '
        '[class*="breadcrumbCurrent"]:has-text("插件管理")'
    )
    INSTALL_BTN = (
        'button:has-text("Install Plugin"), '
        'button:has-text("安装插件")'
    )
    TAB_INSTALLED = (
        '.qwenpaw-tabs-tab:has-text("Installed"), '
        '.qwenpaw-tabs-tab:has-text("已安装")'
    )
    TAB_OFFICIAL = (
        '.qwenpaw-tabs-tab:has-text("Official"), '
        '.qwenpaw-tabs-tab:has-text("官方")'
    )

    # Empty-state text inside the installed table
    EMPTY_INSTALLED = (
        'text=/(No plugins installed|暂无已安装插件)/'
    )

    # localStorage agent storage — see CodingPage for the rationale.
    AGENT_ID_DEFAULT = "default"

    # ========== Lifecycle ==========

    _init_script_installed = False

    def _install_default_agent_init_script(self) -> None:
        """Pin selectedAgent to ``default`` for every page in this context."""
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
            logger.info("Installed default-agent init script (plugins)")
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Could not install init script: %s", exc)

    def open(self, force_default_agent: bool = True) -> "PluginPage":
        """Navigate to the Plugin Manager page."""
        if force_default_agent:
            self._install_default_agent_init_script()
        logger.info("Open Plugin Manager page")
        self.page.goto(self.PAGE_URL, wait_until="commit", timeout=self.timeout)
        # Wait until SPA chunks have settled — the Plugin Manager page
        # is route-split, so domcontentloaded fires too early.
        try:
            self.page.wait_for_load_state(
                "networkidle",
                timeout=self.timeout,
            )
        except TimeoutError:
            logger.warning("networkidle wait timed out; continuing")
        return self
