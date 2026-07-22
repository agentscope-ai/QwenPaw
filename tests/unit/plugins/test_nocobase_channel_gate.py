# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for the NocoBase channel gate checker."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nocobase_auth.channel_gate import build_checker
from nocobase_auth.permission_store import PermissionStore


def _enabled() -> bool:
    return True


def _disabled() -> bool:
    return False


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
    checker = build_checker(store, _enabled)
    assert checker("console", "alice@example.com", {}) == "allow"


def test_checker_denies(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "bob@example.com", "roles": ["viewer"]},
        ],
        roles=[{"id": "1", "name": "viewer", "title": "Viewer"}],
        role_channel_map={"viewer": {"allowed": [], "denied": ["dingtalk"]}},
    )
    checker = build_checker(store, _enabled)
    assert checker("dingtalk", "bob@example.com", {}) == "deny"


def test_checker_falls_through_unknown_channel(store: PermissionStore) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "alice@example.com", "roles": ["admin"]},
        ],
        roles=[{"id": "1", "name": "admin", "title": "Admin"}],
        role_channel_map={"admin": {"allowed": ["console"], "denied": []}},
    )
    checker = build_checker(store, _enabled)
    # Non-fail-closed channel with no opinion -> fall through.
    assert checker("telegram", "alice@example.com", {}) is None


# ── Fail-closed semantics for the console channel ────────────────────────


def test_console_denies_unknown_user_when_enabled(
    store: PermissionStore,
) -> None:
    """An authenticated login user with no NocoBase account is blocked."""
    checker = build_checker(store, _enabled)
    assert checker("console", "stranger@example.com", {}) == "deny"


def test_console_denies_empty_sender_when_enabled(
    store: PermissionStore,
) -> None:
    """No identity (not logged into NocoBase) is blocked on console."""
    checker = build_checker(store, _enabled)
    assert checker("console", "", {}) == "deny"


def test_console_allows_known_user_without_mapping(
    store: PermissionStore,
) -> None:
    """A known NocoBase user with no explicit console mapping is allowed."""
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "alice@example.com", "roles": ["member"]},
        ],
        roles=[{"id": "1", "name": "member", "title": "Member"}],
        role_channel_map={},
    )
    checker = build_checker(store, _enabled)
    assert checker("console", "alice@example.com", {}) == "allow"


def test_console_explicit_deny_wins_for_known_user(
    store: PermissionStore,
) -> None:
    store.update_from_sync(
        users=[
            {"id": "1", "sender_id": "bob@example.com", "roles": ["member"]},
        ],
        roles=[{"id": "1", "name": "member", "title": "Member"}],
        role_channel_map={"member": {"allowed": [], "denied": ["console"]}},
    )
    checker = build_checker(store, _enabled)
    assert checker("console", "bob@example.com", {}) == "deny"


def test_console_falls_through_when_disabled(store: PermissionStore) -> None:
    """A disabled integration never blocks; console falls through."""
    checker = build_checker(store, _disabled)
    assert checker("console", "stranger@example.com", {}) is None
    assert checker("console", "", {}) is None


def test_non_console_unknown_user_falls_through_when_enabled(
    store: PermissionStore,
) -> None:
    """Fail-closed is scoped to console; IM channels keep fall-through."""
    checker = build_checker(store, _enabled)
    assert checker("dingtalk", "stranger@example.com", {}) is None
    assert checker("telegram", "", {}) is None


def test_checker_survives_store_exception(store: PermissionStore) -> None:
    # Simulate a checker that uses a broken store by overriding
    # is_channel_allowed.
    store.is_channel_allowed = lambda *_a, **_kw: (_ for _ in ()).throw(
        RuntimeError("boom"),
    )
    checker = build_checker(store, _enabled)
    assert checker("console", "alice@example.com", {}) is None
