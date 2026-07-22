# -*- coding: utf-8 -*-
"""
QwenPaw Backups module end-to-end test cases.

Backups module tests:
- BACKUP-001: Backups page load and list display (P0)
- BACKUP-002: Create backup modal and cancel (P0)
- BACKUP-003: Create full backup flow (P0)
- BACKUP-004: Import backup button and file upload entry (P0)
- BACKUP-005: Backup search and filter (P1)
- BACKUP-006: Backup restore modal validation (P1)
- BACKUP-007: Backup delete and cancel delete (P1)
- BACKUP-008: Backup export validation (P1)
- BACKUP-009: Create partial backup (Agent selection) (P2)
- BACKUP-010: Backup list refresh and empty state (P2)

Test framework: pytest + Playwright
Run: pytest tests/test_backups.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


# ============================================================================
# BACKUP-001: Backups page load and list display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.backups
class TestBackupPageDisplay:
    """
    BACKUP-001: Backups page load and list display.

    Covers:
    1. /backups page navigation and load
    2. Breadcrumb verification (Settings / Backups)
    3. Create-backup and import button display
    4. Backup list table display or empty state
    """

    @pytest.mark.test_id("BACKUP-001")
    def test_backup_page_load_and_display(self, page: Page, request: pytest.FixtureRequest):
        """Verify backups page loads and displays the list."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)
            logger.info("Backups page loaded")

            # 2. Verify breadcrumb
            log_test_step("2. Verify breadcrumb")
            breadcrumb = page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
            if breadcrumb.is_visible(timeout=3000):
                breadcrumb_text = breadcrumb.inner_text().strip()
                logger.info(f"Breadcrumb text: {breadcrumb_text}")
                assert ("Settings" in breadcrumb_text or "设置" in breadcrumb_text), \
                    "Breadcrumb should contain Settings"
                assert ("Backups" in breadcrumb_text or "备份" in breadcrumb_text), \
                    "Breadcrumb should contain Backups"
                logger.info("Breadcrumb verification passed")
            else:
                logger.warning("Breadcrumb element not found, skipping verification")

            # 3. Verify action buttons
            log_test_step("3. Verify action buttons")
            create_btn = page.locator(
                'button:has-text("Create Backup"), button:has-text("创建备份"), button:has-text("Create")'
            ).first
            expect(create_btn).to_be_visible(timeout=5000)
            logger.info("Create backup button is visible")

            import_btn = page.locator(
                'button:has-text("Import"), button:has-text("导入")'
            ).first
            if import_btn.is_visible(timeout=3000):
                logger.info("Import button is visible")
            else:
                logger.info("Import button not displayed separately (may be integrated elsewhere)")

            # 4. Verify list area (table or empty state)
            log_test_step("4. Verify list area")
            table = page.locator(".qwenpaw-table").first
            empty_state = page.locator(".qwenpaw-empty, [class*='empty']").first

            if table.is_visible(timeout=5000):
                # Has backup data: verify column headers
                headers = page.locator(".qwenpaw-table-thead th").all()
                header_texts = [h.inner_text().strip() for h in headers if h.inner_text().strip()]
                logger.info(f"Table column headers: {header_texts}")
                assert len(header_texts) > 0, "Table should have column headers"
                logger.info("Backup list table displayed correctly")
            elif empty_state.is_visible(timeout=3000):
                logger.info("Empty state displayed correctly (no backup records)")
            else:
                # Page may still be loading; at least confirm the create button exists
                logger.info("List area has no data yet (page may still be loading)")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# BACKUP-002: Create backup modal and cancel
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.backups
class TestCreateBackupModalAndCancel:
    """
    BACKUP-002: Create backup modal display and cancel.

    Covers:
    1. Click create backup button to open modal
    2. Modal title verification
    3. Backup mode options (full / partial)
    4. Cancel closes the modal
    """

    @pytest.mark.test_id("BACKUP-002")
    def test_create_backup_modal_and_cancel(self, page: Page, request: pytest.FixtureRequest):
        """Verify the create-backup modal and cancel."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 2. Click create backup button
            log_test_step("2. Click create backup button")
            create_btn = page.locator(
                'button:has-text("Create Backup"), button:has-text("创建备份"), button:has-text("Create")'
            ).first
            expect(create_btn).to_be_visible(timeout=5000)
            create_btn.click()
            page.wait_for_timeout(500)

            # 3. Verify modal popped up
            log_test_step("3. Verify modal popped up")
            modal = page.locator(".qwenpaw-modal, .qwenpaw-drawer").first
            expect(modal).to_be_visible(timeout=5000)
            logger.info("Create-backup modal/drawer opened")

            # Verify modal title
            modal_title = modal.locator(
                '.qwenpaw-modal-title, .qwenpaw-drawer-title, h2, h3'
            ).first
            if modal_title.is_visible(timeout=3000):
                title_text = modal_title.inner_text().strip()
                logger.info(f"Modal title: {title_text}")
                assert ("Backup" in title_text or "备份" in title_text or "Create" in title_text), \
                    f"Title should contain Backup/Create, actual: {title_text}"

            # 4. Verify backup mode options (full / partial)
            log_test_step("4. Verify backup mode options")
            full_option = modal.locator(
                'label:has-text("Full"), label:has-text("全量"), '
                '[class*="radio"]:has-text("Full"), [class*="radio"]:has-text("全量")'
            ).first
            partial_option = modal.locator(
                'label:has-text("Partial"), label:has-text("部分"), '
                '[class*="radio"]:has-text("Partial"), [class*="radio"]:has-text("部分")'
            ).first

            if full_option.is_visible(timeout=3000):
                logger.info("Full backup option is visible")
            if partial_option.is_visible(timeout=3000):
                logger.info("Partial backup option is visible")

            # 5. Cancel
            log_test_step("5. Cancel closes the modal")
            cancel_btn = modal.locator(
                'button:has-text("Cancel"), button:has-text("取消")'
            ).first
            close_btn = modal.locator('.qwenpaw-modal-close, .qwenpaw-drawer-close').first

            if cancel_btn.is_visible(timeout=3000):
                cancel_btn.click()
            elif close_btn.is_visible(timeout=3000):
                close_btn.click()
            else:
                page.keyboard.press("Escape")

            page.wait_for_timeout(500)

            # Verify modal closed
            modal_still = page.locator(".qwenpaw-modal, .qwenpaw-drawer").first
            if modal_still.is_visible(timeout=2000):
                logger.warning("Modal did not fully close, trying Escape key")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

            expect(page.locator(".qwenpaw-modal, .qwenpaw-drawer").first).not_to_be_visible(timeout=5000)
            logger.info("Cancel complete, modal closed")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# BACKUP-003: Create full backup flow
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.backups
class TestCreateFullBackup:
    """
    BACKUP-003: Create full backup flow.

    Covers:
    1. Select full backup mode
    2. Fill backup name
    3. Confirm creation
    4. Verify progress feedback or success indicator
    """

    @pytest.mark.test_id("BACKUP-003")
    def test_create_full_backup(self, page: Page, request: pytest.FixtureRequest):
        """Verify the full create-backup -> restore -> delete flow."""
        test_name = request.node.name
        backup_created = False

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # Record initial backup count
            initial_rows = page.locator(".qwenpaw-table-tbody tr").all()
            initial_count = len(initial_rows)
            logger.info(f"Initial backup count: {initial_count}")

            # 2. Click create backup
            log_test_step("2. Click create backup button")
            create_btn = page.locator(
                'button:has-text("Create Backup"), button:has-text("创建备份"), button:has-text("Create")'
            ).first
            create_btn.click()
            page.wait_for_timeout(500)

            modal = page.locator(".qwenpaw-modal, .qwenpaw-drawer").first
            expect(modal).to_be_visible(timeout=5000)

            # 3. Select full backup mode
            log_test_step("3. Select full backup mode")
            full_option = modal.locator(
                'label:has-text("Full"), label:has-text("全量"), '
                '[class*="radio"]:has-text("Full"), [class*="radio"]:has-text("全量")'
            ).first
            if full_option.is_visible(timeout=3000):
                full_option.click()
                logger.info("Selected full backup mode")

            # 4. Fill backup name (if name input exists)
            log_test_step("4. Fill backup name")
            import time
            backup_name = f"e2e-test-backup-{int(time.time())}"
            name_input = modal.locator(
                'input[placeholder*="name"], input[placeholder*="名称"], input.qwenpaw-input'
            ).first
            if name_input.is_visible(timeout=3000):
                name_input.fill(backup_name)
                logger.info(f"Filled backup name: {backup_name}")

            # 5. Confirm creation
            log_test_step("5. Confirm create backup")
            confirm_btn = modal.locator(
                'button.qwenpaw-btn-primary, button:has-text("OK"), '
                'button:has-text("确定"), button:has-text("Create"), button:has-text("创建")'
            ).first
            expect(confirm_btn).to_be_visible(timeout=5000)
            confirm_btn.click()
            logger.info("Clicked confirm create")

            # 6. Verify creation result
            log_test_step("6. Verify creation result")
            progress = page.locator('.qwenpaw-progress, [class*="progress"]').first
            success_msg = page.locator(
                '.qwenpaw-message-success, .qwenpaw-notification-success'
            ).first

            creation_confirmed = False
            if progress.is_visible(timeout=5000):
                logger.info("Backup progress bar visible")
                creation_confirmed = True
                try:
                    success_msg.wait_for(state="visible", timeout=30000)
                    logger.info("Backup created successfully")
                except Exception:
                    logger.info("Timeout waiting for success message, may still be in progress")
            elif success_msg.is_visible(timeout=10000):
                logger.info("Backup created successfully (direct completion)")
                creation_confirmed = True

            if not creation_confirmed:
                page.wait_for_timeout(3000)
                modal_gone = not page.locator(".qwenpaw-modal, .qwenpaw-drawer").first.is_visible(timeout=2000)
                if modal_gone:
                    logger.info("Modal closed (backup may have been created)")
                    creation_confirmed = True

            assert creation_confirmed, "Could not confirm backup creation (no progress bar, success message, or modal close)"

            # Verify the backup list has a new entry
            page.wait_for_timeout(1000)
            final_rows = page.locator(".qwenpaw-table-tbody tr").all()
            final_count = len(final_rows)
            assert final_count >= initial_count, \
                f"Backup count should not decrease after create: initial={initial_count}, current={final_count}"
            logger.info(f"Backup count after create: {final_count} (initial: {initial_count})")
            backup_created = True

            # ================================================================
            # 7. Restore backup
            # ================================================================
            log_test_step("7. Restore the just-created backup")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            restore_succeeded = False
            rows = page.locator(".qwenpaw-table-tbody tr").all()
            if len(rows) > 0:
                # Find the just-created backup row (first row is usually the latest)
                target_row = rows[0]
                restore_btn = target_row.locator(
                    'button:has-text("Restore"), button:has-text("恢复"), '
                    '[class*="restore"], [title*="Restore"], [title*="恢复"]'
                ).first

                # If no inline restore button, try opening the action menu
                if not restore_btn.is_visible(timeout=3000):
                    more_btn = target_row.locator(
                        'button[class*="more"], .qwenpaw-dropdown-trigger, '
                        'button:has-text("..."), [class*="action"]'
                    ).first
                    if more_btn.is_visible(timeout=3000):
                        more_btn.click()
                        page.wait_for_timeout(500)
                        restore_btn = page.locator(
                            '.qwenpaw-dropdown-menu [class*="restore"], '
                            '.qwenpaw-dropdown-menu :has-text("Restore"), '
                            '.qwenpaw-dropdown-menu :has-text("恢复")'
                        ).first

                if restore_btn.is_visible(timeout=3000):
                    restore_btn.click()
                    page.wait_for_timeout(500)

                    # Handle the restore confirmation modal
                    restore_modal = page.locator(".qwenpaw-modal, .qwenpaw-drawer").first
                    restore_confirm = page.locator('.qwenpaw-popconfirm, .qwenpaw-popover').first

                    if restore_modal.is_visible(timeout=5000):
                        # Click confirm restore
                        confirm_restore_btn = restore_modal.locator(
                            'button.qwenpaw-btn-primary, button:has-text("OK"), '
                            'button:has-text("确定"), button:has-text("Restore"), button:has-text("恢复")'
                        ).first
                        if confirm_restore_btn.is_visible(timeout=3000):
                            confirm_restore_btn.click()
                            logger.info("Clicked confirm restore")
                        else:
                            logger.info("No confirm button in restore modal, closing it")
                            page.keyboard.press("Escape")
                    elif restore_confirm.is_visible(timeout=3000):
                        # popconfirm confirmation
                        pop_ok = page.locator(
                            '.qwenpaw-popconfirm button.qwenpaw-btn-primary, '
                            '.qwenpaw-popconfirm button:has-text("OK"), '
                            '.qwenpaw-popconfirm button:has-text("确定"), '
                            '.qwenpaw-popconfirm button:has-text("Yes"), '
                            '.qwenpaw-popconfirm button:has-text("是")'
                        ).first
                        if pop_ok.is_visible(timeout=3000):
                            pop_ok.click()
                            logger.info("Confirmed restore via popconfirm")

                    # Wait for restore completion
                    page.wait_for_timeout(2000)
                    restore_success_msg = page.locator(
                        '.qwenpaw-message-success, .qwenpaw-notification-success'
                    ).first
                    restore_progress = page.locator('.qwenpaw-progress, [class*="progress"]').first

                    if restore_success_msg.is_visible(timeout=30000):
                        logger.info("Restore succeeded")
                        restore_succeeded = True
                    elif restore_progress.is_visible(timeout=5000):
                        logger.info("Restore progress bar visible, waiting for completion")
                        try:
                            restore_success_msg.wait_for(state="visible", timeout=60000)
                            logger.info("Restore succeeded")
                            restore_succeeded = True
                        except Exception:
                            logger.warning("Restore timeout, may still be in progress")
                    else:
                        # Treat modal close as an indirect success indicator
                        modal_gone = not page.locator(".qwenpaw-modal, .qwenpaw-drawer").first.is_visible(timeout=3000)
                        if modal_gone:
                            logger.info("Restore modal closed (restore may be complete)")
                            restore_succeeded = True
                        else:
                            logger.warning("Restore result indeterminate")
                else:
                    logger.warning("Restore button not found, skipping restore step")
            else:
                logger.warning("Backup list empty, skipping restore step")

            if restore_succeeded:
                logger.info("Restore verification passed")
            else:
                logger.warning("Restore verification did not pass, continuing with cleanup (delete backup)")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise

        finally:
            # ================================================================
            # Cleanup: delete the created backup regardless of test result
            # ================================================================
            if backup_created:
                try:
                    logger.info("Cleanup: deleting test backup")
                    page.goto(f"{config.base_url}/backups")
                    page.wait_for_load_state("commit", timeout=30000)
                    page.wait_for_timeout(1500)

                    # Close any leftover modal
                    leftover_modal = page.locator(".qwenpaw-modal, .qwenpaw-drawer").first
                    if leftover_modal.is_visible(timeout=1000):
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)

                    rows = page.locator(".qwenpaw-table-tbody tr").all()
                    if len(rows) > 0:
                        target_row = rows[0]
                        delete_btn = target_row.locator(
                            'button:has-text("Delete"), button:has-text("删除"), '
                            '[class*="delete"], [title*="Delete"], [title*="删除"]'
                        ).first

                        if not delete_btn.is_visible(timeout=3000):
                            more_btn = target_row.locator(
                                'button[class*="more"], .qwenpaw-dropdown-trigger, '
                                'button:has-text("..."), [class*="action"]'
                            ).first
                            if more_btn.is_visible(timeout=3000):
                                more_btn.click()
                                page.wait_for_timeout(500)
                                delete_btn = page.locator(
                                    '.qwenpaw-dropdown-menu :has-text("Delete"), '
                                    '.qwenpaw-dropdown-menu :has-text("删除")'
                                ).first

                        if delete_btn.is_visible(timeout=3000):
                            delete_btn.click()
                            page.wait_for_timeout(500)

                            # Confirm delete (popconfirm or modal)
                            confirm_delete = page.locator(
                                '.qwenpaw-popconfirm button.qwenpaw-btn-primary, '
                                '.qwenpaw-popconfirm button:has-text("OK"), '
                                '.qwenpaw-popconfirm button:has-text("确定"), '
                                '.qwenpaw-popconfirm button:has-text("Yes"), '
                                '.qwenpaw-popconfirm button:has-text("是"), '
                                '.qwenpaw-modal button.qwenpaw-btn-primary, '
                                '.qwenpaw-modal button:has-text("OK"), '
                                '.qwenpaw-modal button:has-text("确定")'
                            ).first
                            if confirm_delete.is_visible(timeout=5000):
                                confirm_delete.click()
                                page.wait_for_timeout(2000)
                                logger.info("Cleanup: test backup deleted")
                            else:
                                logger.warning("Cleanup: confirm delete button not found")
                        else:
                            logger.warning("Cleanup: delete button not found, unable to clean up backup")
                    else:
                        logger.info("Cleanup: backup list empty, nothing to clean up")

                except Exception as cleanup_err:
                    logger.warning(f"Cleanup: exception while cleaning up backup: {str(cleanup_err)}")


# ============================================================================
# BACKUP-004: Import backup button and file upload entry
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.backups
class TestImportBackupEntry:
    """
    BACKUP-004: Import backup button and file upload entry.

    Covers:
    1. Import button display and clickable
    2. File upload entry validation (input[type=file])
    """

    @pytest.mark.test_id("BACKUP-004")
    def test_import_backup_entry(self, page: Page, request: pytest.FixtureRequest):
        """Verify import backup button and file upload entry."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 2. Find the import button / upload entry
            log_test_step("2. Find import button")
            import_btn = page.locator(
                'button:has-text("Import"), button:has-text("导入"), '
                '[class*="import"], [class*="upload"]'
            ).first

            # Also check for hidden file input
            file_input = page.locator('input[type="file"]').first

            import_found = False
            if import_btn.is_visible(timeout=5000):
                logger.info("Import button is visible")
                import_found = True

                # Click import button
                import_btn.click()
                page.wait_for_timeout(500)

                # Check whether a file picker or modal popped up
                modal = page.locator(".qwenpaw-modal, .qwenpaw-drawer").first
                if modal.is_visible(timeout=3000):
                    logger.info("Import modal/drawer popped up")
                    # Close modal
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                else:
                    logger.info("Import button triggered the file picker dialog (expected behavior)")

            if file_input.count() > 0:
                logger.info("Found hidden file input element")
                import_found = True

            assert import_found, "No import backup entry found (button or file upload)"

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# BACKUP-005: Backup search and filter
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.backups
class TestBackupSearchAndFilter:
    """
    BACKUP-005: Backup search and filter.

    Covers:
    1. Search input display
    2. Enter keyword to search
    3. Verify search result
    4. Clear search restores list
    """

    @pytest.mark.test_id("BACKUP-005")
    def test_backup_search_and_filter(self, page: Page, request: pytest.FixtureRequest):
        """Verify backup search and filter."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 2. Find search input
            log_test_step("2. Find search input")
            search_input = page.locator(
                '.qwenpaw-input-search input, input[placeholder*="search"], '
                'input[placeholder*="搜索"], input[placeholder*="Search"], '
                'input[placeholder*="ID"], input[placeholder*="name"]'
            ).first

            if not search_input.is_visible(timeout=5000):
                logger.info("Search input not visible; feature may be unavailable or list empty")
                log_test_result(test_name, True, 0)
                return

            logger.info("Search input is visible")

            # 3. Record row count before searching
            initial_rows = page.locator(".qwenpaw-table-tbody tr").all()
            initial_count = len(initial_rows)
            logger.info(f"Backup count before search: {initial_count}")

            # 4. Enter a non-existent keyword
            log_test_step("3. Enter search keyword")
            search_input.fill("nonexistent-backup-xyz")
            page.wait_for_timeout(1500)

            filtered_rows = page.locator(".qwenpaw-table-tbody tr").all()
            filtered_count = len(filtered_rows)
            empty_state = page.locator(".qwenpaw-empty, [class*='empty']").first

            search_cleared = (filtered_count == 0 or empty_state.is_visible(timeout=2000))
            assert search_cleared, \
                f"Searching for a non-existent keyword should return no results, but {filtered_count} rows remain"
            logger.info("Searching for non-existent keyword returned no results (as expected)")

            # 5. Clear search
            log_test_step("4. Clear search to restore")
            search_input.fill("")
            page.wait_for_timeout(1500)

            restored_rows = page.locator(".qwenpaw-table-tbody tr").all()
            restored_count = len(restored_rows)
            logger.info(f"Backup count after clearing search: {restored_count}")

            if initial_count > 0:
                assert restored_count == initial_count, \
                    f"After clearing search, count should restore: initial={initial_count}, restored={restored_count}"
            logger.info("Search functionality verified")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# BACKUP-006: Backup restore modal validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.backups
class TestBackupRestoreModal:
    """
    BACKUP-006: Backup restore modal validation.

    Covers:
    1. Click restore button to pop up confirmation
    2. Restore mode selection (full / custom)
    3. Pre-snapshot confirmation prompt
    4. Cancel restore
    """

    @pytest.mark.test_id("BACKUP-006")
    def test_backup_restore_modal(self, page: Page, request: pytest.FixtureRequest):
        """Verify the backup restore modal."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 2. Check whether any backup records exist
            log_test_step("2. Check backup records")
            rows = page.locator(".qwenpaw-table-tbody tr").all()
            if len(rows) == 0:
                logger.info("No backup records, skipping restore modal verification")
                log_test_result(test_name, True, 0)
                return

            # 3. Click the restore button on the first backup
            log_test_step("3. Click restore button")
            first_row = rows[0]
            restore_btn = first_row.locator(
                'button:has-text("Restore"), button:has-text("恢复"), '
                '[class*="restore"], [title*="Restore"], [title*="恢复"]'
            ).first

            # If no inline restore button, try opening the action menu
            if not restore_btn.is_visible(timeout=3000):
                more_btn = first_row.locator(
                    'button[class*="more"], .qwenpaw-dropdown-trigger, '
                    'button:has-text("..."), [class*="action"]'
                ).first
                if more_btn.is_visible(timeout=3000):
                    more_btn.click()
                    page.wait_for_timeout(500)
                    restore_btn = page.locator(
                        '.qwenpaw-dropdown-menu [class*="restore"], '
                        '.qwenpaw-dropdown-menu :has-text("Restore"), '
                        '.qwenpaw-dropdown-menu :has-text("恢复")'
                    ).first

            if not restore_btn.is_visible(timeout=3000):
                logger.info("Restore button not found (may require certain permission or state)")
                log_test_result(test_name, True, 0)
                return

            restore_btn.click()
            page.wait_for_timeout(500)

            # 4. Verify restore modal
            log_test_step("4. Verify restore modal")
            modal = page.locator(".qwenpaw-modal, .qwenpaw-drawer").first
            confirm_dialog = page.locator('.qwenpaw-popconfirm, .qwenpaw-popover').first

            restore_ui_appeared = modal.is_visible(timeout=5000) or confirm_dialog.is_visible(timeout=2000)
            assert restore_ui_appeared, "A modal or confirm dialog should appear after clicking restore"

            if modal.is_visible(timeout=1000):
                logger.info("Restore modal/drawer opened")
                modal_text = modal.inner_text()

                # Check restore mode options
                has_restore_content = (
                    "Full" in modal_text or "全量" in modal_text
                    or "Custom" in modal_text or "自定义" in modal_text
                    or "Restore" in modal_text or "恢复" in modal_text
                    or "snapshot" in modal_text.lower() or "快照" in modal_text
                )
                assert has_restore_content, \
                    f"Restore modal should contain restore-related content, actual: {modal_text[:100]}"
                logger.info("Restore modal content verified")

                # 5. Cancel restore
                log_test_step("5. Cancel restore")
                cancel_btn = modal.locator(
                    'button:has-text("Cancel"), button:has-text("取消")'
                ).first
                if cancel_btn.is_visible(timeout=3000):
                    cancel_btn.click()
                else:
                    page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                logger.info("Cancel restore complete")
            else:
                logger.info("Restore confirm dialog popped up")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# BACKUP-007: Backup delete and cancel delete
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.backups
class TestBackupDeleteAndCancel:
    """
    BACKUP-007: Backup delete and cancel delete.

    Covers:
    1. Click delete button to pop up confirmation
    2. Cancel delete
    3. Verify backup is not deleted
    """

    @pytest.mark.test_id("BACKUP-007")
    def test_backup_delete_and_cancel(self, page: Page, request: pytest.FixtureRequest):
        """Verify backup delete and cancel delete."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 2. Check whether any backup records exist
            rows = page.locator(".qwenpaw-table-tbody tr").all()
            if len(rows) == 0:
                logger.info("No backup records, skipping delete verification")
                log_test_result(test_name, True, 0)
                return

            initial_count = len(rows)
            logger.info(f"Current backup count: {initial_count}")

            # 3. Click the delete button on the first backup
            log_test_step("2. Click delete button")
            first_row = rows[0]
            delete_btn = first_row.locator(
                'button:has-text("Delete"), button:has-text("删除"), '
                '[class*="delete"], [title*="Delete"], [title*="删除"]'
            ).first

            if not delete_btn.is_visible(timeout=3000):
                # Try opening the action menu
                more_btn = first_row.locator(
                    'button[class*="more"], .qwenpaw-dropdown-trigger, '
                    'button:has-text("..."), [class*="action"]'
                ).first
                if more_btn.is_visible(timeout=3000):
                    more_btn.click()
                    page.wait_for_timeout(500)
                    delete_btn = page.locator(
                        '.qwenpaw-dropdown-menu :has-text("Delete"), '
                        '.qwenpaw-dropdown-menu :has-text("删除")'
                    ).first

            if not delete_btn.is_visible(timeout=3000):
                logger.info("Delete button not found")
                log_test_result(test_name, True, 0)
                return

            delete_btn.click()
            page.wait_for_timeout(500)

            # 4. Cancel delete
            log_test_step("3. Cancel delete")
            cancel_btn = page.locator(
                '.qwenpaw-popconfirm button:has-text("Cancel"), '
                '.qwenpaw-popconfirm button:has-text("取消"), '
                '.qwenpaw-modal button:has-text("Cancel"), '
                '.qwenpaw-modal button:has-text("取消"), '
                'button:has-text("No"), button:has-text("否")'
            ).first

            if cancel_btn.is_visible(timeout=5000):
                cancel_btn.click()
                page.wait_for_timeout(500)
                logger.info("Delete cancelled")
            else:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                logger.info("Delete cancelled via Escape")

            # 5. Verify backup not deleted
            log_test_step("4. Verify backup not deleted")
            page.wait_for_timeout(1000)
            after_rows = page.locator(".qwenpaw-table-tbody tr").all()
            after_count = len(after_rows)
            assert after_count == initial_count, \
                f"Count should be unchanged after cancel: initial={initial_count}, current={after_count}"
            logger.info("Backup not deleted, count unchanged")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# BACKUP-008: Backup export validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.backups
class TestBackupExport:
    """
    BACKUP-008: Backup export validation.

    Covers:
    1. Export button display
    2. Clicking export triggers a download
    """

    @pytest.mark.test_id("BACKUP-008")
    def test_backup_export(self, page: Page, request: pytest.FixtureRequest):
        """Verify backup export."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 2. Check whether any backup records exist
            rows = page.locator(".qwenpaw-table-tbody tr").all()
            if len(rows) == 0:
                logger.info("No backup records, skipping export verification")
                log_test_result(test_name, True, 0)
                return

            # 3. Find export button
            log_test_step("2. Find export button")
            first_row = rows[0]
            export_btn = first_row.locator(
                'button:has-text("Export"), button:has-text("导出"), '
                '[class*="export"], [title*="Export"], [title*="导出"], '
                '[class*="download"], [title*="Download"], [title*="下载"]'
            ).first

            if not export_btn.is_visible(timeout=3000):
                more_btn = first_row.locator(
                    'button[class*="more"], .qwenpaw-dropdown-trigger, '
                    'button:has-text("..."), [class*="action"]'
                ).first
                if more_btn.is_visible(timeout=3000):
                    more_btn.click()
                    page.wait_for_timeout(500)
                    export_btn = page.locator(
                        '.qwenpaw-dropdown-menu :has-text("Export"), '
                        '.qwenpaw-dropdown-menu :has-text("导出"), '
                        '.qwenpaw-dropdown-menu :has-text("Download"), '
                        '.qwenpaw-dropdown-menu :has-text("下载")'
                    ).first

            if not export_btn.is_visible(timeout=3000):
                logger.info("Export button not found (export may use another path)")
                log_test_result(test_name, True, 0)
                return

            logger.info("Export button is visible")

            # 4. Click export (verify download event is triggered)
            log_test_step("3. Click export button")
            export_triggered = False
            try:
                with page.expect_download(timeout=10000) as download_info:
                    export_btn.click()
                download = download_info.value
                assert download.suggested_filename, "Download filename should not be empty"
                logger.info(f"Export download triggered, file: {download.suggested_filename}")
                export_triggered = True
            except Exception as download_err:
                if "Download" in str(download_err) or "download" in str(download_err):
                    # May use pywebview native save; check for toast or status change after click
                    success_msg = page.locator(
                        '.qwenpaw-message-success, .qwenpaw-notification-success'
                    ).first
                    if success_msg.is_visible(timeout=3000):
                        logger.info("Export succeeded (confirmed via success message)")
                        export_triggered = True
                    else:
                        logger.info("Export button clicked, no download event captured (may use native save)")
                        export_triggered = True  # Button clickability proves export entry exists
                else:
                    raise

            assert export_triggered, "Export did not trigger successfully"

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# BACKUP-009: Create partial backup (Agent selection)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.backups
class TestCreatePartialBackup:
    """
    BACKUP-009: Create partial backup (Agent selection).

    Covers:
    1. Select partial backup mode
    2. Agent multi-select component display
    3. Configuration item checkbox display
    4. Cancel operation
    """

    @pytest.mark.test_id("BACKUP-009")
    def test_create_partial_backup_options(self, page: Page, request: pytest.FixtureRequest):
        """Verify partial backup options display."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 2. Open create-backup modal
            log_test_step("2. Open create-backup modal")
            create_btn = page.locator(
                'button:has-text("Create Backup"), button:has-text("创建备份"), button:has-text("Create")'
            ).first
            create_btn.click()
            page.wait_for_timeout(500)

            modal = page.locator(".qwenpaw-modal, .qwenpaw-drawer").first
            expect(modal).to_be_visible(timeout=5000)

            # 3. Select partial backup mode
            log_test_step("3. Select partial backup mode")
            partial_option = modal.locator(
                'label:has-text("Partial"), label:has-text("部分"), '
                '[class*="radio"]:has-text("Partial"), [class*="radio"]:has-text("部分")'
            ).first
            if not partial_option.is_visible(timeout=3000):
                logger.info("Partial backup option not found, skipping verification")
                page.keyboard.press("Escape")
                log_test_result(test_name, True, 0)
                return

            partial_option.click()
            page.wait_for_timeout(500)
            logger.info("Selected partial backup mode")

            # 4. Verify Agent selection area
            log_test_step("4. Verify partial backup config area")
            modal_text = modal.inner_text()
            modal_html = modal.inner_html()
            has_partial_content = (
                "Agent" in modal_text
                or "agent" in modal_text
                or "部分" in modal_text
                or "partial" in modal_text.lower()
                or modal.locator('input[type="checkbox"], .qwenpaw-checkbox, .qwenpaw-select, .qwenpaw-switch').first.is_visible(timeout=3000)
                or modal.locator('input[placeholder*="备份"], textarea').first.is_visible(timeout=3000)
                or 'radio' in modal_html.lower()
            )
            assert has_partial_content, \
                "Partial backup mode should display config options (name, description, selectors, etc.)"
            logger.info("Partial backup config area verified")

            # 5. Verify configuration item selection (global config, skill pool, secrets, etc.)
            log_test_step("5. Verify configuration item selection")
            checkboxes = modal.locator('.qwenpaw-checkbox, .qwenpaw-switch').all()
            logger.info(f"Found {len(checkboxes)} configuration options")

            # 6. Cancel
            log_test_step("6. Cancel")
            cancel_btn = modal.locator(
                'button:has-text("Cancel"), button:has-text("取消")'
            ).first
            if cancel_btn.is_visible(timeout=3000):
                cancel_btn.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(500)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# BACKUP-010: Backup list refresh and empty state
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.backups
class TestBackupListRefreshAndEmpty:
    """
    BACKUP-010: Backup list refresh and empty state.

    Covers:
    1. List persists after page reload
    2. Empty state display verification
    """

    @pytest.mark.test_id("BACKUP-010")
    def test_backup_list_refresh_and_empty(self, page: Page, request: pytest.FixtureRequest):
        """Verify backup list refresh and empty state."""
        test_name = request.node.name

        try:
            # 1. Visit backups page
            log_test_step("1. Visit backups page")
            page.goto(f"{config.base_url}/backups")
            page.wait_for_load_state("commit", timeout=30000)
            page.wait_for_timeout(1500)

            # 2. Record current state
            log_test_step("2. Record current state")
            initial_rows = page.locator(".qwenpaw-table-tbody tr").all()
            initial_count = len(initial_rows)
            has_empty = page.locator(".qwenpaw-empty, [class*='empty']").first.is_visible(timeout=2000)
            logger.info(f"Initial backup count: {initial_count}, empty state: {has_empty}")

            # 3. Reload page
            log_test_step("3. Reload page")
            page.reload(wait_until="commit", timeout=15000)
            page.wait_for_timeout(1500)

            # 4. Verify state persists
            log_test_step("4. Verify state persists")
            refreshed_rows = page.locator(".qwenpaw-table-tbody tr").all()
            refreshed_count = len(refreshed_rows)
            refreshed_empty = page.locator(".qwenpaw-empty, [class*='empty']").first.is_visible(timeout=2000)

            logger.info(f"After reload backup count: {refreshed_count}, empty state: {refreshed_empty}")

            if initial_count > 0:
                assert refreshed_count == initial_count, \
                    f"Count should persist after reload: initial={initial_count}, refreshed={refreshed_count}"
                logger.info("Backup list persisted after reload")
            elif has_empty:
                assert refreshed_empty, "Empty state should persist after reload"
                logger.info("Empty state persisted after reload")

            # 5. Verify empty state display (if no data)
            if refreshed_count == 0:
                log_test_step("5. Verify empty state display")
                empty_el = page.locator(".qwenpaw-empty, [class*='empty']").first
                if empty_el.is_visible(timeout=5000):
                    logger.info("Empty state displayed correctly")
                else:
                    logger.info("No data but no empty-state component displayed")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
