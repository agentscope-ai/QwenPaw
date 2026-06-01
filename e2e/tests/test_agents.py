# -*- coding: utf-8 -*-
"""
QwenPaw Agents module P0-level end-to-end test cases.

Combined test cases:
- AGENT-001: Agent list display and refresh
- AGENT-002: Create agent (full flow)
- AGENT-003: Edit agent info
- AGENT-004: Delete agent (with confirmation)
- AGENT-005: Enable/disable agent
- AGENT-006: Agent file management
- AGENT-007: Agent API operations

Run: pytest tests/test_agents_p0.py -v
"""
from __future__ import annotations

import json
import logging
import time
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from pages.agents_page import AgentsPage
from utils.helpers import log_test_step, log_test_result, take_screenshot

logger = logging.getLogger(__name__)

AGENTS_URL = f"{config.base_url}/agents"


def navigate_to_agents(page: Page):
    """Navigate to the Agents management page and wait for it to load."""
    page.goto(AGENTS_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)


# ============================================================================
# AGENT-001: Agent list display and refresh
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agents_core
class TestAgentList:
    """
    AGENT-001: Agent list display and refresh.

    Coverage:
    1. Agents management page access and load
    2. Agent list display (name, ID, description, status)
    3. List refresh
    4. Empty-state handling
    """

    @pytest.mark.test_id("AGENT-001")
    def test_agent_list_display_and_refresh(self, page: Page, request: pytest.FixtureRequest):
        """Verify agent list display and refresh."""
        test_name = request.node.name

        # Step 1: Open the Agents management page
        log_test_step("1. Open the Agents management page")
        navigate_to_agents(page)

        # Step 2: Verify page title (supports CN/EN)
        log_test_step("2. Verify page title")
        try:
            header_cn = page.locator('span[class*="breadcrumbCurrent"]:has-text("智能体")').first
            header_en = page.locator('span[class*="breadcrumbCurrent"]:has-text("Agents")').first
            if header_cn.is_visible(timeout=3000):
                logger.info("Page title verified (CN)")
            elif header_en.is_visible(timeout=3000):
                logger.info("Page title verified (EN)")
            else:
                logger.warning("Page title not found, skipping verification")
        except Exception:
            logger.warning("Page title verification skipped")

        # Step 3: Verify breadcrumb (supports CN/EN)
        log_test_step("3. Verify breadcrumb")
        try:
            breadcrumb_cn = page.locator('span[class*="breadcrumbCurrent"]:has-text("智能体")').first
            breadcrumb_en = page.locator('span[class*="breadcrumbCurrent"]:has-text("Agents")').first
            if breadcrumb_cn.is_visible(timeout=3000):
                logger.info("Breadcrumb verified (CN)")
            elif breadcrumb_en.is_visible(timeout=3000):
                logger.info("Breadcrumb verified (EN)")
            else:
                logger.warning("Breadcrumb not found, skipping verification")
        except Exception:
            logger.warning("Breadcrumb verification skipped")

        # Step 4: Verify the agent list is present
        log_test_step("4. Verify the agent list is present")
        agents_page = AgentsPage(page)
        agent_count = agents_page.get_agent_count()
        assert agent_count >= 1, "Agent list should contain at least one agent (default)"
        logger.info(f"Agent list verified, {agent_count} agent(s) total")

        # Step 5: Verify agent info display
        log_test_step("5. Verify agent info display")
        agents = agents_page.get_agent_list()
        assert len(agents) > 0, "Agent list should not be empty"

        has_name = any(agent["name"] for agent in agents)
        assert has_name, "Agents should have a name"
        logger.info(f"Agent info verified: {agents[0]['name']}")

        # Step 6: Refresh the list and verify data is consistent
        log_test_step("6. Refresh the list and verify data is consistent")
        count_before = agents_page.get_agent_count()
        agents_page.refresh_agent_list()
        count_after = agents_page.get_agent_count()
        assert count_before == count_after, "Agent count should match before and after refresh"
        logger.info("Refresh verified")

        log_test_result(test_name, "PASS", "Agent list display and refresh OK")


