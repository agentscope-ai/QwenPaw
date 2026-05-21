# -*- coding: utf-8 -*-
"""
QwenPaw Sessions 页面对象

封装 Sessions 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class SessionsPage(BasePage):
    """
    Sessions 页面对象
    
    封装 Sessions 页面的所有用户操作：
    - 会话列表展示
    - 会话过滤（UserID/Channel）
    - 会话排序
    - 编辑会话
    - 删除会话
    - 批量删除
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/sessions"
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志（页面无 h1 标签，使用表格作为加载完成标志）
    PAGE_LOAD_INDICATOR = '.ant-table, .qwenpaw-table, table'
    
    # 过滤栏
    FILTER_USER_ID_INPUT = 'input[placeholder*="User ID" i], input[placeholder*="用户" i]'
    FILTER_CHANNEL_SELECT = '.ant-select[data-placeholder*="Channel" i], .qwenpaw-select'
    FILTER_RESET_BTN = 'button:has-text("Reset"), button:has-text("重置")'
    
    # 会话表格
    SESSION_TABLE = '.ant-table, .qwenpaw-table, table'
    SESSION_ROW = '.ant-table-tbody tr, .qwenpaw-table-tbody tr, table tbody tr'
    SESSION_TABLE_ROW = '.ant-table-tbody tr, .qwenpaw-table-tbody tr, table tbody tr'
    SESSION_ROW_SELECTED = '.ant-table-tbody tr.ant-table-row-selected, .qwenpaw-table-tbody tr.qwenpaw-table-row-selected'
    
    # 表格列
    SESSION_ID_COL = 'td:nth-child(1)'
    SESSION_NAME_COL = 'td:nth-child(2)'
    SESSION_SESSIONID_COL = 'td:nth-child(3)'
    SESSION_USERID_COL = 'td:nth-child(4)'
    SESSION_CHANNEL_COL = 'td:nth-child(5)'
    SESSION_CREATEDAT_COL = 'td:nth-child(6)'
    SESSION_UPDATEDAT_COL = 'td:nth-child(7)'
    
    # 操作按钮
    # 注意：被测系统的 Action 列在 antd Table 中使用 fixed="right"，
    # 渲染时会被 Ant Design 拆到独立的"右固定影子表"中，行 locator 的 scope
    # 不一定能直接定位到这些按钮。下面的选择器同时覆盖：
    # 1) 行内直接找文本按钮（最理想情况）
    # 2) 通过 fix-right 列查找（fixed 列实际位置）
    # 3) Button type="link" 的小按钮
    EDIT_BTN = (
        'button:has-text("Edit"), button:has-text("编辑"), '
        'a:has-text("Edit"), a:has-text("编辑"), '
        '.qwenpaw-table-cell-fix-right button:has-text("Edit"), '
        '.qwenpaw-table-cell-fix-right button:has-text("编辑"), '
        '.ant-table-cell-fix-right button:has-text("Edit"), '
        '.ant-table-cell-fix-right button:has-text("编辑")'
    )
    DELETE_BTN = (
        'button:has-text("Delete"), button:has-text("删除"), '
        'a:has-text("Delete"), a:has-text("删除"), '
        '.qwenpaw-table-cell-fix-right button:has-text("Delete"), '
        '.qwenpaw-table-cell-fix-right button:has-text("删除"), '
        '.ant-table-cell-fix-right button:has-text("Delete"), '
        '.ant-table-cell-fix-right button:has-text("删除")'
    )
    BATCH_DELETE_BTN = 'button:has-text("Batch Delete"), button:has-text("批量删除")'
    
    # 分页
    PAGINATION = '.ant-pagination'
    PAGINATION_NEXT = '.ant-pagination-next'
    PAGINATION_PREV = '.ant-pagination-prev'
    
    # 编辑抽屉
    SESSION_DRAWER = '[class*=drawer], .ant-drawer, .qwenpaw-drawer'
    DRAWER_TITLE = '[class*=drawer] .ant-drawer-header-title, .ant-drawer-title, .qwenpaw-drawer-title'
    DRAWER_CLOSE = '.ant-drawer-close, .qwenpaw-drawer-close'
    
    # 表单字段
    FORM_NAME_INPUT = 'input[name="name"], input[placeholder*="Name" i], input[placeholder*="名称" i]'
    FORM_USERID_INPUT = 'input[name="user_id"], input[placeholder*="User ID" i], input[placeholder*="用户" i]'
    FORM_CHANNEL_SELECT = '.ant-select[name="channel"], .qwenpaw-select[name="channel"]'
    FORM_SUBMIT_BTN = '[class*=drawer] button.ant-btn-primary, [class*=drawer] button.qwenpaw-btn-primary, button:has-text("Save"), button:has-text("保存")'
    FORM_CANCEL_BTN = '[class*=drawer] button:has-text("Cancel"), [class*=drawer] button:has-text("取消")'
    
    # 确认对话框
    CONFIRM_MODAL = '.ant-modal, .qwenpaw-modal'
    CONFIRM_OK_BTN = '.ant-modal .ant-btn-primary, .qwenpaw-modal .qwenpaw-btn-primary, button:has-text("OK"), button:has-text("确认"), button:has-text("确定")'
    CONFIRM_CANCEL_BTN = '.ant-modal .ant-btn:not(.ant-btn-primary), .qwenpaw-modal .qwenpaw-btn:not(.qwenpaw-btn-primary), button:has-text("Cancel"), button:has-text("取消")'
    
    # 空状态
    EMPTY_STATE = '.ant-empty, [class*=empty]'
    
    # 消息提示和加载状态（继承自 BasePage，此处无需重复定义）
    
    # ========== 初始化 ==========
    
    def __init__(self, page: Page):
        super().__init__(page)
    
    # ========== 导航方法 ==========
    
    def open(self) -> "SessionsPage":
        """打开 Sessions 页面"""
        logger.info("Opening Sessions page")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "SessionsPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        logger.info("Waiting for Sessions page to load")
        
        # 等待表格出现（页面无 h1 标签）
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        
        return self
    
    # ========== 表格操作 ==========
    
    def get_session_rows(self) -> List[Locator]:
        """获取所有会话行"""
        return self.page.locator(self.SESSION_ROW).all()
    
    def get_session_count(self) -> int:
        """获取会话数量"""
        return len(self.get_session_rows())
    
    def find_session_row(self, session_id: str) -> Optional[Locator]:
        """
        根据会话 ID 查找会话行
        
        Args:
            session_id: 会话 ID
            
        Returns:
            会话行 Locator，未找到返回 None
        """
        rows = self.get_session_rows()
        for row in rows:
            try:
                id_cell = row.locator(self.SESSION_ID_COL).first
                if session_id in id_cell.inner_text():
                    return row
            except Exception:
                continue
        return None
    
    def find_session_by_name(self, name: str) -> Optional[Locator]:
        """根据会话名称查找会话行"""
        rows = self.get_session_rows()
        for row in rows:
            try:
                name_cell = row.locator(self.SESSION_NAME_COL).first
                if name.lower() in name_cell.inner_text().lower():
                    return row
            except Exception:
                continue
        return None
    
    def get_session_data(self, row: Locator) -> Dict[str, str]:
        """
        获取会话行数据
        
        Args:
            row: 会话行 Locator
            
        Returns:
            会话数据字典
        """
        return {
            'id': row.locator(self.SESSION_ID_COL).first.inner_text(),
            'name': row.locator(self.SESSION_NAME_COL).first.inner_text(),
            'session_id': row.locator(self.SESSION_SESSIONID_COL).first.inner_text(),
            'user_id': row.locator(self.SESSION_USERID_COL).first.inner_text(),
            'channel': row.locator(self.SESSION_CHANNEL_COL).first.inner_text(),
            'created_at': row.locator(self.SESSION_CREATEDAT_COL).first.inner_text(),
            'updated_at': row.locator(self.SESSION_UPDATEDAT_COL).first.inner_text(),
        }
    
    # ========== 过滤功能 ==========
    
    def filter_by_user_id(self, user_id: str) -> "SessionsPage":
        """按 UserID 过滤"""
        logger.info(f"Filtering by user_id: {user_id}")
        self.page.locator(self.FILTER_USER_ID_INPUT).first.fill(user_id)
        self.wait_for_loading()
        return self
    
    def filter_by_channel(self, channel: str) -> "SessionsPage":
        """按 Channel 过滤"""
        logger.info(f"Filtering by channel: {channel}")
        self.page.locator(self.FILTER_CHANNEL_SELECT).first.click()
        self.page.locator(f'.ant-select-option:has-text("{channel}")').first.click()
        self.wait_for_loading()
        return self
    
    def reset_filter(self) -> "SessionsPage":
        """重置过滤"""
        logger.info("Resetting filters")
        self.page.locator(self.FILTER_RESET_BTN).first.click()
        self.wait_for_loading()
        return self
    
    # ========== 排序功能 ==========
    
    def sort_by_column(self, column_name: str) -> "SessionsPage":
        """
        按列排序
        
        Args:
            column_name: 列名（ID, Name, CreatedAt 等）
        """
        logger.info(f"Sorting by {column_name}")
        sort_btn = self.page.locator(f'.ant-table-column-sorters:has-text("{column_name}")').first
        sort_btn.click()
        self.wait_for_loading()
        return self
    
    # ========== 编辑会话 ==========
    
    def click_edit(self, session_id: str) -> "SessionsPage":
        """
        点击编辑按钮
        
        Args:
            session_id: 会话 ID
        """
        logger.info(f"Clicking edit for session: {session_id}")
        row = self.find_session_row(session_id)
        if row:
            row.locator(self.EDIT_BTN).first.click()
            self.wait_for_drawer_open()
        else:
            raise Exception(f"Session not found: {session_id}")
        return self
    
    def wait_for_drawer_open(self, timeout: Optional[int] = None) -> "SessionsPage":
        """等待编辑抽屉打开"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.SESSION_DRAWER)).to_be_visible(timeout=timeout)
        return self
    
    def wait_for_drawer_close(self, timeout: Optional[int] = None) -> "SessionsPage":
        """等待编辑抽屉关闭"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.SESSION_DRAWER)).to_be_hidden(timeout=timeout)
        return self
    
    def fill_session_name(self, name: str) -> "SessionsPage":
        """填写会话名称"""
        self.page.locator(self.FORM_NAME_INPUT).first.fill(name)
        return self
    
    def fill_session_user_id(self, user_id: str) -> "SessionsPage":
        """填写 UserID"""
        self.page.locator(self.FORM_USERID_INPUT).first.fill(user_id)
        return self
    
    def select_channel(self, channel: str) -> "SessionsPage":
        """选择 Channel"""
        self.page.locator(self.FORM_CHANNEL_SELECT).first.click()
        self.page.locator(f'.ant-select-option:has-text("{channel}")').first.click()
        return self
    
    def save_session(self) -> "SessionsPage":
        """保存会话"""
        logger.info("Saving session")
        self.page.locator(self.FORM_SUBMIT_BTN).first.click()
        self.wait_for_loading()
        self.wait_for_success_message()
        self.wait_for_drawer_close()
        return self
    
    def cancel_session_edit(self) -> "SessionsPage":
        """取消编辑"""
        logger.info("Canceling session edit")
        self.page.locator(self.FORM_CANCEL_BTN).first.click()
        self.wait_for_drawer_close()
        return self
    
    # ========== 删除会话 ==========
    
    def click_delete(self, session_id: str) -> "SessionsPage":
        """
        点击删除按钮
        
        Args:
            session_id: 会话 ID
        """
        logger.info(f"Clicking delete for session: {session_id}")
        row = self.find_session_row(session_id)
        if row:
            row.locator(self.DELETE_BTN).first.click()
        else:
            raise Exception(f"Session not found: {session_id}")
        return self
    
    def confirm_delete(self) -> "SessionsPage":
        """确认删除"""
        logger.info("Confirming delete")
        self.page.locator(self.CONFIRM_OK_BTN).first.click()
        self.wait_for_loading()
        self.wait_for_success_message()
        return self
    
    def cancel_delete(self) -> "SessionsPage":
        """取消删除"""
        logger.info("Canceling delete")
        self.page.locator(self.CONFIRM_CANCEL_BTN).first.click()
        return self
    
    # ========== 批量删除 ==========
    
    def select_session(self, session_id: str) -> "SessionsPage":
        """选择会话（用于批量操作）"""
        row = self.find_session_row(session_id)
        if row:
            row.locator('input[type="checkbox"]').first.click()
        return self
    
    def select_all_sessions(self) -> "SessionsPage":
        """选择所有会话"""
        self.page.locator('thead input[type="checkbox"]').first.click()
        return self
    
    def click_batch_delete(self) -> "SessionsPage":
        """点击批量删除按钮"""
        logger.info("Clicking batch delete")
        self.page.locator(self.BATCH_DELETE_BTN).first.click()
        return self
    
    # ========== 验证方法 ==========
    
    def verify_session_exists(self, session_id: str) -> bool:
        """验证会话是否存在"""
        return self.find_session_row(session_id) is not None
    
    def verify_session_count(self, expected_count: int) -> bool:
        """验证会话数量"""
        actual_count = self.get_session_count()
        logger.info(f"Session count: {actual_count}, expected: {expected_count}")
        return actual_count == expected_count
    
    def verify_filter_result(self, expected_count: int) -> bool:
        """验证过滤结果"""
        return self.get_session_count() == expected_count
    
    def verify_session_data(self, session_id: str, expected_data: Dict[str, str]) -> bool:
        """验证会话数据"""
        row = self.find_session_row(session_id)
        if not row:
            return False
        
        actual_data = self.get_session_data(row)
        for key, expected_value in expected_data.items():
            if key in actual_data and actual_data[key] != expected_value:
                logger.error(f"{key}: expected {expected_value}, got {actual_data[key]}")
                return False
        
        return True
    
    def wait_for_success_message(self, timeout: int = 5000) -> bool:
        """等待成功消息"""
        try:
            expect(self.page.locator(self.SUCCESS_MESSAGE)).to_be_visible(timeout=timeout)
            return True
        except TimeoutError:
            return False
    
    def wait_for_error_message(self, timeout: int = 5000) -> bool:
        """等待错误消息"""
        try:
            expect(self.page.locator(self.ERROR_MESSAGE)).to_be_visible(timeout=timeout)
            return True
        except TimeoutError:
            return False
    
    def wait_for_loading(self, timeout: int = 3000) -> "SessionsPage":
        """等待加载完成"""
        try:
            loading = self.page.locator(self.LOADING_SPINNER)
            if loading.count() > 0:
                expect(loading).to_be_hidden(timeout=timeout)
        except Exception:
            pass
        return self
    
    def verify_empty_state(self) -> bool:
        """验证空状态"""
        try:
            return self.page.locator(self.EMPTY_STATE).first.is_visible()
        except Exception:
            return False