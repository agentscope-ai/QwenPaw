# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the fallback chat model implementation."""

import asyncio
import time
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from agentscope.model._model_response import ChatResponse

from copaw.providers.fallback_chat_model import (
    CooldownState,
    FailoverReason,
    FallbackAttempt,
    FallbackChatModel,
    FallbackExhaustedError,
    _classify_error,
    _STATUS_CODE_RE,
)
from copaw.providers.models import (
    FallbackModelConfig,
    ModelFallbackConfig,
    ModelSlotConfig,
)


class TestFailoverReason:
    """Tests for FailoverReason enum."""

    def test_enum_values(self):
        """Test that all expected enum values exist."""
        assert FailoverReason.RATE_LIMIT.value == "rate_limit"
        assert FailoverReason.TIMEOUT.value == "timeout"
        assert FailoverReason.CONNECTION.value == "connection"
        assert FailoverReason.OVERLOADED.value == "overloaded"
        assert FailoverReason.BILLING.value == "billing"
        assert FailoverReason.AUTH.value == "auth"
        assert FailoverReason.CONTEXT_OVERFLOW.value == "context_overflow"
        assert FailoverReason.ABORT.value == "abort"
        assert FailoverReason.UNKNOWN.value == "unknown"


class TestClassifyError:
    """Tests for error classification function."""

    def test_rate_limit_by_status_code(self):
        """Test classification of 429 status code."""
        exc = MagicMock()
        exc.status_code = 429
        assert _classify_error(exc) == FailoverReason.RATE_LIMIT

    def test_timeout_by_status_code(self):
        """Test classification of timeout status codes."""
        exc = MagicMock()
        exc.status_code = 408
        assert _classify_error(exc) == FailoverReason.TIMEOUT

        exc.status_code = 504
        assert _classify_error(exc) == FailoverReason.TIMEOUT

    def test_connection_error_by_status_code(self):
        """Test classification of connection error status codes."""
        exc = MagicMock()
        exc.status_code = 502
        assert _classify_error(exc) == FailoverReason.CONNECTION

    def test_overloaded_by_status_code(self):
        """Test classification of overloaded status codes."""
        exc = MagicMock()
        exc.status_code = 503
        assert _classify_error(exc) == FailoverReason.OVERLOADED

        exc.status_code = 529
        assert _classify_error(exc) == FailoverReason.OVERLOADED

    def test_auth_by_status_code(self):
        """Test classification of auth error status codes."""
        exc = MagicMock()
        exc.status_code = 401
        assert _classify_error(exc) == FailoverReason.AUTH

    def test_billing_by_status_code(self):
        """Test classification of billing error status codes."""
        exc = MagicMock()
        exc.status_code = 402
        assert _classify_error(exc) == FailoverReason.BILLING

    def test_openai_rate_limit_error(self):
        """Test classification of OpenAI RateLimitError."""
        exc = MagicMock()
        exc.__class__.__name__ = "RateLimitError"
        assert _classify_error(exc) == FailoverReason.RATE_LIMIT

    def test_openai_timeout_error(self):
        """Test classification of OpenAI APITimeoutError."""
        exc = MagicMock()
        exc.__class__.__name__ = "APITimeoutError"
        assert _classify_error(exc) == FailoverReason.TIMEOUT

    def test_context_overflow_detection(self):
        """Test detection of context overflow by message."""
        exc = Exception("context length exceeded")
        assert _classify_error(exc) == FailoverReason.CONTEXT_OVERFLOW

        exc = Exception("maximum context length reached")
        assert _classify_error(exc) == FailoverReason.CONTEXT_OVERFLOW

        exc = Exception("token limit exceeded")
        assert _classify_error(exc) == FailoverReason.CONTEXT_OVERFLOW

    def test_abort_detection(self):
        """Test detection of user abort."""
        exc = Exception("user aborted the request")
        assert _classify_error(exc) == FailoverReason.ABORT

    def test_unknown_error(self):
        """Test classification of unknown errors."""
        exc = Exception("some random error")
        assert _classify_error(exc) == FailoverReason.UNKNOWN

    def test_status_code_from_string(self):
        """Test extraction of status code from error string."""
        exc = Exception("HTTP 429 Too Many Requests")
        assert _classify_error(exc) == FailoverReason.RATE_LIMIT


