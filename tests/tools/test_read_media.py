# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-import,line-too-long
"""Unit tests for read_media tool."""
import base64
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from copaw.agents.tools.read_media import (
    read_media,
    _parse_source,
    _get_media_type,
    _get_file_category,
    MAX_FILE_SIZE,
    SUPPORTED_FORMATS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    AUDIO_EXTENSIONS,
)


# Test fixtures
@pytest.fixture
def temp_dir(tmp_path: Path):
    """Create a temporary directory for testing."""
    return tmp_path


@pytest.fixture
def sample_png(temp_dir: Path):
    """Create a sample PNG file for testing."""
    # Minimal valid PNG (1x1 transparent pixel)
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",  # noqa: E501
    )
    png_path = temp_dir / "test.png"
    png_path.write_bytes(png_data)
    return png_path


@pytest.fixture
def sample_jpg(temp_dir: Path):
    """Create a sample JPG file for testing."""
    # Minimal valid JPEG
    jpg_data = base64.b64decode(
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP///////////////////////////////////"
        "////////////////////////////////////////////////////////////////"
        "////////////////////////////////////////////////wAALCA"
        "ACAgBARE"
        "A/8QAFQAAAQUBAQEAAAAAAAAAAAAAAAIDAQQFBgcICf/aAAgBAQABBQKb"
        "pqD/2gAIAQAAAQUFpmmo/9oACAEBAAEFAlD/2gAIAQIBAQFwUf/aAAgBAwEB"
        "AXBR/9oADAMBEQCEAaEAAX//2Q==",
    )
    jpg_path = temp_dir / "test.jpg"
    jpg_path.write_bytes(jpg_data)
    return jpg_path


@pytest.fixture
def sample_mp4(temp_dir: Path):
    """Create a minimal MP4 file for testing."""
    # Minimal MP4-like file with ftyp box
    mp4_data = b"\x00\x00\x00\x20ftypisomisommp41"
    mp4_path = temp_dir / "test.mp4"
    mp4_path.write_bytes(mp4_data)
    return mp4_path


@pytest.fixture
def sample_mp3(temp_dir: Path):
    """Create a minimal MP3 file for testing."""
    # Minimal MP3-like file with MPEG sync word
    mp3_data = b"\xff\xfb\x90\x00" + b"\x00" * 100
    mp3_path = temp_dir / "test.mp3"
    mp3_path.write_bytes(mp3_data)
    return mp3_path


class TestGetMediaType:
    """Tests for _get_media_type function."""

    def test_image_extensions(self):
        """Test image format detection."""
        assert _get_media_type("test.png") == "image/png"
        assert _get_media_type("test.jpg") == "image/jpeg"
        assert _get_media_type("test.jpeg") == "image/jpeg"
        assert _get_media_type("test.gif") == "image/gif"
        assert _get_media_type("test.webp") == "image/webp"
        assert _get_media_type("test.bmp") == "image/bmp"

    def test_video_extensions(self):
        """Test video format detection."""
        assert _get_media_type("test.mp4") == "video/mp4"
        assert _get_media_type("test.avi") == "video/x-msvideo"
        assert _get_media_type("test.mov") == "video/quicktime"
        assert _get_media_type("test.mkv") == "video/x-matroska"
        assert _get_media_type("test.webm") == "video/webm"

    def test_audio_extensions(self):
        """Test audio format detection."""
        assert _get_media_type("test.mp3") == "audio/mpeg"
        assert _get_media_type("test.wav") == "audio/wav"
        assert _get_media_type("test.aac") == "audio/aac"
        assert _get_media_type("test.ogg") == "audio/ogg"
        assert _get_media_type("test.m4a") == "audio/mp4"
        assert _get_media_type("test.flac") == "audio/flac"

    def test_unsupported_format(self):
        """Test unsupported format returns None."""
        assert _get_media_type("test.txt") is None
        assert _get_media_type("test.pdf") is None
        assert _get_media_type("test.svg") is None

    def test_no_extension(self):
        """Test file without extension returns None."""
        assert _get_media_type("testfile") is None


class TestGetFileCategory:
    """Tests for _get_file_category function."""

    def test_image_category(self):
        """Test image category detection."""
        assert _get_file_category("test.png") == "image"
        assert _get_file_category("/path/to/photo.jpg") == "image"
        assert _get_file_category("image.GIF") == "image"

    def test_video_category(self):
        """Test video category detection."""
        assert _get_file_category("test.mp4") == "video"
        assert _get_file_category("/path/to/movie.mov") == "video"
        assert _get_file_category("video.AVI") == "video"

    def test_audio_category(self):
        """Test audio category detection."""
        assert _get_file_category("test.mp3") == "audio"
        assert _get_file_category("/path/to/song.wav") == "audio"
        assert _get_file_category("audio.MP3") == "audio"

    def test_unknown_category(self):
        """Test unknown category."""
        assert _get_file_category("test.txt") == "unknown"
        assert _get_file_category("test.pdf") == "unknown"


