# -*- coding: utf-8 -*-
"""Tests for the DashScope provider's oversized-media capping formatter.

agentscope's base DashScope formatter reads every local ``file://`` media
source off disk and base64-encodes the entire file into the request body
on every API call.  For a large file persisted in conversation history
(e.g. a generated video) this balloons the request and the provider drops
the connection on every subsequent turn.  The capping formatter
substitutes a text placeholder for oversized media so the model request
stays small, while leaving small media and persisted history untouched.

The cap threshold is the provider's configurable ``max_inline_media_bytes``
field; ``0`` disables capping.
"""
# pylint: disable=protected-access
from __future__ import annotations

import base64

from qwenpaw.providers.dashscope_provider import (
    _CappingDashScopeFormatter,
    MAX_INLINE_MEDIA_BYTES,
)


def _base64_source(size: int, media_type: str):
    """Build the in-memory source produced by async media preparation."""
    from agentscope.message import Base64Source

    data = base64.b64encode(b"\0" * size).decode("ascii")
    return Base64Source(data=data, media_type=media_type)


def test_prepared_media_size_is_measured() -> None:
    source = _base64_source(1023, "video/mp4")
    assert _CappingDashScopeFormatter._inline_media_size(source) == 1023


def test_remote_url_is_not_inlined() -> None:
    from agentscope.message import URLSource

    source = URLSource(url="https://example.com/v.mp4", media_type="video/mp4")
    assert _CappingDashScopeFormatter._inline_media_size(source) is None


def test_oversized_video_is_replaced_with_text_placeholder() -> None:
    source = _base64_source(MAX_INLINE_MEDIA_BYTES + 1, "video/mp4")
    out = _CappingDashScopeFormatter()._format_video_source(
        source,
    )
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_small_image_passes_through() -> None:
    source = _base64_source(2048, "image/jpeg")
    out = _CappingDashScopeFormatter()._format_image_source(
        source,
    )
    assert out["type"] == "image_url"
    assert out["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_remote_video_passes_through_unchanged() -> None:
    from agentscope.message import URLSource

    out = _CappingDashScopeFormatter()._format_video_source(
        URLSource(url="https://cdn.example.com/v.mp4", media_type="video/mp4"),
    )
    assert out == {
        "type": "video_url",
        "video_url": {"url": "https://cdn.example.com/v.mp4"},
    }


def test_missing_file_is_passed_through_to_base() -> None:
    # Unprepared local URLs must not reach AgentScope's synchronous reader.
    from agentscope.message import URLSource

    source = URLSource(
        url="file:///nonexistent/does-not-exist.mp4",
        media_type="video/mp4",
    )
    assert _CappingDashScopeFormatter._inline_media_size(source) is None
    out = _CappingDashScopeFormatter()._format_video_source(source)
    assert out["type"] == "text"
    assert "preparation was bypassed" in out["text"]


def test_custom_threshold_is_honored() -> None:
    # A 4 KB file is well under the 2 MB default, but a 1 KB threshold
    # should cap it — proving the per-provider threshold is honored.
    source = _base64_source(4096, "video/mp4")
    assert _CappingDashScopeFormatter()._maybe_cap(source, "video") is None
    assert (
        _CappingDashScopeFormatter(max_bytes=1024)._maybe_cap(source, "video")
        is not None
    )


def test_zero_threshold_disables_capping() -> None:
    source = _base64_source(MAX_INLINE_MEDIA_BYTES + 1, "video/mp4")
    # max_bytes=0 means disabled -> never capped, defer to base formatter.
    assert (
        _CappingDashScopeFormatter(max_bytes=0)._maybe_cap(source, "video")
        is None
    )
    out = _CappingDashScopeFormatter(max_bytes=0)._format_video_source(source)
    assert out["type"] == "video_url"
