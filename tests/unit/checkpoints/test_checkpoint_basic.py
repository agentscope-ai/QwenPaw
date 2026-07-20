# -*- coding: utf-8 -*-
"""Command-level tests for checkpoint basics."""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.runtime.commands.control.checkpoint_handler import (
    CheckpointCommandHandler,
)
from qwenpaw.checkpoints.service import CheckpointService
from qwenpaw.checkpoints.policy import session_file_path, session_key
from qwenpaw.checkpoints.models import CheckpointError
from qwenpaw.checkpoints.runtime import RUNTIME

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="checkpoint tests require git",
)

SESSION_ID = "session-1"
USER_ID = "user"
CHANNEL = "console"


class _Workspace:
    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir


@pytest.fixture(autouse=True)
async def _clear_checkpoint_registry():
    await RUNTIME.flush_and_close_all()
    yield
    await RUNTIME.flush_and_close_all()


@pytest.fixture
def workspace(tmp_path: Path) -> _Workspace:
    return _Workspace(tmp_path)


def _context(workspace: _Workspace, raw: str) -> SimpleNamespace:
    return SimpleNamespace(
        workspace=workspace,
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        args={"_raw_args": raw},
    )


async def _run(workspace: _Workspace, raw: str) -> str:
    return await CheckpointCommandHandler().handle(_context(workspace, raw))


