# -*- coding: utf-8 -*-
"""Unit tests for OpenSandboxFileSystemBackend.

All OpenSandbox SDK calls are mocked — no real sandbox is needed.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from copaw.fs_backend.opensandbox_backend import OpenSandboxFileSystemBackend


# ── helpers ───────────────────────────────────────────────────────────


def _entry_info(path, mode=0o100644, size=42, is_dir=False):
    """Create a fake EntryInfo-like object."""
    if is_dir:
        mode = 0o40755
    return SimpleNamespace(
        path=path,
        mode=mode,
        size=size,
        owner="root",
        group="root",
        modified_at=datetime(2025, 1, 1, 0, 0, 0),
        created_at=datetime(2025, 1, 1, 0, 0, 0),
    )


def _make_sandbox():
    """Build a mock sandbox with .files and .commands services."""
    sandbox = MagicMock()
    sandbox.files = MagicMock()
    sandbox.commands = MagicMock()
    return sandbox


# ── read_file ─────────────────────────────────────────────────────────


async def test_read_file_success():
    sandbox = _make_sandbox()
    sandbox.files.read_file = AsyncMock(return_value="file content")

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.read_file("/workspace/test.txt")

    assert result.success
    assert result.data == "file content"
    sandbox.files.read_file.assert_awaited_once_with("/workspace/test.txt")


async def test_read_file_error():
    sandbox = _make_sandbox()
    sandbox.files.read_file = AsyncMock(side_effect=Exception("not found"))

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.read_file("/workspace/missing.txt")

    assert not result.success
    assert "not found" in result.error_message


# ── write_file ────────────────────────────────────────────────────────


async def test_write_file_success():
    sandbox = _make_sandbox()
    sandbox.files.write_file = AsyncMock(return_value=None)

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.write_file("/workspace/out.txt", "hello")

    assert result.success
    sandbox.files.write_file.assert_awaited_once_with(
        "/workspace/out.txt", "hello",
    )


async def test_write_file_error():
    sandbox = _make_sandbox()
    sandbox.files.write_file = AsyncMock(side_effect=IOError("disk full"))

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.write_file("/workspace/out.txt", "data")

    assert not result.success
    assert "disk full" in result.error_message


# ── delete_file ───────────────────────────────────────────────────────


async def test_delete_file_success():
    sandbox = _make_sandbox()
    sandbox.files.delete_files = AsyncMock(return_value=None)

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.delete_file("/workspace/gone.txt")

    assert result.success
    sandbox.files.delete_files.assert_awaited_once_with(["/workspace/gone.txt"])


async def test_delete_file_error():
    sandbox = _make_sandbox()
    sandbox.files.delete_files = AsyncMock(side_effect=Exception("perm denied"))

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.delete_file("/root/secret")

    assert not result.success
    assert "perm denied" in result.error_message


# ── create_directory ──────────────────────────────────────────────────


async def test_create_directory_success(monkeypatch):
    sandbox = _make_sandbox()
    sandbox.files.create_directories = AsyncMock(return_value=None)

    # Mock the WriteEntry import inside the method
    fake_write_entry = MagicMock()
    monkeypatch.setattr(
        "copaw.fs_backend.opensandbox_backend.OpenSandboxFileSystemBackend"
        ".__module__",
        "copaw.fs_backend.opensandbox_backend",
    )

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.create_directory("/workspace/newdir")

    assert result.success


# ── list_directory ────────────────────────────────────────────────────


async def test_list_directory_success():
    sandbox = _make_sandbox()
    entries = [
        _entry_info("/workspace/file.py", size=100),
        _entry_info("/workspace/subdir", is_dir=True),
    ]
    sandbox.files.search = AsyncMock(return_value=entries)

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.list_directory("/workspace")

    assert result.success
    assert len(result.data) == 2

    file_entry = next(fi for fi in result.data if fi.name == "file.py")
    assert not file_entry.is_directory
    assert file_entry.size == 100

    dir_entry = next(fi for fi in result.data if fi.name == "subdir")
    assert dir_entry.is_directory


async def test_list_directory_error():
    sandbox = _make_sandbox()
    sandbox.files.search = AsyncMock(side_effect=Exception("timeout"))

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.list_directory("/workspace")

    assert not result.success
    assert "timeout" in result.error_message


# ── get_file_info ─────────────────────────────────────────────────────


async def test_get_file_info_exists():
    sandbox = _make_sandbox()
    entry = _entry_info("/workspace/info.txt", size=256)
    sandbox.files.get_file_info = AsyncMock(
        return_value={"/workspace/info.txt": entry},
    )

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.get_file_info("/workspace/info.txt")

    assert result.success
    assert result.data.exists is True
    assert result.data.name == "info.txt"
    assert result.data.size == 256
    assert result.data.is_directory is False


async def test_get_file_info_not_found():
    sandbox = _make_sandbox()
    sandbox.files.get_file_info = AsyncMock(return_value={})

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.get_file_info("/workspace/nope.txt")

    assert result.success
    assert result.data.exists is False


async def test_get_file_info_exception_returns_not_exists():
    sandbox = _make_sandbox()
    sandbox.files.get_file_info = AsyncMock(side_effect=Exception("boom"))

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.get_file_info("/workspace/err.txt")

    assert result.success
    assert result.data.exists is False


# ── exists ────────────────────────────────────────────────────────────


async def test_exists_true():
    sandbox = _make_sandbox()
    entry = _entry_info("/workspace/yes.txt")
    sandbox.files.get_file_info = AsyncMock(
        return_value={"/workspace/yes.txt": entry},
    )

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.exists("/workspace/yes.txt")

    assert result.success
    assert result.data is True


async def test_exists_false():
    sandbox = _make_sandbox()
    sandbox.files.get_file_info = AsyncMock(return_value={})

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.exists("/workspace/no.txt")

    assert result.success
    assert result.data is False


# ── move_file ─────────────────────────────────────────────────────────


async def test_move_file_success():
    sandbox = _make_sandbox()
    sandbox.files.move_files = AsyncMock(return_value=None)

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.move_file("/workspace/a.txt", "/workspace/b.txt")

    assert result.success


async def test_move_file_error():
    sandbox = _make_sandbox()
    sandbox.files.move_files = AsyncMock(side_effect=Exception("conflict"))

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.move_file("/workspace/a.txt", "/workspace/b.txt")

    assert not result.success
    assert "conflict" in result.error_message


# ── search_files ──────────────────────────────────────────────────────


async def test_search_files_success():
    sandbox = _make_sandbox()
    entries = [
        _entry_info("/workspace/foo.py"),
        _entry_info("/workspace/sub/bar.py"),
    ]
    sandbox.files.search = AsyncMock(return_value=entries)

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.search_files("/workspace", "*.py")

    assert result.success
    assert result.data == ["/workspace/foo.py", "/workspace/sub/bar.py"]


async def test_search_files_empty():
    sandbox = _make_sandbox()
    sandbox.files.search = AsyncMock(return_value=[])

    backend = OpenSandboxFileSystemBackend(sandbox)
    result = await backend.search_files("/workspace", "*.rs")

    assert result.success
    assert result.data == []


# ── close ─────────────────────────────────────────────────────────────


async def test_close():
    sandbox = _make_sandbox()
    backend = OpenSandboxFileSystemBackend(sandbox)
    await backend.close()  # should not raise
    assert backend._watchers == []
