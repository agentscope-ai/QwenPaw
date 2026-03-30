# -*- coding: utf-8 -*-
from __future__ import annotations

from copaw.config.context import set_current_workspace_dir
from copaw.security.tool_guard.guardians.file_guardian import (
    FilePathToolGuardian,
)


def test_file_guardian_blocks_sensitive_file(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    set_current_workspace_dir(repo_root)
    try:
        guardian = FilePathToolGuardian(sensitive_files=["config.env"])

        findings = guardian.guard("read_file", {"file_path": "config.env"})

        assert len(findings) == 1
        assert findings[0].matched_value == "config.env"
    finally:
        set_current_workspace_dir(None)


def test_file_guardian_blocks_sensitive_directory_descendants(
    tmp_path,
) -> None:
    repo_root = tmp_path / "repo"
    set_current_workspace_dir(repo_root)
    try:
        guardian = FilePathToolGuardian(sensitive_files=["secrets/"])

        findings = guardian.guard(
            "read_file",
            {"file_path": "secrets/token.txt"},
        )

        assert len(findings) == 1
        assert findings[0].param_name == "file_path"
    finally:
        set_current_workspace_dir(None)


def test_file_guardian_keeps_shell_path_extraction(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    set_current_workspace_dir(repo_root)
    try:
        guardian = FilePathToolGuardian(sensitive_files=["secrets/"])

        findings = guardian.guard(
            "execute_shell_command",
            {"command": "cat notes.txt > secrets/out.txt"},
        )

        assert len(findings) == 1
        assert findings[0].param_name == "command"
    finally:
        set_current_workspace_dir(None)
