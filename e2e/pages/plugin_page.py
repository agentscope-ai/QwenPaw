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
- COMPAT-001 P1  test_market_compat_tags_render
- COMPAT-002 P1  test_incompatible_install_warning_modal
"""
from __future__ import annotations

import logging

from playwright.sync_api import TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class PluginPage(BasePage):
    """Page object for the Plugin Manager (``/plugin-manager``)."""

    PAGE_URL = f"{config.base_url}/market?tab=plugins"

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
    TAB_MARKET = (
        '.qwenpaw-tabs-tab:has-text("Plugin Market"), '
        '.qwenpaw-tabs-tab:has-text("插件市场")'
    )

    # ----- Plugin Market compatibility (upstream #5661) -----
    # Catalog rows share CSS-module classes with the Official list
    # (OfficialPluginList.module.less), matched by basename substring.
    #
    # Pane scope is mandatory, not cosmetic: all three Plugin Manager tabs
    # (Installed / Official / Market) render cards/rows with the SAME
    # CSS-module classes (InstalledPluginList and OfficialPluginList import
    # MarketPluginList.module.less), and antd Tabs keep inactive panes in
    # the DOM (display:none; no destroyInactiveTabPane is configured). A
    # global ``.first`` therefore resolves to the FIRST pane in DOM order
    # (Installed). Before #8128 that pane was empty and the miss was
    # harmless; #8128 seeds four built-in hub plugins into it, so the
    # hidden ``<article aria-label="ModelScope Hub" ...>`` now shadows the
    # Market rows forever (nightly 2026-10-13/14: "123 x locator resolved
    # to hidden"). Scope every Market selector to the active tab pane.
    MARKET_TABPANE = '.qwenpaw-tabs-tabpane-active'
    MARKET_ROW = (
        '.qwenpaw-tabs-tabpane-active [class*="catalogRow"], '
        '.qwenpaw-tabs-tabpane-active article[class*="pluginCard"]'
    )
    # The card/list view toggle (PluginViewToggle) is rendered once PER
    # pane with identical aria-labels in all three lists, so it needs the
    # same pane scope: the unscoped variant clicked the HIDDEN Installed
    # pane's toggle, the click raised, and a bare ``except: pass`` swallowed
    # it -- leaving the Market pane in card view where catalogRow never
    # renders (failure screenshot 2026-10-14 shows the Market tab active
    # with both mocked cards still in card view).
    MARKET_LIST_TOGGLE = (
        '.qwenpaw-tabs-tabpane-active span[aria-label*="List view"], '
        '.qwenpaw-tabs-tabpane-active span[aria-label*="列表"]'
    )
    # antd Tag with prefixCls=qwenpaw; text is "QwenPaw <labels>"
    COMPAT_TAG_GREEN = '.qwenpaw-tag-green:has-text("QwenPaw")'
    COMPAT_TAG_ORANGE = '.qwenpaw-tag-orange:has-text("QwenPaw")'
    MARKET_INSTALL_BTN = (
        '[class*="catalogActions"] button:has-text("Install"), '
        '[class*="catalogActions"] button:has-text("安装"), '
        '[class*="cardActions"] button:has-text("Install"), '
        '[class*="cardActions"] button:has-text("安装")'
    )
    # Modal.confirm for incompatible installs
    COMPAT_MODAL = '.qwenpaw-modal-confirm'
    COMPAT_MODAL_TITLE = (
        '.qwenpaw-modal-confirm-title:has-text("Compatibility Warning"), '
        '.qwenpaw-modal-confirm-title:has-text("兼容性警告")'
    )
    COMPAT_MODAL_OK = (
        '.qwenpaw-modal-confirm-btns button:has-text("Install anyway"), '
        '.qwenpaw-modal-confirm-btns button:has-text("仍然安装")'
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
