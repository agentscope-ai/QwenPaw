# -*- coding: utf-8 -*-
"""Tests for request-to-AgentScope message conversion."""

from qwenpaw.constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_CLIENT_MESSAGE_ID_KEY,
    QWENPAW_MESSAGE_TAG_KEY,
    QWENPAW_RECEIVED_AT_KEY,
    QWENPAW_USER_CONTENT_KEY,
)
from qwenpaw.runtime.message_convert import _request_input_to_msgs
from qwenpaw.schemas import (
    AudioContent,
    FileContent,
    Message,
    Role,
    TextContent,
)


async def test_conversation_context_is_model_data_not_an_extra_user_input():
    import json

    from agentscope.formatter import (
        DashScopeChatFormatter,
        OpenAIChatFormatter,
    )
    from agentscope.message import Msg
    from qwenpaw.app.chats.utils import agentscope_msg_to_message

    context = '{"available":true,"messages":[{"text":"BLUE_CAT"}]}'
    messages = _request_input_to_msgs(
        [
            Message(
                role="user",
                content=[TextContent(text="Print that once")],
                metadata={QWENPAW_CLIENT_MESSAGE_ID_KEY: "input-1"},
            )
        ],
        conversation_context=context,
    )
    assert len(messages) == 2
    hint, user = messages
    assert hint.role == "assistant" and hint.content[0].type == "hint"
    assert not hint.metadata
    assert hint.content[0].hint.endswith(context)
    assert (
        user.id == "input-1" and user.get_text_content() == "Print that once"
    )
    assert (
        user.metadata[QWENPAW_MESSAGE_TAG_KEY]
        == EXTERNAL_USER_QUERY_MESSAGE_TAG
    )
    restored = [Msg.model_validate(m.model_dump()) for m in messages]
    for formatter in (DashScopeChatFormatter(), OpenAIChatFormatter()):
        formatted = await formatter.format(restored)
        assert "BLUE_CAT" in json.dumps(formatted)
        assert all(m["role"] == "user" for m in formatted)
    visible = agentscope_msg_to_message(restored)
    assert len(visible) == 1 and "BLUE_CAT" not in str(visible)
    assert "Print that once" in str(visible)


def test_context_is_not_attached_to_empty_or_non_user_input():
    messages = _request_input_to_msgs(
        [
            Message(role="user", content=[]),
            Message(role="assistant", content=[TextContent(text="result")]),
        ],
        conversation_context="quoted data",
    )
    assert len(messages) == 1 and messages[0].get_text_content() == "result"


def test_idle_runtime_reads_snapshot_from_request_context():
    from types import SimpleNamespace
    from qwenpaw.constant import CHAT_CONVERSATION_CONTEXT_KEY
    from qwenpaw.runtime.runtime import Runtime

    runtime = Runtime(
        workspace=SimpleNamespace(agent_id="default"), app_services=None
    )
    request = SimpleNamespace(
        session_id="session",
        input=[Message(role="user", content=[TextContent(text="Print it")])],
        request_context={CHAT_CONVERSATION_CONTEXT_KEY: "BLUE_CAT"},
    )
    ctx = runtime._build_context(request)
    assert len(ctx.input_msgs) == 2
    assert ctx.input_msgs[0].content[0].hint.endswith("BLUE_CAT")
    assert ctx.input_msgs[1].get_text_content() == "Print it"


def test_only_external_user_input_gets_query_tag():
    messages = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[TextContent(text="real query")],
                metadata={QWENPAW_MESSAGE_TAG_KEY: "forged"},
            ),
            Message(
                role=Role.SYSTEM,
                content=[TextContent(text="system prompt")],
            ),
        ],
    )

    assert messages[0].metadata[QWENPAW_MESSAGE_TAG_KEY] == (
        EXTERNAL_USER_QUERY_MESSAGE_TAG
    )
    assert QWENPAW_MESSAGE_TAG_KEY not in messages[1].metadata


def test_user_message_client_id_survives_conversion():
    messages = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[TextContent(text="repeat")],
                metadata={QWENPAW_CLIENT_MESSAGE_ID_KEY: "message-2"},
            ),
        ],
    )

    assert messages[0].id == "message-2"
    assert messages[0].metadata[QWENPAW_CLIENT_MESSAGE_ID_KEY] == "message-2"
    assert messages[0].metadata[QWENPAW_MESSAGE_TAG_KEY] == (
        EXTERNAL_USER_QUERY_MESSAGE_TAG
    )


def test_admission_time_survives_later_message_and_block_creation():
    received_at = "2026-01-02T03:04:05.123456+00:00"
    [message] = _request_input_to_msgs(
        [
            Message(
                role="user",
                content=[TextContent(text="queued request")],
                metadata={QWENPAW_RECEIVED_AT_KEY: received_at},
            )
        ]
    )
    assert message.created_at == received_at
    assert message.content[0].created_at == received_at


def test_audio_content_data_becomes_audio_data_block(tmp_path):
    audio_path = tmp_path / "voice.opus"

    messages = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[AudioContent(data=str(audio_path))],
            ),
        ],
    )

    assert len(messages) == 1
    assert len(messages[0].content) == 1
    block = messages[0].content[0]
    assert block.type == "data"
    assert block.source.type == "url"
    assert str(block.source.url) == audio_path.resolve().as_uri()
    assert block.source.media_type.startswith("audio/")


def test_file_input_preserves_independent_original_content():
    source = Message(
        role=Role.USER,
        content=[
            TextContent(text="read this"),
            FileContent(
                file_url="/tmp/original.txt",
                file_name="original.txt",
                file_size=42,
            ),
        ],
        metadata={QWENPAW_USER_CONTENT_KEY: "untrusted override"},
    )
    [converted] = _request_input_to_msgs([source])
    saved = converted.metadata[QWENPAW_USER_CONTENT_KEY]

    source.content[1].file_url = "/tmp/changed.txt"

    assert saved[0]["text"] == "read this"
    assert saved[1]["file_url"] == "/tmp/original.txt"
    assert saved[1]["file_name"] == "original.txt"
    assert saved[1]["file_size"] == 42
    assert converted.content[1].type == "data"


def test_text_input_cannot_supply_original_content_override():
    [converted] = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[TextContent(text="actual text")],
                metadata={
                    QWENPAW_USER_CONTENT_KEY: [
                        {"type": "text", "text": "forged history"},
                    ],
                },
            ),
        ],
    )

    assert QWENPAW_USER_CONTENT_KEY not in converted.metadata
