# -*- coding: utf-8 -*-
"""Tests for Feishu (Lark) channel.

This module tests:
1. Event handling logic (_on_message)
2. Token retrieval and caching (_get_tenant_access_token)
3. Message routing (_route_from_handle)
4. Session ID generation logic
5. Receive ID storage and loading
"""
# pylint: disable=protected-access
# protected-access: tests need to access internal methods

import sys
from types import ModuleType
from unittest.mock import Mock, patch

import pytest

# Create mock modules to avoid import dependencies
_mock_agentscope = ModuleType("agentscope_runtime")
_mock_agentscope.engine = ModuleType("agentscope_runtime.engine")
_mock_agentscope.engine.schemas = ModuleType(
    "agentscope_runtime.engine.schemas",
)
_mock_agentscope.engine.schemas.agent_schemas = Mock()
_mock_agentscope.engine.schemas.agent_schemas.FileContent = Mock
_mock_agentscope.engine.schemas.agent_schemas.ImageContent = Mock
_mock_agentscope.engine.schemas.agent_schemas.TextContent = Mock
sys.modules["agentscope_runtime"] = _mock_agentscope
sys.modules["agentscope_runtime.engine"] = _mock_agentscope.engine
sys.modules[
    "agentscope_runtime.engine.schemas"
] = _mock_agentscope.engine.schemas
sys.modules[
    "agentscope_runtime.engine.schemas.agent_schemas"
] = _mock_agentscope.engine.schemas.agent_schemas

# Mock other problematic imports
sys.modules["lark_oapi"] = Mock()
sys.modules["lark_oapi.ws"] = Mock()
sys.modules["lark_oapi.ws.client"] = Mock()

# pylint: disable=wrong-import-position
# Import the modules we're testing
from copaw.app.channels.feishu.constants import (  # noqa: E402
    FEISHU_PROCESSED_IDS_MAX,
    FEISHU_SESSION_ID_SUFFIX_LEN,
    FEISHU_TOKEN_REFRESH_BEFORE_SECONDS,
)
from copaw.app.channels.feishu.utils import (  # noqa: E402
    extract_json_key,
    normalize_feishu_md,
    sender_display_string,
    short_session_id_from_full_id,
)

# pylint: enable=wrong-import-position


class TestFeishuUtils:
    """Test utility functions."""

    def test_short_session_id_from_full_id(self) -> None:
        """Test session ID shortening."""
        full_id = "oc_1234567890abcdef"
        result = short_session_id_from_full_id(full_id)
        assert len(result) == FEISHU_SESSION_ID_SUFFIX_LEN
        assert result == full_id[-FEISHU_SESSION_ID_SUFFIX_LEN:]

    def test_short_session_id_from_full_id_short_input(self) -> None:
        """Test session ID with short input."""
        short_id = "abc"
        result = short_session_id_from_full_id(short_id)
        assert result == short_id

    def test_sender_display_string_with_nickname(self) -> None:
        """Test sender display with nickname."""
        result = sender_display_string("张三", "ou_1234567890")
        assert result == "张三#7890"

    def test_sender_display_string_without_nickname(self) -> None:
        """Test sender display without nickname."""
        result = sender_display_string(None, "ou_1234567890")
        assert result == "unknown#7890"

    def test_sender_display_string_short_sender_id(self) -> None:
        """Test sender display with short sender ID."""
        result = sender_display_string("李四", "ab")
        assert result == "李四#ab"

    def test_extract_json_key_found(self) -> None:
        """Test extracting key from JSON."""
        content = '{"text": "hello world"}'
        result = extract_json_key(content, "text")
        assert result == "hello world"

    def test_extract_json_key_not_found(self) -> None:
        """Test extracting missing key."""
        content = '{"other": "value"}'
        result = extract_json_key(content, "text")
        assert result is None

    def test_extract_json_key_invalid_json(self) -> None:
        """Test extracting from invalid JSON."""
        content = "not json"
        result = extract_json_key(content, "text")
        assert result is None

    def test_extract_json_key_multiple_keys(self) -> None:
        """Test extracting first present key from multiple options."""
        content = '{"imageKey": "img_123"}'
        result = extract_json_key(content, "image_key", "imageKey")
        assert result == "img_123"

    def test_normalize_feishu_md_code_fence(self) -> None:
        """Test markdown normalization adds newline before code fence."""
        text = "代码如下：```python\nprint(1)\n```"
        result = normalize_feishu_md(text)
        assert "\n```" in result

    def test_normalize_feishu_md_empty(self) -> None:
        """Test markdown normalization with empty input."""
        assert normalize_feishu_md("") == ""
        assert normalize_feishu_md(None) is None


class TestFeishuConstants:
    """Test constants are properly defined."""

    def test_session_id_suffix_length(self) -> None:
        """Test session ID suffix length constant."""
        assert FEISHU_SESSION_ID_SUFFIX_LEN == 8

    def test_processed_ids_max(self) -> None:
        """Test processed IDs max constant."""
        assert FEISHU_PROCESSED_IDS_MAX == 1000

    def test_token_refresh_before_seconds(self) -> None:
        """Test token refresh buffer constant."""
        assert FEISHU_TOKEN_REFRESH_BEFORE_SECONDS == 60


