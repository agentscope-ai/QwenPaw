# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio

import pytest
from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    TextContent,
)

from copaw.app.channels.dingtalk.channel import DingTalkChannel


async def _dummy_process(_request):
    return None


class _TestDingTalkChannel(DingTalkChannel):
    async def _get_session_webhook_for_send(
        self,
        to_handle,
        meta,
    ):  # noqa: ANN001
        del to_handle
        del meta
        return getattr(self, "test_webhook", None)

    async def _send_via_session_webhook(  # noqa: ANN001
        self,
        session_webhook,
        body,
        bot_prefix="",
    ):
        del session_webhook
        del body
        del bot_prefix
        return bool(getattr(self, "test_send_ok", True))


def _build_channel() -> _TestDingTalkChannel:
    return _TestDingTalkChannel(
        process=_dummy_process,
        enabled=True,
        client_id="",
        client_secret="",
        bot_prefix="[BOT] ",
    )


@pytest.mark.asyncio
async def test_proactive_send_raises_when_no_session_webhook() -> None:
    ch = _build_channel()
    ch.test_webhook = None

    with pytest.raises(RuntimeError, match="no sessionWebhook found"):
        await ch.send_content_parts(
            "dingtalk:sw:missing",
            [TextContent(type=ContentType.TEXT, text="hello")],
            {"session_id": "missing", "user_id": "u1"},
        )


@pytest.mark.asyncio
async def test_proactive_send_raises_when_webhook_api_fails() -> None:
    ch = _build_channel()
    ch.test_webhook = "https://oapi.dingtalk.com/robot/sendBySession?session=x"
    ch.test_send_ok = False

    with pytest.raises(RuntimeError, match="text sendBySession failed"):
        await ch.send_content_parts(
            "dingtalk:sw:exists",
            [TextContent(type=ContentType.TEXT, text="hello")],
            {"session_id": "exists", "user_id": "u2"},
        )


@pytest.mark.asyncio
async def test_reply_context_without_webhook_does_not_raise() -> None:
    ch = _build_channel()
    ch.test_webhook = None

    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    await ch.send_content_parts(
        "dingtalk:sw:reply",
        [TextContent(type=ContentType.TEXT, text="hello")],
        {"reply_loop": loop, "reply_future": future},
    )
    out = await asyncio.wait_for(future, timeout=1.0)
    assert out == "hello"