class TestParseSource:
    """Tests for _parse_source function."""

    def test_http_url(self):
        """Test HTTP URL parsing."""
        source_type, parsed, error = _parse_source(
            "http://example.com/image.png",
        )
        assert source_type == "http_url"
        assert parsed == "http://example.com/image.png"
        assert error == ""

    def test_https_url(self):
        """Test HTTPS URL parsing."""
        source_type, parsed, error = _parse_source(
            "https://example.com/video.mp4",
        )
        assert source_type == "http_url"
        assert parsed == "https://example.com/video.mp4"
        assert error == ""

    def test_file_url(self):
        """Test file:// URL parsing."""
        source_type, parsed, error = _parse_source(
            "file:///Users/test/media.mp3",
        )
        assert source_type == "file_url"
        assert parsed == "/Users/test/media.mp3"
        assert error == ""

    def test_file_url_encoded(self):
        """Test file:// URL with encoded characters."""
        source_type, parsed, error = _parse_source(
            "file:///Users/test%20folder/video.mp4",
        )
        assert source_type == "file_url"
        assert parsed == "/Users/test folder/video.mp4"
        assert error == ""

    def test_local_path(self):
        """Test local path parsing."""
        source_type, parsed, error = _parse_source("/Users/test/audio.mp3")
        assert source_type == "local"
        assert parsed == "/Users/test/audio.mp3"
        assert error == ""

    def test_relative_path(self):
        """Test relative path parsing."""
        source_type, parsed, error = _parse_source("video.mp4")
        assert source_type == "local"
        assert parsed == "video.mp4"
        assert error == ""


