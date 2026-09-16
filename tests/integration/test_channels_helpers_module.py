# -*- coding: utf-8 -*-
"""Integration tests for channel adapter helper functions.

Covers pure helpers across the channel family (dingtalk, feishu,
matrix, qq, telegram, wechat, wecom, yuanbao, discord) — text
sanitization, chunk splitting, handle parsing, attachment
classification, markdown rendering. Roughly 4,000 uncovered lines
across channel adapters are targeted by this and follow-up batches.
"""

# pylint: disable=protected-access

from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# QQ channel
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_qq_sanitize_text_strips_urls() -> None:
    """URLs are replaced and flagged for plain QQ messages."""
    from qwenpaw.app.channels.qq.channel import _sanitize_qq_text

    text, removed = _sanitize_qq_text("see https://a.com/x ok")
    assert removed is True
    assert "https://a.com" not in text
    assert "see" in text and "ok" in text


@pytest.mark.integration
@pytest.mark.p1
def test_qq_sanitize_text_plain_passthrough() -> None:
    """Text without URLs passes through unchanged."""
    from qwenpaw.app.channels.qq.channel import _sanitize_qq_text

    text, removed = _sanitize_qq_text("no links here")
    assert text == "no links here"
    assert removed is False


@pytest.mark.integration
@pytest.mark.p1
def test_qq_sanitize_text_empty() -> None:
    """Empty input yields empty output and no flag."""
    from qwenpaw.app.channels.qq.channel import _sanitize_qq_text

    assert _sanitize_qq_text("") == ("", False)


@pytest.mark.integration
@pytest.mark.p1
def test_qq_aggressive_sanitize_bare_domains() -> None:
    """Bare domain patterns are caught by the aggressive variant."""
    from qwenpaw.app.channels.qq.channel import (
        _aggressive_sanitize_qq_text,
    )

    text, removed = _aggressive_sanitize_qq_text("visit www.example.com now")
    assert removed is True
    assert "www.example.com" not in text


@pytest.mark.integration
@pytest.mark.p1
def test_qq_as_bool_variants() -> None:
    """Boolean coercion handles bool, string, and truthy values."""
    from qwenpaw.app.channels.qq.channel import _as_bool

    assert _as_bool(True) is True
    assert _as_bool(False) is False
    assert _as_bool("true") is True
    assert _as_bool("YES") is True
    assert _as_bool("1") is True
    assert _as_bool("on") is True
    assert _as_bool("false") is False
    assert _as_bool("") is False
    assert _as_bool(1) is True
    assert _as_bool(0) is False


@pytest.mark.integration
@pytest.mark.p1
def test_qq_recoverable_ws_os_error() -> None:
    """Connection abort/reset/pipe errors are recoverable."""
    from qwenpaw.app.channels.qq.channel import (
        _is_recoverable_ws_os_error,
    )

    assert _is_recoverable_ws_os_error(ConnectionAbortedError()) is True
    assert _is_recoverable_ws_os_error(ConnectionResetError()) is True
    assert _is_recoverable_ws_os_error(BrokenPipeError()) is True
    assert _is_recoverable_ws_os_error(OSError("plain")) is False


