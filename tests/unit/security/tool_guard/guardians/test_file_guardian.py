# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Tests for file_guardian path-sensitive file guard.

Target: src/qwenpaw/security/tool_guard/guardians/file_guardian.py
Goal: push coverage from 38% to 78%+.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.security.tool_guard.guardians.file_guardian import (
    FilePathToolGuardian,
    _extract_paths_from_shell_command,
    _looks_like_path_token,
    _normalize_path,
    ensure_file_guard_paths,
)
from qwenpaw.security.tool_guard.models import GuardFinding, GuardSeverity

# Short alias for the long module path used in patch() calls
_FG_MOD = "qwenpaw.security.tool_guard.guardians.file_guardian"


# ---------------------------------------------------------------------------
# Pure-function tests: _looks_like_path_token
# ---------------------------------------------------------------------------


class TestLooksLikePathToken:
    """Heuristic that decides if a shell token looks like a file path."""

    @pytest.mark.parametrize(
        "token, expected",
        [
            # Empty / whitespace-ish
            ("", False),
            # Flags
            ("-la", False),
            ("--verbose", False),
            ("-rf", False),
            ("--output=file", False),
            # URLs
            ("http://example.com", False),
            ("https://example.com/path", False),
            ("ftp://files.example.com", False),
            ("data:text/plain;base64,AA==", False),
            # MIME-type-like
            ("text/plain", False),
            ("application/json", False),
            ("image/png", False),
            ("audio/mp3", False),
            ("video/mp4", False),
            # Paths: starting indicators
            ("~/docs", True),
            ("/etc/passwd", True),
            ("./relative", True),
            ("../parent", True),
            # Paths: contains slash
            ("src/main.py", True),
            # Bare words (not paths, not flags)
            ("echo", False),
            ("cat", False),
            ("hello", False),
            # Single slash (edge)
            ("/", True),
        ],
    )
    def test_parametrized(self, token: str, expected: bool):
        assert _looks_like_path_token(token) is expected


# ---------------------------------------------------------------------------
# Pure-function tests: _extract_paths_from_shell_command
# ---------------------------------------------------------------------------


class TestExtractPathsFromShellCommand:
    """Extract candidate file paths from shell command strings."""

    def test_simple_command(self):
        result = _extract_paths_from_shell_command("cat /etc/passwd")
        assert result == ["/etc/passwd"]

    def test_redirect_separate(self):
        # Bare tokens like "input.txt" lack path indicators (no /, ~, etc.)
        # and are NOT detected by the heuristic. Use path-like tokens instead.
        result = _extract_paths_from_shell_command(
            "cat ./input.txt > /tmp/output.txt",
        )
        assert "./input.txt" in result
        assert "/tmp/output.txt" in result

    def test_redirect_bare_filename_not_detected(self):
        # Bare filenames without path indicators are not extracted.
        result = _extract_paths_from_shell_command(
            "cat input.txt > output.txt",
        )
        # Neither "input.txt" nor "output.txt" look like paths.
        assert not result

    def test_redirect_attached(self):
        result = _extract_paths_from_shell_command(
            "cat ./input.txt >/tmp/output.txt",
        )
        assert "./input.txt" in result
        assert "/tmp/output.txt" in result

    def test_redirect_fd_attached(self):
        result = _extract_paths_from_shell_command("cmd 2>/tmp/err.log")
        assert "/tmp/err.log" in result

    def test_redirect_append(self):
        result = _extract_paths_from_shell_command("echo hi >>/tmp/log.txt")
        assert "/tmp/log.txt" in result

    def test_redirect_fd_append(self):
        result = _extract_paths_from_shell_command("cmd 2>>/tmp/err.log")
        assert "/tmp/err.log" in result

    def test_redirect_and_stdout(self):
        result = _extract_paths_from_shell_command("cmd &>/tmp/all.log")
        assert "/tmp/all.log" in result

    def test_redirect_and_append(self):
        result = _extract_paths_from_shell_command("cmd &>>/tmp/all.log")
        assert "/tmp/all.log" in result

    def test_input_redirect(self):
        result = _extract_paths_from_shell_command("sort </tmp/input.txt")
        assert "/tmp/input.txt" in result

    def test_heredoc_not_path(self):
        # << introduces a heredoc; "EOF" is the delimiter, not a path.
        result = _extract_paths_from_shell_command("cat <<EOF")
        assert not result

    def test_pipe_tokens_not_paths(self):
        # "grep" and "pattern" are bare words; only /var/log/syslog is a path.
        result = _extract_paths_from_shell_command(
            "cat /var/log/syslog | grep error",
        )
        assert "/var/log/syslog" in result
        assert "grep" not in result
        assert "error" not in result

    def test_quoted_path_with_path_indicator(self):
        # Quoted path with slash inside is detected.
        result = _extract_paths_from_shell_command('cat "/tmp/my file.txt"')
        assert "/tmp/my file.txt" in result

    def test_quoted_bare_name_not_detected(self):
        # Bare name without path indicator is not detected, even if quoted.
        result = _extract_paths_from_shell_command('cat "my file.txt"')
        assert not result

    def test_malformed_quotes_fallback(self):
        # Mismatched quotes cause shlex.split to fail; fallback to split().
        result = _extract_paths_from_shell_command(
            'cat "unclosed quote /tmp/file',
        )
        # Fallback split still picks up /tmp/file if it's a separate token.
        # With a single token after split, we get
        # the whole string as one token.
        # The key thing: no exception raised.
        assert isinstance(result, list)

    def test_duplicate_paths_deduped(self):
        result = _extract_paths_from_shell_command("cat /etc/hosts /etc/hosts")
        assert result.count("/etc/hosts") == 1

    def test_flags_not_extracted(self):
        result = _extract_paths_from_shell_command("ls -la /tmp")
        assert "/tmp" in result
        assert "-la" not in result

    def test_empty_command(self):
        assert not _extract_paths_from_shell_command("")

    def test_only_flags(self):
        assert not _extract_paths_from_shell_command("ls -la")


