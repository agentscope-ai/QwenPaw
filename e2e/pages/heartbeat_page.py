# -*- coding: utf-8 -*-
"""
QwenPaw Heartbeat 页面对象

封装 Heartbeat 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class HeartbeatPage(BasePage):
    """
    Heartbeat 页面对象
    
    封装 Heartbeat 页面的所有用户操作：
    - 心跳配置展示
    - 启用/禁用心跳
    - 配置心跳间隔
    - 配置心跳时间
    - 配置心跳技能
    - 保存配置
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/heartbeat"
    PAGE_HEADER = "h1, h2, [class*=title], [class*=header]"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志（页面无 h1 标签，使用开关或输入框作为加载完成标志）
    PAGE_LOAD_INDICATOR = '.ant-switch, .qwenpaw-switch, input'
    
    # 配置卡片
    CONFIG_CARD = ".ant-card, .qwenpaw-card, [class*=card]"
    CONFIG_FORM = ".ant-form, .qwenpaw-form"
    
    # 启用开关（精确匹配 id="enabled" 的开关，避免匹配到 "活跃时段" 开关）
    ENABLED_SWITCH = '#enabled'
    ENABLED_LABEL = '.ant-form-item:has-text("Enable"), .ant-form-item:has-text("启用"), .qwenpaw-form-item:has-text("启用"), .qwenpaw-form-item:has-text("开启")'
    
    # 间隔配置
    INTERVAL_INPUT = 'input[id*="interval"], input[type="number"], input.qwenpaw-input-number-input'
    INTERVAL_UNIT_SELECT = '.qwenpaw-select:has(#everyUnit), .ant-select:has(#everyUnit), .ant-select:has-text("seconds"), .ant-select:has-text("minutes"), .ant-select:has-text("hours"), .qwenpaw-select:has-text("秒"), .qwenpaw-select:has-text("分钟"), .qwenpaw-select:has-text("小时")'
    
    # 时间配置
    TIME_PICKER = '.ant-picker-input > input, .qwenpaw-picker-input > input'
    TIME_PICKER_PANEL = '.ant-picker-panel, .qwenpaw-picker-panel'
    
    # 技能配置
    SKILL_SELECT = '.ant-select[data-placeholder*="Skill" i], .ant-select:has-text("skill"), .qwenpaw-select[data-placeholder*="技能" i], .qwenpaw-select:has-text("技能")'
    
    # 保存按钮（注意实际 UI 中可能是 "保 存" 带空格）
    SAVE_BTN = 'button:has-text("Save"), button:has-text("保存"), button:has-text("保 存")'
    
    # 状态指示器
    STATUS_INDICATOR = '.ant-badge-status, .qwenpaw-badge-status, .status-indicator'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "HeartbeatPage":
        """打开 Heartbeat 页面

        Heartbeat 页面可能存在持续轮询请求，使用 networkidle 会导致超时，
        因此改用 domcontentloaded 并增加超时时间。
        """
        logger.info("打开 Heartbeat 页面")
        target_url = self.PAGE_URL
        logger.info(f"Navigating to: {target_url}")
        try:
            self.page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            logger.warning(f"Heartbeat 页面导航超时，尝试等待 DOM 加载: {e}")
            self.page.goto(target_url, wait_until="commit", timeout=30000)
        self.page.wait_for_timeout(2000)
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "HeartbeatPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        # 等待开关或输入框出现（页面无 h1 标签）
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== 配置读取方法 ==========
    
    def is_heartbeat_enabled(self) -> bool:
        """检查心跳是否启用"""
        switch = self.page.locator(self.ENABLED_SWITCH)
        if switch.count() > 0:
            return switch.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked') || el.getAttribute('aria-checked') === 'true'")
        return False
    
    def get_interval(self) -> Dict[str, Any]:
        """获取心跳间隔配置"""
        interval_input = self.page.locator(self.INTERVAL_INPUT)
        unit_select = self.page.locator(self.INTERVAL_UNIT_SELECT)
        
        result = {"value": None, "unit": None}
        
        if interval_input.count() > 0:
            result["value"] = interval_input.first.input_value()
        
        if unit_select.count() > 0:
            # 尝试获取选中项的文本，优先使用 title 属性，其次使用 inner_text
            selection_item = unit_select.first.locator('.qwenpaw-select-selection-item, .ant-select-selection-item')
            if selection_item.count() > 0:
                unit_text = selection_item.get_attribute('title') or selection_item.inner_text().strip()
                result["unit"] = unit_text if unit_text else None
            else:
                # 降级方案：直接获取容器文本并清理
                raw_text = unit_select.first.inner_text().strip()
                # 过滤掉标签文本，只保留选中值
                if raw_text:
                    result["unit"] = raw_text.split('\n')[0].strip() if '\n' in raw_text else raw_text
        
        return result
    
    def get_scheduled_time(self) -> Optional[str]:
        """获取定时时间"""
        time_picker = self.page.locator(self.TIME_PICKER)
        if time_picker.count() > 0:
            return time_picker.first.input_value()
        return None
    
    def get_skill(self) -> Optional[str]:
        """获取配置的技能"""
        skill_select = self.page.locator(self.SKILL_SELECT)
        if skill_select.count() > 0:
            return skill_select.first.inner_text()
        return None
    
    # ========== 配置修改方法 ==========
    
    def toggle_heartbeat(self) -> "HeartbeatPage":
        """切换心跳启用状态"""
        self.page.locator(self.ENABLED_SWITCH).click()
        return self
    
    def enable_heartbeat(self) -> "HeartbeatPage":
        """启用心跳"""
        if not self.is_heartbeat_enabled():
            self.toggle_heartbeat()
        return self
    
    def disable_heartbeat(self) -> "HeartbeatPage":
        """禁用心跳"""
        if self.is_heartbeat_enabled():
            self.toggle_heartbeat()
        return self
    
    def set_interval(self, value: int, unit: str = "minutes") -> "HeartbeatPage":
        """设置心跳间隔（兼容中英文单位）"""
        # 设置数值
        interval_input = self.page.locator(self.INTERVAL_INPUT)
        if interval_input.count() > 0:
            interval_input.fill(str(value))
        
        # 选择单位
        if unit:
            unit_select = self.page.locator(self.INTERVAL_UNIT_SELECT)
            if unit_select.count() > 0:
                unit_select.first.click()
                self.page.wait_for_timeout(300)
                # 尝试所有可能的中英文别名
                aliases = self.UNIT_ALIASES.get(unit, [unit])
                clicked = False
                for alias in aliases:
                    option = self.page.locator(
                        f'.qwenpaw-select-item-option:has-text("{alias}"), '
                        f'.ant-select-item-option:has-text("{alias}"), '
                        f'.qwenpaw-select-item:has-text("{alias}"), '
                        f'.ant-select-item:has-text("{alias}")'
                    )
                    if option.count() > 0:
                        option.first.click()
                        clicked = True
                        logger.info(f"已选择单位：{alias}")
                        break
                if not clicked:
                    logger.warning(f"未找到单位选项：{unit}（别名：{aliases}）")
        
        return self
    
    def set_scheduled_time(self, time_str: str) -> "HeartbeatPage":
        """设置定时时间 (HH:mm 格式)"""
        time_picker = self.page.locator(self.TIME_PICKER)
        if time_picker.count() > 0:
            time_picker.click()
            # 直接输入时间
            time_picker.fill(time_str)
            # 关闭时间选择器
            self.page.keyboard.press("Enter")
        return self
    
    def set_skill(self, skill_name: str) -> "HeartbeatPage":
        """配置心跳技能"""
        skill_select = self.page.locator(self.SKILL_SELECT)
        if skill_select.count() > 0:
            skill_select.click()
            self.page.locator(f'.ant-select-option:has-text("{skill_name}")').click()
        return self
    
    def save_config(self) -> "HeartbeatPage":
        """保存配置"""
        self.page.locator(self.SAVE_BTN).first.click()
        self.page.wait_for_timeout(1000)
        return self
    
    # ========== 完整配置流程 ==========
    
    def configure_heartbeat(
        self,
        enabled: bool = True,
        interval: int = 30,
        unit: str = "minutes",
        scheduled_time: Optional[str] = None,
        skill_name: Optional[str] = None,
    ) -> "HeartbeatPage":
        """完整的心跳配置流程"""
        if enabled:
            self.enable_heartbeat()
        else:
            self.disable_heartbeat()
        
        self.set_interval(interval, unit)
        
        if scheduled_time:
            self.set_scheduled_time(scheduled_time)
        
        if skill_name:
            self.set_skill(skill_name)
        
        self.save_config()
        return self
    
    # ========== 断言方法 ==========
    
    def assert_heartbeat_enabled(self) -> "HeartbeatPage":
        """断言心跳已启用"""
        assert self.is_heartbeat_enabled(), "心跳应该是启用状态"
        return self
    
    def assert_heartbeat_disabled(self) -> "HeartbeatPage":
        """断言心跳已禁用"""
        assert not self.is_heartbeat_enabled(), "心跳应该是禁用状态"
        return self
    
    # 中英文单位映射表
    UNIT_ALIASES = {
        "分钟": ["分钟", "Minutes", "minutes", "min"],
        "小时": ["小时", "Hours", "hours", "hour", "hr"],
        "秒": ["秒", "Seconds", "seconds", "sec"],
        "Minutes": ["分钟", "Minutes", "minutes", "min"],
        "Hours": ["小时", "Hours", "hours", "hour", "hr"],
        "Seconds": ["秒", "Seconds", "seconds", "sec"],
    }

    def assert_interval(self, expected_value: int, expected_unit: str = "分钟") -> "HeartbeatPage":
        """断言间隔配置（兼容中英文单位）"""
        interval = self.get_interval()
        assert int(interval["value"]) == expected_value, f"间隔值应该是 {expected_value}，实际是 {interval['value']}"
        actual_unit = interval["unit"] or ""
        # 查找 expected_unit 的所有别名
        aliases = self.UNIT_ALIASES.get(expected_unit, [expected_unit])
        unit_matched = any(alias in actual_unit for alias in aliases)
        assert unit_matched, f"间隔单位应该是 {expected_unit}（或其别名 {aliases}），实际是 {actual_unit}"
        return self
    
    def assert_config_saved(self) -> "HeartbeatPage":
        """断言配置保存成功（通过验证页面无错误消息来判断）"""
        error_msg = self.page.locator('.ant-message-error, .qwenpaw-message-error')
        assert error_msg.count() == 0, "保存后出现错误消息"
        return self