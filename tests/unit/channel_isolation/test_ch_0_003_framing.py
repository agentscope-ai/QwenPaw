# -*- coding: utf-8 -*-
"""Tests for CH-0-003 strict LSP Content-Length framing."""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.channel_protocol import (
    FrameEOFError,
    FrameLimitError,
    FrameProtocolError,
    FrameReader,
    FrameTimeoutError,
    FramingLimits,
    encode_frame,
)


def _reader_with_data(
    *chunks: bytes,
    eof: bool = True,
) -> asyncio.StreamReader:
    """Build a StreamReader with deterministic input chunks."""
    reader = asyncio.StreamReader()
    for chunk in chunks:
        reader.feed_data(chunk)
    if eof:
        reader.feed_eof()
    return reader


def test_encode_frame_uses_utf8_byte_length() -> None:
    """Content-Length counts encoded bytes instead of Python characters."""
    message = '{"text":"你好"}'
    body = message.encode("utf-8")

    assert encode_frame(message) == (
        f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    )


@pytest.mark.parametrize("message", ["", b"{}", 1, None])
def test_encode_frame_rejects_non_message_values(message: object) -> None:
    """A control frame is a non-empty UTF-8 text message."""
    with pytest.raises(FrameProtocolError):
        encode_frame(message)  # type: ignore[arg-type]


def test_encode_frame_enforces_maximum_body_size() -> None:
    """Oversized outbound control data never reaches the writer."""
    limits = FramingLimits(max_frame_bytes=2)

    with pytest.raises(FrameLimitError):
        encode_frame("€", limits=limits)


@pytest.mark.asyncio
async def test_reader_handles_fragmented_and_sticky_frames() -> None:
    """One reader preserves partial and surplus bytes across messages."""
    first = encode_frame('{"first":"é"}')
    second = encode_frame("[1,2,3]")
    reader = _reader_with_data(
        first[:1],
        first[1:12],
        first[12:] + second[:9],
        second[9:],
    )
    framing = FrameReader(reader)

    assert await framing.read_message() == '{"first":"é"}'
    assert await framing.read_message() == "[1,2,3]"


@pytest.mark.parametrize(
    "raw",
    [
        b"Content-Type: application/json\r\n\r\n{}",
        b"Content-Length : 2\r\n\r\n{}",
        b"Content-Length: value\r\n\r\n{}",
        b"Content-Length: -1\r\n\r\n",
        b"Content-Length: 0\r\n\r\n",
        b" Content-Length: 2\r\n\r\n{}",
        b"Content-Length: 2 \t extra\r\n\r\n{}",
        b"Content-Length: 2\n\n{}",
        b"Content-Length: 2\rX\r\n\r\n{}",
    ],
)
@pytest.mark.asyncio
async def test_reader_rejects_invalid_headers(raw: bytes) -> None:
    """Only the frozen single Content-Length header grammar is accepted."""
    framing = FrameReader(_reader_with_data(raw))

    with pytest.raises(FrameProtocolError):
        await framing.read_message()


@pytest.mark.parametrize(
    "raw",
    [
        b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        b"Content-Length: 2\r\nX-Test: value\r\n\r\n{}",
    ],
)
@pytest.mark.asyncio
async def test_reader_rejects_duplicate_or_extra_headers(raw: bytes) -> None:
    """V1 permits exactly one header line."""
    framing = FrameReader(_reader_with_data(raw))

    with pytest.raises(FrameProtocolError):
        await framing.read_message()


@pytest.mark.asyncio
async def test_reader_accepts_case_insensitive_header_whitespace() -> None:
    """LSP header names are case-insensitive around an exact field name."""
    raw = b"content-length:\t2 \r\n\r\n{}"
    framing = FrameReader(_reader_with_data(raw))

    assert await framing.read_message() == "{}"


@pytest.mark.asyncio
async def test_reader_rejects_header_over_limit() -> None:
    """A missing terminator cannot grow the header buffer without bound."""
    limits = FramingLimits(max_header_bytes=24)
    framing = FrameReader(
        _reader_with_data(b"Content-Length: 2", b"XXXXXXX"),
        limits=limits,
    )

    with pytest.raises(FrameLimitError):
        await framing.read_message()


@pytest.mark.asyncio
async def test_reader_rejects_declared_body_over_limit() -> None:
    """The declared size is checked before waiting for its body."""
    raw = b"Content-Length: 4\r\n\r\n{}"
    limits = FramingLimits(max_frame_bytes=3)
    framing = FrameReader(_reader_with_data(raw), limits=limits)

    with pytest.raises(FrameLimitError):
        await framing.read_message()


@pytest.mark.asyncio
async def test_reader_rejects_invalid_utf8() -> None:
    """Bodies must decode as strict UTF-8."""
    raw = b"Content-Length: 1\r\n\r\n\xff"
    framing = FrameReader(_reader_with_data(raw))

    with pytest.raises(FrameProtocolError):
        await framing.read_message()


@pytest.mark.parametrize(
    "raw",
    [
        b"Content-Len",
        b"Content-Length: 4\r\n\r\n{}",
    ],
)
@pytest.mark.asyncio
async def test_reader_distinguishes_truncated_frame_from_clean_eof(
    raw: bytes,
) -> None:
    """EOF within a frame is a protocol failure, not a clean shutdown."""
    framing = FrameReader(_reader_with_data(raw))

    with pytest.raises(FrameProtocolError, match="truncated"):
        await framing.read_message()


@pytest.mark.asyncio
async def test_reader_reports_clean_eof_at_frame_boundary() -> None:
    """EOF before the next frame closes the read side cleanly."""
    framing = FrameReader(_reader_with_data())

    with pytest.raises(FrameEOFError):
        await framing.read_message()


@pytest.mark.asyncio
async def test_idle_wait_does_not_consume_partial_frame_timeout() -> None:
    """The read deadline begins only after the first frame byte arrives."""
    reader = asyncio.StreamReader()
    limits = FramingLimits(read_timeout=0.01)
    framing = FrameReader(reader, limits=limits)
    pending = asyncio.create_task(framing.read_message())

    await asyncio.sleep(0.03)
    reader.feed_data(encode_frame("{}"))

    assert await pending == "{}"


@pytest.mark.asyncio
async def test_partial_header_times_out() -> None:
    """A peer cannot hold an incomplete header open indefinitely."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"Content-Length")
    limits = FramingLimits(read_timeout=0.01)
    framing = FrameReader(reader, limits=limits)

    with pytest.raises(FrameTimeoutError):
        await framing.read_message()


@pytest.mark.asyncio
async def test_partial_body_times_out() -> None:
    """The same frame deadline covers its header and body."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"Content-Length: 4\r\n\r\n{}")
    limits = FramingLimits(read_timeout=0.01)
    framing = FrameReader(reader, limits=limits)

    with pytest.raises(FrameTimeoutError):
        await framing.read_message()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_frame_bytes", 0),
        ("max_header_bytes", 0),
        ("read_timeout", 0),
        ("write_timeout", 0),
        ("write_queue_size", 0),
        ("max_frame_bytes", True),
        ("read_timeout", float("inf")),
        ("write_timeout", float("nan")),
    ],
)
def test_limits_require_positive_finite_values(
    field: str,
    value: int | float,
) -> None:
    """Every safety limit must remain active."""
    values = {field: value}

    with pytest.raises(ValueError):
        FramingLimits(**values)