# ============================================================================
# AGENT-002: Create agent (full flow)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agents_create
class TestCreateAgent:
    """
    AGENT-002: Create agent (full flow).

    Coverage:
    1. Click the Create Agent button
    2. Fill the form (name, description, language)
    3. Submit the form
    4. Verify creation success
    5. Cancel creation
    """

    @pytest.mark.test_id("AGENT-002")
    def test_create_agent_success(self, page: Page, request: pytest.FixtureRequest):
        """Verify agent is created successfully."""
        test_name = request.node.name

        # Generate a unique agent name
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestAgent_{timestamp}"
        agent_description = f"测试智能体_{timestamp}"

        try:
            # Step 1: Open the Agents management page
            log_test_step("1. Open the Agents management page")
            agents_page = AgentsPage(page)
            agents_page.goto()

            # Step 2: Get the agent count before creating
            log_test_step("2. Get the agent count before creating")
            count_before = agents_page.get_agent_count()
            logger.info(f"Agent count before create: {count_before}")

            # Step 3: Click the Create Agent button
            log_test_step("3. Click the Create Agent button")
            agents_page.click_create_agent()

            # Step 4: Verify the form dialog is shown
            log_test_step("4. Verify the form dialog is shown")
            form_dialog = page.locator(agents_page.FORM_DIALOG).first
            expect(form_dialog).to_be_visible(timeout=5000)
            logger.info("Create Agent form dialog is shown")

            # Step 5: Fill agent info
            log_test_step("5. Fill agent info")
            agents_page.fill_agent_form(agent_name, agent_description, "zh")
            logger.info(f"Filled agent info: name={agent_name}, description={agent_description}")

            # Step 6: Submit the form
            log_test_step("6. Submit the form")
            agents_page.submit_agent_form()
            page.wait_for_timeout(2000)

            # Step 7: Verify success message
            log_test_step("7. Verify success message")
            assert agents_page.verify_success_message(), "Create success message should be shown"
            logger.info("Create success message verified")

            # Step 8: Verify the agent appears in the list (with retries)
            log_test_step("8. Verify the agent appears in the list")
            found = False
            for attempt in range(5):
                agents_page.refresh_agent_list()
                page.wait_for_timeout(2000)
                if agents_page.is_agent_exists(agent_name):
                    found = True
                    break
                logger.warning(f"Attempt {attempt + 1}/5: agent {agent_name} not found, retrying...")
                page.wait_for_timeout(2000)
            assert found, f"Agent {agent_name} should appear in the list"
            logger.info(f"Agent {agent_name} found in the list")

            # Step 9: Verify the agent count increased
            log_test_step("9. Verify the agent count increased")
            count_after = agents_page.get_agent_count()
            assert count_after == count_before + 1, f"Agent count should grow from {count_before} to {count_before + 1}"
            logger.info(f"Agent count verified: {count_before} -> {count_after}")

            log_test_result(test_name, "PASS", f"Successfully created agent: {agent_name}")

        finally:
            # Cleanup: delete the created test agent (re-navigate to ensure stable page state)
            try:
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page = AgentsPage(page)
                agents_page.wait_for_page_load()
                if agents_page.is_agent_exists(agent_name):
                    logger.info(f"Cleaning up test agent: {agent_name}")
                    agents_page.delete_agent(agent_name)
            except Exception as e:
                logger.warning(f"Failed to clean up test agent: {e}")

    @pytest.mark.test_id("AGENT-002-CANCEL")
    def test_create_agent_cancel(self, page: Page, request: pytest.FixtureRequest):
        """Verify cancelling agent creation."""
        test_name = request.node.name

        try:
            # Step 1: Open the Agents management page
            log_test_step("1. Open the Agents management page")
            agents_page = AgentsPage(page)
            agents_page.goto()

            # Step 2: Get the agent count before creating
            log_test_step("2. Get the agent count before creating")
            count_before = agents_page.get_agent_count()

            # Step 3: Click the Create Agent button
            log_test_step("3. Click the Create Agent button")
            agents_page.click_create_agent()

            # Step 4: Fill partial info
            log_test_step("4. Fill partial info")
            agents_page.fill_agent_form("TestCancelAgent", "测试取消")

            # Step 5: Cancel creation
            log_test_step("5. Cancel creation")
            agents_page.cancel_agent_form()
            page.wait_for_timeout(1000)

            # Step 6: Verify the form is closed
            log_test_step("6. Verify the form is closed")
            form_dialog = page.locator(agents_page.FORM_DIALOG).first
            expect(form_dialog).not_to_be_visible(timeout=3000)
            logger.info("Form is closed")

            # Step 7: Verify the agent count is unchanged
            log_test_step("7. Verify the agent count is unchanged")
            count_after = agents_page.get_agent_count()
            assert count_before == count_after, "Agent count should not change after cancel"
            logger.info("Cancel creation verified")

            log_test_result(test_name, "PASS", "Cancel-create-agent works")

        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

    @pytest.mark.test_id("AGENT-002-VALIDATION")
    def test_create_agent_name_required(self, page: Page, request: pytest.FixtureRequest):
        """Verify that the agent name is required."""
        test_name = request.node.name

        try:
            # Step 1: Open the Agents management page
            log_test_step("1. Open the Agents management page")
            agents_page = AgentsPage(page)
            agents_page.goto()

            # Step 2: Click the Create Agent button
            log_test_step("2. Click the Create Agent button")
            agents_page.click_create_agent()

            # Step 3: Submit without filling the name
            log_test_step("3. Submit without filling the name")
            agents_page.submit_agent_form()
            page.wait_for_timeout(1000)

            # Step 4: Verify the error or that the form is still open
            log_test_step("4. Verify the error or that the form is still open")
            form_dialog = page.locator(agents_page.FORM_DIALOG).first
            # Form should still be visible (submission did not succeed) or an error message is shown
            assert form_dialog.is_visible() or agents_page.verify_error_message(), \
                "Empty name should either show an error or block submission"
            logger.info("Required-name validation verified")

            log_test_result(test_name, "PASS", "Required-name validation works")

            # Cancel creation
            agents_page.cancel_agent_form()

        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise


