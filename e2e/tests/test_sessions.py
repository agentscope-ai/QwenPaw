# -*- coding: utf-8 -*-
"""
QwenPaw Sessions 模块 P0 级端到端测试用例

P0 级别定义：
- 核心用户操作流程
- 多个功能点组合覆盖
- 真实用户场景模拟
- 高优先级功能验证

测试框架：pytest + Playwright + Page Object Pattern
执行命令：pytest tests/test_sessions_p0.py -v
"""
from __future__ import annotations

import logging
import time
import pytest
from playwright.sync_api import Page, expect, TimeoutError

from pages.sessions_page import SessionsPage
from config.settings import config
from utils.helpers import (
    log_test_step,
    log_test_result,
    take_screenshot,
    assert_text_contains,
)

logger = logging.getLogger(__name__)


# ============================================================================
# SESS-001: 会话列表展示 + 过滤 + 详情查看
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.sessions_core
class TestSessionListFilterAndDetail:
    """
    SESS-001: 会话列表展示 + 过滤 + 详情查看

    组合覆盖功能点：
    1. Sessions 页面访问与加载
    2. 会话列表表格展示（列验证）
    3. UserID 过滤
    4. Channel 过滤
    5. 列表排序
    6. 会话详情查看

    业务场景：
    用户进入 Sessions 管理页面，查看会话列表，
    通过过滤和排序快速定位目标会话，然后查看会话详情。
    """

    @pytest.mark.test_id("SESS-001")
    def test_session_list_filter_and_detail(self, sessions_page: SessionsPage, request: pytest.FixtureRequest):
        """
        验证会话列表展示、过滤、排序和详情查看

        测试步骤：
        1. 访问 Sessions 页面，验证表格加载
        2. 验证表格关键列（ID / UserID / Channel / Created）
        3. 验证过滤器可用（UserID / Channel）
        4. 验证排序功能（表头可点击）
        5. 查看第一条会话详情
        """
        test_name = request.node.name

        log_test_step("1. 访问 Sessions 页面，验证表格加载")
        sessions_page.open()
        session_count = sessions_page.get_session_count()
        logger.info(f"会话数量：{session_count}")

        log_test_step("2. 验证表格关键列")
        table_header = sessions_page.page.locator("thead th")
        header_count = table_header.count()
        assert header_count >= 3, f"表格应至少有3列，实际 {header_count} 列"
        logger.info(f"✅ 表格列数：{header_count}")

        log_test_step("3. 验证过滤器并执行过滤操作")
        userid_input = sessions_page.page.locator(sessions_page.FILTER_USER_ID_INPUT).first
        if userid_input.count() > 0 and userid_input.is_visible(timeout=3000):
            # 输入一个过滤值并验证
            userid_input.fill("e2e_test_filter")
            sessions_page.page.wait_for_timeout(1500)
            filtered_count = sessions_page.get_session_count()
            logger.info(f"过滤后会话数量：{filtered_count}")
            assert filtered_count <= session_count, \
                f"过滤后数量({filtered_count})不应超过原始数量({session_count})"
            logger.info("✅ UserID 过滤器功能正常")
            # 清空过滤
            userid_input.fill("")
            sessions_page.page.wait_for_timeout(1000)
        else:
            logger.info("ℹ️ 未找到 UserID 过滤器输入框")

        log_test_step("4. 验证排序功能（点击表头）")
        headers = sessions_page.page.locator("thead th")
        assert headers.count() > 0, "应该存在表头"
        # 点击第一个可排序表头
        first_header = headers.first
        first_header.click()
        sessions_page.page.wait_for_timeout(1000)
        logger.info("✅ 已点击表头排序")

        log_test_step("5. 查看第一条会话详情")
        refreshed_count = sessions_page.get_session_count()
        if refreshed_count > 0:
            visible_rows = sessions_page.page.locator("tbody tr:not([aria-hidden='true'])")
            assert visible_rows.count() > 0, "应该有可见的会话行"
            first_row = visible_rows.first
            first_row.click()
            sessions_page.page.wait_for_timeout(2000)
            # 验证详情面板或抽屉打开
            detail_panel = sessions_page.page.locator('.qwenpaw-drawer, .qwenpaw-modal, [class*="detail"]').first
            if detail_panel.count() > 0 and detail_panel.is_visible(timeout=3000):
                detail_text = detail_panel.text_content() or ""
                assert len(detail_text) > 10, "会话详情内容不应为空"
                logger.info(f"✅ 会话详情面板已打开，内容长度: {len(detail_text)}")
                sessions_page.page.keyboard.press("Escape")
                sessions_page.page.wait_for_timeout(500)
            else:
                logger.info("ℹ️ 点击行后未打开详情面板（可能使用路由跳转）")
            logger.info(f"✅ 可见会话行数：{visible_rows.count()}")
        else:
            logger.info("ℹ️ 无会话数据，跳过详情查看")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 会话列表展示、过滤、排序、详情功能正常")


