# -*- coding: utf-8 -*-
"""Command-level tests for checkpoint basics."""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.checkpoints import policy as checkpoint_policy
from qwenpaw.runtime.commands.control.checkpoint_handler import (
    CheckpointCommandHandler,
)
from qwenpaw.checkpoints.service import CheckpointService
from qwenpaw.checkpoints.policy import (
    ref_session_key,
    session_file_path,
    session_key,
)
from qwenpaw.checkpoints.models import CheckpointError
from qwenpaw.checkpoints.runtime import RUNTIME
from qwenpaw.checkpoints.repository import CheckpointRepository

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


def _write_session(
    workspace_dir: Path,
    text: str,
    *,
    session_id: str = SESSION_ID,
) -> Path:
    path = session_file_path(
        workspace_dir,
        session_id=session_id,
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


def test_session_key_is_unambiguous_and_bounded() -> None:
    left = session_key(channel="a-b", user_id="c", session_id="d")
    right = session_key(channel="a", user_id="b-c", session_id="d")
    punctuation = session_key(channel="a:b", user_id="c", session_id="d")
    repeated = session_key(channel="a--b", user_id="c", session_id="d")
    long_key = session_key(
        channel="频" * 300,
        user_id="user" * 300,
        session_id="session" * 300,
    )

    assert len({left, right, punctuation, repeated}) == 4
    assert len(long_key.encode("ascii")) <= 89
    assert long_key.rsplit("-", 1)[-1].isalnum()
    assert len(long_key.rsplit("-", 1)[-1]) == 64


def test_shadow_git_preserves_crlf_despite_user_git_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_config = tmp_path / "user.gitconfig"
    global_config.write_text("[core]\n\tautocrlf = true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    (tmp_path / ".gitattributes").write_text(
        "*.txt text eol=lf\n",
        encoding="utf-8",
    )
    source = tmp_path / "sample.txt"
    expected = b"first\r\nsecond\r\n"
    source.write_bytes(expected)

    repository = CheckpointRepository(tmp_path)
    tree = repository.write_workspace_tree()

    assert repository.read_blob(tree, "sample.txt") == expected
    source.write_bytes(b"changed\n")
    restored, deleted = repository.restore_tree_paths(tree, {"sample.txt"})
    assert restored == ["sample.txt"]
    assert deleted == []
    assert source.read_bytes() == expected


def test_config_fields_are_validated_lazily(tmp_path: Path) -> None:
    engine = CheckpointService(tmp_path)
    config = engine.repository.config_file
    previous_mtime_ns = config.stat().st_mtime_ns
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace("gc_keep_count = 20", 'gc_keep_count = "invalid"'),
        encoding="utf-8",
    )
    # Advance by one second so coarse timestamp resolution cannot hide the
    # change from the lazy mtime-based reload.
    stat = config.stat()
    os.utime(
        config,
        ns=(
            stat.st_atime_ns,
            max(stat.st_mtime_ns, previous_mtime_ns + 1_000_000_000),
        ),
    )

    assert engine.auto_enabled is False
    with pytest.raises(CheckpointError, match="gc.gc_keep_count"):
        _ = engine.gc_keep_count


