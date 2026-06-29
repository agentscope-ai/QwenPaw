# -*- coding: utf-8 -*-
"""Tests for the shared capping-formatter module.

agentscope's chat formatters (OpenAI, Anthropic, Gemini, DashScope) all read
every local ``file://`` media source off disk and base64-encode the entire
file into the request body on every API call.  For a large file persisted in
conversation history this balloons the request and the provider drops the
connection on every subsequent turn.  The shared
:mod:`qwenpaw.providers.capping_formatter` substitutes a text placeholder for
oversized media so the request stays small, while leaving small media,
remote URLs, and persisted history untouched.

These tests cover the shared helpers and each per-provider capping formatter
directly; the provider-level wiring (the field reaching
``model.formatter.max_bytes``) is covered in ``test_provider_manager.py``.
"""

# pylint: disable=protected-access
from __future__ import annotations

import pytest

from qwenpaw.providers.capping_formatter import (
    MAX_INLINE_MEDIA_BYTES,
    _CappingAnthropicFormatter,
    _CappingDashScopeFormatter,
    _CappingGeminiFormatter,
    _CappingOpenAIFormatter,
    inline_media_size,
)

_ALL_CAPPING_FORMATTERS = [
    _CappingOpenAIFormatter,
    _CappingAnthropicFormatter,
    _CappingGeminiFormatter,
    _CappingDashScopeFormatter,
]


def _write(tmp_path, name: str, size: int) -> str:
    path = tmp_path / name
    path.write_bytes(b"\0" * size)
    return path.as_uri()


# ---------------------------------------------------------------------------
# inline_media_size
# ---------------------------------------------------------------------------


def test_local_file_size_is_measured(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "clip.mp4", 1024)
    source = URLSource(url=url, media_type="video/mp4")
    assert inline_media_size(source) == 1024


def test_remote_url_is_not_inlined() -> None:
    from agentscope.message import URLSource

    source = URLSource(url="https://example.com/v.mp4", media_type="video/mp4")
    assert inline_media_size(source) is None


def test_missing_file_returns_none() -> None:
    from agentscope.message import URLSource

    source = URLSource(
        url="file:///nonexistent/does-not-exist.mp4",
        media_type="video/mp4",
    )
    assert inline_media_size(source) is None


def test_base64_source_size_approximated() -> None:
    from agentscope.message import Base64Source

    # 8 base64 chars -> ~6 raw bytes.
    source = Base64Source(data="AAAAAAAA", media_type="image/png")
    assert inline_media_size(source) == 6


def test_unknown_source_returns_none() -> None:
    assert inline_media_size(object()) is None


# ---------------------------------------------------------------------------
# CappingFormatterMixin._maybe_cap
# ---------------------------------------------------------------------------


def test_maybe_cap_returns_none_within_limit(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "small.mp4", 1024)
    source = URLSource(url=url, media_type="video/mp4")
    assert _CappingDashScopeFormatter()._maybe_cap(source, "video") is None


def test_maybe_cap_returns_placeholder_over_limit(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "big.mp4", MAX_INLINE_MEDIA_BYTES + 1)
    source = URLSource(url=url, media_type="video/mp4")
    capped = _CappingDashScopeFormatter()._maybe_cap(source, "video")
    assert capped is not None
    assert "omitted" in capped["text"]


def test_maybe_cap_custom_threshold(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "clip.mp4", 4096)
    source = URLSource(url=url, media_type="video/mp4")
    assert _CappingDashScopeFormatter()._maybe_cap(source, "video") is None
    assert (
        _CappingDashScopeFormatter(max_bytes=1024)._maybe_cap(source, "video")
        is not None
    )


def test_maybe_cap_zero_disables(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "big.mp4", MAX_INLINE_MEDIA_BYTES + 1)
    source = URLSource(url=url, media_type="video/mp4")
    assert (
        _CappingDashScopeFormatter(max_bytes=0)._maybe_cap(source, "video")
        is None
    )


def test_maybe_cap_remote_url_not_capped() -> None:
    from agentscope.message import URLSource

    source = URLSource(
        url="https://cdn.example.com/v.mp4",
        media_type="video/mp4",
    )
    assert _CappingDashScopeFormatter()._maybe_cap(source, "video") is None


# ---------------------------------------------------------------------------
# Default field on every capping formatter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", _ALL_CAPPING_FORMATTERS)
def test_default_max_bytes(cls) -> None:
    assert cls().max_bytes == MAX_INLINE_MEDIA_BYTES
    assert cls(max_bytes=1024).max_bytes == 1024


# ---------------------------------------------------------------------------
# Per-formatter: oversized -> provider-shaped text placeholder;
#                within-limit / remote -> passthrough to base formatter.
# ---------------------------------------------------------------------------


def test_openai_oversized_image_capped(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "big.jpg", MAX_INLINE_MEDIA_BYTES + 1)
    out = _CappingOpenAIFormatter()._format_image_source(
        URLSource(url=url, media_type="image/jpeg"),
    )
    # OpenAI wire format uses {"type": "text", "text": ...}.
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_openai_small_image_passthrough(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "thumb.jpg", 2048)
    out = _CappingOpenAIFormatter()._format_image_source(
        URLSource(url=url, media_type="image/jpeg"),
    )
    assert out["type"] == "image_url"
    assert out["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openai_oversized_audio_capped(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "big.wav", MAX_INLINE_MEDIA_BYTES + 1)
    out = _CappingOpenAIFormatter()._format_audio_source(
        URLSource(url=url, media_type="audio/wav"),
    )
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_anthropic_oversized_image_capped(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "big.png", MAX_INLINE_MEDIA_BYTES + 1)
    out = _CappingAnthropicFormatter()._format_image_source(
        URLSource(url=url, media_type="image/png"),
    )
    # Anthropic wire format uses {"type": "text", "text": ...}.
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_anthropic_small_image_passthrough(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "thumb.png", 2048)
    out = _CappingAnthropicFormatter()._format_image_source(
        URLSource(url=url, media_type="image/png"),
    )
    assert out["type"] == "image"
    assert out["source"]["type"] == "base64"


def test_gemini_oversized_media_capped_with_text_part(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "big.mp4", MAX_INLINE_MEDIA_BYTES + 1)
    out = _CappingGeminiFormatter()._format_media_source(
        URLSource(url=url, media_type="video/mp4"),
    )
    # Gemini part shape is {"text": ...}, NOT {"type": "text", ...}.
    assert out == {"text": out["text"]}
    assert "omitted" in out["text"]
    assert "type" not in out


def test_gemini_small_media_passthrough(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "thumb.jpg", 2048)
    out = _CappingGeminiFormatter()._format_media_source(
        URLSource(url=url, media_type="image/jpeg"),
    )
    assert "inline_data" in out
    assert out["inline_data"]["mime_type"] == "image/jpeg"


def test_dashscope_oversized_video_capped(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "big.mp4", MAX_INLINE_MEDIA_BYTES + 1)
    out = _CappingDashScopeFormatter()._format_video_source(
        URLSource(url=url, media_type="video/mp4"),
    )
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_dashscope_remote_video_passthrough_unchanged() -> None:
    from agentscope.message import URLSource

    out = _CappingDashScopeFormatter()._format_video_source(
        URLSource(url="https://cdn.example.com/v.mp4", media_type="video/mp4"),
    )
    assert out == {
        "type": "video_url",
        "video_url": {"url": "https://cdn.example.com/v.mp4"},
    }
