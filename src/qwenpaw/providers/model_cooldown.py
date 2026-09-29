# -*- coding: utf-8 -*-
"""Process-wide cooldown registry for model fallback candidates.

A candidate that fails a fallback hop is remembered for a cooling period,
so the next request starts from a healthy candidate instead of paying the
retry cost of a model that is known to be down.  The state is keyed by
``provider_id:model_id`` and shared by every
:class:`~qwenpaw.providers.fallback_chat_model.FallbackChatModel` in the
process, because each agent, cron job, and title generator builds its own
model chain.

Durations grow exponentially with consecutive failures and are capped, so
a permanently broken candidate backs off to a fixed interval instead of
growing without bound.  The failure counter only resets when the candidate
serves a request successfully; a candidate that fails again right after
its cooldown expired keeps escalating.

Thread-safety: designed for a single asyncio event loop -- there is no
``await`` between a read and a write, so no lock is taken.  If QwenPaw
ever introduces thread-pool concurrency here, add a lock around
``_states`` access.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .model_error_policy import classify_model_error

logger = logging.getLogger(__name__)

# Upper bound on tracked candidates.  Real keys are bounded by the models
# a deployment actually uses, so this only guards against churn from
# repeated provider add/remove.
_MAX_TRACKED = 256

# Caps the exponent so a long-lived entry cannot build a huge integer.
_MAX_EXPONENT = 32

# Only availability errors cool a candidate down.  Request-level problems
# (context overflow, content safety, a malformed request) and unclassified
# errors leave the candidate usable -- the model itself did nothing wrong.
_COOLDOWN_KINDS = frozenset(
    {
        "rate_limited",
        "transient",
        "authentication",
        "model_not_found",
    },
)


@dataclass(frozen=True)
class CooldownPolicy:
    """Durations applied when a candidate fails a fallback hop."""

    enabled: bool = True
    base_seconds: float = 60.0
    max_seconds: float = 3600.0


@dataclass
class _CooldownState:
    """State of one ``provider_id:model_id`` pair."""

    expires_at: float
    consecutive_failures: int = 0


_states: dict[str, _CooldownState] = {}


def _now() -> float:
    """Return the monotonic clock every deadline is measured against."""
    return time.monotonic()


def model_cooldown_key(provider_id: str, model_id: str) -> str:
    """Return the registry key for one provider/model pair."""
    return f"{provider_id}:{model_id}"


def is_cooldown_eligible(exc: Exception) -> bool:
    """Return whether *exc* marks the candidate as unusable."""
    return classify_model_error(exc).kind in _COOLDOWN_KINDS


def is_on_cooldown(key: str) -> bool:
    """Return whether *key* is cooling down.

    An expired entry is kept in the registry on purpose: a candidate that
    fails again after its cooldown must keep escalating.  Entries are
    dropped by :func:`record_model_success` or by the size cap in
    :func:`record_model_failure`.
    """
    state = _states.get(key)
    return state is not None and _now() < state.expires_at


def cooldown_remaining(key: str) -> float:
    """Return the seconds left on *key*, or 0.0 when it is not cooling."""
    state = _states.get(key)
    if state is None:
        return 0.0
    return max(0.0, state.expires_at - _now())


def record_model_failure(
    key: str,
    exc: Exception,
    policy: CooldownPolicy,
) -> float:
    """Record one failure of *key* and return the cooldown length.

    Returns 0.0 without recording anything when cooldown is disabled or
    when *exc* does not indicate an unusable candidate.
    """
    if not policy.enabled or not is_cooldown_eligible(exc):
        return 0.0
    state = _states.get(key)
    failures = (state.consecutive_failures if state is not None else 0) + 1
    cooldown = _cooldown_seconds(failures, policy)
    _states[key] = _CooldownState(
        expires_at=_now() + cooldown,
        consecutive_failures=failures,
    )
    _prune()
    logger.warning(
        "Model %s cooling down for %.1fs after %d consecutive failure(s) "
        "(%s)",
        key,
        cooldown,
        failures,
        classify_model_error(exc).kind,
    )
    return cooldown


def record_model_success(key: str) -> None:
    """Clear the cooldown and the failure counter for *key*."""
    if _states.pop(key, None) is not None:
        logger.debug("Model %s is serving again; cooldown cleared", key)


def reset_model_cooldowns() -> None:
    """Drop every tracked candidate (test and diagnostics helper)."""
    _states.clear()


def _cooldown_seconds(failures: int, policy: CooldownPolicy) -> float:
    """Return the cooldown for *failures* consecutive failures.

    The first failure waits ``base_seconds``, the second twice as long,
    and so on, never exceeding ``max_seconds``.
    """
    base = max(0.0, policy.base_seconds)
    if base <= 0.0:
        return 0.0
    ceiling = max(base, policy.max_seconds)
    exponent = min(max(0, failures - 1), _MAX_EXPONENT)
    return min(ceiling, base * (2**exponent))


def _prune() -> None:
    """Forget the longest-expired entries once the registry is too big."""
    overflow = len(_states) - _MAX_TRACKED
    if overflow <= 0:
        return
    ordered = sorted(
        _states.items(),
        key=lambda item: item[1].expires_at,
    )
    for key, _state in ordered[:overflow]:
        _states.pop(key, None)
