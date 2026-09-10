# -*- coding: utf-8 -*-
"""Binary framing shared by QwenPaw nodes and Platform Relay."""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


RELAY_PROTOCOL_VERSION = 1
_HEADER_LENGTH = struct.Struct(">I")
_MAX_HEADER_BYTES = 64 * 1024


class RelayFrameError(ValueError):
    """Raised when a Relay frame violates the wire contract."""


class RelayFrameType(StrEnum):
    """Supported control and data frame types."""

    HELLO = "hello"
    OPEN = "open"
    DATA = "data"
    END = "end"
    RESULT_META = "result_meta"
    CANCEL = "cancel"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"
    SESSION_EVENT = "session_event"
    EVENT_ACK = "event_ack"
    RESUME = "resume"


class RelayOperation(StrEnum):
    """Fixed operations allowed across the Relay boundary."""

    AGENT_LIST = "agent.list"
    AGENT_GET = "agent.get"
    SESSION_LIST = "session.list"
    SESSION_GET = "session.get"
    SESSION_CREATE = "session.create"
    SESSION_UPDATE = "session.update"
    SESSION_ARCHIVE = "session.archive"
    SESSION_DELETE = "session.delete"
    MESSAGE_SEND = "message.send"
    RUN_CANCEL = "run.cancel"
    APPROVAL_RESOLVE = "approval.resolve"
    ATTACHMENT_UPLOAD_BEGIN = "attachment.upload.begin"
    ATTACHMENT_UPLOAD_CHUNK = "attachment.upload.chunk"
    ATTACHMENT_UPLOAD_COMPLETE = "attachment.upload.complete"
    ATTACHMENT_DOWNLOAD = "attachment.download"


@dataclass(frozen=True, slots=True)
class RelayFrame:
    """One Relay message with a JSON header and optional binary payload."""

    frame_type: RelayFrameType
    stream_id: str | None = None
    request_id: str | None = None
    sequence: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    payload: bytes = b""
    version: int = RELAY_PROTOCOL_VERSION

    def validate(self) -> None:
        """Validate fields required for safe multiplexing."""
        if self.version != RELAY_PROTOCOL_VERSION:
            raise RelayFrameError(
                f"Unsupported Relay protocol version: {self.version}",
            )
        if self.sequence is not None and self.sequence < 0:
            raise RelayFrameError("Frame sequence must be non-negative")
        if (
            self.frame_type
            in {
                RelayFrameType.OPEN,
                RelayFrameType.DATA,
                RelayFrameType.END,
                RelayFrameType.RESULT_META,
                RelayFrameType.CANCEL,
                RelayFrameType.ERROR,
            }
            and not self.stream_id
        ):
            raise RelayFrameError(
                f"{self.frame_type.value} frame requires stream_id",
            )
        if self.frame_type is RelayFrameType.OPEN:
            if not self.request_id:
                raise RelayFrameError("Open frame requires request_id")
            _validate_operation(self.metadata.get("operation_id"))
            schema_version = self.metadata.get("schema_version")
            if (
                isinstance(schema_version, bool)
                or not isinstance(schema_version, int)
                or schema_version < 1
            ):
                raise RelayFrameError(
                    "Open frame schema_version is invalid",
                )
        if self.frame_type is RelayFrameType.SESSION_EVENT:
            required = {
                "session_id",
                "session_revision",
                "event_id",
                "event_type",
            }
            missing = sorted(required.difference(self.metadata))
            if self.sequence is None:
                missing.append("sequence")
            if missing:
                raise RelayFrameError(
                    f"Session event is missing: {', '.join(missing)}",
                )
        if self.frame_type is RelayFrameType.EVENT_ACK:
            if self.sequence is None or "session_id" not in self.metadata:
                raise RelayFrameError(
                    "Event acknowledgement requires session_id and sequence",
                )

    def header(self) -> dict[str, Any]:
        """Return the JSON-serializable wire header."""
        value: dict[str, Any] = {
            "v": self.version,
            "type": self.frame_type.value,
        }
        if self.stream_id is not None:
            value["stream_id"] = self.stream_id
        if self.request_id is not None:
            value["request_id"] = self.request_id
        if self.sequence is not None:
            value["sequence"] = self.sequence
        if self.metadata:
            value["metadata"] = dict(self.metadata)
        return value


def encode_frame(frame: RelayFrame) -> bytes:
    """Encode a Relay frame as header length, JSON header, then payload."""
    frame.validate()
    try:
        header = json.dumps(
            frame.header(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RelayFrameError(
            "Relay metadata must be JSON serializable",
        ) from exc
    if len(header) > _MAX_HEADER_BYTES:
        raise RelayFrameError("Relay frame header is too large")
    return _HEADER_LENGTH.pack(len(header)) + header + frame.payload


def decode_frame(value: bytes | bytearray | memoryview) -> RelayFrame:
    """Decode and validate one complete Relay binary message."""
    raw = bytes(value)
    if len(raw) < _HEADER_LENGTH.size:
        raise RelayFrameError("Relay frame is missing its header length")
    (header_length,) = _HEADER_LENGTH.unpack_from(raw)
    if header_length <= 0 or header_length > _MAX_HEADER_BYTES:
        raise RelayFrameError("Relay frame header length is invalid")
    header_end = _HEADER_LENGTH.size + header_length
    if len(raw) < header_end:
        raise RelayFrameError("Relay frame header is truncated")
    try:
        header = json.loads(raw[_HEADER_LENGTH.size : header_end])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RelayFrameError("Relay frame header is not valid JSON") from exc
    if not isinstance(header, dict):
        raise RelayFrameError("Relay frame header must be an object")
    raw_frame_type = header.get("type")
    if not isinstance(raw_frame_type, str):
        raise RelayFrameError("Relay frame type is unsupported")
    try:
        frame_type = RelayFrameType(raw_frame_type)
    except ValueError as exc:
        raise RelayFrameError("Relay frame type is unsupported") from exc
    metadata = header.get("metadata", {})
    if not isinstance(metadata, dict):
        raise RelayFrameError("Relay frame metadata must be an object")
    try:
        version = int(header.get("v", 0))
        sequence = _optional_int(header.get("sequence"), "sequence")
    except (TypeError, ValueError) as exc:
        raise RelayFrameError("Relay frame numeric field is invalid") from exc
    frame = RelayFrame(
        frame_type=frame_type,
        stream_id=_optional_string(header.get("stream_id"), "stream_id"),
        request_id=_optional_string(
            header.get("request_id"),
            "request_id",
        ),
        sequence=sequence,
        metadata=metadata,
        payload=raw[header_end:],
        version=version,
    )
    frame.validate()
    return frame


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RelayFrameError(f"Relay frame {name} must be a string")
    return value


def _optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RelayFrameError(f"Relay frame {name} must be an integer")
    return value


def _validate_operation(value: Any) -> None:
    if not isinstance(value, str):
        raise RelayFrameError("Open frame operation_id is unsupported")
    try:
        RelayOperation(value)
    except ValueError as exc:
        raise RelayFrameError(
            "Open frame operation_id is unsupported",
        ) from exc
