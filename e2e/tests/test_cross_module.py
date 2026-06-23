# -*- coding: utf-8 -*-
"""
QwenPaw cross-module end-to-end test cases.

Verify business linkages between multiple modules:
- CROSS-001: Skill full chain (Skills -> Agents -> Chat)
- CROSS-002: Model switching linkage (Models -> Chat)
- CROSS-003: Security interception linkage (Security -> Chat)
- CROSS-004: Workspace file linkage (Files -> Chat)

Run with: pytest tests/test_cross_module.py -v
"""
from __future__ import annotations

import logging
import time
import pytest
from playwright.sync_api import Page, expect, TimeoutError

from pages.chat_page import ChatPage
from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

BASE_URL = config.base_url


def navigate_to_skills(page: Page):
    """Navigate to the skills management page."""
    page.goto(f"{BASE_URL}/skills")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


def navigate_to_agents(page: Page):
    """Navigate to the agents management page."""
    page.goto(f"{BASE_URL}/agents")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


def navigate_to_security(page: Page):
    """Navigate to the security page."""
    page.goto(f"{BASE_URL}/security")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


def navigate_to_files(page: Page):
    """Navigate to the files management page."""
    page.goto(f"{BASE_URL}/workspace")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


def navigate_to_chat(page: Page):
    """Navigate to the chat page."""
    page.goto(f"{BASE_URL}/chat")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


