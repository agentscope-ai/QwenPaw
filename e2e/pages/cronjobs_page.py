# -*- coding: utf-8 -*-
"""
QwenPaw CronJobs page object.

Wraps all interactions on the CronJobs page and exposes business-level methods.
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
    CronJobs page object.

    Wraps all user interactions on the CronJobs page:
    - List scheduled jobs
    - Create a scheduled job
    - Edit a scheduled job
    - Delete a scheduled job
    - Enable/disable a job
    - Run a job immediately
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/cron-jobs"

    # ========== Selector definitions ==========

    # Page-loaded indicator (the page has no h1; use the create button as the load-complete marker)
    PAGE_LOAD_INDICATOR = 'button:has-text("创建任务"), button:has-text("Create Job"), .qwenpaw-table, .ant-table'

    # Create button (UI text is in Chinese)
    CREATE_JOB_BTN = 'button:has-text("创建任务"), button:has-text("+ 创建任务"), button:has-text("Create Job"), button:has-text("+ Create Job")'

    # Table selectors
    JOB_TABLE = ".ant-table, .qwenpaw-table, table"
    JOB_TABLE_ROW = ".ant-table-tbody > tr, .qwenpaw-table-tbody > tr, table tbody tr"

    # Job action buttons
    EDIT_BTN = 'button:has-text("Edit"), button:has-text("编辑"), .ant-btn:has(svg):not(:has-text("Delete")):not(:has-text("删除"))'
    DELETE_BTN = 'button:has-text("Delete"), button:has-text("删除")'
    ENABLE_TOGGLE = '.ant-switch, .qwenpaw-switch'
    EXECUTE_NOW_BTN = 'button:has-text("Execute Now"), button:has-text("Run"), button:has-text("立即执行"), button:has-text("执行")'

    # Drawer / dialog
    DRAWER = ".ant-drawer, .qwenpaw-drawer, [class*=drawer]"
    DRAWER_TITLE = ".ant-drawer-title, .qwenpaw-drawer-title"
    DRAWER_SAVE_BTN = '.ant-drawer .ant-btn-primary:has-text("Save"), .ant-drawer button:has-text("OK"), [class*=drawer] button:has-text("Save"), [class*=drawer] button:has-text("OK"), [class*=drawer] button:has-text("保存"), [class*=drawer] button:has-text("保 存"), [class*=drawer] button:has-text("确定"), [class*=drawer] .qwenpaw-btn-primary'
    DRAWER_CANCEL_BTN = '.ant-drawer .ant-btn:has-text("Cancel"), [class*=drawer] button:has-text("取消"), [class*=drawer] button:has-text("取 消")'

    # Form fields
    JOB_NAME_INPUT = 'input#name, input[id*="jobName"], input[placeholder*="Job Name" i], input[placeholder*="任务名称" i], input[placeholder*="每日早报" i]'
    CRON_EXPRESSION_INPUT = '#schedule_cron'
    TIMEZONE_SELECT = '.ant-select[data-placeholder*="Timezone" i], .qwenpaw-select[data-placeholder*="时区" i]'
    TASK_TYPE_SELECT = '.ant-select[data-placeholder*="Task Type" i], .qwenpaw-select[data-placeholder*="任务类型" i]'
    DESCRIPTION_INPUT = 'textarea[id*="description"], textarea[placeholder*="Description" i], textarea[placeholder*="描述" i]'
    ENABLED_SWITCH = '.ant-switch, .qwenpaw-switch'

    # Filter and search
    SEARCH_INPUT = 'input[placeholder*="Search" i], input[placeholder*="搜索" i]'

    # ========== Helper methods ==========

    def _select_option(self, field_id: str, value: str) -> None:
        """Interact with an Ant Design Select (showSearch) component:
        check current value -> click to open if change needed -> type to search -> pick the option."""
        select = self.page.locator(f'{field_id}')
        if select.count() == 0 or not select.first.is_visible():
            return
        # Check whether the Select already holds the target value
        current_value = select.first.locator('.qwenpaw-select-selection-item, .ant-select-selection-item')
        if current_value.count() > 0 and current_value.first.is_visible():
            current_text = current_value.first.inner_text().strip()
            if current_text == value:
                return  # Already correct, skip
        # Click the Select's selector area to open the dropdown (bypass occlusion via JS)
        selector = select.first.locator('.qwenpaw-select-selector, .ant-select-selector')
        if selector.count() > 0:
            selector.first.evaluate("el => el.click()")
        else:
            select.first.evaluate("el => el.click()")
        self.page.wait_for_timeout(500)
        # Type the search value (use type rather than fill because the input may be readonly)
        self.page.keyboard.type(value, delay=50)
        self.page.wait_for_timeout(500)
        # Try clicking the matching option
        option = self.page.locator(f'.qwenpaw-select-item-option-content:has-text("{value}")').first
        if option.is_visible(timeout=1500):
            option.click()
        else:
            self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(300)

    # ========== Navigation methods ==========

    def open(self) -> "CronJobsPage":
        """Open the CronJobs page."""
        logger.info("Opening CronJobs page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "CronJobsPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        # Wait for the table to appear (the page has no h1)
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== List operation methods ==========

    def get_job_count(self) -> int:
        """Get the number of jobs."""
        rows = self.page.locator(self.JOB_TABLE_ROW)
        return rows.count()

    def get_job_row(self, job_name: str) -> Locator:
        """Get the row of the given job (excluding hidden rows and placeholder rows)."""
        return self.page.locator(f"tr:not([aria-hidden='true']):not(.qwenpaw-table-placeholder):not(.qwenpaw-table-measure-row):has-text('{job_name}')")

    def job_exists(self, job_name: str) -> bool:
        """Check whether the job exists (traverses all pages of pagination)."""
        self.page.wait_for_timeout(500)
        if self.get_job_row(job_name).count() > 0:
            return True

        # Iterate through pagination to look up
        pagination_items = self.page.locator('.qwenpaw-pagination-item:not(.qwenpaw-pagination-item-active)').all()
        for page_item in pagination_items:
            if page_item.is_visible():
                page_item.click()
                self.page.wait_for_timeout(1000)
                if self.get_job_row(job_name).count() > 0:
                    return True

        return False

    def search_job(self, keyword: str) -> "CronJobsPage":
        """Search jobs."""
        search_input = self.page.locator(self.SEARCH_INPUT)
        if search_input.count() > 0:
            search_input.fill(keyword)
        return self

    # ========== Create job methods ==========

    def click_create_job(self) -> "CronJobsPage":
        """Click the Create Job button."""
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
        """Fill in the job form.

        Required fields (source: JobDrawer.tsx):
        - name: job name
        - dispatch.channel: dispatch channel (required)
        - dispatch.target.user_id: target user id (required)
        - dispatch.target.session_id: target session id (required)
        - task_type: task type (text/agent, required)
        - text: text content (required when task_type=text)
        - request.input: request payload (required when task_type=agent; must be valid JSON)
        """
        # Fill in the job name
        job_name_input = self.page.locator('#name')
        if job_name_input.count() > 0:
            job_name_input.fill(job_name)

        # Select task type (Ant Design Select; default is agent)
        self._select_option('#task_type', task_type)
        self.page.wait_for_timeout(500)

        # Use the default "Daily" schedule; do not switch to a custom Cron
        cron_input = self.page.locator(self.CRON_EXPRESSION_INPUT)
        if cron_input.count() > 0 and cron_input.first.is_visible():
            cron_input.first.click()
            cron_input.first.fill(cron_expression)

        # Fill in the text content (required field for text-type tasks)
        text_textarea = self.page.locator('#text')
        if text_textarea.count() > 0 and text_textarea.first.is_visible():
            text_textarea.first.fill(description or "E2E test task content")

        # Fill in the request payload (required for agent-type tasks; must be valid JSON)
        request_textarea = self.page.locator('#request_input')
        if request_textarea.count() > 0 and request_textarea.first.is_visible():
            request_textarea.first.fill(request_input)

        # Fill in the dispatch channel (Ant Design Select with showSearch)
        self._select_option('#dispatch_channel', dispatch_channel)

        # Fill in the target user id (Ant Design Select with showSearch)
        self._select_option('#dispatch_target_user_id', target_user_id)

        # Fill in the target session id (Ant Design Select with showSearch)
        self._select_option('#dispatch_target_session_id', target_session_id)

        return self

    def save_job(self) -> "CronJobsPage":
        """Save the job."""
        # Close any open dropdowns
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(300)
        # Trigger the save button via JS, bypassing Select component occlusion
        save_btn = self.page.locator(self.DRAWER_SAVE_BTN).first
        save_btn.evaluate("""el => {
            // React needs a native event; try both dispatchEvent and native click
            const evt = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
            el.dispatchEvent(evt);
            el.click();
        }""")
        self.page.wait_for_timeout(2000)
        # If the drawer is still visible, close it manually
        drawer = self.page.locator('.qwenpaw-drawer:visible, .ant-drawer:visible')
        if drawer.count() > 0:
            close_btn = self.page.locator('.qwenpaw-drawer-close, .ant-drawer-close')
            if close_btn.count() > 0 and close_btn.first.is_visible():
                close_btn.first.click()
                self.page.wait_for_timeout(500)
        # Reload to make sure the list is up-to-date
        self.page.reload()
        self.wait_for_page_loaded()
        return self

    def cancel_job_creation(self) -> "CronJobsPage":
        """Cancel creating the job."""
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
        """End-to-end flow for creating a job."""
        self.click_create_job()
        self.fill_job_form(job_name, cron_expression, timezone, task_type, description, enabled)
        self.save_job()
        return self

    # ========== Edit job methods ==========

    def click_edit_job(self, job_name: str) -> "CronJobsPage":
        """Click the edit button for a job."""
        row = self.get_job_row(job_name)
        edit_btn = row.locator(self.EDIT_BTN)
        if edit_btn.count() == 0:
            # Try clicking the action menu
            row.locator('.ant-btn:has(svg)').first.click()
            edit_btn = self.page.locator('.ant-dropdown .ant-dropdown-menu-item:has-text("Edit")')
        edit_btn.click()
        expect(self.page.locator(self.DRAWER).first).to_be_visible()
        return self

    def update_job(self, job_name: str, **kwargs) -> "CronJobsPage":
        """Update a job."""
        self.click_edit_job(job_name)
        self.fill_job_form(**kwargs)
        self.save_job()
        return self

    # ========== Delete job methods ==========

    def delete_job(self, job_name: str, confirm: bool = True) -> "CronJobsPage":
        """Delete a job."""
        row = self.get_job_row(job_name)
        row.locator(self.DELETE_BTN).click()

        if confirm:
            # Confirm deletion
            confirm_btn = self.page.locator('.ant-modal .ant-btn-danger:has-text("OK"), .qwenpaw-modal .qwenpaw-btn-danger:has-text("OK"), .ant-modal button:has-text("确定"), .qwenpaw-modal button:has-text("确定"), button:has-text("确认")')
            if confirm_btn.count() > 0:
                confirm_btn.click()
                expect(self.page.locator(self.DRAWER).first).to_be_hidden(timeout=10000)

        return self

    # ========== Enable/disable job ==========

    def toggle_job_enabled(self, job_name: str) -> "CronJobsPage":
        """Toggle a job's enabled state."""
        row = self.get_job_row(job_name)
        toggle = row.locator(self.ENABLE_TOGGLE)
        toggle.click()
        return self

    def enable_job(self, job_name: str) -> "CronJobsPage":
        """Enable a job."""
        row = self.get_job_row(job_name)
        toggle = row.locator(self.ENABLE_TOGGLE)
        is_enabled = toggle.first.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked')")
        if not is_enabled:
            toggle.click()
        return self

    def disable_job(self, job_name: str) -> "CronJobsPage":
        """Disable a job."""
        row = self.get_job_row(job_name)
        toggle = row.locator(self.ENABLE_TOGGLE)
        is_enabled = toggle.first.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked')")
        if is_enabled:
            toggle.click()
        return self

    # ========== Execute job ==========

    def execute_job_now(self, job_name: str) -> "CronJobsPage":
        """Execute a job immediately."""
        row = self.get_job_row(job_name)
        execute_btn = row.locator(self.EXECUTE_NOW_BTN)
        if execute_btn.count() == 0:
            # Try clicking the action menu
            row.locator('.ant-btn:has(svg)').first.click()
            execute_btn = self.page.locator('.ant-dropdown .ant-dropdown-menu-item:has-text("Execute")')
        execute_btn.click()
        return self

    # ========== Assertion methods ==========

    def assert_job_exists(self, job_name: str) -> "CronJobsPage":
        """Assert the job exists."""
        assert self.job_exists(job_name), f"Job '{job_name}' does not exist"
        return self

    def assert_job_not_exists(self, job_name: str) -> "CronJobsPage":
        """Assert the job does not exist."""
        assert not self.job_exists(job_name), f"Job '{job_name}' should not exist"
        return self

    def assert_job_enabled(self, job_name: str) -> "CronJobsPage":
        """Assert the job is enabled."""
        row = self.get_job_row(job_name)
        # Try the switch component first
        toggle = row.locator(self.ENABLE_TOGGLE)
        if toggle.count() > 0:
            is_enabled = toggle.first.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked') || el.getAttribute('aria-checked') === 'true'")
            assert is_enabled, f"Job '{job_name}' should be enabled"
        else:
            # Fall back to text check
            row_text = row.inner_text()
            assert "启用" in row_text or "enabled" in row_text.lower() or "是" in row_text, f"Job '{job_name}' should be enabled; row text: {row_text[:100]}"
        return self

    def assert_job_disabled(self, job_name: str) -> "CronJobsPage":
        """Assert the job is disabled."""
        row = self.get_job_row(job_name)
        toggle = row.locator(self.ENABLE_TOGGLE)
        if toggle.count() > 0:
            is_enabled = toggle.first.evaluate("el => el.classList.contains('ant-switch-checked') || el.classList.contains('qwenpaw-switch-checked') || el.getAttribute('aria-checked') === 'true'")
            assert not is_enabled, f"Job '{job_name}' should be disabled"
        else:
            row_text = row.inner_text()
            assert "禁用" in row_text or "disabled" in row_text.lower() or "否" in row_text, f"Job '{job_name}' should be disabled; row text: {row_text[:100]}"
        return self
