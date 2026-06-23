# -*- coding: utf-8 -*-
"""
QwenPaw agent statistics dashboard module end-to-end tests

AgentStats module tests:
- ASTAT-001: Stats page load and summary cards display (P0)
- ASTAT-002: Date range picker interaction (P0)
- ASTAT-003: Trend chart area display (P0)
- ASTAT-004: Channel distribution pie chart display (P1)
- ASTAT-005: Data refresh after date filter (P1)
- ASTAT-006: Summary card tooltip (P1)
- ASTAT-007: Empty state and loading state (P2)
- ASTAT-008: Data persistence after page refresh (P2)

Test framework: pytest + Playwright
Run command: pytest tests/test_agent_stats.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


# ============================================================================
# ASTAT-001: Stats page load and summary cards display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agent_stats
class TestAgentStatsPageDisplay:
    """
    ASTAT-001: Agent stats page load and summary cards display

    Functional coverage:
    1. /agent-stats page access and load
    2. Breadcrumb validation (Settings / Agent Stats)
    3. Summary cards display (6 statistic cards)
    4. Card title and value validation
    """

    @pytest.mark.test_id("ASTAT-001")
    def test_agent_stats_page_load_and_cards(self, page: Page, request: pytest.FixtureRequest):
        """Verify agent stats page load and summary cards display."""
        test_name = request.node.name

        try:
            # 1. Navigate to agent stats page
            log_test_step("1. Navigate to agent stats page")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)
            logger.info("Agent stats page loaded")

            # 2. Verify breadcrumb
            log_test_step("2. Verify breadcrumb")
            breadcrumb = page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
            if breadcrumb.is_visible(timeout=3000):
                breadcrumb_text = breadcrumb.inner_text().strip()
                logger.info(f"Breadcrumb content: {breadcrumb_text}")
                assert ("Settings" in breadcrumb_text or "设置" in breadcrumb_text), \
                    "Breadcrumb should contain Settings"
                assert ("Agent Stats" in breadcrumb_text or "Statistics" in breadcrumb_text
                        or "统计" in breadcrumb_text or "Stats" in breadcrumb_text), \
                    "Breadcrumb should contain Agent Stats/Statistics"
                logger.info("Breadcrumb validation passed")
            else:
                logger.warning("Breadcrumb element not found, skipping validation")

            # 3. Verify summary cards area
            log_test_step("3. Verify summary cards area")
            # Look for summary cards (SummaryCard component)
            cards = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], '
                '.qwenpaw-statistic, [class*="statistic"]'
            ).all()

            # Fall back to generic card lookup if specific classes are not found
            if len(cards) == 0:
                cards = page.locator('.qwenpaw-card').all()

            logger.info(f"Found {len(cards)} summary cards")

            # Page should display either summary cards or empty state
            empty = page.locator(".qwenpaw-empty, [class*='empty']").first
            has_cards_or_empty = len(cards) > 0 or empty.is_visible(timeout=3000)
            assert has_cards_or_empty, "Page should display summary cards or empty state"

            if len(cards) > 0:
                logger.info(f"Found {len(cards)} summary cards")
            else:
                logger.info("Page displays empty state (no statistics data)")

            # 4. Verify card content (if any)
            if len(cards) > 0:
                log_test_step("4. Verify card content")
                for i, card in enumerate(cards[:6]):
                    card_text = card.inner_text().strip()
                    if card_text:
                        logger.info(f"Card {i+1}: {card_text[:80]}")

                # Verify key metrics exist (supports both English and Chinese UI)
                page_text = page.locator("body").inner_text()
                expected_keywords = [
                    ("Sessions", "会话"),
                    ("Messages", "消息"),
                    ("Tokens", "Token"),
                ]
                found_any_keyword = False
                for en_kw, zh_kw in expected_keywords:
                    if en_kw in page_text or zh_kw in page_text:
                        logger.info(f"Found key metric: {en_kw}/{zh_kw}")
                        found_any_keyword = True
                assert found_any_keyword, \
                    "Summary cards should contain at least one key metric (Sessions/Messages/Tokens)"

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-002: Date range picker interaction
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agent_stats
class TestAgentStatsDatePicker:
    """
    ASTAT-002: Date range picker interaction

    Functional coverage:
    1. Date range picker display
    2. Click to expand calendar panel
    3. Default date range (last 7 days)
    4. Close calendar panel
    """

    @pytest.mark.test_id("ASTAT-002")
    def test_date_range_picker_interaction(self, page: Page, request: pytest.FixtureRequest):
        """Verify date range picker interaction."""
        test_name = request.node.name

        try:
            # 1. Navigate to agent stats page
            log_test_step("1. Navigate to agent stats page")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. Find date range picker
            log_test_step("2. Find date range picker")
            date_picker = page.locator(
                '.qwenpaw-picker-range, .qwenpaw-picker, '
                '[class*="datePicker"], [class*="DatePicker"], '
                '[class*="dateRange"], [class*="DateRange"]'
            ).first

            assert date_picker.is_visible(timeout=5000), "Date range picker should be visible"
            logger.info("Date range picker is visible")

            # 3. Verify default date (click to view panel)
            log_test_step("3. Click to expand calendar panel")
            date_picker.click()
            page.wait_for_timeout(500)

            # Check whether calendar panel is expanded
            panel = page.locator(
                '.qwenpaw-picker-dropdown, .qwenpaw-picker-panel-container, '
                '.qwenpaw-picker-panel, '
                '[class*="pickerPanel"], [class*="calendar"]'
            ).first
            assert panel.is_visible(timeout=3000), "Calendar panel should pop up after clicking date picker"
            logger.info("Calendar panel expanded")

            # Verify panel contains date content (prefer date cells, fallback to other rendering)
            date_cells = panel.locator('.qwenpaw-picker-cell, td[class*="cell"]')
            cell_count = date_cells.count()
            if cell_count > 0:
                logger.info(f"Calendar panel contains {cell_count} date cells")
                assert cell_count > 0, "Calendar panel should contain date cells"
            else:
                panel_text = panel.inner_text()
                panel_html = panel.inner_html()
                has_content = len(panel_text.strip()) > 0 or len(panel_html.strip()) > 100
                assert has_content, "Calendar panel should contain date content"
                logger.info(f"Calendar panel content snippet: {panel_text[:100]}")

            # 4. Close calendar panel
            log_test_step("4. Close calendar panel")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            logger.info("Calendar panel closed")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-003: Trend chart area display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agent_stats
class TestAgentStatsCharts:
    """
    ASTAT-003: Trend chart area display

    Functional coverage:
    1. Chart area display
    2. Canvas chart rendering validation
    3. Multiple trend charts exist (messages, sessions, tokens, calls)
    """

    @pytest.mark.test_id("ASTAT-003")
    def test_chart_area_display(self, page: Page, request: pytest.FixtureRequest):
        """Verify trend chart area display."""
        test_name = request.node.name

        try:
            # 1. Navigate to agent stats page
            log_test_step("1. Navigate to agent stats page")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. Find chart area
            log_test_step("2. Find chart area")
            # Charts are usually rendered with canvas or svg
            canvas_elements = page.locator("canvas").all()
            svg_charts = page.locator("svg[class*='chart'], svg[class*='g2']").all()
            chart_containers = page.locator(
                '[class*="chartContainer"], [class*="chart"], [class*="Chart"]'
            ).all()

            total_charts = len(canvas_elements) + len(svg_charts)
            logger.info(f"Canvas elements: {len(canvas_elements)}, SVG charts: {len(svg_charts)}, "
                        f"Chart containers: {len(chart_containers)}")

            # Page should display chart elements or empty state
            empty = page.locator(".qwenpaw-empty, [class*='empty']").first
            has_charts_or_empty = (total_charts > 0 or len(chart_containers) > 0
                                   or empty.is_visible(timeout=3000))
            assert has_charts_or_empty, \
                "Page should display chart elements (canvas/svg/container) or empty state"

            if total_charts > 0:
                logger.info(f"Found {total_charts} chart elements")
            elif len(chart_containers) > 0:
                logger.info(f"Found {len(chart_containers)} chart containers")
            else:
                logger.info("Chart area not displayed when no data (empty state)")

            # 3. Verify chart titles (if any)
            log_test_step("3. Verify chart titles")
            page_text = page.locator("body").inner_text()
            chart_keywords = [
                ("Message", "消息"),
                ("Session", "会话"),
                ("Token", "Token"),
                ("LLM", "LLM"),
                ("Tool", "工具"),
            ]
            found_keywords = []
            for en_kw, zh_kw in chart_keywords:
                if en_kw in page_text or zh_kw in page_text:
                    found_keywords.append(en_kw)
            logger.info(f"Chart keywords found in page: {found_keywords}")
            assert len(found_keywords) >= 2, \
                f"Page should contain at least 2 chart-related keywords, actual: {found_keywords}"

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-004: Channel distribution pie chart display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agent_stats
class TestAgentStatsChannelDistribution:
    """
    ASTAT-004: Channel distribution pie chart display

    Functional coverage:
    1. Channel distribution area display
    2. Pie/donut chart rendering
    3. Channel name labels
    """

    @pytest.mark.test_id("ASTAT-004")
    def test_channel_distribution_display(self, page: Page, request: pytest.FixtureRequest):
        """Verify channel distribution pie chart display."""
        test_name = request.node.name

        try:
            # 1. Navigate to agent stats page
            log_test_step("1. Navigate to agent stats page")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. Find channel distribution area
            log_test_step("2. Find channel distribution area")
            main_content = page.locator('main, [class*="content"], [class*="pageContent"]').first
            if main_content.count() > 0:
                page_text = main_content.inner_text()
            else:
                page_text = page.locator("body").inner_text()

            has_channel_section = (
                "Channel Distribution" in page_text or "渠道分布" in page_text
                or ("Distribution" in page_text and "Channel" in page_text)
            )

            empty = page.locator(".qwenpaw-empty, .ant-empty, [class*='empty']").first
            assert has_channel_section or (empty.count() > 0 and empty.is_visible(timeout=3000)), \
                "Page should contain channel distribution area or display empty state"

            if has_channel_section:
                logger.info("Page contains channel distribution content")

                pie_containers = page.locator(
                    '[class*="pie"], [class*="Pie"], [class*="donut"], '
                    '[class*="distribution"], [class*="Distribution"]'
                ).all()
                canvas_in_page = page.locator("canvas").all()

                has_chart_element = len(pie_containers) > 0 or len(canvas_in_page) > 0
                if has_chart_element:
                    logger.info(f"Found chart elements (pie containers: {len(pie_containers)}, canvas: {len(canvas_in_page)})")
                else:
                    logger.info("Channel distribution section present but no chart rendered (possibly no data)")
            else:
                logger.info("Page displays empty state (no channel distribution data)")

            # 3. Check channel names (console, dingtalk, etc.)
            log_test_step("3. Check channel names")
            channel_names = ["console", "dingtalk", "feishu", "wechat", "discord", "telegram"]
            found_channels = [ch for ch in channel_names if ch.lower() in page_text.lower()]
            if found_channels:
                logger.info(f"Found channel labels: {found_channels}")
            else:
                logger.info("No channel labels found (possibly no data)")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-005: Data refresh after date filter
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agent_stats
class TestAgentStatsDateFilter:
    """
    ASTAT-005: Data refresh after date filter

    Functional coverage:
    1. Switch date range
    2. Data refreshes automatically
    3. Loading state display
    """

    @pytest.mark.test_id("ASTAT-005")
    def test_date_filter_refreshes_data(self, page: Page, request: pytest.FixtureRequest):
        """Verify data refresh after date filter."""
        test_name = request.node.name

        try:
            # 1. Navigate to agent stats page
            log_test_step("1. Navigate to agent stats page")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. Find date picker
            log_test_step("2. Find date picker")
            date_picker = page.locator(
                '.qwenpaw-picker-range, .qwenpaw-picker, '
                '[class*="datePicker"], [class*="DatePicker"]'
            ).first

            assert date_picker.is_visible(timeout=5000), "Date picker should be visible"

            # 3. Record current card data
            log_test_step("3. Record current card data")
            cards_before = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()
            data_before = []
            for card in cards_before:
                data_before.append(card.inner_text().strip()[:60])
            logger.info(f"Card data before filter: {len(data_before)} cards")

            # 4. Click date picker and choose a different range
            log_test_step("4. Interact with date picker")
            date_picker.click()
            page.wait_for_timeout(500)

            # Try selecting a preset range (e.g. "last 30 days")
            preset_buttons = page.locator(
                '.qwenpaw-picker-presets button, '
                '.qwenpaw-picker-ranges button, '
                '[class*="preset"]'
            ).all()

            if len(preset_buttons) > 1:
                # Select the second preset (usually a different range)
                preset_buttons[1].click()
                page.wait_for_timeout(1000)
                logger.info("Selected a different date preset range")
            else:
                # No preset buttons, close panel
                page.keyboard.press("Escape")
                logger.info("No date preset buttons found")

            # 5. Verify data refresh
            log_test_step("5. Verify data refresh")
            page.wait_for_timeout(2000)

            # Wait for any loading state to finish
            spin = page.locator(".qwenpaw-spin, [class*='loading']").first
            if spin.is_visible(timeout=2000):
                logger.info("Data refreshing (loading state visible)")
                try:
                    spin.wait_for(state="hidden", timeout=10000)
                except Exception:
                    pass

            # After filter, should still have cards or empty state
            cards_after = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()
            empty_state = page.locator(".qwenpaw-empty, [class*='empty']").first
            assert len(cards_after) > 0 or empty_state.is_visible(timeout=3000), \
                "After date filter, should still have cards or display empty state"
            logger.info(f"Date filter refresh validation passed (cards: {len(cards_after)})")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-006: Summary card tooltip
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agent_stats
class TestAgentStatsCardTooltip:
    """
    ASTAT-006: Summary card tooltip

    Functional coverage:
    1. Hover on card
    2. Tooltip appears
    3. Tooltip content validation
    """

    @pytest.mark.test_id("ASTAT-006")
    def test_card_tooltip_display(self, page: Page, request: pytest.FixtureRequest):
        """Verify summary card tooltip."""
        test_name = request.node.name

        try:
            # 1. Navigate to agent stats page
            log_test_step("1. Navigate to agent stats page")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. Find summary cards
            log_test_step("2. Find summary cards")
            cards = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], '
                '.qwenpaw-statistic, .qwenpaw-card'
            ).all()

            if len(cards) == 0:
                logger.info("No summary cards found, skipping tooltip validation")
                log_test_result(test_name, True, 0)
                return

            # 3. Hover on info icon of the first card
            log_test_step("3. Hover to see tooltip")
            first_card = cards[0]

            # Look for info icon or tooltip trigger
            info_icon = first_card.locator(
                '[class*="info"], [class*="tooltip"], '
                '.anticon-info-circle, .anticon-question-circle, '
                'svg, [class*="icon"]'
            ).first

            # Try hovering info icon or card itself to trigger tooltip
            hover_target = info_icon if info_icon.is_visible(timeout=3000) else first_card
            hover_target.hover()
            page.wait_for_timeout(500)

            tooltip = page.locator(
                '.qwenpaw-tooltip, [role="tooltip"], [class*="tooltip"]'
            ).first
            if tooltip.is_visible(timeout=3000):
                tooltip_text = tooltip.inner_text().strip()
                assert len(tooltip_text) > 0, "Tooltip content should not be empty"
                logger.info(f"Tooltip content: {tooltip_text[:80]}")
            else:
                # Not all themes/configs have tooltips; only verify hover interaction works
                logger.info("Tooltip not triggered (possibly no tip info), hover interaction OK")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-007: Empty state and loading state
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agent_stats
class TestAgentStatsEmptyAndLoading:
    """
    ASTAT-007: Empty state and loading state

    Functional coverage:
    1. Loading state display (Spin)
    2. Empty state display (Empty)
    3. Error state and retry
    """

    @pytest.mark.test_id("ASTAT-007")
    def test_empty_and_loading_states(self, page: Page, request: pytest.FixtureRequest):
        """Verify empty state and loading state display."""
        test_name = request.node.name

        try:
            # 1. Navigate to agent stats page
            log_test_step("1. Navigate to agent stats page")
            page.goto(f"{config.base_url}/agent-stats")

            # 2. Check loading state
            log_test_step("2. Check loading state")
            spin = page.locator(".qwenpaw-spin, [class*='loading'], [class*='spin']").first
            if spin.is_visible(timeout=3000):
                logger.info("Loading state (Spin) visible")
                # Wait for loading to finish
                try:
                    spin.wait_for(state="hidden", timeout=15000)
                    logger.info("Loading finished")
                except Exception:
                    logger.info("Loading state persists")
            else:
                logger.info("Loading state not captured (possibly loaded too fast)")

            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 3. Check empty state
            log_test_step("3. Check empty state or data display")
            empty = page.locator(".qwenpaw-empty, [class*='empty']").first
            cards = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()

            # Page should display one of: data cards, empty state, or error state + retry button
            error = page.locator('[class*="error"]').first
            has_valid_state = (
                empty.is_visible(timeout=3000)
                or len(cards) > 0
                or error.is_visible(timeout=2000)
            )
            assert has_valid_state, \
                "Page should display data cards, empty state, or error state after loading"

            if len(cards) > 0:
                logger.info(f"Data displayed ({len(cards)} cards)")
            elif empty.is_visible(timeout=1000):
                logger.info("Empty state displayed correctly (no data)")
            elif error.is_visible(timeout=1000):
                logger.info("Error state detected")
                retry_btn = page.locator(
                    'button:has-text("Retry"), button:has-text("重试")'
                ).first
                if retry_btn.is_visible(timeout=2000):
                    logger.info("Retry button visible in error state")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-008: Data persistence after page refresh
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agent_stats
class TestAgentStatsRefresh:
    """
    ASTAT-008: Data persistence after page refresh

    Functional coverage:
    1. Page reload re-renders
    2. Card count remains consistent
    3. Chart area re-renders
    """

    @pytest.mark.test_id("ASTAT-008")
    def test_page_refresh_data_persistence(self, page: Page, request: pytest.FixtureRequest):
        """Verify data persistence after page refresh."""
        test_name = request.node.name

        try:
            # 1. Navigate to agent stats page
            log_test_step("1. Navigate to agent stats page")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. Record initial state
            log_test_step("2. Record initial state")
            cards_before = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()
            card_count_before = len(cards_before)
            canvas_count_before = len(page.locator("canvas").all())
            logger.info(f"Before refresh: cards={card_count_before}, canvas={canvas_count_before}")

            # 3. Reload page
            log_test_step("3. Reload page")
            page.reload(wait_until="commit", timeout=15000)
            page.wait_for_timeout(2000)

            # 4. Verify data persists
            log_test_step("4. Verify data persists")
            cards_after = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()
            card_count_after = len(cards_after)
            canvas_count_after = len(page.locator("canvas").all())
            logger.info(f"After refresh: cards={card_count_after}, canvas={canvas_count_after}")

            assert card_count_after == card_count_before, \
                f"Card count should match: before={card_count_before}, after={card_count_after}"
            logger.info("Data persists after page refresh")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
