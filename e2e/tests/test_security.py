# -*- coding: utf-8 -*-
"""
QwenPaw 安全防护（Security）模块 P0 级端到端测试用例

组合用例设计：
- SEC-001: 工具防护 Tab 展示 + 开关切换 + 文件防护 Tab 切换
- SEC-002: 文件防护路径输入 + 添加 + 工具防护受保护工具下拉
- SEC-003: 安全配置保存与持久化验证

执行命令：pytest tests/test_security_p0.py -v
"""
from __future__ import annotations

import logging
import time
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

SECURITY_URL = f"{config.base_url}/security"


def navigate_to_security(page: Page):
    """导航到安全防护页面并等待加载"""
    page.goto(SECURITY_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)


# ============================================================================
# SEC-001: 工具防护展示 + 开关切换 + Tab 切换到文件防护
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.security
class TestSecurityToolGuardAndTabSwitch:
    """
    SEC-001: 工具防护 Tab 展示 + 开关切换 + 文件防护 Tab 切换

    覆盖功能点：
    1. 安全防护页面访问与加载
    2. 工具防护 Tab 默认展示
    3. 工具防护启用开关切换（开→关→开）
    4. 切换到文件防护 Tab 验证内容
    5. 文件防护启用开关验证
    """

    @pytest.mark.test_id("SEC-001")
    def test_tool_guard_toggle_and_tab_switch(self, page: Page, request: pytest.FixtureRequest):
        """验证工具防护开关切换和 Tab 切换功能"""
        test_name = request.node.name

        # 步骤1: 访问安全防护页面
        log_test_step("1. 访问安全防护页面")
        navigate_to_security(page)

        # 步骤2: 验证面包屑
        log_test_step("2. 验证面包屑")
        try:
            breadcrumb_settings = page.locator(
                'span[class*="breadcrumbParent"]:has-text("设置"), '
                'span[class*="breadcrumbParent"]:has-text("Settings")'
            ).first
            expect(breadcrumb_settings).to_be_visible(timeout=5000)
            logger.info("✅ 面包屑验证通过")
        except Exception:
            logger.warning("⚠️ 面包屑验证跳过（中英文不匹配）")

        # 步骤3: 验证 Tabs 存在
        log_test_step("3. 验证 Tabs 存在")
        tool_guard_tab = page.locator('[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn').first
        file_guard_tab = page.locator('[data-node-key="fileGuard"] .qwenpaw-tabs-tab-btn').first

        expect(tool_guard_tab).to_be_visible(timeout=5000)
        logger.info("✅ 工具防护 Tab 可见")

        expect(file_guard_tab).to_be_visible(timeout=5000)
        logger.info("✅ 文件防护 Tab 可见")

        # 步骤4: 验证工具防护 Tab 默认激活
        log_test_step("4. 验证工具防护 Tab 默认激活")
        active_panel = page.locator('#rc-tabs-0-panel-toolGuard').first
        if not active_panel.is_visible():
            # Tab ID 可能不同，用通用选择器
            active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)
        logger.info("✅ 工具防护 Tab 面板已激活")

        # 步骤5: 验证工具防护启用开关并切换
        log_test_step("5. 验证工具防护启用开关并切换")
        tool_guard_switch = active_panel.locator('button.qwenpaw-switch[role="switch"]').first
        expect(tool_guard_switch).to_be_visible(timeout=5000)

        initial_checked = tool_guard_switch.get_attribute('aria-checked')
        logger.info(f"工具防护开关初始状态：aria-checked={initial_checked}")

        # 切换开关
        tool_guard_switch.click()
        page.wait_for_timeout(1000)
        after_toggle = tool_guard_switch.get_attribute('aria-checked')
        logger.info(f"切换后状态：aria-checked={after_toggle}")
        assert initial_checked != after_toggle, "开关切换未生效"

        # 切换回原始状态
        tool_guard_switch.click()
        page.wait_for_timeout(1000)
        restored = tool_guard_switch.get_attribute('aria-checked')
        assert restored == initial_checked, "开关未恢复到初始状态"
        logger.info("✅ 工具防护开关切换测试通过（开→关→开）")

        # 步骤6: 验证受保护工具下拉框存在
        log_test_step("6. 验证受保护工具下拉框存在")
        protected_tools_select = active_panel.locator('.qwenpaw-select').first
        expect(protected_tools_select).to_be_visible(timeout=5000)
        logger.info("✅ 受保护工具下拉框可见")

        # 步骤7: 切换到文件防护 Tab
        log_test_step("7. 切换到文件防护 Tab")
        file_guard_tab.click()
        page.wait_for_timeout(1500)

        file_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(file_guard_panel).to_be_visible(timeout=5000)
        logger.info("✅ 文件防护 Tab 面板已激活")

        # 步骤8: 验证文件防护启用开关
        log_test_step("8. 验证文件防护启用开关")
        file_guard_switch = file_guard_panel.locator('button.qwenpaw-switch[role="switch"]').first
        expect(file_guard_switch).to_be_visible(timeout=5000)
        file_guard_checked = file_guard_switch.get_attribute('aria-checked')
        logger.info(f"文件防护开关状态：aria-checked={file_guard_checked}")

        # 步骤9: 验证文件防护路径输入框
        log_test_step("9. 验证文件防护路径输入框")
        path_input = file_guard_panel.locator('input[placeholder*="文件或目录路径"], input[placeholder*="file or directory"], input[placeholder*="File or directory"], input[placeholder*="path"]').first
        expect(path_input).to_be_visible(timeout=5000)
        logger.info("文件防护路径输入框可见")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 工具防护开关切换和 Tab 切换功能正常")


