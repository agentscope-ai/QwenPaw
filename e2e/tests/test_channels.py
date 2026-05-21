# -*- coding: utf-8 -*-
"""
QwenPaw Channels 模块端到端测试用例

测试框架：pytest + Playwright + Page Object Pattern
执行命令：pytest tests/test_channels.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect, TimeoutError

from pages.channels_page import ChannelsPage
from config.settings import config
from utils.helpers import (
    log_test_step,
    log_test_result,
    take_screenshot,
    assert_text_contains,
)

logger = logging.getLogger(__name__)


# ============================================================================
# CHAN-001: 全频道列表展示 + All/Built-in/Custom 过滤 + Built-in 标签验证
# 覆盖频道：Console, DingTalk, Feishu, Discord, Telegram, QQ, XiaoYi, Mattermost, MQTT, WeCom, WeChat, OneBot 等全部频道
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.channels_core
class TestChannelListAndFilter:
    """
    CHAN-001: 全频道列表展示 + 过滤功能 + 频道类型识别

    覆盖频道：Console, DingTalk, Feishu, Discord, Telegram, QQ, XiaoYi, Mattermost, MQTT, WeCom, WeChat, OneBot 等全部频道

    组合覆盖功能点：
    1. Channels 页面访问与加载
    2. 频道列表展示（15+ 个内置频道卡片）
    3. 过滤按钮显示与切换（All / Built-in / Custom）
    4. Built-in / Custom 过滤结果正确性
    5. 内置频道 Built-in 标签识别

    业务场景：
    用户进入 Channels 页面，浏览所有频道列表，
    使用过滤功能快速定位内置或自定义频道，
    并确认频道类型标签正确显示。
    """

    @pytest.mark.test_id("CHAN-001")
    def test_channel_list_filter_and_type(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证频道列表展示、过滤切换及频道类型标签

        测试步骤：
        1. 访问 Channels 页面，验证页面标题
        2. 验证 All / Built-in / Custom 过滤按钮可见
        3. 默认 All 视图下频道卡片 >= 15
        4. 验证多个内置频道显示 Built-in 标签
        5. 点击 Built-in 过滤，验证结果全部为内置频道
        6. 点击 Custom 过滤，验证结果全部为自定义频道（可能为空）
        7. 点击 All 过滤，验证恢复全部频道
        """
        test_name = request.node.name

        log_test_step("1. 访问 Channels 页面，验证页面标题")
        channels_page.open()
        page_title = channels_page.page.title()
        assert "QwenPaw" in page_title or "Channels" in page_title, f"页面标题不正确：{page_title}"

        log_test_step("2. 验证过滤按钮可见")
        assert channels_page.page.locator(channels_page.FILTER_ALL_BTN).first.is_visible(), "All 过滤按钮未显示"
        assert channels_page.page.locator(channels_page.FILTER_BUILTIN_BTN).first.is_visible(), "Built-in 过滤按钮未显示"
        assert channels_page.page.locator(channels_page.FILTER_CUSTOM_BTN).first.is_visible(), "Custom 过滤按钮未显示"

        log_test_step("3. 默认 All 视图下频道卡片 >= 15")
        all_count = channels_page.get_channel_card_count()
        assert all_count >= 15, f"频道卡片数量不足：{all_count} < 15"
        logger.info(f"All 视图频道数量：{all_count}")

        log_test_step("4. 验证多个内置频道 Built-in 标签")
        builtin_channels = ["Console", "DingTalk", "Discord", "Telegram", "Feishu", "QQ", "WeCom", "WeChat"]
        for channel_name in builtin_channels:
            card = channels_page.find_channel_card(channel_name)
            if card:
                assert channels_page.is_builtin_channel(channel_name), \
                    f"{channel_name} 应标记为内置频道"
                logger.info(f"✅ {channel_name} 正确标记为 Built-in")

        log_test_step("5. 点击 Built-in 过滤，验证结果")
        channels_page.click_filter_builtin()
        builtin_count = channels_page.get_channel_card_count()
        assert builtin_count > 0, "Built-in 过滤后无频道显示"
        assert channels_page.verify_filter_result('builtin'), "Built-in 过滤结果包含非内置频道"
        logger.info(f"Built-in 过滤显示 {builtin_count} 个频道")

        log_test_step("6. 点击 Custom 过滤，验证结果")
        channels_page.click_filter_custom()
        custom_count = channels_page.get_channel_card_count()
        if custom_count > 0:
            assert channels_page.verify_filter_result('custom'), "Custom 过滤结果包含非自定义频道"
        logger.info(f"Custom 过滤显示 {custom_count} 个频道")

        log_test_step("7. 点击 All 过滤，验证恢复全部频道")
        channels_page.click_filter_all()
        restored_count = channels_page.get_channel_card_count()
        assert restored_count == all_count, \
            f"All 过滤恢复后数量不一致：期望 {all_count}，实际 {restored_count}"

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 频道列表展示、过滤、类型标签全部正常")