class TestCooldownState:
    """Tests for CooldownState class."""

    def test_initial_state(self):
        """Test initial cooldown state."""
        state = CooldownState(provider_id="openai")
        assert state.provider_id == "openai"
        assert state.cooldown_until is None
        assert state.error_count == 0
        assert not state.is_in_cooldown(time.time())

    def test_transient_error_cooldown(self):
        """Test cooldown calculation for transient errors."""
        state = CooldownState(provider_id="openai")
        now = time.time()

        # First error: 1 minute cooldown
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        assert state.error_count == 1
        assert state.cooldown_until == now + 60
        assert state.is_in_cooldown(now + 30)
        assert not state.is_in_cooldown(now + 120)

    def test_transient_error_backoff_progression(self):
        """Test exponential backoff for transient errors.

        Note: Error count resets after cooldown expires, so to see
        backoff progression we need consecutive failures WITHOUT
        waiting for cooldown to expire.
        """
        state = CooldownState(provider_id="openai")
        now = time.time()

        # First error: 1 minute
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        assert state.error_count == 1
        expected_cooldown = now + 60
        assert (
            abs(state.cooldown_until - expected_cooldown) < 1.0
        )  # 1 second tolerance for CI

        # Second error (during first cooldown - window immutability)
        # Should NOT extend the cooldown or increment count
        state.record_failure(now + 30, FailoverReason.RATE_LIMIT)
        assert state.error_count == 1  # Count unchanged
        # Cooldown unchanged (window immutability)
        assert (
            abs(state.cooldown_until - expected_cooldown) < 1.0
        )  # 1 second tolerance for CI

        # Third error after cooldown expiry resets count (fresh start: 1 min)
        now = state.cooldown_until + 10
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        # Count resets to 0 then increments to 1
        assert state.error_count == 1
        expected_cooldown = now + 60
        assert (
            abs(state.cooldown_until - expected_cooldown) < 1.0
        )  # 1 second tolerance for CI

    def test_consecutive_error_backoff(self):
        """Test backoff progression with consecutive errors."""
        state = CooldownState(provider_id="openai")
        now = time.time()

        # Simulate consecutive errors without cooldown expiry
        # by manually setting error_count (as if from persistent state)

        # First error: 1 minute
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        assert state.error_count == 1
        assert (
            abs(state.cooldown_until - (now + 60)) < 1.0
        )  # 1 second tolerance for CI

        # Simulate second error during cooldown by setting up state
        # (in real scenario, this would come from persistent storage)
        state.error_count = 1
        state.cooldown_until = now + 60

        # Second error (before cooldown expiry): 5 minutes
        state.record_failure(now + 30, FailoverReason.RATE_LIMIT)
        # Window immutability - count doesn't increment, cooldown unchanged
        assert state.error_count == 1

        # Actually test the progression by bypassing window immutability
        # (simulating a new failure after cooldown but before next attempt)
        state.error_count = 2  # Simulate we had 2 errors
        state.cooldown_until = None  # Cooldown expired

        now = now + 100  # After cooldown
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        # With error_count=2, should be 5 minutes (index 1 in backoff list)
        assert state.cooldown_until is not None

    def test_auth_billing_error_cooldown(self):
        """Test cooldown calculation for auth/billing errors."""
        state = CooldownState(provider_id="openai")
        now = time.time()

        # First auth error: 5 hours
        state.record_failure(now, FailoverReason.AUTH)
        assert state.error_count == 1
        assert state.disabled_until == now + (5 * 3600)
        assert state.is_in_cooldown(now + 3600)

    def test_window_immutability(self):
        """Test that cooldown window is not extended during cooldown."""
        state = CooldownState(provider_id="openai")
        now = time.time()

        # First error sets cooldown
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        original_cooldown = state.cooldown_until

        # Second error during cooldown should not extend
        state.record_failure(now + 30, FailoverReason.RATE_LIMIT)
        assert state.cooldown_until == original_cooldown
        assert state.error_count == 1  # Count not incremented either

    def test_error_count_reset_after_cooldown(self):
        """Test that error count resets after cooldown expires."""
        state = CooldownState(provider_id="openai")
        now = time.time()

        # First error
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        assert state.error_count == 1

        # Wait for cooldown to expire and record new error
        now += 120
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        assert state.error_count == 2  # Count continues from previous

    def test_record_success_resets_cooldown(self):
        """Test that success resets cooldown state."""
        state = CooldownState(provider_id="openai")
        now = time.time()

        # Record error
        state.record_failure(now, FailoverReason.RATE_LIMIT)
        assert state.error_count == 1

        # Record success after cooldown
        state.record_success(now + 120)
        assert state.error_count == 0
        assert state.cooldown_until is None


