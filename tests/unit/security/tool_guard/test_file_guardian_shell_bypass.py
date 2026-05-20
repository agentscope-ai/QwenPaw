# -*- coding: utf-8 -*-
from collections.abc import Callable
from pathlib import Path

import pytest

from qwenpaw.security.tool_guard.guardians import file_guardian
from qwenpaw.security.tool_guard.guardians.file_guardian import (
    FilePathToolGuardian,
)
from qwenpaw.security.tool_guard.models import GuardFinding


@pytest.fixture(name="workspace_root")
def _workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        file_guardian,
        "get_current_workspace_dir",
        lambda: str(workspace),
    )
    monkeypatch.setattr(file_guardian, "_is_file_guard_enabled", lambda: True)
    monkeypatch.setattr(
        file_guardian,
        "_load_sensitive_files_from_config",
        lambda: [],
    )
    return workspace


def _findings_for(
    command: str,
    sensitive_paths: list[str],
) -> list[GuardFinding]:
    guardian = FilePathToolGuardian(sensitive_files=sensitive_paths)
    return guardian.guard("execute_shell_command", {"command": command})


def test_file_guard_blocks_direct_shell_file_access(
    workspace_root: Path,
) -> None:
    sensitive_dir = workspace_root / "protected"
    sensitive_dir.mkdir()
    sensitive_file = sensitive_dir / "secret.txt"
    sensitive_paths = [str(sensitive_dir) + "/"]

    read_findings = _findings_for(f"cat {sensitive_file}", sensitive_paths)
    write_findings = _findings_for(
        f"echo hello > {sensitive_file}",
        sensitive_paths,
    )

    assert read_findings
    assert write_findings


@pytest.mark.parametrize(
    ("case_name", "command_factory", "sensitive_path_factory"),
    [
        (
            "posix_env_home",
            lambda workspace, home: "cat $HOME/.ssh/id_rsa",
            lambda workspace, home: [str(home / ".ssh") + "/"],
        ),
        (
            "nested_bash_lc",
            lambda workspace, home: (
                f"bash -lc 'cat {workspace / 'protected' / 'secret.txt'}'"
            ),
            lambda workspace, home: [
                str(workspace / "protected") + "/",
            ],
        ),
        (
            "python_inline_open",
            lambda workspace, home: (
                "python -c "
                f"\"open('{workspace / 'protected' / 'secret.txt'}').read()\""
            ),
            lambda workspace, home: [
                str(workspace / "protected") + "/",
            ],
        ),
        (
            "windows_shell_path",
            lambda workspace, home: r"type C:\Users\alice\.ssh\id_rsa",
            lambda workspace, home: [r"C:\Users\alice\.ssh\\"],
        ),
        (
            "powershell_env_userprofile",
            lambda workspace, home: (
                r"powershell -Command "
                r'"Get-Content $env:USERPROFILE\.ssh\id_rsa"'
            ),
            lambda workspace, home: [r"C:\Users\alice\.ssh\\"],
        ),
        (
            "cmd_percent_userprofile",
            lambda workspace, home: (r"cmd /c type %USERPROFILE%\.ssh\id_rsa"),
            lambda workspace, home: [r"C:\Users\alice\.ssh\\"],
        ),
    ],
)
def test_file_guard_blocks_shell_fallback_bypass_patterns(
    case_name: str,
    command_factory: Callable[[Path, Path], str],
    sensitive_path_factory: Callable[[Path, Path], list[str]],
    workspace_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home" / "alice"
    (home / ".ssh").mkdir(parents=True)
    (workspace_root / "protected").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", r"C:\Users\alice")

    command = command_factory(workspace_root, home)
    sensitive_paths = sensitive_path_factory(workspace_root, home)
    findings = _findings_for(command, sensitive_paths)

    assert findings, f"{case_name} was not blocked: {command}"
