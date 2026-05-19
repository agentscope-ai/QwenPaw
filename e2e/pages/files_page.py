# -*- coding: utf-8 -*-
"""
QwenPaw Files 页面对象

封装 Files 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class FilesPage(BasePage):
    """
    Files 页面对象
    
    封装 Files 页面的所有用户操作：
    - 打开文件页面
    - 获取文件列表
    - 获取文件名和元信息
    - 点击文件打开编辑器
    - 切换文件开关
    - 检查文件启用状态
    """
    
    PAGE_TITLE = "QwenPaw Console"
    WORKSPACE_URL = f"{config.base_url}/workspace"
    PAGE_URL = WORKSPACE_URL
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    PAGE_LOAD_INDICATOR = 'div[class*="fileItem"]'
    
    # 文件项相关选择器
    FILE_ITEM_SELECTOR = 'div[class*="fileItem"]'
    FILE_NAME_SELECTOR = 'div[class*="fileItemName"]'
    FILE_META_SELECTOR = 'div[class*="fileItemMeta"]'
    SWITCH_SELECTOR = 'button.qwenpaw-switch[role="switch"]'
    DRAG_HANDLE_SELECTOR = 'div[class*="dragHandle"]'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "FilesPage":
        """打开 Files 页面"""
        logger.info("打开 Files 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "FilesPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== 文件列表操作方法 ==========
    
    def get_file_items(self) -> List[Locator]:
        """获取所有文件项"""
        items = self.page.locator(self.FILE_ITEM_SELECTOR).all()
        logger.info(f"找到 {len(items)} 个文件项")
        return items
    
    def get_file_name(self, item: Locator) -> str:
        """获取文件名"""
        name_element = item.locator(self.FILE_NAME_SELECTOR).first
        if name_element.count() > 0:
            return name_element.inner_text()
        return ""
    
    def get_file_meta(self, item: Locator) -> str:
        """获取文件元信息"""
        meta_element = item.locator(self.FILE_META_SELECTOR).first
        if meta_element.count() > 0:
            return meta_element.inner_text()
        return ""
    
    def click_file(self, item: Locator) -> "FilesPage":
        """点击文件打开编辑器"""
        item.click()
        logger.info("点击文件打开编辑器")
        return self
    
    def toggle_file_switch(self, item: Locator) -> "FilesPage":
        """切换文件开关"""
        switch = item.locator(self.SWITCH_SELECTOR).first
        if switch.count() > 0:
            switch.click()
            logger.info("切换文件开关")
        return self
    
    def is_file_enabled(self, item: Locator) -> bool:
        """检查文件是否启用"""
        switch = item.locator(self.SWITCH_SELECTOR).first
        if switch.count() > 0:
            return switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
        return False
    
    # ========== 断言方法 ==========
    
    def assert_file_count(self, expected_count: int, timeout: Optional[int] = None) -> "FilesPage":
        """断言文件数量"""
        expect(self.page.locator(self.FILE_ITEM_SELECTOR)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self
    
    def assert_file_exists(self, file_name: str, timeout: Optional[int] = None) -> "FilesPage":
        """断言文件存在"""
        file_item = self.page.locator(self.FILE_ITEM_SELECTOR).filter(
            has=self.page.locator(self.FILE_NAME_SELECTOR).filter(has_text=file_name)
        ).first
        expect(file_item).to_be_visible(timeout=timeout or self.timeout)
        return self
