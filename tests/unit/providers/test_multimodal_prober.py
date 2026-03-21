# -*- coding: utf-8 -*-
"""Unit tests for multimodal capability prober functions.

Validates: Requirements 4.1, 4.2, 4.3, 4.9
"""
from __future__ import annotations

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


class _FakeStream:
    """Minimal async iterator that yields one chunk then stops."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


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
        """When the model accepts the image probe, return (True, message)."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _FakeStream()
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_image_support(
            "https://api.example.com/v1", "sk-test", "gpt-4o",
        )

        assert ok is True
        assert "Image supported" in msg
        mock_client.chat.completions.create.assert_awaited_once()

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
        """When the model accepts the video probe, return (True, message)."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _FakeStream()
        mock_openai_cls.return_value = mock_client

        ok, msg = await probe_video_support(
            "https://api.example.com/v1", "sk-test", "gpt-4o",
        )

        assert ok is True
        assert "Video supported" in msg

    @patch("copaw.providers.multimodal_prober.AsyncOpenAI")
    async def test_400_api_error_returns_false(self, mock_openai_cls) -> None:
        """When the model returns 400 APIError, return (False, ...)."""
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
        mock_client.chat.completions.create.return_value = _FakeStream()
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
            # First call is image probe (succeeds), second is video (fails)
            if call_count == 1:
                return _FakeStream()
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
