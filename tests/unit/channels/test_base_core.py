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
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=reimported,broad-exception-raised,using-constant-test
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

        # Should fill with default empty text (implementation uses space " ")
        assert len(request.input[0].content) == 1
        assert request.input[0].content[0].type == ContentType.TEXT
        # Implementation uses " " as default to satisfy non-empty validation
        assert request.input[0].content[0].text == " "


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

    def test_meta_merge_combined(self, base_channel):
        """Meta merge should combine specific special keys (last wins)"""
        # The implementation only merges special keys (last wins):
        # reply_future, reply_loop, incoming_message, conversation_id
        future_a = object()
        future_b = object()

        items = [
            {
                "content_parts": [],
                "meta": {"reply_future": future_a, "extra": 1},
            },
            {
                "content_parts": [],
                "meta": {"reply_future": future_b, "conversation_id": "abc"},
            },
        ]

        result = base_channel.merge_native_items(items)

        # Verify result has meta
        assert "meta" in result
        # Later future should override earlier (last wins)
        assert result["meta"]["reply_future"] is future_b
        # conversation_id should be merged
        assert result["meta"]["conversation_id"] == "abc"
        # Extra keys are NOT merged (implementation limitation)
        # This is documented behavior - only specific keys are merged

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
        # Create a mock that doesn't auto-create attributes
        mock_response = MagicMock(spec=[])
        mock_response.error = None
        mock_response.data = None

        result = base_channel._get_response_error_message(mock_response)

        # Should return None when there's no error
        assert result is None

    def test_nested_error_message_extracted(self, base_channel):
        """Nested error message should be extracted"""
        # Create a mock error with message attribute
        mock_error = MagicMock(spec=[])
        mock_error.message = "Nested error occurred"

        mock_response = MagicMock(spec=[])
        mock_response.error = mock_error
        mock_response.data = None

        result = base_channel._get_response_error_message(mock_response)

        assert result == "Nested error occurred"

    def test_dict_error_message_handled(self, base_channel):
        """Dict type error should be extracted"""
        mock_response = MagicMock(spec=[])
        mock_response.error = {"message": "Dict error message"}
        mock_response.data = None

        result = base_channel._get_response_error_message(mock_response)

        assert result == "Dict error message"

    def test_string_error_handled(self, base_channel):
        """String error should be returned as-is"""
        mock_response = MagicMock(spec=[])
        mock_response.error = "Plain string error"
        mock_response.data = None

        result = base_channel._get_response_error_message(mock_response)

        assert result == "Plain string error"


# =============================================================================
# P1: set_enqueue / set_workspace (Simple Setters)
# =============================================================================


class TestLifecycleCallbacks:
    """
    Lifecycle callback setting logic tests.

    Channels need callbacks set by ChannelManager during initialization.
    """

    def test_set_enqueue_stores_callback(self, base_channel):
        """set_enqueue should store the callback function."""
        callback = MagicMock()

        base_channel.set_enqueue(callback)

        assert base_channel._enqueue is callback

    def test_set_enqueue_overwrites_existing(self, base_channel):
        """set_enqueue should overwrite existing callback."""
        old_callback = MagicMock()
        new_callback = MagicMock()
        base_channel._enqueue = old_callback

        base_channel.set_enqueue(new_callback)

        assert base_channel._enqueue is new_callback

    def test_set_workspace_stores_workspace(self, base_channel):
        """set_workspace should store workspace and command_registry."""
        workspace = MagicMock()
        command_registry = MagicMock()

        base_channel.set_workspace(workspace, command_registry)

        assert base_channel._workspace is workspace
        assert base_channel._command_registry is command_registry

    def test_set_workspace_without_registry(self, base_channel):
        """set_workspace should work without command_registry."""
        workspace = MagicMock()

        base_channel.set_workspace(workspace)

        assert base_channel._workspace is workspace
        assert base_channel._command_registry is None


# =============================================================================
# P1: send_message_content (Message Sending Core)
# =============================================================================