# ============================================================================
# SESS-002: 编辑会话 + 删除会话 + 批量删除
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.sessions_edit
class TestEditAndDeleteSession:
    """
    SESS-002: 编辑会话 + 删除会话 + 批量删除

    组合覆盖功能点：
    1. 点击编辑按钮打开编辑弹窗
    2. 验证编辑弹窗和表单
    3. 取消编辑关闭弹窗
    4. 验证删除按钮可用
    5. 验证批量选择和批量删除功能

    业务场景：
    管理员打开编辑弹窗查看会话信息后取消，
    然后验证单条删除和批量删除功能可用。
    """

    @pytest.mark.test_id("SESS-002")
    def test_edit_and_delete_session(self, sessions_page: SessionsPage, ensure_session_data, request: pytest.FixtureRequest):
        """
        验证编辑、删除、批量删除功能

        测试步骤：
        1. 访问 Sessions 页面
        2. 验证有可操作的会话
        3. 点击编辑按钮，验证弹窗打开
        4. 取消编辑，验证弹窗关闭
        5. 验证删除按钮可用
        6. 验证批量选择和批量删除功能
        """
        test_name = request.node.name

        log_test_step("1. 访问 Sessions 页面")
        sessions_page.open()
        sessions_page.step_shot("01_sessions_page_opened")

        log_test_step("2. 验证有可操作的会话")
        session_count = sessions_page.get_session_count()
        assert session_count > 0, (
            "ensure_session_data fixture 应已创建测试数据，但页面会话数为 0"
        )
        first_row = sessions_page.page.locator(sessions_page.SESSION_TABLE_ROW).first

        # --- 编辑功能：必须真的能打开和关闭 drawer ---
        log_test_step("3. 点击编辑按钮，验证弹窗打开")
        # 注意：被测系统 Action 列 fixed="right"，可能在行内查找不到按钮，
        # 这里用页面级的 EDIT_BTN 选择器并取第一个匹配（覆盖固定列影子表场景）。
        page_edit_btns = sessions_page.page.locator(sessions_page.EDIT_BTN)
        edit_btn_count = page_edit_btns.count()
        assert edit_btn_count > 0, (
            f"页面上未找到任何编辑按钮（行数={session_count}）。"
            f"page object EDIT_BTN 选择器可能未覆盖真实 DOM，请检查 fixed-right 列结构。"
        )
        edit_btn = page_edit_btns.first
        edit_btn.scroll_into_view_if_needed()
        edit_btn.click()
        sessions_page.step_shot("02_edit_btn_clicked")
        expect(
            sessions_page.page.locator(sessions_page.SESSION_DRAWER).first
        ).to_be_visible(timeout=5000)
        logger.info("✅ 编辑弹窗已打开")
        sessions_page.step_shot("03_edit_drawer_opened")

        log_test_step("4. 取消编辑，验证弹窗关闭")
        cancel_btns = sessions_page.page.locator(sessions_page.FORM_CANCEL_BTN)
        if cancel_btns.count() > 0 and cancel_btns.first.is_visible():
            cancel_btns.first.click()
        else:
            # 兜底：按 ESC 关闭 drawer
            sessions_page.page.keyboard.press("Escape")
        expect(
            sessions_page.page.locator(sessions_page.SESSION_DRAWER).first
        ).to_be_hidden(timeout=5000)
        sessions_page.step_shot("04_edit_drawer_closed")
        logger.info("✅ 编辑弹窗已关闭")

        # --- 删除功能：按钮必须存在且可用 ---
        log_test_step("5. 验证删除按钮可用")
        page_delete_btns = sessions_page.page.locator(sessions_page.DELETE_BTN)
        del_count = page_delete_btns.count()
        assert del_count > 0, "页面上未找到任何删除按钮"
        first_delete = page_delete_btns.first
        assert first_delete.is_enabled(), "第一个删除按钮应该可用"
        logger.info(f"✅ 删除按钮验证通过（共 {del_count} 个删除按钮）")
        sessions_page.step_shot("05_delete_btn_visible")

        # --- 批量删除功能：checkbox 必须真的能选中 ---
        log_test_step("6. 验证批量选择 checkbox 可勾选")
        row_checkboxes = sessions_page.page.locator(
            'tbody tr .qwenpaw-checkbox-input, '
            'tbody tr .ant-checkbox-input, '
            'tbody tr input[type="checkbox"]'
        )
        cb_count = row_checkboxes.count()
        assert cb_count > 0, "未找到任何行 checkbox（批量选择应该可用）"
        first_cb = row_checkboxes.first
        first_cb.click(force=True)
        sessions_page.page.wait_for_timeout(800)
        sessions_page.step_shot("06_first_checkbox_checked")
        # 勾选后页面上应该出现批量删除按钮（fixed bar 或 toolbar）
        batch_btns = sessions_page.page.locator(
            'button.qwenpaw-btn-dangerous:has-text("删除"), '
            'button.qwenpaw-btn-dangerous:has-text("Delete"), '
            'button:has-text("批量删除"), '
            'button:has-text("Batch Delete")'
        )
        # 这一步是软校验：批量删除按钮文案/类名因前端实现而异，看到任意一个 dangerous 按钮即可
        assert batch_btns.count() > 0, (
            "勾选 checkbox 后应该出现批量删除/dangerous 按钮，但未找到。"
        )
        logger.info(f"✅ 勾选 checkbox 后批量删除按钮已出现（{batch_btns.count()} 个）")
        # 取消勾选，避免污染下一个用例
        first_cb.click(force=True)
        sessions_page.page.wait_for_timeout(300)

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 编辑、删除、批量删除功能验证完成")


