# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Safe filesystem segments for Runtime-owned record paths."""

from __future__ import annotations

import hashlib
import re

from .errors import RuntimeFileValidationError


_SAFE_RUNTIME_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_MAX_HASHED_PREFIX_LENGTH = 127


def require_safe_runtime_segment(
    value: str,
    *,
    label: str = "Runtime id",
) -> str:
    """Return one normalized path segment or reject traversal/control input."""

    if not isinstance(value, str) or not _SAFE_RUNTIME_SEGMENT.fullmatch(
        value,
    ):
        raise RuntimeFileValidationError(f"{label} is not a safe path segment")
    return value


def hashed_runtime_segment(prefix: str, *opaque_parts: str) -> str:
    """Map opaque client identifiers to a stable, non-reversible safe segment."""

    safe_prefix = require_safe_runtime_segment(
        prefix,
        label="Runtime id prefix",
    )
    if len(safe_prefix) > _MAX_HASHED_PREFIX_LENGTH:
        raise RuntimeFileValidationError(
            "Runtime id prefix must not exceed 127 characters when hashed",
        )
    digest = hashlib.sha256()
    for part in opaque_parts:
        if not isinstance(part, str):
            raise RuntimeFileValidationError(
                "opaque Runtime id parts must be strings",
            )
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return require_safe_runtime_segment(
        f"{safe_prefix}-{digest.hexdigest()}",
        label="Hashed Runtime id",
    )


__all__ = ["hashed_runtime_segment", "require_safe_runtime_segment"]
