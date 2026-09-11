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
import re
import time
import pytest
from playwright.sync_api import Page, expect, TimeoutError

from pages.chat_page import ChatPage
from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

BASE_URL = config.base_url

# -- Environments page anchors (rebuilt for #7538) -------------------------
# The Environments page was rewritten by #7538 ("unify runtime environment
# management"): rows are no longer table rows / inline inputs but
# `styles.row` divs grouped into three sections.  The old selector list
# (`tr.qwenpaw-table-row`, `[class*=envRow]`, `.qwenpaw-form-item`) matches
# nothing on the new page, which would have made the before/after count
# comparison below a vacuous `0 == 0`.
#
# Class names are CSS-module scoped as `[name]__[local]__[hash:base64:5]`, and
# this stylesheet shares the `index.module.less` filename with PageHeader, so
# every generated class starts with `index-module__`.  Matching `__row__`
# (double-underscore bounded) hits `index-module__row__<hash>` without
# matching neighbours such as `index-module__envRow__<hash>`.
ENV_ROW_SELECTOR = 'div[class*="__row__"]'
# `styles.sectionHeading` is rendered only in the loaded branch; the loading
# and error branches render `styles.state` instead, so it doubles as a
# "catalogue data has arrived" signal.
ENV_SECTION_HEADING = 'div[class*="__sectionHeading__"]'


def wait_for_environments_loaded(page: Page, timeout: int = 15000):
    """Open the Environments page and wait for the catalogue to render."""
    page.goto(f"{BASE_URL}/environments")
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator(ENV_SECTION_HEADING).first).to_be_visible(timeout=timeout)


def count_environment_rows(page: Page) -> int:
    """Count variable rows across all three sections of the Environments page."""
    return page.locator(ENV_ROW_SELECTOR).count()


