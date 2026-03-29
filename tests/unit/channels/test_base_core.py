# -*- coding: utf-8 -*-
"""
BaseChannel Core Unit Tests
============================

Division of Labor with Contract Tests:
- Contract Tests (tests/contract/channels/):
  Verify external interface contracts, prevent breaking subclasses
- This Unit Test (tests/unit/channels/):
  Verify base class internal logic correctness

Corresponding Tier Strategy:
- B-tier (channels/*): Contract tests cover interfaces
- This file: As B-tier supplement, covers complex internal logic
  (debounce, merge, permissions)
"""
# pylint: disable=redefined-outer-name,protected-access
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import BaseChannel directly for internal logic testing
from copaw.app.channels.base import BaseChannel, ProcessHandler
from copaw.app.channels.console.channel import ConsoleChannel


# =============================================================================
# Test Fixtures (Shared Infrastructure)
# =============================================================================


@pytest.fixture
def mock_process() -> ProcessHandler:
    """Mock agent processing flow, returns simple text response."""

    async def process(_request: Any):
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Event,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        yield Event(
            object="message",
            status=RunStatus.Completed,
            type="message.completed",
            id="test-1",
            created_at=1234567890,
            message=Message(
                type=MessageType.MESSAGE,
                role=Role.ASSISTANT,
                content=[
                    TextContent(type=ContentType.TEXT, text="Test response"),
                ],
            ),
        )

    return process


@pytest.fixture
def base_channel(mock_process) -> BaseChannel:
    """
    Use ConsoleChannel as a testable instance of BaseChannel.
    ConsoleChannel is the simplest implementation,
    suitable for testing base class logic.
    """
    return ConsoleChannel(
        process=mock_process,
        enabled=True,
        bot_prefix="[TEST] ",
    )


@pytest.fixture
def content_builder():
    """Build different types of content parts for testing."""
    from agentscope_runtime.engine.schemas.agent_schemas import (
        TextContent,
        ImageContent,
        RefusalContent,
        ContentType,
    )

    class Builder:
        @staticmethod
        def text(text: str) -> TextContent:
            return TextContent(type=ContentType.TEXT, text=text)

        @staticmethod
        def image(url: str) -> ImageContent:
            return ImageContent(type=ContentType.IMAGE, image_url=url)

        @staticmethod
        def refusal(text: str) -> RefusalContent:
            return RefusalContent(type=ContentType.REFUSAL, refusal=text)

        @staticmethod
        def empty_text() -> TextContent:
            return TextContent(type=ContentType.TEXT, text="")

        @staticmethod
        def whitespace_text() -> TextContent:
            return TextContent(type=ContentType.TEXT, text="   ")

    return Builder()


# =============================================================================
# P0: Session & Request Building (Core Contract Internal Implementation)
# =============================================================================


class TestResolveSessionIdCore:
    """
    Session ID resolution core logic tests.

    Contract tests verify: resolve_session_id method exists and returns string
    This unit test verifies: Return format is correct, boundary cases handled
    """

    def test_default_format_channel_colon_sender(self, base_channel):
        """Default format must be {channel}:{sender_id}"""
        result = base_channel.resolve_session_id("user123")

        assert result == "console:user123"
        assert ":" in result
        assert result.startswith("console:")

    def test_empty_sender_id_handled(self, base_channel):
        """Empty sender_id should not crash"""
        result = base_channel.resolve_session_id("")

        assert result == "console:"

    def test_special_characters_in_sender_id(self, base_channel):
        """sender_id with special characters should be preserved"""
        result = base_channel.resolve_session_id("user@domain.com")

        assert "user@domain.com" in result