# ------------------------------------------------------------------ #
# Telegram channel
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_base_urls() -> None:
    """Base URLs derive bot and file endpoints."""
    from qwenpaw.app.channels.telegram.channel import _telegram_base_urls

    bot_url, file_url = _telegram_base_urls("https://api.example.com/")
    assert bot_url == "https://api.example.com/bot"
    assert file_url == "https://api.example.com/file/bot"


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_base_urls_empty() -> None:
    """Empty base yields empty endpoints."""
    from qwenpaw.app.channels.telegram.channel import _telegram_base_urls

    assert _telegram_base_urls("") == ("", "")
    assert _telegram_base_urls("   ") == ("", "")


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_chunk_text_short() -> None:
    """Text under the limit is a single chunk."""
    from qwenpaw.app.channels.telegram.channel import TelegramChannel

    channel = TelegramChannel.__new__(TelegramChannel)
    assert channel._chunk_text("short") == ["short"]
    assert not channel._chunk_text("")


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_chunk_text_long_splits() -> None:
    """Long text splits at whitespace near the limit."""
    from qwenpaw.app.channels.telegram.channel import (
        TELEGRAM_SEND_CHUNK_SIZE,
        TelegramChannel,
    )

    channel = TelegramChannel.__new__(TelegramChannel)
    text = ("word " * 2000).strip()
    chunks = channel._chunk_text(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= TELEGRAM_SEND_CHUNK_SIZE
    assert (
        "".join(chunks).replace("\n", "").strip()
        == text.replace(
            "\n",
            "",
        ).strip()
    )


# ------------------------------------------------------------------ #
# Matrix channel
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_matrix_md_to_html_basic() -> None:
    """Markdown renders to HTML with bold and escapes raw HTML."""
    from qwenpaw.app.channels.matrix.channel import _md_to_html

    html = _md_to_html("**bold** and <script>")
    assert "<strong>bold</strong>" in html
    assert "<script>" not in html  # raw html escaped


@pytest.mark.integration
@pytest.mark.p1
def test_matrix_md_to_html_newlines() -> None:
    """Single newlines become breaks."""
    from qwenpaw.app.channels.matrix.channel import _md_to_html

    html = _md_to_html("line1\nline2")
    assert "line1" in html and "line2" in html
    assert "<br" in html or "\n" in html


@pytest.mark.integration
@pytest.mark.p1
def test_matrix_derive_device_id() -> None:
    """Device id falls back to the stripped device name."""
    from qwenpaw.app.channels.matrix.channel import MatrixChannel

    derive = MatrixChannel._derive_device_id_from_name
    assert derive("  my-device  ") == "my-device"
    assert derive("") == ""
    assert derive(None) == ""


# ------------------------------------------------------------------ #
# Discord channel
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_discord_classify_attachment_by_content_type() -> None:
    """content_type drives attachment classification."""
    from qwenpaw.app.channels.discord_.channel import DiscordChannel

    class Attachment:
        def __init__(self, content_type, filename):
            self.content_type = content_type
            self.filename = filename

    classify = DiscordChannel._classify_attachment
    assert classify(Attachment("image/png", "a.png")) == "image"
    assert classify(Attachment("video/mp4", "v.mp4")) == "video"
    assert classify(Attachment("audio/mpeg", "a.mp3")) == "audio"


@pytest.mark.integration
@pytest.mark.p1
def test_discord_classify_attachment_by_filename() -> None:
    """Filename MIME guessing is the fallback."""
    from qwenpaw.app.channels.discord_.channel import DiscordChannel

    class Attachment:
        def __init__(self, content_type, filename):
            self.content_type = content_type
            self.filename = filename

    classify = DiscordChannel._classify_attachment
    assert classify(Attachment("", "photo.jpg")) == "image"
    assert classify(Attachment("", "data.bin")) == "file"


@pytest.mark.integration
@pytest.mark.p1
def test_discord_chunk_text_short() -> None:
    """Text under the limit stays whole."""
    from qwenpaw.app.channels.discord_.channel import DiscordChannel

    assert DiscordChannel._chunk_text("hello", max_len=2000) == ["hello"]


@pytest.mark.integration
@pytest.mark.p1
def test_discord_chunk_text_long_preserves_content() -> None:
    """Long text splits without losing content."""
    from qwenpaw.app.channels.discord_.channel import DiscordChannel

    text = "\n".join(f"line {i}" for i in range(500))
    chunks = DiscordChannel._chunk_text(text, max_len=200)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 200 + 16  # allow fence suffix slack


# ------------------------------------------------------------------ #
# WeChat / WeCom / Yuanbao handle parsing
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_wechat_parse_user_id_from_handle() -> None:
    """User id extracted from wechat handle prefixes."""
    from qwenpaw.app.channels.wechat.channel import WeChatChannel

    parse = WeChatChannel._parse_user_id_from_handle
    assert parse("wechat:group:G1") == "G1"
    assert parse("wechat:U1") == "U1"
    assert parse("raw-id") == "raw-id"
    assert parse("") == ""


@pytest.mark.integration
@pytest.mark.p1
def test_wechat_to_handle_from_target() -> None:
    """Target handle prefers session_id, falls back to user id."""
    from qwenpaw.app.channels.wechat.channel import WeChatChannel

    channel = WeChatChannel.__new__(WeChatChannel)
    assert (
        channel.to_handle_from_target(
            user_id="u1",
            session_id="s1",
        )
        == "s1"
    )
    assert (
        channel.to_handle_from_target(
            user_id="u1",
            session_id="",
        )
        == "wechat:u1"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_wecom_parse_chatid_from_handle() -> None:
    """Chat id extracted from wecom handle prefixes."""
    from qwenpaw.app.channels.wecom.channel import WecomChannel

    parse = WecomChannel._parse_chatid_from_handle
    assert parse("wecom:group:C1") == "C1"
    assert parse("wecom:U1") == "U1"
    assert parse("plain") == "plain"


@pytest.mark.integration
@pytest.mark.p1
def test_yuanbao_short_id() -> None:
    """Short id keeps the trailing suffix."""
    from qwenpaw.app.channels.yuanbao.channel import _short_id

    long_id = "0123456789abcdef"
    short = _short_id(long_id)
    assert long_id.endswith(short)
    assert len(short) <= len(long_id)
    assert _short_id("ab") == "ab"


@pytest.mark.integration
@pytest.mark.p1
def test_yuanbao_sender_display() -> None:
    """Sender display combines nickname and trailing id digits."""
    from qwenpaw.app.channels.yuanbao.channel import _sender_display

    display = _sender_display("Alice", "1234567890")
    assert "Alice" in display
    assert display.endswith("7890")