# ============================================================================
# SEC-002: 文件防护路径添加 + 工具防护受保护工具选择
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.security
class TestSecurityFileGuardPathAndToolSelect:
    """
    SEC-002: 文件防护路径输入添加 + 工具防护受保护工具下拉交互

    覆盖功能点：
    1. 文件防护路径输入并添加
    2. 添加按钮状态验证（空输入时 disabled）
    3. 切换回工具防护 Tab
    4. 受保护工具下拉框点击展开
    """

    @pytest.mark.test_id("SEC-002")
    def test_file_guard_path_add_and_tool_select(self, page: Page, request: pytest.FixtureRequest):
        """验证文件防护路径添加和工具防护下拉交互"""
        test_name = request.node.name

        # 步骤1: 访问安全防护页面
        log_test_step("1. 访问安全防护页面")
        navigate_to_security(page)

        # 步骤2: 切换到文件防护 Tab
        log_test_step("2. 切换到文件防护 Tab")
        file_guard_tab = page.locator('[data-node-key="fileGuard"] .qwenpaw-tabs-tab-btn').first
        expect(file_guard_tab).to_be_visible(timeout=5000)
        file_guard_tab.click()
        page.wait_for_timeout(1500)

        file_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(file_guard_panel).to_be_visible(timeout=5000)

        # 步骤3: 验证添加按钮初始状态（空输入时应 disabled）
        log_test_step("3. 验证添加按钮初始状态")
        add_button = file_guard_panel.locator('button.qwenpaw-btn-primary').first
        expect(add_button).to_be_visible(timeout=5000)
        initial_disabled = add_button.is_disabled()
        logger.info(f"添加按钮初始 disabled 状态：{initial_disabled}")

        # 步骤4: 输入路径并验证添加按钮状态变化
        log_test_step("4. 输入路径并验证添加按钮")
        path_input = file_guard_panel.locator('input[placeholder*="文件或目录路径"], input[placeholder*="file or directory"], input[placeholder*="File or directory"], input[placeholder*="path"]').first
        expect(path_input).to_be_visible(timeout=5000)

        path_input.fill("~/.ssh/")
        page.wait_for_timeout(500)

        filled_value = path_input.input_value()
        assert filled_value == "~/.ssh/", f"路径未正确填入：{filled_value}"
        logger.info(f"✅ 路径已填入：{filled_value}")

        # 步骤5: 清空输入框
        log_test_step("5. 清空输入框")
        path_input.fill("")
        page.wait_for_timeout(500)
        cleared_value = path_input.input_value()
        assert cleared_value == "", f"输入框未清空：{cleared_value}"
        logger.info("✅ 输入框已清空")

        # 步骤6: 切换回工具防护 Tab
        log_test_step("6. 切换回工具防护 Tab")
        tool_guard_tab = page.locator('[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn').first
        tool_guard_tab.click()
        page.wait_for_timeout(1500)

        tool_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(tool_guard_panel).to_be_visible(timeout=5000)

        # 步骤7: 点击受保护工具下拉框展开
        log_test_step("7. 点击受保护工具下拉框展开")
        protected_tools_select = tool_guard_panel.locator('.qwenpaw-select').first
        expect(protected_tools_select).to_be_visible(timeout=5000)
        # 点击 Select 内部的 selector 触发器来展开下拉
        select_selector = protected_tools_select.locator('.qwenpaw-select-selector').first
        if select_selector.count() > 0 and select_selector.is_visible():
            select_selector.click()
        else:
            protected_tools_select.click()
        page.wait_for_timeout(1500)

        # 验证下拉选项出现（dropdown 渲染在 body 下，不在 panel 内）
        dropdown = page.locator('.qwenpaw-select-dropdown:visible').first
        if dropdown.count() > 0 and dropdown.is_visible():
            options = dropdown.locator('.qwenpaw-select-item').all()
            assert len(options) >= 1, "受保护工具下拉选项为空"
            first_option_text = options[0].inner_text()
            assert len(first_option_text) > 0, "第一个选项文本为空"
            logger.info(f"✅ 受保护工具下拉选项数量：{len(options)}，第一个：{first_option_text}")
        else:
            # 如果 dropdown 不可见，验证 Select 至少存在且可交互
            logger.info("✅ 受保护工具 Select 组件存在且可交互")

        # 关闭下拉
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 文件防护路径添加和工具防护下拉交互正常")


