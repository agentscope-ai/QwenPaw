# -*- coding: utf-8 -*-
"""Channel key, source digest, and shared interpreter validation."""

from __future__ import annotations

from collections.abc import Collection
import re

from packaging.tags import sys_tags

from .errors import validation_error


_CHANNEL_KEY_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$",
)
_PYTHON_ABI_PATTERN = re.compile(r"^[a-z0-9_]+-[a-z0-9_]+$")
_PLATFORM_TAG_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PLATFORM_ALIASES = frozenset({"windows", "darwin", "macos", "x86_64"})


def validate_channel_key(value: str) -> str:
    """Validate a canonical v1 builtin or isolated Channel key."""
    if not isinstance(value, str) or not _CHANNEL_KEY_PATTERN.fullmatch(value):
        raise validation_error("Channel key is not canonical")
    return value


def validate_digest(value: str, *, name: str = "digest") -> str:
    """Validate a complete lowercase SHA-256 hexadecimal digest."""
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise validation_error(f"{name} must be 64 lowercase hex characters")
    return value


def validate_python_abi(value: str) -> str:
    """Validate the canonical interpreter-ABI pair."""
    if not isinstance(value, str) or not _PYTHON_ABI_PATTERN.fullmatch(value):
        raise validation_error("Python ABI is not canonical")
    return value


def current_python_abi() -> str:
    """Return the current interpreter's first concrete PEP 425 ABI."""
    for tag in sys_tags():
        if tag.abi != "none":
            return validate_python_abi(f"{tag.interpreter}-{tag.abi}")
    raise validation_error("Current interpreter has no concrete ABI tag")


def validate_platform_tag(
    value: str,
    *,
    allowed_platform_tags: Collection[str],
) -> str:
    """Validate syntax and release-target registry membership."""
    if not isinstance(value, str) or not _PLATFORM_TAG_PATTERN.fullmatch(
        value,
    ):
        raise validation_error("Platform tag is not canonical")
    if value in _PLATFORM_ALIASES:
        raise validation_error("Product platform aliases are not PEP 425 tags")
    if value not in allowed_platform_tags:
        raise validation_error("Platform tag is not in the release registry")
    return value
