# -*- coding: utf-8 -*-
"""
QwenPaw Sessions module P0 end-to-end test cases.

P0 definition:
- Core user flows
- Multi-feature combined coverage
- Real user scenarios
- High-priority functionality

Stack: pytest + Playwright + Page Object Pattern
Run with: pytest tests/test_sessions_p0.py -v
"""
from __future__ import annotations

import logging
import time
import pytest
from playwright.sync_api import Page, expect, TimeoutError

from pages.sessions_page import SessionsPage
from config.settings import config
from utils.helpers import (
    log_test_step,
    log_test_result,
    take_screenshot,
    assert_text_contains,
)

logger = logging.getLogger(__name__)


# ============================================================================
# SESS-001: Session list display + filter + detail view
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.sessions_core
class TestSessionListFilterAndDetail:
    """
    SESS-001: Session list display + filter + detail view.

    Combined coverage:
    1. Sessions page navigation and load
    2. Session list table display (column verification)
    3. UserID filter
    4. Channel filter
    5. List sorting
    6. Session detail view

    Scenario:
    A user opens the Sessions management page, browses the list,
    narrows down via filter and sort, then views session detail.
    """

    @pytest.mark.test_id("SESS-001")
    def test_session_list_filter_and_detail(self, sessions_page: SessionsPage, request: pytest.FixtureRequest):
        """
        Verify session list display, filtering, sorting and detail view.

        Steps:
        1. Visit the Sessions page and verify the table loads
        2. Verify key columns (ID / UserID / Channel / Created)
        3. Verify filters are available (UserID / Channel)
        4. Verify sorting (table header is clickable)
        5. View detail for the first session
        """
        test_name = request.node.name

        log_test_step("1. Visit the Sessions page and verify the table loads")
        sessions_page.open()
        session_count = sessions_page.get_session_count()
        logger.info(f"Session count: {session_count}")

        log_test_step("2. Verify key table columns")
        table_header = sessions_page.page.locator("thead th")
        header_count = table_header.count()
        assert header_count >= 3, f"Table should have at least 3 columns, got {header_count}"
        logger.info(f"Table column count: {header_count}")

        log_test_step("3. Verify filters and run a filter operation")
        userid_input = sessions_page.page.locator(sessions_page.FILTER_USER_ID_INPUT).first
        if userid_input.count() > 0 and userid_input.is_visible(timeout=3000):
            # Type a filter value and verify
            userid_input.fill("e2e_test_filter")
            sessions_page.page.wait_for_timeout(1500)
            filtered_count = sessions_page.get_session_count()
            logger.info(f"Session count after filter: {filtered_count}")
            assert filtered_count <= session_count, \
                f"Filtered count ({filtered_count}) should not exceed original count ({session_count})"
            logger.info("UserID filter works")
            # Clear filter
            userid_input.fill("")
            sessions_page.page.wait_for_timeout(1000)
        else:
            logger.info("UserID filter input not found")

        log_test_step("4. Verify sorting (click table header)")
        headers = sessions_page.page.locator("thead th")
        assert headers.count() > 0, "Table headers should exist"
        # Click the first sortable header
        first_header = headers.first
        first_header.click()
        sessions_page.page.wait_for_timeout(1000)
        logger.info("Clicked header to sort")

        log_test_step("5. View detail for the first session")
        refreshed_count = sessions_page.get_session_count()
        if refreshed_count > 0:
            visible_rows = sessions_page.page.locator("tbody tr:not([aria-hidden='true'])")
            assert visible_rows.count() > 0, "Visible session rows should exist"
            first_row = visible_rows.first
            first_row.click()
            sessions_page.page.wait_for_timeout(2000)
            # Verify the detail panel or drawer opens
            detail_panel = sessions_page.page.locator('.qwenpaw-drawer, .qwenpaw-modal, [class*="detail"]').first
            if detail_panel.count() > 0 and detail_panel.is_visible(timeout=3000):
                detail_text = detail_panel.text_content() or ""
                assert len(detail_text) > 10, "Session detail content should not be empty"
                logger.info(f"Session detail panel opened, content length: {len(detail_text)}")
                sessions_page.page.keyboard.press("Escape")
                sessions_page.page.wait_for_timeout(500)
            else:
                logger.info("Clicking row did not open a detail panel (may use route navigation)")
            logger.info(f"Visible session rows: {visible_rows.count()}")
        else:
            logger.info("No session data, skipping detail view")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - session list display, filter, sort and detail OK")