# ---------------------------------------------------------------------------
# Pure-function tests: ensure_file_guard_paths
# ---------------------------------------------------------------------------


class TestEnsureFileGuardPaths:
    """Merge paths with compat secret dirs, de-duplicate."""

    def test_empty_input_returns_compat_dirs(self):
        result = ensure_file_guard_paths([])
        assert len(result) > 0
        # Every _COMPAT_SECRET_DIRS entry must be present.
        from qwenpaw.security.tool_guard.guardians.file_guardian import (
            _COMPAT_SECRET_DIRS,
        )

        for d in _COMPAT_SECRET_DIRS:
            assert d in result

    def test_deduplication(self):
        from qwenpaw.security.tool_guard.guardians.file_guardian import (
            _COMPAT_SECRET_DIRS,
        )

        duplicate = _COMPAT_SECRET_DIRS[0]
        result = ensure_file_guard_paths([duplicate])
        assert result.count(duplicate) == 1

    def test_preserves_order(self):
        result = ensure_file_guard_paths(["/first", "/second"])
        # User paths come before compat dirs.
        assert result[0] == "/first"
        assert result[1] == "/second"

    def test_filters_empty_strings(self):
        result = ensure_file_guard_paths(["", "/valid", ""])
        assert "" not in result
        assert "/valid" in result

    def test_merge_with_existing_paths(self):
        result = ensure_file_guard_paths(["/custom/secret"])
        assert "/custom/secret" in result
        # Also contains the compat dirs.
        assert len(result) > 1


# ---------------------------------------------------------------------------
# _normalize_path
# ---------------------------------------------------------------------------


class TestNormalizePath:
    """Path normalization: expanduser, resolve relative via workspace root."""

    def test_absolute_unchanged(self, tmp_path: Path):
        with patch(
            f"{_FG_MOD}._workspace_root",
            return_value=tmp_path,
        ):
            result = _normalize_path("/etc/passwd")
            assert result.endswith("/etc/passwd")

    def test_relative_resolved(self, tmp_path: Path):
        with patch(
            f"{_FG_MOD}._workspace_root",
            return_value=tmp_path,
        ):
            result = _normalize_path("sub/file.txt")
            # _normalize_path returns forward-slash + lowercase on
            # Windows, so compare against the normalized workspace root.
            normalized_root = _normalize_path(str(tmp_path))
            assert normalized_root in result

    def test_tilde_expanded(self, tmp_path: Path):
        with patch(
            f"{_FG_MOD}._workspace_root",
            return_value=tmp_path,
        ):
            result = _normalize_path("~/myfile")
            assert "~" not in result
            assert "myfile" in result


# ---------------------------------------------------------------------------
# Fixtures for FilePathToolGuardian tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_guard_enabled():
    with patch(
        f"{_FG_MOD}._is_file_guard_enabled",
        return_value=True,
    ):
        yield


