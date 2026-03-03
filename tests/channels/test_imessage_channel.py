# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, AsyncIterator

from copaw.app.channels.imessage.channel import IMessageChannel


async def _dummy_process(_: Any) -> AsyncIterator[Any]:
    for event in ():
        yield event


def _build_channel(bot_prefix: str) -> IMessageChannel:
    return IMessageChannel(
        process=_dummy_process,
        enabled=True,
        db_path="~/Library/Messages/chat.db",
        poll_sec=1.0,
        bot_prefix=bot_prefix,
    )


def test_should_skip_empty_message() -> None:
    channel = _build_channel("@bot")
    assert channel.should_skip_incoming_text("")
    assert channel.should_skip_incoming_text(None)


def test_should_skip_message_without_prefix_when_prefix_configured() -> None:
    channel = _build_channel("@bot")
    assert channel.should_skip_incoming_text("hello")


def test_should_accept_message_with_prefix_when_prefix_configured() -> None:
    channel = _build_channel("@bot")
    assert not channel.should_skip_incoming_text("@bot hello")


def test_should_accept_any_non_empty_message_when_prefix_empty() -> None:
    channel = _build_channel("")
    assert not channel.should_skip_incoming_text("hello")