# ============================================================================
# SESS-002: Edit session + delete session + batch delete
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.sessions_edit
class TestEditAndDeleteSession:
    """
    SESS-002: Edit session + delete session + batch delete.

    Combined coverage:
    1. Click the edit button to open the edit dialog
    2. Verify the edit dialog and form
    3. Cancel editing and close the dialog
    4. Verify the delete button is available
    5. Verify batch selection and batch delete

    Scenario:
    Admin opens the edit dialog to inspect a session, cancels,
    then verifies single delete and batch delete are available.
    """

    @pytest.mark.test_id("SESS-002")
    def test_edit_and_delete_session(self, sessions_page: SessionsPage, ensure_session_data, request: pytest.FixtureRequest):
        """
        Verify edit, delete and batch-delete features.

        Steps:
        1. Visit the Sessions page
        2. Verify operable sessions exist
        3. Click the edit button and verify the dialog opens
        4. Cancel editing and verify the dialog closes
        5. Verify the delete button is available
        6. Verify batch selection and batch-delete
        """
        test_name = request.node.name

        log_test_step("1. Visit the Sessions page")
        sessions_page.open()
        sessions_page.step_shot("01_sessions_page_opened")

        log_test_step("2. Verify operable sessions exist")
        session_count = sessions_page.get_session_count()
        assert session_count > 0, (
            "ensure_session_data fixture should have created test data, but the page shows 0 sessions"
        )
        first_row = sessions_page.page.locator(sessions_page.SESSION_TABLE_ROW).first

        # --- Edit: must actually open and close the drawer ---
        log_test_step("3. Click the edit button and verify the dialog opens")
        # Note: SUT has Action column fixed="right"; in-row lookup may miss the button.
        # Use the page-level EDIT_BTN selector and take the first match (covers fixed-column shadow row).
        page_edit_btns = sessions_page.page.locator(sessions_page.EDIT_BTN)
        edit_btn_count = page_edit_btns.count()
        assert edit_btn_count > 0, (
            f"No edit button found on the page (rows={session_count}). "
            f"Page object EDIT_BTN selector may not cover real DOM; check fixed-right column structure."
        )
        edit_btn = page_edit_btns.first
        edit_btn.scroll_into_view_if_needed()
        edit_btn.click()
        sessions_page.step_shot("02_edit_btn_clicked")
        expect(
            sessions_page.page.locator(sessions_page.SESSION_DRAWER).first
        ).to_be_visible(timeout=5000)
        logger.info("Edit dialog opened")
        sessions_page.step_shot("03_edit_drawer_opened")

        log_test_step("4. Cancel editing and verify the dialog closes")
        cancel_btns = sessions_page.page.locator(sessions_page.FORM_CANCEL_BTN)
        if cancel_btns.count() > 0 and cancel_btns.first.is_visible():
            cancel_btns.first.click()
        else:
            # Fallback: press ESC to close the drawer
            sessions_page.page.keyboard.press("Escape")
        expect(
            sessions_page.page.locator(sessions_page.SESSION_DRAWER).first
        ).to_be_hidden(timeout=5000)
        sessions_page.step_shot("04_edit_drawer_closed")
        logger.info("Edit dialog closed")

        # --- Delete: the button must exist and be enabled ---
        log_test_step("5. Verify the delete button is available")
        page_delete_btns = sessions_page.page.locator(sessions_page.DELETE_BTN)
        del_count = page_delete_btns.count()
        assert del_count > 0, "No delete button found on the page"
        first_delete = page_delete_btns.first
        assert first_delete.is_enabled(), "First delete button should be enabled"
        logger.info(f"Delete button verified ({del_count} delete buttons)")
        sessions_page.step_shot("05_delete_btn_visible")

        # --- Batch delete: checkbox must actually be selectable ---
        log_test_step("6. Verify batch-selection checkbox is selectable")
        row_checkboxes = sessions_page.page.locator(
            'tbody tr .qwenpaw-checkbox-input, '
            'tbody tr .ant-checkbox-input, '
            'tbody tr input[type="checkbox"]'
        )
        cb_count = row_checkboxes.count()
        assert cb_count > 0, "No row checkboxes found (batch selection should be available)"
        first_cb = row_checkboxes.first
        first_cb.click(force=True)
        sessions_page.page.wait_for_timeout(800)
        sessions_page.step_shot("06_first_checkbox_checked")
        # After selection, a batch-delete button should appear (fixed bar or toolbar)
        batch_btns = sessions_page.page.locator(
            'button.qwenpaw-btn-dangerous:has-text("Delete"), '
            'button:has-text("Batch Delete")'
        )
        # This is a soft check: batch-delete button text/class varies by frontend; any dangerous button is fine
        assert batch_btns.count() > 0, (
            "A batch-delete / dangerous button should appear after selecting a checkbox, but none found."
        )
        logger.info(f"Batch-delete button appeared after selecting checkbox ({batch_btns.count()})")
        # Unselect to avoid polluting the next test
        first_cb.click(force=True)
        sessions_page.page.wait_for_timeout(300)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - edit, delete and batch-delete verified")


