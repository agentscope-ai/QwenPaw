# -*- coding: utf-8 -*-
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.project_files import Project, ProjectStore
from services.runtime_files.manual_edit_store import (
    ManualEditBufferStore,
    ManualEditChangeConflict,
    ManualEditGenerationConflict,
)
from services.runtime_files.models import ProjectChange, ProjectChangeKind
from services.runtime_files import manual_edit_store as store_module


pytestmark = pytest.mark.unit


PROJECT_ID = "project-1"


def _store(tmp_path: Path) -> tuple[Path, ManualEditBufferStore]:
    root = tmp_path.resolve()
    ProjectStore(root).create(
        Project.new(project_id=PROJECT_ID, name="Project"),
    )
    return root, ManualEditBufferStore(root)


def _change(
    pointer: str,
    before_hash: str,
    after_hash: str,
    *,
    before: object,
    after: object,
    kind: ProjectChangeKind = ProjectChangeKind.UPDATE,
) -> ProjectChange:
    return ProjectChange(
        kind=kind,
        json_pointer=pointer,
        before_hash=before_hash,
        after_hash=after_hash,
        before=before,
        after=after,
    )


def test_frontend_commits_coalesce_first_before_to_latest_after(tmp_path):
    _root, store = _store(tmp_path)
    first = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=0,
        head_generation=1,
        changes=[
            _change(
                "/name",
                "sha256:name-a",
                "sha256:name-b",
                before="A",
                after="B",
            ),
        ],
    )
    second = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=1,
        head_generation=2,
        changes=[
            _change(
                "/name",
                "sha256:name-b",
                "sha256:name-c",
                before="B",
                after="C",
            ),
        ],
    )
    final = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=2,
        head_generation=3,
        changes=[
            _change(
                "/story/title",
                "sha256:title-a",
                "sha256:title-b",
                before="Old",
                after="New",
            ),
        ],
    )

    assert first is not None and second is not None and final is not None
    assert first.buffer_id == second.buffer_id == final.buffer_id
    assert final.base_generation == 0
    assert final.head_generation == 3
    assert final.head == 3
    assert [item.json_pointer for item in final.changes] == [
        "/name",
        "/story/title",
    ]
    name = final.changes[0]
    assert name.before_hash == "sha256:name-a"
    assert name.after_hash == "sha256:name-c"
    assert name.before == "A"
    assert name.after == "C"
    assert store.read(PROJECT_ID) == final


def test_restoring_baseline_removes_update_and_create_delete_buffer(tmp_path):
    root, store = _store(tmp_path)
    store.record_frontend_commit(
        PROJECT_ID,
        base_generation=0,
        head_generation=1,
        changes=[
            _change(
                "/name",
                "sha256:a",
                "sha256:b",
                before="A",
                after="B",
            ),
        ],
    )
    restored = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=1,
        head_generation=2,
        changes=[
            _change(
                "/name",
                "sha256:b",
                "sha256:a",
                before="B",
                after="A",
            ),
        ],
    )

    assert restored is None
    assert store.read(PROJECT_ID) is None
    assert not (
        root / PROJECT_ID / "runtime" / "manual-edit" / "buffer.json"
    ).exists()

    store.record_frontend_commit(
        PROJECT_ID,
        base_generation=2,
        head_generation=3,
        changes=[
            _change(
                "/story/new",
                "sha256:missing",
                "sha256:new",
                before=None,
                after={"id": "new"},
                kind=ProjectChangeKind.CREATE,
            ),
        ],
    )
    removed = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=3,
        head_generation=4,
        changes=[
            _change(
                "/story/new",
                "sha256:new",
                "sha256:missing",
                before={"id": "new"},
                after=None,
                kind=ProjectChangeKind.DELETE,
            ),
        ],
    )
    assert removed is None
    assert store.read(PROJECT_ID) is None


def test_record_rejects_generation_gaps_payload_gaps_and_duplicates(tmp_path):
    _root, store = _store(tmp_path)
    first_change = _change(
        "/name",
        "sha256:a",
        "sha256:b",
        before="A",
        after="B",
    )
    first = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=0,
        head_generation=1,
        changes=[first_change],
    )

    with pytest.raises(ManualEditGenerationConflict, match="expected base=1"):
        store.record_frontend_commit(
            PROJECT_ID,
            base_generation=0,
            head_generation=2,
            changes=[],
        )
    with pytest.raises(ManualEditChangeConflict, match="expected before"):
        store.record_frontend_commit(
            PROJECT_ID,
            base_generation=1,
            head_generation=2,
            changes=[
                _change(
                    "/name",
                    "sha256:unrelated",
                    "sha256:c",
                    before="Other",
                    after="C",
                ),
            ],
        )
    with pytest.raises(ManualEditChangeConflict, match="duplicate"):
        store.record_frontend_commit(
            PROJECT_ID,
            base_generation=1,
            head_generation=2,
            changes=[first_change, first_change],
        )

    assert store.read(PROJECT_ID) == first


