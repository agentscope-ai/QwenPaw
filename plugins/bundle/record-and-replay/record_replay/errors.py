# -*- coding: utf-8 -*-
"""Stable errors for the Record & Replay plugin."""

from __future__ import annotations


class DesktopRecordingError(RuntimeError):
    """Base class for record-and-replay failures."""


class RecordingProtocolError(DesktopRecordingError):
    """Raised when the native recording contract fails or is unavailable."""


class RecordingStateError(DesktopRecordingError):
    """Raised when a recording operation is invalid for the current state."""


class RecordingStoreError(DesktopRecordingError):
    """Raised when a recording cannot be persisted safely."""


class RecordingPrivacyError(DesktopRecordingError):
    """Raised when an event cannot pass the final privacy guard."""


class RecordingLearnError(DesktopRecordingError):
    """Raised when recording evidence cannot produce a safe Skill draft."""


class RecordingConsentError(RecordingLearnError):
    """Raised when evidence transfer was not explicitly authorized."""


class RecordingDraftError(RecordingLearnError):
    """Raised when a generated or reviewed Skill draft is invalid."""


__all__ = [
    "DesktopRecordingError",
    "RecordingConsentError",
    "RecordingDraftError",
    "RecordingLearnError",
    "RecordingPrivacyError",
    "RecordingProtocolError",
    "RecordingStateError",
    "RecordingStoreError",
]
