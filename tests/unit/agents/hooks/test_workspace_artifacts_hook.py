# -*- coding: utf-8 -*-
"""Workspace artifact lifecycle hook behavior."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import qwenpaw.hooks.workspace_artifacts_hook as artifacts_hook_module
from qwenpaw.config.context import set_current_project_dir
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
    workspace = SimpleNamespace(artifact_turn_lock=asyncio.Lock())
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        workspace=workspace,
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


async def test_external_project_artifact_uses_project_root(
    tmp_path: Path,
) -> None:
    workspace_dir = tmp_path / "workspace"
    project_dir = tmp_path / "project"
    workspace_dir.mkdir()
    project_dir.mkdir()
    workspace = SimpleNamespace(artifact_turn_lock=asyncio.Lock())
    ctx = SimpleNamespace(
        workspace_dir=workspace_dir,
        workspace=workspace,
        extras={"turn_id": "turn-1"},
        agent_id="agent-1",
        session_id="chat-1",
    )
    set_current_project_dir(project_dir)
    try:
        await WorkspaceArtifactsHook().run(ctx)
        (project_dir / "report.txt").write_text(
            "ready",
            encoding="utf-8",
        )
        await WorkspaceArtifactsFinalizeHook().run(ctx)
    finally:
        await WorkspaceArtifactsCleanupHook().run(ctx)
        set_current_project_dir(None)

    artifact = ctx.extras["workspace_artifact_manifest"]["artifacts"][0]
    assert artifact["path"] == "report.txt"
    assert artifact["root"] == "project"


def test_nested_project_root_is_scanned_once(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    project_dir = workspace_dir / "project"
    project_dir.mkdir(parents=True)

    resolve_roots = getattr(
        artifacts_hook_module,
        "_resolve_artifact_roots",
    )
    roots = resolve_roots(
        workspace_dir,
        project_dir,
    )

    assert roots == {"workspace": workspace_dir.resolve()}


async def test_turns_share_one_workspace_artifact_lock(
    tmp_path: Path,
) -> None:
    workspace = SimpleNamespace(artifact_turn_lock=asyncio.Lock())
    first_ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        workspace=workspace,
        extras={"turn_id": "turn-1"},
        agent_id="agent-1",
        session_id="chat-1",
    )
    second_ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        workspace=workspace,
        extras={"turn_id": "turn-2"},
        agent_id="agent-1",
        session_id="chat-2",
    )
    second_started = asyncio.Event()
    second_acquired = asyncio.Event()
    allow_second_cleanup = asyncio.Event()

    async def run_second_turn() -> None:
        second_started.set()
        await WorkspaceArtifactsHook().run(second_ctx)
        second_acquired.set()
        await allow_second_cleanup.wait()
        await WorkspaceArtifactsCleanupHook().run(second_ctx)

    await WorkspaceArtifactsHook().run(first_ctx)
    second_task = asyncio.create_task(run_second_turn())
    await second_started.wait()
    await asyncio.sleep(0)

    assert second_acquired.is_set() is False

    await WorkspaceArtifactsCleanupHook().run(first_ctx)
    await asyncio.wait_for(second_acquired.wait(), timeout=1)
    allow_second_cleanup.set()
    await second_task


async def test_cancelled_pre_scan_releases_turn_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = SimpleNamespace(artifact_turn_lock=asyncio.Lock())
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        workspace=workspace,
        extras={"turn_id": "turn-1"},
        agent_id="agent-1",
        session_id="chat-1",
    )

    async def cancel_scan(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(artifacts_hook_module, "run_sync_io", cancel_scan)

    with pytest.raises(asyncio.CancelledError):
        await WorkspaceArtifactsHook().run(ctx)

    assert workspace.artifact_turn_lock.locked() is False
