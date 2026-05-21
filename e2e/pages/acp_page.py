# -*- coding: utf-8 -*-
"""
QwenPaw ACP (Agent Communication Protocol) 页面对象

封装 ACP 配置管理页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class ACPPage(BasePage):
    """
    ACP 配置管理页面对象

    封装 ACP 页面的所有用户操作：
    - 页面导航与加载
    - 过滤标签切换（All/Builtin/Custom）
    - ACP 卡片列表交互
    - 创建/编辑 ACP 配置（抽屉）
    - 删除自定义 ACP
    - 内置 ACP 保护验证
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/acp"

    # ========== 选择器定义 ==========

    # 页面容器
    PAGE_CONTAINER = 'div[class*="acp"], div[class*="ACP"], [class*="acpPage"]'
    BREADCRUMB_PARENT = 'span[class*="breadcrumbParent"]'
    BREADCRUMB_CURRENT = 'span[class*="breadcrumbCurrent"]'

    # 过滤标签页
    FILTER_TABS = '.qwenpaw-tabs, .qwenpaw-segmented, [class*="filterTabs"]'
    TAB_ALL = '[class*="tab"]:has-text("All"), [class*="tab"]:has-text("全部"), .qwenpaw-segmented-item:has-text("All")'
    TAB_BUILTIN = '[class*="tab"]:has-text("Builtin"), [class*="tab"]:has-text("内置"), .qwenpaw-segmented-item:has-text("Builtin")'
    TAB_CUSTOM = '[class*="tab"]:has-text("Custom"), [class*="tab"]:has-text("自定义"), .qwenpaw-segmented-item:has-text("Custom")'

    # 创建按钮
    CREATE_BUTTON = 'button:has-text("Create"), button:has-text("创建"), button:has-text("Add"), button:has-text("添加")'

    # ACP 卡片列表
    ACP_CARD = '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
    ACP_CARD_TITLE = '[class*="agentKey"], [class*="title"], .qwenpaw-card-meta-title'
    ACP_CARD_TAG = '.qwenpaw-tag'
    ACP_CARD_SWITCH = '.qwenpaw-switch'

    # ACP 抽屉（创建/编辑）
    DRAWER = '.qwenpaw-drawer'
    DRAWER_TITLE = '.qwenpaw-drawer-title'
    DRAWER_CLOSE = '.qwenpaw-drawer-close'

    # 抽屉表单字段
    FORM_AGENT_KEY = 'input[id*="agentKey"], input[name*="agentKey"], #agentKey'
    FORM_COMMAND = 'input[id*="command"], input[name*="command"], #command'
    FORM_ARGS = 'textarea[id*="args"], textarea[name*="args"], #argsText'
    FORM_ENV = 'textarea[id*="env"], textarea[name*="env"], #envText'
    FORM_ENABLED_SWITCH = '[class*="enabled"] .qwenpaw-switch, #enabled'
    FORM_TRUSTED_SWITCH = '[class*="trusted"] .qwenpaw-switch, #trusted'
    FORM_TOOL_PARSE_MODE = '.qwenpaw-select, select[id*="tool_parse_mode"]'
    FORM_BUFFER_LIMIT = 'input[id*="buffer"], input[name*="buffer"], input[type="number"]'

    # 抽屉操作按钮
    SAVE_BUTTON = '.qwenpaw-drawer button:has-text("Save"), .qwenpaw-drawer button:has-text("保存"), .qwenpaw-drawer button.qwenpaw-btn-primary'
    CANCEL_BUTTON = '.qwenpaw-drawer button:has-text("Cancel"), .qwenpaw-drawer button:has-text("取消")'
    DELETE_BUTTON_DRAWER = '.qwenpaw-drawer button:has-text("Delete"), .qwenpaw-drawer button:has-text("删除")'
    DOC_LINK = '.qwenpaw-drawer a[href*="doc"], .qwenpaw-drawer a[href*="integration"]'

    # 确认弹窗
    POPCONFIRM = '.qwenpaw-popconfirm, .qwenpaw-modal-confirm'
    POPCONFIRM_OK = '.qwenpaw-popconfirm button:has-text("OK"), .qwenpaw-popconfirm button:has-text("确定"), .qwenpaw-popconfirm .qwenpaw-btn-primary'
    POPCONFIRM_CANCEL = '.qwenpaw-popconfirm button:has-text("Cancel"), .qwenpaw-popconfirm button:has-text("取消")'

    # 消息提示
    SUCCESS_TOAST = '.qwenpaw-message-success, .qwenpaw-notification-success'
    ERROR_TOAST = '.qwenpaw-message-error, .qwenpaw-notification-error'

    # 内置 ACP 名称
    BUILTIN_ACP_NAMES = ["opencode", "qwen_code", "claude_code", "codex"]

    # ========== 初始化 ==========

    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("ACPPage initialized")

    # ========== 页面导航 ==========

    def open(self) -> "ACPPage":
        """打开 ACP 配置页面"""
        logger.info("打开 ACP 配置管理页面")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "ACPPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        self.page.wait_for_load_state("networkidle", timeout=timeout)
        self.page.wait_for_timeout(1000)
        return self

    # ========== 面包屑验证 ==========

    def get_breadcrumb_text(self) -> str:
        """获取面包屑文本"""
        breadcrumb = self.page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
        if breadcrumb.is_visible(timeout=3000):
            return breadcrumb.inner_text().strip()
        return ""

    def verify_breadcrumb(self) -> bool:
        """验证面包屑包含工作区和 ACP"""
        text = self.get_breadcrumb_text()
        has_workspace = "Workspace" in text or "工作区" in text or "Agent" in text
        has_acp = "ACP" in text
        return has_workspace and has_acp

    # ========== 过滤标签操作 ==========

    def click_tab_all(self) -> "ACPPage":
        """点击 All 标签"""
        tab = self.page.locator(self.TAB_ALL).first
        if tab.is_visible(timeout=5000):
            tab.click()
            self.page.wait_for_timeout(500)
            logger.info("点击 All 标签")
        return self

    def click_tab_builtin(self) -> "ACPPage":
        """点击 Builtin 标签"""
        tab = self.page.locator(self.TAB_BUILTIN).first
        if tab.is_visible(timeout=5000):
            tab.click()
            self.page.wait_for_timeout(500)
            logger.info("点击 Builtin 标签")
        return self

    def click_tab_custom(self) -> "ACPPage":
        """点击 Custom 标签"""
        tab = self.page.locator(self.TAB_CUSTOM).first
        if tab.is_visible(timeout=5000):
            tab.click()
            self.page.wait_for_timeout(500)
            logger.info("点击 Custom 标签")
        return self

    def is_tab_visible(self, tab_name: str) -> bool:
        """判断指定标签是否可见"""
        tab_selectors = {
            "all": self.TAB_ALL,
            "builtin": self.TAB_BUILTIN,
            "custom": self.TAB_CUSTOM,
        }
        selector = tab_selectors.get(tab_name.lower(), "")
        if selector:
            return self.page.locator(selector).first.is_visible(timeout=3000)
        return False

    # ========== ACP 卡片列表 ==========

    def get_acp_cards(self) -> List[Locator]:
        """获取所有 ACP 卡片"""
        cards = self.page.locator(self.ACP_CARD).all()
        logger.info(f"找到 {len(cards)} 个 ACP 卡片")
        return cards

    def get_acp_card_count(self) -> int:
        """获取 ACP 卡片数量"""
        return len(self.get_acp_cards())

    def get_card_agent_key(self, card: Locator) -> str:
        """获取卡片的 agentKey"""
        title_el = card.locator(
            '[class*="agentKey"], [class*="title"], '
            '.qwenpaw-card-meta-title, h3, h4'
        ).first
        if title_el.is_visible(timeout=3000):
            return title_el.inner_text().strip()
        return card.inner_text().strip()[:50]

    def is_card_builtin(self, card: Locator) -> bool:
        """判断卡片是否为内置 ACP"""
        card_text = card.inner_text().lower()
        return "builtin" in card_text or "内置" in card_text

    def is_card_enabled(self, card: Locator) -> bool:
        """判断卡片是否启用"""
        switch = card.locator(self.ACP_CARD_SWITCH).first
        if switch.count() > 0:
            return switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
        return False

    def click_card(self, card: Locator) -> "ACPPage":
        """点击卡片打开编辑抽屉"""
        card.click()
        self.page.wait_for_timeout(500)
        logger.info("点击 ACP 卡片")
        return self

    def toggle_card_switch(self, card: Locator) -> "ACPPage":
        """切换卡片启用/禁用开关"""
        switch = card.locator(self.ACP_CARD_SWITCH).first
        if switch.count() > 0:
            switch.click()
            self.page.wait_for_timeout(500)
            logger.info("切换 ACP 卡片开关")
        return self

    # ========== 抽屉操作 ==========

    def click_create_button(self) -> "ACPPage":
        """点击创建按钮"""
        create_btn = self.page.locator(self.CREATE_BUTTON).first
        expect(create_btn).to_be_visible(timeout=5000)
        create_btn.click()
        self.page.wait_for_timeout(500)
        logger.info("点击创建 ACP 按钮")
        return self

    def is_drawer_visible(self) -> bool:
        """判断抽屉是否可见"""
        drawer = self.page.locator(self.DRAWER).first
        return drawer.is_visible(timeout=5000)

    def get_drawer_title(self) -> str:
        """获取抽屉标题"""
        title = self.page.locator(self.DRAWER_TITLE).first
        if title.is_visible(timeout=3000):
            return title.inner_text().strip()
        return ""

    def fill_agent_key(self, key: str) -> "ACPPage":
        """填写 agentKey"""
        key_input = self.page.locator(self.FORM_AGENT_KEY).first
        if key_input.is_visible(timeout=3000):
            key_input.fill(key)
            logger.info(f"填写 agentKey: {key}")
        return self

    def fill_command(self, command: str) -> "ACPPage":
        """填写 command"""
        cmd_input = self.page.locator(self.FORM_COMMAND).first
        if cmd_input.is_visible(timeout=3000):
            cmd_input.fill(command)
            logger.info(f"填写 command: {command}")
        return self

    def fill_args(self, args_text: str) -> "ACPPage":
        """填写 args（多行文本）"""
        args_input = self.page.locator(self.FORM_ARGS).first
        if args_input.is_visible(timeout=3000):
            args_input.fill(args_text)
            logger.info(f"填写 args: {args_text[:50]}")
        return self

    def fill_env(self, env_text: str) -> "ACPPage":
        """填写 env（KEY=VALUE 格式）"""
        env_input = self.page.locator(self.FORM_ENV).first
        if env_input.is_visible(timeout=3000):
            env_input.fill(env_text)
            logger.info(f"填写 env: {env_text[:50]}")
        return self

    def save_drawer(self) -> "ACPPage":
        """点击保存按钮"""
        save_btn = self.page.locator(self.SAVE_BUTTON).first
        if save_btn.is_visible(timeout=5000):
            save_btn.click()
            self.page.wait_for_timeout(1000)
            logger.info("点击保存")
        return self

    def cancel_drawer(self) -> "ACPPage":
        """点击取消按钮"""
        cancel_btn = self.page.locator(self.CANCEL_BUTTON).first
        if cancel_btn.is_visible(timeout=3000):
            cancel_btn.click()
        else:
            close_btn = self.page.locator(self.DRAWER_CLOSE).first
            if close_btn.is_visible(timeout=3000):
                close_btn.click()
            else:
                self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(500)
        logger.info("关闭抽屉")
        return self

    def click_delete_in_drawer(self) -> "ACPPage":
        """在抽屉中点击删除按钮"""
        delete_btn = self.page.locator(self.DELETE_BUTTON_DRAWER).first
        if delete_btn.is_visible(timeout=3000):
            delete_btn.click()
            self.page.wait_for_timeout(500)
            logger.info("点击抽屉内删除按钮")
        return self

    def confirm_delete(self) -> "ACPPage":
        """确认删除"""
        ok_btn = self.page.locator(self.POPCONFIRM_OK).first
        if ok_btn.is_visible(timeout=5000):
            ok_btn.click()
            self.page.wait_for_timeout(1000)
            logger.info("确认删除")
        return self

    def cancel_delete(self) -> "ACPPage":
        """取消删除"""
        cancel_btn = self.page.locator(self.POPCONFIRM_CANCEL).first
        if cancel_btn.is_visible(timeout=3000):
            cancel_btn.click()
            self.page.wait_for_timeout(500)
            logger.info("取消删除")
        return self

    def is_agent_key_editable(self) -> bool:
        """判断 agentKey 输入框是否可编辑"""
        key_input = self.page.locator(self.FORM_AGENT_KEY).first
        if key_input.is_visible(timeout=3000):
            return key_input.is_enabled()
        return False

    def is_delete_button_visible(self) -> bool:
        """判断抽屉中的删除按钮是否可见"""
        delete_btn = self.page.locator(self.DELETE_BUTTON_DRAWER).first
        return delete_btn.is_visible(timeout=3000)

    # ========== 消息断言 ==========

    def wait_for_success_message(self, timeout: Optional[int] = None) -> bool:
        """等待成功消息"""
        try:
            self.page.locator(self.SUCCESS_TOAST).first.wait_for(
                state="visible", timeout=timeout or 10000
            )
            return True
        except Exception:
            return False

    # ========== 断言方法 ==========

    def assert_page_loaded(self, timeout: Optional[int] = None) -> "ACPPage":
        """断言页面已加载"""
        timeout = timeout or self.timeout
        indicator = self.page.locator(
            f'{self.CREATE_BUTTON}, {self.ACP_CARD}, {self.FILTER_TABS}'
        ).first
        expect(indicator).to_be_visible(timeout=timeout)
        return self

    def assert_card_count(self, expected: int, timeout: Optional[int] = None) -> "ACPPage":
        """断言 ACP 卡片数量"""
        expect(self.page.locator(self.ACP_CARD)).to_have_count(
            expected, timeout=timeout or self.timeout
        )
        return self
