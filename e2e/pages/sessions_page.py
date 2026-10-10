# -*- coding: utf-8 -*-
"""
QwenPaw Sessions page object.

Wraps all interactions on the Sessions page and exposes business-level methods.
"""
from __future__ import annotations

import logging
import re
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
    #
    # antd Table renders a non-data row inside ``tbody`` for column measurement
    # (``<tr aria-hidden="true" class="...-measure-row">``), plus an empty-state
    # placeholder row. Counting bare ``tbody tr`` therefore over-counts by one,
    # which is exactly the off-by-one seen in CI (the batch-delete case counted
    # 11 rows while the fixture's own counter reported 10 for the same page).
    # ``e2e/fixtures`` already excludes both; align this selector with it.
    # (Upstream ``ConfigProvider`` sets ``prefixCls="qwenpaw"``, so the
    # ``ant-`` variants are legacy fallbacks for older builds.)
    SESSION_TABLE = '.ant-table, .qwenpaw-table, table'
    _ROW_EXCLUDES = (
        ":not([aria-hidden='true'])"
        ":not(.qwenpaw-table-placeholder)"
        ":not(.ant-table-placeholder)"
        ":not(.qwenpaw-table-measure-row)"
        ":not(.ant-table-measure-row)"
    )
    SESSION_ROW = (
        '.qwenpaw-table-tbody tr' + _ROW_EXCLUDES + ', '
        '.ant-table-tbody tr' + _ROW_EXCLUDES + ', '
        'table tbody tr' + _ROW_EXCLUDES
    )
    SESSION_TABLE_ROW = SESSION_ROW
    # Total count from the ``Active (N)`` tab label. Unlike ``SESSION_ROW`` this
    # is not limited to the current page: the table is paginated at
    # ``pageSize: 10`` (``console/src/pages/Control/Sessions/index.tsx``) while
    # ``activeCount`` in ``useSessions.ts`` is the length of the full
    # ``chatApi.listChats()`` result filtered client-side. So a page-size-capped
    # row count stays at 10 after deleting 2 of 15 rows (the next page shifts
    # up to fill the page) whereas the tab label drops to 13 — which is why
    # "did the count decrease" assertions must read the tab, not the rows.
    SESSION_ACTIVE_TAB = (
        '.qwenpaw-tabs-tab:has-text("Active"), '
        '.ant-tabs-tab:has-text("Active"), '
        '.qwenpaw-tabs-tab:has-text("活跃"), '
        '.ant-tabs-tab:has-text("活跃")'
    )
    SESSION_ROW_SELECTED = '.ant-table-tbody tr.ant-table-row-selected, .qwenpaw-table-tbody tr.qwenpaw-table-row-selected'

    # Data rows only: exclude the rows antd/rc-table injects into <tbody> that
    # carry no session data. Verified against the live DOM (2026-09-11):
    #   - tr.qwenpaw-table-measure-row  -> aria-hidden="true", 0 <td> cells,
    #     yet Playwright reports is_visible()==True for both the row and the
    #     checkbox inside it, so a bare "tbody tr" locator matches it first.
    #   - tr.qwenpaw-table-placeholder  -> the "no data" row.
    # Keep this in sync with the exclusion list used by the ensure_session_data
    # fixture in tests/test_sessions.py.
    SESSION_ROW_EXCLUSIONS = (
        ':not([aria-hidden="true"])'
        ':not(.qwenpaw-table-placeholder)'
        ':not(.qwenpaw-table-measure-row)'
        ':not(.ant-table-placeholder)'
        ':not(.ant-table-measure-row)'
    )
    SESSION_DATA_ROW = (
        f'.ant-table-tbody tr{SESSION_ROW_EXCLUSIONS}, '
        f'.qwenpaw-table-tbody tr{SESSION_ROW_EXCLUSIONS}, '
        f'table tbody tr{SESSION_ROW_EXCLUSIONS}'
    )

    # Row checkboxes, restricted to data rows (see SESSION_ROW_EXCLUSIONS).
    # The first match of the unqualified "tbody tr <checkbox>" selector is the
    # measure-row checkbox: clicking it registers NO selection, which silently
    # degrades a batch delete into a single delete.
    ROW_CHECKBOX = (
        f'tbody tr{SESSION_ROW_EXCLUSIONS} .qwenpaw-checkbox-input, '
        f'tbody tr{SESSION_ROW_EXCLUSIONS} .ant-checkbox-input, '
        f'tbody tr{SESSION_ROW_EXCLUSIONS} input[type="checkbox"]'
    )

    # Batch-delete button. Rendered ONLY while selectedRowKeys.length > 0
    # (console/src/pages/Control/Sessions/index.tsx), labelled
    # "Batch Delete (N)" via sessions.batchDeleteButton. The in-row Action
    # column also renders a danger "Delete" link button, so a selector such as
    # 'button:has-text("Delete")' matches those too and picks the WRONG button
    # when nothing is selected. Match on the batch label instead.
    BATCH_DELETE_BTN_STRICT = (
        'button:has-text("Batch Delete"), button:has-text("批量删除")'
    )

    # Tab labels: "Active (N)" / "Archived (N)" -- the server-side totals.
    SESSION_TAB = '.qwenpaw-tabs-tab, .ant-tabs-tab'

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
        """Get the number of session rows rendered on the CURRENT page.

        Scope: this counts DOM rows of the visible table page only -- it is the
        right measure for filter assertions (filtered rows <= original rows) but
        it is NOT a global session total. The table is paginated with
        ``pageSize: 10`` and ``showSizeChanger: false``, so once the server holds
        more than 10 sessions the first page stays full and this value stops
        responding to deletions. Use :meth:`get_active_session_total` whenever a
        test needs to assert that a mutation changed the server-side total.
        """
        return len(self.get_session_rows())

    def get_session_data_rows(self) -> List[Locator]:
        """Get session data rows only (measure-row / placeholder excluded)."""
        return self.page.locator(self.SESSION_DATA_ROW).all()

    def get_active_session_total(self) -> Optional[int]:
        """Get the server-side total of ACTIVE sessions from the "Active (N)" tab.

        The tab label is rendered from ``activeCount = activeSessions.length``
        where ``activeSessions`` comes from a full (non-paginated)
        ``GET /api/chats`` response, so this reflects the server-side total
        rather than the current table page. Cross-verified against
        ``GET /api/chats`` on a live instance (2026-09-11): three consecutive
        samples returned identical values with 14 seeded sessions.

        Returns:
            The active session total, or None if the label cannot be parsed
            (callers get None so they can distinguish "0 sessions" from
            "count unavailable" instead of silently treating a miss as zero).
        """
        tabs = self.page.locator(self.SESSION_TAB).all()
        for tab in tabs:
            try:
                text = tab.inner_text().strip()
            except Exception:
                continue
            # "Active (14)" -- match the first tab carrying a count; skip the
            # archived one so the number always refers to the active set.
            if text.lower().startswith("archived"):
                continue
            match = re.search(r"\((\d+)\)", text)
            if match:
                return int(match.group(1))
        logger.warning(
            "Could not parse the active-session total from tabs: %s",
            [t.inner_text() for t in tabs] if tabs else "no tab found",
        )
        return None

    def wait_for_session_total(self, timeout: Optional[int] = None) -> int:
        """Wait for the "Active (N)" tab label to render a count, then return N.

        Auto-retrying counterpart of :meth:`get_active_session_total`: it waits
        for the tab label to carry a parenthesised number instead of relying on
        a fixed sleep, which matters right after a reload (the count renders
        only once GET /api/chats resolves).

        Returns:
            The active session total.

        Raises:
            AssertionError: if no count appears within the timeout.
        """
        timeout = timeout or self.timeout
        first_tab = self.page.locator(self.SESSION_TAB).first
        expect(first_tab).to_have_text(re.compile(r"\(\d+\)"), timeout=timeout)
        total = self.get_active_session_total()
        if total is None:
            raise AssertionError(
                "Active tab matched the count pattern but parsing failed"
            )
        logger.info(f"Active session total: {total}")
        return total

    def get_selected_row_keys(self) -> List[str]:
        """Get the chat UUIDs of the rows whose checkbox is currently ticked.

        antd Table renders ``rowKey="id"`` as a ``data-row-key`` attribute on
        each <tr>, so the ids of the selected rows can be read without relying
        on column positions. Verified on a live DOM (2026-09-11): ticking two
        rows returned exactly their two UUIDs. The measure-row has
        ``data-row-key=null`` and never carries a checkbox that registers a
        selection.
        """
        return self.page.evaluate(
            """() => Array.from(
                   document.querySelectorAll('tbody input[type="checkbox"]:checked')
               ).map(cb => {
                   const tr = cb.closest('tr');
                   return tr ? tr.getAttribute('data-row-key') : null;
               }).filter(k => k)"""
        )

    def get_page_row_ids(self) -> List[str]:
        """Get the chat UUIDs of the data rows rendered on the current page."""
        return self.page.evaluate(
            """() => Array.from(document.querySelectorAll('tbody tr[data-row-key]'))
                   .map(tr => tr.getAttribute('data-row-key'))
                   .filter(k => k)"""
        )

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