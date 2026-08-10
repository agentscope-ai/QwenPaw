# -*- coding: utf-8 -*-
"""Workspace artifact lifecycle hook behavior."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import qwenpaw.hooks.workspace_artifacts_hook as artifacts_hook_module
import qwenpaw.agents.artifacts.lifecycle as artifact_lifecycle_module
from qwenpaw.agents.artifacts import (
    ArtifactCollectorGroup,
    WorkspaceSnapshot,
)
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
    capture_snapshot = artifact_lifecycle_module.capture_workspace_snapshot

    def tracked_capture(workspace_dir):
        scan_threads.append(threading.get_ident())
        return capture_snapshot(workspace_dir)

    monkeypatch.setattr(
        artifact_lifecycle_module,
        "capture_workspace_snapshot",
        tracked_capture,
    )
    workspace = SimpleNamespace()
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


async def test_root_canonicalization_runs_once_off_event_loop(
    monkeypatch,
    tmp_path: Path,
) -> None:
    event_loop_thread = threading.get_ident()
    calls: list[int] = []
    resolve_roots = artifact_lifecycle_module.resolve_artifact_roots

    def tracked_resolve(workspace_dir, project_dir):
        calls.append(threading.get_ident())
        return resolve_roots(workspace_dir, project_dir)

    monkeypatch.setattr(
        artifact_lifecycle_module,
        "resolve_artifact_roots",
        tracked_resolve,
    )
    workspace = SimpleNamespace()
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        workspace=workspace,
        extras={"turn_id": "turn-1"},
        agent_id="agent-1",
        session_id="chat-1",
    )

    await WorkspaceArtifactsHook().run(ctx)
    await WorkspaceArtifactsCleanupHook().run(ctx)

    assert len(calls) == 1
    assert calls[0] != event_loop_thread


async def test_external_project_artifact_uses_project_root(
    tmp_path: Path,
) -> None:
    workspace_dir = tmp_path / "workspace"
    project_dir = tmp_path / "project"
    workspace_dir.mkdir()
    project_dir.mkdir()
    workspace = SimpleNamespace()
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


def test_truncated_only_collection_generates_manifest(tmp_path: Path) -> None:
    collector = ArtifactCollectorGroup(
        {"workspace": tmp_path},
        {"workspace": WorkspaceSnapshot.create({}, truncated=True)},
    )

    # pylint: disable=protected-access
    manifest = artifact_lifecycle_module._collect_manifest(
        collector,
        agent_id="agent-1",
        session_id="chat-1",
        turn_id="turn-1",
    )
    # pylint: enable=protected-access

    assert manifest is not None
    assert manifest["artifacts"] == []
    assert manifest["changes"] == []
    assert manifest["truncated"] is True


async def test_overlapping_turns_run_without_cross_claiming_files(
    tmp_path: Path,
) -> None:
    workspace = SimpleNamespace()
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
    second_acquired = asyncio.Event()
    finish_second = asyncio.Event()

    async def run_second_turn() -> None:
        await WorkspaceArtifactsHook().run(second_ctx)
        second_acquired.set()
        await finish_second.wait()
        await WorkspaceArtifactsFinalizeHook().run(second_ctx)
        await WorkspaceArtifactsCleanupHook().run(second_ctx)

    await WorkspaceArtifactsHook().run(first_ctx)
    second_task = asyncio.create_task(run_second_turn())
    await asyncio.wait_for(second_acquired.wait(), timeout=1)
    first_file = tmp_path / "first.txt"
    second_file = tmp_path / "second.txt"
    first_file.write_text("first", encoding="utf-8")
    second_file.write_text("second", encoding="utf-8")
    first_ctx.extras["workspace_artifact_turn"].collector.register(first_file)
    second_ctx.extras["workspace_artifact_turn"].collector.register(
        second_file,
    )

    await WorkspaceArtifactsFinalizeHook().run(first_ctx)
    await WorkspaceArtifactsCleanupHook().run(first_ctx)
    finish_second.set()
    await second_task

    first_manifest = first_ctx.extras["workspace_artifact_manifest"]
    second_manifest = second_ctx.extras["workspace_artifact_manifest"]
    assert [item["path"] for item in first_manifest["artifacts"]] == [
        "first.txt",
    ]
    assert [item["path"] for item in second_manifest["artifacts"]] == [
        "second.txt",
    ]
    assert first_manifest["truncated"] is True
    assert second_manifest["truncated"] is True


async def test_cancelled_pre_scan_finishes_coordination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = SimpleNamespace()
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        workspace=workspace,
        extras={"turn_id": "turn-1"},
        agent_id="agent-1",
        session_id="chat-1",
    )

    async def cancel_scan(*_args, **_kwargs):
        raise asyncio.CancelledError

    original_run_sync_io = artifact_lifecycle_module.run_sync_io
    monkeypatch.setattr(
        artifact_lifecycle_module,
        "run_sync_io",
        cancel_scan,
    )

    with pytest.raises(asyncio.CancelledError):
        await WorkspaceArtifactsHook().run(ctx)

    monkeypatch.setattr(
        artifact_lifecycle_module,
        "run_sync_io",
        original_run_sync_io,
    )
    next_ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        workspace=workspace,
        extras={"turn_id": "turn-2"},
        agent_id="agent-1",
        session_id="chat-2",
    )
    await WorkspaceArtifactsHook().run(next_ctx)
    (tmp_path / "report.txt").write_text("ready", encoding="utf-8")
    await WorkspaceArtifactsFinalizeHook().run(next_ctx)
    await WorkspaceArtifactsCleanupHook().run(next_ctx)

    manifest = next_ctx.extras["workspace_artifact_manifest"]
    assert manifest["truncated"] is False
