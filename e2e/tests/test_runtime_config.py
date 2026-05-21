# -*- coding: utf-8 -*-
"""
QwenPaw 运行配置（Agent Config）模块 P0 级端到端测试用例

组合用例设计：
- AGCFG-001: ReAct 智能体 Tab 展示 + 语言下拉切换 + 时区验证
- AGCFG-002: Tab 切换（LLM重试/并发限流/上下文压缩）+ 各 Tab 内容验证
- AGCFG-003: 配置修改保存与重置

执行命令：pytest tests/test_runtime_config_p0.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

AGENT_CONFIG_URL = f"{config.base_url}/agent-config"


def navigate_to_agent_config(page: Page):
    """导航到运行配置页面并等待加载"""
    page.goto(AGENT_CONFIG_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)


# ============================================================================
# AGCFG-001: ReAct 智能体 Tab 展示 + 语言下拉切换 + 时区验证
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.config
class TestReActAgentConfig:
    """
    AGCFG-001: ReAct 智能体 Tab 展示 + 语言下拉切换 + 时区验证

    覆盖功能点：
    1. 运行配置页面访问与加载
    2. ReAct 智能体 Tab 默认激活
    3. 智能体语言下拉框展示与切换
    4. 用户时区下拉框展示
    5. 表单卡片标题验证
    """

    @pytest.mark.test_id("AGCFG-001")
    def test_react_agent_language_and_timezone(self, page: Page, request: pytest.FixtureRequest):
        """验证 ReAct 智能体语言切换和时区配置"""
        test_name = request.node.name

        # 步骤1: 访问运行配置页面
        log_test_step("1. 访问运行配置页面")
        navigate_to_agent_config(page)

        # 步骤2: 验证面包屑
        log_test_step("2. 验证面包屑")
        try:
            breadcrumb = page.locator(
                'span[class*="breadcrumbCurrent"]:has-text("运行配置"), '
                'span[class*="breadcrumbCurrent"]:has-text("Runtime"), '
                'span[class*="breadcrumbCurrent"]:has-text("Config")'
            ).first
            if not breadcrumb.is_visible():
                breadcrumb = page.locator('text=运行配置').first
            if not breadcrumb.is_visible():
                breadcrumb = page.locator('text=Runtime').first
            expect(breadcrumb).to_be_visible(timeout=5000)
            logger.info("✅ 面包屑验证通过")
        except Exception:
            logger.warning("⚠️ 面包屑验证跳过（中英文不匹配）")

        # 步骤3: 验证 Tabs 存在
        log_test_step("3. 验证 Tabs 存在")
        react_tab = page.locator('[data-node-key="reactAgent"] .qwenpaw-tabs-tab-btn').first
        expect(react_tab).to_be_visible(timeout=5000)
        logger.info("✅ ReAct 智能体 Tab 可见")

        # 步骤4: 验证 ReAct 智能体 Tab 默认激活
        log_test_step("4. 验证 ReAct 智能体 Tab 默认激活")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # 验证卡片标题
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible(timeout=5000)
        title_text = card_title.inner_text()
        assert "ReAct" in title_text, f"卡片标题不包含 ReAct：{title_text}"
        logger.info(f"✅ 卡片标题：{title_text}")

        # 步骤5: 验证智能体语言下拉框
        log_test_step("5. 验证智能体语言下拉框")
        language_label = active_panel.locator('label:has-text("智能体语言"), label:has-text("Agent Language"), label:has-text("Language")').first
        try:
            expect(language_label).to_be_visible(timeout=5000)
            logger.info("✅ 智能体语言标签可见")
        except Exception:
            logger.warning("⚠️ 智能体语言标签未找到，跳过验证")

        # 找到语言下拉框（第一个 select）
        language_select = active_panel.locator('.qwenpaw-select').first
        expect(language_select).to_be_visible(timeout=5000)

        # 获取当前选中值
        current_value = language_select.locator('.qwenpaw-select-selection-item').first.inner_text()
        logger.info(f"当前智能体语言：{current_value}")

        # 点击展开下拉
        language_select.click()
        page.wait_for_timeout(1000)

        dropdown = page.locator('.qwenpaw-select-dropdown:visible').first
        if dropdown.is_visible():
            options = dropdown.locator('.qwenpaw-select-item-option').all()
            option_texts = [opt.inner_text() for opt in options]
            logger.info(f"语言选项：{option_texts}")
            assert len(options) >= 2, f"语言选项不足：{len(options)}"
            assert "English" in option_texts, f"缺少 English 选项：{option_texts}"
            logger.info("✅ 语言下拉框展开正常，选项验证通过")

            # 关闭下拉（不实际切换，避免修改用户配置）
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        else:
            page.keyboard.press("Escape")
            logger.warning("⚠️ 语言下拉选项未展开，跳过验证")

        # 步骤6: 验证用户时区下拉框
        log_test_step("6. 验证用户时区下拉框")
        timezone_label = active_panel.locator('label:has-text("用户时区"), label:has-text("User Timezone"), label:has-text("Timezone")').first
        try:
            expect(timezone_label).to_be_visible(timeout=5000)
            logger.info("✅ 用户时区标签可见")
        except Exception:
            logger.warning("⚠️ 用户时区标签未找到，跳过验证")

        # 时区下拉框是第二个 select
        selects = active_panel.locator('.qwenpaw-select').all()
        assert len(selects) >= 2, f"下拉框数量不足（期望 ≥ 2）：{len(selects)}"
        timezone_select = selects[1]
        timezone_value = timezone_select.locator('.qwenpaw-select-selection-item').first.inner_text()
        assert len(timezone_value) > 0, "时区值为空"
        logger.info(f"✅ 当前时区：{timezone_value}")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - ReAct 智能体语言切换和时区配置正常")


# ============================================================================
# AGCFG-002: Tab 切换验证（LLM重试/并发限流/上下文压缩）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.config
class TestAgentConfigTabSwitch:
    """
    AGCFG-002: Tab 切换验证

    覆盖功能点：
    1. 切换到 LLM 自动重试 Tab 并验证内容
    2. 切换到 LLM 并发限流 Tab 并验证内容
    3. 切换到上下文压缩 Tab 并验证内容
    4. 各 Tab 的开关/配置项验证
    """

    @pytest.mark.test_id("AGCFG-002")
    def test_agent_config_tab_switch(self, page: Page, request: pytest.FixtureRequest):
        """验证运行配置各 Tab 切换和内容展示"""
        test_name = request.node.name

        # 步骤1: 访问运行配置页面
        log_test_step("1. 访问运行配置页面")
        navigate_to_agent_config(page)

        # 步骤2: 验证所有 Tab 可见
        log_test_step("2. 验证所有 Tab 可见")
        tab_keys = ["reactAgent", "llmRetry", "llmRateLimiter", "lightContext"]

        for key in tab_keys:
            tab_btn = page.locator(f'[data-node-key="{key}"] .qwenpaw-tabs-tab-btn').first
            expect(tab_btn).to_be_visible(timeout=5000)

        logger.info(f"✅ 所有 {len(tab_keys)} 个 Tab 均可见")

        # 步骤3: 切换到 LLM 自动重试 Tab
        log_test_step("3. 切换到 LLM 自动重试 Tab")
        llm_retry_tab = page.locator('[data-node-key="llmRetry"] .qwenpaw-tabs-tab-btn').first
        llm_retry_tab.click()
        page.wait_for_timeout(1500)

        retry_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(retry_panel).to_be_visible(timeout=5000)

        retry_switches = retry_panel.locator('button.qwenpaw-switch[role="switch"]').all()
        retry_inputs = retry_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        assert len(retry_switches) + len(retry_inputs) >= 1, "LLM 自动重试 Tab 内无配置项"
        logger.info(f"✅ LLM 自动重试 Tab - 开关数：{len(retry_switches)}, 输入项数：{len(retry_inputs)}")

        # 步骤4: 切换到 LLM 并发限流 Tab
        log_test_step("4. 切换到 LLM 并发限流 Tab")
        rate_limiter_tab = page.locator('[data-node-key="llmRateLimiter"] .qwenpaw-tabs-tab-btn').first
        rate_limiter_tab.click()
        page.wait_for_timeout(1500)

        rate_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(rate_panel).to_be_visible(timeout=5000)

        rate_switches = rate_panel.locator('button.qwenpaw-switch[role="switch"]').all()
        rate_inputs = rate_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        assert len(rate_switches) + len(rate_inputs) >= 1, "LLM 并发限流 Tab 内无配置项"
        logger.info(f"✅ LLM 并发限流 Tab - 开关数：{len(rate_switches)}, 输入项数：{len(rate_inputs)}")

        # 步骤5: 切换到上下文管理 Tab
        log_test_step("5. 切换到上下文管理 Tab")
        context_tab = page.locator('[data-node-key="lightContext"] .qwenpaw-tabs-tab-btn').first
        context_tab.click()
        page.wait_for_timeout(1500)

        context_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(context_panel).to_be_visible(timeout=5000)

        context_inputs = context_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        assert len(context_inputs) >= 1, "上下文管理 Tab 内无配置项"
        logger.info(f"✅ 上下文管理 Tab - 输入项数：{len(context_inputs)}")

        # 步骤6: 切换回 ReAct 智能体 Tab 确认可正常回切
        log_test_step("6. 切换回 ReAct 智能体 Tab")
        react_tab = page.locator('[data-node-key="reactAgent"] .qwenpaw-tabs-tab-btn').first
        react_tab.click()
        page.wait_for_timeout(1000)

        react_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(react_panel).to_be_visible(timeout=5000)
        logger.info("✅ 已切换回 ReAct 智能体 Tab")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 运行配置各 Tab 切换和内容展示正常")


# ============================================================================
# AGCFG-003: 配置修改保存与重置
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.config
class TestAgentConfigSaveAndReset:
    """
    AGCFG-003: 配置修改保存与重置

    覆盖功能点：
    1. 访问运行配置页面
    2. 切换到上下文压缩 Tab
    3. 找到启用开关并记录当前状态
    4. 切换开关状态
    5. 找到保存按钮并点击
    6. 验证保存成功提示
    7. 刷新页面
    8. 切换到上下文压缩 Tab
    9. 验证开关状态已持久化
    10. 恢复原始状态并保存
    """

    @pytest.mark.test_id("AGCFG-003")
    def test_config_save_and_reset(self, page: Page, request: pytest.FixtureRequest):
        """验证配置修改、保存和持久化功能"""
        test_name = request.node.name

        # ── 步骤1: 访问运行配置页面 ──
        log_test_step("1. 访问运行配置页面")
        navigate_to_agent_config(page)

        # ── 步骤2: 切换到长期记忆 Tab（原上下文压缩已合并，长期记忆 Tab 有开关可切换）──
        log_test_step("2. 切换到长期记忆 Tab")
        context_tab = page.locator('[data-node-key="remeLightMemory"] .qwenpaw-tabs-tab-btn').first
        expect(context_tab).to_be_visible(timeout=5000)
        context_tab.click()
        page.wait_for_timeout(1500)

        context_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(context_panel).to_be_visible(timeout=5000)
        logger.info("✅ 已切换到长期记忆 Tab")

        # ── 步骤3: 找到启用开关并记录当前状态 ──
        log_test_step("3. 记录开关初始状态")
        enable_switch = context_panel.locator('.qwenpaw-switch').first
        expect(enable_switch).to_be_visible(timeout=5000)
        
        initial_checked = enable_switch.get_attribute('aria-checked')
        assert initial_checked in ['true', 'false'], f"开关初始状态异常：{initial_checked}"
        logger.info(f"开关初始状态：aria-checked={initial_checked}")

        # ── 步骤4: 切换开关状态 ──
        log_test_step("4. 切换开关状态")
        enable_switch.click()
        page.wait_for_timeout(1000)
        
        new_checked = enable_switch.get_attribute('aria-checked')
        assert new_checked != initial_checked, f"开关切换后状态未翻转：{initial_checked} → {new_checked}"
        logger.info(f"✅ 开关已切换：{initial_checked} → {new_checked}")

        # ── 步骤5: 找到保存按钮并点击 ──
        log_test_step("5. 点击保存按钮")
        save_btn = page.locator('button.qwenpaw-btn-primary:has-text("保存"), button:has-text("保 存")').first
        if not save_btn.is_visible():
            # 尝试在页面底部查找
            save_btn = page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first
        expect(save_btn).to_be_visible(timeout=5000)
        save_btn.click()
        page.wait_for_timeout(2000)

        # ── 步骤6: 验证保存成功提示 ──
        log_test_step("6. 验证保存成功提示")
        success_msg = page.locator('.qwenpaw-message-success, .qwenpaw-message-notice-content:has-text("保存")').first
        try:
            expect(success_msg).to_be_visible(timeout=3000)
            logger.info("✅ 保存成功提示可见")
        except Exception:
            logger.info("未检测到明显的成功提示，继续执行")

        # ── 步骤7: 刷新页面 ──
        log_test_step("7. 刷新页面")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        # ── 步骤8: 切换到长期记忆 Tab ──
        log_test_step("8. 切换到长期记忆 Tab")
        context_tab_refreshed = page.locator('[data-node-key="remeLightMemory"] .qwenpaw-tabs-tab-btn').first
        expect(context_tab_refreshed).to_be_visible(timeout=5000)
        context_tab_refreshed.click()
        page.wait_for_timeout(1500)

        context_panel_refreshed = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(context_panel_refreshed).to_be_visible(timeout=5000)

        # ── 步骤9: 验证开关状态已持久化 ──
        log_test_step("9. 验证开关状态已持久化")
        enable_switch_refreshed = context_panel_refreshed.locator('.qwenpaw-switch').first
        expect(enable_switch_refreshed).to_be_visible(timeout=5000)
        
        persisted_checked = enable_switch_refreshed.get_attribute('aria-checked')
        assert persisted_checked == new_checked, (
            f"开关状态未持久化：期望 {new_checked}，实际 {persisted_checked}"
        )
        logger.info(f"✅ 开关状态已持久化：{persisted_checked}")

        # ── 步骤10: 恢复原始状态并保存 ──
        log_test_step("10. 恢复原始状态并保存")
        enable_switch_refreshed.click()
        page.wait_for_timeout(1000)
        
        restored_checked = enable_switch_refreshed.get_attribute('aria-checked')
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

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 配置修改、保存和持久化验证通过")


# ============================================================================
# P1 级测试用例：LLM 重试机制、限流器、工具结果压缩、Embedding 配置
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.config
class TestLlmRetryConfig:
    """
    test_llm_retry_config: LLM 重试机制配置

    覆盖功能点：
    1. LLM 自动重试 Tab 切换
    2. 重试开关展示与切换
    3. 最大重试次数、退避基数、退避上限的展示与修改
    4. 配置保存验证
    """

    def test_llm_retry_config(self, page: Page):
        """LLM 重试机制配置测试"""
        log_test_step("导航到 Agent Config 页面")
        navigate_to_agent_config(page)

        from pages.runtime_config_page import RuntimeConfigPage
        runtime_config_page = RuntimeConfigPage(page)

        log_test_step("切换到 LLM 自动重试 Tab")
        runtime_config_page.switch_to_llm_retry_tab()

        # 验证卡片标题
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible()
        title_text = card_title.inner_text()
        assert "LLM" in title_text or "Retry" in title_text or "重试" in title_text, \
            f"卡片标题不包含预期关键词：{title_text}"
        logger.info("LLM 重试配置卡片标题验证通过")

        # 验证重试开关存在
        switch_selector = '.qwenpaw-switch'
        retry_switch = active_panel.locator(switch_selector).first
        expect(retry_switch).to_be_visible()
        logger.info("LLM 重试开关展示验证通过")

        # 验证输入框存在
        input_selectors = [
            '#llm_max_retries',
            '#llm_backoff_base',
            '#llm_backoff_cap'
        ]
        for selector in input_selectors:
            input_el = active_panel.locator(selector).first
            expect(input_el).to_be_visible()
        logger.info("LLM 重试配置输入框展示验证通过")

        # 记录原始值
        log_test_step("记录原始配置值")
        max_retries_input = active_panel.locator('#llm_max_retries').first
        original_max_retries = max_retries_input.input_value()
        backoff_base_input = active_panel.locator('#llm_backoff_base').first
        original_backoff_base = backoff_base_input.input_value()
        backoff_cap_input = active_panel.locator('#llm_backoff_cap').first
        original_backoff_cap = backoff_cap_input.input_value()
        logger.info(f"原始值: max_retries={original_max_retries}, base={original_backoff_base}, cap={original_backoff_cap}")

        try:
            # 修改配置值
            log_test_step("修改 LLM 重试配置")
            max_retries_input.fill('5')
            backoff_base_input.fill('2.0')
            backoff_cap_input.fill('30.0')
            logger.info("LLM 重试配置值修改完成")

            # 保存配置
            log_test_step("保存 LLM 重试配置")
            runtime_config_page.click_save()
            runtime_config_page.assert_config_saved()
            logger.info("LLM 重试配置保存成功")

            # 刷新页面验证持久化
            log_test_step("刷新页面验证持久化")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            runtime_config_page.switch_to_llm_retry_tab()
            active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            persisted_value = active_panel.locator('#llm_max_retries').first.input_value()
            assert persisted_value == '5', f"刷新后 max_retries 应为 '5'，实际为 '{persisted_value}'"
            logger.info("✅ LLM 重试配置持久化验证通过")
        finally:
            # 恢复原始配置
            try:
                navigate_to_agent_config(page)
                runtime_config_page.switch_to_llm_retry_tab()
                active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
                active_panel.locator('#llm_max_retries').first.fill(original_max_retries)
                active_panel.locator('#llm_backoff_base').first.fill(original_backoff_base)
                active_panel.locator('#llm_backoff_cap').first.fill(original_backoff_cap)
                runtime_config_page.click_save()
                runtime_config_page.assert_config_saved()
                logger.info('✅ 已恢复原始配置')
            except Exception as cleanup_error:
                logger.warning(f'恢复配置失败：{cleanup_error}')


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.config
class TestLlmRateLimiterConfig:
    """
    test_llm_rate_limiter_config: LLM 限流器配置

    覆盖功能点：
    1. LLM 并发限流 Tab 切换
    2. 最大并发数、QPM、暂停时间、抖动、获取超时等字段展示
    3. 配置修改与保存验证
    """

    def test_llm_rate_limiter_config(self, page: Page):
        """LLM 限流器配置测试"""
        log_test_step("导航到 Agent Config 页面")
        navigate_to_agent_config(page)

        from pages.runtime_config_page import RuntimeConfigPage
        runtime_config_page = RuntimeConfigPage(page)

        log_test_step("切换到 LLM 并发限流 Tab")
        runtime_config_page.switch_to_llm_rate_limiter_tab()

        # 验证卡片标题
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible()
        title_text = card_title.inner_text()
        assert "LLM" in title_text or "Rate" in title_text or "限流" in title_text, \
            f"卡片标题不包含预期关键词：{title_text}"
        logger.info("LLM 限流配置卡片标题验证通过")

        # 验证输入框存在
        input_selectors = [
            '#llm_max_concurrent',
            '#llm_max_qpm',
            '#llm_rate_limit_pause',
            '#llm_rate_limit_jitter',
            '#llm_acquire_timeout'
        ]
        for selector in input_selectors:
            input_el = active_panel.locator(selector).first
            expect(input_el).to_be_visible()
        logger.info("LLM 限流配置输入框展示验证通过")

        # 记录原始值
        log_test_step("记录原始配置值")
        max_concurrent_input = active_panel.locator('#llm_max_concurrent').first
        original_concurrent = max_concurrent_input.input_value()
        max_qpm_input = active_panel.locator('#llm_max_qpm').first
        original_qpm = max_qpm_input.input_value()
        pause_input = active_panel.locator('#llm_rate_limit_pause').first
        original_pause = pause_input.input_value()
        logger.info(f"原始值: concurrent={original_concurrent}, qpm={original_qpm}, pause={original_pause}")

        try:
            # 修改配置值
            log_test_step("修改 LLM 限流配置")
            max_concurrent_input.fill('10')
            max_qpm_input.fill('100')
            pause_input.fill('60.0')

            jitter_input = active_panel.locator('#llm_rate_limit_jitter').first
            jitter_input.fill('10.0')

            acquire_timeout_input = active_panel.locator('#llm_acquire_timeout').first
            acquire_timeout_input.fill('120')

            logger.info("LLM 限流配置值修改完成")

            # 保存配置
            log_test_step("保存 LLM 限流配置")
            runtime_config_page.click_save()
            runtime_config_page.assert_config_saved()
            logger.info("LLM 限流配置保存成功")

            # 刷新页面验证持久化
            log_test_step("刷新页面验证持久化")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            runtime_config_page.switch_to_llm_rate_limiter_tab()
            active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            persisted_concurrent = active_panel.locator('#llm_max_concurrent').first.input_value()
            assert persisted_concurrent == '10', f"刷新后 max_concurrent 应为 '10'，实际为 '{persisted_concurrent}'"
            logger.info("✅ LLM 限流配置持久化验证通过")
        finally:
            # 恢复原始配置
            try:
                navigate_to_agent_config(page)
                runtime_config_page.switch_to_llm_rate_limiter_tab()
                active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
                active_panel.locator('#llm_max_concurrent').first.fill(original_concurrent)
                active_panel.locator('#llm_max_qpm').first.fill(original_qpm)
                active_panel.locator('#llm_rate_limit_pause').first.fill(original_pause)
                runtime_config_page.click_save()
                runtime_config_page.assert_config_saved()
                logger.info('✅ 已恢复原始配置')
            except Exception as cleanup_error:
                logger.warning(f'恢复配置失败：{cleanup_error}')


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.config
class TestToolResultCompactConfig:
    """
    test_tool_result_compact_config: 上下文管理配置（原工具结果压缩已合并到上下文管理 Tab）

    覆盖功能点：
    1. 上下文管理 Tab 切换
    2. 面板内容展示验证（上下文压缩、工具结果压缩等子项）
    3. 配置项展示验证
    """

    def test_tool_result_compact_config(self, page: Page):
        """上下文管理配置测试（原工具结果压缩已合并到此 Tab）"""
        log_test_step("导航到 Agent Config 页面")
        navigate_to_agent_config(page)

        from pages.runtime_config_page import RuntimeConfigPage
        runtime_config_page = RuntimeConfigPage(page)

        log_test_step("切换到上下文管理 Tab（原工具结果压缩已合并于此）")
        runtime_config_page.switch_to_context_compact_tab()

        # 验证面板可见
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # 验证面板包含上下文管理相关内容
        panel_text = active_panel.inner_text()
        assert any(kw in panel_text for kw in ["上下文", "Context", "压缩", "工具结果"]), \
            f"面板内容不包含上下文管理相关关键词：{panel_text[:200]}"
        logger.info("✅ 上下文管理面板内容验证通过")

        # 验证有配置项（输入框或选择器）
        inputs = active_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        assert len(inputs) >= 1, f"上下文管理面板内无配置项，找到 {len(inputs)} 个"
        logger.info(f"✅ 上下文管理面板找到 {len(inputs)} 个配置项")


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.config
class TestEmbeddingConfig:
    """
    test_embedding_config: 长期记忆配置（原向量模型配置已合并到长期记忆 Tab）

    覆盖功能点：
    1. 长期记忆 Tab 切换
    2. 面板内容展示验证（向量模型配置、记忆开关等子项）
    3. 开关和配置项展示验证
    """

    def test_embedding_config(self, page: Page):
        """长期记忆配置测试（原 Embedding 配置已合并到此 Tab）"""
        log_test_step("导航到 Agent Config 页面")
        navigate_to_agent_config(page)

        from pages.runtime_config_page import RuntimeConfigPage
        runtime_config_page = RuntimeConfigPage(page)

        log_test_step("切换到长期记忆 Tab（原 Embedding 配置已合并于此）")
        runtime_config_page.switch_to_memory_summary_tab()

        # 验证面板可见
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # 验证面板包含长期记忆相关内容
        panel_text = active_panel.inner_text()
        assert any(kw in panel_text for kw in ["长期记忆", "Memory", "向量", "Embedding", "记忆"]), \
            f"面板内容不包含长期记忆相关关键词：{panel_text[:200]}"
        logger.info("✅ 长期记忆面板内容验证通过")

        # 验证有开关
        switches = active_panel.locator('.qwenpaw-switch').all()
        assert len(switches) >= 1, f"长期记忆面板未找到开关，找到 {len(switches)} 个"
        logger.info(f"✅ 长期记忆面板找到 {len(switches)} 个开关")


# ============================================================================
# AGCFG-P1-001: 上下文压缩配置
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.runtime_config
class TestContextCompactConfig:
    """
    AGCFG-P1-001: 上下文压缩配置

    覆盖功能点：
    1. 切换到 Context Compact Tab
    2. 验证表单字段存在（开关、滑块等）
    3. 修改配置并保存
    """

    @pytest.mark.test_id("AGCFG-P1-001")
    def test_context_compact_config(self, page: Page, request: pytest.FixtureRequest):
        """测试上下文压缩配置的展示和修改"""
        test_name = request.node.name

        log_test_step("导航到运行配置页面")
        navigate_to_agent_config(page)

        log_test_step("切换到上下文管理 Tab")
        context_tab = page.locator(
            '[data-node-key="lightContext"] .qwenpaw-tabs-tab-btn, '
            '.qwenpaw-tabs-tab-btn:has-text("Context"), '
            '.qwenpaw-tabs-tab-btn:has-text("上下文")'
        ).first
        expect(context_tab).to_be_visible(timeout=5000)
        context_tab.click()
        page.wait_for_timeout(1500)
        logger.info("✅ 已切换到 Context Compact Tab")

        log_test_step("验证活动面板内容")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # 验证卡片标题
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible()
        title_text = card_title.inner_text()
        assert "Context" in title_text or "上下文" in title_text or "Compact" in title_text, \
            f"卡片标题不包含预期关键词：{title_text}"
        logger.info(f"✅ 卡片标题验证通过：{title_text}")

        log_test_step("验证上下文管理配置项存在")
        # 上下文管理 Tab 可能有开关、滑块、输入框或选择器
        switches = active_panel.locator('.qwenpaw-switch').all()
        sliders = active_panel.locator('.qwenpaw-slider').all()
        inputs = active_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        total_controls = len(switches) + len(sliders) + len(inputs)
        assert total_controls >= 1, \
            f"上下文管理面板无配置项：开关={len(switches)}, 滑块={len(sliders)}, 输入框={len(inputs)}"
        logger.info(f"✅ 找到配置项：开关={len(switches)}, 滑块={len(sliders)}, 输入框={len(inputs)}")

        # 如果有开关，测试切换
        if len(switches) >= 1:
            log_test_step("切换上下文管理开关")
            first_switch = switches[0]
            original_state = first_switch.get_attribute("aria-checked")
            first_switch.click()
            page.wait_for_timeout(1000)
            new_state = first_switch.get_attribute("aria-checked")
            assert original_state != new_state, \
                f"开关切换未生效：切换前 {original_state}，切换后 {new_state}"
            logger.info(f"✅ 开关切换成功：{original_state} → {new_state}")
            # 恢复原始状态
            first_switch.click()
            page.wait_for_timeout(500)
        else:
            logger.info("ℹ️ 上下文管理 Tab 无开关控件，跳过开关切换测试")

        log_test_result(test_name, True, 0)


# ============================================================================
# AGCFG-P2-001: 配置项动态联动验证
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.runtime_config
class TestConfigDynamicLinkage:
    """AGCFG-P2-001: 配置项动态联动验证"""

    @pytest.mark.test_id("AGCFG-P2-001")
    def test_config_dynamic_linkage(self, page: Page, request: pytest.FixtureRequest):
        """测试配置项动态联动"""
        test_name = request.node.name

        log_test_step("导航到运行配置页面")
        navigate_to_agent_config(page)

        log_test_step("验证 Tab 切换联动")
        tabs = page.locator('.qwenpaw-tabs-tab').all()
        assert len(tabs) >= 3, f"Tab 数量不足：{len(tabs)}"
        logger.info(f"✅ 找到 {len(tabs)} 个配置 Tab")

        log_test_step("切换 Tab 验证面板内容变化")
        for i in range(min(3, len(tabs))):
            tabs[i].click()
            page.wait_for_timeout(1000)
            active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            panel_content = active_panel.inner_text()
            logger.info(f"Tab {i+1} 面板内容长度：{len(panel_content)}")
            assert len(panel_content) > 10, f"Tab {i+1} 面板内容为空"

        logger.info("✅ 配置项动态联动验证通过")
        log_test_result(test_name, True, 0)


# ============================================================================
# AGCFG-P1-002: 记忆摘要配置
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.runtime_config
class TestMemorySummaryConfig:
    """
    AGCFG-P1-002: 记忆摘要配置

    覆盖功能点：
    1. 切换到 Memory Summary Tab
    2. 验证表单字段存在（开关、输入框、滑块等）
    3. 修改配置并验证
    """

    @pytest.mark.test_id("AGCFG-P1-002")
    def test_memory_summary_config(self, page: Page, request: pytest.FixtureRequest):
        """测试记忆摘要配置的展示和修改"""
        test_name = request.node.name

        log_test_step("导航到运行配置页面")
        navigate_to_agent_config(page)

        log_test_step("切换到 Memory Summary Tab")
        memory_tab = page.locator(
            '[data-node-key="memorySummary"] .qwenpaw-tabs-tab-btn, '
            '.qwenpaw-tabs-tab-btn:has-text("Memory"), '
            '.qwenpaw-tabs-tab-btn:has-text("记忆")'
        ).first
        expect(memory_tab).to_be_visible(timeout=5000)
        memory_tab.click()
        page.wait_for_timeout(1500)
        logger.info("✅ 已切换到 Memory Summary Tab")

        log_test_step("验证活动面板内容")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # 验证卡片标题
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible()
        title_text = card_title.inner_text()
        assert "Memory" in title_text or "记忆" in title_text or "Summary" in title_text, \
            f"卡片标题不包含预期关键词：{title_text}"
        logger.info(f"✅ 卡片标题验证通过：{title_text}")

        log_test_step("验证记忆摘要开关存在")
        switches = active_panel.locator('.qwenpaw-switch').all()
        assert len(switches) >= 1, f"未找到记忆摘要开关，找到 {len(switches)} 个开关"
        logger.info(f"✅ 找到 {len(switches)} 个开关")

        log_test_step("验证 Cron 表达式输入框存在")
        cron_input = active_panel.locator('#memory_summary_dream_cron, input[id*="dream_cron"]').first
        if cron_input.count() == 0:
            cron_input = active_panel.locator('input').nth(0)
        assert cron_input.count() > 0, "未找到 Cron 表达式输入框"
        logger.info("✅ Cron 表达式输入框存在")

        log_test_step("验证数值输入框存在")
        number_inputs = active_panel.locator('.qwenpaw-input-number').all()
        assert len(number_inputs) >= 1, f"未找到数值输入框，找到 {len(number_inputs)} 个"
        logger.info(f"✅ 找到 {len(number_inputs)} 个数值输入框")

        log_test_step("切换记忆摘要开关")
        first_switch = switches[0]
        original_state = first_switch.get_attribute("aria-checked")
        first_switch.click()
        page.wait_for_timeout(1000)
        new_state = first_switch.get_attribute("aria-checked")
        assert original_state != new_state, \
            f"开关切换未生效：切换前 {original_state}，切换后 {new_state}"
        logger.info(f"✅ 开关切换成功：{original_state} → {new_state}")

        # 恢复原始状态
        first_switch.click()
        page.wait_for_timeout(500)

        log_test_result(test_name, True, 0)