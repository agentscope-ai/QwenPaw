# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.tools.file_io.

Covers:
- _resolve_file_path
- _get_encoding_for_file
- read_file
- write_file
- edit_file
- append_file
"""
# pylint: disable=protected-access,unused-argument

from unittest.mock import patch

import pytest

from qwenpaw.agents.tools.file_io import (
    _get_encoding_for_file,
    _resolve_file_path,
    append_file,
    edit_file,
    read_file,
    write_file,
)


# ---------------------------------------------------------------------------
# _resolve_file_path
# ---------------------------------------------------------------------------


class TestResolveFilePath:
    """Tests for _resolve_file_path."""

    @patch("qwenpaw.agents.tools.file_io.get_current_workspace_dir")
    def test_absolute_path_unchanged(self, mock_ws):
        import sys

        mock_ws.return_value = None
        result = _resolve_file_path("/tmp/test.txt")
        # On Unix, path stays as-is; on Windows, it may get a
        # drive prefix (e.g. C:\tmp\test.txt)
        if sys.platform == "win32":
            assert result.endswith("test.txt")
        else:
            assert result == "/tmp/test.txt"

    @patch("qwenpaw.agents.tools.file_io.get_current_workspace_dir")
    def test_relative_path_resolved(self, mock_ws):
        from pathlib import Path

        mock_ws.return_value = Path("/workspace")
        result = _resolve_file_path("subdir/file.txt")
        assert result == str(Path("/workspace/subdir/file.txt"))

    @patch("qwenpaw.agents.tools.file_io.get_current_workspace_dir")
    def test_tilde_expansion(self, mock_ws):
        mock_ws.return_value = None
        result = _resolve_file_path("~/test.txt")
        assert "~" not in result
        assert result.endswith("test.txt")

    @patch("qwenpaw.agents.tools.file_io.get_current_workspace_dir")
    def test_workspace_fallback_to_working_dir(self, mock_ws):
        mock_ws.return_value = None
        # When workspace is None, WORKING_DIR is used
        result = _resolve_file_path("file.txt")
        assert result.endswith("file.txt")


# ---------------------------------------------------------------------------
# _get_encoding_for_file
# ---------------------------------------------------------------------------


class TestGetEncodingForFile:
    """Tests for _get_encoding_for_file."""

    @pytest.mark.parametrize(
        "ext",
        [".csv", ".tsv", ".tab", ".txt", ".log"],
    )
    def test_bom_extensions(self, ext):
        assert _get_encoding_for_file(f"data{ext}") == "utf-8-sig"

    @pytest.mark.parametrize(
        "ext",
        [".py", ".json", ".yaml", ".sh", ".md", ".js"],
    )
    def test_non_bom_extensions(self, ext):
        assert _get_encoding_for_file(f"code{ext}") == "utf-8"


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    """Tests for read_file."""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = await read_file(str(f))
        assert "hello world" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path):
        result = await read_file(str(tmp_path / "missing.txt"))
        assert "does not exist" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_directory_error(self, tmp_path):
        result = await read_file(str(tmp_path))
        assert "not a file" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_with_line_range(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
        result = await read_file(str(f), start_line=2, end_line=3)
        text = result.content[0]["text"]
        assert "line2" in text
        assert "line3" in text

    @pytest.mark.asyncio
    async def test_read_start_line_exceeds_file(self, tmp_path):
        f = tmp_path / "short.txt"
        f.write_text("only one line\n", encoding="utf-8")
        result = await read_file(str(f), start_line=100)
        assert "exceeds file length" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_invalid_start_line(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("data\n", encoding="utf-8")
        result = await read_file(str(f), start_line="abc")
        assert "must be an integer" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_invalid_end_line(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("data\n", encoding="utf-8")
        result = await read_file(str(f), end_line="xyz")
        assert "must be an integer" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_start_greater_than_end(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = await read_file(str(f), start_line=3, end_line=1)
        assert "start_line" in result.content[0]["text"]


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    """Tests for write_file."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, tmp_path):
        f = tmp_path / "new.txt"
        result = await write_file(str(f), "hello")
        assert "Wrote" in result.content[0]["text"]
        # .txt uses utf-8-sig which adds BOM
        assert f.read_text(encoding="utf-8-sig") == "hello"

    @pytest.mark.asyncio
    async def test_write_overwrites_existing(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("old", encoding="utf-8")
        await write_file(str(f), "new")
        assert f.read_text(encoding="utf-8-sig") == "new"

    @pytest.mark.asyncio
    async def test_write_empty_path(self):
        result = await write_file("", "content")
        assert (
            "No" in result.content[0]["text"]
            and "file_path" in result.content[0]["text"]
        )

    @pytest.mark.asyncio
    async def test_write_csv_uses_bom(self, tmp_path):
        f = tmp_path / "data.csv"
        await write_file(str(f), "a,b,c")
        content_bytes = f.read_bytes()
        # UTF-8 BOM starts with EF BB BF
        assert content_bytes[:3] == b"\xef\xbb\xbf"

    @pytest.mark.asyncio
    async def test_write_py_uses_no_bom(self, tmp_path):
        f = tmp_path / "code.py"
        await write_file(str(f), "print('hi')")
        content_bytes = f.read_bytes()
        assert content_bytes[:3] != b"\xef\xbb\xbf"


# ---------------------------------------------------------------------------
# edit_file
# ---------------------------------------------------------------------------


class TestEditFile:
    """Tests for edit_file."""

    @pytest.mark.asyncio
    async def test_edit_replaces_text(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world", encoding="utf-8")
        result = await edit_file(str(f), "hello", "goodbye")
        assert "Successfully replaced" in result.content[0]["text"]
        assert f.read_text(encoding="utf-8-sig") == "goodbye world"

    @pytest.mark.asyncio
    async def test_edit_text_not_found(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world", encoding="utf-8")
        result = await edit_file(str(f), "missing", "replacement")
        assert "not found" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_edit_nonexistent_file(self, tmp_path):
        result = await edit_file(str(tmp_path / "missing.txt"), "a", "b")
        assert "does not exist" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_edit_empty_path(self):
        result = await edit_file("", "a", "b")
        assert (
            "No" in result.content[0]["text"]
            and "file_path" in result.content[0]["text"]
        )

    @pytest.mark.asyncio
    async def test_edit_replaces_all_occurrences(self, tmp_path):
        f = tmp_path / "multi.txt"
        f.write_text("aaa bbb aaa", encoding="utf-8")
        await edit_file(str(f), "aaa", "ccc")
        assert f.read_text(encoding="utf-8-sig") == "ccc bbb ccc"


# ---------------------------------------------------------------------------
# append_file
# ---------------------------------------------------------------------------


class TestAppendFile:
    """Tests for append_file."""

    @pytest.mark.asyncio
    async def test_append_to_existing(self, tmp_path):
        f = tmp_path / "append.txt"
        f.write_text("line1\n", encoding="utf-8")
        result = await append_file(str(f), "line2\n")
        assert "Appended" in result.content[0]["text"]
        assert f.read_text(encoding="utf-8") == "line1\nline2\n"

    @pytest.mark.asyncio
    async def test_append_creates_new_file(self, tmp_path):
        f = tmp_path / "new_append.txt"
        result = await append_file(str(f), "first line")
        assert "Appended" in result.content[0]["text"]
        assert f.read_text(encoding="utf-8-sig") == "first line"

    @pytest.mark.asyncio
    async def test_append_empty_path(self):
        result = await append_file("", "content")
        assert (
            "No" in result.content[0]["text"]
            and "file_path" in result.content[0]["text"]
        )
