# -*- coding: utf-8 -*-
"""Regression tests for literal tilde tokens in deep path inspection."""

import os
from pathlib import Path

import pytest

from qwenpaw.governance.detectors import (
    _normalize_path,
    detect_sensitive_paths,
    run_deep_scan,
)


@pytest.fixture
def unresolved_tilde(monkeypatch):
    """Model shell expansion when a named home cannot be resolved."""
    original = os.path.expanduser

    def expand(path):
        if path.startswith(("~,", "~qwenpaw_missing_user/")):
            return path
        return original(path)

    monkeypatch.setattr(os.path, "expanduser", expand)


@pytest.mark.parametrize("token", ["~,", "~qwenpaw_missing_user/file"])
def test_unresolved_tilde_is_a_literal_path(token, unresolved_tilde):
    assert _normalize_path(token) == str((Path.cwd() / token).resolve())


def test_resolved_home_still_expands():
    assert _normalize_path("~/scan-test") == str(
        (Path.home() / "scan-test").resolve(),
    )


def test_heredoc_literal_does_not_abort_scan(tmp_path, unresolved_tilde):
    command = "python3 - <<'PY'\nvalues = ['x', '~', 'y']\nPY"
    findings = detect_sensitive_paths(
        tool_name="Bash",
        target=command,
        tool_type="shell",
        sensitive_paths=[str(tmp_path / "protected") + "/"],
    )
    assert findings == []


def test_literal_comma_filename_can_still_be_sensitive(unresolved_tilde):
    findings = detect_sensitive_paths(
        tool_name="Read",
        target="~,",
        tool_type="file",
        sensitive_paths=["~,"],
    )
    assert len(findings) == 1
    assert findings[0].matched_pattern == str(
        (Path.cwd() / "~,").resolve(),
    )


def test_other_paths_and_detectors_still_run(tmp_path, unresolved_tilde):
    protected = tmp_path / "protected"
    protected.mkdir()
    findings = run_deep_scan(
        tool_name="Bash",
        target=f"printf '%s' '~,'; cat {protected / 'key'}; echo $(whoami)",
        tool_type="shell",
        sensitive_paths=[str(protected) + "/"],
        detection_rules=[],
        shell_evasion_checks={"command_substitution": True},
    )
    assert any(f.detector == "sensitive_path_detector" for f in findings)
    assert any(f.detector == "shell_evasion_detector" for f in findings)
