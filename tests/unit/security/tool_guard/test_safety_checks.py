# -*- coding: utf-8 -*-
"""Tests for shared safety check primitives."""
from __future__ import annotations

import pytest

from qwenpaw.security.tool_guard.safety_checks import (
    is_command_destructive,
    is_path_outside_boundary,
)


class TestIsCommandDestructive:
    """Verify destructive command pattern matching."""

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -r --recursive /home/user",
            "rm --recursive ~",
            "rm -rf *",
            "mkfs.ext4 /dev/sda1",
            "mke2fs /dev/sdb",
            "dd if=/dev/zero of=/dev/sda",
            "shutdown now",
            "reboot",
            "halt",
            "poweroff",
            ": () { : | : & } ; :",
        ],
    )
    def test_blocks_known_dangerous_commands(self, command: str) -> None:
        assert is_command_destructive(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "echo hello",
            "cat README.md",
            "git status",
            "python3 script.py",
            "rm file.txt",
            "rm -f single_file.log",
            "mkdir new_dir",
        ],
    )
    def test_allows_safe_commands(self, command: str) -> None:
        assert is_command_destructive(command) is False

    def test_case_insensitive_matching(self) -> None:
        assert is_command_destructive("SHUTDOWN now") is True
        assert is_command_destructive("ReBoot") is True
        assert is_command_destructive("RM -RF /") is True


class TestIsPathOutsideBoundary:
    """Verify path boundary checking."""

    def test_path_inside_cwd(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary("subdir/file.txt", cwd) is False
        assert (
            is_path_outside_boundary(str(tmp_path / "file.txt"), cwd) is False
        )

    def test_path_outside_cwd(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary("/etc/passwd", cwd) is True
        assert is_path_outside_boundary("/tmp/outside", cwd) is True

    def test_relative_path_resolved_inside(self, tmp_path) -> None:
        cwd = str(tmp_path)
        subdir = tmp_path / "sub"
        subdir.mkdir()
        assert is_path_outside_boundary("sub/../file.txt", cwd) is False

    def test_relative_path_traversal_outside(self, tmp_path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        assert is_path_outside_boundary("../outside.txt", str(inner)) is True

    def test_tilde_expansion(self, tmp_path) -> None:
        # ~ expands to home dir which is almost certainly outside tmp_path
        cwd = str(tmp_path)
        assert is_path_outside_boundary("~/some_file", cwd) is True

    def test_sibling_directory_bypass_blocked(self, tmp_path) -> None:
        """A sibling whose name shares a prefix must NOT pass the check.

        String-prefix matching (``startswith``) would incorrectly allow
        ``/tmp/project_evil/file`` when cwd is ``/tmp/project`` because
        the string starts with the cwd prefix.  ``is_relative_to``
        handles this correctly.
        """
        project = tmp_path / "project"
        project.mkdir()
        evil = tmp_path / "project_evil"
        evil.mkdir()
        target = evil / "secret.txt"
        target.touch()
        assert is_path_outside_boundary(str(target), str(project)) is True

    def test_exact_cwd_path_is_inside(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary(cwd, cwd) is False

    def test_nonexistent_path_inside_cwd(self, tmp_path) -> None:
        assert is_path_outside_boundary("nonexistent", str(tmp_path)) is False
