# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for qwenpaw.app.inbox_store.

Real file IO through a monkeypatched ``_INBOX_PATH`` -- no over-mocking.
Covers: append_event, list_events filters/pagination, mark_read,
mark_all_read, delete_event (incl. run_id reference tracking), and the
5000-event cap.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.app import inbox_store

# p0: critical user flows (CRUD, pagination, mark_read); p2: error paths
pytestmark = [
    pytest.mark.unit,
    pytest.mark.p0,
]


@pytest.fixture
def inbox_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module-level _INBOX_PATH to a tmp file."""
    target = tmp_path / "inbox_events.json"
    monkeypatch.setattr(inbox_store, "_INBOX_PATH", target)
    return target


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_event_creates_file_and_returns_event(inbox_path: Path):
    event = await inbox_store.append_event(
        agent_id="agent-1",
        source_type="cron",
        source_id="job-1",
        event_type="dispatch",
        status="success",
        title="Job ran",
        body="ok",
    )
    assert inbox_path.exists()
    data = json.loads(inbox_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == event["id"]
    assert event["agent_id"] == "agent-1"
    assert event["read"] is False
    assert event["severity"] == "info"
    assert event["payload"] == {}


@pytest.mark.asyncio
async def test_append_event_defaults_agent_id(inbox_path: Path):
    event = await inbox_store.append_event(
        agent_id=None,
        source_type="manual",
        source_id=None,
        event_type="note",
        status="info",
        title="t",
        body="b",
    )
    assert event["agent_id"] == "default"
    assert event["source_id"] == ""


@pytest.mark.asyncio
async def test_append_event_prepends_newest_first(inbox_path: Path):
    await inbox_store.append_event(
        agent_id="a",
        source_type="t",
        source_id="1",
        event_type="e",
        status="ok",
        title="first",
        body="b",
    )
    await inbox_store.append_event(
        agent_id="a",
        source_type="t",
        source_id="2",
        event_type="e",
        status="ok",
        title="second",
        body="b",
    )
    events = await inbox_store.list_events(limit=10)
    assert len(events) == 2
    assert events[0]["source_id"] == "2"
    assert events[1]["source_id"] == "1"


@pytest.mark.asyncio
async def test_append_event_carries_payload(inbox_path: Path):
    payload = {"run_id": "run-xyz", "extra": [1, 2, 3]}
    event = await inbox_store.append_event(
        agent_id="a",
        source_type="t",
        source_id="1",
        event_type="e",
        status="ok",
        title="t",
        body="b",
        payload=payload,
    )
    assert event["payload"] == payload


# ---------------------------------------------------------------------------
# list_events: filters + pagination
# ---------------------------------------------------------------------------


async def _seed_events(inbox_path: Path) -> None:
    """Seed a mix of events for filter tests."""
    await inbox_store.append_event(
        agent_id="A",
        source_type="cron",
        source_id="1",
        event_type="dispatch",
        status="success",
        title="t1",
        body="b",
    )
    await inbox_store.append_event(
        agent_id="B",
        source_type="manual",
        source_id="2",
        event_type="note",
        status="pending",
        title="t2",
        body="b",
    )
    await inbox_store.append_event(
        agent_id="A",
        source_type="cron",
        source_id="3",
        event_type="dispatch",
        status="error",
        title="t3",
        body="b",
    )


@pytest.mark.asyncio
async def test_list_events_filter_by_source_type(inbox_path: Path):
    await _seed_events(inbox_path)
    events = await inbox_store.list_events(source_type="cron")
    assert len(events) == 2
    assert all(e["source_type"] == "cron" for e in events)


@pytest.mark.asyncio
async def test_list_events_filter_by_status(inbox_path: Path):
    await _seed_events(inbox_path)
    events = await inbox_store.list_events(status="error")
    assert len(events) == 1
    assert events[0]["status"] == "error"


@pytest.mark.asyncio
async def test_list_events_filter_by_agent_id(inbox_path: Path):
    await _seed_events(inbox_path)
    events = await inbox_store.list_events(agent_id="A")
    assert len(events) == 2
    assert all(e["agent_id"] == "A" for e in events)


@pytest.mark.asyncio
async def test_list_events_unread_only(inbox_path: Path):
    await _seed_events(inbox_path)
    # Mark the first (newest) as read.
    events = await inbox_store.list_events(limit=1)
    await inbox_store.mark_read([events[0]["id"]])

    unread = await inbox_store.list_events(unread_only=True)
    assert len(unread) == 2
    assert all(not e["read"] for e in unread)


@pytest.mark.asyncio
async def test_list_events_pagination(inbox_path: Path):
    await _seed_events(inbox_path)
    page1 = await inbox_store.list_events(limit=2, offset=0)
    page2 = await inbox_store.list_events(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert page1[0]["source_id"] == "3"  # newest first
    assert page2[0]["source_id"] == "1"


@pytest.mark.asyncio
async def test_list_events_empty_when_no_file(inbox_path: Path):
    events = await inbox_store.list_events()
    assert events == []


@pytest.mark.asyncio
async def test_list_events_handles_non_list_json(inbox_path: Path):
    """Valid JSON that isn't a list → returns [] via the isinstance
    guard (not the except branch)."""
    inbox_path.write_text("not a json list", encoding="utf-8")
    events = await inbox_store.list_events()
    assert events == []


@pytest.mark.asyncio
async def test_list_events_handles_malformed_json(
    inbox_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Genuinely malformed JSON → caught by the except branch, returns [],
    and logs a warning (so permission/disk errors aren't silently
    swallowed). Regression for the #5809 review feedback."""
    inbox_path.write_text("{bad", encoding="utf-8")
    with caplog.at_level("WARNING"):
        events = await inbox_store.list_events()
    assert events == []
    assert any("Failed to load" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# mark_read / mark_all_read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_read_returns_count_of_newly_read(inbox_path: Path):
    await _seed_events(inbox_path)
    events = await inbox_store.list_events(limit=2)
    updated = await inbox_store.mark_read([events[0]["id"], events[1]["id"]])
    assert updated == 2


@pytest.mark.asyncio
async def test_mark_read_idempotent(inbox_path: Path):
    await _seed_events(inbox_path)
    events = await inbox_store.list_events(limit=1)
    first = await inbox_store.mark_read([events[0]["id"]])
    second = await inbox_store.mark_read([events[0]["id"]])
    assert first == 1
    assert second == 0


@pytest.mark.asyncio
async def test_mark_read_empty_list_returns_zero(inbox_path: Path):
    assert await inbox_store.mark_read([]) == 0


@pytest.mark.asyncio
async def test_mark_all_read(inbox_path: Path):
    await _seed_events(inbox_path)
    updated = await inbox_store.mark_all_read()
    assert updated == 3
    # Second call is idempotent.
    assert await inbox_store.mark_all_read() == 0


# ---------------------------------------------------------------------------
# delete_event (with run_id reference tracking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_event_returns_false_for_empty_id(inbox_path: Path):
    deleted, run_id, still_ref = await inbox_store.delete_event("")
    assert (deleted, run_id, still_ref) == (False, None, False)


@pytest.mark.asyncio
async def test_delete_event_removes_event(inbox_path: Path):
    await _seed_events(inbox_path)
    events = await inbox_store.list_events(limit=1)
    deleted, _, _ = await inbox_store.delete_event(events[0]["id"])
    assert deleted is True
    remaining = await inbox_store.list_events()
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_delete_event_returns_false_for_missing_id(inbox_path: Path):
    deleted, run_id, still_ref = await inbox_store.delete_event("ghost-id")
    assert (deleted, run_id, still_ref) == (False, None, False)


@pytest.mark.asyncio
async def test_delete_event_tracks_run_id_reference(inbox_path: Path):
    """Two events share the same run_id. Deleting one should report that
    the run_id is still referenced by the other event."""
    await inbox_store.append_event(
        agent_id="a",
        source_type="t",
        source_id="1",
        event_type="e",
        status="ok",
        title="t",
        body="b",
        payload={"run_id": "run-shared"},
    )
    await inbox_store.append_event(
        agent_id="a",
        source_type="t",
        source_id="2",
        event_type="e",
        status="ok",
        title="t",
        body="b",
        payload={"run_id": "run-shared"},
    )
    events = await inbox_store.list_events(limit=1)
    deleted, run_id, still_ref = await inbox_store.delete_event(
        events[0]["id"],
    )
    assert deleted is True
    assert run_id == "run-shared"
    assert still_ref is True


@pytest.mark.asyncio
async def test_delete_event_run_id_not_referenced_after_last(inbox_path: Path):
    await inbox_store.append_event(
        agent_id="a",
        source_type="t",
        source_id="1",
        event_type="e",
        status="ok",
        title="t",
        body="b",
        payload={"run_id": "run-solo"},
    )
    events = await inbox_store.list_events(limit=1)
    deleted, run_id, still_ref = await inbox_store.delete_event(
        events[0]["id"],
    )
    assert deleted is True
    assert run_id == "run-solo"
    assert still_ref is False


# ---------------------------------------------------------------------------
# 5000-event cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_event_caps_at_max(
    inbox_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The event list is trimmed to _MAX_EVENTS, keeping the newest.

    append_event does ``events.insert(0, event); del events[_MAX_EVENTS:]``
    on every call, and _save_events re-serializes the whole list — so a
    test that appends ``_MAX_EVENTS + 50`` (5050) times is O(n^2) and
    takes ~160s, which tips over CI's --timeout=300 under parallel load.

    monkeypatch a small cap so the trim is exercised in O(1): append one
    past the cap and confirm the list is capped and the oldest is dropped.
    """
    small_cap = 5
    monkeypatch.setattr(inbox_store, "_MAX_EVENTS", small_cap)

    for i in range(small_cap + 2):
        await inbox_store.append_event(
            agent_id="a",
            source_type="t",
            source_id=str(i),
            event_type="e",
            status="ok",
            title="t",
            body="b",
        )

    events = await inbox_store.list_events(limit=small_cap + 100)
    assert len(events) == small_cap
    # newest-first: the last two appended (indices small_cap+1, small_cap)
    # survived; the oldest two (0, 1) were trimmed off the tail.
    assert events[0]["source_id"] == str(small_cap + 1)
    assert events[-1]["source_id"] == str(2)
    assert str(0) not in {e["source_id"] for e in events}
    assert str(1) not in {e["source_id"] for e in events}


# ---------------------------------------------------------------------------
# large payload write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_event_large_payload_round_trips(inbox_path: Path):
    big_payload = {"k": "v" * 50_000}
    event = await inbox_store.append_event(
        agent_id="a",
        source_type="t",
        source_id="1",
        event_type="e",
        status="ok",
        title="t",
        body="b",
        payload=big_payload,
    )
    assert len(event["payload"]["k"]) == 50_000

    events = await inbox_store.list_events(limit=1)
    assert len(events[0]["payload"]["k"]) == 50_000
