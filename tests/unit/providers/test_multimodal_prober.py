# -*- coding: utf-8 -*-
"""Unit tests for multimodal capability prober functions.

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
    probe_image_support,
    probe_multimodal_support,
    probe_video_support,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api_error(status_code: int, message: str = "error") -> APIStatusError:
    """Create an APIStatusError (subclass of APIError) with the given status code."""
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )
    return APIStatusError(
        message=message,
        response=response,
        body=None,
    )


def _fake_completion(text: str):
    """Create a fake chat completion response with the given text content."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
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
# probe_image_support
# ---------------------------------------------------------------------------


class TestProbeImageSupport:
    """Tests for probe_image_support function."""

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_success_returns_true(self, mock_openai_cls) -> None:
        """When the model correctly identifies the red image, return True."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion("red")
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_image_support(
            "https://api.example.com/v1", "sk-test", "gpt-4o",
        )

        assert ok is True
        assert "Image supported" in msg
        mock_client.chat.completions.create.assert_awaited_once()

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_wrong_color_returns_false(self, mock_openai_cls) -> None:
        """When the model answers a wrong color, it didn't see the image."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion("blue")
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_image_support(
            "https://api.example.com/v1", "sk-test", "text-only-model",
        )

        assert ok is False
        assert "did not recognise" in msg.lower()

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_400_api_error_returns_false(self, mock_openai_cls) -> None:
        """When the model returns 400 APIError, return (False, ...)."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            400, "image_url is not supported",
        )
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_image_support(
            "https://api.example.com/v1", "sk-test", "text-only-model",
        )

        assert ok is False
        assert "not supported" in msg.lower()

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_non_400_api_error_with_media_keyword(
        self, mock_openai_cls,
    ) -> None:
        """Non-400 APIError with media keyword still returns False."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            422, "This model does not support image input",
        )
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_image_support(
            "https://api.example.com/v1", "sk-test", "some-model",
        )

        assert ok is False


# ---------------------------------------------------------------------------
# probe_video_support
# ---------------------------------------------------------------------------