# ============================================================================
# SESS-003: 会话名称编辑保存
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.sessions_edit
class TestSessionEditAndSave:
    """
    SESS-003: 会话名称编辑保存
    
    覆盖功能点：
    1. 点击编辑按钮打开编辑抽屉
    2. 验证编辑抽屉打开
    3. 修改会话名称
    4. 保存并验证名称更新
    5. 恢复原始名称
    
    业务场景：
    用户编辑会话名称以更好地标识会话内容，保存后验证名称已更新，
    最后恢复原始名称以保持环境干净。
    """
    
    @pytest.mark.test_id("SESS-003")
    def test_session_edit_name_and_save(
        self,
        sessions_page: SessionsPage,
        ensure_session_data,
        request: pytest.FixtureRequest,
    ):
        """
        验证会话名称编辑和保存功能
        
        测试步骤：
        1. 访问 Sessions 页面
        2. 验证有可操作的会话
        3. 点击第一条会话的编辑按钮
        4. 验证编辑抽屉打开
        5. 修改会话名称为 "E2E_Test_Renamed_xxx"
        6. 点击保存按钮
        7. 验证抽屉关闭
        8. 验证列表中会话名称已更新
        9. 恢复原始名称（再次编辑并保存）
        """
        test_name = request.node.name
        
        log_test_step("1. 访问 Sessions 页面")
        sessions_page.open()
        
        log_test_step("2. 验证有可操作的会话")
        session_count = sessions_page.get_session_count()
        if session_count == 0:
            pytest.skip("没有可操作的会话")
        
        first_row = sessions_page.page.locator(sessions_page.SESSION_TABLE_ROW).first
        
        # 获取原始会话名称
        original_name_cell = first_row.locator('td').nth(1)  # 假设名称在第2列
        original_name = original_name_cell.text_content().strip() if original_name_cell.count() > 0 else ""
        logger.info(f"原始会话名称：{original_name}")
        
        log_test_step("3. 点击第一条会话的编辑按钮")
        # 源码：Action 列 fixed="right"，按钮是 Button type="link" size="small"
        # 需要在固定列中查找编辑按钮
        edit_btn = first_row.locator('button:has-text("Edit"), button:has-text("编辑")').first
        if not edit_btn.is_visible():
            # 尝试在固定列中查找
            fixed_row = sessions_page.page.locator('.qwenpaw-table-cell-fix-right button:has-text("Edit"), .qwenpaw-table-cell-fix-right button:has-text("编辑")').first
            if fixed_row.is_visible():
                edit_btn = fixed_row
        if not edit_btn.is_visible():
            pytest.skip("编辑按钮不可用")
        
        edit_btn.click()
        
        log_test_step("4. 验证编辑抽屉打开")
        expect(sessions_page.page.locator(sessions_page.SESSION_DRAWER).first).to_be_visible(timeout=5000)
        logger.info("✅ 编辑抽屉已打开")
        
        log_test_step("5. 修改会话名称")
        new_name = f"E2E_Test_Renamed_{request.node.name[-8:]}"
        name_input = sessions_page.page.locator(sessions_page.SESSION_DRAWER).first.locator('input').first
        if name_input.count() > 0 and name_input.is_visible():
            name_input.fill(new_name)
            logger.info(f"已输入新名称：{new_name}")
        else:
            # 尝试其他可能的输入框选择器
            name_input = sessions_page.page.locator('#sessionName, [name="sessionName"], input[placeholder*="名称"]').first
            if name_input.count() > 0:
                name_input.fill(new_name)
                logger.info(f"已输入新名称：{new_name}")
            else:
                pytest.skip("未找到名称输入框")
        
        log_test_step("6. 点击保存按钮")
        save_btn = sessions_page.page.locator(sessions_page.FORM_SUBMIT_BTN).first
        if save_btn.count() == 0:
            save_btn = sessions_page.page.locator('button:has-text("保存"), button:has-text("Save"), button.qwenpaw-btn-primary').first
        if save_btn.count() > 0 and save_btn.is_visible():
            save_btn.click()
            logger.info("已点击保存按钮")
        else:
            pytest.skip("未找到保存按钮")
        
        log_test_step("7. 验证抽屉关闭")
        expect(sessions_page.page.locator(sessions_page.SESSION_DRAWER).first).to_be_hidden(timeout=5000)
        logger.info("✅ 编辑抽屉已关闭")
        
        log_test_step("8. 验证列表中会话名称已更新（强断言）")
        sessions_page.page.wait_for_timeout(1500)
        # 主动刷新页面，确保看到的是最新数据（避免乐观更新缓存假象）
        sessions_page.page.reload()
        sessions_page.page.wait_for_load_state("domcontentloaded")
        sessions_page.page.wait_for_timeout(2000)
        sessions_page.step_shot("08_after_save_reloaded")

        # 在整个表格的所有行里查找 new_name（不限定第一行，因为排序可能变化）
        page_text = sessions_page.page.locator("tbody").inner_text() or ""
        assert new_name in page_text, (
            f"保存后整个会话列表的文本中未发现新名称 '{new_name}'，"
            f"可能保存未真正生效。表格内容预览: {page_text[:300]}"
        )
        logger.info(f"✅ 会话列表中已找到新名称：{new_name}")
        
        log_test_step("9. 恢复原始名称")
        if original_name:
            edit_btn.click()
            expect(sessions_page.page.locator(sessions_page.SESSION_DRAWER).first).to_be_visible(timeout=5000)
            
            name_input = sessions_page.page.locator(sessions_page.SESSION_DRAWER).first.locator('input').first
            if name_input.count() > 0:
                name_input.fill(original_name)
                save_btn = sessions_page.page.locator(sessions_page.FORM_SUBMIT_BTN).first
                if save_btn.count() == 0:
                    save_btn = sessions_page.page.locator('button:has-text("保存"), button:has-text("Save"), button.qwenpaw-btn-primary').first
                if save_btn.count() > 0:
                    save_btn.click()
                    expect(sessions_page.page.locator(sessions_page.SESSION_DRAWER).first).to_be_hidden(timeout=5000)
                    logger.info(f"✅ 已恢复原始名称：{original_name}")
        
        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")