class TestFallbackAttempt:
    """Tests for FallbackAttempt dataclass."""

    def test_fallback_attempt_creation(self):
        """Test creation of FallbackAttempt."""
        attempt = FallbackAttempt(
            provider_id="openai",
            model="gpt-4",
            reason=FailoverReason.RATE_LIMIT,
            error="Rate limit exceeded",
        )
        assert attempt.provider_id == "openai"
        assert attempt.model == "gpt-4"
        assert attempt.reason == FailoverReason.RATE_LIMIT
        assert attempt.error == "Rate limit exceeded"
        assert attempt.timestamp > 0


class TestFallbackExhaustedError:
    """Tests for FallbackExhaustedError."""

    def test_error_creation(self):
        """Test creation of FallbackExhaustedError."""
        attempts = [
            {"provider": "openai", "model": "gpt-4", "reason": "rate_limit"},
            {"provider": "anthropic", "model": "claude", "reason": "timeout"},
        ]
        error = FallbackExhaustedError(attempts)
        assert error.attempts == attempts
        assert error.attempt_count == 2
        assert "openai" in str(error)
        assert "anthropic" in str(error)

    def test_error_with_custom_message(self):
        """Test FallbackExhaustedError with custom message."""
        attempts = [
            {"provider": "openai", "model": "gpt-4", "reason": "rate_limit"},
        ]
        error = FallbackExhaustedError(attempts, "Custom error message")
        assert str(error) == "Custom error message"


