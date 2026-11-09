# -*- coding: utf-8 -*-
"""Scratch is released when its content stops being needed, not later."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import types

import pytest

from domain.enums import TaskKind, TaskStatus
from services.media_files import task_scratch
from services.media_files.task_scratch import (
    ORPHAN_RELEASE_GRACE,
    link_asset_into_scratch,
    project_storage_profile,
    read_scratch_baseline,
    release_finished_task_scratch,
    release_orphaned_scratch,
    release_scratch_file,
    release_scratch_media,
    remember_scratch_baseline,
    stamp_scratch_baseline,
    task_scratch_dir,
    terminal_release_listener,
)
from services.project_files.assets import AssetFileStore, AssetFileCorrupt
from services.project_files.models import IndexedFile
from services.runtime_files.execution_models import TaskRecord
from services.runtime_files.execution_store import ProjectExecutionStore

PROJECT_ID = "project-scratch"
T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def _moved(
    store: ProjectExecutionStore,
    task_id: str,
    *,
    frm,
    to,
    updated_at: datetime,
) -> TaskRecord:
    return store.transition_task(
        PROJECT_ID,
        task_id,
        expected_status=frm,
        status=to,
        updated_at=updated_at,
    )


def _services(root: Path) -> types.SimpleNamespace:
    """The two ProjectStore calls the release path actually makes."""

    return types.SimpleNamespace(
        root=root,
        projects=types.SimpleNamespace(
            project_root=lambda project_id: root / project_id,
            discover_project_ids=lambda: tuple(
                sorted(
                    item.name
                    for item in root.iterdir()
                    if (item / "project.json").is_file()
                ),
            ),
        ),
    )


# Where a platform cannot open a directory handle that refuses to follow a
# redirect, the release refuses to delete anything at all -- so the assertions
# below about files disappearing do not hold there.
_needs_pinned_release = pytest.mark.skipif(
    not task_scratch.pinned_release_supported(),
    reason="scratch release needs directory handles that refuse redirects",
)


def _scratch(
    root: Path,
    task_id: str = "task-1",
    *,
    media: tuple[str, ...] = ("output.mp4", "inputs/000000-artifact.mp4"),
) -> Path:
    project = root / PROJECT_ID
    project.mkdir(parents=True, exist_ok=True)
    (project / "project.json").write_text("{}", encoding="utf-8")
    scratch = task_scratch_dir(project, task_id)
    for name in media:
        target = scratch / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 64)
    (scratch / "spec.json").write_text("{}", encoding="utf-8")
    (scratch / "provider-tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (scratch / "notes.txt").write_text("note", encoding="utf-8")
    return scratch


def _survivors(scratch: Path) -> set[str]:
    return {
        item.relative_to(scratch).as_posix()
        for item in scratch.rglob("*")
        if item.is_file()
    }


@_needs_pinned_release
def test_release_drops_media_and_keeps_documents(tmp_path: Path) -> None:
    scratch = _scratch(tmp_path)

    result = release_scratch_media(scratch, reason="test")

    assert result.removed_files == 2
    assert result.removed_bytes == 128
    assert _survivors(scratch) == {
        "spec.json",
        "provider-tasks.jsonl",
        "notes.txt",
    }


def _empty() -> task_scratch.ScratchReleaseResult:
    return task_scratch.ScratchReleaseResult()


@_needs_pinned_release
def test_release_is_idempotent(tmp_path: Path) -> None:
    scratch = _scratch(tmp_path)
    release_scratch_media(scratch, reason="first")

    assert release_scratch_media(scratch, reason="second") == _empty()


def test_release_refuses_links_and_missing_directories(
    tmp_path: Path,
    file_symlink,
    directory_link,
) -> None:
    scratch = _scratch(tmp_path, media=("output.mp4",))
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"x" * 64)
    file_symlink(outside, scratch / "linked.mp4")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "inside.mp4").write_bytes(b"x" * 64)
    directory_link(foreign, scratch / "nested")

    release_scratch_media(scratch, reason="test")

    assert outside.is_file()
    assert (foreign / "inside.mp4").is_file()
    assert release_scratch_media(scratch / "nope", reason="test") == _empty()


@_needs_pinned_release
def test_release_swallows_unlink_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = _scratch(tmp_path)

    def explode(_path, **_kwargs) -> None:
        raise OSError("device busy")

    monkeypatch.setattr(os, "unlink", explode)

    result = release_scratch_media(scratch, reason="test")

    assert result.removed_files == 0
    assert result.skipped_files == 2
    assert (scratch / "output.mp4").is_file()


def _task(status: TaskStatus, *, updated_at: datetime = T0) -> TaskRecord:
    return TaskRecord(
        task_id="task-1",
        project_id=PROJECT_ID,
        kind=TaskKind.R2V_GENERATION,
        request_fingerprint="fp",
        status=status,
        created_at=T0 - timedelta(days=7),
        updated_at=updated_at,
    )


@pytest.mark.parametrize(
    "status, expected_files",
    [
        (TaskStatus.QUEUED, 2),
        (TaskStatus.RUNNING, 2),
        (TaskStatus.QUARANTINED, 2),
        (TaskStatus.SUCCEEDED, 0),
        (TaskStatus.FAILED, 0),
        (TaskStatus.CANCELLED, 0),
    ],
)
@_needs_pinned_release
def test_only_a_finished_task_frees_its_scratch(
    tmp_path: Path,
    status: TaskStatus,
    expected_files: int,
) -> None:
    scratch = _scratch(tmp_path)

    release_finished_task_scratch(_services(tmp_path), _task(status))

    assert len(_media(scratch)) == expected_files


def _media(scratch: Path) -> list[Path]:
    return [
        item
        for item in scratch.rglob("*")
        if item.is_file() and item.suffix in task_scratch.MEDIA_SUFFIXES
    ]


@_needs_pinned_release
def test_terminal_transition_releases_scratch_without_an_extra_call(
    tmp_path: Path,
) -> None:
    scratch = _scratch(tmp_path)
    store = ProjectExecutionStore(tmp_path)
    store.create_task(_task(TaskStatus.QUEUED))
    wired = ProjectExecutionStore(
        tmp_path,
        on_task_terminal=terminal_release_listener(_services(tmp_path)),
    )

    _moved(
        wired,
        "task-1",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.RUNNING,
        updated_at=T0,
    )
    assert len(_media(scratch)) == 2

    _moved(
        wired,
        "task-1",
        frm=TaskStatus.RUNNING,
        to=TaskStatus.SUCCEEDED,
        updated_at=T0 + timedelta(minutes=1),
    )
    assert _media(scratch) == []
    assert (scratch / "spec.json").is_file()
    assert (scratch / "provider-tasks.jsonl").is_file()


@_needs_pinned_release
def test_a_failing_listener_cannot_rollback_task_state(
    tmp_path: Path,
) -> None:
    _scratch(tmp_path)
    store = ProjectExecutionStore(tmp_path)
    store.create_task(_task(TaskStatus.QUEUED))

    def explode(_task: TaskRecord) -> None:
        raise RuntimeError("release blew up")

    wired = ProjectExecutionStore(tmp_path, on_task_terminal=explode)
    _moved(
        wired,
        "task-1",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.RUNNING,
        updated_at=T0,
    )

    moved = _moved(
        wired,
        "task-1",
        frm=TaskStatus.RUNNING,
        to=TaskStatus.SUCCEEDED,
        updated_at=T0 + timedelta(minutes=1),
    )

    assert moved.status is TaskStatus.SUCCEEDED


@_needs_pinned_release
def test_sweep_ignores_everything_from_before_the_baseline(
    tmp_path: Path,
) -> None:
    scratch = _scratch(tmp_path)
    store = ProjectExecutionStore(tmp_path)
    store.create_task(_task(TaskStatus.QUEUED))
    _moved(
        store,
        "task-1",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.RUNNING,
        updated_at=T0 - timedelta(days=2),
    )
    _moved(
        store,
        "task-1",
        frm=TaskStatus.RUNNING,
        to=TaskStatus.SUCCEEDED,
        updated_at=T0 - timedelta(days=1),
    )

    swept = release_orphaned_scratch(_services(tmp_path), now=T0)

    assert swept.removed_files == 0
    assert read_scratch_baseline(tmp_path / PROJECT_ID) == T0
    assert len(_media(scratch)) == 2

    # A task that finished after the baseline is fair game once it is quiet.
    later = _scratch(tmp_path, "task-2")
    store.create_task(
        _task(TaskStatus.QUEUED).model_copy(update={"task_id": "task-2"}),
    )
    _moved(
        store,
        "task-2",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.FAILED,
        updated_at=T0 + timedelta(minutes=5),
    )

    summary = release_orphaned_scratch(
        _services(tmp_path),
        now=T0 + ORPHAN_RELEASE_GRACE + timedelta(minutes=10),
    )

    assert summary.removed_files == 2
    assert _media(later) == []
    assert len(_media(scratch)) == 2


@_needs_pinned_release
def test_sweep_holds_recent_and_orphan_directories(tmp_path: Path) -> None:
    recent = _scratch(tmp_path, "task-1")
    unknown = _scratch(tmp_path, "task-ghost")
    remember_scratch_baseline(tmp_path / PROJECT_ID, now=T0)
    store = ProjectExecutionStore(tmp_path)
    store.create_task(
        _task(TaskStatus.QUEUED).model_copy(update={"task_id": "task-1"}),
    )
    _moved(
        store,
        "task-1",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.CANCELLED,
        updated_at=T0 + timedelta(seconds=1),
    )

    summary = release_orphaned_scratch(
        _services(tmp_path),
        now=T0 + timedelta(minutes=1),
    )

    assert summary.released_directories == 0
    assert len(_media(recent)) == 2
    assert len(_media(unknown)) == 2


def test_baseline_is_written_once(tmp_path: Path) -> None:
    (tmp_path / PROJECT_ID / "runtime").mkdir(parents=True)
    project = tmp_path / PROJECT_ID

    assert remember_scratch_baseline(project, now=T0) == T0

    assert (
        remember_scratch_baseline(project, now=T0 + timedelta(days=30)) == T0
    )
    assert read_scratch_baseline(project) == T0


def test_emergency_switch_stops_releasing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = _scratch(tmp_path)
    monkeypatch.setenv("CREATOR_SCRATCH_RELEASE_ENABLED", "false")

    release_finished_task_scratch(
        _services(tmp_path),
        _task(TaskStatus.SUCCEEDED),
    )
    assert release_orphaned_scratch(_services(tmp_path), now=T0).projects == 0

    assert len(_media(scratch)) == 2


@_needs_pinned_release
def test_emergency_switch_also_stops_a_superseded_step_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The render pipeline drops the renamed predecessor itself, so the
    # switch has to cover this entry or it cannot stop every new deletion.
    scratch = _scratch(tmp_path, media=("premix.mp4",))
    premix = scratch / "premix.mp4"

    assert release_scratch_file(premix, reason="superseded-by-audio-mix")
    assert not premix.exists()

    monkeypatch.setenv("CREATOR_SCRATCH_RELEASE_ENABLED", "false")
    other = _scratch(tmp_path, "task-2", media=("preloud.mp4",))
    preloud = other / "preloud.mp4"

    released = release_scratch_file(preloud, reason="superseded-by-loudnorm")

    assert released is False
    assert preloud.is_file()


@_needs_pinned_release
def test_a_project_created_after_boot_is_still_swept(
    tmp_path: Path,
) -> None:
    # The sweep runs at startup only. Without the creation-time stamp the
    # next start would date this Project's baseline past its own abandoned
    # Task and file it as pre-upgrade history forever.
    scratch = _scratch(tmp_path)
    stamp_scratch_baseline(tmp_path / PROJECT_ID)
    moment = datetime.now(timezone.utc)
    store = ProjectExecutionStore(tmp_path)
    store.create_task(_task(TaskStatus.QUEUED))
    _moved(
        store,
        "task-1",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.FAILED,
        updated_at=moment + timedelta(seconds=5),
    )

    summary = release_orphaned_scratch(
        _services(tmp_path),
        now=moment + ORPHAN_RELEASE_GRACE + timedelta(minutes=5),
    )

    assert summary.removed_files == 2
    assert _media(scratch) == []


@_needs_pinned_release
def test_allocating_scratch_baselines_a_project_that_was_never_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Archive import and example install publish a Project without going
    # through ProjectStore.create, so allocation is the only choke point that
    # can promise a baseline earlier than the tasks this build writes.
    from utils.paths import media_task_scope, task_work_root

    project = tmp_path / PROJECT_ID
    (project / "runtime").mkdir(parents=True)
    (project / "project.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    now = datetime.now(timezone.utc)

    with media_task_scope("task-1", project_id=PROJECT_ID):
        scratch = task_work_root("task-1")

    assert read_scratch_baseline(project) is not None
    (scratch / "output.mp4").write_bytes(b"x" * 64)
    store = ProjectExecutionStore(tmp_path)
    store.create_task(_task(TaskStatus.QUEUED))
    _moved(
        store,
        "task-1",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.FAILED,
        updated_at=now + timedelta(seconds=5),
    )

    summary = release_orphaned_scratch(
        _services(tmp_path),
        now=now + ORPHAN_RELEASE_GRACE + timedelta(minutes=5),
    )

    assert summary.removed_files == 1


def test_scratch_brought_in_by_an_import_stays_protected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The stamp lands at first allocation, later than any archived Task, so
    # the "pre-upgrade bytes stay put" rule holds for a Project that arrived
    # through an archive rather than through creation.
    from utils.paths import media_task_scope, task_work_root

    legacy = _scratch(tmp_path, "task-legacy")
    now = datetime.now(timezone.utc)
    store = ProjectExecutionStore(tmp_path)
    store.create_task(
        _task(TaskStatus.QUEUED).model_copy(update={"task_id": "task-legacy"}),
    )
    _moved(
        store,
        "task-legacy",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.FAILED,
        updated_at=now - timedelta(hours=1),
    )
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))

    with media_task_scope("task-1", project_id=PROJECT_ID):
        task_work_root("task-1")

    summary = release_orphaned_scratch(
        _services(tmp_path),
        now=now + ORPHAN_RELEASE_GRACE + timedelta(minutes=5),
    )

    assert summary.removed_files == 0
    assert len(_media(legacy)) == 2


def _replace_with_a_link(scratch: Path, outside: Path) -> Path:
    """Move the real ``task-work`` aside and point that name outside it.

    The directory behind the link carries the same media filenames as the real
    scratch, so a delete that re-resolved the path after the swap would cut
    those copies instead of the pinned tree.  Returns the linked task dir.
    """

    original = scratch.parent.with_name("task-work-original")
    scratch.parent.rename(original)
    landed = outside / scratch.name
    landed.mkdir(parents=True)
    for item in (original / scratch.name).iterdir():
        if item.suffix == ".mp4":
            (landed / item.name).write_bytes(b"external-original")
    scratch.parent.symlink_to(outside, target_is_directory=True)
    return landed


def _swap_task_work_after_listing(
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,
    outside: Path,
) -> None:
    """Swap the ancestor once the release has listed the pinned directory.

    That is the gap a path-based delete falls through: the handle is open and
    every filename is known, only the unlink is left.
    """

    # The gap is only reachable by wrapping the release's own internals.
    # pylint: disable=protected-access
    release_tree = task_scratch._release_pinned_tree

    def listed_then_swapped(dir_fd: int):
        list(os.scandir(dir_fd))
        _replace_with_a_link(scratch, outside)
        return release_tree(dir_fd)

    monkeypatch.setattr(
        task_scratch,
        "_release_pinned_tree",
        listed_then_swapped,
    )


def _swap_task_work_after_the_check(
    monkeypatch: pytest.MonkeyPatch,
    outside: Path,
) -> None:
    """Swap the ancestor right after the single-file entry pins its handle."""

    # The entry point hands its own directory to the wrapper, so the pinned
    # handle is what gets swapped, not the ``scratch`` argument.
    # pylint: disable=protected-access
    open_scratch = task_scratch._open_pinned_scratch

    def opened_then_swapped(scratch_dir: Path):
        dir_fd = open_scratch(scratch_dir)
        list(os.scandir(dir_fd))
        _replace_with_a_link(Path(scratch_dir), outside)
        return dir_fd

    monkeypatch.setattr(
        task_scratch,
        "_open_pinned_scratch",
        opened_then_swapped,
    )


def _landed_task_dir(scratch: Path) -> Path:
    """Where the task directory really is after ``task-work`` was renamed."""

    return scratch.parent.with_name("task-work-original") / scratch.name


def test_file_native_allocation_baselines_the_project(tmp_path: Path) -> None:
    # The render pipeline allocates scratch on its own path, not through
    # utils.paths, so its allocator has to carry the same guarantee.
    from services.media_files.local_execution import _ensure_task_work_dir

    project = tmp_path / PROJECT_ID
    (project / "runtime").mkdir(parents=True)

    work_dir = _ensure_task_work_dir(project, "task-1")

    assert work_dir.is_dir()
    assert read_scratch_baseline(project) is not None


def _escaped_scratch(root: Path) -> tuple[Path, Path]:
    """Build the escape layout: a real Project, a redirected scratch tree.

    ``runtime/task-work`` is a directory link out of the data root, so the task
    directory below it still stats as an ordinary real directory -- exactly the
    case a leaf-only check used to accept.
    """

    project = root / PROJECT_ID
    (project / "runtime").mkdir(parents=True)
    (project / "project.json").write_text("{}", encoding="utf-8")
    outside = root / "outside-data-root"
    valuable = outside / "task-1" / "valuable.mp4"
    valuable.parent.mkdir(parents=True)
    valuable.write_bytes(b"external-original")
    (project / "runtime" / "task-work").symlink_to(
        outside,
        target_is_directory=True,
    )
    return project, valuable


def test_the_terminal_release_never_deletes_through_a_redirected_tree(
    tmp_path: Path,
) -> None:
    _project, valuable = _escaped_scratch(tmp_path)

    summary = release_finished_task_scratch(
        _services(tmp_path),
        _task(TaskStatus.SUCCEEDED),
    )

    assert summary.removed_files == 0
    assert valuable.read_bytes() == b"external-original"


def test_the_startup_sweep_never_deletes_through_a_redirected_tree(
    tmp_path: Path,
) -> None:
    project, valuable = _escaped_scratch(tmp_path)
    store = ProjectExecutionStore(tmp_path)
    store.create_task(_task(TaskStatus.QUEUED))
    moment = datetime.now(timezone.utc)
    # Baseline before the Task finishes, so the only thing that can stop this
    # delete is the layout check -- not the pre-upgrade-history rule.
    remember_scratch_baseline(project, now=moment)
    _moved(
        store,
        "task-1",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.FAILED,
        updated_at=moment + timedelta(seconds=5),
    )

    summary = release_orphaned_scratch(
        _services(tmp_path),
        now=moment + ORPHAN_RELEASE_GRACE + timedelta(minutes=5),
    )

    assert summary.removed_files == 0
    assert valuable.read_bytes() == b"external-original"


@_needs_pinned_release
def test_a_parent_swapped_during_the_terminal_release_stays_inside_the_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = _scratch(tmp_path, media=("output.mp4",))
    outside = tmp_path / "outside-data-root"
    _swap_task_work_after_listing(monkeypatch, scratch, outside)

    result = release_finished_task_scratch(
        _services(tmp_path),
        _task(TaskStatus.SUCCEEDED),
    )

    # The delete lands on the pinned directory, not on the swapped-in link.
    assert result.removed_files == 1
    assert not (_landed_task_dir(scratch) / "output.mp4").exists()
    assert (outside / "task-1" / "output.mp4").read_bytes() == (
        b"external-original"
    )


@_needs_pinned_release
def test_a_parent_swapped_during_the_sweep_stays_inside_the_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = _scratch(tmp_path, media=("output.mp4",))
    outside = tmp_path / "outside-data-root"
    store = ProjectExecutionStore(tmp_path)
    moment = datetime.now(timezone.utc)
    remember_scratch_baseline(tmp_path / PROJECT_ID, now=moment)
    store.create_task(_task(TaskStatus.QUEUED))
    _moved(
        store,
        "task-1",
        frm=TaskStatus.QUEUED,
        to=TaskStatus.FAILED,
        updated_at=moment + timedelta(seconds=5),
    )
    _swap_task_work_after_listing(monkeypatch, scratch, outside)

    summary = release_orphaned_scratch(
        _services(tmp_path),
        now=moment + ORPHAN_RELEASE_GRACE + timedelta(minutes=5),
    )

    assert summary.removed_files == 1
    assert not (_landed_task_dir(scratch) / "output.mp4").exists()
    assert (outside / "task-1" / "output.mp4").read_bytes() == (
        b"external-original"
    )


@_needs_pinned_release
def test_a_parent_swapped_before_a_superseded_delete_stays_inside_the_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = _scratch(tmp_path, media=("premix.mp4",))
    outside = tmp_path / "outside-data-root"
    _swap_task_work_after_the_check(monkeypatch, outside)

    assert release_scratch_file(
        scratch / "premix.mp4",
        reason="superseded-by-audio-mix",
    )

    assert not (_landed_task_dir(scratch) / "premix.mp4").exists()
    assert (outside / "task-1" / "premix.mp4").read_bytes() == (
        b"external-original"
    )


def _asset(
    tmp_path: Path,
    content: bytes,
) -> tuple[AssetFileStore, IndexedFile, Path]:
    project = tmp_path / PROJECT_ID
    project.mkdir(exist_ok=True)
    store = AssetFileStore(project, chunk_size=3)
    published = store.publish(
        store.stage_bytes(content),
        "assets/sources/source-1/version-1/original.bin",
    )
    indexed = IndexedFile(
        file_id="file-1",
        kind="other",
        relative_uri=published.relative_uri,
        sha256=published.sha256,
        size_bytes=published.size_bytes,
        media_type="application/octet-stream",
        created_at=T0,
    )
    return store, indexed, project / published.relative_uri


@pytest.mark.parametrize("disable_pinned_release", [False, True])
def test_an_input_links_the_asset_instead_of_doubling_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disable_pinned_release: bool,
) -> None:
    if disable_pinned_release:
        monkeypatch.setattr(
            task_scratch,
            "pinned_release_supported",
            lambda: False,
        )
    store, indexed, final = _asset(tmp_path, b"artifact-payload" * 8)
    scratch = _scratch(tmp_path, media=("output.mp4",))
    destination = scratch / "inputs" / "000000-artifact.mp4"
    destination.parent.mkdir(parents=True)

    assert link_asset_into_scratch(store, indexed, destination)

    assert destination.stat().st_ino == final.stat().st_ino
    assert final.stat().st_nlink == 2

    result = release_scratch_media(scratch, reason="terminal")

    if task_scratch.pinned_release_supported():
        assert result.removed_files == 2
        assert not destination.exists()
        assert not (scratch / "output.mp4").exists()
        assert final.stat().st_nlink == 1
    else:
        assert result == _empty()
        assert destination.read_bytes() == b"artifact-payload" * 8
        assert (scratch / "output.mp4").read_bytes() == b"x" * 64
        assert final.stat().st_nlink == 2
    assert final.read_bytes() == b"artifact-payload" * 8


def test_linking_refuses_an_asset_that_changed(tmp_path: Path) -> None:
    store, indexed, final = _asset(tmp_path, b"original-payload")
    final.write_bytes(b"different-bytes")

    with pytest.raises(AssetFileCorrupt):
        link_asset_into_scratch(store, indexed, tmp_path / "input.mp4")

    assert not (tmp_path / "input.mp4").exists()


def test_linking_reports_a_filesystem_that_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, indexed, final = _asset(tmp_path, b"artifact-payload")

    def refuse(*_args, **_kwargs):
        raise OSError("cross-device link")

    monkeypatch.setattr(task_scratch.os, "link", refuse)

    assert not link_asset_into_scratch(store, indexed, tmp_path / "input.mp4")

    assert not (tmp_path / "input.mp4").exists()
    assert final.is_file()


def _tree_bytes(path: Path) -> int:
    return sum(
        item.stat().st_size for item in path.rglob("*") if item.is_file()
    )


def _media_bytes(path: Path) -> int:
    """Only what a release would delete: media files, kept names aside."""

    return sum(item.stat().st_size for item in _media(path))


def _stamp(path: Path, moment: datetime) -> None:
    """Age a directory and everything in it, the way a real clock would."""

    epoch = moment.timestamp()
    for item in (path, *path.rglob("*")):
        os.utime(item, (epoch, epoch))


def test_profile_splits_scratch_and_transactions_at_the_baseline(
    tmp_path: Path,
) -> None:
    legacy = _scratch(tmp_path, "task-legacy")
    transactions = tmp_path / PROJECT_ID / "runtime" / "transactions"
    old_tx = transactions / "tx-legacy"
    old_tx.mkdir(parents=True)
    (old_tx / "journal.json").write_text("{}", encoding="utf-8")
    _stamp(old_tx, T0 - timedelta(days=1))
    remember_scratch_baseline(tmp_path / PROJECT_ID, now=T0)

    fresh = _scratch(tmp_path, "task-fresh")
    new_tx = transactions / "tx-fresh"
    new_tx.mkdir(parents=True)
    (new_tx / "journal.json").write_bytes(b"{}\n")
    _stamp(new_tx, T0 + timedelta(hours=2))

    store = ProjectExecutionStore(tmp_path)
    for name, moment in (
        ("task-legacy", T0 - timedelta(days=1)),
        ("task-fresh", T0),
    ):
        store.create_task(
            _task(TaskStatus.QUEUED).model_copy(update={"task_id": name}),
        )
        _moved(
            store,
            name,
            frm=TaskStatus.QUEUED,
            to=TaskStatus.FAILED,
            updated_at=moment,
        )

    entry = project_storage_profile(
        _services(tmp_path),
        now=T0 + timedelta(hours=3),
    )["projects"][0]

    assert entry["baselineAt"] == T0.isoformat()
    assert entry["taskWorkLegacyBytes"] == _tree_bytes(legacy)
    assert entry["taskWorkBytes"] == _tree_bytes(fresh)
    # A finished Task whose scratch outlived the grace window is reclaimable,
    # counted as the media a release would take rather than the kept docs.
    assert entry["taskWorkReclaimableBytes"] == _media_bytes(fresh)
    assert entry["taskWorkReclaimableBytes"] < _tree_bytes(fresh)
    assert entry["transactionsLegacyBytes"] == _tree_bytes(old_tx)
    assert entry["transactionsBytes"] == _tree_bytes(new_tx)
    assert project_storage_profile(_services(tmp_path))["totals"][
        "taskWorkReclaimableBytes"
    ] == _media_bytes(fresh)
