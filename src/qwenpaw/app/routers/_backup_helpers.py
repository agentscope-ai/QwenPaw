# -*- coding: utf-8 -*-
"""Small helpers for backup API routes.

Kept separate from the router so trust-token validation and public response
shaping are shared by import/list/detail/restore without expanding the route
handlers themselves.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from ...backup.models import BackupMeta, BackupValidationError
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
