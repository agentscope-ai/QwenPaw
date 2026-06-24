# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the NocoBase permission store."""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from nocobase_auth.permission_store import PermissionStore


@pytest.fixture
def store() -> PermissionStore:
    with tempfile.TemporaryDirectory() as tmp:
        yield PermissionStore(path=Path(tmp) / "perms.json")


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX file mode bits do not apply on Windows",
)
def test_saved_store_is_owner_only(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[{"id": "1", "sender_id": "alice@example.com", "roles": []}],
        roles=[],
    )
    mode = stat.S_IMODE(os.stat(store._path).st_mode)
    assert mode == 0o600


def test_update_and_get_user(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "alice@example.com", "roles": ["admin"]},
        ],
        roles=[{"id": "1", "name": "admin", "title": "Admin"}],
        role_channel_map={"admin": {"allowed": ["console"], "denied": []}},
    )

    user = store.get_user("alice@example.com")
    assert user is not None
    assert user["roles"] == ["admin"]


def test_is_channel_allowed(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "alice@example.com", "roles": ["admin"]},
            {"id": "2", "sender_id": "bob@example.com", "roles": ["viewer"]},
        ],
        roles=[
            {"id": "1", "name": "admin", "title": "Admin"},
            {"id": "2", "name": "viewer", "title": "Viewer"},
        ],
        role_channel_map={
            "admin": {"allowed": ["console", "dingtalk"], "denied": []},
            "viewer": {"allowed": ["console"], "denied": ["dingtalk"]},
        },
    )

    assert store.is_channel_allowed("alice@example.com", "console") is True
    assert store.is_channel_allowed("alice@example.com", "telegram") is None
    assert store.is_channel_allowed("bob@example.com", "console") is True
    assert store.is_channel_allowed("bob@example.com", "dingtalk") is False
    assert store.is_channel_allowed("unknown@example.com", "console") is None


def test_deny_takes_precedence(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "alice@example.com", "roles": ["hybrid"]},
        ],
        roles=[{"id": "1", "name": "hybrid", "title": "Hybrid"}],
        role_channel_map={
            "hybrid": {"allowed": ["console"], "denied": ["console"]},
        },
    )

    assert store.is_channel_allowed("alice@example.com", "console") is False


def test_persistence(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "alice@example.com", "roles": ["admin"]},
        ],
        roles=[{"id": "1", "name": "admin", "title": "Admin"}],
        role_channel_map={},
    )

    store2 = PermissionStore(path=store._path)
    assert store2.get_user("alice@example.com") is not None
    status = store2.get_last_sync_status()
    assert status["user_count"] == 1


def test_concurrent_reads_during_write(store: PermissionStore) -> None:
    errors = []
    results = []

    def writer() -> None:
        try:
            store.update_from_sync(
                users=[
                    {"id": str(i), "sender_id": f"u{i}@test.com", "roles": []}
                    for i in range(20)
                ],
                roles=[],
                role_channel_map={},
            )
        except Exception as exc:
            errors.append(exc)

    def reader() -> None:
        try:
            results.append(len(store.list_users()))
        except Exception as exc:
            errors.append(exc)

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    readers = [threading.Thread(target=reader) for _ in range(10)]
    for t in readers:
        t.start()
    for t in readers:
        t.join()
    writer_thread.join()

    assert not errors
    # After the writer finishes, the cache should contain all 20 users.
    assert len(store.list_users()) == 20


def test_role_channel_map_persistence(store: PermissionStore) -> None:
    store.set_role_channel_map(
        {"admin": {"allowed": ["console"], "denied": []}},
    )
    assert store.get_role_channel_map()["admin"]["allowed"] == ["console"]

    store2 = PermissionStore(path=store._path)
    assert store2.get_role_channel_map()["admin"]["allowed"] == ["console"]
