# -*- coding: utf-8 -*-
"""
Zalo Channel Unit Tests

Covers the helpers that have no I/O and are easy to test in isolation:
- Thinking/Null-text filtering (``_strip_thinking``, ``_strip_null_tokens``).
- Smart outbound text routing (``_extract_actions``).
- Photo/sticker/voice event payload extraction (``_dispatch_native_event``).

Tests for the actual HTTP client live in
``tests/contract/channels/test_zalo_contract.py`` and the integration
E2E flow is exercised against the live Zalo Bot Platform.
"""

# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


def test_strip_thinking_removes_standard_block():
    from qwenpaw.app.channels.zalo.channel import _strip_thinking

    text = "<think>\nLet me think...\nThis is reasoning.\n</think>\nDạ em chào anh/chị."
    assert _strip_thinking(text) == "Dạ em chào anh/chị."


def test_strip_thinking_removes_variant_block():
    from qwenpaw.app.channels.zalo.channel import _strip_thinking

    text = "<think>hidden</think>\nactual reply"
    assert _strip_thinking(text) == "actual reply"


def test_strip_thinking_handles_label_only_lines():
    from qwenpaw.app.channels.zalo.channel import _strip_thinking

    # Only lines that are themselves a label (e.g. "Reasoning:") get
    # stripped — the body text below is the model's reasoning output.
    text = "Reasoning:\nThis is reasoning text\n\nDạ em chào anh."
    stripped = _strip_thinking(text)
    assert "Dạ em chào anh." in stripped
    # The label line is gone.
    assert "\nReasoning:" not in stripped
    assert "\nReasoning" not in stripped


def test_strip_null_tokens_drops_lone_null():
    from qwenpaw.app.channels.zalo.channel import _strip_null_tokens

    assert _strip_null_tokens("null") == ""
    assert _strip_null_tokens("none") == ""
    assert _strip_null_tokens("None") == ""
    assert _strip_null_tokens("undefined") == ""
    assert _strip_null_tokens("nil") == ""
    assert _strip_null_tokens("nan") == ""
    assert _strip_null_tokens("n/a") == ""


def test_strip_null_tokens_drops_null_prefix_with_blank():
    from qwenpaw.app.channels.zalo.channel import _strip_null_tokens

    assert _strip_null_tokens("null\n\nDạ em chào anh.") == "Dạ em chào anh."
    assert _strip_null_tokens("None\nDạ em chào anh.") == "Dạ em chào anh."


def test_strip_null_tokens_keeps_real_text():
    from qwenpaw.app.channels.zalo.channel import _strip_null_tokens

    assert _strip_null_tokens("Dạ em chào anh/chị.") == "Dạ em chào anh/chị."
    assert _strip_null_tokens("Hello world") == "Hello world"


def test_strip_filters_combined():
    """Real-world combined case: thinking + null + real reply."""
    from qwenpaw.app.channels.zalo.channel import (
        _strip_null_tokens,
        _strip_thinking,
    )

    raw = "<think>\nreasoning here\n</think>\nnull\n\nDạ em chào anh/chị."
    out = _strip_null_tokens(_strip_thinking(raw))
    assert out == "Dạ em chào anh/chị."


# ---------------------------------------------------------------------------
# Smart outbound text routing
# ---------------------------------------------------------------------------


def test_extract_actions_magic_image_token():
    from qwenpaw.app.channels.zalo.channel import _extract_actions

    actions, leftover = _extract_actions(
        "[IMAGE: https://example.com/cat.png] Dạ đây ạ."
    )
    assert len(actions) == 1
    assert actions[0].kind == "photo"
    assert actions[0].payload == "https://example.com/cat.png"
    assert "Dạ đây ạ." in leftover


def test_extract_actions_magic_sticker_token():
    from qwenpaw.app.channels.zalo.channel import _extract_actions

    actions, leftover = _extract_actions("[STICKER: sticker_42_abc] hi")
    assert len(actions) == 1
    assert actions[0].kind == "sticker"
    assert actions[0].payload == "sticker_42_abc"


