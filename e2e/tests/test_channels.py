# -*- coding: utf-8 -*-
"""
QwenPaw Channels module end-to-end test cases.

Framework: pytest + Playwright + Page Object Pattern.
Run: pytest tests/test_channels.py -v
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
# CHAN-001: Full channel list display + All/Built-in/Custom filter + Built-in tag verification
# Channels covered: Console, DingTalk, Feishu, Discord, Telegram, QQ, XiaoYi, Mattermost, MQTT, WeCom, WeChat, OneBot, etc.
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.channels_core
class TestChannelListAndFilter:
    """
    CHAN-001: Full channel list display + filter + channel-type recognition.

    Channels covered: Console, DingTalk, Feishu, Discord, Telegram, QQ, XiaoYi, Mattermost, MQTT, WeCom, WeChat, OneBot, etc.

    Combined coverage:
    1. Channels page access and load
    2. Channel list display (15+ built-in channel cards)
    3. Filter button visibility and switching (All / Built-in / Custom)
    4. Correctness of Built-in / Custom filter results
    5. Built-in tag recognition on built-in channels

    Business scenario:
    The user opens the Channels page, browses the channel list, uses the
    filters to quickly locate built-in or custom channels, and confirms
    that the channel-type tag is displayed correctly.
    """

    @pytest.mark.test_id("CHAN-001")
    def test_channel_list_filter_and_type(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify channel list display, filter switching, and channel-type tag.

        Steps:
        1. Open the Channels page and verify the page title
        2. Verify the All / Built-in / Custom filter buttons are visible
        3. Under the default All view there are >= 15 channel cards
        4. Verify several built-in channels show the Built-in tag
        5. Click the Built-in filter and verify results are all built-in channels
        6. Click the Custom filter and verify results are all custom channels (may be empty)
        7. Click the All filter and verify all channels are restored
        """
        test_name = request.node.name

        log_test_step("1. Open the Channels page and verify the page title")
        channels_page.open()
        page_title = channels_page.page.title()
        assert "QwenPaw" in page_title or "Channels" in page_title, f"Unexpected page title: {page_title}"

        log_test_step("2. Verify the filter buttons are visible")
        assert channels_page.page.locator(channels_page.FILTER_ALL_BTN).first.is_visible(), "All filter button not shown"
        assert channels_page.page.locator(channels_page.FILTER_BUILTIN_BTN).first.is_visible(), "Built-in filter button not shown"
        assert channels_page.page.locator(channels_page.FILTER_CUSTOM_BTN).first.is_visible(), "Custom filter button not shown"

        log_test_step("3. Default All view shows >= 15 channel cards")
        all_count = channels_page.get_channel_card_count()
        assert all_count >= 15, f"Not enough channel cards: {all_count} < 15"
        logger.info(f"All view channel count: {all_count}")

        log_test_step("4. Verify Built-in tags on several built-in channels")
        builtin_channels = ["Console", "DingTalk", "Discord", "Telegram", "Feishu", "QQ", "WeCom", "WeChat"]
        for channel_name in builtin_channels:
            card = channels_page.find_channel_card(channel_name)
            if card:
                assert channels_page.is_builtin_channel(channel_name), \
                    f"{channel_name} should be tagged as built-in"
                logger.info(f"{channel_name} correctly tagged as Built-in")

        log_test_step("5. Click the Built-in filter and verify results")
        channels_page.click_filter_builtin()
        builtin_count = channels_page.get_channel_card_count()
        assert builtin_count > 0, "No channels shown after Built-in filter"
        assert channels_page.verify_filter_result('builtin'), "Built-in filter results include non-built-in channels"
        logger.info(f"Built-in filter shows {builtin_count} channel(s)")

        log_test_step("6. Click the Custom filter and verify results")
        channels_page.click_filter_custom()
        custom_count = channels_page.get_channel_card_count()
        if custom_count > 0:
            assert channels_page.verify_filter_result('custom'), "Custom filter results include non-custom channels"
        logger.info(f"Custom filter shows {custom_count} channel(s)")

        log_test_step("7. Click the All filter and verify all channels are restored")
        channels_page.click_filter_all()
        restored_count = channels_page.get_channel_card_count()
        assert restored_count == all_count, \
            f"Count mismatch after All filter restore: expected {all_count}, actual {restored_count}"

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - channel list, filter, and type tags are all correct")


