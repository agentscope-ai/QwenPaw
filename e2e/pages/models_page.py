# -*- coding: utf-8 -*-
"""
QwenPaw Models 页面对象

封装 Models 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class ModelsPage(BasePage):
    """
    Models 页面对象
    
    封装 Models 页面的所有用户操作：
    - 打开模型页面
    - 获取面包屑
    - 点击下载模型按钮
    - 获取模型列表
    """
    
    PAGE_TITLE = "QwenPaw Console"
    MODELS_URL = f"{config.base_url}/models"
    PAGE_URL = MODELS_URL
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    PAGE_LOAD_INDICATOR = '.ant-breadcrumb, .qwenpaw-breadcrumb, h1, h2, [class*="breadcrumb"]'
    
    # 面包屑
    BREADCRUMB_SELECTOR = '.ant-breadcrumb, .qwenpaw-breadcrumb, nav[class*="breadcrumb"], [class*="Breadcrumb"]'
    
    # 下载模型按钮
    DOWNLOAD_MODEL_BTN = 'button:has-text("下载模型"), button:has-text("Download Model"), button:has-text("下载"), button:has-text("Download")'
    
    # 模型列表
    MODEL_LIST_SELECTOR = '.ant-list-item, .qwenpaw-list-item, [class*="modelItem"], [class*="model-item"], table tbody tr, .ant-table-row, .qwenpaw-table-row'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "ModelsPage":
        """打开 Models 页面"""
        logger.info("打开 Models 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "ModelsPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== 页面元素操作方法 ==========
    
    def get_breadcrumb(self) -> str:
        """获取面包屑文本"""
        breadcrumb = self.page.locator(self.BREADCRUMB_SELECTOR).first
        if breadcrumb.count() > 0:
            return breadcrumb.inner_text()
        return ""
    
    def click_download_model(self) -> "ModelsPage":
        """点击下载模型按钮"""
        download_btn = self.page.locator(self.DOWNLOAD_MODEL_BTN).first
        if download_btn.count() > 0:
            download_btn.click()
            logger.info("点击下载模型按钮")
        else:
            logger.warning("未找到下载模型按钮")
        return self
    
    def get_model_list(self) -> List[Locator]:
        """获取模型列表"""
        models = self.page.locator(self.MODEL_LIST_SELECTOR).all()
        logger.info(f"找到 {len(models)} 个模型")
        return models
    
    # ========== 断言方法 ==========
    
    def assert_breadcrumb_contains(self, expected_text: str, timeout: Optional[int] = None) -> "ModelsPage":
        """断言面包屑包含指定文本"""
        breadcrumb = self.page.locator(self.BREADCRUMB_SELECTOR).first
        expect(breadcrumb).to_contain_text(expected_text, timeout=timeout or self.timeout)
        return self
    
    def assert_model_count(self, expected_count: int, timeout: Optional[int] = None) -> "ModelsPage":
        """断言模型数量"""
        expect(self.page.locator(self.MODEL_LIST_SELECTOR)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self
    
    def assert_download_button_visible(self, timeout: Optional[int] = None) -> "ModelsPage":
        """断言下载按钮可见"""
        download_btn = self.page.locator(self.DOWNLOAD_MODEL_BTN).first
        expect(download_btn).to_be_visible(timeout=timeout or self.timeout)
        return self