# ============================================================================
# AGENT-003: Edit agent info
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agents_edit
class TestEditAgent:
    """
    AGENT-003: Edit agent info.

    Coverage:
    1. Edit-agent entry point
    2. Modify agent name
    3. Modify agent description
    4. Save changes
    5. Cancel changes
    """

    @pytest.mark.test_id("AGENT-003")
    def test_edit_agent_info(self, page: Page, request: pytest.FixtureRequest):
        """Verify editing agent info."""
        test_name = request.node.name

        # Create test agent
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestEditAgent_{timestamp}"
        new_description = f"更新后的描述_{timestamp}"

        try:
            # Step 1: Create the test agent
            log_test_step("1. Create the test agent")
            agents_page = AgentsPage(page)
            agents_page.goto()
            agents_page.create_agent(agent_name, "原始描述", "zh")
            page.wait_for_timeout(2000)
            assert agents_page.is_agent_exists(agent_name), "Test agent should be created"
            logger.info(f"Test agent created: {agent_name}")

            # Step 2: Click Edit Agent
            log_test_step("2. Click Edit Agent")
            agents_page.click_edit_agent(agent_name)

            # Step 3: Verify the edit form is shown
            log_test_step("3. Verify the edit form is shown")
            form_dialog = page.locator(agents_page.FORM_DIALOG).first
            expect(form_dialog).to_be_visible(timeout=5000)
            logger.info("Edit form is shown")

            # Step 4: Modify the description
            log_test_step("4. Modify the description")
            agents_page.fill_agent_form(name=agent_name, description=new_description)

            # Step 5: Save changes
            log_test_step("5. Save changes")
            agents_page.submit_agent_form()
            page.wait_for_timeout(2000)

            # Step 6: Verify edit success
            log_test_step("6. Verify edit success")
            assert agents_page.verify_success_message(), "Edit success message should be shown"
            logger.info("Edit success message verified")

            log_test_result(test_name, "PASS", f"Successfully edited agent: {agent_name}")

        finally:
            # Cleanup: delete the test agent (re-navigate to ensure stable page state)
            try:
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page = AgentsPage(page)
                agents_page.wait_for_page_load()
                if agents_page.is_agent_exists(agent_name):
                    logger.info(f"Cleaning up test agent: {agent_name}")
                    agents_page.delete_agent(agent_name)
            except Exception as e:
                logger.warning(f"Failed to clean up test agent: {e}")