class TestBuildAgentRequestCore:
    """
    AgentRequest building core logic tests.

    Contract tests verify: build_agent_request_from_user_content exists
    This unit test verifies: Building logic is correct, boundary cases handled
    """

    def test_creates_request_with_all_fields(
        self,
        base_channel,
        content_builder,
    ):
        """Created request should contain all required fields"""
        request = base_channel.build_agent_request_from_user_content(
            channel_id="test_channel",
            sender_id="sender_123",
            session_id="test_channel:sender_123",
            content_parts=[content_builder.text("Hello")],
            channel_meta={"extra": "data"},
        )

        assert request.session_id == "test_channel:sender_123"
        assert request.user_id == "sender_123"
        assert request.channel == "test_channel"
        assert len(request.input) == 1

    def test_empty_content_gets_default(self, base_channel):
        """Empty content should auto-fill with default empty text"""
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        request = base_channel.build_agent_request_from_user_content(
            channel_id="test",
            sender_id="user1",
            session_id="test:user1",
            content_parts=[],
        )

        # Should fill with default empty text
        assert len(request.input[0].content) == 1
        assert request.input[0].content[0].type == ContentType.TEXT
        assert request.input[0].content[0].text == ""


# =============================================================================
# P1: Debounce & Content Buffering (Complex State Logic - Core Risk Area)
# =============================================================================


class TestContentHasTextLogic:
    """
    _content_has_text internal logic tests.

    This is the core of debounce mechanism, bugs cause message loss or delay.
    """

    def test_text_with_content_returns_true(
        self,
        base_channel,
        content_builder,
    ):
        """TEXT type with actual content should return True"""
        result = base_channel._content_has_text(
            [content_builder.text("Hello")],
        )
        assert result is True

    def test_empty_text_returns_false(self, base_channel, content_builder):
        """Empty string TEXT should return False"""
        result = base_channel._content_has_text([content_builder.empty_text()])
        assert result is False

    def test_whitespace_only_returns_false(
        self,
        base_channel,
        content_builder,
    ):
        """Whitespace-only TEXT should return False"""
        result = base_channel._content_has_text(
            [content_builder.whitespace_text()],
        )
        assert result is False

    def test_refusal_with_content_returns_true(
        self,
        base_channel,
        content_builder,
    ):
        """REFUSAL type with content should return True"""
        result = base_channel._content_has_text(
            [content_builder.refusal("I cannot")],
        )
        assert result is True

    def test_image_only_returns_false(self, base_channel, content_builder):
        """Pure IMAGE without text should return False"""
        result = base_channel._content_has_text(
            [content_builder.image("http://a.jpg")],
        )
        assert result is False

    def test_mixed_content_with_text(self, base_channel, content_builder):
        """IMAGE + TEXT combination should return True"""
        result = base_channel._content_has_text(
            [
                content_builder.image("http://a.jpg"),
                content_builder.text("caption"),
            ],
        )
        assert result is True


class TestNoTextDebounceBuffering:
    """
    _apply_no_text_debounce debounce buffering logic tests.

    **High Risk Area**: Modifying base class debounce logic
    causes abnormal message processing.
    """

    def test_no_text_content_buffered_not_processed(
        self,
        base_channel,
        content_builder,
    ):
        """Content without text should be buffered, not processed now"""
        parts = [content_builder.image("http://a.jpg")]

        should_process, merged = base_channel._apply_no_text_debounce(
            "session_1",
            parts,
        )

        assert should_process is False
        assert merged == []
        # Verify content is buffered
        assert "session_1" in base_channel._pending_content_by_session
        assert len(base_channel._pending_content_by_session["session_1"]) == 1

    def test_text_content_releases_buffer(self, base_channel, content_builder):
        """Text content should trigger buffer release"""
        # Buffer image first
        base_channel._apply_no_text_debounce(
            "session_2",
            [content_builder.image("http://a.jpg")],
        )

        # Then send text
        should_process, merged = base_channel._apply_no_text_debounce(
            "session_2",
            [content_builder.text("Hello")],
        )

        assert should_process is True
        assert len(merged) == 2  # image + text
        # Session buffer should be cleared
        assert "session_2" not in base_channel._pending_content_by_session

    def test_buffered_content_order_preserved(
        self,
        base_channel,
        content_builder,
    ):
        """Buffered content should maintain entry order"""
        # Buffer two images
        base_channel._apply_no_text_debounce(
            "session_3",
            [content_builder.image("http://1.jpg")],
        )
        base_channel._apply_no_text_debounce(
            "session_3",
            [content_builder.image("http://2.jpg")],
        )

        # Send text to trigger release
        _, merged = base_channel._apply_no_text_debounce(
            "session_3",
            [content_builder.text("Done")],
        )

        # Order: 1.jpg, 2.jpg, text
        assert merged[0].image_url == "http://1.jpg"
        assert merged[1].image_url == "http://2.jpg"
        assert merged[2].text == "Done"

    def test_isolated_sessions(self, base_channel, content_builder):
        """Different session buffers should be isolated"""
        base_channel._apply_no_text_debounce(
            "session_a",
            [content_builder.image("http://a.jpg")],
        )
        base_channel._apply_no_text_debounce(
            "session_b",
            [content_builder.image("http://b.jpg")],
        )

        # Only release session_a
        base_channel._apply_no_text_debounce(
            "session_a",
            [content_builder.text("Release A")],
        )

        # session_b buffer should remain
        assert "session_b" in base_channel._pending_content_by_session
        assert len(base_channel._pending_content_by_session["session_b"]) == 1


