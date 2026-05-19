# -*- coding: utf-8 -*-
"""
QwenPaw Backups 备份管理页面对象

封装备份管理页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class BackupsPage(BasePage):
    """
    Backups 备份管理页面对象

    封装备份管理页面的所有用户操作：
    - 页面导航与加载
    - 备份列表展示与搜索
    - 创建备份（全量/部分）
    - 恢复备份
    - 导入备份
    - 删除与导出备份
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/backups"

    # ========== 选择器定义 ==========

    # 页面容器与加载标志
    PAGE_CONTAINER = 'div[class*="backups"], div[class*="Backups"], [class*="backup"]'
    PAGE_LOAD_INDICATOR = '.qwenpaw-table, [class*="backup"]'
    BREADCRUMB_PARENT = 'span[class*="breadcrumbParent"]'
    BREADCRUMB_CURRENT = 'span[class*="breadcrumbCurrent"]'

    # 备份列表表格
    BACKUP_TABLE = ".qwenpaw-table"
    BACKUP_TABLE_ROW = ".qwenpaw-table-tbody tr"
    BACKUP_TABLE_HEADER = ".qwenpaw-table-thead th"
    EMPTY_STATE = ".qwenpaw-empty, [class*='empty']"

    # 操作按钮
    CREATE_BACKUP_BUTTON = 'button:has-text("Create Backup"), button:has-text("创建备份")'
    IMPORT_BUTTON = 'button:has-text("Import"), button:has-text("导入")'
    SEARCH_INPUT = '.qwenpaw-input-search input, input[placeholder*="search"], input[placeholder*="搜索"], input[placeholder*="Search"]'

    # 表格行操作
    EXPORT_BUTTON = 'button:has-text("Export"), button:has-text("导出"), [class*="export"]'
    RESTORE_BUTTON = 'button:has-text("Restore"), button:has-text("恢复")'
    DELETE_BUTTON = 'button:has-text("Delete"), button:has-text("删除")'

    # 模态框
    MODAL = ".qwenpaw-modal"
    MODAL_TITLE = ".qwenpaw-modal-title"
    MODAL_OK_BUTTON = '.qwenpaw-modal-footer button.qwenpaw-btn-primary, .qwenpaw-modal-footer button:has-text("OK"), .qwenpaw-modal-footer button:has-text("确定")'
    MODAL_CANCEL_BUTTON = '.qwenpaw-modal-footer button:has-text("Cancel"), .qwenpaw-modal-footer button:has-text("取消")'
    MODAL_CLOSE = ".qwenpaw-modal-close"

    # 创建备份模态框
    CREATE_MODAL = '.qwenpaw-modal:has-text("Create Backup"), .qwenpaw-modal:has-text("创建备份")'
    FULL_BACKUP_OPTION = 'label:has-text("Full"), label:has-text("全量"), [data-value="full"]'
    PARTIAL_BACKUP_OPTION = 'label:has-text("Partial"), label:has-text("部分"), [data-value="partial"]'
    BACKUP_NAME_INPUT = 'input[placeholder*="name"], input[placeholder*="名称"], .qwenpaw-modal input.qwenpaw-input'
    AGENT_SELECT = '.qwenpaw-modal [class*="agent"] .qwenpaw-select, .qwenpaw-modal [class*="Agent"]'
    PROGRESS_BAR = '.qwenpaw-progress, [class*="progress"]'

    # 恢复备份模态框
    RESTORE_MODAL = '.qwenpaw-modal:has-text("Restore"), .qwenpaw-modal:has-text("恢复")'
    FULL_RESTORE_OPTION = 'label:has-text("Full"), label:has-text("全量恢复")'
    CUSTOM_RESTORE_OPTION = 'label:has-text("Custom"), label:has-text("自定义")'
    PRE_RESTORE_CONFIRM = '.qwenpaw-modal:has-text("snapshot"), .qwenpaw-modal:has-text("快照")'

    # 导入冲突模态框
    CONFLICT_MODAL = '.qwenpaw-modal:has-text("conflict"), .qwenpaw-modal:has-text("冲突"), .qwenpaw-modal:has-text("Conflict")'
    OVERWRITE_BUTTON = 'button:has-text("Overwrite"), button:has-text("覆盖")'

    # 消息提示
    SUCCESS_TOAST = '.qwenpaw-message-success, .qwenpaw-notification-success'
    ERROR_TOAST = '.qwenpaw-message-error, .qwenpaw-notification-error'

    # 通用开关和加载
    SWITCH = ".qwenpaw-switch"
    CHECKBOX = ".qwenpaw-checkbox"
    SPIN = ".qwenpaw-spin"

    # ========== 初始化 ==========

    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("BackupsPage initialized")

    # ========== 页面导航 ==========

    def open(self) -> "BackupsPage":
        """打开备份管理页面"""
        logger.info("打开 Backups 备份管理页面")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "BackupsPage":
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
        """验证面包屑包含 Settings 和 Backups"""
        text = self.get_breadcrumb_text()
        has_settings = "Settings" in text or "设置" in text
        has_backups = "Backups" in text or "备份" in text
        return has_settings and has_backups

    # ========== 备份列表操作 ==========

    def get_backup_rows(self) -> List[Locator]:
        """获取备份列表所有行"""
        rows = self.page.locator(self.BACKUP_TABLE_ROW).all()
        logger.info(f"找到 {len(rows)} 条备份记录")
        return rows

    def get_backup_count(self) -> int:
        """获取备份数量"""
        return len(self.get_backup_rows())

    def is_empty_state(self) -> bool:
        """判断是否为空状态"""
        empty = self.page.locator(self.EMPTY_STATE).first
        return empty.is_visible(timeout=3000)

    def search_backup(self, keyword: str) -> "BackupsPage":
        """搜索备份"""
        search_input = self.page.locator(self.SEARCH_INPUT).first
        if search_input.is_visible(timeout=5000):
            search_input.fill(keyword)
            self.page.wait_for_timeout(1000)
            logger.info(f"搜索备份关键词: {keyword}")
        else:
            logger.warning("未找到搜索输入框")
        return self

    def get_table_headers(self) -> List[str]:
        """获取表格列头文本"""
        headers = self.page.locator(self.BACKUP_TABLE_HEADER).all()
        return [header.inner_text().strip() for header in headers if header.inner_text().strip()]

    # ========== 创建备份 ==========

    def click_create_backup(self) -> "BackupsPage":
        """点击创建备份按钮"""
        create_btn = self.page.locator(self.CREATE_BACKUP_BUTTON).first
        expect(create_btn).to_be_visible(timeout=5000)
        create_btn.click()
        self.page.wait_for_timeout(500)
        logger.info("点击创建备份按钮")
        return self

    def is_create_modal_visible(self) -> bool:
        """判断创建备份模态框是否可见"""
        modal = self.page.locator(self.MODAL).first
        return modal.is_visible(timeout=5000)

    def select_full_backup(self) -> "BackupsPage":
        """选择全量备份"""
        full_option = self.page.locator(self.FULL_BACKUP_OPTION).first
        if full_option.is_visible(timeout=3000):
            full_option.click()
            logger.info("选择全量备份模式")
        return self

    def select_partial_backup(self) -> "BackupsPage":
        """选择部分备份"""
        partial_option = self.page.locator(self.PARTIAL_BACKUP_OPTION).first
        if partial_option.is_visible(timeout=3000):
            partial_option.click()
            logger.info("选择部分备份模式")
        return self

    def fill_backup_name(self, name: str) -> "BackupsPage":
        """填写备份名称"""
        name_input = self.page.locator(self.BACKUP_NAME_INPUT).first
        if name_input.is_visible(timeout=3000):
            name_input.fill(name)
            logger.info(f"填写备份名称: {name}")
        return self

    def confirm_create_backup(self) -> "BackupsPage":
        """确认创建备份"""
        ok_btn = self.page.locator(self.MODAL_OK_BUTTON).first
        if ok_btn.is_visible(timeout=3000):
            ok_btn.click()
            logger.info("确认创建备份")
            self.page.wait_for_timeout(2000)
        return self

    def cancel_create_backup(self) -> "BackupsPage":
        """取消创建备份"""
        cancel_btn = self.page.locator(self.MODAL_CANCEL_BUTTON).first
        if cancel_btn.is_visible(timeout=3000):
            cancel_btn.click()
            logger.info("取消创建备份")
        return self

    def is_progress_visible(self) -> bool:
        """判断进度条是否可见"""
        progress = self.page.locator(self.PROGRESS_BAR).first
        return progress.is_visible(timeout=3000)

    # ========== 导入备份 ==========

    def click_import_button(self) -> "BackupsPage":
        """点击导入按钮"""
        import_btn = self.page.locator(self.IMPORT_BUTTON).first
        if import_btn.is_visible(timeout=5000):
            import_btn.click()
            logger.info("点击导入按钮")
            self.page.wait_for_timeout(500)
        return self

    # ========== 行级操作 ==========

    def click_row_restore(self, row: Locator) -> "BackupsPage":
        """点击行中的恢复按钮"""
        restore_btn = row.locator(self.RESTORE_BUTTON).first
        if restore_btn.is_visible(timeout=3000):
            restore_btn.click()
            logger.info("点击行恢复按钮")
            self.page.wait_for_timeout(500)
        return self

    def click_row_delete(self, row: Locator) -> "BackupsPage":
        """点击行中的删除按钮"""
        delete_btn = row.locator(self.DELETE_BUTTON).first
        if delete_btn.is_visible(timeout=3000):
            delete_btn.click()
            logger.info("点击行删除按钮")
            self.page.wait_for_timeout(500)
        return self

    def click_row_export(self, row: Locator) -> "BackupsPage":
        """点击行中的导出按钮"""
        export_btn = row.locator(self.EXPORT_BUTTON).first
        if export_btn.is_visible(timeout=3000):
            export_btn.click()
            logger.info("点击行导出按钮")
            self.page.wait_for_timeout(500)
        return self

    # ========== 模态框操作 ==========

    def confirm_modal(self) -> "BackupsPage":
        """确认模态框"""
        ok_btn = self.page.locator(self.MODAL_OK_BUTTON).first
        if ok_btn.is_visible(timeout=5000):
            ok_btn.click()
            self.page.wait_for_timeout(1000)
            logger.info("确认模态框操作")
        return self

    def cancel_modal(self) -> "BackupsPage":
        """取消模态框"""
        cancel_btn = self.page.locator(self.MODAL_CANCEL_BUTTON).first
        if cancel_btn.is_visible(timeout=3000):
            cancel_btn.click()
            self.page.wait_for_timeout(500)
            logger.info("取消模态框操作")
        return self

    def close_modal(self) -> "BackupsPage":
        """关闭模态框"""
        close_btn = self.page.locator(self.MODAL_CLOSE).first
        if close_btn.is_visible(timeout=3000):
            close_btn.click()
            self.page.wait_for_timeout(500)
            logger.info("关闭模态框")
        return self

    def is_modal_visible(self) -> bool:
        """判断是否有模态框可见"""
        modal = self.page.locator(self.MODAL).first
        return modal.is_visible(timeout=3000)

    # ========== 恢复备份 ==========

    def is_restore_modal_visible(self) -> bool:
        """判断恢复模态框是否可见"""
        modal = self.page.locator(self.RESTORE_MODAL).first
        return modal.is_visible(timeout=5000)

    def is_pre_restore_confirm_visible(self) -> bool:
        """判断恢复前确认（快照提示）是否可见"""
        confirm = self.page.locator(self.PRE_RESTORE_CONFIRM).first
        return confirm.is_visible(timeout=3000)

    # ========== 消息断言 ==========

    def wait_for_success_message(self, timeout: Optional[int] = None) -> bool:
        """等待成功消息出现"""
        try:
            self.page.locator(self.SUCCESS_TOAST).first.wait_for(
                state="visible", timeout=timeout or 10000
            )
            return True
        except Exception:
            return False

    def wait_for_error_message(self, timeout: Optional[int] = None) -> bool:
        """等待错误消息出现"""
        try:
            self.page.locator(self.ERROR_TOAST).first.wait_for(
                state="visible", timeout=timeout or 5000
            )
            return True
        except Exception:
            return False

    # ========== 断言方法 ==========

    def assert_page_loaded(self, timeout: Optional[int] = None) -> "BackupsPage":
        """断言页面已加载"""
        timeout = timeout or self.timeout
        page_indicator = self.page.locator(
            f'{self.CREATE_BACKUP_BUTTON}, {self.BACKUP_TABLE}, {self.EMPTY_STATE}'
        ).first
        expect(page_indicator).to_be_visible(timeout=timeout)
        return self

    def assert_backup_count(self, expected: int, timeout: Optional[int] = None) -> "BackupsPage":
        """断言备份数量"""
        expect(self.page.locator(self.BACKUP_TABLE_ROW)).to_have_count(
            expected, timeout=timeout or self.timeout
        )
        return self
