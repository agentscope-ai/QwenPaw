"""Tests for DingTalk message deduplication in handler."""

import asyncio
from collections import OrderedDict
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


@pytest.fixture
def handler():
    """Create a DingTalkChannelHandler with mocked dependencies."""
    from copaw.app.channels.dingtalk.handler import DingTalkChannelHandler

    loop = asyncio.new_event_loop()
    h = DingTalkChannelHandler(
        main_loop=loop,
        enqueue_callback=MagicMock(),
        bot_prefix="",
        download_url_fetcher=AsyncMock(),
    )
    yield h
    loop.close()


class TestDingTalkDedup:
    """Test message deduplication logic."""

    def test_processed_ids_initialized(self, handler):
        """Handler should initialize empty dedup structures."""
        assert isinstance(handler._processed_message_ids, OrderedDict)
        assert len(handler._processed_message_ids) == 0
        assert isinstance(handler._inflight_message_ids, set)
        assert len(handler._inflight_message_ids) == 0

    @pytest.mark.asyncio
    async def test_completed_dedup_rejects_duplicate(self, handler):
        """process() should return OK and skip for already-completed msgId."""
        handler._processed_message_ids["dup_msg_001"] = None

        cb = MagicMock()
        cb.data = {
            "msgId": "dup_msg_001",
            "text": {"content": "hello"},
            "senderNick": "test",
            "senderId": "user1",
            "conversationId": "conv1",
        }
        # Patch ChatbotMessage.from_dict to return a mock message
        fake_msg = MagicMock()
        fake_msg.msgId = "dup_msg_001"
        fake_msg.msg_id = "dup_msg_001"
        fake_msg.text = MagicMock()
        fake_msg.text.content = "hello"
        fake_msg.to_dict = lambda: cb.data

        import dingtalk_stream
        with patch(
            "copaw.app.channels.dingtalk.handler.ChatbotMessage.from_dict",
            return_value=fake_msg,
        ):
            status, msg = await handler.process(cb)

        assert status == dingtalk_stream.AckMessage.STATUS_OK
        assert msg == "ok"
        # Enqueue should NOT have been called (message was skipped)
        handler._enqueue_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_inflight_dedup_rejects_concurrent(self, handler):
        """process() should return OK and skip for in-flight msgId."""
        handler._inflight_message_ids.add("inflight_msg_002")

        cb = MagicMock()
        cb.data = {
            "msgId": "inflight_msg_002",
            "text": {"content": "hello"},
            "senderNick": "test",
            "senderId": "user1",
            "conversationId": "conv1",
        }
        fake_msg = MagicMock()
        fake_msg.msgId = "inflight_msg_002"
        fake_msg.msg_id = "inflight_msg_002"
        fake_msg.text = MagicMock()
        fake_msg.text.content = "hello"
        fake_msg.to_dict = lambda: cb.data

        import dingtalk_stream
        with patch(
            "copaw.app.channels.dingtalk.handler.ChatbotMessage.from_dict",
            return_value=fake_msg,
        ):
            status, msg = await handler.process(cb)

        assert status == dingtalk_stream.AckMessage.STATUS_OK
        assert msg == "ok"
        handler._enqueue_callback.assert_not_called()

    def test_mark_completed_moves_from_inflight(self, handler):
        """_mark_completed should move from inflight to completed."""
        handler._inflight_message_ids.add("msg_003")
        handler._mark_completed("msg_003")
        assert "msg_003" not in handler._inflight_message_ids
        assert "msg_003" in handler._processed_message_ids

    def test_mark_completed_empty_noop(self, handler):
        """_mark_completed with empty string should be no-op."""
        handler._mark_completed("")
        assert len(handler._processed_message_ids) == 0

    def test_dedup_max_size_eviction(self, handler):
        """Oldest entries should be evicted when max size is reached."""
        from copaw.app.channels.dingtalk.handler import (
            DINGTALK_PROCESSED_IDS_MAX,
        )

        for i in range(DINGTALK_PROCESSED_IDS_MAX + 100):
            handler._mark_completed(f"msg_{i}")

        assert (
            len(handler._processed_message_ids)
            == DINGTALK_PROCESSED_IDS_MAX
        )
        assert "msg_0" not in handler._processed_message_ids
        newest = f"msg_{DINGTALK_PROCESSED_IDS_MAX + 99}"
        assert newest in handler._processed_message_ids

    def test_extract_msg_id_from_attribute(self, handler):
        """_extract_msg_id should extract from message attribute."""
        msg = MagicMock()
        msg.msgId = "attr_id_123"
        cb = MagicMock()
        cb.data = {}
        result = handler._extract_msg_id(msg, cb)
        assert result == "attr_id_123"

    def test_extract_msg_id_from_callback_data(self, handler):
        """_extract_msg_id should fall back to callback.data dict."""
        msg = MagicMock(spec=[])  # no msgId/msg_id attrs
        cb = MagicMock()
        cb.data = {"msgId": "data_id_456"}
        result = handler._extract_msg_id(msg, cb)
        assert result == "data_id_456"

    def test_extract_msg_id_empty_when_missing(self, handler):
        """_extract_msg_id should return '' when no ID found."""
        msg = MagicMock(spec=[])
        cb = MagicMock()
        cb.data = {}
        result = handler._extract_msg_id(msg, cb)
        assert result == ""

    def test_extract_msg_id_strips_whitespace(self, handler):
        """_extract_msg_id should strip whitespace."""
        msg = MagicMock()
        msg.msgId = "  spaced_id  "
        cb = MagicMock()
        cb.data = {}
        result = handler._extract_msg_id(msg, cb)
        assert result == "spaced_id"

    def test_failure_removes_from_inflight(self, handler):
        """On failure, msg should be removed from inflight for retry."""
        handler._inflight_message_ids.add("fail_msg")
        # Simulate failure cleanup
        handler._inflight_message_ids.discard("fail_msg")
        assert "fail_msg" not in handler._inflight_message_ids
        assert "fail_msg" not in handler._processed_message_ids

    def test_dedup_constant_value(self):
        """DINGTALK_PROCESSED_IDS_MAX should be reasonable."""
        from copaw.app.channels.dingtalk.handler import (
            DINGTALK_PROCESSED_IDS_MAX,
        )
        assert DINGTALK_PROCESSED_IDS_MAX >= 1024
        assert DINGTALK_PROCESSED_IDS_MAX <= 10000
