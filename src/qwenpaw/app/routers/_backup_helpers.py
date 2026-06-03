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

from ...backup._utils.constants import PREFIX_CONFIG, find_zip_path
from ...backup._ops.restore_helpers import (
    LOCAL_PROTECTED_CONFIG_KEYS,
    resolve_preserve_flag,
)
from ...backup.models import (
    BackupMeta,
    BackupTrustMode,
    BackupValidationError,
    RestoreBackupRequest,
)
from ...constant import BACKUP_DIR

TMP_UPLOAD_SUFFIX = ".upload_tmp"
TMP_TRUST_LEGACY_SUFFIX = ".upload_tmp.trust_legacy"
TMP_TRUST_FOREIGN_SUFFIX = ".upload_tmp.trust_foreign"
_TRUST_SUFFIX_BY_MODE: dict[BackupTrustMode, str] = {
    "legacy": TMP_TRUST_LEGACY_SUFFIX,
    "foreign": TMP_TRUST_FOREIGN_SUFFIX,
}


def upload_suffix_for_trust_mode(
    trust_mode: BackupTrustMode | None,
) -> str:
    """Return the temp upload suffix that preserves the trust choice."""
    if trust_mode is None:
        return TMP_UPLOAD_SUFFIX
    return _TRUST_SUFFIX_BY_MODE[trust_mode]


def parse_pending_token(
    token: str,
) -> tuple[Path, BackupTrustMode | None]:
    """Return ``(tmp_path, trust_mode)`` for a safe pending token.

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
    trust_mode: BackupTrustMode | None = None
    for mode, suffix in _TRUST_SUFFIX_BY_MODE.items():
        if token.endswith(suffix):
            trust_mode = mode
            break
    if trust_mode is None and not token.endswith(TMP_UPLOAD_SUFFIX):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired pending_token",
        )
    if not tmp_path.is_file():
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired pending_token",
        )
    return tmp_path, trust_mode


def strip_signature(meta: BackupMeta) -> BackupMeta:
    """Hide the HMAC while preserving the public trust-state signal.

    Clients only need the public trust marker, not the raw HMAC. Returning the
    signature would add no UI value and would expose an internal integrity
    token in API responses.
    """
    updates: dict[str, object | None] = {"signature": None}
    if meta.signature is None:
        updates["accepted_via_trust"] = None
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
    must be enabled for this backup's trust state.
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
        zp = find_zip_path(backup_id)
        if zp is None:
            return False
        with zipfile.ZipFile(zp, "r") as zf:
            return PREFIX_CONFIG in zf.namelist()
    except (FileNotFoundError, zipfile.BadZipFile):
        return False
