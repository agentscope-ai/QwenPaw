# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.utils.file_handling.

Covers:
- read_text_file_with_encoding_fallback
- _default_download_dir
- _resolve_local_path
- _guess_suffix_from_file_content
- download_file_from_base64
- download_file_from_url
"""
# pylint: disable=protected-access,unused-argument

import urllib.parse
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.agents.utils.file_handling import (
    _default_download_dir,
    _guess_suffix_from_file_content,
    _resolve_local_path,
    download_file_from_base64,
    download_file_from_url,
    read_text_file_with_encoding_fallback,
)


# ---------------------------------------------------------------------------
# read_text_file_with_encoding_fallback
# ---------------------------------------------------------------------------


class TestReadTextFileWithEncodingFallback:
    """Tests for read_text_file_with_encoding_fallback."""

    def test_utf8_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = read_text_file_with_encoding_fallback(f)
        assert result == "hello world"

    def test_utf8_bom_file(self, tmp_path):
        f = tmp_path / "bom.txt"
        f.write_bytes(b"\xef\xbb\xbfhello")
        result = read_text_file_with_encoding_fallback(f)
        assert "hello" in result

    def test_gbk_file(self, tmp_path):
        f = tmp_path / "gbk.txt"
        f.write_bytes("你好".encode("gbk"))
        result = read_text_file_with_encoding_fallback(f)
        assert "你好" in result

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            read_text_file_with_encoding_fallback("/nonexistent/file.txt")

    def test_string_path(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content", encoding="utf-8")
        result = read_text_file_with_encoding_fallback(str(f))
        assert result == "content"


# ---------------------------------------------------------------------------
# _default_download_dir
# ---------------------------------------------------------------------------


class TestDefaultDownloadDir:
    """Tests for _default_download_dir."""

    @patch("qwenpaw.agents.utils.file_handling.get_current_workspace_dir")
    def test_with_workspace(self, mock_ws):
        mock_ws.return_value = Path("/workspace")
        result = _default_download_dir()
        assert result == str(Path("/workspace/downloads"))

    @patch("qwenpaw.agents.utils.file_handling.get_current_workspace_dir")
    def test_without_workspace(self, mock_ws):
        mock_ws.return_value = None
        result = _default_download_dir()
        assert "downloads" in result


# ---------------------------------------------------------------------------
# _resolve_local_path
# ---------------------------------------------------------------------------


class TestResolveLocalPath:
    """Tests for _resolve_local_path."""

    def test_file_scheme(self, tmp_path):
        f = tmp_path / "local.txt"
        f.write_text("data", encoding="utf-8")
        parsed = urllib.parse.urlparse(f.as_uri())
        result = _resolve_local_path(f.as_uri(), parsed)
        assert result is not None
        assert "local.txt" in result

    def test_file_scheme_missing(self):
        parsed = urllib.parse.urlparse("file:///nonexistent/file.txt")
        with pytest.raises(FileNotFoundError, match="not found"):
            _resolve_local_path("file:///nonexistent/file.txt", parsed)

    def test_file_scheme_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        parsed = urllib.parse.urlparse(f.as_uri())
        from agentscope_runtime.engine.schemas.exception import (
            AgentRuntimeErrorException,
        )

        with pytest.raises(AgentRuntimeErrorException):
            _resolve_local_path(f.as_uri(), parsed)

    def test_plain_existing_path(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data", encoding="utf-8")
        parsed = urllib.parse.urlparse(str(f))
        result = _resolve_local_path(str(f), parsed)
        assert result is not None

    def test_remote_url_returns_none(self):
        url = "https://example.com/file.pdf"
        parsed = urllib.parse.urlparse(url)
        result = _resolve_local_path(url, parsed)
        assert result is None


# ---------------------------------------------------------------------------
# _guess_suffix_from_file_content
# ---------------------------------------------------------------------------


class TestGuessSuffixFromFileContent:
    """Tests for _guess_suffix_from_file_content."""

    def test_pdf_magic(self, tmp_path):
        f = tmp_path / "data.file"
        f.write_bytes(b"%PDF-1.4 rest of pdf")
        result = _guess_suffix_from_file_content(f)
        assert result == ".pdf"

    def test_png_magic(self, tmp_path):
        f = tmp_path / "data.file"
        f.write_bytes(b"\x89PNG\r\n\x1a\nrest")
        result = _guess_suffix_from_file_content(f)
        assert result == ".png"

    def test_jpg_magic(self, tmp_path):
        f = tmp_path / "data.file"
        f.write_bytes(b"\xff\xd8\xff\xe0rest")
        result = _guess_suffix_from_file_content(f)
        assert result == ".jpg"

    def test_zip_magic(self, tmp_path):
        f = tmp_path / "data.file"
        f.write_bytes(b"PK\x03\x04rest")
        result = _guess_suffix_from_file_content(f)
        assert result == ".zip"

    def test_unknown_magic_returns_none(self, tmp_path):
        f = tmp_path / "data.file"
        f.write_bytes(b"unknown binary data")
        result = _guess_suffix_from_file_content(f)
        assert result is None

    def test_nonexistent_file_returns_none(self):
        result = _guess_suffix_from_file_content(Path("/nonexistent"))
        assert result is None


# ---------------------------------------------------------------------------
# download_file_from_base64
# ---------------------------------------------------------------------------


class TestDownloadFileFromBase64:
    """Tests for download_file_from_base64."""

    @pytest.mark.asyncio
    async def test_download_with_filename(self, tmp_path):
        import base64

        data = base64.b64encode(b"hello world").decode()
        result = await download_file_from_base64(
            data,
            filename="test.txt",
            download_dir=str(tmp_path),
        )
        assert "test.txt" in result
        assert Path(result).read_bytes() == b"hello world"

    @pytest.mark.asyncio
    async def test_download_without_filename(self, tmp_path):
        import base64

        data = base64.b64encode(b"content").decode()
        result = await download_file_from_base64(
            data,
            download_dir=str(tmp_path),
        )
        assert result is not None
        assert Path(result).exists()

    @pytest.mark.asyncio
    async def test_creates_download_dir(self, tmp_path):
        import base64

        data = base64.b64encode(b"data").decode()
        new_dir = tmp_path / "new_subdir"
        result = await download_file_from_base64(
            data,
            filename="f.txt",
            download_dir=str(new_dir),
        )
        assert new_dir.exists()
        assert Path(result).exists()


# ---------------------------------------------------------------------------
# download_file_from_url
# ---------------------------------------------------------------------------


class TestDownloadFileFromUrl:
    """Tests for download_file_from_url."""

    @pytest.mark.asyncio
    async def test_local_file_path(self, tmp_path):
        f = tmp_path / "local.txt"
        f.write_text("hello", encoding="utf-8")
        result = await download_file_from_url(str(f))
        assert result is not None
        assert "local.txt" in result

    @pytest.mark.asyncio
    @patch(
        "qwenpaw.agents.utils.file_handling._download_remote_to_path",
    )
    async def test_remote_download(self, mock_download, tmp_path):
        # Create a file that the mock download would produce
        target = tmp_path / "remote.txt"
        target.write_text("downloaded", encoding="utf-8")

        def fake_download(url, path):
            path.write_text("downloaded", encoding="utf-8")

        mock_download.side_effect = fake_download
        result = await download_file_from_url(
            "https://example.com/remote.txt",
            download_dir=str(tmp_path),
        )
        assert result is not None
