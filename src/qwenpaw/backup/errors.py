# -*- coding: utf-8 -*-
"""Custom exceptions for user asset backup & migration."""
from __future__ import annotations


class InvalidAssetPackageError(Exception):
    """Raised when a ZIP asset package is invalid or corrupted.

    Examples: missing manifest.json, malformed JSON, checksum mismatch.
    """


class IncompatibleVersionError(Exception):
    """Raised when the asset package schema version is incompatible.

    This happens when the package's major version is higher than the
    current system version, or when a required migration path is missing.
    """


class InsufficientStorageError(Exception):
    """Raised when there is not enough disk space for backup or import."""
