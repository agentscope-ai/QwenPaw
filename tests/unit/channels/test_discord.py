# -*- coding: utf-8 -*-
"""Discord native routing, attachments and Gateway cleanup."""

import asyncio
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import eventually, send


class Author:
    def __init__(self, ident=42, bot=False):
        self.id, self.bot = ident, bot

    def __str__(self):
        return "Human"


class Channel:
    def __init__(self, ident=123, parent_id=None):
        self.id, self.parent_id, self.sent = ident, parent_id, []

    async def send(self, text=None, file=None):
        self.sent.append(
            {
                "text": text,
                "file": file.fp.read() if file else None,
                "filename": file.filename if file else None,
            },
        )
        return NS(id=len(self.sent))


class Thread(Channel):
    pass


class Attachment:
    id, filename, content_type = 9, "picture.png", "image/png"

    async def save(self, path):
        Path(path).write_bytes(b"png image")


class Client:
    def __init__(self, **kwargs):
        self.user, self.handlers, self.channels = Author(99, True), {}, {}
        self.closed = False

    def event(self, callback):
        self.handlers[callback.__name__] = callback
        return callback

    async def start(self, token, reconnect):
        self.token = token
        await self.handlers["on_ready"]()
        await asyncio.Event().wait()

    def get_channel(self, ident):
        return self.channels[ident]

    def get_user(self, ident):
        return NS(dm_channel=self.channels[123])

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed


@pytest.fixture
async def discord(tmp_path, monkeypatch):
    native = module("discord", "platform")
    monkeypatch.setattr(native.discord, "Client", Client)
    monkeypatch.setattr(native.discord, "Thread", Thread)
    monkeypatch.setattr(native.discord, "Attachment", Attachment)
    driver = module("discord").DiscordDriver()
    peer, identity = bind("discord", driver, tmp_path)
    await driver.start(
        dict(
            bot_token="test-token",
            workspace_dir=str(tmp_path),
            media_dir=str(tmp_path / "media"),
        ),
    )
    await eventually(lambda: driver._connected)
    yield driver, peer, identity, driver._platform._client, tmp_path
    await driver.stop()


async def receive(value, kind="dm", *, author=None, attachments=(), ident=1):
    _, peer, _, client, _ = value
    channel = Thread(456, 123) if kind == "thread" else Channel(123)
    client.channels[channel.id] = channel
    message = NS(
        id=ident,
        author=author or Author(),
        content="<@99> hello" if kind != "dm" else "hello",
        guild=(
            NS(id=888, get_member=lambda ident: None) if kind != "dm" else None
        ),
        channel=channel,
        mentions=[client.user] if kind != "dm" else [],
        role_mentions=[],
        mention_everyone=False,
        attachments=attachments,
    )
    await client.handlers["on_message"](message)
    return (peer.batches[-1]["events"][0] if peer.batches else None), channel


@pytest.mark.parametrize("kind", ["dm", "group", "thread"])
async def test_native_dm_group_and_thread_keep_exact_reply_channel(
    discord,
    kind,
):
    driver, peer, identity, client, _ = discord
    event, channel = await receive(discord, kind)
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert event["acl_sender_id"] == "42" and event["sender_id"] == "Human"
    assert event["conversation"]["type"] == ("dm" if kind == "dm" else "group")
    assert event["conversation"]["id"] == str(channel.id)
    assert event["conversation"]["thread_id"] == (
        "456" if kind == "thread" else None
    )
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    assert channel.sent == [
        {"text": "native answer", "file": None, "filename": None},
    ]
    if kind != "dm":
        assert event["metadata"]["bot_mentioned"] is True


async def test_own_message_and_other_bot_are_filtered(discord):
    _, peer, _, client, _ = discord
    await receive(discord, author=client.user)
    await receive(discord, author=Author(88, True), ident=2)
    assert not peer.batches
    await receive(discord, ident=3)
    assert len(peer.batches) == 1


async def test_attachment_is_downloaded_classified_and_sent_as_file(discord):
    _, peer, identity, _, root = discord
    event, channel = await receive(discord, attachments=[Attachment()])
    part = event["content_parts"][1]
    assert part["type"] == "image"
    assert Path(part["image_url"]).read_bytes() == b"png image"
    assert Path(part["image_url"]).is_relative_to(root)
    result = await send(
        peer,
        identity,
        event["response_handle"],
        parts=[{"type": "file", "file_url": Path(part["image_url"]).as_uri()}],
    )
    assert result["state"] == "acknowledged"
    assert channel.sent[0]["file"] == b"png image"
    assert channel.sent[0]["filename"] == "9_picture.png"


async def test_duplicate_callback_and_stop_gateway(discord):
    driver, peer, _, client, _ = discord
    await receive(discord)
    await receive(discord)
    assert len(peer.batches) == 1
    task = driver._platform._task
    await driver.stop()
    assert client.closed and task.done() and driver._platform is None
