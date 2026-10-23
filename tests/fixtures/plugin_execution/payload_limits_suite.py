"""Prepared public limits contracts; no candidate run before Source freeze."""

import asyncio

import pytest

from payload_support import ledger_rows

pytest_plugins = ["process_suite", "payload_support"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_message_bytes": 0},
        {"max_pending_bytes": -1},
        {"max_pending_files": True},
        {"max_message_bytes": 1.5},
    ],
)
def test_explicit_payload_limits_reject_disabled_or_non_integer_values(kwargs):
    from qwenpaw.plugins.execution.payloads import PayloadLimits

    with pytest.raises(ValueError):
        PayloadLimits(**kwargs)


@pytest.mark.asyncio
async def test_default_frame_boundary_remains_exact_one_mib_and_strict_utf8():
    from qwenpaw.plugins.execution.errors import FrameLimitError, FrameProtocolError
    from qwenpaw.plugins.execution.framing import FrameReader, FramingLimits, encode_frame

    limit = 1024 * 1024
    assert FramingLimits().max_frame_bytes == limit
    message = '"' + "a" * (limit - 2) + '"'
    wire = encode_frame(message)
    assert wire == f"Content-Length: {limit}\r\n\r\n".encode() + message.encode()
    reader = asyncio.StreamReader()
    reader.feed_data(wire)
    reader.feed_eof()
    assert await FrameReader(reader).read_message() == message
    with pytest.raises(FrameLimitError):
        encode_frame(message + " ")
    reader = asyncio.StreamReader()
    reader.feed_data(b"Content-Length: 1\r\n\r\n\xff")
    reader.feed_eof()
    with pytest.raises(FrameProtocolError):
        await FrameReader(reader).read_message()


@pytest.mark.asyncio
async def test_user_message_limit_fails_before_child_business_visibility(
    payload_launch, payload_processes
):
    from qwenpaw.plugins.execution.errors import FrameLimitError
    from qwenpaw.plugins.execution.payloads import PayloadLimits

    spec, marker = payload_launch()
    process = payload_processes(
        payload_limits=PayloadLimits(
            max_message_bytes=2 * 1024 * 1024,
            max_pending_bytes=2 * 1024 * 1024,
            max_pending_files=2,
        )
    )
    await process.start(spec)
    with pytest.raises(FrameLimitError):
        await process.call("fixture.payload_echo", {"text": "x" * (3 * 1024 * 1024)})
    assert ledger_rows(marker) == []
    assert process.health_snapshot()["unknown_outcomes"] == []
    cleanup = await process.stop()
    assert cleanup.exited and not cleanup.residual
    assert ledger_rows(marker) == []
