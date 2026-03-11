# -*- coding: utf-8 -*-
# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    RunStatus,
    TextContent,
)

from copaw.app.channels.qq.channel import QQChannel


def _make_request() -> SimpleNamespace:
    return SimpleNamespace(
        input=None,
        user_id="user-1",
        session_id="qq:user-1",
        channel_meta={"message_id": "msg-1"},
    )


def _make_events() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type="commentary",
            text="好的，让我检查一下今天早上的定时任务执行情况",
        ),
        SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type="final",
            text="今天早上的 3 个定时任务都成功执行",
        ),
        SimpleNamespace(object="response", error=None),
    ]


def _make_channel(
    events: list[SimpleNamespace],
    *,
    stream_reply: bool,
) -> QQChannel:
    async def process(_request):
        for event in events:
            yield event

    channel = QQChannel(
        process=process,
        enabled=True,
        app_id="app-id",
        client_secret="secret",
        stream_reply=stream_reply,
    )
    channel._message_to_content_parts = lambda event: [
        TextContent(type=ContentType.TEXT, text=event.text),
    ]
    return channel


@pytest.mark.asyncio
async def test_qq_stream_reply_sends_messages_separately() -> None:
    sent: list[list[str]] = []
    channel = _make_channel(_make_events(), stream_reply=True)

    async def fake_send_content_parts(to_handle, parts, _meta=None):
        assert to_handle == "user-1"
        sent.append([getattr(part, "text", "") for part in parts])

    channel.send_content_parts = fake_send_content_parts

    await channel.consume_one(_make_request())

    assert sent == [
        ["好的，让我检查一下今天早上的定时任务执行情况"],
        ["今天早上的 3 个定时任务都成功执行"],
    ]


@pytest.mark.asyncio
async def test_qq_non_stream_reply_keeps_accumulated_single_message() -> None:
    sent: list[list[str]] = []
    channel = _make_channel(_make_events(), stream_reply=False)

    async def fake_send_content_parts(to_handle, parts, _meta=None):
        assert to_handle == "user-1"
        sent.append([getattr(part, "text", "") for part in parts])

    channel.send_content_parts = fake_send_content_parts

    await channel.consume_one(_make_request())

    assert sent == [
        [
            "好的，让我检查一下今天早上的定时任务执行情况",
            "今天早上的 3 个定时任务都成功执行",
        ],
    ]
