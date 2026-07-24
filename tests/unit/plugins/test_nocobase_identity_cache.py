# -*- coding: utf-8 -*-
"""Unit tests for TokenIdentityCache."""
from __future__ import annotations

from nocobase_auth.identity_cache import TokenIdentityCache


def test_miss_returns_false() -> None:
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 100.0)
    assert c.get("t") == (False, None)


def test_positive_hit_within_ttl() -> None:
    now = {"t": 100.0}
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: now["t"])
    c.put("t", "alice@example.com")
    now["t"] = 159.0
    assert c.get("t") == (True, "alice@example.com")


def test_expired_is_miss() -> None:
    now = {"t": 100.0}
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: now["t"])
    c.put("t", "alice@example.com")
    now["t"] = 161.0
    assert c.get("t") == (False, None)


def test_negative_entry_is_hit_with_none() -> None:
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 100.0)
    c.put("bad", None)
    assert c.get("bad") == (True, None)


def test_arbitrary_object_round_trips_by_identity() -> None:
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 100.0)
    identity = object()
    c.put("t", identity)
    hit, value = c.get("t")
    assert hit is True
    assert value is identity


def test_negative_entry_distinct_from_miss() -> None:
    now = {"t": 100.0}
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: now["t"])
    c.put("bad", None)
    assert c.get("bad") == (True, None)
    assert c.get("missing") == (False, None)