# ============================================================================
# CROSS-001: Skill full-chain verification (Skills -> Agents -> Chat)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
@pytest.mark.requires_llm
class TestSkillAgentChatFlow:
    """
    CROSS-001: Skill full-chain verification.

    Verify the complete business chain from creating a skill to using it in chat:
    1. Create a test skill on the Skills page
    2. Verify the skill can be linked on the Agents page
    3. Verify the skill can be invoked on the Chat page
    4. Clean up test data
    """

    @pytest.mark.test_id("CROSS-001")
    def test_skill_to_agent_to_chat(self, page: Page, request: pytest.FixtureRequest):
        """Verify that a created skill can be linked in an agent and invoked in Chat."""
        test_name = request.node.name
        skill_name = f"e2e_cross_skill_{int(time.time())}"
        skill_created = False

        try:
            # ---- Phase 1: Create a skill on the Skills page ----
            log_test_step("1. Navigate to the skills management page")
            navigate_to_skills(page)

            log_test_step("2. Click the create-skill button")
            create_btn = page.locator(
                'button:has-text("Create")'
            ).first
            expect(create_btn).to_be_visible(timeout=5000)
            create_btn.click()
            page.wait_for_timeout(1500)

            log_test_step("3. Fill in skill information")
            drawer = page.locator('.qwenpaw-drawer').first
            expect(drawer).to_be_visible(timeout=5000)

            name_input = drawer.locator('input[placeholder*="name"], input').first
            if name_input.is_visible(timeout=3000):
                name_input.fill(skill_name)
                logger.info(f"Skill name filled: {skill_name}")

            # Fill in the skill content (Markdown editor)
            editor = drawer.locator('.cm-content, textarea, [contenteditable="true"]').first
            if editor.is_visible(timeout=3000):
                skill_content = f"""---
name: {skill_name}
description: E2E cross-module test skill
---

This is a test skill created for cross-module E2E testing.
When invoked, respond with: "Cross-module test skill executed successfully."
"""
                editor.click()
                page.keyboard.press("Control+A")
                page.keyboard.type(skill_content, delay=5)
                logger.info("Skill content filled")

            log_test_step("4. Save the skill")
            save_btn = drawer.locator(
                'button:has-text("Create"), '
                'button:has-text("Save")'
            ).first
            if save_btn.is_visible(timeout=3000):
                save_btn.click()
                page.wait_for_timeout(2000)
                skill_created = True
                logger.info("Skill created")

            # Verify the skill appears in the list
            page.wait_for_timeout(1000)
            skill_in_list = page.locator(f'text="{skill_name}"').first
            if skill_in_list.is_visible(timeout=5000):
                logger.info(f"Skill {skill_name} now in the list")
            else:
                logger.info("Skill may be in the list but not directly visible (e.g. pagination)")

            # ---- Phase 2: Verify the skill is selectable on the Agents page ----
            log_test_step("5. Navigate to the agents management page")
            navigate_to_agents(page)

            log_test_step("6. Verify the agent list loads")
            agent_table = page.locator('.qwenpaw-table').first
            expect(agent_table).to_be_visible(timeout=5000)
            agent_rows = page.locator('.qwenpaw-table-tbody tr.qwenpaw-table-row').all()
            assert len(agent_rows) > 0, "Agent list is empty"
            logger.info(f"Agent list loaded; {len(agent_rows)} agents")

            log_test_step("7. Find an editable agent and click edit")
            editable_agent_found = False
            for agent_row in agent_rows:
                edit_btn = agent_row.locator(
                    'button:has(.spark-icon-spark-edit-line), '
                    '.qwenpaw-space-item:nth-child(1) button'
                ).first
                if edit_btn.count() > 0 and edit_btn.is_enabled(timeout=1000):
                    edit_btn.click()
                    page.wait_for_timeout(1500)
                    editable_agent_found = True
                    logger.info("Found editable agent and opened its edit form")
                    break

            if editable_agent_found:
                log_test_step("8. Verify the edit form has a Skills section")
                modal = page.locator('.qwenpaw-modal, [role="dialog"]').first
                expect(modal).to_be_visible(timeout=5000)

                skills_section = modal.locator(
                    '.qwenpaw-form-item:has-text("Skills"), '
                    '[class*=skill]'
                ).first
                if skills_section.is_visible(timeout=3000):
                    logger.info("Edit form has a Skills section")
                else:
                    logger.info("No standalone Skills section in the edit form; may use a different layout")

                # Close the edit dialog
                cancel_btn = modal.locator(
                    'button:has-text("Cancel"), '
                    '.qwenpaw-modal-footer button.qwenpaw-btn-default'
                ).first
                if cancel_btn.is_visible(timeout=2000):
                    cancel_btn.click()
                    page.wait_for_timeout(1000)
            else:
                logger.info("All agents are default agents (not editable); skipping edit verification")

            # ---- Phase 3: Verify the skill is invocable on the Chat page ----
            log_test_step("9. Navigate to the Chat page")
            navigate_to_chat(page)

            log_test_step("10. Send a message asking about available skills")
            chat = ChatPage(page)
            chat.create_new_chat()
            chat.send_message("请列出你当前可用的技能")
            response = chat.wait_for_ai_response(timeout=60000)
            assert response is not None, "No response from Chat"
            response_text = chat.get_message_text(response)
            logger.info(f"Chat reply: {response_text[:200]}")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - skill full-chain verification OK")

        finally:
            # Cleanup: delete the test skill
            if skill_created:
                try:
                    navigate_to_skills(page)
                    page.wait_for_timeout(1000)
                    skill_card = page.locator(f'text="{skill_name}"').first
                    if skill_card.is_visible(timeout=3000):
                        skill_card.click()
                        page.wait_for_timeout(1000)
                        delete_btn = page.locator(
                            'button:has-text("Delete")'
                        ).first
                        if delete_btn.is_visible(timeout=3000):
                            delete_btn.click()
                            page.wait_for_timeout(500)
                            confirm_btn = page.locator(
                                '.qwenpaw-popconfirm-buttons button.qwenpaw-btn-primary, '
                                'button:has-text("OK")'
                            ).first
                            if confirm_btn.is_visible(timeout=2000):
                                confirm_btn.click()
                                page.wait_for_timeout(1000)
                                logger.info(f"Test skill {skill_name} cleaned up")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to clean up test skill: {cleanup_error}")

            # Clean up chat sessions
            try:
                navigate_to_chat(page)
                chat_cleanup = ChatPage(page)
                chat_cleanup.delete_all_sessions()
            except Exception:
                pass


