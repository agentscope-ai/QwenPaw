from pathlib import Path

from qwenpaw.agents.artifacts import (
    ArtifactCollector,
    ArtifactLimits,
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
