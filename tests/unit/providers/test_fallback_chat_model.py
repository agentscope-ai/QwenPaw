# -*- coding: utf-8 -*-
"""Tests for the fallback chat model module."""

# pylint: disable=redefined-outer-name,protected-access

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.providers.fallback_chat_model import (
    CooldownManager,
    CooldownState,
    FallbackCandidate,
    FallbackChatModel,
    ModelFallbackError,
    is_fallback_eligible_error,
)

# ---- Fixtures -----------------------------------------------------------


@pytest.fixture
def mock_model():
    """Create a mock ChatModelBase."""
    model = MagicMock()
    model.__call__ = AsyncMock()
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
    fb_model = MagicMock()
    fb_model.__call__ = AsyncMock()
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


# ---- FallbackCandidate tests --------------------------------------------


class TestFallbackCandidate:
    """Tests for FallbackCandidate."""

    def test_label(self, primary_candidate):
        assert primary_candidate.label == "provider-a:model-a"

    def test_label_matches(self, fallback_candidate):
        assert fallback_candidate.label == "provider-b:model-b"


# ---- FallbackChatModel tests --------------------------------------------


class TestFallbackChatModel:
    """Tests for FallbackChatModel."""

    def setup_method(self):
        CooldownManager._states.clear()

    def test_single_candidate_success(self, primary_candidate):
        """Primary model succeeds on first try."""
        primary_candidate.model.__call__ = AsyncMock(return_value="success")
        fallback = FallbackChatModel([primary_candidate])
        result = fallback()
        assert result == "success"

    def test_requires_at_least_one_candidate(self):
        with pytest.raises(ValueError):
            FallbackChatModel([])

    def test_fallback_on_failure(self, primary_candidate, fallback_candidate):
        """Primary fails, fallback succeeds."""
        primary_candidate.model.__call__ = AsyncMock(
            side_effect=Exception("rate limit"),
        )
        primary_candidate.model.__call__.side_effect.status_code = 429
        fallback_candidate.model.__call__ = AsyncMock(
            return_value="fallback-ok",
        )
        fallback = FallbackChatModel([primary_candidate, fallback_candidate])
        result = fallback()
        assert result == "fallback-ok"

    def test_all_fail_raises_error(
        self,
        primary_candidate,
        fallback_candidate,
    ):
        """All candidates fail."""
        primary_candidate.model.__call__ = AsyncMock(
            side_effect=Exception("rate limit"),
        )
        primary_candidate.model.__call__.side_effect.status_code = 429
        fallback_candidate.model.__call__ = AsyncMock(
            side_effect=Exception("also failed"),
        )
        fallback_candidate.model.__call__.side_effect.status_code = 500
        fallback = FallbackChatModel([primary_candidate, fallback_candidate])
        with pytest.raises(ModelFallbackError):
            fallback()

    def test_non_eligible_error_raises_immediately(self, primary_candidate):
        """Non-eligible errors (e.g. context overflow) are not caught."""
        primary_candidate.model.__call__ = AsyncMock(
            side_effect=Exception("context overflow"),
        )
        fallback = FallbackChatModel([primary_candidate])
        with pytest.raises(Exception, match="context overflow"):
            fallback()

    def test_cooldown_skips_failed_candidate(
        self,
        primary_candidate,
        fallback_candidate,
    ):
        """After a failure, the candidate is on cooldown."""
        primary_candidate.model.__call__ = AsyncMock(
            side_effect=Exception("rate limit"),
        )
        primary_candidate.model.__call__.side_effect.status_code = 429
        fallback_candidate.model.__call__ = AsyncMock(
            return_value="fallback-ok",
        )
        fallback = FallbackChatModel([primary_candidate, fallback_candidate])
        result = fallback()
        assert result == "fallback-ok"
        # Primary should be on cooldown now
        assert CooldownManager.is_on_cooldown(primary_candidate.label) is True

    async def test_stream_fallback_before_first_chunk(
        self,
        primary_candidate,
        fallback_candidate,
    ):
        """Streaming: primary stream fails before first chunk, fallback succeeds."""
        # Mock primary model to return an async generator that fails before yielding
        async def failing_stream():
            raise Exception("network error")

        primary_candidate.model.__call__ = AsyncMock(
            return_value=failing_stream(),
        )
        primary_candidate.model.__call__.side_effect = None

        # Mock fallback model to return a successful async generator
        async def success_stream():
            yield "chunk-a"
            yield "chunk-b"

        fallback_candidate.model.__call__ = AsyncMock(
            return_value=success_stream(),
        )
        fallback = FallbackChatModel([primary_candidate, fallback_candidate])

        # Collect streamed results
        results = []
        async for chunk in fallback():
            results.append(chunk)

        assert results == ["chunk-a", "chunk-b"]

    async def test_stream_primary_success(self, primary_candidate):
        """Streaming: primary stream succeeds, no fallback needed."""
        async def success_stream():
            yield "chunk-x"
            yield "chunk-y"

        primary_candidate.model.__call__ = AsyncMock(
            return_value=success_stream(),
        )
        primary_candidate.model.__call__.side_effect = None
        fallback = FallbackChatModel([primary_candidate])

        results = []
        async for chunk in fallback():
            results.append(chunk)

        assert results == ["chunk-x", "chunk-y"]


# ---- Error classification tests -----------------------------------------


class TestErrorClassification:
    """Tests for error classification functions."""

    def test_retryable_error(self):
        """429 is retryable."""
        exc = Exception("rate limit")
        exc.status_code = 429
        # We can't easily test is_retryable_llm_error without mocking
        # the SDK classes, but we can test is_fallback_eligible_error
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