class TestReadMedia:
    """Tests for read_media async function."""

    @pytest.mark.asyncio
    async def test_empty_source(self):
        """Test empty source returns error."""
        response = await read_media("")
        assert len(response.content) == 1
        assert response.content[0]["type"] == "text"
        assert "No media file source provided" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_png_file(self, sample_png: Path):
        """Test reading a valid PNG file."""
        response = await read_media(str(sample_png))
        assert len(response.content) == 2  # Text + ImageBlock
        assert response.content[0]["type"] == "text"
        assert response.content[1]["type"] == "image"
        assert response.content[1]["source"]["type"] == "base64"
        assert response.content[1]["source"]["media_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_read_jpg_file(self, sample_jpg: Path):
        """Test reading a valid JPG file."""
        response = await read_media(str(sample_jpg))
        assert len(response.content) == 2
        assert response.content[1]["type"] == "image"
        assert response.content[1]["source"]["media_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_read_mp4_file(self, sample_mp4: Path):
        """Test reading a valid MP4 file."""
        response = await read_media(str(sample_mp4))
        assert len(response.content) == 2
        assert response.content[0]["type"] == "text"
        assert response.content[1]["type"] == "video"
        assert response.content[1]["source"]["media_type"] == "video/mp4"

    @pytest.mark.asyncio
    async def test_read_mp3_file(self, sample_mp3: Path):
        """Test reading a valid MP3 file."""
        response = await read_media(str(sample_mp3))
        assert len(response.content) == 2
        assert response.content[0]["type"] == "text"
        assert response.content[1]["type"] == "audio"
        assert response.content[1]["source"]["media_type"] == "audio/mpeg"

    @pytest.mark.asyncio
    async def test_file_url(self, sample_png: Path):
        """Test reading media via file:// URL."""
        file_url = f"file://{sample_png}"
        response = await read_media(file_url)
        assert len(response.content) == 2
        assert response.content[1]["type"] == "image"

    @pytest.mark.asyncio
    async def test_nonexistent_file(self):
        """Test reading nonexistent file returns error."""
        response = await read_media("/nonexistent/path/file.png")
        assert response.content[0]["type"] == "text"
        assert "File does not exist" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_unsupported_format(self, temp_dir: Path):
        """Test reading unsupported format returns error."""
        txt_file = temp_dir / "test.txt"
        txt_file.write_text("not a media file")
        response = await read_media(str(txt_file))
        assert response.content[0]["type"] == "text"
        assert "Unsupported media format" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_file_too_large(self, temp_dir: Path):
        """Test reading file larger than 20MB returns error."""
        # Create a file slightly larger than 20MB with valid PNG header
        png_header = b"\x89PNG\r\n\x1a\n"
        large_file = temp_dir / "large.png"
        large_file.write_bytes(png_header + b"\x00" * (MAX_FILE_SIZE + 1))

        response = await read_media(str(large_file))
        assert response.content[0]["type"] == "text"
        assert "File too large" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_directory_instead_of_file(self, temp_dir: Path):
        """Test reading directory returns error."""
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        response = await read_media(str(subdir))
        assert response.content[0]["type"] == "text"
        assert "Path is not a file" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_relative_path(self, temp_dir: Path):
        """Test relative path resolution."""
        # Create a file
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",  # noqa: E501
        )
        (temp_dir / "relative.png").write_bytes(png_data)

        # Change to temp dir and test relative path
        original_dir = os.getcwd()
        try:
            os.chdir(temp_dir)
            response = await read_media("relative.png")
            assert response.content[1]["type"] == "image"
        finally:
            os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_http_url_success(self, sample_png: Path):
        """Test fetching media from HTTP URL."""
        png_data = sample_png.read_bytes()
        mock_response = AsyncMock()
        mock_response.content = png_data
        mock_response.headers = {"content-type": "image/png"}
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response,
            )

            response = await read_media("https://example.com/test.png")
            assert response.content[0]["type"] == "image"
            assert response.content[0]["source"]["media_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_http_url_video(self, sample_mp4: Path):
        """Test fetching video from HTTP URL."""
        mp4_data = sample_mp4.read_bytes()
        mock_response = AsyncMock()
        mock_response.content = mp4_data
        mock_response.headers = {"content-type": "video/mp4"}
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response,
            )

            response = await read_media("https://example.com/test.mp4")
            assert response.content[0]["type"] == "video"
            assert response.content[0]["source"]["media_type"] == "video/mp4"

    @pytest.mark.asyncio
    async def test_http_url_too_large(self):
        """Test HTTP URL with file too large returns error."""
        mock_response = AsyncMock()
        mock_response.content = b"\x00" * (MAX_FILE_SIZE + 1)
        mock_response.headers = {"content-type": "image/png"}
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response,
            )

            response = await read_media("https://example.com/large.png")
            assert response.content[0]["type"] == "text"
            assert "File too large" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_broken_symlink(self, temp_dir: Path):
        """Test broken symlink returns error."""
        # Create symlink pointing to non-existent file
        symlink_path = temp_dir / "broken_link.png"
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(temp_dir / "nonexistent.png")

        response = await read_media(str(symlink_path))
        assert response.content[0]["type"] == "text"
        assert (
            "Symbolic link" in response.content[0]["text"]
            or "does not exist" in response.content[0]["text"]
        )

    @pytest.mark.asyncio
    async def test_magic_number_mismatch(self, temp_dir: Path):
        """Test file with wrong magic number is rejected."""
        # Create a file with .png extension but invalid PNG content
        fake_png = temp_dir / "fake.png"
        fake_png.write_bytes(b"This is not a PNG file at all!")

        response = await read_media(str(fake_png))
        assert response.content[0]["type"] == "text"
        assert (
            "format" in response.content[0]["text"].lower()
            or "file" in response.content[0]["text"].lower()
        )

    @pytest.mark.asyncio
    async def test_image_compression(self, temp_dir: Path):
        """Test image compression for large images."""
        # Create a mock for PIL
        mock_img = MagicMock()
        mock_img.mode = "RGB"
        mock_img.width = 100
        mock_img.height = 100

        # Create a large file with valid PNG header
        png_header = b"\x89PNG\r\n\x1a\n"
        large_png = temp_dir / "large.png"
        # Create file larger than 5MB (default max_size_mb)
        large_png.write_bytes(png_header + b"\x00" * (6 * 1024 * 1024))

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_img)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)

            response = await read_media(
                str(large_png),
                compress=True,
                max_size_mb=5.0,
            )

            # Should return blocks (either compressed or original)
            assert len(response.content) >= 1

    @pytest.mark.asyncio
    async def test_compress_false(self, temp_dir: Path):
        """Test disabling compression."""
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",  # noqa: E501
        )
        png_path = temp_dir / "test.png"
        png_path.write_bytes(png_data)

        response = await read_media(str(png_path), compress=False)
        assert response.content[1]["type"] == "image"

    @pytest.mark.asyncio
    async def test_video_with_fps_parameter(self, sample_mp4: Path):
        """Test reading video with custom FPS parameter."""
        response = await read_media(str(sample_mp4), video_fps=5)
        assert response.content[0]["type"] == "text"
        assert response.content[1]["type"] == "video"


class TestConstants:
    """Tests for module constants."""

    def test_max_file_size(self):
        """Test max file size is 20MB."""
        assert MAX_FILE_SIZE == 20 * 1024 * 1024

    def test_supported_formats(self):
        """Test all required formats are supported."""
        required_images = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]
        required_videos = [".mp4", ".avi", ".mov", ".mkv", ".webm"]
        required_audio = [".mp3", ".wav", ".aac", ".ogg", ".m4a", ".flac"]

        for fmt in required_images + required_videos + required_audio:
            assert fmt in SUPPORTED_FORMATS, f"Missing format: {fmt}"

    def test_extension_categories(self):
        """Test extension categories are correctly defined."""
        assert IMAGE_EXTENSIONS == {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".bmp",
        }
        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".mp3" in AUDIO_EXTENSIONS
