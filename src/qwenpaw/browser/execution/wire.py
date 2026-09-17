# -*- coding: utf-8 -*-
"""Cross-plane wire contracts: deliberately independent from the SDK."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import struct
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...constant import WORKING_DIR
from ...utils.io_utils import (
    read_bytes_async,
    run_sync_io,
    unlink_async,
    write_bytes_async,
)

WIRE_PROTOCOL_VERSION = 1
_FRAME_KINDS = frozenset(
    {
        "exec_request",
        "exec_result",
        "ctrl_call",
        "ctrl_result",
        "approval_request",
        "approval_verdict",
        "event",
    },
)
_FRAME_HEADER_SIZE = 4
# A validator, not a capacity knob: only control data and references may
# cross this wire, so any frame reaching this size means bulk leaked onto it.
MAX_FRAME_BYTES = 1024 * 1024
_SPILLABLE_KINDS = frozenset({"ctrl_call", "ctrl_result"})
_SPILL_MARKER = "__spill__"
# WORKING_DIR is app infrastructure, not SDK surface: spill files must follow
# the instance data root so the main process and spawned worker agree.
_SPILL_ROOT = WORKING_DIR / "browser" / "wire"


class WireProtocolError(ValueError):
    """Raised when a peer sends a malformed or incompatible wire frame."""


class SpillRequired(Exception):
    """Signal that a spillable frame must be written outside the event loop."""

    def __init__(self, raw: bytes) -> None:
        self.raw = raw


def _spill_dir() -> Path:
    """Return the shared overflow directory used by both planes."""
    _SPILL_ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(_SPILL_ROOT, 0o700)
    return _SPILL_ROOT


async def _write_spill_async(raw: bytes) -> str:
    """Write an oversized wire frame with restrictive creation permissions."""
    directory = await run_sync_io(_spill_dir)
    path = directory / f"{os.getpid()}-{uuid.uuid4().hex}.json"
    await write_bytes_async(path, raw, new_file_mode=0o600)
    return str(path)


def spill_stdout(request_id: str, text: str) -> str:
    """Store unbounded worker stdout until the core can relocate it."""
    path = _spill_dir() / f"{request_id}-stdout.txt"
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)
    return str(path.resolve())


def sweep_spill(max_age_seconds: float = 3600.0) -> int:
    """Delete overflow files a crashed peer never consumed."""
    deleted = 0
    cutoff = time.time() - max_age_seconds
    try:
        entries = list(_SPILL_ROOT.iterdir())
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                deleted += 1
        except OSError:
            continue
    return deleted


@dataclass(frozen=True)
class ExecRequest:
    request_id: str
    code: str
    context: str = "auto"
    owner_workspace_id: str = "default"
    owner_session_id: str = "default"


@dataclass(frozen=True)
class ExecResult:
    request_id: str
    value: Any = None
    stdout: str = ""
    error: dict[str, Any] | None = None
    handoff: dict[str, Any] | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    origin: str
    action_category: str
    signal: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TokenVerdict:
    request_id: str
    decision: str
    token: str | None = None


@dataclass(frozen=True)
class EventInterrupt:
    request_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


def encode_frame(kind: str, payload: dict[str, Any]) -> bytes:
    """Purely encode one strict JSON frame for the socket transport."""
    if kind not in _FRAME_KINDS:
        raise WireProtocolError(f"unsupported frame kind: {kind}")
    if not isinstance(payload, dict):
        raise WireProtocolError("frame payload must be an object")
    try:
        raw = json.dumps(
            {
                "v": WIRE_PROTOCOL_VERSION,
                "kind": kind,
                "payload": payload,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WireProtocolError(
            "frame payload must be JSON serializable",
        ) from exc
    if not raw:
        raise WireProtocolError("frame payload exceeds the size limit")
    if len(raw) > MAX_FRAME_BYTES:
        if kind in _SPILLABLE_KINDS:
            raise SpillRequired(raw)
        if kind == "exec_result":
            raise WireProtocolError(
                "browser output exceeds the single-frame limit; filter "
                "the text in Python before printing it",
            )
        raise WireProtocolError(
            f"{kind} frame exceeds the size limit, which means bulk "
            "data leaked onto the control wire",
        )
    return struct.pack("!I", len(raw)) + raw


async def encode_frame_async(kind: str, payload: dict[str, Any]) -> bytes:
    """Encode a frame, spilling rare large control payloads asynchronously."""
    try:
        return encode_frame(kind, payload)
    except SpillRequired as spill:
        try:
            reference = await _write_spill_async(spill.raw)
        except OSError as exc:
            raise WireProtocolError(
                "cannot spill an oversized frame to disk",
            ) from exc
        return encode_frame(kind, {_SPILL_MARKER: reference})


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Read and validate one fixed-schema JSON frame from ``reader``."""
    try:
        header = await reader.readexactly(_FRAME_HEADER_SIZE)
        size = struct.unpack("!I", header)[0]
        if not 0 < size <= MAX_FRAME_BYTES:
            raise WireProtocolError("invalid frame size")
        raw = await reader.readexactly(size)
    except asyncio.IncompleteReadError as exc:
        raise WireProtocolError("truncated wire frame") from exc
    try:
        frame = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WireProtocolError("wire frame is not valid JSON") from exc
    if not isinstance(frame, dict) or set(frame) != {"v", "kind", "payload"}:
        raise WireProtocolError("wire frame has an unexpected schema")
    if frame["v"] != WIRE_PROTOCOL_VERSION:
        raise WireProtocolError("wire protocol version mismatch")
    if frame["kind"] not in _FRAME_KINDS or not isinstance(
        frame["payload"],
        dict,
    ):
        raise WireProtocolError("wire frame has an invalid kind or payload")
    payload = frame["payload"]
    if set(payload) == {_SPILL_MARKER} and frame["kind"] in _SPILLABLE_KINDS:
        path = Path(str(payload[_SPILL_MARKER]))
        try:
            spilled = json.loads(
                (await read_bytes_async(path)).decode("utf-8"),
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WireProtocolError(
                "spilled frame payload is unreadable",
            ) from exc
        finally:
            with contextlib.suppress(OSError):
                await unlink_async(path)
        inner = spilled.get("payload") if isinstance(spilled, dict) else None
        if not isinstance(inner, dict):
            raise WireProtocolError(
                "spilled frame payload has an invalid schema",
            )
        frame = {**frame, "payload": inner}
    return frame


def exec_request_payload(request: ExecRequest) -> dict[str, Any]:
    """Serialize an execution request without using pickle."""
    return asdict(request)


def exec_request_from_payload(payload: dict[str, Any]) -> ExecRequest:
    """Deserialize a validated execution-request payload."""
    fields = {
        "request_id",
        "code",
        "context",
        "owner_workspace_id",
        "owner_session_id",
    }
    if set(payload) != fields or not all(
        isinstance(payload[name], str) for name in fields
    ):
        raise WireProtocolError("invalid exec_request payload")
    return ExecRequest(**payload)


def exec_result_payload(result: ExecResult) -> dict[str, Any]:
    """Serialize an execution result without using pickle."""
    return asdict(result)


def exec_result_from_payload(payload: dict[str, Any]) -> ExecResult:
    """Deserialize a validated execution-result payload."""
    fields = {"request_id", "value", "stdout", "error", "handoff"}
    if set(payload) != fields or not isinstance(payload["request_id"], str):
        raise WireProtocolError("invalid exec_result payload")
    if not isinstance(payload["stdout"], str):
        raise WireProtocolError("invalid exec_result stdout")
    for name in ("error", "handoff"):
        if payload[name] is not None and not isinstance(payload[name], dict):
            raise WireProtocolError(f"invalid exec_result {name}")
    return ExecResult(**payload)