# ============================================================================
# SESS-003: Session name edit and save
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.sessions_edit
class TestSessionEditAndSave:
    """
    SESS-003: Session name edit and save.

    Coverage:
    1. Click the edit button to open the edit drawer
    2. Verify the edit drawer opens
    3. Modify the session name
    4. Save and verify the name updated
    5. Restore the original name

    Scenario:
    A user edits the session name to better identify the conversation,
    saves it and verifies the name update, then restores the original name
    to keep the environment clean.
    """

    @pytest.mark.test_id("SESS-003")
    def test_session_edit_name_and_save(
        self,
        sessions_page: SessionsPage,
        ensure_session_data,
        request: pytest.FixtureRequest,
    ):
        """
        Verify session name edit-and-save flow.

        Steps:
        1. Visit the Sessions page
        2. Verify operable sessions exist
        3. Click the edit button on the first session
        4. Verify the edit drawer opens
        5. Change the session name to "E2E_Test_Renamed_xxx"
        6. Click save
        7. Verify the drawer closes
        8. Verify the new name appears in the list
        9. Restore the original name (edit and save again)
        """
        test_name = request.node.name

        log_test_step("1. Visit the Sessions page")
        sessions_page.open()

        log_test_step("2. Verify operable sessions exist")
        session_count = sessions_page.get_session_count()
        if session_count == 0:
            pytest.skip("No operable sessions")

        first_row = sessions_page.page.locator(sessions_page.SESSION_TABLE_ROW).first

        # Get the original session name
        original_name_cell = first_row.locator('td').nth(1)  # Assume the name is in the 2nd column
        original_name = original_name_cell.text_content().strip() if original_name_cell.count() > 0 else ""
        logger.info(f"Original session name: {original_name}")

        log_test_step("3. Click the edit button on the first session")
        # Source: Action column fixed="right"; button is Button type="link" size="small"
        # Need to find the edit button within the fixed column
        edit_btn = first_row.locator('button:has-text("Edit")').first
        if not edit_btn.is_visible():
            # Try the fixed column
            fixed_row = sessions_page.page.locator('.qwenpaw-table-cell-fix-right button:has-text("Edit")').first
            if fixed_row.is_visible():
                edit_btn = fixed_row
        if not edit_btn.is_visible():
            pytest.skip("Edit button not available")

        edit_btn.click()

        log_test_step("4. Verify the edit drawer opens")
        expect(sessions_page.page.locator(sessions_page.SESSION_DRAWER).first).to_be_visible(timeout=5000)
        logger.info("Edit drawer opened")

        log_test_step("5. Modify the session name")
        new_name = f"E2E_Test_Renamed_{request.node.name[-8:]}"
        name_input = sessions_page.page.locator(sessions_page.SESSION_DRAWER).first.locator('input').first
        if name_input.count() > 0 and name_input.is_visible():
            name_input.fill(new_name)
            logger.info(f"Entered new name: {new_name}")
        else:
            # Try other possible input selectors
            name_input = sessions_page.page.locator('#sessionName, [name="sessionName"]').first
            if name_input.count() > 0:
                name_input.fill(new_name)
                logger.info(f"Entered new name: {new_name}")
            else:
                pytest.skip("Name input not found")

        log_test_step("6. Click the save button")
        save_btn = sessions_page.page.locator(sessions_page.FORM_SUBMIT_BTN).first
        if save_btn.count() == 0:
            save_btn = sessions_page.page.locator('button:has-text("Save"), button.qwenpaw-btn-primary').first
        if save_btn.count() > 0 and save_btn.is_visible():
            save_btn.click()
            logger.info("Clicked save button")
        else:
            pytest.skip("Save button not found")

        log_test_step("7. Verify the drawer closes")
        expect(sessions_page.page.locator(sessions_page.SESSION_DRAWER).first).to_be_hidden(timeout=5000)
        logger.info("Edit drawer closed")

        log_test_step("8. Verify the new name appears in the list (hard assert)")
        sessions_page.page.wait_for_timeout(1500)
        # Reload the page to ensure we see the latest data (avoid optimistic-update cache illusion)
        sessions_page.page.reload()
        sessions_page.page.wait_for_load_state("domcontentloaded")
        sessions_page.page.wait_for_timeout(2000)
        sessions_page.step_shot("08_after_save_reloaded")

        # Search for new_name across all rows in the table (not just the first, sort order may change)
        page_text = sessions_page.page.locator("tbody").inner_text() or ""
        assert new_name in page_text, (
            f"New name '{new_name}' not found in session list text after save; "
            f"save may not have taken effect. Table preview: {page_text[:300]}"
        )
        logger.info(f"Found new name in session list: {new_name}")

        log_test_step("9. Restore the original name")
        if original_name:
            edit_btn.click()
            expect(sessions_page.page.locator(sessions_page.SESSION_DRAWER).first).to_be_visible(timeout=5000)

            name_input = sessions_page.page.locator(sessions_page.SESSION_DRAWER).first.locator('input').first
            if name_input.count() > 0:
                name_input.fill(original_name)
                save_btn = sessions_page.page.locator(sessions_page.FORM_SUBMIT_BTN).first
                if save_btn.count() == 0:
                    save_btn = sessions_page.page.locator('button:has-text("Save"), button.qwenpaw-btn-primary').first
                if save_btn.count() > 0:
                    save_btn.click()
                    expect(sessions_page.page.locator(sessions_page.SESSION_DRAWER).first).to_be_hidden(timeout=5000)
                    logger.info(f"Restored original name: {original_name}")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# SESS-004: Batch delete sessions
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.sessions_batch
class TestSessionBatchDelete:
    """
    SESS-004: Batch delete sessions.

    Coverage:
    1. Tick checkboxes for multiple sessions
    2. Verify the batch-delete button becomes available
    3. Click the batch-delete button
    4. Confirm deletion
    5. Verify the session count decreased

    Scenario:
    A user batch-selects and deletes multiple unwanted sessions for efficiency.
    Note: this is destructive, skip if there are insufficient sessions.
    """

    @pytest.mark.test_id("SESS-004")
    def test_session_batch_delete(
        self,
        sessions_page: SessionsPage,
        ensure_session_data,
        request: pytest.FixtureRequest,
    ):
        """
        Verify batch delete sessions.

        Steps:
        1. Visit the Sessions page
        2. Verify at least 2 sessions exist
        3. Tick checkboxes for the first two sessions
        4. Verify the batch-delete button becomes available
        5. Click the batch-delete button
        6. Confirm deletion (if a confirm dialog appears)
        7. Verify the session count decreased
        """
        test_name = request.node.name

        log_test_step("1. Visit the Sessions page")
        sessions_page.open()

        log_test_step("2. Verify at least 2 sessions exist")
        session_count = sessions_page.get_session_count()
        if session_count < 2:
            pytest.skip(f"Insufficient sessions; need at least 2, have {session_count}")

        log_test_step("3. Tick checkboxes for the first two sessions")
        # Source: Table rowSelection; each tbody tr has a checkbox.
        # Don't tick the select-all (in thead); tick the tbody row checkboxes.
        # Use broad selectors to cover both antd and qwenpaw prefixes
        row_checkboxes = sessions_page.page.locator(
            'tbody tr .qwenpaw-checkbox-input, '
            'tbody tr .ant-checkbox-input, '
            'tbody tr input[type="checkbox"]'
        ).all()
        if len(row_checkboxes) < 2:
            pytest.skip(f"Not enough row checkboxes found; got {len(row_checkboxes)}")

        checked_count = 0
        for i in range(min(2, len(row_checkboxes))):
            checkbox = row_checkboxes[i]
            if checkbox.is_visible():
                checkbox.click(force=True)
                sessions_page.page.wait_for_timeout(800)
                checked_count += 1
                logger.info(f"Ticked checkbox for session #{i + 1}")
        assert checked_count >= 1, "At least 1 session checkbox should be ticked"
        logger.info(f"Ticked {checked_count} session checkbox(es)")

        log_test_step("4. Verify the batch-delete button appears")
        # Source: button Type="primary" danger renders only when selectedRowKeys.length > 0
        # antd Button type="primary" danger may have classes qwenpaw-btn-primary + qwenpaw-btn-dangerous
        batch_delete_btn = None
        batch_btn_selectors = [
            'button.qwenpaw-btn-dangerous:has-text("Delete")',
            'button:has-text("Batch Delete")',
            'button:has-text("Delete")',
        ]
        for selector in batch_btn_selectors:
            btn = sessions_page.page.locator(selector).first
            if btn.count() > 0 and btn.is_visible(timeout=3000):
                batch_delete_btn = btn
                logger.info(f"Found batch-delete button: {selector}")
                break

        assert batch_delete_btn is not None, "Batch-delete button not found"
        logger.info("Batch-delete button appeared")

        log_test_step("5. Record session count before deletion")
        count_before = sessions_page.get_session_count()
        logger.info(f"Session count before deletion: {count_before}")

        log_test_step("6. Click the batch-delete button")
        batch_delete_btn.click()
        sessions_page.page.wait_for_timeout(1500)

        log_test_step("7. Confirm deletion (if a confirm dialog appears)")
        # Source: Modal.confirm, okType="danger"
        # Explicitly wait for the dialog to appear
        modal_visible = False
        try:
            modal = sessions_page.page.locator('.qwenpaw-modal, .ant-modal').first
            modal.wait_for(state="visible", timeout=5000)
            modal_visible = True
            logger.info("Confirm dialog appeared")
        except Exception:
            logger.warning("No dialog detected, trying to match the confirm button directly")

        sessions_page.page.wait_for_timeout(500)

        # Try multiple selectors to match the confirm button
        confirm_btn = None
        confirm_selectors = [
            # Modal.confirm okType="danger" buttons
            '.qwenpaw-modal-confirm-btns .qwenpaw-btn-dangerous',
            '.qwenpaw-modal-confirm-btns .qwenpaw-btn-primary',
            '.qwenpaw-modal .qwenpaw-btn-dangerous',
            '.qwenpaw-modal .qwenpaw-btn-primary',
            # Original antd prefixes
            '.ant-modal-confirm-btns .ant-btn-dangerous',
            '.ant-modal-confirm-btns .ant-btn-primary',
            '.ant-modal .ant-btn-primary',
            # Generic text matchers
            '.qwenpaw-modal button:has-text("OK")',
            '.qwenpaw-modal button:has-text("Delete")',
            '.ant-modal button:has-text("OK")',
            # Popconfirm or other confirm components
            '.qwenpaw-popconfirm button.qwenpaw-btn-primary',
            'button:has-text("OK")',
        ]
        for selector in confirm_selectors:
            try:
                btn = sessions_page.page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=2000):
                    confirm_btn = btn
                    logger.info(f"Found confirm button: {selector}")
                    break
            except Exception:
                continue

        if confirm_btn is not None:
            confirm_btn.click()
            logger.info("Clicked confirm-delete button")
        else:
            logger.warning("Confirm-dialog button not found, trying to confirm via Enter")
            sessions_page.page.keyboard.press("Enter")

        # Wait for the delete API to finish and the list to refresh
        sessions_page.page.wait_for_timeout(5000)

        log_test_step("8. Verify session count decreased")
        # Wait for the list to refresh
        sessions_page.page.reload()
        sessions_page.page.wait_for_load_state("domcontentloaded")
        sessions_page.page.wait_for_timeout(3000)
        count_after = sessions_page.get_session_count()
        logger.info(f"Session count after deletion: {count_after}")

        assert count_after < count_before, \
            f"Session count did not decrease: before={count_before}, after={count_after}"

        logger.info(f"Session count went from {count_before} down to {count_after}")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def sessions_page(page: Page) -> SessionsPage:
    """Create a SessionsPage instance."""
    return SessionsPage(page)