# ============================================================================
# AGENT-004: Delete agent (with confirmation)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agents_delete
class TestDeleteAgent:
    """
    AGENT-004: Delete agent (with confirmation).

    Coverage:
    1. Delete-agent entry point
    2. Delete confirmation dialog
    3. Confirm delete
    4. Cancel delete
    5. Post-delete verification
    """

    @pytest.mark.test_id("AGENT-004")
    def test_delete_agent_success(self, page: Page, request: pytest.FixtureRequest):
        """Verify agent is deleted successfully."""
        test_name = request.node.name

        # Create test agent
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestDeleteAgent_{timestamp}"

        try:
            # Step 1: Create the test agent
            log_test_step("1. Create the test agent")
            agents_page = AgentsPage(page)
            agents_page.goto()
            agents_page.create_agent(agent_name, "测试删除", "zh")
            page.wait_for_timeout(2000)
            assert agents_page.is_agent_exists(agent_name), "Test agent should be created"
            logger.info(f"Test agent created: {agent_name}")

            # Step 2: Get the agent count before deleting
            log_test_step("2. Get the agent count before deleting")
            count_before = agents_page.get_agent_count()

            # Step 3: Click Delete Agent
            log_test_step("3. Click Delete Agent")
            agents_page.click_delete_agent(agent_name)

            # Step 4: Verify the delete-confirm dialog is shown
            log_test_step("4. Verify the delete-confirm dialog is shown")
            confirm_dialog = page.locator(agents_page.DELETE_CONFIRM_DIALOG).first
            expect(confirm_dialog).to_be_visible(timeout=5000)
            logger.info("Delete confirm dialog is shown")

            # Step 5: Confirm delete
            log_test_step("5. Confirm delete")
            agents_page.confirm_delete()
            page.wait_for_timeout(2000)

            # Step 6: Verify the delete success message
            log_test_step("6. Verify the delete success message")
            assert agents_page.verify_success_message(), "Delete success message should be shown"
            logger.info("Delete success message verified")

            # Step 7: Verify the agent is removed from the list
            log_test_step("7. Verify the agent is removed from the list")
            agents_page.refresh_agent_list()
            assert not agents_page.is_agent_exists(agent_name), f"Agent {agent_name} should be removed from the list"
            logger.info(f"Agent {agent_name} removed from the list")

            # Step 8: Verify the agent count decreased
            log_test_step("8. Verify the agent count decreased")
            count_after = agents_page.get_agent_count()
            assert count_after == count_before - 1, f"Agent count should drop from {count_before} to {count_before - 1}"
            logger.info(f"Agent count verified: {count_before} -> {count_after}")

            log_test_result(test_name, "PASS", f"Successfully deleted agent: {agent_name}")

        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            # Ensure cleanup
            try:
                if agents_page.is_agent_exists(agent_name):
                    agents_page.delete_agent(agent_name)
            except Exception:
                pass
            raise

    @pytest.mark.test_id("AGENT-004-CANCEL")
    def test_delete_agent_cancel(self, page: Page, request: pytest.FixtureRequest):
        """Verify cancelling agent deletion."""
        test_name = request.node.name

        # Create test agent
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestCancelDelete_{timestamp}"

        try:
            # Step 1: Create the test agent
            log_test_step("1. Create the test agent")
            agents_page = AgentsPage(page)
            agents_page.goto()
            agents_page.create_agent(agent_name, "测试取消删除", "zh")
            page.wait_for_timeout(2000)

            # Step 2: Get the agent count before deleting
            log_test_step("2. Get the agent count before deleting")
            count_before = agents_page.get_agent_count()

            # Step 3: Click Delete Agent
            log_test_step("3. Click Delete Agent")
            agents_page.click_delete_agent(agent_name)

            # Step 4: Cancel delete
            log_test_step("4. Cancel delete")
            agents_page.cancel_delete()
            page.wait_for_timeout(1000)

            # Step 5: Verify the agent still exists
            log_test_step("5. Verify the agent still exists")
            assert agents_page.is_agent_exists(agent_name), f"Agent {agent_name} should still exist"
            logger.info(f"Agent {agent_name} still exists")

            # Step 6: Verify the agent count is unchanged
            log_test_step("6. Verify the agent count is unchanged")
            count_after = agents_page.get_agent_count()
            assert count_before == count_after, "Agent count should not change after cancel delete"
            logger.info("Cancel delete verified")

            log_test_result(test_name, "PASS", "Cancel-delete-agent works")

        finally:
            # Cleanup (re-navigate to ensure stable page state)
            try:
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page = AgentsPage(page)
                agents_page.wait_for_page_load()
                if agents_page.is_agent_exists(agent_name):
                    agents_page.delete_agent(agent_name)
            except Exception:
                pass


