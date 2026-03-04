# -*- coding: utf-8 -*-
# pylint: disable=protected-access
import time

import pytest

from copaw.app import console_push_store as push_store


@pytest.fixture(autouse=True)
async def _reset_store():
    async with push_store._lock:
        push_store._list.clear()
    yield
    async with push_store._lock:
        push_store._list.clear()


@pytest.mark.asyncio
async def test_take_filters_expired_messages() -> None:
    await push_store.append("s1", "old")
    await push_store.append("s1", "fresh")
    await push_store.append("s2", "other-session")

    async with push_store._lock:
        push_store._list[0]["ts"] = time.time() - (
            push_store._MAX_AGE_SECONDS + 5
        )

    out = await push_store.take("s1")
    texts = [item["text"] for item in out]

    assert texts == ["fresh"]
    async with push_store._lock:
        assert [m["text"] for m in push_store._list] == ["other-session"]


@pytest.mark.asyncio
async def test_take_all_filters_expired_messages() -> None:
    await push_store.append("s1", "expired")
    await push_store.append("s2", "fresh")

    async with push_store._lock:
        push_store._list[0]["ts"] = time.time() - (
            push_store._MAX_AGE_SECONDS + 5
        )

    out = await push_store.take_all()

    assert [item["text"] for item in out] == ["fresh"]
    async with push_store._lock:
        assert not push_store._list


@pytest.mark.asyncio
async def test_get_recent_prunes_expired_messages() -> None:
    await push_store.append("s1", "expired")
    await push_store.append("s1", "fresh")

    async with push_store._lock:
        push_store._list[0]["ts"] = time.time() - (
            push_store._MAX_AGE_SECONDS + 5
        )

    out = await push_store.get_recent()

    assert [item["text"] for item in out] == ["fresh"]
    async with push_store._lock:
        assert [m["text"] for m in push_store._list] == ["fresh"]


@pytest.mark.asyncio
async def test_get_recent_rejects_negative_max_age() -> None:
    await push_store.append("s1", "fresh")

    with pytest.raises(ValueError, match="non-negative"):
        await push_store.get_recent(max_age_seconds=-1)

    async with push_store._lock:
        assert [m["text"] for m in push_store._list] == ["fresh"]