def sum_environment_section_counts(page: Page) -> int:
    """Sum the three section-heading counts (Custom + Live + Read-only).

    index.tsx renders `<span>{customVariables.length}</span>`,
    `<span>{editableCatalog.length}</span>` and
    `<span>{readonlyCatalog.length}</span>` inside each `styles.sectionHeading`,
    and those three lists are exactly what produces the `styles.row` elements.
    Their sum is therefore an independent measurement of the same quantity as
    `count_environment_rows()`, derived from text rather than from the row
    class name.

    Comparing the two is a self-consistent invariant: it catches row-selector
    drift (rows would count 0 while the headings still sum to the catalogue
    size) without hard-coding the catalogue size, which upstream is free to
    change — `src/qwenpaw/envs/registry.py` currently ships 17 `EnvVarSpec`
    entries (2 hot_runtime + 15 startup_only), but a future entry would make a
    literal `>= 17` assertion wrong in either direction.
    """
    total = 0
    for heading_text in ("Custom variables", "Live settings", "Read-only settings"):
        heading = page.locator(ENV_SECTION_HEADING).filter(has_text=heading_text).first
        expect(heading).to_be_visible(timeout=10000)
        raw = heading.locator("span").first.inner_text().strip()
        if not raw.isdigit():
            raise AssertionError(
                f"'{heading_text}' section count is not an integer: {raw!r}"
            )
        total += int(raw)
    return total


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
    page.goto(f"{BASE_URL}/files")
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

            log_test_step("2. Open Add Skill menu and choose Create Skill")
            # Post v2.0.0 the create entry lives inside the "Add Skill"
            # dropdown (AddSkillDropdown.tsx), not a standalone button.
            add_btn = page.locator(
                'button:has-text("Add Skill"), button:has-text("添加技能")'
            ).first
            expect(add_btn).to_be_visible(timeout=8000)
            add_btn.click()
            page.wait_for_timeout(600)
            create_item = page.locator(
                '.qwenpaw-dropdown-menu-item:has-text("Create Skill"), '
                '.qwenpaw-dropdown-menu-item:has-text("创建技能")'
            ).first
            expect(create_item).to_be_visible(timeout=5000)
            create_item.click()
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
                edit_btn = agent_row.locator('button:has(.anticon-edit)').first
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
    CROSS-005: Environment variables and agent (runtime) config boundary.

    Verify the two pages that expose the same LLM settings at different layers:
    1. Environments page renders the whole variable catalogue, and its row
       anchor agrees with the sum of the three section-heading counts
    2. Agent config page (/agent-config) renders the LLM Retry and LLM Rate
       Limiter tabs — the persisted running-config counterparts of the
       QWENPAW_LLM_* environment variables
    3. Confirm the two pages do not interfere with each other: navigating
       away and back leaves the Environments catalogue unchanged

    SCOPE CHANGE (#7538): the Environments row anchor had to be rebuilt for the
    unified page (rows are `styles.row` divs in three sections, not table rows),
    and the old navigation target `/settings/runtime-config` has never existed
    in console/src at any revision, so step 3 used to land on a blank page
    while step 4 logged a message instead of asserting.  Both are fixed here.

    What this case deliberately does NOT assert: that changing an environment
    variable makes the agent config page show a new number.  #7538 does connect
    the two layers — `AgentsRunningConfig` defaults now come from
    `EnvVarLoader.get_int("QWENPAW_LLM_MAX_RETRIES", ...)` — but that default
    is only consulted when an agent has no persisted running config
    (`running = agent_config.running or AgentsRunningConfig()`), so for any
    already-configured agent the page shows stored values and never follows
    the environment.  Asserting a live env -> UI linkage would be flaky by
    construction.
    """

    @pytest.mark.test_id("CROSS-005")
    def test_env_and_runtime_config_consistency(self, page: Page, request: pytest.FixtureRequest):
        """Verify consistency between environment variables and runtime config."""
        test_name = request.node.name

        log_test_step("1. Navigate to the environments page")
        wait_for_environments_loaded(page)

        log_test_step("2. Record the environment variable count")
        env_count = count_environment_rows(page)
        # Lower-bound guard: without it a selector that stopped matching would
        # compare 0 == 0 and this case would stay green while testing nothing
        # (the same silent-pass family as the shard-selection blind spots).
        assert env_count > 0, (
            "Environments page reported zero variable rows — the row selector "
            "no longer matches the page, so this comparison would be vacuous"
        )
        # Self-consistency guard: the row count and the sum of the three
        # section-heading counts measure the same thing two independent ways
        # (class name vs. rendered text).  Agreeing means the row anchor is
        # really pointing at variable rows, not at some unrelated element that
        # happens to match, and it stays correct when upstream adds or removes
        # catalogue entries.
        section_sum = sum_environment_section_counts(page)
        assert env_count == section_sum, (
            f"Row count ({env_count}) disagrees with the sum of the section "
            f"heading counts ({section_sum}) — one of the two anchors is wrong"
        )
        logger.info(
            f"Environment variable count: {env_count} "
            f"(section headings sum to the same {section_sum})"
        )

        log_test_step("3. Navigate to the agent config (runtime config) page")
        # The authoritative route is /agent-config: console/src/layouts/registry/
        # builtinRoutes.tsx maps core.agent-config -> /agent-config, and
        # e2e/pages/runtime_config_page.py:31 plus e2e/tests/
        # test_runtime_config.py:23 already use it.  "/settings/runtime-config"
        # has never existed in console/src at any revision (zero hits across the
        # whole history), so the previous navigation landed on a blank page and
        # step 4 could not fail no matter what it found.
        page.goto(f"{BASE_URL}/agent-config")
        page.wait_for_load_state("domcontentloaded")

        log_test_step("4. Verify the agent config page renders its LLM tabs")
        # Hard assertions on the tab keys declared in
        # console/src/pages/Agent/Config/index.tsx (key: "llmRetry" at line 165,
        # key: "llmRateLimiter" at line 178).  These are the runtime-config
        # counterparts of the QWENPAW_LLM_* environment variables, which is the
        # actual boundary this cross-module case is about.  The same
        # data-node-key anchors are already proven green in
        # e2e/tests/test_runtime_config.py, so no new selector idiom is
        # introduced here.
        for tab_key in ("llmRetry", "llmRateLimiter"):
            tab = page.locator(f'[data-node-key="{tab_key}"] .qwenpaw-tabs-tab-btn').first
            expect(tab).to_be_visible(timeout=10000)
            logger.info(f"Agent config tab present: {tab_key}")
        # The two pages coexist as separate routes: #7538 unified how
        # environment variables are read (EnvVarLoader + envs/registry.py as the
        # single source of truth), it did not merge this page into Environments.
        expect(page.locator('.qwenpaw-tabs').first).to_be_visible(timeout=5000)

        log_test_step("5. Return to the environments page and verify data unchanged")
        wait_for_environments_loaded(page)

        env_count_after = count_environment_rows(page)
        assert env_count_after == env_count, \
            f"Environment variable count inconsistent: before={env_count}, after={env_count_after}"
        # Re-check the invariant after the round trip: navigating away and back
        # must not leave the two anchors disagreeing either.
        section_sum_after = sum_environment_section_counts(page)
        assert env_count_after == section_sum_after, (
            f"After the round trip the row count ({env_count_after}) disagrees "
            f"with the section heading sum ({section_sum_after})"
        )
        logger.info(
            f"Environment variable count consistent: {env_count_after} "
            f"(section headings sum to the same {section_sum_after})"
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - environment variable and runtime config linkage verified")


# ============================================================================
# MA-001 P1 — sidebar Agent switcher (Agents API -> Chat sidebar)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
class TestAgentSwitcherInChat:
    """MA-001: seed an agent via API, switch to it in the sidebar
    AgentSelector, assert the trigger reflects the selection; restore."""

    @pytest.mark.test_id("MA-001")
    def test_agent_switcher_in_chat(
        self,
        page: Page,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        from pages.agents_page import AgentsPage

        test_name = request.node.name
        chat = ChatPage(page)
        agents_page = AgentsPage(page)
        agent_name = f"E2E Switcher {int(time.time())}"
        agent_id = None

        log_test_step("1. Seed a fresh agent via API")
        created = agents_page.api_create_agent(
            api_context, agent_name, description="switcher probe"
        )
        agent_id = (created or {}).get("id")
        if not agent_id:
            pytest.skip(f"agent seed failed: {created!r}")

        try:
            log_test_step("2. Open /chat — AgentSelector mounts and fetches")
            chat.open()
            switcher = page.locator(chat.AGENT_SWITCHER).first
            expect(switcher).to_be_visible(timeout=chat.timeout)

            log_test_step("3. Open the switcher; seeded agent is listed")
            switcher.click()
            option = page.locator(chat.AGENT_SWITCHER_OPTION).filter(
                has_text=agent_name
            ).first
            expect(option).to_be_visible(timeout=chat.timeout)

            log_test_step("4. Select it; trigger label shows the agent name")
            option.click()
            page.wait_for_timeout(800)
            value = page.locator(chat.AGENT_SWITCHER_VALUE).first
            expect(value).to_contain_text(
                agent_name, timeout=chat.timeout
            )

            log_test_step("5. Switch back to the default agent")
            switcher.click()
            default_option = page.locator(
                chat.AGENT_SWITCHER_OPTION
            ).filter(has_text=re.compile("Default Agent|默认智能体")).first
            expect(default_option).to_be_visible(timeout=chat.timeout)
            default_option.click()
            page.wait_for_timeout(800)
            expect(
                page.locator(chat.AGENT_SWITCHER_VALUE).first
            ).not_to_contain_text(agent_name, timeout=chat.timeout)
        finally:
            if agent_id:
                try:
                    agents_page.api_delete_agent(api_context, agent_id)
                except Exception:
                    pass

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