# =============================================================================
# P1: Native Items Merging (Complex Merge Logic)
# =============================================================================


class TestMergeNativeItemsLogic:
    """
    merge_native_items merge logic tests.

    Correctness of multi-part message merging directly affects user experience.
    """

    def test_empty_list_returns_none(self, base_channel):
        """Empty list should return None"""
        result = base_channel.merge_native_items([])
        assert result is None

    def test_single_item_preserved(self, base_channel, content_builder):
        """Single item should be returned as-is"""
        item = {
            "channel_id": "test",
            "sender_id": "user1",
            "content_parts": [content_builder.text("Hello")],
            "meta": {"key": "value"},
        }

        result = base_channel.merge_native_items([item])

        assert result["channel_id"] == "test"
        assert result["sender_id"] == "user1"
        assert result["meta"]["key"] == "value"

    def test_multiple_items_content_concatenated(
        self,
        base_channel,
        content_builder,
    ):
        """Multi-item content should be concatenated"""
        items = [
            {"content_parts": [content_builder.text("A")], "meta": {}},
            {"content_parts": [content_builder.text("B")], "meta": {}},
            {"content_parts": [content_builder.text("C")], "meta": {}},
        ]

        result = base_channel.merge_native_items(items)

        assert len(result["content_parts"]) == 3
        assert result["content_parts"][0].text == "A"
        assert result["content_parts"][1].text == "B"
        assert result["content_parts"][2].text == "C"

    def test_meta_merge_last_wins(self, base_channel):
        """Meta merge should use 'later overrides earlier' strategy"""
        items = [
            {"content_parts": [], "meta": {"a": 1, "b": 2}},
            {"content_parts": [], "meta": {"b": 3, "c": 4}},
        ]

        result = base_channel.merge_native_items(items)

        assert result["meta"]["a"] == 1  # preserved
        assert result["meta"]["b"] == 3  # overridden
        assert result["meta"]["c"] == 4  # added

    def test_special_meta_keys_preserved(self, base_channel):
        """Special meta keys (reply_future, conv_id) should be preserved"""
        future_a = object()
        future_b = object()

        items = [
            {"content_parts": [], "meta": {"reply_future": future_a}},
            {
                "content_parts": [],
                "meta": {"reply_future": future_b, "conversation_id": "abc"},
            },
        ]

        result = base_channel.merge_native_items(items)

        # Later future should override earlier
        assert result["meta"]["reply_future"] is future_b
        assert result["meta"]["conversation_id"] == "abc"


# =============================================================================
# P1: Allowlist Permission Logic (Security Critical)
# =============================================================================


