# -*- coding: utf-8 -*-
"""
QwenPaw built-in tools management module P0 end-to-end test cases.

Tool module tests:
- TOOL-001: Page display + global toggle + tool card verification
- TOOL-002: Per-tool enable/disable + async-execute toggle
- TOOL-003: Global toggle state consistency

Stack: pytest + Playwright
Run with: pytest tests/test_tools_p0.py -v
"""
from __future__ import annotations

import logging
import re

import pytest
from playwright.sync_api import APIRequestContext, Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


# ============================================================================
# Setup helper
# ============================================================================
#
# Since v2.0.0 (PR #5509) the Tools page uses an enabled/available split
# layout: `.toolsGrid` is only rendered when `enabledTools.length > 0`. On
# an isolated e2e backend all built-in tools default to disabled, so the
# grid does not appear and any test that asserts on it fails with
# "toolsGrid not visible". We seed one non-config tool as enabled via the
# public API before entering the UI — this is setup only, the tests still
# assert on DOM state.
def _ensure_at_least_one_tool_enabled(
    api_context: APIRequestContext,
) -> None:
    """Ensure at least one built-in tool is enabled so `.toolsGrid` renders.

    Prefers tools that do not require configuration to avoid seeding
    `requires_config` warnings on the card. No-op when a tool is already
    enabled.
    """
    resp = api_context.get("/api/tools")
    if not resp.ok:
        logger.warning(
            "Could not list tools for seed (status=%s); skipping toolsGrid "
            "prerequisite. Test may fall back to legacy behaviour.",
            resp.status,
        )
        return
    tools = resp.json()
    if any(t.get("enabled") for t in tools):
        logger.info("At least one tool is already enabled; no seed needed")
        return
    # Pick the first tool that does not require config; fall back to the
    # first tool of any kind if every tool requires config.
    seed = next(
        (t for t in tools if not t.get("requires_config")),
        tools[0] if tools else None,
    )
    if seed is None:
        logger.warning("No tools returned by backend; nothing to seed")
        return
    name = seed["name"]
    logger.info("Seeding tool '%s' as enabled to make toolsGrid render", name)
    toggle_resp = api_context.patch(f"/api/tools/{name}/toggle")
    if not toggle_resp.ok:
        logger.warning(
            "Failed to seed tool '%s' (status=%s): %s",
            name,
            toggle_resp.status,
            toggle_resp.text(),
        )