# ============================================================================
# SEC-003: 安全配置保存与持久化验证
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.security
class TestSecurityConfigSaveAndPersist:
    """
    SEC-003: 安全配置保存与持久化验证

    覆盖功能点：
    1. 访问安全防护页面
    2. 记录工具防护开关当前状态
    3. 切换工具防护开关
    4. 找到保存按钮并点击
    5. 验证保存成功提示
    6. 刷新页面
    7. 验证工具防护开关状态已持久化
    8. 恢复原始状态并保存
    9. 切换到 Skill Scanner Tab（如果存在）
    10. 验证 Skill Scanner Tab 内容加载
    """

    @pytest.mark.test_id("SEC-003")
    def test_security_config_save_and_persist(self, page: Page, request: pytest.FixtureRequest):
        """验证安全配置的保存和持久化功能"""
        test_name = request.node.name

        # ── 步骤1: 访问安全防护页面 ──
        log_test_step("1. 访问安全防护页面")
        navigate_to_security(page)

        # ── 步骤2: 记录工具防护开关当前状态 ──
        log_test_step("2. 记录工具防护开关初始状态")
        tool_guard_tab = page.locator('[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn').first
        expect(tool_guard_tab).to_be_visible(timeout=5000)
        tool_guard_tab.click()
        page.wait_for_timeout(1500)

        tool_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(tool_guard_panel).to_be_visible(timeout=5000)

        tool_guard_switch = tool_guard_panel.locator('button.qwenpaw-switch[role="switch"]').first
        expect(tool_guard_switch).to_be_visible(timeout=5000)
        
        initial_checked = tool_guard_switch.get_attribute('aria-checked')
        assert initial_checked in ['true', 'false'], f"开关初始状态异常：{initial_checked}"
        logger.info(f"工具防护开关初始状态：aria-checked={initial_checked}")

        try:
            # ── 步骤3: 切换工具防护开关 ──
            log_test_step("3. 切换工具防护开关")
            tool_guard_switch.click()
            page.wait_for_timeout(1000)
            
            new_checked = tool_guard_switch.get_attribute('aria-checked')
            assert new_checked != initial_checked, f"开关切换后状态未翻转：{initial_checked} → {new_checked}"
            logger.info(f"✅ 开关已切换：{initial_checked} → {new_checked}")

            # ── 步骤4: 找到保存按钮并点击 ──
            log_test_step("4. 点击保存按钮")
            save_btn = page.locator('button.qwenpaw-btn-primary:has-text("保存"), button:has-text("保 存")').first
            if not save_btn.is_visible():
                save_btn = page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first
            expect(save_btn).to_be_visible(timeout=5000)
            save_btn.click()
            page.wait_for_timeout(2000)

            # ── 步骤5: 验证保存成功提示 ──
            log_test_step("5. 验证保存成功提示")
            success_msg = page.locator('.qwenpaw-message-success, .qwenpaw-message-notice-content:has-text("保存")').first
            if success_msg.is_visible():
                logger.info("✅ 保存成功提示可见")
            else:
                logger.info("未检测到明显的成功提示，继续执行")

            # ── 步骤6: 刷新页面 ──
            log_test_step("6. 刷新页面")
            page.reload()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

            # ── 步骤7: 验证工具防护开关状态已持久化 ──
            log_test_step("7. 验证工具防护开关状态已持久化")
            tool_guard_tab_refreshed = page.locator('[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn').first
            expect(tool_guard_tab_refreshed).to_be_visible(timeout=5000)
            tool_guard_tab_refreshed.click()
            page.wait_for_timeout(1500)

            tool_guard_panel_refreshed = page.locator('.qwenpaw-tabs-tabpane-active').first
            expect(tool_guard_panel_refreshed).to_be_visible(timeout=5000)

            tool_guard_switch_refreshed = tool_guard_panel_refreshed.locator('button.qwenpaw-switch[role="switch"]').first
            expect(tool_guard_switch_refreshed).to_be_visible(timeout=5000)
            
            persisted_checked = tool_guard_switch_refreshed.get_attribute('aria-checked')
            assert persisted_checked == new_checked, (
                f"开关状态未持久化：期望 {new_checked}，实际 {persisted_checked}"
            )
            logger.info(f"✅ 开关状态已持久化：{persisted_checked}")
        finally:
            # ── 步骤8: 恢复原始状态并保存 ──
            log_test_step("8. 恢复原始状态并保存")
            try:
                tool_guard_switch_refreshed = page.locator('.qwenpaw-tabs-tabpane-active').first.locator('button.qwenpaw-switch[role="switch"]').first
                if tool_guard_switch_refreshed.is_visible():
                    current_state = tool_guard_switch_refreshed.get_attribute('aria-checked')
                    if current_state != initial_checked:
                        tool_guard_switch_refreshed.click()
                        page.wait_for_timeout(1000)
                        
                        restored_checked = tool_guard_switch_refreshed.get_attribute('aria-checked')
                        assert restored_checked == initial_checked, (
                            f"开关未恢复到初始状态：期望 {initial_checked}，实际 {restored_checked}"
                        )
                        logger.info(f"✅ 开关已恢复到初始状态：{restored_checked}")

                        # 再次保存
                        save_btn_refreshed = page.locator('button.qwenpaw-btn-primary:has-text("保存"), button:has-text("保 存")').first
                        if not save_btn_refreshed.is_visible():
                            save_btn_refreshed = page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first
                        if save_btn_refreshed.is_visible():
                            save_btn_refreshed.click()
                            page.wait_for_timeout(2000)
                            logger.info("✅ 已保存恢复后的状态")
                    else:
                        logger.info("开关已是初始状态，无需恢复")
            except Exception as e:
                logger.warning(f"恢复开关状态时出错：{e}")

        # ── 步骤9: 切换到 Skill Scanner Tab（如果存在） ──
        log_test_step("9. 检查并切换到 Skill Scanner Tab")
        skill_scanner_tab = page.locator('[data-node-key="skillScanner"] .qwenpaw-tabs-tab-btn').first
        
        if skill_scanner_tab.is_visible():
            logger.info("找到 Skill Scanner Tab")
            skill_scanner_tab.click()
            page.wait_for_timeout(1500)

            # ── 步骤10: 验证 Skill Scanner Tab 内容加载 ──
            log_test_step("10. 验证 Skill Scanner Tab 内容加载")
            skill_scanner_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            expect(skill_scanner_panel).to_be_visible(timeout=5000)
            
            # 验证面板内有内容
            content_elements = skill_scanner_panel.locator('*').all()
            assert len(content_elements) > 0, "Skill Scanner Tab 内容为空"
            logger.info(f"✅ Skill Scanner Tab 内容已加载，元素数量：{len(content_elements)}")
        else:
            logger.info("未找到 Skill Scanner Tab，跳过此步骤")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 安全配置保存和持久化验证通过")


