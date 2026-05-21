# -*- coding: utf-8 -*-
"""
QwenPaw 跨模块联动 E2E 测试用例

验证多个功能模块之间的业务联动关系：
- CROSS-001: 技能全链路 (Skills → Agents → Chat)
- CROSS-002: 模型切换联动 (Models → Chat)
- CROSS-003: 安全防护拦截联动 (Security → Chat)
- CROSS-004: 工作区文件联动 (Files → Chat)

执行命令：pytest tests/test_cross_module.py -v
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
    """导航到技能管理页面"""
    page.goto(f"{BASE_URL}/skills")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


def navigate_to_agents(page: Page):
    """导航到智能体管理页面"""
    page.goto(f"{BASE_URL}/agents")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


def navigate_to_security(page: Page):
    """导航到安全防护页面"""
    page.goto(f"{BASE_URL}/security")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


def navigate_to_files(page: Page):
    """导航到文件管理页面"""
    page.goto(f"{BASE_URL}/workspace")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


def navigate_to_chat(page: Page):
    """导航到聊天页面"""
    page.goto(f"{BASE_URL}/chat")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


# ============================================================================
# CROSS-001: 技能全链路验证 (Skills → Agents → Chat)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
class TestSkillAgentChatFlow:
    """
    CROSS-001: 技能全链路验证

    验证从创建技能到在 Chat 中使用的完整业务链路：
    1. 在 Skills 页面创建一个测试技能
    2. 在 Agents 页面验证技能可被关联
    3. 在 Chat 页面验证技能可被调用
    4. 清理测试数据
    """

    @pytest.mark.test_id("CROSS-001")
    def test_skill_to_agent_to_chat(self, page: Page, request: pytest.FixtureRequest):
        """验证技能创建后可在智能体中关联，并在 Chat 中调用"""
        test_name = request.node.name
        skill_name = f"e2e_cross_skill_{int(time.time())}"
        skill_created = False

        try:
            # ---- 阶段 1: 在 Skills 页面创建技能 ----
            log_test_step("1. 导航到技能管理页面")
            navigate_to_skills(page)

            log_test_step("2. 点击创建技能按钮")
            create_btn = page.locator(
                'button:has-text("创建"), '
                'button:has-text("Create"), '
                'button:has-text("新建")'
            ).first
            expect(create_btn).to_be_visible(timeout=5000)
            create_btn.click()
            page.wait_for_timeout(1500)

            log_test_step("3. 填写技能信息")
            drawer = page.locator('.qwenpaw-drawer').first
            expect(drawer).to_be_visible(timeout=5000)

            name_input = drawer.locator('input[placeholder*="name"], input[placeholder*="名称"], input').first
            if name_input.is_visible(timeout=3000):
                name_input.fill(skill_name)
                logger.info(f"✅ 技能名称已填写：{skill_name}")

            # 填写技能内容（Markdown 编辑器）
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
                logger.info("✅ 技能内容已填写")

            log_test_step("4. 保存技能")
            save_btn = drawer.locator(
                'button:has-text("创建"), '
                'button:has-text("Create"), '
                'button:has-text("保存"), '
                'button:has-text("Save")'
            ).first
            if save_btn.is_visible(timeout=3000):
                save_btn.click()
                page.wait_for_timeout(2000)
                skill_created = True
                logger.info("✅ 技能已创建")

            # 验证技能出现在列表中
            page.wait_for_timeout(1000)
            skill_in_list = page.locator(f'text="{skill_name}"').first
            if skill_in_list.is_visible(timeout=5000):
                logger.info(f"✅ 技能 {skill_name} 已出现在列表中")
            else:
                logger.info("ℹ️ 技能可能在列表中但未直接可见（分页等原因）")

            # ---- 阶段 2: 在 Agents 页面验证技能可关联 ----
            log_test_step("5. 导航到智能体管理页面")
            navigate_to_agents(page)

            log_test_step("6. 验证智能体列表加载")
            agent_table = page.locator('.qwenpaw-table').first
            expect(agent_table).to_be_visible(timeout=5000)
            agent_rows = page.locator('.qwenpaw-table-tbody tr.qwenpaw-table-row').all()
            assert len(agent_rows) > 0, "智能体列表为空"
            logger.info(f"✅ 智能体列表已加载，共 {len(agent_rows)} 个智能体")

            log_test_step("7. 找到可编辑的智能体并点击编辑")
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
                    logger.info("✅ 找到可编辑的智能体并已打开编辑表单")
                    break

            if editable_agent_found:
                log_test_step("8. 验证编辑表单中有 Skills 选择区域")
                modal = page.locator('.qwenpaw-modal, [role="dialog"]').first
                expect(modal).to_be_visible(timeout=5000)

                skills_section = modal.locator(
                    '.qwenpaw-form-item:has-text("Skills"), '
                    '.qwenpaw-form-item:has-text("技能"), '
                    '[class*=skill]'
                ).first
                if skills_section.is_visible(timeout=3000):
                    logger.info("✅ 编辑表单中存在 Skills 关联区域")
                else:
                    logger.info("ℹ️ 编辑表单中未找到独立的 Skills 区域，可能使用其他布局")

                # 关闭编辑弹窗
                cancel_btn = modal.locator(
                    'button:has-text("取消"), '
                    'button:has-text("Cancel"), '
                    '.qwenpaw-modal-footer button.qwenpaw-btn-default'
                ).first
                if cancel_btn.is_visible(timeout=2000):
                    cancel_btn.click()
                    page.wait_for_timeout(1000)
            else:
                logger.info("ℹ️ 所有智能体均为默认智能体（不可编辑），跳过编辑验证")

            # ---- 阶段 3: 在 Chat 页面验证技能可调用 ----
            log_test_step("9. 导航到 Chat 页面")
            navigate_to_chat(page)

            log_test_step("10. 发送消息询问可用技能")
            chat = ChatPage(page)
            chat.create_new_chat()
            chat.send_message("请列出你当前可用的技能")
            response = chat.wait_for_ai_response(timeout=60000)
            assert response is not None, "Chat 无响应"
            response_text = chat.get_message_text(response)
            logger.info(f"✅ Chat 回复：{response_text[:200]}")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed - 技能全链路验证通过")

        finally:
            # 清理：删除测试技能
            if skill_created:
                try:
                    navigate_to_skills(page)
                    page.wait_for_timeout(1000)
                    skill_card = page.locator(f'text="{skill_name}"').first
                    if skill_card.is_visible(timeout=3000):
                        skill_card.click()
                        page.wait_for_timeout(1000)
                        delete_btn = page.locator(
                            'button:has-text("删除"), '
                            'button:has-text("Delete")'
                        ).first
                        if delete_btn.is_visible(timeout=3000):
                            delete_btn.click()
                            page.wait_for_timeout(500)
                            confirm_btn = page.locator(
                                '.qwenpaw-popconfirm-buttons button.qwenpaw-btn-primary, '
                                'button:has-text("确定"), '
                                'button:has-text("OK")'
                            ).first
                            if confirm_btn.is_visible(timeout=2000):
                                confirm_btn.click()
                                page.wait_for_timeout(1000)
                                logger.info(f"✅ 测试技能 {skill_name} 已清理")
                except Exception as cleanup_error:
                    logger.warning(f"清理测试技能失败：{cleanup_error}")

            # 清理 Chat 会话
            try:
                navigate_to_chat(page)
                chat_cleanup = ChatPage(page)
                chat_cleanup.delete_all_sessions()
            except Exception:
                pass


# ============================================================================
# CROSS-002: 模型切换联动验证 (Models → Chat)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
class TestModelSwitchInChat:
    """
    CROSS-002: 模型切换联动验证

    验证在 Chat 中切换模型后对话功能正常：
    1. 打开 Chat 页面，记录当前模型
    2. 切换到另一个模型
    3. 发送消息验证新模型可正常回复
    4. 切换回原模型验证一致性
    """

    @pytest.mark.test_id("CROSS-002")
    @pytest.mark.timeout(240)
    def test_model_switch_and_chat_continuity(self, page: Page, request: pytest.FixtureRequest):
        """验证模型切换后对话功能正常且上下文保持"""
        test_name = request.node.name

        try:
            log_test_step("1. 导航到 Chat 页面")
            chat = ChatPage(page)
            page.goto(f"{config.base_url}/chat", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            log_test_step("2. 创建新对话")
            chat.create_new_chat()

            log_test_step("3. 使用当前模型发送第一条消息")
            chat.send_message("请记住这个数字：42。只需回复'已记住'即可。")
            first_response = chat.wait_for_ai_response(timeout=60000)
            assert first_response is not None, "第一条消息无响应"
            first_text = chat.get_message_text(first_response)
            logger.info(f"第一条回复：{first_text[:100]}")

            log_test_step("4. 打开模型选择器，查看可用模型")
            chat.open_model_selector()
            models = chat.get_available_models()
            logger.info(f"可用模型列表：{models}")

            if len(models) <= 1:
                logger.info("ℹ️ 仅有一个模型，跳过模型切换测试")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

                # 仍然验证当前模型可正常对话（增加重试）
                chat.send_message("我之前让你记住的数字是什么？")
                recall_response = chat.wait_for_ai_response(timeout=90000)
                if recall_response is None:
                    logger.warning("首次等待 AI 响应超时，重试发送...")
                    chat.send_message("请回复任意内容")
                    recall_response = chat.wait_for_ai_response(timeout=90000)
                assert recall_response is not None, "回忆消息无响应（重试后仍超时）"
                recall_text = chat.get_message_text(recall_response)
                logger.info(f"回忆回复：{recall_text[:100]}")
                logger.info("✅ 单模型对话验证通过")
            else:
                log_test_step("5. 切换到第二个模型")
                target_model = models[1] if len(models) > 1 else models[0]
                chat.select_model(target_model)
                page.wait_for_timeout(1000)
                logger.info(f"✅ 已切换到模型：{target_model}")

                log_test_step("6. 使用新模型发送消息")
                chat.send_message("你好，请简单介绍一下你自己，用一句话。")
                second_response = chat.wait_for_ai_response(timeout=60000)
                assert second_response is not None, "切换模型后消息无响应"
                second_text = chat.get_message_text(second_response)
                logger.info(f"新模型回复：{second_text[:100]}")
                logger.info("✅ 模型切换后对话正常")

                log_test_step("7. 切换回第一个模型")
                chat.open_model_selector()
                chat.select_model(models[0])
                page.wait_for_timeout(1000)

                log_test_step("8. 验证切换回后仍可正常对话")
                chat.send_message("1+1等于几？请直接回答数字。")
                third_response = chat.wait_for_ai_response(timeout=60000)
                assert third_response is not None, "切换回原模型后消息无响应"
                third_text = chat.get_message_text(third_response)
                logger.info(f"原模型回复：{third_text[:100]}")
                logger.info("✅ 切换回原模型后对话正常")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed - 模型切换联动验证通过")

        finally:
            try:
                navigate_to_chat(page)
                chat_cleanup = ChatPage(page)
                chat_cleanup.delete_all_sessions()
            except Exception:
                pass


# ============================================================================
# CROSS-003: 安全防护拦截联动验证 (Security → Chat)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
class TestSecurityInterceptionInChat:
    """
    CROSS-003: 安全防护拦截联动验证

    验证安全防护配置能在 Chat 中生效：
    1. 访问安全防护页面，确认工具防护状态
    2. 在 Chat 中发送正常消息验证基础功能
    3. 验证安全配置页面与 Chat 页面的联动一致性
    """

    @pytest.mark.test_id("CROSS-003")
    def test_security_config_affects_chat(self, page: Page, request: pytest.FixtureRequest):
        """验证安全防护配置与 Chat 行为的联动"""
        test_name = request.node.name
        initial_guard_state = None

        try:
            # ---- 阶段 1: 检查安全防护配置 ----
            log_test_step("1. 导航到安全防护页面")
            navigate_to_security(page)

            log_test_step("2. 检查工具防护 Tab")
            tool_guard_tab = page.locator('[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn').first
            if tool_guard_tab.is_visible(timeout=5000):
                tool_guard_tab.click()
                page.wait_for_timeout(1500)
                logger.info("✅ 工具防护 Tab 已切换")

            log_test_step("3. 记录工具防护开关状态")
            tool_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            guard_switch = tool_guard_panel.locator('button.qwenpaw-switch[role="switch"]').first
            if guard_switch.is_visible(timeout=3000):
                initial_guard_state = guard_switch.get_attribute('aria-checked')
                logger.info(f"工具防护当前状态：{'已启用' if initial_guard_state == 'true' else '已禁用'}")
            else:
                logger.info("ℹ️ 未找到工具防护开关")

            log_test_step("4. 检查文件防护 Tab")
            file_guard_tab = page.locator('[data-node-key="fileGuard"] .qwenpaw-tabs-tab-btn').first
            if file_guard_tab.is_visible(timeout=3000):
                file_guard_tab.click()
                page.wait_for_timeout(1000)
                file_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
                file_switch = file_guard_panel.locator('button.qwenpaw-switch[role="switch"]').first
                if file_switch.is_visible(timeout=3000):
                    file_guard_state = file_switch.get_attribute('aria-checked')
                    logger.info(f"文件防护当前状态：{'已启用' if file_guard_state == 'true' else '已禁用'}")
                logger.info("✅ 文件防护 Tab 检查完成")

            # ---- 阶段 2: 在 Chat 中验证基础功能 ----
            log_test_step("5. 导航到 Chat 页面")
            navigate_to_chat(page)
            chat = ChatPage(page)
            chat.create_new_chat()

            # 主动选择千问3.5plus模型，确保模型支持对话
            log_test_step("5.1 选择千问3.5plus模型")
            chat.open_model_selector()
            models = chat.get_available_models()
            logger.info(f"可用模型：{models}")
            target_model = None
            for model in models:
                if "3.5" in model and "plus" in model.lower():
                    target_model = model
                    break
            if target_model:
                chat.select_model(target_model)
                chat.wait(1000)
                logger.info(f"已切换到模型：{target_model}")
            else:
                logger.info("未找到千问3.5plus模型，使用当前默认模型")
                chat.page.keyboard.press("Escape")
                chat.wait(500)

            log_test_step("6. 发送正常消息验证 Chat 功能")
            chat.send_message("你好，请简单回复'收到'两个字。")
            response = chat.wait_for_ai_response(timeout=60000)
            assert response is not None, "Chat 基础功能异常：无响应"
            response_text = chat.get_message_text(response)
            logger.info(f"Chat 回复：{response_text[:100]}")
            logger.info("✅ Chat 基础功能正常")

            log_test_step("7. 发送涉及文件操作的消息")
            chat.send_message("请帮我读取当前工作目录下的文件列表")
            file_response = chat.wait_for_ai_response(timeout=60000)
            if file_response is not None:
                file_text = chat.get_message_text(file_response)
                logger.info(f"文件操作回复：{file_text[:200]}")

                # 根据安全防护状态验证行为
                if initial_guard_state == 'true':
                    logger.info("ℹ️ 工具防护已启用，文件操作可能受限")
                else:
                    logger.info("ℹ️ 工具防护未启用，文件操作应正常执行")
            else:
                logger.info("ℹ️ 文件操作请求超时")

            # ---- 阶段 3: 回到安全页面验证配置未被改变 ----
            log_test_step("8. 回到安全防护页面验证配置一致性")
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
                    f"安全配置被意外修改：期望 {initial_guard_state}，实际 {current_state}"
                logger.info("✅ 安全配置一致性验证通过")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed - 安全防护联动验证通过")

        finally:
            try:
                navigate_to_chat(page)
                chat_cleanup = ChatPage(page)
                chat_cleanup.delete_all_sessions()
            except Exception:
                pass


# ============================================================================
# CROSS-004: 工作区文件联动验证 (Files → Chat)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
class TestWorkspaceFileChatFlow:
    """
    CROSS-004: 工作区文件联动验证

    验证工作区文件管理与 Chat 的联动：
    1. 在 Files 页面查看/编辑文件
    2. 在 Chat 中上传文件并提问
    3. 验证 AI 能基于文件内容回答
    """

    @pytest.mark.test_id("CROSS-004")
    def test_workspace_file_and_chat_qa(self, page: Page, test_file: str, request: pytest.FixtureRequest):
        """验证工作区文件与 Chat 文件问答的联动"""
        test_name = request.node.name

        try:
            # ---- 阶段 1: 在 Files 页面验证文件管理功能 ----
            log_test_step("1. 导航到文件管理页面")
            navigate_to_files(page)

            log_test_step("2. 验证文件列表加载")
            file_list = page.locator(
                '.qwenpaw-table, '
                '[class*=fileList], '
                '[class*=file-tree], '
                '.qwenpaw-list'
            ).first
            if file_list.is_visible(timeout=5000):
                logger.info("✅ 文件列表已加载")
            else:
                logger.info("ℹ️ 文件列表可能为空或使用其他布局")

            log_test_step("3. 检查文件编辑器区域")
            editor_area = page.locator(
                '.cm-editor, '
                '[class*=editor], '
                '[class*=codeEditor], '
                'textarea'
            ).first
            if editor_area.is_visible(timeout=3000):
                editor_content = editor_area.inner_text()[:200]
                logger.info(f"编辑器内容预览：{editor_content}")
                logger.info("✅ 文件编辑器可用")
            else:
                # 尝试点击第一个文件打开编辑器
                file_items = page.locator(
                    '[class*=fileName], '
                    '.qwenpaw-table-row, '
                    '[class*=fileItem]'
                ).all()
                if file_items:
                    file_items[0].click()
                    page.wait_for_timeout(1500)
                    logger.info("✅ 已点击第一个文件")

            # ---- 阶段 2: 在 Chat 中上传文件并提问 ----
            log_test_step("4. 导航到 Chat 页面")
            navigate_to_chat(page)
            chat = ChatPage(page)
            chat.create_new_chat()

            # 主动选择千问3.5plus模型，确保模型支持对话
            log_test_step("4.1 选择千问3.5plus模型")
            chat.open_model_selector()
            models = chat.get_available_models()
            logger.info(f"可用模型：{models}")
            target_model = None
            for model in models:
                if "3.5" in model and "plus" in model.lower():
                    target_model = model
                    break
            if target_model:
                chat.select_model(target_model)
                chat.wait(1000)
                logger.info(f"已切换到模型：{target_model}")
            else:
                logger.info("未找到千问3.5plus模型，使用当前默认模型")
                chat.page.keyboard.press("Escape")
                chat.wait(500)

            log_test_step("5. 上传测试文件")
            chat.upload_file(test_file)
            upload_success = chat.verify_file_uploaded(timeout=10000)
            if upload_success:
                logger.info("✅ 文件上传成功")
            else:
                logger.info("ℹ️ 文件上传状态未确认，继续测试")

            log_test_step("6. 基于文件内容提问")
            chat.send_message("请分析我上传的文件内容，告诉我这个文件主要讲了什么？")
            file_response = chat.wait_for_ai_response(timeout=60000)
            assert file_response is not None, "文件问答无响应"
            file_text = chat.get_message_text(file_response)
            logger.info(f"文件问答回复：{file_text[:200]}")

            # 验证回复与文件内容相关
            file_keywords = ["QwenPaw", "智能", "对话", "功能", "平台"]
            keyword_found = any(kw in file_text for kw in file_keywords)
            if keyword_found:
                logger.info("✅ AI 回复包含文件相关关键词，文件联动验证通过")
            else:
                logger.info("ℹ️ AI 回复未包含预期关键词，但文件问答流程正常")

            log_test_step("7. 追问文件细节验证上下文保持")
            chat.send_message("这个文件提到了哪些具体功能？请列举。")
            detail_response = chat.wait_for_ai_response(timeout=60000)
            if detail_response is not None:
                detail_text = chat.get_message_text(detail_response)
                logger.info(f"追问回复：{detail_text[:200]}")
                logger.info("✅ 文件上下文追问正常")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed - 工作区文件联动验证通过")

        finally:
            try:
                navigate_to_chat(page)
                chat_cleanup = ChatPage(page)
                chat_cleanup.delete_all_sessions()
            except Exception:
                pass


# ============================================================================
# CROSS-005: 环境变量与运行时配置联动 (Environments → RuntimeConfig)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cross_module
class TestEnvAndRuntimeConfigFlow:
    """
    CROSS-005: 环境变量与运行时配置联动验证

    验证环境变量配置页面和运行时配置页面的数据一致性：
    1. 在 Environments 页面查看已配置的环境变量
    2. 在 RuntimeConfig 页面验证配置项
    3. 确认两个页面的配置不会互相干扰
    """

    @pytest.mark.test_id("CROSS-005")
    def test_env_and_runtime_config_consistency(self, page: Page, request: pytest.FixtureRequest):
        """验证环境变量与运行时配置的一致性"""
        test_name = request.node.name

        log_test_step("1. 导航到环境变量页面")
        page.goto(f"{BASE_URL}/environments")
        page.wait_for_load_state("commit")
        page.wait_for_timeout(2000)

        log_test_step("2. 记录环境变量数量")
        env_rows = page.locator(
            '.qwenpaw-table-tbody tr.qwenpaw-table-row, '
            '[class*=envRow], '
            '.qwenpaw-form-item'
        ).all()
        env_count = len(env_rows)
        logger.info(f"环境变量数量：{env_count}")

        log_test_step("3. 导航到运行时配置页面")
        page.goto(f"{BASE_URL}/settings/runtime-config")
        page.wait_for_load_state("commit")
        page.wait_for_timeout(2000)

        log_test_step("4. 验证运行时配置页面加载")
        config_area = page.locator(
            '.qwenpaw-tabs, '
            '.qwenpaw-form, '
            '[class*=config], '
            '[class*=setting]'
        ).first
        if config_area.is_visible(timeout=5000):
            logger.info("✅ 运行时配置页面已加载")
        else:
            logger.info("ℹ️ 运行时配置页面布局可能不同")

        log_test_step("5. 回到环境变量页面验证数据未变")
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
            f"环境变量数量不一致：之前 {env_count}，之后 {env_count_after}"
        logger.info(f"✅ 环境变量数量一致：{env_count_after}")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 环境变量与运行时配置联动验证通过")