@pytest.mark.asyncio
async def test_gc_settings_are_persisted_without_overwriting_other_sections(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    await engine.set_auto_enabled(True)

    result = await engine.set_gc_settings(
        gc_keep_count=42,
        gc_keep_days=9,
        pre_restore_retention_days=5,
    )

    assert result == {
        "gc_keep_count": 42,
        "gc_keep_days": 9,
        "pre_restore_retention_days": 5,
    }
    assert engine.auto_enabled is True
    config = engine.repository.config_file.read_text(encoding="utf-8")
    assert "gc_keep_count = 42" in config
    assert "gc_keep_days = 9" in config
    assert "pre_restore_retention_days = 5" in config
    assert "enabled = true" in config


@pytest.mark.asyncio
async def test_concurrent_config_updates_preserve_both_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    first_write_started = threading.Event()
    release_first_write = threading.Event()
    original_write = checkpoint_policy.write_text_atomic
    call_count = 0
    count_lock = threading.Lock()

    def delayed_first_write(path, content, **kwargs) -> None:
        nonlocal call_count
        with count_lock:
            call_count += 1
            is_first = call_count == 1
        if is_first:
            first_write_started.set()
            assert release_first_write.wait(timeout=5)
        original_write(path, content, **kwargs)

    monkeypatch.setattr(
        checkpoint_policy,
        "write_text_atomic",
        delayed_first_write,
    )
    auto_task = asyncio.create_task(engine.set_auto_enabled(True))
    assert await asyncio.to_thread(first_write_started.wait, 5)
    gc_task = asyncio.create_task(
        engine.set_gc_settings(
            gc_keep_count=33,
            gc_keep_days=11,
            pre_restore_retention_days=4,
        ),
    )
    await asyncio.sleep(0.05)
    release_first_write.set()
    await asyncio.gather(auto_task, gc_task)

    assert await engine.auto_settings() == (True, 1.5)
    assert await engine.gc_settings() == {
        "gc_keep_count": 33,
        "gc_keep_days": 11,
        "pre_restore_retention_days": 4,
    }


@pytest.mark.asyncio
async def test_first_service_initialization_does_not_block_event_loop(
    workspace: _Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    original_init = CheckpointRepository.__init__

    def slow_init(self, workspace_dir) -> None:
        started.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test initialization release timed out")
        original_init(self, workspace_dir)

    monkeypatch.setattr(CheckpointRepository, "__init__", slow_init)
    init_task = asyncio.create_task(
        RUNTIME.get_for_workspace_async(workspace),
    )
    assert await asyncio.to_thread(started.wait, 5)
    second_init_task = asyncio.create_task(
        RUNTIME.get_for_workspace_async(workspace),
    )

    heartbeats = 0
    for _ in range(5):
        await asyncio.sleep(0.01)
        heartbeats += 1

    assert heartbeats == 5
    assert not init_task.done()
    assert not second_init_task.done()
    release.set()
    service = await init_task
    second_service = await second_init_task
    assert second_service is service
    assert service.workspace_dir == workspace.workspace_dir.resolve()


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
async def test_snapshot_accepts_windows_reserved_device_name(
    workspace: _Workspace,
) -> None:
    _write_session(workspace.workspace_dir, "reserved snapshot name")

    created = await _run(workspace, "snapshot CON.txt")

    assert "**Snapshot created**" in created
    assert "ref-CON.txt" in created


@pytest.mark.asyncio
async def test_restore_command_validates_and_preserves_file_selection(
    workspace: _Workspace,
) -> None:
    confirmation = await _run(
        workspace,
        ('restore abcdef1 --include-files --files "docs/a b.md" src/app.py'),
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
async def test_control_restore_waits_for_active_agent(
    workspace: _Workspace,
) -> None:
    engine = _engine(workspace)
    session_path = _write_session(workspace.workspace_dir, "before")
    ref = await engine.make_auto_checkpoint(
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        query="before",
    )
    target = engine.repository.run_git("rev-parse", ref)
    _write_session(workspace.workspace_dir, "after")
    tracker = TaskTracker()
    workspace.task_tracker = tracker
    agent_started = asyncio.Event()
    release_agent = asyncio.Event()
    restore_started = asyncio.Event()
    restore_finished = asyncio.Event()
    restore_result: list[str] = []

    async def running_agent(_payload):
        agent_started.set()
        await release_agent.wait()
        yield "agent finished"

    async def restore_command(_payload):
        restore_started.set()
        restore_result.append(
            await _run(
                workspace,
                f"restore {target[:12]} --confirm",
            ),
        )
        restore_finished.set()
        yield "restore finished"

    agent_queue, _ = await tracker.attach_or_start(
        "running-agent",
        None,
        running_agent,
    )
    await asyncio.wait_for(agent_started.wait(), timeout=1)
    restore_queue, _ = await tracker.attach_or_start(
        "restore-command",
        None,
        restore_command,
    )
    await asyncio.wait_for(restore_started.wait(), timeout=1)
    for _ in range(100):
        if not engine.query_gate.is_set():
            break
        await asyncio.sleep(0.01)

    assert "after" in session_path.read_text(encoding="utf-8")
    assert not restore_finished.is_set()
    assert not engine.query_gate.is_set()

    release_agent.set()
    await asyncio.wait_for(restore_finished.wait(), timeout=30)
    async for _ in tracker.stream_from_queue(agent_queue, "running-agent"):
        pass
    async for _ in tracker.stream_from_queue(restore_queue, "restore-command"):
        pass

    assert "**Restore complete**" in restore_result[0]
    assert "before" in session_path.read_text(encoding="utf-8")
    assert engine.query_gate.is_set()
    assert not engine.maintenance_lock.locked()
    assert not engine.lock.locked()
    assert await tracker.list_active_tasks() == []


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
async def test_workspace_gc_applies_keep_count_per_session(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    session_ids = ("session-a", "session-b")
    expected_keys = {
        session_key(
            channel=CHANNEL,
            user_id=USER_ID,
            session_id=session_id,
        )
        for session_id in session_ids
    }
    for session_id in session_ids:
        for index in range(3):
            query = f"{session_id}-{index}"
            _write_session(
                tmp_path,
                query,
                session_id=session_id,
            )
            await engine.make_auto_checkpoint(
                session_id=session_id,
                user_id=USER_ID,
                channel=CHANNEL,
                query=query,
            )

    retained = await engine.gc(
        session_id="console",
        user_id="console",
        channel="console",
        all_sessions=True,
        dry_run=True,
        keep_count=2,
        keep_days=0,
    )
    retained_by_session = {
        key: [ref for ref in retained.kept_refs if ref_session_key(ref) == key]
        for key in expected_keys
    }
    deleted_by_session = {
        key: [
            ref for ref in retained.deleted_refs if ref_session_key(ref) == key
        ]
        for key in expected_keys
    }

    assert {key: len(refs) for key, refs in retained_by_session.items()} == {
        key: 2 for key in expected_keys
    }
    assert {key: len(refs) for key, refs in deleted_by_session.items()} == {
        key: 1 for key in expected_keys
    }

    compacted = await engine.gc(
        session_id="console",
        user_id="console",
        channel="console",
        all_sessions=True,
        compact=True,
        dry_run=True,
    )
    assert {
        key: sum(ref_session_key(ref) == key for ref in compacted.kept_refs)
        for key in expected_keys
    } == {key: 1 for key in expected_keys}
    assert {
        key: sum(ref_session_key(ref) == key for ref in compacted.deleted_refs)
        for key in expected_keys
    } == {key: 2 for key in expected_keys}


@pytest.mark.asyncio
async def test_session_gc_only_computes_current_session_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    for session_id in ("session-a", "session-b"):
        _write_session(tmp_path, session_id, session_id=session_id)
        await engine.make_auto_checkpoint(
            session_id=session_id,
            user_id=USER_ID,
            channel=CHANNEL,
            query=session_id,
        )

    current_key = session_key(
        channel=CHANNEL,
        user_id=USER_ID,
        session_id="session-a",
    )
    computed_keys: list[str] = []
    original_head_for_records = getattr(engine, "_head_for_records")

    def recording_head_for_records(key, records):
        computed_keys.append(key)
        return original_head_for_records(key, records)

    monkeypatch.setattr(
        engine,
        "_head_for_records",
        recording_head_for_records,
    )
    await engine.gc(
        session_id="session-a",
        user_id=USER_ID,
        channel=CHANNEL,
        dry_run=True,
        keep_count=0,
        keep_days=0,
    )

    assert computed_keys == [current_key]


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
