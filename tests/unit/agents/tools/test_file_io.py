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
    _decode_capped_text_snapshot,
    _read_file_safe_sync,
    read_file_safe,
)
from qwenpaw.agents.utils.file_handling import (
    _decode_mostly_utf8_lossy,
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
    @pytest.mark.parametrize("partial", [0, 1, 2])
    async def test_safe_read_capped_dirty_utf8_keeps_prefix(
        self,
        tmp_path,
        partial,
    ):
        """Cap after dirty byte + partial 行 must keep 张三, not Latin-1."""
        base = "姓名: 张三\n".encode("utf-8") + b"\xff"
        content = base + "行".encode("utf-8")[:partial]
        path = tmp_path / "capped-dirty.txt"
        path.write_bytes(content + b"TAIL")

        result = await read_file_safe(str(path), max_bytes=len(content))

        assert "张三" in result
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
    async def test_safe_read_longer_gbk_keeps_character(self, tmp_path):
        """GBK ``name=锘`` must not collapse to a lossy UTF-8 replacement."""
        path = tmp_path / "name.txt"
        path.write_bytes("name=锘".encode("gbk"))

        assert await read_file_safe(str(path)) == "name=锘"

    @pytest.mark.asyncio
    async def test_safe_read_gbk_qiao_not_lossy(self, tmp_path):
        """GBK ``name=丂`` must not become lossy UTF-8 ``name=\ufffd@``."""
        path = tmp_path / "qiao.txt"
        path.write_bytes("name=丂".encode("gbk"))

        assert await read_file_safe(str(path)) == "name=丂"

    @pytest.mark.asyncio
    async def test_safe_read_longer_cp1252_keeps_accent(self, tmp_path):
        """CP1252 ``Cafés`` must not collapse to a lossy UTF-8 replacement."""
        path = tmp_path / "cafes.txt"
        path.write_bytes("Cafés".encode("cp1252"))

        assert await read_file_safe(str(path)) == "Cafés"

    async def test_safe_read_gbk_letter_trails_without_unpaired_ascii(
        self,
        tmp_path,
    ):
        """GBK pairs whose trails are ASCII letters stay GBK, not CP1252."""
        raw = bytes.fromhex("99748c48")
        path = tmp_path / "pairs.txt"
        path.write_bytes(raw)

        assert await read_file_safe(str(path)) == "\u6a9b\u5b52"
        assert _read_file_safe_sync(str(path), 64) == "\u6a9b\u5b52"

    @pytest.mark.asyncio
    async def test_safe_read_bom_and_dirty_byte_strips_bom(self, tmp_path):
        """A BOM plus one invalid byte is lossy UTF-8 without U+FEFF."""
        path = tmp_path / "bom.txt"
        path.write_bytes(b"\xef\xbb\xbfhello\xff")

        result = await read_file_safe(str(path))

        assert result == "hello\ufffd"
        assert not result.startswith("\ufeff")

    @pytest.mark.asyncio
    async def test_safe_read_utf8_chinese_cp1252_decodable_stays(
        self,
        tmp_path,
    ):
        """A dirty UTF-8 note that CP1252 accepts must stay Chinese."""
        path = tmp_path / "nihao.txt"
        path.write_bytes("你好世界\n".encode("utf-8") + b"\xff")

        result = await read_file_safe(str(path))

        assert "你好世界" in result
        assert "\ufffd" in result
        assert "ä" not in result

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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("name=锘".encode("gbk"), "name=锘"),
        ("name=锘 and more".encode("gbk"), "name=锘 and more"),
        ("Cafés".encode("cp1252"), "Cafés"),
        ("Cafés au lait".encode("cp1252"), "Cafés au lait"),
    ],
)
def test_decode_longer_legacy_strings(raw, expected):
    """Longer GBK/CP1252 must fall through a sparse lossy UTF-8 decode."""
    assert _decode_mostly_utf8_lossy(raw) is None
    assert decode_text_bytes_with_encoding_fallback(raw) == expected


