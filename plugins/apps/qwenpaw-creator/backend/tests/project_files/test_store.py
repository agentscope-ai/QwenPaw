# -*- coding: utf-8 -*-
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os

import pytest

from services.project_files import (
    Project,
    ProjectAlreadyExists,
    ProjectConflict,
    ProjectIntegrityError,
    ProjectNotFound,
    ProjectStore,
    UnsafeProjectPath,
)
from services.project_files import store as store_module


pytestmark = pytest.mark.unit


def _project(project_id: str, name: str = "Project") -> Project:
    return Project.new(
        project_id=project_id,
        name=name,
        now=datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc),
    )


def _next(project: Project, *, name: str = "Updated") -> Project:
    raw = project.model_dump(mode="python")
    raw["generation"] = project.generation + 1
    raw["updated_at"] = project.updated_at + timedelta(seconds=1)
    raw["name"] = name
    return Project.model_validate(raw)


def test_create_read_list_replace_and_delete(tmp_path):
    store = ProjectStore(tmp_path.resolve())
    created = store.create(_project("project-b", "B"))
    store.create(_project("project-a", "A"))

    assert created.generation == 0
    assert created.etag.startswith("sha256:")
    assert store.project_path("project-b").is_file()
    assert (store.project_root("project-b") / "assets").is_dir()
    assert (
        store.project_root("project-b") / "observability" / "logs"
    ).is_dir()
    assert (
        store.project_root("project-b") / "observability" / "traces"
    ).is_dir()
    assert (store.project_root("project-b") / "runtime" / "temp").is_dir()
    assert store.read("project-b") == created
    assert [item.project_id for item in store.list()] == [
        "project-a",
        "project-b",
    ]

    replacement = _next(created.project)
    updated = store.replace(
        "project-b",
        replacement,
        expected_etag=created.etag,
    )
    assert updated.generation == 1
    assert updated.project.name == "Updated"
    assert updated.etag != created.etag

    store.delete("project-b", expected_etag=updated.etag)
    with pytest.raises(ProjectNotFound):
        store.read("project-b")
    assert [item.project_id for item in store.list()] == ["project-a"]


def test_create_is_exclusive_and_does_not_overwrite(tmp_path):
    store = ProjectStore(tmp_path.resolve())
    first = store.create(_project("project-1", "First"))

    with pytest.raises(ProjectAlreadyExists):
        store.create(_project("project-1", "Second"))

    assert store.read("project-1") == first


def test_create_staging_initializer_is_published_atomically_or_rolled_back(
    tmp_path,
):
    store = ProjectStore(tmp_path.resolve())

    def initialize(staged_root):
        assert (staged_root / "project.json").is_file()
        (staged_root / "runtime" / "bootstrap.txt").write_text(
            "ready",
            encoding="utf-8",
        )

    store.create(
        _project("project-ready"),
        initialize_staged_project=initialize,
    )
    assert (
        store.project_root("project-ready") / "runtime" / "bootstrap.txt"
    ).read_text(encoding="utf-8") == "ready"

    def fail(_staged_root):
        raise RuntimeError("injected bootstrap failure")

    with pytest.raises(RuntimeError, match="injected bootstrap failure"):
        store.create(
            _project("project-failed"),
            initialize_staged_project=fail,
        )

    assert not store.project_root("project-failed").exists()
    assert [item.project_id for item in store.list()] == ["project-ready"]


def test_create_and_delete_acquire_lifecycle_before_store_lock(
    tmp_path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path.resolve())
    events: list[str] = []

    class TraceLock:
        def __init__(self, name: str) -> None:
            self.name = name

        def __enter__(self):
            events.append(f"enter:{self.name}")
            return self

        def __exit__(self, *_args) -> None:
            events.append(f"exit:{self.name}")

    store._lock = TraceLock("store")
    monkeypatch.setattr(
        store,
        "lifecycle_lock",
        lambda _project_id: TraceLock("lifecycle"),
    )

    store.create(_project("project-1"))
    assert events[:2] == ["enter:lifecycle", "enter:store"]

    events.clear()
    store.delete("project-1")
    assert events[:2] == ["enter:lifecycle", "enter:store"]


def test_create_rejects_an_existing_empty_project_directory(tmp_path):
    store = ProjectStore(tmp_path.resolve())
    store.project_root("project-1").mkdir()

    with pytest.raises(ProjectAlreadyExists):
        store.create(_project("project-1"))

    assert store.project_root("project-1").is_dir()
    assert not store.project_path("project-1").exists()


def test_create_failure_never_exposes_a_partial_project(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path.resolve())
    original = store._atomic_write

    def fail_after_staging(project_root, payload):
        original(project_root, payload)
        raise OSError("injected staging failure")

    monkeypatch.setattr(store, "_atomic_write", fail_after_staging)
    with pytest.raises(OSError, match="injected staging failure"):
        store.create(_project("project-1"))

    assert not store.project_root("project-1").exists()
    assert list((tmp_path / ".staging").iterdir()) == []


def test_replace_and_delete_enforce_etag_and_generation(tmp_path):
    store = ProjectStore(tmp_path.resolve())
    current = store.create(_project("project-1"))
    next_project = _next(current.project)

    with pytest.raises(ProjectConflict, match="ETag"):
        store.replace(
            "project-1",
            next_project,
            expected_etag="sha256:" + "0" * 64,
        )
    with pytest.raises(ProjectConflict, match="generation"):
        store.replace(
            "project-1",
            current.project.model_copy(update={"name": "bad"}),
            expected_etag=current.etag,
        )
    with pytest.raises(ProjectConflict, match="ETag"):
        store.delete("project-1", expected_etag="sha256:" + "0" * 64)

    assert store.read("project-1") == current


