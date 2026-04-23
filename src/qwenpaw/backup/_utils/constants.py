# -*- coding: utf-8 -*-
"""Shared constants and path helpers used across backup sub-modules."""
from __future__ import annotations

import re
from pathlib import Path

from ...constant import BACKUP_DIR

META_FILE = "meta.json"

# Zip internal path prefixes – defined once to avoid scattered hardcoding.
# PREFIX_CONFIG is intentionally hardcoded to "data/config.json" and NOT
# derived from the QWENPAW_CONFIG_FILE env-var so that backup archives are
# portable across installations regardless of runtime configuration.
PREFIX_WORKSPACES = "data/workspaces/"
PREFIX_SECRETS = "data/secrets/"
PREFIX_SKILL_POOL = "data/skill_pool/"
PREFIX_CONFIG = "data/config.json"

# Allowed characters for a backup ID. Accepts both the new human-readable
# format (qwenpaw-{ver}-{ts}-{short8}) and legacy UUID strings.
# Forbids path-traversal characters: '/', '\', '..', NUL, etc.
BACKUP_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,200}$")


def validate_backup_id(backup_id: str) -> None:
    """Raise ``ValueError`` if *backup_id* contains unsafe characters."""
    if not BACKUP_ID_RE.match(backup_id):
        raise ValueError(
            f"Invalid backup id {backup_id!r}: "
            f"must match {BACKUP_ID_RE.pattern}",
        )


def zip_path(backup_id: str) -> Path:
    return BACKUP_DIR / f"{backup_id}.zip"