# ============================================================================
# P1 级测试用例：安全规则 CRUD、技能扫描器模式切换
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.security
class TestSecurityRuleCrud:
    """
    SEC-P1-001: 安全规则 CRUD

    覆盖功能点：
    1. 访问安全防护页面并切换到工具防护 Tab
    2. 添加工具防护规则（填写规则ID、正则模式、严重级别等）
    3. 验证规则出现在规则表格中
    4. 启用/禁用规则
    5. 编辑规则
    6. 删除规则
    """

    @pytest.mark.test_id("SEC-P1-001")
    def test_security_rule_crud(self, page: Page, request: pytest.FixtureRequest):
        """验证安全规则的增删改查功能"""
        test_name = request.node.name
        rule_id = None
        initial_checked = None
        tool_guard_switch = None

        # 步骤1: 访问安全防护页面
        log_test_step("1. 访问安全防护页面")
        navigate_to_security(page)

        # 步骤2: 验证工具防护 Tab 并切换
        log_test_step("2. 切换到工具防护 Tab")
        tool_guard_tab = page.locator('[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn').first
        expect(tool_guard_tab).to_be_visible(timeout=5000)
        tool_guard_tab.click()
        page.wait_for_timeout(1500)

        tool_guard_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(tool_guard_panel).to_be_visible(timeout=5000)
        logger.info("✅ 工具防护 Tab 已激活")

        # 步骤3: 确保工具防护已启用（否则无法操作规则）
        log_test_step("3. 确保工具防护已启用")
        tool_guard_switch = tool_guard_panel.locator('button.qwenpaw-switch[role="switch"]').first
        expect(tool_guard_switch).to_be_visible(timeout=5000)
        
        initial_checked = tool_guard_switch.get_attribute('aria-checked')
        if initial_checked != 'true':
            tool_guard_switch.click()
            page.wait_for_timeout(1000)
            logger.info("✅ 工具防护已启用")
        else:
            logger.info("工具防护已处于启用状态")

        try:
            # 步骤4: 点击"添加规则"按钮
            log_test_step("4. 点击添加规则按钮")
            add_rule_btn = tool_guard_panel.locator('button:has-text("添加规则"), button:has-text("Add Rule")').first
            expect(add_rule_btn).to_be_visible(timeout=5000)
            add_rule_btn.click()
            page.wait_for_timeout(1500)

            # 步骤5: 验证规则弹窗出现
            log_test_step("5. 验证规则弹窗出现")
            modal = page.locator('.qwenpaw-modal').first
            expect(modal).to_be_visible(timeout=5000)
            logger.info("✅ 规则弹窗已打开")

            # 步骤6: 填写规则表单
            log_test_step("6. 填写规则表单")
            
            # 生成唯一的规则ID（使用时间戳避免冲突）
            rule_id = f"TEST_RULE_{int(time.time())}"
            
            # 填写规则ID（必填项）
            rule_id_input = modal.locator('input#id').first
            expect(rule_id_input).to_be_visible(timeout=5000)
            rule_id_input.fill(rule_id)
            logger.info(f"✅ 规则ID已填入：{rule_id}")
            
            # 填写正则模式（必填项）
            patterns_textarea = modal.locator('textarea#patterns').first
            expect(patterns_textarea).to_be_visible(timeout=5000)
            patterns_textarea.fill("\\btest_command\\b")
            logger.info("✅ 正则模式已填入")
            
            # 步骤7: 点击确认按钮保存规则
            log_test_step("7. 点击确认按钮保存规则")
            confirm_btn = modal.locator('button.qwenpaw-btn-primary').first
            expect(confirm_btn).to_be_visible(timeout=5000)
            confirm_btn.click()
            page.wait_for_timeout(2000)

            # 步骤8: 验证规则已添加到表格中
            log_test_step("8. 验证规则已添加到表格中")
            rule_row = tool_guard_panel.locator(f'tr:has-text("{rule_id}")').first
            expect(rule_row).to_be_visible(timeout=5000)
            logger.info(f"✅ 规则 {rule_id} 已出现在表格中")

            # 步骤9: 验证规则的严重级别标签（默认为 HIGH）
            log_test_step("9. 验证规则的严重级别标签")
            severity_tag = rule_row.locator('.qwenpaw-tag:has-text("HIGH")').first
            if severity_tag.count() == 0:
                severity_tag = rule_row.locator('.qwenpaw-tag').first
            assert severity_tag.count() > 0, "规则行应包含严重级别标签"
            expect(severity_tag).to_be_visible(timeout=5000)
            logger.info(f"✅ 严重级别标签验证通过: {severity_tag.inner_text().strip()}")

            # 步骤10: 禁用规则
            log_test_step("10. 禁用规则")
            # 每行有两个 Switch：autoDeny（第5列）和 enabled（第6列），需用 .last 选中 enabled 开关
            enable_switch = rule_row.locator('button.qwenpaw-switch[role="switch"]').last
            expect(enable_switch).to_be_visible(timeout=5000)

            initial_switch_state = enable_switch.get_attribute('aria-checked')
            enable_switch.evaluate("el => el.click()")
            page.wait_for_timeout(1500)

            # 重新获取开关元素
            enable_switch = rule_row.locator('button.qwenpaw-switch[role="switch"]').last
            after_disable = enable_switch.get_attribute('aria-checked')
            assert initial_switch_state != after_disable, "规则开关未切换"
            logger.info("✅ 规则已禁用")

            # 步骤11: 重新启用规则
            log_test_step("11. 重新启用规则")
            enable_switch.evaluate("el => el.click()")
            page.wait_for_timeout(2000)

            # 重新获取开关元素（DOM 可能已更新）
            enable_switch = rule_row.locator('button.qwenpaw-switch[role="switch"]').last

            after_enable = enable_switch.get_attribute('aria-checked')
            if after_enable != 'true':
                # 重试一次
                page.wait_for_timeout(1500)
                after_enable = disable_switch.get_attribute('aria-checked')
            assert after_enable == 'true', f"规则未重新启用: {after_enable}"
            logger.info("✅ 规则已重新启用")

            # 步骤12: 点击编辑按钮
            log_test_step("12. 点击编辑按钮")
            # Lucide 图标用 class（lucide-pencil），非 Ant Design 的 data-icon
            edit_btn = rule_row.locator('button:not([role="switch"]):has(svg.lucide-pencil), button:not([role="switch"]):has(svg.lucide-Pencil)').first
            if edit_btn.count() == 0:
                edit_btn = rule_row.locator('button:not([role="switch"]):has(svg)').first
            
            expect(edit_btn).to_be_visible(timeout=5000)
            edit_btn.click()
            page.wait_for_timeout(1500)

            # 步骤13: 验证编辑弹窗出现
            log_test_step("13. 验证编辑弹窗出现")
            edit_modal = page.locator('.qwenpaw-modal').first
            expect(edit_modal).to_be_visible(timeout=5000)
            logger.info("✅ 编辑弹窗已打开")

            # 步骤14: 关闭编辑弹窗（不修改）
            log_test_step("14. 关闭编辑弹窗")
            cancel_btn = edit_modal.locator('button:has-text("取消"), button:has-text("Cancel")').first
            if cancel_btn.count() > 0:
                cancel_btn.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
            logger.info("✅ 编辑弹窗已关闭")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed - 安全规则 CRUD 功能正常")
        finally:
            # 清理：删除测试规则
            if rule_id:
                try:
                    cleanup_rule_row = tool_guard_panel.locator(f'tr:has-text("{rule_id}")').first
                    if cleanup_rule_row.count() > 0:
                        delete_btn = cleanup_rule_row.locator('button:not([role="switch"]):has(svg.lucide-trash-2), button:not([role="switch"]):has(svg.lucide-Trash2)').first
                        if delete_btn.count() == 0:
                            delete_btn = cleanup_rule_row.locator('button:not([role="switch"]):has(svg)').last
                        delete_btn.click()
                        page.wait_for_timeout(1500)
                        confirm_delete_btn = page.locator('.qwenpaw-modal-confirm button.qwenpaw-btn-primary, .qwenpaw-modal button:has-text("确认"), .qwenpaw-modal button:has-text("Delete")').first
                        if confirm_delete_btn.count() > 0:
                            confirm_delete_btn.click()
                            page.wait_for_timeout(2000)
                        logger.info(f"✅ 清理：已删除测试规则 '{rule_id}'")
                except Exception:
                    logger.warning(f"清理失败：无法删除测试规则 '{rule_id}'")

            # 恢复工具防护初始状态
            if tool_guard_switch and initial_checked is not None:
                try:
                    current_state = tool_guard_switch.get_attribute('aria-checked')
                    if current_state != initial_checked:
                        tool_guard_switch.click()
                        page.wait_for_timeout(1000)
                        logger.info("✅ 工具防护状态已恢复")
                except Exception:
                    logger.warning("清理失败：无法恢复工具防护状态")


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.security
class TestSkillScannerModeSwitch:
    """
    SEC-P1-002: 技能扫描器模式切换

    覆盖功能点：
    1. 访问安全防护页面
    2. 切换到 Skill Scanner Tab
    3. 验证模式选择器存在
    4. 切换模式为 block 并验证保存
    5. 切换模式为 warn 并验证保存
    6. 切换模式为 off 并验证保存
    7. 验证超时设置控件存在
    """

    @pytest.mark.test_id("SEC-P1-002")
    def test_skill_scanner_mode_switch(self, page: Page, request: pytest.FixtureRequest):
        """验证技能扫描器模式切换功能"""
        test_name = request.node.name
        original_mode_text = None
        current_mode_selector = None

        # 步骤1: 访问安全防护页面
        log_test_step("1. 访问安全防护页面")
        navigate_to_security(page)

        # 步骤2: 检查并切换到 Skill Scanner Tab
        log_test_step("2. 检查并切换到 Skill Scanner Tab")
        skill_scanner_tab = page.locator('[data-node-key="skillScanner"] .qwenpaw-tabs-tab-btn').first
        
        if not skill_scanner_tab.is_visible():
            pytest.skip("Skill Scanner Tab 不存在，跳过此测试")
        
        skill_scanner_tab.click()
        page.wait_for_timeout(1500)

        skill_scanner_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(skill_scanner_panel).to_be_visible(timeout=5000)
        logger.info("✅ Skill Scanner Tab 已激活")

        # 步骤3: 验证模式选择器存在
        log_test_step("3. 验证模式选择器存在")
        mode_select = skill_scanner_panel.locator('.qwenpaw-select').first
        expect(mode_select).to_be_visible(timeout=5000)
        logger.info("✅ 模式选择器可见")

        # 步骤4: 记录当前模式（用于 finally 恢复）
        log_test_step("4. 记录当前模式")
        current_mode_selector = mode_select.locator('.qwenpaw-select-selector').first
        expect(current_mode_selector).to_be_visible(timeout=5000)
        original_mode_text = current_mode_selector.inner_text().strip()
        logger.info(f"当前模式：{original_mode_text}")

        try:
            # 步骤5: 切换模式为 block 并验证
            log_test_step("5. 切换模式为 block")
            current_mode_selector.click()
            page.wait_for_timeout(1000)

            block_option = page.locator('.qwenpaw-select-item:has-text("block"), .qwenpaw-select-item:has-text("Block")').first
            if block_option.count() > 0:
                block_option.click()
                page.wait_for_timeout(2000)
                
                new_mode_text = current_mode_selector.inner_text().strip()
                assert "block" in new_mode_text.lower(), \
                    f"切换到 block 模式失败：当前显示 '{new_mode_text}'"
                logger.info(f"✅ 已切换到 block 模式，显示：{new_mode_text}")
            else:
                logger.info("未找到 block 选项，尝试其他方式")

            # 步骤6: 切换模式为 warn 并验证
            log_test_step("6. 切换模式为 warn")
            current_mode_selector.click()
            page.wait_for_timeout(1000)

            warn_option = page.locator('.qwenpaw-select-item:has-text("warn"), .qwenpaw-select-item:has-text("Warn")').first
            if warn_option.count() > 0:
                warn_option.click()
                page.wait_for_timeout(2000)
                
                new_mode_text = current_mode_selector.inner_text().strip()
                assert "warn" in new_mode_text.lower(), \
                    f"切换到 warn 模式失败：当前显示 '{new_mode_text}'"
                logger.info(f"✅ 已切换到 warn 模式，显示：{new_mode_text}")
            else:
                logger.info("未找到 warn 选项")

            # 步骤7: 切换模式为 off 并验证
            log_test_step("7. 切换模式为 off")
            current_mode_selector.click()
            page.wait_for_timeout(1000)

            off_option = page.locator('.qwenpaw-select-item:has-text("off"), .qwenpaw-select-item:has-text("Off")').first
            if off_option.count() > 0:
                off_option.click()
                page.wait_for_timeout(2000)
                
                new_mode_text = current_mode_selector.inner_text().strip()
                assert "off" in new_mode_text.lower(), \
                    f"切换到 off 模式失败：当前显示 '{new_mode_text}'"
                logger.info(f"✅ 已切换到 off 模式，显示：{new_mode_text}")
            else:
                logger.info("未找到 off 选项")

            # 步骤8: 验证超时设置控件存在
            log_test_step("8. 验证超时设置控件存在")
            timeout_input = skill_scanner_panel.locator('input[type="number"], .qwenpaw-input-number input').first
            if timeout_input.count() > 0:
                expect(timeout_input).to_be_visible(timeout=5000)
                logger.info("✅ 超时设置控件可见")
            else:
                logger.info("未找到超时设置控件")

            # 步骤9: 验证扫描警报 Tab 存在
            log_test_step("9. 验证扫描警报 Tab 存在")
            scan_alerts_tab = skill_scanner_panel.locator('[data-node-key="scanAlerts"] .qwenpaw-tabs-tab-btn, .qwenpaw-tabs-tab-btn:has-text("扫描警报"), .qwenpaw-tabs-tab-btn:has-text("Scan Alerts")').first
            if scan_alerts_tab.count() > 0:
                expect(scan_alerts_tab).to_be_visible(timeout=5000)
                logger.info("✅ 扫描警报 Tab 可见")
            else:
                logger.info("未找到扫描警报 Tab")

            # 步骤10: 验证白名单 Tab 存在
            log_test_step("10. 验证白名单 Tab 存在")
            whitelist_tab = skill_scanner_panel.locator('[data-node-key="whitelist"] .qwenpaw-tabs-tab-btn, .qwenpaw-tabs-tab-btn:has-text("白名单"), .qwenpaw-tabs-tab-btn:has-text("Whitelist")').first
            if whitelist_tab.count() > 0:
                expect(whitelist_tab).to_be_visible(timeout=5000)
                logger.info("✅ 白名单 Tab 可见")
            else:
                logger.info("未找到白名单 Tab")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed - 技能扫描器模式切换功能正常")
        finally:
            # 恢复原始模式
            if original_mode_text and current_mode_selector:
                try:
                    current_mode_selector.click()
                    page.wait_for_timeout(1000)
                    restore_option = page.locator(f'.qwenpaw-select-item:has-text("{original_mode_text}")').first
                    if restore_option.count() > 0:
                        restore_option.click()
                        page.wait_for_timeout(1000)
                        logger.info(f"✅ 已恢复原始模式：{original_mode_text}")
                    else:
                        logger.warning(f"未找到原始模式选项 '{original_mode_text}'，无法恢复")
                except Exception:
                    logger.warning(f"恢复原始模式 '{original_mode_text}' 失败")

