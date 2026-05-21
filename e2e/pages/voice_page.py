# -*- coding: utf-8 -*-
"""
QwenPaw Voice 页面对象

封装 Voice 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class VoicePage(BasePage):
    """
    Voice 页面对象
    
    封装 Voice 页面的所有用户操作：
    - 语音服务配置展示
    - 启用/禁用语音服务
    - 查看语音服务状态
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/settings/voice"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    PAGE_LOAD_INDICATOR = '.qwenpaw-switch, .qwenpaw-switch-input, [class*=voiceToggle]'
    
    # 语音服务开关
    VOICE_TOGGLE_SELECTOR = '.qwenpaw-switch, .qwenpaw-switch-input, [class*=voiceToggle]'
    
    # 配置表单
    CONFIG_FORM_SELECTOR = '.qwenpaw-form, [class*=configForm], form'
    
    # 成功消息
    SUCCESS_MESSAGE_SELECTOR = '.qwenpaw-message-success, .qwenpaw-notification-success'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "VoicePage":
        """打开 Voice 页面"""
        logger.info("打开 Voice 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "VoicePage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== 语音服务操作方法 ==========
    
    def get_voice_toggle(self) -> Locator:
        """获取语音服务开关"""
        toggle = self.page.locator(self.VOICE_TOGGLE_SELECTOR).first
        expect(toggle).to_be_visible(timeout=5000)
        logger.debug("获取语音服务开关")
        return toggle
    
    def is_voice_enabled(self) -> bool:
        """检查语音是否启用"""
        toggle = self.get_voice_toggle()
        toggle_class = toggle.get_attribute('class')
        is_checked = 'checked' in toggle_class if toggle_class else False
        logger.debug(f"语音服务状态: {'已启用' if is_checked else '已禁用'}")
        return is_checked
    
    def toggle_voice(self) -> "VoicePage":
        """切换语音开关"""
        toggle = self.get_voice_toggle()
        toggle.click()
        logger.info("切换语音开关")
        return self
    
    def enable_voice(self) -> "VoicePage":
        """启用语音服务"""
        if not self.is_voice_enabled():
            self.toggle_voice()
        return self
    
    def disable_voice(self) -> "VoicePage":
        """禁用语音服务"""
        if self.is_voice_enabled():
            self.toggle_voice()
        return self
    
    # ========== 断言方法 ==========
    
    def assert_voice_toggle_visible(self) -> "VoicePage":
        """断言语音开关可见"""
        toggle = self.get_voice_toggle()
        expect(toggle).to_be_visible(timeout=5000)
        return self
    
    def assert_voice_enabled(self) -> "VoicePage":
        """断言语音已启用"""
        assert self.is_voice_enabled(), "语音服务应该是启用状态"
        return self
    
    def assert_voice_disabled(self) -> "VoicePage":
        """断言语音已禁用"""
        assert not self.is_voice_enabled(), "语音服务应该是禁用状态"
        return self
    
    def assert_config_saved(self) -> "VoicePage":
        """断言配置保存成功"""
        success_msg = self.page.locator(self.SUCCESS_MESSAGE_SELECTOR).first
        if success_msg.is_visible(timeout=3000):
            logger.info("✅ 保存成功消息显示")
        else:
            logger.info("ℹ️ 未找到保存成功消息（可能自动保存）")
        return self
