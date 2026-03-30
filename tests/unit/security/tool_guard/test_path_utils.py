# -*- coding: utf-8 -*-
from __future__ import annotations

from copaw.security.tool_guard.path_utils import (
    is_within_root,
    matches_sensitive_path,
    normalize_guard_path,
)


def test_normalize_guard_path_resolves_relative_path(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    expected = str((repo_root / "README.md").resolve(strict=False))

    assert normalize_guard_path("README.md", repo_root) == expected


def test_is_within_root_rejects_path_traversal(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    escaped = normalize_guard_path("../secret.txt", repo_root)

    assert is_within_root(escaped, repo_root) is False


def test_matches_sensitive_path_supports_directory_guards(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    target = normalize_guard_path("secrets/token.txt", repo_root)

    assert (
        matches_sensitive_path(
            target,
            ["secrets/"],
            base_dir=repo_root,
        )
        is True
    )


def test_windows_paths_are_supported_without_host_os_switch() -> None:
    assert (
        normalize_guard_path(
            r"..\foo.txt",
            r"C:\repo\subdir",
        )
        == r"C:\repo\foo.txt"
    )
    assert is_within_root(r"C:\repo\docs\a.md", r"C:\repo") is True
    assert is_within_root(r"D:\other.txt", r"C:\repo") is False