def test_decode_gbk_letter_trails_without_unpaired_ascii():
    """Pure GBK with letter trails must not be decoded as CP1252."""
    raw = bytes.fromhex("99748c48")
    assert decode_text_bytes_with_encoding_fallback(raw) == "\u6a9b\u5b52"


def test_lossy_utf8_strips_bom_before_dirty_byte():
    """BOM + invalid tail is lossy UTF-8 with the BOM removed."""
    raw = b"\xef\xbb\xbfhello\xff"
    assert _decode_mostly_utf8_lossy(raw) == "hello\ufffd"
    assert decode_text_bytes_with_encoding_fallback(raw) == "hello\ufffd"


def test_lossy_utf8_keeps_dirty_chinese_and_ascii_lead():
    """Real UTF-8 text with one dirty byte stays lossy, not legacy."""
    chinese = "姓名: 张三\n".encode("utf-8") + b"\xff"
    text = _decode_mostly_utf8_lossy(chinese)
    assert text is not None and "张三" in text and "\ufffd" in text

    # CP1252 can decode this note; lossy UTF-8 must still win.
    nihao = "你好世界\n".encode("utf-8") + b"\xff"
    nihao_text = decode_text_bytes_with_encoding_fallback(nihao)
    assert "你好世界" in nihao_text
    assert "\ufffd" in nihao_text

    # A dirty lead that GBK would pair with the next letter stays lossy.
    dirty_lead = decode_text_bytes_with_encoding_fallback(b"hello\x81world")
    assert dirty_lead == "hello\ufffdworld"


def test_decode_gbk_ascii_prefix_not_cp1252():
    """GBK ``name=檔`` must not become CP1252 ``name=™n``."""
    raw = "name=檔".encode("gbk")
    assert decode_text_bytes_with_encoding_fallback(raw) == "name=檔"


def test_decode_gbk_not_overridden_by_accidental_utf8():
    """GBK ``name=一锘`` must not keep a lossy UTF-8 decode of ``一``."""
    raw = "name=一锘".encode("gbk")
    assert decode_text_bytes_with_encoding_fallback(raw) == "name=一锘"


def test_decode_gbk_zhebu_not_lossy_utf8():
    """GBK ``name=这不`` must not keep incidental three-byte lossy UTF-8."""
    raw = "name=这不".encode("gbk")
    assert decode_text_bytes_with_encoding_fallback(raw) == "name=这不"


def test_decode_gbk_rubu_not_lossy_utf8():
    """GBK ``name=如不`` must not keep incidental CJK lossy UTF-8."""
    raw = "name=如不\n".encode("gbk")
    assert decode_text_bytes_with_encoding_fallback(raw) == "name=如不\n"
    assert "\ufffd" not in decode_text_bytes_with_encoding_fallback(raw)


def test_decode_gbk_qijing_not_lossy_utf8():
    """GBK ``name=其经`` must not keep incidental CJK lossy UTF-8."""
    raw = "name=其经\n".encode("gbk")
    assert decode_text_bytes_with_encoding_fallback(raw) == "name=其经\n"
    assert "\ufffd" not in decode_text_bytes_with_encoding_fallback(raw)


def test_decode_gbk_qiao_not_lossy_utf8():
    """Strict GBK must win for ``name=丂`` instead of ``name=\ufffd@``."""
    raw = "name=丂".encode("gbk")
    assert raw == b"name=\x81@"
    assert decode_text_bytes_with_encoding_fallback(raw) == "name=丂"
    assert "\ufffd" not in decode_text_bytes_with_encoding_fallback(raw)


def test_decode_gbk_axc0a_not_cp1252():
    """Ambiguous ``A\\xc0A`` is valid GBK ``A繟``, not CP1252 ``AÀA``."""
    raw = b"A\xc0A"
    assert decode_text_bytes_with_encoding_fallback(raw) == "A繟"
    assert decode_text_bytes_with_encoding_fallback(raw) != "AÀA"


