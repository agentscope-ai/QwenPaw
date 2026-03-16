# -*- coding: utf-8 -*-

from __future__ import annotations

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    ImageContent,
    TextContent,
)

from copaw.app.channels.qq.channel import QQChannel


async def _dummy_process(_request):  # pragma: no cover
    return  # noqa: B901
    yield  # pylint: disable=unreachable


def _make_channel() -> QQChannel:
    return QQChannel(
        process=_dummy_process,
        enabled=False,
        app_id="app-id",
        client_secret="secret",
    )


def test_build_agent_request_from_user_content_drops_empty_text():
    channel = _make_channel()

    request = channel.build_agent_request_from_user_content(
        channel_id="qq",
        sender_id="user-1",
        session_id="qq:user-1",
        content_parts=[
            TextContent(type=ContentType.TEXT, text=""),
            ImageContent(
                type=ContentType.IMAGE,
                image_url="/tmp/demo.png",
            ),
        ],
    )

    assert [part.type for part in request.input[0].content] == [
        ContentType.IMAGE,
    ]


def test_build_agent_request_from_native_keeps_media():
    channel = _make_channel()
    channel._parse_qq_attachments = (  # pylint: disable=protected-access
        lambda _attachments: [
            ImageContent(
                type=ContentType.IMAGE,
                image_url="/tmp/demo.png",
            ),
        ]
    )

    request = channel.build_agent_request_from_native(
        {
            "channel_id": "qq",
            "sender_id": "user-1",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text=""),
            ],
            "meta": {
                "attachments": [
                    {
                        "filename": "demo.png",
                        "url": "https://example.com/demo.png",
                        "content_type": "image/png",
                    },
                ],
            },
        },
    )

    assert [part.type for part in request.input[0].content] == [
        ContentType.IMAGE,
    ]


async def test_consume_one_merges_image_then_text():
    captured: list[list[str]] = []

    async def fake_process(request):  # pragma: no cover
        captured.append(
            [
                getattr(part, "text", None)
                if part.type == ContentType.TEXT
                else getattr(part, "image_url", None)
                for part in request.input[0].content
            ],
        )
        return  # noqa: B901
        yield  # pylint: disable=unreachable

    channel = QQChannel(
        process=fake_process,
        enabled=False,
        app_id="app-id",
        client_secret="secret",
    )

    image_request = channel.build_agent_request_from_user_content(
        channel_id="qq",
        sender_id="user-1",
        session_id="qq:user-1",
        content_parts=[
            TextContent(type=ContentType.TEXT, text=""),
            ImageContent(
                type=ContentType.IMAGE,
                image_url="/tmp/demo.png",
            ),
        ],
    )
    text_request = channel.build_agent_request_from_user_content(
        channel_id="qq",
        sender_id="user-1",
        session_id="qq:user-1",
        content_parts=[
            TextContent(type=ContentType.TEXT, text="后续文字"),
        ],
    )

    await channel.consume_one(image_request)
    assert not captured

    await channel.consume_one(text_request)

    assert captured == [["/tmp/demo.png", "后续文字"]]
