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

from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    URLSource,
)

from qwenpaw.providers.capping_formatter import (
    MAX_INLINE_MEDIA_BYTES,
    MAX_TOTAL_INLINE_MEDIA_BYTES,
    _CappingAnthropicFormatter,
    _CappingDashScopeFormatter,
    _CappingGeminiFormatter,
    _CappingOpenAIFormatter,
    _CappingOpenAIResponseFormatter,
    _MediaBudget,
    _MediaOccurrence,
    _request_media_budget,
    inline_media_size,
    media_dedup_key,
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
    url = _write(tmp_path, "clip.mp4", 1024)
    source = URLSource(url=url, media_type="video/mp4")
    assert inline_media_size(source) is None


def test_remote_url_is_not_inlined() -> None:
    source = URLSource(url="https://example.com/v.mp4", media_type="video/mp4")
    assert inline_media_size(source) is None


def test_missing_file_returns_none() -> None:
    source = URLSource(
        url="file:///nonexistent/does-not-exist.mp4",
        media_type="video/mp4",
    )
    assert inline_media_size(source) is None


def test_base64_source_size_approximated() -> None:
    # 8 base64 chars -> ~6 raw bytes.
    source = Base64Source(data="AAAAAAAA", media_type="image/png")
    assert inline_media_size(source) == 6


def test_data_url_size_counted() -> None:
    """A base64 data: URL is inlined verbatim, so it is sized like a
    Base64Source (#8028 review: inline data: URLs bypassed the budget)."""
    payload = "A" * 684  # 684 base64 chars -> ~513 raw bytes
    source = URLSource(
        url=f"data:image/png;base64,{payload}",
        media_type="image/png",
    )
    assert inline_media_size(source) == 513


def test_percent_encoded_data_url_size_counted() -> None:
    source = URLSource(
        url="data:text/plain,hello%20world",
        media_type="text/plain",
    )
    assert inline_media_size(source) == 11


def test_malformed_data_url_returns_none() -> None:
    source = URLSource(url="data:image/png;base64,", media_type="image/png")
    assert inline_media_size(source) is None


def test_unknown_source_returns_none() -> None:
    assert inline_media_size(object()) is None


@pytest.mark.parametrize("data", [b"a", b"ab", b"abc"])
def test_base64_size_excludes_padding(data):
    import base64

    source = Base64Source(
        data=base64.b64encode(data).decode("ascii"),
        media_type="image/png",
    )
    assert inline_media_size(source) == len(data)


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


def test_openai_oversized_pdf_capped_per_file() -> None:
    """PDF attachments also obey the per-file cap, not only the budget."""
    out = _CappingOpenAIFormatter()._format_file_source(
        _base64_source(MAX_INLINE_MEDIA_BYTES + 4, "application/pdf"),
        "doc.pdf",
    )
    assert out["type"] == "text"
    assert "omitted" in out["text"]


def test_openai_small_pdf_passthrough() -> None:
    out = _CappingOpenAIFormatter()._format_file_source(
        _base64_source(2046, "application/pdf"),
        "doc.pdf",
    )
    assert out["type"] == "file"


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

# What _base64_source(_EACH_IMAGE_BYTES, ...) emits, and what
# inline_media_size therefore measures for it.
_B64_CHARS = ((_EACH_IMAGE_BYTES + 2) // 3) * 4
_MEASURED_BYTES = _B64_CHARS * 3 // 4


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


def _distinct_image_msg(index: int) -> Msg:
    """A user message carrying one image whose bytes differ per index.

    The Anthropic wire format deduplicates repeated media sources inside
    one request, so the production-path tests need media that differ from
    each other to exercise the budget rather than the dedup.
    """
    data = "A" * (_B64_CHARS - 1) + chr(ord("A") + index)
    return Msg(
        name="user",
        role="user",
        content=[
            TextBlock(text=f"look at this {index}"),
            DataBlock(
                source=Base64Source(data=data, media_type="image/png"),
                name=f"img{index}.png",
            ),
        ],
    )


def _seeded_image_msg(index: int, seed: str) -> Msg:
    """A user message carrying one image whose bytes end with *seed*.

    Two messages built with the same seed carry the same media source,
    so the Anthropic wire format treats the second one as a duplicate of
    the first.
    """
    data = "A" * (_B64_CHARS - 1) + seed
    return Msg(
        name="user",
        role="user",
        content=[
            TextBlock(text=f"look at this {index}"),
            DataBlock(
                source=Base64Source(data=data, media_type="image/png"),
                name=f"img{index}.png",
            ),
        ],
    )


def _tool_result_image_msgs(seed: str) -> list[Msg]:
    """An assistant tool call plus the tool result carrying one image."""
    tool_msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ToolCallBlock(
                id="call_1",
                name="view_image",
                input='{"path": "img.png"}',
            ),
            ToolResultBlock(
                id="call_1",
                name="view_image",
                output=[
                    TextBlock(text="here is the image"),
                    DataBlock(
                        source=Base64Source(
                            data="A" * (_B64_CHARS - 1) + seed,
                            media_type="image/png",
                        ),
                        name="img.png",
                    ),
                ],
            ),
        ],
    )
    return [tool_msg]


