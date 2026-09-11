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

import asyncio
import base64
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agentscope.message import Base64Source
from PIL import Image

from qwenpaw.agents.tools import view_media
from qwenpaw.agents.utils import image_freezing
from qwenpaw.agents.utils.image_freezing import freeze_image_bytes
from qwenpaw.agents.tools.view_media import (
    _IMAGE_EXTENSIONS,
    _VIDEO_EXTENSIONS,
    _check_multimodal_support,
    _download_remote_image,
    _get_multimodal_fallback_hint,
    _is_url,
    _validate_media_path,
    _validate_url_extension,
    view_image,
    view_video,
)
from qwenpaw.providers.capping_formatter import MAX_INLINE_MEDIA_BYTES


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
        assert "image" in result.content[0].text.lower()

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
        assert "video" in result.content[0].text.lower()


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
        assert "does not exist" in err.content[0].text

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.xyz"
        f.write_text("data", encoding="utf-8")
        _, err = _validate_media_path(
            str(f),
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert err is not None
        assert "not a supported image" in err.content[0].text

    def test_directory_not_file(self, tmp_path):
        _, err = _validate_media_path(
            str(tmp_path),
            _IMAGE_EXTENSIONS,
            "image",
        )
        assert err is not None
        assert "does not exist" in err.content[0].text

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
    @patch(
        "qwenpaw.agents.tools.view_media._download_remote_image",
        new_callable=AsyncMock,
    )
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_url_image(self, mock_support, mock_download):
        mock_support.return_value = True
        image_bytes = BytesIO()
        Image.new("RGB", (2, 2), color="red").save(
            image_bytes,
            format="PNG",
        )
        mock_download.return_value = (image_bytes.getvalue(), None)

        result = await view_image("https://example.com/photo.jpg")

        assert len(result.content) == 2
        assert result.content[0].model_dump(
            mode="json",
            exclude={"id", "created_at", "finished_at"},
        ) == {
            "type": "data",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(image_bytes.getvalue()).decode(
                    "ascii",
                ),
            },
            "name": None,
        }
        assert result.content[1].model_dump(
            mode="json",
            exclude={"id", "created_at", "finished_at"},
        ) == {
            "type": "text",
            "text": "Image loaded from remote source.",
        }
        mock_download.assert_awaited_once_with(
            "https://example.com/photo.jpg",
            50 * 1024 * 1024,
        )

    @pytest.mark.asyncio
    @patch(
        "qwenpaw.agents.tools.view_media._download_remote_image",
        new_callable=AsyncMock,
    )
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_oversized_url_image_is_staged_for_compression(
        self,
        mock_support,
        mock_download,
        monkeypatch,
        tmp_path,
    ):
        mock_support.return_value = True
        channels = [Image.effect_noise((32, 32), 100) for _ in range(3)]
        image = Image.merge("RGB", channels)
        image_buffer = BytesIO()
        image.save(image_buffer, format="PNG")
        image_bytes = image_buffer.getvalue()
        assert len(image_bytes) > 64
        mock_download.return_value = (image_bytes, None)
        monkeypatch.setattr(view_media, "MAX_INLINE_MEDIA_BYTES", 64)
        monkeypatch.setattr(
            view_media,
            "get_current_workspace_dir",
            lambda: tmp_path,
        )

        result = await view_image("https://example.com/photo.png")

        downloaded_files = list((tmp_path / "downloads").iterdir())
        assert len(downloaded_files) == 1
        downloaded_file = downloaded_files[0]
        assert downloaded_file.name.startswith("remote-image-")
        assert downloaded_file.suffix == ".png"
        assert downloaded_file.read_bytes() == image_bytes
        assert [
            block.model_dump(
                mode="json",
                exclude={"id", "created_at", "finished_at"},
            )
            for block in result.content
        ] == [
            {
                "type": "text",
                "text": (
                    f"Remote image is {len(image_bytes)} bytes and "
                    "exceeds the 64-byte inline image limit. It was "
                    f"downloaded to: {downloaded_file}. Compress or "
                    "resize this local file below the inline limit, "
                    "then call view_image with the compressed file path."
                ),
            },
        ]

    @pytest.mark.asyncio
    @patch(
        "qwenpaw.agents.tools.view_media._download_remote_image",
        new_callable=AsyncMock,
    )
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_invalid_oversized_url_image_is_not_staged(
        self,
        mock_support,
        mock_download,
        monkeypatch,
        tmp_path,
    ):
        mock_support.return_value = True
        mock_download.return_value = (b"x" * 65, None)
        monkeypatch.setattr(view_media, "MAX_INLINE_MEDIA_BYTES", 64)
        monkeypatch.setattr(
            view_media,
            "get_current_workspace_dir",
            lambda: tmp_path,
        )

        result = await view_image("https://example.com/photo.png")

        assert [block.type for block in result.content] == ["text"]
        assert "not a valid image" in result.content[0].text
        assert not (tmp_path / "downloads").exists()

    @pytest.mark.asyncio
    @patch(
        "qwenpaw.agents.tools.view_media._download_remote_image",
        new_callable=AsyncMock,
    )
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_url_download_failure_is_text_only(
        self,
        mock_support,
        mock_download,
    ):
        mock_support.return_value = True
        mock_download.return_value = (None, "remote server returned HTTP 404")

        result = await view_image("https://example.com/missing.png")

        assert [
            block.model_dump(
                mode="json",
                exclude={"id", "created_at", "finished_at"},
            )
            for block in result.content
        ] == [
            {
                "type": "text",
                "text": (
                    "Error: failed to load remote image: "
                    "remote server returned HTTP 404"
                ),
            },
        ]

    @pytest.mark.asyncio
    @patch(
        "qwenpaw.agents.tools.view_media._download_remote_image",
        new_callable=AsyncMock,
    )
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_url_invalid_image_is_text_only(
        self,
        mock_support,
        mock_download,
    ):
        mock_support.return_value = True
        mock_download.return_value = (b"<html>not an image</html>", None)

        result = await view_image("https://example.com/image.png")

        assert len(result.content) == 1
        assert result.content[0].type == "text"
        assert "not a valid image" in result.content[0].text

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_invalid_url_extension(self, mock_support):
        mock_support.return_value = True
        result = await view_image("https://example.com/doc.pdf")
        assert "image" in result.content[0].text.lower()

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_local_image_file(self, mock_support, tmp_path):
        mock_support.return_value = True
        img = tmp_path / "photo.png"
        Image.new("RGB", (2, 2), color="red").save(img)
        result = await view_image(str(img))
        types = [getattr(b, "type", None) for b in result.content]
        assert "data" in types
        image_block = next(
            block for block in result.content if block.type == "data"
        )
        assert isinstance(image_block.source, Base64Source)
        assert image_block.source.media_type == "image/png"
        assert base64.b64decode(image_block.source.data) == img.read_bytes()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("suffix", "image_format"),
        [(".bmp", "BMP"), (".tiff", "TIFF")],
    )
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_local_image_converts_to_png(
        self,
        mock_support,
        tmp_path,
        suffix,
        image_format,
    ):
        mock_support.return_value = True
        img = tmp_path / f"photo{suffix}"
        Image.new("RGB", (2, 2), color="green").save(
            img,
            format=image_format,
        )

        result = await view_image(str(img))

        image_block = next(
            block for block in result.content if block.type == "data"
        )
        assert isinstance(image_block.source, Base64Source)
        assert image_block.source.media_type == "image/png"
        converted_bytes = base64.b64decode(image_block.source.data)
        with Image.open(BytesIO(converted_bytes)) as converted:
            assert converted.format == "PNG"

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_tiff_with_jpeg_suffix_converts_to_png(
        self,
        mock_support,
        tmp_path,
    ):
        mock_support.return_value = True
        img = tmp_path / "misleading.jpg"
        Image.new("RGB", (2, 2), color="yellow").save(
            img,
            format="TIFF",
        )

        result = await view_image(str(img))

        image_block = next(
            block for block in result.content if block.type == "data"
        )
        assert image_block.source.media_type == "image/png"
        converted_bytes = base64.b64decode(image_block.source.data)
        with Image.open(BytesIO(converted_bytes)) as converted:
            assert converted.format == "PNG"

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_local_image_uses_detected_mime(
        self,
        mock_support,
        tmp_path,
    ):
        mock_support.return_value = True
        img = tmp_path / "misleading.jpg"
        Image.new("RGB", (2, 2), color="blue").save(img, format="PNG")

        result = await view_image(str(img))

        image_block = next(
            block for block in result.content if block.type == "data"
        )
        assert image_block.source.media_type == "image/png"

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_invalid_local_image_returns_error(
        self,
        mock_support,
        tmp_path,
    ):
        mock_support.return_value = True
        img = tmp_path / "broken.png"
        img.write_bytes(b"not-an-image")

        result = await view_image(str(img))

        assert len(result.content) == 1
        assert "not a valid image" in result.content[0].text

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_oversized_local_image_is_rejected_before_decode(
        self,
        mock_support,
        tmp_path,
    ):
        mock_support.return_value = True
        img = tmp_path / "oversized.png"
        img.write_bytes(b"x" * (MAX_INLINE_MEDIA_BYTES + 1))

        result = await view_image(str(img))

        assert len(result.content) == 1
        assert "exceeds" in result.content[0].text
        assert str(MAX_INLINE_MEDIA_BYTES) in result.content[0].text

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_converted_png_must_fit_image_limit(
        self,
        mock_support,
        monkeypatch,
        tmp_path,
    ):
        mock_support.return_value = True
        img = tmp_path / "compressed.tiff"
        channels = [Image.effect_noise((1000, 1000), 100) for _ in range(3)]
        Image.merge("RGB", channels).save(
            img,
            format="TIFF",
            compression="jpeg",
            quality=75,
        )
        with Image.open(img) as image:
            image.load()
            converted = BytesIO()
            image.convert("RGB").save(converted, format="PNG")
        source_size = img.stat().st_size
        converted_size = len(converted.getvalue())
        assert source_size < converted_size
        image_limit = (source_size + converted_size) // 2
        monkeypatch.setattr(
            image_freezing,
            "MAX_INLINE_MEDIA_BYTES",
            image_limit,
        )

        result = await view_image(str(img))

        assert len(result.content) == 1
        assert "converted" in result.content[0].text
        assert "exceeds" in result.content[0].text

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_overwritten_path_preserves_each_version(
        self,
        mock_support,
        tmp_path,
    ):
        mock_support.return_value = True
        img = tmp_path / "preview.png"
        Image.new("RGB", (2, 2), color="red").save(img)
        first = await view_image(str(img))
        first_block = next(
            block for block in first.content if block.type == "data"
        )
        first_data = first_block.source.data

        Image.new("RGB", (2, 2), color="blue").save(img)
        second = await view_image(str(img))
        second_block = next(
            block for block in second.content if block.type == "data"
        )

        assert first_block.source.data == first_data
        assert second_block.source.data != first_data

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_nonexistent_local_file(self, mock_support):
        mock_support.return_value = True
        result = await view_image("/nonexistent/image.png")
        assert "does not exist" in result.content[0].text

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._probe_multimodal_if_needed")
    @patch(
        "qwenpaw.agents.tools.view_media._download_remote_image",
        new_callable=AsyncMock,
    )
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_fallback_hint_included(
        self,
        mock_support,
        mock_download,
        mock_probe,
    ):
        mock_support.return_value = False
        mock_probe.return_value = False
        image_bytes = BytesIO()
        Image.new("RGB", (2, 2), color="red").save(
            image_bytes,
            format="PNG",
        )
        mock_download.return_value = (image_bytes.getvalue(), None)
        result = await view_image("https://example.com/img.jpg")
        text_parts = [
            b.text
            for b in result.content
            if getattr(b, "type", None) == "text"
        ]
        assert any("multimodal" in t.lower() for t in text_parts)