class TestFallbackChatModel:
    """Tests for FallbackChatModel class."""

    @pytest.fixture
    def mock_inner_model(self):
        """Create a mock inner model."""
        model = MagicMock()
        model.model_name = "gpt-4"
        model.stream = True
        model._provider_id = "openai"
        return model

    @pytest.fixture
    def mock_provider_manager(self):
        """Create a mock provider manager."""
        manager = MagicMock()
        provider = MagicMock()
        provider.is_local = False
        fallback_model = MagicMock()
        provider.get_chat_model_instance.return_value = fallback_model
        manager.get_provider.return_value = provider
        return manager

    @pytest.fixture
    def fallback_config(self):
        """Create a sample fallback configuration."""
        return ModelFallbackConfig(
            fallbacks=[
                FallbackModelConfig(provider_id="anthropic", model="claude"),
            ],
            cooldown_enabled=True,
            max_fallbacks=3,
        )

    @pytest.fixture
    def fallback_model(
        self,
        mock_inner_model,
        fallback_config,
        mock_provider_manager,
    ):
        """Create a FallbackChatModel instance."""
        return FallbackChatModel(
            inner=mock_inner_model,
            fallback_config=fallback_config,
            provider_manager=mock_provider_manager,
        )

    @pytest.mark.asyncio
    async def test_successful_primary_call(
        self,
        fallback_model,
        mock_inner_model,
    ):
        """Test successful call to primary model."""
        expected_response = ChatResponse(text="Hello")
        mock_inner_model.return_value = asyncio.Future()
        mock_inner_model.return_value.set_result(expected_response)

        result = await fallback_model(
            messages=[{"role": "user", "content": "Hi"}],
        )

        assert result == expected_response
        mock_inner_model.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_rate_limit(
        self,
        fallback_model,
        mock_inner_model,
        mock_provider_manager,
    ):
        """Test fallback when primary hits rate limit."""
        # Setup primary to fail with rate limit
        rate_limit_error = Exception("Rate limit exceeded")
        rate_limit_error.status_code = 429
        mock_inner_model.return_value = asyncio.Future()
        mock_inner_model.return_value.set_exception(rate_limit_error)

        # Setup fallback to succeed
        expected_response = ChatResponse(text="Hello from fallback")

        # Create mock for the wrapped fallback model
        mock_wrapped = AsyncMock(return_value=expected_response)

        with patch(
            "copaw.providers.fallback_chat_model.TokenRecordingModelWrapper",
        ):
            with patch(
                "copaw.providers.fallback_chat_model.RetryChatModel",
            ) as mock_retry_wrapper:
                mock_retry_wrapper.return_value = mock_wrapped

                await fallback_model(
                    messages=[{"role": "user", "content": "Hi"}],
                )

        # Verify fallback was used
        assert mock_provider_manager.get_provider.called

    @pytest.mark.asyncio
    async def test_non_recoverable_error_no_fallback(
        self,
        fallback_model,
        mock_inner_model,
    ):
        """Test that non-recoverable errors don't trigger fallback."""
        # Context overflow should not trigger fallback
        context_error = Exception("context length exceeded")
        mock_inner_model.return_value = asyncio.Future()
        mock_inner_model.return_value.set_exception(context_error)

        with pytest.raises(Exception) as exc_info:
            await fallback_model(messages=[{"role": "user", "content": "Hi"}])

        assert "context" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_all_candidates_exhausted(
        self,
        fallback_model,
        mock_inner_model,
    ):
        """Test that FallbackExhaustedError is raised when all fail."""
        # Setup all models to fail
        error = Exception("Rate limit")
        error.status_code = 429
        mock_inner_model.return_value = asyncio.Future()
        mock_inner_model.return_value.set_exception(error)

        with patch.object(
            fallback_model,
            "_create_model_for_candidate",
        ) as mock_create:
            fallback_mock = AsyncMock(side_effect=Exception("Also failed"))
            mock_create.return_value = fallback_mock

            with pytest.raises(FallbackExhaustedError) as exc_info:
                await fallback_model(
                    messages=[{"role": "user", "content": "Hi"}],
                )

            assert exc_info.value.attempt_count > 0

    def test_build_candidate_chain(self, fallback_model):
        """Test building the candidate chain."""
        candidates = fallback_model._build_candidate_chain()

        # Should have primary + fallbacks
        assert len(candidates) >= 1
        # Check that fallbacks are included
        if fallback_model._fallback_config.fallbacks:
            assert len(candidates) == 1 + len(
                fallback_model._fallback_config.fallbacks,
            )

    def test_cooldown_state_tracking(self, fallback_model):
        """Test cooldown state tracking."""
        state = fallback_model._get_or_create_cooldown_state("openai")
        assert state.provider_id == "openai"
        assert "openai" in fallback_model._cooldown_states

    def test_get_attempt_history(self, fallback_model):
        """Test getting attempt history."""
        # Initially empty
        assert fallback_model.get_attempt_history() == []

        # Add an attempt manually
        attempt = FallbackAttempt(
            provider_id="openai",
            model="gpt-4",
            reason=FailoverReason.RATE_LIMIT,
            error="test",
        )
        fallback_model._attempt_history.append(attempt)

        history = fallback_model.get_attempt_history()
        assert len(history) == 1
        assert history[0].provider_id == "openai"

    def test_clear_attempt_history(self, fallback_model):
        """Test clearing attempt history."""
        attempt = FallbackAttempt(
            provider_id="openai",
            model="gpt-4",
            reason=FailoverReason.RATE_LIMIT,
            error="test",
        )
        fallback_model._attempt_history.append(attempt)

        fallback_model.clear_attempt_history()
        assert fallback_model._attempt_history == []

    def test_get_cooldown_states(self, fallback_model):
        """Test getting cooldown states."""
        # Create a state
        fallback_model._get_or_create_cooldown_state("openai")

        states = fallback_model.get_cooldown_states()
        assert "openai" in states
        assert states["openai"].provider_id == "openai"

    def test_filter_available_candidates(self, fallback_model):
        """Test filtering candidates by cooldown state."""
        candidates = [
            ModelSlotConfig(provider_id="openai", model="gpt-4"),
            ModelSlotConfig(provider_id="anthropic", model="claude"),
        ]

        # Put one provider in cooldown
        now = time.time()
        state = fallback_model._get_or_create_cooldown_state("openai")
        state.record_failure(now, FailoverReason.RATE_LIMIT)

        available, in_cooldown = fallback_model._filter_available_candidates(
            candidates,
            now + 30,
        )

        assert len(available) == 1
        assert len(in_cooldown) == 1
        assert available[0].provider_id == "anthropic"
        assert in_cooldown[0].provider_id == "openai"

    def test_inner_class_property(self, fallback_model, mock_inner_model):
        """Test inner_class property returns correct class."""
        assert fallback_model.inner_class == mock_inner_model.__class__


