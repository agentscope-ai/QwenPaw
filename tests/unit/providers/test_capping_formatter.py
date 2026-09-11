# -*- coding: utf-8 -*-
"""Tests for the shared capping-formatter module.

The request formatter prepares local media outside the event loop and hands
these formatters in-memory ``Base64Source`` objects. The shared capping layer
then substitutes provider-shaped text placeholders for oversized data.

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


def _base64_source(size: int, media_type: str):
    """Build an in-memory source with an approximate raw byte size."""
    from agentscope.message import Base64Source

    encoded_size = ((size + 2) // 3) * 4
    return Base64Source(data="A" * encoded_size, media_type=media_type)


# ---------------------------------------------------------------------------
# inline_media_size
# ---------------------------------------------------------------------------


def test_url_source_size_is_left_to_async_preparation(tmp_path) -> None:
    from agentscope.message import URLSource

    url = _write(tmp_path, "clip.mp4", 1024)
    source = URLSource(url=url, media_type="video/mp4")
    assert inline_media_size(source) is None


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


def test_maybe_cap_returns_none_within_limit() -> None:
    source = _base64_source(1023, "video/mp4")
    assert _CappingDashScopeFormatter()._maybe_cap(source, "video") is None


def test_maybe_cap_returns_placeholder_over_limit() -> None:
    source = _base64_source(MAX_INLINE_MEDIA_BYTES + 4, "video/mp4")
    capped = _CappingDashScopeFormatter()._maybe_cap(source, "video")
    assert capped is not None
    assert "omitted" in capped["text"]


def test_maybe_cap_custom_threshold() -> None:
    source = _base64_source(4095, "video/mp4")
    assert _CappingDashScopeFormatter()._maybe_cap(source, "video") is None
    assert (
        _CappingDashScopeFormatter(max_bytes=1024)._maybe_cap(source, "video")
        is not None
    )


def test_maybe_cap_zero_disables() -> None:
    source = _base64_source(MAX_INLINE_MEDIA_BYTES + 4, "video/mp4")
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


def test_openai_oversized_image_capped() -> None:
    out = _CappingOpenAIFormatter()._format_image_source(
        _base64_source(MAX_INLINE_MEDIA_BYTES + 4, "image/jpeg"),
    )
    # OpenAI wire format uses {"type": "text", "text": ...}.
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_openai_small_image_passthrough() -> None:
    out = _CappingOpenAIFormatter()._format_image_source(
        _base64_source(2046, "image/jpeg"),
    )
    assert out["type"] == "image_url"
    assert out["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openai_oversized_audio_capped() -> None:
    out = _CappingOpenAIFormatter()._format_audio_source(
        _base64_source(MAX_INLINE_MEDIA_BYTES + 4, "audio/wav"),
    )
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_anthropic_oversized_image_capped() -> None:
    out = _CappingAnthropicFormatter()._format_source(
        _base64_source(MAX_INLINE_MEDIA_BYTES + 4, "image/png"),
        "image",
    )
    # Anthropic wire format uses {"type": "text", "text": ...}.
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_anthropic_small_image_passthrough() -> None:
    out = _CappingAnthropicFormatter()._format_source(
        _base64_source(2046, "image/png"),
        "image",
    )
    assert out["type"] == "image"
    assert out["source"]["type"] == "base64"


def test_anthropic_oversized_pdf_capped() -> None:
    out = _CappingAnthropicFormatter()._format_source(
        _base64_source(
            MAX_INLINE_MEDIA_BYTES + 4,
            "application/pdf",
        ),
        "document",
    )
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_anthropic_small_pdf_passthrough() -> None:
    out = _CappingAnthropicFormatter()._format_source(
        _base64_source(2046, "application/pdf"),
        "document",
    )
    assert out["type"] == "document"
    assert out["source"]["type"] == "base64"


def test_gemini_oversized_media_capped_with_text_part() -> None:
    out = _CappingGeminiFormatter()._format_media_source(
        _base64_source(MAX_INLINE_MEDIA_BYTES + 4, "video/mp4"),
    )
    # Gemini part shape is {"text": ...}, NOT {"type": "text", ...}.
    assert out == {"text": out["text"]}
    assert "omitted" in out["text"]
    assert "type" not in out


def test_gemini_small_media_passthrough() -> None:
    out = _CappingGeminiFormatter()._format_media_source(
        _base64_source(2046, "image/jpeg"),
    )
    assert "inline_data" in out
    assert out["inline_data"]["mime_type"] == "image/jpeg"


def test_dashscope_oversized_video_capped() -> None:
    out = _CappingDashScopeFormatter()._format_video_source(
        _base64_source(MAX_INLINE_MEDIA_BYTES + 4, "video/mp4"),
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


# -----------------------------------------------------------------
# Bare local path support (after _fixup_media_list normalization)
# -----------------------------------------------------------------


def _source_with_bare_path(path, media_type: str):
    """Create URLSource then assign bare path (mimics _fixup_media_list)."""
    from agentscope.message import URLSource

    source = URLSource(url=f"file://{path}", media_type=media_type)
    source.url = str(path)
    return source


def test_bare_local_path_size_is_deferred(tmp_path) -> None:
    """Bare paths are measured by the asynchronous preparation stage."""
    path = tmp_path / "img.png"
    path.write_bytes(b"\x89PNG" + b"\0" * 500)
    source = _source_with_bare_path(path, "image/png")
    assert inline_media_size(source) is None


def test_prepared_image_is_formatted_without_file_access() -> None:
    """Prepared in-memory media produces the expected provider payload."""
    out = _CappingOpenAIFormatter()._format_image_source(
        _base64_source(54, "image/png"),
    )
    assert out["type"] == "image_url"
    assert out["image_url"]["url"].startswith("data:image/png;base64,")


def test_non_http_remote_scheme_passthrough() -> None:
    """s3://, oss://, ftp:// etc. pass through unchanged (#5934 H1)."""
    from agentscope.message import URLSource

    for scheme_url in [
        "s3://bucket/image.png",
        "oss://bucket/image.png",
        "ftp://host/file.txt",
    ]:
        source = URLSource(url=scheme_url, media_type="image/png")
        # inline_media_size must return None (not try getsize)
        assert inline_media_size(source) is None