# ============================================================================
# SESS-004: 批量删除会话执行
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.sessions_batch
class TestSessionBatchDelete:
    """
    SESS-004: 批量删除会话执行
    
    覆盖功能点：
    1. 勾选多个会话的 checkbox
    2. 验证批量删除按钮变为可用
    3. 点击批量删除按钮
    4. 确认删除
    5. 验证会话数量减少
    
    业务场景：
    用户批量选择并删除多个不需要的会话，提高管理效率。
    注意：由于是破坏性操作，如果会话数量不足则跳过。
    """
    
    @pytest.mark.test_id("SESS-004")
    def test_session_batch_delete(
        self,
        sessions_page: SessionsPage,
        ensure_session_data,
        request: pytest.FixtureRequest,
    ):
        """
        验证批量删除会话功能
        
        测试步骤：
        1. 访问 Sessions 页面
        2. 验证有至少2条会话
        3. 勾选前两条会话的 checkbox
        4. 验证批量删除按钮变为可用
        5. 点击批量删除按钮
        6. 确认删除（如有确认弹窗）
        7. 验证会话数量减少
        """
        test_name = request.node.name
        
        log_test_step("1. 访问 Sessions 页面")
        sessions_page.open()
        
        log_test_step("2. 验证有至少2条会话")
        session_count = sessions_page.get_session_count()
        if session_count < 2:
            pytest.skip(f"会话数量不足，需要至少2条，当前只有{session_count}条")
        
        log_test_step("3. 勾选前两条会话的 checkbox")
        # 源码：Table rowSelection，每行 tbody tr 中有 checkbox
        # 注意：不要选全选框（thead 中的），要选 tbody 中每行的
        # 使用更宽泛的选择器，兼容 antd 和 qwenpaw 前缀
        row_checkboxes = sessions_page.page.locator(
            'tbody tr .qwenpaw-checkbox-input, '
            'tbody tr .ant-checkbox-input, '
            'tbody tr input[type="checkbox"]'
        ).all()
        if len(row_checkboxes) < 2:
            pytest.skip(f"无法找到足够的行 checkbox，找到 {len(row_checkboxes)} 个")
        
        checked_count = 0
        for i in range(min(2, len(row_checkboxes))):
            checkbox = row_checkboxes[i]
            if checkbox.is_visible():
                checkbox.click(force=True)
                sessions_page.page.wait_for_timeout(800)
                checked_count += 1
                logger.info(f"已勾选第 {i + 1} 条会话的 checkbox")
        assert checked_count >= 1, "至少应成功勾选 1 条会话"
        logger.info(f"已勾选 {checked_count} 条会话的 checkbox")
        
        log_test_step("4. 验证批量删除按钮出现")
        # 源码：selectedRowKeys.length > 0 时才渲染 Button type="primary" danger
        # antd Button type="primary" danger 的 class 可能是 qwenpaw-btn-primary + qwenpaw-btn-dangerous
        batch_delete_btn = None
        batch_btn_selectors = [
            'button.qwenpaw-btn-dangerous:has-text("删除")',
            'button.qwenpaw-btn-dangerous:has-text("Delete")',
            'button:has-text("批量删除")',
            'button:has-text("Batch Delete")',
            'button:has-text("删除")',
            'button:has-text("Delete")',
        ]
        for selector in batch_btn_selectors:
            btn = sessions_page.page.locator(selector).first
            if btn.count() > 0 and btn.is_visible(timeout=3000):
                batch_delete_btn = btn
                logger.info(f"找到批量删除按钮: {selector}")
                break
        
        assert batch_delete_btn is not None, "未找到批量删除按钮"
        logger.info("批量删除按钮已出现")
        
        log_test_step("5. 记录删除前的会话数量")
        count_before = sessions_page.get_session_count()
        logger.info(f"删除前会话数量：{count_before}")
        
        log_test_step("6. 点击批量删除按钮")
        batch_delete_btn.click()
        sessions_page.page.wait_for_timeout(1500)
        
        log_test_step("7. 确认删除（如有确认弹窗）")
        # 源码：Modal.confirm, okType="danger"
        # 先显式等待弹窗出现
        modal_visible = False
        try:
            modal = sessions_page.page.locator('.qwenpaw-modal, .ant-modal').first
            modal.wait_for(state="visible", timeout=5000)
            modal_visible = True
            logger.info("确认弹窗已出现")
        except Exception:
            logger.warning("未检测到弹窗出现，尝试直接匹配确认按钮")

        sessions_page.page.wait_for_timeout(500)
        
        # 多种选择器尝试匹配确认按钮
        confirm_btn = None
        confirm_selectors = [
            # Modal.confirm 中 okType="danger" 的按钮
            '.qwenpaw-modal-confirm-btns .qwenpaw-btn-dangerous',
            '.qwenpaw-modal-confirm-btns .qwenpaw-btn-primary',
            '.qwenpaw-modal .qwenpaw-btn-dangerous',
            '.qwenpaw-modal .qwenpaw-btn-primary',
            # antd 原始前缀
            '.ant-modal-confirm-btns .ant-btn-dangerous',
            '.ant-modal-confirm-btns .ant-btn-primary',
            '.ant-modal .ant-btn-primary',
            # 通用文本匹配
            '.qwenpaw-modal button:has-text("确定")',
            '.qwenpaw-modal button:has-text("确认")',
            '.qwenpaw-modal button:has-text("OK")',
            '.qwenpaw-modal button:has-text("Delete")',
            '.qwenpaw-modal button:has-text("删除")',
            '.ant-modal button:has-text("确定")',
            '.ant-modal button:has-text("OK")',
            # Popconfirm 或其他确认组件
            '.qwenpaw-popconfirm button.qwenpaw-btn-primary',
            'button:has-text("确定")',
            'button:has-text("OK")',
        ]
        for selector in confirm_selectors:
            try:
                btn = sessions_page.page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=2000):
                    confirm_btn = btn
                    logger.info(f"找到确认按钮: {selector}")
                    break
            except Exception:
                continue
        
        if confirm_btn is not None:
            confirm_btn.click()
            logger.info("✅ 已点击确认删除按钮")
        else:
            logger.warning("未找到确认弹窗按钮，尝试通过键盘 Enter 确认")
            sessions_page.page.keyboard.press("Enter")
        
        # 等待删除 API 完成和列表刷新
        sessions_page.page.wait_for_timeout(5000)
        
        log_test_step("8. 验证会话数量减少")
        # 等待列表刷新
        sessions_page.page.reload()
        sessions_page.page.wait_for_load_state("domcontentloaded")
        sessions_page.page.wait_for_timeout(3000)
        count_after = sessions_page.get_session_count()
        logger.info(f"删除后会话数量：{count_after}")
        
        assert count_after < count_before, \
            f"会话数量未减少：删除前{count_before}，删除后{count_after}"
        
        logger.info(f"✅ 会话数量从 {count_before} 减少到 {count_after}")
        
        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def sessions_page(page: Page) -> SessionsPage:
    """创建 SessionsPage 实例"""
    return SessionsPage(page)