def test_extract_actions_magic_voice_token():
    from qwenpaw.app.channels.zalo.channel import _extract_actions

    actions, leftover = _extract_actions("[VOICE: https://x/y.ogg] ok")
    assert len(actions) == 1
    assert actions[0].kind == "voice"
    assert actions[0].payload == "https://x/y.ogg"


def test_extract_actions_bare_image_url():
    from qwenpaw.app.channels.zalo.channel import _extract_actions

    actions, leftover = _extract_actions("Look: https://example.com/cat.jpg")
    assert len(actions) == 1
    assert actions[0].kind == "photo"
    assert actions[0].payload == "https://example.com/cat.jpg"
    assert "Look:" in leftover


def test_extract_actions_markdown_image():
    from qwenpaw.app.channels.zalo.channel import _extract_actions

    actions, leftover = _extract_actions("![cat](https://example.com/cat.png) hello")
    assert len(actions) == 1
    assert actions[0].kind == "photo"
    assert actions[0].payload == "https://example.com/cat.png"


def test_extract_actions_plain_text_only():
    from qwenpaw.app.channels.zalo.channel import _extract_actions

    actions, leftover = _extract_actions("Xin chào anh/chị.")
    assert actions == []
    assert leftover.strip() == "Xin chào anh/chị."


def test_extract_actions_multiple_in_order():
    from qwenpaw.app.channels.zalo.channel import _extract_actions

    text = "[IMAGE: https://a/1.png] before [STICKER: s1] after"
    actions, leftover = _extract_actions(text)
    assert len(actions) == 2
    assert actions[0].kind == "photo"
    assert actions[1].kind == "sticker"
    assert "before" in leftover
    assert "after" in leftover


# ---------------------------------------------------------------------------
# _dispatch_native_event extraction (asserts on captured _enqueue payload)
# ---------------------------------------------------------------------------


def _build_channel():
    """Build a ZaloChannel instance with a captured _enqueue callable."""
    from qwenpaw.app.channels.zalo.channel import ZaloChannel

    process = MagicMock()
    captured: List[Dict[str, Any]] = []

    def _enqueue(payload):
        captured.append(payload)

    ch = ZaloChannel(
        process=process,
        bot_token="",
        poll_interval=999,
        show_typing=False,
    )
    ch._enqueue = _enqueue  # type: ignore[assignment]
    ch._captured = captured  # type: ignore[attr-defined]
    ch._client = None  # type: ignore[assignment]
    return ch


def _captured_payload(ch) -> Dict[str, Any]:
    assert (
        len(ch._captured) == 1
    ), f"expected 1 enqueued payload, got {len(ch._captured)}"
    return ch._captured[0]


def _texts(payload) -> List[str]:
    """Pull TextContent.text values out of a captured native payload."""
    out: List[str] = []
    for blk in payload["content_parts"]:
        text = getattr(blk, "text", None)
        if text is not None:
            out.append(text)
    return out


def _image_urls(payload) -> List[str]:
    """Pull ImageContent.image_url values out of a captured native payload."""
    out: List[str] = []
    for blk in payload["content_parts"]:
        url = getattr(blk, "image_url", None)
        if url is not None:
            out.append(url)
    return out


def test_dispatch_image_only_event():
    """Image-only event: agent gets a Vietnamese hint + image marker."""
    ch = _build_channel()
    native = {
        "event_name": "message.image.received",
        "message": {
            "chat": {"id": "c1", "chat_type": "PRIVATE"},
            "from": {"id": "u1", "display_name": "Anh Lâm"},
            "message_type": "CHAT_PHOTO",
            "photo_url": "https://cdn.example.com/photo.jpg",
            "caption": "",
            "message_id": "m1",
        },
    }
    ch._dispatch_native_event(native)

    payload = _captured_payload(ch)
    assert payload["sender_id"] == "u1"
    assert payload["meta"]["chat_id"] == "c1"

    texts = _texts(payload)
    urls = _image_urls(payload)

    # Image URL is preserved
    assert any("https://cdn.example.com/photo.jpg" == u for u in urls)
    # Vietnamese hint is added so the agent knows an image arrived
    assert any("URL: https://cdn.example.com/photo.jpg" in t for t in texts)


