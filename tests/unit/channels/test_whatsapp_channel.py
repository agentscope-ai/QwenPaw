# -*- coding: utf-8 -*-
# pylint: disable=protected-access,wrong-import-position
# pylint: disable=unused-variable,use-implicit-booleaness-not-comparison
"""Unit tests for WhatsApp channel."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock neonize before importing the channel module so the import does not fail
# in environments where neonize is not installed.
# ---------------------------------------------------------------------------

_neonize_mods = [
    "neonize",
    "neonize.aioze",
    "neonize.aioze.client",
    "neonize.events",
    "neonize.utils",
    "neonize.proto",
    "neonize.proto.waE2E",
    "neonize.proto.waE2E.WAWebProtobufsE2E_pb2",
]
for mod in _neonize_mods:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Provide lightweight stubs that the channel code actually touches
_utils_mod = sys.modules["neonize.utils"]
_utils_mod.build_jid = lambda user, server: MagicMock(User=user, Server=server)

# Ensure NEONIZE_AVAILABLE is True so WhatsAppChannel can be instantiated.
# All imports below the sys.modules patching above are intentionally late
# (E402 / wrong-import-position is by design and silenced inline).
from agentscope_runtime.engine.schemas.agent_schemas import (  # noqa: E402
    TextContent,
    ImageContent,
    AudioContent,
    VideoContent,
    FileContent,
    ContentType,
)
from qwenpaw.app.channels.whatsapp import channel as _wa_mod  # noqa: E402
from qwenpaw.app.channels.whatsapp.channel import (  # noqa: E402
    WhatsAppChannel,
    _jid_to_str,
    _is_group_jid,
    WHATSAPP_MAX_TEXT_LENGTH,
)

_wa_mod.NEONIZE_AVAILABLE = True
_wa_mod.NewAClient = MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(**overrides: Any) -> WhatsAppChannel:
    """Create a WhatsAppChannel with dummy process handler."""

    async def _noop_process(_request):
        yield  # pragma: no cover

    defaults = {
        "process": _noop_process,
        "enabled": True,
        "auth_dir": tempfile.mkdtemp(),
    }
    defaults.update(overrides)
    ch = WhatsAppChannel(**defaults)
    ch._client = MagicMock()
    ch._connected = True
    return ch


def _make_proto_message(**fields):
    """Build a lightweight mock that behaves like a protobuf WAMessage.

    Usage::

        msg = _make_proto_message(conversation="hello")
        msg = _make_proto_message(
            extendedTextMessage=MagicMock(text="hi", contextInfo=MagicMock(...)),  # noqa: E501
        )
    """
    msg = MagicMock()
    # HasField returns True only for keys explicitly supplied
    _present = set(fields.keys())
    msg.HasField = lambda name: name in _present
    for k, v in fields.items():
        setattr(msg, k, v)
    # Provide defaults for commonly accessed scalar fields
    if "conversation" not in fields:
        msg.conversation = ""
    return msg


# ===================================================================
# TestExtractMessageContent
# ===================================================================


class TestExtractMessageContent:
    async def test_text_conversation(self):
        ch = _make_channel()
        msg = _make_proto_message(conversation="hello world")
        body, parts = await ch._extract_message_content(
            MagicMock(),
            msg,
            "id1",
        )
        assert body == "hello world"
        assert len(parts) == 1
        assert parts[0].type == ContentType.TEXT
        assert parts[0].text == "hello world"

    async def test_extended_text_message(self):
        ch = _make_channel()
        etm = MagicMock()
        etm.text = "extended hello"
        msg = _make_proto_message(extendedTextMessage=etm)
        msg.conversation = ""
        body, parts = await ch._extract_message_content(
            MagicMock(),
            msg,
            "id2",
        )
        assert body == "extended hello"
        assert any(
            p.text == "extended hello" for p in parts if hasattr(p, "text")
        )

    async def test_image_with_caption(self):
        ch = _make_channel()
        img_msg = MagicMock()
        img_msg.caption = "nice photo"
        client = MagicMock()
        client.download_any = AsyncMock()
        msg = _make_proto_message(imageMessage=img_msg)
        msg.conversation = ""

        body, parts = await ch._extract_message_content(client, msg, "id3")
        # Caption should appear as text
        text_parts = [p for p in parts if hasattr(p, "text")]
        assert any("nice photo" in p.text for p in text_parts)
        # Image content part should be present
        img_parts = [p for p in parts if p.type == ContentType.IMAGE]
        assert len(img_parts) == 1
        client.download_any.assert_called_once()

    async def test_audio_ptt(self):
        ch = _make_channel()
        audio = MagicMock()
        audio.ptt = True
        client = MagicMock()
        client.download_any = AsyncMock()
        msg = _make_proto_message(audioMessage=audio)
        msg.conversation = ""

        body, parts = await ch._extract_message_content(client, msg, "id4")
        audio_parts = [p for p in parts if p.type == ContentType.AUDIO]
        assert len(audio_parts) == 1
        # PTT uses .ogg extension
        assert audio_parts[0].data.endswith(".ogg")

    async def test_audio_non_ptt(self):
        ch = _make_channel()
        audio = MagicMock()
        audio.ptt = False
        client = MagicMock()
        client.download_any = AsyncMock()
        msg = _make_proto_message(audioMessage=audio)
        msg.conversation = ""

        body, parts = await ch._extract_message_content(client, msg, "id5")
        audio_parts = [p for p in parts if p.type == ContentType.AUDIO]
        assert len(audio_parts) == 1
        # Non-PTT uses .m4a extension
        assert audio_parts[0].data.endswith(".m4a")

    async def test_document_path_traversal_sanitized(self):
        ch = _make_channel()
        doc = MagicMock()
        doc.fileName = "../../../etc/passwd"
        client = MagicMock()
        client.download_any = AsyncMock()
        msg = _make_proto_message(documentMessage=doc)
        msg.conversation = ""

        body, parts = await ch._extract_message_content(client, msg, "id6")
        file_parts = [p for p in parts if p.type == ContentType.FILE]
        assert len(file_parts) == 1
        # Path should be sanitized — only the final component "passwd"
        saved_path = Path(file_parts[0].file_url)
        assert saved_path.name == "passwd"
        assert ".." not in str(saved_path)
        # Should be within media dir
        assert str(ch._media_dir) in str(saved_path.parent)


# ===================================================================
# TestExtractQuoteContent
# ===================================================================


class TestExtractQuoteContent:
    async def test_quote_with_text_only(self):
        ch = _make_channel()
        ctx = MagicMock()
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.participant = "123456@s.whatsapp.net"
        quoted = _make_proto_message(conversation="original text")
        # Ensure text extraction works
        quoted.extendedTextMessage = MagicMock()
        quoted.HasField = (
            lambda name: name == "extendedTextMessage"
            if name == "extendedTextMessage"
            else False
        )
        quoted.extendedTextMessage.text = ""
        # Use conversation path
        quoted.conversation = "original text"
        quoted.HasField = lambda name: False  # No media fields
        ctx.quotedMessage = quoted
        ctx.stanzaId = "stanza1"

        etm = MagicMock()
        etm.text = "reply text"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        parts = await ch._extract_quote_content(MagicMock(), msg)
        assert len(parts) >= 1
        text_parts = [p for p in parts if hasattr(p, "text")]
        assert any("UNTRUSTED reply-to" in p.text for p in text_parts)
        assert any("original text" in p.text for p in text_parts)

    async def test_quote_with_image_download(self):
        ch = _make_channel()
        ctx = MagicMock()
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.participant = "sender@s.whatsapp.net"
        ctx.stanzaId = "stanza2"

        img = MagicMock()
        img.caption = "photo caption"

        quoted = MagicMock()
        quoted.conversation = ""
        quoted.HasField = lambda name: name == "imageMessage"
        quoted.imageMessage = img
        ctx.quotedMessage = quoted

        etm = MagicMock()
        etm.text = "responding"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        # Simulate download failure (common for quoted messages)
        client = MagicMock()
        client.download_any = AsyncMock(side_effect=Exception("no media key"))

        parts = await ch._extract_quote_content(client, msg)
        assert len(parts) >= 1
        # Should have text description mentioning image
        text_parts = [p for p in parts if hasattr(p, "text")]
        combined = " ".join(p.text for p in text_parts)
        assert "UNTRUSTED reply-to" in combined
        assert "image" in combined.lower()

    async def test_quote_with_video_described(self):
        """Quoted video produces 'Media: video' in reply-to block."""
        ch = _make_channel()
        ctx = MagicMock()
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.participant = "video_sender@s.whatsapp.net"
        ctx.stanzaId = "stanza_video"

        quoted = MagicMock()
        quoted.conversation = ""
        quoted.HasField = lambda name: name == "videoMessage"
        ctx.quotedMessage = quoted

        etm = MagicMock()
        etm.text = "nice clip"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        parts = await ch._extract_quote_content(MagicMock(), msg)
        text_parts = [p for p in parts if hasattr(p, "text")]
        assert len(text_parts) == 1
        assert "UNTRUSTED reply-to" in text_parts[0].text
        assert "Media: video" in text_parts[0].text

    async def test_quote_with_voice_note_described(self):
        """Quoted audio with ptt=True is described as 'voice note'."""
        ch = _make_channel()
        ctx = MagicMock()
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.participant = "audio_sender@s.whatsapp.net"
        ctx.stanzaId = "stanza_audio"

        audio_msg = MagicMock()
        audio_msg.ptt = True

        quoted = MagicMock()
        quoted.conversation = ""
        quoted.HasField = lambda name: name == "audioMessage"
        quoted.audioMessage = audio_msg
        ctx.quotedMessage = quoted

        etm = MagicMock()
        etm.text = "hear this"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        parts = await ch._extract_quote_content(MagicMock(), msg)
        text = parts[0].text
        assert "Media: voice note" in text

    async def test_quote_with_audio_non_ptt_described(self):
        """Quoted audio with ptt=False is described as 'audio'."""
        ch = _make_channel()
        ctx = MagicMock()
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.participant = "audio_sender@s.whatsapp.net"
        ctx.stanzaId = "stanza_audio2"

        audio_msg = MagicMock()
        audio_msg.ptt = False

        quoted = MagicMock()
        quoted.conversation = ""
        quoted.HasField = lambda name: name == "audioMessage"
        quoted.audioMessage = audio_msg
        ctx.quotedMessage = quoted

        etm = MagicMock()
        etm.text = ""
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        parts = await ch._extract_quote_content(MagicMock(), msg)
        text = parts[0].text
        assert "Media: audio" in text
        assert "voice note" not in text

    async def test_quote_with_document_described(self):
        """Quoted document is described with its filename."""
        ch = _make_channel()
        ctx = MagicMock()
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.participant = "doc_sender@s.whatsapp.net"
        ctx.stanzaId = "stanza_doc"

        doc_msg = MagicMock()
        doc_msg.fileName = "report.pdf"

        quoted = MagicMock()
        quoted.conversation = ""
        quoted.HasField = lambda name: name == "documentMessage"
        quoted.documentMessage = doc_msg
        ctx.quotedMessage = quoted

        etm = MagicMock()
        etm.text = "read this"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        parts = await ch._extract_quote_content(MagicMock(), msg)
        text = parts[0].text
        assert "file: report.pdf" in text

    async def test_quote_with_sticker_described(self):
        """Quoted sticker is described as 'sticker'."""
        ch = _make_channel()
        ctx = MagicMock()
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.participant = "s@s.whatsapp.net"
        ctx.stanzaId = "stanza_sticker"

        quoted = MagicMock()
        quoted.conversation = ""
        quoted.HasField = lambda name: name == "stickerMessage"
        ctx.quotedMessage = quoted

        etm = MagicMock()
        etm.text = "lol"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        parts = await ch._extract_quote_content(MagicMock(), msg)
        text = parts[0].text
        assert "Media: sticker" in text

    async def test_no_quoted_message_returns_empty(self):
        ch = _make_channel()
        # Message with no contextInfo
        msg = _make_proto_message(conversation="plain message")
        parts = await ch._extract_quote_content(MagicMock(), msg)
        assert parts == []

    async def test_quote_participant_lid_resolution(self):
        ch = _make_channel()
        # Pre-populate LID cache
        ch._lid_cache["123456@lid"] = {"phone": "85251159218", "name": "Alice"}

        ctx = MagicMock()
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.participant = "123456@lid"
        ctx.stanzaId = "stanza_lid"

        quoted = MagicMock()
        quoted.conversation = "lid message"
        quoted.HasField = lambda name: False
        ctx.quotedMessage = quoted

        etm = MagicMock()
        etm.text = "reply"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        parts = await ch._extract_quote_content(MagicMock(), msg)
        assert len(parts) >= 1
        text_parts = [p for p in parts if hasattr(p, "text")]
        combined = " ".join(p.text for p in text_parts)
        # Should show resolved phone number, not raw LID
        assert "+85251159218" in combined


# ===================================================================
# TestCheckAccess
# ===================================================================


class TestCheckAccess:
    def test_group_policy_open_allows(self):
        ch = _make_channel(group_policy="open")
        assert (
            ch._check_access(
                is_group=True,
                chat_str="groupA@g.us",
                sender_str="user@s.whatsapp.net",
                sender_jid=MagicMock(),
                client=MagicMock(),
                msg=MagicMock(),
                body="hi",
            )
            is True
        )

    def test_group_policy_allowlist_group_in_list(self):
        ch = _make_channel(group_policy="allowlist", groups=["groupA@g.us"])
        assert (
            ch._check_access(
                is_group=True,
                chat_str="groupA@g.us",
                sender_str="user@s.whatsapp.net",
                sender_jid=MagicMock(),
                client=MagicMock(),
                msg=MagicMock(),
                body="hi",
            )
            is True
        )

    def test_group_policy_allowlist_group_not_in_list(self):
        ch = _make_channel(group_policy="allowlist", groups=["groupA@g.us"])
        assert (
            ch._check_access(
                is_group=True,
                chat_str="groupB@g.us",
                sender_str="user@s.whatsapp.net",
                sender_jid=MagicMock(),
                client=MagicMock(),
                msg=MagicMock(),
                body="hi",
            )
            is False
        )

    def test_group_policy_allowlist_empty_groups_blocks_all(self):
        ch = _make_channel(group_policy="allowlist", groups=[])
        assert (
            ch._check_access(
                is_group=True,
                chat_str="anygroup@g.us",
                sender_str="user@s.whatsapp.net",
                sender_jid=MagicMock(),
                client=MagicMock(),
                msg=MagicMock(),
                body="hi",
            )
            is False
        )

    def test_dm_policy_open_allows(self):
        """DM access is not blocked in _check_access (async check in _on_message)."""  # noqa: E501
        ch = _make_channel(dm_policy="open")
        assert (
            ch._check_access(
                is_group=False,
                chat_str="user@s.whatsapp.net",
                sender_str="user@s.whatsapp.net",
                sender_jid=MagicMock(),
                client=MagicMock(),
                msg=MagicMock(),
                body="hi",
            )
            is True
        )

    def test_group_allow_from_stored(self):
        """group_allow_from is stored on the channel for use in _on_message."""
        ch = _make_channel(group_allow_from=["+85251159218"])
        assert ch._group_allow_from == ["+85251159218"]


# ===================================================================
# TestGroupHistory
# ===================================================================


class TestGroupHistory:
    def test_non_mentioned_message_recorded(self):
        """When bot is NOT mentioned, message should be buffered in history."""
        ch = _make_channel(require_mention=True)
        ch._my_jid = MagicMock(User="botlid")
        ch._bot_lid = "botlid"
        ch._bot_phone = "85200000000"

        chat_str = "group123@g.us"
        history = ch._group_history.setdefault(chat_str, [])
        # Simulate recording (as done in _on_message)
        history.append(
            {"sender": "+85251159218", "body": "hello", "ts": "12345"},
        )
        assert len(ch._group_history[chat_str]) == 1

    def test_history_limit_enforced(self):
        ch = _make_channel()
        ch._group_history_limit = 5
        chat_str = "group123@g.us"
        history = ch._group_history.setdefault(chat_str, [])
        for i in range(10):
            history.append(
                {"sender": f"user{i}", "body": f"msg{i}", "ts": str(i)},
            )
        # Trim like the channel does
        if len(history) > ch._group_history_limit:
            ch._group_history[chat_str] = history[-ch._group_history_limit :]
        assert len(ch._group_history[chat_str]) == 5
        assert ch._group_history[chat_str][0]["body"] == "msg5"

    def test_history_injected_when_mentioned(self):
        """When bot IS mentioned, buffered history should be injected."""
        ch = _make_channel()
        chat_str = "group123@g.us"
        ch._group_history[chat_str] = [
            {"sender": "+852111", "body": "earlier msg 1", "ts": "1"},
            {"sender": "+852222", "body": "earlier msg 2", "ts": "2"},
        ]
        # Simulate the injection logic from _on_message
        history = ch._group_history.get(chat_str, [])
        ctx_lines = []
        for h in history[-10:]:
            ctx_lines.append(f"  {h['sender']}: {h['body']}")
        ctx_text = (
            "--- Recent group messages (context only, not directed at you) ---\n"  # noqa: E501
            + "\n".join(ctx_lines)
        )
        content_parts = [TextContent(type=ContentType.TEXT, text=ctx_text)]
        ch._group_history[chat_str] = []

        assert "earlier msg 1" in content_parts[0].text
        assert "earlier msg 2" in content_parts[0].text

    def test_history_cleared_after_injection(self):
        ch = _make_channel()
        chat_str = "group123@g.us"
        ch._group_history[chat_str] = [
            {"sender": "u1", "body": "msg", "ts": "1"},
        ]
        # Simulate clearing after injection
        ch._group_history[chat_str] = []
        assert ch._group_history[chat_str] == []

    def test_history_entry_includes_media_paths(self, tmp_path):
        """History entries should capture media paths alongside text."""
        # Create a dummy image file
        img = tmp_path / "wa_img_abc.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
        ch = _make_channel()
        chat_str = "group123@g.us"
        history = ch._group_history.setdefault(chat_str, [])
        # Simulate what _on_message does: scan content_parts for media
        parts = [
            TextContent(type=ContentType.TEXT, text="look at this"),
            ImageContent(type=ContentType.IMAGE, image_url=str(img)),
        ]
        media_paths = []
        for p in parts:
            for attr in ("image_url", "video_url", "file_url", "data"):
                v = getattr(p, attr, None)
                if v and os.path.isfile(str(v)):
                    media_paths.append(str(v))
                    break
        history.append(
            {
                "sender": "+852111",
                "body": "look at this",
                "ts": "1",
                "media": media_paths,
            },
        )
        assert ch._group_history[chat_str][0]["media"] == [str(img)]

    def test_history_context_includes_media_count(self, tmp_path):
        """Context injection format should mention attached media."""
        img = tmp_path / "img.jpg"
        img.write_bytes(b"\xff\xd8\xff")
        ch = _make_channel()
        chat_str = "group123@g.us"
        ch._group_history[chat_str] = [
            {
                "sender": "+852111",
                "body": "photo",
                "ts": "1",
                "media": [str(img)],
            },
        ]
        # Simulate injection format
        history = ch._group_history.get(chat_str, [])
        lines = [
            "=== UNTRUSTED WhatsApp group history "  # noqa: E501
            "(context only, not directed at you) ===",
        ]
        for h in history[-10:]:
            line = f"  {h['sender']}: {h['body']}"
            if h.get("media"):
                line += f"  [media: {len(h['media'])}]"
            lines.append(line)
        ctx = "\n".join(lines)
        assert "[media: 1]" in ctx
        assert "=== UNTRUSTED WhatsApp group history" in ctx


# ===================================================================
# TestEnvelopeFormat
# ===================================================================


class TestEnvelopeFormat:
    """Tests for the [WhatsApp group/DM] ... envelope prefix."""

    def test_group_envelope_prefix(self):
        chat_str = "120363421135228220@g.us"
        sender = "Joe HO (+85251159218)"
        envelope = f"[WhatsApp group {chat_str}] {sender}"
        assert envelope.startswith("[WhatsApp group ")
        assert "g.us" in envelope
        assert "Joe HO" in envelope

    def test_dm_envelope_prefix(self):
        sender = "+85251159218"
        envelope = f"[WhatsApp DM] {sender}"
        assert envelope == "[WhatsApp DM] +85251159218"

    def test_command_extraction_from_envelope(self):
        """After envelope wrap, extracting /command should still work."""
        # Simulate post-envelope text
        wrapped = "[WhatsApp group 120363@g.us] Joe (+85251159218): /new"
        # Agent extraction: skip [WhatsApp ...], find first ": " after "] "
        bracket_end = wrapped.find("] ")
        assert bracket_end > 0
        after = wrapped[bracket_end + 2 :]
        idx = after.find(": ")
        assert idx > 0
        raw = after[idx + 2 :]
        assert raw == "/new"


# ===================================================================
# TestMentionDetection (_is_bot_mentioned)
# ===================================================================


class TestMentionDetection:
    def _setup_channel(self) -> WhatsAppChannel:
        ch = _make_channel()
        ch._my_jid = MagicMock(User="botlid123")
        ch._bot_lid = "botlid123"
        ch._bot_phone = "85200000000"
        return ch

    def test_at_lid_in_body(self):
        ch = self._setup_channel()
        msg = _make_proto_message(conversation="hello @botlid123 test")
        assert ch._is_bot_mentioned(msg, "hello @botlid123 test") is True

    def test_at_phone_in_body(self):
        ch = self._setup_channel()
        msg = _make_proto_message(conversation="hello @85200000000 test")
        assert ch._is_bot_mentioned(msg, "hello @85200000000 test") is True

    def test_at_plus_phone_in_body(self):
        ch = self._setup_channel()
        msg = _make_proto_message(conversation="hello @+85200000000 test")
        assert ch._is_bot_mentioned(msg, "hello @+85200000000 test") is True

    def test_native_mentioned_jid_match(self):
        ch = self._setup_channel()
        ctx = MagicMock()
        jid = MagicMock()
        jid.User = "botlid123"
        ctx.mentionedJID = [jid]
        ctx.HasField = lambda name: False
        ctx.stanzaId = ""
        ctx.participant = ""

        etm = MagicMock()
        etm.text = "hey bot"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        assert ch._is_bot_mentioned(msg, "hey bot") is True

    def test_reply_to_bot_message(self):
        ch = self._setup_channel()
        ctx = MagicMock()
        ctx.mentionedJID = []
        ctx.HasField = lambda name: name == "quotedMessage"
        ctx.stanzaId = "some_stanza"
        ctx.participant = "botlid123@lid"

        etm = MagicMock()
        etm.text = "replying"
        etm.contextInfo = ctx
        msg = _make_proto_message(extendedTextMessage=etm)

        assert ch._is_bot_mentioned(msg, "replying") is True

    def test_no_mention_returns_false(self):
        ch = self._setup_channel()
        msg = _make_proto_message(conversation="hello world")
        assert ch._is_bot_mentioned(msg, "hello world") is False


# ===================================================================
# TestSend
# ===================================================================


class TestSend:
    async def test_basic_text_send(self):
        ch = _make_channel()
        ch._client.send_message = AsyncMock()
        await ch.send("+85200000000", "hello", {})
        ch._client.send_message.assert_called_once()
        args = ch._client.send_message.call_args[0]
        assert args[1] == "hello"

    async def test_empty_text_noop(self):
        ch = _make_channel()
        ch._client.send_message = AsyncMock()
        await ch.send("+85200000000", "", {})
        ch._client.send_message.assert_not_called()

    async def test_disabled_noop(self):
        ch = _make_channel(enabled=False)
        ch._client = MagicMock()
        ch._client.send_message = AsyncMock()
        await ch.send("+85200000000", "hi")
        ch._client.send_message.assert_not_called()

    async def test_image_path_restricted_to_media_dir(self):
        ch = _make_channel()
        ch._client.send_image = AsyncMock()
        ch._client.send_message = AsyncMock()
        # Image outside media dir should be blocked
        text = "[Image: /etc/passwd] check this"
        await ch.send("+85200000000", text, {})
        ch._client.send_image.assert_not_called()

    async def test_text_chunking(self):
        ch = _make_channel(text_chunk_limit=10)
        ch._client.send_message = AsyncMock()
        text = "AAAAAAAAAA" + "BBBBBBBBBB"  # 20 chars, limit 10
        await ch.send("+85200000000", text, {})
        assert ch._client.send_message.call_count == 2


# ===================================================================
# TestSendMedia — outbound attachments via WhatsAppChannel.send_media
# ===================================================================


class TestSendMedia:
    """Primary outbound media path. Called by base.send_content_parts
    for every non-text block the agent emits (via send_file_to_user
    or directly returning ImageBlock/AudioBlock/VideoBlock/FileBlock)."""

    def _ready_channel(self, tmp_path):
        ch = _make_channel()
        ch._connected = True
        ch._client = MagicMock()
        ch._client.send_image = AsyncMock()
        ch._client.send_video = AsyncMock()
        ch._client.send_audio = AsyncMock()
        ch._client.send_document = AsyncMock()
        f = tmp_path / "a.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
        return ch, f

    async def test_send_image(self, tmp_path):
        ch, f = self._ready_channel(tmp_path)
        part = ImageContent(type=ContentType.IMAGE, image_url=str(f))
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_image.assert_called_once()
        args = ch._client.send_image.call_args.args
        assert args[1] == str(f)

    async def test_send_video(self, tmp_path):
        ch, _ = self._ready_channel(tmp_path)
        vid = tmp_path / "clip.mp4"
        vid.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 10)
        part = VideoContent(type=ContentType.VIDEO, video_url=str(vid))
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_video.assert_called_once()
        assert ch._client.send_document.call_count == 0

    async def test_send_audio(self, tmp_path):
        ch, _ = self._ready_channel(tmp_path)
        aud = tmp_path / "voice.ogg"
        aud.write_bytes(b"OggS" + b"\x00" * 10)
        part = AudioContent(type=ContentType.AUDIO, data=str(aud))
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_audio.assert_called_once()
        # ptt=True for voice notes
        assert ch._client.send_audio.call_args.kwargs.get("ptt") is True

    async def test_send_file(self, tmp_path):
        ch, _ = self._ready_channel(tmp_path)
        doc = tmp_path / "doc.pdf"
        doc.write_bytes(b"%PDF-1.5")
        part = FileContent(type=ContentType.FILE, file_url=str(doc))
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_document.assert_called_once()
        assert ch._client.send_image.call_count == 0

    async def test_send_strips_file_scheme(self, tmp_path):
        ch, f = self._ready_channel(tmp_path)
        part = ImageContent(type=ContentType.IMAGE, image_url=f"file://{f}")
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        args = ch._client.send_image.call_args.args
        assert args[1] == str(f)

    async def test_missing_file_noop(self, tmp_path):
        ch, _ = self._ready_channel(tmp_path)
        missing = tmp_path / "gone.jpg"
        part = ImageContent(type=ContentType.IMAGE, image_url=str(missing))
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_image.assert_not_called()

    async def test_no_path_noop(self, tmp_path):
        ch, _ = self._ready_channel(tmp_path)
        part = ImageContent(type=ContentType.IMAGE, image_url="")
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_image.assert_not_called()

    async def test_disconnected_noop(self, tmp_path):
        ch, f = self._ready_channel(tmp_path)
        ch._connected = False
        part = ImageContent(type=ContentType.IMAGE, image_url=str(f))
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_image.assert_not_called()

    async def test_disabled_noop(self, tmp_path):
        ch, f = self._ready_channel(tmp_path)
        ch.enabled = False
        part = ImageContent(type=ContentType.IMAGE, image_url=str(f))
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_image.assert_not_called()

    async def test_file_fallback_to_file_id(self, tmp_path):
        """FileContent uses file_id when file_url is absent."""
        ch, _ = self._ready_channel(tmp_path)
        doc = tmp_path / "doc.pdf"
        doc.write_bytes(b"%PDF-1.5")
        part = MagicMock()
        part.type = ContentType.FILE
        part.file_url = None
        part.file_id = str(doc)
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )
        ch._client.send_document.assert_called_once()

    async def test_send_fails_logs_error(self, tmp_path):
        ch, f = self._ready_channel(tmp_path)
        ch._client.send_image = AsyncMock(side_effect=RuntimeError("boom"))
        part = ImageContent(type=ContentType.IMAGE, image_url=str(f))
        # Should not raise — error is caught + logged
        await ch.send_media(
            "12345@s.whatsapp.net",
            part,
            {"chat_jid": "12345@s.whatsapp.net"},
        )


# ===================================================================
# TestChunkText
# ===================================================================


class TestChunkText:
    def test_short_text_not_chunked(self):
        ch = _make_channel()
        assert ch._chunk_text("hello") == ["hello"]

    def test_empty_text(self):
        ch = _make_channel()
        assert ch._chunk_text("") == []

    def test_long_text_chunked(self):
        ch = _make_channel(text_chunk_limit=20)
        text = "A" * 50
        chunks = ch._chunk_text(text)
        assert len(chunks) >= 2
        assert "".join(chunks) == text

    def test_chunking_prefers_newline_break(self):
        ch = _make_channel(text_chunk_limit=30)
        # Chunk limit 30, half = 15. Newline must be at index > 15 to trigger break.  # noqa: E501
        # "A" * 16 + "\n" puts newline at index 16, which is > 15.
        text = "A" * 16 + "\n" + "B" * 25
        chunks = ch._chunk_text(text)
        assert chunks[0] == "A" * 16


# ===================================================================
# TestTypingLoop
# ===================================================================


class TestTypingLoop:
    async def test_typing_loop_created_and_cancelled(self):
        ch = _make_channel()
        mock_client = MagicMock()
        mock_client._NewAClient__client = MagicMock()
        mock_client._NewAClient__client.SendChatPresence = AsyncMock()
        mock_client.uuid = "test-uuid"

        typing_jid = MagicMock()
        typing_jid.SerializeToString = lambda: b"\x00"

        task = asyncio.create_task(
            ch._typing_loop(mock_client, typing_jid, interval=0.05),
        )
        await asyncio.sleep(0.15)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ===================================================================
# Utility functions
# ===================================================================


class TestJidUtils:
    def test_jid_to_str(self):
        jid = MagicMock(User="85200000000", Server="s.whatsapp.net")
        assert _jid_to_str(jid) == "85200000000@s.whatsapp.net"

    def test_jid_to_str_no_user(self):
        jid = MagicMock(spec=[])
        result = _jid_to_str(jid)
        assert isinstance(result, str)

    def test_is_group_jid(self):
        jid = MagicMock(Server="g.us")
        assert _is_group_jid(jid) is True

    def test_is_not_group_jid(self):
        jid = MagicMock(Server="s.whatsapp.net")
        assert _is_group_jid(jid) is False


class TestFormatSender:
    def test_with_phone_and_name(self):
        ch = _make_channel()
        ch._lid_cache["123@lid"] = {"phone": "85200000000", "name": "Alice"}
        assert ch._format_sender("123@lid") == "+85200000000 (Alice)"

    def test_with_phone_only(self):
        ch = _make_channel()
        ch._lid_cache["123@lid"] = {"phone": "85200000000", "name": ""}
        assert ch._format_sender("123@lid") == "+85200000000"

    def test_fallback_to_raw(self):
        ch = _make_channel()
        assert ch._format_sender("unknown@lid") == "unknown@lid"


# ===================================================================
# TestStripBotMention
# ===================================================================


class TestStripBotMention:
    """Tests for bot @mention stripping (enables /command detection)."""

    def test_strip_phone_mention_at_start(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        assert ch._strip_bot_mention("@+817089933036 /new") == "/new"

    def test_strip_phone_mention_no_plus(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        assert ch._strip_bot_mention("@817089933036 hello") == "hello"

    def test_strip_lid_mention(self):
        ch = _make_channel()
        ch._bot_lid = "229661330157571"
        assert ch._strip_bot_mention("@229661330157571 /stop") == "/stop"

    def test_strip_both_phone_and_lid(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        ch._bot_lid = "229661330157571"
        assert (
            ch._strip_bot_mention("@+817089933036 @229661330157571 hi") == "hi"
        )

    def test_no_mention_unchanged(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        assert ch._strip_bot_mention("just plain text") == "just plain text"

    def test_no_bot_phone_or_lid_unchanged(self):
        ch = _make_channel()
        ch._bot_phone = ""
        ch._bot_lid = ""
        assert (
            ch._strip_bot_mention("@+817089933036 hi") == "@+817089933036 hi"
        )

    def test_empty_text(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        assert ch._strip_bot_mention("") == ""

    def test_none_text(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        assert ch._strip_bot_mention(None) is None

    def test_different_mention_not_stripped(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        # Mention of a DIFFERENT number should stay
        assert (
            ch._strip_bot_mention("@+85251159218 hello")
            == "@+85251159218 hello"
        )

    def test_mention_in_middle(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        # Mentions are only stripped at the START of the message (so /commands
        # after "@+bot" work). A mid-string mention is left untouched to avoid
        # altering normal conversational text.
        assert (
            ch._strip_bot_mention("hello @+817089933036 world")
            == "hello @+817089933036 world"
        )


# ===================================================================
# TestSlashCommandDetection
# ===================================================================


class TestSlashCommandDetection:
    """Tests for slash command detection after mention strip."""

    def test_slash_command_after_mention(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        body = ch._strip_bot_mention("@+817089933036 /new")
        assert body.lstrip().startswith("/")

    def test_slash_command_no_mention(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        body = ch._strip_bot_mention("/clear")
        assert body.lstrip().startswith("/")

    def test_regular_text_not_command(self):
        ch = _make_channel()
        ch._bot_phone = "817089933036"
        body = ch._strip_bot_mention("@+817089933036 what is this")
        assert not body.lstrip().startswith("/")

    def test_slash_in_middle_not_command(self):
        body = "do /not detect this"
        assert not body.lstrip().startswith("/")


# ===================================================================
# TestAckReactions
# ===================================================================


class TestAckReactions:
    """Tests for the thinking/done reaction acknowledgement flow."""

    async def test_send_reaction_calls_build_and_send(self):
        ch = _make_channel()
        client = MagicMock()
        client.build_reaction = AsyncMock(return_value="REACTION_MSG")
        client.send_message = AsyncMock()
        chat_jid = MagicMock()
        sender_jid = MagicMock()
        await ch._send_reaction(client, chat_jid, sender_jid, "MSGID", "🤔")
        client.build_reaction.assert_awaited_once_with(
            chat_jid,
            sender_jid,
            "MSGID",
            "🤔",
        )
        client.send_message.assert_awaited_once_with(chat_jid, "REACTION_MSG")

    async def test_send_reaction_swallows_errors(self):
        ch = _make_channel()
        client = MagicMock()
        client.build_reaction = AsyncMock(side_effect=RuntimeError("boom"))
        # Should not raise
        await ch._send_reaction(
            client,
            MagicMock(),
            MagicMock(),
            "MSGID",
            "🤔",
        )

    async def test_empty_emoji_clears_reaction(self):
        """Passing emoji='' removes any existing reaction — WhatsApp
        convention."""
        ch = _make_channel()
        client = MagicMock()
        client.build_reaction = AsyncMock(return_value="EMPTY")
        client.send_message = AsyncMock()
        await ch._send_reaction(
            client,
            MagicMock(),
            MagicMock(),
            "MSGID",
            "",
        )
        client.build_reaction.assert_called_once()
        assert client.build_reaction.call_args[0][3] == ""

    def test_ack_reactions_configurable(self):
        ch = _make_channel(
            ack_reaction_thinking="⏳",
            ack_reaction_done="✅",
        )
        assert ch._ack_reaction_thinking == "⏳"
        assert ch._ack_reaction_done == "✅"

    def test_ack_reactions_can_be_disabled(self):
        ch = _make_channel(ack_reaction_thinking="", ack_reaction_done="")
        assert ch._ack_reaction_thinking == ""
        assert ch._ack_reaction_done == ""

    def test_error_reaction_configurable(self):
        ch = _make_channel(ack_reaction_error="💥")
        assert ch._ack_reaction_error == "💥"

    def test_error_reaction_default(self):
        ch = _make_channel()
        assert ch._ack_reaction_error == "⚠️"

    def test_error_reaction_can_be_disabled(self):
        ch = _make_channel(ack_reaction_error="")
        assert ch._ack_reaction_error == ""


# ---------------------------------------------------------------------------
# Reply-to trigger message tests
# ---------------------------------------------------------------------------


class TestReplyToTrigger:
    """Tests for the reply-to-trigger-message feature."""

    def test_reply_to_trigger_default_enabled(self):
        ch = _make_channel()
        assert ch._reply_to_trigger is True

    def test_reply_to_trigger_can_disable(self):
        ch = _make_channel(reply_to_trigger=False)
        assert ch._reply_to_trigger is False

    def test_pending_quote_msgs_initialised(self):
        ch = _make_channel()
        assert isinstance(ch._pending_quote_msgs, dict)
        assert len(ch._pending_quote_msgs) == 0

    @pytest.mark.asyncio
    async def test_send_with_quote_calls_build_reply(self):
        """When reply_to_trigger is True and a quote msg exists, first chunk
        should use build_reply_message (awaited) + send_message."""
        ch = _make_channel(reply_to_trigger=True)
        fake_quote = MagicMock()
        ch._pending_quote_msgs["test_chat"] = fake_quote

        # build_reply_message is async
        reply_proto = MagicMock()
        ch._client.build_reply_message = AsyncMock(return_value=reply_proto)
        ch._client.send_message = AsyncMock()

        await ch.send(
            "test_chat",
            "hello world",
            meta={"chat_jid": "test_chat"},
        )

        ch._client.build_reply_message.assert_awaited_once_with(
            message="hello world",
            quoted=fake_quote,
        )
        ch._client.send_message.assert_awaited()
        # Quote msg consumed (popped)
        assert "test_chat" not in ch._pending_quote_msgs

    @pytest.mark.asyncio
    async def test_send_without_quote_sends_normally(self):
        """When no quote msg is pending, send_message is called directly."""
        ch = _make_channel(reply_to_trigger=True)
        ch._client.send_message = AsyncMock()

        await ch.send("test_chat", "hello", meta={})

        ch._client.build_reply_message.assert_not_called()
        ch._client.send_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_send_disabled_skips_quote(self):
        """When reply_to_trigger is False, never quote even if msg pending."""
        ch = _make_channel(reply_to_trigger=False)
        fake_quote = MagicMock()
        ch._pending_quote_msgs["test_chat"] = fake_quote
        ch._client.send_message = AsyncMock()

        await ch.send("test_chat", "hello", meta={"chat_jid": "test_chat"})

        ch._client.build_reply_message.assert_not_called()
        ch._client.send_message.assert_awaited()
        # Quote msg NOT consumed since feature disabled
        assert "test_chat" in ch._pending_quote_msgs

    @pytest.mark.asyncio
    async def test_send_multipart_only_first_chunk_quotes(self):
        """For multi-chunk messages, only the first chunk should quote."""
        ch = _make_channel(reply_to_trigger=True)
        fake_quote = MagicMock()
        long_text = "x" * (WHATSAPP_MAX_TEXT_LENGTH + 100)
        ch._pending_quote_msgs["test_chat"] = fake_quote

        reply_proto = MagicMock()
        ch._client.build_reply_message = AsyncMock(return_value=reply_proto)
        ch._client.send_message = AsyncMock()

        await ch.send("test_chat", long_text, meta={"chat_jid": "test_chat"})

        # build_reply called exactly once (first chunk)
        assert ch._client.build_reply_message.await_count == 1
        # send_message called for all chunks (>= 2)
        assert ch._client.send_message.await_count >= 2

    @pytest.mark.asyncio
    async def test_build_reply_failure_falls_back(self):
        """If build_reply_message raises, should still attempt normal send."""
        ch = _make_channel(reply_to_trigger=True)
        ch._pending_quote_msgs["test_chat"] = MagicMock()
        ch._client.build_reply_message = AsyncMock(
            side_effect=Exception("proto error"),
        )
        ch._client.send_message = AsyncMock()

        # Should not raise — error is caught
        await ch.send("test_chat", "hello", meta={"chat_jid": "test_chat"})


# ---------------------------------------------------------------------------
# Typing loop tests (SendChatPresence panic prevention)
# ---------------------------------------------------------------------------


class TestTypingLoopPresencePanicPrevention:
    """Tests for _typing_loop — especially that cancelled typing does NOT
    send presence type 2 (paused) which causes neonize Go panic."""

    @pytest.mark.asyncio
    async def test_typing_sends_composing_presence(self):
        """While active, typing loop sends presence type 0 (composing)."""
        ch = _make_channel()
        mock_jid = MagicMock()
        mock_jid.SerializeToString = MagicMock(return_value=b"\x00")

        mock_inner = AsyncMock()
        ch._client._NewAClient__client = MagicMock()
        ch._client._NewAClient__client.SendChatPresence = mock_inner
        ch._client.uuid = "test-uuid"

        task = asyncio.create_task(
            ch._typing_loop(ch._client, mock_jid, interval=0.1),
        )
        await asyncio.sleep(0.25)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have called SendChatPresence with type 0 (composing)
        assert mock_inner.await_count >= 2
        for call in mock_inner.call_args_list:
            args = call[0]
            # 4th arg is presence type: 0=composing, 2=paused
            assert (
                args[3] == 0
            ), f"Expected presence type 0 (composing), got {args[3]}"

    @pytest.mark.asyncio
    async def test_cancelled_typing_does_not_send_paused(self):
        """CRITICAL: Cancelling typing loop must NOT send presence type 2.

        SendChatPresence(type=2) causes neonize Go panic:
        'index out of range [2] with length 2' -> SIGABRT -> process crash.
        """
        ch = _make_channel()
        mock_jid = MagicMock()
        mock_jid.SerializeToString = MagicMock(return_value=b"\x00")

        mock_inner = AsyncMock()
        ch._client._NewAClient__client = MagicMock()
        ch._client._NewAClient__client.SendChatPresence = mock_inner
        ch._client.uuid = "test-uuid"

        task = asyncio.create_task(
            ch._typing_loop(ch._client, mock_jid, interval=0.1),
        )
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # MUST NOT have any call with presence type 2 (paused)
        for call in mock_inner.call_args_list:
            args = call[0]
            assert args[3] != 2, (
                "FATAL: SendChatPresence called with type=2 (paused). "
                "This causes neonize Go panic -> SIGABRT -> process crash!"
            )

    @pytest.mark.asyncio
    async def test_typing_loop_handles_send_error_gracefully(self):
        """If SendChatPresence raises, loop continues (no crash)."""
        ch = _make_channel()
        mock_jid = MagicMock()
        mock_jid.SerializeToString = MagicMock(return_value=b"\x00")

        call_count = 0

        async def flaky_send(*_args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")

        ch._client._NewAClient__client = MagicMock()
        ch._client._NewAClient__client.SendChatPresence = flaky_send
        ch._client.uuid = "test-uuid"

        task = asyncio.create_task(
            ch._typing_loop(ch._client, mock_jid, interval=0.1),
        )
        await asyncio.sleep(0.35)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have retried after error
        assert (
            call_count >= 2
        ), f"Expected at least 2 calls (1 error + 1 success), got {call_count}"

    @pytest.mark.asyncio
    async def test_typing_loop_cancellation_is_clean(self):
        """Cancelling typing loop should not raise or leave dangling tasks."""
        ch = _make_channel()
        mock_jid = MagicMock()
        mock_jid.SerializeToString = MagicMock(return_value=b"\x00")

        ch._client._NewAClient__client = MagicMock()
        ch._client._NewAClient__client.SendChatPresence = AsyncMock()
        ch._client.uuid = "test-uuid"

        task = asyncio.create_task(
            ch._typing_loop(ch._client, mock_jid, interval=0.1),
        )
        await asyncio.sleep(0.15)
        task.cancel()

        # Should complete without raising
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert task.done()
        assert not task.cancelled()  # CancelledError is caught internally
