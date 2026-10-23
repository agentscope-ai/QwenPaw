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
def test_qq_sanitize_text_strips_urls(monkeypatch) -> None:
    """URLs are replaced and flagged for plain QQ messages."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/qq"),
    )
    from qwenpaw_channel_qq.formatting import _sanitize_qq_text

    text, removed = _sanitize_qq_text("see https://a.com/x ok")
    assert removed is True
    assert "https://a.com" not in text
    assert "see" in text and "ok" in text


@pytest.mark.integration
@pytest.mark.p1
def test_qq_aggressive_sanitize_bare_domains(monkeypatch) -> None:
    """Bare domain patterns are caught by the aggressive variant."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/qq"),
    )
    from qwenpaw_channel_qq.formatting import (
        _aggressive_sanitize_qq_text,
    )

    text, removed = _aggressive_sanitize_qq_text("visit www.example.com now")
    assert removed is True
    assert "www.example.com" not in text


@pytest.mark.integration
@pytest.mark.p1
def test_qq_as_bool_variants(monkeypatch) -> None:
    """Boolean coercion handles bool, string, and truthy values."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/qq"),
    )
    from qwenpaw_channel_qq.formatting import _as_bool

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
def test_qq_recoverable_ws_os_error(monkeypatch) -> None:
    """Connection abort/reset/pipe errors are recoverable."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/qq"),
    )
    from qwenpaw_channel_qq.platform import (
        _is_recoverable_ws_os_error,
    )

    assert _is_recoverable_ws_os_error(ConnectionAbortedError()) is True
    assert _is_recoverable_ws_os_error(ConnectionResetError()) is True
    assert _is_recoverable_ws_os_error(BrokenPipeError()) is True
    assert _is_recoverable_ws_os_error(OSError("plain")) is False


# ------------------------------------------------------------------ #
# Telegram channel
# ------------------------------------------------------------------ #


@pytest.fixture
def telegram_helpers(monkeypatch):
    import importlib
    from pathlib import Path

    payload_root = (
        Path(__file__).resolve().parents[2] / "plugins/channel/telegram"
    )
    monkeypatch.syspath_prepend(str(payload_root))
    module = importlib.import_module("qwenpaw_channel_telegram.platform")
    assert Path(module.__file__).resolve().is_relative_to(payload_root)
    return module


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_base_urls(telegram_helpers) -> None:
    """Base URLs derive bot and file endpoints."""
    _telegram_base_urls = telegram_helpers._telegram_base_urls

    bot_url, file_url = _telegram_base_urls("https://api.example.com/")
    assert bot_url == "https://api.example.com/bot"
    assert file_url == "https://api.example.com/file/bot"


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_base_urls_empty(telegram_helpers) -> None:
    """Empty base yields empty endpoints."""
    _telegram_base_urls = telegram_helpers._telegram_base_urls

    assert _telegram_base_urls("") == ("", "")
    assert _telegram_base_urls("   ") == ("", "")


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_chunk_text_long_splits(telegram_helpers) -> None:
    """Long text splits at whitespace near the limit."""
    TELEGRAM_SEND_CHUNK_SIZE = telegram_helpers.TELEGRAM_SEND_CHUNK_SIZE
    _chunk_text = telegram_helpers._chunk_text

    text = ("word " * 2000).strip()
    chunks = _chunk_text(text)
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
def test_matrix_md_to_html_basic(monkeypatch) -> None:
    """Markdown renders to HTML with bold and escapes raw HTML."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/matrix"),
    )
    from qwenpaw_channel_matrix.platform import _md_to_html

    html = _md_to_html("**bold** and <script>")
    assert "<strong>bold</strong>" in html
    assert "<script>" not in html  # raw html escaped


@pytest.mark.integration
@pytest.mark.p1
def test_matrix_derive_device_id(monkeypatch) -> None:
    """Device id falls back to the stripped device name."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/matrix"),
    )
    from qwenpaw_channel_matrix.platform import MatrixPlatform

    derive = MatrixPlatform._derive_device_id_from_name
    assert derive("  my-device  ") == "my-device"
    assert derive("") == ""
    assert derive(None) == ""


# ------------------------------------------------------------------ #
# Discord channel
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_discord_classify_attachment_by_content_type(monkeypatch) -> None:
    """content_type drives attachment classification."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/discord"),
    )
    from qwenpaw_channel_discord import formatting

    class Attachment:
        def __init__(self, content_type, filename):
            self.content_type = content_type
            self.filename = filename

    classify = formatting.classify_attachment
    assert classify(Attachment("image/png", "a.png")) == "image"
    assert classify(Attachment("video/mp4", "v.mp4")) == "video"
    assert classify(Attachment("audio/mpeg", "a.mp3")) == "audio"


@pytest.mark.integration
@pytest.mark.p1
def test_discord_classify_attachment_by_filename(monkeypatch) -> None:
    """Filename MIME guessing is the fallback."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/discord"),
    )
    from qwenpaw_channel_discord import formatting

    class Attachment:
        def __init__(self, content_type, filename):
            self.content_type = content_type
            self.filename = filename

    classify = formatting.classify_attachment
    assert classify(Attachment("", "photo.jpg")) == "image"
    assert classify(Attachment("", "data.bin")) == "file"


@pytest.mark.integration
@pytest.mark.p1
def test_discord_chunk_text_long_preserves_content(monkeypatch) -> None:
    """Long text splits without losing content."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/discord"),
    )
    from qwenpaw_channel_discord import formatting

    text = "\n".join(f"line {i}" for i in range(500))
    chunks = formatting.chunk_text(text, max_len=200)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 200 + 16  # retain the original bound
    assert "\n".join(chunks) == text


# ------------------------------------------------------------------ #
# WeChat / WeCom / Yuanbao handle parsing
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_wechat_parse_user_id_from_handle() -> None:
    """Legacy handles use the real private Driver; empty is strict."""
    from pathlib import Path
    import sys

    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[2] / "plugins/channel/wechat"),
    )
    from qwenpaw_channel_wechat.driver import WeChatDriver

    for handle, expected in (
        ("wechat:group:G1", "G1"),
        ("wechat:U1", "U1"),
        ("raw-id", "raw-id"),
    ):
        assert (
            WeChatDriver._target(handle, {})["wechat_from_user_id"] == expected
        )
    with pytest.raises(ValueError, match="OUTBOUND_TARGET_UNKNOWN"):
        WeChatDriver._target("", {})


@pytest.mark.integration
@pytest.mark.p1
def test_wechat_to_handle_from_target() -> None:
    """Opaque protocol target retains original session and user values."""
    from qwenpaw.channel_protocol.targets import (
        decode_reply_target,
        encode_reply_target,
    )

    target = encode_reply_target(user_id="u1", session_id="s1")
    assert decode_reply_target(target) == {"user_id": "u1", "session_id": "s1"}
    target = encode_reply_target(user_id="u1", session_id="")
    assert decode_reply_target(target) == {"user_id": "u1", "session_id": ""}


@pytest.mark.integration
@pytest.mark.p1
def test_wecom_parse_chatid_from_handle(monkeypatch) -> None:
    """Chat id extracted from wecom handle prefixes."""
    from pathlib import Path

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/channel/wecom"),
    )
    from qwenpaw_channel_wecom.inbound import parse_chatid_from_handle

    parse = parse_chatid_from_handle
    assert parse("wecom:group:C1") == "C1"
    assert parse("wecom:U1") == "U1"
    assert parse("plain") == "plain"