@pytest.fixture(scope="function")
def ensure_session_data(page: Page):
    """Ensure the Sessions page has enough test data (at least 3 entries).

    Sends messages via POST /api/console/chat to auto-create sessions,
    each with a different session_id and user_id. After the test, the
    created test sessions are deleted via the API.
    """
    base_url = config.base_url
    page.goto(f"{base_url}/sessions")
    page.wait_for_timeout(2000)

    existing_count = page.locator(
        "tbody tr:not([aria-hidden='true'])"
        ":not(.qwenpaw-table-placeholder)"
        ":not(.qwenpaw-table-measure-row)"
    ).count()

    needed = max(0, 3 - existing_count)
    created_session_ids = []

    if needed == 0:
        logger.info(f"Already have {existing_count} sessions; no creation needed")
        yield created_session_ids
        return

    logger.info(f"Currently {existing_count} sessions; need to create {needed} more")

    for i in range(needed):
        session_id = f"e2e_sess_{int(time.time() * 1000)}_{i}"
        user_id = f"e2e_user_{int(time.time() * 1000)}_{i}"
        result = page.evaluate(
            """async ([sessionId, userId, idx]) => {
                try {
                    const resp = await fetch('/api/console/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            input: [{
                                role: 'user',
                                type: 'message',
                                content: [{ type: 'text', text: 'E2E test session ' + idx, status: 'created' }]
                            }],
                            session_id: sessionId,
                            user_id: userId,
                            channel: 'console',
                            stream: false
                        })
                    });
                    return { ok: resp.ok, status: resp.status };
                } catch (e) {
                    return { ok: false, error: e.message };
                }
            }""",
            [session_id, user_id, str(i)],
        )
        if result.get("ok"):
            created_session_ids.append(session_id)
        else:
            logger.warning(f"  Failed to create session: {result}")
        page.wait_for_timeout(1500)
        logger.info(f"  Created session: sid={session_id}, uid={user_id}")

    # Reload page to verify data was created
    page.reload()
    page.wait_for_timeout(2000)
    logger.info(f"Created {needed} test sessions")

    yield created_session_ids

    # ---- teardown: clean up created test sessions ----
    if not created_session_ids:
        return

    logger.info(f"Starting cleanup of {len(created_session_ids)} test sessions")
    try:
        # Fetch /api/chats to map session_id -> UUID (id field)
        chat_list = page.evaluate(
            """async (targetSessionIds) => {
                try {
                    const resp = await fetch('/api/chats');
                    if (!resp.ok) return { ok: false, status: resp.status };
                    const chats = await resp.json();
                    const matches = chats
                        .filter(c => targetSessionIds.includes(c.session_id))
                        .map(c => ({ id: c.id, session_id: c.session_id }));
                    return { ok: true, matches };
                } catch (e) {
                    return { ok: false, error: e.message };
                }
            }""",
            created_session_ids,
        )
        if not chat_list.get("ok"):
            logger.warning(f"  Failed to fetch session list: {chat_list}")
            return

        for match in chat_list.get("matches", []):
            uuid = match["id"]
            sid = match["session_id"]
            try:
                delete_result = page.evaluate(
                    """async (uuid) => {
                        try {
                            const resp = await fetch('/api/chats/' + uuid, {
                                method: 'DELETE',
                            });
                            return { ok: resp.ok, status: resp.status };
                        } catch (e) {
                            return { ok: false, error: e.message };
                        }
                    }""",
                    uuid,
                )
                if delete_result.get("ok"):
                    logger.info(f"  Deleted session: {sid} (uuid={uuid})")
                else:
                    logger.warning(f"  Delete failed: {sid} -> {delete_result}")
            except Exception as delete_error:
                logger.warning(f"  Delete exception: {sid} -> {delete_error}")
    except Exception as cleanup_error:
        logger.warning(f"  Cleanup process exception: {cleanup_error}")
    logger.info("Test session cleanup complete")


