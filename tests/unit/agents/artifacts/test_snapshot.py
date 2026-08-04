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
