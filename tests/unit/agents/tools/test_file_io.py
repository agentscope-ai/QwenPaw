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
import os
import stat
import threading
import time
from pathlib import Path
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
from qwenpaw.agents.tools.utils import (
    TRUNCATION_METADATA_KEY,
    read_file_safe,
)
from qwenpaw.config.context import (
    set_current_project_dir,
    set_current_project_dirs,
    set_current_workspace_dir,
)
from qwenpaw.services.project_directory import (
    PathEscapeError,
    ResolvedProjectDir,
)


@pytest.fixture(autouse=True)
def _grant_tmp_path(tmp_path):
    """Authorize each test's tmp_path as the effective project root.

    At runtime ContextVarsSetupHook always populates the project-root
    contextvars; unit tests mirror that instead of relying on the
    global WORKING_DIR fallback.
    """
    root = tmp_path.resolve()
    set_current_workspace_dir(root)
    set_current_project_dir(root)
    set_current_project_dirs((ResolvedProjectDir(path=root, exists=True),))
    yield
    set_current_workspace_dir(None)
    set_current_project_dir(None)
    set_current_project_dirs(None)


def _clear_project_context() -> None:
    set_current_workspace_dir(None)
    set_current_project_dir(None)
    set_current_project_dirs(None)


# ---------------------------------------------------------------------------
# _resolve_file_path
# ---------------------------------------------------------------------------


class TestResolveFilePath:
    """Tests for _resolve_file_path."""

    def test_absolute_path_inside_root_is_resolved(self, tmp_path):
        target = tmp_path / "test.txt"
        result = _resolve_file_path(str(target))
        assert result == str(target.resolve())

    def test_absolute_path_outside_roots_is_rejected(self, tmp_path):
        with pytest.raises(PathEscapeError):
            _resolve_file_path("/definitely/not/a/granted/root.txt")

    def test_relative_path_resolves_from_primary(self, tmp_path):
        result = _resolve_file_path("subdir/file.txt")
        assert result == str((tmp_path / "subdir" / "file.txt").resolve())

    def test_dotdot_escaping_is_rejected(self, tmp_path):
        depth = len(tmp_path.resolve().parts)
        escape = "/".join([".."] * (depth + 2)) + "/escaped.txt"
        with pytest.raises(PathEscapeError):
            _resolve_file_path(escape)

    def test_workspace_fallback_to_working_dir(self):
        """With no context at all, resolution falls back to WORKING_DIR."""
        _clear_project_context()
        result = _resolve_file_path("file.txt")
        assert result.endswith("file.txt")


class TestMultiRootResolution:
    """Multi-root semantics at the tool layer."""

    @pytest.fixture()
    def two_roots(self, tmp_path):
        primary = (tmp_path / "main").resolve()
        extra = (tmp_path / "extra").resolve()
        primary.mkdir()
        extra.mkdir()
        set_current_workspace_dir(tmp_path.resolve())
        set_current_project_dir(primary)
        set_current_project_dirs(
            (
                ResolvedProjectDir(path=primary, exists=True),
                ResolvedProjectDir(path=extra, exists=True),
            ),
        )
        return primary, extra

    def test_absolute_path_in_extra_root_is_allowed(self, two_roots):
        _, extra = two_roots
        result = _resolve_file_path(str(extra / "file.txt"))
        assert result == str(extra / "file.txt")

    def test_relative_path_resolves_from_primary_only(self, two_roots):
        primary, extra = two_roots
        # Even when the same-named file exists in the extra root, a
        # relative path lands in the primary.
        (extra / "file.txt").write_text("extra")
        result = _resolve_file_path("file.txt")
        assert result == str(primary / "file.txt")

    def test_dotdot_reaching_extra_root_is_legitimate(self, two_roots):
        _, extra = two_roots
        result = _resolve_file_path(f"../{extra.name}/file.txt")
        assert result == str(extra / "file.txt")


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
        assert "hello world" in result.content[0].text

    @pytest.mark.asyncio
    async def test_safe_read_uses_one_binary_snapshot(self, tmp_path):
        """Safe reads strip a BOM and tolerate invalid trailing bytes."""
        path = tmp_path / "snapshot.txt"
        path.write_bytes(b"\xef\xbb\xbfhello\xff")

        assert await read_file_safe(str(path)) == "hello"

    @pytest.mark.asyncio
    async def test_safe_read_normalizes_platform_newlines(self, tmp_path):
        """Binary snapshots retain text-mode universal newline behavior."""
        path = tmp_path / "newlines.txt"
        path.write_bytes(b"first\r\nsecond\rthird\n")

        assert await read_file_safe(str(path)) == "first\nsecond\nthird\n"

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
    async def test_write_new_file(self, tmp_path):
        f = tmp_path / "new.txt"
        result = await write_file(str(f), "hello")
        assert "Wrote" in result.content[0].text
        # .txt uses utf-8-sig which adds BOM
        assert f.read_text(encoding="utf-8-sig") == "hello"
        if os.name != "nt":
            assert stat.S_IMODE(f.stat().st_mode) == 0o644

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
    async def test_edit_replaces_text(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world", encoding="utf-8")
        result = await edit_file(str(f), "hello", "goodbye")
        assert "Successfully replaced" in result.content[0].text
        assert f.read_text(encoding="utf-8-sig") == "goodbye world"

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
    async def test_append_to_existing(self, tmp_path):
        f = tmp_path / "append.txt"
        f.write_text("line1\n", encoding="utf-8")
        result = await append_file(str(f), "line2\n")
        assert "Appended" in result.content[0].text
        assert f.read_text(encoding="utf-8") == "line1\nline2\n"

    @pytest.mark.asyncio
    async def test_append_creates_new_file(self, tmp_path):
        f = tmp_path / "new_append.txt"
        result = await append_file(str(f), "first line")
        assert "Appended" in result.content[0].text
        assert f.read_text(encoding="utf-8-sig") == "first line"

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

        def delayed_append(file_path, content, encoding):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)
            with open(file_path, "a", encoding=encoding) as handle:
                handle.write(content)
            with guard:
                active -= 1

        with patch(
            "qwenpaw.utils.io_utils._append_text",
            delayed_append,
        ):
            await asyncio.gather(
                *(append_file(str(f), f"{index}\n") for index in range(8)),
            )

        assert max_active == 1
        assert len(f.read_text(encoding="utf-8-sig").splitlines()) == 8
