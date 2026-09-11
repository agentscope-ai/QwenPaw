# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=arguments-out-of-order
"""Storage primitives: atomic JSON records, durable JSONL, locks, content store."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import errno
import os
import threading
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict
import pytest

from services.runtime_files import atomic_store as atomic_store_module
from services.runtime_files import (
    AtomicJsonRecordStore,
    CorruptRecordError,
    CrossProcessFileLock,
    DurableJsonlStore,
    FieldBlockBaseConflictError,
    FieldBlockConflictError,
    FieldBlockStore,
    JsonlCorruptionError,
    LockTimeoutError,
    RecordAlreadyExistsError,
    RecordConflictError,
    SequenceConflictError,
    pointers_overlap,
)
from services.workspace import content_store as content_store_module
from services.workspace.content_store import ContentStore


pytestmark = pytest.mark.unit


def _windows_like_open(real_open):
    def windows_like(target, flags, mode=0o777, *args, **kwargs):
        if Path(target).is_dir():
            raise PermissionError(errno.EACCES, "Permission denied", target)
        return real_open(target, flags, mode, *args, **kwargs)

    return windows_like


class DemoRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    count: int


def test_atomic_json_record_is_typed_deterministic_and_cas_guarded(tmp_path):
    path = tmp_path / "runtime" / "state.json"
    stages: list[str] = []
    store = AtomicJsonRecordStore(
        path,
        DemoRecord,
        stage_hook=lambda stage, _path: stages.append(stage),
    )

    created = store.create({"name": "before", "count": 1})
    assert created.value == DemoRecord(name="before", count=1)
    expected_text = '{\n  "count": 1,\n  "name": "before"\n}\n'
    assert path.read_text(encoding="utf-8") == expected_text
    assert stages == [
        "temp_created",
        "temp_fsynced",
        "created",
        "directory_fsynced",
    ]

    with pytest.raises(RecordAlreadyExistsError):
        store.create(DemoRecord(name="duplicate", count=2))

    updated = store.compare_and_swap(
        expected_checksum=created.checksum,
        value=DemoRecord(name="after", count=2),
    )

    with pytest.raises(RecordConflictError) as caught:
        store.compare_and_swap(
            expected_checksum=created.checksum,
            value=DemoRecord(name="stale", count=3),
        )
    assert caught.value.actual_checksum == updated.checksum
    assert store.read().name == "after"


def test_failure_before_replace_preserves_previous_complete_record(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    store = AtomicJsonRecordStore(path, DemoRecord)
    store.write(DemoRecord(name="old", count=1))

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("simulated crash before publish")

    monkeypatch.setattr(atomic_store_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="before publish"):
        store.write(DemoRecord(name="new", count=2))

    assert store.read() == DemoRecord(name="old", count=1)


def test_atomic_bytes_tolerate_windows_like_missing_fchmod_and_dir_fsync(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    monkeypatch.delattr(atomic_store_module.os, "fchmod", raising=False)
    monkeypatch.setattr(
        atomic_store_module.os,
        "open",
        _windows_like_open(os.open),
    )

    atomic_store_module.atomic_replace_bytes(path, b'{"ok":true}\n')
    assert path.read_bytes() == b'{"ok":true}\n'

    atomic_store_module.atomic_create_bytes(
        tmp_path / "created.json",
        b'{"created":true}\n',
    )
    assert (tmp_path / "created.json").read_bytes() == b'{"created":true}\n'


def test_non_standard_nonfinite_json_is_reported_as_corruption(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"name":"bad","count":NaN}\n', encoding="utf-8")

    with pytest.raises(CorruptRecordError, match="non-finite JSON"):
        AtomicJsonRecordStore(path, DemoRecord).read()


class EventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker: int
    value: int


def _append_events(path: str, worker: int, count: int) -> None:
    store = DurableJsonlStore(Path(path), EventRecord, lock_timeout_seconds=5)
    for value in range(count):
        store.append(EventRecord(worker=worker, value=value))


def test_jsonl_restart_retains_durable_sequence_and_expected_seq_cas(tmp_path):
    path = tmp_path / "events.jsonl"
    first_store = DurableJsonlStore(path, EventRecord)
    assert first_store.append(EventRecord(worker=0, value=1)).seq == 1
    first_store.append(EventRecord(worker=0, value=2), expected_next_seq=2)

    restarted = DurableJsonlStore(path, EventRecord)
    assert restarted.last_seq() == 2
    with pytest.raises(SequenceConflictError):
        restarted.append(EventRecord(worker=0, value=3), expected_next_seq=2)
    third = restarted.append(
        EventRecord(worker=0, value=3),
        expected_next_seq=3,
    )
    assert third.seq == 3
    assert [record.value for record in restarted.read_records()] == [1, 2, 3]


def test_jsonl_append_recovers_only_an_unterminated_crash_tail(tmp_path):
    path = tmp_path / "events.jsonl"
    store = DurableJsonlStore(path, EventRecord)
    store.append(EventRecord(worker=1, value=1))
    with path.open("ab") as handle:
        handle.write(b'{"seq":2,"record":{"worker":1')

    assert store.append(EventRecord(worker=1, value=2)).seq == 2
    assert [entry.seq for entry in store.read_all()] == [1, 2]
    assert path.read_bytes().endswith(b"\n")


def test_jsonl_never_skips_a_malformed_complete_line(tmp_path):
    path = tmp_path / "events.jsonl"
    store = DurableJsonlStore(path, EventRecord)
    store.append(EventRecord(worker=1, value=1))
    with path.open("ab") as handle:
        handle.write(b"not-json\n")

    with pytest.raises(JsonlCorruptionError, match="complete line 2"):
        store.append(EventRecord(worker=1, value=2))


def test_concurrent_threads_allocate_unique_contiguous_jsonl_sequences(
    tmp_path,
):
    path = tmp_path / "events.jsonl"
    threads = [
        threading.Thread(target=_append_events, args=(str(path), worker, 12))
        for worker in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    entries = DurableJsonlStore(path, EventRecord).read_all()
    assert [entry.seq for entry in entries] == list(range(1, 49))
    pairs = {(e.record["worker"], e.record["value"]) for e in entries}
    assert len(pairs) == 48


def _hold_lock(path: str, ready, release) -> None:
    with CrossProcessFileLock(path, timeout_seconds=2):
        ready.set()
        release.wait(timeout=5)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 15, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _acquire(store: FieldBlockStore, pointer: str, **overrides):
    kwargs = {
        "project_id": "project-1",
        "owner_kind": "user",
        "owner_id": "browser-1",
        "base_field_hash": "sha256:before",
        "ttl_seconds": 30,
    }
    kwargs.update(overrides)
    return store.acquire(json_pointer=pointer, **kwargs)


def test_lock_times_out_while_held_and_recovers_after_release(tmp_path):
    path = tmp_path / "project-write.lock"
    ready = threading.Event()
    release = threading.Event()
    holder = threading.Thread(
        target=_hold_lock,
        args=(str(path), ready, release),
    )
    holder.start()
    assert ready.wait(timeout=3)

    with pytest.raises(LockTimeoutError) as caught:
        with CrossProcessFileLock(
            path,
            timeout_seconds=0.05,
            poll_interval_seconds=0.005,
        ):
            pass
    assert caught.value.phase == "resource"
    assert caught.value.waiter["mode"] == "exclusive"
    assert caught.value.holder["pid"] == os.getpid()

    release.set()
    holder.join(timeout=3)
    assert not holder.is_alive()
    with CrossProcessFileLock(path, timeout_seconds=0.2):
        pass
    # In-process locks never create coordination files.
    assert not path.exists()


def test_same_thread_nested_lock_waits_then_times_out(tmp_path):
    path = tmp_path / "nested.lock"
    with CrossProcessFileLock(path):
        # Executor threads are reused across requests while a hold spans an
        # await, so same-thread re-acquisition must WAIT (not fail fast); a
        # genuine nested acquisition then surfaces as the retryable timeout.
        with pytest.raises(LockTimeoutError):
            with CrossProcessFileLock(path, timeout_seconds=0.2):
                pass


def test_cross_thread_release_clears_the_acquiring_threads_owner(tmp_path):
    path = tmp_path / "cross-thread-release.lock"
    first = CrossProcessFileLock(path)
    acquired = threading.Event()
    reacquire = threading.Event()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            first.acquire()
            acquired.set()
            reacquire.wait(timeout=1)
            with CrossProcessFileLock(path, timeout_seconds=0.1):
                pass
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    assert acquired.wait(timeout=1)
    first.release()
    reacquire.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert not errors


def test_detached_acquire_does_not_poison_the_reused_executor_thread(
    tmp_path,
):
    """Regression: exclusive lock acquired via ``asyncio.to_thread``.

    A coroutine that acquires the Project lifecycle lock with
    ``await asyncio.to_thread(lock.acquire_detached)`` keeps holding it
    across awaits while the worker thread returns to the pool.  A shared
    poll read (for example SSE ``list_events``) scheduled onto that reused
    thread must wait on the lock like any other reader — not explode with
    the same-thread nested-acquisition guard.
    """

    path = tmp_path / "detached.lock"
    owner = CrossProcessFileLock(path)
    outcomes: list[object] = []
    held = threading.Event()
    released = threading.Event()

    def executor_thread() -> None:
        try:
            # Simulates ``await asyncio.to_thread(lock.acquire_detached)``:
            # the acquiring pooled thread immediately moves on to other work.
            owner.acquire_detached()
            held.set()
            # The reused thread now runs an unrelated shared read while the
            # coroutine still holds the exclusive lock: it must block and
            # time out on the file lock, not trip the nesting guard.
            try:
                with CrossProcessFileLock(
                    path,
                    timeout_seconds=0.05,
                    poll_interval_seconds=0.005,
                    shared=True,
                ):
                    outcomes.append("read-acquired-while-exclusive-held")
            except LockTimeoutError:
                outcomes.append("read-timed-out-while-exclusive-held")
            assert released.wait(timeout=2)
            with CrossProcessFileLock(
                path,
                timeout_seconds=1,
                poll_interval_seconds=0.005,
                shared=True,
            ):
                outcomes.append("read-acquired-after-release")
        except BaseException as error:  # pragma: no cover - asserted below
            outcomes.append(error)

    thread = threading.Thread(target=executor_thread)
    thread.start()
    assert held.wait(timeout=2)
    deadline = time.monotonic() + 2
    while not outcomes and time.monotonic() < deadline:
        time.sleep(0.005)
    # Release from a different thread, like the event-loop coroutine does.
    owner.release()
    released.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert outcomes == [
        "read-timed-out-while-exclusive-held",
        "read-acquired-after-release",
    ]


def test_store_operations_create_no_lock_artifacts_on_disk(tmp_path):
    record_path = tmp_path / "record.json"
    store = AtomicJsonRecordStore(record_path)
    store.write({"value": 1})
    store.update(lambda value: {"value": value["value"] + 1})
    stream = DurableJsonlStore(tmp_path / "events.jsonl", EventRecord)
    stream.append(EventRecord(worker=1, value=1))
    with CrossProcessFileLock(tmp_path / "domain.lock"):
        pass

    leftovers = [
        entry.name
        for entry in tmp_path.rglob("*")
        if ".lock" in entry.name
        or entry.name.endswith(".gate")
        or entry.name.endswith(".readers")
    ]
    assert leftovers == []


def test_writer_blocked_by_shared_holder_times_out(tmp_path):
    path = tmp_path / "reader-owner.lock"
    reader = CrossProcessFileLock(path, shared=True).acquire()
    failures: list[LockTimeoutError] = []

    def writer() -> None:
        try:
            with CrossProcessFileLock(path, timeout_seconds=0.05):
                pass
        except LockTimeoutError as error:
            failures.append(error)

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    writer_thread.join(timeout=1)
    reader.release()

    assert failures and failures[0].phase == "resource"


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("", "/story", True),
        ("/story/title", "/story/title", True),
        ("/story/1", "/story/10", False),
        ("/a~1b", "/a/b", False),
        ("/a~1b", "/a~1b/title", True),
    ],
)
def test_json_pointer_overlap_is_segment_aware(first, second, expected):
    assert pointers_overlap(first, second) is expected
    assert pointers_overlap(second, first) is expected


def test_field_blocks_conflict_on_ancestor_and_expire_by_ttl(tmp_path):
    clock = MutableClock()
    store = FieldBlockStore(tmp_path / "fields", clock=clock)
    base = "/timelines/items/timeline:main/elements_by_id"
    title = _acquire(store, f"{base}/element-1", ttl_seconds=5)

    with pytest.raises(FieldBlockConflictError) as caught:
        _acquire(
            store,
            f"{base}/element-1/label",
            owner_kind="agent",
            owner_id="run-1",
            ttl_seconds=5,
        )
    assert caught.value.block.block_id == title.block_id

    sibling = _acquire(
        store,
        f"{base}/element-10/label",
        owner_kind="agent",
        owner_id="run-1",
        base_field_hash="sha256:other",
        ttl_seconds=5,
    )
    assert len(store.list_active(project_id="project-1")) == 2

    clock.value += timedelta(seconds=6)
    assert set(store.cleanup_expired()) == {title.block_id, sibling.block_id}
    assert store.list_active() == []


def test_field_block_release_is_idempotent_after_valid_release(tmp_path):
    store = FieldBlockStore(tmp_path / "fields")
    block = _acquire(store, "/strategy/title")
    assert store.release(block.block_id, token=block.token) is True
    assert store.release(block.block_id, token=block.token) is False


def test_field_block_base_is_checked_under_index_lock(tmp_path):
    store = FieldBlockStore(tmp_path / "fields")

    with pytest.raises(FieldBlockBaseConflictError) as caught:
        _acquire(
            store,
            "/name",
            base_field_hash="sha256:old",
            current_field_hash=lambda: "sha256:new",
        )

    assert caught.value.actual == "sha256:new"
    assert store.list_active() == []


def test_guard_write_rejects_overlap_unless_token_owns_block(tmp_path):
    store = FieldBlockStore(tmp_path / "fields")
    block = _acquire(store, "/story")

    with pytest.raises(FieldBlockConflictError):
        with store.guard_write(
            project_id="project-1",
            json_pointers=["/story/title"],
        ):
            pass

    with store.guard_write(
        project_id="project-1",
        json_pointers=["/story/title"],
        token=block.token,
    ):
        pass


def test_content_store_tolerates_windows_like_private_file_surface(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delattr(atomic_store_module.os, "fchmod", raising=False)
    monkeypatch.setattr(
        content_store_module.os,
        "open",
        _windows_like_open(os.open),
    )

    store = ContentStore(tmp_path)
    stored = store.put_bytes(b"creator-content")

    assert stored.path.read_bytes() == b"creator-content"
    assert stored.size == len(b"creator-content")


# ── Conflict regressions for the historical lock incidents ──────────────


def test_hammering_readers_never_starve_or_slow_a_writer(tmp_path):
    """The「停止按钮永远转圈」class: reads must not contend with writes."""

    stream = DurableJsonlStore(tmp_path / "events.jsonl", EventRecord)
    record = AtomicJsonRecordStore(tmp_path / "session.json")
    record.write({"status": "IDLE", "revision": 0})
    stop = threading.Event()
    reader_errors: list[BaseException] = []
    read_counts = [0] * 6

    def reader(index: int) -> None:
        while not stop.is_set():
            try:
                stream.read_all()
                stream.read_records_after(0, limit=20)
                stream.last_seq()
                value = record.read_or_none()
                assert value is None or isinstance(value["revision"], int)
                read_counts[index] += 1
            except BaseException as error:  # pragma: no cover - asserted
                reader_errors.append(error)
                return

    threads = [
        threading.Thread(target=reader, args=(index,)) for index in range(6)
    ]
    for thread in threads:
        thread.start()
    try:
        started = time.monotonic()
        for value in range(1, 201):
            stream.append(EventRecord(worker=0, value=value))
            record.update(
                lambda current: {
                    "status": "RUNNING",
                    "revision": current["revision"] + 1,
                },
            )
        writer_elapsed = time.monotonic() - started
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
    assert not reader_errors
    # Before the redesign every read also took the write lock, and a single
    # writer routinely hit the 10s timeout under this pressure.
    assert writer_elapsed < 20.0
    assert [e.seq for e in stream.read_all()] == list(range(1, 201))
    assert record.read()["revision"] == 200
    assert all(count > 0 for count in read_counts)


def test_concurrent_updates_to_one_record_lose_nothing(tmp_path):
    """Mutual exclusion of the in-process per-path lock: no lost updates."""

    record = AtomicJsonRecordStore(tmp_path / "counter.json")
    record.write({"value": 0})
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(40):
                record.update(lambda current: {"value": current["value"] + 1})
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors
    assert record.read()["value"] == 200


def test_shared_holders_overlap_and_exclude_the_exclusive_side(tmp_path):
    """Runtime writers share the lifecycle lock; delete/commit waits."""

    path = tmp_path / "project-lifecycle.lock"
    first_in = threading.Event()
    second_in = threading.Event()
    release_shared = threading.Event()
    order: list[str] = []

    def shared_holder(name: str, entered: threading.Event) -> None:
        with CrossProcessFileLock(path, shared=True, timeout_seconds=5):
            entered.set()
            release_shared.wait(timeout=5)
            order.append(f"{name}-released")

    def exclusive_writer() -> None:
        with CrossProcessFileLock(path, timeout_seconds=5):
            order.append("exclusive-acquired")

    holders = [
        threading.Thread(target=shared_holder, args=("a", first_in)),
        threading.Thread(target=shared_holder, args=("b", second_in)),
    ]
    for thread in holders:
        thread.start()
    assert first_in.wait(timeout=2)
    assert second_in.wait(timeout=2)
    writer = threading.Thread(target=exclusive_writer)
    writer.start()
    time.sleep(0.05)
    assert "exclusive-acquired" not in order
    release_shared.set()
    writer.join(timeout=5)
    for thread in holders:
        thread.join(timeout=5)
    assert order[-1] == "exclusive-acquired"


def test_torn_crash_tail_never_breaks_lockfree_readers(tmp_path):
    """A crash fragment is invisible to readers and repaired by append."""

    path = tmp_path / "events.jsonl"
    stream = DurableJsonlStore(path, EventRecord)
    for value in range(1, 4):
        stream.append(EventRecord(worker=1, value=value))
    with path.open("ab") as handle:
        handle.write(b'{"seq":4,"record":{"worker":1')

    errors: list[BaseException] = []

    def reader() -> None:
        try:
            for _ in range(50):
                assert [e.seq for e in stream.read_all()] == [1, 2, 3]
                assert stream.last_seq() == 3
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    # Reads never truncated the fragment; only the next append repairs it.
    assert not path.read_bytes().endswith(b"\n")
    assert stream.append(EventRecord(worker=1, value=4)).seq == 4
    assert [e.seq for e in stream.read_all()] == [1, 2, 3, 4]