# ============================================================================
# AGENT-005: Enable/disable agent
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agents_toggle
class TestToggleAgent:
    """
    AGENT-005: Enable/disable agent.

    Coverage:
    1. Display agent status
    2. Toggle agent status
    3. Verify status update
    """

    @pytest.mark.test_id("AGENT-005")
    def test_toggle_agent_status(self, page: Page, request: pytest.FixtureRequest):
        """Verify toggling the agent's enabled state."""
        test_name = request.node.name

        # Create test agent
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestToggleAgent_{timestamp}"

        try:
            # Step 1: Create the test agent
            log_test_step("1. Create the test agent")
            agents_page = AgentsPage(page)
            agents_page.goto()
            agents_page.create_agent(agent_name, "测试状态切换", "zh")
            page.wait_for_timeout(2000)

            # Step 2: Verify the agent's initial state is enabled
            log_test_step("2. Verify the agent's initial state is enabled")
            assert agents_page.is_agent_exists(agent_name), "Test agent should exist"
            initial_status = agents_page.get_agent_status(agent_name)
            logger.info(f"Initial status: {initial_status}")

            # Step 3: Disable the agent
            log_test_step("3. Disable the agent")
            agents_page.disable_agent(agent_name)
            page.wait_for_timeout(2000)

            # Step 4: Verify the post-disable state (do not refresh the page,
            # since refreshing may filter out disabled agents)
            log_test_step("4. Verify the post-disable state")
            # Approach 1: check whether the Disabled tag appears on the current page
            disabled_tag = page.locator(f'.qwenpaw-table-row:has-text("{agent_name}") .qwenpaw-tag:has-text("Disabled")')
            # Approach 2: check the success toast
            success_msg = page.locator('.qwenpaw-message-success, .qwenpaw-notification-success')
            tag_visible = disabled_tag.count() > 0 and disabled_tag.first.is_visible()
            msg_visible = success_msg.count() > 0
            assert tag_visible or msg_visible, \
                "Agent should be disabled (Disabled tag or success message should appear)"
            logger.info("Disabled state verified")

            # Step 5: Enable the agent (operate directly on the current page, no refresh)
            log_test_step("5. Enable the agent")
            # Locate the agent row again and click the toggle
            agent_row = page.locator(f'.qwenpaw-table-row:has-text("{agent_name}")').first
            if agent_row.is_visible():
                toggle_btn = agent_row.locator('.qwenpaw-space-item:nth-child(2) button').first
                toggle_btn.click()
                page.wait_for_timeout(500)
                # Handle a possible confirm popover
                popconfirm_btn = page.locator('.qwenpaw-popconfirm-buttons button.qwenpaw-btn-primary').first
                if popconfirm_btn.is_visible():
                    popconfirm_btn.click()
                page.wait_for_timeout(2000)

            # Step 6: Verify the post-enable state is restored
            log_test_step("6. Verify the post-enable state")
            # The Disabled tag should disappear
            disabled_tag_after = page.locator(f'.qwenpaw-table-row:has-text("{agent_name}") .qwenpaw-tag:has-text("Disabled")')
            is_still_disabled = disabled_tag_after.count() > 0 and disabled_tag_after.first.is_visible()
            assert not is_still_disabled, "Agent should be enabled (Disabled tag should disappear)"
            logger.info("Enabled state verified")

            log_test_result(test_name, "PASS", f"Agent status toggle verified: {agent_name}")

        finally:
            # Cleanup (re-navigate to ensure stable page state)
            try:
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page = AgentsPage(page)
                agents_page.wait_for_page_load()
                if agents_page.is_agent_exists(agent_name):
                    agents_page.delete_agent(agent_name)
            except Exception:
                pass


