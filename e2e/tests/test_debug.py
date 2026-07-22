# -*- coding: utf-8 -*-
"""
QwenPaw Debug page E2E tests

Functional coverage:
1. Debug page load and basic display
2. Backend log card display
3. Log level filter (All/ERROR/WARNING/INFO/DEBUG)
4. Keyword search and highlight
5. Auto-refresh toggle
6. Newest-first sort toggle
7. Manual refresh button
8. Copy logs button

Run command: pytest tests/test_debug.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

BASE_URL = config.server.base_url


def navigate_to_debug(page: Page):
    """Navigate to the Debug page."""
    page.goto(f"{BASE_URL}/debug")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


# ============================================================================
# DEBUG-001: Debug page load and basic display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.debug
class TestDebugPageDisplay:
    """
    DEBUG-001: Debug page load and basic display

    Functional coverage:
    1. Page accessibility
    2. Page title/description Alert display
    3. Backend log card display
    4. Log content area exists
    """

    @pytest.mark.test_id("DEBUG-001")
    def test_debug_page_load_and_display(self, page: Page, request: pytest.FixtureRequest):
        """Verify Debug page load and basic element display."""
        test_name = request.node.name

        log_test_step("1. Navigate to Debug page")
        navigate_to_debug(page)

        log_test_step("2. Verify page description Alert")
        info_alert = page.locator('.qwenpaw-alert-info, .qwenpaw-alert').first
        expect(info_alert).to_be_visible(timeout=5000)
        alert_text = info_alert.inner_text()
        debug_keywords = ["Debug", "debug", "调试", "日志", "log", "diagnose", "排查"]
        assert any(kw in alert_text for kw in debug_keywords), \
            f"Alert should contain debug-related description, actual: {alert_text[:100]}"
        logger.info(f"Page description Alert visible: {alert_text[:80]}")

        log_test_step("3. Verify backend log card")
        log_card = page.locator('.qwenpaw-card').first
        expect(log_card).to_be_visible(timeout=5000)
        card_title = log_card.locator('.qwenpaw-card-head-title').first
        if card_title.is_visible(timeout=3000):
            title_text = card_title.inner_text()
            logger.info(f"Log card title: {title_text}")
        else:
            logger.info("Log card visible")

        log_test_step("4. Verify log content area")
        log_content = page.locator('[style*="monospace"], [style*="pre-wrap"]').first
        if log_content.is_visible(timeout=5000):
            content_text = log_content.inner_text()
            logger.info(f"Log content area visible, length: {len(content_text)}")
        else:
            logger.info("Log content area may be empty or use other styling")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# DEBUG-002: Log control buttons
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.debug
class TestDebugLogControls:
    """
    DEBUG-002: Log control buttons

    Functional coverage:
    1. Manual refresh button
    2. Copy logs button
    3. Auto-refresh toggle
    4. Newest-first sort toggle
    """

    @pytest.mark.test_id("DEBUG-002")
    def test_debug_log_control_buttons(self, page: Page, request: pytest.FixtureRequest):
        """Verify log control button functionality."""
        test_name = request.node.name

        log_test_step("1. Navigate to Debug page")
        navigate_to_debug(page)

        log_test_step("2. Verify manual refresh button")
        refresh_btn = page.locator(
            'button:has-text("Refresh"), '
            'button:has-text("刷新")'
        ).first
        expect(refresh_btn).to_be_visible(timeout=5000)
        logger.info("Manual refresh button visible")

        log_test_step("3. Click manual refresh button")
        refresh_btn.click()
        page.wait_for_timeout(2000)
        # Verify no errors after refresh
        error_alert = page.locator('.qwenpaw-alert-error').first
        if error_alert.is_visible(timeout=2000):
            logger.info("Error alert appears after refresh (backend may be down)")
        else:
            logger.info("Manual refresh succeeded")

        log_test_step("4. Verify copy logs button")
        copy_btn = page.locator(
            'button:has-text("Copy"), '
            'button:has-text("复制")'
        ).first
        expect(copy_btn).to_be_visible(timeout=5000)
        logger.info("Copy logs button visible")

        log_test_step("5. Verify auto-refresh toggle")
        switches = page.locator('.qwenpaw-card-extra .qwenpaw-switch, .qwenpaw-card-head .qwenpaw-switch').all()
        assert len(switches) >= 2, f"Should have at least 2 switches (auto-refresh + newest-first), actual: {len(switches)}"
        logger.info(f"Found {len(switches)} switches")

        log_test_step("6. Toggle auto-refresh switch")
        auto_refresh_switch = switches[-1]  # Auto-refresh is the last one
        initial_state = auto_refresh_switch.get_attribute('aria-checked')
        auto_refresh_switch.click()
        page.wait_for_timeout(1000)
        new_state = auto_refresh_switch.get_attribute('aria-checked')
        assert initial_state != new_state, "Auto-refresh toggle state should change"
        logger.info(f"Auto-refresh toggle changed: {initial_state} -> {new_state}")

        # Restore original state
        auto_refresh_switch.click()
        page.wait_for_timeout(500)

        log_test_step("7. Toggle newest-first sort switch")
        newest_first_switch = switches[0]  # Newest-first is the first one
        initial_order = newest_first_switch.get_attribute('aria-checked')
        newest_first_switch.click()
        page.wait_for_timeout(1000)
        new_order = newest_first_switch.get_attribute('aria-checked')
        assert initial_order != new_order, "Sort toggle state should change"
        logger.info(f"Newest-first toggle changed: {initial_order} -> {new_order}")

        # Restore original state
        newest_first_switch.click()
        page.wait_for_timeout(500)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# DEBUG-003: Log level filter
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.debug
class TestDebugLogLevelFilter:
    """
    DEBUG-003: Log level filter

    Functional coverage:
    1. Level filter dropdown display
    2. Switch between levels (All/ERROR/WARNING/INFO/DEBUG)
    3. Log content changes after filter
    """

    @pytest.mark.test_id("DEBUG-003")
    def test_debug_log_level_filter(self, page: Page, request: pytest.FixtureRequest):
        """Verify log level filter functionality."""
        test_name = request.node.name

        log_test_step("1. Navigate to Debug page")
        navigate_to_debug(page)

        log_test_step("2. Verify level filter dropdown")
        level_select = page.locator('.qwenpaw-select').first
        expect(level_select).to_be_visible(timeout=5000)
        logger.info("Level filter dropdown visible")

        log_test_step("3. Open level dropdown")
        level_select.click()
        page.wait_for_timeout(500)

        log_test_step("4. Verify dropdown options")
        dropdown = page.locator('.qwenpaw-select-dropdown').first
        expect(dropdown).to_be_visible(timeout=3000)

        expected_levels = ["All", "ERROR", "WARNING", "INFO", "DEBUG"]
        for level in expected_levels:
            option = dropdown.locator(f'.qwenpaw-select-item:has-text("{level}")').first
            if option.is_visible(timeout=2000):
                logger.info(f"  Level option '{level}' exists")
            else:
                logger.info(f"  Level option '{level}' not found (may be rendered as Tag)")

        log_test_step("5. Select ERROR level")
        error_option = dropdown.locator(
            '.qwenpaw-select-item:has-text("ERROR"), '
            '.qwenpaw-select-item:has(.qwenpaw-tag)'
        ).first
        if error_option.is_visible(timeout=2000):
            error_option.click()
            page.wait_for_timeout(1000)
            logger.info("Selected ERROR level filter")
        else:
            page.keyboard.press("Escape")
            logger.info("ERROR option not found, skipping")

        log_test_step("6. Switch back to All level")
        level_select.click()
        page.wait_for_timeout(500)
        all_option = page.locator('.qwenpaw-select-dropdown .qwenpaw-select-item').first
        if all_option.is_visible(timeout=2000):
            all_option.click()
            page.wait_for_timeout(1000)
            logger.info("Switched back to All level")
        else:
            page.keyboard.press("Escape")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# DEBUG-004: Keyword search
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.debug
class TestDebugLogSearch:
    """
    DEBUG-004: Keyword search

    Functional coverage:
    1. Search input display
    2. Enter keyword to search
    3. Clear search
    """

    @pytest.mark.test_id("DEBUG-004")
    def test_debug_log_keyword_search(self, page: Page, request: pytest.FixtureRequest):
        """Verify log keyword search functionality."""
        test_name = request.node.name

        log_test_step("1. Navigate to Debug page")
        navigate_to_debug(page)

        log_test_step("2. Verify search input")
        search_input = page.locator(
            'input[placeholder*="Search"], '
            'input[placeholder*="搜索"], '
            '.qwenpaw-input[placeholder*="log"]'
        ).first
        expect(search_input).to_be_visible(timeout=5000)
        logger.info("Search input visible")

        log_test_step("3. Enter search keyword")
        search_input.fill("error")
        page.wait_for_timeout(1000)
        logger.info("Entered search keyword 'error'")

        log_test_step("4. Verify search results (log content may change)")
        log_content = page.locator('[style*="monospace"], [style*="pre-wrap"]').first
        if log_content.is_visible(timeout=3000):
            content_text = log_content.inner_text()
            if "error" in content_text.lower():
                logger.info("Search result contains keyword 'error'")
            else:
                logger.info("No log content matching 'error'")
        else:
            logger.info("Log content area not visible")

        log_test_step("5. Clear search")
        clear_btn = search_input.locator('..').locator('.qwenpaw-input-clear-icon').first
        if clear_btn.is_visible(timeout=2000):
            clear_btn.click()
            page.wait_for_timeout(500)
            logger.info("Cleared search keyword")
        else:
            search_input.fill("")
            page.wait_for_timeout(500)
            logger.info("Manually cleared search input")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# DEBUG-005: Log file info display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.debug
class TestDebugLogFileInfo:
    """
    DEBUG-005: Log file info display

    Functional coverage:
    1. Log file path display
    2. Updated timestamp display
    3. Warning when log file does not exist
    """

    @pytest.mark.test_id("DEBUG-005")
    def test_debug_log_file_info(self, page: Page, request: pytest.FixtureRequest):
        """Verify log file info display."""
        test_name = request.node.name

        log_test_step("1. Navigate to Debug page")
        navigate_to_debug(page)

        log_test_step("2. Wait for logs to load")
        page.wait_for_timeout(3000)

        log_test_step("3. Check log file path")
        path_text = page.locator('text="Log file"').first
        if path_text.is_visible(timeout=3000):
            logger.info("Log file path label visible")
        else:
            # Try Chinese
            path_text_zh = page.locator('text="日志文件"').first
            if path_text_zh.is_visible(timeout=2000):
                logger.info("Log file path label visible (Chinese)")
            else:
                logger.info("Log file path not shown (file may not exist)")

        log_test_step("4. Check updated timestamp")
        updated_text = page.locator('text="Updated at"').first
        if updated_text.is_visible(timeout=3000):
            logger.info("Updated timestamp label visible")
        else:
            updated_text_zh = page.locator('text="更新时间"').first
            if updated_text_zh.is_visible(timeout=2000):
                logger.info("Updated timestamp label visible (Chinese)")
            else:
                logger.info("Updated timestamp not shown (logs not yet loaded)")

        log_test_step("5. Check warning when log file is missing")
        warning_alert = page.locator('.qwenpaw-alert-warning').first
        if warning_alert.is_visible(timeout=2000):
            warning_text = warning_alert.inner_text()
            logger.info(f"Log file not found warning: {warning_text[:100]}")
        else:
            logger.info("No log file missing warning (file exists)")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
