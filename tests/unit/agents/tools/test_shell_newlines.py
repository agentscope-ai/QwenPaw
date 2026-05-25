# -*- coding: utf-8 -*-
"""Tests for shell command newline normalization."""

# pylint: disable=protected-access
import sys

from qwenpaw.agents.tools.shell import _collapse_embedded_newlines


def test_unix_preserves_newlines_for_multi_command_scripts(monkeypatch):
    """Unix shells parse newlines natively as command separators."""
    monkeypatch.setattr(sys, "platform", "linux")

    cmd = "echo A\necho B"

    assert _collapse_embedded_newlines(cmd) == cmd


def test_unix_preserves_heredoc_delimiters(monkeypatch):
    """Heredocs require real newline delimiters and must not be collapsed."""
    monkeypatch.setattr(sys, "platform", "linux")

    cmd = "cat <<'EOF'\nline1\nline2\nEOF"

    assert _collapse_embedded_newlines(cmd) == cmd


def test_unix_preserves_multiline_control_blocks(monkeypatch):
    """Valid multi-line shell blocks should be passed through unchanged."""
    monkeypatch.setattr(sys, "platform", "linux")

    cmd = "for i in 1 2 3; do\n  echo n$i\ndone"

    assert _collapse_embedded_newlines(cmd) == cmd


def test_windows_collapses_newlines(monkeypatch):
    """Keep newline collapsing on Windows for cmd.exe compatibility."""
    monkeypatch.setattr(sys, "platform", "win32")

    cmd = "echo A\necho B"

    assert _collapse_embedded_newlines(cmd) == "echo A echo B"


def test_windows_collapses_carriage_returns(monkeypatch):
    """Also handle carriage-return-only input on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")

    cmd = "echo A\recho B"

    assert _collapse_embedded_newlines(cmd) == "echo A echo B"