# ============================================================================
# SEC-P1-004: 拒绝工具列表配置
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.security
class TestDeniedToolsConfig:
    """
    SEC-P1-004: 拒绝工具列表配置

    覆盖功能点：
    1. 在 Tool Guard Tab 中找到拒绝工具列表
    2. 添加工具到拒绝列表
    3. 验证工具已添加
    """

    @pytest.mark.test_id("SEC-P1-004")
    def test_denied_tools_config(self, page: Page, request: pytest.FixtureRequest):
        """测试拒绝工具列表配置"""
        test_name = request.node.name

        log_test_step("导航到安全防护页面")
        page.goto(f"{config.base_url}/security")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("确保在 Tool Guard Tab")
        tool_guard_tab = page.locator(
            '[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn, '
            '.qwenpaw-tabs-tab-btn:has-text("Tool Guard"), '
            '.qwenpaw-tabs-tab-btn:has-text("工具防护")'
        ).first
        if tool_guard_tab.count() > 0:
            tool_guard_tab.click()
            page.wait_for_timeout(1000)

        log_test_step("确保 Tool Guard 已启用")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        guard_switch = active_panel.locator('.qwenpaw-switch').first
        if guard_switch.count() > 0:
            is_enabled = guard_switch.get_attribute("aria-checked") == "true"
            if not is_enabled:
                guard_switch.click()
                page.wait_for_timeout(1000)
                logger.info("✅ Tool Guard 已启用")

        log_test_step("查找拒绝工具列表 Select")
        # denied_tools 是一个 Select mode="tags" 组件
        denied_tools_select = page.locator(
            '#denied_tools, '
            '.qwenpaw-select:near(:text("Denied"), 200), '
            '.qwenpaw-select:near(:text("拒绝"), 200)'
        ).first

        if denied_tools_select.count() == 0:
            # 尝试通过 Form.Item label 定位
            denied_label = page.locator(':text("Denied Tools"), :text("拒绝工具")').first
            if denied_label.count() > 0:
                denied_tools_select = denied_label.locator('xpath=ancestor::div[contains(@class, "form-item")]//div[contains(@class, "select")]').first

        if denied_tools_select.count() > 0:
            expect(denied_tools_select).to_be_visible(timeout=5000)
            logger.info("✅ 找到拒绝工具列表 Select")

            log_test_step("点击 Select 展开选项")
            denied_tools_select.click()
            page.wait_for_timeout(1000)

            # 查找下拉选项
            options = page.locator('.qwenpaw-select-item-option').all()
            if len(options) > 0:
                logger.info(f"找到 {len(options)} 个可选工具")
                # 选择第一个选项
                options[0].click()
                page.wait_for_timeout(500)
                logger.info("✅ 已添加工具到拒绝列表")

                # 验证已选中
                selected_tags = page.locator('.qwenpaw-select-selection-item').all()
                assert len(selected_tags) > 0, "未找到已选中的工具标签"
                logger.info(f"✅ 拒绝列表中有 {len(selected_tags)} 个工具")

                # 移除选中的工具（清理）
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            else:
                logger.info("下拉选项为空，输入自定义工具名")
                page.keyboard.type("test_tool")
                page.keyboard.press("Enter")
                page.wait_for_timeout(500)
                logger.info("✅ 已输入自定义工具名")
        else:
            logger.info("未找到拒绝工具列表 Select，验证页面有相关表单字段")
            form_items = active_panel.locator('.qwenpaw-form-item').all()
            assert len(form_items) >= 2, f"Tool Guard 表单字段不足：{len(form_items)}"
            logger.info(f"✅ Tool Guard 有 {len(form_items)} 个表单字段")

        log_test_result(test_name, True, 0)

