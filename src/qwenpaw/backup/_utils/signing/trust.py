# -*- coding: utf-8 -*-
"""Trust decisions for locally signed backup archives.

Import and restore both need the same boundary check: a backup is either
already signed by this instance, or it requires an explicit user trust action
before being re-signed with the local key. Keeping that decision in the signing
package prevents import and restore from drifting apart.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Literal

from ...models import BackupMeta, BackupTrustMode
from .digest import signature_error, verify_signature
from .resign import replace_meta_with_local_signature

logger = logging.getLogger(__name__)

SignatureAction = Literal["none", "sign_trusted"]


def resolve_signature_action(
    zf: zipfile.ZipFile,
    meta: BackupMeta,
    backup_id: str,
    *,
    trust_mode: BackupTrustMode | None,
    operation: str,
) -> SignatureAction:
    """Verify local signature or return the trust action required.

    ``"none"`` means the archive already verifies with the local signing key.
    ``"sign_trusted"`` means the user explicitly trusted a legacy or foreign
    archive and the caller should re-sign it locally before using its bytes.
    """
    if meta.signature:
        if verify_signature(zf, meta):
            return "none"
        if trust_mode == "foreign":
            logger.warning(
                "%s foreign signed backup after explicit trust: %s",
                operation,
                backup_id,
            )
            return "sign_trusted"
        raise signature_error(meta)

    if trust_mode != "legacy":
        raise signature_error(meta)

    logger.warning(
        "%s legacy unsigned backup after explicit trust: %s",
        operation,
        backup_id,
    )
    return "sign_trusted"


def sign_trusted_backup(
    src_zip: Path,
    meta: BackupMeta,
    dest_zip: Path | None = None,
) -> BackupMeta:
    """Sign an explicitly trusted backup using this instance's key.

    Once the user has approved a legacy or foreign archive, re-signing it makes
    later imports/restores follow the normal local-signature path instead of
    asking for trust on every attempt.
    """
    logger.warning(
        "Signing trusted backup with local signature: %s",
        src_zip,
    )
    signed = meta.model_copy(
        update={"accepted_via_trust": True, "signature": None},
    )
    return replace_meta_with_local_signature(
        src_zip,
        signed,
        dest_zip=dest_zip,
    )