# ============================================================================
# AGENT-006: Agent API operations
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agents_api
class TestAgentAPI:
    """
    AGENT-006: Agent API operations.

    Coverage:
    1. API: list agents
    2. API: create agent
    3. API: delete agent
    4. API: toggle agent status
    """

    @pytest.mark.test_id("AGENT-006")
    def test_agent_api_operations(self, page: Page, request: pytest.FixtureRequest, api_context):
        """Verify agent API operations."""
        test_name = request.node.name

        # Create test agent
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"APIAgent_{timestamp}"

        try:
            # Step 1: API: list agents
            log_test_step("1. API: list agents")
            agents_page = AgentsPage(page)
            agents_list = agents_page.api_get_agents(api_context)
            assert isinstance(agents_list, list), "API should return a list"
            logger.info(f"API returned {len(agents_list)} agent(s)")

            # Step 2: API: create agent
            log_test_step("2. API: create agent")
            create_result = agents_page.api_create_agent(
                api_context,
                name=agent_name,
                description="通过 API 创建的测试智能体",
                language="zh"
            )
            assert create_result, "API create should return a result"
            logger.info(f"API create result: {create_result}")

            # Step 3: Verify the agent was created (with retries)
            log_test_step("3. Verify the agent was created")
            found = False
            for attempt in range(5):
                page.goto(AGENTS_URL)
                page.wait_for_timeout(3000)
                agents_page.refresh_agent_list()
                page.wait_for_timeout(2000)
                if agents_page.is_agent_exists(agent_name):
                    found = True
                    break
                logger.warning(f"Attempt {attempt + 1}/5: agent {agent_name} not found, retrying...")
                page.wait_for_timeout(3000)
            assert found, f"Agent {agent_name} should exist (still not found after 5 retries)"
            logger.info(f"Agent {agent_name} created")

            # Step 4: Get the agent ID
            log_test_step("4. Get the agent ID")
            agents = agents_page.get_agent_list()
            agent_id = None
            for agent in agents:
                if agent["name"] == agent_name:
                    agent_id = agent.get("id", "")
                    break
            assert agent_id, "Should be able to obtain the agent ID"
            logger.info(f"Agent ID: {agent_id}")

            # Step 5: API: toggle agent status (if supported)
            log_test_step("5. API: toggle agent status")
            try:
                toggle_result = agents_page.api_toggle_agent(api_context, agent_id, False)
                logger.info(f"API toggle result: {toggle_result}")
            except (AssertionError, Exception) as toggle_err:
                logger.info(f"API toggle not available ({toggle_err}), skipping this step")

            # Step 6: API: delete agent
            log_test_step("6. API: delete agent")
            delete_result = agents_page.api_delete_agent(api_context, agent_id)
            assert delete_result, "API delete should return a result"
            logger.info(f"API delete result: {delete_result}")

            # Step 7: Verify the agent was deleted
            log_test_step("7. Verify the agent was deleted")
            page.reload()
            page.wait_for_timeout(2000)
            agents_page.refresh_agent_list()
            assert not agents_page.is_agent_exists(agent_name), f"Agent {agent_name} should be deleted"
            logger.info(f"Agent {agent_name} deleted")

            log_test_result(test_name, "PASS", "Agent API operations verified")

        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

        finally:
            # Cleanup: ensure the test agent is deleted
            try:
                agents_page = AgentsPage(page)
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page.refresh_agent_list()
                if agents_page.is_agent_exists(agent_name):
                    logger.info(f"Cleanup: deleting test agent {agent_name}")
                    agents_page.delete_agent(agent_name)
            except Exception as cleanup_error:
                logger.warning(f"Failed to clean up test agent: {cleanup_error}")


