"""QwenPaw realtime voice session and coordination contracts."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...providers.realtime_voice import MediaConfig
from ..chats.replies import ChatReply

PROTOCOL_VERSION = 2
TOKEN_TTL_SECONDS = 30
MAX_AUDIO_PAYLOAD_BYTES = 256 * 1024

_AUDIO_MAGIC = b"QV"
_AUDIO_HEADER = struct.Struct("!2sBBIIHI")
VoiceAdmissionMode = Literal["queue", "steer"]
VoiceActionType = Literal["HANDOFF", "CONVERSE", "CLARIFY"]


@dataclass(frozen=True)
class HandoffVoiceAction:
    """Hand original speech to the current Chat's ordinary Agent."""

    task_ref: str = ""
    type: Literal["HANDOFF"] = field(default="HANDOFF", init=False)

    def public_dict(self) -> dict[str, str]:
        return {
            "type": self.type,
            **({"task_ref": self.task_ref} if self.task_ref else {}),
        }


@dataclass(frozen=True)
class ConverseVoiceAction:
    """Answer a non-work conversational turn through realtime speech."""

    type: Literal["CONVERSE"] = field(default="CONVERSE", init=False)

    def public_dict(self) -> dict[str, str]:
        return {"type": self.type}


@dataclass(frozen=True)
class ClarifyVoiceAction:
    """Ask for information required before work can be admitted."""

    missing_information: str
    type: Literal["CLARIFY"] = field(default="CLARIFY", init=False)

    def public_dict(self) -> dict[str, str]:
        return {"type": self.type}


VoiceAction = HandoffVoiceAction | ConverseVoiceAction | ClarifyVoiceAction


class AudioFrameKind(IntEnum):
    """Binary frame direction/type."""

    INPUT_PCM16 = 1
    OUTPUT_PCM16 = 2


@dataclass(frozen=True)
class AudioFrame:
    kind: AudioFrameKind
    sequence: int
    sample_rate: int
    channels: int
    payload: bytes


def encode_audio_frame(frame: AudioFrame) -> bytes:
    """Encode one versioned PCM16 frame for the renderer protocol."""
    if not 0 <= frame.sequence <= 0xFFFFFFFF:
        raise ValueError("audio sequence is out of range")
    if not 8000 <= frame.sample_rate <= 192000:
        raise ValueError("audio sample rate is out of range")
    if not 1 <= frame.channels <= 8:
        raise ValueError("audio channel count is out of range")
    if len(frame.payload) > MAX_AUDIO_PAYLOAD_BYTES:
        raise ValueError("audio payload exceeds the frame limit")
    return (
        _AUDIO_HEADER.pack(
            _AUDIO_MAGIC,
            PROTOCOL_VERSION,
            int(frame.kind),
            frame.sequence,
            frame.sample_rate,
            frame.channels,
            len(frame.payload),
        )
        + frame.payload
    )


def decode_audio_frame(data: bytes) -> AudioFrame:
    """Decode and validate one versioned PCM16 frame."""
    if len(data) < _AUDIO_HEADER.size:
        raise ValueError("audio frame header is truncated")
    (
        magic,
        version,
        kind,
        sequence,
        sample_rate,
        channels,
        length,
    ) = _AUDIO_HEADER.unpack_from(data)
    if magic != _AUDIO_MAGIC:
        raise ValueError("invalid audio frame magic")
    if version != PROTOCOL_VERSION:
        raise ValueError("unsupported audio protocol version")
    if length > MAX_AUDIO_PAYLOAD_BYTES:
        raise ValueError("audio payload exceeds the frame limit")
    if len(data) != _AUDIO_HEADER.size + length:
        raise ValueError("audio frame payload length does not match header")
    try:
        frame_kind = AudioFrameKind(kind)
    except ValueError as exc:
        raise ValueError("unknown audio frame kind") from exc
    if not 8000 <= sample_rate <= 192000 or not 1 <= channels <= 8:
        raise ValueError("invalid audio media parameters")
    return AudioFrame(
        kind=frame_kind,
        sequence=sequence,
        sample_rate=sample_rate,
        channels=channels,
        payload=data[_AUDIO_HEADER.size :],
    )


class CreateSessionRequest(BaseModel):
    """Bootstrap a new session or reconnect an existing Voice Chat."""

    model_config = ConfigDict(extra="forbid")

    chat_id: str | None = Field(default=None, max_length=128)
    previous_session_id: str | None = Field(default=None, max_length=128)
    replace_session_id: str | None = Field(default=None, max_length=128)
    admission_mode: VoiceAdmissionMode = "queue"


class SessionBootstrap(BaseModel):
    """Single-use renderer authorization for one realtime stream."""

    session_id: str
    agent_id: str
    chat_id: str
    generation: int
    protocol_version: int = PROTOCOL_VERSION
    media: MediaConfig
    ws_url: str
    token: str
    expires_at: str
    admission_mode: VoiceAdmissionMode


VoiceTaskStatus = Literal[
    "accepted",
    "queued",
    "processing",
    "waiting",
    "responded",
    "failed",
    "cancelled",
    "unsupported",
    "not_found",
]


@dataclass(frozen=True)
class VoiceTaskReceipt:
    """One-shot result returned by current-Chat speech admission."""

    task_id: str
    task_ref: str
    accepted: bool
    status: VoiceTaskStatus
    message: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_ref": self.task_ref,
            "accepted": self.accepted,
            "completed": False,
            **({"message": self.message} if self.message else {}),
        }


@dataclass(frozen=True)
class VoiceTaskSnapshot:
    """Versioned application-owned state for one admitted Voice task."""

    task_id: str
    task_ref: str
    status: VoiceTaskStatus
    version: int
    request: str
    run_id: str = ""
    background_work: tuple[dict[str, Any], ...] = ()
    replies: tuple[ChatReply, ...] = ()
    input_states: tuple[tuple[str, str], ...] = ()
    input_requests: tuple[tuple[str, str], ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_ref": self.task_ref,
            "status": self.status,
            "version": self.version,
            **(
                {"reply_ids": [reply.identity for reply in self.replies]}
                if self.replies
                else {}
            ),
            **(
                {"background_work": list(self.background_work)}
                if self.background_work
                else {}
            ),
        }


@dataclass(frozen=True)
class VoiceTaskEvent:
    """A monotonic task-state transition emitted by the current Chat."""

    snapshot: VoiceTaskSnapshot


@dataclass(frozen=True)
class VoiceRunEvent:
    """Canonical terminal state for one observed ordinary Chat run."""

    run_id: str
    status: Literal["started", "completed", "failed", "cancelled"]
    error: str = ""


VoiceBridgeEvent = VoiceTaskEvent | VoiceRunEvent


class RealtimeVoiceServiceError(RuntimeError):
    """Actionable service error safe to expose through the local API."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


__all__ = [
    "AudioFrame",
    "AudioFrameKind",
    "ClarifyVoiceAction",
    "ConverseVoiceAction",
    "CreateSessionRequest",
    "HandoffVoiceAction",
    "MediaConfig",
    "RealtimeVoiceServiceError",
    "SessionBootstrap",
    "VoiceAction",
    "VoiceActionType",
    "VoiceAdmissionMode",
    "VoiceBridgeEvent",
    "VoiceRunEvent",
    "VoiceTaskEvent",
    "VoiceTaskReceipt",
    "VoiceTaskSnapshot",
    "VoiceTaskStatus",
    "decode_audio_frame",
    "encode_audio_frame",
]
