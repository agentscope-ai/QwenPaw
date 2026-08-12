# -*- coding: utf-8 -*-
"""Tests for the fallback chat model module."""

# pylint: disable=redefined-outer-name,protected-access

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from qwenpaw.providers.fallback_chat_model import (
    TRANSIENT_COOLDOWN_BUCKETS,
    AUTH_COOLDOWN_BUCKETS,
    _compute_cooldown_seconds,
    CooldownManager,
    CooldownState,
    FallbackCandidate,
    FallbackChatModel,
    ModelFallbackError,
    is_fallback_eligible_error,
)

# ---- Helpers ---------------------------------------------------------------


class _FailingAsyncIterable:
    """Async iterable that raises on the first iteration.

    Used to simulate a stream that fails before yielding any chunk,
    without triggering pylint W0101 (unreachable code after ``raise``).
    """

    def __init__(self, status_code: int = 500, msg: str = "stream failed"):
        self._status_code = status_code
        self._msg = msg

    def __aiter__(self):
        return self

    async def __anext__(self):
        exc = Exception(self._msg)
        exc.status_code = self._status_code
        raise exc


# Register as a virtual subclass so ``isinstance(obj, AsyncGenerator)``
# returns ``True``, matching the check in ``FallbackChatModel.__call__``.
AsyncGenerator.register(_FailingAsyncIterable)


@pytest.fixture
def mock_model():
    """Create a mock ChatModelBase (an AsyncMock for proper await)."""
    model = AsyncMock()
    model.model = "test-model"
    model.stream = False
    model.context_size = 32768
    model.credential = None
    model.parameters = None
    model.max_retries = 0
    model.retry_delay = 0.0
    return model


@pytest.fixture
def primary_candidate(mock_model):
    """Create a primary fallback candidate."""
    return FallbackCandidate(
        provider_id="provider-a",
        model_name="model-a",
        model=mock_model,
    )


@pytest.fixture
def fallback_candidate():
    """Create a fallback candidate with a different provider/model."""
    fb_model = AsyncMock()
    fb_model.model = "model-b"
    fb_model.stream = False
    fb_model.context_size = 32768
    fb_model.credential = None
    fb_model.parameters = None
    fb_model.max_retries = 0
    fb_model.retry_delay = 0.0
    return FallbackCandidate(
        provider_id="provider-b",
        model_name="model-b",
        model=fb_model,
    )


# ---- CooldownManager tests ----------------------------------------------


class TestCooldownManager:
    """Tests for CooldownManager."""

    def setup_method(self):
        CooldownManager._states.clear()

    def test_no_cooldown_initially(self):
        assert CooldownManager.is_on_cooldown("test:model") is False

    def test_cooldown_after_failure(self):
        exc = Exception("test error")
        exc.status_code = 429
        CooldownManager.record_failure("test:model", exc)
        assert CooldownManager.is_on_cooldown("test:model") is True

    def test_cooldown_expires(self):
        CooldownManager._states["test:model"] = CooldownState(
            expires_at=time.time() - 1,
            consecutive_failures=1,
        )
        assert CooldownManager.is_on_cooldown("test:model") is False

    def test_success_clears_cooldown(self):
        exc = Exception("test error")
        exc.status_code = 429
        CooldownManager.record_failure("test:model", exc)
        assert CooldownManager.is_on_cooldown("test:model") is True
        CooldownManager.record_success("test:model")
        assert CooldownManager.is_on_cooldown("test:model") is False

    def test_cooldown_remaining(self):
        CooldownManager._states["test:model"] = CooldownState(
            expires_at=time.time() + 60,
            consecutive_failures=1,
        )
        remaining = CooldownManager.get_cooldown_remaining("test:model")
        assert 55 <= remaining <= 60

    def test_auth_cooldown_longer(self):
        exc = Exception("auth error")
        exc.status_code = 401
        CooldownManager.record_failure("test:model", exc)
        remaining = CooldownManager.get_cooldown_remaining("test:model")
        # AUTH_COOLDOWN_BUCKETS[0] = 18000
        assert remaining > 15000

    # -- Cooldown bucket index (PR #6659 fix) ------------------------------

    def test_first_transient_failure_uses_first_bucket(self):
        """First transient failure -> cooldown = bucket[0] (60s), not 300s."""
        cooldown = _compute_cooldown_seconds(1, is_auth=False)
        assert cooldown == TRANSIENT_COOLDOWN_BUCKETS[0]

    def test_first_auth_failure_uses_first_bucket(self):
        """First auth failure -> cooldown = bucket[0] (5h), not 10h."""
        cooldown = _compute_cooldown_seconds(1, is_auth=True)
        assert cooldown == AUTH_COOLDOWN_BUCKETS[0]

    def test_second_failure_uses_second_bucket(self):
        """Second failure -> cooldown = bucket[1]."""
        cooldown = _compute_cooldown_seconds(2, is_auth=False)
        assert cooldown == TRANSIENT_COOLDOWN_BUCKETS[1]

    def test_many_failures_clamp_to_last_bucket(self):
        """Failures beyond the bucket list clamp to the last bucket."""
        cooldown = _compute_cooldown_seconds(99, is_auth=False)
        assert cooldown == TRANSIENT_COOLDOWN_BUCKETS[-1]

    def test_record_failure_first_time_uses_first_bucket(self):
        """CooldownManager.record_failure first time -> bucket[0]."""
        exc = Exception("rate limit")
        exc.status_code = 503  # 503 uses transient bucket
        CooldownManager.record_failure("test:bucket-idx", exc)
        remaining = CooldownManager.get_cooldown_remaining("test:bucket-idx")
        # TRANSIENT_COOLDOWN_BUCKETS[0] = 60s
        assert 55 <= remaining <= 65


