# -*- coding: utf-8 -*-
"""
QwenPaw Agents management page object.

Wraps all interactions on the agent management page and exposes business-level
methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config
from utils.helpers import log_test_step


logger = logging.getLogger(__name__)


class AgentsPage(BasePage):
    """
    Agents management page object.

    Wraps all user interactions on the agent management page:
    - View agent list
    - Create agent
    - Edit agent
    - Delete agent
    - Enable/disable agent
    - Reorder agents
    - Manage agent files
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/agents"

    # ========== Selector definitions ==========

    # Page title and breadcrumb
    PAGE_HEADER = 'button:has-text("Create Agent"), span[class*="breadcrumbCurrent"]:has-text("智能体")'
    BREADCRUMB = 'span[class*="breadcrumbCurrent"]:has-text("智能体")'

    # Agent list (table structure)
    AGENT_TABLE = '.qwenpaw-table'
    AGENT_LIST = '.qwenpaw-table-tbody'
    AGENT_ITEM = '.qwenpaw-table-tbody tr.qwenpaw-table-row'
    # Table column order: drag handle (1) | Name (2) | ID (3) | Description (4) | Workspace (5) | Model (6) | Actions (7)
    AGENT_NAME_CELL = 'td.qwenpaw-table-cell:nth-child(2)'
    AGENT_ID_CELL = 'td.qwenpaw-table-cell:nth-child(3)'
    AGENT_DESC_CELL = 'td.qwenpaw-table-cell:nth-child(4)'
    AGENT_WORKSPACE_CELL = 'td.qwenpaw-table-cell:nth-child(5)'
    AGENT_MODEL_CELL = 'td.qwenpaw-table-cell:nth-child(6)'
    AGENT_ACTIONS_CELL = 'td.qwenpaw-table-cell:nth-child(7)'
    AGENT_STATUS = '.qwenpaw-tag'

    # Action buttons
    CREATE_AGENT_BTN = 'button:has-text("创建智能体"), button:has-text("Create Agent"), .qwenpaw-btn-primary'
    # Inline action buttons in a table row (3 icon buttons: edit, toggle, delete)
    # Locate via Ant Design icon class names (anticon-edit / anticon-delete), fallback to nth-child
    EDIT_BTN = 'button:has(.anticon-edit), .qwenpaw-space-item:nth-child(1) button'
    TOGGLE_BTN = '.qwenpaw-space-item:nth-child(2) button'
    DELETE_BTN = 'button.qwenpaw-btn-dangerous, button:has(.anticon-delete)'
    ENABLE_TOGGLE = '.qwenpaw-space-item:nth-child(2) button'
    REFRESH_BTN = 'button:has(.anticon-reload), button:has(.spark-icon-spark-refresh-line)'

    # Create/edit form
    FORM_DIALOG = '.qwenpaw-modal, [role="dialog"]'
    FORM_TITLE = '.qwenpaw-modal-header-title, .qwenpaw-spark-title'
    FORM_NAME_INPUT = 'input#name, input[placeholder*="My Agent"]'
    FORM_DESC_INPUT = 'textarea#description, textarea[placeholder*="describe"]'
    FORM_WORKSPACE_INPUT = 'input#workspace_dir'
    FORM_SKILLS_SELECT = '.qwenpaw-form-item:has-text("Skills") .qwenpaw-select-selector'
    FORM_SUBMIT_BTN = '.qwenpaw-modal-footer button.qwenpaw-btn-primary, button:has-text("保存"), button:has-text("Save")'
    FORM_CANCEL_BTN = '.qwenpaw-modal-footer button.qwenpaw-btn-default, button:has-text("取消"), button:has-text("Cancel")'

    # Delete confirmation (Popconfirm bubble)
    DELETE_CONFIRM_DIALOG = '.qwenpaw-popconfirm'
    DELETE_CONFIRM_BTN = '.qwenpaw-popconfirm-buttons button.qwenpaw-btn-primary'
    DELETE_CANCEL_BTN = '.qwenpaw-popconfirm-buttons button.qwenpaw-btn-default'

    # Agent detail
    AGENT_DETAIL_TAB = '.qwenpaw-tabs-tab-btn'
    AGENT_DETAIL_PANEL = '.qwenpaw-tabs-tabpane-active'
    AGENT_FILES_LIST = '[class*=fileList], .qwenpaw-list'
    AGENT_FILE_ITEM = '[class*=fileItem], .qwenpaw-list-item'

    # Empty state
    EMPTY_STATE = '.qwenpaw-empty, [class*=empty]'
    EMPTY_STATE_TEXT = '.qwenpaw-empty-description, .qwenpaw-empty-desc'

    # Toast messages (inherited from BasePage, no redefinition needed)

    # ========== Initialization ==========

    def __init__(self, page: Page):
        super().__init__(page)

    # ========== Navigation and basic operations ==========

    def goto(self) -> "AgentsPage":
        """Navigate to the agents management page."""
        logger.info("Navigating to agents management page")
        self.page.goto(self.PAGE_URL)
        self.wait_for_page_load()
        return self

    def wait_for_page_load(self, timeout: int = 10000):
        """Wait for the page to finish loading."""
        try:
            self.page.locator(self.PAGE_HEADER).first.wait_for(state="visible", timeout=timeout)
            logger.info("Agents page loaded successfully")
        except TimeoutError:
            # Fall back to other possible titles
            self.page.locator(self.BREADCRUMB).first.wait_for(state="visible", timeout=timeout)
            logger.info("Agents page loaded (breadcrumb found)")
        return self

    # ========== Agent list operations ==========

    def get_agent_list(self) -> List[Dict]:
        """
        Return the agent list (table structure).

        Returns:
            List of agent metadata dicts.
        """
        logger.info("Getting agent list")
        agent_rows = self.page.locator(self.AGENT_ITEM).all()

        agents = []
        for row in agent_rows:
            try:
                name_cell = row.locator(self.AGENT_NAME_CELL).first
                name_text = name_cell.inner_text() if name_cell.is_visible() else ""
                # The name cell may contain a "Disabled" tag that needs to be stripped
                status_tag = name_cell.locator(self.AGENT_STATUS).first
                status = status_tag.inner_text().strip() if status_tag.is_visible() else ""
                # Remove the status tag text from the raw name text
                clean_name = name_text.replace(status, "").strip() if status else name_text.strip()

                id_cell = row.locator(self.AGENT_ID_CELL).first
                agent_id = id_cell.inner_text().strip() if id_cell.is_visible() else ""

                desc_cell = row.locator(self.AGENT_DESC_CELL).first
                desc = desc_cell.inner_text().strip() if desc_cell.is_visible() else ""

                agents.append({
                    "name": clean_name,
                    "id": agent_id,
                    "description": desc[:200],
                    "status": status,
                    "element": row
                })
            except Exception as e:
                logger.debug(f"Failed to parse agent row: {e}")
                continue

        logger.info(f"Found {len(agents)} agents")
        return agents

    def get_agent_count(self) -> int:
        """Return the agent count (waits for table data to load)."""
        # Wait for at least one row to appear so we do not return 0 before the table renders
        try:
            self.page.locator(self.AGENT_ITEM).first.wait_for(state="visible", timeout=5000)
        except Exception:
            logger.debug("No agent rows found within timeout, table may be empty")
        count = self.page.locator(self.AGENT_ITEM).count()
        logger.info(f"Agent count: {count}")
        return count

    def is_agent_exists(self, agent_name: str) -> bool:
        """Return whether the given agent exists."""
        agents = self.get_agent_list()
        return any(agent["name"] == agent_name for agent in agents)

    def find_agent_by_name(self, agent_name: str) -> Optional[Locator]:
        """Find an agent row by name."""
        agents = self.get_agent_list()
        for agent in agents:
            if agent["name"] == agent_name:
                return agent["element"]
        return None

    def refresh_agent_list(self) -> "AgentsPage":
        """Refresh the agent list."""
        logger.info("Refreshing agent list")
        refresh_btn = self.page.locator(self.REFRESH_BTN).first
        if refresh_btn.is_visible():
            refresh_btn.click()
            self.wait(1000)
        else:
            self.page.reload()
            self.wait_for_page_load()
        return self

    # ========== Create agent ==========

    def click_create_agent(self) -> "AgentsPage":
        """Click the create agent button."""
        logger.info("Clicking create agent button")
        create_btn = self.page.locator(self.CREATE_AGENT_BTN).first
        expect(create_btn).to_be_visible(timeout=5000)
        create_btn.click()
        self.wait(500)
        return self

    def fill_agent_form(self, name: str, description: str = "", language: str = "zh") -> "AgentsPage":
        """
        Fill in the agent form.

        Args:
            name: Agent name.
            description: Agent description.
            language: Language (kept for parameter compatibility, the form has no language picker).
        """
        logger.info(f"Filling agent form: name={name}, description={description}")

        # Wait for the modal to load
        self.page.locator(self.FORM_DIALOG).first.wait_for(state="visible", timeout=5000)
        self.wait(500)

        # Fill in the name
        name_input = self.page.locator(self.FORM_NAME_INPUT).first
        name_input.wait_for(state="visible", timeout=5000)
        name_input.fill(name)

        # Fill in the description
        if description:
            desc_input = self.page.locator(self.FORM_DESC_INPUT).first
            if desc_input.is_visible():
                desc_input.fill(description)

        return self

    def submit_agent_form(self) -> "AgentsPage":
        """Submit the agent form."""
        logger.info("Submitting agent form")
        submit_btn = self.page.locator(self.FORM_SUBMIT_BTN).first
        expect(submit_btn).to_be_visible(timeout=5000)
        submit_btn.click()
        self.wait(1000)
        return self

    def cancel_agent_form(self) -> "AgentsPage":
        """Cancel the agent form."""
        logger.info("Canceling agent form")
        cancel_btn = self.page.locator(self.FORM_CANCEL_BTN).first
        if cancel_btn.is_visible():
            cancel_btn.click()
            self.wait(500)
        return self

    def create_agent(self, name: str, description: str = "", language: str = "zh") -> "AgentsPage":
        """
        Create an agent (full flow).

        Args:
            name: Agent name.
            description: Agent description.
            language: Language.
        """
        log_test_step(f"Create agent: {name}")
        self.click_create_agent()
        self.fill_agent_form(name, description, language)
        self.submit_agent_form()
        return self

    # ========== Edit agent ==========

    def click_edit_agent(self, agent_name: str) -> "AgentsPage":
        """
        Click edit for the given agent.

        Args:
            agent_name: Agent name.
        """
        logger.info(f"Clicking edit for agent: {agent_name}")
        agent_row = self.find_agent_by_name(agent_name)
        if agent_row:
            actions_cell = agent_row.locator(self.AGENT_ACTIONS_CELL).first
            edit_btn = actions_cell.locator(self.EDIT_BTN).first
            edit_btn.click()
            self.wait(500)
        else:
            raise ValueError(f"Agent not found: {agent_name}")
        return self

    def update_agent(self, agent_name: str, new_name: str = None, new_description: str = None) -> "AgentsPage":
        """
        Update agent details.

        Args:
            agent_name: Existing agent name.
            new_name: New name (optional).
            new_description: New description (optional).
        """
        log_test_step(f"Update agent: {agent_name}")
        self.click_edit_agent(agent_name)

        if new_name:
            name_input = self.page.locator(self.FORM_NAME_INPUT).first
            name_input.fill(new_name)

        if new_description:
            desc_input = self.page.locator(self.FORM_DESC_INPUT).first
            desc_input.fill(new_description)

        self.submit_agent_form()
        return self

    # ========== Delete agent ==========

    def click_delete_agent(self, agent_name: str) -> "AgentsPage":
        """
        Click delete for the given agent.

        Args:
            agent_name: Agent name.
        """
        logger.info(f"Clicking delete for agent: {agent_name}")
        agent_row = self.find_agent_by_name(agent_name)
        if agent_row:
            actions_cell = agent_row.locator(self.AGENT_ACTIONS_CELL).first
            delete_btn = actions_cell.locator(self.DELETE_BTN).first
            delete_btn.click()
            self.wait(500)
        else:
            raise ValueError(f"Agent not found: {agent_name}")
        return self

    def confirm_delete(self) -> "AgentsPage":
        """Confirm deletion (Popconfirm bubble)."""
        logger.info("Confirming delete")
        # Wait for the Popconfirm to appear
        self.page.locator(self.DELETE_CONFIRM_DIALOG).first.wait_for(state="visible", timeout=5000)
        confirm_btn = self.page.locator(self.DELETE_CONFIRM_BTN).first
        confirm_btn.click()
        self.wait(1000)
        return self

    def cancel_delete(self) -> "AgentsPage":
        """Cancel deletion (Popconfirm bubble)."""
        logger.info("Canceling delete")
        popconfirm = self.page.locator(self.DELETE_CONFIRM_DIALOG).first
        if popconfirm.is_visible():
            cancel_btn = self.page.locator(self.DELETE_CANCEL_BTN).first
            cancel_btn.click()
            self.wait(500)
        return self

    def delete_agent(self, agent_name: str) -> "AgentsPage":
        """
        Delete an agent (full flow).

        Args:
            agent_name: Agent name.
        """
        log_test_step(f"Delete agent: {agent_name}")
        self.click_delete_agent(agent_name)
        self.confirm_delete()
        return self

    # ========== Enable/disable agent ==========

    def toggle_agent_status(self, agent_name: str) -> "AgentsPage":
        """
        Toggle the agent enabled status (clicks the second Actions button and confirms the Popconfirm).

        Args:
            agent_name: Agent name.
        """
        logger.info(f"Toggling agent status: {agent_name}")
        agent_row = self.find_agent_by_name(agent_name)
        if agent_row:
            actions_cell = agent_row.locator(self.AGENT_ACTIONS_CELL).first
            toggle_btn = actions_cell.locator(self.TOGGLE_BTN).first
            toggle_btn.click()
            self.wait(500)
            # The toggle action triggers a Popconfirm that must be confirmed
            popconfirm = self.page.locator(self.DELETE_CONFIRM_DIALOG).first
            if popconfirm.is_visible():
                confirm_btn = self.page.locator(self.DELETE_CONFIRM_BTN).first
                confirm_btn.click()
                logger.info("Toggle popconfirm confirmed")
            self.wait(1000)
        else:
            raise ValueError(f"Agent not found: {agent_name}")
        return self

    def enable_agent(self, agent_name: str) -> "AgentsPage":
        """Enable an agent."""
        log_test_step(f"Enable agent: {agent_name}")
        return self.toggle_agent_status(agent_name)

    def disable_agent(self, agent_name: str) -> "AgentsPage":
        """Disable an agent."""
        log_test_step(f"Disable agent: {agent_name}")
        return self.toggle_agent_status(agent_name)

    def get_agent_status(self, agent_name: str) -> str:
        """
        Return the agent status.

        Args:
            agent_name: Agent name.

        Returns:
            Status text (e.g. "Disabled" or empty string when enabled).
        """
        agent_row = self.find_agent_by_name(agent_name)
        if agent_row:
            name_cell = agent_row.locator(self.AGENT_NAME_CELL).first
            status_tag = name_cell.locator(self.AGENT_STATUS).first
            if status_tag.is_visible():
                return status_tag.inner_text().strip()
        return ""

    def is_agent_enabled(self, agent_name: str) -> bool:
        """Return whether the agent is enabled (no Disabled tag means enabled)."""
        status = self.get_agent_status(agent_name)
        return status == "" or "Enabled" in status or "active" in status.lower()

    # ========== Agent file management ==========

    def open_agent_files(self, agent_name: str) -> "AgentsPage":
        """
        Open the agent files panel.

        Args:
            agent_name: Agent name.
        """
        logger.info(f"Opening agent files: {agent_name}")
        agent_item = self.find_agent_by_name(agent_name)
        if agent_item:
            agent_item.click()
            self.wait(1000)
        else:
            raise ValueError(f"Agent not found: {agent_name}")
        return self

    def get_agent_files(self) -> List[str]:
        """Return the agent file list."""
        logger.info("Getting agent files")
        file_items = self.page.locator(self.AGENT_FILE_ITEM).all()
        files = [item.inner_text().strip() for item in file_items]
        logger.info(f"Found {len(files)} files")
        return files

    # ========== Verification and assertions ==========

    def verify_agent_created(self, agent_name: str) -> bool:
        """Verify the agent was created."""
        return self.is_agent_exists(agent_name)

    def verify_agent_deleted(self, agent_name: str) -> bool:
        """Verify the agent was deleted."""
        return not self.is_agent_exists(agent_name)

    def verify_success_message(self, message_contains: str = "") -> bool:
        """Verify the success message."""
        try:
            msg = self.page.locator(self.SUCCESS_MESSAGE).first
            msg.wait_for(state="visible", timeout=3000)
            if message_contains:
                text = msg.inner_text()
                return message_contains in text
            return True
        except TimeoutError:
            return False

    def verify_error_message(self, message_contains: str = "") -> bool:
        """Verify the error message."""
        try:
            msg = self.page.locator(self.ERROR_MESSAGE).first
            msg.wait_for(state="visible", timeout=3000)
            if message_contains:
                text = msg.inner_text()
                return message_contains in text
            return True
        except TimeoutError:
            return False

    def verify_empty_state(self) -> bool:
        """Verify the empty state is shown."""
        try:
            empty = self.page.locator(self.EMPTY_STATE).first
            return empty.is_visible()
        except Exception:
            return False

    # ========== API helper methods ==========

    def api_get_agents(self, api_context) -> List[Dict]:
        """
        Fetch the agent list via API.

        Args:
            api_context: API request context.

        Returns:
            Agent list.
        """
        from utils.helpers import api_get
        response = api_get(api_context, "/api/agents")
        return response.get("agents", [])

    def api_create_agent(self, api_context, name: str, description: str = "", language: str = "zh") -> Dict:
        """
        Create an agent via API.

        Args:
            api_context: API request context.
            name: Agent name.
            description: Agent description.
            language: Language.

        Returns:
            Creation result.
        """
        from utils.helpers import api_post
        data = {
            "name": name,
            "description": description,
            "language": language
        }
        return api_post(api_context, "/api/agents", data)

    def api_delete_agent(self, api_context, agent_id: str) -> Dict:
        """
        Delete an agent via API.

        Args:
            api_context: API request context.
            agent_id: Agent ID.

        Returns:
            Deletion result.
        """
        from utils.helpers import api_delete
        return api_delete(api_context, f"/api/agents/{agent_id}")

    def api_toggle_agent(self, api_context, agent_id: str, enabled: bool) -> Dict:
        """
        Toggle agent status via API.

        Args:
            api_context: API request context.
            agent_id: Agent ID.
            enabled: Target enabled state.

        Returns:
            Toggle result.
        """
        from utils.helpers import api_post
        return api_post(api_context, f"/api/agents/{agent_id}/toggle", {"enabled": enabled})
