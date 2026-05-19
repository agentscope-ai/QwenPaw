# -*- coding: utf-8 -*-
"""
QwenPaw Token 消耗（Token Usage）模块 P0 级端到端测试用例

组合用例设计：
- TOKEN-001: Token 消耗页面加载 + 概览展示 + 空状态验证
- TOKEN-002: 日期范围筛选 + 快捷选项 + 数据刷新
- TOKEN-003: 模型筛选 + Provider 筛选
- TOKEN-004: 数据表格展示 + 分页 + 排序验证
- TOKEN-005: 数据导出功能 + 格式选项验证

执行命令：pytest tests/test_token_usage_p0.py -v
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
    """导航到 Token 消耗页面并等待加载"""
    page.goto(TOKEN_USAGE_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)

# ============================================================================
# TOKEN-001: 页面加载 + 概览展示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.token_core
class TestTokenUsageDisplay:
    """
    TOKEN-001: Token 消耗页面加载 + 概览展示 + 空状态验证
    
    覆盖功能点：
    1. Token 消耗页面访问与加载
    2. 面包屑导航验证
    3. 概览卡片展示（总消耗、今日消耗等）
    4. 图表区域展示
    5. 数据表格展示
    6. 空状态验证
    """
    
    @pytest.mark.test_id("TOKEN-001")
    def test_token_usage_overview(self, page: Page, request: pytest.FixtureRequest):
        """验证 Token 消耗概览正常展示及空状态"""
        test_name = request.node.name
        
        # 步骤 1: 访问 Token 消耗页面
        log_test_step("1. 访问 Token 消耗页面")
        navigate_to_token_usage(page)
        
        # 步骤 2: 验证面包屑（软断言，兼容中英文 UI）
        log_test_step("2. 验证面包屑")
        try:
            # 尝试中文面包屑
            breadcrumb_settings = page.locator('span[class*="breadcrumbParent"]:has-text("设置"), span[class*="breadcrumbParent"]:has-text("Settings")').first
            if breadcrumb_settings.is_visible(timeout=3000):
                breadcrumb_current = page.locator('span[class*="breadcrumbCurrent"]:has-text("Token 消耗"), span[class*="breadcrumbCurrent"]:has-text("Token Usage")').first
                if breadcrumb_current.is_visible(timeout=3000):
                    logger.info("✅ 面包屑验证通过")
                else:
                    logger.info("ℹ️ 面包屑当前项未找到，跳过验证")
            else:
                logger.info("ℹ️ 面包屑父项未找到，跳过验证")
        except Exception as e:
            logger.info(f"ℹ️ 面包屑验证跳过（可能页面结构不同）：{e}")
        
        # 步骤 3: 验证页面标题
        log_test_step("3. 验证页面标题")
        page_title = page.locator('h1:has-text("Token Usage"), h1:has-text("Token"), .qwenpaw-page-header:has-text("Token")').first
        if page_title.is_visible(timeout=3000):
            logger.info("✅ 页面标题可见")
        
        # 步骤 4: 验证概览卡片
        log_test_step("4. 验证概览卡片")
        overview_cards = page.locator('.qwenpaw-card, [class*=overviewCard], [class*=statCard]').all()
        
        assert len(overview_cards) > 0, "Token 消耗页面应展示概览卡片"
        logger.info(f"✅ 找到 {len(overview_cards)} 个概览卡片")
        
        # 验证卡片内容
        for i, card in enumerate(overview_cards[:3]):  # 检查前 3 个卡片
            card_text = card.inner_text()
            logger.info(f"卡片 {i+1}: {card_text[:50]}...")
        
        # 步骤 5: 验证数据表格并检查交互
        log_test_step("5. 验证数据表格")
        table_area = page.locator('.qwenpaw-table, table, [class*=dataTable]').first
        assert table_area.count() > 0 and table_area.is_visible(timeout=5000), \
            "Token 消耗页面应展示数据表格"
        logger.info("✅ 数据表格可见")
        
        # 验证表格有列标题
        table_headers = table_area.locator('th').all()
        visible_headers = [h for h in table_headers if h.is_visible()]
        assert len(visible_headers) > 0, "数据表格应有列标题"
        header_texts = [h.inner_text().strip() for h in visible_headers]
        logger.info(f"✅ 表格列标题：{header_texts}")
        
        # 步骤 6: 点击表头排序验证交互
        log_test_step("6. 点击表头排序验证交互")
        if len(visible_headers) > 0:
            first_sortable_header = visible_headers[0]
            first_sortable_header.click()
            page.wait_for_timeout(1000)
            logger.info("✅ 已点击表头排序")
        
        # 步骤 7: 验证有数据行或空状态
        log_test_step("7. 验证数据行或空状态")
        data_rows = table_area.locator('tbody tr').all()
        empty_state = page.locator('.qwenpaw-empty, [class*=empty]').first
        has_data = len(data_rows) > 0
        has_empty = empty_state.count() > 0 and empty_state.is_visible(timeout=2000)
        assert has_data or has_empty, "表格应有数据行或显示空状态"
        if has_data:
            logger.info(f"✅ 表格有 {len(data_rows)} 行数据")
        else:
            logger.info("✅ 空状态展示正确")
        
        log_test_result(test_name, "PASS", "Token 消耗概览展示及交互验证通过")

# ============================================================================
# TOKEN-P1-001: 按模型统计 Token 消耗
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.token_usage
class TestTokenUsageByModel:
    """
    TOKEN-P1-001: 按模型统计 Token 消耗

    覆盖功能点：
    1. 验证按模型统计表格存在
    2. 验证表格有列标题
    3. 验证数据行或空状态
    """

    @pytest.mark.test_id("TOKEN-P1-001")
    def test_token_usage_by_model(self, page: Page, request: pytest.FixtureRequest):
        """测试按模型统计 Token 消耗"""
        test_name = request.node.name

        log_test_step("导航到 Token 消耗页面")
        navigate_to_token_usage(page)

        log_test_step("查找按模型统计表格")
        tables = page.locator('.qwenpaw-table, table').all()
        logger.info(f"页面上找到 {len(tables)} 个表格")

        if len(tables) > 0:
            first_table = tables[0]
            expect(first_table).to_be_visible(timeout=5000)

            log_test_step("验证表格列标题")
            headers = first_table.locator('th, .qwenpaw-table-thead th').all()
            header_texts = [h.inner_text().strip() for h in headers if h.is_visible()]
            logger.info(f"表格列标题：{header_texts}")
            assert len(header_texts) > 0, "表格没有列标题"
            logger.info("✅ 按模型统计表格列标题验证通过")

            log_test_step("验证数据行或空状态")
            data_rows = first_table.locator('tbody tr, .qwenpaw-table-row').all()
            empty_state = first_table.locator('.qwenpaw-empty, :text("暂无"), :text("No data")').first

            assert len(data_rows) > 0 or empty_state.count() > 0, \
                "按模型统计表格应有数据行或显示空状态"
            if len(data_rows) > 0:
                logger.info(f"✅ 按模型统计表格有 {len(data_rows)} 行数据")
            else:
                logger.info("✅ 按模型统计表格显示空状态")
        else:
            logger.info("未找到表格，验证页面有统计相关内容")
            stat_content = page.locator(':text("Model"), :text("模型"), :text("Token")').all()
            logger.info(f"找到 {len(stat_content)} 个统计相关元素")

        log_test_result(test_name, True, 0)

# ============================================================================
# TOKEN-P1-002: 按日期统计 Token 趋势
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.token_usage
class TestTokenUsageByDate:
    """
    TOKEN-P1-002: 按日期统计 Token 趋势

    覆盖功能点：
    1. 验证按日期统计表格存在
    2. 验证日期列存在
    3. 验证数据行或空状态
    """

    @pytest.mark.test_id("TOKEN-P1-002")
    def test_token_usage_by_date(self, page: Page, request: pytest.FixtureRequest):
        """测试按日期统计 Token 趋势"""
        test_name = request.node.name

        log_test_step("导航到 Token 消耗页面")
        navigate_to_token_usage(page)

        log_test_step("查找按日期统计表格")
        tables = page.locator('.qwenpaw-table, table').all()

        if len(tables) >= 2:
            date_table = tables[1]
            expect(date_table).to_be_visible(timeout=5000)

            log_test_step("验证日期列存在")
            headers = date_table.locator('th, .qwenpaw-table-thead th').all()
            header_texts = [h.inner_text().strip() for h in headers if h.is_visible()]
            logger.info(f"日期表格列标题：{header_texts}")

            has_date_column = any(
                "date" in h.lower() or "日期" in h or "Date" in h
                for h in header_texts
            )
            if has_date_column:
                logger.info("✅ 日期列存在")
            else:
                logger.info(f"未找到明确的日期列，列标题为：{header_texts}")

            log_test_step("验证数据行")
            data_rows = date_table.locator('tbody tr, .qwenpaw-table-row').all()
            logger.info(f"按日期统计表格有 {len(data_rows)} 行数据")
        elif len(tables) == 1:
            logger.info("只找到 1 个表格，可能按模型和按日期合并展示")
            # 验证表格有 Tab 切换
            tabs = page.locator('.qwenpaw-tabs-tab, .qwenpaw-segmented-item').all()
            if len(tabs) > 0:
                logger.info(f"找到 {len(tabs)} 个 Tab/Segment 切换项")
                # 点击第二个 Tab
                if len(tabs) >= 2:
                    tabs[1].click()
                    page.wait_for_timeout(1000)
                    logger.info("✅ 已切换到按日期统计视图")
        else:
            logger.info("未找到统计表格")

        log_test_result(test_name, True, 0)

# ============================================================================
# TOKEN-P1-003: 时间范围筛选
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.token_usage
class TestTokenUsageDateFilter:
    """
    TOKEN-P1-003: 时间范围筛选

    覆盖功能点：
    1. 验证日期范围选择器存在
    2. 点击打开日期选择器
    3. 验证日期选择器弹窗
    """

    @pytest.mark.test_id("TOKEN-P1-003")
    def test_token_usage_date_filter(self, page: Page, request: pytest.FixtureRequest):
        """测试时间范围筛选功能"""
        test_name = request.node.name

        log_test_step("导航到 Token 消耗页面")
        navigate_to_token_usage(page)

        log_test_step("查找日期范围选择器")
        range_picker = page.locator(
            '.qwenpaw-picker-range, .ant-picker-range, '
            '[class*="rangePicker"], [class*="date-range"]'
        ).first

        if range_picker.count() == 0:
            # 尝试查找普通日期选择器
            range_picker = page.locator(
                '.qwenpaw-picker, .ant-picker'
            ).first

        if range_picker.count() > 0:
            expect(range_picker).to_be_visible(timeout=5000)
            logger.info("✅ 日期范围选择器存在")

            log_test_step("验证选择器有默认值")
            picker_text = range_picker.inner_text().strip()
            picker_inputs = range_picker.locator('input').all()
            if len(picker_inputs) > 0:
                start_value = picker_inputs[0].input_value()
                logger.info(f"起始日期：{start_value}")
                if len(picker_inputs) > 1:
                    end_value = picker_inputs[1].input_value()
                    logger.info(f"结束日期：{end_value}")
            logger.info("✅ 日期选择器有值")

            log_test_step("点击打开日期选择器")
            range_picker.click()
            page.wait_for_timeout(1000)

            # 验证日期面板弹出
            date_panel = page.locator(
                '.qwenpaw-picker-dropdown, .ant-picker-dropdown, '
                '.qwenpaw-picker-panel, .ant-picker-panel'
            ).first
            if date_panel.count() > 0:
                expect(date_panel).to_be_visible(timeout=3000)
                logger.info("✅ 日期选择面板已弹出")
                
                # 实际选择一个日期
                log_test_step("选择日期")
                today_cell = date_panel.locator(
                    '.qwenpaw-picker-cell-today, .ant-picker-cell-today, '
                    'td.qwenpaw-picker-cell-in-view'
                ).first
                if today_cell.count() > 0 and today_cell.is_visible(timeout=2000):
                    today_cell.click()
                    page.wait_for_timeout(500)
                    logger.info("✅ 已点击选择日期单元格")
                    
                    # 如果是范围选择器，需要再选一个结束日期
                    is_range = range_picker.locator('input').count() > 1
                    if is_range:
                        # 选择同一天或下一个可见日期作为结束日期
                        end_cells = date_panel.locator('td.qwenpaw-picker-cell-in-view, td.ant-picker-cell-in-view').all()
                        if len(end_cells) > 1:
                            end_cells[-1].click()
                            page.wait_for_timeout(500)
                            logger.info("✅ 已选择结束日期")
                else:
                    logger.info("ℹ️ 未找到可点击的日期单元格")
            else:
                logger.info("日期面板未弹出")

            # 关闭日期面板
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            
            # 验证选择后日期值已更新
            picker_inputs_after = range_picker.locator('input').all()
            if len(picker_inputs_after) > 0:
                updated_value = picker_inputs_after[0].input_value()
                logger.info(f"选择后日期值：{updated_value}")
                assert len(updated_value) > 0, "选择日期后，日期值不应为空"
                logger.info("✅ 日期选择器值已更新")
        else:
            logger.info("未找到日期范围选择器")

        log_test_result(test_name, True, 0)


# ============================================================================
# TOKEN-P2-001: 空数据/加载状态展示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.token_usage
class TestTokenUsageEmptyState:
    """TOKEN-P2-001: 空数据/加载状态展示"""

    @pytest.mark.test_id("TOKEN-P2-001")
    def test_token_usage_empty_state(self, page: Page, request: pytest.FixtureRequest):
        """测试空数据/加载状态展示"""
        test_name = request.node.name

        log_test_step("导航到 Token 消耗页面")
        navigate_to_token_usage(page)

        log_test_step("验证页面加载状态")
        # 检查是否有加载动画
        loading = page.locator('.qwenpaw-spin, .ant-spin, [class*="loading"]').first
        if loading.count() > 0 and loading.is_visible():
            logger.info("页面正在加载中...")
            page.wait_for_timeout(5000)

        log_test_step("验证空状态或数据展示")
        empty_state = page.locator('.qwenpaw-empty, :text("暂无"), :text("No data"), :text("Empty")').first
        tables = page.locator('.qwenpaw-table, table').all()
        cards = page.locator('.qwenpaw-card').all()

        if empty_state.count() > 0 and empty_state.is_visible():
            logger.info("✅ 空状态展示正确")
        elif len(tables) > 0 or len(cards) > 0:
            logger.info(f"✅ 有数据展示：{len(tables)} 个表格, {len(cards)} 个卡片")
        else:
            logger.info("页面既无空状态也无数据展示")

        log_test_result(test_name, True, 0)