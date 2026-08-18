# -*- coding: utf-8 -*-
"""Regression: concurrent credential writes must not lose entries.

Review #7081 Issue 1: a fresh ``AsyncCredentialStore`` per call site meant
each instance had its own RLock, so two concurrent read-modify-write cycles
(AnySearch auto-registration racing a Console save) could each ``os.replace``
the whole YAML, silently dropping the other writer's entry.

The store is now a process-level singleton keyed by canonical path; this
test widens the read-modify-write window and verifies both refs survive.
"""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import time

import pytest

from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord


@pytest.mark.asyncio
async def test_same_path_instances_are_shared(tmp_path) -> None:
    path = tmp_path / "credentials.yaml"
    assert AsyncCredentialStore(path) is AsyncCredentialStore(path)


@pytest.mark.asyncio
async def test_concurrent_writes_preserve_both_refs(tmp_path) -> None:
    path = tmp_path / "credentials.yaml"
    store_a = AsyncCredentialStore(path)
    store_b = AsyncCredentialStore(path)

    # Widen the read-modify-write window so a lost update would be
    # deterministic if the instances did not share a lock.
    original_write = AsyncCredentialStore._write_root

    def slow_write(instance, data) -> None:
        time.sleep(0.05)
        return original_write(instance, data)

    AsyncCredentialStore._write_root = slow_write  # type: ignore[assignment]
    try:
        await asyncio.gather(
            store_a.put(
                CredentialRecord(
                    ref="tool/a",
                    kind="static",
                    secrets={"api_key": "a"},
                ),
            ),
            store_b.put(
                CredentialRecord(
                    ref="tool/b",
                    kind="static",
                    secrets={"api_key": "b"},
                ),
            ),
        )
    finally:
        AsyncCredentialStore._write_root = original_write

    refs = await store_a.list_refs()
    assert "tool/a" in refs
    assert "tool/b" in refs
    assert await store_a.get("tool/a") is not None
    assert await store_a.get("tool/b") is not None