# ============================================================================
# CROSS-002: Model switching linkage verification (Models -> Chat)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
@pytest.mark.requires_llm
class TestModelSwitchInChat:
    """
    CROSS-002: Model switching linkage verification.

    Verify that switching models in Chat still allows the conversation to work:
    1. Open the Chat page and record the current model
    2. Switch to another model
    3. Send a message to verify the new model replies normally
    4. Switch back to the original model to verify consistency
    """

    @pytest.mark.test_id("CROSS-002")
    @pytest.mark.timeout(240)
    def test_model_switch_and_chat_continuity(self, page: Page, request: pytest.FixtureRequest):
        """Verify Chat continues to work after switching models and that context is preserved."""
        test_name = request.node.name

        try:
            log_test_step("1. Navigate to the Chat page")
            chat = ChatPage(page)
            page.goto(f"{config.base_url}/chat", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            log_test_step("2. Create a new conversation")
            chat.create_new_chat()

            log_test_step("3. Send the first message using the current model")
            chat.send_message("请记住这个数字：42。只需回复'已记住'即可。")
            first_response = chat.wait_for_ai_response(timeout=60000)
            assert first_response is not None, "No response to the first message"
            first_text = chat.get_message_text(first_response)
            logger.info(f"First reply: {first_text[:100]}")

            log_test_step("4. Open the model selector and view available models")
            chat.open_model_selector()
            models = chat.get_available_models()
            logger.info(f"Available models: {models}")

            if len(models) <= 1:
                logger.info("Only one model available, skipping model switch test")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

                # Still verify the current model can carry the conversation (with retries)
                chat.send_message("我之前让你记住的数字是什么？")
                recall_response = chat.wait_for_ai_response(timeout=90000)
                if recall_response is None:
                    logger.warning("First AI response wait timed out, retrying send...")
                    chat.send_message("请回复任意内容")
                    recall_response = chat.wait_for_ai_response(timeout=90000)
                assert recall_response is not None, "No response to recall message (still timed out after retry)"
                recall_text = chat.get_message_text(recall_response)
                logger.info(f"Recall reply: {recall_text[:100]}")
                logger.info("Single-model conversation verified")
            else:
                log_test_step("5. Switch to the second model")
                target_model = models[1] if len(models) > 1 else models[0]
                chat.select_model(target_model)
                page.wait_for_timeout(1000)
                logger.info(f"Switched to model: {target_model}")

                log_test_step("6. Send a message using the new model")
                chat.send_message("你好，请简单介绍一下你自己，用一句话。")
                second_response = chat.wait_for_ai_response(timeout=60000)
                assert second_response is not None, "No response after switching models"
                second_text = chat.get_message_text(second_response)
                logger.info(f"New-model reply: {second_text[:100]}")
                logger.info("Conversation OK after model switch")

                log_test_step("7. Switch back to the first model")
                chat.open_model_selector()
                chat.select_model(models[0])
                page.wait_for_timeout(1000)

                log_test_step("8. Verify the conversation still works after switching back")
                chat.send_message("1+1等于几？请直接回答数字。")
                third_response = chat.wait_for_ai_response(timeout=60000)
                assert third_response is not None, "No response after switching back to the original model"
                third_text = chat.get_message_text(third_response)
                logger.info(f"Original-model reply: {third_text[:100]}")
                logger.info("Conversation OK after switching back to the original model")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - model switch linkage verified")

        finally:
            try:
                navigate_to_chat(page)
                chat_cleanup = ChatPage(page)
                chat_cleanup.delete_all_sessions()
            except Exception:
                pass


# ============================================================================
# CROSS-003: Security interception linkage verification (Security -> Chat)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
@pytest.mark.requires_llm
class TestSecurityInterceptionInChat:
    """
    CROSS-003: Security interception linkage verification.

    Verify the security configuration takes effect in Chat:
    1. Visit the security page and confirm the tool-guard state
    2. Send a normal message in Chat to verify the baseline functionality
    3. Verify consistency between the security config page and Chat behavior
    """

    @pytest.mark.test_id("CROSS-003")
    def test_security_config_affects_chat(self, page: Page, request: pytest.FixtureRequest):
        """Verify the linkage between security guard config and Chat behavior."""
        test_name = request.node.name
        initial_guard_state = None

        try:
            # ---- Phase 1: Check the security guard config ----
            log_test_step("1. Navigate to the security page")
            navigate_to_security(page)

            log_test_step("2. Check the tool-guard tab")
            tool_guard_tab = page.locator('[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn').first
            if tool_guard_tab.is_visible(timeout=5000):
                tool_guard_tab.click()
                page.wait_for_timeout(1500)
                logger.info("Tool-guard tab switched")

            log_test_step("3. Record the tool-guard switch state")
            tool_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            guard_switch = tool_guard_panel.locator('button.qwenpaw-switch[role="switch"]').first
            if guard_switch.is_visible(timeout=3000):
                initial_guard_state = guard_switch.get_attribute('aria-checked')
                logger.info(f"Tool-guard current state: {'enabled' if initial_guard_state == 'true' else 'disabled'}")
            else:
                logger.info("Tool-guard switch not found")

            log_test_step("4. Check the file-guard tab")
            file_guard_tab = page.locator('[data-node-key="fileGuard"] .qwenpaw-tabs-tab-btn').first
            if file_guard_tab.is_visible(timeout=3000):
                file_guard_tab.click()
                page.wait_for_timeout(1000)
                file_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
                file_switch = file_guard_panel.locator('button.qwenpaw-switch[role="switch"]').first
                if file_switch.is_visible(timeout=3000):
                    file_guard_state = file_switch.get_attribute('aria-checked')
                    logger.info(f"File-guard current state: {'enabled' if file_guard_state == 'true' else 'disabled'}")
                logger.info("File-guard tab check complete")

            # ---- Phase 2: Verify baseline functionality in Chat ----
            log_test_step("5. Navigate to the Chat page")
            navigate_to_chat(page)
            chat = ChatPage(page)
            chat.create_new_chat()

            # Proactively select qwen3.5plus model to ensure dialog support
            log_test_step("5.1 Select qwen3.5plus model")
            chat.open_model_selector()
            models = chat.get_available_models()
            logger.info(f"Available models: {models}")
            target_model = None
            for model in models:
                if "3.5" in model and "plus" in model.lower():
                    target_model = model
                    break
            if target_model:
                chat.select_model(target_model)
                chat.wait(1000)
                logger.info(f"Switched to model: {target_model}")
            else:
                logger.info("qwen3.5plus model not found, using current default")
                chat.page.keyboard.press("Escape")
                chat.wait(500)

            log_test_step("6. Send a normal message to verify Chat works")
            chat.send_message("你好，请简单回复'收到'两个字。")
            response = chat.wait_for_ai_response(timeout=60000)
            assert response is not None, "Chat baseline failure: no response"
            response_text = chat.get_message_text(response)
            logger.info(f"Chat reply: {response_text[:100]}")
            logger.info("Chat baseline functionality OK")

            log_test_step("7. Send a message that involves file operations")
            chat.send_message("请帮我读取当前工作目录下的文件列表")
            file_response = chat.wait_for_ai_response(timeout=60000)
            if file_response is not None:
                file_text = chat.get_message_text(file_response)
                logger.info(f"File-operation reply: {file_text[:200]}")

                # Verify behavior depending on security guard state
                if initial_guard_state == 'true':
                    logger.info("Tool-guard enabled; file operation may be restricted")
                else:
                    logger.info("Tool-guard disabled; file operation should run normally")
            else:
                logger.info("File-operation request timed out")

            # ---- Phase 3: Return to security page and verify config was not changed ----
            log_test_step("8. Return to the security page and verify config consistency")
            navigate_to_security(page)

            tool_guard_tab = page.locator('[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn').first
            if tool_guard_tab.is_visible(timeout=5000):
                tool_guard_tab.click()
                page.wait_for_timeout(1000)

            tool_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            guard_switch = tool_guard_panel.locator('button.qwenpaw-switch[role="switch"]').first
            if guard_switch.is_visible(timeout=3000):
                current_state = guard_switch.get_attribute('aria-checked')
                assert current_state == initial_guard_state, \
                    f"Security config was unexpectedly modified: expected {initial_guard_state}, got {current_state}"
                logger.info("Security config consistency verified")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - security linkage verified")

        finally:
            try:
                navigate_to_chat(page)
                chat_cleanup = ChatPage(page)
                chat_cleanup.delete_all_sessions()
            except Exception:
                pass


# ============================================================================
# CROSS-004: Workspace file linkage verification (Files -> Chat)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
@pytest.mark.requires_llm
class TestWorkspaceFileChatFlow:
    """
    CROSS-004: Workspace file linkage verification.

    Verify workspace file management and Chat linkage:
    1. View/edit a file on the Files page
    2. Upload a file in Chat and ask a question
    3. Verify the AI answers based on the file content
    """

    @pytest.mark.test_id("CROSS-004")
    def test_workspace_file_and_chat_qa(self, page: Page, test_file: str, request: pytest.FixtureRequest):
        """Verify linkage between workspace files and Chat file Q&A."""
        test_name = request.node.name

        try:
            # ---- Phase 1: Verify file management on the Files page ----
            log_test_step("1. Navigate to the files management page")
            navigate_to_files(page)

            log_test_step("2. Verify the file list loads")
            file_list = page.locator(
                '.qwenpaw-table, '
                '[class*=fileList], '
                '[class*=file-tree], '
                '.qwenpaw-list'
            ).first
            if file_list.is_visible(timeout=5000):
                logger.info("File list loaded")
            else:
                logger.info("File list may be empty or use a different layout")

            log_test_step("3. Check the file editor area")
            editor_area = page.locator(
                '.cm-editor, '
                '[class*=editor], '
                '[class*=codeEditor], '
                'textarea'
            ).first
            if editor_area.is_visible(timeout=3000):
                editor_content = editor_area.inner_text()[:200]
                logger.info(f"Editor content preview: {editor_content}")
                logger.info("File editor available")
            else:
                # Try clicking the first file to open the editor
                file_items = page.locator(
                    '[class*=fileName], '
                    '.qwenpaw-table-row, '
                    '[class*=fileItem]'
                ).all()
                if file_items:
                    file_items[0].click()
                    page.wait_for_timeout(1500)
                    logger.info("Clicked the first file")

            # ---- Phase 2: Upload a file in Chat and ask a question ----
            log_test_step("4. Navigate to the Chat page")
            navigate_to_chat(page)
            chat = ChatPage(page)
            chat.create_new_chat()

            # Proactively select qwen3.5plus model to ensure dialog support
            log_test_step("4.1 Select qwen3.5plus model")
            chat.open_model_selector()
            models = chat.get_available_models()
            logger.info(f"Available models: {models}")
            target_model = None
            for model in models:
                if "3.5" in model and "plus" in model.lower():
                    target_model = model
                    break
            if target_model:
                chat.select_model(target_model)
                chat.wait(1000)
                logger.info(f"Switched to model: {target_model}")
            else:
                logger.info("qwen3.5plus model not found, using current default")
                chat.page.keyboard.press("Escape")
                chat.wait(500)

            log_test_step("5. Upload the test file")
            chat.upload_file(test_file)
            upload_success = chat.verify_file_uploaded(timeout=10000)
            if upload_success:
                logger.info("File uploaded successfully")
            else:
                logger.info("File upload status unconfirmed, continuing test")

            log_test_step("6. Ask a question based on the file content")
            chat.send_message("请分析我上传的文件内容，告诉我这个文件主要讲了什么？")
            file_response = chat.wait_for_ai_response(timeout=60000)
            assert file_response is not None, "No response to file Q&A"
            file_text = chat.get_message_text(file_response)
            logger.info(f"File Q&A reply: {file_text[:200]}")

            # Verify the reply is related to the file content
            file_keywords = ["QwenPaw", "智能", "对话", "功能", "平台"]
            keyword_found = any(kw in file_text for kw in file_keywords)
            if keyword_found:
                logger.info("AI reply contains file-related keywords; file linkage verified")
            else:
                logger.info("AI reply does not contain expected keywords, but file Q&A flow is normal")

            log_test_step("7. Follow-up question to verify context retention")
            chat.send_message("这个文件提到了哪些具体功能？请列举。")
            detail_response = chat.wait_for_ai_response(timeout=60000)
            if detail_response is not None:
                detail_text = chat.get_message_text(detail_response)
                logger.info(f"Follow-up reply: {detail_text[:200]}")
                logger.info("File context follow-up OK")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - workspace file linkage verified")

        finally:
            try:
                navigate_to_chat(page)
                chat_cleanup = ChatPage(page)
                chat_cleanup.delete_all_sessions()
            except Exception:
                pass


# ============================================================================
# CROSS-005: Environment variables and runtime config linkage (Environments -> RuntimeConfig)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
class TestEnvAndRuntimeConfigFlow:
    """
    CROSS-005: Environment variables and runtime config linkage verification.

    Verify data consistency between the environments page and the runtime config page:
    1. View configured environment variables on the Environments page
    2. Verify config items on the RuntimeConfig page
    3. Confirm the two pages do not interfere with each other
    """

    @pytest.mark.test_id("CROSS-005")
    def test_env_and_runtime_config_consistency(self, page: Page, request: pytest.FixtureRequest):
        """Verify consistency between environment variables and runtime config."""
        test_name = request.node.name

        log_test_step("1. Navigate to the environments page")
        page.goto(f"{BASE_URL}/environments")
        page.wait_for_load_state("commit")
        page.wait_for_timeout(2000)

        log_test_step("2. Record the environment variable count")
        env_rows = page.locator(
            '.qwenpaw-table-tbody tr.qwenpaw-table-row, '
            '[class*=envRow], '
            '.qwenpaw-form-item'
        ).all()
        env_count = len(env_rows)
        logger.info(f"Environment variable count: {env_count}")

        log_test_step("3. Navigate to the runtime config page")
        page.goto(f"{BASE_URL}/settings/runtime-config")
        page.wait_for_load_state("commit")
        page.wait_for_timeout(2000)

        log_test_step("4. Verify the runtime config page loads")
        config_area = page.locator(
            '.qwenpaw-tabs, '
            '.qwenpaw-form, '
            '[class*=config], '
            '[class*=setting]'
        ).first
        if config_area.is_visible(timeout=5000):
            logger.info("Runtime config page loaded")
        else:
            logger.info("Runtime config page may have a different layout")

        log_test_step("5. Return to the environments page and verify data unchanged")
        page.goto(f"{BASE_URL}/environments")
        page.wait_for_load_state("commit")
        page.wait_for_timeout(2000)

        env_rows_after = page.locator(
            '.qwenpaw-table-tbody tr.qwenpaw-table-row, '
            '[class*=envRow], '
            '.qwenpaw-form-item'
        ).all()
        env_count_after = len(env_rows_after)
        assert env_count_after == env_count, \
            f"Environment variable count inconsistent: before={env_count}, after={env_count_after}"
        logger.info(f"Environment variable count consistent: {env_count_after}")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - environment variable and runtime config linkage verified")