class TestProbeVideoSupport:
    """Tests for probe_video_support function."""

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_success_returns_true(self, mock_openai_cls) -> None:
        """When the model correctly identifies the blue video, return True."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion("blue")
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_video_support(
            "https://api.example.com/v1", "sk-test", "gpt-4o",
        )

        assert ok is True
        assert "Video supported" in msg

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_wrong_color_returns_false(self, mock_openai_cls) -> None:
        """When the model answers a wrong color, it didn't see the video."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion("red")
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_video_support(
            "https://api.example.com/v1", "sk-test", "text-only-model",
        )

        assert ok is False
        assert "did not recognise" in msg.lower()

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_400_api_error_returns_false(self, mock_openai_cls) -> None:
        """When both formats return 400 APIError, return (False, ...)."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            400, "video_url is not supported",
        )
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_video_support(
            "https://api.example.com/v1", "sk-test", "text-only-model",
        )

        assert ok is False
        assert "not supported" in msg.lower()

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_base64_400_falls_back_to_url(self, mock_openai_cls) -> None:
        """When base64 gets 400, fallback to HTTP URL and succeed."""
        mock_client = AsyncMock()
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # base64 attempt rejected
                raise _make_api_error(400, "Invalid video file")
            # HTTP URL attempt succeeds
            return _fake_completion("blue")

        mock_client.chat.completions.create.side_effect = _side_effect
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_video_support(
            "https://api.example.com/v1", "sk-test", "dashscope-model",
        )

        assert ok is True
        assert "Video supported" in msg
        assert call_count == 2


# ---------------------------------------------------------------------------
# Timeout / network error → safe default (False)
# ---------------------------------------------------------------------------


class TestTimeoutSafeDefault:
    """Validates Requirement 4.9: timeout returns False (safe default)."""

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_image_timeout_returns_false(self, mock_openai_cls) -> None:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = httpx.TimeoutException(
            "Connection timed out",
        )
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_image_support(
            "https://api.example.com/v1", "sk-test", "slow-model",
        )

        assert ok is False
        assert "failed" in msg.lower() or "timed out" in msg.lower()

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_video_timeout_returns_false(self, mock_openai_cls) -> None:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = httpx.TimeoutException(
            "Connection timed out",
        )
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_video_support(
            "https://api.example.com/v1", "sk-test", "slow-model",
        )

        assert ok is False
        assert "failed" in msg.lower() or "timed out" in msg.lower()

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_connection_error_returns_false(
        self, mock_openai_cls,
    ) -> None:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = ConnectionError(
            "Connection refused",
        )
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_image_support(
            "https://api.example.com/v1", "sk-test", "unreachable-model",
        )

        assert ok is False
        assert "failed" in msg.lower()


# ---------------------------------------------------------------------------
# probe_multimodal_support (combines image + video)
# ---------------------------------------------------------------------------


class TestProbeMultimodalSupport:
    """Tests for probe_multimodal_support combining image and video probes."""

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_both_supported(self, mock_openai_cls) -> None:
        """Both image and video succeed → supports_multimodal is True."""
        mock_client = AsyncMock()
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _fake_completion("red")
            return _fake_completion("blue")

        mock_client.chat.completions.create.side_effect = _side_effect
        mock_openai_cls.return_value = mock_client

        result = await probe_multimodal_support(
            "https://api.example.com/v1", "sk-test", "vision-model",
        )

        assert result.supports_image is True
        assert result.supports_video is True
        assert result.supports_multimodal is True

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_image_only(self, mock_openai_cls) -> None:
        """Image succeeds, video fails → supports_multimodal is True."""
        mock_client = AsyncMock()
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _fake_completion("red")
            raise _make_api_error(400, "video_url is not supported")

        mock_client.chat.completions.create.side_effect = _side_effect
        mock_openai_cls.return_value = mock_client

        result = await probe_multimodal_support(
            "https://api.example.com/v1", "sk-test", "image-only-model",
        )

        assert result.supports_image is True
        assert result.supports_video is False
        assert result.supports_multimodal is True

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_neither_supported(self, mock_openai_cls) -> None:
        """Both fail → supports_multimodal is False."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            400, "does not support media input",
        )
        mock_openai_cls.return_value = mock_client

        result = await probe_multimodal_support(
            "https://api.example.com/v1", "sk-test", "text-only-model",
        )

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
    """Verify INFO/WARNING log output from probe functions.

    Validates: Requirements 9.1, 9.2, 9.3, 9.4
    """

    LOGGER_NAME = "copaw.providers.multimodal_prober"

    @staticmethod
    def _enable_propagation(monkeypatch):
        """Enable propagation on the copaw logger so caplog can capture records."""
        import logging

        copaw_logger = logging.getLogger("copaw")
        monkeypatch.setattr(copaw_logger, "propagate", True)

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_image_probe_logs_info_on_start_and_complete(
        self, mock_openai_cls, monkeypatch, caplog,
    ) -> None:
        """Successful image probe emits two INFO logs: started + completed."""
        import logging

        self._enable_propagation(monkeypatch)

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion("red")
        mock_openai_cls.return_value = mock_client

        with caplog.at_level(logging.INFO, logger=self.LOGGER_NAME):
            await probe_image_support(
                "https://api.example.com/v1", "sk-test", "gpt-4o",
            )

        info_messages = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO and r.name == self.LOGGER_NAME
        ]
        assert any("Image probe started" in m for m in info_messages), (
            f"Expected 'Image probe started' INFO log, got: {info_messages}"
        )
        assert any("Image probe completed" in m for m in info_messages), (
            f"Expected 'Image probe completed' INFO log, got: {info_messages}"
        )

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_video_probe_logs_info_on_start_and_complete(
        self, mock_openai_cls, monkeypatch, caplog,
    ) -> None:
        """Successful video probe emits two INFO logs: started + completed."""
        import logging

        self._enable_propagation(monkeypatch)

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _fake_completion("blue")
        mock_openai_cls.return_value = mock_client

        with caplog.at_level(logging.INFO, logger=self.LOGGER_NAME):
            await probe_video_support(
                "https://api.example.com/v1", "sk-test", "gpt-4o",
            )

        info_messages = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO and r.name == self.LOGGER_NAME
        ]
        assert any("Video probe started" in m for m in info_messages), (
            f"Expected 'Video probe started' INFO log, got: {info_messages}"
        )
        assert any("Video probe completed" in m for m in info_messages), (
            f"Expected 'Video probe completed' INFO log, got: {info_messages}"
        )

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_image_probe_logs_warning_on_api_error(
        self, mock_openai_cls, monkeypatch, caplog,
    ) -> None:
        """APIError during image probe emits a WARNING log."""
        import logging

        self._enable_propagation(monkeypatch)

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = _make_api_error(
            422, "image_url is not supported",
        )
        mock_openai_cls.return_value = mock_client

        with caplog.at_level(logging.WARNING, logger=self.LOGGER_NAME):
            await probe_image_support(
                "https://api.example.com/v1", "sk-test", "text-only-model",
            )

        warning_messages = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING and r.name == self.LOGGER_NAME
        ]
        assert any("Image probe exception" in m for m in warning_messages), (
            f"Expected 'Image probe exception' WARNING log, got: {warning_messages}"
        )

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_video_probe_logs_warning_on_general_exception(
        self, mock_openai_cls, monkeypatch, caplog,
    ) -> None:
        """General Exception during video probe emits a WARNING log."""
        import logging

        self._enable_propagation(monkeypatch)

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = RuntimeError(
            "Something went wrong",
        )
        mock_openai_cls.return_value = mock_client

        with caplog.at_level(logging.WARNING, logger=self.LOGGER_NAME):
            await probe_video_support(
                "https://api.example.com/v1", "sk-test", "broken-model",
            )

        warning_messages = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING and r.name == self.LOGGER_NAME
        ]
        assert any("Video probe exception" in m for m in warning_messages), (
            f"Expected 'Video probe exception' WARNING log, got: {warning_messages}"
        )
