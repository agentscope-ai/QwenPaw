# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from qwenpaw.app.rollback.service import SnapshotService


@pytest.fixture
def temp_workspace():
    with TemporaryDirectory() as temp_dir:
        workspace_dir = Path(temp_dir)
        yield workspace_dir


def _run(coro):
    return asyncio.run(coro)


def test_snapshot_service_init_and_track(temp_workspace):
    svc = SnapshotService(temp_workspace)

    _run(svc.init())
    assert (svc.git_dir / "HEAD").exists()
    assert (svc.git_dir / "info" / "exclude").exists()

    test_file = temp_workspace / "test.txt"
    test_file.write_text("hello world", encoding="utf-8")

    hash1 = _run(svc.track())
    assert hash1 is not None

    test_file.write_text("hello modified", encoding="utf-8")

    hash2 = _run(svc.track())
    assert hash2 is not None
    assert hash1 != hash2


def test_snapshot_service_excludes_runtime_files(temp_workspace):
    svc = SnapshotService(temp_workspace)
    user_file = temp_workspace / "keep.txt"
    user_file.write_text("payload", encoding="utf-8")

    hash1 = _run(svc.track())

    sessions_dir = temp_workspace / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "state.json").write_text("{}", encoding="utf-8")
    (temp_workspace / "agent.json").write_text("{}", encoding="utf-8")
    (temp_workspace / "chats.json").write_text("{}", encoding="utf-8")
    (temp_workspace / "token_usage.json").write_text("[]", encoding="utf-8")
    memory_dir = temp_workspace / "memory"
    memory_dir.mkdir()
    (memory_dir / "note.md").write_text("runtime memory", encoding="utf-8")
    (temp_workspace / ".reme_store_v1").write_text("", encoding="utf-8")

    hash2 = _run(svc.track())
    assert hash1 == hash2


def test_snapshot_service_patch(temp_workspace):
    svc = SnapshotService(temp_workspace)

    f1 = temp_workspace / "f1.txt"
    f1.write_text("f1", encoding="utf-8")
    hash1 = _run(svc.track())

    f1.write_text("f1 modified", encoding="utf-8")
    f2 = temp_workspace / "f2.txt"
    f2.write_text("f2", encoding="utf-8")

    changed_files = _run(svc.patch(hash1))

    assert "f1.txt" in changed_files
    assert "f2.txt" in changed_files
    assert len(changed_files) == 2


def test_snapshot_service_revert_overwrite_and_new_file(temp_workspace):
    svc = SnapshotService(temp_workspace)

    original = temp_workspace / "test.txt"
    original.write_text("initial", encoding="utf-8")
    hash1 = _run(svc.track())

    original.write_text("changed", encoding="utf-8")
    created = temp_workspace / "new.txt"
    created.write_text("new", encoding="utf-8")

    patch_files = _run(svc.patch(hash1))
    success = _run(svc.revert(hash1, patch_files))

    assert success
    assert original.read_text(encoding="utf-8") == "initial"
    assert not created.exists()


def test_undo_restores_renamed_file(temp_workspace):
    svc = SnapshotService(temp_workspace)
    source = temp_workspace / "a.txt"
    source.write_text("payload", encoding="utf-8")
    before_hash = _run(svc.track())

    target = temp_workspace / "b.txt"
    source.rename(target)
    entry = _run(svc.record_history_if_changed("sess1", before_hash))

    assert entry is not None
    assert sorted(entry.files) == ["a.txt", "b.txt"]

    status, _ = _run(svc.undo_latest())

    assert status == "ok"
    assert source.read_text(encoding="utf-8") == "payload"
    assert not target.exists()


def test_record_history_if_changed_creates_linear_entry(temp_workspace):
    svc = SnapshotService(temp_workspace)
    file_path = temp_workspace / "note.txt"
    file_path.write_text("v1", encoding="utf-8")
    before_hash = _run(svc.track())

    file_path.write_text("v2", encoding="utf-8")
    entry = _run(svc.record_history_if_changed("sess1", before_hash))

    assert entry is not None
    assert entry.session_id == "sess1"
    assert entry.before_hash == before_hash
    assert entry.after_hash != before_hash
    assert entry.files == ["note.txt"]

    latest = _run(svc.get_latest_applied())
    assert latest is not None
    assert latest.id == entry.id


def test_undo_restores_deleted_file(temp_workspace):
    svc = SnapshotService(temp_workspace)
    target = temp_workspace / "important.txt"
    target.write_text("keep me", encoding="utf-8")
    before_hash = _run(svc.track())

    target.unlink()
    entry = _run(svc.record_history_if_changed("sess1", before_hash))
    assert entry is not None

    status, undone = _run(svc.undo_latest())

    assert status == "ok"
    assert undone is not None
    assert target.read_text(encoding="utf-8") == "keep me"


