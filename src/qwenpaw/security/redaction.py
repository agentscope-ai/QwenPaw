# -*- coding: utf-8 -*-
"""Secret redaction helpers for persisted logs and debug artifacts."""

from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"tvly-(?:dev-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"mkt_[A-Za-z0-9]{20,}"),
    re.compile(r"agent-world-[A-Za-z0-9]{30,}"),
)


def _mask_secret(match: re.Match[str]) -> str:
    value = match.group(0)
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def redact_text(text: str) -> str:
    """Redact known secret token formats inside *text*."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_mask_secret, redacted)
    return redacted


def redact_secrets(value: Any) -> Any:
    """Recursively redact known secret token formats in JSON-like data."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    return value
