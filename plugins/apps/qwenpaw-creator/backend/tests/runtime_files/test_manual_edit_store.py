# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.project_files import Project, ProjectStore
from services.runtime_files import manual_edit_store as store_module
from services.runtime_files.manual_edit_store import (
    ManualEditBufferStore,
    ManualEditChangeConflict,
    ManualEditGenerationConflict,
)
from services.runtime_files.models import ProjectChange, ProjectChangeKind


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


def _name(before: str, after: str) -> ProjectChange:
    return _change(
        "/name",
        f"sha256:{before}",
        f"sha256:{after}",
        before=before,
        after=after,
    )


def _commit(store: ManualEditBufferStore, base: int, head: int, *changes):
    return store.record_frontend_commit(
        PROJECT_ID,
        base_generation=base,
        head_generation=head,
        changes=list(changes),
    )


def test_frontend_commits_coalesce_first_before_to_latest_after(tmp_path):
    _root, store = _store(tmp_path)
    first = _commit(store, 0, 1, _name("A", "B"))
    final = _commit(store, 1, 2, _name("B", "C"))

    assert first is not None and final is not None
    assert first.buffer_id == final.buffer_id
    assert final.base_generation == 0
    assert final.head_generation == 2
    assert final.head == 2
    name = final.changes[0]
    assert (name.before_hash, name.after_hash) == ("sha256:A", "sha256:C")
    assert (name.before, name.after) == ("A", "C")
    assert store.read(PROJECT_ID) == final


def test_restoring_baseline_removes_update_and_create_delete_buffer(tmp_path):
    root, store = _store(tmp_path)
    _commit(store, 0, 1, _name("A", "B"))
    restored = _commit(store, 1, 2, _name("B", "A"))

    assert restored is None
    assert store.read(PROJECT_ID) is None
    buffer_path = root / PROJECT_ID / "runtime" / "manual-edit" / "buffer.json"
    assert not buffer_path.exists()


def test_record_rejects_generation_gaps_payload_gaps_and_duplicates(tmp_path):
    _root, store = _store(tmp_path)
    first_change = _name("A", "B")
    first = _commit(store, 0, 1, first_change)

    with pytest.raises(ManualEditGenerationConflict, match="expected base=1"):
        _commit(store, 0, 2)
    with pytest.raises(ManualEditChangeConflict, match="expected before"):
        _commit(
            store,
            1,
            2,
            _change(
                "/name",
                "sha256:unrelated",
                "sha256:C",
                before="Other",
                after="C",
            ),
        )
    with pytest.raises(ManualEditChangeConflict, match="duplicate"):
        _commit(store, 1, 2, first_change, first_change)

    assert store.read(PROJECT_ID) == first


def test_concurrent_same_consumer_gets_one_take_and_durable_replays(tmp_path):
    root, store = _store(tmp_path)
    expected = _commit(store, 0, 1, _name("A", "B"))
    consumer_id = "../../agent/request/1"

    def consume(_index: int):
        return ManualEditBufferStore(root).consume(
            PROJECT_ID,
            consumer_id=consumer_id,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(consume, range(6)))

    assert expected is not None
    consumptions = [result for result in results if result is not None]
    assert len(consumptions) == 6
    assert sum(item.replayed is False for item in consumptions) == 1
    assert sum(item.replayed is True for item in consumptions) == 5
    assert {item.buffer.buffer_id for item in consumptions} == {
        expected.buffer_id,
    }
    assert store.read(PROJECT_ID) is None
    receipt = store.receipt_path(PROJECT_ID, consumer_id)
    assert receipt.is_file()
    assert ".." not in receipt.name and "request" not in receipt.name


def test_restart_replays_receipt_when_directory_fsync_failed_after_rename(
    tmp_path,
    monkeypatch,
):
    root, store = _store(tmp_path)
    expected = _commit(store, 0, 1, _name("A", "B"))
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
    _commit(
        store,
        0,
        1,
        _name("A", "B"),
        _change(
            "/story/title",
            "sha256:title-a",
            "sha256:title-b",
            before="Old",
            after="New",
        ),
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


def test_forward_generation_gap_restarts_buffer_instead_of_failing(tmp_path):
    _root, store = _store(tmp_path)
    _commit(store, 0, 1, _name("A", "B"))

    fresh = _commit(store, 5, 6, _name("X", "Y"))
    assert fresh is not None
    assert (fresh.base_generation, fresh.head_generation) == (5, 6)
    assert [item.before_hash for item in fresh.changes] == ["sha256:X"]