def test_dispatch_image_with_caption():
    ch = _build_channel()
    native = {
        "event_name": "message.image.received",
        "message": {
            "chat": {"id": "c1", "chat_type": "PRIVATE"},
            "from": {"id": "u1", "display_name": "Anh"},
            "message_type": "CHAT_PHOTO",
            "photo_url": "https://cdn.example.com/x.jpg",
            "caption": "bạn xem giúp",
            "message_id": "m2",
        },
    }
    ch._dispatch_native_event(native)

    payload = _captured_payload(ch)
    texts = _texts(payload)
    urls = _image_urls(payload)

    assert "bạn xem giúp" in " ".join(texts)
    assert any("https://cdn.example.com/x.jpg" == u for u in urls)


def test_dispatch_text_event():
    ch = _build_channel()
    native = {
        "event_name": "message.text.received",
        "message": {
            "chat": {"id": "c1", "chat_type": "PRIVATE"},
            "from": {"id": "u1", "display_name": "Anh"},
            "text": "hello",
            "message_id": "m3",
        },
    }
    ch._dispatch_native_event(native)

    payload = _captured_payload(ch)
    assert payload["sender_id"] == "u1"
    assert "hello" in " ".join(_texts(payload))


def test_dispatch_sticker_event():
    ch = _build_channel()
    native = {
        "event_name": "message.sticker.received",
        "message": {
            "chat": {"id": "c1", "chat_type": "PRIVATE"},
            "from": {"id": "u1", "display_name": "Anh"},
            "message_type": "STICKER",
            "sticker_id": "sticker_42",
            "message_id": "m4",
        },
    }
    ch._dispatch_native_event(native)

    payload = _captured_payload(ch)
    texts = _texts(payload)
    assert any("sticker_42" in t for t in texts)


def test_dispatch_voice_event():
    ch = _build_channel()
    native = {
        "event_name": "message.voice.received",
        "message": {
            "chat": {"id": "c1", "chat_type": "PRIVATE"},
            "from": {"id": "u1", "display_name": "Anh"},
            "message_type": "VOICE",
            "voice_url": "https://cdn.example.com/v.ogg",
            "message_id": "m5",
        },
    }
    ch._dispatch_native_event(native)

    payload = _captured_payload(ch)
    texts = _texts(payload)
    assert any("https://cdn.example.com/v.ogg" in t for t in texts)


def test_dispatch_file_event():
    ch = _build_channel()
    native = {
        "event_name": "message.file.received",
        "message": {
            "chat": {"id": "c1", "chat_type": "PRIVATE"},
            "from": {"id": "u1", "display_name": "Anh"},
            "attachment_url": "https://cdn.example.com/f.pdf",
            "attachment_name": "spec.pdf",
            "message_id": "m6",
        },
    }
    ch._dispatch_native_event(native)

    payload = _captured_payload(ch)
    texts = _texts(payload)
    assert any("spec.pdf" in t and "https://cdn.example.com/f.pdf" in t for t in texts)


def test_dispatch_unknown_event_still_enqueues_marker():
    ch = _build_channel()
    native = {
        "event_name": "message.unknown.received",
        "message": {
            "chat": {"id": "c1", "chat_type": "PRIVATE"},
            "from": {"id": "u1", "display_name": "Anh"},
            "message_id": "m7",
        },
    }
    ch._dispatch_native_event(native)

    payload = _captured_payload(ch)
    # Should not crash; should fall back to a placeholder marker.
    assert payload["sender_id"] == "u1"
    assert payload["content_parts"]


# ---------------------------------------------------------------------------
# Channel metadata
# ---------------------------------------------------------------------------


def test_channel_class_metadata():
    from qwenpaw.app.channels.zalo.channel import ZaloChannel

    assert ZaloChannel.channel == "zalo"
    assert ZaloChannel.uses_manager_queue is True


def test_channel_registered_in_builtin_registry():
    from qwenpaw.app.channels.registry import (
        BUILTIN_CHANNEL_KEYS,
        _load_builtin_channels,
    )

    assert "zalo" in BUILTIN_CHANNEL_KEYS
    assert "zalo" in _load_builtin_channels()
