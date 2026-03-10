# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument

from types import MethodType

import pytest

from copaw.app.channels.discord_.channel import (
    DISCORD_SEND_CHUNK_SIZE,
    DiscordChannel,
)


class _FakeClient:
    def is_ready(self) -> bool:
        return True


class _FakeTarget:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, text: str) -> None:
        self.messages.append(text)


def _make_channel(target: _FakeTarget) -> DiscordChannel:
    channel = object.__new__(DiscordChannel)
    channel.enabled = True
    channel._client = _FakeClient()

    async def _resolve_target(self, to_handle, meta):
        return target

    channel._resolve_target = MethodType(_resolve_target, channel)
    return channel


def test_discord_chunk_text_splits_long_message() -> None:
    channel = object.__new__(DiscordChannel)
    text = "a" * (DISCORD_SEND_CHUNK_SIZE * 2 + 123)

    chunks = DiscordChannel._chunk_text(channel, text)

    assert [len(chunk) for chunk in chunks] == [
        DISCORD_SEND_CHUNK_SIZE,
        DISCORD_SEND_CHUNK_SIZE,
        123,
    ]
    assert "".join(chunks) == text


@pytest.mark.asyncio
async def test_discord_send_sends_multiple_chunks() -> None:
    target = _FakeTarget()
    channel = _make_channel(target)
    text = "a" * (DISCORD_SEND_CHUNK_SIZE * 2 + 123)

    await DiscordChannel.send(channel, "discord:ch:123", text, {})

    assert [len(message) for message in target.messages] == [
        DISCORD_SEND_CHUNK_SIZE,
        DISCORD_SEND_CHUNK_SIZE,
        123,
    ]
    assert "".join(target.messages) == text
