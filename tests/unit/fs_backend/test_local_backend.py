# -*- coding: utf-8 -*-
"""Unit tests for LocalFileSystemBackend."""

import tempfile
from pathlib import Path

import pytest

from copaw.fs_backend.local_backend import LocalFileSystemBackend


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def backend(tmp_dir):
    return LocalFileSystemBackend(working_dir=tmp_dir)


# ── read / write ──────────────────────────────────────────────────────


async def test_write_and_read_file(backend, tmp_dir):
    result = await backend.write_file(f"{tmp_dir}/hello.txt", "world")
    assert result.success

    result = await backend.read_file(f"{tmp_dir}/hello.txt")
    assert result.success
    assert result.data == "world"


async def test_read_nonexistent_file(backend, tmp_dir):
    result = await backend.read_file(f"{tmp_dir}/no_such_file.txt")
    assert not result.success
    assert "not found" in result.error_message.lower()


async def test_write_creates_parent_dirs(backend, tmp_dir):
    path = f"{tmp_dir}/a/b/c/deep.txt"
    result = await backend.write_file(path, "nested")
    assert result.success
    assert Path(path).read_text() == "nested"


# ── delete ────────────────────────────────────────────────────────────


async def test_delete_file(backend, tmp_dir):
    path = f"{tmp_dir}/to_delete.txt"
    await backend.write_file(path, "bye")
    result = await backend.delete_file(path)
    assert result.success
    assert not Path(path).exists()


async def test_delete_nonexistent(backend, tmp_dir):
    result = await backend.delete_file(f"{tmp_dir}/nope.txt")
    assert not result.success


async def test_delete_directory(backend, tmp_dir):
    dir_path = f"{tmp_dir}/subdir"
    await backend.create_directory(dir_path)
    await backend.write_file(f"{dir_path}/f.txt", "x")
    result = await backend.delete_file(dir_path)
    assert result.success
    assert not Path(dir_path).exists()


# ── directory operations ──────────────────────────────────────────────


async def test_create_directory(backend, tmp_dir):
    result = await backend.create_directory(f"{tmp_dir}/new_dir")
    assert result.success
    assert Path(f"{tmp_dir}/new_dir").is_dir()


async def test_list_directory(backend, tmp_dir):
    await backend.write_file(f"{tmp_dir}/a.txt", "a")
    await backend.write_file(f"{tmp_dir}/b.txt", "b")
    await backend.create_directory(f"{tmp_dir}/sub")

    result = await backend.list_directory(tmp_dir)
    assert result.success
    names = {fi.name for fi in result.data}
    assert "a.txt" in names
    assert "b.txt" in names
    assert "sub" in names

    dirs = {fi.name for fi in result.data if fi.is_directory}
    assert "sub" in dirs


async def test_list_nonexistent_directory(backend, tmp_dir):
    result = await backend.list_directory(f"{tmp_dir}/nope")
    assert not result.success


# ── file info / exists ────────────────────────────────────────────────


async def test_get_file_info_existing(backend, tmp_dir):
    path = f"{tmp_dir}/info_test.txt"
    await backend.write_file(path, "hello")
    result = await backend.get_file_info(path)
    assert result.success
    assert result.data.exists is True
    assert result.data.is_directory is False
    assert result.data.size > 0


async def test_get_file_info_nonexistent(backend, tmp_dir):
    result = await backend.get_file_info(f"{tmp_dir}/missing.txt")
    assert result.success
    assert result.data.exists is False


async def test_exists_true(backend, tmp_dir):
    path = f"{tmp_dir}/exists.txt"
    await backend.write_file(path, "yes")
    result = await backend.exists(path)
    assert result.success
    assert result.data is True


async def test_exists_false(backend, tmp_dir):
    result = await backend.exists(f"{tmp_dir}/nope.txt")
    assert result.success
    assert result.data is False


# ── move ──────────────────────────────────────────────────────────────


async def test_move_file(backend, tmp_dir):
    src = f"{tmp_dir}/src.txt"
    dst = f"{tmp_dir}/dst.txt"
    await backend.write_file(src, "moving")
    result = await backend.move_file(src, dst)
    assert result.success
    assert not Path(src).exists()
    assert Path(dst).read_text() == "moving"


async def test_move_nonexistent(backend, tmp_dir):
    result = await backend.move_file(f"{tmp_dir}/no.txt", f"{tmp_dir}/d.txt")
    assert not result.success


# ── search ────────────────────────────────────────────────────────────


async def test_search_files(backend, tmp_dir):
    await backend.write_file(f"{tmp_dir}/foo.py", "# python")
    await backend.write_file(f"{tmp_dir}/bar.txt", "text")
    await backend.write_file(f"{tmp_dir}/sub/baz.py", "# sub")

    result = await backend.search_files(tmp_dir, "*.py")
    assert result.success
    assert len(result.data) == 2
    assert all(p.endswith(".py") for p in result.data)


# ── close ─────────────────────────────────────────────────────────────


async def test_close(backend):
    await backend.close()  # should not raise