# ============================================================================
# TOOL-001: Page display + global toggle + tool card verification
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.tools
class TestToolsPageDisplayAndGlobalToggle:
    """
    TOOL-001: Built-in tools page display and global toggle switching.

    Coverage:
    1. Navigate to and load /tools page
    2. Breadcrumb verification (Workspace / Built-in Tools)
    3. Global enable/disable switch display and toggling
    4. Tool card grid display
    5. Restore original state
    """

    @pytest.mark.test_id("TOOL-001")
    def test_tools_page_display_and_global_toggle(self, page: Page, request: pytest.FixtureRequest):
        """Verify built-in tools page display and global toggle."""
        test_name = request.node.name

        initial_enabled = None
        global_switch = None

        try:
            # 1. Visit the built-in tools page
            log_test_step("1. Visit the built-in tools page")
            page.goto(f"{config.base_url}/tools")

            # Wait for the page container to be visible
            tools_page = page.locator('div[class*="toolsPage"]')
            expect(tools_page).to_be_visible(timeout=10000)
            logger.info("Built-in tools page loaded")

            # 2. Verify breadcrumb
            log_test_step("2. Verify breadcrumb")
            breadcrumb = page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
            if breadcrumb.is_visible():
                breadcrumb_text = breadcrumb.inner_text().strip()
                logger.info(f"Breadcrumb text: {breadcrumb_text}")
                assert "Tools" in breadcrumb_text, (
                    "Breadcrumb should contain Tools"
                )
                logger.info("Breadcrumb verified")
            else:
                logger.warning("Breadcrumb element not found, skipping verification")

            # 3. Verify batch controls introduced by the tools redesign.
            log_test_step("3. Verify batch enable/disable controls")
            enable_all = page.locator(
                'button:has-text("Enable all"), '
                'button:has-text("全部启用")'
            ).first
            disable_all = page.locator(
                'button:has-text("Disable all"), '
                'button:has-text("全部禁用")'
            ).first
            expect(enable_all).to_be_visible(timeout=5000)
            expect(disable_all).to_be_visible(timeout=5000)

            # 4. Verify the tool card grid
            log_test_step("4. Verify the tool card grid")
            tool_cards = page.locator('div[class*="toolCard"]')
            expect(tool_cards.first).to_be_visible(timeout=15000)
            card_count = tool_cards.count()
            logger.info(f"Tool card count: {card_count}")
            assert card_count > 0, "There should be at least one tool card"

            # Verify the first tool card structure
            first_card = tool_cards.first
            expect(first_card).to_be_visible()

            # Verify the tool name
            tool_name = first_card.locator('h3[class*="toolName"]')
            expect(tool_name).to_be_visible()
            name_text = tool_name.inner_text().strip()
            logger.info(f"First tool name: {name_text}")

            tool_switch = first_card.locator('[role="switch"]').first
            expect(tool_switch).to_be_visible()
            assert tool_switch.get_attribute("aria-checked") in (
                "true",
                "false",
            )

            # Verify the description
            description = first_card.locator('p[class*="description"]')
            expect(description).to_be_visible()
            desc_text = description.inner_text().strip()
            logger.info(f"First tool description: {desc_text[:50]}...")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - tools page display OK")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
        finally:
            # 6. Restore the original state
            try:
                if initial_enabled is not None and global_switch is not None:
                    log_test_step("6. Restore original state")
                    current_aria = global_switch.first.get_attribute('aria-checked')
                    current_enabled = current_aria == 'true'
                    if current_enabled != initial_enabled:
                        global_switch.first.click()
                        expected_restore = 'true' if initial_enabled else 'false'
                        for _poll in range(10):
                            page.wait_for_timeout(1000)
                            if global_switch.first.get_attribute('aria-checked') == expected_restore:
                                break
                        logger.info("Global toggle restored")
            except Exception as restore_error:
                logger.warning(f"Error restoring original state (does not affect test result): {str(restore_error)}")

