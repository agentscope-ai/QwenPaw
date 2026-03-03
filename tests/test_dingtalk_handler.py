# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import dingtalk_stream
import pytest

from copaw.app.channels.dingtalk.handler import (
    DINGTALK_PROCESSED_IDS_MAX,
    DingTalkChannelHandler,
)


@pytest.fixture
def handler() -> DingTalkChannelHandler:
    loop = asyncio.new_event_loop()
    h = DingTalkChannelHandler(
        main_loop=loop,
        enqueue_callback=None,
        bot_prefix="",
        download_url_fetcher=AsyncMock(),
    )
    yield h
    loop.close()


def _callback(
    data: dict | None = None,
    header_message_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        data=data or {},
        headers=SimpleNamespace(message_id=header_message_id),
    )


def test_extract_msg_id_prefers_message_id(handler: DingTalkChannelHandler) -> None:
    incoming = SimpleNamespace(message_id="mid-001")
    cb = _callback(data={"msgId": "msg-001"}, header_message_id="hdr-001")

    assert handler._extract_msg_id(incoming, cb) == "mid-001"


def test_extract_msg_id_from_callback_data(handler: DingTalkChannelHandler) -> None:
    incoming = SimpleNamespace()
    cb = _callback(data={"msgId": "msg-002"}, header_message_id="hdr-002")

    assert handler._extract_msg_id(incoming, cb) == "msg-002"


def test_extract_msg_id_from_headers_fallback(
    handler: DingTalkChannelHandler,
) -> None:
    incoming = SimpleNamespace()
    cb = _callback(data={}, header_message_id="hdr-003")

    assert handler._extract_msg_id(incoming, cb) == "hdr-003"


def test_mark_completed_moves_from_inflight(
    handler: DingTalkChannelHandler,
) -> None:
    handler._inflight_message_ids.add("msg-100")

    handler._mark_completed("msg-100")

    assert "msg-100" not in handler._inflight_message_ids
    assert "msg-100" in handler._processed_message_ids


def test_mark_completed_evicts_oldest(handler: DingTalkChannelHandler) -> None:
    for i in range(DINGTALK_PROCESSED_IDS_MAX + 1):
        handler._mark_completed(f"msg-{i}")

    assert len(handler._processed_message_ids) == DINGTALK_PROCESSED_IDS_MAX
    assert "msg-0" not in handler._processed_message_ids
    assert (
        f"msg-{DINGTALK_PROCESSED_IDS_MAX}" in handler._processed_message_ids
    )


@pytest.mark.asyncio
async def test_process_skips_already_processed(
    handler: DingTalkChannelHandler,
) -> None:
    handler._processed_message_ids["dup-001"] = None
    cb = _callback(data={"msgId": "dup-001"})
    incoming = SimpleNamespace(message_id="dup-001")

    with patch(
        "copaw.app.channels.dingtalk.handler.ChatbotMessage.from_dict",
        return_value=incoming,
    ):
        status, message = await handler.process(cb)

    assert status == dingtalk_stream.AckMessage.STATUS_OK
    assert message == "ok"


@pytest.mark.asyncio
async def test_process_skips_inflight_duplicate(
    handler: DingTalkChannelHandler,
) -> None:
    handler._inflight_message_ids.add("dup-002")
    cb = _callback(data={"msgId": "dup-002"})
    incoming = SimpleNamespace(message_id="dup-002")

    with patch(
        "copaw.app.channels.dingtalk.handler.ChatbotMessage.from_dict",
        return_value=incoming,
    ):
        status, message = await handler.process(cb)

    assert status == dingtalk_stream.AckMessage.STATUS_OK
    assert message == "ok"


@pytest.mark.asyncio
async def test_process_failure_clears_inflight(
    handler: DingTalkChannelHandler,
) -> None:
    class BrokenMessage:
        message_id = "err-001"
        text = None

        def to_dict(self) -> dict:
            raise RuntimeError("boom")

    cb = _callback(data={"msgId": "err-001"})

    with patch(
        "copaw.app.channels.dingtalk.handler.ChatbotMessage.from_dict",
        return_value=BrokenMessage(),
    ):
        status, message = await handler.process(cb)

    assert status == dingtalk_stream.AckMessage.STATUS_SYSTEM_EXCEPTION
    assert message == "error"
    assert "err-001" not in handler._inflight_message_ids
