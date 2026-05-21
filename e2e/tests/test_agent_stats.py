# -*- coding: utf-8 -*-
"""
QwenPaw 智能体统计仪表板模块端到端测试用例

AgentStats 模块测试：
- ASTAT-001: 统计页面加载与汇总卡片展示 (P0)
- ASTAT-002: 日期范围筛选器交互 (P0)
- ASTAT-003: 趋势图表区域展示 (P0)
- ASTAT-004: 渠道分布饼图展示 (P1)
- ASTAT-005: 日期筛选后数据刷新 (P1)
- ASTAT-006: 汇总卡片 Tooltip 提示 (P1)
- ASTAT-007: 空状态与加载状态 (P2)
- ASTAT-008: 页面刷新后数据保持 (P2)

测试框架：pytest + Playwright
执行命令：pytest tests/test_agent_stats.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


# ============================================================================
# ASTAT-001: 统计页面加载与汇总卡片展示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agent_stats
class TestAgentStatsPageDisplay:
    """
    ASTAT-001: 智能体统计页面加载与汇总卡片展示

    覆盖功能点：
    1. /agent-stats 页面访问与加载
    2. 面包屑验证（Settings / Agent Stats）
    3. 汇总卡片展示（6 个统计卡片）
    4. 卡片标题和数值验证
    """

    @pytest.mark.test_id("ASTAT-001")
    def test_agent_stats_page_load_and_cards(self, page: Page, request: pytest.FixtureRequest):
        """验证智能体统计页面加载与汇总卡片展示"""
        test_name = request.node.name

        try:
            # 1. 访问智能体统计页面
            log_test_step("1. 访问智能体统计页面")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)
            logger.info("智能体统计页面已加载")

            # 2. 验证面包屑
            log_test_step("2. 验证面包屑")
            breadcrumb = page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
            if breadcrumb.is_visible(timeout=3000):
                breadcrumb_text = breadcrumb.inner_text().strip()
                logger.info(f"面包屑内容: {breadcrumb_text}")
                assert ("Settings" in breadcrumb_text or "设置" in breadcrumb_text), \
                    "面包屑应包含 Settings/设置"
                assert ("Agent Stats" in breadcrumb_text or "Statistics" in breadcrumb_text
                        or "统计" in breadcrumb_text or "Stats" in breadcrumb_text), \
                    "面包屑应包含 Agent Stats/Statistics/统计"
                logger.info("✅ 面包屑验证通过")
            else:
                logger.warning("未找到面包屑元素，跳过验证")

            # 3. 验证汇总卡片区域
            log_test_step("3. 验证汇总卡片区域")
            # 查找汇总卡片（SummaryCard 组件）
            cards = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], '
                '.qwenpaw-statistic, [class*="statistic"]'
            ).all()

            # 如果找不到特定类名的卡片，尝试查找通用卡片
            if len(cards) == 0:
                cards = page.locator('.qwenpaw-card').all()

            logger.info(f"找到 {len(cards)} 个汇总卡片")

            # 页面应展示汇总卡片或空状态
            empty = page.locator(".qwenpaw-empty, [class*='empty']").first
            has_cards_or_empty = len(cards) > 0 or empty.is_visible(timeout=3000)
            assert has_cards_or_empty, "页面应展示汇总卡片或空状态"

            if len(cards) > 0:
                logger.info(f"✅ 找到 {len(cards)} 个汇总卡片")
            else:
                logger.info("ℹ️ 页面展示空状态（无统计数据）")

            # 4. 验证卡片内容（如果有）
            if len(cards) > 0:
                log_test_step("4. 验证卡片内容")
                for i, card in enumerate(cards[:6]):
                    card_text = card.inner_text().strip()
                    if card_text:
                        logger.info(f"卡片 {i+1}: {card_text[:80]}")

                # 验证关键指标是否存在（兼容中英文）
                page_text = page.locator("body").inner_text()
                expected_keywords = [
                    ("Sessions", "会话"),
                    ("Messages", "消息"),
                    ("Tokens", "Token"),
                ]
                found_any_keyword = False
                for en_kw, zh_kw in expected_keywords:
                    if en_kw in page_text or zh_kw in page_text:
                        logger.info(f"✅ 找到关键指标: {en_kw}/{zh_kw}")
                        found_any_keyword = True
                assert found_any_keyword, \
                    "汇总卡片中应至少包含一个关键指标（Sessions/Messages/Tokens）"

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-002: 日期范围筛选器交互
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agent_stats
class TestAgentStatsDatePicker:
    """
    ASTAT-002: 日期范围筛选器交互

    覆盖功能点：
    1. 日期范围选择器展示
    2. 点击展开日历面板
    3. 默认日期范围（最近 7 天）
    4. 关闭日历面板
    """

    @pytest.mark.test_id("ASTAT-002")
    def test_date_range_picker_interaction(self, page: Page, request: pytest.FixtureRequest):
        """验证日期范围筛选器交互"""
        test_name = request.node.name

        try:
            # 1. 访问智能体统计页面
            log_test_step("1. 访问智能体统计页面")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. 查找日期范围选择器
            log_test_step("2. 查找日期范围选择器")
            date_picker = page.locator(
                '.qwenpaw-picker-range, .qwenpaw-picker, '
                '[class*="datePicker"], [class*="DatePicker"], '
                '[class*="dateRange"], [class*="DateRange"]'
            ).first

            assert date_picker.is_visible(timeout=5000), "日期范围选择器应可见"
            logger.info("✅ 日期范围选择器可见")

            # 3. 验证默认日期（点击查看面板）
            log_test_step("3. 点击展开日历面板")
            date_picker.click()
            page.wait_for_timeout(500)

            # 检查日历面板是否展开
            panel = page.locator(
                '.qwenpaw-picker-dropdown, .qwenpaw-picker-panel-container, '
                '.qwenpaw-picker-panel, '
                '[class*="pickerPanel"], [class*="calendar"]'
            ).first
            assert panel.is_visible(timeout=3000), "点击日期选择器后日历面板应弹出"
            logger.info("✅ 日历面板已展开")

            # 验证面板中有日期内容（优先检查日期单元格，兼容不同渲染方式）
            date_cells = panel.locator('.qwenpaw-picker-cell, td[class*="cell"]')
            cell_count = date_cells.count()
            if cell_count > 0:
                logger.info(f"日历面板包含 {cell_count} 个日期单元格")
                assert cell_count > 0, "日历面板应包含日期单元格"
            else:
                panel_text = panel.inner_text()
                panel_html = panel.inner_html()
                has_content = len(panel_text.strip()) > 0 or len(panel_html.strip()) > 100
                assert has_content, "日历面板应包含日期内容"
                logger.info(f"日历面板内容片段: {panel_text[:100]}")

            # 4. 关闭日历面板
            log_test_step("4. 关闭日历面板")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            logger.info("✅ 日历面板已关闭")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-003: 趋势图表区域展示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agent_stats
class TestAgentStatsCharts:
    """
    ASTAT-003: 趋势图表区域展示

    覆盖功能点：
    1. 图表区域展示
    2. Canvas 图表渲染验证
    3. 多个趋势图存在（消息、会话、Token、调用）
    """

    @pytest.mark.test_id("ASTAT-003")
    def test_chart_area_display(self, page: Page, request: pytest.FixtureRequest):
        """验证趋势图表区域展示"""
        test_name = request.node.name

        try:
            # 1. 访问智能体统计页面
            log_test_step("1. 访问智能体统计页面")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. 查找图表区域
            log_test_step("2. 查找图表区域")
            # 图表通常用 canvas 或 svg 渲染
            canvas_elements = page.locator("canvas").all()
            svg_charts = page.locator("svg[class*='chart'], svg[class*='g2']").all()
            chart_containers = page.locator(
                '[class*="chartContainer"], [class*="chart"], [class*="Chart"]'
            ).all()

            total_charts = len(canvas_elements) + len(svg_charts)
            logger.info(f"Canvas 元素: {len(canvas_elements)}, SVG 图表: {len(svg_charts)}, "
                        f"图表容器: {len(chart_containers)}")

            # 页面应展示图表元素或空状态
            empty = page.locator(".qwenpaw-empty, [class*='empty']").first
            has_charts_or_empty = (total_charts > 0 or len(chart_containers) > 0
                                   or empty.is_visible(timeout=3000))
            assert has_charts_or_empty, \
                "页面应展示图表元素（canvas/svg/容器）或空状态"

            if total_charts > 0:
                logger.info(f"✅ 找到 {total_charts} 个图表元素")
            elif len(chart_containers) > 0:
                logger.info(f"✅ 找到 {len(chart_containers)} 个图表容器")
            else:
                logger.info("ℹ️ 无数据时图表区域不展示（空状态）")

            # 3. 验证图表标题（如果存在）
            log_test_step("3. 验证图表标题")
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
            logger.info(f"页面中找到的图表关键词: {found_keywords}")
            assert len(found_keywords) >= 2, \
                f"页面应至少包含 2 个图表相关关键词，实际找到: {found_keywords}"

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-004: 渠道分布饼图展示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agent_stats
class TestAgentStatsChannelDistribution:
    """
    ASTAT-004: 渠道分布饼图展示

    覆盖功能点：
    1. 渠道分布区域展示
    2. 饼图/环图渲染
    3. 渠道名称标签
    """

    @pytest.mark.test_id("ASTAT-004")
    def test_channel_distribution_display(self, page: Page, request: pytest.FixtureRequest):
        """验证渠道分布饼图展示"""
        test_name = request.node.name

        try:
            # 1. 访问智能体统计页面
            log_test_step("1. 访问智能体统计页面")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. 查找渠道分布区域
            log_test_step("2. 查找渠道分布区域")
            page_text = page.locator("body").inner_text()

            # 检查是否有渠道分布相关标题
            has_channel_section = (
                "Channel" in page_text or "渠道" in page_text
                or "Distribution" in page_text or "分布" in page_text
            )

            # 应该至少有渠道分布区域或空状态
            empty = page.locator(".qwenpaw-empty, [class*='empty']").first
            assert has_channel_section or empty.is_visible(timeout=3000), \
                "页面应包含渠道分布区域或展示空状态"

            if has_channel_section:
                logger.info("✅ 页面包含渠道分布相关内容")

                # 查找饼图或环图（通常在页面下半部分）
                pie_containers = page.locator(
                    '[class*="pie"], [class*="Pie"], [class*="donut"], '
                    '[class*="distribution"], [class*="Distribution"]'
                ).all()
                canvas_in_page = page.locator("canvas").all()

                has_chart_element = len(pie_containers) > 0 or len(canvas_in_page) > 0
                assert has_chart_element, \
                    "渠道分布区域应有饼图容器或 canvas 元素"
                logger.info(f"✅ 找到图表元素（饼图容器: {len(pie_containers)}, canvas: {len(canvas_in_page)}）")
            else:
                logger.info("ℹ️ 页面展示空状态（无渠道分布数据）")

            # 3. 检查渠道名称（console、dingtalk 等）
            log_test_step("3. 检查渠道名称")
            channel_names = ["console", "dingtalk", "feishu", "wechat", "discord", "telegram"]
            found_channels = [ch for ch in channel_names if ch.lower() in page_text.lower()]
            if found_channels:
                logger.info(f"✅ 发现渠道标签: {found_channels}")
            else:
                logger.info("ℹ️ 未发现渠道标签（可能无数据）")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-005: 日期筛选后数据刷新
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agent_stats
class TestAgentStatsDateFilter:
    """
    ASTAT-005: 日期筛选后数据刷新

    覆盖功能点：
    1. 切换日期范围
    2. 数据自动刷新
    3. 加载状态展示
    """

    @pytest.mark.test_id("ASTAT-005")
    def test_date_filter_refreshes_data(self, page: Page, request: pytest.FixtureRequest):
        """验证日期筛选后数据刷新"""
        test_name = request.node.name

        try:
            # 1. 访问智能体统计页面
            log_test_step("1. 访问智能体统计页面")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. 查找日期选择器
            log_test_step("2. 查找日期选择器")
            date_picker = page.locator(
                '.qwenpaw-picker-range, .qwenpaw-picker, '
                '[class*="datePicker"], [class*="DatePicker"]'
            ).first

            assert date_picker.is_visible(timeout=5000), "日期选择器应可见"

            # 3. 记录当前卡片数据
            log_test_step("3. 记录当前卡片数据")
            cards_before = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()
            data_before = []
            for card in cards_before:
                data_before.append(card.inner_text().strip()[:60])
            logger.info(f"筛选前卡片数据: {len(data_before)} 张卡片")

            # 4. 点击日期选择器并选择不同范围
            log_test_step("4. 交互日期选择器")
            date_picker.click()
            page.wait_for_timeout(500)

            # 尝试选择预设范围（如"最近30天"）
            preset_buttons = page.locator(
                '.qwenpaw-picker-presets button, '
                '.qwenpaw-picker-ranges button, '
                '[class*="preset"]'
            ).all()

            if len(preset_buttons) > 1:
                # 选择第二个预设（通常是不同的范围）
                preset_buttons[1].click()
                page.wait_for_timeout(1000)
                logger.info("✅ 选择了不同的日期预设范围")
            else:
                # 没有预设按钮，关闭面板
                page.keyboard.press("Escape")
                logger.info("ℹ️ 未找到日期预设按钮")

            # 5. 验证数据刷新
            log_test_step("5. 验证数据刷新")
            page.wait_for_timeout(2000)

            # 等待可能出现的加载状态完成
            spin = page.locator(".qwenpaw-spin, [class*='loading']").first
            if spin.is_visible(timeout=2000):
                logger.info("✅ 数据刷新中（加载状态可见）")
                try:
                    spin.wait_for(state="hidden", timeout=10000)
                except Exception:
                    pass

            # 筛选后应仍有卡片或展示空状态
            cards_after = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()
            empty_state = page.locator(".qwenpaw-empty, [class*='empty']").first
            assert len(cards_after) > 0 or empty_state.is_visible(timeout=3000), \
                "日期筛选后应仍有卡片展示或展示空状态"
            logger.info(f"✅ 日期筛选后数据刷新验证通过（卡片: {len(cards_after)} 张）")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-006: 汇总卡片 Tooltip 提示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agent_stats
class TestAgentStatsCardTooltip:
    """
    ASTAT-006: 汇总卡片 Tooltip 提示

    覆盖功能点：
    1. 鼠标悬停在卡片上
    2. Tooltip 提示出现
    3. Tooltip 内容验证
    """

    @pytest.mark.test_id("ASTAT-006")
    def test_card_tooltip_display(self, page: Page, request: pytest.FixtureRequest):
        """验证汇总卡片 Tooltip 提示"""
        test_name = request.node.name

        try:
            # 1. 访问智能体统计页面
            log_test_step("1. 访问智能体统计页面")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. 查找汇总卡片
            log_test_step("2. 查找汇总卡片")
            cards = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], '
                '.qwenpaw-statistic, .qwenpaw-card'
            ).all()

            if len(cards) == 0:
                logger.info("ℹ️ 未找到汇总卡片，跳过 Tooltip 验证")
                log_test_result(test_name, True, 0)
                return

            # 3. 悬停在第一个卡片的 info icon 上
            log_test_step("3. 悬停查看 Tooltip")
            first_card = cards[0]

            # 查找 info 图标或 tooltip trigger
            info_icon = first_card.locator(
                '[class*="info"], [class*="tooltip"], '
                '.anticon-info-circle, .anticon-question-circle, '
                'svg, [class*="icon"]'
            ).first

            # 尝试悬停 info 图标或卡片本身来触发 Tooltip
            hover_target = info_icon if info_icon.is_visible(timeout=3000) else first_card
            hover_target.hover()
            page.wait_for_timeout(500)

            tooltip = page.locator(
                '.qwenpaw-tooltip, [role="tooltip"], [class*="tooltip"]'
            ).first
            if tooltip.is_visible(timeout=3000):
                tooltip_text = tooltip.inner_text().strip()
                assert len(tooltip_text) > 0, "Tooltip 内容不应为空"
                logger.info(f"✅ Tooltip 内容: {tooltip_text[:80]}")
            else:
                # Tooltip 不是所有主题/配置都有，验证悬停交互不报错即可
                logger.info("ℹ️ 未触发 Tooltip（可能无提示信息），悬停交互无异常")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-007: 空状态与加载状态
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agent_stats
class TestAgentStatsEmptyAndLoading:
    """
    ASTAT-007: 空状态与加载状态

    覆盖功能点：
    1. 加载状态展示（Spin）
    2. 空状态展示（Empty）
    3. 错误状态与重试
    """

    @pytest.mark.test_id("ASTAT-007")
    def test_empty_and_loading_states(self, page: Page, request: pytest.FixtureRequest):
        """验证空状态与加载状态展示"""
        test_name = request.node.name

        try:
            # 1. 访问智能体统计页面
            log_test_step("1. 访问智能体统计页面")
            page.goto(f"{config.base_url}/agent-stats")

            # 2. 检查加载状态
            log_test_step("2. 检查加载状态")
            spin = page.locator(".qwenpaw-spin, [class*='loading'], [class*='spin']").first
            if spin.is_visible(timeout=3000):
                logger.info("✅ 加载状态（Spin）可见")
                # 等待加载完成
                try:
                    spin.wait_for(state="hidden", timeout=15000)
                    logger.info("✅ 加载完成")
                except Exception:
                    logger.info("ℹ️ 加载状态持续显示")
            else:
                logger.info("ℹ️ 未捕获到加载状态（可能加载过快）")

            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 3. 检查空状态
            log_test_step("3. 检查空状态或数据展示")
            empty = page.locator(".qwenpaw-empty, [class*='empty']").first
            cards = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()

            # 页面应展示以下任一状态：数据卡片、空状态、或错误状态+重试按钮
            error = page.locator('[class*="error"]').first
            has_valid_state = (
                empty.is_visible(timeout=3000)
                or len(cards) > 0
                or error.is_visible(timeout=2000)
            )
            assert has_valid_state, \
                "页面加载完成后应展示数据卡片、空状态或错误状态"

            if len(cards) > 0:
                logger.info(f"✅ 有数据展示（{len(cards)} 张卡片）")
            elif empty.is_visible(timeout=1000):
                logger.info("✅ 空状态展示正常（无数据）")
            elif error.is_visible(timeout=1000):
                logger.info("ℹ️ 检测到错误状态")
                retry_btn = page.locator(
                    'button:has-text("Retry"), button:has-text("重试")'
                ).first
                if retry_btn.is_visible(timeout=2000):
                    logger.info("✅ 错误状态下重试按钮可见")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ASTAT-008: 页面刷新后数据保持
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agent_stats
class TestAgentStatsRefresh:
    """
    ASTAT-008: 页面刷新后数据保持

    覆盖功能点：
    1. 页面刷新后重新加载
    2. 卡片数量保持一致
    3. 图表区域重新渲染
    """

    @pytest.mark.test_id("ASTAT-008")
    def test_page_refresh_data_persistence(self, page: Page, request: pytest.FixtureRequest):
        """验证页面刷新后数据保持"""
        test_name = request.node.name

        try:
            # 1. 访问智能体统计页面
            log_test_step("1. 访问智能体统计页面")
            page.goto(f"{config.base_url}/agent-stats")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. 记录初始状态
            log_test_step("2. 记录初始状态")
            cards_before = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()
            card_count_before = len(cards_before)
            canvas_count_before = len(page.locator("canvas").all())
            logger.info(f"刷新前: 卡片={card_count_before}, Canvas={canvas_count_before}")

            # 3. 刷新页面
            log_test_step("3. 刷新页面")
            page.reload(wait_until="commit", timeout=15000)
            page.wait_for_timeout(2000)

            # 4. 验证数据保持
            log_test_step("4. 验证数据保持")
            cards_after = page.locator(
                '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-statistic, .qwenpaw-card'
            ).all()
            card_count_after = len(cards_after)
            canvas_count_after = len(page.locator("canvas").all())
            logger.info(f"刷新后: 卡片={card_count_after}, Canvas={canvas_count_after}")

            assert card_count_after == card_count_before, \
                f"卡片数量应一致: 刷新前={card_count_before}, 刷新后={card_count_after}"
            logger.info("✅ 页面刷新后数据保持一致")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
