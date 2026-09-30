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

import asyncio

import pytest

from agentscope.message import Base64Source, DataBlock, Msg, TextBlock

from qwenpaw.providers.capping_formatter import (
    MAX_INLINE_MEDIA_BYTES,
    MAX_TOTAL_INLINE_MEDIA_BYTES,
    _CappingAnthropicFormatter,
    _CappingDashScopeFormatter,
    _CappingGeminiFormatter,
    _CappingOpenAIFormatter,
    _CappingOpenAIResponseFormatter,
    _request_media_budget,
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


# ---------------------------------------------------------------------------
# Cumulative per-request media budget
# ---------------------------------------------------------------------------

# A source sized so base64 rounding stays comfortably under the per-file cap
# used below, so only the cumulative budget can fire.
_EACH_IMAGE_BYTES = 512


def _image_msg(index: int, size: int = _EACH_IMAGE_BYTES) -> Msg:
    """A user message carrying one in-memory image block."""
    return Msg(
        name="user",
        role="user",
        content=[
            TextBlock(text=f"look at this {index}"),
            DataBlock(
                source=_base64_source(size, "image/png"),
                name=f"img{index}.png",
            ),
        ],
    )


def _wire_parts(messages: list[dict]) -> list[dict]:
    """Flatten a formatted request into its content parts.

    Chat Completions / Anthropic use ``content``; Gemini uses ``parts``.
    """
    parts: list[dict] = []
    for message in messages:
        blocks = message.get("content", message.get("parts"))
        if isinstance(blocks, str):
            parts.append({"type": "text", "text": blocks})
        elif isinstance(blocks, list):
            parts.extend(blocks)
    return parts


def _total_limit_placeholders(parts: list[dict]) -> list[dict]:
    return [
        part
        for part in parts
        if "per-request limit" in (part.get("text") or "")
    ]


# Keys each provider uses to carry an actually-inlined media payload.
_MEDIA_PAYLOAD_KEYS = ("inline_data", "image_url", "source", "input_audio")


def _media_parts(parts: list[dict]) -> list[dict]:
    return [
        part for part in parts if any(k in part for k in _MEDIA_PAYLOAD_KEYS)
    ]


class TestCumulativeBudget:
    """A request may not inline unbounded media (#7671 / the #7965 TODO)."""

    def test_default_total_budget_scales_with_the_per_file_cap(self) -> None:
        assert MAX_TOTAL_INLINE_MEDIA_BYTES == 4 * MAX_INLINE_MEDIA_BYTES

    def test_budget_spends_down_and_then_caps(self) -> None:
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )
        token = formatter._begin_media_budget()
        try:
            image = _base64_source(_EACH_IMAGE_BYTES, "image/png")
            assert formatter._maybe_cap_total(image, "image") is None

            # The second image no longer fits: the budget is exhausted.
            capped = formatter._maybe_cap_total(image, "image")
            assert capped is not None
            assert "per-request limit" in capped["text"]
            assert "900-byte" in capped["text"]
        finally:
            formatter._end_media_budget(token)

    def test_media_over_the_per_file_cap_is_never_charged(self) -> None:
        """An oversized file is capped per-file, so it costs no budget."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=512,
            max_total_bytes=4096,
        )
        token = formatter._begin_media_budget()
        try:
            capped = formatter._cap_media(
                _base64_source(4096, "image/png"),
                "image",
            )
            # The per-file placeholder fires, not the cumulative one.
            assert "inline limit of 512 bytes" in capped["text"]
            # ...so nothing was charged to the budget.
            assert (
                formatter._cap_media(
                    _base64_source(64, "image/png"),
                    "image",
                )
                is None
            )
        finally:
            formatter._end_media_budget(token)

    def test_undersized_media_still_spends_the_budget(self) -> None:
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )
        token = formatter._begin_media_budget()
        try:
            assert (
                formatter._cap_media(
                    _base64_source(_EACH_IMAGE_BYTES, "image/png"),
                    "image",
                )
                is None
            )
            # The budget really was spent.
            assert (
                formatter._cap_media(
                    _base64_source(_EACH_IMAGE_BYTES, "image/png"),
                    "image",
                )
                is not None
            )
        finally:
            formatter._end_media_budget(token)

    def test_no_budget_outside_format_keeps_legacy_behaviour(self) -> None:
        formatter = _CappingOpenAIFormatter(max_total_bytes=1)
        assert (
            formatter._maybe_cap_total(
                _base64_source(64, "image/png"),
                "image",
            )
            is None
        )

    def test_zero_total_disables_the_budget(self) -> None:
        assert (
            _CappingOpenAIFormatter(max_total_bytes=0)._begin_media_budget()
            is None
        )

    def test_budget_is_restored_on_every_request(self) -> None:
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )
        image = _base64_source(_EACH_IMAGE_BYTES, "image/png")

        first = formatter._begin_media_budget()
        formatter._maybe_cap_total(image, "image")
        formatter._end_media_budget(first)

        second = formatter._begin_media_budget()
        try:
            # A fresh request gets the whole budget back.
            assert formatter._maybe_cap_total(image, "image") is None
        finally:
            formatter._end_media_budget(second)

    def test_ending_a_budget_clears_the_context(self) -> None:
        formatter = _CappingOpenAIFormatter(max_total_bytes=4096)
        token = formatter._begin_media_budget()
        formatter._end_media_budget(token)
        assert _request_media_budget.get() is None


class TestCumulativeBudgetEndToEnd:
    """Drive the real formatters so the budget is exercised in context."""

    @pytest.mark.parametrize(
        "formatter_cls",
        _ALL_CAPPING_FORMATTERS,
    )
    @pytest.mark.asyncio
    async def test_oldest_media_dropped_newest_kept(
        self,
        formatter_cls,
    ) -> None:
        """Formatting walks oldest-first, so the newest media survives."""
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=900)
        messages = [_image_msg(i) for i in range(3)]

        parts = _wire_parts(await formatter.format(messages))

        placeholders = _total_limit_placeholders(parts)
        assert len(placeholders) == 2
        assert "900-byte" in placeholders[0]["text"]
        # Exactly one image is still inlined: the newest one.
        assert len(_media_parts(parts)) == 1

    @pytest.mark.asyncio
    async def test_under_budget_nothing_is_capped(self) -> None:
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=8192,
        )

        parts = _wire_parts(
            await formatter.format([_image_msg(0), _image_msg(1)]),
        )

        assert not _total_limit_placeholders(parts)

    @pytest.mark.asyncio
    async def test_disabled_budget_inlines_everything(self) -> None:
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=0,
        )

        parts = _wire_parts(
            await formatter.format([_image_msg(i) for i in range(5)]),
        )

        assert not _total_limit_placeholders(parts)

    @pytest.mark.asyncio
    async def test_budget_is_spent_afresh_on_every_call(self) -> None:
        """A long-lived formatter must not carry a spent budget forward."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )
        messages = [_image_msg(i) for i in range(3)]

        first = await formatter.format(messages)
        second = await formatter.format(messages)

        assert _wire_parts(first) == _wire_parts(second)

    @pytest.mark.asyncio
    async def test_responses_formatter_uses_input_text_placeholder(
        self,
    ) -> None:
        """The Responses API placeholder must match its own wire shape."""
        formatter = _CappingOpenAIResponseFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )

        parts = _wire_parts(
            await formatter.format([_image_msg(i) for i in range(3)]),
        )

        placeholders = _total_limit_placeholders(parts)
        assert len(placeholders) == 2
        assert all(part.get("type") == "input_text" for part in placeholders)

    @pytest.mark.asyncio
    async def test_concurrent_requests_do_not_share_a_budget(self) -> None:
        """Two sessions on one formatter must not starve each other."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )
        single = [_image_msg(0)]

        results = await asyncio.gather(
            formatter.format(single),
            formatter.format(single),
            formatter.format(single),
        )

        for formatted in results:
            assert not _total_limit_placeholders(_wire_parts(formatted))
