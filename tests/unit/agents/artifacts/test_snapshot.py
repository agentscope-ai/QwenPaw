# -*- coding: utf-8 -*-
from pathlib import Path

from qwenpaw.agents.artifacts import (
    SnapshotLimits,
    capture_workspace_snapshot,
    diff_workspace_snapshots,
)


def test_snapshot_tracks_regular_files_with_posix_paths(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "reports"
    nested.mkdir()
    report = nested / "summary.md"
    report.write_text("ready", encoding="utf-8")

    snapshot = capture_workspace_snapshot(tmp_path)

    assert tuple(snapshot.files) == ("reports/summary.md",)
    assert snapshot.files["reports/summary.md"].size == 5
    assert snapshot.truncated is False


def test_snapshot_excludes_runtime_and_temporary_files(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "index").write_text("state", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text(
        "code",
        encoding="utf-8",
    )
    (tmp_path / "history.db").write_text("state", encoding="utf-8")
    (tmp_path / "draft.md.swp").write_text("temp", encoding="utf-8")
    (tmp_path / "deliverable.md").write_text("keep", encoding="utf-8")

    snapshot = capture_workspace_snapshot(tmp_path)

    assert tuple(snapshot.files) == ("deliverable.md",)


def test_snapshot_excludes_qwenpaw_root_state_without_hiding_user_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "chats.json").write_text("{}", encoding="utf-8")
    (tmp_path / "skill.json").write_text("{}", encoding="utf-8")
    session_name = "80bb94519e1a4ccc87337a8fc3ff91bb.jsonl"
    (tmp_path / session_name).write_text("", encoding="utf-8")
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "chats.json").write_text("{}", encoding="utf-8")
    (tmp_path / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "test.xlsx").write_bytes(b"xlsx")
    (tmp_path / "work.md").write_text("report", encoding="utf-8")

    snapshot = capture_workspace_snapshot(tmp_path)

    assert tuple(snapshot.files) == (
        "events.jsonl",
        "exports/chats.json",
        "test.xlsx",
        "work.md",
    )


def test_snapshot_skips_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        return

    snapshot = capture_workspace_snapshot(tmp_path)

    assert "target.txt" in snapshot.files
    assert "link.txt" not in snapshot.files


def test_snapshot_stops_at_file_limit(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"file-{index}.txt").write_text(
            str(index),
            encoding="utf-8",
        )

    snapshot = capture_workspace_snapshot(
        tmp_path,
        limits=SnapshotLimits(max_files=2),
    )

    assert len(snapshot.files) == 2
    assert snapshot.truncated is True


def test_snapshot_file_limit_stops_nested_directory_traversal(
    tmp_path: Path,
) -> None:
    directory = tmp_path
    for index in range(25):
        directory = directory / f"level-{index}"
        directory.mkdir()
        (directory / f"file-{index}.txt").write_text(
            str(index),
            encoding="utf-8",
        )

    snapshot = capture_workspace_snapshot(
        tmp_path,
        limits=SnapshotLimits(max_files=3),
    )

    assert len(snapshot.files) == 3
    assert snapshot.truncated is True


def test_diff_reports_created_modified_and_deleted(
    tmp_path: Path,
) -> None:
    modified = tmp_path / "modified.txt"
    deleted = tmp_path / "deleted.txt"
    modified.write_text("before", encoding="utf-8")
    deleted.write_text("remove", encoding="utf-8")
    before = capture_workspace_snapshot(tmp_path)

    modified.write_text("after content", encoding="utf-8")
    deleted.unlink()
    (tmp_path / "created.txt").write_text("new", encoding="utf-8")
    after = capture_workspace_snapshot(tmp_path)

    changes = diff_workspace_snapshots(before, after)

    assert [(change.path, change.change) for change in changes] == [
        ("created.txt", "created"),
        ("deleted.txt", "deleted"),
        ("modified.txt", "modified"),
    ]
