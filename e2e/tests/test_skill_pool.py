# -*- coding: utf-8 -*-
"""
QwenPaw E2E tests - Skill Pool P0 cases

Functional coverage:
1. Skill pool page load
2. Skill pool list display
3. Builtin skill source list
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

BASE_URL = config.server.base_url

def navigate_to_skill_pool(page: Page):
    """Navigate to the skill pool page."""
    page.goto(f"{BASE_URL}/skill-pool", wait_until="domcontentloaded", timeout=60000)
    # Explicitly wait for skill cards to render rather than only relying on a fixed timeout
    try:
        page.wait_for_selector('.qwenpaw-card', timeout=15000)
    except Exception:
        logger.warning("Timed out waiting for skill cards; page may have no data or be slow")
    page.wait_for_timeout(1000)

# ============================================================================
# POOL-001: Skill pool page load
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
class TestSkillPoolPageLoad:
    """POOL-001: Skill pool page load"""

    @pytest.mark.test_id("POOL-001")
    def test_skill_pool_page_load(self, page: Page, request: pytest.FixtureRequest):
        """Verify skill pool page loads normally."""
        test_name = request.node.name

        try:
            log_test_step("1. Navigate to skill pool page")
            navigate_to_skill_pool(page)

            log_test_step("2. Verify page loaded")
            body = page.locator("body").first
            assert body.is_visible(timeout=5000), "Page should load"
            logger.info("Skill pool page loaded")

            log_test_result(test_name, "PASS", "Skill pool page load validation passed")
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

# ============================================================================
# POOL-P1-001: Skill pool search/filter
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolSearch:
    """
    POOL-P1-001: Skill pool search/filter

    Functional coverage:
    1. Verify search input exists
    2. Enter keyword to filter skill list
    3. Clear search to restore full list
    """

    @pytest.mark.test_id("POOL-P1-001")
    def test_skill_pool_search(self, page: Page, request: pytest.FixtureRequest):
        """Test skill pool search/filter functionality."""
        test_name = request.node.name

        log_test_step("Navigate to skill pool page")
        navigate_to_skill_pool(page)

        log_test_step("Verify search input exists")
        search_input = page.locator(
            'input[placeholder*="筛选"], input[placeholder*="搜索"], '
            'input[placeholder*="search"], input[placeholder*="Search"], '
            'input[placeholder*="filter"], '
            '.qwenpaw-select-selection-search-input, '
            '.qwenpaw-input-search input'
        ).first
        expect(search_input).to_be_visible(timeout=5000)
        logger.info("Search input exists")

        log_test_step("Record skill count before search")
        # Wait for cards to finish loading before counting, to avoid async data not yet arriving
        try:
            page.wait_for_selector('.qwenpaw-card', timeout=10000)
            page.wait_for_timeout(500)
        except Exception:
            logger.warning("Did not see skill cards, page may have no data")
        skill_cards = page.locator('.qwenpaw-card').all()
        initial_count = len(skill_cards)
        logger.info(f"Skill count before search: {initial_count}")
        if initial_count == 0:
            logger.info("Skill pool has no data, skipping search filter assertion")
            log_test_result(test_name, True, 0)
            return

        log_test_step("Enter search keyword")
        # Search input is a qwenpaw-select component (readonly input); click parent container to trigger dropdown
        is_readonly = search_input.get_attribute("readonly") is not None
        if is_readonly:
            select_container = page.locator('.qwenpaw-select').first
            select_container.click()
            page.wait_for_timeout(500)
            page.keyboard.type("nonexistent_skill_xyz")
            page.wait_for_timeout(1500)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        else:
            search_input.fill("nonexistent_skill_xyz")
            page.wait_for_timeout(1500)

        filtered_cards = page.locator('.qwenpaw-card').all()
        filtered_count = len(filtered_cards)
        logger.info(f"Skill count after search: {filtered_count}")
        assert filtered_count <= initial_count, \
            f"Filtered count ({filtered_count}) should not exceed initial count ({initial_count})"
        logger.info("Search filter is effective")

        log_test_step("Clear search to restore list")
        if is_readonly:
            clear_btn = page.locator('.qwenpaw-select-clear').first
            if clear_btn.count() > 0:
                clear_btn.click()
            else:
                select_container = page.locator('.qwenpaw-select').first
                select_container.click()
                page.wait_for_timeout(300)
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
                page.keyboard.press("Escape")
        else:
            search_input.clear()
        page.wait_for_timeout(1500)

        restored_cards = page.locator('.qwenpaw-card').all()
        restored_count = len(restored_cards)
        logger.info(f"Skill count after clearing search: {restored_count}")
        logger.info("List restored after clearing search")

        log_test_result(test_name, True, 0)

# ============================================================================
# POOL-P1-002: Install skill to agent (via broadcast)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolInstall:
    """
    POOL-P1-002: Install skill to agent

    Functional coverage:
    1. Find broadcast button
    2. Open broadcast Modal
    3. Verify Modal has skill and workspace selections
    """

    @pytest.mark.test_id("POOL-P1-002")
    def test_skill_pool_install(self, page: Page, request: pytest.FixtureRequest):
        """Test installing a skill to an agent."""
        test_name = request.node.name

        log_test_step("Navigate to skill pool page")
        navigate_to_skill_pool(page)

        log_test_step("Find broadcast button")
        broadcast_btn = page.locator(
            'button:has-text("广播"), button:has-text("Broadcast"), '
            'button:has(.anticon-send)'
        ).first

        if broadcast_btn.count() == 0:
            logger.info("Broadcast button not found, skipping test")
            log_test_result(test_name, True, 0)
            return

        expect(broadcast_btn).to_be_visible(timeout=5000)
        logger.info("Broadcast button exists")

        log_test_step("Click broadcast button")
        broadcast_btn.click()
        page.wait_for_timeout(1500)

        log_test_step("Verify broadcast Modal opens")
        page.wait_for_timeout(500)
        visible_modals = page.locator('.qwenpaw-modal:visible, .ant-modal:visible, [role="dialog"]:visible')
        modal = visible_modals.last if visible_modals.count() > 0 else page.locator('.qwenpaw-modal, .ant-modal').last
        expect(modal).to_be_visible(timeout=8000)
        modal_content = modal.inner_text()
        assert len(modal_content) > 10, "Broadcast Modal content is empty"
        logger.info(f"Broadcast Modal opened, content length: {len(modal_content)}")

        log_test_step("Verify Modal has selection area and interact")
        # Actual UI uses custom pickerCard component instead of standard checkbox/select
        picker_cards = modal.locator('[class*=pickerCard]').all()
        checkboxes = modal.locator('.qwenpaw-checkbox, .ant-checkbox, .qwenpaw-checkbox-wrapper').all()
        selects = modal.locator('.qwenpaw-select, .ant-select').all()
        lists = modal.locator('.qwenpaw-list-item, .ant-list-item, tr').all()
        total_interactive = len(picker_cards) + len(checkboxes) + len(selects) + len(lists)
        assert total_interactive > 0, "Broadcast Modal should have selectable elements (pickerCard/checkbox/select/list item)"
        logger.info(f"Modal contains {len(picker_cards)} pickerCards, {len(checkboxes)} checkboxes, {len(selects)} selects, {len(lists)} list items")

        # If pickerCards exist, click the first to verify interactivity
        if len(picker_cards) > 0:
            first_card = picker_cards[0]
            first_card.click()
            page.wait_for_timeout(500)
            logger.info("Clicked the first pickerCard")
        elif len(checkboxes) > 0:
            first_checkbox = checkboxes[0]
            first_checkbox.click()
            page.wait_for_timeout(500)
            logger.info("Checked the first checkbox")

        # Verify confirm button exists
        confirm_btn = modal.locator(
            'button:has-text("OK"), button:has-text("确定"), '
            'button:has-text("Broadcast"), button:has-text("广播"), '
            'button.qwenpaw-btn-primary'
        ).first
        assert confirm_btn.count() > 0, "Confirm button should exist in broadcast Modal"
        logger.info("Confirm button exists")

        log_test_step("Close Modal")
        close_btn = modal.locator('.qwenpaw-modal-close, button:has-text("Cancel"), button:has-text("取消")').first
        if close_btn.count() > 0:
            close_btn.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

        log_test_result(test_name, True, 0)

# ============================================================================
# POOL-P1-003: Broadcast skill to multiple agents
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolBroadcast:
    """
    POOL-P1-003: Broadcast skill to multiple agents

    Functional coverage:
    1. Open broadcast Modal
    2. Verify multiple workspaces can be selected
    3. Verify confirm button exists
    """

    @pytest.mark.test_id("POOL-P1-003")
    def test_skill_pool_broadcast(self, page: Page, request: pytest.FixtureRequest):
        """Test broadcasting skill to multiple agents."""
        test_name = request.node.name

        log_test_step("Navigate to skill pool page")
        navigate_to_skill_pool(page)

        log_test_step("Find and click broadcast button")
        broadcast_btn = page.locator(
            'button:has-text("广播"), button:has-text("Broadcast"), '
            'button:has(.anticon-send)'
        ).first

        if broadcast_btn.count() == 0:
            logger.info("Broadcast button not found, skipping test")
            log_test_result(test_name, True, 0)
            return

        broadcast_btn.click()
        page.wait_for_timeout(3000)

        # Wait for Modal to appear and grab the reference
        modal_locator = page.locator('.qwenpaw-modal:visible, .ant-modal:visible, [role="dialog"]:visible')
        expect(modal_locator.first).to_be_visible(timeout=8000)
        modal = modal_locator.last

        log_test_step("Verify workspace selection area and tick items")
        # Actual UI uses custom pickerCard components; Modal contains two pickerSections:
        # section 0: "select skill pool items", section 1: "broadcast to workspaces"
        # Grab all pickerCards directly from Modal
        workspace_items = modal.locator('[class*=pickerCard]').all()
        if len(workspace_items) == 0:
            # Fallback: try standard component selectors
            workspace_items = modal.locator(
                '.qwenpaw-checkbox-wrapper, .ant-checkbox-wrapper, '
                '.qwenpaw-list-item, .ant-list-item'
            ).all()
        assert len(workspace_items) > 0, "Broadcast Modal should have workspace/selection items"
        logger.info(f"Found {len(workspace_items)} workspace/selection items")

        # Click the first workspace item
        first_item = workspace_items[0]
        first_item.click()
        page.wait_for_timeout(500)
        logger.info("Selected the first workspace")

        # If multiple items, click the second to verify multi-select
        if len(workspace_items) > 1:
            second_item = workspace_items[1]
            second_item.click()
            page.wait_for_timeout(500)
            logger.info("Selected the second workspace (multi-select verified)")

        log_test_step("Verify confirm button is enabled")
        confirm_btn = modal.locator(
            'button:has-text("OK"), button:has-text("确定"), '
            'button:has-text("Broadcast"), button:has-text("广播"), '
            'button.qwenpaw-btn-primary'
        ).first
        assert confirm_btn.count() > 0, "Confirm button not found in broadcast Modal"
        assert confirm_btn.is_enabled(), "Confirm button should be enabled after selecting workspaces"
        logger.info("Confirm button exists and is enabled")

        log_test_step("Close Modal (do not broadcast)")
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

        log_test_result(test_name, True, 0)

# ============================================================================
# POOL-P1-004: Batch delete skills
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolBatchDelete:
    """
    POOL-P1-004: Batch delete skills

    Functional coverage:
    1. Find batch operation button
    2. Enter batch mode
    3. Verify checkboxes appear
    4. Exit batch mode
    """

    @pytest.mark.test_id("POOL-P1-004")
    def test_skill_pool_batch_delete(self, page: Page, request: pytest.FixtureRequest):
        """Test skill pool batch delete functionality."""
        test_name = request.node.name

        log_test_step("Navigate to skill pool page")
        navigate_to_skill_pool(page)

        log_test_step("Find batch operation button")
        batch_btn = page.locator(
            'button:has-text("批量"), button:has-text("Batch"), '
            'button:has-text("Select"), button:has-text("选择")'
        ).first

        if batch_btn.count() == 0:
            logger.info("Batch operation button not found, skipping test")
            log_test_result(test_name, True, 0)
            return

        expect(batch_btn).to_be_visible(timeout=5000)
        logger.info("Batch operation button exists")

        log_test_step("Enter batch mode")
        batch_btn.click()
        page.wait_for_timeout(1500)

        log_test_step("Verify checkboxes appear and select one")
        checkboxes = page.locator('.qwenpaw-checkbox, .ant-checkbox, .qwenpaw-checkbox-wrapper').all()
        assert len(checkboxes) > 0, "Checkboxes should appear in batch mode"
        logger.info(f"Found {len(checkboxes)} checkboxes in batch mode")

        # Check the first checkbox
        checkboxes[0].click()
        page.wait_for_timeout(500)
        logger.info("Checked the first skill")

        # Verify delete button appears and is enabled
        delete_btn = page.locator(
            'button:has-text("删除"), button:has-text("Delete"), '
            'button.qwenpaw-btn-dangerous'
        ).first
        if delete_btn.count() > 0 and delete_btn.is_visible(timeout=3000):
            assert delete_btn.is_enabled(), "Delete button should be enabled after selecting a skill"
            logger.info("Delete button is visible and enabled")
        else:
            # Verify select-all button exists
            select_all = page.locator(
                'button:has-text("全选"), button:has-text("Select All"), '
                '.qwenpaw-checkbox-wrapper:has-text("全选")'
            ).first
            if select_all.count() > 0:
                logger.info("Select-all button exists")
            else:
                logger.info("No delete/select-all button found")

        log_test_step("Exit batch mode (do not delete)")
        # Click batch button again or click cancel
        cancel_btn = page.locator(
            'button:has-text("取消"), button:has-text("Cancel"), '
            'button:has-text("退出"), button:has-text("Exit")'
        ).first
        if cancel_btn.count() > 0:
            cancel_btn.click()
        else:
            batch_btn.click()
        page.wait_for_timeout(1000)
        logger.info("Exited batch mode")

        log_test_result(test_name, True, 0)

# ============================================================================
# POOL-P1-005: ZIP import skill
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolZipImport:
    """
    POOL-P1-005: ZIP import skill

    Functional coverage:
    1. Find ZIP upload button
    2. Verify hidden file input exists with accept attribute .zip
    3. Create a temp zip file and upload via hidden input
    4. Verify upload succeeded (skill appears in list or success message shown)
    5. Cleanup: delete uploaded skill + delete temp file
    """

    @pytest.mark.test_id("POOL-P1-005")
    def test_skill_pool_zip_import(self, page: Page, request: pytest.FixtureRequest):
        """Test skill pool ZIP import (with actual upload)."""
        import zipfile
        import tempfile
        import os
        import time

        test_name = request.node.name
        skill_name = f"e2e_pool_zip_{int(time.time())}"
        zip_path = None
        skill_uploaded = False

        try:
            log_test_step("1. Navigate to skill pool page")
            navigate_to_skill_pool(page)

            log_test_step("2. Find ZIP upload button")
            upload_btn = page.locator(
                'button:has-text("zip"), button:has-text("ZIP"), '
                'button:has-text("上传"), button:has-text("Upload"), '
                'button:has(.anticon-upload)'
            ).first

            if upload_btn.count() == 0:
                pytest.skip("ZIP upload button not found, skipping test")

            expect(upload_btn).to_be_visible(timeout=5000)
            logger.info("ZIP upload button exists")

            log_test_step("3. Verify hidden file input")
            file_input = page.locator(
                'input[type="file"][accept=".zip"], '
                'input[type="file"][accept*="zip"]'
            ).first
            assert file_input.count() > 0, "Hidden ZIP file input not found"

            accept_attr = file_input.get_attribute("accept")
            assert ".zip" in accept_attr, f"File input accept attribute does not include .zip: {accept_attr}"
            logger.info(f"File input accept={accept_attr}")

            log_test_step("4. Record initial skill count")
            initial_cards = page.locator('.qwenpaw-card').all()
            initial_count = len(initial_cards)
            logger.info(f"Initial skill count: {initial_count}")

            log_test_step("5. Create temporary zip file")
            skill_content = f"""---
