# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import os

import pytest

from services.project_files.assets import (
    AssetAlreadyExists,
    AssetFileCorrupt,
    AssetFileStatus,
    AssetFileStore,
    AssetPathError,
    StagedAssetError,
)
from services.project_files.models import AssetIndex, IndexedFile


pytestmark = pytest.mark.unit
NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


def _store(tmp_path, name: str = "project-1") -> AssetFileStore:
    root = (tmp_path / name).resolve()
    root.mkdir()
    return AssetFileStore(root, chunk_size=3)


def _indexed(
    *,
    file_id: str,
    relative_uri: str,
    content: bytes,
    sha256: str | None = None,
    size_bytes: int | None = None,
) -> IndexedFile:
    return IndexedFile(
        file_id=file_id,
        kind="other",
        relative_uri=relative_uri,
        sha256=sha256 or hashlib.sha256(content).hexdigest(),
        size_bytes=len(content) if size_bytes is None else size_bytes,
        media_type="application/octet-stream",
        created_at=NOW,
    )


def test_streaming_stage_and_immutable_publish_are_fsynced(
    tmp_path,
    monkeypatch,
):
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def record_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr("services.project_files.assets.os.fsync", record_fsync)
    store = _store(tmp_path)
    content = b"streamed-asset-payload"

    staged = store.stage_stream(BytesIO(content), staging_id="upload-1")
    assert staged.path.is_file()
    assert staged.size_bytes == len(content)
    assert staged.sha256 == hashlib.sha256(content).hexdigest()

    published = store.publish(
        staged,
        "assets/sources/source-1/version-1/original.bin",
        expected_sha256=staged.sha256,
        expected_size_bytes=staged.size_bytes,
    )

    final = store.project_root / published.relative_uri
    assert final.read_bytes() == content
    assert not staged.path.exists()
    assert published.sha256 == staged.sha256
    assert (
        len(fsync_calls) >= 5
    )  # staging file/dir, created dirs, final/staging dirs
    assert not (store.assets_root / "ai-edit-plans").exists()


def test_publish_never_overwrites_an_existing_immutable_path(tmp_path):
    store = _store(tmp_path)
    uri = "assets/artifacts/slot-1/version-1/payload.bin"
    first = store.stage_bytes(b"first")
    store.publish(first, uri)
    second = store.stage_bytes(b"second")

    with pytest.raises(AssetAlreadyExists):
        store.publish(second, uri)

    assert (store.project_root / uri).read_bytes() == b"first"
    assert second.path.exists()
    store.abandon(second)
    assert not second.path.exists()


def test_publish_rechecks_staged_content_before_moving_it(tmp_path):
    store = _store(tmp_path)
    staged = store.stage_bytes(b"before")
    staged.path.write_bytes(b"after!")

    with pytest.raises(StagedAssetError, match="modified"):
        store.publish(staged, "assets/content/file-1.bin")

    assert not (store.assets_root / "content" / "file-1.bin").exists()


@pytest.mark.parametrize(
    "relative_uri",
    [
        "../outside.bin",
        "/assets/content/file.bin",
        r"assets\content\file.bin",
        "assets/.staging/file.bin",
        "assets/content/bad\x01.bin",
    ],
)
def test_publish_rejects_noncanonical_or_reserved_paths(
    tmp_path,
    relative_uri,
):
    store = _store(tmp_path)
    staged = store.stage_bytes(b"payload")

    with pytest.raises(AssetPathError):
        store.publish(staged, relative_uri)

    assert staged.path.exists()


