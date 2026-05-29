# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.tools.view_media.

Covers:
- _is_url
- _validate_url_extension
- _validate_media_path
- _check_multimodal_support
- _get_multimodal_fallback_hint
- view_image
- view_video
"""
# pylint: disable=protected-access,unused-argument

from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.agents.tools.view_media import (
    _IMAGE_EXTENSIONS,
    _VIDEO_EXTENSIONS,
    _check_multimodal_support,
    _get_multimodal_fallback_hint,
    _is_url,
    _validate_media_path,
    _validate_url_extension,
    view_image,
    view_video,
)


# ---------------------------------------------------------------------------
# _is_url
# ---------------------------------------------------------------------------


class TestIsUrl:
    """Tests for _is_url."""

    def test_http_url(self):
        assert _is_url("http://example.com/img.png") is True

    def test_https_url(self):
        assert _is_url("https://example.com/img.png") is True

    def test_local_path(self):
        assert _is_url("/tmp/img.png") is False

    def test_relative_path(self):
        assert _is_url("images/photo.jpg") is False


# ---------------------------------------------------------------------------
# _validate_url_extension
# ---------------------------------------------------------------------------


class TestValidateUrlExtension:
    """Tests for _validate_url_extension."""

    def test_valid_image_url(self):
        result = _validate_url_extension(
            "https://example.com/photo.jpg",
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert result is None

    def test_invalid_image_url(self):
        result = _validate_url_extension(
            "https://example.com/doc.pdf",
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert result is not None
        assert "image" in result.content[0]["text"].lower()

    def test_url_without_extension_passes(self):
        result = _validate_url_extension(
            "https://example.com/api/image",
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert result is None

    def test_valid_video_url(self):
        result = _validate_url_extension(
            "https://example.com/clip.mp4",
            _VIDEO_EXTENSIONS,
            "video",
        )
        assert result is None

    def test_invalid_video_url(self):
        result = _validate_url_extension(
            "https://example.com/file.txt",
            _VIDEO_EXTENSIONS,
            "video",
        )
        assert result is not None
        assert "video" in result.content[0]["text"].lower()


# ---------------------------------------------------------------------------
# _validate_media_path
# ---------------------------------------------------------------------------


class TestValidateMediaPath:
    """Tests for _validate_media_path."""

    def test_valid_image_file(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10)
        _, err = _validate_media_path(
            str(img),
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert err is None

    def test_nonexistent_file(self):
        _, err = _validate_media_path(
            "/nonexistent/img.png",
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert err is not None
        assert "does not exist" in err.content[0]["text"]

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.xyz"
        f.write_text("data", encoding="utf-8")
        _, err = _validate_media_path(
            str(f),
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert err is not None
        assert "not a supported image" in err.content[0]["text"]

    def test_directory_not_file(self, tmp_path):
        _, err = _validate_media_path(
            str(tmp_path),
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert err is not None
        assert "does not exist" in err.content[0]["text"]

    def test_valid_video_file(self, tmp_path):
        vid = tmp_path / "clip.mp4"
        vid.write_bytes(b"\x00" * 100)
        _, err = _validate_media_path(
            str(vid),
            _VIDEO_EXTENSIONS,
            "video",
        )
        assert err is None


# ---------------------------------------------------------------------------
# _check_multimodal_support
# ---------------------------------------------------------------------------


class TestCheckMultimodalSupport:
    """Tests for _check_multimodal_support."""

    @patch("qwenpaw.agents.prompt._get_active_model_info", create=True)
    def test_no_model_info_returns_true(self, mock_info):
        mock_info.return_value = (None, None)
        assert _check_multimodal_support("image") is True

    @patch("qwenpaw.agents.prompt._get_active_model_info", create=True)
    def test_supports_image_true(self, mock_info):
        model_info = MagicMock()
        model_info.supports_image = True
        model_info.supports_multimodal = False
        mock_info.return_value = (model_info, None)
        assert _check_multimodal_support("image") is True

    @patch("qwenpaw.agents.prompt._get_active_model_info", create=True)
    def test_supports_multimodal_true(self, mock_info):
        model_info = MagicMock()
        model_info.supports_image = False
        model_info.supports_multimodal = True
        mock_info.return_value = (model_info, None)
        assert _check_multimodal_support("image") is True

    @patch("qwenpaw.agents.prompt._get_active_model_info", create=True)
    def test_video_requires_explicit_support(self, mock_info):
        model_info = MagicMock()
        model_info.supports_video = False
        model_info.supports_multimodal = True
        mock_info.return_value = (model_info, None)
        assert _check_multimodal_support("video") is False

    @patch("qwenpaw.agents.prompt._get_active_model_info", create=True)
    def test_exception_returns_true(self, mock_info):
        mock_info.side_effect = ImportError("no module")
        assert _check_multimodal_support("image") is True


# ---------------------------------------------------------------------------
# _get_multimodal_fallback_hint
# ---------------------------------------------------------------------------


class TestGetMultimodalFallbackHint:
    """Tests for _get_multimodal_fallback_hint."""

    @patch(
        "qwenpaw.agents.prompt.get_active_model_multimodal_raw",
        create=True,
    )
    def test_when_raw_is_none(self, mock_raw):
        mock_raw.return_value = None
        hint = _get_multimodal_fallback_hint("image", "/path/img.png")
        assert "no multimodal capability was detected" in hint

    @patch(
        "qwenpaw.agents.prompt.get_active_model_multimodal_raw",
        create=True,
    )
    def test_when_raw_is_false(self, mock_raw):
        mock_raw.return_value = False
        hint = _get_multimodal_fallback_hint("video", "/path/vid.mp4")
        assert "multimodal" in hint.lower()

    @patch(
        "qwenpaw.agents.prompt.get_active_model_multimodal_raw",
        create=True,
    )
    def test_when_raw_is_true(self, mock_raw):
        mock_raw.return_value = True
        hint = _get_multimodal_fallback_hint("image", "/path/img.png")
        assert "multimodal" in hint.lower()

    @patch(
        "qwenpaw.agents.prompt.get_active_model_multimodal_raw",
        create=True,
    )
    def test_exception_returns_none_hint(self, mock_raw):
        mock_raw.side_effect = ImportError("no module")
        hint = _get_multimodal_fallback_hint("image", "/path/img.png")
        assert "no multimodal capability was detected" in hint


# ---------------------------------------------------------------------------
# view_image
# ---------------------------------------------------------------------------


class TestViewImage:
    """Tests for view_image."""

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_url_image(self, mock_support):
        mock_support.return_value = True
        result = await view_image("https://example.com/photo.jpg")
        assert result.content is not None
        types = [b.get("type") for b in result.content]
        assert "image" in types

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_invalid_url_extension(self, mock_support):
        mock_support.return_value = True
        result = await view_image("https://example.com/doc.pdf")
        assert "image" in result.content[0]["text"].lower()

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_local_image_file(self, mock_support, tmp_path):
        mock_support.return_value = True
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        result = await view_image(str(img))
        types = [b.get("type") for b in result.content]
        assert "image" in types

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_nonexistent_local_file(self, mock_support):
        mock_support.return_value = True
        result = await view_image("/nonexistent/image.png")
        assert "does not exist" in result.content[0]["text"]

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._probe_multimodal_if_needed")
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_fallback_hint_included(self, mock_support, mock_probe):
        mock_support.return_value = False
        mock_probe.return_value = False
        result = await view_image("https://example.com/img.jpg")
        text_parts = [
            b["text"] for b in result.content if b.get("type") == "text"
        ]
        assert any("multimodal" in t.lower() for t in text_parts)


# ---------------------------------------------------------------------------
# view_video
# ---------------------------------------------------------------------------


class TestViewVideo:
    """Tests for view_video."""

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_url_video(self, mock_support):
        mock_support.return_value = True
        result = await view_video("https://example.com/clip.mp4")
        types = [b.get("type") for b in result.content]
        assert "video" in types

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_invalid_url_extension(self, mock_support):
        mock_support.return_value = True
        result = await view_video("https://example.com/doc.pdf")
        assert "video" in result.content[0]["text"].lower()

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_local_video_file(self, mock_support, tmp_path):
        mock_support.return_value = True
        vid = tmp_path / "clip.mp4"
        vid.write_bytes(b"\x00" * 100)
        result = await view_video(str(vid))
        types = [b.get("type") for b in result.content]
        assert "video" in types

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_nonexistent_local_file(self, mock_support):
        mock_support.return_value = True
        result = await view_video("/nonexistent/vid.mp4")
        assert "does not exist" in result.content[0]["text"]