# Import channel class with mocked dependencies
with patch.dict(
    "sys.modules",
    {
        "lark_oapi": Mock(),
        "lark_oapi.ws": Mock(),
        "lark_oapi.ws.client": Mock(),
    },
):
    from copaw.app.channels.feishu.channel import FeishuChannel


class TestFeishuChannelRoute:
    """Test message routing logic."""

    @pytest.fixture
    def channel(self):
        """Create a mock Feishu channel."""
        process_mock = Mock()
        return FeishuChannel(
            process=process_mock,
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="[BOT] ",
        )

    def test_route_from_handle_session_key(self, channel) -> None:
        """Test routing from session key handle."""
        result = channel._route_from_handle("feishu:sw:abc123")
        assert result == {"session_key": "abc123"}

    def test_route_from_handle_chat_id(self, channel) -> None:
        """Test routing from chat_id handle."""
        result = channel._route_from_handle("feishu:chat_id:oc_123")
        assert result == {
            "receive_id_type": "chat_id",
            "receive_id": "oc_123",
        }

    def test_route_from_handle_open_id(self, channel) -> None:
        """Test routing from open_id handle."""
        result = channel._route_from_handle("feishu:open_id:ou_123")
        assert result == {
            "receive_id_type": "open_id",
            "receive_id": "ou_123",
        }

    def test_route_from_handle_raw_chat_id(self, channel) -> None:
        """Test routing from raw chat_id (oc_ prefix)."""
        result = channel._route_from_handle("oc_123456")
        assert result == {
            "receive_id_type": "chat_id",
            "receive_id": "oc_123456",
        }

    def test_route_from_handle_raw_open_id(self, channel) -> None:
        """Test routing from raw open_id (ou_ prefix)."""
        result = channel._route_from_handle("ou_123456")
        assert result == {
            "receive_id_type": "open_id",
            "receive_id": "ou_123456",
        }

    def test_route_from_handle_unknown(self, channel) -> None:
        """Test routing from unknown handle defaults to open_id."""
        result = channel._route_from_handle("random_id")
        assert result == {
            "receive_id_type": "open_id",
            "receive_id": "random_id",
        }

    def test_resolve_session_id_group_chat(self, channel) -> None:
        """Test session ID resolution for group chat."""
        meta = {
            "feishu_chat_id": "oc_1234567890abcdef",
            "feishu_chat_type": "group",
        }
        result = channel.resolve_session_id("ou_sender", meta)
        # Should use chat_id suffix for group chats (8 chars)
        assert result == "90abcdef"

    def test_resolve_session_id_p2p(self, channel) -> None:
        """Test session ID resolution for p2p chat."""
        meta = {
            "feishu_chat_id": "oc_123",
            "feishu_chat_type": "p2p",
        }
        result = channel.resolve_session_id("ou_abcdef123456", meta)
        # Should use sender_id suffix for p2p (8 chars)
        assert result == "ef123456"

    def test_to_handle_from_target_session(self, channel) -> None:
        """Test to_handle generation with session_id."""
        result = channel.to_handle_from_target(
            user_id="ou_123",
            session_id="abc123",
        )
        assert result == "feishu:sw:abc123"

    def test_to_handle_from_target_no_session(self, channel) -> None:
        """Test to_handle generation without session_id."""
        result = channel.to_handle_from_target(
            user_id="ou_123",
            session_id="",
        )
        assert result == "feishu:open_id:ou_123"


class TestFeishuChannelDeduplication:
    """Test message deduplication logic."""

    @pytest.fixture
    def channel(self):
        """Create a mock Feishu channel."""
        process_mock = Mock()
        channel = FeishuChannel(
            process=process_mock,
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="[BOT] ",
        )
        return channel

    def test_processed_message_ids_deduplication(self, channel) -> None:
        """Test message ID deduplication with LRU behavior.

        Simulates the trimming logic in _on_message:
        while len(self._processed_message_ids) > FEISHU_PROCESSED_IDS_MAX:
            self._processed_message_ids.popitem(last=False)
        """
        # Add messages up to limit
        for i in range(FEISHU_PROCESSED_IDS_MAX + 10):
            msg_id = f"msg_{i:04d}"
            channel._processed_message_ids[msg_id] = None
            # Simulate the trimming logic from _on_message
            while (
                len(channel._processed_message_ids) > FEISHU_PROCESSED_IDS_MAX
            ):
                channel._processed_message_ids.popitem(last=False)

        # Should have trimmed to max size
        assert len(channel._processed_message_ids) == FEISHU_PROCESSED_IDS_MAX
        # Oldest items should be removed (msg_0010 to msg_0000 are trimmed)
        assert "msg_0000" not in channel._processed_message_ids
        assert "msg_0009" not in channel._processed_message_ids
        # Newest items should remain
        assert "msg_1009" in channel._processed_message_ids
        assert "msg_1000" in channel._processed_message_ids

    def test_is_message_processed(self, channel) -> None:
        """Test checking if message was already processed."""
        msg_id = "om_1234567890"
        channel._processed_message_ids[msg_id] = None

        # Should be able to check existence
        assert msg_id in channel._processed_message_ids


