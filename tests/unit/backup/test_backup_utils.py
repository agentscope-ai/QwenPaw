# -*- coding: utf-8 -*-
# pylint: disable=consider-using-with
"""Unit tests for backup/_utils/meta.py and backup/_utils/constants.py.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the remaining uncovered
branches in the backup metadata and ID-validation helpers.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from types import SimpleNamespace

import pytest

from qwenpaw.backup._utils import constants as bc
from qwenpaw.backup._utils import meta as bm


# ---------------------------------------------------------------------------
# meta.py
# ---------------------------------------------------------------------------


class TestGetQwenpawVersion:
    def test_returns_version_string(self):
        version = bm.get_qwenpaw_version()
        assert isinstance(version, str)
        assert version != ""

    def test_import_failure_returns_unknown(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "qwenpaw.__version__":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        # Drop the cached module so the import actually runs.
        monkeypatch.delitem(sys.modules, "qwenpaw.__version__", raising=False)
        assert bm.get_qwenpaw_version() == "unknown"


class TestGenerateBackupId:
    def test_format(self):
        backup_id = bm.generate_backup_id()
        assert backup_id.startswith("qwenpaw-")
        parts = backup_id.split("-")
        # qwenpaw-{version}-{ts}-{short8}
        assert len(parts[-1]) == 8
        assert parts[-2].endswith("Z")

    def test_filesystem_safe(self):
        backup_id = bm.generate_backup_id()
        assert "/" not in backup_id
        assert "\\" not in backup_id


class TestGetSystemInfo:
    def test_snapshot_keys(self):
        info = bm.get_system_info()
        assert set(info) == {
            "os",
            "os_version",
            "os_release",
            "machine",
            "python_version",
            "python_implementation",
        }


class TestFinalizeBackupMeta:
    def test_populates_fields(self):
        meta = SimpleNamespace(
            agent_count=0,
            qwenpaw_version="",
            system_info={},
        )
        bm.finalize_backup_meta(meta, 3)
        assert meta.agent_count == 3
        assert meta.qwenpaw_version != ""
        assert meta.system_info["os"]


class TestReadMetaFromZip:
    def test_reads_meta_json(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(bm.META_FILE, '{"id": "x"}')
        zf = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
        assert bm.read_meta_from_zip(zf) == '{"id": "x"}'

    def test_missing_meta_returns_none(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.txt", "x")
        zf = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
        assert bm.read_meta_from_zip(zf) is None


# ---------------------------------------------------------------------------
# constants.py
# ---------------------------------------------------------------------------


class TestValidateBackupId:
    @pytest.mark.parametrize(
        "good",
        ["qwenpaw-1.0-20260101T000000Z-ab12cd34", "abc", "A-b_c.9"],
    )
    def test_valid_ids(self, good):
        bc.validate_backup_id(good)  # no raise

    @pytest.mark.parametrize(
        "bad",
        ["", "../etc/passwd", "a/b", "a\\b", "a b", "x" * 201],
    )
    def test_invalid_ids_raise(self, bad):
        with pytest.raises(ValueError, match="Invalid backup id"):
            bc.validate_backup_id(bad)


class TestFindZipPath:
    def test_invalid_id_returns_none(self):
        assert bc.find_zip_path("../bad") is None

    def test_canonical_zip_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "BACKUP_DIR", tmp_path)
        zp = tmp_path / "b1.zip"
        zp.write_bytes(b"PK\x03\x04")
        assert bc.find_zip_path("b1") == zp

    def test_missing_dir_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "BACKUP_DIR", tmp_path / "nope")
        assert bc.find_zip_path("b1") is None

    def test_matches_meta_id_in_other_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "BACKUP_DIR", tmp_path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(bc.META_FILE, json.dumps({"id": "b1"}))
        (tmp_path / "imported-archive.zip").write_bytes(buf.getvalue())
        found = bc.find_zip_path("b1")
        assert found == tmp_path / "imported-archive.zip"

    def test_skips_zip_without_meta(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "BACKUP_DIR", tmp_path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.txt", "x")
        (tmp_path / "nometa.zip").write_bytes(buf.getvalue())
        assert bc.find_zip_path("b1") is None

    def test_skips_corrupt_zip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "BACKUP_DIR", tmp_path)
        (tmp_path / "corrupt.zip").write_bytes(b"not a zip")
        assert bc.find_zip_path("b1") is None

    def test_skips_mismatched_meta_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "BACKUP_DIR", tmp_path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(bc.META_FILE, json.dumps({"id": "other"}))
        (tmp_path / "other.zip").write_bytes(buf.getvalue())
        assert bc.find_zip_path("b1") is None


class TestZipPath:
    def test_path_under_backup_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bc, "BACKUP_DIR", tmp_path)
        assert bc.zip_path("b1") == tmp_path / "b1.zip"
