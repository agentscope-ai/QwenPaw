# -*- coding: utf-8 -*-
"""
QwenPaw Channels 页面对象

封装 Channels 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class ChannelsPage(BasePage):
    """
    Channels 页面对象
    
    封装 Channels 页面的所有用户操作：
    - 频道列表展示
    - 频道过滤（All/Built-in/Custom）
    - 频道配置编辑
    - 启用/禁用频道
    - 频道配置保存/取消
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/channels"
    
    # ========== 选择器定义 ==========
    # 基于 console/src/pages/Control/Channels/index.tsx 和 index.module.less
    
    # 页面加载标志（页面无 h1，使用频道卡片作为加载完成标志）
    PAGE_LOAD_INDICATOR = '[class*=channelCard]'
    
    # 过滤按钮（UI 文本为中文，使用 button[class*=filterTab] 精确匹配按钮而非父容器）
    FILTER_ALL_BTN = 'button[class*=filterTab]:has-text("全部"), button:has-text("All")'
    FILTER_BUILTIN_BTN = 'button[class*=filterTab]:has-text("内置"), button:has-text("Built-in")'
    FILTER_CUSTOM_BTN = 'button[class*=filterTab]:has-text("自定义"), button:has-text("Custom")'
    
    # 频道卡片
    CHANNEL_CARD = '[class*=channelCard]'
    CHANNEL_CARD_ENABLED = '[class*=channelCard][class*=enabled]'
    CHANNEL_CARD_DISABLED = '[class*=channelCard]:not([class*=enabled])'
    
    # 频道卡片内容
    CHANNEL_ICON = '[class*=channelCard] [class*=icon]'
    CHANNEL_NAME = '[class*=channelCard] [class*=name]'
    CHANNEL_STATUS_DOT = '[class*=channelCard] [class*=statusDot]'
    CHANNEL_STATUS_TEXT = '[class*=channelCard] [class*=statusText]'
    CHANNEL_BUILTIN_TAG = '[class*=channelCard] [class*=builtinTag]'
    CHANNEL_CUSTOM_TAG = '[class*=channelCard] [class*=customTag]'
    CHANNEL_BOT_PREFIX = '[class*=channelCard] [class*=botPrefix]'
    
    # 编辑抽屉（改为只匹配可见的抽屉，避免 strict mode violation）
    CHANNEL_DRAWER = '.qwenpaw-drawer:visible, .ant-drawer:visible'
    DRAWER_TITLE = '.qwenpaw-drawer-title, .ant-drawer-title'
    DRAWER_CLOSE_BTN = '.qwenpaw-drawer-close, .ant-drawer-close'
    
    # 表单字段
    FORM_ITEM = '.ant-form-item, .qwenpaw-form-item'
    FORM_LABEL = '.ant-form-item-label, .qwenpaw-form-item-label'
    FORM_INPUT = 'input.ant-input, input.qwenpaw-input'
    FORM_SWITCH = '.ant-switch, .qwenpaw-switch'
    FORM_SELECT = '.ant-select-selector, .qwenpaw-select-selector'
    FORM_SUBMIT_BTN = '.qwenpaw-drawer button:has-text("保 存"), .qwenpaw-drawer button:has-text("保存"), .qwenpaw-drawer button:has-text("Save"), .ant-drawer button:has-text("Save")'
    FORM_CANCEL_BTN = '.qwenpaw-drawer button:has-text("取 消"), .qwenpaw-drawer button:has-text("取消"), .qwenpaw-drawer button:has-text("Cancel"), .ant-drawer button:has-text("Cancel")'
    
    # 特定字段选择器（根据 channel type 动态构建）
    BOT_PREFIX_INPUT = '.qwenpaw-drawer input[placeholder*="@bot"], .qwenpaw-drawer input[placeholder*="bot prefix" i], input[placeholder*="Bot Prefix" i], input[placeholder*="机器人前缀" i]'
    ENABLE_TOGGLE = '.ant-switch, .qwenpaw-switch'
    
    # 消息提示和加载状态（继承自 BasePage，此处无需重复定义）
    
    # ========== 初始化 ==========
    
    def __init__(self, page: Page):
        super().__init__(page)
    
    # ========== 导航方法 ==========
    
    def open(self) -> "ChannelsPage":
        """打开 Channels 页面"""
        logger.info("Opening Channels page")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "ChannelsPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        logger.info("Waiting for Channels page to load")
        
        # 等待频道卡片出现（页面无 h1 标签）
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        
        return self
    
    # ========== 过滤功能 ==========
    
    def click_filter_all(self) -> "ChannelsPage":
        """点击 All 过滤按钮"""
        logger.info("Clicking 'All' filter")
        self.page.locator(self.FILTER_ALL_BTN).first.click()
        self.page.wait_for_timeout(500)  # 等待 DOM 更新
        self.wait_for_loading()
        return self
    
    def click_filter_builtin(self) -> "ChannelsPage":
        """点击 Built-in 过滤按钮"""
        logger.info("Clicking 'Built-in' filter")
        self.page.locator(self.FILTER_BUILTIN_BTN).first.click()
        self.page.wait_for_timeout(500)  # 等待 DOM 更新
        self.wait_for_loading()
        return self
    
    def click_filter_custom(self) -> "ChannelsPage":
        """点击 Custom 过滤按钮"""
        logger.info("Clicking 'Custom' filter")
        self.page.locator(self.FILTER_CUSTOM_BTN).first.click()
        self.page.wait_for_timeout(500)  # 等待 DOM 更新
        self.wait_for_loading()
        return self
    
    # ========== 频道卡片操作 ==========
    
    def get_channel_cards(self) -> List[Locator]:
        """获取所有频道卡片"""
        return self.page.locator(self.CHANNEL_CARD).all()
    
    def get_channel_card_count(self) -> int:
        """获取频道卡片数量"""
        return len(self.get_channel_cards())
    
    # 中英文频道名别名映射：测试用例可能用中文，但前端 UI 显示英文（或反之）
    # 这里把所有可能的别名拢在一起，使 find_channel_card 能跨语言命中
    _CHANNEL_NAME_ALIASES = {
        "钉钉": ["DingTalk", "Dingtalk", "dingtalk", "钉钉"],
        "DingTalk": ["DingTalk", "Dingtalk", "dingtalk", "钉钉"],
        "飞书": ["Feishu", "feishu", "Lark", "飞书"],
        "Feishu": ["Feishu", "feishu", "Lark", "飞书"],
        "微信": ["WeChat", "Wechat", "wechat", "微信"],
        "WeChat": ["WeChat", "Wechat", "wechat", "微信"],
        "企业微信": ["WeCom", "Wecom", "wecom", "企业微信", "WeChat Work"],
        "WeCom": ["WeCom", "Wecom", "wecom", "企业微信"],
        "控制台": ["Console", "console", "控制台"],
        "Console": ["Console", "console", "控制台"],
    }

    def _resolve_channel_aliases(self, channel_name: str) -> List[str]:
        """把测试用例传入的中英文名扩展为所有候选别名（含原名）。"""
        aliases = self._CHANNEL_NAME_ALIASES.get(channel_name)
        if aliases:
            # 把原名也放在第一位（如果不在）
            if channel_name not in aliases:
                return [channel_name] + aliases
            return aliases
        return [channel_name]

    def find_channel_card(self, channel_name: str) -> Optional[Locator]:
        """
        根据频道名称查找频道卡片（支持中英文别名自动兜底）。

        Args:
            channel_name: 频道名称（如 DingTalk/钉钉, Feishu/飞书, Discord 等）

        Returns:
            频道卡片 Locator，未找到返回 None
        """
        candidates = self._resolve_channel_aliases(channel_name)
        cards = self.get_channel_cards()
        for card in cards:
            try:
                # 获取卡片的完整文本内容，因为频道名称可能不在单独的元素中
                card_text = card.inner_text()
                for cand in candidates:
                    if cand in card_text:
                        return card
            except Exception:
                continue
        return None
    
    def click_channel_card(self, channel_name: str) -> "ChannelsPage":
        """
        点击频道卡片打开编辑弹窗
        
        Args:
            channel_name: 频道名称
        """
        logger.info(f"Clicking channel card: {channel_name}")
        card = self.find_channel_card(channel_name)
        if card:
            card.click()
            self.page.wait_for_timeout(1000)
        else:
            raise Exception(f"Channel card not found: {channel_name}")
        return self
    
    def get_channel_status(self, channel_name: str) -> str:
        """
        获取频道状态（enabled/disabled）
        
        Args:
            channel_name: 频道名称
            
        Returns:
            'enabled' 或 'disabled'
        """
        card = self.find_channel_card(channel_name)
        if not card:
            raise Exception(f"Channel card not found: {channel_name}")
        
        card_text = card.inner_text()
        if '已启用' in card_text or 'Enabled' in card_text:
            return 'enabled'
        return 'disabled'
    
    def get_channel_bot_prefix(self, channel_name: str) -> str:
        """
        获取频道的 Bot Prefix 配置
        
        Args:
            channel_name: 频道名称
            
        Returns:
            Bot Prefix 文本
        """
        card = self.find_channel_card(channel_name)
        if not card:
            raise Exception(f"Channel card not found: {channel_name}")
        
        try:
            card_text = card.inner_text()
            # 从卡片文本中提取 "机器人前缀: xxx" 或 "Bot Prefix: xxx"
            for line in card_text.split("\n"):
                line = line.strip()
                if "机器人前缀:" in line or "Bot Prefix:" in line or "bot prefix:" in line:
                    prefix = line.split(":")[-1].strip()
                    if prefix == "Not Set" or prefix == "未设置":
                        return ""
                    return prefix
            return ""
        except Exception:
            return ""
    
    def is_builtin_channel(self, channel_name: str) -> bool:
        """
        判断频道是否为内置频道
        
        Args:
            channel_name: 频道名称
            
        Returns:
            True 如果是内置频道
        """
        card = self.find_channel_card(channel_name)
        if not card:
            raise Exception(f"Channel card not found: {channel_name}")
        
        try:
            # 检查卡片文本中是否包含"内置"或"Built-in"
            card_text = card.inner_text()
            return "内置" in card_text or "Built-in" in card_text
        except Exception:
            try:
                return not card.locator(self.CHANNEL_CUSTOM_TAG).first.is_visible()
            except Exception:
                return True  # 默认认为是内置
    
    # ========== 编辑弹窗/抽屉操作 ==========
    
    def wait_for_drawer_open(self, timeout: Optional[int] = None) -> bool:
        """等待编辑抽屉打开"""
        timeout = timeout or self.timeout
        logger.info("Waiting for drawer to open")
        try:
            self.page.locator('.qwenpaw-drawer, .ant-drawer').first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False
    
    def wait_for_drawer_close(self, timeout: Optional[int] = None) -> "ChannelsPage":
        """等待编辑抽屉关闭"""
        timeout = timeout or self.timeout
        logger.info("Waiting for drawer to close")
        self.page.wait_for_timeout(500)
        return self
    
    def close_drawer(self) -> "ChannelsPage":
        """关闭编辑抽屉"""
        logger.info("Closing drawer")
        close_btn = self.page.locator(self.DRAWER_CLOSE_BTN)
        if close_btn.count() > 0 and close_btn.first.is_visible():
            close_btn.first.click()
            self.page.wait_for_timeout(500)
        return self
    
    def get_drawer_title(self) -> str:
        """获取抽屉标题"""
        try:
            return self.page.locator(self.DRAWER_TITLE).first.inner_text()
        except Exception:
            return ""
    
    # ========== 表单操作 ==========
    
    def fill_bot_prefix(self, prefix: str) -> "ChannelsPage":
        """
        填写 Bot Prefix
        
        Args:
            prefix: Bot Prefix 值
        """
        logger.info(f"Filling bot prefix: {prefix}")
        bot_input = self.page.locator('#bot_prefix, input[placeholder*="@bot"], input[placeholder*="bot prefix" i]')
        if bot_input.count() > 0:
            bot_input.first.clear()
            bot_input.first.fill(prefix)
        return self
    
    def toggle_enable(self, enable: bool = True) -> "ChannelsPage":
        """
        切换启用状态
        
        Args:
            enable: True 启用，False 禁用
        """
        logger.info(f"Toggling enable to: {enable}")
        # 在抽屉内查找开关
        drawer = self.page.locator('.qwenpaw-drawer, .ant-drawer')
        switch = drawer.locator('.qwenpaw-switch, .ant-switch').first
        
        # 获取当前状态
        aria_checked = switch.get_attribute('aria-checked') or 'false'
        is_enabled = aria_checked == 'true'
        
        # 如果需要切换状态则点击
        if is_enabled != enable:
            switch.click()
            self.page.wait_for_timeout(500)
        
        return self
    
    def fill_form_field(self, field_name: str, value: str) -> "ChannelsPage":
        """
        填写表单字段
        
        Args:
            field_name: 字段名称
            value: 字段值
        """
        logger.info(f"Filling field '{field_name}' with value: {value}")
        # 根据字段类型选择填写方式
        try:
            input_elem = self.page.locator(f'input[placeholder*="{field_name}" i], input[label*="{field_name}" i]').first
            input_elem.fill(value)
        except Exception:
            # 备用：使用通用输入框
            self.page.locator(self.FORM_INPUT).first.fill(value)
        return self
    
    def save_channel_config(self) -> "ChannelsPage":
        """保存频道配置（保存后抽屉不会自动关闭）"""
        logger.info("Saving channel configuration")
        submit_btn = self.page.locator(self.FORM_SUBMIT_BTN).first
        # 使用 expect_response 等待保存 API 请求完成
        try:
            with self.page.expect_response(
                lambda resp: '/api/config/channel' in resp.url and resp.request.method in ('PUT', 'POST', 'PATCH'),
                timeout=10000
            ) as response_info:
                submit_btn.click()
            response = response_info.value
            logger.info(f"Save API response: status={response.status}")
            if not response.ok:
                logger.warning(f"Save API returned non-OK status: {response.status}")
        except Exception:
            # API 响应未捕获——可能是前端校验阻止了请求
            logger.warning("未捕获到保存 API 响应，可能存在前端校验错误")
            self.page.wait_for_timeout(2000)
        return self

    def has_form_validation_errors(self) -> bool:
        """检查表单是否存在校验错误"""
        errors = self.page.locator(
            '.qwenpaw-form-item-explain-error, .ant-form-item-explain-error'
        )
        count = errors.count()
        if count > 0:
            for i in range(count):
                logger.warning(f"表单校验错误: {errors.nth(i).inner_text()}")
        return count > 0
    
    def cancel_channel_config(self) -> "ChannelsPage":
        """取消频道配置"""
        logger.info("Canceling channel configuration")
        self.page.locator(self.FORM_CANCEL_BTN).first.click()
        self.wait_for_drawer_close()
        return self
    
    # ========== 验证方法 ==========
    
    def verify_channel_card_visible(self, channel_name: str) -> bool:
        """验证频道卡片可见"""
        card = self.find_channel_card(channel_name)
        return card is not None and card.is_visible()
    
    def verify_channel_count(self, expected_count: int) -> bool:
        """验证频道卡片数量"""
        actual_count = self.get_channel_card_count()
        logger.info(f"Channel count: {actual_count}, expected: {expected_count}")
        return actual_count == expected_count
    
    def verify_filter_result(self, filter_type: str) -> bool:
        """
        验证过滤结果
        
        Args:
            filter_type: 'all', 'builtin', 'custom'
        """
        cards = self.get_channel_cards()
        if filter_type == 'all':
            return len(cards) > 0
        elif filter_type == 'builtin':
            # 所有卡片都应该是内置的
            for card in cards:
                try:
                    card_text = card.inner_text()
                    if "内置" not in card_text and "Built-in" not in card_text:
                        return False
                except Exception:
                    return False
            return len(cards) > 0
        elif filter_type == 'custom':
            # 所有卡片都应该是自定义的
            for card in cards:
                try:
                    card_text = card.inner_text()
                    if "自定义" not in card_text and "Custom" not in card_text:
                        return False
                except Exception:
                    return False
            return len(cards) > 0
        return False
    
    def wait_for_success_message(self, timeout: int = 5000) -> bool:
        """等待成功消息（保存后可能没有 toast，所以不强制要求）"""
        try:
            expect(self.page.locator(self.SUCCESS_MESSAGE)).to_be_visible(timeout=timeout)
            return True
        except Exception:
            logger.info("No success message displayed (may be normal)")
            return False
    
    def wait_for_error_message(self, timeout: int = 5000) -> bool:
        """等待错误消息"""
        try:
            expect(self.page.locator(self.ERROR_MESSAGE)).to_be_visible(timeout=timeout)
            return True
        except TimeoutError:
            return False
    
    def wait_for_loading(self, timeout: int = 3000) -> "ChannelsPage":
        """等待加载完成"""
        try:
            # 等待加载出现（如果有）
            loading = self.page.locator(self.LOADING_SPINNER)
            if loading.count() > 0:
                expect(loading).to_be_hidden(timeout=timeout)
        except Exception:
            pass  # 没有加载动画也正常
        return self
    
    # ========== 高级操作 ==========
    
    def enable_channel(self, channel_name: str) -> "ChannelsPage":
        """
        启用频道
        
        Args:
            channel_name: 频道名称
        """
        logger.info(f"Enabling channel: {channel_name}")
        self.click_channel_card(channel_name)
        self.toggle_enable(True)
        self.save_channel_config()
        self.close_drawer()
        return self
    
    def disable_channel(self, channel_name: str) -> "ChannelsPage":
        """
        禁用频道
        
        Args:
            channel_name: 频道名称
        """
        logger.info(f"Disabling channel: {channel_name}")
        self.click_channel_card(channel_name)
        self.toggle_enable(False)
        self.save_channel_config()
        self.close_drawer()
        return self
    
    def update_bot_prefix(self, channel_name: str, prefix: str) -> "ChannelsPage":
        """
        更新频道的 Bot Prefix
        
        Args:
            channel_name: 频道名称
            prefix: 新的 Bot Prefix
        """
        logger.info(f"Updating bot prefix for {channel_name} to: {prefix}")
        self.click_channel_card(channel_name)
        self.fill_bot_prefix(prefix)
        self.save_channel_config()
        self.close_drawer()
        return self
    
    def refresh_and_verify_channel_status(self, channel_name: str, expected_status: str) -> bool:
        """
        刷新页面并验证频道状态
        
        Args:
            channel_name: 频道名称
            expected_status: 期望状态 'enabled' 或 'disabled'
        """
        logger.info("Refreshing page and verifying channel status")
        self.refresh()
        self.wait_for_page_loaded()
        actual_status = self.get_channel_status(channel_name)
        return actual_status == expected_status