# -*- coding: utf-8 -*-
"""Workspace artifact lifecycle hook behavior."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import qwenpaw.hooks.workspace_artifacts_hook as artifacts_hook_module
from qwenpaw.hooks.workspace_artifacts_hook import (
    WorkspaceArtifactsCleanupHook,
    WorkspaceArtifactsFinalizeHook,
    WorkspaceArtifactsHook,
)


async def test_workspace_scans_run_outside_event_loop(
    monkeypatch,
    tmp_path: Path,
) -> None:
    event_loop_thread = threading.get_ident()
    scan_threads: list[int] = []
    capture_snapshot = artifacts_hook_module.capture_workspace_snapshot

    def tracked_capture(workspace_dir):
        scan_threads.append(threading.get_ident())
        return capture_snapshot(workspace_dir)

    monkeypatch.setattr(
        artifacts_hook_module,
        "capture_workspace_snapshot",
        tracked_capture,
    )
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        extras={"turn_id": "turn-1"},
        agent_id="agent-1",
        session_id="chat-1",
    )

    await WorkspaceArtifactsHook().run(ctx)
    (tmp_path / "report.txt").write_text("ready", encoding="utf-8")
    await WorkspaceArtifactsFinalizeHook().run(ctx)
    await WorkspaceArtifactsCleanupHook().run(ctx)

    assert len(scan_threads) == 2
    assert all(thread_id != event_loop_thread for thread_id in scan_threads)
    assert (
        ctx.extras["workspace_artifact_manifest"]["artifacts"][0]["path"]
        == "report.txt"
    )
