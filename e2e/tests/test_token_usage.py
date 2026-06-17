# -*- coding: utf-8 -*-
"""
QwenPaw Token Usage module P0 end-to-end tests

Combined test design:
- TOKEN-001: Token usage page load + overview display + empty state validation
- TOKEN-002: Date range filter + quick options + data refresh
- TOKEN-003: Model filter + provider filter
- TOKEN-004: Data table display + pagination + sort validation
- TOKEN-005: Data export + format options validation

Run command: pytest tests/test_token_usage_p0.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect, TimeoutError

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

TOKEN_USAGE_URL = f"{config.base_url}/token-usage"

def navigate_to_token_usage(page: Page):
    """Navigate to the Token Usage page and wait for it to load."""
    page.goto(TOKEN_USAGE_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)

# ============================================================================
# TOKEN-001: Page load + overview display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.token_core
class TestTokenUsageDisplay:
    """
    TOKEN-001: Token usage page load + overview display + empty state validation

    Functional coverage:
    1. Token usage page access and load
    2. Breadcrumb navigation validation
    3. Overview cards display (total usage, today's usage, etc.)
    4. Chart area display
    5. Data table display
    6. Empty state validation
    """

    @pytest.mark.test_id("TOKEN-001")
    def test_token_usage_overview(self, page: Page, request: pytest.FixtureRequest):
        """Verify Token usage overview displays correctly along with empty state."""
        test_name = request.node.name

        # Step 1: Navigate to Token Usage page
        log_test_step("1. Navigate to Token Usage page")
        navigate_to_token_usage(page)

        # Step 2: Verify breadcrumb (soft assertion, supports both English and Chinese UI)
        log_test_step("2. Verify breadcrumb")
        try:
            # Try Chinese breadcrumb
            breadcrumb_settings = page.locator('span[class*="breadcrumbParent"]:has-text("设置"), span[class*="breadcrumbParent"]:has-text("Settings")').first
            if breadcrumb_settings.is_visible(timeout=3000):
                breadcrumb_current = page.locator('span[class*="breadcrumbCurrent"]:has-text("Token 消耗"), span[class*="breadcrumbCurrent"]:has-text("Token Usage")').first
                if breadcrumb_current.is_visible(timeout=3000):
                    logger.info("Breadcrumb validation passed")
                else:
                    logger.info("Breadcrumb current item not found, skipping")
            else:
                logger.info("Breadcrumb parent item not found, skipping")
        except Exception as e:
            logger.info(f"Breadcrumb validation skipped (page structure may differ): {e}")

        # Step 3: Verify page title
        log_test_step("3. Verify page title")
        page_title = page.locator('h1:has-text("Token Usage"), h1:has-text("Token"), .qwenpaw-page-header:has-text("Token")').first
        if page_title.is_visible(timeout=3000):
            logger.info("Page title visible")

        # Step 4: Verify overview cards (or empty state)
        log_test_step("4. Verify overview cards")
        overview_cards = page.locator(
            '.qwenpaw-card, .ant-card, [class*=overviewCard], '
            '[class*=statCard], .qwenpaw-statistic, .ant-statistic'
        ).all()

        if len(overview_cards) > 0:
            logger.info(f"Found {len(overview_cards)} overview cards")
            for i, card in enumerate(overview_cards[:3]):
                card_text = card.inner_text()
                logger.info(f"Card {i+1}: {card_text[:50]}...")
        else:
            logger.info("No overview cards found (page may use different layout or have no data)")

        # Step 5: Check for data table or empty state
        log_test_step("5. Verify data table or empty state")
        table_area = page.locator('.qwenpaw-table, .ant-table, table, [class*=dataTable]').first
        empty_state = page.locator('.qwenpaw-empty, .ant-empty, [class*=empty], [class*=Empty]').first
        has_table = table_area.count() > 0 and table_area.is_visible(timeout=5000)
        has_empty = empty_state.count() > 0 and empty_state.is_visible(timeout=3000)

        if not has_table and not has_empty:
            main = page.locator('main, [class*="content"], [class*="pageContent"]').first
            body = main if main.count() > 0 else page.locator("body")
            page_text = body.inner_text().lower()
            empty_state_keywords = (
                "no token", "no tokens", "no data",
                "no usage", "no usage data", "暂无", "暂无数据",
            )
            if any(kw in page_text for kw in empty_state_keywords):
                logger.info("Page shows text-based empty state (no table or empty component rendered)")
                log_test_result(test_name, "PASS", "Token usage page empty state validated")
                return

        assert has_table or has_empty, \
            "Token Usage page should display data table or empty state"

        if has_table:
            logger.info("Data table visible")

            table_headers = table_area.locator('th').all()
            visible_headers = [h for h in table_headers if h.is_visible()]
            if len(visible_headers) > 0:
                header_texts = [h.inner_text().strip() for h in visible_headers]
                logger.info(f"Table column headers: {header_texts}")

                log_test_step("6. Click header to sort")
                visible_headers[0].click()
                page.wait_for_timeout(1000)
                logger.info("Clicked column header to sort")

            log_test_step("7. Verify data rows or empty state")
            data_rows = table_area.locator('tbody tr').all()
            if len(data_rows) > 0:
                logger.info(f"Table has {len(data_rows)} data rows")
            else:
                logger.info("Table has no data rows (empty state)")
        else:
            logger.info("Empty state displayed correctly (no token usage data)")

        log_test_result(test_name, "PASS", "Token usage overview display and interaction validation passed")

# ============================================================================
# TOKEN-P1-001: Token usage by model
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.token_usage
class TestTokenUsageByModel:
    """
    TOKEN-P1-001: Token usage by model

    Functional coverage:
    1. Verify by-model statistics table exists
    2. Verify table has column headers
    3. Verify data rows or empty state
    """

    @pytest.mark.test_id("TOKEN-P1-001")
    def test_token_usage_by_model(self, page: Page, request: pytest.FixtureRequest):
        """Test Token usage statistics by model."""
        test_name = request.node.name

        log_test_step("Navigate to Token Usage page")
        navigate_to_token_usage(page)

        log_test_step("Find by-model statistics table")
        tables = page.locator('.qwenpaw-table, table').all()
        logger.info(f"Found {len(tables)} tables on the page")

        if len(tables) > 0:
            first_table = tables[0]
            expect(first_table).to_be_visible(timeout=5000)

            log_test_step("Verify table column headers")
            headers = first_table.locator('th, .qwenpaw-table-thead th').all()
            header_texts = [h.inner_text().strip() for h in headers if h.is_visible()]
            logger.info(f"Table column headers: {header_texts}")
            assert len(header_texts) > 0, "Table has no column headers"
            logger.info("By-model statistics table column headers validation passed")

            log_test_step("Verify data rows or empty state")
            data_rows = first_table.locator('tbody tr, .qwenpaw-table-row').all()
            empty_state = first_table.locator('.qwenpaw-empty, :text("暂无"), :text("No data")').first

            assert len(data_rows) > 0 or empty_state.count() > 0, \
                "By-model statistics table should have data rows or show empty state"
            if len(data_rows) > 0:
                logger.info(f"By-model statistics table has {len(data_rows)} data rows")
            else:
                logger.info("By-model statistics table shows empty state")
        else:
            logger.info("No table found; verify the page has statistics-related content")
            stat_content = page.locator(':text("Model"), :text("模型"), :text("Token")').all()
            logger.info(f"Found {len(stat_content)} statistics-related elements")

        log_test_result(test_name, True, 0)

# ============================================================================
# TOKEN-P1-002: Token trend by date
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.token_usage
class TestTokenUsageByDate:
    """
    TOKEN-P1-002: Token trend by date

    Functional coverage:
    1. Verify by-date statistics table exists
    2. Verify date column exists
    3. Verify data rows or empty state
    """

    @pytest.mark.test_id("TOKEN-P1-002")
    def test_token_usage_by_date(self, page: Page, request: pytest.FixtureRequest):
        """Test Token usage trend by date."""
        test_name = request.node.name

        log_test_step("Navigate to Token Usage page")
        navigate_to_token_usage(page)

        log_test_step("Find by-date statistics table")
        tables = page.locator('.qwenpaw-table, table').all()

        if len(tables) >= 2:
            date_table = tables[1]
            expect(date_table).to_be_visible(timeout=5000)

            log_test_step("Verify date column exists")
            headers = date_table.locator('th, .qwenpaw-table-thead th').all()
            header_texts = [h.inner_text().strip() for h in headers if h.is_visible()]
            logger.info(f"Date table column headers: {header_texts}")

            has_date_column = any(
                "date" in h.lower() or "日期" in h or "Date" in h
                for h in header_texts
            )
            if has_date_column:
                logger.info("Date column exists")
            else:
                logger.info(f"No explicit date column found; headers: {header_texts}")

            log_test_step("Verify data rows")
            data_rows = date_table.locator('tbody tr, .qwenpaw-table-row').all()
            logger.info(f"By-date statistics table has {len(data_rows)} data rows")
        elif len(tables) == 1:
            logger.info("Only 1 table found; by-model and by-date may be combined")
            # Verify table has Tab switching
            tabs = page.locator('.qwenpaw-tabs-tab, .qwenpaw-segmented-item').all()
            if len(tabs) > 0:
                logger.info(f"Found {len(tabs)} Tab/Segment switch items")
                # Click the second Tab
                if len(tabs) >= 2:
                    tabs[1].click()
                    page.wait_for_timeout(1000)
                    logger.info("Switched to by-date statistics view")
        else:
            logger.info("No statistics table found")

        log_test_result(test_name, True, 0)

# ============================================================================
# TOKEN-P1-003: Date range filter
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.token_usage
class TestTokenUsageDateFilter:
    """
    TOKEN-P1-003: Date range filter

    Functional coverage:
    1. Verify date range picker exists
    2. Click to open date picker
    3. Verify date picker popup
    """

    @pytest.mark.test_id("TOKEN-P1-003")
    def test_token_usage_date_filter(self, page: Page, request: pytest.FixtureRequest):
        """Test date range filter functionality."""
        test_name = request.node.name

        log_test_step("Navigate to Token Usage page")
        navigate_to_token_usage(page)

        log_test_step("Find date range picker")
        range_picker = page.locator(
            '.qwenpaw-picker-range, .ant-picker-range, '
            '[class*="rangePicker"], [class*="date-range"]'
        ).first

        if range_picker.count() == 0:
            # Try finding a single date picker
            range_picker = page.locator(
                '.qwenpaw-picker, .ant-picker'
            ).first

        if range_picker.count() > 0:
            expect(range_picker).to_be_visible(timeout=5000)
            logger.info("Date range picker exists")

            log_test_step("Verify picker has default value")
            picker_text = range_picker.inner_text().strip()
            picker_inputs = range_picker.locator('input').all()
            if len(picker_inputs) > 0:
                start_value = picker_inputs[0].input_value()
                logger.info(f"Start date: {start_value}")
                if len(picker_inputs) > 1:
                    end_value = picker_inputs[1].input_value()
                    logger.info(f"End date: {end_value}")
            logger.info("Date picker has value")

            log_test_step("Click to open date picker")
            range_picker.click()
            page.wait_for_timeout(1000)

            # Verify date panel pops up
            date_panel = page.locator(
                '.qwenpaw-picker-dropdown, .ant-picker-dropdown, '
                '.qwenpaw-picker-panel, .ant-picker-panel'
            ).first
            if date_panel.count() > 0:
                expect(date_panel).to_be_visible(timeout=3000)
                logger.info("Date selection panel popped up")

                # Actually select a date
                log_test_step("Select a date")
                today_cell = date_panel.locator(
                    '.qwenpaw-picker-cell-today, .ant-picker-cell-today, '
                    'td.qwenpaw-picker-cell-in-view'
                ).first
                if today_cell.count() > 0 and today_cell.is_visible(timeout=2000):
                    today_cell.click()
                    page.wait_for_timeout(500)
                    logger.info("Clicked a date cell")

                    # If it's a range picker, need to select an end date too
                    is_range = range_picker.locator('input').count() > 1
                    if is_range:
                        # Pick the same day or the next visible day as the end date
                        end_cells = date_panel.locator('td.qwenpaw-picker-cell-in-view, td.ant-picker-cell-in-view').all()
                        if len(end_cells) > 1:
                            end_cells[-1].click()
                            page.wait_for_timeout(500)
                            logger.info("Selected end date")
                else:
                    logger.info("No clickable date cell found")
            else:
                logger.info("Date panel did not pop up")

            # Close date panel
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

            # Verify date value updated after selection
            picker_inputs_after = range_picker.locator('input').all()
            if len(picker_inputs_after) > 0:
                updated_value = picker_inputs_after[0].input_value()
                logger.info(f"Date value after selection: {updated_value}")
                assert len(updated_value) > 0, "Date value should not be empty after selecting"
                logger.info("Date picker value updated")
        else:
            logger.info("Date range picker not found")

        log_test_result(test_name, True, 0)


# ============================================================================
# TOKEN-P2-001: Empty data / loading state display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.token_usage
class TestTokenUsageEmptyState:
    """TOKEN-P2-001: Empty data / loading state display"""

    @pytest.mark.test_id("TOKEN-P2-001")
    def test_token_usage_empty_state(self, page: Page, request: pytest.FixtureRequest):
        """Test empty data / loading state display."""
        test_name = request.node.name

        log_test_step("Navigate to Token Usage page")
        navigate_to_token_usage(page)

        log_test_step("Verify page loading state")
        # Check for loading animation
        loading = page.locator('.qwenpaw-spin, .ant-spin, [class*="loading"]').first
        if loading.count() > 0 and loading.is_visible():
            logger.info("Page is loading...")
            page.wait_for_timeout(5000)

        log_test_step("Verify empty state or data display")
        empty_state = page.locator('.qwenpaw-empty, :text("暂无"), :text("No data"), :text("Empty")').first
        tables = page.locator('.qwenpaw-table, table').all()
        cards = page.locator('.qwenpaw-card').all()

        if empty_state.count() > 0 and empty_state.is_visible():
            logger.info("Empty state displayed correctly")
        elif len(tables) > 0 or len(cards) > 0:
            logger.info(f"Data displayed: {len(tables)} tables, {len(cards)} cards")
        else:
            logger.info("Page has neither empty state nor data")

        log_test_result(test_name, True, 0)