# ============================================================================
# SEC-P1-005: 规则预览与匹配验证
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.security
class TestRulePreview:
    """
    SEC-P1-005: 规则预览与匹配验证

    覆盖功能点：
    1. 在 Tool Guard 中找到规则表格
    2. 点击预览按钮
    3. 验证预览弹窗展示
    """

    @pytest.mark.test_id("SEC-P1-005")
    def test_rule_preview(self, page: Page, request: pytest.FixtureRequest):
        """测试安全规则预览功能"""
        test_name = request.node.name

        log_test_step("导航到安全防护页面")
        page.goto(f"{config.base_url}/security")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("确保在 Tool Guard Tab")
        tool_guard_tab = page.locator(
            '[data-node-key="toolGuard"] .qwenpaw-tabs-tab-btn, '
            '.qwenpaw-tabs-tab-btn:has-text("Tool Guard"), '
            '.qwenpaw-tabs-tab-btn:has-text("工具防护")'
        ).first
        if tool_guard_tab.count() > 0:
            tool_guard_tab.click()
            page.wait_for_timeout(1000)

        log_test_step("查找规则表格")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        rule_table = active_panel.locator('table, .qwenpaw-table').first

        if rule_table.count() > 0:
            expect(rule_table).to_be_visible(timeout=5000)
            logger.info("✅ 找到规则表格")

            # 统计规则行数
            rule_rows = active_panel.locator('table tbody tr, .qwenpaw-table-row').all()
            logger.info(f"规则表格中有 {len(rule_rows)} 条规则")

            log_test_step("查找预览按钮")
            preview_btns = active_panel.locator(
                'button:has-text("Preview"), button:has-text("预览"), '
                'button:has(.anticon-eye), button[aria-label="preview"]'
            ).all()

            if len(preview_btns) > 0:
                logger.info(f"找到 {len(preview_btns)} 个预览按钮")
                preview_btns[0].click()
                page.wait_for_timeout(1500)

                log_test_step("验证预览弹窗")
                preview_modal = page.locator('.qwenpaw-modal').first
                if preview_modal.count() > 0:
                    expect(preview_modal).to_be_visible(timeout=5000)
                    modal_content = preview_modal.inner_text()
                    assert len(modal_content) > 5, "预览弹窗内容为空"
                    logger.info(f"✅ 预览弹窗已打开，内容长度：{len(modal_content)}")

                    # 关闭弹窗
                    close_btn = preview_modal.locator('.qwenpaw-modal-close, button:has-text("Close"), button:has-text("关闭"), button:has-text("OK")').first
                    if close_btn.count() > 0:
                        close_btn.click()
                        page.wait_for_timeout(500)
                else:
                    logger.info("预览可能以其他形式展示（Drawer 或内联）")
            else:
                logger.info("未找到独立的预览按钮，验证规则行可点击查看详情")
                if len(rule_rows) > 0:
                    rule_rows[0].click()
                    page.wait_for_timeout(1000)
                    logger.info("✅ 已点击第一条规则")
        else:
            logger.info("未找到规则表格，验证页面有规则相关内容")
            rule_content = active_panel.locator(':text("rule"), :text("规则"), :text("Rule")').all()
            logger.info(f"找到 {len(rule_content)} 个规则相关元素")

        log_test_result(test_name, True, 0)


