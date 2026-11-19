# -*- coding: utf-8 -*-
"""Public, host-independent audio transcription contracts (SDK 1.1)."""

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from .tools import ToolContext


@dataclass(frozen=True)
class TranscriptionContext(ToolContext):
    backend_id: str = ""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str = ""
    error: Literal["", "unavailable", "empty", "failed"] = ""
    message: str = ""


@dataclass(frozen=True)
class TranscriptionStatus:
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class TranscriptionSpec:
    id: str
    label: str
    transcribe: Callable[
        [TranscriptionContext, str],
        TranscriptionResult | Awaitable[TranscriptionResult],
    ]
    status: Callable[
        [TranscriptionContext],
        TranscriptionStatus | Awaitable[TranscriptionStatus],
    ]
    timeout: float | None = None
