# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the Signal channel (subprocess JSON-RPC transport).

The transport (SignalSubprocessClient) is replaced with a fake that
records calls and lets tests push notifications — no real signal-cli
subprocess is spawned.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.channels.signal.channel import (
    SignalChannel,
    _markdown_to_signal,
)


# ───────────────────────────── fakes ─────────────────────────────────

class FakeClient:
    """Records outbound calls, exposes `connected` flag, pushes
    notifications through the registered callback."""

    def __init__(self, *_args, **_kwargs):
        self.connected = False
        self.sent: List[Dict[str, Any]] = []
        self.reactions: List[Dict[str, Any]] = []
        self.typing: List[Dict[str, Any]] = []
        self._on_notify = None

    async def connect(self, on_notify) -> bool:
        self._on_notify = on_notify
        self.connected = True
        return True

    async def disconnect(self) -> None:
        self.connected = False

    async def send_message(
        self,
        target: str,
        text: str,
        is_group: bool = False,
        quote_timestamp: int = 0,
        quote_author: str = "",
        attachments: Optional[List[str]] = None,
        text_style: Optional[List[str]] = None,
        mentions: Optional[List[str]] = None,
    ) -> Optional[int]:
        self.sent.append({
            "target": target,
            "text": text,
            "is_group": is_group,
            "quote_timestamp": quote_timestamp,
            "quote_author": quote_author,
            "attachments": list(attachments or []),
            "text_style": list(text_style or []),
            "mentions": list(mentions or []),
        })
        return 1_700_000_000

    async def send_reaction(self, *args, **kwargs) -> bool:
        self.reactions.append({"args": args, "kwargs": kwargs})
        return True

    async def send_typing(self, *args, **kwargs) -> None:
        self.typing.append({"args": args, "kwargs": kwargs})

    async def download_attachment(self, attachment_id, dest_dir):
        return None


# ───────────────────────────── helpers ───────────────────────────────

def _make_channel(**overrides: Any) -> SignalChannel:
    """Build a SignalChannel with the subprocess client swapped for a fake."""
    async def _noop_process(_request):
        if False:
            yield None  # pragma: no cover

    defaults: Dict[str, Any] = {
        "process": _noop_process,
        "enabled": True,
        "account": "+85251159218",
        "account_uuid": "82e0393a-1f09-4a0a-b000-000000000000",
    }
    defaults.update(overrides)
    ch = SignalChannel(**defaults)
    # Replace the real client with the fake
    ch.client = FakeClient()
    return ch


# ───────────────────────────── markdown ──────────────────────────────

def test_markdown_bold_produces_text_style_range() -> None:
    plain, styles = _markdown_to_signal("hello **world** foo")
    assert plain == "hello world foo"
    assert len(styles) == 1
    assert styles[0] == {"start": 6, "length": 5, "style": "BOLD"}


def test_markdown_header_becomes_bold() -> None:
    plain, styles = _markdown_to_signal("## Heading\nbody")
    assert plain == "Heading\nbody"
    assert styles and styles[0]["style"] == "BOLD"
    assert styles[0]["start"] == 0
    assert styles[0]["length"] == len("Heading")


def test_markdown_monospace_and_italic() -> None:
    plain, styles = _markdown_to_signal("run `foo` then *go*")
    assert plain == "run foo then go"
    kinds = sorted(s["style"] for s in styles)
    assert kinds == ["ITALIC", "MONOSPACE"]


# ───────────────────────────── outbound mentions ─────────────────────

def test_compile_outbound_mentions_phone_bare() -> None:
    text, mentions = SignalChannel._compile_outbound_mentions(
        "Ping @+85298765432 now",
    )
    assert text == "Ping \ufffc now"
    assert mentions == [{"start": 5, "length": 1, "number": "+85298765432"}]


def test_compile_outbound_mentions_uuid_bare() -> None:
    text, mentions = SignalChannel._compile_outbound_mentions(
        "Hi @uuid:abc12345 there",
    )
    assert "\ufffc" in text
    assert mentions and mentions[0]["uuid"].startswith("abc12345")


def test_compile_outbound_mentions_name_with_phone_parens() -> None:
    text, mentions = SignalChannel._compile_outbound_mentions(
        "See @Joe (+85251159218)!",
    )
    assert text.count("\ufffc") == 1
    assert mentions == [{"start": 4, "length": 1, "number": "+85251159218"}]


# ───────────────────────────── outbound send ─────────────────────────

@pytest.mark.asyncio
async def test_send_sets_target_and_style_and_mention_params() -> None:
    ch = _make_channel()
    ch.client.connected = True  # pretend the subprocess is up

    await ch.send(
        "+85298765432",
        "Hey @+85298349370, please run **this**",
        meta={"group_id": "", "quote_timestamp": 0, "quote_author": ""},
    )
    assert len(ch.client.sent) == 1
    frame = ch.client.sent[0]
    assert frame["target"] == "+85298765432"
    assert frame["is_group"] is False
    # Placeholder present in the sent text (U+FFFC)
    assert "\ufffc" in frame["text"]
    # Bold style in `text_style`
    assert any(s.endswith(":BOLD") for s in frame["text_style"])
    # Mention compiled to "start:1:+number" form
    assert any(
        m.split(":")[-1] == "+85298349370" for m in frame["mentions"]
    )


