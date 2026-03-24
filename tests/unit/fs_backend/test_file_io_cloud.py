# -*- coding: utf-8 -*-
"""Unit tests for cloud-aware file I/O tools (file_io.py, file_search.py, send_file.py)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from copaw.fs_backend.fs_backend import OperationResult, FileInfo
from copaw.agents.tools.file_io import (
    _is_cloud_mode,
    _resolve_file_path,
    _file_exists,
    _is_file,
    _read_content,
    _write_content,
    _append_content,
    read_file,
    write_file,
    edit_file,
    append_file,
)


def _get_text(resp) -> str:
    """Extract text from ToolResponse content."""
    item = resp.content[0]
    if isinstance(item, dict):
        return item["text"]
    return item.text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cloud_adapter(backend=None):
    """Create a mock FileSystemAdapter in cloud mode."""
    adapter = MagicMock()
    adapter.is_cloud = True
    adapter._backend = backend or MagicMock()
    adapter.sandbox = MagicMock()
    return adapter


def _make_local_adapter():
    """Create a mock FileSystemAdapter in local mode."""
    adapter = MagicMock()
    adapter.is_cloud = False
    adapter._backend = MagicMock()
    return adapter


# ---------------------------------------------------------------------------
# _is_cloud_mode tests
# ---------------------------------------------------------------------------


class TestIsCloudMode:
    def test_cloud_mode_true(self):
        adapter = _make_cloud_adapter()
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            assert _is_cloud_mode() is True

    def test_cloud_mode_false_when_local(self):
        adapter = _make_local_adapter()
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            assert _is_cloud_mode() is False

    def test_cloud_mode_false_on_exception(self):
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter",
            side_effect=Exception("not initialized"),
        ):
            assert _is_cloud_mode() is False

    def test_cloud_mode_false_when_backend_is_none(self):
        adapter = MagicMock()
        adapter.is_cloud = True
        adapter._backend = None
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            assert _is_cloud_mode() is False


# ---------------------------------------------------------------------------
# _resolve_file_path tests
# ---------------------------------------------------------------------------


class TestResolveFilePath:
    def test_absolute_path_in_cloud(self):
        adapter = _make_cloud_adapter()
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            assert _resolve_file_path("/etc/config.json") == "/etc/config.json"

    def test_relative_path_in_cloud(self):
        adapter = _make_cloud_adapter()
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            result = _resolve_file_path("src/main.py")
            assert result == "/workspace/src/main.py"

    def test_relative_path_local_mode(self):
        adapter = _make_local_adapter()
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            # Should use local WORKING_DIR logic
            result = _resolve_file_path("/tmp/test.txt")
            assert result == "/tmp/test.txt"


# ---------------------------------------------------------------------------
# Cloud I/O helper tests
# ---------------------------------------------------------------------------


class TestCloudIOHelpers:
    @pytest.mark.asyncio
    async def test_file_exists_cloud_true(self):
        adapter = _make_cloud_adapter()
        adapter.exists = AsyncMock(
            return_value=OperationResult(success=True, data=True)
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            result = await _file_exists("/workspace/test.py")
            assert result is True

    @pytest.mark.asyncio
    async def test_file_exists_cloud_false(self):
        adapter = _make_cloud_adapter()
        adapter.exists = AsyncMock(
            return_value=OperationResult(success=True, data=False)
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            result = await _file_exists("/workspace/nonexistent.py")
            assert result is False

    @pytest.mark.asyncio
    async def test_is_file_cloud(self):
        adapter = _make_cloud_adapter()
        adapter.get_file_info = AsyncMock(
            return_value=OperationResult(
                success=True,
                data=FileInfo(
                    name="test.py",
                    path="/workspace/test.py",
                    is_directory=False,
                    exists=True,
                ),
            )
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            result = await _is_file("/workspace/test.py")
            assert result is True

    @pytest.mark.asyncio
    async def test_is_file_cloud_directory(self):
        adapter = _make_cloud_adapter()
        adapter.get_file_info = AsyncMock(
            return_value=OperationResult(
                success=True,
                data=FileInfo(
                    name="src",
                    path="/workspace/src",
                    is_directory=True,
                    exists=True,
                ),
            )
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            result = await _is_file("/workspace/src")
            assert result is False

    @pytest.mark.asyncio
    async def test_read_content_cloud(self):
        adapter = _make_cloud_adapter()
        adapter.read_file = AsyncMock(
            return_value=OperationResult(success=True, data="hello cloud")
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            content = await _read_content("/workspace/test.txt")
            assert content == "hello cloud"

    @pytest.mark.asyncio
    async def test_read_content_cloud_failure(self):
        adapter = _make_cloud_adapter()
        adapter.read_file = AsyncMock(
            return_value=OperationResult(
                success=False, error_message="File not found"
            )
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            with pytest.raises(IOError, match="File not found"):
                await _read_content("/workspace/missing.txt")

    @pytest.mark.asyncio
    async def test_write_content_cloud(self):
        adapter = _make_cloud_adapter()
        adapter.write_file = AsyncMock(
            return_value=OperationResult(success=True)
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            await _write_content("/workspace/out.txt", "content")
            adapter.write_file.assert_awaited_once_with(
                "/workspace/out.txt", "content"
            )

    @pytest.mark.asyncio
    async def test_append_content_cloud(self):
        adapter = _make_cloud_adapter()
        adapter.read_file = AsyncMock(
            return_value=OperationResult(success=True, data="existing ")
        )
        adapter.write_file = AsyncMock(
            return_value=OperationResult(success=True)
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ):
            await _append_content("/workspace/log.txt", "new data")
            adapter.write_file.assert_awaited_once_with(
                "/workspace/log.txt", "existing new data"
            )


# ---------------------------------------------------------------------------
# Tool-level cloud tests
# ---------------------------------------------------------------------------


class TestReadFileCloud:
    @pytest.mark.asyncio
    async def test_read_file_cloud_success(self):
        adapter = _make_cloud_adapter()
        adapter.exists = AsyncMock(
            return_value=OperationResult(success=True, data=True)
        )
        adapter.get_file_info = AsyncMock(
            return_value=OperationResult(
                success=True,
                data=FileInfo(
                    name="test.py",
                    path="/workspace/test.py",
                    is_directory=False,
                    exists=True,
                ),
            )
        )
        adapter.read_file = AsyncMock(
            return_value=OperationResult(
                success=True, data="line1\nline2\nline3"
            )
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            resp = await read_file("/workspace/test.py")
            text = _get_text(resp)
            assert "line1" in text
            assert "line2" in text

    @pytest.mark.asyncio
    async def test_read_file_cloud_with_line_range(self):
        adapter = _make_cloud_adapter()
        adapter.exists = AsyncMock(
            return_value=OperationResult(success=True, data=True)
        )
        adapter.get_file_info = AsyncMock(
            return_value=OperationResult(
                success=True,
                data=FileInfo(
                    name="test.py",
                    path="/workspace/test.py",
                    is_directory=False,
                    exists=True,
                ),
            )
        )
        adapter.read_file = AsyncMock(
            return_value=OperationResult(
                success=True, data="line1\nline2\nline3\nline4\nline5"
            )
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            resp = await read_file("/workspace/test.py", start_line=2, end_line=3)
            text = _get_text(resp)
            assert "line2" in text
            assert "line3" in text

    @pytest.mark.asyncio
    async def test_read_file_cloud_not_found(self):
        adapter = _make_cloud_adapter()
        adapter.exists = AsyncMock(
            return_value=OperationResult(success=True, data=False)
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            resp = await read_file("/workspace/missing.txt")
            text = _get_text(resp)
            assert "does not exist" in text


class TestWriteFileCloud:
    @pytest.mark.asyncio
    async def test_write_file_cloud_success(self):
        adapter = _make_cloud_adapter()
        adapter.write_file = AsyncMock(
            return_value=OperationResult(success=True)
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            resp = await write_file("/workspace/out.txt", "hello")
            text = _get_text(resp)
            assert "Wrote" in text
            assert "5" in text  # 5 bytes

    @pytest.mark.asyncio
    async def test_write_file_cloud_failure(self):
        adapter = _make_cloud_adapter()
        adapter.write_file = AsyncMock(
            return_value=OperationResult(
                success=False, error_message="Permission denied"
            )
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            resp = await write_file("/workspace/out.txt", "hello")
            text = _get_text(resp)
            assert "Error" in text


class TestEditFileCloud:
    @pytest.mark.asyncio
    async def test_edit_file_cloud_success(self):
        adapter = _make_cloud_adapter()
        adapter.exists = AsyncMock(
            return_value=OperationResult(success=True, data=True)
        )
        adapter.get_file_info = AsyncMock(
            return_value=OperationResult(
                success=True,
                data=FileInfo(
                    name="config.json",
                    path="/workspace/config.json",
                    is_directory=False,
                    exists=True,
                ),
            )
        )
        adapter.read_file = AsyncMock(
            return_value=OperationResult(
                success=True, data='{"key": "old_value"}'
            )
        )
        adapter.write_file = AsyncMock(
            return_value=OperationResult(success=True)
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            resp = await edit_file(
                "/workspace/config.json", "old_value", "new_value"
            )
            text = _get_text(resp)
            assert "Successfully replaced" in text

            # Verify the written content
            written = adapter.write_file.call_args[0][1]
            assert "new_value" in written
            assert "old_value" not in written

    @pytest.mark.asyncio
    async def test_edit_file_cloud_text_not_found(self):
        adapter = _make_cloud_adapter()
        adapter.exists = AsyncMock(
            return_value=OperationResult(success=True, data=True)
        )
        adapter.get_file_info = AsyncMock(
            return_value=OperationResult(
                success=True,
                data=FileInfo(
                    name="test.txt",
                    path="/workspace/test.txt",
                    is_directory=False,
                    exists=True,
                ),
            )
        )
        adapter.read_file = AsyncMock(
            return_value=OperationResult(success=True, data="abc def")
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            resp = await edit_file("/workspace/test.txt", "xyz", "123")
            text = _get_text(resp)
            assert "not found" in text


class TestAppendFileCloud:
    @pytest.mark.asyncio
    async def test_append_file_cloud_success(self):
        adapter = _make_cloud_adapter()
        adapter.read_file = AsyncMock(
            return_value=OperationResult(success=True, data="existing ")
        )
        adapter.write_file = AsyncMock(
            return_value=OperationResult(success=True)
        )
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter", return_value=adapter
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            resp = await append_file("/workspace/log.txt", "new line")
            text = _get_text(resp)
            assert "Appended" in text

            # Verify concatenation
            written = adapter.write_file.call_args[0][1]
            assert written == "existing new line"
