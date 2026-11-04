# -*- coding: utf-8 -*-
"""Tests for the stale daily-note reminder tool."""

from __future__ import annotations

import os
import time
from datetime import date, timedelta

import pytest

from qwenpaw.agents.tools import stale_notes


class _FakeConfig:
    class _Reme:
        daily_dir = "memory"

    running = type("Running", (), {"reme_light_memory_config": _Reme()})


class _FakeInbox:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def append(self, **kwargs):
        event = dict(kwargs)
        event["id"] = str(len(self.events))
        event["read"] = False
        event["created_at"] = time.time()
        self.events.insert(0, event)
        return event

    async def list(self, **kwargs):
        events = list(self.events)
        if kwargs.get("unread_only"):
            events = [event for event in events if not event["read"]]
        return events


@pytest.fixture()
def notes_env(tmp_path, monkeypatch):
    """Point the tool at a temporary workspace with a fake Inbox."""
    root = tmp_path / "memory"
    root.mkdir()
    inbox = _FakeInbox()
    monkeypatch.setattr(
        stale_notes,
        "get_current_workspace_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        stale_notes,
        "load_agent_config",
        lambda _aid: _FakeConfig(),
    )
    monkeypatch.setattr(stale_notes, "get_current_agent_id", lambda: "tester")
    monkeypatch.setattr(stale_notes, "append_event", inbox.append)
    monkeypatch.setattr(stale_notes, "list_events", inbox.list)
    return root, inbox


def _write_note(root, day: date, slug: str, status: str | None = None) -> None:
    folder = root / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    text = "# note\n"
    if status is not None:
        text = f"---\nstatus: {status}\n---\n\n# note\n"
    (folder / f"{slug}.md").write_text(text, encoding="utf-8")


def _text(chunk) -> str:
    return (
        chunk.content[0]["text"]
        if isinstance(chunk.content[0], dict)
        else chunk.content[0].text
    )


async def test_pending_note_is_reported(notes_env):
    root, inbox = notes_env
    old = date.today() - timedelta(days=10)
    _write_note(root, old, "alpha")

    chunk = await stale_notes.check_stale_notes()

    assert "1 stale daily note(s)" in _text(chunk)
    assert len(inbox.events) == 1
    event = inbox.events[0]
    assert event["source_type"] == "stale_notes"
    assert event["payload"]["key"] == f"{old.isoformat()}/alpha.md"
    assert event["payload"]["age_days"] == 10


async def test_recent_note_is_ignored(notes_env):
    root, inbox = notes_env
    _write_note(root, date.today() - timedelta(days=2), "fresh")

    chunk = await stale_notes.check_stale_notes(days=7)

    assert "No stale daily notes" in _text(chunk)
    assert inbox.events == []


async def test_resolved_notes_are_ignored(notes_env):
    root, inbox = notes_env
    old = date.today() - timedelta(days=30)
    _write_note(root, old, "done", status="completed")
    _write_note(root, old, "skipped", status="skipped")

    chunk = await stale_notes.check_stale_notes()

    assert "No stale daily notes" in _text(chunk)
    assert inbox.events == []


async def test_unknown_status_is_not_reported(notes_env):
    root, inbox = notes_env
    _write_note(
        root,
        date.today() - timedelta(days=30),
        "odd",
        status="archived",
    )

    await stale_notes.check_stale_notes()

    assert inbox.events == []


async def test_path_date_wins_over_fresh_mtime(notes_env):
    root, inbox = notes_env
    old = date.today() - timedelta(days=20)
    _write_note(root, old, "path-dated")
    for path in root.glob("*/*.md"):
        os.utime(path, None)  # mtime = now

    await stale_notes.check_stale_notes()

    assert len(inbox.events) == 1
    assert inbox.events[0]["payload"]["age_days"] == 20


async def test_mtime_is_used_when_path_has_no_date(notes_env):
    root, inbox = notes_env
    folder = root / "loose"
    folder.mkdir()
    note = folder / "undated.md"
    note.write_text("# note\n", encoding="utf-8")
    stale = time.time() - 40 * 86400
    os.utime(note, (stale, stale))

    await stale_notes.check_stale_notes()

    assert len(inbox.events) == 1
    assert inbox.events[0]["payload"]["age_days"] >= 39


async def test_dedupe_across_runs(notes_env):
    root, inbox = notes_env
    _write_note(root, date.today() - timedelta(days=10), "repeat")

    await stale_notes.check_stale_notes()
    await stale_notes.check_stale_notes()

    assert len(inbox.events) == 1


async def test_dry_run_pushes_nothing(notes_env):
    root, inbox = notes_env
    _write_note(root, date.today() - timedelta(days=10), "preview")

    chunk = await stale_notes.check_stale_notes(dry_run=True)

    assert "would push 1" in _text(chunk)
    assert inbox.events == []


async def test_read_event_still_suppressed_within_cooldown(notes_env):
    root, inbox = notes_env
    _write_note(root, date.today() - timedelta(days=10), "again")

    await stale_notes.check_stale_notes()
    inbox.events[0]["read"] = True
    await stale_notes.check_stale_notes()

    assert len(inbox.events) == 1


async def test_renotify_after_cooldown_expires(notes_env):
    root, inbox = notes_env
    _write_note(root, date.today() - timedelta(days=10), "later")

    await stale_notes.check_stale_notes()
    inbox.events[0]["created_at"] -= 8 * 86400
    await stale_notes.check_stale_notes()

    assert len(inbox.events) == 2


async def test_invalid_params_fall_back_to_defaults(notes_env):
    root, inbox = notes_env
    _write_note(root, date.today() - timedelta(days=10), "clamp")

    await stale_notes.check_stale_notes(
        days="oops",
        limit=0,
        cooldown_days="bad",
    )

    assert len(inbox.events) == 1


async def test_cooldown_zero_falls_back_to_unread_only(notes_env):
    root, inbox = notes_env
    _write_note(root, date.today() - timedelta(days=10), "nocooldown")

    await stale_notes.check_stale_notes(cooldown_days=0)
    inbox.events[0]["read"] = True
    await stale_notes.check_stale_notes(cooldown_days=0)

    assert len(inbox.events) == 2
