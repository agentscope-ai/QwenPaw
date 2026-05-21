# -*- coding: utf-8 -*-
"""
QwenPaw CronJobs 页面对象

封装 CronJobs 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class CronJobsPage(BasePage):
    """
    CronJobs 页面对象
    
    封装 CronJobs 页面的所有用户操作：
    - 定时任务列表展示
    - 创建定时任务
    - 编辑定时任务
    - 删除定时任务
    - 启用/禁用任务
    - 立即执行任务
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/cron-jobs"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志（页面无 h1 标签，使用创建按钮作为加载完成标志）
    PAGE_LOAD_INDICATOR = 'button:has-text("创建任务"), button:has-text("Create Job"), .qwenpaw-table, .ant-table'
    
    # 创建按钮（UI 文本为中文）
    CREATE_JOB_BTN = 'button:has-text("创建任务"), button:has-text("+ 创建任务"), button:has-text("Create Job"), button:has-text("+ Create Job")'
    
    # 表格选择器
    JOB_TABLE = ".ant-table, .qwenpaw-table, table"
    JOB_TABLE_ROW = ".ant-table-tbody > tr, .qwenpaw-table-tbody > tr, table tbody tr"
    
    # 任务操作按钮
    EDIT_BTN = 'button:has-text("Edit"), button:has-text("编辑"), .ant-btn:has(svg):not(:has-text("Delete")):not(:has-text("删除"))'
    DELETE_BTN = 'button:has-text("Delete"), button:has-text("删除")'
    ENABLE_TOGGLE = '.ant-switch, .qwenpaw-switch'
    EXECUTE_NOW_BTN = 'button:has-text("Execute Now"), button:has-text("Run"), button:has-text("立即执行"), button:has-text("执行")'
    
    # 抽屉/弹窗
    DRAWER = ".ant-drawer, .qwenpaw-drawer, [class*=drawer]"
    DRAWER_TITLE = ".ant-drawer-title, .qwenpaw-drawer-title"
    DRAWER_SAVE_BTN = '.ant-drawer .ant-btn-primary:has-text("Save"), .ant-drawer button:has-text("OK"), [class*=drawer] button:has-text("Save"), [class*=drawer] button:has-text("OK"), [class*=drawer] button:has-text("保存"), [class*=drawer] button:has-text("保 存"), [class*=drawer] button:has-text("确定"), [class*=drawer] .qwenpaw-btn-primary'
    DRAWER_CANCEL_BTN = '.ant-drawer .ant-btn:has-text("Cancel"), [class*=drawer] button:has-text("取消"), [class*=drawer] button:has-text("取 消")'
    
    # 表单字段
    JOB_NAME_INPUT = 'input#name, input[id*="jobName"], input[placeholder*="Job Name" i], input[placeholder*="任务名称" i], input[placeholder*="每日早报" i]'
    CRON_EXPRESSION_INPUT = '#schedule_cron'
    TIMEZONE_SELECT = '.ant-select[data-placeholder*="Timezone" i], .qwenpaw-select[data-placeholder*="时区" i]'
    TASK_TYPE_SELECT = '.ant-select[data-placeholder*="Task Type" i], .qwenpaw-select[data-placeholder*="任务类型" i]'
    DESCRIPTION_INPUT = 'textarea[id*="description"], textarea[placeholder*="Description" i], textarea[placeholder*="描述" i]'
    ENABLED_SWITCH = '.ant-switch, .qwenpaw-switch'
    
    # 过滤和搜索
    SEARCH_INPUT = 'input[placeholder*="Search" i], input[placeholder*="搜索" i]'
    
    # ========== 辅助方法 ==========

    def _select_option(self, field_id: str, value: str) -> None:
        """与 Ant Design Select (showSearch) 组件交互：
        检查当前值 → 如需修改则点击 → 输入搜索 → 选择选项"""
        select = self.page.locator(f'{field_id}')
        if select.count() == 0 or not select.first.is_visible():
            return
        # 检查 Select 当前是否已有目标值
        current_value = select.first.locator('.qwenpaw-select-selection-item, .ant-select-selection-item')
        if current_value.count() > 0 and current_value.first.is_visible():
            current_text = current_value.first.inner_text().strip()
            if current_text == value:
                return  # 已有正确值，跳过
        # 点击 Select 的 selector 区域打开下拉（通过 JS 绕过遮挡）
        selector = select.first.locator('.qwenpaw-select-selector, .ant-select-selector')
        if selector.count() > 0:
            selector.first.evaluate("el => el.click()")
        else:
            select.first.evaluate("el => el.click()")
        self.page.wait_for_timeout(500)
        # 输入搜索值（使用 type 而非 fill，因为 input 可能是 readonly）
        self.page.keyboard.type(value, delay=50)
        self.page.wait_for_timeout(500)
        # 尝试点击匹配选项
        option = self.page.locator(f'.qwenpaw-select-item-option-content:has-text("{value}")').first
        if option.is_visible(timeout=1500):
            option.click()
        else:
            self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(300)

    # ========== 导航方法 ==========
    
    def open(self) -> "CronJobsPage":
        """打开 CronJobs 页面"""
        logger.info("打开 CronJobs 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "CronJobsPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        # 等待表格出现（页面无 h1 标签）
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== 列表操作方法 ==========
    
    def get_job_count(self) -> int:
        """获取任务数量"""
        rows = self.page.locator(self.JOB_TABLE_ROW)
        return rows.count()
    
    def get_job_row(self, job_name: str) -> Locator:
        """获取指定任务的行（排除隐藏行和占位行）"""
        return self.page.locator(f"tr:not([aria-hidden='true']):not(.qwenpaw-table-placeholder):not(.qwenpaw-table-measure-row):has-text('{job_name}')")
    
    def job_exists(self, job_name: str) -> bool:
        """检查任务是否存在（会遍历所有分页）"""
        self.page.wait_for_timeout(500)
        if self.get_job_row(job_name).count() > 0:
            return True

        # 遍历分页查找
        pagination_items = self.page.locator('.qwenpaw-pagination-item:not(.qwenpaw-pagination-item-active)').all()
        for page_item in pagination_items:
            if page_item.is_visible():
                page_item.click()
                self.page.wait_for_timeout(1000)
                if self.get_job_row(job_name).count() > 0:
                    return True

        return False
    
    def search_job(self, keyword: str) -> "CronJobsPage":
        """搜索任务"""
        search_input = self.page.locator(self.SEARCH_INPUT)
        if search_input.count() > 0:
            search_input.fill(keyword)
        return self
    
    # ========== 创建任务方法 ==========
    
    def click_create_job(self) -> "CronJobsPage":
        """点击创建任务按钮"""
        self.page.locator(self.CREATE_JOB_BTN).click()
        expect(self.page.locator(self.DRAWER).first).to_be_visible()
        return self
    
    def fill_job_form(
        self,
        job_name: str,
        cron_expression: str = "0 9 * * *",
        timezone: str = "Asia/Shanghai",
        task_type: str = "text",
        description: str = "",
        enabled: bool = True,
        request_input: str = '[{"role":"user","content":[{"type":"text","text":"Hello"}]}]',
        target_user_id: str = "default",
        target_session_id: str = "default",
        dispatch_channel: str = "console",
    ) -> "CronJobsPage":
        """填写任务表单

        必填字段（源码 JobDrawer.tsx）：
        - name: 任务名称
        - dispatch.channel: 分发渠道 (required)
        - dispatch.target.user_id: 目标用户ID (required)
        - dispatch.target.session_id: 目标会话ID (required)
        - task_type: 任务类型 (text/agent, required)
        - text: 文本内容 (task_type=text 时 required)
        - request.input: 请求内容 (task_type=agent 时 required, 须为有效 JSON)
        """
        # 填写任务名称
        job_name_input = self.page.locator('#name')
        if job_name_input.count() > 0:
            job_name_input.fill(job_name)

        # 选择任务类型（Ant Design Select，默认 agent）
        self._select_option('#task_type', task_type)
        self.page.wait_for_timeout(500)

        # 默认使用"每天"调度类型，不切换到自定义 Cron
        cron_input = self.page.locator(self.CRON_EXPRESSION_INPUT)
        if cron_input.count() > 0 and cron_input.first.is_visible():
            cron_input.first.click()
            cron_input.first.fill(cron_expression)

        # 填写文本内容（text 类型任务的必填字段）
        text_textarea = self.page.locator('#text')
        if text_textarea.count() > 0 and text_textarea.first.is_visible():
            text_textarea.first.fill(description or "E2E test task content")

        # 填写请求内容（agent 类型任务的必填字段，需为有效 JSON）
        request_textarea = self.page.locator('#request_input')
        if request_textarea.count() > 0 and request_textarea.first.is_visible():
            request_textarea.first.fill(request_input)

        # 填写分发渠道（Ant Design Select 组件，showSearch）
        self._select_option('#dispatch_channel', dispatch_channel)

        # 填写目标用户ID（Ant Design Select 组件，showSearch）
        self._select_option('#dispatch_target_user_id', target_user_id)

        # 填写目标会话ID（Ant Design Select 组件，showSearch）
        self._select_option('#dispatch_target_session_id', target_session_id)
        
        return self
    
    def save_job(self) -> "CronJobsPage":
        """保存任务"""
        # 关闭所有下拉菜单
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(300)
        # 通过 JS 触发保存按钮点击，绕过 Select 组件遮挡
        save_btn = self.page.locator(self.DRAWER_SAVE_BTN).first
        save_btn.evaluate("""el => {
            // React 需要通过原生事件触发，dispatchEvent + 原生 click 都试
            const evt = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
            el.dispatchEvent(evt);
            el.click();
        }""")
        self.page.wait_for_timeout(2000)
        # 如果抽屉仍然可见，手动关闭
        drawer = self.page.locator('.qwenpaw-drawer:visible, .ant-drawer:visible')
        if drawer.count() > 0:
            close_btn = self.page.locator('.qwenpaw-drawer-close, .ant-drawer-close')
            if close_btn.count() > 0 and close_btn.first.is_visible():
                close_btn.first.click()
                self.page.wait_for_timeout(500)
        # 刷新页面以确保列表更新
        self.page.reload()
        self.wait_for_page_loaded()
        return self
    
    def cancel_job_creation(self) -> "CronJobsPage":
        """取消创建任务"""
        self.page.locator(self.DRAWER_CANCEL_BTN).click()
        expect(self.page.locator(self.DRAWER).first).to_be_hidden()
        return self
    
    def create_job(
        self,
        job_name: str,
        cron_expression: str = "0 9 * * *",
        timezone: str = "Asia/Shanghai",
        task_type: str = "skill",
        description: str = "",
        enabled: bool = True,
    ) -> "CronJobsPage":
        """创建任务的完整流程"""
        self.click_create_job()
        self.fill_job_form(job_name, cron_expression, timezone, task_type, description, enabled)
        self.save_job()
        return self
    
    # ========== 编辑任务方法 ==========
    
    def click_edit_job(self, job_name: str) -> "CronJobsPage":
        """点击编辑任务"""
        row = self.get_job_row(job_name)
        edit_btn = row.locator(self.EDIT_BTN)
        if edit_btn.count() == 0:
            # 尝试点击操作菜单
            row.locator('.ant-btn:has(svg)').first.click()
            edit_btn = self.page.locator('.ant-dropdown .ant-dropdown-menu-item:has-text("Edit")')
        edit_btn.click()
        expect(self.page.locator(self.DRAWER).first).to_be_visible()
        return self
    
    def update_job(self, job_name: str, **kwargs) -> "CronJobsPage":
        """更新任务"""
        self.click_edit_job(job_name)
        self.fill_job_form(**kwargs)
        self.save_job()
        return self
    
    # ========== 删除任务方法 ==========
    
    def delete_job(self, job_name: str, confirm: bool = True) -> "CronJobsPage":
        """删除任务"""
        row = self.get_job_row(job_name)
        row.locator(self.DELETE_BTN).click()
        
        if confirm:
            # 确认删除
            confirm_btn = self.page.locator('.ant-modal .ant-btn-danger:has-text("OK"), .qwenpaw-modal .qwenpaw-btn-danger:has-text("OK"), .ant-modal button:has-text("确定"), .qwenpaw-modal button:has-text("确定"), button:has-text("确认")')
            if confirm_btn.count() > 0:
                confirm_btn.click()
                expect(self.page.locator(self.DRAWER).first).to_be_hidden(timeout=10000)
        
        return self
    
    # ========== 启用/禁用任务 ==========
    
    def toggle_job_enabled(self, job_name: str) -> "CronJobsPage":
        """切换任务启用状态"""
        row = self.get_job_row(job_name)
        toggle = row.locator(self.ENABLE_TOGGLE)
        toggle.click()
        return self
    
    def enable_job(self, job_name: str) -> "CronJobsPage":
        """启用任务"""
        row = self.get_job_row(job_name)
        toggle = row.locator(self.ENABLE_TOGGLE)
        is_enabled = toggle.first.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked')")
        if not is_enabled:
            toggle.click()
        return self
    
    def disable_job(self, job_name: str) -> "CronJobsPage":
        """禁用任务"""
        row = self.get_job_row(job_name)
        toggle = row.locator(self.ENABLE_TOGGLE)
        is_enabled = toggle.first.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked')")
        if is_enabled:
            toggle.click()
        return self
    
    # ========== 执行任务 ==========
    
    def execute_job_now(self, job_name: str) -> "CronJobsPage":
        """立即执行任务"""
        row = self.get_job_row(job_name)
        execute_btn = row.locator(self.EXECUTE_NOW_BTN)
        if execute_btn.count() == 0:
            # 尝试点击操作菜单
            row.locator('.ant-btn:has(svg)').first.click()
            execute_btn = self.page.locator('.ant-dropdown .ant-dropdown-menu-item:has-text("Execute")')
        execute_btn.click()
        return self
    
    # ========== 断言方法 ==========
    
    def assert_job_exists(self, job_name: str) -> "CronJobsPage":
        """断言任务存在"""
        assert self.job_exists(job_name), f"任务 '{job_name}' 不存在"
        return self
    
    def assert_job_not_exists(self, job_name: str) -> "CronJobsPage":
        """断言任务不存在"""
        assert not self.job_exists(job_name), f"任务 '{job_name}' 应该不存在"
        return self
    
    def assert_job_enabled(self, job_name: str) -> "CronJobsPage":
        """断言任务已启用"""
        row = self.get_job_row(job_name)
        # 先尝试 switch 组件
        toggle = row.locator(self.ENABLE_TOGGLE)
        if toggle.count() > 0:
            is_enabled = toggle.first.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked') || el.getAttribute('aria-checked') === 'true'")
            assert is_enabled, f"任务 '{job_name}' 应该是启用状态"
        else:
            # 回退到文本检查
            row_text = row.inner_text()
            assert "启用" in row_text or "enabled" in row_text.lower() or "是" in row_text, f"任务 '{job_name}' 应该是启用状态，行内容：{row_text[:100]}"
        return self
    
    def assert_job_disabled(self, job_name: str) -> "CronJobsPage":
        """断言任务已禁用"""
        row = self.get_job_row(job_name)
        toggle = row.locator(self.ENABLE_TOGGLE)
        if toggle.count() > 0:
            is_enabled = toggle.first.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked') || el.getAttribute('aria-checked') === 'true'")
            assert not is_enabled, f"任务 '{job_name}' 应该是禁用状态"
        else:
            row_text = row.inner_text()
            assert "禁用" in row_text or "disabled" in row_text.lower() or "否" in row_text, f"任务 '{job_name}' 应该是禁用状态，行内容：{row_text[:100]}"
        return self