class TestAllowlistPermissionLogic:
    """
    _check_allowlist permission check logic tests.

    **Security Critical**: Wrong implementation causes unauthorized access.
    """

    def test_open_policy_allows_all_dm(self, base_channel):
        """Open policy DM should allow any user"""
        base_channel.dm_policy = "open"
        base_channel.allow_from = set()

        allowed, error = base_channel._check_allowlist(
            "any_user",
            is_group=False,
        )

        assert allowed is True
        assert error is None

    def test_restricted_dm_blocks_not_in_list(self, base_channel):
        """Restricted policy should block users not in whitelist (DM)"""
        base_channel.dm_policy = "restricted"
        base_channel.allow_from = {"allowed_user"}
        base_channel.deny_message = "Access denied"

        allowed, error = base_channel._check_allowlist(
            "blocked_user",
            is_group=False,
        )

        assert allowed is False
        assert error is not None
        assert "Access denied" in error

    def test_restricted_dm_allows_in_list(self, base_channel):
        """Restricted policy should allow users in whitelist (DM)"""
        base_channel.dm_policy = "restricted"
        base_channel.allow_from = {"allowed_user"}

        allowed, error = base_channel._check_allowlist(
            "allowed_user",
            is_group=False,
        )

        assert allowed is True
        assert error is None

    def test_group_policy_separate_from_dm(self, base_channel):
        """group_policy should be independent from dm_policy"""
        base_channel.dm_policy = "restricted"
        base_channel.group_policy = "open"
        base_channel.allow_from = {"specific_user"}

        # User blocked in DM
        dm_allowed, _ = base_channel._check_allowlist(
            "stranger",
            is_group=False,
        )
        # Same user allowed in group chat
        group_allowed, _ = base_channel._check_allowlist(
            "stranger",
            is_group=True,
        )

        assert dm_allowed is False
        assert group_allowed is True

    def test_default_deny_message_provided(self, base_channel):
        """Default deny message should be provided when not configured"""
        base_channel.dm_policy = "restricted"
        base_channel.allow_from = {"user1"}
        base_channel.deny_message = ""

        allowed, error = base_channel._check_allowlist(
            "blocked",
            is_group=False,
        )

        assert allowed is False
        assert error is not None
        assert (
            "not authorized" in error.lower()
            or "only available" in error.lower()
        )


# =============================================================================
# P2: Mention Policy Logic
# =============================================================================


class TestMentionPolicyLogic:
    """
    _check_group_mention mention policy logic tests.
    """

    def test_direct_message_bypasses_mention_check(self, base_channel):
        """Direct message should bypass mention check"""
        base_channel.require_mention = True

        result = base_channel._check_group_mention(is_group=False, meta={})

        assert result is True

    def test_group_without_mention_requirement_allows_all(self, base_channel):
        """Group chat without mention requirement should allow all messages"""
        base_channel.require_mention = False

        result = base_channel._check_group_mention(is_group=True, meta={})

        assert result is True

    def test_require_mention_allows_when_bot_mentioned(self, base_channel):
        """When require_mention enabled, bot_mentioned=True should pass"""
        base_channel.require_mention = True

        result = base_channel._check_group_mention(
            is_group=True,
            meta={"bot_mentioned": True},
        )

        assert result is True

    def test_require_mention_allows_when_has_command(self, base_channel):
        """When require_mention enabled, has_bot_command=True should pass"""
        base_channel.require_mention = True

        result = base_channel._check_group_mention(
            is_group=True,
            meta={"has_bot_command": True},
        )

        assert result is True

    def test_require_mention_blocks_without_mention_or_command(
        self,
        base_channel,
    ):
        """When require_mention enabled, no mention/cmd should block"""
        base_channel.require_mention = True

        result = base_channel._check_group_mention(is_group=True, meta={})

        assert result is False


# =============================================================================
# P2: Error Extraction Logic
# =============================================================================


