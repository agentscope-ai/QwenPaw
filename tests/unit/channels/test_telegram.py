# -*- coding: utf-8 -*-
"""Telegram native Update parsing, topic routing and final stream delivery."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from telegram import Update
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import send


class Bot:
    id, username = 99, "testbot"

    def __init__(self):
        self.calls = []

    async def set_my_commands(self, commands):
        self.commands = commands

    async def send_message(self, **kwargs):
        self.calls.append(("message", kwargs))
        return NS(message_id=len(self.calls))

    async def send_document(self, **kwargs):
        document = kwargs["document"]
        self.calls.append(
            (
                "document",
                {
                    **kwargs,
                    "document": (
                        document.read()
                        if hasattr(document, "read")
                        else document
                    ),
                },
            ),
        )
        return NS(message_id=len(self.calls))

    async def edit_message_text(self, **kwargs):
        self.calls.append(("edit", kwargs))
        return True


class Application:
    """External PTB lifecycle boundary; plugin polling remains real."""

    def __init__(self):
        self.bot, self.running, self.closed = Bot(), False, False
        self.updater = NS(
            running=False,
            start_polling=self.poll,
            stop=self.stop_poll,
        )
        self.handlers = []

    @classmethod
    def builder(cls):
        return Builder()

    def add_handler(self, handler):
        self.handlers.append(handler)

    async def initialize(self):
        pass

    async def poll(self, **kwargs):
        self.updater.running = True
        self.poll_options = kwargs

    async def stop_poll(self):
        self.updater.running = False

    async def start(self):
        self.running = True

    async def stop(self):
        self.running = False

    async def shutdown(self):
        self.closed = True


class Builder:
    def __getattr__(self, name):
        return lambda *args, **kwargs: self

    def build(self):
        return Application()


@pytest.fixture
async def telegram(tmp_path, monkeypatch):
    native = module("telegram", "platform")
    monkeypatch.setattr(native, "Application", Application)
    driver = module("telegram").TelegramDriver()
    peer, identity = bind("telegram", driver, tmp_path)
    await driver.start(
        dict(
            bot_token="123:test",
            workspace_dir=str(tmp_path),
            media_dir=str(tmp_path / "media"),
            streaming_enabled=True,
        ),
    )
    yield driver, peer, identity, driver._platform._application
    await driver.stop()


def update(chat_type="private", topic=None, ident=1):
    message = {
        "message_id": ident,
        "date": 1000000000,
        "from": {
            "id": 42,
            "is_bot": False,
            "first_name": "Human",
            "username": "human",
        },
        "chat": {
            "id": -100 if chat_type != "private" else 42,
            "type": chat_type,
        },
        "text": "hello",
    }
    if topic:
        message.update(message_thread_id=topic, is_topic_message=True)
    return Update.de_json({"update_id": ident, "message": message}, None)


async def receive(value, **kwargs):
    driver, peer, _, app = value
    await app.handlers[0].callback(update(**kwargs), NS(bot=app.bot))
    return peer.batches[-1]["events"][0]


@pytest.mark.parametrize(
    "kind,topic",
    [("private", None), ("supergroup", None), ("supergroup", 77)],
)
async def test_native_update_keeps_chat_and_topic_reply_target(
    telegram,
    kind,
    topic,
):
    driver, peer, identity, app = telegram
    event = await receive(telegram, chat_type=kind, topic=topic)
    chat = "42" if kind == "private" else "-100"
    assert event["conversation"] == {
        "id": chat,
        "type": "dm" if kind == "private" else "group",
        "thread_id": str(topic) if topic else None,
    }
    assert event["acl_sender_id"] == "42"
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    kwargs = app.bot.calls[-1][1]
    assert kwargs["chat_id"] == int(chat) and kwargs["text"] == "native answer"
    assert kwargs.get("message_thread_id") == topic


async def test_attachment_reads_local_file_and_uses_same_topic(
    telegram,
    tmp_path,
):
    _, peer, identity, app = telegram
    event = await receive(telegram, chat_type="supergroup", topic=77)
    path = tmp_path / "note.txt"
    path.write_bytes(b"native attachment")
    result = await send(
        peer,
        identity,
        event["response_handle"],
        parts=[
            {
                "type": "file",
                "file_url": path.as_uri(),
                "filename": "note.txt",
            },
        ],
    )
    assert result["state"] == "acknowledged"
    kind, kwargs = app.bot.calls[-1]
    assert kind == "document" and kwargs["document"] == b"native attachment"
    assert kwargs["chat_id"] == -100 and kwargs["message_thread_id"] == 77


async def test_stream_end_edits_placeholder_to_complete_text(telegram):
    _, peer, identity, app = telegram
    handle = (await receive(telegram))["response_handle"]
    assert (
        await send(
            peer,
            identity,
            handle,
            delivery="stream",
            operation="stream.start",
            stream_type="message",
        )
    )["state"] == "acknowledged"
    result = await send(
        peer,
        identity,
        handle,
        delivery="final",
        operation="stream.end",
        target_delivery_id="stream",
        stream_type="message",
        sequence=1,
        accumulated_text="complete response",
    )
    assert result["state"] == "acknowledged"
    assert app.bot.calls[-1] == (
        "edit",
        {
            "chat_id": 42,
            "message_id": 1,
            "text": "complete response",
            "parse_mode": "HTML",
        },
    )


async def test_duplicate_update_is_not_repeated_and_stop_closes_polling(
    telegram,
):
    driver, peer, _, app = telegram
    await receive(telegram)
    await receive(telegram)
    assert len(peer.batches) == 1
    assert app.poll_options["allowed_updates"] == [
        "message",
        "edited_message",
        "callback_query",
    ]
    await driver.stop()
    assert app.closed and not app.running and not app.updater.running
    assert driver._platform is None