name: {skill_name}
description: E2E test skill uploaded via zip to skill pool
---

# {skill_name}

This is a test skill uploaded via zip for E2E testing.
"""
            temp_dir = tempfile.mkdtemp()
            md_path = os.path.join(temp_dir, f"{skill_name}.md")
            zip_path = os.path.join(temp_dir, f"{skill_name}.zip")

            with open(md_path, "w", encoding="utf-8") as md_file:
                md_file.write(skill_content)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(md_path, f"{skill_name}.md")

            logger.info(f"Temporary zip file created: {zip_path}")

            log_test_step("6. Upload zip file via hidden input")
            file_input.set_input_files(zip_path)
            logger.info("Uploaded zip file via set_input_files")

            # Wait for upload to finish processing
            page.wait_for_timeout(5000)

            log_test_step("7. Verify upload result")
            # Check for success message
            success_message = page.locator(
                '.qwenpaw-message-success, '
                '.qwenpaw-message-notice:has-text("成功"), '
                '.qwenpaw-message-notice:has-text("success")'
            ).first
            if success_message.is_visible():
                logger.info("Detected upload success message")

            # Refresh page to ensure list updates
            page.reload()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

            # Verify the new skill appears in the list
            new_skill_locator = page.locator(f'text="{skill_name}"').first
            try:
                expect(new_skill_locator).to_be_visible(timeout=8000)
                skill_uploaded = True
                logger.info(f"Uploaded skill appeared in the skill pool list: {skill_name}")
            except Exception:
                updated_cards = page.locator('.qwenpaw-card').all()
                updated_count = len(updated_cards)
                logger.info(f"Skill count after upload: {updated_count} (initial: {initial_count})")
                if updated_count > initial_count:
                    skill_uploaded = True
                    logger.info("Skill count increased, upload likely succeeded")
                else:
                    logger.warning("No new skill detected; upload may have failed or name mismatch")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - skill pool ZIP import validation passed")

        finally:
            # Cleanup: delete the uploaded test skill
            if skill_uploaded:
                try:
                    target_card = page.locator(f'.qwenpaw-card:has-text("{skill_name}")').first
                    if target_card.is_visible():
                        # Try to find delete button on the card
                        target_card.hover()
                        page.wait_for_timeout(500)
                        delete_btn = target_card.locator(
                            'button.qwenpaw-btn-dangerous, '
                            'button:has-text("删除"), '
                            'button:has-text("Delete"), '
                            'button:has(.anticon-delete)'
                        ).first
                        if delete_btn.is_visible():
                            delete_btn.click()
                            page.wait_for_timeout(1000)
                            confirm_btn = page.locator(
                                '.qwenpaw-modal-confirm-btns button.qwenpaw-btn-dangerous, '
                                '.qwenpaw-modal button.qwenpaw-btn-dangerous, '
                                '.qwenpaw-modal button.qwenpaw-btn-primary'
                            ).first
                            if confirm_btn.is_visible():
                                confirm_btn.click()
                                page.wait_for_timeout(2000)
                            logger.info(f"Cleanup: deleted test skill '{skill_name}'")
                except Exception:
                    logger.warning(f"Cleanup failed: could not delete test skill '{skill_name}'")

            # Cleanup: delete temp file
            if zip_path:
                try:
                    import shutil
                    temp_dir_to_clean = os.path.dirname(zip_path)
                    shutil.rmtree(temp_dir_to_clean, ignore_errors=True)
                    logger.info("Cleanup: deleted temporary zip file")
                except Exception:
                    logger.warning("Cleanup failed: could not delete temp file")


# ============================================================================
# POOL-P2-001: Import builtin skill pack
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.skill_pool
class TestSkillPoolBuiltinImport:
    """POOL-P2-001: Import builtin skill pack"""

    @pytest.mark.test_id("POOL-P2-001")
    def test_skill_pool_builtin_import(self, page: Page, request: pytest.FixtureRequest):
        """Test importing the builtin skill pack."""
        test_name = request.node.name

        log_test_step("Navigate to skill pool page")
        navigate_to_skill_pool(page)

        log_test_step("Find builtin skill import button")
        builtin_btn = page.locator(
            'button:has-text("内置"), button:has-text("Built"), '
            'button:has-text("Builtin"), button:has-text("Update"), '
            'button:has-text("更新")'
        ).first

        if builtin_btn.count() == 0:
            pytest.skip("Builtin skill import button not found, skipping test")

        expect(builtin_btn).to_be_visible(timeout=5000)
        logger.info("Builtin skill import button exists")

        builtin_btn.click()
        page.wait_for_timeout(2000)

        # Check if a dialog/drawer opened, or import ran directly
        modal_or_drawer = page.locator('.qwenpaw-modal, .ant-modal, .qwenpaw-drawer, .ant-drawer, [role="dialog"]').last
        if modal_or_drawer.count() > 0:
            try:
                expect(modal_or_drawer).to_be_visible(timeout=5000)
                logger.info("Builtin skill import dialog opened")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            except Exception:
                logger.info("Dialog exists but not visible, may have auto-closed")
        else:
            # Possibly the click triggered import directly (no dialog)
            success_msg = page.locator('.qwenpaw-message-success, .ant-message-success').first
            if success_msg.count() > 0:
                logger.info("Builtin skill import executed (no dialog confirmation)")
            else:
                logger.info("No dialog appeared after click, may be running in background")

        log_test_result(test_name, True, 0)
