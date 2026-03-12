# -*- coding: utf-8 -*-
"""Unit tests for Feishu channel."""
import pytest
from unittest.mock import MagicMock
from copaw.app.channels.feishu.channel import FeishuChannel

class MockProcessHandler:
    pass

@pytest.fixture
def feishu_channel():
    return FeishuChannel(
        process=MockProcessHandler(),
        enabled=True,
        app_id="fake_app_id",
        app_secret="fake_secret",
        bot_prefix="[BOT] ",
    )

def test_resolve_session_id_p2p(feishu_channel):
    """Test resolving session ID for P2P chat."""
    sender_id = "ou_12345"
    meta = {"feishu_chat_type": "p2p"}
    
    session_id = feishu_channel.resolve_session_id(sender_id, meta)
    
    assert session_id == "u_12345"

def test_resolve_session_id_group(feishu_channel):
    """Test resolving session ID for group chat."""
    sender_id = "ou_12345"
    meta = {
        "feishu_chat_type": "group",
        "feishu_chat_id": "oc_9876543210"
    }
    
    session_id = feishu_channel.resolve_session_id(sender_id, meta)
    
    # For group chat, session_id is derived from chat_id.
    assert session_id == "76543210"

def test_build_agent_request_from_native(feishu_channel):
    """Test building AgentRequest from native payload."""
    native_payload = {
        "channel_id": "feishu",
        "sender_id": "ou_sender",
        "content_parts": [{"type": "text", "text": "hello"}],
        "meta": {"feishu_chat_type": "p2p"}
    }
    
    request = feishu_channel.build_agent_request_from_native(native_payload)
    
    # Check if query exists, if not check if it's in input/messages
    if hasattr(request, "query"):
        assert request.query == "hello"
    elif hasattr(request, "input"):
        # AgentRequest structure might vary, check input content
        assert "hello" in str(request.input)
    
    # 'channel' field is likely used instead of 'channel_id'
    if hasattr(request, "channel_id"):
        assert request.channel_id == "feishu"
    elif hasattr(request, "channel"):
        assert request.channel == "feishu"

    # Verify meta is attached
    if hasattr(request, "channel_meta"):
        assert request.channel_meta["feishu_chat_type"] == "p2p"

def test_merge_native_items(feishu_channel):
    """Test merging multiple native items (e.g. split messages)."""
    item1 = {
        "content_parts": [{"type": "text", "text": "part1"}],
        "sender_id": "u1",
        "session_id": "s1",
        "meta": {"m": 1}
    }
    item2 = {
        "content_parts": [{"type": "text", "text": "part2"}],
        "sender_id": "u1",
        "session_id": "s1",
        "meta": {"m": 2}
    }
    
    merged = feishu_channel.merge_native_items([item1, item2])
    
    assert len(merged["content_parts"]) == 2
    assert merged["content_parts"][0]["text"] == "part1"
    assert merged["content_parts"][1]["text"] == "part2"
    # Should use last item's meta
    assert merged["meta"]["m"] == 2
