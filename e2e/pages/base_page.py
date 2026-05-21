# -*- coding: utf-8 -*-
"""
QwenPaw E2E 测试框架 - Page Object 基类

提供通用的页面操作方法，所有页面对象都应继承此类。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from config.settings import config


logger = logging.getLogger(__name__)


class BasePage:
    """
    Page Object 基类
    
    提供通用的页面操作方法，包括：
    - 导航
    - 元素查找
    - 等待机制
    - 截图
    - 断言辅助
    """
    
    # 子类应重写这些属性
    PAGE_TITLE: str = ""
    PAGE_URL: str = ""
    
    # 通用选择器（子类可覆盖）
    SUCCESS_MESSAGE = '.ant-message-success, .qwenpaw-message-success, .qwenpaw-notification-success'
    ERROR_MESSAGE = '.ant-message-error, .qwenpaw-message-error, .qwenpaw-notification-error'
    LOADING_SPINNER = '.ant-spin, .qwenpaw-spin, [class*=loading]'
    
    def __init__(self, page: Page):
        self.page = page
        self.timeout = config.browser.timeout
    
    # ========== 导航方法 ==========
    
    def goto(self, url: Optional[str] = None) -> "BasePage":
        """
        导航到指定 URL
        
        Args:
            url: 目标 URL，留空则使用 PAGE_URL
            
        Returns:
            self
        """
        target_url = url or self.PAGE_URL
        logger.info(f"Navigating to: {target_url}")
        self.page.goto(target_url, wait_until="commit", timeout=self.timeout)
        return self
    
    def refresh(self) -> "BasePage":
        """刷新页面"""
        logger.info("Refreshing page")
        self.page.reload(wait_until="commit", timeout=self.timeout)
        return self
    
    # ========== 元素查找方法 ==========
    
    def find(self, selector: str, timeout: Optional[int] = None) -> Locator:
        """
        查找单个元素

        Args:
            selector: CSS 选择器
            timeout: 超时时间（毫秒），仅在显式传入时生效

        Returns:
            Locator 对象
        """
        locator = self.page.locator(selector).first
        if timeout is not None:
            locator.wait_for(state="attached", timeout=timeout)
        return locator
    
    def find_all(self, selector: str) -> List[Locator]:
        """
        查找多个元素
        
        Args:
            selector: CSS 选择器
            
        Returns:
            Locator 列表
        """
        return self.page.locator(selector).all()
    
    def find_by_text(self, text: str, exact: bool = False) -> Locator:
        """
        按文本查找元素
        
        Args:
            text: 文本内容
            exact: 是否精确匹配
            
        Returns:
            Locator 对象
        """
        return self.page.get_by_text(text, exact=exact).first
    
    def find_by_role(self, role: str, name: Optional[str] = None) -> Locator:
        """
        按 ARIA role 查找元素
        
        Args:
            role: ARIA role
            name: 可选的 name 属性
            
        Returns:
            Locator 对象
        """
        if name:
            return self.page.get_by_role(role, name=name).first
        return self.page.get_by_role(role).first
    
    def find_by_placeholder(self, placeholder: str) -> Locator:
        """
        按 placeholder 查找输入框
        
        Args:
            placeholder: placeholder 文本
            
        Returns:
            Locator 对象
        """
        return self.page.get_by_placeholder(placeholder).first
    
    def find_by_label(self, label: str) -> Locator:
        """
        按 label 查找元素
        
        Args:
            label: label 文本
            
        Returns:
            Locator 对象
        """
        return self.page.get_by_label(label).first
    
    def find_by_testid(self, testid: str) -> Locator:
        """
        按 data-testid 查找元素
        
        Args:
            testid: testid 值
            
        Returns:
            Locator 对象
        """
        return self.page.get_by_test_id(testid).first
    
    # ========== 等待方法 ==========
    
    def wait_for_element(self, selector: str, timeout: Optional[int] = None, state: str = "visible") -> Locator:
        """
        等待元素出现
        
        Args:
            selector: CSS 选择器
            timeout: 超时时间
            state: 等待状态 (visible, hidden, detached, attached)
            
        Returns:
            Locator 对象
        """
        locator = self.page.locator(selector).first
        locator.wait_for(state=state, timeout=timeout or self.timeout)
        return locator
    
    def wait_for_text(self, text: str, timeout: Optional[int] = None) -> None:
        """
        等待文本出现
        
        Args:
            text: 期望的文本
            timeout: 超时时间
        """
        import json
        safe_text = json.dumps(text)
        self.page.wait_for_function(
            f"document.body.innerText.includes({safe_text})",
            timeout=timeout or self.timeout
        )
    
    def wait_for_url(self, url_pattern: str, timeout: Optional[int] = None) -> None:
        """
        等待 URL 匹配
        
        Args:
            url_pattern: URL 模式
            timeout: 超时时间
        """
        self.page.wait_for_url(url_pattern, timeout=timeout or self.timeout)
    
    def wait_for_loading(self, timeout: Optional[int] = None) -> None:
        """等待页面加载完成"""
        self.page.wait_for_load_state("networkidle", timeout=timeout or self.timeout)
    
    def wait(self, milliseconds: int) -> None:
        """
        强制等待（仅在必要时使用）
        
        Args:
            milliseconds: 等待毫秒数
        """
        self.page.wait_for_timeout(milliseconds)
    
    # ========== 操作方法 ==========
    
    def click(self, selector: str, timeout: Optional[int] = None) -> "BasePage":
        """
        点击元素
        
        Args:
            selector: CSS 选择器
            timeout: 超时时间
            
        Returns:
            self
        """
        locator = self.find(selector)
        locator.click(timeout=timeout or self.timeout)
        logger.debug(f"Clicked: {selector}")
        return self
    
    def fill(self, selector: str, value: str) -> "BasePage":
        """
        填充输入框
        
        Args:
            selector: CSS 选择器
            value: 要填充的值
            
        Returns:
            self
        """
        locator = self.find(selector)
        locator.fill(value)
        logger.debug(f"Filled {selector} with: {value[:50]}...")
        return self
    
    def type_slowly(self, selector: str, value: str, delay: int = 50) -> "BasePage":
        """
        慢速输入（用于测试输入事件）
        
        Args:
            selector: CSS 选择器
            value: 要输入的值
            delay: 每个字符间的延迟（毫秒）
            
        Returns:
            self
        """
        locator = self.find(selector)
        locator.type(value, delay=delay)
        logger.debug(f"Typed slowly: {value[:50]}...")
        return self
    
    def press(self, selector: str, key: str) -> "BasePage":
        """
        按键操作
        
        Args:
            selector: CSS 选择器
            key: 键名 (Enter, Tab, Escape 等)
            
        Returns:
            self
        """
        locator = self.find(selector)
        locator.press(key)
        logger.debug(f"Pressed {key} on {selector}")
        return self
    
    def hover(self, selector: str) -> "BasePage":
        """
        悬停元素
        
        Args:
            selector: CSS 选择器
            
        Returns:
            self
        """
        locator = self.find(selector)
        locator.hover()
        logger.debug(f"Hovered: {selector}")
        return self
    
    def upload_file(self, selector: str, file_path: str) -> "BasePage":
        """
        上传文件
        
        Args:
            selector: 文件输入框选择器
            file_path: 文件路径
            
        Returns:
            self
        """
        locator = self.find(selector)
        locator.set_input_files(file_path)
        logger.info(f"Uploaded file: {file_path}")
        return self
    
    def select_option(self, selector: str, value: str) -> "BasePage":
        """
        选择下拉选项
        
        Args:
            selector: 选择器
            value: 选项值
            
        Returns:
            self
        """
        locator = self.find(selector)
        locator.select_option(value)
        logger.debug(f"Selected option: {value}")
        return self
    
    # ========== 断言辅助方法 ==========
    
    def assert_visible(self, selector: str, timeout: Optional[int] = None) -> bool:
        """
        断言元素可见
        
        Args:
            selector: CSS 选择器
            timeout: 超时时间
            
        Returns:
            是否可见
        """
        try:
            expect(self.find(selector)).to_be_visible(timeout=timeout or self.timeout)
            return True
        except (TimeoutError, AssertionError, Exception):
            return False
    
    def assert_text(self, selector: str, expected_text: str, timeout: Optional[int] = None) -> bool:
        """
        断言元素文本
        
        Args:
            selector: CSS 选择器
            expected_text: 期望文本
            timeout: 超时时间
            
        Returns:
            是否匹配
        """
        try:
            expect(self.find(selector)).to_contain_text(expected_text, timeout=timeout or self.timeout)
            return True
        except TimeoutError:
            return False
    
    def assert_count(self, selector: str, expected_count: int, timeout: Optional[int] = None) -> bool:
        """
        断言元素数量
        
        Args:
            selector: CSS 选择器
            expected_count: 期望数量
            timeout: 超时时间
            
        Returns:
            是否匹配
        """
        try:
            expect(self.page.locator(selector)).to_have_count(expected_count, timeout=timeout or self.timeout)
            return True
        except TimeoutError:
            return False
    
    def assert_url(self, expected_url: str, timeout: Optional[int] = None) -> bool:
        """
        断言当前 URL
        
        Args:
            expected_url: 期望 URL
            timeout: 超时时间
            
        Returns:
            是否匹配
        """
        try:
            expect(self.page).to_have_url(expected_url, timeout=timeout or self.timeout)
            return True
        except TimeoutError:
            return False
    
    # ========== 截图和调试 ==========

    def screenshot(self, name: str, full_page: bool = True) -> str:
        """
        截取屏幕截图

        Args:
            name: 截图名称
            full_page: 是否截取完整页面

        Returns:
            截图文件路径
        """
        path = config.paths.screenshots_dir / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=full_page)
        logger.info(f"Screenshot saved: {path}")
        return str(path)

    # ---- 步骤截图（用例级目录 + 自增序号 + 安全文件名）----
    def step_shot(self, action: str, full_page: bool = False) -> str:
        """
        在测试关键步骤打截图，并按用例自动归档到独立子目录。

        - 用例名通过 page._qwenpaw_test_name 属性传入（由 conftest 注入）
        - 文件名：<序号>_<安全化的 action>_<时分秒毫秒>.png
        - 默认只截可视区域（full_page=False），避免 Thinking 转圈下大长页拖慢测试
        - 截图失败不抛异常（仅 warning），避免污染主用例

        Args:
            action: 步骤短名（如 "open_page" / "send_message_before"）
            full_page: 是否整页截图，默认 False

        Returns:
            截图文件路径；失败返回空字符串
        """
        try:
            from datetime import datetime as _dt
            test_name = getattr(self.page, "_qwenpaw_test_name", None) or "unknown_test"
            # 安全化：只保留字母数字下划线
            import re as _re
            safe_test = _re.sub(r"[^A-Za-z0-9_\-]", "_", test_name)[:80]
            safe_action = _re.sub(r"[^A-Za-z0-9_\-]", "_", action)[:60]

            # 用例级独立子目录
            case_dir = config.paths.screenshots_dir / "steps" / safe_test
            case_dir.mkdir(parents=True, exist_ok=True)

            # 自增序号（挂在 page 上，每个用例独立计数）
            seq = getattr(self.page, "_qwenpaw_step_seq", 0) + 1
            try:
                self.page._qwenpaw_step_seq = seq
            except Exception:
                pass

            ts = _dt.now().strftime("%H%M%S_%f")[:-3]
            filename = f"{seq:02d}_{safe_action}_{ts}.png"
            path = case_dir / filename
            self.page.screenshot(path=str(path), full_page=full_page)
            logger.info(f"[step_shot] {test_name} -> {seq:02d}_{safe_action}")
            return str(path)
        except Exception as e:
            logger.warning(f"[step_shot] failed for action={action}: {e}")
            return ""
    
    def get_page_title(self) -> str:
        """获取页面标题"""
        return self.page.title()
    
    def get_page_url(self) -> str:
        """获取当前 URL"""
        return self.page.url
    
    def get_text(self, selector: str) -> str:
        """获取元素文本"""
        return self.find(selector).inner_text()
    
    def get_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """获取元素属性"""
        return self.find(selector).get_attribute(attribute)
    
    def is_enabled(self, selector: str) -> bool:
        """检查元素是否启用"""
        return self.find(selector).is_enabled()
    
    def is_disabled(self, selector: str) -> bool:
        """检查元素是否禁用"""
        return self.find(selector).is_disabled()
