import sys
import types
from pathlib import Path

import pytest


def _install_google_genai_stub() -> None:
    google_module = sys.modules.setdefault("google", types.ModuleType("google"))

    genai_module = sys.modules.get("google.genai")
    if genai_module is None:
        genai_module = types.ModuleType("google.genai")
        sys.modules["google.genai"] = genai_module

    errors_module = sys.modules.get("google.genai.errors")
    if errors_module is None:
        errors_module = types.ModuleType("google.genai.errors")

        class APIError(Exception):
            pass

        errors_module.APIError = APIError
        sys.modules["google.genai.errors"] = errors_module

    types_module = sys.modules.get("google.genai.types")
    if types_module is None:
        types_module = types.ModuleType("google.genai.types")

        class HttpOptions:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        types_module.HttpOptions = HttpOptions
        sys.modules["google.genai.types"] = types_module

    if not hasattr(genai_module, "Client"):
        class Client:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        genai_module.Client = Client

    genai_module.errors = errors_module
    genai_module.types = types_module
    google_module.genai = genai_module


_install_google_genai_stub()

from copaw.security.tool_guard.engine import ToolGuardEngine
from copaw.security.tool_guard.guardians import file_guardian
from copaw.security.tool_guard.guardians.file_guardian import (
    FilePathToolGuardian,
    _extract_paths_from_shell_command,
)


@pytest.fixture()
def workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


def test_extract_paths_supports_windows_style_shell_access() -> None:
    read_paths = _extract_paths_from_shell_command(
        'Get-Content "C:\\Users\\alice\\.ssh\\id_rsa"',
    )
    assert "C:\\Users\\alice\\.ssh\\id_rsa" in read_paths

    relative_paths = _extract_paths_from_shell_command('type .\\secret.txt')
    assert ".\\secret.txt" in relative_paths

    parent_paths = _extract_paths_from_shell_command('type ..\\secret.txt')
    assert "..\\secret.txt" in parent_paths

    redirect_paths = _extract_paths_from_shell_command(
        'echo hello > "C:\\Users\\alice\\.ssh\\note.txt"',
    )
    assert "C:\\Users\\alice\\.ssh\\note.txt" in redirect_paths

    drive_relative_paths = _extract_paths_from_shell_command("type C:secret.txt")
    assert "C:secret.txt" in drive_relative_paths


def test_extract_paths_scans_flags_and_multiple_shell_file_targets() -> None:
    flagged_paths = _extract_paths_from_shell_command(
        "cat -n ./secret.txt ../more.txt",
    )
    assert "./secret.txt" in flagged_paths
    assert "../more.txt" in flagged_paths

    copy_paths = _extract_paths_from_shell_command(
        "cp ./source.txt ../protected/target.txt",
    )
    assert "./source.txt" in copy_paths
    assert "../protected/target.txt" in copy_paths


def test_file_guard_blocks_sensitive_shell_reads(
    workspace_root: Path,
) -> None:
    sensitive_dir = workspace_root / "protected"
    sensitive_dir.mkdir()
    guardian = FilePathToolGuardian(sensitive_files=[str(sensitive_dir) + "/"])

    command = f'Get-Content "{sensitive_dir / "secret.txt"}"'
    findings = guardian.guard("execute_shell_command", {"command": command})

    assert len(findings) == 1
    assert findings[0].rule_id == "SENSITIVE_FILE_BLOCK"
    assert findings[0].matched_value == str(sensitive_dir / "secret.txt")


def test_file_guard_blocks_sensitive_shell_redirect_writes(
    workspace_root: Path,
) -> None:
    sensitive_dir = workspace_root / "protected"
    sensitive_dir.mkdir()
    guardian = FilePathToolGuardian(sensitive_files=[str(sensitive_dir) + "/"])

    command = f'echo hello > "{sensitive_dir / "note.txt"}"'
    findings = guardian.guard("execute_shell_command", {"command": command})

    assert len(findings) == 1
    assert findings[0].matched_value == str(sensitive_dir / "note.txt")


def test_file_guard_allows_workspace_shell_reads(
    workspace_root: Path,
) -> None:
    allowed_file = workspace_root / "notes.txt"
    guardian = FilePathToolGuardian(
        sensitive_files=[str(workspace_root / "protected") + "/"],
    )

    findings = guardian.guard(
        "execute_shell_command",
        {"command": f'type "{allowed_file}"'},
    )

    assert findings == []


def test_file_guard_blocks_sensitive_file_tools(
    workspace_root: Path,
) -> None:
    sensitive_dir = workspace_root / "protected"
    sensitive_dir.mkdir()
    sensitive_file = sensitive_dir / "secret.txt"
    guardian = FilePathToolGuardian(sensitive_files=[str(sensitive_dir) + "/"])

    findings = guardian.guard("read_file", {"file_path": str(sensitive_file)})

    assert len(findings) == 1
    assert findings[0].matched_value == str(sensitive_file)


def test_engine_default_guardians_cover_shell_file_access(
    workspace_root: Path,
) -> None:
    sensitive_dir = workspace_root / "protected"
    sensitive_dir.mkdir()
    file_guardian._load_sensitive_files_from_config = lambda: [
        str(sensitive_dir) + "/",
    ]
    engine = ToolGuardEngine()

    assert "file_path_tool_guardian" in engine.guardian_names

    result = engine.guard(
        "execute_shell_command",
        {"command": f'type "{sensitive_dir / "secret.txt"}"'},
    )

    assert result is not None
    assert result.findings_count == 1
    assert result.findings[0].guardian == "file_path_tool_guardian"


def test_file_guard_scans_string_lists_for_unknown_tools(
    workspace_root: Path,
) -> None:
    sensitive_dir = workspace_root / "protected"
    sensitive_dir.mkdir()
    guardian = FilePathToolGuardian(sensitive_files=[str(sensitive_dir) + "/"])

    findings = guardian.guard(
        "custom_batch_tool",
        {
            "targets": [
                str(workspace_root / "notes.txt"),
                str(sensitive_dir / "secret.txt"),
            ],
        },
    )

    assert len(findings) == 1
    assert findings[0].matched_value == str(sensitive_dir / "secret.txt")