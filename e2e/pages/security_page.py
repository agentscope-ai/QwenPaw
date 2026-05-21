# -*- coding: utf-8 -*-
"""
QwenPaw Security 页面对象

封装 Security（安全防护）页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class SecurityPage(BasePage):
    """
    Security 页面对象
    
    封装安全防护页面的所有用户操作：
    - 工具防护 Tab
    - 文件防护 Tab
    - 防护开关切换
    - 配置保存
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/security"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    PAGE_LOAD_INDICATOR = '.qwenpaw-tabs-tab-btn'
    
    # Tabs
    TOOL_GUARD_TAB = '[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn'
    FILE_GUARD_TAB = '[data-node-key="fileGuard"] .qwenpaw-tabs-tab-btn'
    
    # 激活的面板
    ACTIVE_PANEL = '.qwenpaw-tabs-tabpane-active'
    
    # 防护开关
    GUARD_SWITCH = 'button.qwenpaw-switch[role="switch"]'
    
    # 保存按钮
    SAVE_BTN = 'button.qwenpaw-btn-primary:has-text("保存"), button:has-text("保 存")'
    
    # 受保护工具下拉框
    PROTECTED_TOOLS_SELECT = '.qwenpaw-select'
    
    # 文件防护路径输入框
    PATH_INPUT = 'input[placeholder*="文件或目录路径"]'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "SecurityPage":
        """打开 Security 页面"""
        logger.info("打开 Security 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "SecurityPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== Tab 操作方法 ==========
    
    def get_tool_guard_tab(self) -> Locator:
        """获取工具防护 Tab"""
        return self.page.locator(self.TOOL_GUARD_TAB).first
    
    def get_file_guard_tab(self) -> Locator:
        """获取文件防护 Tab"""
        return self.page.locator(self.FILE_GUARD_TAB).first
    
    def switch_to_tab(self, tab_name: str) -> "SecurityPage":
        """
        切换到指定 Tab
        
        Args:
            tab_name: Tab 名称，可选值："toolGuard", "fileGuard"
            
        Returns:
            self
        """
        if tab_name == "toolGuard":
            tab_locator = self.get_tool_guard_tab()
        elif tab_name == "fileGuard":
            tab_locator = self.get_file_guard_tab()
        else:
            raise ValueError(f"不支持的 Tab 名称：{tab_name}")
        
        expect(tab_locator).to_be_visible(timeout=self.timeout)
        tab_locator.click()
        self.page.wait_for_timeout(1500)
        
        # 验证面板已激活
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info(f"✅ 已切换到 {tab_name} Tab")
        return self
    
    # ========== 防护开关操作方法 ==========
    
    def get_guard_toggle(self) -> Locator:
        """获取当前激活面板中的防护开关"""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.GUARD_SWITCH).first
    
    def is_guard_enabled(self) -> bool:
        """检查防护是否启用"""
        switch = self.get_guard_toggle()
        if switch.count() > 0:
            aria_checked = switch.get_attribute('aria-checked')
            return aria_checked == 'true'
        return False
    
    def toggle_guard(self) -> "SecurityPage":
        """切换防护开关"""
        switch = self.get_guard_toggle()
        expect(switch).to_be_visible(timeout=self.timeout)
        switch.click()
        self.page.wait_for_timeout(1000)
        logger.info("✅ 防护开关已切换")
        return self
    
    def enable_guard(self) -> "SecurityPage":
        """启用防护"""
        if not self.is_guard_enabled():
            self.toggle_guard()
        return self
    
    def disable_guard(self) -> "SecurityPage":
        """禁用防护"""
        if self.is_guard_enabled():
            self.toggle_guard()
        return self
    
    # ========== 保存操作 ==========
    
    def click_save(self) -> "SecurityPage":
        """点击保存按钮"""
        save_btn = self.page.locator(self.SAVE_BTN).first
        if not save_btn.is_visible():
            # 尝试在 footer 中查找
            save_btn = self.page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first
        
        expect(save_btn).to_be_visible(timeout=self.timeout)
        save_btn.click()
        self.page.wait_for_timeout(2000)
        logger.info("✅ 已点击保存按钮")
        return self
    
    # ========== 其他操作方法 ==========
    
    def get_protected_tools_select(self) -> Locator:
        """获取受保护工具下拉框"""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.PROTECTED_TOOLS_SELECT).first
    
    def get_path_input(self) -> Locator:
        """获取文件防护路径输入框"""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.PATH_INPUT).first
    
    # ========== 断言方法 ==========
    
    def assert_guard_enabled(self) -> "SecurityPage":
        """断言防护已启用"""
        assert self.is_guard_enabled(), "防护应该是启用状态"
        return self
    
    def assert_guard_disabled(self) -> "SecurityPage":
        """断言防护已禁用"""
        assert not self.is_guard_enabled(), "防护应该是禁用状态"
        return self
    
    def assert_config_saved(self) -> "SecurityPage":
        """断言配置保存成功"""
        error_msg = self.page.locator('.qwenpaw-message-error')
        assert error_msg.count() == 0, "保存后出现错误消息"
        return self