def _data_url_image_msg(index: int) -> Msg:
    """A user message carrying one inline ``data:`` URL image block."""
    return Msg(
        name="user",
        role="user",
        content=[
            TextBlock(text=f"look at this {index}"),
            DataBlock(
                source=URLSource(
                    url=f"data:image/png;base64,{'A' * _B64_CHARS}",
                    media_type="image/png",
                ),
                name=f"img{index}.png",
            ),
        ],
    )


def _pdf_msg(index: int) -> Msg:
    """A user message carrying one in-memory PDF attachment."""
    return Msg(
        name="user",
        role="user",
        content=[
            TextBlock(text=f"read this {index}"),
            DataBlock(
                source=_base64_source(_EACH_IMAGE_BYTES, "application/pdf"),
                name=f"doc{index}.pdf",
            ),
        ],
    )


def _wire_parts(messages: list[dict]) -> list[dict]:
    """Flatten a formatted request into its content parts.

    Chat Completions / Anthropic use ``content``; Gemini uses ``parts``.
    Tool results nest their own content list, which is flattened too so
    media returned by a tool is visible to the assertions.
    """
    parts: list[dict] = []
    for message in messages:
        blocks = message.get("content", message.get("parts"))
        if isinstance(blocks, str):
            parts.append({"type": "text", "text": blocks})
        elif isinstance(blocks, list):
            parts.extend(blocks)
    flattened: list[dict] = []
    for part in parts:
        nested = part.get("content")
        if isinstance(nested, list):
            flattened.extend(nested)
        flattened.append(part)
    return flattened


def _total_limit_placeholders(parts: list[dict]) -> list[dict]:
    return [
        part
        for part in parts
        if "per-request limit" in (part.get("text") or "")
    ]


def _duplicate_placeholders(parts: list[dict]) -> list[dict]:
    """Parts that fold a media source as a duplicate of an earlier one."""
    return [
        part
        for part in parts
        if "already shown above" in (part.get("text") or "")
    ]


# Keys each provider uses to carry an actually-inlined media payload.
# ``file`` / ``file_data`` cover OpenAI Chat and Responses PDF attachments.
_MEDIA_PAYLOAD_KEYS = (
    "inline_data",
    "image_url",
    "source",
    "input_audio",
    "file",
    "file_data",
)


def _media_parts(parts: list[dict]) -> list[dict]:
    return [
        part for part in parts if any(k in part for k in _MEDIA_PAYLOAD_KEYS)
    ]


def _media_payload(part: dict) -> str:
    """Return the base64 payload a media part carries.

    Anthropic nests it under ``source``, Chat Completions wraps it in a
    data URL under ``image_url``, and the Responses API puts the data
    URL directly under ``image_url``.
    """
    source = part.get("source")
    if isinstance(source, dict):
        return str(source.get("data") or "")
    image_url = part.get("image_url")
    if isinstance(image_url, dict):
        image_url = image_url.get("url")
    if isinstance(image_url, str):
        return image_url.rsplit(",", 1)[-1]
    inline_data = part.get("inline_data")
    if isinstance(inline_data, dict):
        return str(inline_data.get("data") or "")
    return ""