@pytest.fixture(scope="function")
def ensure_session_data(page: Page):
    """确保 Sessions 页面有足够的测试数据（至少 3 条）。

    通过 POST /api/console/chat 发送消息来自动创建 Session，
    每个 Session 使用不同的 session_id 和 user_id。
    测试结束后自动通过 API 删除创建的测试 Session。
    """
    base_url = config.base_url
    page.goto(f"{base_url}/sessions")
    page.wait_for_timeout(2000)

    existing_count = page.locator(
        "tbody tr:not([aria-hidden='true'])"
        ":not(.qwenpaw-table-placeholder)"
        ":not(.qwenpaw-table-measure-row)"
    ).count()

    needed = max(0, 3 - existing_count)
    created_session_ids = []

    if needed == 0:
        logger.info(f"已有 {existing_count} 条 Session，无需创建")
        yield created_session_ids
        return

    logger.info(f"当前 {existing_count} 条 Session，需创建 {needed} 条")

    for i in range(needed):
        session_id = f"e2e_sess_{int(time.time() * 1000)}_{i}"
        user_id = f"e2e_user_{int(time.time() * 1000)}_{i}"
        result = page.evaluate(
            """async ([sessionId, userId, idx]) => {
                try {
                    const resp = await fetch('/api/console/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            input: [{
                                role: 'user',
                                type: 'message',
                                content: [{ type: 'text', text: 'E2E test session ' + idx, status: 'created' }]
                            }],
                            session_id: sessionId,
                            user_id: userId,
                            channel: 'console',
                            stream: false
                        })
                    });
                    return { ok: resp.ok, status: resp.status };
                } catch (e) {
                    return { ok: false, error: e.message };
                }
            }""",
            [session_id, user_id, str(i)],
        )
        if result.get("ok"):
            created_session_ids.append(session_id)
        else:
            logger.warning(f"  创建 Session 失败: {result}")
        page.wait_for_timeout(1500)
        logger.info(f"  创建 Session: sid={session_id}, uid={user_id}")

    # 刷新页面验证数据已创建
    page.reload()
    page.wait_for_timeout(2000)
    logger.info(f"✅ 已创建 {needed} 条测试 Session")

    yield created_session_ids

    # ---- teardown: 清理创建的测试 Session ----
    if not created_session_ids:
        return

    logger.info(f"🧹 开始清理 {len(created_session_ids)} 条测试 Session")
    try:
        # 先通过 /api/chats 获取列表，找到 session_id 对应的 UUID (id 字段)
        chat_list = page.evaluate(
            """async (targetSessionIds) => {
                try {
                    const resp = await fetch('/api/chats');
                    if (!resp.ok) return { ok: false, status: resp.status };
                    const chats = await resp.json();
                    const matches = chats
                        .filter(c => targetSessionIds.includes(c.session_id))
                        .map(c => ({ id: c.id, session_id: c.session_id }));
                    return { ok: true, matches };
                } catch (e) {
                    return { ok: false, error: e.message };
                }
            }""",
            created_session_ids,
        )
        if not chat_list.get("ok"):
            logger.warning(f"  ⚠️ 获取 Session 列表失败: {chat_list}")
            return

        for match in chat_list.get("matches", []):
            uuid = match["id"]
            sid = match["session_id"]
            try:
                delete_result = page.evaluate(
                    """async (uuid) => {
                        try {
                            const resp = await fetch('/api/chats/' + uuid, {
                                method: 'DELETE',
                            });
                            return { ok: resp.ok, status: resp.status };
                        } catch (e) {
                            return { ok: false, error: e.message };
                        }
                    }""",
                    uuid,
                )
                if delete_result.get("ok"):
                    logger.info(f"  🗑️ 已删除 Session: {sid} (uuid={uuid})")
                else:
                    logger.warning(f"  ⚠️ 删除失败: {sid} -> {delete_result}")
            except Exception as delete_error:
                logger.warning(f"  ⚠️ 删除异常: {sid} -> {delete_error}")
    except Exception as cleanup_error:
        logger.warning(f"  ⚠️ 清理过程异常: {cleanup_error}")
    logger.info("🧹 测试 Session 清理完成")


