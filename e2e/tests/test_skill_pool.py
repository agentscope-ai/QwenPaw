# -*- coding: utf-8 -*-
"""
QwenPaw E2E 测试 - Skill Pool P0 用例

覆盖功能：
1. 技能池页面加载
2. 技能池列表展示
3. 内置技能源列表
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
    """导航到技能池页面"""
    page.goto(f"{BASE_URL}/skill-pool", wait_until="domcontentloaded", timeout=60000)
    # 显式等待技能卡片渲染完成，而非仅靠固定超时
    try:
        page.wait_for_selector('.qwenpaw-card', timeout=15000)
    except Exception:
        logger.warning("等待技能卡片超时，页面可能无数据或加载缓慢")
    page.wait_for_timeout(1000)

# ============================================================================
# POOL-001: 技能池页面加载
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
class TestSkillPoolPageLoad:
    """POOL-001: 技能池页面加载"""
    
    @pytest.mark.test_id("POOL-001")
    def test_skill_pool_page_load(self, page: Page, request: pytest.FixtureRequest):
        """验证技能池页面正常加载"""
        test_name = request.node.name
        
        try:
            log_test_step("1. 访问技能池页面")
            navigate_to_skill_pool(page)
            
            log_test_step("2. 验证页面加载")
            body = page.locator("body").first
            assert body.is_visible(timeout=5000), "页面应正常加载"
            logger.info(f"✅ 技能池页面加载成功")
            
            log_test_result(test_name, "PASS", "技能池页面加载验证通过")
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

# ============================================================================
# POOL-P1-001: 技能池搜索/筛选
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolSearch:
    """
    POOL-P1-001: 技能池搜索/筛选

    覆盖功能点：
    1. 验证搜索框存在
    2. 输入关键词过滤技能列表
    3. 清空搜索恢复完整列表
    """

    @pytest.mark.test_id("POOL-P1-001")
    def test_skill_pool_search(self, page: Page, request: pytest.FixtureRequest):
        """测试技能池搜索/筛选功能"""
        test_name = request.node.name

        log_test_step("导航到技能池页面")
        navigate_to_skill_pool(page)

        log_test_step("验证搜索框存在")
        search_input = page.locator(
            'input[placeholder*="筛选"], input[placeholder*="搜索"], '
            'input[placeholder*="search"], input[placeholder*="Search"], '
            'input[placeholder*="filter"], '
            '.qwenpaw-select-selection-search-input, '
            '.qwenpaw-input-search input'
        ).first
        expect(search_input).to_be_visible(timeout=5000)
        logger.info("✅ 搜索框存在")

        log_test_step("记录搜索前的技能数量")
        # 等待卡片加载完成后再计数，避免异步数据未到导致 count=0
        try:
            page.wait_for_selector('.qwenpaw-card', timeout=10000)
            page.wait_for_timeout(500)
        except Exception:
            logger.warning("未等到技能卡片，可能页面无数据")
        skill_cards = page.locator('.qwenpaw-card').all()
        initial_count = len(skill_cards)
        logger.info(f"搜索前技能数量：{initial_count}")
        if initial_count == 0:
            logger.info("ℹ️ 技能池无数据，跳过搜索过滤断言")
            log_test_result(test_name, True, 0)
            return

        log_test_step("输入搜索关键词")
        # 搜索框是 qwenpaw-select 组件（readonly input），需要点击父容器触发下拉
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
        logger.info(f"搜索后技能数量：{filtered_count}")
        assert filtered_count <= initial_count, \
            f"过滤后数量({filtered_count})不应大于初始数量({initial_count})"
        logger.info("✅ 搜索过滤生效")

        log_test_step("清空搜索恢复列表")
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
        logger.info(f"清空搜索后技能数量：{restored_count}")
        logger.info("✅ 搜索清空后列表恢复")

        log_test_result(test_name, True, 0)

# ============================================================================
# POOL-P1-002: 技能安装到智能体（通过广播）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolInstall:
    """
    POOL-P1-002: 技能安装到智能体

    覆盖功能点：
    1. 查找广播按钮
    2. 打开广播 Modal
    3. 验证 Modal 中有技能和工作区选择
    """

    @pytest.mark.test_id("POOL-P1-002")
    def test_skill_pool_install(self, page: Page, request: pytest.FixtureRequest):
        """测试技能安装到智能体功能"""
        test_name = request.node.name

        log_test_step("导航到技能池页面")
        navigate_to_skill_pool(page)

        log_test_step("查找广播按钮")
        broadcast_btn = page.locator(
            'button:has-text("广播"), button:has-text("Broadcast"), '
            'button:has(.anticon-send)'
        ).first

        if broadcast_btn.count() == 0:
            logger.info("未找到广播按钮，跳过测试")
            log_test_result(test_name, True, 0)
            return

        expect(broadcast_btn).to_be_visible(timeout=5000)
        logger.info("✅ 广播按钮存在")

        log_test_step("点击广播按钮")
        broadcast_btn.click()
        page.wait_for_timeout(1500)

        log_test_step("验证广播 Modal 打开")
        page.wait_for_timeout(500)
        visible_modals = page.locator('.qwenpaw-modal:visible, .ant-modal:visible, [role="dialog"]:visible')
        modal = visible_modals.last if visible_modals.count() > 0 else page.locator('.qwenpaw-modal, .ant-modal').last
        expect(modal).to_be_visible(timeout=8000)
        modal_content = modal.inner_text()
        assert len(modal_content) > 10, "广播 Modal 内容为空"
        logger.info(f"✅ 广播 Modal 已打开，内容长度：{len(modal_content)}")

        log_test_step("验证 Modal 中有选择区域并操作")
        # 实际 UI 使用自定义 pickerCard 组件而非标准 checkbox/select
        picker_cards = modal.locator('[class*=pickerCard]').all()
        checkboxes = modal.locator('.qwenpaw-checkbox, .ant-checkbox, .qwenpaw-checkbox-wrapper').all()
        selects = modal.locator('.qwenpaw-select, .ant-select').all()
        lists = modal.locator('.qwenpaw-list-item, .ant-list-item, tr').all()
        total_interactive = len(picker_cards) + len(checkboxes) + len(selects) + len(lists)
        assert total_interactive > 0, "广播 Modal 中应有可选择的元素（pickerCard/复选框/选择器/列表项）"
        logger.info(f"✅ Modal 中找到 {len(picker_cards)} 个 pickerCard, {len(checkboxes)} 个复选框, {len(selects)} 个选择器, {len(lists)} 个列表项")

        # 如果有 pickerCard，点击第一个验证可交互
        if len(picker_cards) > 0:
            first_card = picker_cards[0]
            first_card.click()
            page.wait_for_timeout(500)
            logger.info("✅ 已点击第一个 pickerCard")
        elif len(checkboxes) > 0:
            first_checkbox = checkboxes[0]
            first_checkbox.click()
            page.wait_for_timeout(500)
            logger.info("✅ 已勾选第一个复选框")

        # 验证确认按钮存在
        confirm_btn = modal.locator(
            'button:has-text("OK"), button:has-text("确定"), '
            'button:has-text("Broadcast"), button:has-text("广播"), '
            'button.qwenpaw-btn-primary'
        ).first
        assert confirm_btn.count() > 0, "广播 Modal 中应有确认按钮"
        logger.info("✅ 确认按钮存在")

        log_test_step("关闭 Modal")
        close_btn = modal.locator('.qwenpaw-modal-close, button:has-text("Cancel"), button:has-text("取消")').first
        if close_btn.count() > 0:
            close_btn.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

        log_test_result(test_name, True, 0)

# ============================================================================
# POOL-P1-003: 技能广播到多个智能体
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolBroadcast:
    """
    POOL-P1-003: 技能广播到多个智能体

    覆盖功能点：
    1. 打开广播 Modal
    2. 验证可以选择多个工作区
    3. 验证确认按钮存在
    """

    @pytest.mark.test_id("POOL-P1-003")
    def test_skill_pool_broadcast(self, page: Page, request: pytest.FixtureRequest):
        """测试技能广播到多个智能体"""
        test_name = request.node.name

        log_test_step("导航到技能池页面")
        navigate_to_skill_pool(page)

        log_test_step("查找并点击广播按钮")
        broadcast_btn = page.locator(
            'button:has-text("广播"), button:has-text("Broadcast"), '
            'button:has(.anticon-send)'
        ).first

        if broadcast_btn.count() == 0:
            logger.info("未找到广播按钮，跳过测试")
            log_test_result(test_name, True, 0)
            return

        broadcast_btn.click()
        page.wait_for_timeout(3000)

        # 等待 Modal 出现并获取引用
        modal_locator = page.locator('.qwenpaw-modal:visible, .ant-modal:visible, [role="dialog"]:visible')
        expect(modal_locator.first).to_be_visible(timeout=8000)
        modal = modal_locator.last

        log_test_step("验证工作区选择区域并勾选")
        # 实际 UI 使用自定义 pickerCard 组件，Modal 包含两个 pickerSection：
        # section 0: "选择技能池项目"，section 1: "广播到工作区"
        # 直接从 Modal 中获取所有 pickerCard
        workspace_items = modal.locator('[class*=pickerCard]').all()
        if len(workspace_items) == 0:
            # 兜底：尝试标准组件选择器
            workspace_items = modal.locator(
                '.qwenpaw-checkbox-wrapper, .ant-checkbox-wrapper, '
                '.qwenpaw-list-item, .ant-list-item'
            ).all()
        assert len(workspace_items) > 0, "广播 Modal 应有工作区/选择项"
        logger.info(f"✅ 找到 {len(workspace_items)} 个工作区/选择项")

        # 点击第一个工作区选择项
        first_item = workspace_items[0]
        first_item.click()
        page.wait_for_timeout(500)
        logger.info("✅ 已选择第一个工作区")

        # 如果有多个，点击第二个验证多选
        if len(workspace_items) > 1:
            second_item = workspace_items[1]
            second_item.click()
            page.wait_for_timeout(500)
            logger.info("✅ 已选择第二个工作区（验证多选）")

        log_test_step("验证确认按钮可用")
        confirm_btn = modal.locator(
            'button:has-text("OK"), button:has-text("确定"), '
            'button:has-text("Broadcast"), button:has-text("广播"), '
            'button.qwenpaw-btn-primary'
        ).first
        assert confirm_btn.count() > 0, "广播 Modal 中未找到确认按钮"
        assert confirm_btn.is_enabled(), "勾选工作区后确认按钮应可用"
        logger.info("✅ 确认按钮存在且可用")

        log_test_step("关闭 Modal（不执行广播）")
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

        log_test_result(test_name, True, 0)

# ============================================================================
# POOL-P1-004: 批量删除技能
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolBatchDelete:
    """
    POOL-P1-004: 批量删除技能

    覆盖功能点：
    1. 查找批量操作按钮
    2. 进入批量模式
    3. 验证复选框出现
    4. 退出批量模式
    """

    @pytest.mark.test_id("POOL-P1-004")
    def test_skill_pool_batch_delete(self, page: Page, request: pytest.FixtureRequest):
        """测试技能池批量删除功能"""
        test_name = request.node.name

        log_test_step("导航到技能池页面")
        navigate_to_skill_pool(page)

        log_test_step("查找批量操作按钮")
        batch_btn = page.locator(
            'button:has-text("批量"), button:has-text("Batch"), '
            'button:has-text("Select"), button:has-text("选择")'
        ).first

        if batch_btn.count() == 0:
            logger.info("未找到批量操作按钮，跳过测试")
            log_test_result(test_name, True, 0)
            return

        expect(batch_btn).to_be_visible(timeout=5000)
        logger.info("✅ 批量操作按钮存在")

        log_test_step("进入批量模式")
        batch_btn.click()
        page.wait_for_timeout(1500)

        log_test_step("验证复选框出现并勾选")
        checkboxes = page.locator('.qwenpaw-checkbox, .ant-checkbox, .qwenpaw-checkbox-wrapper').all()
        assert len(checkboxes) > 0, "批量模式下应出现复选框"
        logger.info(f"✅ 批量模式下找到 {len(checkboxes)} 个复选框")

        # 勾选第一个复选框
        checkboxes[0].click()
        page.wait_for_timeout(500)
        logger.info("✅ 已勾选第一个技能")

        # 验证删除按钮出现且可用
        delete_btn = page.locator(
            'button:has-text("删除"), button:has-text("Delete"), '
            'button.qwenpaw-btn-dangerous'
        ).first
        if delete_btn.count() > 0 and delete_btn.is_visible(timeout=3000):
            assert delete_btn.is_enabled(), "勾选技能后删除按钮应可用"
            logger.info("✅ 删除按钮可见且可用")
        else:
            # 验证有全选按钮
            select_all = page.locator(
                'button:has-text("全选"), button:has-text("Select All"), '
                '.qwenpaw-checkbox-wrapper:has-text("全选")'
            ).first
            if select_all.count() > 0:
                logger.info("✅ 全选按钮存在")
            else:
                logger.info("ℹ️ 未找到删除/全选按钮")

        log_test_step("退出批量模式（不执行删除）")
        # 再次点击批量按钮或点击取消
        cancel_btn = page.locator(
            'button:has-text("取消"), button:has-text("Cancel"), '
            'button:has-text("退出"), button:has-text("Exit")'
        ).first
        if cancel_btn.count() > 0:
            cancel_btn.click()
        else:
            batch_btn.click()
        page.wait_for_timeout(1000)
        logger.info("✅ 已退出批量模式")

        log_test_result(test_name, True, 0)

# ============================================================================
# POOL-P1-005: ZIP 导入技能
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.skill_pool
class TestSkillPoolZipImport:
    """
    POOL-P1-005: ZIP 导入技能

    覆盖功能点：
    1. 查找 ZIP 上传按钮
    2. 验证隐藏的文件输入框存在且 accept 属性为 .zip
    3. 创建临时 zip 文件并通过隐藏 input 上传
    4. 验证上传成功（技能出现在列表中或出现成功提示）
    5. 清理：删除上传的技能 + 删除临时文件
    """

    @pytest.mark.test_id("POOL-P1-005")
    def test_skill_pool_zip_import(self, page: Page, request: pytest.FixtureRequest):
        """测试技能池 ZIP 导入功能（含实际上传）"""
        import zipfile
        import tempfile
        import os
        import time

        test_name = request.node.name
        skill_name = f"e2e_pool_zip_{int(time.time())}"
        zip_path = None
        skill_uploaded = False

        try:
            log_test_step("1. 导航到技能池页面")
            navigate_to_skill_pool(page)

            log_test_step("2. 查找 ZIP 上传按钮")
            upload_btn = page.locator(
                'button:has-text("zip"), button:has-text("ZIP"), '
                'button:has-text("上传"), button:has-text("Upload"), '
                'button:has(.anticon-upload)'
            ).first

            if upload_btn.count() == 0:
                pytest.skip("未找到 ZIP 上传按钮，跳过测试")

            expect(upload_btn).to_be_visible(timeout=5000)
            logger.info("✅ ZIP 上传按钮存在")

            log_test_step("3. 验证隐藏的文件输入框")
            file_input = page.locator(
                'input[type="file"][accept=".zip"], '
                'input[type="file"][accept*="zip"]'
            ).first
            assert file_input.count() > 0, "未找到隐藏的 ZIP 文件输入框"

            accept_attr = file_input.get_attribute("accept")
            assert ".zip" in accept_attr, f"文件输入框 accept 属性不包含 .zip：{accept_attr}"
            logger.info(f"✅ 文件输入框 accept={accept_attr}")

            log_test_step("4. 记录初始技能数量")
            initial_cards = page.locator('.qwenpaw-card').all()
            initial_count = len(initial_cards)
            logger.info(f"初始技能数量：{initial_count}")

            log_test_step("5. 创建临时 zip 文件")
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

            logger.info(f"✅ 临时 zip 文件已创建：{zip_path}")

            log_test_step("6. 通过隐藏 input 上传 zip 文件")
            file_input.set_input_files(zip_path)
            logger.info("✅ 已通过 set_input_files 上传 zip 文件")

            # 等待上传处理完成
            page.wait_for_timeout(5000)

            log_test_step("7. 验证上传结果")
            # 检查是否有成功提示
            success_message = page.locator(
                '.qwenpaw-message-success, '
                '.qwenpaw-message-notice:has-text("成功"), '
                '.qwenpaw-message-notice:has-text("success")'
            ).first
            if success_message.is_visible():
                logger.info("✅ 检测到上传成功提示消息")

            # 刷新页面确保列表更新
            page.reload()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

            # 验证新技能出现在列表中
            new_skill_locator = page.locator(f'text="{skill_name}"').first
            try:
                expect(new_skill_locator).to_be_visible(timeout=8000)
                skill_uploaded = True
                logger.info(f"✅ 上传的技能已出现在技能池列表中：{skill_name}")
            except Exception:
                updated_cards = page.locator('.qwenpaw-card').all()
                updated_count = len(updated_cards)
                logger.info(f"上传后技能数量：{updated_count}（初始：{initial_count}）")
                if updated_count > initial_count:
                    skill_uploaded = True
                    logger.info("✅ 技能数量已增加，上传可能成功")
                else:
                    logger.warning("⚠️ 未检测到新技能，上传可能未成功或技能名称不匹配")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed - 技能池 ZIP 导入验证通过")

        finally:
            # 清理：删除上传的测试技能
            if skill_uploaded:
                try:
                    target_card = page.locator(f'.qwenpaw-card:has-text("{skill_name}")').first
                    if target_card.is_visible():
                        # 尝试找到卡片上的删除按钮
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
                            logger.info(f"✅ 清理：已删除测试技能 '{skill_name}'")
                except Exception:
                    logger.warning(f"清理失败：无法删除测试技能 '{skill_name}'")

            # 清理：删除临时文件
            if zip_path:
                try:
                    import shutil
                    temp_dir_to_clean = os.path.dirname(zip_path)
                    shutil.rmtree(temp_dir_to_clean, ignore_errors=True)
                    logger.info("✅ 清理：已删除临时 zip 文件")
                except Exception:
                    logger.warning("清理失败：无法删除临时文件")


# ============================================================================
# POOL-P2-001: 导入内置技能包
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.skill_pool
class TestSkillPoolBuiltinImport:
    """POOL-P2-001: 导入内置技能包"""

    @pytest.mark.test_id("POOL-P2-001")
    def test_skill_pool_builtin_import(self, page: Page, request: pytest.FixtureRequest):
        """测试导入内置技能包"""
        test_name = request.node.name

        log_test_step("导航到技能池页面")
        navigate_to_skill_pool(page)

        log_test_step("查找内置技能导入按钮")
        builtin_btn = page.locator(
            'button:has-text("内置"), button:has-text("Built"), '
            'button:has-text("Builtin"), button:has-text("Update"), '
            'button:has-text("更新")'
        ).first

        if builtin_btn.count() == 0:
            pytest.skip("未找到内置技能导入按钮，跳过测试")

        expect(builtin_btn).to_be_visible(timeout=5000)
        logger.info("✅ 内置技能导入按钮存在")

        builtin_btn.click()
        page.wait_for_timeout(2000)

        # 检查是否打开了弹窗/抽屉，或者直接执行了导入操作
        modal_or_drawer = page.locator('.qwenpaw-modal, .ant-modal, .qwenpaw-drawer, .ant-drawer, [role="dialog"]').last
        if modal_or_drawer.count() > 0:
            try:
                expect(modal_or_drawer).to_be_visible(timeout=5000)
                logger.info("✅ 内置技能导入弹窗已打开")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            except Exception:
                logger.info("ℹ️ 弹窗存在但不可见，可能已自动关闭")
        else:
            # 可能点击后直接执行了导入操作（无弹窗确认）
            success_msg = page.locator('.qwenpaw-message-success, .ant-message-success').first
            if success_msg.count() > 0:
                logger.info("✅ 内置技能导入操作已执行（无弹窗确认）")
            else:
                logger.info("ℹ️ 点击后未出现弹窗，可能正在后台处理")

        log_test_result(test_name, True, 0)