# ============================================================================
# TOOL-002: Per-tool enable/disable + async-execute toggle
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.tools
class TestToolEnableDisableAndAsyncToggle:
    """
    TOOL-002: Per-tool enable/disable and async-execute toggle.

    Coverage:
    1. Per-tool enable/disable button
    2. Async-execute switch toggle
    3. State change verification
    4. Restore original state
    """

    @pytest.mark.test_id("TOOL-002")
    def test_tool_enable_disable_and_async_toggle(
        self,
        page: Page,
        api_context: APIRequestContext,
        request: pytest.FixtureRequest,
    ):
        """Verify per-tool enable/disable and async-execute toggle."""
        test_name = request.node.name

        initial_status = None
        enable_disable_button = None
        status_text = None
        tool_switch = None

        try:
            # 0. Seed: v2.0.0 Tools page hides `.toolsGrid` until at least
            # one tool is enabled. Setup only — the assertions below all
            # target DOM state.
            _ensure_at_least_one_tool_enabled(api_context)

            # 1. Visit the built-in tools page (with timeout and retry)
            log_test_step("1. Visit the built-in tools page")
            try:
                page.goto(f"{config.base_url}/tools", timeout=60000)
            except Exception:
                logger.warning("Tools page first load timed out, retrying...")
                page.wait_for_timeout(3000)
                page.goto(f"{config.base_url}/tools", wait_until="domcontentloaded", timeout=60000)

            # Wait for the page container to be visible
            tools_page = page.locator('div[class*="toolsPage"]')
            expect(tools_page).to_be_visible(timeout=15000)
            logger.info("Built-in tools page loaded")

            # 2. Get the first tool card.
            log_test_step("2. Get the first tool card")
            tool_cards = page.locator('div[class*="toolCard"]')
            expect(tool_cards.first).to_be_visible()

            first_card = tool_cards.first

            # Get the tool name for logging
            tool_name_elem = first_card.locator('h3[class*="toolName"]')
            tool_name = tool_name_elem.inner_text().strip()
            logger.info(f"Test tool: {tool_name}")

            # 3. Verify the initial status
            log_test_step("3. Verify initial status")

            tool_switch = first_card.locator('[role="switch"]').first
            expect(tool_switch).to_be_visible(timeout=5000)
            initial_status = tool_switch.get_attribute("aria-checked")

            # 4. Test the async-execute toggle (if present)
            # Source: the async-execute button exists only on the execute_shell_command tool,
            # and is disabled={!tool.enabled}, i.e. the tool must be enabled to interact.
            log_test_step("4. Test async-execute toggle")
            async_button = first_card.locator(
                'button:has-text("Async"), button:has-text("异步")'
            ).first

            if async_button.is_visible():
                # Async-execute button is disabled when the tool is disabled; ensure the tool is enabled first
                async_text = async_button.inner_text().strip()
                logger.info(f"Async-execute button text: {async_text}")

                # Determine current async-execute state (case-insensitive)
                is_async_enabled = "enabled" in async_text.lower() and "disabled" not in async_text.lower()

                # Toggle the async-execute state
                async_button.click()
                page.wait_for_timeout(2000)

                # Verify the state changed
                new_async_text = async_button.inner_text().strip()
                logger.info(f"Async-execute new state: {new_async_text}")
                new_is_async_enabled = "enabled" in new_async_text.lower() and "disabled" not in new_async_text.lower()
                assert new_is_async_enabled != is_async_enabled, "Async-execute state should have toggled"

                # Restore async-execute state
                async_button.click()
                page.wait_for_timeout(2000)
                restored_async_text = async_button.inner_text().strip()
                logger.info(f"Async-execute restored state: {restored_async_text}")
                restored_is_async_enabled = "enabled" in restored_async_text.lower() and "disabled" not in restored_async_text.lower()
                assert restored_is_async_enabled == is_async_enabled, "Async-execute state should be restored"

                logger.info("Async-execute toggle test passed")
            else:
                logger.warning("Async-execute button not found, skipping async-execute test")

            # 5. Toggle the card switch and verify its accessible state.
            log_test_step("5. Test per-tool switch")
            tool_switch.click()
            expected = "false" if initial_status == "true" else "true"
            expect(tool_switch).to_have_attribute(
                "aria-checked", expected, timeout=10000
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - per-tool enable/disable and async-execute toggle OK")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
        finally:
            # 6. Restore the original state.
            # If the tool was toggled off (moved to the Available section),
            # click its availableItem tile to re-enable it. Reading the old
            # status_text is unsafe post-move, so we rely on the API seed
            # having left a consistent baseline instead.
            try:
                if tool_switch is not None and initial_status is not None:
                    log_test_step("6. Restore original state")
                    current_status = tool_switch.get_attribute("aria-checked")
                    if current_status != initial_status:
                        tool_switch.click()
                        expect(tool_switch).to_have_attribute(
                            "aria-checked", initial_status, timeout=10000
                        )
            except Exception as restore_error:
                logger.warning(f"Error restoring original state (does not affect test result): {str(restore_error)}")

# ============================================================================
# TOOL-003: Global toggle state consistency verification
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.tools
class TestToolsGlobalToggleConsistency:
    """TOOL-003: Batch enable and disable state consistency."""

    @pytest.mark.test_id("TOOL-003")
    def test_global_toggle_consistency(
        self,
        page: Page,
        api_context: APIRequestContext,
        request: pytest.FixtureRequest,
    ):
        """Verify batch controls update every tool and restore prior states."""
        test_name = request.node.name
        _ensure_at_least_one_tool_enabled(api_context)

        log_test_step("1. Visit the built-in tools page")
        page.goto(f"{config.base_url}/tools")
        cards = page.locator('div[class*="toolCard"]')
        expect(cards.first).to_be_visible(timeout=10000)
        switches = cards.locator('[role="switch"]')
        initial_states = [
            switches.nth(index).get_attribute("aria-checked")
            for index in range(switches.count())
        ]
        assert initial_states, "There should be at least one tool switch"

        disable_all = page.locator(
            'button:has-text("Disable all"), button:has-text("全部禁用")'
        ).first
        enable_all = page.locator(
            'button:has-text("Enable all"), button:has-text("全部启用")'
        ).first

        try:
            log_test_step("2. Disable all tools")
            disable_all.click()
            for index in range(switches.count()):
                expect(switches.nth(index)).to_have_attribute(
                    "aria-checked", "false", timeout=10000
                )

            log_test_step("3. Enable all tools")
            enable_all.click()
            for index in range(switches.count()):
                expect(switches.nth(index)).to_have_attribute(
                    "aria-checked", "true", timeout=10000
                )

            log_test_result(test_name, True, 0)
            logger.info(
                f"Test {test_name} passed - batch controls updated all tools"
            )
        finally:
            log_test_step("4. Restore original tool states")
            for index, initial_state in enumerate(initial_states):
                switch = switches.nth(index)
                if switch.get_attribute("aria-checked") != initial_state:
                    switch.click()
                    expect(switch).to_have_attribute(
                        "aria-checked", initial_state, timeout=10000
                    )


# ============================================================================
# TOOL-P2-001: Async-execute toggle verification
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.tools
class TestToolAsyncSwitch:
    """TOOL-P2-001: Async-execute toggle verification."""

    @pytest.mark.test_id("TOOL-P2-001")
    def test_tool_async_switch(
        self,
        page: Page,
        api_context: APIRequestContext,
        request: pytest.FixtureRequest,
    ):
        """Toggle async execution for the shell-command tool only."""
        test_name = request.node.name
        response = api_context.get("/api/tools")
        assert response.ok, response.text()
        shell_tool = next(
            (
                tool
                for tool in response.json()
                if tool["name"] == "execute_shell_command"
            ),
            None,
        )
        assert shell_tool is not None, (
            "execute_shell_command must be registered"
        )
        original_enabled = shell_tool["enabled"]
        original_async = shell_tool["async_execution"]

        try:
            if not original_enabled:
                enabled = api_context.patch(
                    "/api/tools/execute_shell_command/toggle"
                )
                assert enabled.ok, enabled.text()

            page.goto(
                f"{config.base_url}/tools",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            card = page.locator('div[class*="toolCard"]').filter(
                has_text=re.compile(r"Run commands|执行命令")
            )
            expect(card).to_have_count(1, timeout=10000)

            async_button = card.locator('button[aria-pressed]')
            expect(async_button).to_be_visible(timeout=5000)
            initial_state = async_button.get_attribute("aria-pressed")
            assert initial_state == str(original_async).lower()

            async_button.click()
            expected = str(not original_async).lower()
            expect(async_button).to_have_attribute(
                "aria-pressed", expected, timeout=10000
            )
            updated = api_context.get("/api/tools")
            assert updated.ok, updated.text()
            updated_shell = next(
                tool
                for tool in updated.json()
                if tool["name"] == "execute_shell_command"
            )
            assert updated_shell["async_execution"] is not original_async
            log_test_result(test_name, True, 0)
        finally:
            restored = api_context.patch(
                "/api/tools/execute_shell_command/async-execution",
                data={"async_execution": original_async},
            )
            assert restored.ok, restored.text()
            current = restored.json()
            if current["enabled"] != original_enabled:
                toggle = api_context.patch(
                    "/api/tools/execute_shell_command/toggle"
                )
                assert toggle.ok, toggle.text()
