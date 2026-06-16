# -*- coding: utf-8 -*-
"""
QwenPaw Plugin Manager end-to-end tests.

UI-driven only: any pure API/contract checks for the Plugin Manager
endpoints belong in ``tests/integration/`` (which already covers them).

Cases:
- PLUGIN-001 P0  test_plugin_manager_page_loads
"""
from __future__ import annotations

import logging

import pytest
from playwright.sync_api import expect

from pages.plugin_page import PluginPage
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
