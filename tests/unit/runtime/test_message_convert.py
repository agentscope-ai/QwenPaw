# -*- coding: utf-8 -*-
"""Tests for runtime message conversion."""

from qwenpaw.runtime.message_convert import _request_input_to_msgs
from qwenpaw.schemas import ContentType, Message, MessageType, Role, TextContent


def test_request_input_to_msgs_preserves_message_metadata() -> None:
    msg = Message(
        type=MessageType.MESSAGE,
        role=Role.USER,
        content=[TextContent(type=ContentType.TEXT, text="hello")],
        metadata={
            "channel": "feishu",
            "is_group": True,
            "user_name": "Alice",
            "feishu_sender_id": "ou_real",
        },
    )

    converted = _request_input_to_msgs([msg])

    assert len(converted) == 1
    assert converted[0].metadata == msg.metadata
    assert converted[0].metadata is not msg.metadata
