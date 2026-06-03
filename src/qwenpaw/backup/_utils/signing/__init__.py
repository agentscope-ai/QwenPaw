# -*- coding: utf-8 -*-
"""Local backup signing utilities.

The signing key lives in ``BACKUP_DIR/.signing_key`` and is never included in
backup archives or restored from the secrets subsystem.  A valid signature
covers canonical ``meta.json`` data (excluding the signature field itself) and
all non-directory zip entries except ``meta.json``.
"""
from .digest import (
    SCHEME,
    compute_signature,
    signature_error,
    verify_signature,
)
from .key import get_signing_key
from .resign import replace_meta_with_local_signature
from .trust import (
    SignatureAction,
    resolve_signature_action,
    sign_trusted_backup,
)

__all__ = [
    "SCHEME",
    "SignatureAction",
    "compute_signature",
    "get_signing_key",
    "replace_meta_with_local_signature",
    "resolve_signature_action",
    "signature_error",
    "sign_trusted_backup",
    "verify_signature",
]