def test_consume_renames_to_hashed_idempotency_receipt(tmp_path):
    root, store = _store(tmp_path)
    first = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=0,
        head_generation=1,
        changes=[
            _change(
                "/name",
                "sha256:a",
                "sha256:b",
                before="A",
                after="B",
            ),
        ],
    )
    consumer_id = "../../agent/request/1"
    consumed = store.consume(PROJECT_ID, consumer_id=consumer_id)
    replay = store.consume(PROJECT_ID, consumer_id=consumer_id)

    assert first is not None and consumed is not None and replay is not None
    assert consumed.buffer == first
    assert consumed.replayed is False
    assert replay.buffer == first
    assert replay.replayed is True
    assert store.read(PROJECT_ID) is None
    receipt = store.receipt_path(PROJECT_ID, consumer_id)
    assert receipt.is_file()
    assert receipt.parent.parent == (
        root / PROJECT_ID / "runtime" / "manual-edit"
    )
    assert ".." not in receipt.name
    assert "request" not in receipt.name

    later = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=1,
        head_generation=2,
        changes=[
            _change(
                "/name",
                "sha256:b",
                "sha256:c",
                before="B",
                after="C",
            ),
        ],
    )
    old_retry = store.consume(PROJECT_ID, consumer_id=consumer_id)
    assert old_retry is not None and old_retry.buffer == first
    assert store.read(PROJECT_ID) == later

    next_consumed = store.consume(PROJECT_ID, consumer_id="agent-request-2")
    assert next_consumed is not None
    assert next_consumed.buffer == later
    assert next_consumed.replayed is False


def test_concurrent_same_consumer_gets_one_take_and_durable_replays(tmp_path):
    root, store = _store(tmp_path)
    expected = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=0,
        head_generation=1,
        changes=[
            _change(
                "/name",
                "sha256:a",
                "sha256:b",
                before="A",
                after="B",
            ),
        ],
    )

    def consume(_index: int):
        return ManualEditBufferStore(root).consume(
            PROJECT_ID,
            consumer_id="agent-request",
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(consume, range(6)))

    assert expected is not None
    assert all(result is not None for result in results)
    consumptions = [result for result in results if result is not None]
    assert sum(item.replayed is False for item in consumptions) == 1
    assert sum(item.replayed is True for item in consumptions) == 5
    assert {item.buffer.buffer_id for item in consumptions} == {
        expected.buffer_id,
    }
    assert store.read(PROJECT_ID) is None


def test_restart_replays_receipt_when_directory_fsync_failed_after_rename(
    tmp_path,
    monkeypatch,
):
    root, store = _store(tmp_path)
    expected = store.record_frontend_commit(
        PROJECT_ID,
        base_generation=0,
        head_generation=1,
        changes=[
            _change(
                "/name",
                "sha256:a",
                "sha256:b",
                before="A",
                after="B",
            ),
        ],
    )
    real_fsync = store_module.fsync_directory
    calls = 0

    def fail_after_rename(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected receipt fsync failure")
        real_fsync(path)

    monkeypatch.setattr(store_module, "fsync_directory", fail_after_rename)
    with pytest.raises(OSError, match="injected receipt fsync failure"):
        store.consume(PROJECT_ID, consumer_id="agent-request")
    monkeypatch.setattr(store_module, "fsync_directory", real_fsync)

    restarted = ManualEditBufferStore(root)
    replay = restarted.consume(PROJECT_ID, consumer_id="agent-request")
    assert expected is not None and replay is not None
    assert replay.replayed is True
    assert replay.buffer == expected
    assert restarted.read(PROJECT_ID) is None


def test_non_frontend_commit_keeps_unrelated_edits_and_drops_overlap(tmp_path):
    _root, store = _store(tmp_path)
    store.record_frontend_commit(
        PROJECT_ID,
        base_generation=0,
        head_generation=1,
        changes=[
            _change(
                "/name",
                "sha256:name-a",
                "sha256:name-b",
                before="A",
                after="B",
            ),
            _change(
                "/story/title",
                "sha256:title-a",
                "sha256:title-b",
                before="Old",
                after="New",
            ),
        ],
    )

    retained = store.reconcile_non_frontend_commit(
        PROJECT_ID,
        base_generation=1,
        head_generation=2,
        changes=[
            _change(
                "/story",
                "sha256:story-a",
                "sha256:story-b",
                before={},
                after={"title": "Agent"},
            ),
        ],
    )
    assert retained is not None
    assert retained.head_generation == 2
    assert [change.json_pointer for change in retained.changes] == ["/name"]

    removed = store.reconcile_non_frontend_commit(
        PROJECT_ID,
        base_generation=2,
        head_generation=3,
        changes=[
            _change(
                "/name",
                "sha256:name-b",
                "sha256:name-c",
                before="B",
                after="C",
            ),
        ],
    )
    assert removed is None
    assert store.read(PROJECT_ID) is None