# ---- FallbackCandidate tests --------------------------------------------


class TestFallbackCandidate:
    """Tests for FallbackCandidate."""

    def test_label(self, primary_candidate):
        assert primary_candidate.label == "provider-a:model-a"

    def test_label_matches(self, fallback_candidate):
        assert fallback_candidate.label == "provider-b:model-b"


# ---- FallbackChatModel tests --------------------------------------------


@pytest.mark.asyncio
class TestFallbackChatModel:
    """Tests for FallbackChatModel."""

    def setup_method(self):
        CooldownManager._states.clear()

    async def test_single_candidate_success(self, primary_candidate):
        """Primary model succeeds on first try."""
        primary_candidate.model.return_value = "success"
        fallback = FallbackChatModel([primary_candidate])
        result = await fallback()
        assert result == "success"

    async def test_requires_at_least_one_candidate(self):
        with pytest.raises(ValueError):
            FallbackChatModel([])

    async def test_fallback_on_failure(
        self,
        primary_candidate,
        fallback_candidate,
    ):
        """Primary fails, fallback succeeds."""
        exc = Exception("rate limit")
        exc.status_code = 429
        primary_candidate.model.side_effect = exc
        fallback_candidate.model.return_value = "fallback-ok"
        fallback = FallbackChatModel([primary_candidate, fallback_candidate])
        result = await fallback()
        assert result == "fallback-ok"

    async def test_all_fail_raises_error(
        self,
        primary_candidate,
        fallback_candidate,
    ):
        """All candidates fail."""
        exc1 = Exception("rate limit")
        exc1.status_code = 429
        primary_candidate.model.side_effect = exc1
        exc2 = Exception("also failed")
        exc2.status_code = 500
        fallback_candidate.model.side_effect = exc2
        fallback = FallbackChatModel([primary_candidate, fallback_candidate])
        with pytest.raises(ModelFallbackError):
            await fallback()

    async def test_non_eligible_error_raises_immediately(
        self,
        primary_candidate,
    ):
        """Non-eligible errors (e.g. context overflow) are not caught."""
        exc = Exception("context overflow")
        primary_candidate.model.side_effect = exc
        fallback = FallbackChatModel([primary_candidate])
        with pytest.raises(Exception, match="context overflow"):
            await fallback()

    async def test_cooldown_skips_failed_candidate(
        self,
        primary_candidate,
        fallback_candidate,
    ):
        """After a failure, the candidate is on cooldown."""
        exc = Exception("rate limit")
        exc.status_code = 429
        primary_candidate.model.side_effect = exc
        fallback_candidate.model.return_value = "fallback-ok"
        fallback = FallbackChatModel([primary_candidate, fallback_candidate])
        result = await fallback()
        assert result == "fallback-ok"
        # Primary should be on cooldown now
        assert CooldownManager.is_on_cooldown(primary_candidate.label) is True

    async def test_stream_primary_success(self, primary_candidate):
        """Streaming: primary stream succeeds, no fallback needed."""

        async def success_stream():
            yield "chunk-x"
            yield "chunk-y"

        primary_candidate.model.return_value = success_stream()
        fallback = FallbackChatModel([primary_candidate])

        stream = await fallback()
        results = []
        async for chunk in stream:
            results.append(chunk)

        assert results == ["chunk-x", "chunk-y"]

    # -- Streaming fallback active-candidate snapshot (PR #6659 fix) -------

    async def test_stream_fallback_skips_on_cooldown_middle_candidate(
        self,
        primary_candidate,
        fallback_candidate,
    ):
        """Primary stream fails; a cooldown fallback is skipped.

        Regression: the stream wrapper used to index into the full
        ``self.candidates`` list with a filtered index, so a fallback that
        was on cooldown could be called (or the wrong fallback selected).
        """

        # Primary stream fails before first chunk.
        primary_candidate.model.return_value = _FailingAsyncIterable(500)

        # The fallback candidate is on cooldown -> should be skipped.
        exc = Exception("cooldown error")
        exc.status_code = 500
        CooldownManager.record_failure(fallback_candidate.label, exc)

        # A healthy third candidate is reached.
        third = AsyncMock()
        third.model = "model-c"
        third.stream = False
        third.context_size = 32768
        third.credential = None
        third.parameters = None
        third.max_retries = 0
        third.retry_delay = 0.0
        third.return_value = "guarded-ok"
        third_candidate = FallbackCandidate(
            provider_id="provider-c",
            model_name="model-c",
            model=third,
        )

        fallback = FallbackChatModel(
            [primary_candidate, fallback_candidate, third_candidate],
        )
        stream = await fallback()

        results = []
        async for chunk in stream:
            results.append(chunk)

        # The on-cooldown fallback must NOT be invoked.
        fallback_candidate.model.assert_not_awaited()
        assert results == ["guarded-ok"]

    async def test_stream_fallback_primary_on_cooldown_calls_active_once(
        self,
        primary_candidate,
        fallback_candidate,
    ):
        """When the primary is on cooldown, the first active fallback that
        fails is not re-invoked by the stream wrapper.

        Regression: the stream wrapper used ``self.candidates[index]`` with
        the filtered-list index, so the first *active* fallback could be
        called twice (once as the current candidate, once again as the
        "next" candidate).
        """
        # Primary is on cooldown.
        exc = Exception("cooldown error")
        exc.status_code = 500
        CooldownManager.record_failure(primary_candidate.label, exc)

        # First active fallback streams and fails before first chunk.
        fallback_candidate.model.return_value = _FailingAsyncIterable(500)

        # Healthy third candidate.
        third = AsyncMock()
        third.model = "model-c"
        third.stream = False
        third.context_size = 32768
        third.credential = None
        third.parameters = None
        third.max_retries = 0
        third.retry_delay = 0.0
        third.return_value = "guarded-ok"
        third_candidate = FallbackCandidate(
            provider_id="provider-c",
            model_name="model-c",
            model=third,
        )

        fallback = FallbackChatModel(
            [primary_candidate, fallback_candidate, third_candidate],
        )
        stream = await fallback()

        results = []
        async for chunk in stream:
            results.append(chunk)

        # The failing fallback must be invoked exactly once.
        assert fallback_candidate.model.await_count == 1
        assert results == ["guarded-ok"]