def _write_session(workspace_dir: Path, text: str) -> Path:
    path = session_file_path(
        workspace_dir,
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "agent": {
                    "state": {
                        "context": [
                            {
                                "id": f"msg-{text}",
                                "role": "user",
                                "content": [{"type": "text", "text": text}],
                            },
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _engine(workspace: _Workspace):
    return RUNTIME.get_for_workspace(workspace)


def test_config_fields_are_validated_lazily(tmp_path: Path) -> None:
    engine = CheckpointService(tmp_path)
    config = engine.repository.config_file
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace("gc_keep_count = 20", 'gc_keep_count = "invalid"'),
        encoding="utf-8",
    )

    assert engine.auto_enabled is False
    with pytest.raises(CheckpointError, match="gc.gc_keep_count"):
        _ = engine.gc_keep_count


@pytest.mark.asyncio
async def test_auto_command_reports_toggles_and_validates_args(
    workspace: _Workspace,
) -> None:
    status = await _run(workspace, "auto")
    assert "**Auto checkpoint: disabled**" in status

    enabled = await _run(workspace, "auto on")
    assert "**Auto checkpoint enabled**" in enabled
    assert _engine(workspace).auto_enabled is True

    disabled = await _run(workspace, "auto off")
    assert "**Auto checkpoint disabled**" in disabled
    assert _engine(workspace).auto_enabled is False

    with pytest.raises(CheckpointError, match="auto \\[on\\|off\\]"):
        await _run(workspace, "auto maybe")


@pytest.mark.asyncio
async def test_snapshot_and_timeline_cover_named_checkpoint(
    workspace: _Workspace,
) -> None:
    _write_session(workspace.workspace_dir, "first query")

    created = await _run(workspace, "snapshot manual save")
    assert "**Snapshot created**" in created
    assert "manual-save" in created

    timeline = await _run(workspace, "timeline --limit=5")
    assert "**Checkpoint timeline**" in timeline
    assert "snapshot" in timeline
    assert "manual-save" in timeline
    assert "first query" in timeline
    assert "Restore by number" in timeline

    with pytest.raises(CheckpointError, match="Unknown option"):
        await _run(workspace, "timeline --unknown")


@pytest.mark.asyncio
async def test_restore_command_validates_and_preserves_file_selection(
    workspace: _Workspace,
) -> None:
    confirmation = await _run(
        workspace,
        (
            "restore abcdef1 --include-files "
            '--files "docs/a b.md" src/app.py'
        ),
    )
    assert "**Confirmation required**" in confirmation
    assert '--files "docs/a b.md"' in confirmation
    assert '--files "src/app.py"' in confirmation

    selection_required = await _run(
        workspace,
        "restore abcdef1 --include-files",
    )
    assert "**File selection required**" in selection_required
    assert "--include-files --dry-run" in selection_required
    assert "--files <path...> --confirm" in selection_required

    with pytest.raises(CheckpointError, match="together with"):
        await _run(workspace, "restore abcdef1 --files src/app.py")
    with pytest.raises(CheckpointError, match="requires at least one"):
        await _run(
            workspace,
            "restore abcdef1 --include-files --files --dry-run",
        )
    with pytest.raises(CheckpointError, match="requires `--files`"):
        await _run(
            workspace,
            "restore abcdef1 --include-files --confirm",
        )


@pytest.mark.asyncio
async def test_gc_requires_confirmation_and_compacts_auto_checkpoints(
    workspace: _Workspace,
) -> None:
    engine = _engine(workspace)
    for index in range(3):
        _write_session(workspace.workspace_dir, f"query {index}")
        await engine.make_auto_checkpoint(
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
            query=f"query {index}",
        )
    _write_session(workspace.workspace_dir, "manual")
    await engine.snapshot(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        message="keep me",
    )

    confirmation = await _run(workspace, "gc --compact")
    assert "**Confirmation required**" in confirmation
    assert "/checkpoint gc --compact --dry-run" in confirmation

    preview = await _run(workspace, "gc --compact --dry-run")
    assert "**Checkpoint cleanup preview**" in preview
    assert "Would remove" in preview

    before = await engine.timeline(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        include_all=True,
    )
    assert sum(entry.kind == "auto" for entry in before) == 3

    applied = await _run(workspace, "gc --compact --confirm")
    assert "**Checkpoint cleanup complete**" in applied

    after = await engine.timeline(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        include_all=True,
    )
    assert sum(entry.kind == "auto" for entry in after) == 0
    assert any(
        entry.kind == "snap" and entry.name == "keep-me" for entry in after
    )


@pytest.mark.asyncio
async def test_reset_requires_confirm_and_reinitializes_checkpoint_store(
    workspace: _Workspace,
) -> None:
    _write_session(workspace.workspace_dir, "before reset")
    await _run(workspace, "auto on")
    await _run(workspace, "snapshot reset target")
    assert _engine(workspace).auto_enabled is True

    prompt = await _run(workspace, "reset")
    assert "**Reset checkpoint data?**" in prompt
    assert "reset --confirm" in prompt

    reset = await _run(workspace, "reset --confirm")
    assert "**Checkpoint data reset**" in reset
    assert _engine(workspace).auto_enabled is False

    timeline = await _run(workspace, "timeline")
    assert "No checkpoints found for this session" in timeline


@pytest.mark.asyncio
async def test_snapshot_reuses_index_and_timeline_batches_git_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    _write_session(tmp_path, "first")
    await engine.make_auto_checkpoint(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        query="first",
    )

    calls: list[tuple[str, ...]] = []
    original_run_git = engine.repository.run_git

    def recording_run_git(*args: str, input_text: str | None = None) -> str:
        calls.append(args)
        return original_run_git(*args, input_text=input_text)

    monkeypatch.setattr(engine.repository, "run_git", recording_run_git)
    _write_session(tmp_path, "second")
    await engine.make_auto_checkpoint(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        query="second",
    )
    assert not any(call[:2] == ("read-tree", "--empty") for call in calls)

    calls.clear()
    entries = await engine.timeline(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
    )
    assert len(entries) == 2
    assert sum(call[0] == "for-each-ref" for call in calls) == 1
    assert not any(call[0] in {"log", "show"} for call in calls)


@pytest.mark.asyncio
async def test_gc_skips_git_maintenance_when_nothing_is_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    _write_session(tmp_path, "permanent")
    await engine.snapshot(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        message="permanent",
    )
    calls: list[tuple[str, ...]] = []
    original_run_git = engine.repository.run_git

    def recording_run_git(*args: str, input_text: str | None = None) -> str:
        calls.append(args)
        return original_run_git(*args, input_text=input_text)

    monkeypatch.setattr(engine.repository, "run_git", recording_run_git)
    result = await engine.gc(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
    )
    assert result.deleted_refs == ()
    assert not any(call[0] == "gc" for call in calls)


@pytest.mark.asyncio
async def test_delete_sessions_removes_only_target_refs_and_head(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    _write_session(tmp_path, "target")
    target_ref = await engine.make_snapshot(
        kind="snap",
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        name="target",
        message="target",
    )
    other_ref = await engine.make_snapshot(
        kind="snap",
        session_id="session-2",
        user_id=USER_ID,
        channel=CHANNEL,
        name="other",
        message="other",
    )

    deleted = await engine.delete_sessions(
        [(SESSION_ID, USER_ID, CHANNEL)],
    )

    assert deleted == (target_ref,)
    assert engine.repository.ref_exists(target_ref) is False
    assert engine.repository.ref_exists(other_ref) is True
    assert (
        engine.repository.get_session_head(
            session_key(
                channel=CHANNEL,
                user_id=USER_ID,
                session_id=SESSION_ID,
            ),
        )
        is None
    )
    assert (
        await engine.timeline(
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
        )
        == []
    )


@pytest.mark.asyncio
async def test_delete_session_cancels_pending_auto_snapshot(
    workspace: _Workspace,
) -> None:
    _write_session(workspace.workspace_dir, "pending")
    engine = _engine(workspace)
    created = False

    async def delayed_snapshot() -> None:
        nonlocal created
        created = True
        await engine.make_auto_checkpoint(
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
        )

    key = session_key(
        channel=CHANNEL,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    RUNTIME.debouncer.schedule(
        f"{engine.workspace_dir}:{key}",
        delayed_snapshot,
        delay=0.01,
    )

    await RUNTIME.delete_session_checkpoints(
        workspace,
        [(SESSION_ID, USER_ID, CHANNEL)],
    )
    await asyncio.sleep(0.03)

    assert created is False
    assert (
        await engine.timeline(
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
        )
        == []
    )


@pytest.mark.asyncio
async def test_delete_session_does_not_create_unused_checkpoint_store(
    workspace: _Workspace,
) -> None:
    deleted = await RUNTIME.delete_session_checkpoints(
        workspace,
        [(SESSION_ID, USER_ID, CHANNEL)],
    )

    assert deleted == ()
    assert not (workspace.workspace_dir / "checkpoints").exists()
