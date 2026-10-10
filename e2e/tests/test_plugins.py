# -*- coding: utf-8 -*-
"""
QwenPaw Plugin Manager end-to-end tests.

UI-driven only: any pure API/contract checks for the Plugin Manager
endpoints belong in ``tests/integration/`` (which already covers them).

Cases:
- PLUGIN-001 P0  test_plugin_manager_page_loads
- COMPAT-001 P1  test_market_compat_tags_render
- COMPAT-002 P1  test_incompatible_install_warning_modal
"""
from __future__ import annotations

import logging

import pytest
from playwright.sync_api import expect

from pages.plugin_page import PluginPage
from mocks import plugin_market
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


# ============================================================================
# PLUGIN-001 P0 — Plugin Manager page loads
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.plugins
class TestPluginManagerPageLoads:
    """PLUGIN-001: /plugin-manager renders header, install button, two tabs."""

    @pytest.mark.test_id("PLUGIN-001")
    def test_plugin_manager_page_loads(
        self,
        plugin_page: PluginPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Navigate to /plugin-manager")
        plugin_page.open()

        log_test_step("2. 'Install Plugin' button visible (page-ready signal)")
        expect(
            plugin_page.page.locator(plugin_page.INSTALL_BTN).first
        ).to_be_visible(timeout=plugin_page.timeout)

        log_test_step("3. 'Installed' and 'Official' tabs both visible")
        expect(
            plugin_page.page.locator(plugin_page.TAB_INSTALLED).first
        ).to_be_visible(timeout=plugin_page.timeout)
        expect(
            plugin_page.page.locator(plugin_page.TAB_OFFICIAL).first
        ).to_be_visible(timeout=plugin_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# COMPAT-001/002 P1 — Plugin Market version compatibility (upstream #5661)
#
# Market catalog data comes from the network (platform.agentscope.io
# proxy), so the catalog / version / install endpoints are intercepted
# with page.route mocks; all UI interactions and assertions stay real.
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.plugins
class TestPluginCompatibility:
    """Market tab compat tags + incompatible-install warning modal."""

    def _open_market_tab(self, plugin_page: PluginPage) -> None:
        """Register mocks, open the plugin market and switch to list view."""
        plugin_market.register(plugin_page.page)
        plugin_page.open()
        plugin_page.page.locator(plugin_page.TAB_MARKET).first.click()
        # The market defaults to card view; the catalog rows the assertions
        # rely on only render in list view.
        list_toggle = plugin_page.page.locator(
            '[aria-label*="List view"], [aria-label*="列表"]'
        ).first
        try:
            list_toggle.click(timeout=5000)
        except Exception:
            pass
        plugin_page.page.locator(plugin_page.MARKET_ROW).first.wait_for(
            state="visible", timeout=plugin_page.timeout
        )

    @pytest.mark.test_id("COMPAT-001")
    def test_market_compat_tags_render(
        self,
        plugin_page: PluginPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = plugin_page.page

        log_test_step("1. Open Market tab with mocked catalog (1 compat + 1 legacy)")
        self._open_market_tab(plugin_page)

        log_test_step("2. Compatible plugin row shows a green 'QwenPaw 2.x' tag")
        compat_row = page.locator(plugin_page.MARKET_ROW).filter(
            has_text=plugin_market.COMPATIBLE_PLUGIN_NAME
        ).first
        expect(compat_row).to_be_visible(timeout=plugin_page.timeout)
        green_tag = compat_row.locator(plugin_page.COMPAT_TAG_GREEN).first
        expect(green_tag).to_be_visible(timeout=plugin_page.timeout)
        assert "2.x" in (green_tag.inner_text() or ""), (
            f"green tag text unexpected: {green_tag.inner_text()!r}"
        )

        log_test_step("3. Incompatible plugin row shows an orange 'QwenPaw 1.x' tag")
        legacy_row = page.locator(plugin_page.MARKET_ROW).filter(
            has_text=plugin_market.INCOMPATIBLE_PLUGIN_NAME
        ).first
        expect(legacy_row).to_be_visible(timeout=plugin_page.timeout)
        orange_tag = legacy_row.locator(plugin_page.COMPAT_TAG_ORANGE).first
        expect(orange_tag).to_be_visible(timeout=plugin_page.timeout)
        assert "1.x" in (orange_tag.inner_text() or ""), (
            f"orange tag text unexpected: {orange_tag.inner_text()!r}"
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")

    @pytest.mark.test_id("COMPAT-002")
    def test_incompatible_install_warning_modal(
        self,
        plugin_page: PluginPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = plugin_page.page

        log_test_step("1. Open Market tab with mocked catalog")
        self._open_market_tab(plugin_page)

        log_test_step("2. Click Install on the incompatible plugin")
        legacy_row = page.locator(plugin_page.MARKET_ROW).filter(
            has_text=plugin_market.INCOMPATIBLE_PLUGIN_NAME
        ).first
        expect(legacy_row).to_be_visible(timeout=plugin_page.timeout)
        # Card view reveals the install action only on hover.
        legacy_row.hover()
        page.wait_for_timeout(300)
        legacy_row.locator(plugin_page.MARKET_INSTALL_BTN).first.click()

        log_test_step("3. 'Compatibility Warning' Modal.confirm appears")
        modal = page.locator(plugin_page.COMPAT_MODAL).first
        expect(modal).to_be_visible(timeout=plugin_page.timeout)
        expect(
            page.locator(plugin_page.COMPAT_MODAL_TITLE).first
        ).to_be_visible(timeout=plugin_page.timeout)

        log_test_step("4. Confirm 'Install anyway' — modal closes (install mocked)")
        page.locator(plugin_page.COMPAT_MODAL_OK).first.click()
        expect(modal).not_to_be_visible(timeout=plugin_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
