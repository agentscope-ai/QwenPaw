# -*- coding: utf-8 -*-
"""Unit tests for FileSystemAdapter and convenience functions."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from copaw.fs_backend.adapter import FileSystemAdapter
from copaw.fs_backend.fs_backend import OperationResult


# ── adapter initialization ────────────────────────────────────────────


def test_adapter_singleton():
    """FileSystemAdapter is a singleton."""
    # Reset for test isolation
    FileSystemAdapter._instance = None
    FileSystemAdapter._initialized = False

    a = FileSystemAdapter()
    b = FileSystemAdapter()
    assert a is b

    # Cleanup
    FileSystemAdapter._instance = None
    FileSystemAdapter._initialized = False


def test_initialize_local():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()
    adapter.initialize(use_cloud=False)

    assert adapter.is_cloud is False
    assert adapter.sandbox is None


def test_initialize_cloud_requires_sandbox():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    with pytest.raises(ValueError, match="Sandbox instance is required"):
        adapter.initialize(use_cloud=True, sandbox=None)


def test_initialize_cloud_with_sandbox():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    fake_sandbox = MagicMock()
    adapter.initialize(use_cloud=True, sandbox=fake_sandbox)

    assert adapter.is_cloud is True
    assert adapter.sandbox is fake_sandbox


# ── adapter delegates to backend ──────────────────────────────────────


async def test_adapter_delegates_read():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    mock_backend = MagicMock()
    mock_backend.read_file = AsyncMock(
        return_value=OperationResult(success=True, data="content"),
    )
    adapter._backend = mock_backend

    result = await adapter.read_file("/test.txt")
    assert result.success
    assert result.data == "content"
    mock_backend.read_file.assert_awaited_once_with("/test.txt")


async def test_adapter_delegates_write():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    mock_backend = MagicMock()
    mock_backend.write_file = AsyncMock(
        return_value=OperationResult(success=True),
    )
    adapter._backend = mock_backend

    result = await adapter.write_file("/test.txt", "data")
    assert result.success
    mock_backend.write_file.assert_awaited_once_with("/test.txt", "data")


async def test_adapter_delegates_delete():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    mock_backend = MagicMock()
    mock_backend.delete_file = AsyncMock(
        return_value=OperationResult(success=True),
    )
    adapter._backend = mock_backend

    result = await adapter.delete_file("/test.txt")
    assert result.success


async def test_adapter_delegates_list_directory():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    mock_backend = MagicMock()
    mock_backend.list_directory = AsyncMock(
        return_value=OperationResult(success=True, data=[]),
    )
    adapter._backend = mock_backend

    result = await adapter.list_directory("/workspace")
    assert result.success
    assert result.data == []


async def test_adapter_delegates_exists():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    mock_backend = MagicMock()
    mock_backend.exists = AsyncMock(
        return_value=OperationResult(success=True, data=True),
    )
    adapter._backend = mock_backend

    result = await adapter.exists("/test.txt")
    assert result.success
    assert result.data is True


async def test_adapter_delegates_move():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    mock_backend = MagicMock()
    mock_backend.move_file = AsyncMock(
        return_value=OperationResult(success=True),
    )
    adapter._backend = mock_backend

    result = await adapter.move_file("/a.txt", "/b.txt")
    assert result.success


async def test_adapter_delegates_search():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    mock_backend = MagicMock()
    mock_backend.search_files = AsyncMock(
        return_value=OperationResult(success=True, data=["/a.py"]),
    )
    adapter._backend = mock_backend

    result = await adapter.search_files("/workspace", "*.py")
    assert result.success
    assert result.data == ["/a.py"]


async def test_adapter_close():
    adapter = FileSystemAdapter.__new__(FileSystemAdapter)
    adapter._initialized = False
    adapter.__init__()

    mock_backend = MagicMock()
    mock_backend.close = AsyncMock()
    adapter._backend = mock_backend

    await adapter.close()
    mock_backend.close.assert_awaited_once()
    assert adapter._backend is None


# ── convenience functions (edit_file / append_file) ───────────────────


async def test_edit_file_replaces_text(tmp_path):
    """edit_file reads, replaces, and writes back."""
    from copaw.fs_backend import adapter as adapter_mod

    # Use a real local backend for this integration-style test
    file_path = str(tmp_path / "edit_me.txt")
    Path(file_path).write_text("hello world", encoding="utf-8")

    # Create a fresh adapter on local mode
    a = FileSystemAdapter.__new__(FileSystemAdapter)
    a._initialized = False
    a.__init__()
    a.initialize(use_cloud=False)
    a._backend.working_dir = tmp_path

    # Monkey-patch the module-level _adapter
    old_adapter = adapter_mod._adapter
    adapter_mod._adapter = a
    try:
        result = await adapter_mod.edit_file(file_path, "world", "copaw")
        assert result.success
        assert Path(file_path).read_text() == "hello copaw"
    finally:
        adapter_mod._adapter = old_adapter


async def test_edit_file_text_not_found(tmp_path):
    from copaw.fs_backend import adapter as adapter_mod

    file_path = str(tmp_path / "no_match.txt")
    Path(file_path).write_text("abc", encoding="utf-8")

    a = FileSystemAdapter.__new__(FileSystemAdapter)
    a._initialized = False
    a.__init__()
    a.initialize(use_cloud=False)
    a._backend.working_dir = tmp_path

    old_adapter = adapter_mod._adapter
    adapter_mod._adapter = a
    try:
        result = await adapter_mod.edit_file(file_path, "xyz", "replaced")
        assert not result.success
        assert "not found" in result.error_message.lower()
    finally:
        adapter_mod._adapter = old_adapter