def test_decode_capped_utf8_partial_char_keeps_prefix():
    """A max_bytes cut mid-character must not inflate invalids into Latin-1."""
    base = "姓名: 张三\n".encode("utf-8") + b"\xff"
    for n in (0, 1, 2):
        content = base + "行".encode("utf-8")[:n]
        text = _decode_capped_text_snapshot(
            content,
            file_name="note.txt",
            truncated=True,
        )
        assert "张三" in text
        assert not text.startswith("å")


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
    async def test_edit_rubu_gbk_not_lossy(self, tmp_path):
        """edit_file must keep GBK ``如不`` instead of lossy CJK leftovers."""
        f = tmp_path / "rubu.txt"
        f.write_bytes("name=如不\n".encode("gbk"))
        result = await edit_file(str(f), "name=", "title=")
        assert "Successfully replaced" in result.content[0].text
        assert f.read_text(encoding="utf-8") == "title=如不\n"
        assert "\ufffd" not in f.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_edit_gbk_qiao_not_lossy(self, tmp_path):
        """edit_file must keep GBK ``丂`` instead of persisting ``\ufffd@``."""
        f = tmp_path / "qiao.txt"
        f.write_bytes("name=丂".encode("gbk"))
        result = await edit_file(str(f), "name=", "title=")
        assert "Successfully replaced" in result.content[0].text
        assert f.read_text(encoding="utf-8") == "title=丂"
        assert "\ufffd" not in f.read_text(encoding="utf-8")

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

    @pytest.mark.asyncio
    async def test_edit_longer_gbk_writes_utf8(self, tmp_path):
        """GBK ``name=锘`` is found and rewritten without U+FFFD."""
        f = tmp_path / "name.txt"
        f.write_bytes("name=锘".encode("gbk"))

        result = await edit_file(str(f), "锘", "锁")

        assert "Successfully replaced" in result.content[0].text
        written = f.read_text(encoding="utf-8")
        assert written == "name=锁"
        assert "\ufffd" not in written

    @pytest.mark.asyncio
    async def test_edit_longer_cp1252_keeps_accent(self, tmp_path):
        """CP1252 ``Cafés`` is replaced, not saved with U+FFFD."""
        f = tmp_path / "cafes.txt"
        f.write_bytes("Cafés".encode("cp1252"))

        result = await edit_file(str(f), "Cafés", "Cafes")

        assert "Successfully replaced" in result.content[0].text
        written = f.read_text(encoding="utf-8")
        assert written == "Cafes"
        assert "\ufffd" not in written

    @pytest.mark.asyncio
    async def test_edit_gbk_letter_trails_not_saved_as_cp1252(self, tmp_path):
        """Editing GBK letter-trail pairs must not persist CP1252 mojibake."""
        f = tmp_path / "pairs.txt"
        f.write_bytes(bytes.fromhex("99748c48"))

        result = await edit_file(str(f), "\u6a9b", "A")

        assert "Successfully replaced" in result.content[0].text
        written = f.read_text(encoding="utf-8")
        assert written == "A\u5b52"
        assert "\u2122" not in written

    @pytest.mark.asyncio
    async def test_edit_gbk_name_dang_not_cp1252(self, tmp_path):
        """Editing GBK ``name=檔`` must not persist ``title=™n``."""
        f = tmp_path / "dang.txt"
        f.write_bytes("name=檔".encode("gbk"))

        result = await edit_file(str(f), "name=", "title=")

        assert "Successfully replaced" in result.content[0].text
        written = f.read_text(encoding="utf-8")
        assert written == "title=檔"
        assert "\u2122" not in written

    @pytest.mark.asyncio
    async def test_edit_gbk_yi_nuo_keeps_characters(self, tmp_path):
        """Editing GBK ``name=一锘`` must find the real characters."""
        f = tmp_path / "yi.txt"
        f.write_bytes("name=一锘".encode("gbk"))

        result = await edit_file(str(f), "一锘", "锁")

        assert "Successfully replaced" in result.content[0].text
        written = f.read_text(encoding="utf-8")
        assert written == "name=锁"
        assert "\ufffd" not in written

    @pytest.mark.asyncio
    async def test_edit_bom_and_dirty_byte_does_not_double_bom(self, tmp_path):
        """Editing BOM + invalid byte must not persist a second BOM."""
        f = tmp_path / "bom.txt"
        f.write_bytes(b"\xef\xbb\xbfhello\xff")

        result = await edit_file(str(f), "hello", "hi")

        assert "Successfully replaced" in result.content[0].text
        raw = f.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        assert not raw.startswith(b"\xef\xbb\xbf\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        assert text.startswith("hi")
        assert "\ufeff" not in text

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

    @pytest.mark.asyncio
    async def test_edit_preserves_crlf_line_endings(self, tmp_path):
        """edit_file must not rewrite a CRLF file as LF (full-file diffs)."""
        f = tmp_path / "app.py"
        f.write_bytes(b'def hi():\r\n    return "old"\r\n')

        result = await edit_file(str(f), "old", "new")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b'def hi():\r\n    return "new"\r\n'

    @pytest.mark.asyncio
    async def test_edit_preserves_lf_line_endings(self, tmp_path):
        """LF files stay LF after a successful edit."""
        f = tmp_path / "app.py"
        f.write_bytes(b'def hi():\n    return "old"\n')

        result = await edit_file(str(f), "old", "new")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b'def hi():\n    return "new"\n'

    @pytest.mark.asyncio
    async def test_edit_preserves_mixed_line_endings(self, tmp_path):
        """One CRLF must not rewrite the other lines of an LF file."""
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"alpha\nbeta\r\ngamma\n")

        result = await edit_file(str(f), "beta", "BETA")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"alpha\nBETA\r\ngamma\n"

    @pytest.mark.asyncio
    async def test_edit_maps_match_across_mixed_newline(self, tmp_path):
        """A match that covers CRLF keeps the surrounding endings."""
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"alpha\nbeta\r\ngamma\n")

        result = await edit_file(str(f), "beta\ngamma", "BETA\nGAMMA")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"alpha\nBETA\r\nGAMMA\n"

    @pytest.mark.asyncio
    async def test_edit_reuses_each_original_break_in_order(self, tmp_path):
        """Same break count keeps each matched ending in position.

        Replacing ``a\\n b\\n c`` must not copy the leading CRLF onto the
        following LF.
        """
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"a\r\nb\nc\r\nd")

        result = await edit_file(str(f), "a\nb\nc", "a\nB\nc")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"a\r\nB\nc\r\nd"

    @pytest.mark.asyncio
    async def test_edit_reuses_endings_on_every_match(self, tmp_path):
        """Each match reuses its own endings in one streaming pass."""
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"a\r\nb\nc\r\nda\nb\nc\n")

        result = await edit_file(str(f), "a\nb\nc", "a\nB\nc")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"a\r\nB\nc\r\nda\nB\nc\n"

    @pytest.mark.asyncio
    async def test_edit_folds_new_text_before_reusing_endings(
        self,
        tmp_path,
    ):
        """CRLF typed in new_text does not override original endings."""
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"a\r\nb\nc\r\nd")

        result = await edit_file(str(f), "a\nb\nc", "a\r\nB\r\nc")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"a\r\nB\nc\r\nd"

    @pytest.mark.asyncio
    async def test_edit_styles_extra_breaks_from_the_span(self, tmp_path):
        """Added breaks follow the span when the break count changes."""
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"a\r\nb\nc\r\nd")

        result = await edit_file(str(f), "b\nc", "B\nC\nX")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"a\r\nB\nC\nX\r\nd"

    @pytest.mark.asyncio
    async def test_edit_preserves_each_distinct_line_ending(self, tmp_path):
        """LF, CRLF, and lone CR on different lines all stay put."""
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"alpha\nbeta\r\ngamma\rdelta\n")

        result = await edit_file(str(f), "beta", "BETA")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"alpha\nBETA\r\ngamma\rdelta\n"

    @pytest.mark.asyncio
    async def test_edit_styles_new_breaks_on_pure_crlf(self, tmp_path):
        """Breaks introduced in new_text follow a pure CRLF file."""
        f = tmp_path / "app.py"
        f.write_bytes(b"keep\r\nold\r\n")

        result = await edit_file(str(f), "old", "new\nline")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"keep\r\nnew\r\nline\r\n"

    @pytest.mark.asyncio
    async def test_edit_styles_new_breaks_on_pure_lf(self, tmp_path):
        """Breaks introduced in new_text stay LF in a pure LF file."""
        f = tmp_path / "app.py"
        f.write_bytes(b"keep\nold\n")

        result = await edit_file(str(f), "old", "new\nline")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"keep\nnew\nline\n"

    @pytest.mark.asyncio
    async def test_edit_preserves_cr_line_endings(self, tmp_path):
        """Lone CR files stay CR, including breaks new_text introduces."""
        f = tmp_path / "legacy.txt"
        f.write_bytes(b"keep\rold\r")

        result = await edit_file(str(f), "old", "new\nline")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"keep\rnew\rline\r"

    @pytest.mark.asyncio
    async def test_edit_keeps_break_between_lone_cr_and_lf(self, tmp_path):
        """Deleting text between a lone CR and an LF keeps both breaks."""
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"\ra\nb")

        result = await edit_file(str(f), "a", "")

        assert "Successfully replaced" in result.content[0].text
        updated = f.read_bytes()
        lf_view = updated.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert lf_view == b"\n\nb"
        assert updated == b"\r\n\nb"

    @pytest.mark.asyncio
    async def test_edit_keeps_positional_lone_cr_then_lf(self, tmp_path):
        """Reusing a lone CR and the next LF must stay two breaks.

        Positional endings used to join ``\\r`` directly to ``\\n`` and
        collapse ``\\ra\\n`` edited as ``\\na\\n`` -> ``\\n\\n`` into one
        CRLF.
        """
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"\ra\n")

        result = await edit_file(str(f), "\na\n", "\n\n")

        assert "Successfully replaced" in result.content[0].text
        updated = f.read_bytes()
        lf_view = updated.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert lf_view == b"\n\n"
        assert updated == b"\r\n\n"

    @pytest.mark.asyncio
    async def test_edit_styles_repeated_matches_from_one_line_ending(
        self,
        tmp_path,
    ):
        """Matches on one line share that line's ending.

        Each ``a`` has no break, and ``new_text`` adds one, so every
        replacement takes the CRLF that ends the run. A later match past
        that CRLF takes the following LF, not the cached CRLF.
        """
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"aaa\r\nx\na")

        result = await edit_file(str(f), "a", "b\nc")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"b\r\ncb\r\ncb\r\nc\r\nx\nb\nc"

    @pytest.mark.asyncio
    async def test_edit_normalizes_trailing_lone_cr_in_new_text(
        self,
        tmp_path,
    ):
        """A trailing lone CR in new_text must not swallow the next LF.

        Folding ``new_text`` only after ``str.replace`` lets ``\\r`` join
        the untouched ``\\n`` and collapse to one break.
        """
        f = tmp_path / "lf.txt"
        f.write_bytes(b"a\nb")

        result = await edit_file(str(f), "a", "\r")

        assert "Successfully replaced" in result.content[0].text
        assert f.read_bytes() == b"\n\nb"


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
