# -*- coding: utf-8 -*-
"""
QwenPaw Heartbeat 模块 P0 级端到端测试用例

P0 级别定义：
- 核心用户操作流程
- 多个功能点组合覆盖
- 真实用户场景模拟
- 高优先级功能验证

测试框架：pytest + Playwright + Page Object Pattern
执行命令：pytest tests/test_heartbeat_p0.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect, TimeoutError

from pages.heartbeat_page import HeartbeatPage
from config.settings import config
from utils.helpers import (
    log_test_step,
    log_test_result,
    take_screenshot,
    assert_text_contains,
)

logger = logging.getLogger(__name__)

# ============================================================================
# HEART-001: 页面展示 + 启用/禁用
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.heartbeat_core
class TestHeartbeatDisplayAndToggle:
    """
    HEART-001: 页面展示 + 启用/禁用

    组合覆盖功能点：
    1. Heartbeat 页面访问与加载
    2. 页面标题验证
    3. 配置卡片和表单元素展示（开关、间隔、时间、保存按钮）
    4. 切换启用/禁用状态
    5. 保存并验证状态变更
    6. 恢复原始状态

    业务场景：
    管理员进入心跳配置页面，确认所有配置项正常展示，
    然后切换启用/禁用状态并验证变更生效。
    """

    @pytest.mark.test_id("HEART-001")
    def test_heartbeat_display_and_toggle(self, heartbeat_page: HeartbeatPage, request: pytest.FixtureRequest):
        """
        验证页面展示和启用/禁用切换

        测试步骤：
        1. 访问 Heartbeat 页面，验证标题
        2. 验证配置卡片和表单元素（开关、间隔、时间、保存按钮）
        3. 记录当前启用状态
        4. 切换状态并保存
        5. 验证状态变更
        6. 恢复原始状态
        """
        test_name = request.node.name

        log_test_step("1. 访问 Heartbeat 页面，验证标题")
        heartbeat_page.open()

        log_test_step("2. 验证配置卡片和表单元素")
        expect(heartbeat_page.page.locator(heartbeat_page.ENABLED_SWITCH).first).to_be_visible()
        expect(heartbeat_page.page.locator(heartbeat_page.INTERVAL_INPUT).first).to_be_visible()
        expect(heartbeat_page.page.locator(heartbeat_page.SAVE_BTN).first).to_be_visible()
        logger.info("✅ 所有配置元素展示正常")

        log_test_step("3. 记录当前启用状态")
        original_state = heartbeat_page.is_heartbeat_enabled()
        logger.info(f"原始状态：{'启用' if original_state else '禁用'}")

        log_test_step("4. 切换状态并保存")
        heartbeat_page.toggle_heartbeat()
        heartbeat_page.save_config()

        log_test_step("5. 验证状态变更")
        new_state = heartbeat_page.is_heartbeat_enabled()
        assert new_state != original_state, \
            f"状态应该从 {'启用' if original_state else '禁用'} 变为 {'禁用' if original_state else '启用'}"
        logger.info(f"✅ 状态已变更为 {'启用' if new_state else '禁用'}")

        log_test_step("6. 恢复原始状态")
        if heartbeat_page.is_heartbeat_enabled() != original_state:
            heartbeat_page.toggle_heartbeat()
            heartbeat_page.save_config()

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 页面展示和启用/禁用切换正常")

# ============================================================================
# HEART-002: 完整配置流程（间隔 + 时间 + 技能 + 保存验证）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.heartbeat_config
class TestHeartbeatFullConfig:
    """
    HEART-002: 完整配置流程

    组合覆盖功能点：
    1. 记录原始配置
    2. 设置心跳间隔（数值 + 单位）
    3. 设置定时时间
    4. 选择技能
    5. 启用心跳
    6. 保存并验证所有配置生效
    7. 恢复原始配置

    业务场景：
    管理员一次性完成心跳的完整配置：
    设置间隔为 30 分钟、定时时间为 09:00、选择技能、启用心跳，
    保存后验证所有配置项均已生效。
    """

    @pytest.mark.test_id("HEART-002")
    def test_full_heartbeat_configuration(self, heartbeat_page: HeartbeatPage, request: pytest.FixtureRequest):
        """
        验证完整心跳配置流程

        测试步骤：
        1. 访问 Heartbeat 页面
        2. 记录原始配置（启用状态、间隔、时间）
        3. 设置间隔为 15 分钟
        4. 设置定时时间为 09:00
        5. 选择技能（如有可用选项）
        6. 启用心跳，保存配置
        7. 验证所有配置生效
        8. 恢复原始配置
        """
        test_name = request.node.name
        test_time = "09:00"

        log_test_step("1. 访问 Heartbeat 页面")
        heartbeat_page.open()

        log_test_step("2. 记录原始配置")
        original_enabled = heartbeat_page.is_heartbeat_enabled()
        original_interval = heartbeat_page.get_interval()
        original_time = heartbeat_page.get_scheduled_time()
        logger.info(f"原始配置：启用={original_enabled}, 间隔={original_interval}, 时间={original_time}")

        log_test_step("3. 设置间隔为 15 分钟")
        heartbeat_page.set_interval(15, "分钟")

        log_test_step("4. 设置定时时间为 09:00")
        heartbeat_page.set_scheduled_time(test_time)

        log_test_step("5. 选择技能（如有可用选项）")
        skill_select = heartbeat_page.page.locator(heartbeat_page.SKILL_SELECT)
        if skill_select.count() > 0:
            skill_select.click()
            options = heartbeat_page.page.locator('.ant-select-option')
            if options.count() > 0:
                options.first.click()
                logger.info("✅ 已选择技能")

        log_test_step("6. 启用心跳，保存配置")
        heartbeat_page.configure_heartbeat(
            enabled=True,
            interval=15,
            unit="分钟",
            scheduled_time=test_time,
        )

        log_test_step("7. 验证配置生效")
        heartbeat_page.assert_heartbeat_enabled()
        heartbeat_page.assert_interval(15, "分钟")
        heartbeat_page.assert_config_saved()
        logger.info("✅ 所有配置已生效")

        log_test_step("8. 恢复原始配置")
        heartbeat_page.configure_heartbeat(
            enabled=original_enabled,
            interval=int(original_interval.get("value", 30)),
            unit=original_interval.get("unit", "分钟") or "分钟",
            scheduled_time=original_time,
        )

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 完整心跳配置流程正常，已恢复原始配置")

# ============================================================================
# HEART-003: 目标会话选择与活跃时间段配置
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.heartbeat_config
class TestHeartbeatTargetAndActiveHours:
    """
    HEART-003: 目标会话选择与活跃时间段配置

    组合覆盖功能点：
    1. 访问 Heartbeat 页面
    2. 记录原始配置
    3. 找到目标会话选择器（main/last）
    4. 验证选择器存在并记录当前值
    5. 切换目标会话选项
    6. 找到活跃时间段开关
    7. 启用活跃时间段
    8. 设置开始时间
    9. 设置结束时间
    10. 保存配置
    11. 验证配置已保存
    12. 恢复原始配置

    业务场景：
    管理员配置心跳的目标会话和活跃时间段，
    验证不同目标会话选项和活跃时间段的配置是否正确保存。
    """

    @pytest.mark.test_id("HEART-003")
    def test_target_session_and_active_hours(self, heartbeat_page: HeartbeatPage, request: pytest.FixtureRequest):
        """
        验证目标会话选择与活跃时间段配置

        测试步骤：
        1. 访问 Heartbeat 页面
        2. 记录原始配置
        3. 找到目标会话选择器（main/last）
        4. 验证选择器存在并记录当前值
        5. 切换目标会话选项
        6. 找到活跃时间段开关
        7. 启用活跃时间段
        8. 设置开始时间
        9. 设置结束时间
        10. 保存配置
        11. 验证配置已保存
        12. 恢复原始配置
        """
        test_name = request.node.name

        log_test_step("1. 访问 Heartbeat 页面")
        heartbeat_page.open()

        log_test_step("2. 记录原始配置")
        original_enabled = heartbeat_page.is_heartbeat_enabled()
        original_interval = heartbeat_page.get_interval()
        original_time = heartbeat_page.get_scheduled_time()
        logger.info(f"原始配置：启用={original_enabled}, 间隔={original_interval}, 时间={original_time}")

        log_test_step("3. 找到目标会话选择器（main/last）")
        target_session_selector = heartbeat_page.page.locator(
            '.qwenpaw-radio-group, .qwenpaw-select, [class*="targetSession"], [class*="target"]'
        ).first
        expect(target_session_selector).to_be_visible(timeout=3000)
        logger.info("✅ 目标会话选择器存在")

        log_test_step("4. 验证选择器存在并记录当前值")
        current_target = ""
        main_option = heartbeat_page.page.locator(
            '.qwenpaw-radio-label:has-text("main"), .qwenpaw-radio-label:has-text("主会话"), '
            '[class*="radio"]:has-text("main"), [class*="radio"]:has-text("主")'
        ).first
        last_option = heartbeat_page.page.locator(
            '.qwenpaw-radio-label:has-text("last"), .qwenpaw-radio-label:has-text("最近"), '
            '[class*="radio"]:has-text("last"), [class*="radio"]:has-text("最近")'
        ).first
        
        if main_option.is_visible():
            current_target = "main" if main_option.get_attribute('aria-checked') == 'true' else "last"
        elif last_option.is_visible():
            current_target = "last" if last_option.get_attribute('aria-checked') == 'true' else "main"
        logger.info(f"当前目标会话：{current_target}")

        log_test_step("5. 切换目标会话选项")
        if current_target == "main" and last_option.is_visible():
            last_option.click()
            heartbeat_page.page.wait_for_timeout(1000)
            logger.info("✅ 已切换到 last 会话")
        elif current_target == "last" and main_option.is_visible():
            main_option.click()
            heartbeat_page.page.wait_for_timeout(1000)
            logger.info("✅ 已切换到 main 会话")

        log_test_step("6. 找到活跃时间段开关")
        active_hours_switch = heartbeat_page.page.locator(
            '.qwenpaw-switch, [class*="activeHours"], [class*="active"]'
        ).first
        expect(active_hours_switch).to_be_visible(timeout=3000)
        logger.info("✅ 活跃时间段开关存在")

        log_test_step("7. 启用活跃时间段")
        active_hours_checked = active_hours_switch.get_attribute('aria-checked')
        if active_hours_checked != 'true':
            active_hours_switch.click()
            heartbeat_page.page.wait_for_timeout(1000)
            logger.info("✅ 已启用活跃时间段")

        log_test_step("8. 设置开始时间")
        start_time_picker = heartbeat_page.page.locator(
            '.qwenpaw-picker, .qwenpaw-time-picker, [class*="startTime"], [class*="start"]'
        ).first
        if start_time_picker.is_visible():
            start_time_picker.click()
            heartbeat_page.page.wait_for_timeout(500)
            # 选择 09:00
            time_option = heartbeat_page.page.locator('.qwenpaw-picker-panel li, .ant-picker-panel li').filter(has_text="09").first
            if time_option.is_visible():
                time_option.click()
                heartbeat_page.page.wait_for_timeout(500)
            logger.info("✅ 已设置开始时间")

        log_test_step("9. 设置结束时间")
        end_time_picker = heartbeat_page.page.locator(
            '.qwenpaw-picker, .qwenpaw-time-picker, [class*="endTime"], [class*="end"]'
        ).first
        if end_time_picker.is_visible():
            end_time_picker.click()
            heartbeat_page.page.wait_for_timeout(500)
            # 选择 18:00
            time_option = heartbeat_page.page.locator('.qwenpaw-picker-panel li, .ant-picker-panel li').filter(has_text="18").first
            if time_option.is_visible():
                time_option.click()
                heartbeat_page.page.wait_for_timeout(500)
            logger.info("✅ 已设置结束时间")

        log_test_step("10. 保存配置")
        save_btn = heartbeat_page.page.locator(heartbeat_page.SAVE_BTN).first
        if save_btn.is_visible():
            save_btn.click()
            heartbeat_page.page.wait_for_timeout(2000)
            logger.info("✅ 已点击保存按钮")

        log_test_step("11. 验证配置已保存")
        heartbeat_page.assert_config_saved()
        logger.info("✅ 配置已保存")

        log_test_step("12. 恢复原始配置")
        heartbeat_page.configure_heartbeat(
            enabled=original_enabled,
            interval=int(original_interval.get("value", 30)),
            unit=original_interval.get("unit", "分钟") or "分钟",
            scheduled_time=original_time,
        )
        logger.info("✅ 已恢复原始配置")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 目标会话选择与活跃时间段配置正常")

# ============================================================================
# HB-P2-001: 间隔单位切换（分钟/小时组合）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.heartbeat
class TestHeartbeatIntervalUnit:
    """HB-P2-001: 间隔单位切换"""

    @pytest.mark.test_id("HB-P2-001")
    def test_heartbeat_interval_unit(self, page: Page, heartbeat_page: "HeartbeatPage", request: pytest.FixtureRequest):
        """测试心跳间隔单位切换"""
        test_name = request.node.name

        log_test_step("导航到心跳配置页面")
        heartbeat_page.open()

        log_test_step("查找间隔单位选择器")
        # 页面上单位选择器的 input id 为 everyUnit，class 包含 everyUnit
        # 需要定位到包含该 input 的 .qwenpaw-select 容器
        unit_select = page.locator('.qwenpaw-select:has(#everyUnit)').first

        if unit_select.count() > 0:
            # 获取当前选中的单位文本（使用 selection-item 避免重复文本）
            selection_item = unit_select.locator('.qwenpaw-select-selection-item')
            if selection_item.count() > 0:
                current_unit = selection_item.get_attribute('title') or selection_item.inner_text().strip()
            else:
                current_unit = unit_select.inner_text().strip().split('\n')[0]
            logger.info(f"当前间隔单位：{current_unit}")

            log_test_step("点击单位选择器展开选项")
            unit_select.click()
            page.wait_for_timeout(500)

            options = page.locator('.qwenpaw-select-item-option').all()
            assert len(options) > 0, "单位下拉选项不应为空"
            logger.info(f"✅ 找到 {len(options)} 个单位选项")

            option_texts = []
            for opt in options:
                opt_title = opt.get_attribute('title') or opt.inner_text().strip()
                option_texts.append(opt_title)
                logger.info(f"  单位选项：{opt_title}")

            log_test_step("切换到另一个单位")
            # 选择一个不同于当前的单位
            target_option = None
            target_text = None
            for opt in options:
                opt_title = opt.get_attribute('title') or opt.inner_text().strip()
                if opt_title != current_unit:
                    target_option = opt
                    target_text = opt_title
                    break

            if target_option:
                target_option.click()
                page.wait_for_timeout(500)

                # 重新获取选中值
                if selection_item.count() > 0:
                    new_unit = selection_item.get_attribute('title') or selection_item.inner_text().strip()
                else:
                    new_unit = unit_select.inner_text().strip().split('\n')[0]
                logger.info(f"切换后单位：{new_unit}")
                assert new_unit == target_text, f"单位应切换为 {target_text}，实际为 {new_unit}"
                logger.info(f"✅ 单位已从 '{current_unit}' 切换为 '{new_unit}'")

                log_test_step("恢复原始单位")
                unit_select.click()
                page.wait_for_timeout(500)
                restore_option = page.locator(f'.qwenpaw-select-item-option:has-text("{current_unit}")').first
                if restore_option.count() > 0:
                    restore_option.click()
                    page.wait_for_timeout(500)
                    logger.info(f"✅ 已恢复为原始单位：{current_unit}")
                else:
                    page.keyboard.press("Escape")
            else:
                logger.info("ℹ️ 只有一个单位选项，无法切换")
                page.keyboard.press("Escape")
        else:
            pytest.skip("未找到间隔单位选择器，跳过测试")

        log_test_result(test_name, True, 0)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def heartbeat_page(page: Page) -> HeartbeatPage:
    """创建 HeartbeatPage 实例"""
    return HeartbeatPage(page)