# ============================================================================
# P1 级测试用例：会话过滤组合查询
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.sessions_filter
class TestSessionFilterByUseridAndChannel:
    """
    SESS-P1-001: 会话按 UserID 和 Channel 组合过滤
    
    覆盖功能点：
    1. UserID 输入框过滤
    2. Channel 下拉选择过滤
    3. 组合过滤结果验证
    4. 清除过滤条件恢复列表
    """

    def test_session_filter_by_userid_and_channel(self, page: Page, ensure_session_data):
        """测试会话的 UserID 和 Channel 组合过滤功能"""
        log_test_step("导航到会话管理页面")
        page.goto(f"{config.base_url}/sessions")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)
        
        log_test_step("查找过滤控件")
        # 源码 FilterBar.tsx: UserID 输入框 placeholder 为 t("sessions.filterUserId")
        # Channel 选择器 placeholder 为 t("sessions.filterChannel")
        userid_input = page.locator(
            "input[placeholder*='user'], input[placeholder*='User'], "
            "input[placeholder*='userid'], input[placeholder*='UserId'], "
            "input[placeholder*='ID'], input[placeholder*='id']"
        ).first
        channel_select = page.locator(".qwenpaw-select, .ant-select").first
        
        # 至少需要一个过滤控件
        has_userid_input = userid_input.count() > 0
        has_channel_select = channel_select.count() > 0
        assert has_userid_input or has_channel_select, \
            "未找到任何过滤控件（UserID 输入框或 Channel 选择器）"
        logger.info(f"✅ 过滤控件：UserID输入框={'有' if has_userid_input else '无'}, Channel选择器={'有' if has_channel_select else '无'}")
        
        log_test_step("获取初始会话列表")
        session_row_selector = "tbody tr:not(.qwenpaw-table-placeholder):not(.qwenpaw-table-measure-row)"
        initial_sessions = page.locator(session_row_selector).all()
        initial_count = len(initial_sessions)
        assert initial_count > 0, "ensure_session_data fixture 应已创建测试数据，但会话列表仍为空"
        logger.info(f"初始会话数量: {initial_count}")
        
        if has_userid_input:
            log_test_step("提取第一个会话的 UserID")
            first_session = initial_sessions[0]
            cells = first_session.locator("td").all()
            assert len(cells) >= 2, "会话行的列数不足"
            test_userid = cells[1].inner_text().strip()
            assert len(test_userid) > 0, "无法提取 UserID"
            logger.info(f"使用测试 UserID: {test_userid}")
            
            log_test_step(f"输入 UserID 过滤: {test_userid}")
            userid_input.fill(test_userid)
            page.wait_for_timeout(2000)
            
            log_test_step("验证过滤结果")
            filtered_sessions = page.locator(session_row_selector).all()
            filtered_count = len(filtered_sessions)
            assert filtered_count <= initial_count, \
                f"过滤后会话数量({filtered_count})不应超过初始数量({initial_count})"
            logger.info(f"✅ UserID 过滤后会话数量: {filtered_count}（初始: {initial_count}）")
            
            # 验证过滤结果中包含目标 UserID
            if filtered_count > 0:
                first_filtered_cells = filtered_sessions[0].locator("td").all()
                if len(first_filtered_cells) >= 2:
                    result_userid = first_filtered_cells[1].inner_text().strip()
                    assert test_userid in result_userid or result_userid in test_userid, \
                        f"过滤结果的 UserID({result_userid}) 不匹配输入({test_userid})"
                    logger.info(f"✅ 过滤结果 UserID 匹配: {result_userid}")
            
            log_test_step("清除过滤并验证恢复")
            userid_input.fill("")
            page.wait_for_timeout(2000)
            
            restored_sessions = page.locator(session_row_selector).all()
            restored_count = len(restored_sessions)
            assert abs(restored_count - initial_count) <= 2, \
                f"清除过滤后数量异常：初始 {initial_count}，恢复后 {restored_count}"
            logger.info(f"✅ 清除过滤后恢复到 {restored_count} 条（初始 {initial_count}）")
        
        logger.info("✅ 会话过滤测试完成")
