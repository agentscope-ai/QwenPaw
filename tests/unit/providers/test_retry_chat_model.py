# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.providers.retry_chat_model import (
    RETRYABLE_STATUS_CODES,
    RetryConfig,
    RateLimitConfig,
    _compute_backoff,
    _extract_retry_after,
    _inject_reasoning_content,
    _is_missing_reasoning_content_error,
    _is_rate_limit,
    _is_retryable,
    _normalize_rate_limit_config,
    _normalize_retry_config,
)

# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(RETRYABLE_STATUS_CODES))
def test_is_retryable_status_codes(code: int) -> None:
    exc = Exception()
    exc.status_code = code  # type: ignore[attr-defined]
    assert _is_retryable(exc) is True


def test_is_retryable_non_retryable_code() -> None:
    exc = Exception()
    exc.status_code = 400  # type: ignore[attr-defined]
    assert _is_retryable(exc) is False


def test_is_retryable_no_status_code() -> None:
    assert _is_retryable(Exception("plain")) is False


# ---------------------------------------------------------------------------
# _is_rate_limit
# ---------------------------------------------------------------------------


def test_is_rate_limit_429() -> None:
    exc = Exception()
    exc.status_code = 429  # type: ignore[attr-defined]
    assert _is_rate_limit(exc) is True


def test_is_rate_limit_500() -> None:
    exc = Exception()
    exc.status_code = 500  # type: ignore[attr-defined]
    assert _is_rate_limit(exc) is False


def test_is_rate_limit_no_attr() -> None:
    assert _is_rate_limit(Exception()) is False


# ---------------------------------------------------------------------------
# _is_missing_reasoning_content_error
# ---------------------------------------------------------------------------


def test_missing_reasoning_content_400() -> None:
    exc = Exception("reasoning_content is required")
    exc.status_code = 400  # type: ignore[attr-defined]
    assert _is_missing_reasoning_content_error(exc) is True


def test_missing_reasoning_content_wrong_status() -> None:
    exc = Exception("reasoning_content is required")
    exc.status_code = 500  # type: ignore[attr-defined]
    assert _is_missing_reasoning_content_error(exc) is False


def test_missing_reasoning_content_wrong_message() -> None:
    exc = Exception("some other error")
    exc.status_code = 400  # type: ignore[attr-defined]
    assert _is_missing_reasoning_content_error(exc) is False


# ---------------------------------------------------------------------------
# _inject_reasoning_content
# ---------------------------------------------------------------------------


def test_inject_reasoning_content_via_kwargs() -> None:
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "bye"},
    ]
    result = _inject_reasoning_content((), {"messages": messages})
    assert result is True
    assert messages[1]["reasoning_content"] == " "
    assert "reasoning_content" not in messages[0]
    assert "reasoning_content" not in messages[2]


def test_inject_reasoning_content_via_args() -> None:
    messages = [{"role": "assistant", "content": "x"}]
    result = _inject_reasoning_content((messages,), {})
    assert result is True
    assert messages[0]["reasoning_content"] == " "


def test_inject_reasoning_content_already_present() -> None:
    messages = [
        {"role": "assistant", "content": "x", "reasoning_content": "think"},
    ]
    result = _inject_reasoning_content((), {"messages": messages})
    assert result is False
    assert messages[0]["reasoning_content"] == "think"


def test_inject_reasoning_content_no_messages() -> None:
    assert _inject_reasoning_content((), {}) is False


def test_inject_reasoning_content_empty_list() -> None:
    assert _inject_reasoning_content((), {"messages": []}) is False


# ---------------------------------------------------------------------------
# _extract_retry_after
# ---------------------------------------------------------------------------


def test_extract_retry_after_from_headers() -> None:
    exc = Exception()
    exc.headers = {"Retry-After": "5.0"}  # type: ignore[attr-defined]
    assert _extract_retry_after(exc) == 5.0


def test_extract_retry_after_lowercase() -> None:
    exc = Exception()
    exc.headers = {"retry-after": "3"}  # type: ignore[attr-defined]
    assert _extract_retry_after(exc) == 3.0


def test_extract_retry_after_from_response() -> None:
    exc = Exception()
    exc.response = SimpleNamespace(  # type: ignore[attr-defined]
        headers={"Retry-After": "10"},
    )
    assert _extract_retry_after(exc) == 10.0


def test_extract_retry_after_no_header() -> None:
    exc = Exception()
    exc.headers = {}  # type: ignore[attr-defined]
    assert _extract_retry_after(exc) is None


def test_extract_retry_after_no_attrs() -> None:
    assert _extract_retry_after(Exception()) is None


def test_extract_retry_after_non_numeric() -> None:
    exc = Exception()
    exc.headers = {"Retry-After": "not-a-number"}  # type: ignore[attr-defined]
    assert _extract_retry_after(exc) is None


# ---------------------------------------------------------------------------
# _compute_backoff
# ---------------------------------------------------------------------------


def test_compute_backoff_first_attempt() -> None:
    cfg = RetryConfig(backoff_base=2.0, backoff_cap=60.0)
    assert _compute_backoff(1, cfg) == 2.0


def test_compute_backoff_second_attempt() -> None:
    cfg = RetryConfig(backoff_base=2.0, backoff_cap=60.0)
    assert _compute_backoff(2, cfg) == 4.0


def test_compute_backoff_third_attempt() -> None:
    cfg = RetryConfig(backoff_base=2.0, backoff_cap=60.0)
    assert _compute_backoff(3, cfg) == 8.0


def test_compute_backoff_capped() -> None:
    cfg = RetryConfig(backoff_base=2.0, backoff_cap=5.0)
    assert _compute_backoff(10, cfg) == 5.0


def test_compute_backoff_zero_attempt() -> None:
    cfg = RetryConfig(backoff_base=3.0, backoff_cap=60.0)
    assert _compute_backoff(0, cfg) == 3.0


# ---------------------------------------------------------------------------
# _normalize_retry_config
# ---------------------------------------------------------------------------


def test_normalize_retry_config_none_returns_default() -> None:
    result = _normalize_retry_config(None)
    assert isinstance(result, RetryConfig)


def test_normalize_retry_config_clamps_backoff_base() -> None:
    cfg = RetryConfig(backoff_base=0.01, backoff_cap=60.0)
    result = _normalize_retry_config(cfg)
    assert result.backoff_base == 0.1


def test_normalize_retry_config_cap_at_least_base() -> None:
    cfg = RetryConfig(backoff_base=10.0, backoff_cap=1.0)
    result = _normalize_retry_config(cfg)
    assert result.backoff_cap >= result.backoff_base


def test_normalize_retry_config_min_retries() -> None:
    cfg = RetryConfig(max_retries=0)
    result = _normalize_retry_config(cfg)
    assert result.max_retries >= 1


# ---------------------------------------------------------------------------
# _normalize_rate_limit_config
# ---------------------------------------------------------------------------


def test_normalize_rate_limit_config_none_returns_default() -> None:
    result = _normalize_rate_limit_config(None)
    assert isinstance(result, RateLimitConfig)


def test_normalize_rate_limit_config_clamps() -> None:
    cfg = RateLimitConfig(
        max_concurrent=0,
        max_qpm=-1,
        pause_seconds=0.1,
        jitter_range=-1.0,
        acquire_timeout=1.0,
    )
    result = _normalize_rate_limit_config(cfg)
    assert result.max_concurrent >= 1
    assert result.max_qpm >= 0
    assert result.pause_seconds >= 1.0
    assert result.jitter_range >= 0.0
    assert result.acquire_timeout >= 10.0