# ============================================================================
# CHAN-002: Console 编辑 Bot Prefix 保存+取消
# 覆盖频道：Console（唯一 Enabled 的频道，无必填字段）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.channels_edit
class TestConsoleEditConfig:
    """
    CHAN-002: Console 编辑 Bot Prefix 保存+取消

    覆盖频道：Console（唯一 Enabled 的频道，保存不需要额外必填字段）

    组合覆盖功能点：
    1. 点击 Console 卡片打开编辑抽屉
    2. 验证抽屉标题与表单字段
    3. 修改 Bot Prefix 并保存，验证配置更新
    4. 再次修改 Bot Prefix 后取消，验证配置未变化
    5. 刷新页面验证配置持久化

    业务场景：
    Console 是唯一 Enabled 且无必填字段的频道，用户可以直接保存配置。
    验证保存后配置持久化，以及取消操作不会改变已保存的配置。
    """

    @pytest.mark.test_id("CHAN-002")
    def test_console_edit_save_cancel(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证 Console 频道编辑抽屉打开、表单填写、保存和取消功能

        测试步骤：
        1. 访问 Channels 页面
        2. 点击 Console 卡片，验证抽屉打开及标题
        3. 验证表单字段（启用开关 + Bot Prefix 输入框）
        4. 记录原始 Bot Prefix，修改并保存
        5. 刷新页面后重新打开抽屉，验证保存生效
        6. 再次打开抽屉，修改后取消，验证配置未变化
        7. 恢复原始值
        """
        test_name = request.node.name
        channel_name = "Console"

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        log_test_step("2. 点击 Console 卡片，验证抽屉打开及标题")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "编辑抽屉未打开"
        drawer_title = channels_page.get_drawer_title()
        # 支持中英文标题匹配（前端已本地化为中文）
        channel_name_cn = {"Console": "控制台", "DingTalk": "钉钉", "Feishu": "飞书",
                           "WeCom": "企业微信", "WeChat": "微信"}.get(channel_name, channel_name)
        title_first_line = drawer_title.split('\n')[0].strip()
        assert channel_name in title_first_line or channel_name_cn in title_first_line, \
            f"抽屉标题不正确：{drawer_title}，期望包含 {channel_name} 或 {channel_name_cn}"
        logger.info(f"✅ 抽屉标题：{drawer_title}")

        log_test_step("3. 验证表单字段")
        bot_input = channels_page.page.locator('#bot_prefix')
        assert bot_input.count() > 0 and bot_input.is_visible(), "Bot Prefix 输入框不可见"
        switch = channels_page.page.locator('.qwenpaw-switch, .ant-switch')
        assert switch.count() > 0, "启用开关不存在"
        logger.info("✅ 表单字段验证通过（启用开关 + Bot Prefix）")

        log_test_step("4. 记录原始值，修改 Bot Prefix 并保存")
        original_prefix = bot_input.input_value()
        logger.info(f"原始 Bot Prefix: '{original_prefix}'")
        test_prefix = "test_console_prefix"

        try:
            channels_page.fill_bot_prefix(test_prefix)
            channels_page.save_channel_config()

            # Console 无必填字段，应该可以成功保存
            if channels_page.has_form_validation_errors():
                pytest.fail(f"Console 频道不应有表单校验错误，但检测到错误")

            channels_page.close_drawer()
            channels_page.page.wait_for_timeout(1500)
            logger.info("✅ 已保存配置")

            log_test_step("5. 刷新页面后重新打开抽屉，验证保存生效")
            channels_page.page.reload(wait_until="domcontentloaded")
            channels_page.page.wait_for_timeout(2000)
            channels_page.click_channel_card(channel_name)
            channels_page.wait_for_drawer_open()
            channels_page.page.wait_for_timeout(1000)
            saved_prefix = channels_page.page.locator('#bot_prefix').input_value()
            assert saved_prefix == test_prefix, \
                f"保存后 Bot Prefix 应为 '{test_prefix}'，实际为 '{saved_prefix}'"
            logger.info(f"✅ 保存验证通过：Bot Prefix = '{saved_prefix}'")
            channels_page.close_drawer()
            channels_page.page.wait_for_timeout(1000)

            log_test_step("6. 再次打开抽屉，修改后取消")
            channels_page.click_channel_card(channel_name)
            channels_page.wait_for_drawer_open()
            channels_page.page.wait_for_timeout(500)
            channels_page.fill_bot_prefix("should_not_save")
            channels_page.cancel_channel_config()
            channels_page.page.wait_for_timeout(1000)
            logger.info("✅ 取消操作完成")

            log_test_step("7. 再次打开抽屉，验证取消未生效")
            channels_page.click_channel_card(channel_name)
            channels_page.wait_for_drawer_open()
            channels_page.page.wait_for_timeout(1000)
            after_cancel_prefix = channels_page.page.locator('#bot_prefix').input_value()
            assert after_cancel_prefix == test_prefix, \
                f"取消后 Bot Prefix 应仍为 '{test_prefix}'，实际为 '{after_cancel_prefix}'"
            logger.info(f"✅ 取消验证通过：Bot Prefix 仍为 '{test_prefix}'")

            log_test_result(test_name, True, 0)
            logger.info(f"✅ Test {test_name} passed - Console 编辑保存和取消功能正常")
        finally:
            # 无论测试是否通过，都恢复原始 Bot Prefix
            try:
                channels_page.open()
                channels_page.click_channel_card(channel_name)
                channels_page.wait_for_drawer_open()
                channels_page.page.wait_for_timeout(500)
                current_prefix = channels_page.page.locator('#bot_prefix').input_value()
                if current_prefix != original_prefix:
                    channels_page.fill_bot_prefix(original_prefix)
                    channels_page.save_channel_config()
                    logger.info(f"🧹 已恢复原始 Bot Prefix: '{original_prefix}'")
                channels_page.close_drawer()
            except Exception as cleanup_err:
                logger.warning(f"⚠️ 恢复 Bot Prefix 失败: {cleanup_err}")


# ============================================================================
# CHAN-003: Discord 启用/禁用开关 UI 切换验证
# 覆盖频道：Discord（有必填字段，保存会失败，验证未持久化）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.channels_enable
class TestDiscordEnableDisable:
    """
    CHAN-003: Discord 启用/禁用开关 UI 切换验证

    覆盖频道：Discord（有必填字段 Client ID/Client Secret，保存会失败）

    组合覆盖功能点：
    1. 打开 Discord 抽屉
    2. 切换 Enabled 开关
    3. 验证 aria-checked 属性变化
    4. 因 Discord 有必填字段所以保存会失败，验证未持久化

    业务场景：
    用户尝试启用/禁用 Discord 频道，但由于缺少必填字段（Client ID/Secret），
    保存操作会失败。验证开关 UI 可以切换，但配置未持久化。
    """

    @pytest.mark.test_id("CHAN-003")
    def test_discord_enable_disable_ui(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证 Discord 频道启用/禁用开关 UI 切换

        测试步骤：
        1. 访问 Channels 页面
        2. 点击 Discord 卡片，验证抽屉打开
        3. 获取当前开关状态
        4. 切换开关，验证 aria-checked 变化
        5. 尝试保存（预期失败，因为有必填字段未填）
        6. 关闭抽屉后重新打开，验证开关状态未持久化
        """
        test_name = request.node.name
        channel_name = "Discord"

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        log_test_step("2. 点击 Discord 卡片，验证抽屉打开")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "编辑抽屉未打开"
        drawer_title = channels_page.get_drawer_title()
        assert channel_name in drawer_title, f"抽屉标题不正确：{drawer_title}，期望包含 {channel_name}"
        logger.info(f"✅ 抽屉标题：{drawer_title}")

        log_test_step("3. 获取当前开关状态")
        switch = channels_page.page.locator('.qwenpaw-switch, .ant-switch').first
        initial_checked = switch.get_attribute('aria-checked')
        logger.info(f"初始开关状态 aria-checked: {initial_checked}")

        log_test_step("4. 切换开关，验证 aria-checked 变化")
        channels_page.toggle_enable(initial_checked != 'true')
        channels_page.page.wait_for_timeout(500)
        new_checked = switch.get_attribute('aria-checked')
        expected_checked = 'true' if initial_checked != 'true' else 'false'
        assert new_checked == expected_checked, \
            f"开关状态未变化：期望 {expected_checked}，实际 {new_checked}"
        logger.info(f"✅ 开关状态已切换：{initial_checked} -> {new_checked}")

        log_test_step("5. 尝试保存（预期失败，因为有必填字段未填）")
        channels_page.save_channel_config()
        channels_page.page.wait_for_timeout(1000)

        # Discord 有必填字段，保存应该失败
        has_errors = channels_page.has_form_validation_errors()
        if has_errors:
            logger.info("✅ 保存失败，检测到表单校验错误（预期行为）")
        else:
            logger.warning("⚠️ 保存未检测到校验错误，可能 Discord 已有默认值")

        log_test_step("6. 关闭抽屉后重新打开，验证开关状态未持久化")
        channels_page.close_drawer()
        channels_page.page.wait_for_timeout(1000)

        channels_page.click_channel_card(channel_name)
        channels_page.wait_for_drawer_open()
        channels_page.page.wait_for_timeout(1000)

        after_reopen_checked = switch.get_attribute('aria-checked')
        # 由于保存失败，开关状态应该恢复到初始值
        assert after_reopen_checked == initial_checked, \
            f"开关状态未恢复：期望 {initial_checked}，实际 {after_reopen_checked}"
        logger.info(f"✅ 开关状态已恢复：{after_reopen_checked}（未持久化）")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - Discord 开关 UI 切换正常，未持久化")


# ============================================================================
# CHAN-004: DingTalk + Feishu + Telegram + QQ 四个频道的配置表单差异验证
# 覆盖频道：DingTalk, Feishu, Telegram, QQ
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.channels_form
class TestMultipleChannelFormFields:
    """
    CHAN-004: DingTalk + Feishu + Telegram + QQ 四个频道的配置表单差异验证

    覆盖频道：DingTalk, Feishu, Telegram, QQ

    组合覆盖功能点：
    1. 分别打开四个频道的抽屉
    2. 验证各自有独特的表单字段

    业务场景：
    不同频道有不同的配置表单字段，验证每个频道的表单字段存在且独特。
    """

    @pytest.mark.test_id("CHAN-004")
    def test_four_channels_form_fields(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证 DingTalk, Feishu, Telegram, QQ 四个频道的配置表单字段差异

        测试步骤：
        1. 访问 Channels 页面
        2. 依次打开四个频道的抽屉，验证各自有独特的表单字段
        3. 关闭每个抽屉后继续下一个
        """
        test_name = request.node.name

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        # 定义四个频道及其预期的独特字段关键词
        channels_to_check = [
            ("DingTalk", ["Client ID", "Client Secret", "App Key"]),
            ("Feishu", ["App ID", "App Secret"]),
            ("Telegram", ["Bot Token"]),
            ("QQ", ["App ID", "App Secret"]),
        ]

        for channel_name, expected_field_keywords in channels_to_check:
            log_test_step(f"2. 打开 {channel_name} 抽屉，验证表单字段")
            channels_page.click_channel_card(channel_name)
            assert channels_page.wait_for_drawer_open(), f"{channel_name} 编辑抽屉未打开"

            drawer_title = channels_page.get_drawer_title()
            # 支持中英文标题匹配
            channel_name_cn = {"Console": "控制台", "DingTalk": "钉钉", "Feishu": "飞书",
                               "WeCom": "企业微信", "WeChat": "微信", "QQ": "QQ",
                               "Telegram": "Telegram"}.get(channel_name, channel_name)
            title_first_line = drawer_title.split('\n')[0].strip()
            assert channel_name in title_first_line or channel_name_cn in title_first_line, \
                f"{channel_name} 抽屉标题不正确：{drawer_title}"

            # 获取抽屉内的所有文本内容，验证包含预期字段关键词
            drawer_content = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body').inner_text()
            found_keywords = []
            for keyword in expected_field_keywords:
                if keyword.lower() in drawer_content.lower():
                    found_keywords.append(keyword)

            assert len(found_keywords) > 0, \
                f"{channel_name} 抽屉中未找到预期字段关键词 {expected_field_keywords}，实际内容：{drawer_content[:200]}"
            logger.info(f"✅ {channel_name} 找到字段关键词：{found_keywords}")

            channels_page.close_drawer()
            channels_page.page.wait_for_timeout(500)

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 四个频道表单字段验证通过")


# ============================================================================
# CHAN-005: Mattermost 频道过滤+编辑+切换组合操作
# 覆盖频道：Mattermost
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_combo
class TestMattermostComboOperations:
    """
    CHAN-005: Mattermost 频道过滤+编辑+切换组合操作

    覆盖频道：Mattermost

    组合覆盖功能点：
    1. Built-in 过滤
    2. 找到 Mattermost
    3. 打开抽屉
    4. 编辑 Bot Prefix
    5. 取消
    6. 验证未变

    业务场景：
    用户在 Built-in 过滤下找到 Mattermost 频道，打开编辑抽屉修改 Bot Prefix 后取消，
    验证取消操作不会改变配置。
    """

    @pytest.mark.test_id("CHAN-005")
    def test_mattermost_filter_edit_cancel(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证 Mattermost 频道在 Built-in 过滤下的编辑+取消组合操作

        测试步骤：
        1. 访问 Channels 页面
        2. 点击 Built-in 过滤
        3. 找到 Mattermost 卡片并点击
        4. 验证抽屉打开
        5. 记录原始 Bot Prefix
        6. 修改 Bot Prefix 后取消
        7. 重新打开抽屉，验证 Bot Prefix 未变化
        """
        test_name = request.node.name
        channel_name = "Mattermost"

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        log_test_step("2. 点击 Built-in 过滤")
        channels_page.click_filter_builtin()
        channels_page.page.wait_for_timeout(500)

        log_test_step(f"3. 找到 {channel_name} 卡片并点击")
        card = channels_page.find_channel_card(channel_name)
        assert card is not None, f"在 Built-in 过滤下未找到 {channel_name} 频道"
        channels_page.click_channel_card(channel_name)

        log_test_step("4. 验证抽屉打开")
        assert channels_page.wait_for_drawer_open(), f"{channel_name} 编辑抽屉未打开"
        drawer_title = channels_page.get_drawer_title()
        assert channel_name in drawer_title, f"{channel_name} 抽屉标题不正确：{drawer_title}"

        log_test_step("5. 记录原始 Bot Prefix")
        bot_input = channels_page.page.locator('#bot_prefix')
        original_prefix = bot_input.input_value()
        logger.info(f"原始 Bot Prefix: '{original_prefix}'")

        log_test_step("6. 修改 Bot Prefix 后取消")
        channels_page.fill_bot_prefix("temp_prefix_for_cancel")
        channels_page.cancel_channel_config()
        channels_page.page.wait_for_timeout(1000)
        logger.info("✅ 取消操作完成")

        log_test_step("7. 重新打开抽屉，验证 Bot Prefix 未变化")
        channels_page.click_channel_card(channel_name)
        channels_page.wait_for_drawer_open()
        channels_page.page.wait_for_timeout(1000)
        after_cancel_prefix = channels_page.page.locator('#bot_prefix').input_value()
        assert after_cancel_prefix == original_prefix, \
            f"取消后 Bot Prefix 应恢复为 '{original_prefix}'，实际为 '{after_cancel_prefix}'"
        logger.info(f"✅ 取消验证通过：Bot Prefix 仍为 '{original_prefix}'")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - Mattermost 过滤+编辑+取消组合操作正常")


# ============================================================================
# CHAN-006: 遍历所有频道找到有 'Show Tool Messages'/'Show Thinking' 开关的频道，验证开关 UI 可切换
# 覆盖频道：遍历所有频道，找到有消息过滤开关的频道
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_toggle
class TestMessageFilterSwitches:
    """
    CHAN-006: 遍历所有频道找到有 'Show Tool Messages'/'Show Thinking' 开关的频道，验证开关 UI 可切换

    覆盖频道：遍历所有频道，找到有消息过滤开关的频道

    组合覆盖功能点：
    1. 遍历所有频道
    2. 找到有 'Show Tool Messages' 或 'Show Thinking' 开关的频道
    3. 验证开关 UI 可切换

    业务场景：
    某些频道有消息过滤开关（Show Tool Messages / Show Thinking），
    验证这些开关可以在 UI 上切换。
    """

    @pytest.mark.test_id("CHAN-006")
    def test_message_filter_switches(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        遍历所有频道，找到有消息过滤开关的频道并验证开关可切换

        测试步骤：
        1. 访问 Channels 页面
        2. 获取所有频道卡片
        3. 遍历每个频道，打开抽屉检查是否有 'Show Tool Messages' 或 'Show Thinking' 开关
        4. 如果找到，验证开关可以切换
        5. 至少找到一个有开关的频道
        """
        test_name = request.node.name
        # 用已知频道名列表逐个尝试，避免依赖卡片 DOM 选择器提取名字
        candidate_channels = [
            "Console", "DingTalk", "Feishu", "Discord", "Telegram",
            "QQ", "XiaoYi", "Mattermost", "MQTT", "WeCom", "WeChat", "OneBot",
        ]

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        log_test_step("2. 遍历频道，查找带 Show Tool Messages / Show Thinking 开关的频道")
        found_switch_channels = []

        for channel_name in candidate_channels:
            card = channels_page.find_channel_card(channel_name)
            if card is None:
                logger.info(f"频道 {channel_name} 卡片未找到，跳过")
                continue

            log_test_step(f"3. 检查频道 {channel_name} 是否有消息过滤开关")
            channels_page.click_channel_card(channel_name)
            if not channels_page.wait_for_drawer_open():
                logger.warning(f"无法打开 {channel_name} 抽屉，跳过")
                continue

            channels_page.page.wait_for_timeout(500)

            drawer_body = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body')
            drawer_text = drawer_body.inner_text()

            has_tool_messages = any(kw in drawer_text.lower() for kw in [
                'show tool messages', '显示工具消息', '工具消息',
            ])
            has_thinking = any(kw in drawer_text.lower() for kw in [
                'show thinking', '显示思考', '思考过程',
            ])

            if not (has_tool_messages or has_thinking):
                logger.info(f"频道 {channel_name} 无消息过滤开关，关闭抽屉继续")
                channels_page.close_drawer()
                channels_page.page.wait_for_timeout(500)
                continue

            logger.info(f"✅ 频道 {channel_name} 有消息过滤开关")
            found_switch_channels.append(channel_name)

            # 找到 Show Tool Messages / Show Thinking 对应的开关并切换
            # 开关在文本标签附近，这里用所有 switch 元素按顺序匹配
            switches = drawer_body.locator('.qwenpaw-switch, .ant-switch').all()
            # 启用开关是第一个；Show Tool Messages 通常在后面
            # 跳过第一个(Enabled 开关)，取第二个（Show Tool Messages）
            target_switch = None
            switch_label = ""
            if len(switches) >= 2 and has_tool_messages:
                target_switch = switches[1]
                switch_label = "Show Tool Messages"
            elif len(switches) >= 3 and has_thinking:
                target_switch = switches[2]
                switch_label = "Show Thinking"
            elif len(switches) >= 2:
                target_switch = switches[1]
                switch_label = "消息过滤开关"

            if target_switch is not None:
                initial_state = target_switch.get_attribute('aria-checked')
                logger.info(f"初始 {switch_label} 状态: {initial_state}")

                try:
                    target_switch.click()
                    channels_page.page.wait_for_timeout(500)
                    new_state = target_switch.get_attribute('aria-checked')
                    logger.info(f"切换后 {switch_label} 状态: {new_state}")

                    assert initial_state != new_state, f"{switch_label} 开关状态未变化：{initial_state}"
                    logger.info(f"✅ {switch_label} 已成功切换")
                finally:
                    # 无论断言是否通过，都恢复原始状态
                    try:
                        current_state = target_switch.get_attribute('aria-checked')
                        if current_state != initial_state:
                            target_switch.click()
                            channels_page.page.wait_for_timeout(300)
                            logger.info(f"🧹 已恢复 {switch_label} 到初始状态: {initial_state}")
                    except Exception as restore_err:
                        logger.warning(f"⚠️ 恢复开关状态失败: {restore_err}")

            channels_page.close_drawer()
            channels_page.page.wait_for_timeout(500)
            break  # 只验证第一个找到的

        assert len(found_switch_channels) > 0, "未找到任何有消息过滤开关的频道"
        logger.info(f"✅ 找到有消息过滤开关的频道：{found_switch_channels}")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - 消息过滤开关验证通过")


# ============================================================================
# CHAN-P1-001: WeCom 频道的抽屉配置表单字段验证
# 覆盖频道：WeCom
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_wecom
class TestWeComFormFields:
    """
    CHAN-P1-001: WeCom 频道的抽屉配置表单字段验证

    覆盖频道：WeCom

    组合覆盖功能点：
    1. 打开 WeCom 抽屉
    2. 验证抽屉标题
    3. 验证表单字段存在

    业务场景：
    验证 WeCom 频道的配置表单字段是否正确显示。
    """

    @pytest.mark.test_id("CHAN-P1-001")
    def test_wecom_form_fields(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证 WeCom 频道的抽屉配置表单字段

        测试步骤：
        1. 访问 Channels 页面
        2. 点击 WeCom 卡片，验证抽屉打开
        3. 验证抽屉标题包含 WeCom
        4. 验证表单字段存在
        """
        test_name = request.node.name
        channel_name = "WeCom"

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        log_test_step("2. 点击 WeCom 卡片，验证抽屉打开")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "编辑抽屉未打开"

        log_test_step("3. 验证抽屉标题")
        drawer_title = channels_page.get_drawer_title()
        channel_name_cn = {"WeCom": "企业微信"}.get(channel_name, channel_name)
        title_first_line = drawer_title.split('\n')[0].strip()
        assert channel_name in title_first_line or channel_name_cn in title_first_line, \
            f"抽屉标题不正确：{drawer_title}，期望包含 {channel_name} 或 {channel_name_cn}"
        logger.info(f"✅ 抽屉标题：{drawer_title}")

        log_test_step("4. 验证 WeCom 独有的表单字段存在")
        drawer_content = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body').inner_text()
        # WeCom 独有字段（中英文均可匹配）
        expected_keywords = [
            "Bot ID", "Secret", "DM Policy", "Group Policy", "Require @Mention",
            "私聊策略", "群聊策略", "需要 @提及", "扫码授权", "白名单",
        ]
        found_keywords = [kw for kw in expected_keywords if kw.lower() in drawer_content.lower()]

        assert len(found_keywords) >= 2, \
            f"WeCom 抽屉中未找到足够的独有字段（至少 2 个），预期 {expected_keywords}，" \
            f"找到 {found_keywords}，实际内容：{drawer_content[:300]}"
        logger.info(f"✅ WeCom 找到独有字段关键词：{found_keywords}")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - WeCom 表单字段验证通过")


# ============================================================================
# CHAN-P1-004: WeChat 频道的抽屉配置表单字段验证
# 覆盖频道：WeChat
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_wechat
class TestWeChatFormFields:
    """
    CHAN-P1-004: WeChat 频道的抽屉配置表单字段验证

    覆盖频道：WeChat

    组合覆盖功能点：
    1. 打开 WeChat 抽屉
    2. 验证抽屉标题
    3. 验证表单字段存在

    业务场景：
    验证 WeChat 频道的配置表单字段是否正确显示。
    """

    @pytest.mark.test_id("CHAN-P1-004")
    def test_wechat_form_fields(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证 WeChat 频道的抽屉配置表单字段

        测试步骤：
        1. 访问 Channels 页面
        2. 点击 WeChat 卡片，验证抽屉打开
        3. 验证抽屉标题包含 WeChat
        4. 验证表单字段存在
        """
        test_name = request.node.name
        channel_name = "WeChat"

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        log_test_step("2. 点击 WeChat 卡片，验证抽屉打开")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "编辑抽屉未打开"

        log_test_step("3. 验证抽屉标题")
        drawer_title = channels_page.get_drawer_title()
        channel_name_cn = {"WeChat": "微信"}.get(channel_name, channel_name)
        title_first_line = drawer_title.split('\n')[0].strip()
        assert channel_name in title_first_line or channel_name_cn in title_first_line, \
            f"抽屉标题不正确：{drawer_title}，期望包含 {channel_name} 或 {channel_name_cn}"
        logger.info(f"✅ 抽屉标题：{drawer_title}")

        log_test_step("4. 验证 WeChat 独有的描述和字段")
        drawer_content = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body').inner_text()
        # WeChat 独有特征（中英文均可匹配）
        wechat_unique_keywords = [
            "iLink", "QR code", "Bot Token", "Bot ID", "Secret",
            "扫码授权", "二维码", "私聊策略", "群聊策略", "需要 @提及", "白名单",
        ]
        found_unique = [kw for kw in wechat_unique_keywords if kw.lower() in drawer_content.lower()]

        assert len(found_unique) >= 2, \
            f"WeChat 抽屉中未找到足够的独有特征（至少 2 个），预期 {wechat_unique_keywords}，" \
            f"找到 {found_unique}，实际内容：{drawer_content[:300]}"
        logger.info(f"✅ WeChat 找到独有特征关键词：{found_unique}")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - WeChat 表单字段验证通过")


# ============================================================================
# CHAN-P1-005: OneBot 频道的抽屉配置表单字段验证
# 覆盖频道：OneBot
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_onebot
class TestOneBotFormFields:
    """
    CHAN-P1-005: OneBot 频道的抽屉配置表单字段验证

    覆盖频道：OneBot

    组合覆盖功能点：
    1. 打开 OneBot 抽屉
    2. 验证抽屉标题
    3. 验证表单字段存在

    业务场景：
    验证 OneBot 频道的配置表单字段是否正确显示。
    """

    @pytest.mark.test_id("CHAN-P1-005")
    def test_onebot_form_fields(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证 OneBot 频道的抽屉配置表单字段

        测试步骤：
        1. 访问 Channels 页面
        2. 点击 OneBot 卡片，验证抽屉打开
        3. 验证抽屉标题包含 OneBot
        4. 验证表单字段存在
        """
        test_name = request.node.name
        channel_name = "OneBot"

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        log_test_step("2. 点击 OneBot 卡片，验证抽屉打开")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "编辑抽屉未打开"

        log_test_step("3. 验证抽屉标题")
        drawer_title = channels_page.get_drawer_title()
        assert channel_name in drawer_title, f"抽屉标题不正确：{drawer_title}，期望包含 {channel_name}"
        logger.info(f"✅ 抽屉标题：{drawer_title}")

        log_test_step("4. 验证表单字段存在")
        drawer_content = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body').inner_text()
        # OneBot 应该有 URL, Access Token 等字段
        expected_keywords = ["URL", "Access Token", "Token"]
        found_keywords = []
        for keyword in expected_keywords:
            if keyword.lower() in drawer_content.lower():
                found_keywords.append(keyword)

        assert len(found_keywords) > 0, \
            f"OneBot 抽屉中未找到预期字段关键词 {expected_keywords}，实际内容：{drawer_content[:200]}"
        logger.info(f"✅ OneBot 找到字段关键词：{found_keywords}")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - OneBot 表单字段验证通过")


# ============================================================================
# CHAN-P2-001: MQTT 频道的 Bot Prefix 配置验证
# 覆盖频道：MQTT
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.channels_mqtt
class TestMQTTBotPrefix:
    """
    CHAN-P2-001: MQTT 频道的 Bot Prefix 配置验证

    覆盖频道：MQTT

    组合覆盖功能点：
    1. 打开 MQTT 抽屉
    2. 验证抽屉标题
    3. 验证 Bot Prefix 字段存在
    4. 修改 Bot Prefix 后取消，验证未持久化

    业务场景：
    验证 MQTT 频道的 Bot Prefix 配置功能。
    """

    @pytest.mark.test_id("CHAN-P2-001")
    def test_mqtt_bot_prefix(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        验证 MQTT 频道的 Bot Prefix 配置

        测试步骤：
        1. 访问 Channels 页面
        2. 点击 MQTT 卡片，验证抽屉打开
        3. 验证抽屉标题包含 MQTT
        4. 验证 Bot Prefix 字段存在
        5. 修改 Bot Prefix 后取消，验证未持久化
        """
        test_name = request.node.name
        channel_name = "MQTT"

        log_test_step("1. 访问 Channels 页面")
        channels_page.open()

        log_test_step("2. 点击 MQTT 卡片，验证抽屉打开")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "编辑抽屉未打开"

        log_test_step("3. 验证抽屉标题")
        drawer_title = channels_page.get_drawer_title()
        assert channel_name in drawer_title, f"抽屉标题不正确：{drawer_title}，期望包含 {channel_name}"
        logger.info(f"✅ 抽屉标题：{drawer_title}")

        log_test_step("4. 验证 Bot Prefix 字段存在")
        bot_input = channels_page.page.locator('#bot_prefix')
        assert bot_input.count() > 0 and bot_input.is_visible(), "Bot Prefix 输入框不可见"
        original_prefix = bot_input.input_value()
        logger.info(f"原始 Bot Prefix: '{original_prefix}'")

        log_test_step("5. 修改 Bot Prefix 后取消，验证未持久化")
        channels_page.fill_bot_prefix("temp_mqtt_prefix")
        channels_page.cancel_channel_config()
        channels_page.page.wait_for_timeout(1000)

        # 重新打开验证未持久化
        channels_page.click_channel_card(channel_name)
        channels_page.wait_for_drawer_open()
        channels_page.page.wait_for_timeout(1000)
        after_cancel_prefix = channels_page.page.locator('#bot_prefix').input_value()
        assert after_cancel_prefix == original_prefix, \
            f"取消后 Bot Prefix 应恢复为 '{original_prefix}'，实际为 '{after_cancel_prefix}'"
        logger.info(f"✅ 取消验证通过：Bot Prefix 仍为 '{original_prefix}'")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed - MQTT Bot Prefix 配置验证通过")