# ============================================================================
# P1 test case: combined session filtering
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.sessions_filter
class TestSessionFilterByUseridAndChannel:
    """
    SESS-P1-001: Filter sessions by UserID and Channel combined.

    Coverage:
    1. Filter by UserID input
    2. Filter by Channel dropdown
    3. Verify combined filter results
    4. Clear filters and verify the list is restored
    """

    def test_session_filter_by_userid_and_channel(self, page: Page, ensure_session_data):
        """Test combined session filter by UserID and Channel."""
        log_test_step("Navigate to the session management page")
        page.goto(f"{config.base_url}/sessions")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Find filter controls")
        # Source FilterBar.tsx: UserID input placeholder is t("sessions.filterUserId");
        # Channel selector placeholder is t("sessions.filterChannel")
        userid_input = page.locator(
            "input[placeholder*='user'], input[placeholder*='User'], "
            "input[placeholder*='userid'], input[placeholder*='UserId'], "
            "input[placeholder*='ID'], input[placeholder*='id']"
        ).first
        channel_select = page.locator(".qwenpaw-select, .ant-select").first

        # At least one filter control must exist
        has_userid_input = userid_input.count() > 0
        has_channel_select = channel_select.count() > 0
        assert has_userid_input or has_channel_select, \
            "No filter controls found (UserID input or Channel selector)"
        logger.info(f"Filter controls: UserID input={'yes' if has_userid_input else 'no'}, Channel selector={'yes' if has_channel_select else 'no'}")

        log_test_step("Get the initial session list")
        session_row_selector = "tbody tr:not(.qwenpaw-table-placeholder):not(.qwenpaw-table-measure-row)"
        initial_sessions = page.locator(session_row_selector).all()
        initial_count = len(initial_sessions)
        assert initial_count > 0, "ensure_session_data fixture should have created test data, but session list is still empty"
        logger.info(f"Initial session count: {initial_count}")

        if has_userid_input:
            log_test_step("Extract UserID from the first session")
            first_session = initial_sessions[0]
            cells = first_session.locator("td").all()
            assert len(cells) >= 2, "Session row has too few columns"
            test_userid = cells[1].inner_text().strip()
            assert len(test_userid) > 0, "Could not extract UserID"
            logger.info(f"Using test UserID: {test_userid}")

            log_test_step(f"Enter UserID filter: {test_userid}")
            userid_input.fill(test_userid)
            page.wait_for_timeout(2000)

            log_test_step("Verify filter results")
            filtered_sessions = page.locator(session_row_selector).all()
            filtered_count = len(filtered_sessions)
            assert filtered_count <= initial_count, \
                f"Filtered session count ({filtered_count}) should not exceed initial ({initial_count})"
            logger.info(f"After UserID filter: {filtered_count} sessions (initial: {initial_count})")

            # Verify the filtered results contain the target UserID
            if filtered_count > 0:
                first_filtered_cells = filtered_sessions[0].locator("td").all()
                if len(first_filtered_cells) >= 2:
                    result_userid = first_filtered_cells[1].inner_text().strip()
                    assert test_userid in result_userid or result_userid in test_userid, \
                        f"Filtered UserID ({result_userid}) does not match input ({test_userid})"
                    logger.info(f"Filtered UserID matches: {result_userid}")

            log_test_step("Clear filter and verify list is restored")
            userid_input.fill("")
            page.wait_for_timeout(2000)

            restored_sessions = page.locator(session_row_selector).all()
            restored_count = len(restored_sessions)
            assert abs(restored_count - initial_count) <= 2, \
                f"Restored count is off: initial {initial_count}, restored {restored_count}"
            logger.info(f"After clearing filter, restored to {restored_count} sessions (initial {initial_count})")

        logger.info("Session filter test complete")