class TestFreezeImageBytes:
    """Tests for the shared local/remote image freezing path."""

    @pytest.mark.parametrize(
        ("image_format", "media_type"),
        [
            ("PNG", "image/png"),
            ("JPEG", "image/jpeg"),
            ("GIF", "image/gif"),
            ("WEBP", "image/webp"),
        ],
    )
    def test_native_format_uses_detected_type_and_preserves_bytes(
        self,
        image_format,
        media_type,
    ):
        image_bytes = BytesIO()
        Image.new("RGB", (2, 2), color="blue").save(
            image_bytes,
            format=image_format,
        )

        block, error = freeze_image_bytes(
            image_bytes.getvalue(),
            "misleading.jpg",
        )

        assert error is None
        assert block is not None
        assert block.model_dump(
            mode="json",
            exclude={"id", "created_at", "finished_at"},
        ) == {
            "type": "data",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(image_bytes.getvalue()).decode(
                    "ascii",
                ),
            },
            "name": None,
        }

    @pytest.mark.parametrize(
        "invalid_bytes",
        [
            b"<html>not an image</html>",
            b'{"type": "not-an-image"}',
            b"random-bytes",
            b"\x89PNG\r\n\x1a\ntruncated",
        ],
    )
    def test_invalid_bytes_are_rejected(self, invalid_bytes):
        block, error = freeze_image_bytes(
            invalid_bytes,
            "image.png",
        )

        assert block is None
        assert error is not None
        assert "not a valid image" in error


