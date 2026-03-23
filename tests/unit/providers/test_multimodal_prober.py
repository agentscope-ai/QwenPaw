# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for multimodal capability prober functions.

After the refactoring, probe logic lives in OpenAIProvider.
This file tests via OpenAIProvider instance methods.

Validates: Requirements 4.1, 4.2, 4.3, 4.9
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import APIStatusError

from copaw.providers.multimodal_prober import (
    ProbeResult,
    _is_media_keyword_error,
)
from copaw.providers.openai_provider import OpenAIProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider() -> OpenAIProvider:
    return OpenAIProvider(
        id="openai",
        name="OpenAI",
        base_url="https://api.example.com/v1",
        api_key="sk-test",
    )


def _make_api_error(
    status_code: int,
    message: str = "error",
) -> APIStatusError:
    """Create an APIStatusError with the given status code."""
    response = httpx.Response(
        status_code,
        request=httpx.Request(
            "POST",
            "https://api.example.com/v1/chat/completions",
        ),
    )
    return APIStatusError(
        message=message,
        response=response,
        body=None,
    )


def _fake_completion(text: str, reasoning: str | None = None):
    """Create a fake chat completion response with the given text content."""
    msg = SimpleNamespace(content=text)
    if reasoning is not None:
        msg.reasoning_content = reasoning
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
    )


# ---------------------------------------------------------------------------
# ProbeResult dataclass
# ---------------------------------------------------------------------------


class TestProbeResult:
    def test_defaults(self) -> None:
        r = ProbeResult()
        assert r.supports_image is False
        assert r.supports_video is False
        assert r.supports_multimodal is False

    def test_image_only(self) -> None:
        r = ProbeResult(supports_image=True)
        assert r.supports_multimodal is True

    def test_video_only(self) -> None:
        r = ProbeResult(supports_video=True)
        assert r.supports_multimodal is True

    def test_both(self) -> None:
        r = ProbeResult(supports_image=True, supports_video=True)
        assert r.supports_multimodal is True


# ---------------------------------------------------------------------------
# OpenAIProvider._probe_image_support
# ---------------------------------------------------------------------------


