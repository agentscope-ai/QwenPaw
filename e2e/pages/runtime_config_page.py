# -*- coding: utf-8 -*-
"""
QwenPaw Runtime Config 页面对象

封装运行配置（Agent Config）页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class RuntimeConfigPage(BasePage):
    """
    Runtime Config 页面对象
    
    封装运行配置页面的所有用户操作：
    - ReAct 智能体 Tab
    - 语言下拉选择
    - 时区显示
    - 配置保存
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/agent-config"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    PAGE_LOAD_INDICATOR = '.qwenpaw-tabs-tab-btn'
    
    # Tabs
    REACT_TAB = '[data-node-key="reactAgent"] .qwenpaw-tabs-tab-btn'
    LLM_RETRY_TAB = '[data-node-key="llmRetry"] .qwenpaw-tabs-tab-btn'
    LLM_RATE_LIMITER_TAB = '[data-node-key="llmRateLimiter"] .qwenpaw-tabs-tab-btn'
    CONTEXT_COMPACT_TAB = '[data-node-key="lightContext"] .qwenpaw-tabs-tab-btn'
    TOOL_RESULT_COMPACT_TAB = '[data-node-key="lightContext"] .qwenpaw-tabs-tab-btn'  # 已合并到上下文管理 Tab
    MEMORY_SUMMARY_TAB = '[data-node-key="remeLightMemory"] .qwenpaw-tabs-tab-btn'
    EMBEDDING_CONFIG_TAB = '[data-node-key="remeLightMemory"] .qwenpaw-tabs-tab-btn'  # 向量模型配置已合并到长期记忆 Tab
    TOOL_EXECUTION_LEVEL_TAB = '[data-node-key="toolExecutionLevel"] .qwenpaw-tabs-tab-btn'
    
    # 激活的面板
    ACTIVE_PANEL = '.qwenpaw-tabs-tabpane-active'
    
    # 语言下拉框
    LANGUAGE_SELECT = '.qwenpaw-select'
    
    # 时区显示
    TIMEZONE_DISPLAY = '.qwenpaw-select-selection-item'
    
    # ReAct Tab 表单字段
    MAX_ITERS_INPUT = '#max_iters'
    AUTO_CONTINUE_SWITCH = '#auto_continue_on_text_only'
    MEMORY_BACKEND_SELECT = '#memory_manager_backend'
    MAX_INPUT_LENGTH_INPUT = '#max_input_length'
    
    # 保存按钮
    SAVE_BTN = 'button.qwenpaw-btn-primary:has-text("保存"), button:has-text("保 存")'
    RESET_BTN = 'button:has-text("重置"), button:has-text("重 置")'
    
    # 卡片标题
    CARD_TITLE = '.qwenpaw-spark-title'
    
    # 通用表单元素
    SWITCH = '.qwenpaw-switch'
    INPUT_NUMBER = '.qwenpaw-input-number-input'
    SLIDER = '.qwenpaw-slider'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "RuntimeConfigPage":
        """打开 Runtime Config 页面"""
        logger.info("打开 Runtime Config 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "RuntimeConfigPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== Tab 操作方法 ==========
    
    def get_react_tab(self) -> Locator:
        """获取 ReAct 智能体 Tab"""
        return self.page.locator(self.REACT_TAB).first
    
    def switch_to_react_tab(self) -> "RuntimeConfigPage":
        """切换到 ReAct 智能体 Tab"""
        tab = self.get_react_tab()
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)
        
        # 验证面板已激活
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info("✅ 已切换到 ReAct 智能体 Tab")
        return self
    
    def switch_to_llm_retry_tab(self) -> "RuntimeConfigPage":
        """切换到 LLM 自动重试 Tab"""
        tab = self.page.locator(self.LLM_RETRY_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)
        
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info("✅ 已切换到 LLM 自动重试 Tab")
        return self
    
    def switch_to_llm_rate_limiter_tab(self) -> "RuntimeConfigPage":
        """切换到 LLM 并发限流 Tab"""
        tab = self.page.locator(self.LLM_RATE_LIMITER_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)
        
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info("✅ 已切换到 LLM 并发限流 Tab")
        return self
    
    def switch_to_context_compact_tab(self) -> "RuntimeConfigPage":
        """切换到上下文压缩 Tab"""
        tab = self.page.locator(self.CONTEXT_COMPACT_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)
        
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info("✅ 已切换到上下文压缩 Tab")
        return self
    
    def switch_to_tool_result_compact_tab(self) -> "RuntimeConfigPage":
        """切换到工具结果压缩配置 Tab"""
        tab = self.page.locator(self.TOOL_RESULT_COMPACT_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)
        
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info("✅ 已切换到工具结果压缩配置 Tab")
        return self
    
    def switch_to_memory_summary_tab(self) -> "RuntimeConfigPage":
        """切换到长期记忆配置 Tab"""
        tab = self.page.locator(self.MEMORY_SUMMARY_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)
        
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info("✅ 已切换到长期记忆配置 Tab")
        return self
    
    def switch_to_embedding_config_tab(self) -> "RuntimeConfigPage":
        """切换到向量模型配置 Tab"""
        tab = self.page.locator(self.EMBEDDING_CONFIG_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)
        
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info("✅ 已切换到向量模型配置 Tab")
        return self
    
    def switch_to_tab(self, tab_key: str) -> "RuntimeConfigPage":
        """
        通用 Tab 切换方法
        
        Args:
            tab_key: Tab 的 data-node-key 值，如 "reactAgent", "llmRetry" 等
        """
        tab_selector = f'[data-node-key="{tab_key}"] .qwenpaw-tabs-tab-btn'
        tab = self.page.locator(tab_selector).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)
        
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)
        
        logger.info(f"✅ 已切换到 Tab: {tab_key}")
        return self
    
    # ========== ReAct Tab 字段操作方法 ==========
    
    def get_max_iters(self) -> str:
        """获取最大迭代次数"""
        input_el = self.page.locator(self.MAX_ITERS_INPUT).first
        return input_el.input_value() if input_el.is_visible() else ""
    
    def set_max_iters(self, value: int) -> "RuntimeConfigPage":
        """设置最大迭代次数"""
        input_el = self.page.locator(self.MAX_ITERS_INPUT).first
        expect(input_el).to_be_visible(timeout=self.timeout)
        input_el.fill(str(value))
        logger.info(f"✅ 已设置最大迭代次数：{value}")
        return self
    
    def is_auto_continue_enabled(self) -> bool:
        """检查纯文本步骤自动续跑是否启用"""
        switch = self.page.locator(self.AUTO_CONTINUE_SWITCH).first
        if switch.count() > 0:
            return switch.get_attribute("aria-checked") == "true"
        return False
    
    def toggle_auto_continue(self) -> "RuntimeConfigPage":
        """切换纯文本步骤自动续跑开关"""
        switch = self.page.locator(self.AUTO_CONTINUE_SWITCH).first
        expect(switch).to_be_visible(timeout=self.timeout)
        switch.click()
        self.page.wait_for_timeout(500)
        logger.info("✅ 已切换纯文本步骤自动续跑开关")
        return self
    
    def get_memory_backend(self) -> str:
        """获取当前记忆管理后端"""
        select = self.page.locator(self.MEMORY_BACKEND_SELECT).first
        if select.is_visible():
            selection = select.locator('.qwenpaw-select-selection-item').first
            return selection.inner_text() if selection.is_visible() else ""
        return ""
    
    def get_max_input_length(self) -> str:
        """获取最大上下文长度"""
        input_el = self.page.locator(self.MAX_INPUT_LENGTH_INPUT).first
        return input_el.input_value() if input_el.is_visible() else ""
    
    def set_max_input_length(self, value: int) -> "RuntimeConfigPage":
        """设置最大上下文长度"""
        input_el = self.page.locator(self.MAX_INPUT_LENGTH_INPUT).first
        expect(input_el).to_be_visible(timeout=self.timeout)
        input_el.fill(str(value))
        logger.info(f"✅ 已设置最大上下文长度：{value}")
        return self
    
    # ========== 通用面板操作方法 ==========
    
    def get_active_panel_switches(self) -> List[Locator]:
        """获取当前激活面板中的所有开关"""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.SWITCH).all()
    
    def get_active_panel_inputs(self) -> List[Locator]:
        """获取当前激活面板中的所有数字输入框"""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.INPUT_NUMBER).all()
    
    def get_active_panel_sliders(self) -> List[Locator]:
        """获取当前激活面板中的所有滑块"""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.SLIDER).all()
    
    def click_reset(self) -> "RuntimeConfigPage":
        """点击重置按钮"""
        reset_btn = self.page.locator(self.RESET_BTN).first
        expect(reset_btn).to_be_visible(timeout=self.timeout)
        reset_btn.click()
        self.page.wait_for_timeout(2000)
        logger.info("✅ 已点击重置按钮")
        return self
    
    # ========== 语言选择操作方法 ==========
    
    def get_language_select(self) -> Locator:
        """获取语言下拉框"""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.LANGUAGE_SELECT).first
    
    def select_language(self, language: str) -> "RuntimeConfigPage":
        """
        选择语言
        
        Args:
            language: 语言名称，如 "English", "中文"
            
        Returns:
            self
        """
        language_select = self.get_language_select()
        expect(language_select).to_be_visible(timeout=self.timeout)
        
        # 点击展开下拉
        language_select.click()
        self.page.wait_for_timeout(1000)
        
        # 选择选项
        dropdown = self.page.locator('.qwenpaw-select-dropdown:visible').first
        if dropdown.is_visible():
            option = dropdown.locator(f'.qwenpaw-select-item-option:has-text("{language}")').first
            expect(option).to_be_visible(timeout=self.timeout)
            option.click()
            self.page.wait_for_timeout(500)
            logger.info(f"✅ 已选择语言：{language}")
        else:
            logger.warning("语言下拉选项未展开")
            self.page.keyboard.press("Escape")
        
        return self
    
    def get_current_language(self) -> str:
        """获取当前选中的语言"""
        language_select = self.get_language_select()
        selection_item = language_select.locator('.qwenpaw-select-selection-item').first
        return selection_item.inner_text()
    
    # ========== 时区操作方法 ==========
    
    def get_timezone_display(self) -> Locator:
        """获取时区显示元素"""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        selects = active_panel.locator(self.LANGUAGE_SELECT).all()
        # 时区是第二个 select
        if len(selects) >= 2:
            return selects[1]
        return selects[0] if len(selects) > 0 else self.page.locator('.qwenpaw-select').last
    
    def get_current_timezone(self) -> str:
        """获取当前时区"""
        timezone_select = self.get_timezone_display()
        selection_item = timezone_select.locator(self.TIMEZONE_DISPLAY).first
        return selection_item.inner_text()
    
    # ========== 保存操作 ==========
    
    def get_save_button(self) -> Locator:
        """获取保存按钮"""
        return self.page.locator(self.SAVE_BTN).first
    
    def click_save(self) -> "RuntimeConfigPage":
        """点击保存按钮"""
        save_btn = self.get_save_button()
        if not save_btn.is_visible():
            # 尝试在 footer 中查找
            save_btn = self.page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first
        
        expect(save_btn).to_be_visible(timeout=self.timeout)
        save_btn.click()
        self.page.wait_for_timeout(2000)
        logger.info("✅ 已点击保存按钮")
        return self
    
    # ========== 断言方法 ==========
    
    def assert_react_tab_active(self) -> "RuntimeConfigPage":
        """断言 ReAct 智能体 Tab 已激活"""
        card_title = self.page.locator(self.ACTIVE_PANEL).locator(self.CARD_TITLE).first
        expect(card_title).to_be_visible(timeout=self.timeout)
        title_text = card_title.inner_text()
        assert "ReAct" in title_text, f"卡片标题不包含 ReAct：{title_text}"
        return self
    
    def assert_config_saved(self) -> "RuntimeConfigPage":
        """断言配置保存成功"""
        error_msg = self.page.locator('.qwenpaw-message-error')
        assert error_msg.count() == 0, "保存后出现错误消息"
        return self
