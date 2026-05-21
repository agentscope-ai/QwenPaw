# -*- coding: utf-8 -*-
"""
QwenPaw AgentStats 智能体统计页面对象

封装智能体统计仪表板页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class AgentStatsPage(BasePage):
    """
    AgentStats 智能体统计页面对象

    封装智能体统计仪表板页面的所有用户操作：
    - 页面导航与加载
    - 日期范围筛选
    - 汇总卡片数据获取
    - 趋势图表验证
    - 渠道分布饼图验证
    - 空状态与加载状态
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/agent-stats"

    # ========== 选择器定义 ==========

    # 页面容器与加载标志
    PAGE_CONTAINER = 'div[class*="agentStats"], div[class*="AgentStats"], [class*="agent-stats"]'
    BREADCRUMB_PARENT = 'span[class*="breadcrumbParent"]'
    BREADCRUMB_CURRENT = 'span[class*="breadcrumbCurrent"]'

    # 日期范围选择器
    DATE_RANGE_PICKER = ".qwenpaw-picker-range, .qwenpaw-picker"
    DATE_RANGE_INPUT = ".qwenpaw-picker-range input, .qwenpaw-picker input"
    DATE_PICKER_PANEL = ".qwenpaw-picker-panel, .qwenpaw-picker-dropdown"

    # 汇总卡片
    SUMMARY_CARD = '[class*="summaryCard"], [class*="SummaryCard"], .qwenpaw-card'
    SUMMARY_CARD_TITLE = '[class*="cardTitle"], [class*="title"], .qwenpaw-statistic-title'
    SUMMARY_CARD_VALUE = '[class*="cardValue"], [class*="value"], .qwenpaw-statistic-content-value'

    # 图表容器
    CHART_CONTAINER = '[class*="chartContainer"], [class*="chart"], canvas'
    COLUMN_CHART = '[class*="column"], [class*="bar"]'
    PIE_CHART = '[class*="pie"], [class*="donut"]'

    # 空状态与加载
    EMPTY_STATE = ".qwenpaw-empty, [class*='empty']"
    LOADING_SPIN = ".qwenpaw-spin, [class*='loading']"
    ERROR_STATE = '[class*="error"]'
    RETRY_BUTTON = 'button:has-text("Retry"), button:has-text("重试")'

    # Tooltip
    TOOLTIP = '.qwenpaw-tooltip, [class*="tooltip"]'

    # ========== 初始化 ==========

    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("AgentStatsPage initialized")

    # ========== 页面导航 ==========

    def open(self) -> "AgentStatsPage":
        """打开智能体统计页面"""
        logger.info("打开 AgentStats 智能体统计页面")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "AgentStatsPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        self.page.wait_for_load_state("networkidle", timeout=timeout)
        self.page.wait_for_timeout(1500)
        return self

    # ========== 面包屑验证 ==========

    def get_breadcrumb_text(self) -> str:
        """获取面包屑文本"""
        breadcrumb = self.page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
        if breadcrumb.is_visible(timeout=3000):
            return breadcrumb.inner_text().strip()
        return ""

    def verify_breadcrumb(self) -> bool:
        """验证面包屑包含 Settings 和 Agent Stats"""
        text = self.get_breadcrumb_text()
        has_settings = "Settings" in text or "设置" in text
        has_stats = "Agent Stats" in text or "统计" in text or "Stats" in text
        return has_settings and has_stats

    # ========== 日期范围筛选 ==========

    def is_date_picker_visible(self) -> bool:
        """判断日期范围选择器是否可见"""
        picker = self.page.locator(self.DATE_RANGE_PICKER).first
        return picker.is_visible(timeout=5000)

    def click_date_picker(self) -> "AgentStatsPage":
        """点击日期范围选择器"""
        picker = self.page.locator(self.DATE_RANGE_PICKER).first
        if picker.is_visible(timeout=5000):
            picker.click()
            self.page.wait_for_timeout(500)
            logger.info("点击日期范围选择器")
        return self

    def is_date_panel_visible(self) -> bool:
        """判断日期面板是否弹出"""
        panel = self.page.locator(self.DATE_PICKER_PANEL).first
        return panel.is_visible(timeout=3000)

    # ========== 汇总卡片 ==========

    def get_summary_cards(self) -> List[Locator]:
        """获取所有汇总卡片"""
        cards = self.page.locator(self.SUMMARY_CARD).all()
        logger.info(f"找到 {len(cards)} 个汇总卡片")
        return cards

    def get_summary_card_count(self) -> int:
        """获取汇总卡片数量"""
        return len(self.get_summary_cards())

    def get_card_title(self, card: Locator) -> str:
        """获取卡片标题"""
        title_el = card.locator(
            '[class*="title"], .qwenpaw-statistic-title, h3, h4, span'
        ).first
        if title_el.is_visible(timeout=3000):
            return title_el.inner_text().strip()
        return ""

    def get_card_value(self, card: Locator) -> str:
        """获取卡片数值"""
        value_el = card.locator(
            '[class*="value"], .qwenpaw-statistic-content-value, '
            '[class*="number"], [class*="count"]'
        ).first
        if value_el.is_visible(timeout=3000):
            return value_el.inner_text().strip()
        return ""

    def get_all_card_data(self) -> List[dict]:
        """获取所有卡片的标题和数值"""
        cards = self.get_summary_cards()
        result = []
        for card in cards:
            title = self.get_card_title(card)
            value = self.get_card_value(card)
            if title:
                result.append({"title": title, "value": value})
        return result

    # ========== 图表验证 ==========

    def get_chart_containers(self) -> List[Locator]:
        """获取所有图表容器"""
        charts = self.page.locator(self.CHART_CONTAINER).all()
        logger.info(f"找到 {len(charts)} 个图表容器")
        return charts

    def get_chart_count(self) -> int:
        """获取图表数量"""
        return len(self.get_chart_containers())

    def has_canvas_elements(self) -> bool:
        """检查是否有 canvas 图表元素"""
        canvases = self.page.locator("canvas").all()
        return len(canvases) > 0

    # ========== 状态检查 ==========

    def is_loading(self) -> bool:
        """判断是否正在加载"""
        spin = self.page.locator(self.LOADING_SPIN).first
        return spin.is_visible(timeout=2000)

    def is_empty_state(self) -> bool:
        """判断是否为空状态"""
        empty = self.page.locator(self.EMPTY_STATE).first
        return empty.is_visible(timeout=3000)

    def has_error(self) -> bool:
        """判断是否有错误状态"""
        error = self.page.locator(self.ERROR_STATE).first
        return error.is_visible(timeout=2000)

    def click_retry(self) -> "AgentStatsPage":
        """点击重试按钮"""
        retry_btn = self.page.locator(self.RETRY_BUTTON).first
        if retry_btn.is_visible(timeout=3000):
            retry_btn.click()
            self.page.wait_for_timeout(1000)
            logger.info("点击重试按钮")
        return self

    # ========== 断言方法 ==========

    def assert_page_loaded(self, timeout: Optional[int] = None) -> "AgentStatsPage":
        """断言页面已加载"""
        timeout = timeout or self.timeout
        page_indicator = self.page.locator(
            f'{self.SUMMARY_CARD}, {self.EMPTY_STATE}, {self.DATE_RANGE_PICKER}'
        ).first
        expect(page_indicator).to_be_visible(timeout=timeout)
        return self

    def assert_card_count(self, expected: int, timeout: Optional[int] = None) -> "AgentStatsPage":
        """断言汇总卡片数量"""
        expect(self.page.locator(self.SUMMARY_CARD)).to_have_count(
            expected, timeout=timeout or self.timeout
        )
        return self