class TestRemoteImageDownloadLimit:
    """Tests for the configurable remote image download limit."""

    def test_default_limit(self, monkeypatch):
        monkeypatch.delenv(
            "QWENPAW_REMOTE_IMAGE_DOWNLOAD_MAX_MB",
            raising=False,
        )
        result = view_media._remote_image_download_max_bytes()

        assert result == 50 * 1024 * 1024

    def test_positive_limit_has_no_upper_clamp(self, monkeypatch):
        monkeypatch.setenv(
            "QWENPAW_REMOTE_IMAGE_DOWNLOAD_MAX_MB",
            "10000",
        )

        result = view_media._remote_image_download_max_bytes()

        assert result == 10000 * 1024 * 1024

    @pytest.mark.parametrize("value", ["invalid", "0", "-1"])
    def test_invalid_or_nonpositive_limit_uses_default(
        self,
        monkeypatch,
        value,
    ):
        monkeypatch.setenv(
            "QWENPAW_REMOTE_IMAGE_DOWNLOAD_MAX_MB",
            value,
        )

        result = view_media._remote_image_download_max_bytes()

        assert result == 50 * 1024 * 1024


class TestDownloadRemoteImage:
    """Tests for bounded remote image downloads."""

    @pytest.mark.asyncio
    async def test_public_image_is_downloaded(self):
        requests = []

        def return_image(request):
            requests.append(request)
            return httpx.Response(
                200,
                content=b"image-bytes",
                request=request,
            )

        transport = httpx.MockTransport(return_image)
        client = httpx.AsyncClient(transport=transport)

        with patch.object(
            view_media,
            "_resolve_host_addresses",
            return_value=("93.184.216.34",),
        ) as mock_resolve, patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://example.com/image.png",
                32,
            )

        assert result == (b"image-bytes", None)
        mock_resolve.assert_called_once_with("example.com", 443)
        assert len(requests) == 1
        assert requests[0].url == httpx.URL(
            "https://93.184.216.34/image.png",
        )
        assert requests[0].headers["host"] == "example.com"
        assert requests[0].extensions["sni_hostname"] == "example.com"

    @pytest.mark.asyncio
    async def test_http_error_is_returned(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                404,
                request=request,
            ),
        )
        client = httpx.AsyncClient(transport=transport)

        with patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://93.184.216.34/missing.png",
                32,
            )

        assert result == (None, "remote server returned HTTP 404")

    @pytest.mark.asyncio
    async def test_timeout_is_returned(self):
        def raise_timeout(request):
            raise httpx.ReadTimeout(
                "timed out",
                request=request,
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(raise_timeout),
        )

        with patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://93.184.216.34/slow.png",
                32,
            )

        assert result == (None, "remote image download timed out")

    @pytest.mark.asyncio
    async def test_reported_size_is_rejected_before_reading(self):
        class TrackingStream(httpx.AsyncByteStream):
            def __init__(self):
                self.was_read = False

            async def __aiter__(self):
                self.was_read = True
                yield b"a" * 33

        stream = TrackingStream()
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-length": "33"},
                stream=stream,
                request=request,
            ),
        )
        client = httpx.AsyncClient(transport=transport)

        with patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://93.184.216.34/image.png",
                32,
            )

        assert result == (
            None,
            "remote image exceeds the 32-byte download limit",
        )
        assert stream.was_read is False

    @pytest.mark.asyncio
    async def test_streamed_image_over_limit_is_rejected(self):
        class ChunkedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"a" * 17
                yield b"b" * 17

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                stream=ChunkedStream(),
                request=request,
            ),
        )
        client = httpx.AsyncClient(transport=transport)

        with patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://93.184.216.34/image.png",
                32,
            )

        assert result == (
            None,
            "remote image exceeds the 32-byte download limit",
        )

    @pytest.mark.asyncio
    async def test_total_timeout_is_returned(self, monkeypatch):
        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                await asyncio.sleep(0.05)
                yield b"image-bytes"

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                stream=SlowStream(),
                request=request,
            ),
        )
        client = httpx.AsyncClient(transport=transport)
        monkeypatch.setattr(
            view_media,
            "_REMOTE_IMAGE_TOTAL_TIMEOUT",
            0.01,
        )

        with patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://93.184.216.34/slow.png",
                32,
            )

        assert result == (None, "remote image download timed out")

    @pytest.mark.asyncio
    async def test_public_redirect_is_downloaded(self):
        requested_paths = []

        def redirect_then_image(request):
            requested_paths.append(request.url.path)
            if request.url.path == "/start.png":
                return httpx.Response(
                    302,
                    headers={"location": "/final.png"},
                    request=request,
                )
            return httpx.Response(
                200,
                content=b"image-bytes",
                request=request,
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(redirect_then_image),
        )

        with patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://93.184.216.34/start.png",
                32,
            )

        assert result == (b"image-bytes", None)
        assert requested_paths == ["/start.png", "/final.png"]

    @pytest.mark.asyncio
    async def test_redirect_limit_is_rejected(self):
        requested_paths = []

        def redirect_again(request):
            requested_paths.append(request.url.path)
            return httpx.Response(
                302,
                headers={"location": "/again.png"},
                request=request,
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(redirect_again),
        )

        with patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://93.184.216.34/start.png",
                32,
            )

        assert result == (None, "remote image exceeded redirect limit")
        assert len(requested_paths) == (
            view_media._REMOTE_IMAGE_MAX_REDIRECTS + 1
        )

    @pytest.mark.asyncio
    async def test_redirect_to_loopback_is_rejected(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                302,
                headers={
                    "location": "http://127.0.0.1/private.png",
                },
                request=request,
            ),
        )
        client = httpx.AsyncClient(transport=transport)

        with patch.object(
            view_media.httpx,
            "AsyncClient",
            return_value=client,
        ):
            result = await _download_remote_image(
                "https://93.184.216.34/start.png",
                32,
            )

        assert result == (
            None,
            "remote image URL targets a non-public address",
        )

    @pytest.mark.asyncio
    async def test_mixed_public_and_private_dns_answers_are_rejected(self):
        with patch.object(
            view_media,
            "_resolve_host_addresses",
            return_value=("93.184.216.34", "127.0.0.1"),
        ):
            result = await _download_remote_image(
                "https://example.com/image.png",
                32,
            )

        assert result == (
            None,
            "remote image URL targets a non-public address",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/image.png",
            "http://192.168.1.10/image.png",
        ],
    )
    async def test_non_public_target_is_rejected(self, url):
        data, error = await _download_remote_image(
            url,
            MAX_INLINE_MEDIA_BYTES,
        )

        assert data is None
        assert error == "remote image URL targets a non-public address"


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
        types = [getattr(b, "type", None) for b in result.content]
        assert "data" in types

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_invalid_url_extension(self, mock_support):
        mock_support.return_value = True
        result = await view_video("https://example.com/doc.pdf")
        assert "video" in result.content[0].text.lower()

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_local_video_file(self, mock_support, tmp_path):
        mock_support.return_value = True
        vid = tmp_path / "clip.mp4"
        vid.write_bytes(b"\x00" * 100)
        result = await view_video(str(vid))
        types = [getattr(b, "type", None) for b in result.content]
        assert "data" in types

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.view_media._check_multimodal_support")
    async def test_nonexistent_local_file(self, mock_support):
        mock_support.return_value = True
        result = await view_video("/nonexistent/vid.mp4")
        assert "does not exist" in result.content[0].text