@pytest.fixture
def mock_no_sensitive_files():
    with patch(
        f"{_FG_MOD}._load_sensitive_files_from_config",
        return_value=[],
    ):
        yield


@pytest.fixture
def guardian(tmp_path, mock_guard_enabled, mock_no_sensitive_files):
    with patch(
        f"{_FG_MOD}._workspace_root",
        return_value=tmp_path,
    ):
        g = FilePathToolGuardian()
        yield g


@pytest.fixture
def disabled_guardian(tmp_path, mock_no_sensitive_files):
    with patch(
        f"{_FG_MOD}._is_file_guard_enabled",
        return_value=False,
    ), patch(
        f"{_FG_MOD}._workspace_root",
        return_value=tmp_path,
    ):
        g = FilePathToolGuardian()
        yield g


# ---------------------------------------------------------------------------
# FilePathToolGuardian tests
# ---------------------------------------------------------------------------


class TestFilePathToolGuardianInit:
    """__init__, enabled state, sensitive_files property."""

    def test_init_enabled_by_default(self, guardian):
        assert guardian._enabled is True

    def test_init_disabled(self, disabled_guardian):
        assert disabled_guardian._enabled is False

    def test_init_name(self, guardian):
        assert guardian.name == "file_path_tool_guardian"

    def test_init_always_run(self, guardian):
        assert guardian.always_run is True

    def test_sensitive_files_property_returns_copy(self, guardian):
        guardian.add_sensitive_file("/tmp/secret.key")
        first = guardian.sensitive_files
        second = guardian.sensitive_files
        assert first == second
        assert first is not second

    def test_init_with_sensitive_files_kwarg(
        self,
        tmp_path,
        mock_guard_enabled,
        mock_no_sensitive_files,
    ):
        sensitive_path = str(tmp_path / "creds.pem")
        Path(sensitive_path).touch()
        with patch(
            f"{_FG_MOD}._workspace_root",
            return_value=tmp_path,
        ):
            g = FilePathToolGuardian(sensitive_files=[sensitive_path])
        assert any("creds.pem" in p for p in g.sensitive_files)


class TestSetSensitiveFiles:
    """set_sensitive_files replaces the entire sensitive set."""

    def test_replaces_existing(self, guardian, tmp_path):
        path1 = str(tmp_path / "a.key")
        Path(path1).touch()
        path2 = str(tmp_path / "b.key")
        Path(path2).touch()
        guardian.add_sensitive_file(path1)
        guardian.set_sensitive_files([path2])
        assert path1 not in guardian.sensitive_files
        assert any("b.key" in p for p in guardian.sensitive_files)

    def test_directory_path_goes_to_dirs(self, guardian, tmp_path):
        dir_path = str(tmp_path / "secrets")
        Path(dir_path).mkdir()
        guardian.set_sensitive_files([dir_path])
        # The normalized dir should be in sensitive_files
        # (the combined property).
        assert any("secrets" in p for p in guardian.sensitive_files)
        # Internally stored in _sensitive_dirs, not _sensitive_files.
        norm = _normalize_path(dir_path)
        assert norm in guardian._sensitive_dirs
        assert norm not in guardian._sensitive_files

    def test_trailing_slash_treated_as_dir(self, guardian, tmp_path):
        # A path ending with "/" is treated as a directory even if it
        # doesn't exist on disk.
        dir_path = str(tmp_path / "nonexistent") + "/"
        guardian.set_sensitive_files([dir_path])
        norm = _normalize_path(dir_path.rstrip("/"))
        assert norm in guardian._sensitive_dirs

    def test_empty_strings_skipped(self, guardian):
        guardian.set_sensitive_files(["", ""])
        assert len(guardian.sensitive_files) == 0