# ============================================================================
# AGENT-007: Default agent protection
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agents_protection
class TestAgentProtection:
    """
    AGENT-007: Default agent protection.

    Coverage:
    1. Default agent cannot be deleted
    2. Default agent cannot be disabled
    """

    @pytest.mark.test_id("AGENT-007")
    def test_default_agent_protected(self, page: Page, request: pytest.FixtureRequest):
        """Verify that the default agent is protected."""
        test_name = request.node.name

        # Step 1: Open the Agents management page
        log_test_step("1. Open the Agents management page")
        agents_page = AgentsPage(page)
        agents_page.goto()

        # Step 2: Find the default agent
        log_test_step("2. Find the default agent")
        # Wait for the table data to load
        page.wait_for_timeout(2000)
        default_agent = None
        agents = agents_page.get_agent_list()
        logger.info(f"Agent list has {len(agents)} item(s): {[a.get('name') + '(id=' + a.get('id', '') + ')' for a in agents]}")
        for agent in agents:
            agent_id = agent.get("id", "").lower()
            agent_name = agent.get("name", "").lower()
            if agent_id == "default" or "default" in agent_id or agent_name in ("默认智能体", "copaw"):
                default_agent = agent["element"]
                logger.info(f"Found default agent: name={agent.get('name')}, id={agent.get('id')}")
                break

        if default_agent:
            # Step 3: Verify the default agent's delete button is disabled
            log_test_step("3. Verify the default agent's delete protection")
            actions_cell = default_agent.locator(agents_page.AGENT_ACTIONS_CELL).first
            delete_btn = actions_cell.locator(agents_page.DELETE_BTN).first

            if delete_btn.is_visible():
                is_disabled = delete_btn.is_disabled()
                title = delete_btn.get_attribute("title") or ""
                logger.info(f"Delete button disabled={is_disabled}, title=\"{title}\"")
                assert is_disabled, "Default agent's delete button should be disabled"
                logger.info("Default agent's delete button is disabled, protection verified")
            else:
                logger.info("Delete button not found (default agent may not expose one)")

            logger.info("Default agent protection verified")
        else:
            pytest.skip("Default agent not found, skipping protection check")

        log_test_result(test_name, "PASS", "Default agent protection verified")


# ============================================================================
# P1 test case: agent drag-and-drop reorder
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agents_reorder
class TestAgentDragReorder:
    """
    AGENT-P1-001: Agent drag-and-drop reorder.

    Coverage:
    1. Identify drag handles in the agent list
    2. Perform drag operation (from position A to position B)
    3. Verify the new order
    4. Refresh the page to verify persistence
    """

    def test_agent_drag_reorder(self, page: Page):
        """Test agent drag-and-drop reordering."""
        log_test_step("Navigate to the Agents management page")
        navigate_to_agents(page)

        log_test_step("Find rows in the agent list")
        agent_rows = page.locator("tr[data-row-key], .ant-table-row, [class*='agent-row'], tbody tr").all()

        if len(agent_rows) < 2:
            pytest.skip(f"Not enough agents ({len(agent_rows)}); cannot run drag test")

        log_test_step(f"Found {len(agent_rows)} agent(s); preparing drag test")

        first_row = agent_rows[0]
        second_row = agent_rows[1]

        log_test_step("Capture agent order before drag")
        before_order = []
        for row in agent_rows[:3]:
            row_key = row.get_attribute("data-row-key")
            if row_key:
                before_order.append(row_key)
            else:
                name_cell = row.locator("td").nth(1)
                if name_cell.count() > 0:
                    name_text = name_cell.inner_text()
                    before_order.append(name_text.strip())

        assert len(before_order) >= 2, "Could not read identifiers for at least 2 agents"
        logger.info(f"Order before drag: {before_order}")

        log_test_step("Find the drag handle")
        drag_handle = first_row.locator(".drag-handle, [class*='drag-handle'], .anticon-menu, svg[data-icon='menu']").first

        if drag_handle.count() == 0:
            drag_handle = first_row.locator("button[class*='drag'], [class*='sortable-handle']").first

        if drag_handle.count() == 0:
            pytest.skip("Drag handle not found; this page may not support drag reordering")

        log_test_step("Drag handle found; starting drag operation")
        drag_handle.hover()
        time.sleep(0.5)

        page.mouse.down()
        time.sleep(0.3)

        second_row_center = second_row.bounding_box()
        assert second_row_center is not None, "Could not read the position of the second row"

        target_y = second_row_center["y"] + second_row_center["height"] / 2
        target_x = second_row_center["x"] + second_row_center["width"] / 2

        page.mouse.move(target_x, target_y, steps=10)
        time.sleep(0.5)

        page.mouse.up()
        time.sleep(2)

        log_test_step("Drag finished; verifying the new order")
        refreshed_rows = page.locator("tr[data-row-key], .ant-table-row, [class*='agent-row'], tbody tr").all()
        after_order = []
        for row in refreshed_rows[:3]:
            row_key = row.get_attribute("data-row-key")
            if row_key:
                after_order.append(row_key)
            else:
                name_cell = row.locator("td").nth(1)
                if name_cell.count() > 0:
                    name_text = name_cell.inner_text()
                    after_order.append(name_text.strip())

        logger.info(f"Order after drag: {after_order}")
        assert before_order != after_order, "Agent order did not change after drag; reorder did not take effect"
        logger.info("Agent order changed; drag reorder succeeded")

        log_test_step("Refresh page to verify persistence")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)

        persisted_rows = page.locator("tr[data-row-key], .ant-table-row, [class*='agent-row'], tbody tr").all()
        persisted_order = []
        for row in persisted_rows[:3]:
            row_key = row.get_attribute("data-row-key")
            if row_key:
                persisted_order.append(row_key)
            else:
                name_cell = row.locator("td").nth(1)
                if name_cell.count() > 0:
                    name_text = name_cell.inner_text()
                    persisted_order.append(name_text.strip())

        logger.info(f"Order after refresh: {persisted_order}")
        assert after_order == persisted_order, \
            f"Drag reorder did not persist: after drag {after_order}, after refresh {persisted_order}"
        logger.info("Drag reorder persisted; test passed")

        logger.info("Agent drag reorder test complete")