class TestCumulativeBudget:
    """A request may not inline unbounded media (#7671 / the #7965 TODO)."""

    def test_default_total_budget_scales_with_the_per_file_cap(self) -> None:
        assert MAX_TOTAL_INLINE_MEDIA_BYTES == 4 * MAX_INLINE_MEDIA_BYTES

    def test_measure_pass_records_sizes_without_capping(self) -> None:
        """The first pass records every sent occurrence, capping nothing."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=1,
        )
        source = _base64_source(_EACH_IMAGE_BYTES, "image/png")
        token = formatter._begin_media_budget()
        try:
            assert formatter._maybe_cap_total(source, "image") is None
            assert _request_media_budget.get().occurrences == [
                _MediaOccurrence(
                    key=media_dedup_key(source),
                    size=_MEASURED_BYTES,
                    folded=False,
                ),
            ]
        finally:
            formatter._end_media_budget(token)

    def test_enforce_pass_drops_the_planned_oldest_prefix(self) -> None:
        """Occurrences inside ``dropped_before`` are replaced with
        placeholders; the first occurrence past it is kept and spends
        the budget."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )
        image = _base64_source(_EACH_IMAGE_BYTES, "image/png")
        token = _request_media_budget.set(
            _MediaBudget(remaining=900, dropped_before=1),
        )
        try:
            dropped = formatter._maybe_cap_total(image, "image")
            assert dropped is not None
            assert "per-request limit" in dropped["text"]
            assert "900-byte" in dropped["text"]

            assert formatter._maybe_cap_total(image, "image") is None
        finally:
            _request_media_budget.reset(token)

    def test_folded_duplicate_costs_no_budget_until_reinflated(self) -> None:
        """The plan charges only the deduplicated payload: a folded
        duplicate costs nothing while its source is still on the wire,
        and a folded copy is re-inlined once every earlier copy of its
        source is dropped."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )
        key_a = ("base64", "image/png", "A")
        key_b = ("base64", "image/png", "B")

        # A -> B -> A(dup): dropping the two oldest occurrences re-inlines
        # the newest A, so the surviving payload is 512 bytes, not 1024.
        repeated = [
            _MediaOccurrence(key=key_a, size=512, folded=False),
            _MediaOccurrence(key=key_b, size=512, folded=False),
            _MediaOccurrence(key=key_a, size=512, folded=True),
        ]
        assert formatter._plan_dropped_prefix(repeated) == 2

        deduped = [
            _MediaOccurrence(key=key_a, size=512, folded=False),
            _MediaOccurrence(key=key_b, size=512, folded=False),
            _MediaOccurrence(key=key_b, size=512, folded=True),
        ]
        # A -> B -> B(dup): the folded duplicate sends nothing, so the
        # deduplicated payload is A + B = 1024 <= 1200 at this budget —
        # nothing needs to be dropped at all.
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=1200,
        )
        assert formatter._plan_dropped_prefix(deduped) == 0

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
            assert _request_media_budget.get().occurrences == []

            # A source within the per-file cap *is* measured by the
            # measuring pass, so it shows up in the budget accounting.
            small = _base64_source(64, "image/png")
            assert formatter._cap_media(small, "image") is None
            assert _request_media_budget.get().occurrences == [
                _MediaOccurrence(
                    key=media_dedup_key(small),
                    size=inline_media_size(small),
                    folded=False,
                ),
            ]
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
            # A fresh measuring pass sees no earlier charges.
            assert formatter._maybe_cap_total(image, "image") is None
            assert _request_media_budget.get().occurrences == [
                _MediaOccurrence(
                    key=media_dedup_key(image),
                    size=_MEASURED_BYTES,
                    folded=False,
                ),
            ]
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
    async def test_newest_media_kept_oldest_dropped(
        self,
        formatter_cls,
    ) -> None:
        """Overflow drops the *oldest* media; the newest image survives."""
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=900)
        messages = [_image_msg(i) for i in range(3)]

        parts = _wire_parts(await formatter.format(messages))

        placeholders = _total_limit_placeholders(parts)
        assert len(placeholders) == 2
        assert "900-byte" in placeholders[0]["text"]
        # Exactly one image is still inlined, and identity matters: it is
        # the newest one, i.e. the media part of the final message.
        kept = _media_parts(parts)
        assert len(kept) == 1
        assert parts[-1] == kept[0]
        assert "look at this 2" in (parts[-2].get("text") or "")

    @pytest.mark.asyncio
    async def test_data_url_images_are_budget_capped(self) -> None:
        """Inline ``data:`` URLs are inlined bytes: they spend the budget."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )

        parts = _wire_parts(
            await formatter.format(
                [_data_url_image_msg(i) for i in range(3)],
            ),
        )

        assert len(_total_limit_placeholders(parts)) == 2
        kept = _media_parts(parts)
        assert len(kept) == 1
        assert parts[-1] == kept[0]

    @pytest.mark.asyncio
    async def test_openai_pdf_attachments_are_budget_capped(self) -> None:
        """Chat Completions PDFs flow through ``_format_file_source``,
        which must spend the same budget as image/audio media."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )

        parts = _wire_parts(
            await formatter.format([_pdf_msg(i) for i in range(3)]),
        )

        assert len(_total_limit_placeholders(parts)) == 2
        kept = _media_parts(parts)
        assert len(kept) == 1
        assert kept[0].get("type") == "file"

    @pytest.mark.asyncio
    async def test_responses_pdf_attachments_are_budget_capped(self) -> None:
        """Responses API PDFs (``input_file`` parts) are capped too."""
        formatter = _CappingOpenAIResponseFormatter(
            max_bytes=1024,
            max_total_bytes=900,
        )

        parts = _wire_parts(
            await formatter.format([_pdf_msg(i) for i in range(3)]),
        )

        assert len(_total_limit_placeholders(parts)) == 2
        kept = _media_parts(parts)
        assert len(kept) == 1
        assert kept[0].get("type") == "input_file"

    @pytest.mark.asyncio
    async def test_single_media_over_the_budget_is_dropped(self) -> None:
        """When nothing smaller can be dropped, the only media goes."""
        formatter = _CappingOpenAIFormatter(
            max_bytes=4096,
            max_total_bytes=900,
        )

        parts = _wire_parts(await formatter.format([_image_msg(0, 2048)]))

        assert len(_total_limit_placeholders(parts)) == 1
        assert _media_parts(parts) == []

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


class TestCumulativeBudgetThroughProductionWrapper:
    """The budget must survive the formatter wrapper used in production.

    The wrapper keeps a per-request media dedup scope around the whole
    request.  The budget formats the request twice (measure, then
    enforce), so the scope has to be reset between the passes — otherwise
    the enforcing pass sees every source as "already shown above" and
    drops all media, including the newest one the budget keeps.
    """

    @pytest.mark.asyncio
    async def test_anthropic_wrapper_keeps_the_newest_media(self) -> None:
        from qwenpaw.agents import model_factory

        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingAnthropicFormatter,
        )
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=900)
        messages = [_distinct_image_msg(i) for i in range(3)]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 1
        assert parts[-1] == kept[0]
        assert len(_total_limit_placeholders(parts)) == 2

    @pytest.mark.asyncio
    async def test_openai_wrapper_keeps_the_newest_media(self) -> None:
        from qwenpaw.agents import model_factory

        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingOpenAIFormatter,
        )
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=900)
        messages = [_distinct_image_msg(i) for i in range(3)]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 1
        assert parts[-1] == kept[0]


class TestRepeatedMediaSurvivesTheBudget:
    """A repeated media source must not be folded away by an older copy.

    The budget drops the oldest media to keep the newest.  When the
    dropped copy shares its source with a later one, the later copy has
    to take its place — folding it as "already shown above" would leave
    the request without that media at all.
    """

    @pytest.mark.asyncio
    async def test_anthropic_wrapper_keeps_the_newest_repeated_media(
        self,
    ) -> None:
        from qwenpaw.agents import model_factory

        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingAnthropicFormatter,
        )
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=900)
        messages = [
            _seeded_image_msg(0, "A"),
            _seeded_image_msg(1, "B"),
            _seeded_image_msg(2, "A"),
        ]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 1
        assert parts[-1] == kept[0]
        # The surviving media is the newest copy of A, not the copy of B
        # that the budget kept before the fix.
        assert _media_payload(kept[0]).endswith("A")
        assert len(_total_limit_placeholders(parts)) == 2
        assert not _duplicate_placeholders(parts)

    @pytest.mark.asyncio
    async def test_anthropic_wrapper_still_folds_a_repeated_source(
        self,
    ) -> None:
        """A repeated source that fits the budget is still deduplicated."""
        from qwenpaw.agents import model_factory

        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingAnthropicFormatter,
        )
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=2048)
        messages = [
            _seeded_image_msg(0, "A"),
            _seeded_image_msg(1, "A"),
        ]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 1
        assert len(_duplicate_placeholders(parts)) == 1
        assert not _total_limit_placeholders(parts)

    @pytest.mark.asyncio
    async def test_anthropic_wrapper_keeps_the_newest_repeated_tool_media(
        self,
    ) -> None:
        from qwenpaw.agents import model_factory

        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingAnthropicFormatter,
        )
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=900)
        messages = [
            _seeded_image_msg(0, "A"),
            _seeded_image_msg(1, "B"),
            *_tool_result_image_msgs("A"),
        ]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 1
        assert _media_payload(kept[0]).endswith("A")
        assert len(_total_limit_placeholders(parts)) == 2
        assert not _duplicate_placeholders(parts)

    @pytest.mark.asyncio
    async def test_openai_wrapper_keeps_the_newest_repeated_media(
        self,
    ) -> None:
        from qwenpaw.agents import model_factory

        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingOpenAIFormatter,
        )
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=900)
        messages = [
            _seeded_image_msg(0, "A"),
            _seeded_image_msg(1, "B"),
            _seeded_image_msg(2, "A"),
        ]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 1
        assert parts[-1] == kept[0]
        assert _media_payload(kept[0]).endswith("A")
        assert len(_total_limit_placeholders(parts)) == 2

    @pytest.mark.asyncio
    async def test_responses_wrapper_keeps_the_newest_repeated_media(
        self,
    ) -> None:
        from qwenpaw.agents import model_factory

        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingOpenAIResponseFormatter,
        )
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=900)
        messages = [
            _seeded_image_msg(0, "A"),
            _seeded_image_msg(1, "B"),
            _seeded_image_msg(2, "A"),
        ]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 1
        assert parts[-1] == kept[0]
        assert _media_payload(kept[0]).endswith("A")
        assert len(_total_limit_placeholders(parts)) == 2


class TestDeduplicatedPayloadFitsTheBudget:
    """A folded duplicate sends no bytes, so it must cost no budget.

    Regression: the measuring pass charged folded duplicates to the
    budget, so A -> B -> B (513 bytes each, 1200-byte budget) measured
    1539 bytes, dropped A, and kept only B — although after dedup
    A + B need just 1026 bytes and both fit.
    """

    @pytest.mark.asyncio
    async def test_anthropic_wrapper_keeps_both_when_dup_folds(
        self,
    ) -> None:
        """A -> B -> B at a 1200-byte budget keeps both A and B."""
        from qwenpaw.agents import model_factory

        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingAnthropicFormatter,
        )
        formatter = formatter_cls(max_bytes=1024, max_total_bytes=1200)
        messages = [
            _seeded_image_msg(0, "A"),
            _seeded_image_msg(1, "B"),
            _seeded_image_msg(2, "B"),
        ]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 2
        assert _media_payload(kept[0]).endswith("A")
        assert _media_payload(kept[1]).endswith("B")
        assert len(_duplicate_placeholders(parts)) == 1
        assert not _total_limit_placeholders(parts)

    @pytest.mark.asyncio
    async def test_anthropic_wrapper_keeps_media_despite_folded_copies(
        self,
    ) -> None:
        """One A followed by six copies of B (1.5 MiB each) fits the
        default 8 MiB budget after dedup: the distinct media total
        3 MiB, so A must not be dropped."""
        from qwenpaw.agents import model_factory

        mib = 1024 * 1024
        b64_chars = ((3 * mib // 2 + 2) // 3) * 4
        formatter_cls = model_factory._create_file_block_support_formatter(
            _CappingAnthropicFormatter,
        )
        formatter = formatter_cls(
            max_bytes=2 * mib,
            max_total_bytes=8 * mib,
        )

        def _big_image_msg(index: int, seed: str) -> Msg:
            data = "A" * (b64_chars - 1) + seed
            return Msg(
                name="user",
                role="user",
                content=[
                    TextBlock(text=f"look at this {index}"),
                    DataBlock(
                        source=Base64Source(
                            data=data,
                            media_type="image/png",
                        ),
                        name=f"img{index}.png",
                    ),
                ],
            )

        messages = [
            _big_image_msg(0, "A"),
            *[_big_image_msg(i, "B") for i in range(1, 7)],
        ]

        parts = _wire_parts(await formatter.format(messages))

        kept = _media_parts(parts)
        assert len(kept) == 2
        assert _media_payload(kept[0]).endswith("A")
        assert _media_payload(kept[1]).endswith("B")
        assert len(_duplicate_placeholders(parts)) == 5
        assert not _total_limit_placeholders(parts)