def test_symlink_parents_and_symlink_files_cannot_escape_project(tmp_path):
    store = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, store.assets_root / "sources")
    staged = store.stage_bytes(b"payload")

    with pytest.raises(AssetPathError, match="non-symlink"):
        store.publish(staged, "assets/sources/source-1/version-1/original.bin")

    (store.assets_root / "content").mkdir()
    outside_file = outside / "outside.bin"
    outside_file.write_bytes(b"outside")
    os.symlink(outside_file, store.assets_root / "content" / "linked.bin")
    indexed = _indexed(
        file_id="file-linked",
        relative_uri="assets/content/linked.bin",
        content=b"outside",
    )

    assert store.inspect(indexed).status is AssetFileStatus.UNSAFE
    with pytest.raises(AssetPathError, match="symlink"):
        store.open_verified(indexed)


def test_index_validation_and_reads_verify_presence_size_and_sha256(tmp_path):
    store = _store(tmp_path)
    valid_content = b"valid"
    corrupt_content = b"wrong"
    valid_uri = "assets/content/valid.bin"
    corrupt_uri = "assets/content/corrupt.bin"
    store.publish(store.stage_bytes(valid_content), valid_uri)
    store.publish(store.stage_bytes(corrupt_content), corrupt_uri)

    index = AssetIndex(
        files_by_id={
            "file-valid": _indexed(
                file_id="file-valid",
                relative_uri=valid_uri,
                content=valid_content,
            ),
            "file-corrupt": _indexed(
                file_id="file-corrupt",
                relative_uri=corrupt_uri,
                content=corrupt_content,
                sha256="0" * 64,
            ),
            "file-missing": _indexed(
                file_id="file-missing",
                relative_uri="assets/content/missing.bin",
                content=b"missing",
            ),
        },
    )

    report = store.validate_index(index)
    assert [item.file_id for item in report.files] == [
        "file-corrupt",
        "file-missing",
        "file-valid",
    ]
    assert {item.file_id: item.status for item in report.files} == {
        "file-corrupt": AssetFileStatus.CORRUPT,
        "file-missing": AssetFileStatus.MISSING,
        "file-valid": AssetFileStatus.AVAILABLE,
    }
    assert not report.valid
    assert (
        store.read_verified(index.files_by_id["file-valid"]) == valid_content
    )
    with pytest.raises(AssetFileCorrupt, match="sha256"):
        store.open_verified(index.files_by_id["file-corrupt"])
    with pytest.raises(AssetFileCorrupt, match="unavailable"):
        store.require_valid_index(index)


def test_orphan_scan_marks_candidates_and_requires_persisted_grace(tmp_path):
    store = _store(tmp_path)
    indexed_content = b"indexed"
    indexed_uri = "assets/content/indexed.bin"
    orphan_uri = "assets/content/orphan.bin"
    store.publish(store.stage_bytes(indexed_content), indexed_uri)
    store.publish(store.stage_bytes(b"orphan"), orphan_uri)
    staged = store.stage_bytes(b"in-flight")

    # An old mtime must not let a newly discovered orphan skip its grace period.
    os.utime(store.project_root / orphan_uri, (1, 1))
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    os.symlink(outside, store.assets_root / "linked.bin")
    index = AssetIndex(
        files_by_id={
            "file-indexed": _indexed(
                file_id="file-indexed",
                relative_uri=indexed_uri,
                content=indexed_content,
            ),
        },
    )

    first = store.scan_orphans(index, now=NOW, grace_period=timedelta(hours=1))
    assert [item.relative_uri for item in first.candidates] == [orphan_uri]
    assert first.candidates[0].first_observed_at == NOW
    assert not first.candidates[0].eligible_for_collection
    assert first.unsafe_entries == ("assets/linked.bin",)
    assert (
        staged.path.exists()
    )  # .staging is excluded from orphan publication GC

    second = store.scan_orphans(
        index,
        previous_candidates={orphan_uri: NOW - timedelta(hours=2)},
        now=NOW,
        grace_period=timedelta(hours=1),
    )
    assert second.candidates[0].eligible_for_collection
    assert (store.project_root / orphan_uri).exists()  # scan never deletes

    with pytest.raises(ValueError, match="positive"):
        store.scan_orphans(index, now=NOW, grace_period=timedelta(0))
