# -*- coding: utf-8 -*-
"""Tests for the QwenPaw Relay binary protocol."""
from __future__ import annotations

import json
import struct

import pytest

from qwenpaw.remote_access.protocol import (
    RelayFrame,
    RelayFrameError,
    RelayFrameType,
    RelayOperation,
    decode_frame,
    encode_frame,
)


def test_binary_frame_round_trip_preserves_payload() -> None:
    frame = RelayFrame(
        frame_type=RelayFrameType.DATA,
        stream_id="stream-1",
        request_id="request-1",
        sequence=3,
        metadata={"content_type": "image/png"},
        payload=b"\x00\x01png-data",
    )

    assert decode_frame(encode_frame(frame)) == frame


def test_session_event_requires_revision_identity_and_sequence() -> None:
    frame = RelayFrame(
        frame_type=RelayFrameType.SESSION_EVENT,
        metadata={"session_id": "session-1"},
    )

    with pytest.raises(RelayFrameError, match="event_id"):
        encode_frame(frame)


def test_open_requires_fixed_operation_and_schema_version() -> None:
    valid = RelayFrame(
        frame_type=RelayFrameType.OPEN,
        stream_id="stream-1",
        request_id="request-1",
        metadata={
            "operation_id": RelayOperation.MESSAGE_SEND.value,
            "schema_version": 1,
        },
    )

    assert decode_frame(encode_frame(valid)) == valid

    with pytest.raises(RelayFrameError, match="operation_id"):
        encode_frame(
            RelayFrame(
                frame_type=RelayFrameType.OPEN,
                stream_id="stream-1",
                request_id="request-1",
                metadata={
                    "operation_id": "http.proxy",
                    "schema_version": 1,
                },
            ),
        )


def test_event_ack_requires_session_and_sequence() -> None:
    frame = RelayFrame(
        frame_type=RelayFrameType.EVENT_ACK,
        sequence=1,
    )

    with pytest.raises(RelayFrameError, match="session_id"):
        encode_frame(frame)


@pytest.mark.parametrize(
    "wire",
    [
        b"",
        struct.pack(">I", 0),
        struct.pack(">I", 100) + b"{}",
        struct.pack(">I", 2) + b"[]",
        struct.pack(">I", 1) + b"{",
    ],
)
def test_malformed_frames_are_rejected(wire: bytes) -> None:
    with pytest.raises(RelayFrameError):
        decode_frame(wire)


def test_unknown_protocol_version_is_rejected() -> None:
    header = json.dumps({"v": 2, "type": "ping"}).encode("utf-8")
    wire = struct.pack(">I", len(header)) + header

    with pytest.raises(RelayFrameError, match="version"):
        decode_frame(wire)