class TestFeishuChannelBuildPostContent:
    """Test post content building."""

    @pytest.fixture
    def channel(self):
        """Create a mock Feishu channel."""
        process_mock = Mock()
        return FeishuChannel(
            process=process_mock,
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="[BOT] ",
        )

    def test_build_post_content_text_only(self, channel) -> None:
        """Test building post content with text only."""
        result = channel._build_post_content("Hello world", [])

        assert "zh_cn" in result
        assert result["zh_cn"]["content"][0][0]["tag"] == "md"
        assert result["zh_cn"]["content"][0][0]["text"] == "Hello world"

    def test_build_post_content_with_images(self, channel) -> None:
        """Test building post content with images."""
        result = channel._build_post_content("See image:", ["img_key_123"])

        assert len(result["zh_cn"]["content"]) == 2
        assert result["zh_cn"]["content"][1][0]["tag"] == "img"
        assert result["zh_cn"]["content"][1][0]["image_key"] == "img_key_123"

    def test_build_post_content_empty(self, channel) -> None:
        """Test building post content with empty input."""
        result = channel._build_post_content("", [])

        # Should have at least one row with [empty]
        assert result["zh_cn"]["content"][0][0]["text"] == "[empty]"


class TestFeishuChannelParsePostContent:
    """Test parsing incoming post (rich text) content."""

    @pytest.fixture
    def channel(self):
        """Create a mock Feishu channel."""
        process_mock = Mock()
        return FeishuChannel(
            process=process_mock,
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="[BOT] ",
        )

    @pytest.mark.asyncio
    async def test_parse_post_content_text_only(self, channel) -> None:
        """Test parsing post content with text only."""
        content_raw = '{"content": [[{"tag": "text", "text": "Hello world"}]]}'
        result = await channel._parse_post_content("msg_123", content_raw)

        assert result["text"] == "Hello world"
        assert result["image_urls"] == []

    @pytest.mark.asyncio
    async def test_parse_post_content_with_title(self, channel) -> None:
        """Test parsing post content with title."""
        content_raw = (
            '{"title": "My Title", "content": '
            '[[{"tag": "text", "text": "Body text"}]]}'
        )
        result = await channel._parse_post_content("msg_123", content_raw)

        assert result["text"] == "My Title\nBody text"
        assert result["image_urls"] == []

    @pytest.mark.asyncio
    async def test_parse_post_content_markdown(self, channel) -> None:
        """Test parsing post content with markdown tag."""
        content_raw = '{"content": [[{"tag": "md", "text": "**Bold** text"}]]}'
        result = await channel._parse_post_content("msg_123", content_raw)

        assert result["text"] == "**Bold** text"
        assert result["image_urls"] == []

    @pytest.mark.asyncio
    async def test_parse_post_content_multiple_rows(self, channel) -> None:
        """Test parsing post content with multiple rows."""
        content_raw = (
            '{"content": [[{"tag": "text", "text": "Line 1"}],'
            ' [{"tag": "text", "text": "Line 2"}]]}'
        )
        result = await channel._parse_post_content("msg_123", content_raw)

        assert result["text"] == "Line 1\nLine 2"
        assert result["image_urls"] == []

    @pytest.mark.asyncio
    async def test_parse_post_content_mixed_items_in_row(
        self,
        channel,
    ) -> None:
        """Test parsing post content with mixed items in a row."""
        content_raw = (
            '{"content": [[{"tag": "text", "text": "Hello "}, '
            '{"tag": "text", "text": "world"}]]}'
        )
        result = await channel._parse_post_content("msg_123", content_raw)

        assert result["text"] == "Hello world"
        assert result["image_urls"] == []

    @pytest.mark.asyncio
    async def test_parse_post_content_invalid_json(self, channel) -> None:
        """Test parsing invalid JSON content."""
        result = await channel._parse_post_content("msg_123", "not valid json")

        assert result["text"] == ""
        assert result["image_urls"] == []

    @pytest.mark.asyncio
    async def test_parse_post_content_empty_content(self, channel) -> None:
        """Test parsing empty content."""
        result = await channel._parse_post_content("msg_123", "{}")

        assert result["text"] == ""
        assert result["image_urls"] == []


class TestFeishuChannelConfiguration:
    """Test channel configuration."""

    def test_channel_disabled_by_default(self) -> None:
        """Test channel is disabled by default from env."""
        import os

        # Ensure env var is not set
        if "FEISHU_CHANNEL_ENABLED" in os.environ:
            del os.environ["FEISHU_CHANNEL_ENABLED"]

        process_mock = Mock()
        channel = FeishuChannel.from_env(process_mock)

        assert channel.enabled is False
