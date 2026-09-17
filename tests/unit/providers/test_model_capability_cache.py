# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import time
from unittest import mock

import pytest

from qwenpaw.providers.model_capability_cache import ModelCapabilityCache

_TTL = "qwenpaw.providers.model_capability_cache.CAPABILITY_CACHE_TTL_SECONDS"


@pytest.fixture()
def cache() -> ModelCapabilityCache:
    return ModelCapabilityCache()


def test_learn_and_get_roundtrip(cache: ModelCapabilityCache) -> None:
    cache.learn("p:m", "rejects_media", True)
    assert cache.get("p:m", "rejects_media", False) is True


def test_get_returns_default_when_unlearned(
    cache: ModelCapabilityCache,
) -> None:
    assert cache.get("p:m", "rejects_media", False) is False
    assert cache.get("p:m", "rejects_media") is None


def test_clear_all(cache: ModelCapabilityCache) -> None:
    cache.learn("p:m", "rejects_media", True)
    cache.clear()
    assert cache.get("p:m", "rejects_media", False) is False


def test_clear_single_model_key(cache: ModelCapabilityCache) -> None:
    cache.learn("a:m", "rejects_media", True)
    cache.learn("b:n", "rejects_media", True)
    cache.clear("a:m")
    assert cache.get("a:m", "rejects_media", False) is False
    assert cache.get("b:n", "rejects_media", False) is True


def test_forget_drops_single_capability(cache: ModelCapabilityCache) -> None:
    cache.learn("p:m", "rejects_media", True)
    cache.learn("p:m", "needs_reasoning_content", True)
    cache.forget("p:m", "rejects_media")
    assert cache.get("p:m", "rejects_media", False) is False
    assert cache.get("p:m", "needs_reasoning_content", False) is True


def test_forget_preserves_other_models(cache: ModelCapabilityCache) -> None:
    cache.learn("a:m", "rejects_media", True)
    cache.learn("b:n", "rejects_media", True)
    cache.forget("a:m", "rejects_media")
    assert cache.get("a:m", "rejects_media", False) is False
    assert cache.get("b:n", "rejects_media", False) is True


def test_forget_unknown_key_is_noop(cache: ModelCapabilityCache) -> None:
    cache.forget("nonexistent", "rejects_media")
    cache.learn("p:m", "rejects_media", True)
    cache.forget("p:m", "needs_reasoning_content")
    assert cache.get("p:m", "rejects_media", False) is True


def test_relearn_same_value_refreshes_timestamp(
    cache: ModelCapabilityCache,
) -> None:
    with mock.patch(
        "qwenpaw.providers.model_capability_cache.time.monotonic",
        side_effect=[100.0, 200.0],
    ):
        cache.learn("p:m", "rejects_media", True)
        set_at_before = cache._learned["p:m"]["rejects_media"].set_at
        cache.learn("p:m", "rejects_media", True)
        set_at_after = cache._learned["p:m"]["rejects_media"].set_at
    assert set_at_after > set_at_before
    assert cache._learned["p:m"]["rejects_media"].value is True


def test_relearn_different_value_overwrites(
    cache: ModelCapabilityCache,
) -> None:
    cache.learn("p:m", "rejects_media", True)
    cache.learn("p:m", "rejects_media", False)
    assert cache.get("p:m", "rejects_media") is False


def test_expired_entry_returns_default(
    cache: ModelCapabilityCache,
) -> None:
    with mock.patch(_TTL, 0.05):
        cache.learn("p:m", "rejects_media", True)
        assert cache.get("p:m", "rejects_media", False) is True
        time.sleep(0.08)
        assert cache.get("p:m", "rejects_media", False) is False


def test_expired_entry_is_evicted_from_bucket(
    cache: ModelCapabilityCache,
) -> None:
    with mock.patch(_TTL, 0.05):
        cache.learn("p:m", "rejects_media", True)
        time.sleep(0.08)
        cache.get("p:m", "rejects_media", False)
        assert "p:m" not in cache._learned


def test_ttl_zero_disables_expiry(cache: ModelCapabilityCache) -> None:
    with mock.patch(_TTL, 0.0):
        cache.learn("p:m", "rejects_media", True)
        time.sleep(0.05)
        assert cache.get("p:m", "rejects_media", False) is True
