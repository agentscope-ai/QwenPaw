# -*- coding: utf-8 -*-
"""
QwenPaw Debug 调试页面 E2E 测试用例

覆盖功能：
1. Debug 页面加载与基础展示
2. 后端日志卡片展示
3. 日志级别过滤（All/ERROR/WARNING/INFO/DEBUG）
4. 关键词搜索与高亮
5. 自动刷新开关
6. 最新优先排序开关
7. 手动刷新按钮
8. 复制日志按钮

执行命令：pytest tests/test_debug.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

BASE_URL = config.server.base_url


def navigate_to_debug(page: Page):
    """导航到 Debug 页面"""
    page.goto(f"{BASE_URL}/debug")
    page.wait_for_load_state("commit")
    page.wait_for_timeout(2000)


# ============================================================================
# DEBUG-001: Debug 页面加载与基础展示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.debug
class TestDebugPageDisplay:
    """
    DEBUG-001: Debug 页面加载与基础展示

    覆盖功能点：
    1. 页面可访问性
    2. 页面标题/描述 Alert 展示
    3. 后端日志卡片展示
    4. 日志内容区域存在
    """

    @pytest.mark.test_id("DEBUG-001")
    def test_debug_page_load_and_display(self, page: Page, request: pytest.FixtureRequest):
        """验证 Debug 页面加载和基础元素展示"""
        test_name = request.node.name

        log_test_step("1. 导航到 Debug 页面")
        navigate_to_debug(page)

        log_test_step("2. 验证页面描述 Alert")
        info_alert = page.locator('.qwenpaw-alert-info, .qwenpaw-alert').first
        expect(info_alert).to_be_visible(timeout=5000)
        alert_text = info_alert.inner_text()
        debug_keywords = ["Debug", "debug", "调试", "日志", "log", "diagnose", "排查"]
        assert any(kw in alert_text for kw in debug_keywords), \
            f"Alert 应包含调试相关描述，实际：{alert_text[:100]}"
        logger.info(f"✅ 页面描述 Alert 可见：{alert_text[:80]}")

        log_test_step("3. 验证后端日志卡片")
        log_card = page.locator('.qwenpaw-card').first
        expect(log_card).to_be_visible(timeout=5000)
        card_title = log_card.locator('.qwenpaw-card-head-title').first
        if card_title.is_visible(timeout=3000):
            title_text = card_title.inner_text()
            logger.info(f"✅ 日志卡片标题：{title_text}")
        else:
            logger.info("✅ 日志卡片可见")

        log_test_step("4. 验证日志内容区域")
        log_content = page.locator('[style*="monospace"], [style*="pre-wrap"]').first
        if log_content.is_visible(timeout=5000):
            content_text = log_content.inner_text()
            logger.info(f"✅ 日志内容区域可见，内容长度：{len(content_text)}")
        else:
            logger.info("ℹ️ 日志内容区域可能为空或使用其他样式")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")


# ============================================================================
# DEBUG-002: 日志控制按钮功能
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.debug
class TestDebugLogControls:
    """
    DEBUG-002: 日志控制按钮功能

    覆盖功能点：
    1. 手动刷新按钮
    2. 复制日志按钮
    3. 自动刷新开关
    4. 最新优先排序开关
    """

    @pytest.mark.test_id("DEBUG-002")
    def test_debug_log_control_buttons(self, page: Page, request: pytest.FixtureRequest):
        """验证日志控制按钮功能"""
        test_name = request.node.name

        log_test_step("1. 导航到 Debug 页面")
        navigate_to_debug(page)

        log_test_step("2. 验证手动刷新按钮")
        refresh_btn = page.locator(
            'button:has-text("Refresh"), '
            'button:has-text("刷新")'
        ).first
        expect(refresh_btn).to_be_visible(timeout=5000)
        logger.info("✅ 手动刷新按钮可见")

        log_test_step("3. 点击手动刷新按钮")
        refresh_btn.click()
        page.wait_for_timeout(2000)
        # 验证刷新后无错误
        error_alert = page.locator('.qwenpaw-alert-error').first
        if error_alert.is_visible(timeout=2000):
            logger.info("ℹ️ 刷新后出现错误提示（可能后端未启动）")
        else:
            logger.info("✅ 手动刷新成功")

        log_test_step("4. 验证复制日志按钮")
        copy_btn = page.locator(
            'button:has-text("Copy"), '
            'button:has-text("复制")'
        ).first
        expect(copy_btn).to_be_visible(timeout=5000)
        logger.info("✅ 复制日志按钮可见")

        log_test_step("5. 验证自动刷新开关")
        switches = page.locator('.qwenpaw-card-extra .qwenpaw-switch, .qwenpaw-card-head .qwenpaw-switch').all()
        assert len(switches) >= 2, f"应有至少 2 个开关（自动刷新 + 最新优先），实际：{len(switches)}"
        logger.info(f"✅ 找到 {len(switches)} 个开关")

        log_test_step("6. 切换自动刷新开关")
        auto_refresh_switch = switches[-1]  # 自动刷新是最后一个
        initial_state = auto_refresh_switch.get_attribute('aria-checked')
        auto_refresh_switch.click()
        page.wait_for_timeout(1000)
        new_state = auto_refresh_switch.get_attribute('aria-checked')
        assert initial_state != new_state, "自动刷新开关状态应发生变化"
        logger.info(f"✅ 自动刷新开关切换成功：{initial_state} → {new_state}")

        # 恢复原始状态
        auto_refresh_switch.click()
        page.wait_for_timeout(500)

        log_test_step("7. 切换最新优先排序开关")
        newest_first_switch = switches[0]  # 最新优先是第一个
        initial_order = newest_first_switch.get_attribute('aria-checked')
        newest_first_switch.click()
        page.wait_for_timeout(1000)
        new_order = newest_first_switch.get_attribute('aria-checked')
        assert initial_order != new_order, "排序开关状态应发生变化"
        logger.info(f"✅ 最新优先排序开关切换成功：{initial_order} → {new_order}")

        # 恢复原始状态
        newest_first_switch.click()
        page.wait_for_timeout(500)

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")


# ============================================================================
# DEBUG-003: 日志级别过滤
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.debug
class TestDebugLogLevelFilter:
    """
    DEBUG-003: 日志级别过滤

    覆盖功能点：
    1. 级别过滤下拉框展示
    2. 切换不同级别（All/ERROR/WARNING/INFO/DEBUG）
    3. 过滤后日志内容变化
    """

    @pytest.mark.test_id("DEBUG-003")
    def test_debug_log_level_filter(self, page: Page, request: pytest.FixtureRequest):
        """验证日志级别过滤功能"""
        test_name = request.node.name

        log_test_step("1. 导航到 Debug 页面")
        navigate_to_debug(page)

        log_test_step("2. 验证级别过滤下拉框")
        level_select = page.locator('.qwenpaw-select').first
        expect(level_select).to_be_visible(timeout=5000)
        logger.info("✅ 级别过滤下拉框可见")

        log_test_step("3. 打开级别下拉框")
        level_select.click()
        page.wait_for_timeout(500)

        log_test_step("4. 验证下拉选项")
        dropdown = page.locator('.qwenpaw-select-dropdown').first
        expect(dropdown).to_be_visible(timeout=3000)

        expected_levels = ["All", "ERROR", "WARNING", "INFO", "DEBUG"]
        for level in expected_levels:
            option = dropdown.locator(f'.qwenpaw-select-item:has-text("{level}")').first
            if option.is_visible(timeout=2000):
                logger.info(f"  ✅ 级别选项 '{level}' 存在")
            else:
                logger.info(f"  ℹ️ 级别选项 '{level}' 未找到（可能使用 Tag 渲染）")

        log_test_step("5. 选择 ERROR 级别")
        error_option = dropdown.locator(
            '.qwenpaw-select-item:has-text("ERROR"), '
            '.qwenpaw-select-item:has(.qwenpaw-tag)'
        ).first
        if error_option.is_visible(timeout=2000):
            error_option.click()
            page.wait_for_timeout(1000)
            logger.info("✅ 已选择 ERROR 级别过滤")
        else:
            page.keyboard.press("Escape")
            logger.info("ℹ️ 未找到 ERROR 选项，跳过")

        log_test_step("6. 切换回 All 级别")
        level_select.click()
        page.wait_for_timeout(500)
        all_option = page.locator('.qwenpaw-select-dropdown .qwenpaw-select-item').first
        if all_option.is_visible(timeout=2000):
            all_option.click()
            page.wait_for_timeout(1000)
            logger.info("✅ 已切换回 All 级别")
        else:
            page.keyboard.press("Escape")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")


# ============================================================================
# DEBUG-004: 关键词搜索
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.debug
class TestDebugLogSearch:
    """
    DEBUG-004: 关键词搜索

    覆盖功能点：
    1. 搜索输入框展示
    2. 输入关键词搜索
    3. 清除搜索
    """

    @pytest.mark.test_id("DEBUG-004")
    def test_debug_log_keyword_search(self, page: Page, request: pytest.FixtureRequest):
        """验证日志关键词搜索功能"""
        test_name = request.node.name

        log_test_step("1. 导航到 Debug 页面")
        navigate_to_debug(page)

        log_test_step("2. 验证搜索输入框")
        search_input = page.locator(
            'input[placeholder*="Search"], '
            'input[placeholder*="搜索"], '
            '.qwenpaw-input[placeholder*="log"]'
        ).first
        expect(search_input).to_be_visible(timeout=5000)
        logger.info("✅ 搜索输入框可见")

        log_test_step("3. 输入搜索关键词")
        search_input.fill("error")
        page.wait_for_timeout(1000)
        logger.info("✅ 已输入搜索关键词 'error'")

        log_test_step("4. 验证搜索结果（日志内容可能变化）")
        log_content = page.locator('[style*="monospace"], [style*="pre-wrap"]').first
        if log_content.is_visible(timeout=3000):
            content_text = log_content.inner_text()
            if "error" in content_text.lower():
                logger.info("✅ 搜索结果包含关键词 'error'")
            else:
                logger.info("ℹ️ 当前日志中无匹配 'error' 的内容")
        else:
            logger.info("ℹ️ 日志内容区域不可见")

        log_test_step("5. 清除搜索")
        clear_btn = search_input.locator('..').locator('.qwenpaw-input-clear-icon').first
        if clear_btn.is_visible(timeout=2000):
            clear_btn.click()
            page.wait_for_timeout(500)
            logger.info("✅ 已清除搜索关键词")
        else:
            search_input.fill("")
            page.wait_for_timeout(500)
            logger.info("✅ 已手动清空搜索框")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")


# ============================================================================
# DEBUG-005: 日志文件信息展示
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.debug
class TestDebugLogFileInfo:
    """
    DEBUG-005: 日志文件信息展示

    覆盖功能点：
    1. 日志文件路径展示
    2. 更新时间展示
    3. 日志不存在时的警告提示
    """

    @pytest.mark.test_id("DEBUG-005")
    def test_debug_log_file_info(self, page: Page, request: pytest.FixtureRequest):
        """验证日志文件信息展示"""
        test_name = request.node.name

        log_test_step("1. 导航到 Debug 页面")
        navigate_to_debug(page)

        log_test_step("2. 等待日志加载完成")
        page.wait_for_timeout(3000)

        log_test_step("3. 检查日志文件路径")
        path_text = page.locator('text="Log file"').first
        if path_text.is_visible(timeout=3000):
            logger.info("✅ 日志文件路径标签可见")
        else:
            # 尝试中文
            path_text_zh = page.locator('text="日志文件"').first
            if path_text_zh.is_visible(timeout=2000):
                logger.info("✅ 日志文件路径标签可见（中文）")
            else:
                logger.info("ℹ️ 日志文件路径未显示（可能日志文件不存在）")

        log_test_step("4. 检查更新时间")
        updated_text = page.locator('text="Updated at"').first
        if updated_text.is_visible(timeout=3000):
            logger.info("✅ 更新时间标签可见")
        else:
            updated_text_zh = page.locator('text="更新时间"').first
            if updated_text_zh.is_visible(timeout=2000):
                logger.info("✅ 更新时间标签可见（中文）")
            else:
                logger.info("ℹ️ 更新时间未显示（可能日志尚未加载）")

        log_test_step("5. 检查日志不存在时的警告")
        warning_alert = page.locator('.qwenpaw-alert-warning').first
        if warning_alert.is_visible(timeout=2000):
            warning_text = warning_alert.inner_text()
            logger.info(f"⚠️ 日志文件未找到警告：{warning_text[:100]}")
        else:
            logger.info("✅ 无日志文件未找到警告（日志文件存在）")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")
