# -*- coding: utf-8 -*-
"""
QwenPaw MCP 页面对象

封装 MCP 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class McpPage(BasePage):
    """
    MCP 页面对象
    
    封装 MCP 页面的所有用户操作：
    - MCP 客户端列表展示
    - 启用/禁用 MCP 客户端
    - 创建新的 MCP 客户端
    - 查看 MCP 配置信息
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/mcp"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    PAGE_LOAD_INDICATOR = MCP_CARD_SELECTOR = 'div[class*="mcpCard"]'
    
    # MCP 卡片相关
    MCP_CARD_SELECTOR = 'div[class*="mcpCard"]'
    TOGGLE_BTN_SELECTOR = 'button[class*="toggleButton"]'
    CREATE_BTN_SELECTOR = 'button.qwenpaw-btn-primary:has-text("创建客户端")'
    
    # 卡片内部元素
    CARD_TITLE_SELECTOR = 'h3[class*="mcpTitle"]'
    TYPE_BADGE_SELECTOR = 'span[class*="typeBadge"]'
    STATUS_TEXT_SELECTOR = 'span[class*="statusText"]'
    
    # 面包屑
    BREADCRUMB_SELECTOR = 'span[class*="breadcrumbCurrent"]:has-text("MCP")'
    
    # 创建对话框
    MODAL_CONTENT_SELECTOR = '.qwenpaw-modal-content'
    MODAL_TITLE_SELECTOR = '.qwenpaw-spark-modal-title'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "McpPage":
        """打开 MCP 页面"""
        logger.info("打开 MCP 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "McpPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== MCP 卡片操作方法 ==========
    
    def get_mcp_cards(self) -> List[Locator]:
        """获取所有 MCP 卡片"""
        cards = self.page.locator(self.MCP_CARD_SELECTOR).all()
        logger.info(f"找到 {len(cards)} 个 MCP 客户端卡片")
        return cards
    
    def get_card_name(self, card: Locator) -> str:
        """获取卡片名称"""
        title_el = card.locator(self.CARD_TITLE_SELECTOR).first
        expect(title_el).to_be_visible(timeout=5000)
        name = title_el.inner_text()
        logger.debug(f"卡片名称: {name}")
        return name
    
    def toggle_mcp(self, card: Locator) -> "McpPage":
        """切换 MCP 开关"""
        toggle_btn = card.locator(self.TOGGLE_BTN_SELECTOR).first
        expect(toggle_btn).to_be_visible(timeout=5000)
        toggle_btn.click()
        logger.info("切换 MCP 开关")
        return self
    
    def is_mcp_enabled(self, card: Locator) -> bool:
        """检查 MCP 是否启用"""
        status_el = card.locator(self.STATUS_TEXT_SELECTOR).first
        expect(status_el).to_be_visible(timeout=3000)
        status_text = status_el.inner_text()
        is_enabled = status_text == "已启用"
        logger.debug(f"MCP 状态: {'已启用' if is_enabled else '已禁用'}")
        return is_enabled
    
    def click_create_client(self) -> "McpPage":
        """点击创建客户端按钮"""
        create_btn = self.page.locator(self.CREATE_BTN_SELECTOR).first
        expect(create_btn).to_be_visible(timeout=5000)
        assert not create_btn.is_disabled(), "创建客户端按钮不应为 disabled"
        create_btn.click()
        logger.info("点击创建客户端按钮")
        return self
    
    def get_breadcrumb(self) -> str:
        """获取面包屑"""
        breadcrumb = self.page.locator(self.BREADCRUMB_SELECTOR).first
        expect(breadcrumb).to_be_visible(timeout=5000)
        breadcrumb_text = breadcrumb.inner_text()
        logger.debug(f"面包屑: {breadcrumb_text}")
        return breadcrumb_text
    
    # ========== 断言方法 ==========
    
    def assert_mcp_cards_exist(self, min_count: int = 1) -> "McpPage":
        """断言 MCP 卡片存在"""
        cards = self.get_mcp_cards()
        assert len(cards) >= min_count, f"至少应有 {min_count} 个 MCP 客户端，实际有 {len(cards)} 个"
        return self
    
    def assert_create_button_visible(self) -> "McpPage":
        """断言创建按钮可见"""
        create_btn = self.page.locator(self.CREATE_BTN_SELECTOR).first
        expect(create_btn).to_be_visible(timeout=5000)
        assert not create_btn.is_disabled(), "创建客户端按钮不应为 disabled"
        return self
    
    def assert_breadcrumb(self, expected_text: str = "MCP") -> "McpPage":
        """断言面包屑"""
        breadcrumb_text = self.get_breadcrumb()
        assert expected_text in breadcrumb_text, f"面包屑应包含 '{expected_text}'，实际为 '{breadcrumb_text}'"
        return self