class TestResponseErrorExtraction:
    """
    _get_response_error_message error extraction logic tests.
    """

    def test_none_response_returns_none(self, base_channel):
        """None response should return None"""
        result = base_channel._get_response_error_message(None)
        assert result is None

    def test_response_without_error_returns_none(self, base_channel):
        """Response without error should return None"""
        mock_response = MagicMock()
        mock_response.error = None

        result = base_channel._get_response_error_message(mock_response)

        assert result is None

    def test_nested_error_message_extracted(self, base_channel):
        """Nested error message should be extracted"""
        mock_error = MagicMock()
        mock_error.message = "Nested error occurred"
        mock_response = MagicMock()
        mock_response.error = mock_error

        result = base_channel._get_response_error_message(mock_response)

        assert result == "Nested error occurred"

    def test_dict_error_message_extracted(self, base_channel):
        """Dict type error should extract message field"""
        mock_response = MagicMock()
        mock_response.error = {"message": "Dict error message"}

        result = base_channel._get_response_error_message(mock_response)

        assert result == "Dict error message"

    def test_string_error_returned_directly(self, base_channel):
        """String error should be returned directly"""
        mock_response = MagicMock()
        mock_response.error = "Plain string error"

        result = base_channel._get_response_error_message(mock_response)

        assert result == "Plain string error"


# =============================================================================
# Async Process Loop Integration Test
# =============================================================================


@pytest.mark.asyncio
class TestRunProcessLoopIntegration:
    """
    _run_process_loop integration tests.

    Verify coordination of entire event handling process.
    """

    async def test_completed_message_triggers_send(self, base_channel):
        """Complete message event should trigger sending"""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Event,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        # Mock send method
        base_channel.send_message_content = AsyncMock()

        # Create mock request
        mock_request = MagicMock()
        mock_request.user_id = "user1"
        mock_request.session_id = "test:user1"
        mock_request.channel_meta = {}

        # Define process that returns completed event
        async def mock_process(_request):
            yield Event(
                object="message",
                status=RunStatus.Completed,
                type="message.completed",
                id="msg-1",
                created_at=1234567890,
                message=Message(
                    type=MessageType.MESSAGE,
                    role=Role.ASSISTANT,
                    content=[TextContent(type=ContentType.TEXT, text="Hello")],
                ),
            )

        base_channel._process = mock_process

        # Execute
        await base_channel._run_process_loop(
            mock_request,
            to_handle="user1",
            send_meta={},
        )

        # Verify send_message_content was called
        base_channel.send_message_content.assert_called_once()

    async def test_response_error_triggers_error_message(self, base_channel):
        """Response containing error should trigger error message sending"""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            Response,
            AgentResponse,
            ErrorDetail,
            RunStatus,
        )

        # Mock error sending
        base_channel.send_content_parts = AsyncMock()

        mock_request = MagicMock()
        mock_request.user_id = "user1"

        async def error_process(_request):
            yield Response(
                object="response",
                status=RunStatus.Completed,
                type="response.completed",
                id="resp-1",
                created_at=1234567890,
                response=AgentResponse(
                    error=ErrorDetail(
                        message="Processing failed",
                        type="test_error",
                    ),
                ),
            )

        base_channel._process = error_process

        await base_channel._run_process_loop(
            mock_request,
            to_handle="user1",
            send_meta={},
        )

        # Verify error message was sent
        base_channel.send_content_parts.assert_called_once()
        # Verify error text is included in message
        call_args = base_channel.send_content_parts.call_args
        parts = call_args[0][1]  # second positional arg is parts list
        assert any("Processing failed" in str(part) for part in parts)


# =============================================================================
# Division of Labor with Contract Tests
# =============================================================================
# Test Layering Summary
# =====================
#
# This unit test (test_base_core.py) covers:
#   - Complex algorithm logic (debounce, merge, permissions)
#   - Boundary case handling (nulls, special characters)
#   - Error handling flow
#   - Internal state management
#
# Contract tests (tests/contract/channels/) cover:
#   - Interface method existence (method exists)
#   - Return type correctness (returns correct type)
#   - Parameter signature compatibility (signature compatible)
#   - Required subclass methods (abstract enforcement)
#
# Relationship between the two:
#       Unit Test              Contract Test
#   Internal impl correct  <->  External contract compliance
#          ^                         v
#     BaseChannel  <-------->  Console/DingTalk/QQ
#
# When modifying BaseChannel:
#   1. Run Unit Tests first: Verify internal logic is still correct
#   2. Then run Contract Tests: Verify subclass contracts not broken
#
# Test order example:
#   - Modify DingTalk: Run dingtalk unit tests first
#     → then dingtalk contract tests
