# -*- coding: utf-8 -*-
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, ConfigDict
import pytest

from services.runtime_files import (
    AtomicJsonRecordStore,
    CorruptRecordError,
    RecordAlreadyExistsError,
    RecordConflictError,
)


pytestmark = pytest.mark.unit


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
    assert (
        path.read_text(encoding="utf-8")
        == '{\n  "count": 1,\n  "name": "before"\n}\n'
    )
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
    assert store.read() == DemoRecord(name="after", count=2)

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

    monkeypatch.setattr(
        "services.runtime_files.atomic_store.os.replace",
        fail_replace,
    )
    with pytest.raises(OSError, match="before publish"):
        store.write(DemoRecord(name="new", count=2))

    assert store.read() == DemoRecord(name="old", count=1)
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_concurrent_record_cas_allows_exactly_one_writer(tmp_path):
    path = tmp_path / "state.json"
    initial = AtomicJsonRecordStore(path, DemoRecord).write(
        DemoRecord(name="initial", count=0),
    )

    def replace(count: int) -> str:
        store = AtomicJsonRecordStore(path, DemoRecord)
        try:
            return store.compare_and_swap(
                expected_checksum=initial.checksum,
                value=DemoRecord(name=f"writer-{count}", count=count),
            ).value.name
        except RecordConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(replace, (1, 2)))

    assert outcomes.count("conflict") == 1
    assert AtomicJsonRecordStore(path, DemoRecord).read().name in {
        "writer-1",
        "writer-2",
    }


def test_failure_before_create_publish_never_exposes_partial_target(tmp_path):
    path = tmp_path / "record.json"

    def crash(stage: str, _path: Path) -> None:
        if stage == "temp_fsynced":
            raise RuntimeError("simulated crash")

    store = AtomicJsonRecordStore(path, DemoRecord, stage_hook=crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.create(DemoRecord(name="not-published", count=1))

    assert not path.exists()
    assert not list(tmp_path.glob(".record.json.*.tmp"))


def test_non_standard_nonfinite_json_is_reported_as_corruption(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"name":"bad","count":NaN}\n', encoding="utf-8")

    with pytest.raises(CorruptRecordError, match="non-finite JSON"):
        AtomicJsonRecordStore(path, DemoRecord).read()
