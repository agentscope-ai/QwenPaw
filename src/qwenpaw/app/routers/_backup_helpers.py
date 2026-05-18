# -*- coding: utf-8 -*-
"""Small helpers for backup API routes.

Kept separate from the router so trust-token validation and public response
shaping are shared by import/list/detail/restore without expanding the route
handlers themselves.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi import HTTPException

from ...backup._utils.constants import PREFIX_CONFIG, zip_path
from ...backup._ops.restore_helpers import (
    LOCAL_PROTECTED_CONFIG_KEYS,
    resolve_preserve_flag,
)
from ...backup.models import (
    BackupMeta,
    BackupValidationError,
    RestoreBackupRequest,
)
from ...constant import BACKUP_DIR

TMP_UPLOAD_SUFFIX = ".upload_tmp"
TMP_TRUST_SUFFIX = ".upload_tmp.trust"


def parse_pending_token(token: str) -> tuple[Path, bool]:
    """Return ``(tmp_path, trust_foreign)`` for a safe pending token.

    Pending import tokens are temp filenames, not arbitrary paths. Resolving
    them under BACKUP_DIR prevents retry-after-conflict from becoming a path
    traversal primitive.
    """
    backup_dir = BACKUP_DIR.resolve()
    tmp_path = (BACKUP_DIR / token).resolve()
    if tmp_path.parent != backup_dir:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired pending_token",
        )
    trust_foreign = token.endswith(TMP_TRUST_SUFFIX)
    if not (trust_foreign or token.endswith(TMP_UPLOAD_SUFFIX)):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired pending_token",
        )
    if not tmp_path.is_file():
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired pending_token",
        )
    return tmp_path, trust_foreign


def strip_signature(meta: BackupMeta) -> BackupMeta:
    """Hide the HMAC while preserving the public trust-state signal.

    Clients only need to know whether the backup is local/foreign/legacy.
    Returning the raw HMAC would add no UI value and would expose an internal
    integrity token in API responses.
    """
    updates: dict[str, object | None] = {"signature": None}
    if meta.signature is None:
        updates["imported_via_trust_foreign"] = None
    return meta.model_copy(update=updates)


def validation_detail(exc: BackupValidationError) -> dict[str, object]:
    """Convert stable backup validation failures to FastAPI detail payloads."""
    return {"code": exc.code, "message": exc.message, **exc.details}


def restored_local_keys(
    req: RestoreBackupRequest,
    meta: BackupMeta,
    *,
    archive_has_global_config: bool,
) -> list[str]:
    """Return protected local keys preserved by a completed restore.

    Match the actual staging condition in ``_stage_global_config``: config
    must be requested, the archive must contain config.json, and preservation
    must be enabled for this local/foreign trust state.
    """
    if not req.include_global_config:
        return []
    if not archive_has_global_config:
        return []
    if not resolve_preserve_flag(req, meta):
        return []
    return list(LOCAL_PROTECTED_CONFIG_KEYS)


def backup_contains_global_config(backup_id: str) -> bool:
    """Return whether the stored archive has a config payload to restore."""
    try:
        with zipfile.ZipFile(zip_path(backup_id), "r") as zf:
            return PREFIX_CONFIG in zf.namelist()
    except (FileNotFoundError, zipfile.BadZipFile):
        return False