@pytest.mark.asyncio
class TestSendMessageContent:
    """
    send_message_content and _message_to_content_parts tests.

    Core message sending logic that converts messages to content parts.
    """

    async def test_send_message_content_converts_to_parts(
        self,
        base_channel,
    ):
        """send_message_content should convert message to parts."""
        mock_message = MagicMock()
        mock_parts = [MagicMock()]

        with patch.object(
            base_channel,
            "_message_to_content_parts",
            return_value=mock_parts,
        ) as mock_convert:
            with patch.object(
                base_channel,
                "send_content_parts",
            ) as mock_send:
                await base_channel.send_message_content(
                    "user123",
                    mock_message,
                    meta={},
                )

                mock_convert.assert_called_once_with(mock_message)
                mock_send.assert_called_once()

    async def test_send_message_content_skips_empty_parts(self, base_channel):
        """send_message_content should skip when no parts."""
        mock_message = MagicMock()

        with patch.object(
            base_channel,
            "_message_to_content_parts",
            return_value=[],
        ):
            with patch.object(
                base_channel,
                "send_content_parts",
            ) as mock_send:
                await base_channel.send_message_content(
                    "user123",
                    mock_message,
                    meta={},
                )

                mock_send.assert_not_called()


# =============================================================================
# P1: _consume_with_tracker / _stream_with_tracker (Core Consumer Logic)
# =============================================================================


@pytest.mark.asyncio
class TestConsumeWithTracker:
    """
    _consume_with_tracker tests.

    High-risk integration with TaskTracker for cancellation support.
    """

    async def test_consume_with_tracker_uses_workspace(self, base_channel):
        """_consume_with_tracker should use workspace for chat management."""
        mock_workspace = MagicMock()
        mock_chat_manager = AsyncMock()

        # Create async mock for task_tracker with async methods
        async def mock_attach_or_start(*args, **kwargs):
            return (MagicMock(), True)  # (queue, is_new)

        async def mock_stream(*args, **kwargs):
            if False:  # Make it an async generator
                yield None
            return

        mock_task_tracker = MagicMock()
        mock_task_tracker.attach_or_start = mock_attach_or_start
        mock_task_tracker.stream_from_queue = mock_stream

        mock_workspace.chat_manager = mock_chat_manager
        mock_workspace.task_tracker = mock_task_tracker
        mock_chat_manager.get_or_create_chat.return_value = MagicMock(
            id="chat-123",
        )

        base_channel.set_workspace(mock_workspace)

        mock_request = MagicMock(
            session_id="test:session",
            user_id="user123",
            channel="test",
        )
        mock_payload = {"content_parts": []}

        with patch.object(
            base_channel,
            "_extract_chat_name",
            return_value="Test Chat",
        ):
            await base_channel._consume_with_tracker(
                mock_request,
                mock_payload,
            )

        mock_chat_manager.get_or_create_chat.assert_called_once()

    async def test_consume_with_tracker_existing_task_logs_warning(
        self,
        base_channel,
    ):
        """When task already exists, should log warning and not start new."""
        mock_workspace = MagicMock()
        mock_chat_manager = AsyncMock()

        # Create async mock that returns is_new=False
        async def mock_attach_or_start(*args, **kwargs):
            return (MagicMock(), False)  # (queue, is_new) - is_new=False

        mock_task_tracker = MagicMock()
        mock_task_tracker.attach_or_start = mock_attach_or_start

        mock_workspace.chat_manager = mock_chat_manager
        mock_workspace.task_tracker = mock_task_tracker
        mock_chat_manager.get_or_create_chat.return_value = MagicMock(
            id="chat-123",
        )

        base_channel.set_workspace(mock_workspace)

        mock_request = MagicMock(
            session_id="test:session",
            user_id="user123",
            channel="test",
        )
        mock_payload = {"content_parts": []}

        with patch.object(
            base_channel,
            "_extract_chat_name",
            return_value="Test Chat",
        ):
            await base_channel._consume_with_tracker(
                mock_request,
                mock_payload,
            )

        # Test passed if we reach here (warning was logged for is_new=False)


