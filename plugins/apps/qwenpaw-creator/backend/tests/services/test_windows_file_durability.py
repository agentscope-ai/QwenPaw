# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from domain.errors import StorageIntegrityError
from services.media_files import keyframe_cache
from services.project_files import Project, ProjectStore
from services.project_files import remote_cache, store as project_store
from services.project_files.assets import StagedAsset
from services.project_files.models import SourceAssetVersion
from services.runtime_files import atomic_store, durability, jsonl_store
from services.workspace import content_store


pytestmark = pytest.mark.unit


class _WindowsLikeOS:
    """Expose regular file I/O but omit POSIX-only durability APIs."""

    name = "nt"

    def __getattr__(self, name: str):
        if name == "fchmod":
            raise AttributeError(name)
        return getattr(os, name)

    def open(
        self,
        path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd=None,
    ) -> int:
        if Path(path).is_dir():
            raise PermissionError("Windows cannot open directories this way")
        return os.open(path, flags, mode, dir_fd=dir_fd)


def test_atomic_writes_work_without_posix_durability_apis(
    tmp_path,
    monkeypatch,
) -> None:
    windows_os = _WindowsLikeOS()
    monkeypatch.setattr(atomic_store, "os", windows_os)
    monkeypatch.setattr(durability, "os", windows_os)

    replaced = tmp_path / "replaced.json"
    atomic_store.atomic_replace_bytes(replaced, b'{"value":1}\n')
    assert replaced.read_bytes() == b'{"value":1}\n'

    created = tmp_path / "created.json"
    assert atomic_store.atomic_create_bytes(created, b'{"value":2}\n')
    assert created.read_bytes() == b'{"value":2}\n'


def test_jsonl_append_works_without_fchmod(
    tmp_path,
    monkeypatch,
) -> None:
    windows_os = _WindowsLikeOS()
    monkeypatch.setattr(jsonl_store, "os", windows_os)
    monkeypatch.setattr(durability, "os", windows_os)
    store = jsonl_store.DurableJsonlStore(tmp_path / "events.jsonl")

    assert store.append({"event": "created"}).seq == 1
    assert store.read_records() == [{"event": "created"}]


def test_content_writes_work_without_posix_durability_apis(
    tmp_path,
    monkeypatch,
) -> None:
    windows_os = _WindowsLikeOS()
    monkeypatch.setattr(content_store, "os", windows_os)
    monkeypatch.setattr(durability, "os", windows_os)

    replaced = tmp_path / "metadata.json"
    content_store.atomic_replace_bytes(replaced, b'{"value":1}\n')
    assert replaced.read_bytes() == b'{"value":1}\n'

    source = tmp_path / "source.bin"
    source.write_bytes(b"content")
    copied = tmp_path / "copied.bin"
    content_store.atomic_copy_file(source, copied)
    assert copied.read_bytes() == b"content"


def test_content_write_keeps_directory_fsync_error_contract(
    tmp_path,
    monkeypatch,
) -> None:
    def fail_directory_fsync(_path) -> None:
        raise OSError("simulated directory failure")

    monkeypatch.setattr(
        content_store,
        "fsync_directory",
        fail_directory_fsync,
    )

    with pytest.raises(StorageIntegrityError, match="fsync"):
        content_store.atomic_replace_bytes(
            tmp_path / "metadata.json",
            b'{"value":1}\n',
        )


def test_project_create_works_without_directory_handles(
    tmp_path,
    monkeypatch,
) -> None:
    windows_os = _WindowsLikeOS()
    monkeypatch.setattr(project_store, "os", windows_os)
    monkeypatch.setattr(durability, "os", windows_os)

    store = ProjectStore(tmp_path.resolve())
    created = store.create(Project.new(project_id="project-1", name="Demo"))

    assert created.project.project_id == "project-1"
    assert store.read("project-1") == created


def test_keyframe_publish_works_without_directory_handles(
    tmp_path,
    monkeypatch,
) -> None:
    windows_os = _WindowsLikeOS()
    monkeypatch.setattr(keyframe_cache, "os", windows_os)
    monkeypatch.setattr(durability, "os", windows_os)
    project_root = tmp_path / "project-1"
    project_root.mkdir()
    source = project_root / "source.mp4"
    source.write_bytes(b"source-video")

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(keyframe_cache.subprocess, "run", fake_run)

    cached = keyframe_cache.materialize_keyframe(
        project_root,
        source_path=source,
        source_identity="sha256:source",
        timestamp_seconds=1,
        width=640,
        ffmpeg_path="fake-ffmpeg",
    )

    assert cached.path.read_bytes() == b"jpeg"


def test_remote_cache_publish_works_without_directory_handles(
    tmp_path,
    monkeypatch,
) -> None:
    windows_os = _WindowsLikeOS()
    monkeypatch.setattr(remote_cache, "os", windows_os)
    monkeypatch.setattr(durability, "os", windows_os)
    project_root = tmp_path / "project-1"
    project_root.mkdir()
    staged_path = tmp_path / "staged.mp4"
    payload = b"remote-video"
    staged_path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    staged = StagedAsset(
        project_root=project_root,
        path=staged_path,
        sha256=checksum,
        size_bytes=len(payload),
    )
    version = SourceAssetVersion(
        version_id="version-1",
        logical_asset_id="asset-1",
        name="source.mp4",
        file_id="file-1",
        checksum=checksum,
        media_kind="video",
        media_type="video/mp4",
        created_at=datetime.now(UTC),
    )

    published = remote_cache.publish_remote_cache(
        project_root,
        version,
        staged,
        media_type="video/mp4",
    )

    assert published.path.read_bytes() == payload
