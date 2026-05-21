# -*- coding: utf-8 -*-
"""
QwenPaw Token Usage 页面对象

封装 Token 用量统计页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class TokenUsagePage(BasePage):
    """
    Token Usage 页面对象
    
    封装 Token 用量统计页面的所有用户操作：
    - 页面导航
    - 获取用量数据
    - 查看图表
    """
    
    PAGE_TITLE = "Token Usage"
    PAGE_URL = f"{config.base_url}/token-usage"
    
    # ========== 选择器定义 ==========
    
    # 表格相关
    USAGE_TABLE = ".qwenpaw-table"
    USAGE_ROW = ".qwenpaw-table-tbody tr"
    
    # 日期选择器
    DATE_PICKER = ".qwenpaw-picker"
    
    # 图表容器
    CHART_CONTAINER = 'div[class*="chart"], canvas'
    
    # ========== 初始化 ==========
    
    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("TokenUsagePage initialized")
    
    # ========== 页面导航 ==========
    
    def open(self) -> "TokenUsagePage":
        """打开 Token Usage 页面"""
        logger.info("Opening Token Usage page")
        self.goto()
        self.wait_for_loading()
        return self
    
    def wait_for_page_loaded(self) -> bool:
        """
        等待页面加载完成
        
        Returns:
            是否加载成功
        """
        try:
            self.wait_for_element(self.USAGE_TABLE, timeout=10000)
            return True
        except Exception as e:
            logger.error(f"Page load failed: {e}")
            return False
    
    # ========== 数据获取 ==========
    
    def get_usage_rows(self) -> List[Locator]:
        """
        获取所有用量行
        
        Returns:
            Locator 列表
        """
        logger.info("Getting usage rows")
        return self.find_all(self.USAGE_ROW)
    
    def get_chart(self) -> Optional[Locator]:
        """
        获取图表元素
        
        Returns:
            图表 Locator 或 None
        """
        logger.info("Getting chart element")
        try:
            chart = self.find(self.CHART_CONTAINER)
            if chart.count() > 0:
                return chart
            return None
        except Exception as e:
            logger.warning(f"Chart not found: {e}")
            return None
    
    def has_usage_data(self) -> bool:
        """
        检查是否有用量数据
        
        Returns:
            是否有数据
        """
        logger.info("Checking if usage data exists")
        try:
            rows = self.get_usage_rows()
            return len(rows) > 0
        except Exception:
            return False
