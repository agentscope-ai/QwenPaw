# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

from pydantic import BaseModel, ConfigDict
import pytest

from services.runtime_files import (
    DurableJsonlStore,
    JsonlCorruptionError,
    SequenceConflictError,
)


pytestmark = pytest.mark.unit


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
    assert (
        first_store.append(
            EventRecord(worker=0, value=2),
            expected_next_seq=2,
        ).seq
        == 2
    )

    restarted = DurableJsonlStore(path, EventRecord)
    assert restarted.last_seq() == 2
    with pytest.raises(SequenceConflictError):
        restarted.append(EventRecord(worker=0, value=3), expected_next_seq=2)
    assert (
        restarted.append(
            EventRecord(worker=0, value=3),
            expected_next_seq=3,
        ).seq
        == 3
    )
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


def test_jsonl_normal_append_reads_only_the_durable_tail(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "events.jsonl"
    store = DurableJsonlStore(path, EventRecord)
    store.append(EventRecord(worker=1, value=1))

    def unexpected_full_recovery():
        raise AssertionError(
            "normal append must not rescan the full JSONL stream",
        )

    monkeypatch.setattr(store, "_recover_unlocked", unexpected_full_recovery)

    assert store.append(EventRecord(worker=1, value=2)).seq == 2


def test_jsonl_never_skips_a_malformed_complete_line(tmp_path):
    path = tmp_path / "events.jsonl"
    store = DurableJsonlStore(path, EventRecord)
    store.append(EventRecord(worker=1, value=1))
    with path.open("ab") as handle:
        handle.write(b"not-json\n")

    with pytest.raises(JsonlCorruptionError, match="complete line 2"):
        store.append(EventRecord(worker=1, value=2))


def test_concurrent_processes_allocate_unique_contiguous_jsonl_sequences(
    tmp_path,
):
    path = tmp_path / "events.jsonl"
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(target=_append_events, args=(str(path), worker, 12))
        for worker in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    entries = DurableJsonlStore(path, EventRecord).read_all()
    assert [entry.seq for entry in entries] == list(range(1, 49))
    pairs = {
        (entry.record["worker"], entry.record["value"]) for entry in entries
    }
    assert len(pairs) == 48


def test_jsonl_file_is_plain_one_object_per_line(tmp_path):
    path = tmp_path / "events.jsonl"
    store = DurableJsonlStore(path, EventRecord)
    store.append(EventRecord(worker=2, value=7))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["seq"] == 1


def test_jsonl_read_records_after_cursor_only_reads_the_tail(tmp_path):
    path = tmp_path / "events.jsonl"
    store = DurableJsonlStore(path, EventRecord)
    count = 600
    for value in range(count):
        store.append(EventRecord(worker=0, value=value))
    total_size = path.stat().st_size
    assert total_size > 8192  # spans multiple read blocks

    read_bytes = {"n": 0}

    class CountingPath(type(path)):
        def open(self, *args, **kwargs):
            handle = super().open(*args, **kwargs)
            real_read = handle.read

            def read(size=-1):
                data = real_read(size)
                read_bytes["n"] += len(data)
                return data

            handle.read = read
            return handle

    store.path = CountingPath(path)

    # seq is 1-indexed, value 0-indexed: after_seq=590 -> seq 591..600.
    records = store.read_records_after(after_seq=count - 10)
    assert [r.value for r in records] == list(range(count - 10, count))
    # The cursor sits near the tail, so the lazy reverse reader must stop after
    # one or two blocks instead of reading the whole stream back to offset 0.
    assert read_bytes["n"] < total_size / 2
