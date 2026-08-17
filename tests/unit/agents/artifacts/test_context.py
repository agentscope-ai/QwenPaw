# -*- coding: utf-8 -*-
from pathlib import Path

from qwenpaw.agents.artifacts import (
    ArtifactCollector,
    capture_workspace_snapshot,
    register_current_artifact,
    reset_current_artifact_collector,
    set_current_artifact_collector,
)


def test_register_current_artifact_uses_active_collector(
    tmp_path: Path,
) -> None:
    collector = ArtifactCollector(
        tmp_path,
        capture_workspace_snapshot(tmp_path),
    )
    file_path = tmp_path / "report.txt"
    file_path.write_text("ready", encoding="utf-8")
    token = set_current_artifact_collector(collector)

    assert register_current_artifact(file_path) is True
    result = collector.collect(capture_workspace_snapshot(tmp_path))
    assert result.artifacts[0].path == "report.txt"

    reset_current_artifact_collector(token)
    assert register_current_artifact(file_path) is False