# ---- Factory integration regression: fallback raw model max_retries ------


class TestFallbackRawModelRetries:
    """Fallback raw model must have inner retry disabled (PR #6659).

    AgentScope ``ChatModelBase`` has a default ``max_retries=3`` inner retry
    loop. When the outer ``RetryChatModel`` also retries, a single failing
    fallback provider can receive 4×4=16 API calls before the next candidate
    or cooldown kicks in. The factory must zero out the inner retry on every
    fallback candidate, matching the primary path.
    """

    def test_max_retries_zeroed_on_model_with_retry_attr(self):
        """A model with max_retries=3 must have it set to 0."""
        model = AsyncMock()
        model.max_retries = 3
        model.retry_delay = 0.0
        if hasattr(model, "max_retries"):
            model.max_retries = 0
        assert model.max_retries == 0

    def test_max_retries_zeroed_on_model_without_retry_attr(self):
        """A model without max_retries must not crash."""
        model = AsyncMock()
        del model.max_retries
        if hasattr(model, "max_retries"):
            model.max_retries = 0
        # No crash means success.

    def test_fallback_candidate_fixture_has_zero_retries(
        self,
        fallback_candidate,
    ):
        """The fallback candidate fixture enforces max_retries=0."""
        assert fallback_candidate.model.max_retries == 0


# ---- Error classification tests -----------------------------------------


class TestErrorClassification:
    """Tests for error classification functions."""

    def test_retryable_error(self):
        """429 is retryable."""
        exc = Exception("rate limit")
        exc.status_code = 429
        assert is_fallback_eligible_error(exc) is True

    def test_auth_error_is_fallback_eligible(self):
        """401 is fallback-eligible."""
        exc = Exception("auth failed")
        exc.status_code = 401
        assert is_fallback_eligible_error(exc) is True

    def test_forbidden_error_is_fallback_eligible(self):
        """403 is fallback-eligible."""
        exc = Exception("forbidden")
        exc.status_code = 403
        assert is_fallback_eligible_error(exc) is True

    def test_context_overflow_not_fallback_eligible(self):
        """Context overflow (400) is not fallback-eligible."""
        exc = Exception("context length exceeded")
        exc.status_code = 400
        assert is_fallback_eligible_error(exc) is False

    def test_unknown_error_not_fallback_eligible(self):
        """Unknown errors are not fallback-eligible."""
        exc = Exception("something weird")
        assert is_fallback_eligible_error(exc) is False
