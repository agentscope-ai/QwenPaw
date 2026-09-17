# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from qwenpaw.backup._utils.signing import (
    resolve_signature_action,
    sign_trusted_backup,
)
from qwenpaw.backup._utils.constants import META_FILE, PREFIX_CONFIG
from qwenpaw.backup._utils.signing import key as signing_key
from qwenpaw.backup._utils.signing.digest import verify_signature
from qwenpaw.backup._utils.signing.resign import (
    replace_meta_with_local_signature,
)
from qwenpaw.backup.models import BackupMeta, BackupValidationError


def _reset_key_cache(
    monkeypatch: pytest.MonkeyPatch,
    backup_dir: Path,
) -> None:
    monkeypatch.setattr(signing_key, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(signing_key, "_cached_key", None)
    monkeypatch.setattr(signing_key, "_cached_mtime_ns", None)


def _write_backup(path: Path, meta: BackupMeta) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(META_FILE, meta.model_dump_json())
        zf.writestr(PREFIX_CONFIG, json.dumps({"security": {"x": 1}}))


def test_restore_requires_explicit_trust_for_foreign_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_path = tmp_path / "foreign.zip"
    meta = BackupMeta(
        id="foreign",
        name="Foreign",
        accepted_via_trust=False,
    )

    _reset_key_cache(monkeypatch, tmp_path / "foreign-keys")
    _write_backup(backup_path, meta)
    replace_meta_with_local_signature(backup_path, meta)

    _reset_key_cache(monkeypatch, tmp_path / "local-keys")
    with zipfile.ZipFile(backup_path, "r") as zf:
        foreign_meta = BackupMeta.model_validate_json(zf.read(META_FILE))
        assert not verify_signature(zf, foreign_meta)

        with pytest.raises(BackupValidationError) as exc_info:
            resolve_signature_action(
                zf,
                foreign_meta,
                "foreign",
                trust_mode=None,
                operation="Restoring",
            )

        assert exc_info.value.code == "backup_signature_mismatch"
        with pytest.raises(BackupValidationError) as wrong_trust:
            resolve_signature_action(
                zf,
                foreign_meta,
                "foreign",
                trust_mode="legacy",
                operation="Restoring",
            )

        assert wrong_trust.value.code == "backup_signature_mismatch"
        assert (
            resolve_signature_action(
                zf,
                foreign_meta,
                "foreign",
                trust_mode="foreign",
                operation="Restoring",
            )
            == "sign_trusted"
        )


def test_restore_trusted_foreign_backup_gets_local_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_path = tmp_path / "foreign.zip"
    meta = BackupMeta(
        id="foreign",
        name="Foreign",
        accepted_via_trust=False,
    )

    _reset_key_cache(monkeypatch, tmp_path / "foreign-keys")
    _write_backup(backup_path, meta)
    replace_meta_with_local_signature(backup_path, meta)

    _reset_key_cache(monkeypatch, tmp_path / "local-keys")
    with zipfile.ZipFile(backup_path, "r") as zf:
        foreign_meta = BackupMeta.model_validate_json(zf.read(META_FILE))
        assert not verify_signature(zf, foreign_meta)

    trusted_meta = sign_trusted_backup(backup_path, foreign_meta)

    assert trusted_meta.accepted_via_trust is True
    with zipfile.ZipFile(backup_path, "r") as zf:
        local_meta = BackupMeta.model_validate_json(zf.read(META_FILE))
        assert local_meta.accepted_via_trust is True
        assert verify_signature(zf, local_meta)
