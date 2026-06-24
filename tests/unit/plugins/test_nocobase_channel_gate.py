# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for the NocoBase channel gate checker."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nocobase_auth.channel_gate import build_checker
from nocobase_auth.permission_store import PermissionStore


@pytest.fixture
def store() -> PermissionStore:
    with tempfile.TemporaryDirectory() as tmp:
        yield PermissionStore(path=Path(tmp) / "perms.json")


def test_checker_allows(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "alice@example.com", "roles": ["admin"]},
        ],
        roles=[{"id": "1", "name": "admin", "title": "Admin"}],
        role_channel_map={"admin": {"allowed": ["console"], "denied": []}},
    )
    checker = build_checker(store)
    assert checker("console", "alice@example.com", {}) == "allow"


def test_checker_denies(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "bob@example.com", "roles": ["viewer"]},
        ],
        roles=[{"id": "1", "name": "viewer", "title": "Viewer"}],
        role_channel_map={"viewer": {"allowed": [], "denied": ["dingtalk"]}},
    )
    checker = build_checker(store)
    assert checker("dingtalk", "bob@example.com", {}) == "deny"


def test_checker_falls_through_unknown_user(store: PermissionStore) -> None:
    checker = build_checker(store)
    assert checker("console", "unknown@example.com", {}) is None


def test_checker_falls_through_unknown_channel(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "alice@example.com", "roles": ["admin"]},
        ],
        roles=[{"id": "1", "name": "admin", "title": "Admin"}],
        role_channel_map={"admin": {"allowed": ["console"], "denied": []}},
    )
    checker = build_checker(store)
    assert checker("telegram", "alice@example.com", {}) is None


def test_checker_falls_through_empty_sender_id(store: PermissionStore) -> None:
    checker = build_checker(store)
    assert checker("console", "", {}) is None


def test_checker_survives_store_exception(store: PermissionStore) -> None:
    # Simulate a checker that uses a broken store by overriding
    # is_channel_allowed.
    store.is_channel_allowed = lambda *_a, **_kw: (_ for _ in ()).throw(
        RuntimeError("boom"),
    )
    checker = build_checker(store)
    assert checker("console", "alice@example.com", {}) is None


# Remove unused assignment placeholder for pylint.
broken_checker = None
