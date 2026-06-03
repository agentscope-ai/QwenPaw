# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import zipfile

from qwenpaw.backup._utils.constants import META_FILE, PREFIX_CONFIG
from qwenpaw.backup._utils.signing import key as signing_key
from qwenpaw.backup._utils.signing.digest import (
    _assert_signed_fields_cover_model,
    verify_signature,
)
from qwenpaw.backup._utils.signing.resign import (
    replace_meta_with_local_signature,
)
from qwenpaw.backup.models import BackupMeta


def _reset_key_cache(monkeypatch, backup_dir):
    monkeypatch.setattr(signing_key, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(signing_key, "_cached_key", None)
    monkeypatch.setattr(signing_key, "_cached_mtime_ns", None)


def _write_backup(path, meta: BackupMeta) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(META_FILE, meta.model_dump_json())
        zf.writestr(
            PREFIX_CONFIG,
            json.dumps({"security": {"enabled": False}}),
        )
        zf.writestr("data/workspaces/a/agent.json", "{}")


def test_resign_writes_verifiable_local_signature(tmp_path, monkeypatch):
    _reset_key_cache(monkeypatch, tmp_path)
    src = tmp_path / "backup.zip"
    meta = BackupMeta(
        id="signed-test",
        name="Signed test",
        accepted_via_trust=False,
    )
    _write_backup(src, meta)

    signed_meta = replace_meta_with_local_signature(src, meta)

    assert signed_meta.signature
    with zipfile.ZipFile(src, "r") as zf:
        assert verify_signature(zf, signed_meta)
        tampered_meta = signed_meta.model_copy(update={"name": "tampered"})
        assert not verify_signature(zf, tampered_meta)


def test_signed_fields_cover_backup_meta_model():
    _assert_signed_fields_cover_model()
