# -*- coding: utf-8 -*-
"""
QwenPaw Environments 页面对象

封装环境变量配置页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class EnvironmentsPage(BasePage):
    """
    Environments 页面对象
    
    封装环境变量配置页面的所有用户操作：
    - 打开环境变量页面
    - 获取环境变量行列表
    - 获取环境变量键名和值
    - 点击添加按钮
    - 点击保存按钮
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/environments"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    ENV_PAGE_CONTAINER = "div[class*=environmentsPage]"
    PAGE_LOAD_INDICATOR = ENV_PAGE_CONTAINER
    
    # 表格相关选择器
    ENV_TABLE = ".qwenpaw-table"
    ENV_ROW = ".qwenpaw-table-tbody tr"
    ADD_BTN = 'button:has-text("添加"), button:has-text("Add")'
    SAVE_BTN = 'button.qwenpaw-btn-primary:has-text("保存"), button:has-text("Save")'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "EnvironmentsPage":
        """打开 Environments 页面"""
        logger.info("打开 Environments 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== 环境变量操作方法 ==========
    
    def get_env_rows(self) -> List[Locator]:
        """获取所有环境变量行"""
        rows = self.page.locator(self.ENV_ROW).all()
        logger.info(f"找到 {len(rows)} 个环境变量行")
        return rows
    
    def get_env_key(self, row: Locator) -> str:
        """获取环境变量的键名"""
        # 尝试从第一列获取键名
        key_cell = row.locator("td").first
        if key_cell.count() > 0:
            return key_cell.inner_text().strip()
        return ""
    
    def get_env_value(self, row: Locator) -> str:
        """获取环境变量的值"""
        # 尝试从第二列获取值
        value_cells = row.locator("td").all()
        if len(value_cells) > 1:
            return value_cells[1].inner_text().strip()
        return ""
    
    def click_add(self) -> "EnvironmentsPage":
        """点击添加按钮"""
        add_btn = self.page.locator(self.ADD_BTN).first
        if add_btn.count() > 0:
            add_btn.click()
            logger.info("点击添加按钮")
        return self
    
    def click_save(self) -> "EnvironmentsPage":
        """点击保存按钮"""
        save_btn = self.page.locator(self.SAVE_BTN).first
        if save_btn.count() > 0:
            save_btn.click()
            logger.info("点击保存按钮")
        return self
    
    # ========== 断言方法 ==========
    
    def assert_env_row_count(self, expected_count: int, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """断言环境变量行数量"""
        expect(self.page.locator(self.ENV_ROW)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self
    
    def assert_env_exists(self, env_key: str, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """断言环境变量存在"""
        env_row = self.page.locator(self.ENV_ROW).filter(
            has_text=env_key
        ).first
        expect(env_row).to_be_visible(timeout=timeout or self.timeout)
        return self
