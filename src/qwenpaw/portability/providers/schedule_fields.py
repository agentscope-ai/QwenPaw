# -*- coding: utf-8 -*-
"""Bounded text normalization shared by schedule providers."""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any


def text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def encoded(value: str) -> bytes:
    return value.encode("utf-8", errors="replace")


def contains_control(value: str, *, allow_whitespace: bool = False) -> bool:
    allowed = "\t\n\r" if allow_whitespace else ""
    return any(
        character not in allowed
        and unicodedata.category(character) in {"Cc", "Cf"}
        for character in value
    )


def text_audit(
    value: str,
    *,
    disposition: str,
    encoded_value: bytes | None = None,
) -> dict[str, Any]:
    raw = encoded_value if encoded_value is not None else encoded(value)
    return {
        "disposition": disposition,
        "original_chars": len(value),
        "original_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def metadata_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(
        " " if contains_control(character) else character
        for character in value[:limit]
    ).strip()


def safe_prompt(
    value: Any,
    *,
    max_chars: int,
    max_bytes: int,
) -> tuple[str, dict[str, Any], str]:
    if value is None:
        return "", {}, ""
    if not isinstance(value, str):
        raw = (
            value
            if isinstance(value, bytes)
            else encoded(type(value).__name__)
        )
        audit = {
            "disposition": "omitted",
            "original_chars": 0,
            "original_bytes": len(raw) if isinstance(value, bytes) else 0,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        return "", audit, "source_prompt_unsafe"
    raw = encoded(value)
    if len(value) > max_chars or len(raw) > max_bytes:
        return (
            "",
            text_audit(value, disposition="omitted", encoded_value=raw),
            "source_prompt_exceeds_limit",
        )
    if contains_control(value, allow_whitespace=True):
        return (
            "",
            text_audit(value, disposition="omitted"),
            "source_prompt_unsafe",
        )
    return value.strip(), {}, ""


def safe_title(
    value: Any,
    *,
    fallback: str,
    max_chars: int,
    max_bytes: int | None = None,
) -> tuple[str, dict[str, Any], str]:
    original = value if isinstance(value, str) else ""
    normalized = (
        " ".join(
            "".join(
                " " if contains_control(character) else character
                for character in original[: max_chars * 4]
            ).split(),
        )
        or fallback
    )
    changed = bool(original) and normalized != original
    while len(normalized) > max_chars or (
        max_bytes is not None and len(encoded(normalized)) > max_bytes
    ):
        normalized = normalized[:-1]
        changed = True
    normalized = normalized.rstrip() or fallback
    if not changed:
        return normalized, {}, ""
    return (
        normalized,
        text_audit(original, disposition="normalized_or_truncated"),
        "source_title_normalized",
    )


def safe_field(
    value: Any,
    *,
    max_chars: int,
    max_bytes: int | None,
    reason: str,
) -> tuple[str, dict[str, Any], str]:
    original = value if isinstance(value, str) else ""
    raw = encoded(original)
    if (
        len(original) > max_chars
        or (max_bytes is not None and len(raw) > max_bytes)
        or contains_control(original)
    ):
        return (
            "",
            text_audit(original, disposition="omitted", encoded_value=raw),
            reason,
        )
    return original.strip(), {}, ""


__all__ = [
    "contains_control",
    "encoded",
    "metadata_text",
    "safe_field",
    "safe_prompt",
    "safe_title",
    "text",
    "text_audit",
]
