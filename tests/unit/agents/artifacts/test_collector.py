# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from qwenpaw.agents.artifacts import (
    ArtifactCollector,
    ArtifactCollectorGroup,
    ArtifactLimits,
    WorkspaceSnapshot,
    SnapshotLimits,
    capture_workspace_snapshot,
)


def test_collector_merges_explicit_and_snapshot_artifacts(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing.md"
    existing.write_text("before", encoding="utf-8")
    before = capture_workspace_snapshot(tmp_path)
    collector = ArtifactCollector(tmp_path, before)

    existing.write_text("after", encoding="utf-8")
    generated = tmp_path / "report.csv"
    generated.write_text("name,value\nA,1", encoding="utf-8")
    collector.register(generated)

    result = collector.collect(capture_workspace_snapshot(tmp_path))

    assert [artifact.path for artifact in result.artifacts] == [
        "existing.md",
        "report.csv",
    ]
    assert result.artifacts[1].mime_type == "text/csv"
    assert result.artifacts[1].preview == "csv"
    assert [change.change for change in result.changes] == [
        "modified",
        "created",
    ]


def test_collector_keeps_explicit_unchanged_file(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "sent.pdf"
    file_path.write_bytes(b"pdf")
    before = capture_workspace_snapshot(tmp_path)
    collector = ArtifactCollector(tmp_path, before)
    collector.register(file_path)

    result = collector.collect(capture_workspace_snapshot(tmp_path))

    assert len(result.artifacts) == 1
    assert result.artifacts[0].path == "sent.pdf"
    assert result.artifacts[0].change == "modified"
    assert result.artifacts[0].preview == "pdf"


def test_collector_rejects_paths_outside_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    collector = ArtifactCollector(
        workspace,
        capture_workspace_snapshot(workspace),
    )

    assert collector.register(outside) is False
    assert collector.register("../outside.txt") is False


def test_collector_rejects_original_file_symlink(tmp_path: Path) -> None:
    """Reject a symlink before resolving it to a regular file."""
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    collector = ArtifactCollector(
        tmp_path,
        capture_workspace_snapshot(tmp_path),
    )

    assert collector.register(link) is False


def test_collector_rejects_symlinked_parent(tmp_path: Path) -> None:
    """Reject files reached through a symlinked directory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_text("target", encoding="utf-8")
    linked_dir = tmp_path / "linked"
    try:
        linked_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    collector = ArtifactCollector(
        tmp_path,
        capture_workspace_snapshot(tmp_path),
    )

    assert collector.register(linked_dir / "target.txt") is False


def test_collector_rejects_internal_state_but_keeps_user_jsonl(
    tmp_path: Path,
) -> None:
    before = capture_workspace_snapshot(tmp_path)
    collector = ArtifactCollector(tmp_path, before)
    internal = tmp_path / "skill.json"
    internal.write_text("{}", encoding="utf-8")
    session = tmp_path / "80bb94519e1a4ccc87337a8fc3ff91bb.jsonl"
    session.write_text("", encoding="utf-8")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    git_config = git_dir / "config"
    git_config.write_text("state", encoding="utf-8")
    user_jsonl = tmp_path / "events.jsonl"
    user_jsonl.write_text("{}\n", encoding="utf-8")

    assert collector.register(internal) is False
    assert collector.register(session) is False
    assert collector.register(git_config) is False
    assert collector.register(user_jsonl) is True

    result = collector.collect(capture_workspace_snapshot(tmp_path))

    assert [artifact.path for artifact in result.artifacts] == [
        "events.jsonl",
    ]


def test_collector_applies_artifact_limit(tmp_path: Path) -> None:
    before = capture_workspace_snapshot(tmp_path)
    for index in range(3):
        (tmp_path / f"result-{index}.txt").write_text(
            "result",
            encoding="utf-8",
        )
    collector = ArtifactCollector(
        tmp_path,
        before,
        limits=ArtifactLimits(max_artifacts=2),
    )

    result = collector.collect(capture_workspace_snapshot(tmp_path))

    assert len(result.artifacts) == 2
    assert result.truncated is True


def test_collector_preserves_initial_snapshot_truncation(
    tmp_path: Path,
) -> None:
    before = WorkspaceSnapshot.create({}, truncated=True)
    collector = ArtifactCollector(tmp_path, before)

    result = collector.collect(capture_workspace_snapshot(tmp_path))

    assert result.truncated is True


def test_collector_keeps_registered_file_outside_snapshot_window(
    tmp_path: Path,
) -> None:
    before = capture_workspace_snapshot(tmp_path)
    collector = ArtifactCollector(tmp_path, before)
    first = tmp_path / "a.txt"
    registered = tmp_path / "z.txt"
    first.write_text("first", encoding="utf-8")
    registered.write_text("registered", encoding="utf-8")
    assert collector.register(registered) is True

    after = capture_workspace_snapshot(
        tmp_path,
        limits=SnapshotLimits(max_files=1),
    )
    result = collector.collect(after)

    assert [(item.path, item.change) for item in result.artifacts] == [
        ("a.txt", "created"),
        ("z.txt", "modified"),
    ]
    assert result.truncated is True


def test_collector_labels_project_images(tmp_path: Path) -> None:
    before = capture_workspace_snapshot(tmp_path)
    (tmp_path / "diagram.svg").write_text(
        "<svg></svg>",
        encoding="utf-8",
    )
    (tmp_path / "favicon.ico").write_bytes(b"icon")
    collector = ArtifactCollector(tmp_path, before, root="project")

    result = collector.collect(capture_workspace_snapshot(tmp_path))

    assert [artifact.root for artifact in result.artifacts] == [
        "project",
        "project",
    ]
    assert [artifact.preview for artifact in result.artifacts] == [
        "image",
        "image",
    ]
    assert [artifact.mime_type for artifact in result.artifacts] == [
        "image/svg+xml",
        "image/x-icon",
    ]


def test_collector_group_merges_disjoint_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    project = tmp_path / "project"
    workspace.mkdir()
    project.mkdir()
    roots = {"workspace": workspace, "project": project}
    before = {
        root: capture_workspace_snapshot(path) for root, path in roots.items()
    }
    collector = ArtifactCollectorGroup(roots, before)
    (workspace / "workspace.txt").write_text(
        "workspace",
        encoding="utf-8",
    )
    (project / "project.txt").write_text(
        "project",
        encoding="utf-8",
    )

    result = collector.collect(
        {
            root: capture_workspace_snapshot(path)
            for root, path in roots.items()
        },
    )

    assert [(item.root, item.path) for item in result.artifacts] == [
        ("project", "project.txt"),
        ("workspace", "workspace.txt"),
    ]


def test_collector_group_applies_one_global_limit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    project = tmp_path / "project"
    workspace.mkdir()
    project.mkdir()
    roots = {"workspace": workspace, "project": project}
    before = {
        root: capture_workspace_snapshot(path) for root, path in roots.items()
    }
    collector = ArtifactCollectorGroup(
        roots,
        before,
        limits=ArtifactLimits(max_artifacts=1),
    )
    (workspace / "workspace.txt").write_text(
        "workspace",
        encoding="utf-8",
    )
    (project / "project.txt").write_text(
        "project",
        encoding="utf-8",
    )

    result = collector.collect(
        {
            root: capture_workspace_snapshot(path)
            for root, path in roots.items()
        },
    )

    assert len(result.artifacts) == 1
    assert result.truncated is True