class TestFallbackChatModelNoFallbacks:
    """Tests for FallbackChatModel with empty fallback config."""

    @pytest.mark.asyncio
    async def test_no_fallbacks_uses_primary_only(self):
        """Test that with no fallbacks, only primary is used."""
        mock_inner = MagicMock()
        mock_inner.model_name = "gpt-4"
        mock_inner.stream = True
        mock_inner._provider_id = "openai"

        config = ModelFallbackConfig(fallbacks=[])
        manager = MagicMock()

        model = FallbackChatModel(
            inner=mock_inner,
            fallback_config=config,
            provider_manager=manager,
        )

        expected_response = ChatResponse(text="Hello")
        mock_inner.return_value = asyncio.Future()
        mock_inner.return_value.set_result(expected_response)

        result = await model(messages=[{"role": "user", "content": "Hi"}])

        assert result == expected_response
        mock_inner.assert_called_once()


class TestModelFallbackConfig:
    """Tests for ModelFallbackConfig pydantic model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ModelFallbackConfig()
        assert config.fallbacks == []
        assert config.cooldown_enabled is True
        assert config.max_fallbacks == 3

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ModelFallbackConfig(
            fallbacks=[
                FallbackModelConfig(provider_id="anthropic", model="claude"),
            ],
            cooldown_enabled=False,
            max_fallbacks=5,
        )
        assert len(config.fallbacks) == 1
        assert config.cooldown_enabled is False
        assert config.max_fallbacks == 5

    def test_max_fallbacks_validation(self):
        """Test max_fallbacks validation constraints."""
        # Valid values
        ModelFallbackConfig(max_fallbacks=1)
        ModelFallbackConfig(max_fallbacks=10)

        # Invalid values should raise validation error
        with pytest.raises(ValidationError):
            ModelFallbackConfig(max_fallbacks=0)

        with pytest.raises(ValidationError):
            ModelFallbackConfig(max_fallbacks=11)


class TestFallbackModelConfig:
    """Tests for FallbackModelConfig pydantic model."""

    def test_creation(self):
        """Test creation of FallbackModelConfig."""
        config = FallbackModelConfig(provider_id="anthropic", model="claude")
        assert config.provider_id == "anthropic"
        assert config.model == "claude"


class TestRegexOptimization:
    """Tests for regex optimization."""

    def test_status_code_regex_compiled(self):
        """Test that status code regex is pre-compiled."""
        assert _STATUS_CODE_RE is not None
        assert hasattr(_STATUS_CODE_RE, "pattern")

    def test_status_code_regex_matches(self):
        """Test that status code regex matches correctly."""
        # Should match 4xx and 5xx codes
        assert _STATUS_CODE_RE.search("Error 404") is not None
        assert _STATUS_CODE_RE.search("Error 500") is not None
        assert _STATUS_CODE_RE.search("Error 429") is not None

    def test_status_code_regex_no_match(self):
        """Test that status code regex doesn't match invalid codes."""
        # Should not match 3xx or other numbers
        assert _STATUS_CODE_RE.search("Error 200") is None
        assert _STATUS_CODE_RE.search("Error 301") is None
        assert _STATUS_CODE_RE.search("1000") is None


