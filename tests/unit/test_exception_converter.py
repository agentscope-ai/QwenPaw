# -*- coding: utf-8 -*-
"""Tests for convert_model_exception error detail propagation."""

from __future__ import annotations

from agentscope_runtime.engine.schemas.exception import (
    ModelContextLengthExceededException,
    ModelExecutionException,
    ModelQuotaExceededException,
    ModelTimeoutException,
    UnauthorizedModelAccessException,
)

from qwenpaw.exceptions import (
    _append_error_detail,
    _extract_error_summary,
    convert_model_exception,
)


# ── helpers ──────────────────────────────────────────────────────────


class _FakeAPIError(Exception):
    """Mimics openai.APIStatusError with status_code & body."""

    def __init__(self, status_code, message, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ── _extract_error_summary ───────────────────────────────────────────


class TestExtractErrorSummary:
    def test_structured_body(self):
        exc = _FakeAPIError(
            402,
            "raw msg",
            body={
                "error": {
                    "message": "Insufficient credits",
                },
            },
        )
        assert _extract_error_summary(exc) == "Insufficient credits"

    def test_fallback_to_str(self):
        exc = ValueError("something broke")
        assert _extract_error_summary(exc) == "something broke"

    def test_multiline_takes_first(self):
        exc = RuntimeError("line1\nline2\nline3")
        assert _extract_error_summary(exc) == "line1"

    def test_truncation(self):
        long_msg = "x" * 300
        exc = RuntimeError(long_msg)
        assert len(_extract_error_summary(exc)) == 200


# ── _append_error_detail ────────────────────────────────────────────


class TestAppendErrorDetail:
    def test_appends_summary(self):
        converted = ModelExecutionException("test-model")
        original = _FakeAPIError(
            500,
            "server exploded",
        )
        result = _append_error_detail(converted, original)
        assert "Reason: server exploded" in result.message
        assert result.message.startswith(
            "Error occurred during execution of model: test-model",
        )

    def test_returns_same_object(self):
        converted = ModelExecutionException("m")
        original = RuntimeError("boom")
        assert _append_error_detail(converted, original) is converted


# ── convert_model_exception detail propagation ──────────────────────


class TestConvertModelExceptionDetail:
    def test_402_insufficient_credits(self):
        exc = _FakeAPIError(
            402,
            "Error code: 402",
            body={
                "error": {
                    "message": ("This request requires more credits"),
                },
            },
        )
        result = convert_model_exception(exc, "deepseek/v4")
        assert isinstance(result, ModelExecutionException)
        assert "more credits" in result.message

    def test_401_unauthorized(self):
        exc = _FakeAPIError(401, "Invalid API key")
        result = convert_model_exception(exc, "gpt-4")
        assert isinstance(
            result,
            UnauthorizedModelAccessException,
        )
        assert "Invalid API key" in result.message

    def test_429_rate_limit(self):
        exc = _FakeAPIError(429, "Rate limit exceeded")
        result = convert_model_exception(exc, "gpt-4")
        assert isinstance(result, ModelQuotaExceededException)
        assert "Rate limit" in result.message

    def test_context_length(self):
        exc = _FakeAPIError(
            400,
            "maximum context length exceeded",
        )
        result = convert_model_exception(exc, "gpt-4")
        assert isinstance(
            result,
            ModelContextLengthExceededException,
        )
        assert "context length" in result.message

    def test_timeout(self):
        exc = _FakeAPIError(408, "Request timed out")
        result = convert_model_exception(exc, "gpt-4")
        assert isinstance(result, ModelTimeoutException)
        assert "timed out" in result.message

    def test_generic_500(self):
        exc = _FakeAPIError(500, "Internal server error")
        result = convert_model_exception(exc, "gpt-4")
        assert isinstance(result, ModelExecutionException)
        assert "Internal server error" in result.message

    def test_details_preserved(self):
        exc = _FakeAPIError(500, "boom")
        result = convert_model_exception(exc, "gpt-4")
        assert result.details["original_error_message"] == "boom"
        assert result.details["status_code"] == 500
