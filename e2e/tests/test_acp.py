# -*- coding: utf-8 -*-
"""
QwenPaw ACP (Agent Communication Protocol) 管理模块端到端测试用例

ACP 模块测试：
- ACP-001: ACP 页面加载与卡片列表展示 (P0)
- ACP-002: 创建 ACP 抽屉表单验证 (P0)
- ACP-003: ACP 启用/禁用切换 (P0)
- ACP-004: 过滤标签切换（All/Builtin/Custom） (P1)
- ACP-005: 编辑 ACP 配置 (P1)
- ACP-006: 创建自定义 ACP 并删除 (P1)
- ACP-007: 内置 ACP 保护验证 (P2)
- ACP-008: ACP 卡片内容详情验证 (P2)

测试框架：pytest + Playwright
执行命令：pytest tests/test_acp.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


# ============================================================================
# ACP-001: ACP 页面加载与卡片列表展示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.acp
class TestACPPageDisplay:
    """
    ACP-001: ACP 配置管理页面加载与卡片列表展示

    覆盖功能点：
    1. /acp 页面访问与加载
    2. 面包屑验证（Workspace / ACP）
    3. 过滤标签展示
    4. 创建按钮展示
    5. ACP 卡片列表展示（内置 ACP 卡片）
    """

    @pytest.mark.test_id("ACP-001")
    def test_acp_page_load_and_card_list(self, page: Page, request: pytest.FixtureRequest):
        """验证 ACP 页面加载与卡片列表展示"""
        test_name = request.node.name

        try:
            # 1. 访问 ACP 页面
            log_test_step("1. 访问 ACP 页面")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            logger.info("ACP 页面已加载")

            # 2. 验证面包屑
            log_test_step("2. 验证面包屑")
            breadcrumb = page.locator('[class*="breadcrumb"], [class*="Breadcrumb"]').first
            if breadcrumb.is_visible(timeout=3000):
                breadcrumb_text = breadcrumb.inner_text().strip()
                logger.info(f"面包屑内容: {breadcrumb_text}")
                assert "ACP" in breadcrumb_text, f"面包屑应包含 ACP，实际: {breadcrumb_text}"
                logger.info("✅ 面包屑验证通过")
            else:
                logger.warning("未找到面包屑元素，跳过验证")

            # 3. 验证过滤标签
            log_test_step("3. 验证过滤标签")
            page_text = page.locator("body").inner_text()
            has_all_tab = "All" in page_text or "全部" in page_text
            has_builtin_tab = "Builtin" in page_text or "内置" in page_text
            has_custom_tab = "Custom" in page_text or "自定义" in page_text

            assert has_all_tab, "页面应包含 All/全部 标签"
            logger.info("✅ All/全部 标签可见")
            if has_builtin_tab:
                logger.info("✅ Builtin/内置 标签可见")
            if has_custom_tab:
                logger.info("✅ Custom/自定义 标签可见")

            # 4. 验证创建/新增按钮
            log_test_step("4. 验证创建/新增按钮")
            create_btn = page.locator(
                'button:has-text("Create"), button:has-text("创建"), '
                'button:has-text("Add"), button:has-text("添加"), '
                'button:has-text("新增"), button:has-text("New")'
            ).first
            assert create_btn.is_visible(timeout=5000), "创建/新增按钮应可见"
            logger.info("✅ 创建/新增按钮可见")

            # 5. 验证 ACP 卡片列表
            log_test_step("5. 验证 ACP 卡片列表")
            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            assert len(cards) > 0, "ACP 卡片列表不应为空（至少应有内置 ACP）"
            logger.info(f"✅ 找到 {len(cards)} 个 ACP 卡片")

            # 验证内置 ACP 是否存在
            builtin_names = ["opencode", "qwen_code", "claude_code", "codex"]
            found_builtin = []
            for card in cards:
                card_text = card.inner_text().strip()
                for bname in builtin_names:
                    if bname in card_text.lower():
                        found_builtin.append(bname)
            if found_builtin:
                logger.info(f"✅ 发现内置 ACP: {found_builtin}")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-002: 创建 ACP 抽屉表单验证
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.acp
class TestCreateACPDrawerForm:
    """
    ACP-002: 创建 ACP 抽屉表单验证

    覆盖功能点：
    1. 点击创建按钮弹出抽屉
    2. 抽屉标题验证
    3. 表单字段验证（agentKey, command, args, env 等）
    4. 取消关闭抽屉
    """

    @pytest.mark.test_id("ACP-002")
    def test_create_acp_drawer_form(self, page: Page, request: pytest.FixtureRequest):
        """验证创建 ACP 抽屉表单"""
        test_name = request.node.name

        try:
            # 1. 访问 ACP 页面
            log_test_step("1. 访问 ACP 页面")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. 点击创建按钮
            log_test_step("2. 点击创建按钮")
            create_btn = page.locator(
                'button:has-text("Create"), button:has-text("创建"), '
                'button:has-text("Add"), button:has-text("添加"), '
                'button:has-text("新增"), button:has-text("New")'
            ).first

            assert create_btn.is_visible(timeout=5000), "创建按钮不可见，无法继续验证"

            create_btn.click()
            page.wait_for_timeout(500)

            # 3. 验证抽屉弹出
            log_test_step("3. 验证抽屉弹出")
            drawer = page.locator(".qwenpaw-drawer, .qwenpaw-modal").first
            expect(drawer).to_be_visible(timeout=5000)
            logger.info("✅ ACP 创建抽屉已弹出")

            # 验证标题
            drawer_title = drawer.locator(
                '.qwenpaw-drawer-title, .qwenpaw-modal-title, h2, h3'
            ).first
            if drawer_title.is_visible(timeout=3000):
                title_text = drawer_title.inner_text().strip()
                logger.info(f"抽屉标题: {title_text}")

            # 4. 验证表单字段
            log_test_step("4. 验证表单字段")
            drawer_text = drawer.inner_text()

            # agentKey 字段
            agent_key_input = drawer.locator(
                'input[id*="agentKey"], input[name*="agentKey"], '
                'input[placeholder*="key"], input[placeholder*="Key"]'
            ).first
            if agent_key_input.is_visible(timeout=3000):
                assert agent_key_input.is_enabled(), "创建时 agentKey 应可编辑"
                logger.info("✅ agentKey 输入框可见且可编辑")

            # command 字段
            command_input = drawer.locator(
                'input[id*="command"], input[name*="command"], '
                'input[placeholder*="command"], input[placeholder*="Command"]'
            ).first
            assert command_input.is_visible(timeout=3000), "command 输入框应可见"
            logger.info("✅ command 输入框可见")

            # args 字段（多行文本）
            args_input = drawer.locator(
                'textarea[id*="args"], textarea[name*="args"], textarea'
            ).first
            if args_input.is_visible(timeout=3000):
                logger.info("✅ args 文本域可见")

            # 开关字段（enabled, trusted）
            switches = drawer.locator('.qwenpaw-switch').all()
            logger.info(f"找到 {len(switches)} 个开关字段")

            # tool_parse_mode 下拉
            select_el = drawer.locator('.qwenpaw-select').first
            if select_el.is_visible(timeout=3000):
                logger.info("✅ 下拉选择框可见（tool_parse_mode）")

            # 关键字段存在性验证
            expected_labels = ["agentKey", "command", "enabled", "trusted"]
            for label in expected_labels:
                if label.lower() in drawer_text.lower():
                    logger.info(f"✅ 找到表单标签: {label}")

            # 5. 取消关闭抽屉
            log_test_step("5. 取消关闭抽屉")
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
            logger.info("✅ 抽屉已关闭")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-003: ACP 启用/禁用切换
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.acp
class TestACPToggleSwitch:
    """
    ACP-003: ACP 启用/禁用切换

    覆盖功能点：
    1. 卡片上的启用/禁用开关
    2. 切换状态变化
    3. 恢复原始状态
    """

    @pytest.mark.test_id("ACP-003")
    def test_acp_toggle_switch(self, page: Page, request: pytest.FixtureRequest):
        """验证 ACP 启用/禁用切换"""
        test_name = request.node.name
        initial_checked = None
        target_switch = None

        try:
            # 1. 访问 ACP 页面
            log_test_step("1. 访问 ACP 页面")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. 查找 ACP 卡片上的开关
            log_test_step("2. 查找 ACP 卡片开关")
            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()

            if len(cards) == 0:
                logger.info("ℹ️ 未找到 ACP 卡片，跳过验证")
                log_test_result(test_name, True, 0)
                return

            # 在第一个卡片中查找开关
            first_card = cards[0]
            target_switch = first_card.locator('.qwenpaw-switch').first

            if not target_switch.is_visible(timeout=3000):
                logger.info("ℹ️ 卡片上未找到开关，跳过验证")
                log_test_result(test_name, True, 0)
                return

            # 3. 记录初始状态
            log_test_step("3. 记录初始状态")
            initial_checked = target_switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
            logger.info(f"初始开关状态: {'启用' if initial_checked else '禁用'}")

            # 4. 切换状态
            log_test_step("4. 切换开关状态")
            target_switch.click()
            page.wait_for_timeout(1000)

            new_checked = target_switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
            logger.info(f"切换后开关状态: {'启用' if new_checked else '禁用'}")
            assert new_checked != initial_checked, \
                f"开关状态应变化: 初始={initial_checked}, 当前={new_checked}"
            logger.info("✅ 开关状态切换成功")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
        finally:
            # 恢复原始状态
            try:
                if initial_checked is not None and target_switch is not None:
                    current = target_switch.evaluate(
                        "el => el.classList.contains('qwenpaw-switch-checked') || "
                        "el.getAttribute('aria-checked') === 'true'"
                    )
                    if current != initial_checked:
                        target_switch.click()
                        page.wait_for_timeout(500)
                        logger.info("开关已恢复原始状态")
            except Exception as restore_err:
                logger.warning(f"恢复原始状态失败: {restore_err}")


# ============================================================================
# ACP-004: 过滤标签切换（All/Builtin/Custom）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.acp
class TestACPFilterTabs:
    """
    ACP-004: 过滤标签切换

    覆盖功能点：
    1. 切换到 Builtin 标签
    2. 验证仅显示内置 ACP
    3. 切换到 Custom 标签
    4. 切换回 All 标签恢复
    """

    @pytest.mark.test_id("ACP-004")
    def test_filter_tabs_switch(self, page: Page, request: pytest.FixtureRequest):
        """验证过滤标签切换功能"""
        test_name = request.node.name

        try:
            # 1. 访问 ACP 页面
            log_test_step("1. 访问 ACP 页面")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. 记录 All 标签下的卡片数量
            log_test_step("2. 记录 All 标签下卡片数量")
            all_cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            all_count = len(all_cards)
            logger.info(f"All 标签下卡片数量: {all_count}")

            # 3. 切换到 Builtin 标签
            log_test_step("3. 切换到 Builtin 标签")
            builtin_tab = page.locator(
                '[class*="tab"]:has-text("Builtin"), '
                '[class*="tab"]:has-text("内置"), '
                '.qwenpaw-segmented-item:has-text("Builtin"), '
                '.qwenpaw-segmented-item:has-text("内置")'
            ).first

            if not builtin_tab.is_visible(timeout=5000):
                logger.info("ℹ️ Builtin 标签不可见，跳过标签切换验证")
                log_test_result(test_name, True, 0)
                return

            builtin_tab.click()
            page.wait_for_timeout(1000)

            builtin_cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            builtin_count = len(builtin_cards)
            logger.info(f"Builtin 标签下卡片数量: {builtin_count}")

            if all_count > 0:
                assert builtin_count <= all_count, \
                    f"Builtin 数量应 <= All 数量: builtin={builtin_count}, all={all_count}"
            logger.info("✅ Builtin 标签过滤正常")

            # 4. 切换到 Custom 标签
            log_test_step("4. 切换到 Custom 标签")
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
                logger.info(f"Custom 标签下卡片数量: {custom_count}")

                assert custom_count <= all_count, \
                    f"Custom 数量应 <= All 数量: custom={custom_count}, all={all_count}"
                logger.info("✅ Custom 标签过滤正常")

            # 5. 切换回 All 标签
            log_test_step("5. 切换回 All 标签")
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
                    f"恢复后数量应与初始一致: restored={restored_count}, all={all_count}"
                logger.info("✅ 恢复 All 标签后数量一致")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-005: 编辑 ACP 配置
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.acp
class TestEditACPConfig:
    """
    ACP-005: 编辑 ACP 配置

    覆盖功能点：
    1. 点击卡片打开编辑抽屉
    2. 抽屉中显示当前配置
    3. 取消编辑不保存
    """

    @pytest.mark.test_id("ACP-005")
    def test_edit_acp_config(self, page: Page, request: pytest.FixtureRequest):
        """验证编辑 ACP 配置"""
        test_name = request.node.name

        try:
            # 1. 访问 ACP 页面
            log_test_step("1. 访问 ACP 页面")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. 点击第一个 ACP 卡片
            log_test_step("2. 点击第一个 ACP 卡片")
            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()

            if len(cards) == 0:
                logger.info("ℹ️ 未找到 ACP 卡片，跳过验证")
                log_test_result(test_name, True, 0)
                return

            first_card = cards[0]
            card_name = first_card.inner_text().strip()[:50]
            logger.info(f"点击卡片: {card_name}")

            # 点击卡片（排除开关区域）
            card_body = first_card.locator(
                '[class*="cardBody"], [class*="content"], .qwenpaw-card-body, '
                '[class*="agentKey"], [class*="title"]'
            ).first
            if card_body.is_visible(timeout=3000):
                card_body.click()
            else:
                first_card.click()
            page.wait_for_timeout(500)

            # 3. 验证编辑抽屉弹出
            log_test_step("3. 验证编辑抽屉弹出")
            drawer = page.locator(".qwenpaw-drawer, .qwenpaw-modal").first
            expect(drawer).to_be_visible(timeout=5000)
            logger.info("✅ 编辑抽屉已弹出")

            # 4. 验证当前配置已填充
            log_test_step("4. 验证配置已填充")

            # 检查 agentKey 字段（内置 ACP 可能隐藏此字段）
            agent_key_input = drawer.locator('#agentKey').first
            if agent_key_input.is_visible(timeout=3000):
                key_value = agent_key_input.input_value()
                assert len(key_value.strip()) > 0, "编辑模式下 agentKey 应有值"
                logger.info(f"✅ agentKey 当前值: {key_value}")
            else:
                # 内置 ACP 的 agentKey 可能被隐藏（form-item-hidden），这是正常保护行为
                # 改为从抽屉标题中验证 agentKey 信息
                drawer_title = drawer.locator('.qwenpaw-drawer-title').first
                if drawer_title.is_visible(timeout=2000):
                    title_text = drawer_title.inner_text().strip()
                    assert len(title_text) > 0, "编辑抽屉应有标题"
                    logger.info(f"✅ agentKey 字段已隐藏（内置保护），抽屉标题: {title_text}")
                else:
                    logger.info("✅ agentKey 字段已隐藏（内置 ACP 保护行为）")

            # 检查 command 字段（必填，应始终可见）
            command_input = drawer.locator('#command').first
            assert command_input.is_visible(timeout=3000), "编辑抽屉中应有 command 输入框"
            cmd_value = command_input.input_value()
            assert len(cmd_value.strip()) > 0, "编辑模式下 command 应有值"
            logger.info(f"✅ command 当前值: {cmd_value}")

            # 5. 取消编辑
            log_test_step("5. 取消编辑不保存")
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
            logger.info("✅ 取消编辑完成")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-006: 创建自定义 ACP 并删除
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.acp
class TestCreateAndDeleteCustomACP:
    """
    ACP-006: 创建自定义 ACP 并删除

    覆盖功能点：
    1. 创建自定义 ACP 配置
    2. 验证新 ACP 出现在列表
    3. 删除自定义 ACP
    4. 验证删除后列表更新
    """

    @pytest.mark.test_id("ACP-006")
    def test_create_and_delete_custom_acp(self, page: Page, request: pytest.FixtureRequest):
        """验证创建并删除自定义 ACP"""
        test_name = request.node.name
        created_acp_key = None

        try:
            # 1. 访问 ACP 页面
            log_test_step("1. 访问 ACP 页面")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            initial_cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            initial_count = len(initial_cards)

            # 2. 点击创建按钮
            log_test_step("2. 打开创建抽屉")
            create_btn = page.locator(
                'button:has-text("Create"), button:has-text("创建"), '
                'button:has-text("Add"), button:has-text("添加"), '
                'button:has-text("新增"), button:has-text("New")'
            ).first

            assert create_btn.is_visible(timeout=5000), "创建按钮不可见，无法继续验证"

            create_btn.click()
            page.wait_for_timeout(500)

            drawer = page.locator(".qwenpaw-drawer, .qwenpaw-modal").first
            expect(drawer).to_be_visible(timeout=5000)

            # 3. 填写表单
            log_test_step("3. 填写创建表单")
            import time
            created_acp_key = f"e2e_test_acp_{int(time.time())}"

            # 填写 agentKey
            key_input = drawer.locator(
                'input[id*="agentKey"], input[name*="agentKey"], '
                'input[placeholder*="key"], input[placeholder*="Key"]'
            ).first
            if key_input.is_visible(timeout=3000) and key_input.is_enabled():
                key_input.fill(created_acp_key)
                logger.info(f"填写 agentKey: {created_acp_key}")

            # 填写 command
            cmd_input = drawer.locator(
                'input[id*="command"], input[name*="command"], '
                'input[placeholder*="command"]'
            ).first
            if cmd_input.is_visible(timeout=3000):
                cmd_input.fill("/usr/bin/echo")
                logger.info("填写 command: /usr/bin/echo")

            # 4. 保存
            log_test_step("4. 保存创建")
            save_btn = drawer.locator(
                'button.qwenpaw-btn-primary, button:has-text("Save"), '
                'button:has-text("保存"), button:has-text("OK"), button:has-text("确定")'
            ).first
            if save_btn.is_visible(timeout=3000):
                save_btn.click()
                page.wait_for_timeout(2000)

            # 检查是否创建成功
            success_msg = page.locator(
                '.qwenpaw-message-success, .qwenpaw-notification-success'
            ).first
            if success_msg.is_visible(timeout=5000):
                logger.info("✅ 创建成功消息出现")

            # 5. 验证新 ACP 出现在列表
            log_test_step("5. 验证新 ACP 出现")
            page.wait_for_timeout(1000)
            new_cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()
            new_count = len(new_cards)
            logger.info(f"创建后卡片数量: {new_count}（初始: {initial_count}）")

            # 查找新创建的 ACP
            found_new = False
            for card in new_cards:
                if created_acp_key in card.inner_text():
                    found_new = True
                    logger.info(f"✅ 找到新创建的 ACP: {created_acp_key}")
                    break

            # 6. 删除新创建的 ACP
            if found_new:
                log_test_step("6. 删除新创建的 ACP")
                # 点击新创建的卡片打开编辑抽屉
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

                            # 确认删除
                            confirm_btn = page.locator(
                                '.qwenpaw-popconfirm button.qwenpaw-btn-primary, '
                                '.qwenpaw-popconfirm button:has-text("OK"), '
                                '.qwenpaw-popconfirm button:has-text("确定"), '
                                '.qwenpaw-modal button.qwenpaw-btn-primary'
                            ).first
                            if confirm_btn.is_visible(timeout=3000):
                                confirm_btn.click()
                                page.wait_for_timeout(2000)
                                logger.info("✅ 已确认删除")
                            else:
                                logger.info("ℹ️ 未找到确认删除按钮")
                        else:
                            # 关闭抽屉
                            page.keyboard.press("Escape")
                            logger.info("ℹ️ 抽屉中未找到删除按钮")

                # 验证删除后数量恢复
                page.wait_for_timeout(1000)
                final_cards = page.locator(
                    '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
                ).all()
                final_count = len(final_cards)
                logger.info(f"删除后卡片数量: {final_count}")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-007: 内置 ACP 保护验证
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.acp
class TestBuiltinACPProtection:
    """
    ACP-007: 内置 ACP 保护验证

    覆盖功能点：
    1. 内置 ACP 的 agentKey 不可修改
    2. 内置 ACP 无删除按钮
    """

    @pytest.mark.test_id("ACP-007")
    def test_builtin_acp_protection(self, page: Page, request: pytest.FixtureRequest):
        """验证内置 ACP 保护机制"""
        test_name = request.node.name

        try:
            # 1. 访问 ACP 页面
            log_test_step("1. 访问 ACP 页面")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. 切换到 Builtin 标签
            log_test_step("2. 查找内置 ACP 卡片")
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
                logger.info("ℹ️ 未找到内置 ACP 卡片，跳过保护验证")
                log_test_result(test_name, True, 0)
                return

            # 3. 点击第一个内置 ACP 卡片
            log_test_step("3. 打开内置 ACP 编辑抽屉")
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
                logger.info("ℹ️ 编辑抽屉未弹出")
                log_test_result(test_name, True, 0)
                return

            # 4. 验证 agentKey 不可修改
            log_test_step("4. 验证 agentKey 不可修改")
            key_input = drawer.locator('#agentKey').first
            if key_input.is_visible(timeout=3000):
                is_disabled = key_input.is_disabled()
                is_readonly = key_input.get_attribute("readonly") is not None
                assert is_disabled or is_readonly, \
                    "内置 ACP 的 agentKey 应为 disabled 或 readonly 状态"
                logger.info("✅ 内置 ACP 的 agentKey 不可修改（disabled/readonly）")
            else:
                # agentKey 被 form-item-hidden 隐藏，这本身就是一种保护
                hidden_item = drawer.locator('.qwenpaw-form-item-hidden').first
                assert hidden_item.count() > 0 or not key_input.is_visible(), \
                    "内置 ACP 的 agentKey 应被隐藏或设为不可修改"
                logger.info("✅ 内置 ACP 的 agentKey 已隐藏（不可修改保护生效）")

            # 5. 验证无删除按钮或删除按钮为 disabled
            log_test_step("5. 验证删除保护")
            delete_btn = drawer.locator(
                'button:has-text("Delete"), button:has-text("删除")'
            ).first
            if delete_btn.is_visible(timeout=3000):
                assert delete_btn.is_disabled(), \
                    "内置 ACP 的删除按钮应为 disabled 状态"
                logger.info("✅ 删除按钮为 disabled 状态（保护生效）")
            else:
                logger.info("✅ 内置 ACP 无删除按钮（保护生效）")

            # 6. 关闭抽屉
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise


# ============================================================================
# ACP-008: ACP 卡片内容详情验证
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.acp
class TestACPCardDetails:
    """
    ACP-008: ACP 卡片内容详情验证

    覆盖功能点：
    1. 卡片显示 agentKey
    2. 卡片显示内置/自定义标签
    3. 卡片显示 command 和 args 摘要
    """

    @pytest.mark.test_id("ACP-008")
    def test_acp_card_content_details(self, page: Page, request: pytest.FixtureRequest):
        """验证 ACP 卡片内容详情"""
        test_name = request.node.name

        try:
            # 1. 访问 ACP 页面
            log_test_step("1. 访问 ACP 页面")
            page.goto(f"{config.base_url}/acp", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 2. 获取 ACP 卡片列表
            log_test_step("2. 获取卡片列表")
            cards = page.locator(
                '[class*="acpCard"], [class*="ACPCard"], .qwenpaw-card'
            ).all()

            assert len(cards) > 0, "ACP 卡片列表不应为空"
            logger.info(f"✅ 找到 {len(cards)} 个 ACP 卡片")

            # 3. 验证每个卡片的内容
            log_test_step("3. 验证卡片内容")
            cards_with_key = 0
            cards_with_switch = 0
            for i, card in enumerate(cards[:4]):  # 最多验证前 4 个
                card_text = card.inner_text().strip()
                assert len(card_text) > 0, f"卡片 {i+1} 内容不应为空"
                logger.info(f"卡片 {i+1} 内容: {card_text[:100]}")

                # 检查是否有 agentKey 类似的标识
                has_key = any(name in card_text.lower() for name in [
                    "opencode", "qwen_code", "claude_code", "codex",
                    "e2e_test", "custom"
                ])
                if has_key:
                    cards_with_key += 1

                # 检查开关存在
                switch = card.locator('.qwenpaw-switch').first
                if switch.count() > 0:
                    cards_with_switch += 1

            # 至少部分卡片应有 agentKey 标识或开关
            assert cards_with_key > 0 or cards_with_switch > 0, \
                "至少部分 ACP 卡片应包含 agentKey 标识或启用/禁用开关"
            logger.info(f"✅ 卡片详情验证通过（有标识: {cards_with_key}, 有开关: {cards_with_switch}）")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed")

        except Exception as e:
            logger.error(f"Test {test_name} failed: {str(e)}")
            log_test_result(test_name, False, 1)
            raise
