# -*- coding: utf-8 -*-
"""Unified browser error contracts and classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .governance.error_codes import BrowserErrorCode


class ErrorCategory(StrEnum):
    """Closed set of recovery categories for browser failures."""

    RETRYABLE = "RETRYABLE"
    REROUTE = "REROUTE"
    ASK_HUMAN = "ASK_HUMAN"
    FATAL = "FATAL"


class ErrorCause(StrEnum):
    """Internal cause dimension used to select actionable browser teaching."""

    LOCATE_FAILED = "locate_failed"
    OUT_OF_BOUNDS = "out_of_bounds"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    APPROVAL_DENIED = "approval_denied"
    API_MISUSE = "api_misuse"
    INTERNAL = "internal"
    STATE_STALE = "state_stale"
    TIMING = "timing"


class BrowserError(Exception):
    """A browser failure with an explicit recovery category."""

    def __init__(
        self,
        *,
        category: ErrorCategory,
        suggested_action: str,
        reason: str,
        detail: str = "",
        cause: ErrorCause | None = None,
        example: str = "",
    ) -> None:
        super().__init__(reason)
        self.category = category
        self.suggested_action = suggested_action
        self.reason = reason
        self.detail = detail
        self.cause = cause
        self.example = example

    @property
    def disposition(self) -> ErrorCategory:
        """Backward-compatible name for the recovery category."""
        return self.category

    def __str__(self) -> str:
        """Render an immediately actionable teaching message for the caller."""
        parts = []
        if self.suggested_action:
            parts.append(self.suggested_action.strip())
        if self.reason:
            parts.append(self.reason.strip())
        if self.example:
            parts.append("Example:\n" + self.example.strip())
        return " — ".join(parts) if parts else (self.reason or "")


def fatal(reason: str, detail: str = "") -> BrowserError:
    """Build a fatal provider or execution-boundary error."""
    return BrowserError(
        category=ErrorCategory.FATAL,
        suggested_action="fatal",
        reason=reason,
        detail=detail,
    )


@dataclass(frozen=True)
class ErrorClassification:
    """The recovery policy associated with one stable transport error code."""

    code: BrowserErrorCode
    category: ErrorCategory
    suggested_action: str
    cause: ErrorCause | None = None


_CODE_TO_CATEGORY: dict[BrowserErrorCode, ErrorCategory] = {
    BrowserErrorCode.UNKNOWN: ErrorCategory.FATAL,
    BrowserErrorCode.BRIDGE_DISCONNECTED: ErrorCategory.REROUTE,
    BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT: ErrorCategory.RETRYABLE,
    BrowserErrorCode.BROWSER_TAB_OCCUPIED: ErrorCategory.RETRYABLE,
    BrowserErrorCode.BROWSER_PROTOCOL_VERSION_MISMATCH: ErrorCategory.FATAL,
}

_CODE_TO_CAUSE: dict[BrowserErrorCode, ErrorCause | None] = {
    BrowserErrorCode.UNKNOWN: None,
    BrowserErrorCode.BRIDGE_DISCONNECTED: ErrorCause.TIMING,
    BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT: ErrorCause.TIMING,
    BrowserErrorCode.BROWSER_TAB_OCCUPIED: ErrorCause.TIMING,
    BrowserErrorCode.BROWSER_PROTOCOL_VERSION_MISMATCH: (
        ErrorCause.CAPABILITY_UNSUPPORTED
    ),
}


def classify_browser_error(code: BrowserErrorCode) -> ErrorClassification:
    """Classify a stable browser transport error into a recovery category."""
    category = _CODE_TO_CATEGORY.get(code, ErrorCategory.FATAL)
    return ErrorClassification(
        code=code,
        category=category,
        suggested_action=category.value.lower(),
        cause=_CODE_TO_CAUSE.get(code),
    )


__all__ = [
    "BrowserError",
    "ErrorCategory",
    "ErrorCause",
    "ErrorClassification",
    "fatal",
    "classify_browser_error",
]
