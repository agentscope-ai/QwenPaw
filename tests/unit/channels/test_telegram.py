# -*- coding: utf-8 -*-
"""Telegram native Update parsing, topic routing and final stream delivery."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from telegram import Update
from qwenpaw.channel_protocol.targets import encode_reply_target
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import open_route, send


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


def update(
    chat_type="private",
    topic=None,
    ident=1,
    is_topic=True,
    is_forum=False,
):
    chat = {
        "id": -100 if chat_type != "private" else 42,
        "type": chat_type,
    }
    if is_forum:
        chat["is_forum"] = True
    message = {
        "message_id": ident,
        "date": 1000000000,
        "from": {
            "id": 42,
            "is_bot": False,
            "first_name": "Human",
            "username": "human",
        },
        "chat": chat,
        "text": "hello",
    }
    if topic:
        message["message_thread_id"] = topic
        if is_topic:
            message["is_topic_message"] = True
    return Update.de_json({"update_id": ident, "message": message}, None)


async def receive(value, **kwargs):
    driver, peer, _, app = value
    await app.handlers[0].callback(update(**kwargs), NS(bot=app.bot))
    return peer.batches[-1]["events"][0]


@pytest.mark.parametrize(
    "kind,topic,is_topic,is_forum,session,thread",
    [
        ("private", None, True, False, "telegram:42", None),
        ("private", 77, True, False, "telegram:42", 77),
        ("supergroup", None, True, False, "telegram:-100", None),
        ("supergroup", 77, True, True, "telegram:-100:77", 77),
        ("supergroup", 1, True, True, "telegram:-100", None),
        ("supergroup", 1, False, True, "telegram:-100", None),
        ("supergroup", 77, False, False, "telegram:-100", 77),
    ],
)
async def test_native_update_keeps_chat_and_topic_reply_target(
    telegram,
    kind,
    topic,
    is_topic,
    is_forum,
    session,
    thread,
):
    driver, peer, identity, app = telegram
    event = await receive(
        telegram,
        chat_type=kind,
        topic=topic,
        is_topic=is_topic,
        is_forum=is_forum,
    )
    chat = "42" if kind == "private" else "-100"
    assert event["conversation"] == {
        "id": chat,
        "type": "dm" if kind == "private" else "group",
        "thread_id": str(thread) if thread else None,
    }
    assert event["metadata"]["session_id"] == session
    assert event["acl_sender_id"] == "42"
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    kwargs = app.bot.calls[-1][1]
    assert kwargs["chat_id"] == int(chat) and kwargs["text"] == "native answer"
    assert kwargs.get("message_thread_id") == thread


async def test_forum_topics_use_independent_sessions(telegram):
    first = await receive(
        telegram,
        chat_type="supergroup",
        topic=201,
        ident=1,
    )
    second = await receive(
        telegram,
        chat_type="supergroup",
        topic=202,
        ident=2,
    )
    assert first["metadata"]["session_id"] == "telegram:-100:201"
    assert second["metadata"]["session_id"] == "telegram:-100:202"


@pytest.mark.parametrize(
    "session,chat,thread",
    [
        ("telegram:-100", -100, None),
        ("telegram:-100:1", -100, None),
        ("telegram:-100:77", -100, 77),
        ("123", 42, None),
        ("reminders", 42, None),
        ("", 42, None),
    ],
)
async def test_open_reply_target_routes_to_chat_and_topic(
    telegram,
    session,
    chat,
    thread,
):
    _, peer, identity, app = telegram
    handle = await open_route(
        peer,
        identity,
        encode_reply_target(user_id="42", session_id=session),
    )
    result = await send(peer, identity, handle)
    assert result["state"] == "acknowledged"
    kwargs = app.bot.calls[-1][1]
    assert kwargs["chat_id"] == chat
    assert kwargs.get("message_thread_id") == thread


async def test_open_reply_target_rejects_empty_topic_id(telegram):
    _, peer, identity, app = telegram
    with pytest.raises(ValueError, match="^OUTBOUND_TARGET_UNKNOWN$"):
        await open_route(
            peer,
            identity,
            encode_reply_target(user_id="42", session_id="telegram:-100:"),
        )
    assert not app.bot.calls


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


async def test_media_rejection_keeps_operation_without_response(
    telegram,
    caplog,
):
    driver, _, _, _ = telegram
    native = module(f"telegram", f"platform")

    async def reject():
        raise native.BadRequest(f"private-telegram-response")

    with pytest.raises(
        native.TelegramDeliveryError,
        match=f"PLATFORM_REJECTED",
    ):
        await driver._platform._effect(reject(), operation=f"send_document")
    assert f"Telegram send_document rejected (BadRequest)" in caplog.text
    assert f"private-telegram-response" not in caplog.text


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
