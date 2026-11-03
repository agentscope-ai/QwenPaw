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

import asyncio
from codecs import BOM_UTF8
import os
import stat
import threading
import time
from unittest.mock import patch

import pytest

from qwenpaw.agents.tools.file_io import (
    _append_file,
    _get_encoding_for_file,
    _resolve_file_path,
    append_file,
    edit_file,
    read_file,
    write_file,
)
from qwenpaw.agents.tools.utils import (
    TRUNCATION_METADATA_KEY,
    read_file_safe,
)
from qwenpaw.agents.utils.file_handling import (
    decode_text_bytes_with_encoding_fallback,
)


# ---------------------------------------------------------------------------
# _resolve_file_path
# ---------------------------------------------------------------------------


class TestResolveFilePath:
    """Tests for _resolve_file_path."""

    @patch("qwenpaw.agents.tools.file_io.get_tool_base_dir")
    def test_absolute_path_unchanged(self, mock_base):
        import sys
        from pathlib import Path

        # get_tool_base_dir() always returns a Path (project → workspace
        # → WORKING_DIR), so the stub must too: on Windows a drive-less
        # POSIX path is *not* absolute and gets joined against the base.
        mock_base.return_value = Path("/workspace")
        result = _resolve_file_path("/tmp/test.txt")
        # On Unix, path stays as-is; on Windows, it may get a
        # drive prefix (e.g. C:\tmp\test.txt)
        if sys.platform == "win32":
            assert result.endswith("test.txt")
        else:
            assert result == "/tmp/test.txt"

    @patch("qwenpaw.agents.tools.file_io.get_tool_base_dir")
    def test_relative_path_resolved(self, mock_base):
        from pathlib import Path

        mock_base.return_value = Path("/workspace")
        result = _resolve_file_path("subdir/file.txt")
        assert result == str(Path("/workspace/subdir/file.txt"))

    @patch("qwenpaw.agents.tools.file_io.get_tool_base_dir")
    def test_tilde_expansion(self, mock_base):
        from pathlib import Path

        mock_base.return_value = Path("/workspace")
        result = _resolve_file_path("~/test.txt")
        assert "~" not in result
        assert result.endswith("test.txt")

    def test_workspace_fallback_to_working_dir(self):
        # Nothing configured: get_tool_base_dir() itself falls back to
        # WORKING_DIR, so the resolver is left unpatched here.
        result = _resolve_file_path("file.txt")
        assert result.endswith("file.txt")


# ---------------------------------------------------------------------------
# _get_encoding_for_file
# ---------------------------------------------------------------------------


