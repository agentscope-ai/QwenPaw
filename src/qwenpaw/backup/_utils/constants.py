# -*- coding: utf-8 -*-
"""Shared constants and path helpers used across backup sub-modules."""
from __future__ import annotations

import json
import re
import zipfile
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


def find_zip_path(backup_id: str) -> Path | None:
    """Return the stored zip path for *backup_id*, regardless of filename.

    Imported backups are stored as ``{backup_id}.zip``, but users may also
    copy older archives into the backup directory under arbitrary filenames.
    The list endpoint already discovers those files by reading ``meta.json``;
    this helper keeps detail/export/restore/delete on the same lookup rule.
    """
    try:
        validate_backup_id(backup_id)
    except ValueError:
        return None
    canonical = zip_path(backup_id)
    if canonical.is_file():
        return canonical
    if not BACKUP_DIR.is_dir():
        return None

    for path in sorted(BACKUP_DIR.iterdir(), key=lambda item: item.name):
        if path == canonical or not (path.is_file() and path.suffix == ".zip"):
            continue
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if META_FILE not in zf.namelist():
                    continue
                meta = json.loads(zf.read(META_FILE).decode("utf-8"))
        except Exception:
            continue
        if meta.get("id") == backup_id:
            return path
    return None
