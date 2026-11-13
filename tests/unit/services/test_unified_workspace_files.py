# -*- coding: utf-8 -*-
"""Tests for unified Files workspace filesystem primitives."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from qwenpaw.services.workspace_files import (
    FileVersionConflict,
    InvalidCursor,
    InvalidWorkspacePath,
    get_file_metadata,
    list_directory,
    read_file_chunk,
    resolve_workspace_path,
    save_text_file,
)


def test_resolve_workspace_path_accepts_portable_relative_path(
    tmp_path: Path,
) -> None:
    """Portable POSIX paths resolve below the workspace root."""
    expected = tmp_path / "src" / "app.py"

    assert resolve_workspace_path(tmp_path, "src/app.py") == expected
    assert resolve_workspace_path(tmp_path, "", allow_root=True) == tmp_path


@pytest.mark.parametrize(
    "api_path",
    [
        "",
        "/etc/passwd",
        "../secret",
        "src/../secret",
        "C:/secret",
        "C:\\secret",
        "\\\\server\\share",
        "folder\\file.txt",
        "folder/",
    ],
)
def test_resolve_workspace_path_rejects_unsafe_paths(
    tmp_path: Path,
    api_path: str,
) -> None:
    """Traversal and non-portable paths are rejected consistently."""
    with pytest.raises(InvalidWorkspacePath):
        resolve_workspace_path(tmp_path, api_path)


@pytest.mark.parametrize(
    "api_path",
    [
        "con.txt",
        "file. ",
    ],
)
def test_portable_creation_rejects_cross_platform_names(
    tmp_path: Path,
    api_path: str,
) -> None:
    """Creation rules remain stricter than lookup of existing files."""
    with pytest.raises(InvalidWorkspacePath):
        resolve_workspace_path(tmp_path, api_path, portable=True)


def test_decomposed_unicode_file_can_be_listed_and_opened(
    tmp_path: Path,
) -> None:
    """A path returned by the directory API must remain addressable."""
    filename = "e\u0301.txt"
    (tmp_path / filename).write_text("content", encoding="utf-8")

    listed = list_directory(tmp_path, "", None, 20)["entries"][0]["path"]

    assert listed == filename
    assert get_file_metadata(tmp_path, listed)["size"] == 7
    assert read_file_chunk(tmp_path, listed, 0, 20)["content"] == "content"


def test_resolve_workspace_path_rejects_symlink_escape(
    tmp_path: Path,
) -> None:
    """A symlink cannot escape the allowed root."""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "outside"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are unavailable")

    with pytest.raises(InvalidWorkspacePath):
        resolve_workspace_path(tmp_path, "outside/secret.txt")


def test_list_directory_is_sorted_paginated_and_non_recursive(
    tmp_path: Path,
) -> None:
    """Directory pages put folders first and expose opaque cursors."""
    (tmp_path / "z-folder").mkdir()
    (tmp_path / "a-folder").mkdir()
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
    (tmp_path / "z-folder" / "nested.txt").write_text(
        "nested",
        encoding="utf-8",
    )

    first = list_directory(tmp_path, "", None, 2)
    second = list_directory(
        tmp_path,
        "",
        first["next_cursor"],
        2,
    )

    assert [entry["name"] for entry in first["entries"]] == [
        "a-folder",
        "z-folder",
    ]
    assert [entry["name"] for entry in second["entries"]] == [
        "a.py",
        "b.txt",
    ]
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert all(entry["name"] != "nested.txt" for entry in second["entries"])


def test_list_directory_rejects_invalid_cursor(tmp_path: Path) -> None:
    """Malformed cursor values fail explicitly."""
    with pytest.raises(InvalidCursor):
        list_directory(tmp_path, "", "not-a-cursor", 20)


def test_metadata_and_utf8_chunk_use_file_versions(tmp_path: Path) -> None:
    """Metadata and chunks agree on ETag and preserve UTF-8 characters."""
    target = tmp_path / "message.txt"
    target.write_text("A你B", encoding="utf-8")

    metadata = get_file_metadata(tmp_path, "message.txt")
    chunk = read_file_chunk(tmp_path, "message.txt", 1, 2)

    assert metadata["preview_kind"] == "text"
    assert metadata["size"] == 5
    assert chunk["content"] == "你"
    assert chunk["offset"] == 1
    assert chunk["next_offset"] == 4
    assert chunk["etag"] == metadata["etag"]
    assert chunk["truncated"] is True


def test_chunk_skips_utf8_continuation_byte(tmp_path: Path) -> None:
    """A range beginning inside a character advances to a valid boundary."""
    (tmp_path / "message.txt").write_text("A你B", encoding="utf-8")

    chunk = read_file_chunk(tmp_path, "message.txt", 2, 3)

    assert chunk["content"] == "B"
    assert chunk["offset"] == 4
    assert chunk["eof"] is True


def test_save_text_file_is_atomic_and_checks_etag(tmp_path: Path) -> None:
    """Writes return a new version and reject stale optimistic updates."""
    target = tmp_path / "notes.md"
    target.write_text("before", encoding="utf-8")
    old_etag = get_file_metadata(tmp_path, "notes.md")["etag"]

    result = save_text_file(
        tmp_path,
        "notes.md",
        "after",
        old_etag,
    )

    assert target.read_text(encoding="utf-8") == "after"
    assert result["etag"] != old_etag
    assert not list(tmp_path.glob(".notes.md.*.qwenpaw.tmp"))
    with pytest.raises(FileVersionConflict):
        save_text_file(tmp_path, "notes.md", "stale", old_etag)


def test_save_rejects_deleted_if_match_target(tmp_path: Path) -> None:
    """A versioned save must not recreate a file deleted by another process."""
    target = tmp_path / "notes.md"
    target.write_text("before", encoding="utf-8")
    old_etag = get_file_metadata(tmp_path, "notes.md")["etag"]
    target.unlink()

    with pytest.raises(FileVersionConflict):
        save_text_file(tmp_path, "notes.md", "stale", old_etag)

    assert not target.exists()


def test_concurrent_versioned_saves_allow_only_one_writer(
    tmp_path: Path,
) -> None:
    """Two server saves cannot both consume the same file version."""
    target = tmp_path / "notes.md"
    target.write_text("before", encoding="utf-8")
    old_etag = get_file_metadata(tmp_path, "notes.md")["etag"]

    def _save(content: str) -> str:
        try:
            save_text_file(tmp_path, "notes.md", content, old_etag)
        except FileVersionConflict:
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(_save, ["first", "second"]))

    assert sorted(results) == ["conflict", "saved"]


def test_save_text_file_supports_shell_metacharacters(
    tmp_path: Path,
) -> None:
    """Valid filenames remain data and are never interpreted by a shell."""
    filename = "safe;$(touch nope).txt"

    save_text_file(tmp_path, filename, "content", None)

    assert (tmp_path / filename).read_text(encoding="utf-8") == "content"
    assert not (tmp_path / "nope").exists()


def test_metadata_rejects_directories(tmp_path: Path) -> None:
    """Metadata endpoints expose regular files only."""
    (tmp_path / "folder").mkdir()

    with pytest.raises(FileNotFoundError):
        get_file_metadata(tmp_path, "folder")


def test_save_replaces_existing_file_on_windows_and_posix(
    tmp_path: Path,
) -> None:
    """The atomic replacement path works with platform-native semantics."""
    target = tmp_path / "replace.txt"
    target.write_text("old", encoding="utf-8")
    original_inode = target.stat().st_ino

    save_text_file(tmp_path, "replace.txt", "new", None)

    assert target.read_text(encoding="utf-8") == "new"
    if os.name != "nt":
        assert target.stat().st_ino != original_inode