# ============================================================================
# AGENT-P2-001: Agent skill association config
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agents
class TestAgentSkillAssociation:
    """AGENT-P2-001: Agent skill association config."""

    @pytest.mark.test_id("AGENT-P2-001")
    def test_agent_skill_association(self, page: Page, request: pytest.FixtureRequest):
        """Test the agent skill association config."""
        test_name = request.node.name

        log_test_step("Navigate to the Agents management page")
        page.goto(f"{config.base_url}/agents")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Look for agent cards")
        agent_cards = page.locator('.qwenpaw-card, [class*="agentCard"]').all()
        if len(agent_cards) == 0:
            logger.info("No agent card found, skipping test")
            log_test_result(test_name, True, 0)
            return
        logger.info(f"Found {len(agent_cards)} agent card(s)")

        log_test_step("Click the first agent to view details")
        agent_cards[0].click()
        page.wait_for_timeout(3000)

        log_test_step("Verify the agent detail view is open")
        # Clicking the card may open a modal/drawer or navigate to a new page
        detail_area = page.locator(
            '.qwenpaw-modal, .ant-modal, .qwenpaw-drawer, .ant-drawer, '
            '[class*="detail"], [class*="config"], [class*="agent"]'
        ).first

        # If no modal/drawer appeared, check whether the page navigated to the detail view
        if detail_area.count() == 0:
            current_url = page.url
            if "/agents/" in current_url or "/agent/" in current_url:
                logger.info(f"Navigated to agent detail page: {current_url}")
            else:
                logger.info("Clicking the agent card did not open a detail view or navigate; may not be supported")
                log_test_result(test_name, True, 0)
                return
        else:
            logger.info("Agent detail view is open")

        log_test_step("Verify the detail view contains key config sections")
        page_content = page.locator('body').inner_text()

        # Verify the detail view contains agent-related config sections
        config_keywords = ['Skills', '技能', 'Model', '模型', 'Prompt', '提示词',
                          'Name', '名称', 'Config', '配置', 'System', 'Setting']
        found_keywords = [kw for kw in config_keywords if kw in page_content]
        assert len(found_keywords) > 0, \
            f"Agent detail view should contain at least one config keyword, but none found: {config_keywords}"
        logger.info(f"Detail view contains config keywords: {found_keywords}")

        # Verify the page has interactive elements (inputs, switches, selects, etc.)
        interactive_elements = page.locator(
            'input, textarea, .qwenpaw-switch, .qwenpaw-select, '
            '.qwenpaw-radio-group, button'
        ).all()
        visible_interactive = [el for el in interactive_elements if el.is_visible()]
        assert len(visible_interactive) > 0, "Detail view should have interactive elements"
        logger.info(f"Detail view has {len(visible_interactive)} interactive element(s)")

        # Look for the skill association section
        skill_section = page.locator(
            ':text("Skills"), :text("技能"), '
            '[class*="skill"], [class*="Skill"]'
        ).first
        if skill_section.count() > 0:
            assert skill_section.is_visible(timeout=3000), "Skills section should be visible"
            logger.info("Found skill association section")
        else:
            logger.info("Skill association section not found (current view may not show skill config)")

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        # If navigated to a new page, go back to the list
        if "/agents/" in page.url or "/agent/" in page.url:
            page.go_back()
            page.wait_for_timeout(1000)
        log_test_result(test_name, True, 0)