class TestAddSensitiveFile:
    """add_sensitive_file appends one entry."""

    def test_add_file(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        assert any("secret.key" in p for p in guardian.sensitive_files)

    def test_add_directory(self, guardian, tmp_path):
        dir_path = str(tmp_path / "secrets")
        Path(dir_path).mkdir()
        guardian.add_sensitive_file(dir_path)
        assert any("secrets" in p for p in guardian.sensitive_files)

    def test_add_trailing_slash_as_dir(self, guardian, tmp_path):
        dir_path = str(tmp_path / "maybe_dir") + "/"
        guardian.add_sensitive_file(dir_path)
        norm = _normalize_path(dir_path.rstrip("/"))
        assert norm in guardian._sensitive_dirs

    def test_add_duplicate_is_idempotent(self, guardian, tmp_path):
        path = str(tmp_path / "dup.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        guardian.add_sensitive_file(path)
        count = sum(1 for p in guardian.sensitive_files if "dup.key" in p)
        assert count == 1


class TestRemoveSensitiveFile:
    """remove_sensitive_file returns True if existed, False otherwise."""

    def test_remove_existing_file(self, guardian, tmp_path):
        path = str(tmp_path / "removeme.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        assert guardian.remove_sensitive_file(path) is True

    def test_remove_nonexistent(self, guardian):
        assert guardian.remove_sensitive_file("/nothing/here") is False

    def test_remove_directory(self, guardian, tmp_path):
        dir_path = str(tmp_path / "secretdir")
        Path(dir_path).mkdir()
        guardian.add_sensitive_file(dir_path)
        assert guardian.remove_sensitive_file(dir_path) is True
        assert dir_path not in guardian._sensitive_dirs


class TestIsSensitive:
    """_is_sensitive checks file match and directory prefix match."""

    def test_file_match(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        norm = _normalize_path(path)
        assert guardian._is_sensitive(norm) is True

    def test_directory_prefix_match(self, guardian, tmp_path):
        dir_path = str(tmp_path / "secrets")
        Path(dir_path).mkdir()
        guardian.add_sensitive_file(dir_path)
        child = str(Path(dir_path) / "deep" / "file.txt")
        # _is_sensitive expects a normalized path (lowercase, forward
        # slashes on Windows), so normalize before checking.
        normalized_child = _normalize_path(child)
        assert guardian._is_sensitive(normalized_child) is True

    def test_no_match(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        assert guardian._is_sensitive("/tmp/safe.txt") is False

    def test_empty_sensitive_sets(self, guardian):
        assert guardian._is_sensitive("/any/path") is False


class TestGuard:
    """guard() returns findings for sensitive paths, empty for safe ones."""

    def test_guard_disabled_returns_empty(self, disabled_guardian):
        findings = disabled_guardian.guard(
            "read_file",
            {"file_path": "/etc/passwd"},
        )
        assert not findings

    def test_guard_no_sensitive_files_returns_empty(self, guardian, tmp_path):
        # Clear all sensitive entries.
        guardian.set_sensitive_files([])
        findings = guardian.guard("read_file", {"file_path": "/any/file"})
        assert not findings

    def test_guard_read_file_sensitive(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        findings = guardian.guard("read_file", {"file_path": path})
        assert len(findings) == 1
        assert findings[0].severity == GuardSeverity.HIGH
        assert findings[0].category.value == "sensitive_file_access"
        assert findings[0].tool_name == "read_file"

    def test_guard_read_file_safe(self, guardian, tmp_path):
        safe_path = str(tmp_path / "safe.txt")
        secret_path = str(tmp_path / "secret.key")
        Path(secret_path).touch()
        guardian.add_sensitive_file(secret_path)
        findings = guardian.guard("read_file", {"file_path": safe_path})
        assert not findings

    def test_guard_write_file_sensitive(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        findings = guardian.guard("write_file", {"file_path": path})
        assert len(findings) == 1

    def test_guard_edit_file_sensitive(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        findings = guardian.guard("edit_file", {"file_path": path})
        assert len(findings) == 1

    def test_guard_execute_shell_command_with_sensitive_path(
        self,
        guardian,
        tmp_path,
    ):
        secret = str(tmp_path / "secret.key")
        Path(secret).touch()
        guardian.add_sensitive_file(secret)
        findings = guardian.guard(
            "execute_shell_command",
            {"command": f"cat {secret}"},
        )
        assert len(findings) >= 1

    def test_guard_execute_shell_command_safe(self, guardian, tmp_path):
        secret = str(tmp_path / "secret.key")
        Path(secret).touch()
        guardian.add_sensitive_file(secret)
        findings = guardian.guard(
            "execute_shell_command",
            {"command": "cat /tmp/safe.txt"},
        )
        assert not findings

    def test_guard_execute_shell_command_empty_command(self, guardian):
        findings = guardian.guard("execute_shell_command", {"command": ""})
        assert not findings

    def test_guard_execute_shell_command_non_string_command(self, guardian):
        findings = guardian.guard("execute_shell_command", {"command": 123})
        assert not findings

    def test_guard_execute_shell_command_missing_command(self, guardian):
        findings = guardian.guard("execute_shell_command", {})
        assert not findings

    def test_guard_unknown_tool_scans_string_params(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        findings = guardian.guard("custom_tool", {"target": path})
        assert len(findings) == 1

    def test_guard_unknown_tool_ignores_non_path_params(self, guardian):
        findings = guardian.guard("custom_tool", {"message": "hello"})
        assert not findings

    def test_guard_unknown_tool_ignores_non_string_params(
        self,
        guardian,
        tmp_path,
    ):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        findings = guardian.guard(
            "custom_tool",
            {"count": 42, "path_list": [path]},
        )
        assert findings == []

    def test_guard_known_tool_empty_param_value(self, guardian):
        findings = guardian.guard("read_file", {"file_path": ""})
        assert not findings

    def test_guard_known_tool_missing_param(self, guardian):
        findings = guardian.guard("read_file", {"other_param": "/tmp/a"})
        assert not findings

    def test_guard_view_text_file_both_params(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        # view_text_file has two path params: file_path and path.
        findings = guardian.guard(
            "view_text_file",
            {"file_path": path, "path": path},
        )
        assert len(findings) == 2

    def test_guard_directory_match_blocks_child(self, guardian, tmp_path):
        dir_path = str(tmp_path / "secrets")
        Path(dir_path).mkdir()
        guardian.add_sensitive_file(dir_path)
        child = str(Path(dir_path) / "nested" / "deep.key")
        findings = guardian.guard("read_file", {"file_path": child})
        assert len(findings) == 1

    def test_guard_finding_metadata_has_resolved_path(
        self,
        guardian,
        tmp_path,
    ):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        findings = guardian.guard("read_file", {"file_path": path})
        assert len(findings) == 1
        assert "resolved_path" in findings[0].metadata


class TestReload:
    """reload() re-reads enabled state and config files."""

    def test_reload_re_enables(self, tmp_path, mock_no_sensitive_files):
        with patch(
            f"{_FG_MOD}._is_file_guard_enabled",
            return_value=False,
        ), patch(
            f"{_FG_MOD}._workspace_root",
            return_value=tmp_path,
        ):
            g = FilePathToolGuardian()
        assert g._enabled is False

        with patch(
            f"{_FG_MOD}._is_file_guard_enabled",
            return_value=True,
        ):
            g.reload()
        assert g._enabled is True

    def test_reload_refreshes_sensitive_files(
        self,
        tmp_path,
        mock_guard_enabled,
    ):
        with patch(
            f"{_FG_MOD}._load_sensitive_files_from_config",
            return_value=[],
        ), patch(
            f"{_FG_MOD}._workspace_root",
            return_value=tmp_path,
        ):
            g = FilePathToolGuardian()
        assert len(g.sensitive_files) == 0

        new_path = str(tmp_path / "from_config.key")
        Path(new_path).touch()
        with patch(
            f"{_FG_MOD}._load_sensitive_files_from_config",
            return_value=[new_path],
        ), patch(
            f"{_FG_MOD}._workspace_root",
            return_value=tmp_path,
        ):
            g.reload()
        assert any("from_config.key" in p for p in g.sensitive_files)


class TestMakeFinding:
    """_make_finding produces a properly structured GuardFinding."""

    def test_finding_fields(self, guardian, tmp_path):
        path = str(tmp_path / "secret.key")
        Path(path).touch()
        guardian.add_sensitive_file(path)
        findings = guardian.guard("read_file", {"file_path": path})
        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, GuardFinding)
        assert f.rule_id == "SENSITIVE_FILE_BLOCK"
        assert f.guardian == "file_path_tool_guardian"
        assert f.tool_name == "read_file"
        assert f.param_name == "file_path"
        assert f.remediation is not None


class TestGuardShellRedirectExtraction:
    """guard() for execute_shell_command exercises redirect extraction."""

    def test_redirect_target_sensitive(self, guardian, tmp_path):
        secret = str(tmp_path / "secret.key")
        Path(secret).touch()
        guardian.add_sensitive_file(secret)
        findings = guardian.guard(
            "execute_shell_command",
            {"command": f"echo data > {secret}"},
        )
        assert len(findings) >= 1

    def test_redirect_input_sensitive(self, guardian, tmp_path):
        secret = str(tmp_path / "secret.key")
        Path(secret).touch()
        guardian.add_sensitive_file(secret)
        findings = guardian.guard(
            "execute_shell_command",
            {"command": f"sort < {secret}"},
        )
        assert len(findings) >= 1
