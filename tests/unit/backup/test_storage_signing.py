# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import zipfile

import pytest

from qwenpaw.backup._ops import storage
from qwenpaw.backup._utils import constants
from qwenpaw.backup._utils.constants import META_FILE, PREFIX_CONFIG
from qwenpaw.backup._utils.signing import key as signing_key
from qwenpaw.backup._utils.signing.digest import verify_signature
from qwenpaw.backup._utils.signing.resign import (
    replace_meta_with_local_signature,
)
from qwenpaw.backup.models import (
    BackupConflictError,
    BackupMeta,
    BackupValidationError,
)


def _patch_backup_dir(monkeypatch, backup_dir):
    monkeypatch.setattr(storage, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(constants, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(signing_key, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(signing_key, "_cached_key", None)
    monkeypatch.setattr(signing_key, "_cached_mtime_ns", None)


def _write_backup(path, meta: BackupMeta) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(META_FILE, meta.model_dump_json())
        zf.writestr(PREFIX_CONFIG, json.dumps({"security": {"x": 1}}))


@pytest.mark.asyncio
async def test_import_requires_trust_for_unsigned_backup(
    tmp_path,
    monkeypatch,
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _patch_backup_dir(monkeypatch, backup_dir)
    upload = tmp_path / "upload.zip"
    _write_backup(upload, BackupMeta(id="legacy", name="Legacy"))

    with pytest.raises(BackupValidationError) as exc_info:
        await storage.import_backup(upload)

    assert exc_info.value.code == "backup_legacy_unsigned"


@pytest.mark.asyncio
async def test_import_trusted_legacy_signs_with_local_key(
    tmp_path,
    monkeypatch,
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _patch_backup_dir(monkeypatch, backup_dir)
    upload = tmp_path / "upload.zip"
    _write_backup(upload, BackupMeta(id="legacy", name="Legacy"))

    with pytest.raises(BackupValidationError) as wrong_trust:
        await storage.import_backup(upload, trust_mode="foreign")

    assert wrong_trust.value.code == "backup_legacy_unsigned"

    result = await storage.import_backup(upload, trust_mode="legacy")

    assert result.accepted_via_trust is True
    assert result.signature
    dest = backup_dir / "legacy.zip"
    with zipfile.ZipFile(dest, "r") as zf:
        meta = BackupMeta.model_validate_json(zf.read(META_FILE))
        assert meta.accepted_via_trust is True
        assert verify_signature(zf, meta)


@pytest.mark.asyncio
async def test_import_trusted_foreign_signature_signs_with_local_key(
    tmp_path,
    monkeypatch,
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _patch_backup_dir(monkeypatch, backup_dir)

    upload = tmp_path / "foreign.zip"
    foreign_keys = tmp_path / "foreign-keys"
    foreign_keys.mkdir()
    _patch_backup_dir(monkeypatch, foreign_keys)
    foreign_meta = BackupMeta(
        id="foreign-signed",
        name="Foreign signed",
        accepted_via_trust=False,
    )
    _write_backup(upload, foreign_meta)
    replace_meta_with_local_signature(upload, foreign_meta)

    _patch_backup_dir(monkeypatch, backup_dir)
    with pytest.raises(BackupValidationError) as wrong_trust:
        await storage.import_backup(upload, trust_mode="legacy")

    assert wrong_trust.value.code == "backup_signature_mismatch"

    result = await storage.import_backup(upload, trust_mode="foreign")

    assert result.accepted_via_trust is True
    dest = backup_dir / "foreign-signed.zip"
    with zipfile.ZipFile(dest, "r") as zf:
        meta = BackupMeta.model_validate_json(zf.read(META_FILE))
        assert meta.accepted_via_trust is True
        assert verify_signature(zf, meta)


@pytest.mark.asyncio
async def test_import_conflict_uses_existing_disk_meta(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _patch_backup_dir(monkeypatch, backup_dir)

    existing_path = backup_dir / "same.zip"
    existing_meta = BackupMeta(
        id="same",
        name="Existing",
        accepted_via_trust=False,
    )
    _write_backup(existing_path, existing_meta)
    replace_meta_with_local_signature(existing_path, existing_meta)

    upload = tmp_path / "upload.zip"
    _write_backup(upload, BackupMeta(id="same", name="Uploaded"))

    with pytest.raises(BackupConflictError) as exc_info:
        await storage.import_backup(upload, trust_mode="legacy")

    assert exc_info.value.existing_meta.name == "Existing"


@pytest.mark.asyncio
async def test_operations_find_backup_when_filename_differs_from_id(
    tmp_path,
    monkeypatch,
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _patch_backup_dir(monkeypatch, backup_dir)

    backup_path = backup_dir / "old-backup.zip"
    _write_backup(
        backup_path,
        BackupMeta(id="canonical-id", name="Copied backup"),
    )

    detail = await storage.get_backup("canonical-id")
    assert detail is not None
    assert detail.name == "Copied backup"

    export_path, export_name = await storage.export_backup("canonical-id")
    assert export_path == backup_path
    assert export_name == "Copied backup"

    result = await storage.delete_backups(["canonical-id"])
    assert result.deleted == ["canonical-id"]
    assert result.failed == []
    assert not backup_path.exists()


@pytest.mark.asyncio
async def test_import_conflict_detects_noncanonical_existing_backup(
    tmp_path,
    monkeypatch,
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _patch_backup_dir(monkeypatch, backup_dir)

    existing_path = backup_dir / "copied-name.zip"
    _write_backup(
        existing_path,
        BackupMeta(id="same-id", name="Existing copied"),
    )

    upload = tmp_path / "upload.zip"
    _write_backup(upload, BackupMeta(id="same-id", name="Uploaded"))

    with pytest.raises(BackupConflictError) as exc_info:
        await storage.import_backup(upload, trust_mode="legacy")

    assert exc_info.value.existing_meta.name == "Existing copied"
