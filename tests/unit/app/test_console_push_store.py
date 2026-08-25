# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for console_push_store.

Tests the in-memory push store: append, take, take_all, _strip_ts.
All functions are async — use pytest-asyncio.
"""
from __future__ import annotations

import pytest

import qwenpaw.app.console_push_store as store


@pytest.fixture(autouse=True)
def _reset():
    """Clear the global push store before each test."""
    store._list.clear()
    yield
    store._list.clear()


# ---------------------------------------------------------------------------
# append + take
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_and_take():
    await store.append("sess-1", "Hello")
    msgs = await store.take("sess-1")
    assert len(msgs) == 1
    assert msgs[0]["text"] == "Hello"


@pytest.mark.asyncio
async def test_take_clears_queue():
    await store.append("sess-1", "Msg")
    first = await store.take("sess-1")
    assert len(first) == 1
    second = await store.take("sess-1")
    assert len(second) == 0


@pytest.mark.asyncio
async def test_take_returns_empty_for_missing_session():
    assert await store.take("ghost") == []


@pytest.mark.asyncio
async def test_append_sticky():
    await store.append("sess-1", "Sticky", sticky=True)
    msgs = await store.take("sess-1")
    assert msgs[0]["sticky"] is True


# ---------------------------------------------------------------------------
# take_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_all_returns_all_sessions():
    await store.append("s1", "A")
    await store.append("s2", "B")
    all_msgs = await store.take_all()
    assert len(all_msgs) == 2


# ---------------------------------------------------------------------------
# _strip_ts
# ---------------------------------------------------------------------------


def test_strip_ts_removes_ts_field():
    msgs = [
        {"id": "a", "text": "hi", "ts": 123},
        {"id": "b", "text": "bye", "ts": 456},
    ]
    result = store._strip_ts(msgs)
    for m in result:
        assert "ts" not in m
    assert result[0]["text"] == "hi"
