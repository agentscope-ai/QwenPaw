# -*- coding: utf-8 -*-
"""Tests for shared retry and cross-model fallback policy."""

from __future__ import annotations

from dataclasses import asdict

import anthropic
import httpx
import openai
import pytest

from qwenpaw.providers.model_error_policy import classify_model_error


class HttpError(Exception):
    """Exception carrying a provider-style status code."""

    def __init__(self, status_code: int, message: str = "error") -> None:
        super().__init__(message)
        self.status_code = status_code


class ResponseStatusError(Exception):
    """Exception exposing status only through its response."""

    def __init__(self, status_code: int, message: str = "error") -> None:
        super().__init__(message)
        self.response = type(
            "Response",
            (),
            {"status_code": status_code},
        )()


class CodeStatusError(Exception):
    """Exception exposing status only through its code attribute."""

    def __init__(self, code: int, message: str = "error") -> None:
        super().__init__(message)
        self.code = code


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 529])
def test_transient_http_errors_allow_retry_and_fallback(status: int) -> None:
    decision = classify_model_error(HttpError(status))

    assert decision.retryable is True
    assert decision.fallback_eligible is True


@pytest.mark.parametrize("status", [400, 401, 403, 422])
def test_permanent_http_errors_do_not_fallback(status: int) -> None:
    decision = classify_model_error(HttpError(status))

    assert decision.retryable is False
    assert decision.fallback_eligible is False


@pytest.mark.parametrize(
    "message",
    [
        "quota exceeded",
        "quota_exceeded",
        "insufficient quota",
        "insufficient_quota",
    ],
)
def test_client_quota_errors_fallback_without_retry(message: str) -> None:
    decision = classify_model_error(HttpError(400, message))

    assert asdict(decision) == {
        "kind": "quota_exceeded",
        "status_code": 400,
        "retryable": False,
        "fallback_eligible": True,
    }


@pytest.mark.parametrize(
    "message",
    [
        "rate limit exceeded",
        "rate_limit_exceeded",
        "too many requests",
        "too_many_requests",
    ],
)
def test_client_rate_limit_messages_allow_retry_and_fallback(
    message: str,
) -> None:
    decision = classify_model_error(HttpError(400, message))

    assert asdict(decision) == {
        "kind": "rate_limited",
        "status_code": 400,
        "retryable": True,
        "fallback_eligible": True,
    }


@pytest.mark.parametrize(
    "message",
    [
        "Invalid request: quota must be a positive integer",
        "Invalid parameter: rate limit is not supported",
    ],
)
def test_unrelated_client_messages_remain_bad_request(message: str) -> None:
    decision = classify_model_error(HttpError(400, message))

    assert asdict(decision) == {
        "kind": "bad_request",
        "status_code": 400,
        "retryable": False,
        "fallback_eligible": False,
    }


def test_structured_quota_code_fallbacks_without_retry() -> None:
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(400, request=request)
    error = openai.BadRequestError(
        "Error code: 400",
        response=response,
        body={
            "error": {
                "code": "insufficient_quota",
                "type": "invalid_request_error",
            },
        },
    )

    decision = classify_model_error(error)

    assert asdict(decision) == {
        "kind": "quota_exceeded",
        "status_code": 400,
        "retryable": False,
        "fallback_eligible": True,
    }


def test_top_level_structured_quota_code_fallbacks_without_retry() -> None:
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(400, request=request)
    error = openai.BadRequestError(
        "Error code: 400",
        response=response,
        body={"code": "insufficient_quota"},
    )

    decision = classify_model_error(error)

    assert asdict(decision) == {
        "kind": "quota_exceeded",
        "status_code": 400,
        "retryable": False,
        "fallback_eligible": True,
    }


async def test_openai_string_quota_error_fallbacks_without_retry() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "quota_exceeded"},
            request=request,
        )

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(
        transport=transport,
        trust_env=False,
    ) as http_client:
        client = openai.AsyncOpenAI(
            api_key="dummy",
            base_url="https://example.invalid/v1",
            http_client=http_client,
            max_retries=0,
        )
        with pytest.raises(openai.BadRequestError) as exc_info:
            await client.chat.completions.create(
                model="primary",
                messages=[{"role": "user", "content": "hi"}],
            )

    decision = classify_model_error(exc_info.value)

    assert asdict(decision) == {
        "kind": "quota_exceeded",
        "status_code": 400,
        "retryable": False,
        "fallback_eligible": True,
    }


def test_http_429_quota_remains_retryable() -> None:
    decision = classify_model_error(HttpError(429, "quota exceeded"))

    assert decision.kind == "rate_limited"
    assert decision.retryable is True
    assert decision.fallback_eligible is True


def test_model_not_found_allows_fallback_without_retry() -> None:
    decision = classify_model_error(HttpError(404))

    assert decision.kind == "model_not_found"
    assert decision.retryable is False
    assert decision.fallback_eligible is True


