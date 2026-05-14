# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.providers import retry_chat_model as retry


class StatusError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str | None = None,
        headers: dict[str, str] | None = None,
        response: SimpleNamespace | None = None,
    ) -> None:
        super().__init__(message or f"status {status_code}")
        self.status_code = status_code
        self.headers = headers
        self.response = response


class RetryableError(Exception):
    pass


@pytest.fixture(autouse=True)
def clear_sdk_retryables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retry, "_get_openai_retryable", lambda: ())
    monkeypatch.setattr(retry, "_get_anthropic_retryable", lambda: ())
    monkeypatch.setattr(retry, "_get_httpx_retryable", lambda: ())


@pytest.mark.parametrize("status_code", sorted(retry.RETRYABLE_STATUS_CODES))
def test_is_retryable_accepts_transient_status_codes(
    status_code: int,
) -> None:
    assert retry._is_retryable(StatusError(status_code)) is True


def test_is_retryable_accepts_configured_sdk_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retry,
        "_get_openai_retryable",
        lambda: (RetryableError,),
    )

    assert retry._is_retryable(RetryableError("timeout")) is True


def test_is_retryable_rejects_non_transient_errors() -> None:
    assert retry._is_retryable(StatusError(400)) is False
    assert retry._is_retryable(ValueError("bad request")) is False


def test_is_rate_limit_only_accepts_429() -> None:
    assert retry._is_rate_limit(StatusError(429)) is True
    assert retry._is_rate_limit(StatusError(503)) is False


def test_missing_reasoning_content_error_requires_400_and_marker() -> None:
    assert (
        retry._is_missing_reasoning_content_error(
            StatusError(400, "missing field reasoning_content"),
        )
        is True
    )
    assert (
        retry._is_missing_reasoning_content_error(
            StatusError(500, "missing field reasoning_content"),
        )
        is False
    )
    assert (
        retry._is_missing_reasoning_content_error(StatusError(400, "other"))
        is False
    )


def test_inject_reasoning_content_updates_missing_assistant_messages() -> None:
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "assistant", "content": "answer"},
        {
            "role": "assistant",
            "content": "reasoned answer",
            "reasoning_content": "kept",
        },
        {"role": "user", "content": "next"},
    ]

    modified = retry._inject_reasoning_content((), {"messages": messages})

    assert modified is True
    assert messages[1]["reasoning_content"] == " "
    assert messages[2]["reasoning_content"] == "kept"
    assert "reasoning_content" not in messages[0]
    assert "reasoning_content" not in messages[3]


def test_inject_reasoning_content_reads_messages_from_first_arg() -> None:
    messages = [{"role": "assistant", "content": "answer"}]

    assert retry._inject_reasoning_content((messages,), {}) is True
    assert messages == [
        {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": " ",
        },
    ]


def test_inject_reasoning_content_reports_false_when_nothing_changed() -> None:
    assert retry._inject_reasoning_content((), {}) is False
    assert retry._inject_reasoning_content((("not", "messages"),), {}) is False
    assert (
        retry._inject_reasoning_content(
            (),
            {"messages": [{"role": "user", "content": "hello"}]},
        )
        is False
    )


def test_extract_retry_after_reads_direct_and_response_headers() -> None:
    response = SimpleNamespace(headers={"retry-after": "7"})

    assert (
        retry._extract_retry_after(
            StatusError(429, headers={"Retry-After": "2.5"}),
        )
        == 2.5
    )
    assert (
        retry._extract_retry_after(StatusError(429, response=response)) == 7.0
    )


def test_extract_retry_after_ignores_missing_or_invalid_values() -> None:
    assert (
        retry._extract_retry_after(
            StatusError(429, headers={"Retry-After": ""}),
        )
        is None
    )
    assert (
        retry._extract_retry_after(
            StatusError(429, headers={"Retry-After": "not-a-number"}),
        )
        is None
    )
    assert retry._extract_retry_after(StatusError(429)) is None


def test_normalize_retry_config_clamps_unsafe_values() -> None:
    cfg = retry._normalize_retry_config(
        retry.RetryConfig(
            enabled=False,
            max_retries=-4,
            backoff_base=0.01,
            backoff_cap=0.2,
        ),
    )

    assert cfg == retry.RetryConfig(
        enabled=False,
        max_retries=1,
        backoff_base=0.1,
        backoff_cap=0.5,
    )


def test_normalize_rate_limit_config_clamps_unsafe_values() -> None:
    cfg = retry._normalize_rate_limit_config(
        retry.RateLimitConfig(
            max_concurrent=0,
            max_qpm=-10,
            pause_seconds=0.1,
            jitter_range=-2.0,
            acquire_timeout=0.5,
        ),
    )

    assert cfg == retry.RateLimitConfig(
        max_concurrent=1,
        max_qpm=0,
        pause_seconds=1.0,
        jitter_range=0.0,
        acquire_timeout=10.0,
    )


def test_compute_backoff_exponentially_increases_and_caps() -> None:
    cfg = retry.RetryConfig(backoff_base=0.5, backoff_cap=2.0)

    assert [retry._compute_backoff(attempt, cfg) for attempt in range(5)] == [
        0.5,
        0.5,
        1.0,
        2.0,
        2.0,
    ]