# ============================================================================
# CHAN-002: Console edit Bot Prefix save+cancel
# Channels covered: Console (the only Enabled channel with no required fields)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.channels_edit
class TestConsoleEditConfig:
    """
    CHAN-002: Console edit Bot Prefix save+cancel.

    Channels covered: Console (the only Enabled channel; save requires no extra required fields).

    Combined coverage:
    1. Click the Console card to open the edit drawer
    2. Verify the drawer title and form fields
    3. Modify Bot Prefix and save, verify the config is updated
    4. Modify Bot Prefix again then cancel, verify the config is unchanged
    5. Refresh the page to verify config persistence

    Business scenario:
    Console is the only Enabled channel with no required fields, so the
    user can save the config directly. Verify that saved config persists
    and that a cancel operation does not modify the saved config.
    """

    @pytest.mark.test_id("CHAN-002")
    def test_console_edit_save_cancel(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify Console channel edit drawer opening, form filling, save and cancel.

        Steps:
        1. Open the Channels page
        2. Click the Console card and verify the drawer opens and title
        3. Verify form fields (Enable switch + Bot Prefix input)
        4. Record the original Bot Prefix, modify and save
        5. Reload the page and reopen the drawer, verify the save took effect
        6. Reopen the drawer, modify and cancel, verify config is unchanged
        7. Restore the original value
        """
        test_name = request.node.name
        channel_name = "Console"

        log_test_step("1. Open the Channels page")
        channels_page.open()

        log_test_step("2. Click the Console card and verify the drawer opens and title")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "Edit drawer did not open"
        drawer_title = channels_page.get_drawer_title()
        # Support CN/EN title matching (frontend has been localized to CN)
        channel_name_cn = {"Console": "控制台", "DingTalk": "钉钉", "Feishu": "飞书",
                           "WeCom": "企业微信", "WeChat": "微信"}.get(channel_name, channel_name)
        title_first_line = drawer_title.split('\n')[0].strip()
        assert channel_name in title_first_line or channel_name_cn in title_first_line, \
            f"Unexpected drawer title: {drawer_title}, expected to contain {channel_name} or {channel_name_cn}"
        logger.info(f"Drawer title: {drawer_title}")

        log_test_step("3. Verify form fields")
        bot_input = channels_page.page.locator('#bot_prefix')
        assert bot_input.count() > 0 and bot_input.is_visible(), "Bot Prefix input not visible"
        switch = channels_page.page.locator('.qwenpaw-switch, .ant-switch')
        assert switch.count() > 0, "Enable switch does not exist"
        logger.info("Form fields verified (Enable switch + Bot Prefix)")

        log_test_step("4. Record the original value, modify Bot Prefix and save")
        original_prefix = bot_input.input_value()
        logger.info(f"Original Bot Prefix: '{original_prefix}'")
        test_prefix = "test_console_prefix"

        try:
            channels_page.fill_bot_prefix(test_prefix)
            channels_page.save_channel_config()

            # Console has no required fields, so save should succeed
            if channels_page.has_form_validation_errors():
                pytest.fail(f"Console channel should have no form validation errors, but errors were detected")

            channels_page.page.wait_for_timeout(2000)
            drawer_still_open = channels_page.page.locator('.qwenpaw-drawer-open, .ant-drawer-open').first
            if drawer_still_open.count() > 0 and drawer_still_open.is_visible(timeout=1000):
                channels_page.close_drawer()
                channels_page.page.wait_for_timeout(1000)
            try:
                channels_page.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            logger.info("Config saved")

            log_test_step("5. Reload the page and reopen the drawer, verify the save took effect")
            channels_page.page.reload(wait_until="domcontentloaded")
            channels_page.page.wait_for_timeout(3000)
            channels_page.click_channel_card(channel_name)
            channels_page.wait_for_drawer_open()
            channels_page.page.wait_for_timeout(1000)
            saved_prefix = channels_page.page.locator('#bot_prefix').input_value()
            assert saved_prefix == test_prefix, \
                f"After save, Bot Prefix should be '{test_prefix}', actual: '{saved_prefix}'"
            logger.info(f"Save verified: Bot Prefix = '{saved_prefix}'")
            channels_page.close_drawer()
            channels_page.page.wait_for_timeout(1000)

            log_test_step("6. Reopen the drawer, modify and cancel")
            channels_page.click_channel_card(channel_name)
            channels_page.wait_for_drawer_open()
            channels_page.page.wait_for_timeout(500)
            channels_page.fill_bot_prefix("should_not_save")
            channels_page.cancel_channel_config()
            channels_page.page.wait_for_timeout(1000)
            logger.info("Cancel completed")

            log_test_step("7. Reopen the drawer and verify cancel did not take effect")
            channels_page.click_channel_card(channel_name)
            channels_page.wait_for_drawer_open()
            channels_page.page.wait_for_timeout(1000)
            after_cancel_prefix = channels_page.page.locator('#bot_prefix').input_value()
            assert after_cancel_prefix == test_prefix, \
                f"After cancel, Bot Prefix should still be '{test_prefix}', actual: '{after_cancel_prefix}'"
            logger.info(f"Cancel verified: Bot Prefix still '{test_prefix}'")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - Console edit save and cancel work correctly")
        finally:
            # Whether the test passes or not, restore the original Bot Prefix
            try:
                channels_page.open()
                channels_page.click_channel_card(channel_name)
                channels_page.wait_for_drawer_open()
                channels_page.page.wait_for_timeout(500)
                current_prefix = channels_page.page.locator('#bot_prefix').input_value()
                if current_prefix != original_prefix:
                    channels_page.fill_bot_prefix(original_prefix)
                    channels_page.save_channel_config()
                    logger.info(f"Restored original Bot Prefix: '{original_prefix}'")
                channels_page.close_drawer()
            except Exception as cleanup_err:
                logger.warning(f"Failed to restore Bot Prefix: {cleanup_err}")


# ============================================================================
# CHAN-003: Discord enable/disable switch UI toggle verification
# Channels covered: Discord (has required fields; save will fail, verifying non-persistence)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.channels_enable
class TestDiscordEnableDisable:
    """
    CHAN-003: Discord enable/disable switch UI toggle verification.

    Channels covered: Discord (required fields Client ID/Client Secret; save will fail).

    Combined coverage:
    1. Open the Discord drawer
    2. Toggle the Enabled switch
    3. Verify aria-checked attribute change
    4. Since Discord has required fields the save will fail; verify non-persistence

    Business scenario:
    The user tries to enable/disable the Discord channel, but missing
    required fields (Client ID/Secret) cause save to fail. Verify that
    the switch UI toggles but the config is not persisted.
    """

    @pytest.mark.test_id("CHAN-003")
    def test_discord_enable_disable_ui(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify Discord channel enable/disable switch UI toggling.

        Steps:
        1. Open the Channels page
        2. Click the Discord card and verify the drawer opens
        3. Read the current switch state
        4. Toggle the switch and verify aria-checked change
        5. Try to save (expected to fail because required fields are empty)
        6. Close the drawer, reopen it, and verify the switch state was not persisted
        """
        test_name = request.node.name
        channel_name = "Discord"

        log_test_step("1. Open the Channels page")
        channels_page.open()

        log_test_step("2. Click the Discord card and verify the drawer opens")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "Edit drawer did not open"
        drawer_title = channels_page.get_drawer_title()
        assert channel_name in drawer_title, f"Unexpected drawer title: {drawer_title}, expected to contain {channel_name}"
        logger.info(f"Drawer title: {drawer_title}")

        log_test_step("3. Read the current switch state")
        switch = channels_page.page.locator('.qwenpaw-switch, .ant-switch').first
        initial_checked = switch.get_attribute('aria-checked')
        logger.info(f"Initial switch aria-checked: {initial_checked}")

        log_test_step("4. Toggle the switch and verify aria-checked change")
        channels_page.toggle_enable(initial_checked != 'true')
        channels_page.page.wait_for_timeout(500)
        new_checked = switch.get_attribute('aria-checked')
        expected_checked = 'true' if initial_checked != 'true' else 'false'
        assert new_checked == expected_checked, \
            f"Switch state did not change: expected {expected_checked}, actual {new_checked}"
        logger.info(f"Switch toggled: {initial_checked} -> {new_checked}")

        log_test_step("5. Try to save (expected to fail because required fields are empty)")
        channels_page.save_channel_config()
        channels_page.page.wait_for_timeout(1000)

        # Discord has required fields, so save should fail
        has_errors = channels_page.has_form_validation_errors()
        if has_errors:
            logger.info("Save failed; form validation errors detected (expected)")
        else:
            logger.warning("Save did not produce validation errors; Discord may already have defaults")

        log_test_step("6. Close the drawer, reopen it, and verify the switch state was not persisted")
        channels_page.close_drawer()
        channels_page.page.wait_for_timeout(1000)

        channels_page.click_channel_card(channel_name)
        channels_page.wait_for_drawer_open()
        channels_page.page.wait_for_timeout(1000)

        after_reopen_checked = switch.get_attribute('aria-checked')
        # Since save failed, the switch state should revert to the initial value
        assert after_reopen_checked == initial_checked, \
            f"Switch state did not revert: expected {initial_checked}, actual {after_reopen_checked}"
        logger.info(f"Switch state reverted: {after_reopen_checked} (not persisted)")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - Discord switch UI toggle works, not persisted")


# ============================================================================
# CHAN-004: DingTalk + Feishu + Telegram + QQ four-channel config form differentiation
# Channels covered: DingTalk, Feishu, Telegram, QQ
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.channels_form
class TestMultipleChannelFormFields:
    """
    CHAN-004: DingTalk + Feishu + Telegram + QQ four-channel config form differentiation.

    Channels covered: DingTalk, Feishu, Telegram, QQ.

    Combined coverage:
    1. Open each of the four channel drawers
    2. Verify each has its own distinctive form fields

    Business scenario:
    Different channels have different config form fields. Verify each
    channel's form fields exist and are distinctive.
    """

    @pytest.mark.test_id("CHAN-004")
    def test_four_channels_form_fields(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify the config form-field differences across DingTalk, Feishu, Telegram, QQ.

        Steps:
        1. Open the Channels page
        2. Open the four channel drawers in turn and verify each has its own distinctive form fields
        3. Close each drawer before moving on to the next
        """
        test_name = request.node.name

        log_test_step("1. Open the Channels page")
        channels_page.open()

        # Define the four channels and their expected distinctive field keywords
        channels_to_check = [
            ("DingTalk", ["Client ID", "Client Secret", "App Key"]),
            ("Feishu", ["App ID", "App Secret"]),
            ("Telegram", ["Bot Token"]),
            ("QQ", ["App ID", "App Secret"]),
        ]

        for channel_name, expected_field_keywords in channels_to_check:
            log_test_step(f"2. Open the {channel_name} drawer and verify form fields")
            channels_page.click_channel_card(channel_name)
            assert channels_page.wait_for_drawer_open(), f"{channel_name} edit drawer did not open"

            drawer_title = channels_page.get_drawer_title()
            # Support CN/EN title matching
            channel_name_cn = {"Console": "控制台", "DingTalk": "钉钉", "Feishu": "飞书",
                               "WeCom": "企业微信", "WeChat": "微信", "QQ": "QQ",
                               "Telegram": "Telegram"}.get(channel_name, channel_name)
            title_first_line = drawer_title.split('\n')[0].strip()
            assert channel_name in title_first_line or channel_name_cn in title_first_line, \
                f"{channel_name} unexpected drawer title: {drawer_title}"

            # Read all text inside the drawer and verify the expected field keywords are present
            drawer_content = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body').inner_text()
            found_keywords = []
            for keyword in expected_field_keywords:
                if keyword.lower() in drawer_content.lower():
                    found_keywords.append(keyword)

            assert len(found_keywords) > 0, \
                f"{channel_name} drawer did not contain the expected field keywords {expected_field_keywords}, actual content: {drawer_content[:200]}"
            logger.info(f"{channel_name} found field keywords: {found_keywords}")

            channels_page.close_drawer()
            channels_page.page.wait_for_timeout(500)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - four-channel form-field verification OK")


# ============================================================================
# CHAN-005: Mattermost channel filter+edit+toggle combination
# Channels covered: Mattermost
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_combo
class TestMattermostComboOperations:
    """
    CHAN-005: Mattermost channel filter+edit+toggle combination.

    Channels covered: Mattermost.

    Combined coverage:
    1. Built-in filter
    2. Find Mattermost
    3. Open the drawer
    4. Edit Bot Prefix
    5. Cancel
    6. Verify unchanged

    Business scenario:
    Under the Built-in filter the user finds the Mattermost channel,
    opens the edit drawer, modifies Bot Prefix and cancels, and verifies
    that the cancel did not modify the config.
    """

    @pytest.mark.test_id("CHAN-005")
    def test_mattermost_filter_edit_cancel(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify the Mattermost edit+cancel combination under the Built-in filter.

        Steps:
        1. Open the Channels page
        2. Click the Built-in filter
        3. Find the Mattermost card and click it
        4. Verify the drawer opens
        5. Record the original Bot Prefix
        6. Modify Bot Prefix and cancel
        7. Reopen the drawer and verify Bot Prefix is unchanged
        """
        test_name = request.node.name
        channel_name = "Mattermost"

        log_test_step("1. Open the Channels page")
        channels_page.open()

        log_test_step("2. Click the Built-in filter")
        channels_page.click_filter_builtin()
        channels_page.page.wait_for_timeout(500)

        log_test_step(f"3. Find the {channel_name} card and click it")
        card = channels_page.find_channel_card(channel_name)
        assert card is not None, f"{channel_name} channel not found under the Built-in filter"
        channels_page.click_channel_card(channel_name)

        log_test_step("4. Verify the drawer opens")
        assert channels_page.wait_for_drawer_open(), f"{channel_name} edit drawer did not open"
        drawer_title = channels_page.get_drawer_title()
        assert channel_name in drawer_title, f"{channel_name} unexpected drawer title: {drawer_title}"

        log_test_step("5. Record the original Bot Prefix")
        bot_input = channels_page.page.locator('#bot_prefix')
        original_prefix = bot_input.input_value()
        logger.info(f"Original Bot Prefix: '{original_prefix}'")

        log_test_step("6. Modify Bot Prefix and cancel")
        channels_page.fill_bot_prefix("temp_prefix_for_cancel")
        channels_page.cancel_channel_config()
        channels_page.page.wait_for_timeout(1000)
        logger.info("Cancel completed")

        log_test_step("7. Reopen the drawer and verify Bot Prefix is unchanged")
        channels_page.click_channel_card(channel_name)
        channels_page.wait_for_drawer_open()
        channels_page.page.wait_for_timeout(1000)
        after_cancel_prefix = channels_page.page.locator('#bot_prefix').input_value()
        assert after_cancel_prefix == original_prefix, \
            f"After cancel, Bot Prefix should revert to '{original_prefix}', actual: '{after_cancel_prefix}'"
        logger.info(f"Cancel verified: Bot Prefix still '{original_prefix}'")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - Mattermost filter+edit+cancel combination works")


# ============================================================================
# CHAN-006: Iterate all channels to find ones with 'Show Tool Messages'/'Show Thinking' switches and verify the switch UI can be toggled
# Channels covered: iterate all channels, find ones with message-filter switches
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_toggle
class TestMessageFilterSwitches:
    """
    CHAN-006: Iterate all channels to find ones with 'Show Tool Messages'/'Show Thinking' switches and verify the switch UI can be toggled.

    Channels covered: iterate all channels, find ones with message-filter switches.

    Combined coverage:
    1. Iterate all channels
    2. Find channels with 'Show Tool Messages' or 'Show Thinking' switches
    3. Verify the switch UI can be toggled

    Business scenario:
    Some channels have message-filter switches (Show Tool Messages /
    Show Thinking). Verify these switches can be toggled in the UI.
    """

    @pytest.mark.test_id("CHAN-006")
    def test_message_filter_switches(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Iterate all channels, find ones with message-filter switches and verify they can be toggled.

        Steps:
        1. Open the Channels page
        2. Get all channel cards
        3. For each channel, open the drawer and check for 'Show Tool Messages' or 'Show Thinking' switches
        4. If found, verify the switch can be toggled
        5. At least one channel with such a switch must be found
        """
        test_name = request.node.name
        # Iterate through a known list of channel names rather than relying on a card-DOM selector to extract names
        candidate_channels = [
            "Console", "DingTalk", "Feishu", "Discord", "Telegram",
            "QQ", "XiaoYi", "Mattermost", "MQTT", "WeCom", "WeChat", "OneBot",
        ]

        log_test_step("1. Open the Channels page")
        channels_page.open()

        log_test_step("2. Iterate channels, looking for ones with Show Tool Messages / Show Thinking switches")
        found_switch_channels = []

        for channel_name in candidate_channels:
            card = channels_page.find_channel_card(channel_name)
            if card is None:
                logger.info(f"Channel {channel_name} card not found, skipping")
                continue

            log_test_step(f"3. Check whether channel {channel_name} has a message-filter switch")
            channels_page.click_channel_card(channel_name)
            if not channels_page.wait_for_drawer_open():
                logger.warning(f"Could not open {channel_name} drawer, skipping")
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
                logger.info(f"Channel {channel_name} has no message-filter switch, closing drawer and continuing")
                channels_page.close_drawer()
                channels_page.page.wait_for_timeout(500)
                continue

            logger.info(f"Channel {channel_name} has a message-filter switch")
            found_switch_channels.append(channel_name)

            # Find the switch corresponding to Show Tool Messages / Show Thinking and toggle it.
            # The switch is near its text label; here we match by position among all switch elements.
            switches = drawer_body.locator('.qwenpaw-switch, .ant-switch').all()
            # The Enable switch is the first one; Show Tool Messages usually comes after.
            # Skip the first (Enabled switch) and take the second (Show Tool Messages).
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
                switch_label = "message filter switch"

            if target_switch is not None:
                initial_state = target_switch.get_attribute('aria-checked')
                logger.info(f"Initial {switch_label} state: {initial_state}")

                try:
                    target_switch.click()
                    channels_page.page.wait_for_timeout(500)
                    new_state = target_switch.get_attribute('aria-checked')
                    logger.info(f"After toggle {switch_label} state: {new_state}")

                    assert initial_state != new_state, f"{switch_label} switch state did not change: {initial_state}"
                    logger.info(f"{switch_label} toggled successfully")
                finally:
                    # Whether the assertion passed or not, restore the original state
                    try:
                        current_state = target_switch.get_attribute('aria-checked')
                        if current_state != initial_state:
                            target_switch.click()
                            channels_page.page.wait_for_timeout(300)
                            logger.info(f"Restored {switch_label} to initial state: {initial_state}")
                    except Exception as restore_err:
                        logger.warning(f"Failed to restore switch state: {restore_err}")

            channels_page.close_drawer()
            channels_page.page.wait_for_timeout(500)
            break  # Only validate the first one found

        assert len(found_switch_channels) > 0, "No channel with a message-filter switch was found"
        logger.info(f"Channels with message-filter switches: {found_switch_channels}")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - message-filter switches verified")


# ============================================================================
# CHAN-P1-001: WeCom channel drawer config form fields verification
# Channels covered: WeCom
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_wecom
class TestWeComFormFields:
    """
    CHAN-P1-001: WeCom channel drawer config form fields verification.

    Channels covered: WeCom.

    Combined coverage:
    1. Open the WeCom drawer
    2. Verify the drawer title
    3. Verify the form fields exist

    Business scenario:
    Verify that the WeCom channel's config form fields are displayed correctly.
    """

    @pytest.mark.test_id("CHAN-P1-001")
    def test_wecom_form_fields(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify the WeCom channel's drawer config form fields.

        Steps:
        1. Open the Channels page
        2. Click the WeCom card and verify the drawer opens
        3. Verify the drawer title contains WeCom
        4. Verify the form fields exist
        """
        test_name = request.node.name
        channel_name = "WeCom"

        log_test_step("1. Open the Channels page")
        channels_page.open()

        log_test_step("2. Click the WeCom card and verify the drawer opens")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "Edit drawer did not open"

        log_test_step("3. Verify the drawer title")
        drawer_title = channels_page.get_drawer_title()
        channel_name_cn = {"WeCom": "企业微信"}.get(channel_name, channel_name)
        title_first_line = drawer_title.split('\n')[0].strip()
        assert channel_name in title_first_line or channel_name_cn in title_first_line, \
            f"Unexpected drawer title: {drawer_title}, expected to contain {channel_name} or {channel_name_cn}"
        logger.info(f"Drawer title: {drawer_title}")

        log_test_step("4. Verify the unique WeCom form fields exist")
        drawer_content = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body').inner_text()
        # WeCom-unique fields (CN/EN both supported)
        expected_keywords = [
            "Bot ID", "Secret", "DM Policy", "Group Policy", "Require @Mention",
            "私聊策略", "群聊策略", "需要 @提及", "扫码授权", "白名单",
        ]
        found_keywords = [kw for kw in expected_keywords if kw.lower() in drawer_content.lower()]

        assert len(found_keywords) >= 2, \
            f"WeCom drawer did not contain enough unique fields (at least 2 required); expected {expected_keywords}, " \
            f"found {found_keywords}, actual content: {drawer_content[:300]}"
        logger.info(f"WeCom found unique field keywords: {found_keywords}")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - WeCom form fields verified")


# ============================================================================
# CHAN-P1-004: WeChat channel drawer config form fields verification
# Channels covered: WeChat
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_wechat
class TestWeChatFormFields:
    """
    CHAN-P1-004: WeChat channel drawer config form fields verification.

    Channels covered: WeChat.

    Combined coverage:
    1. Open the WeChat drawer
    2. Verify the drawer title
    3. Verify the form fields exist

    Business scenario:
    Verify that the WeChat channel's config form fields are displayed correctly.
    """

    @pytest.mark.test_id("CHAN-P1-004")
    def test_wechat_form_fields(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify the WeChat channel's drawer config form fields.

        Steps:
        1. Open the Channels page
        2. Click the WeChat card and verify the drawer opens
        3. Verify the drawer title contains WeChat
        4. Verify the form fields exist
        """
        test_name = request.node.name
        channel_name = "WeChat"

        log_test_step("1. Open the Channels page")
        channels_page.open()

        log_test_step("2. Click the WeChat card and verify the drawer opens")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "Edit drawer did not open"

        log_test_step("3. Verify the drawer title")
        drawer_title = channels_page.get_drawer_title()
        channel_name_cn = {"WeChat": "微信"}.get(channel_name, channel_name)
        title_first_line = drawer_title.split('\n')[0].strip()
        assert channel_name in title_first_line or channel_name_cn in title_first_line, \
            f"Unexpected drawer title: {drawer_title}, expected to contain {channel_name} or {channel_name_cn}"
        logger.info(f"Drawer title: {drawer_title}")

        log_test_step("4. Verify WeChat-unique description and fields")
        drawer_content = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body').inner_text()
        # WeChat-unique markers (CN/EN both supported)
        wechat_unique_keywords = [
            "iLink", "QR code", "Bot Token", "Bot ID", "Secret",
            "扫码授权", "二维码", "私聊策略", "群聊策略", "需要 @提及", "白名单",
        ]
        found_unique = [kw for kw in wechat_unique_keywords if kw.lower() in drawer_content.lower()]

        assert len(found_unique) >= 2, \
            f"WeChat drawer did not contain enough unique markers (at least 2 required); expected {wechat_unique_keywords}, " \
            f"found {found_unique}, actual content: {drawer_content[:300]}"
        logger.info(f"WeChat found unique marker keywords: {found_unique}")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - WeChat form fields verified")


# ============================================================================
# CHAN-P1-005: OneBot channel drawer config form fields verification
# Channels covered: OneBot
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.channels_onebot
class TestOneBotFormFields:
    """
    CHAN-P1-005: OneBot channel drawer config form fields verification.

    Channels covered: OneBot.

    Combined coverage:
    1. Open the OneBot drawer
    2. Verify the drawer title
    3. Verify the form fields exist

    Business scenario:
    Verify that the OneBot channel's config form fields are displayed correctly.
    """

    @pytest.mark.test_id("CHAN-P1-005")
    def test_onebot_form_fields(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify the OneBot channel's drawer config form fields.

        Steps:
        1. Open the Channels page
        2. Click the OneBot card and verify the drawer opens
        3. Verify the drawer title contains OneBot
        4. Verify the form fields exist
        """
        test_name = request.node.name
        channel_name = "OneBot"

        log_test_step("1. Open the Channels page")
        channels_page.open()

        log_test_step("2. Click the OneBot card and verify the drawer opens")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "Edit drawer did not open"

        log_test_step("3. Verify the drawer title")
        drawer_title = channels_page.get_drawer_title()
        assert channel_name in drawer_title, f"Unexpected drawer title: {drawer_title}, expected to contain {channel_name}"
        logger.info(f"Drawer title: {drawer_title}")

        log_test_step("4. Verify the form fields exist")
        drawer_content = channels_page.page.locator('.qwenpaw-drawer-body, .ant-drawer-body').inner_text()
        # OneBot should have URL, Access Token, etc.
        expected_keywords = ["URL", "Access Token", "Token"]
        found_keywords = []
        for keyword in expected_keywords:
            if keyword.lower() in drawer_content.lower():
                found_keywords.append(keyword)

        assert len(found_keywords) > 0, \
            f"OneBot drawer did not contain the expected field keywords {expected_keywords}, actual content: {drawer_content[:200]}"
        logger.info(f"OneBot found field keywords: {found_keywords}")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - OneBot form fields verified")


# ============================================================================
# CHAN-P2-001: MQTT channel Bot Prefix configuration verification
# Channels covered: MQTT
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.channels_mqtt
class TestMQTTBotPrefix:
    """
    CHAN-P2-001: MQTT channel Bot Prefix configuration verification.

    Channels covered: MQTT.

    Combined coverage:
    1. Open the MQTT drawer
    2. Verify the drawer title
    3. Verify the Bot Prefix field exists
    4. Modify Bot Prefix and cancel, verify non-persistence

    Business scenario:
    Verify the Bot Prefix configuration for the MQTT channel.
    """

    @pytest.mark.test_id("CHAN-P2-001")
    def test_mqtt_bot_prefix(self, channels_page: ChannelsPage, request: pytest.FixtureRequest):
        """
        Verify the MQTT channel's Bot Prefix configuration.

        Steps:
        1. Open the Channels page
        2. Click the MQTT card and verify the drawer opens
        3. Verify the drawer title contains MQTT
        4. Verify the Bot Prefix field exists
        5. Modify Bot Prefix and cancel, verify non-persistence
        """
        test_name = request.node.name
        channel_name = "MQTT"

        log_test_step("1. Open the Channels page")
        channels_page.open()

        log_test_step("2. Click the MQTT card and verify the drawer opens")
        channels_page.click_channel_card(channel_name)
        assert channels_page.wait_for_drawer_open(), "Edit drawer did not open"

        log_test_step("3. Verify the drawer title")
        drawer_title = channels_page.get_drawer_title()
        assert channel_name in drawer_title, f"Unexpected drawer title: {drawer_title}, expected to contain {channel_name}"
        logger.info(f"Drawer title: {drawer_title}")

        log_test_step("4. Verify the Bot Prefix field exists")
        bot_input = channels_page.page.locator('#bot_prefix')
        assert bot_input.count() > 0 and bot_input.is_visible(), "Bot Prefix input not visible"
        original_prefix = bot_input.input_value()
        logger.info(f"Original Bot Prefix: '{original_prefix}'")

        log_test_step("5. Modify Bot Prefix and cancel, verify non-persistence")
        channels_page.fill_bot_prefix("temp_mqtt_prefix")
        channels_page.cancel_channel_config()
        channels_page.page.wait_for_timeout(1000)

        # Reopen and verify non-persistence
        channels_page.click_channel_card(channel_name)
        channels_page.wait_for_drawer_open()
        channels_page.page.wait_for_timeout(1000)
        after_cancel_prefix = channels_page.page.locator('#bot_prefix').input_value()
        assert after_cancel_prefix == original_prefix, \
            f"After cancel, Bot Prefix should revert to '{original_prefix}', actual: '{after_cancel_prefix}'"
        logger.info(f"Cancel verified: Bot Prefix still '{original_prefix}'")

        channels_page.close_drawer()

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - MQTT Bot Prefix configuration verified")