class TestGetEncodingForFile:
    """Tests for _get_encoding_for_file."""

    @pytest.mark.parametrize(
        "ext",
        [f".csv", f".tsv", f".tab"],
    )
    def test_bom_extensions(self, ext, tmp_path):
        path = tmp_path / f"data{ext}"
        assert _get_encoding_for_file(str(path)) == f"utf-8-sig"

    @pytest.mark.parametrize(
        "ext",
        [f".py", f".json", f".yaml", f".sh", f".md", f".js", f".txt", f".log"],
    )
    def test_non_bom_extensions(self, ext, tmp_path):
        path = tmp_path / f"code{ext}"
        assert _get_encoding_for_file(str(path)) == f"utf-8"


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
        assert "hello world" in result.content[0].text

    @pytest.mark.asyncio
    async def test_safe_read_uses_one_binary_snapshot(self, tmp_path):
        """Safe reads strip a UTF-8 BOM on the utf-8-sig path."""
        path = tmp_path / "snapshot.txt"
        path.write_bytes(b"\xef\xbb\xbfhello")

        assert await read_file_safe(str(path)) == "hello"

    @pytest.mark.asyncio
    async def test_safe_read_decodes_gbk_without_dropping_text(self, tmp_path):
        """GBK/CP936 notes must not be stripped by a UTF-8-only decode."""
        path = tmp_path / "gbk-note.txt"
        path.write_bytes(("姓名: 张三" + chr(10)).encode("gbk"))

        assert await read_file_safe(str(path)) == "姓名: 张三" + chr(10)

    @pytest.mark.asyncio
    async def test_safe_read_normalizes_platform_newlines(self, tmp_path):
        """Binary snapshots retain text-mode universal newline behavior."""
        path = tmp_path / "newlines.txt"
        path.write_bytes(b"first\r\nsecond\rthird\n")

        assert await read_file_safe(str(path)) == "first\nsecond\nthird\n"

    @pytest.mark.asyncio
    async def test_safe_read_truncated_utf8_keeps_valid_prefix(self, tmp_path):
        """Cutting a multibyte UTF-8 character must not fall through to GBK."""
        text = "行\r\n姓名: 张三"
        raw = text.encode("utf-8")
        snapshot = raw[:-1]
        path = tmp_path / "utf8.txt"
        # Extra bytes make this a capped read, not a short corrupt file.
        path.write_bytes(raw + b"TAIL")

        result = await read_file_safe(str(path), max_bytes=len(snapshot))

        assert result == "行\n姓名: 张"
        assert "三" not in result
        assert not result.startswith("å")

    @pytest.mark.asyncio
    async def test_safe_read_truncated_gbk_still_decodes(self, tmp_path):
        """A capped non-UTF-8 snapshot still uses the encoding ladder."""
        text = "姓名: 张三\n"
        raw = text.encode("gbk")
        with pytest.raises(UnicodeDecodeError):
            raw.decode("utf-8")
        path = tmp_path / "gbk.txt"
        path.write_bytes(raw + b"xxxx")

        assert await read_file_safe(str(path), max_bytes=len(raw)) == text

    @pytest.mark.asyncio
    async def test_safe_read_truncated_gbk_keeps_character_prefix(
        self,
        tmp_path,
    ):
        """A cap inside a GBK character keeps the valid prefix."""
        text = "姓名: 张三"
        raw = text.encode("gbk")
        path = tmp_path / "gbk-cut.txt"
        path.write_bytes(raw + b"TAIL")

        result = await read_file_safe(str(path), max_bytes=len(raw) - 1)

        assert result == "姓名: 张"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prefix", [b"\xef", b"\xef\xbb"])
    async def test_safe_read_incomplete_bom_matches_shared_helper(
        self,
        tmp_path,
        prefix,
    ):
        """Full incomplete BOM follows the ladder; capped keeps empty prefix."""
        expected = decode_text_bytes_with_encoding_fallback(prefix)

        whole = tmp_path / "whole.txt"
        whole.write_bytes(prefix)
        assert await read_file_safe(str(whole)) == expected

        # Cap inside the BOM / first multibyte must not fall through to GBK.
        capped = tmp_path / "capped.txt"
        capped.write_bytes(prefix + b"TAIL")
        assert await read_file_safe(str(capped), max_bytes=len(prefix)) == ""

    @pytest.mark.asyncio
    async def test_safe_read_mostly_utf8_keeps_chinese_on_dirty_byte(
        self,
        tmp_path,
    ):
        """One invalid byte must not send a UTF-8 Chinese note through GBK."""
        path = tmp_path / "dirty.txt"
        path.write_bytes("姓名: 张三\n".encode("utf-8") + b"\xff")

        result = await read_file_safe(str(path))

        assert "张三" in result
        assert "\N{REPLACEMENT CHARACTER}" in result
        assert not result.startswith("å")

    @pytest.mark.asyncio
    async def test_safe_read_short_gbk_keeps_character(self, tmp_path):
        """Short GBK falls through instead of a lossy UTF-8 decode."""
        path = tmp_path / "short-gbk.txt"
        path.write_bytes("A张".encode("gbk"))

        result = await read_file_safe(str(path))

        assert "张" in result

    @pytest.mark.asyncio
    async def test_safe_read_short_cp1252_keeps_accent(self, tmp_path):
        """Short CP1252 keeps the accented character."""
        path = tmp_path / "cafe.txt"
        path.write_bytes("Café".encode("cp1252"))

        result = await read_file_safe(str(path))

        assert result == "Café"

    @pytest.mark.asyncio
    async def test_safe_read_cap_inside_first_multibyte_is_empty(
        self,
        tmp_path,
    ):
        """max_bytes inside the first UTF-8 character yields an empty prefix."""
        raw = "张三".encode("utf-8")
        path = tmp_path / "first.txt"
        path.write_bytes(raw + b"TAIL")

        assert await read_file_safe(str(path), max_bytes=1) == ""
        assert await read_file_safe(str(path), max_bytes=2) == ""
        assert await read_file_safe(str(path), max_bytes=3) == "张"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path):
        result = await read_file(str(tmp_path / "missing.txt"))
        assert "does not exist" in result.content[0].text

    @pytest.mark.asyncio
    async def test_read_directory_error(self, tmp_path):
        result = await read_file(str(tmp_path))
        assert "not a file" in result.content[0].text

    @pytest.mark.asyncio
    async def test_read_with_line_range(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
        result = await read_file(str(f), start_line=2, end_line=3)
        text = result.content[0].text
        assert "line2" in text
        assert "line3" in text
        info = result.metadata[TRUNCATION_METADATA_KEY]["0"]
        assert info["file_path"] == str(f)
        assert info["file_size_bytes"] == len(
            f.read_text(encoding="utf-8").encode("utf-8"),
        )
        assert info["start_line"] == 2
        assert text.endswith(info["notice"])

    @pytest.mark.asyncio
    async def test_read_with_string_line_range(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

        result = await read_file(str(f), start_line="2", end_line="3")

        text = result.content[0].text
        assert "line1" not in text
        assert "line2" in text
        assert "line3" in text
        assert "line4" not in text

    @pytest.mark.asyncio
    async def test_read_start_line_exceeds_file(self, tmp_path):
        f = tmp_path / "short.txt"
        f.write_text("only one line\n", encoding="utf-8")
        result = await read_file(str(f), start_line=100)
        assert "exceeds file length" in result.content[0].text

    @pytest.mark.asyncio
    async def test_read_invalid_start_line(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("data\n", encoding="utf-8")
        result = await read_file(str(f), start_line="abc")
        assert "must be an integer" in result.content[0].text

    @pytest.mark.asyncio
    async def test_read_invalid_end_line(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("data\n", encoding="utf-8")
        result = await read_file(str(f), end_line="xyz")
        assert "must be an integer" in result.content[0].text

    @pytest.mark.asyncio
    async def test_read_start_greater_than_end(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = await read_file(str(f), start_line=3, end_line=1)
        assert "start_line" in result.content[0].text


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    """Tests for write_file."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(f"ext", [f".txt", f".log"])
    async def test_write_new_file(self, tmp_path, ext):
        f = tmp_path / f"new{ext}"
        result = await write_file(str(f), "hello")
        assert "Wrote" in result.content[0].text
        assert f.read_bytes() == f"hello".encode(f"utf-8")
        if os.name != "nt":
            assert stat.S_IMODE(f.stat().st_mode) == 0o644

    @pytest.mark.asyncio
    @pytest.mark.parametrize(f"ext", [f".txt", f".csv", f".py"])
    @pytest.mark.parametrize(f"encoding", [f"utf-8", f"utf-8-sig"])
    async def test_write_overwrites_existing(self, tmp_path, ext, encoding):
        f = tmp_path / f"existing{ext}"
        f.write_bytes(f"old".encode(encoding))
        await write_file(str(f), f"green, white")
        assert f.read_bytes() == f"green, white".encode(encoding)

    @pytest.mark.asyncio
    async def test_write_empty_path(self):
        result = await write_file("", "content")
        assert (
            "No" in result.content[0].text
            and "file_path" in result.content[0].text
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
    async def test_edit_preserves_gbk_text(self, tmp_path):
        """edit_file must not persist a lossy UTF-8 decode of a GBK file."""
        f = tmp_path / "note.txt"
        f.write_bytes(("姓名: 张三" + chr(10)).encode("gbk"))
        result = await edit_file(str(f), "张三", "李四")
        assert "Successfully replaced" in result.content[0].text
        assert f.read_text(encoding="utf-8-sig") == "姓名: 李四" + chr(10)

    @pytest.mark.asyncio
    async def test_edit_short_gbk_writes_utf8(self, tmp_path):
        """Short GBK ``A张`` is replaced and rewritten as UTF-8."""
        f = tmp_path / "short-gbk.txt"
        f.write_bytes("A张".encode("gbk"))

        result = await edit_file(str(f), "张", "李")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_text(encoding="utf-8") == "A李"
        assert "\ufffd" not in f.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_edit_short_cp1252_does_not_truncate(self, tmp_path):
        """Short CP1252 ``Café`` is replaced, not saved truncated."""
        f = tmp_path / "cafe.txt"
        f.write_bytes("Café".encode("cp1252"))

        result = await edit_file(str(f), "Café", "Cafe")

        assert "Successfully replaced" in result.content[0].text
        written = f.read_text(encoding="utf-8")
        assert written == "Cafe"
        assert "\ufffd" not in written

    @pytest.mark.parametrize(f"ext", [f".txt", f".csv", f".py"])
    @pytest.mark.parametrize(f"encoding", [f"utf-8", f"utf-8-sig"])
    async def test_edit_replaces_text(self, tmp_path, ext, encoding):
        f = tmp_path / f"edit{ext}"
        f.write_bytes(f"hello world".encode(encoding))
        result = await edit_file(str(f), f"hello", f"goodbye")
        assert f"Successfully replaced" in result.content[0].text
        assert f.read_bytes() == f"goodbye world".encode(encoding)

    @pytest.mark.asyncio
    async def test_edit_text_not_found(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world", encoding="utf-8")
        result = await edit_file(str(f), "missing", "replacement")
        assert "not found" in result.content[0].text

    @pytest.mark.asyncio
    async def test_edit_nonexistent_file(self, tmp_path):
        result = await edit_file(str(tmp_path / "missing.txt"), "a", "b")
        assert "does not exist" in result.content[0].text

    @pytest.mark.asyncio
    async def test_edit_empty_path(self):
        result = await edit_file("", "a", "b")
        assert (
            "No" in result.content[0].text
            and "file_path" in result.content[0].text
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
    @pytest.mark.parametrize(f"ext", [f".txt", f".csv"])
    @pytest.mark.parametrize(f"encoding", [f"utf-8", f"utf-8-sig"])
    @pytest.mark.parametrize(f"initial", [f"", f"first"])
    async def test_append_to_existing(
        self,
        tmp_path,
        ext,
        encoding,
        initial,
    ):
        f = tmp_path / f"append{ext}"
        f.write_bytes(initial.encode(encoding))
        result = await append_file(str(f), f"second")
        assert f"Appended" in result.content[0].text
        assert f.read_bytes() == f"{initial}second".encode(encoding)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(f"ext", [f".txt", f".log", f".csv"])
    async def test_append_creates_new_file(self, tmp_path, ext):
        f = tmp_path / f"new_append{ext}"
        result = await append_file(str(f), "first line")
        assert "Appended" in result.content[0].text
        bom = BOM_UTF8 if ext == f".csv" else bytes()
        assert f.read_bytes() == bom + f"first line".encode(f"utf-8")

    @pytest.mark.asyncio
    async def test_append_empty_path(self):
        result = await append_file("", "content")
        assert (
            "No" in result.content[0].text
            and "file_path" in result.content[0].text
        )

    @pytest.mark.asyncio
    async def test_concurrent_appends_are_serialized_per_path(self, tmp_path):
        f = tmp_path / "concurrent.txt"
        active = 0
        max_active = 0
        guard = threading.Lock()

        def delayed_append(file_path, content):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)
            _append_file(file_path, content)
            with guard:
                active -= 1

        with patch(
            f"qwenpaw.agents.tools.file_io._append_file",
            delayed_append,
        ):
            await asyncio.gather(
                *(append_file(str(f), f"{index}\n") for index in range(8)),
            )

        assert max_active == 1
        assert len(f.read_text(encoding="utf-8-sig").splitlines()) == 8
