# -*- coding: utf-8 -*-
"""
QwenPaw Sessions page object.

Wraps all interactions on the Sessions page and exposes business-level methods.
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
    Sessions page object.

    Wraps all user interactions on the Sessions page:
    - List sessions
    - Filter sessions (UserID/Channel)
    - Sort sessions
    - Edit a session
    - Delete a session
    - Batch delete
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/sessions"

    # ========== Selector definitions ==========

    # Page-loaded indicator (the page has no h1; use the table as the load-complete marker)
    PAGE_LOAD_INDICATOR = '.ant-table, .qwenpaw-table, table'

    # Filter bar
    FILTER_USER_ID_INPUT = 'input[placeholder*="User ID" i], input[placeholder*="用户" i]'
    FILTER_CHANNEL_SELECT = '.ant-select[data-placeholder*="Channel" i], .qwenpaw-select'
    FILTER_RESET_BTN = 'button:has-text("Reset"), button:has-text("重置")'

    # Session table
    SESSION_TABLE = '.ant-table, .qwenpaw-table, table'
    SESSION_ROW = '.ant-table-tbody tr, .qwenpaw-table-tbody tr, table tbody tr'
    SESSION_TABLE_ROW = '.ant-table-tbody tr, .qwenpaw-table-tbody tr, table tbody tr'
    SESSION_ROW_SELECTED = '.ant-table-tbody tr.ant-table-row-selected, .qwenpaw-table-tbody tr.qwenpaw-table-row-selected'

    # Table columns
    SESSION_ID_COL = 'td:nth-child(1)'
    SESSION_NAME_COL = 'td:nth-child(2)'
    SESSION_SESSIONID_COL = 'td:nth-child(3)'
    SESSION_USERID_COL = 'td:nth-child(4)'
    SESSION_CHANNEL_COL = 'td:nth-child(5)'
    SESSION_CREATEDAT_COL = 'td:nth-child(6)'
    SESSION_UPDATEDAT_COL = 'td:nth-child(7)'

    # Action buttons
    # Note: the system under test uses fixed="right" for the Action column in antd Table,
    # which Ant Design splits into a separate "right-fixed shadow table" at render time. The row
    # locator's scope may not directly find these buttons. The selectors below cover, in order:
    # 1) text buttons directly inside the row (best case)
    # 2) look up via the fix-right column (where the fixed column actually lives)
    # 3) Button type="link" small buttons
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

    # Pagination
    PAGINATION = '.ant-pagination'
    PAGINATION_NEXT = '.ant-pagination-next'
    PAGINATION_PREV = '.ant-pagination-prev'

    # Edit drawer
    SESSION_DRAWER = '[class*=drawer], .ant-drawer, .qwenpaw-drawer'
    DRAWER_TITLE = '[class*=drawer] .ant-drawer-header-title, .ant-drawer-title, .qwenpaw-drawer-title'
    DRAWER_CLOSE = '.ant-drawer-close, .qwenpaw-drawer-close'

    # Form fields
    FORM_NAME_INPUT = 'input[name="name"], input[placeholder*="Name" i], input[placeholder*="名称" i]'
    FORM_USERID_INPUT = 'input[name="user_id"], input[placeholder*="User ID" i], input[placeholder*="用户" i]'
    FORM_CHANNEL_SELECT = '.ant-select[name="channel"], .qwenpaw-select[name="channel"]'
    FORM_SUBMIT_BTN = '[class*=drawer] button.ant-btn-primary, [class*=drawer] button.qwenpaw-btn-primary, button:has-text("Save"), button:has-text("保存")'
    FORM_CANCEL_BTN = '[class*=drawer] button:has-text("Cancel"), [class*=drawer] button:has-text("取消")'

    # Confirmation dialog
    CONFIRM_MODAL = '.ant-modal, .qwenpaw-modal'
    CONFIRM_OK_BTN = '.ant-modal .ant-btn-primary, .qwenpaw-modal .qwenpaw-btn-primary, button:has-text("OK"), button:has-text("确认"), button:has-text("确定")'
    CONFIRM_CANCEL_BTN = '.ant-modal .ant-btn:not(.ant-btn-primary), .qwenpaw-modal .qwenpaw-btn:not(.qwenpaw-btn-primary), button:has-text("Cancel"), button:has-text("取消")'

    # Empty state
    EMPTY_STATE = '.ant-empty, [class*=empty]'

    # Message toast and loading state (inherited from BasePage; no need to redefine here)

    # ========== Initialization ==========

    def __init__(self, page: Page):
        super().__init__(page)

    # ========== Navigation methods ==========

    def open(self) -> "SessionsPage":
        """Open the Sessions page."""
        logger.info("Opening Sessions page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "SessionsPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        logger.info("Waiting for Sessions page to load")

        # Wait for the table to appear (the page has no h1)
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)

        return self

    # ========== Table operations ==========

    def get_session_rows(self) -> List[Locator]:
        """Get all session rows."""
        return self.page.locator(self.SESSION_ROW).all()

    def get_session_count(self) -> int:
        """Get the number of sessions."""
        return len(self.get_session_rows())

    def find_session_row(self, session_id: str) -> Optional[Locator]:
        """
        Find a session row by session ID.

        Args:
            session_id: session ID

        Returns:
            Locator of the row; None if not found.
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
        """Find a session row by session name."""
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
        Get the data from a session row.

        Args:
            row: session row Locator

        Returns:
            dict of session fields
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

    # ========== Filtering ==========

    def filter_by_user_id(self, user_id: str) -> "SessionsPage":
        """Filter by UserID."""
        logger.info(f"Filtering by user_id: {user_id}")
        self.page.locator(self.FILTER_USER_ID_INPUT).first.fill(user_id)
        self.wait_for_loading()
        return self

    def filter_by_channel(self, channel: str) -> "SessionsPage":
        """Filter by Channel."""
        logger.info(f"Filtering by channel: {channel}")
        self.page.locator(self.FILTER_CHANNEL_SELECT).first.click()
        self.page.locator(f'.ant-select-option:has-text("{channel}")').first.click()
        self.wait_for_loading()
        return self

    def reset_filter(self) -> "SessionsPage":
        """Reset filters."""
        logger.info("Resetting filters")
        self.page.locator(self.FILTER_RESET_BTN).first.click()
        self.wait_for_loading()
        return self

    # ========== Sorting ==========

    def sort_by_column(self, column_name: str) -> "SessionsPage":
        """
        Sort by column.

        Args:
            column_name: column name (ID, Name, CreatedAt, etc.)
        """
        logger.info(f"Sorting by {column_name}")
        sort_btn = self.page.locator(f'.ant-table-column-sorters:has-text("{column_name}")').first
        sort_btn.click()
        self.wait_for_loading()
        return self

    # ========== Edit session ==========

    def click_edit(self, session_id: str) -> "SessionsPage":
        """
        Click the edit button.

        Args:
            session_id: session ID
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
        """Wait for the edit drawer to open."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.SESSION_DRAWER)).to_be_visible(timeout=timeout)
        return self

    def wait_for_drawer_close(self, timeout: Optional[int] = None) -> "SessionsPage":
        """Wait for the edit drawer to close."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.SESSION_DRAWER)).to_be_hidden(timeout=timeout)
        return self

    def fill_session_name(self, name: str) -> "SessionsPage":
        """Fill in the session name."""
        self.page.locator(self.FORM_NAME_INPUT).first.fill(name)
        return self

    def fill_session_user_id(self, user_id: str) -> "SessionsPage":
        """Fill in the UserID."""
        self.page.locator(self.FORM_USERID_INPUT).first.fill(user_id)
        return self

    def select_channel(self, channel: str) -> "SessionsPage":
        """Select Channel."""
        self.page.locator(self.FORM_CHANNEL_SELECT).first.click()
        self.page.locator(f'.ant-select-option:has-text("{channel}")').first.click()
        return self

    def save_session(self) -> "SessionsPage":
        """Save the session."""
        logger.info("Saving session")
        self.page.locator(self.FORM_SUBMIT_BTN).first.click()
        self.wait_for_loading()
        self.wait_for_success_message()
        self.wait_for_drawer_close()
        return self

    def cancel_session_edit(self) -> "SessionsPage":
        """Cancel editing."""
        logger.info("Canceling session edit")
        self.page.locator(self.FORM_CANCEL_BTN).first.click()
        self.wait_for_drawer_close()
        return self

    # ========== Delete session ==========

    def click_delete(self, session_id: str) -> "SessionsPage":
        """
        Click the delete button.

        Args:
            session_id: session ID
        """
        logger.info(f"Clicking delete for session: {session_id}")
        row = self.find_session_row(session_id)
        if row:
            row.locator(self.DELETE_BTN).first.click()
        else:
            raise Exception(f"Session not found: {session_id}")
        return self

    def confirm_delete(self) -> "SessionsPage":
        """Confirm deletion."""
        logger.info("Confirming delete")
        self.page.locator(self.CONFIRM_OK_BTN).first.click()
        self.wait_for_loading()
        self.wait_for_success_message()
        return self

    def cancel_delete(self) -> "SessionsPage":
        """Cancel deletion."""
        logger.info("Canceling delete")
        self.page.locator(self.CONFIRM_CANCEL_BTN).first.click()
        return self

    # ========== Batch delete ==========

    def select_session(self, session_id: str) -> "SessionsPage":
        """Select a session (for batch operations)."""
        row = self.find_session_row(session_id)
        if row:
            row.locator('input[type="checkbox"]').first.click()
        return self

    def select_all_sessions(self) -> "SessionsPage":
        """Select all sessions."""
        self.page.locator('thead input[type="checkbox"]').first.click()
        return self

    def click_batch_delete(self) -> "SessionsPage":
        """Click the batch delete button."""
        logger.info("Clicking batch delete")
        self.page.locator(self.BATCH_DELETE_BTN).first.click()
        return self

    # ========== Verification ==========

    def verify_session_exists(self, session_id: str) -> bool:
        """Verify the session exists."""
        return self.find_session_row(session_id) is not None

    def verify_session_count(self, expected_count: int) -> bool:
        """Verify the number of sessions."""
        actual_count = self.get_session_count()
        logger.info(f"Session count: {actual_count}, expected: {expected_count}")
        return actual_count == expected_count

    def verify_filter_result(self, expected_count: int) -> bool:
        """Verify the filter result."""
        return self.get_session_count() == expected_count

    def verify_session_data(self, session_id: str, expected_data: Dict[str, str]) -> bool:
        """Verify session data."""
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
        """Wait for a success message."""
        try:
            expect(self.page.locator(self.SUCCESS_MESSAGE)).to_be_visible(timeout=timeout)
            return True
        except TimeoutError:
            return False

    def wait_for_error_message(self, timeout: int = 5000) -> bool:
        """Wait for an error message."""
        try:
            expect(self.page.locator(self.ERROR_MESSAGE)).to_be_visible(timeout=timeout)
            return True
        except TimeoutError:
            return False

    def wait_for_loading(self, timeout: int = 3000) -> "SessionsPage":
        """Wait for loading to finish."""
        try:
            loading = self.page.locator(self.LOADING_SPINNER)
            if loading.count() > 0:
                expect(loading).to_be_hidden(timeout=timeout)
        except Exception:
            pass
        return self

    def verify_empty_state(self) -> bool:
        """Verify the empty state."""
        try:
            return self.page.locator(self.EMPTY_STATE).first.is_visible()
        except Exception:
            return False