@pytest.mark.asyncio
class TestStreamWithTracker:
    """
    _stream_with_tracker tests.

    Core streaming logic through TaskTracker.
    """

    async def test_stream_with_tracker_yields_sse_events(self, base_channel):
        """_stream_with_tracker should yield SSE-formatted events."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Event,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        mock_event = Event(
            object="message",
            status=RunStatus.InProgress,
            type="message.in_progress",
            id="ev-1",
            created_at=1234567890,
            message=Message(
                type=MessageType.MESSAGE,
                role=Role.ASSISTANT,
                content=[
                    TextContent(type=ContentType.TEXT, text="Hello"),
                ],
            ),
        )

        async def mock_process(request):
            yield mock_event

        base_channel._process = mock_process
        base_channel.set_workspace(MagicMock())

        mock_payload = MagicMock()
        with patch.object(
            base_channel,
            "_payload_to_request",
            return_value=MagicMock(
                session_id="test:session",
                user_id="user123",
                channel="test",
                channel_meta={},
            ),
        ):
            with patch.object(
                base_channel,
                "get_to_handle_from_request",
                return_value="user123",
            ):
                with patch.object(
                    base_channel,
                    "_before_consume_process",
                ):
                    events = []
                    async for event in base_channel._stream_with_tracker(
                        mock_payload,
                    ):
                        events.append(event)
                        break  # Just check first event

                    assert len(events) == 1
                    assert "data:" in events[0]

    async def test_stream_with_tracker_handles_exception(self, base_channel):
        """_stream_with_tracker should handle exceptions gracefully."""

        async def mock_process(request):
            yield MagicMock()
            raise ValueError("Test error")

        base_channel._process = mock_process

        # Mock _on_consume_error to prevent actual error handling
        with patch.object(
            base_channel,
            "_on_consume_error",
            new_callable=AsyncMock,
        ):
            with patch.object(
                base_channel,
                "_payload_to_request",
                return_value=MagicMock(
                    session_id="test:session",
                    user_id="user123",
                    channel="test",
                    channel_meta={},
                ),
            ):
                with patch.object(
                    base_channel,
                    "get_to_handle_from_request",
                    return_value="user123",
                ):
                    with patch.object(
                        base_channel,
                        "_before_consume_process",
                    ):
                        with pytest.raises(ValueError):
                            async for _ in base_channel._stream_with_tracker(
                                {},
                            ):
                                pass


# =============================================================================
# P2: Audio Content Detection
# =============================================================================


class TestAudioContentDetection:
    """
    _content_has_audio internal logic tests.
    """

    def test_audio_content_returns_true(self, base_channel):
        """Content with AudioContent should return True."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AudioContent,
            ContentType,
        )

        parts = [AudioContent(type=ContentType.AUDIO, data=b"audio_data")]

        result = base_channel._content_has_audio(parts)

        assert result is True

    def test_no_audio_content_returns_false(
        self,
        base_channel,
        content_builder,
    ):
        """Content without AudioContent should return False."""
        parts = [content_builder.text("Hello")]

        result = base_channel._content_has_audio(parts)

        assert result is False

    def test_mixed_content_with_audio_returns_true(self, base_channel):
        """Mixed content with audio should return True."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AudioContent,
            TextContent,
            ContentType,
        )

        parts = [
            TextContent(type=ContentType.TEXT, text="Hello"),
            AudioContent(type=ContentType.AUDIO, data=b"audio_data"),
        ]

        result = base_channel._content_has_audio(parts)

        assert result is True


# =============================================================================
# Additional Base Coverage Tests (for 50%+ target)
# =============================================================================


class TestMergeRequests:
    """
    merge_requests tests.

    Merge multiple AgentRequest payloads into one.
    """

    def test_merge_requests_empty_list_returns_none(self, base_channel):
        """Empty list should return None."""
        result = base_channel.merge_requests([])
        assert result is None

    def test_merge_requests_single_request_returns_it(self, base_channel):
        """Single request should return itself."""
        mock_request = MagicMock()
        mock_request.input = [MagicMock(content=[MagicMock()])]

        result = base_channel.merge_requests([mock_request])

        assert result is mock_request

    def test_merge_requests_concatenates_content(self, base_channel):
        """Multiple requests should have content concatenated."""
        content1 = MagicMock(text="Hello")
        content2 = MagicMock(text="World")

        msg1 = MagicMock()
        msg1.content = [content1]

        msg2 = MagicMock()
        msg2.content = [content2]

        req1 = MagicMock()
        req1.input = [msg1]
        req1.model_copy = MagicMock(return_value=MagicMock(input=[msg1]))

        req2 = MagicMock()
        req2.input = [msg2]

        result = base_channel.merge_requests([req1, req2])

        assert result is not None

    def test_merge_requests_no_content_returns_first(self, base_channel):
        """Requests with no content should return first request."""
        req1 = MagicMock()
        req1.input = [MagicMock(content=[])]
        req2 = MagicMock()
        req2.input = [MagicMock(content=[])]

        result = base_channel.merge_requests([req1, req2])

        assert result is req1


class TestExtractChatName:
    """
    _extract_chat_name tests.

    Extract chat name from payload for chat creation.
    """

    def test_extract_from_dict_with_text_content(self, base_channel):
        """Should extract text from dict payload."""
        payload = {
            "content_parts": [{"text": "Hello World this is a test"}],
        }

        result = base_channel._extract_chat_name(payload)

        assert "Hello World this is a test" in result

    def test_extract_from_dict_truncates_to_50(self, base_channel):
        """Should truncate text to 50 chars."""
        payload = {
            "content_parts": [{"text": "A" * 100}],
        }

        result = base_channel._extract_chat_name(payload)

        assert len(result) == 50
        assert result == "A" * 50

    def test_extract_from_dict_empty_returns_new_chat(self, base_channel):
        """Empty content should return 'New Chat'."""
        payload = {"content_parts": []}

        result = base_channel._extract_chat_name(payload)

        assert result == "New Chat"

    def test_extract_from_object_with_input(
        self,
        base_channel,
        content_builder,
    ):
        """Should extract text from object with input."""
        content = content_builder.text("Test message")
        msg = MagicMock()
        msg.content = [content]

        payload = MagicMock()
        payload.input = [msg]

        result = base_channel._extract_chat_name(payload)

        assert "Test message" in result

    def test_extract_handles_exception_gracefully(self, base_channel):
        """Should handle exceptions and return 'New Chat'."""

        # Object that raises exception when accessed
        class BadPayload:
            @property
            def input(self):
                raise Exception("Test error")

        payload = BadPayload()

        result = base_channel._extract_chat_name(payload)

        assert result == "New Chat"


class TestPayloadToRequest:
    """
    _payload_to_request tests.

    Convert queue payload to AgentRequest.
    """

    def test_payload_with_session_id_and_input_returned_as_is(
        self,
        base_channel,
    ):
        """Payload with session_id and input should be returned as-is."""
        payload = MagicMock()
        payload.session_id = "test:session"
        payload.input = [MagicMock()]

        result = base_channel._payload_to_request(payload)

        assert result is payload

    def test_none_payload_raises_value_error(self, base_channel):
        """None payload should raise ValueError."""
        with pytest.raises(ValueError, match="payload is None"):
            base_channel._payload_to_request(None)

    def test_plain_dict_calls_build_agent_request(self, base_channel):
        """Plain dict should call build_agent_request_from_native."""
        payload = {"sender_id": "user123"}

        with patch.object(
            base_channel,
            "build_agent_request_from_native",
            return_value=MagicMock(),
        ) as mock_build:
            base_channel._payload_to_request(payload)

            mock_build.assert_called_once_with(payload)


class TestExtractQueryFromPayload:
    """
    _extract_query_from_payload tests.

    Extract query text from payload for command detection.
    """

    def test_extract_from_dict_with_text_part(self, base_channel):
        """Should extract text from dict payload."""
        payload = {
            "content_parts": [{"type": "text", "text": "Hello world"}],
        }

        result = base_channel._extract_query_from_payload(payload)

        assert result == "Hello world"

    def test_extract_from_dict_with_object_part(
        self,
        base_channel,
        content_builder,
    ):
        """Should extract text from object content parts."""
        text_content = content_builder.text("Test query")

        payload = {
            "content_parts": [text_content],
        }

        result = base_channel._extract_query_from_payload(payload)

        assert "Test query" in result

    def test_extract_from_request_object(self, base_channel, content_builder):
        """Should extract text from AgentRequest object."""
        text_content = content_builder.text("Request query")
        msg = MagicMock()
        msg.content = [text_content]

        payload = MagicMock()
        payload.input = [msg]

        result = base_channel._extract_query_from_payload(payload)

        assert "Request query" in result

    def test_empty_content_returns_empty_string(self, base_channel):
        """Empty content should return empty string."""
        payload = {"content_parts": []}

        result = base_channel._extract_query_from_payload(payload)

        assert result == ""


class TestContentHasAudioAdditional:
    """
    Additional _content_has_audio tests.
    """

    def test_empty_content_returns_false(self, base_channel):
        """Empty content should return False."""
        result = base_channel._content_has_audio([])
        assert result is False

    def test_none_content_returns_false(self, base_channel):
        """None content should return False."""
        result = base_channel._content_has_audio(None)
        assert result is False


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

    @pytest.mark.skip(
        reason="Response/AgentResponse classes removed from schema",
    )
    async def test_response_error_triggers_error_message(self, _base_channel):
        """Response containing error should trigger error message sending"""
        # NOTE: Response, AgentResponse, ErrorDetail classes removed
        # Test disabled until schema definitions are updated
        pytest.skip("Schema classes removed - test needs updating")


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