def test_undo_and_redo_follow_linear_history(temp_workspace):
    svc = SnapshotService(temp_workspace)
    target = temp_workspace / "story.txt"
    target.write_text("state1", encoding="utf-8")

    before_hash = _run(svc.track())
    target.write_text("state2", encoding="utf-8")
    entry1 = _run(svc.record_history_if_changed("sess1", before_hash))
    assert entry1 is not None

    before_hash = _run(svc.track())
    target.write_text("state3", encoding="utf-8")
    entry2 = _run(svc.record_history_if_changed("sess1", before_hash))
    assert entry2 is not None

    status, _ = _run(svc.undo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state2"

    memory_dir = temp_workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    (memory_dir / "runtime.md").write_text(
        "should not block undo",
        encoding="utf-8",
    )
    (temp_workspace / "agent.json").write_text(
        '{"last_dispatch":"runtime"}',
        encoding="utf-8",
    )
    (temp_workspace / ".reme_store_v1").write_text("", encoding="utf-8")

    status, _ = _run(svc.undo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state1"

    status, _ = _run(svc.redo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state2"

    status, _ = _run(svc.redo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state3"


def test_undo_redo_can_interleave(temp_workspace):
    svc = SnapshotService(temp_workspace)
    target = temp_workspace / "story.txt"
    target.write_text("state1", encoding="utf-8")

    before_hash = _run(svc.track())
    target.write_text("state2", encoding="utf-8")
    assert (
        _run(svc.record_history_if_changed("sess1", before_hash)) is not None
    )

    before_hash = _run(svc.track())
    target.write_text("state3", encoding="utf-8")
    assert (
        _run(svc.record_history_if_changed("sess1", before_hash)) is not None
    )

    status, _ = _run(svc.undo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state2"

    status, _ = _run(svc.redo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state3"

    status, _ = _run(svc.undo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state2"

    status, _ = _run(svc.undo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state1"

    status, _ = _run(svc.redo_latest())
    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "state2"


def test_undo_is_blocked_when_workspace_diverges(temp_workspace):
    svc = SnapshotService(temp_workspace)
    target = temp_workspace / "note.txt"
    target.write_text("v1", encoding="utf-8")
    before_hash = _run(svc.track())

    target.write_text("v2", encoding="utf-8")
    entry = _run(svc.record_history_if_changed("sess1", before_hash))
    assert entry is not None

    target.write_text("manual edit", encoding="utf-8")
    status, blocked_entry = _run(svc.undo_latest())

    assert status == "diverged"
    assert blocked_entry is not None
    assert target.read_text(encoding="utf-8") == "manual edit"


def test_undo_ignores_unrelated_workspace_noise(temp_workspace):
    svc = SnapshotService(temp_workspace)
    target = temp_workspace / "note.txt"
    target.write_text("v1", encoding="utf-8")
    before_hash = _run(svc.track())

    target.write_text("v2", encoding="utf-8")
    entry = _run(svc.record_history_if_changed("sess1", before_hash))
    assert entry is not None

    unrelated = temp_workspace / "dialog" / "session.jsonl"
    unrelated.parent.mkdir(exist_ok=True)
    unrelated.write_text("noise", encoding="utf-8")
    (temp_workspace / "agent.json").write_text(
        '{"last_dispatch":"runtime"}',
        encoding="utf-8",
    )
    (temp_workspace / "skill.json").write_text("{}", encoding="utf-8")

    status, _ = _run(svc.undo_latest())

    assert status == "ok"
    assert target.read_text(encoding="utf-8") == "v1"


def test_load_history_skips_invalid_entries(temp_workspace):
    svc = SnapshotService(temp_workspace)
    svc.rollback_dir.mkdir(parents=True, exist_ok=True)
    svc.history_file.write_text(
        '[{"id":"ok","session_id":"s","before_hash":"a","after_hash":"b",'
        '"files":["x.txt"],"created_at":1.0,"status":"applied"},'
        '"bad-entry",'
        '{"id":"broken"}]',
        encoding="utf-8",
    )

    history = _run(svc._load_history_locked())

    assert len(history) == 1
    assert history[0].id == "ok"


def test_track_returns_none_when_git_is_unavailable(
    temp_workspace,
    monkeypatch,
):
    svc = SnapshotService(temp_workspace)
    test_file = temp_workspace / "test.txt"
    test_file.write_text("payload", encoding="utf-8")

    async def fake_run_command(_cmd):
        return 127, "", "git missing"

    monkeypatch.setattr(svc, "_run_command", fake_run_command)

    assert _run(svc.track()) is None