@pytest.mark.parametrize(
    "project_id",
    [
        "../escape",
        "nested/project",
        r"nested\\project",
        ".",
        "..",
        "has:colon",
        " bad",
    ],
)
def test_project_ids_cannot_escape_the_fixed_root(tmp_path, project_id):
    store = ProjectStore(tmp_path.resolve())

    with pytest.raises(UnsafeProjectPath):
        store.project_path(project_id)


def test_root_must_be_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(UnsafeProjectPath, match="absolute"):
        ProjectStore("relative-root")


def test_read_rejects_project_directory_and_file_symlinks(tmp_path):
    store = ProjectStore((tmp_path / "store").resolve())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "project.json").write_text("{}", encoding="utf-8")
    os.symlink(outside, store.root / "project-link")

    with pytest.raises(UnsafeProjectPath):
        store.read("project-link")

    store.create(_project("project-real"))
    target = store.project_path("project-real")
    target.unlink()
    os.symlink(outside / "project.json", target)
    with pytest.raises(ProjectIntegrityError, match="non-symlink"):
        store.read("project-real")


def test_read_rejects_indexed_asset_symlink_escape(tmp_path):
    store = ProjectStore((tmp_path / "store").resolve())
    project = store.create(_project("project-1")).project
    project_root = store.project_root("project-1")
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, project_root / "assets" / "escape")

    raw = project.model_dump(mode="json")
    raw["generation"] = 1
    raw["updated_at"] = "2026-07-15T08:00:01Z"
    raw["assets"]["files_by_id"] = {
        "file-1": {
            "file_id": "file-1",
            "kind": "other",
            "relative_uri": "assets/escape/payload.bin",
            "sha256": "a" * 64,
            "size_bytes": 1,
            "media_type": "application/octet-stream",
            "created_at": "2026-07-15T08:00:00Z",
        },
    }
    candidate = Project.model_validate(raw)

    with pytest.raises(UnsafeProjectPath, match="escapes"):
        store.replace(
            "project-1",
            candidate,
            expected_etag=store.read("project-1").etag,
        )


def test_atomic_replace_failure_preserves_old_project_and_cleans_temp(
    tmp_path,
    monkeypatch,
):
    store = ProjectStore(tmp_path.resolve())
    current = store.create(_project("project-1", "Before"))
    replacement = _next(current.project, name="After")
    real_replace = store_module.os.replace

    def fail_project_publish(source, destination):
        if str(destination).endswith("project.json"):
            raise OSError("simulated publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(store_module.os, "replace", fail_project_publish)
    with pytest.raises(OSError, match="simulated"):
        store.replace("project-1", replacement, expected_etag=current.etag)

    assert store.read("project-1") == current
    assert (
        list((store.project_root("project-1") / "runtime" / "temp").iterdir())
        == []
    )


def test_store_fsyncs_file_and_directories_during_publish(
    tmp_path,
    monkeypatch,
):
    calls: list[int] = []
    real_fsync = store_module.os.fsync

    def record(descriptor: int):
        calls.append(descriptor)
        return real_fsync(descriptor)

    monkeypatch.setattr(store_module.os, "fsync", record)
    store = ProjectStore(tmp_path.resolve())
    store.create(_project("project-1"))

    # temp file + Project dir + runtime/temp dir + store root
    assert len(calls) >= 4


def test_oversized_project_is_rejected_before_publication(tmp_path):
    store = ProjectStore(tmp_path.resolve(), max_project_json_bytes=256)

    with pytest.raises(ProjectIntegrityError, match="move large content"):
        store.create(_project("project-big", "x" * 512))
    assert not store.project_root("project-big").exists()


def test_corrupt_or_duplicate_key_project_is_not_silently_listed(tmp_path):
    store = ProjectStore(tmp_path.resolve())
    store.create(_project("project-1"))
    path = store.project_path("project-1")
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        '{"schema_version":1,"schema_version":1,"project_id":"project-1"}',
        encoding="utf-8",
    )

    with pytest.raises(ProjectIntegrityError):
        store.read("project-1")
    assert store.list() == []
    assert store.discover_project_ids() == ("project-1",)

    # Keep the variable used to make this test's intentional corruption clear.
    assert payload["project_id"] == "project-1"


def test_discovery_ignores_internal_incomplete_and_symlink_directories(
    tmp_path,
):
    store = ProjectStore((tmp_path / "store").resolve())
    store.create(_project("project-b"))
    store.create(_project("project-a"))
    (store.root / "incomplete").mkdir()
    (store.root / ".staging" / "partial").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "project.json").write_text("{}", encoding="utf-8")
    os.symlink(outside, store.root / "project-link")

    assert store.discover_project_ids() == ("project-a", "project-b")


def test_discovery_reports_project_directory_with_invalid_project_file(
    tmp_path,
):
    store = ProjectStore((tmp_path / "store").resolve())
    project_root = store.project_root("project-bad")
    project_root.mkdir()
    (project_root / "project.json").mkdir()

    assert store.discover_project_ids() == ("project-bad",)