def test_context_overflow_does_not_fallback() -> None:
    decision = classify_model_error(
        HttpError(400, "maximum context length exceeded"),
    )

    assert decision.kind == "context_overflow"
    assert decision.fallback_eligible is False


def test_response_status_is_rate_limited() -> None:
    decision = classify_model_error(ResponseStatusError(429))

    assert decision.status_code == 429
    assert decision.kind == "rate_limited"
    assert decision.retryable is True
    assert decision.fallback_eligible is True


def test_code_status_is_transient() -> None:
    decision = classify_model_error(CodeStatusError(529))

    assert decision.status_code == 529
    assert decision.kind == "transient"
    assert decision.retryable is True


def test_streaming_status_is_transient() -> None:
    decision = classify_model_error(
        Exception("Streaming response failed: [503] unavailable"),
    )

    assert decision.status_code == 503
    assert decision.kind == "transient"
    assert decision.retryable is True


def test_gateway_reported_status_is_transient() -> None:
    """A gateway that reports the status only in the text still retries."""
    decision = classify_model_error(
        Exception("status_code=502, 请联系管理员处理！ (request id: abc123)"),
    )

    assert decision.status_code == 502
    assert decision.kind == "transient"
    assert decision.retryable is True
    assert decision.fallback_eligible is True


def test_gateway_reported_status_on_sdk_error_is_transient() -> None:
    """The OpenAI SDK raises a bare APIError without status_code."""
    error = openai.APIError(
        "status_code=503, upstream is overloaded (request id: abc123)",
        request=None,
        body=None,
    )

    decision = classify_model_error(error)

    assert decision.status_code == 503
    assert decision.kind == "transient"
    assert decision.retryable is True
    assert decision.fallback_eligible is True


def test_gateway_reported_client_error_is_not_retryable() -> None:
    decision = classify_model_error(Exception("status_code=400, bad request"))

    assert decision.status_code == 400
    assert decision.kind == "bad_request"
    assert decision.retryable is False


@pytest.mark.parametrize(
    "message",
    [
        "status_code=200, ok",
        "expected status_code=200 but the gateway hung",
        "status_code=99999, out of range",
        "status code 502, missing the equals sign",
        "request id 502 without a status_code prefix",
        "the upstream returned 502 after retrying",
    ],
)
def test_unrelated_numbers_are_not_read_as_gateway_status(message):
    decision = classify_model_error(Exception(message))

    assert decision.status_code is None
    assert decision.kind == "unknown"
    assert decision.retryable is False


def test_remote_protocol_error_is_transient() -> None:
    decision = classify_model_error(
        httpx.RemoteProtocolError("peer closed connection"),
    )

    assert decision.kind == "transient"
    assert decision.retryable is True


def test_rate_limit_status_precedes_context_heuristic() -> None:
    decision = classify_model_error(
        ResponseStatusError(429, "Too many tokens per minute"),
    )

    assert decision.kind == "rate_limited"
    assert decision.retryable is True


def test_content_safety_does_not_fallback() -> None:
    decision = classify_model_error(
        HttpError(400, "content policy rejected this input"),
    )

    assert decision.kind == "content_safety"
    assert decision.fallback_eligible is False


def test_data_inspection_is_content_safety() -> None:
    decision = classify_model_error(
        HttpError(
            400,
            "Input data may contain inappropriate content; "
            "type=data_inspection_failed",
        ),
    )

    assert decision.kind == "content_safety"
    assert decision.retryable is False
    assert decision.fallback_eligible is False


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda request: httpx.ConnectError(
            f"connection failed for {request.url}",
            request=request,
        ),
        lambda request: httpx.ReadTimeout(
            f"request timed out for {request.url}",
            request=request,
        ),
        lambda request: openai.APIConnectionError(request=request),
        lambda request: openai.APITimeoutError(request=request),
        lambda request: anthropic.APIConnectionError(request=request),
        lambda request: anthropic.APITimeoutError(request=request),
    ],
)
def test_sdk_network_errors_allow_retry_and_fallback(error_factory) -> None:
    method = "POST"
    host = "example.com"
    request = httpx.Request(f"{method}", f"https://{host}")

    decision = classify_model_error(error_factory(request))

    assert decision.kind == "transient"
    assert decision.retryable is True
    assert decision.fallback_eligible is True


def test_unknown_error_does_not_allow_retry_or_fallback() -> None:
    kind = "unexpected"
    decision = classify_model_error(RuntimeError(f"{kind}"))

    assert decision.kind == "unknown"
    assert decision.retryable is False
    assert decision.fallback_eligible is False


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (413, "Content Too Large"),
        (None, "Error code: 413 - rejected"),
        (400, "request body is too large"),
        (500, "Failed to buffer the request body: length limit exceeded"),
        (None, "Failed to buffer the request body: length limit exceeded"),
    ],
)
def test_body_overflow_does_not_retry_or_fallback(status, message):
    assert asdict(classify_model_error(HttpError(status, message))) == {
        "kind": "request_body_overflow",
        "status_code": status,
        "retryable": False,
        "fallback_eligible": False,
    }
