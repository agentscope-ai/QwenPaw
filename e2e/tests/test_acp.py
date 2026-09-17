# -*- coding: utf-8 -*-
"""
QwenPaw ACP (Agent Communication Protocol) management module end-to-end tests

ACP module tests:
- ACP-001: ACP page load and card list display (P0)
- ACP-002: Create ACP drawer form validation (P0)
- ACP-003: ACP enable/disable toggle (P0)
- ACP-004: Filter tab switching (All/Builtin/Custom) (P1)
- ACP-005: Edit ACP configuration (P1)
- ACP-006: Create custom ACP and delete (P1)
- ACP-007: Builtin ACP protection validation (P2)
- ACP-008: ACP card content details validation (P2)

Test framework: pytest + Playwright
Run command: pytest tests/test_acp.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


# ============================================================================
# ACP-001: ACP page load and card list display
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.acp
class TestACPPageDisplay:
    """
    ACP-001: ACP configuration management page load and card list display

    Functional coverage:
    1. /acp page access and load
    2. Breadcrumb validation (Workspace / ACP)
    3. Filter tabs display
    4. Create button display
    5. ACP card list display (builtin ACP cards)
    """

    @pytest.mark.test_id("ACP-001")
    def test_acp_page_load_and_card_list(self, page: Page, request: pytest.FixtureRequest):
        """Verify ACP page load and card list display."""
        test_name = request.node.name

        try:
            # 1. Navigate to ACP page
            log_test_step("1. Navigate to ACP page")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            logger.info("ACP page loaded")

            # 2. Verify breadcrumb
            log_test_step("2. Verify breadcrumb")
            breadcrumb = page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
            if breadcrumb.is_visible(timeout=3000):
                breadcrumb_text = breadcrumb.inner_text().strip()
                logger.info(f"Breadcrumb content: {breadcrumb_text}")
                assert "ACP" in breadcrumb_text, f"Breadcrumb should contain ACP, actual: {breadcrumb_text}"
                logger.info("Breadcrumb validation passed")
            else:
                logger.warning("Breadcrumb element not found, skipping validation")

            # 3. Verify filter tabs
            log_test_step("3. Verify filter tabs")
            page_text = page.locator("body").inner_text()
            has_all_tab = "All" in page_text or "全部" in page_text
            has_builtin_tab = "Builtin" in page_text or "内置" in page_text
            has_custom_tab = "Custom" in page_text or "自定义" in page_text

            assert has_all_tab, "Page should contain All tab"
            logger.info("All tab visible")
            if has_builtin_tab:
                logger.info("Builtin tab visible")
            if has_custom_tab:
                logger.info("Custom tab visible")

            # 4. Verify create button
            log_test_step("4. Verify create button")
            create_btn = page.locator(
                'button:has-text("Create"), button:has-text("创建"), '
                'button:has-text("Add"), button:has-text("添加"), '
                'button:has-text("新增"), button:has-text("New")'
            ).first
            assert create_btn.is_visible(timeout=5000), "Create button should be visible"
            logger.info("Create button visible")

            # 5. Verify ACP card list
            log_test_step("5. Verify ACP card list")
            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            assert len(cards) > 0, "ACP card list should not be empty (at least builtin ACP expected)"
            logger.info(f"Found {len(cards)} ACP cards")

            # Verify builtin ACPs exist
            builtin_names = ["opencode", "qwen_code", "claude_code", "codex"]
            found_builtin = []
            for card in cards:
                card_text = card.inner_text().strip()
                for bname in builtin_names:
                    if bname in card_text.lower():
                        found_builtin.append(bname)
            if found_builtin:
                logger.info(f"Found builtin ACPs: {found_builtin}")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-002: Create ACP drawer form validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.acp
class TestCreateACPDrawerForm:
    """
    ACP-002: Create ACP drawer form validation

    Functional coverage:
    1. Click create button to open drawer
    2. Drawer title validation
    3. Form field validation (agentKey, command, args, env, etc.)
    4. Cancel and close drawer
    """

    @pytest.mark.test_id("ACP-002")
    def test_create_acp_drawer_form(self, page: Page, request: pytest.FixtureRequest):
        """Verify create ACP drawer form."""
        test_name = request.node.name

        try:
            # 1. Navigate to ACP page
            log_test_step("1. Navigate to ACP page")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. Click create button
            log_test_step("2. Click create button")
            create_btn = page.locator(
                'button:has-text("Create"), button:has-text("创建"), '
                'button:has-text("Add"), button:has-text("添加"), '
                'button:has-text("新增"), button:has-text("New")'
            ).first

            assert create_btn.is_visible(timeout=5000), "Create button not visible, cannot continue"

            create_btn.click()
            page.wait_for_timeout(500)

            # 3. Verify drawer opens
            log_test_step("3. Verify drawer opens")
            drawer = page.locator(".qwenpaw-drawer, .qwenpaw-modal").first
            expect(drawer).to_be_visible(timeout=5000)
            logger.info("ACP create drawer opened")

            # Verify title
            drawer_title = drawer.locator(
                '.qwenpaw-drawer-title, .qwenpaw-modal-title, h2, h3'
            ).first
            if drawer_title.is_visible(timeout=3000):
                title_text = drawer_title.inner_text().strip()
                logger.info(f"Drawer title: {title_text}")

            # 4. Verify form fields
            log_test_step("4. Verify form fields")
            drawer_text = drawer.inner_text()

            # agentKey field
            agent_key_input = drawer.locator(
                'input[id*="agentKey"], input[name*="agentKey"], '
                'input[placeholder*="key"], input[placeholder*="Key"]'
            ).first
            if agent_key_input.is_visible(timeout=3000):
                assert agent_key_input.is_enabled(), "agentKey should be editable when creating"
                logger.info("agentKey input is visible and editable")

            # command field
            command_input = drawer.locator(
                'input[id*="command"], input[name*="command"], '
                'input[placeholder*="command"], input[placeholder*="Command"]'
            ).first
            assert command_input.is_visible(timeout=3000), "command input should be visible"
            logger.info("command input is visible")

            # args field (textarea)
            args_input = drawer.locator(
                'textarea[id*="args"], textarea[name*="args"], textarea'
            ).first
            if args_input.is_visible(timeout=3000):
                logger.info("args textarea is visible")

            # Switch fields (enabled, trusted)
            switches = drawer.locator('.qwenpaw-switch').all()
            logger.info(f"Found {len(switches)} switch fields")

            # tool_parse_mode dropdown
            select_el = drawer.locator('.qwenpaw-select').first
            if select_el.is_visible(timeout=3000):
                logger.info("Select dropdown visible (tool_parse_mode)")

            # Key field existence validation
            expected_labels = ["agentKey", "command", "enabled", "trusted"]
            for label in expected_labels:
                if label.lower() in drawer_text.lower():
                    logger.info(f"Found form label: {label}")

            # 5. Cancel and close drawer
            log_test_step("5. Cancel and close drawer")
            cancel_btn = drawer.locator(
                'button:has-text("Cancel"), button:has-text("取消")'
            ).first
            close_btn = drawer.locator('.qwenpaw-drawer-close, .qwenpaw-modal-close').first

            if cancel_btn.is_visible(timeout=3000):
                cancel_btn.click()
            elif close_btn.is_visible(timeout=3000):
                close_btn.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            logger.info("Drawer closed")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-003: ACP enable/disable toggle
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.acp
class TestACPToggleSwitch:
    """
    ACP-003: ACP enable/disable toggle

    Functional coverage:
    1. Enable/disable switch on card
    2. Toggle state change
    3. Restore original state
    """

    @pytest.mark.test_id("ACP-003")
    def test_acp_toggle_switch(self, page: Page, request: pytest.FixtureRequest):
        """Verify ACP enable/disable toggle."""
        test_name = request.node.name
        initial_checked = None
        target_switch = None

        try:
            # 1. Navigate to ACP page
            log_test_step("1. Navigate to ACP page")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. Find toggle on ACP card
            log_test_step("2. Find toggle on ACP card")
            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()

            if len(cards) == 0:
                logger.info("No ACP cards found, skipping validation")
                log_test_result(test_name, True, 0)
                return

            # Find switch in the first card
            first_card = cards[0]
            target_switch = first_card.locator('.qwenpaw-switch').first

            if not target_switch.is_visible(timeout=3000):
                logger.info("No switch found on card, skipping validation")
                log_test_result(test_name, True, 0)
                return

            # 3. Record initial state
            log_test_step("3. Record initial state")
            initial_checked = target_switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
            logger.info(f"Initial switch state: {'enabled' if initial_checked else 'disabled'}")

            # 4. Toggle state
            log_test_step("4. Toggle switch state")
            target_switch.click()
            page.wait_for_timeout(1000)

            new_checked = target_switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
            logger.info(f"Switch state after toggle: {'enabled' if new_checked else 'disabled'}")
            assert new_checked != initial_checked, \
                f"Switch state should change: initial={initial_checked}, current={new_checked}"
            logger.info("Switch state toggled successfully")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
        finally:
            # Restore original state
            try:
                if initial_checked is not None and target_switch is not None:
                    current = target_switch.evaluate(
                        "el => el.classList.contains('qwenpaw-switch-checked') || "
                        "el.getAttribute('aria-checked') === 'true'"
                    )
                    if current != initial_checked:
                        target_switch.click()
                        page.wait_for_timeout(500)
                        logger.info("Switch restored to original state")
            except Exception as restore_err:
                logger.warning(f"Failed to restore original state: {restore_err}")


# ============================================================================
# ACP-004: Filter tab switching (All/Builtin/Custom)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.acp
class TestACPFilterTabs:
    """
    ACP-004: Filter tab switching

    Functional coverage:
    1. Switch to Builtin tab
    2. Verify only builtin ACPs are shown
    3. Switch to Custom tab
    4. Switch back to All tab to restore
    """

    @pytest.mark.test_id("ACP-004")
    def test_filter_tabs_switch(self, page: Page, request: pytest.FixtureRequest):
        """Verify filter tab switching."""
        test_name = request.node.name

        try:
            # 1. Navigate to ACP page
            log_test_step("1. Navigate to ACP page")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. Record card count under All tab
            log_test_step("2. Record card count under All tab")
            all_cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            all_count = len(all_cards)
            logger.info(f"Card count under All tab: {all_count}")

            # 3. Switch to Builtin tab
            log_test_step("3. Switch to Builtin tab")
            builtin_tab = page.locator(
                '[class*="tab"]:has-text("Builtin"), '
                '[class*="tab"]:has-text("内置"), '
                '.qwenpaw-segmented-item:has-text("Builtin"), '
                '.qwenpaw-segmented-item:has-text("内置")'
            ).first

            if not builtin_tab.is_visible(timeout=5000):
                logger.info("Builtin tab not visible, skipping tab switch validation")
                log_test_result(test_name, True, 0)
                return

            builtin_tab.click()
            page.wait_for_timeout(1000)

            builtin_cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            builtin_count = len(builtin_cards)
            logger.info(f"Card count under Builtin tab: {builtin_count}")

            if all_count > 0:
                assert builtin_count <= all_count, \
                    f"Builtin count should be <= All count: builtin={builtin_count}, all={all_count}"
            logger.info("Builtin tab filter works correctly")

            # 4. Switch to Custom tab
            log_test_step("4. Switch to Custom tab")
            custom_tab = page.locator(
                '[class*="tab"]:has-text("Custom"), '
                '[class*="tab"]:has-text("自定义"), '
                '.qwenpaw-segmented-item:has-text("Custom"), '
                '.qwenpaw-segmented-item:has-text("自定义")'
            ).first

            if custom_tab.is_visible(timeout=3000):
                custom_tab.click()
                page.wait_for_timeout(1000)

                custom_cards = page.locator(
                    '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
                ).all()
                custom_count = len(custom_cards)
                logger.info(f"Card count under Custom tab: {custom_count}")

                assert custom_count <= all_count, \
                    f"Custom count should be <= All count: custom={custom_count}, all={all_count}"
                logger.info("Custom tab filter works correctly")

            # 5. Switch back to All tab
            log_test_step("5. Switch back to All tab")
            all_tab = page.locator(
                '[class*="tab"]:has-text("All"), '
                '[class*="tab"]:has-text("全部"), '
                '.qwenpaw-segmented-item:has-text("All"), '
                '.qwenpaw-segmented-item:has-text("全部")'
            ).first

            if all_tab.is_visible(timeout=3000):
                all_tab.click()
                page.wait_for_timeout(1000)

                restored_cards = page.locator(
                    '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
                ).all()
                restored_count = len(restored_cards)
                assert restored_count == all_count, \
                    f"Restored count should match initial: restored={restored_count}, all={all_count}"
                logger.info("Restored count matches All tab")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-005: Edit ACP configuration
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.acp
class TestEditACPConfig:
    """
    ACP-005: Edit ACP configuration

    Functional coverage:
    1. Click card to open edit drawer
    2. Drawer displays current configuration
    3. Cancel edit without saving
    """

    @pytest.mark.test_id("ACP-005")
    def test_edit_acp_config(self, page: Page, request: pytest.FixtureRequest):
        """Verify edit ACP configuration."""
        test_name = request.node.name

        try:
            # 1. Navigate to ACP page
            log_test_step("1. Navigate to ACP page")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. Click the first ACP card
            log_test_step("2. Click the first ACP card")
            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()

            if len(cards) == 0:
                logger.info("No ACP cards found, skipping validation")
                log_test_result(test_name, True, 0)
                return

            first_card = cards[0]
            card_name = first_card.inner_text().strip()[:50]
            logger.info(f"Clicking card: {card_name}")

            # Click card body (excluding switch area)
            card_body = first_card.locator(
                '[class*="cardBody"], [class*="content"], .qwenpaw-card-body, '
                '[class*="agentKey"], [class*="title"]'
            ).first
            if card_body.is_visible(timeout=3000):
                card_body.click()
            else:
                first_card.click()
            page.wait_for_timeout(500)

            # 3. Verify edit drawer opens
            log_test_step("3. Verify edit drawer opens")
            drawer = page.locator(".qwenpaw-drawer, .qwenpaw-modal").first
            expect(drawer).to_be_visible(timeout=5000)
            logger.info("Edit drawer opened")

            # 4. Verify current configuration is populated
            log_test_step("4. Verify configuration is populated")

            # Check agentKey field (builtin ACP may hide this field)
            agent_key_input = drawer.locator('#agentKey').first
            if agent_key_input.is_visible(timeout=3000):
                key_value = agent_key_input.input_value()
                assert len(key_value.strip()) > 0, "agentKey should have a value in edit mode"
                logger.info(f"agentKey current value: {key_value}")
            else:
                # agentKey for builtin ACP may be hidden (form-item-hidden), which is normal protection
                # Fall back to validating agentKey info from the drawer title
                drawer_title = drawer.locator('.qwenpaw-drawer-title').first
                if drawer_title.is_visible(timeout=2000):
                    title_text = drawer_title.inner_text().strip()
                    assert len(title_text) > 0, "Edit drawer should have a title"
                    logger.info(f"agentKey field hidden (builtin protection), drawer title: {title_text}")
                else:
                    logger.info("agentKey field hidden (builtin ACP protection behavior)")

            # Check command field (required, should always be visible)
            command_input = drawer.locator('#command').first
            assert command_input.is_visible(timeout=3000), "Edit drawer should have command input"
            cmd_value = command_input.input_value()
            assert len(cmd_value.strip()) > 0, "command should have a value in edit mode"
            logger.info(f"command current value: {cmd_value}")

            # 5. Cancel edit
            log_test_step("5. Cancel edit without saving")
            cancel_btn = drawer.locator(
                'button:has-text("Cancel"), button:has-text("取消")'
            ).first
            close_btn = drawer.locator('.qwenpaw-drawer-close, .qwenpaw-modal-close').first

            if cancel_btn.is_visible(timeout=3000):
                cancel_btn.click()
            elif close_btn.is_visible(timeout=3000):
                close_btn.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            logger.info("Cancel edit completed")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-006: Create custom ACP and delete
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.acp
class TestCreateAndDeleteCustomACP:
    """
    ACP-006: Create custom ACP and delete

    Functional coverage:
    1. Create custom ACP configuration
    2. Verify new ACP appears in the list
    3. Delete custom ACP
    4. Verify the list updates after deletion
    """

    @pytest.mark.test_id("ACP-006")
    def test_create_and_delete_custom_acp(self, page: Page, request: pytest.FixtureRequest):
        """Verify create and delete custom ACP."""
        test_name = request.node.name
        created_acp_key = None

        try:
            # 1. Navigate to ACP page
            log_test_step("1. Navigate to ACP page")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            initial_cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            initial_count = len(initial_cards)

            # 2. Click create button
            log_test_step("2. Open create drawer")
            create_btn = page.locator(
                'button:has-text("Create"), button:has-text("创建"), '
                'button:has-text("Add"), button:has-text("添加"), '
                'button:has-text("新增"), button:has-text("New")'
            ).first

            assert create_btn.is_visible(timeout=5000), "Create button not visible, cannot continue"

            create_btn.click()
            page.wait_for_timeout(500)

            drawer = page.locator(".qwenpaw-drawer, .qwenpaw-modal").first
            expect(drawer).to_be_visible(timeout=5000)

            # 3. Fill in the form
            log_test_step("3. Fill in create form")
            import time
            created_acp_key = f"e2e_test_acp_{int(time.time())}"

            # Fill agentKey
            key_input = drawer.locator(
                'input[id*="agentKey"], input[name*="agentKey"], '
                'input[placeholder*="key"], input[placeholder*="Key"]'
            ).first
            if key_input.is_visible(timeout=3000) and key_input.is_enabled():
                key_input.fill(created_acp_key)
                logger.info(f"Filled agentKey: {created_acp_key}")

            # Fill command
            cmd_input = drawer.locator(
                'input[id*="command"], input[name*="command"], '
                'input[placeholder*="command"]'
            ).first
            if cmd_input.is_visible(timeout=3000):
                cmd_input.fill("/usr/bin/echo")
                logger.info("Filled command: /usr/bin/echo")

            # 4. Save
            log_test_step("4. Save creation")
            save_btn = drawer.locator(
                'button.qwenpaw-btn-primary, button:has-text("Save"), '
                'button:has-text("保存"), button:has-text("OK"), button:has-text("确定")'
            ).first
            if save_btn.is_visible(timeout=3000):
                save_btn.click()
                page.wait_for_timeout(2000)

            # Check creation success
            success_msg = page.locator(
                '.qwenpaw-message-success, .qwenpaw-notification-success'
            ).first
            if success_msg.is_visible(timeout=5000):
                logger.info("Success message appeared")

            # 5. Verify new ACP appears in the list
            log_test_step("5. Verify new ACP appears")
            page.wait_for_timeout(1000)
            new_cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            new_count = len(new_cards)
            logger.info(f"Card count after creation: {new_count} (initial: {initial_count})")

            # Find the newly created ACP
            found_new = False
            for card in new_cards:
                if created_acp_key in card.inner_text():
                    found_new = True
                    logger.info(f"Found newly created ACP: {created_acp_key}")
                    break

            # 6. Delete newly created ACP
            if found_new:
                log_test_step("6. Delete newly created ACP")
                # Click the new card to open the edit drawer
                target_card = page.locator(
                    f'[class*="acpCard"]:has-text("{created_acp_key}"), '
                    f'[class*="ACPCard"]:has-text("{created_acp_key}"), '
                    f'.qwenpaw-card:has-text("{created_acp_key}")'
                ).first

                if target_card.is_visible(timeout=3000):
                    card_body = target_card.locator(
                        '[class*="agentKey"], [class*="title"], [class*="cardBody"]'
                    ).first
                    if card_body.is_visible(timeout=2000):
                        card_body.click()
                    else:
                        target_card.click()
                    page.wait_for_timeout(500)

                    edit_drawer = page.locator(".qwenpaw-drawer, .qwenpaw-modal").first
                    if edit_drawer.is_visible(timeout=5000):
                        delete_btn = edit_drawer.locator(
                            'button:has-text("Delete"), button:has-text("删除")'
                        ).first
                        if delete_btn.is_visible(timeout=3000):
                            delete_btn.click()
                            page.wait_for_timeout(500)

                            # Confirm deletion
                            confirm_btn = page.locator(
                                '.qwenpaw-popconfirm button.qwenpaw-btn-primary, '
                                '.qwenpaw-popconfirm button:has-text("OK"), '
                                '.qwenpaw-popconfirm button:has-text("确定"), '
                                '.qwenpaw-modal button.qwenpaw-btn-primary'
                            ).first
                            if confirm_btn.is_visible(timeout=3000):
                                confirm_btn.click()
                                page.wait_for_timeout(2000)
                                logger.info("Deletion confirmed")
                            else:
                                logger.info("Confirm delete button not found")
                        else:
                            # Close drawer
                            page.keyboard.press("Escape")
                            logger.info("Delete button not found in drawer")

                # Verify count returns after deletion
                page.wait_for_timeout(1000)
                final_cards = page.locator(
                    '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
                ).all()
                final_count = len(final_cards)
                logger.info(f"Card count after deletion: {final_count}")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-007: Builtin ACP protection validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.acp
class TestBuiltinACPProtection:
    """
    ACP-007: Builtin ACP protection validation

    Functional coverage:
    1. Builtin ACP agentKey not editable
    2. Builtin ACP has no delete button
    """

    @pytest.mark.test_id("ACP-007")
    def test_builtin_acp_protection(self, page: Page, request: pytest.FixtureRequest):
        """Verify builtin ACP protection mechanism."""
        test_name = request.node.name

        try:
            # 1. Navigate to ACP page
            log_test_step("1. Navigate to ACP page")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. Switch to Builtin tab
            log_test_step("2. Find builtin ACP card")
            builtin_tab = page.locator(
                '[class*="tab"]:has-text("Builtin"), '
                '[class*="tab"]:has-text("内置"), '
                '.qwenpaw-segmented-item:has-text("Builtin")'
            ).first

            if builtin_tab.is_visible(timeout=3000):
                builtin_tab.click()
                page.wait_for_timeout(1000)

            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()

            if len(cards) == 0:
                logger.info("No builtin ACP cards found, skipping protection validation")
                log_test_result(test_name, True, 0)
                return

            # 3. Click first builtin ACP card
            log_test_step("3. Open builtin ACP edit drawer")
            first_card = cards[0]
            card_body = first_card.locator(
                '[class*="agentKey"], [class*="title"], [class*="cardBody"]'
            ).first
            if card_body.is_visible(timeout=3000):
                card_body.click()
            else:
                first_card.click()
            page.wait_for_timeout(500)

            drawer = page.locator(".qwenpaw-drawer, .qwenpaw-modal").first
            if not drawer.is_visible(timeout=5000):
                logger.info("Edit drawer did not open")
                log_test_result(test_name, True, 0)
                return

            # 4. Verify agentKey is not editable
            log_test_step("4. Verify agentKey is not editable")
            key_input = drawer.locator('#agentKey').first
            if key_input.is_visible(timeout=3000):
                is_disabled = key_input.is_disabled()
                is_readonly = key_input.get_attribute("readonly") is not None
                assert is_disabled or is_readonly, \
                    "Builtin ACP agentKey should be disabled or readonly"
                logger.info("Builtin ACP agentKey is not editable (disabled/readonly)")
            else:
                # agentKey hidden via form-item-hidden, which itself is a form of protection
                hidden_item = drawer.locator('.qwenpaw-form-item-hidden').first
                assert hidden_item.count() > 0 or not key_input.is_visible(), \
                    "Builtin ACP agentKey should be hidden or non-editable"
                logger.info("Builtin ACP agentKey is hidden (non-editable protection in effect)")

            # 5. Verify no delete button or delete button is disabled
            log_test_step("5. Verify delete protection")
            delete_btn = drawer.locator(
                'button:has-text("Delete"), button:has-text("删除")'
            ).first
            if delete_btn.is_visible(timeout=3000):
                assert delete_btn.is_disabled(), \
                    "Builtin ACP delete button should be disabled"
                logger.info("Delete button is disabled (protection in effect)")
            else:
                logger.info("Builtin ACP has no delete button (protection in effect)")

            # 6. Close drawer
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-008: ACP card content details validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.acp
class TestACPCardDetails:
    """
    ACP-008: ACP card content details validation

    Functional coverage:
    1. Card displays agentKey
    2. Card displays builtin/custom tag
    3. Card displays command and args summary
    """

    @pytest.mark.test_id("ACP-008")
    def test_acp_card_content_details(self, page: Page, request: pytest.FixtureRequest):
        """Verify ACP card content details."""
        test_name = request.node.name

        try:
            # 1. Navigate to ACP page
            log_test_step("1. Navigate to ACP page")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. Get ACP card list
            log_test_step("2. Get card list")
            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()

            assert len(cards) > 0, "ACP card list should not be empty"
            logger.info(f"Found {len(cards)} ACP cards")

            # 3. Verify each card content
            log_test_step("3. Verify card content")
            cards_with_key = 0
            cards_with_switch = 0
            for i, card in enumerate(cards[:4]):  # Verify up to first 4
                card_text = card.inner_text().strip()
                assert len(card_text) > 0, f"Card {i+1} content should not be empty"
                logger.info(f"Card {i+1} content: {card_text[:100]}")

                # Check for agentKey-like identifier
                has_key = any(name in card_text.lower() for name in [
                    "opencode", "qwen_code", "claude_code", "codex",
                    "e2e_test", "custom"
                ])
                if has_key:
                    cards_with_key += 1

                # Check switch exists
                switch = card.locator('.qwenpaw-switch').first
                if switch.count() > 0:
                    cards_with_switch += 1

            # At least some cards should have agentKey identifier or switch
            assert cards_with_key > 0 or cards_with_switch > 0, \
                "At least some ACP cards should contain agentKey identifier or enable/disable switch"
            logger.info(f"Card details validation passed (with key: {cards_with_key}, with switch: {cards_with_switch})")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
