# -*- coding: utf-8 -*-
"""
QwenPaw Tools 页面对象

封装工具管理页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class ToolsPage(BasePage):
    """
    Tools 页面对象
    
    封装工具管理页面的所有用户操作：
    - 打开工具页面
    - 获取工具卡片列表
    - 获取工具名称
    - 切换工具开关
    - 检查工具启用状态
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/tools"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    TOOL_PAGE_CONTAINER = "div[class*=toolsPage]"
    PAGE_LOAD_INDICATOR = TOOL_PAGE_CONTAINER
    
    # 工具卡片相关选择器
    TOOL_CARD = ".qwenpaw-card"
    SWITCH = ".qwenpaw-switch"
    BREADCRUMB = 'span[class*="breadcrumbCurrent"]'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "ToolsPage":
        """打开 Tools 页面"""
        logger.info("打开 Tools 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "ToolsPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== 工具列表操作方法 ==========
    
    def get_tool_cards(self) -> List[Locator]:
        """获取所有工具卡片"""
        cards = self.page.locator(self.TOOL_CARD).all()
        logger.info(f"找到 {len(cards)} 个工具卡片")
        return cards
    
    def get_tool_name(self, card: Locator) -> str:
        """获取工具名称"""
        # 尝试从卡片标题中获取工具名称
        title_element = card.locator('.ant-card-meta-title, .qwenpaw-card-meta-title, h3, h4, [class*="title"]').first
        if title_element.count() > 0:
            return title_element.inner_text()
        
        # 如果找不到标题，返回卡片的文本内容
        return card.inner_text().strip()[:50]
    
    def toggle_tool(self, card: Locator) -> "ToolsPage":
        """切换工具开关"""
        switch = card.locator(self.SWITCH).first
        if switch.count() > 0:
            switch.click()
            logger.info("切换工具开关")
        return self
    
    def is_tool_enabled(self, card: Locator) -> bool:
        """检查工具是否启用"""
        switch = card.locator(self.SWITCH).first
        if switch.count() > 0:
            return switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.classList.contains('ant-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
        return False
    
    # ========== 断言方法 ==========
    
    def assert_tool_count(self, expected_count: int, timeout: Optional[int] = None) -> "ToolsPage":
        """断言工具卡片数量"""
        expect(self.page.locator(self.TOOL_CARD)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self
    
    def assert_tool_exists(self, tool_name: str, timeout: Optional[int] = None) -> "ToolsPage":
        """断言工具存在"""
        tool_card = self.page.locator(self.TOOL_CARD).filter(
            has_text=tool_name
        ).first
        expect(tool_card).to_be_visible(timeout=timeout or self.timeout)
        return self
