# -*- coding: utf-8 -*-
"""Tests for console_push_store — expired message filtering."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from copaw.app.console_push_store import (
    _list,
    _MAX_AGE_SECONDS,
    append,
    get_recent,
    take,
    take_all,
)


@pytest.fixture(autouse=True)
def _clear_store():
    """Ensure the global store is empty before and after each test."""
    _list.clear()
    yield
    _list.clear()


# ── helpers ──────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _inject_expired(session_id: str = "s1", age: int = _MAX_AGE_SECONDS + 10):
    """Insert a message that is already expired."""
    _list.append(
        {
            "id": "expired-msg",
            "text": "old",
            "ts": time.time() - age,
            "session_id": session_id,
        }
    )


# ── take() ───────────────────────────────────────────────────────────

def test_take_returns_fresh_messages():
    _run(append("s1", "hello"))
    msgs = _run(take("s1"))
    assert len(msgs) == 1
    assert msgs[0]["text"] == "hello"


def test_take_drops_expired_messages():
    _inject_expired("s1")
    _run(append("s1", "fresh"))

    msgs = _run(take("s1"))
    texts = [m["text"] for m in msgs]

    assert "fresh" in texts
    assert "old" not in texts, "take() must not return expired messages"


def test_take_cleans_expired_from_other_sessions():
    """Expired messages from *other* sessions should also be pruned."""
    _inject_expired("s2")
    _run(append("s1", "mine"))

    _run(take("s1"))
    # The store should no longer contain the expired s2 message.
    assert len(_list) == 0


# ── take_all() ───────────────────────────────────────────────────────

def test_take_all_returns_fresh_messages():
    _run(append("s1", "a"))
    _run(append("s2", "b"))
    msgs = _run(take_all())
    assert len(msgs) == 2


def test_take_all_drops_expired_messages():
    _inject_expired("s1")
    _run(append("s1", "fresh"))

    msgs = _run(take_all())
    texts = [m["text"] for m in msgs]

    assert "fresh" in texts
    assert "old" not in texts, "take_all() must not return expired messages"


# ── get_recent() (existing behaviour, regression guard) ──────────────

def test_get_recent_only_returns_fresh():
    _inject_expired("s1")
    _run(append("s1", "new"))

    msgs = _run(get_recent())
    assert len(msgs) == 1
    assert msgs[0]["text"] == "new"
