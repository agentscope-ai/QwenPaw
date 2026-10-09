# -*- coding: utf-8 -*-
"""Tests for the model fallback cooldown registry."""

# pylint: disable=protected-access

from __future__ import annotations

import pytest

from qwenpaw.providers import model_cooldown
from qwenpaw.providers.model_cooldown import (
    CooldownPolicy,
    cooldown_remaining,
    is_cooldown_eligible,
    is_on_cooldown,
    model_cooldown_key,
    record_model_failure,
    record_model_success,
    reset_model_cooldowns,
)


class _HttpError(Exception):
    """Exception carrying an HTTP status."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


_KEY = f"provider:model"
_POLICY = CooldownPolicy()
_INELIGIBLE_ERRORS = (
    _HttpError(400),
    ValueError(f"context length exceeded"),
    ValueError(f"content policy violation"),
    RuntimeError(f"unclassified provider failure"),
)


def test_unknown_key_is_not_cooling_down() -> None:
    assert is_on_cooldown(_KEY) is False
    assert cooldown_remaining(_KEY) == 0.0


def test_first_failure_uses_the_base_duration() -> None:
    length = record_model_failure(_KEY, _HttpError(429), _POLICY)

    assert length == 60.0
    assert is_on_cooldown(_KEY) is True
    assert cooldown_remaining(_KEY) == 60.0


def test_consecutive_failures_double_up_to_the_cap() -> None:
    policy = CooldownPolicy(base_seconds=60.0, max_seconds=200.0)

    lengths = [
        record_model_failure(_KEY, _HttpError(503), policy) for _ in range(4)
    ]

    assert lengths == [60.0, 120.0, 200.0, 200.0]


def test_expiry_stops_skipping_but_keeps_escalating(
    cooldown_clock,
) -> None:
    policy = CooldownPolicy(base_seconds=60.0, max_seconds=1000.0)
    record_model_failure(_KEY, _HttpError(503), policy)

    cooldown_clock.value += 61.0

    assert is_on_cooldown(_KEY) is False
    assert cooldown_remaining(_KEY) == 0.0
    # A candidate that fails again right after its cooldown is still
    # broken, so the next window is longer rather than back at the base.
    assert record_model_failure(_KEY, _HttpError(503), policy) == 120.0


def test_success_clears_the_window_and_the_counter() -> None:
    policy = CooldownPolicy(base_seconds=60.0, max_seconds=1000.0)
    record_model_failure(_KEY, _HttpError(503), policy)
    record_model_failure(_KEY, _HttpError(503), policy)

    record_model_success(_KEY)

    assert is_on_cooldown(_KEY) is False
    assert record_model_failure(_KEY, _HttpError(503), policy) == 60.0


def test_success_on_an_untracked_key_is_harmless() -> None:
    record_model_success(_KEY)

    assert is_on_cooldown(_KEY) is False


def test_availability_errors_are_eligible() -> None:
    assert is_cooldown_eligible(_HttpError(429)) is True
    assert is_cooldown_eligible(_HttpError(503)) is True
    assert is_cooldown_eligible(_HttpError(404)) is True
    # A revoked key makes this candidate unusable just as a 5xx does.
    assert is_cooldown_eligible(_HttpError(401)) is True


@pytest.mark.parametrize(f"exc", _INELIGIBLE_ERRORS)
def test_request_level_errors_do_not_cool_down(exc) -> None:
    assert is_cooldown_eligible(exc) is False

    assert record_model_failure(_KEY, exc, _POLICY) == 0.0
    assert is_on_cooldown(_KEY) is False


def test_keys_are_isolated() -> None:
    record_model_failure(f"provider:one", _HttpError(503), _POLICY)

    assert is_on_cooldown(f"provider:one") is True
    assert is_on_cooldown(f"provider:two") is False


def test_key_without_a_provider_id_is_stable() -> None:
    assert model_cooldown_key(f"", f"model") == f":model"
    assert model_cooldown_key(f"a", f"m") == f"a:m"


def test_disabled_policy_records_nothing() -> None:
    policy = CooldownPolicy(enabled=False)

    assert record_model_failure(_KEY, _HttpError(503), policy) == 0.0
    assert is_on_cooldown(_KEY) is False


def test_zero_base_never_skips_a_candidate() -> None:
    policy = CooldownPolicy(base_seconds=0.0)

    assert record_model_failure(_KEY, _HttpError(503), policy) == 0.0
    assert is_on_cooldown(_KEY) is False


def test_registry_stops_growing_at_the_tracked_cap(cooldown_clock) -> None:
    newest = model_cooldown._MAX_TRACKED + 9
    for index in range(newest + 1):
        cooldown_clock.value += 1.0
        record_model_failure(f"provider:m{index}", _HttpError(503), _POLICY)

    assert len(model_cooldown._states) == model_cooldown._MAX_TRACKED
    # The longest-expired entry is forgotten first.
    assert f"provider:m0" not in model_cooldown._states
    assert is_on_cooldown(f"provider:m{newest}") is True


def test_reset_clears_every_tracked_key() -> None:
    record_model_failure(_KEY, _HttpError(503), _POLICY)

    reset_model_cooldowns()

    assert is_on_cooldown(_KEY) is False