class TestProbeImageSupport:
    """Tests for OpenAIProvider._probe_image_support."""

    async def test_success_returns_true(self) -> None:
        """When the model correctly identifies the red image, return True."""
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion(
            "red",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_image_support("gpt-4o")

        assert ok is True
        assert "Image supported" in msg

    async def test_wrong_color_returns_false(self) -> None:
        """When the model answers a wrong color, it didn't see the image."""
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion(
            "blue",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_image_support("text-only-model")

        assert ok is False
        assert "did not recognise" in msg.lower()

    async def test_400_api_error_returns_false(self) -> None:
        """When the model returns 400 APIError, return (False, ...)."""
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            400,
            "image_url is not supported",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_image_support("text-only-model")

        assert ok is False
        assert "not supported" in msg.lower()

    async def test_non_400_api_error_with_media_keyword(self) -> None:
        """Non-400 APIError with media keyword still returns False."""
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            422,
            "This model does not support image input",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, _msg = await provider._probe_image_support("some-model")

        assert ok is False


# ---------------------------------------------------------------------------
# OpenAIProvider._probe_video_support
# ---------------------------------------------------------------------------


class TestProbeVideoSupport:
    """Tests for OpenAIProvider._probe_video_support."""

    async def test_success_returns_true(self) -> None:
        """When the model correctly identifies the blue video, return True."""
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion(
            "blue",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_video_support("gpt-4o")

        assert ok is True
        assert "Video supported" in msg

    async def test_wrong_color_returns_false(self) -> None:
        """When the model answers a wrong color, it didn't see the video."""
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion(
            "red",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_video_support("text-only-model")

        assert ok is False
        assert "did not recognise" in msg.lower()

    async def test_400_api_error_returns_false(self) -> None:
        """When both formats return 400 APIError, return (False, ...)."""
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            400,
            "video_url is not supported",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_video_support("text-only-model")

        assert ok is False
        assert "not supported" in msg.lower()

    async def test_base64_400_falls_back_to_url(self) -> None:
        """When base64 gets 400, fallback to HTTP URL and succeed."""
        provider = _make_provider()
        mock_client = AsyncMock()
        call_count = 0

        async def _side_effect(**_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_api_error(400, "Invalid video file")
            return _fake_completion("blue")

        mock_client.chat.completions.create.side_effect = _side_effect

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_video_support("dashscope-model")

        assert ok is True
        assert "Video supported" in msg
        assert call_count == 2


# ---------------------------------------------------------------------------
# Timeout / network error → safe default (False)
# ---------------------------------------------------------------------------


class TestTimeoutSafeDefault:
    """Validates Requirement 4.9: timeout returns False (safe default)."""

    async def test_image_timeout_returns_false(self) -> None:
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = (
            httpx.TimeoutException("Connection timed out")
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_image_support("slow-model")

        assert ok is False
        assert "failed" in msg.lower() or "timed out" in msg.lower()

    async def test_video_timeout_returns_false(self) -> None:
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = (
            httpx.TimeoutException("Connection timed out")
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_video_support("slow-model")

        assert ok is False
        assert "failed" in msg.lower() or "timed out" in msg.lower()

    async def test_connection_error_returns_false(self) -> None:
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = ConnectionError(
            "Connection refused",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            ok, msg = await provider._probe_image_support("unreachable-model")

        assert ok is False
        assert "failed" in msg.lower()


# ---------------------------------------------------------------------------
# probe_model_multimodal (combines image + video)
# ---------------------------------------------------------------------------


class TestProbeMultimodalSupport:
    """Tests for OpenAIProvider.probe_model_multimodal."""

    async def test_both_supported(self) -> None:
        """Both image and video succeed → supports_multimodal is True."""
        provider = _make_provider()
        mock_client = AsyncMock()
        call_count = 0

        async def _side_effect(**_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _fake_completion("red")
            return _fake_completion("blue")

        mock_client.chat.completions.create.side_effect = _side_effect

        with patch.object(provider, "_client", return_value=mock_client):
            result = await provider.probe_model_multimodal("vision-model")

        assert result.supports_image is True
        assert result.supports_video is True
        assert result.supports_multimodal is True

    async def test_image_only(self) -> None:
        """Image succeeds, video fails → supports_multimodal is True."""
        provider = _make_provider()
        mock_client = AsyncMock()
        call_count = 0

        async def _side_effect(**_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _fake_completion("red")
            raise _make_api_error(400, "video_url is not supported")

        mock_client.chat.completions.create.side_effect = _side_effect

        with patch.object(provider, "_client", return_value=mock_client):
            result = await provider.probe_model_multimodal("image-only-model")

        assert result.supports_image is True
        assert result.supports_video is False
        assert result.supports_multimodal is True

    async def test_neither_supported(self) -> None:
        """Both fail → supports_multimodal is False."""
        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            400,
            "does not support media input",
        )

        with patch.object(provider, "_client", return_value=mock_client):
            result = await provider.probe_model_multimodal("text-only-model")

        assert result.supports_image is False
        assert result.supports_video is False
        assert result.supports_multimodal is False


# ---------------------------------------------------------------------------
# _is_media_keyword_error
# ---------------------------------------------------------------------------


class TestIsMediaKeywordError:
    """Tests for _is_media_keyword_error helper."""

    @pytest.mark.parametrize(
        "message",
        [
            "This model does not support image input",
            "video_url is not a valid content type",
            "Vision capabilities are not available",
            "Multimodal input is not supported",
            "image_url content type not allowed",
            "This model does not support video",
            "The model does not support this feature",
        ],
    )
    def test_matches_media_keywords(self, message: str) -> None:
        exc = Exception(message)
        assert _is_media_keyword_error(exc) is True

    @pytest.mark.parametrize(
        "message",
        [
            "Rate limit exceeded",
            "Invalid API key",
            "Internal server error",
            "Model not found",
            "Context length exceeded",
        ],
    )
    def test_no_match_for_non_media_errors(self, message: str) -> None:
        exc = Exception(message)
        assert _is_media_keyword_error(exc) is False

    def test_case_insensitive(self) -> None:
        exc = Exception("IMAGE_URL is not supported")
        assert _is_media_keyword_error(exc) is True

    def test_does_not_support_keyword(self) -> None:
        exc = Exception("This endpoint does not support that format")
        assert _is_media_keyword_error(exc) is True


# ---------------------------------------------------------------------------
# Logging verification (Requirements 9.1, 9.2, 9.3, 9.4)
# ---------------------------------------------------------------------------


class TestProbeLogging:
    """Verify INFO/WARNING log output from probe functions."""

    LOGGER_NAME = "copaw.providers.openai_provider"

    @staticmethod
    def _enable_propagation(monkeypatch):
        """Enable propagation so caplog can capture."""
        import logging

        copaw_logger = logging.getLogger("copaw")
        monkeypatch.setattr(copaw_logger, "propagate", True)

    async def test_image_probe_logs_info_on_start_and_complete(
        self,
        monkeypatch,
        caplog,
    ) -> None:
        """Successful image probe emits two INFO logs."""
        import logging

        self._enable_propagation(monkeypatch)

        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion(
            "red",
        )

        with (
            patch.object(provider, "_client", return_value=mock_client),
            caplog.at_level(logging.INFO, logger=self.LOGGER_NAME),
        ):
            await provider._probe_image_support("gpt-4o")

        info_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.INFO and r.name == self.LOGGER_NAME
        ]
        assert any("Image probe start" in m for m in info_messages)
        assert any("Image probe done" in m for m in info_messages)

    async def test_video_probe_logs_info_on_start_and_complete(
        self,
        monkeypatch,
        caplog,
    ) -> None:
        """Successful video probe emits two INFO logs."""
        import logging

        self._enable_propagation(monkeypatch)

        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion(
            "blue",
        )

        with (
            patch.object(provider, "_client", return_value=mock_client),
            caplog.at_level(logging.INFO, logger=self.LOGGER_NAME),
        ):
            await provider._probe_video_support("gpt-4o")

        info_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.INFO and r.name == self.LOGGER_NAME
        ]
        assert any("Video probe start" in m for m in info_messages)
        assert any("Video probe done" in m for m in info_messages)

    async def test_image_probe_logs_warning_on_api_error(
        self,
        monkeypatch,
        caplog,
    ) -> None:
        """APIError during image probe emits a WARNING log."""
        import logging

        self._enable_propagation(monkeypatch)

        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            422,
            "image_url is not supported",
        )

        with (
            patch.object(provider, "_client", return_value=mock_client),
            caplog.at_level(logging.WARNING, logger=self.LOGGER_NAME),
        ):
            await provider._probe_image_support("text-only-model")

        warning_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.WARNING and r.name == self.LOGGER_NAME
        ]
        assert any("Image probe error" in m for m in warning_messages)

    async def test_video_probe_logs_warning_on_general_exception(
        self,
        monkeypatch,
        caplog,
    ) -> None:
        """General Exception during video probe emits a WARNING log."""
        import logging

        self._enable_propagation(monkeypatch)

        provider = _make_provider()
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = RuntimeError(
            "Something went wrong",
        )

        with (
            patch.object(provider, "_client", return_value=mock_client),
            caplog.at_level(logging.WARNING, logger=self.LOGGER_NAME),
        ):
            await provider._probe_video_support("broken-model")

        warning_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.WARNING and r.name == self.LOGGER_NAME
        ]
        assert any("Video probe error" in m for m in warning_messages)