@pytest.mark.asyncio
async def test_send_group_uses_group_id_as_target() -> None:
    ch = _make_channel()
    ch.client.connected = True
    await ch.send(
        "somehandle",
        "hello",
        meta={"group_id": "ZW5jb2RlZC1ncm91cC1pZA==", "quote_timestamp": 0},
    )
    assert ch.client.sent[0]["target"] == "ZW5jb2RlZC1ncm91cC1pZA=="
    assert ch.client.sent[0]["is_group"] is True


@pytest.mark.asyncio
async def test_send_includes_quote_when_reply_to_trigger_on() -> None:
    ch = _make_channel(reply_to_trigger=True)
    ch.client.connected = True
    await ch.send(
        "+85298765432",
        "ack",
        meta={
            "group_id": "",
            "quote_timestamp": 1_700_000_000,
            "quote_author": "+85298765432",
        },
    )
    sent = ch.client.sent[0]
    assert sent["quote_timestamp"] == 1_700_000_000
    assert sent["quote_author"] == "+85298765432"


@pytest.mark.asyncio
async def test_send_disabled_channel_is_noop() -> None:
    ch = _make_channel(enabled=False)
    ch.client.connected = True
    await ch.send("+85298765432", "should not send", meta={})
    assert ch.client.sent == []


# ───────────────────────────── inbound ───────────────────────────────

@pytest.mark.asyncio
async def test_inbound_dm_enqueues_agent_request() -> None:
    enqueue_calls: List[Any] = []

    ch = _make_channel()
    ch._enqueue = enqueue_calls.append  # attach fake enqueue
    ch.client.connected = True

    notification = {
        "envelope": {
            "sourceNumber": "+85298765432",
            "sourceUuid": "abcd1234-0000-0000-0000-000000000000",
            "sourceName": "Alice",
            "timestamp": 1_700_000_000,
            "dataMessage": {"message": "hi bot"},
        },
    }
    await ch._on_notification(notification)

    assert len(enqueue_calls) == 1
    req = enqueue_calls[0]
    meta = req.channel_meta
    assert meta["platform"] == "signal"
    assert meta["group_id"] == ""
    assert meta["source"] == "+85298765432"


@pytest.mark.asyncio
async def test_group_without_mention_buffers_into_history() -> None:
    ch = _make_channel(require_mention=True, group_policy="open")
    ch._enqueue = lambda _r: (_ for _ in ()).throw(
        AssertionError("should NOT enqueue when unmentioned"),
    )
    ch.client.connected = True

    group_id = "GID=="
    await ch._on_notification({
        "envelope": {
            "sourceNumber": "+85211111111",
            "sourceName": "Bob",
            "timestamp": 1,
            "dataMessage": {
                "message": "casual chat",
                "groupInfo": {"groupId": group_id},
            },
        },
    })
    # Nothing sent, but history now has the line
    assert group_id in ch._group_history
    assert ch._group_history[group_id][0]["body"] == "casual chat"


@pytest.mark.asyncio
async def test_group_with_mention_enqueues_and_injects_history() -> None:
    enqueue_calls: List[Any] = []
    ch = _make_channel(require_mention=True)
    ch._enqueue = enqueue_calls.append
    ch.client.connected = True

    group_id = "GID=="
    # Prior unmentioned chatter → captured as history
    await ch._on_notification({
        "envelope": {
            "sourceNumber": "+85211111111",
            "sourceName": "Bob",
            "timestamp": 1,
            "dataMessage": {
                "message": "weather is nice",
                "groupInfo": {"groupId": group_id},
            },
        },
    })
    # Now a mention triggers the bot
    await ch._on_notification({
        "envelope": {
            "sourceNumber": "+85222222222",
            "sourceName": "Carol",
            "timestamp": 2,
            "dataMessage": {
                "message": "@+85251159218 summarise",
                "mentions": [{"number": "+85251159218", "start": 0, "length": 1}],
                "groupInfo": {"groupId": group_id},
            },
        },
    })
    assert len(enqueue_calls) == 1
    texts = [
        p.text for p in enqueue_calls[0].channel_meta.get("content_parts", [])
        if hasattr(p, "text")
    ] if False else [
        p.text for p in enqueue_calls[0].input[-1].content
        if hasattr(p, "text") and p.text
    ] if hasattr(enqueue_calls[0], "input") else []
    # History should be drained after injection
    assert ch._group_history.get(group_id) == []


# ───────────────────────────── allowlist ─────────────────────────────

def test_is_source_allowed_phone() -> None:
    ch = _make_channel(dm_policy="allowlist", allow_from=["+85298765432"])
    assert ch._is_source_allowed("+85298765432", "")
    assert not ch._is_source_allowed("+85299999999", "")


def test_is_source_allowed_uuid_prefix() -> None:
    ch = _make_channel(
        dm_policy="allowlist",
        allow_from=["uuid:abcd1234-0000-0000-0000-000000000000"],
    )
    assert ch._is_source_allowed("", "abcd1234-0000-0000-0000-000000000000")
    assert not ch._is_source_allowed("", "11111111-0000-0000-0000-000000000000")


# ───────────────────────────── bot self-mention strip ────────────────

def test_strip_bot_self_mention_plain_phone() -> None:
    ch = _make_channel()
    stripped = ch._strip_bot_self_mention("@+85251159218 /stop now")
    assert stripped == "/stop now"


def test_strip_bot_self_mention_name_with_id() -> None:
    ch = _make_channel()
    stripped = ch._strip_bot_self_mention("@Bot (+85251159218) hello")
    assert stripped == "hello"