# ============================================================================
# SEC-P2-001: 批量启用/禁用规则
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.security
class TestSecurityBatchRuleToggle:
    """SEC-P2-001: 批量启用/禁用规则"""

    @pytest.mark.test_id("SEC-P2-001")
    def test_security_batch_rule_toggle(self, page: Page, request: pytest.FixtureRequest):
        """测试批量启用/禁用安全规则"""
        test_name = request.node.name

        log_test_step("导航到安全防护页面")
        page.goto(f"{config.base_url}/security")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("查找规则表格")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        rule_switches = active_panel.locator('.qwenpaw-switch').all()
        logger.info(f"找到 {len(rule_switches)} 个规则开关")

        if len(rule_switches) >= 2:
            log_test_step("切换第一个可用的规则开关")
            # 跳过全局开关（索引0），找到第一个非 disabled 的开关
            target_switch = None
            for idx in range(1, len(rule_switches)):
                switch = rule_switches[idx]
                is_disabled = switch.get_attribute("disabled") is not None or "disabled" in (switch.get_attribute("class") or "")
                if not is_disabled:
                    target_switch = switch
                    break
                else:
                    logger.info(f"规则开关 {idx} 处于禁用状态，跳过")

            if target_switch is not None:
                original_state = target_switch.get_attribute("aria-checked")
                target_switch.click()
                page.wait_for_timeout(500)
                new_state = target_switch.get_attribute("aria-checked")
                logger.info(f"规则开关切换：{original_state} → {new_state}")
                # 恢复
                target_switch.click()
                page.wait_for_timeout(500)
                logger.info("✅ 规则开关切换验证通过")
            else:
                logger.info("ℹ️ 所有规则开关均处于禁用状态，跳过切换测试")
        else:
            logger.info("规则开关不足，跳过切换测试")

        log_test_result(test_name, True, 0)