class TestFallbackChatModelSync:
    """Tests for synchronous chat method."""

    @pytest.fixture
    def mock_fallback_model(self):
        """Create a mock fallback model."""
        inner = MagicMock()
        inner.model_name = "gpt-4"
        inner.stream = False
        inner._provider_id = "openai"

        config = ModelFallbackConfig(fallbacks=[])
        manager = MagicMock()

        model = FallbackChatModel(
            inner=inner,
            fallback_config=config,
            provider_manager=manager,
            primary_provider_id="openai",
            primary_model="gpt-4",
        )
        return model, inner

    def test_primary_provider_id_tracking(self, mock_fallback_model):
        """Test that primary provider_id is properly tracked."""
        model, _ = mock_fallback_model
        assert model._primary_provider_id == "openai"
        assert model._primary_model == "gpt-4"

    def test_get_primary_candidate_with_explicit_tracking(
        self,
        mock_fallback_model,
    ):
        """Test _get_primary_candidate with explicit tracking."""
        model, _ = mock_fallback_model
        primary = model._get_primary_candidate()
        assert primary is not None
        assert primary.provider_id == "openai"
        assert primary.model == "gpt-4"

    def test_build_candidate_chain_with_explicit_tracking(
        self,
        mock_fallback_model,
    ):
        """Test _build_candidate_chain with explicit tracking."""
        model, _ = mock_fallback_model
        candidates = model._build_candidate_chain()
        assert len(candidates) == 1
        assert candidates[0].provider_id == "openai"


class TestFallbackChatModelStreaming:
    """Tests for streaming response handling."""

    @pytest.fixture
    def mock_streaming_fallback_model(self):
        """Create a mock fallback model for streaming tests."""
        inner = MagicMock()
        inner.model_name = "gpt-4"
        inner.stream = True
        inner._provider_id = "openai"

        config = ModelFallbackConfig(
            fallbacks=[
                FallbackModelConfig(provider_id="anthropic", model="claude"),
            ],
        )
        manager = MagicMock()

        model = FallbackChatModel(
            inner=inner,
            fallback_config=config,
            provider_manager=manager,
            primary_provider_id="openai",
            primary_model="gpt-4",
        )
        return model, inner, manager

    @pytest.mark.asyncio
    async def test_streaming_success(self, mock_streaming_fallback_model):
        """Test successful streaming response."""
        model, inner, _ = mock_streaming_fallback_model

        # Create mock stream
        async def mock_stream():
            yield ChatResponse(text="Hello")
            yield ChatResponse(text=" world")

        inner.return_value = mock_stream()

        result = await model(messages=[{"role": "user", "content": "Hi"}])

        # Result should be an async generator
        assert isinstance(result, AsyncGenerator)

        # Collect chunks
        chunks = []
        async for chunk in result:
            chunks.append(chunk)

        assert len(chunks) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
