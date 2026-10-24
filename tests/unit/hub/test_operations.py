# -*- coding: utf-8 -*-
"""Tests for lightweight Hub telemetry and audit storage."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.hub import operations

from qwenpaw.hub.operations import HubOperationsStore


def test_audit_pages_filter_and_preserve_structured_details(
    tmp_path: Path,
) -> None:
    store = HubOperationsStore(tmp_path / "control.db", tmp_path)
    for index in range(3):
        store.record(
            actor_user_id="user-a",
            actor_username="owner",
            action="runtime.start" if index < 2 else "runtime.stop",
            resource_type="runtime",
            resource_id=f"runtime-{index}",
            detail={"index": index},
        )

    events, total = store.list_events(
        page=1,
        page_size=1,
        action="runtime.start",
    )

    assert total == 2
    assert len(events) == 1
    assert events[0]["detail"] in ({"index": 0}, {"index": 1})
    assert events[0]["actor_username"] == "owner"


def test_host_metrics_use_data_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "user-data"
    data_root.mkdir()
    store = HubOperationsStore(tmp_path / "control.db", data_root)
    sampled_paths = []

    def disk_usage(path):
        sampled_paths.append(path)
        return SimpleNamespace(total=1000, used=900, free=80, percent=91.8)

    monkeypatch.setattr(operations.psutil, "disk_usage", disk_usage)
    monkeypatch.setattr(
        operations.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            total=100,
            used=40,
            available=55,
            percent=45,
        ),
    )
    metrics = store.host_metrics()
    assert sampled_paths == [str(data_root.resolve())]
    assert metrics["disk_path"] == str(data_root.resolve())
    assert metrics["disk_used"] == 900
    assert metrics["disk_total"] == 1000
    assert metrics["disk_free"] == 80
    assert metrics["memory_available"] == 55
