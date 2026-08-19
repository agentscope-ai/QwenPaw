# -*- coding: utf-8 -*-
"""Tests for lightweight Hub telemetry and audit storage."""

from pathlib import Path

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


def test_host_metrics_are_bounded_percentages(tmp_path: Path) -> None:
    store = HubOperationsStore(tmp_path / "control.db", tmp_path)

    metrics = store.host_metrics()

    assert set(metrics) == {
        "cpu_percent",
        "memory_percent",
        "disk_percent",
    }
    assert all(0 <= value <= 100 for value in metrics.values())
