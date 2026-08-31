# -*- coding: utf-8 -*-
"""Tests for daemon command parsing and log-tail helpers.

Covers parse_daemon_query (subcommand/short-alias/dispatch/invalid),
is_daemon_command, and _get_last_lines (file tail with bounded memory),
which previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.runtime.commands import daemon as dm


# ---------------------------------------------------------------------------
# parse_daemon_query
# ---------------------------------------------------------------------------


class TestParseDaemonQuery:
    def test_none_returns_none(self):
        assert dm.parse_daemon_query(None) is None

    def test_empty_returns_none(self):
        assert dm.parse_daemon_query("") is None

    def test_non_string_returns_none(self):
        assert dm.parse_daemon_query(123) is None

    def test_no_slash_returns_none(self):
        assert dm.parse_daemon_query("daemon status") is None

    def test_bare_slash_returns_none(self):
        assert dm.parse_daemon_query("/") is None

    def test_daemon_bare_defaults_to_status(self):
        assert dm.parse_daemon_query("/daemon") == ("status", [])

    def test_daemon_status(self):
        assert dm.parse_daemon_query("/daemon status") == ("status", [])

    def test_daemon_restart(self):
        assert dm.parse_daemon_query("/daemon restart") == ("restart", [])

    def test_daemon_logs_with_args(self):
        assert dm.parse_daemon_query("/daemon logs 50") == ("logs", ["50"])

    def test_daemon_version(self):
        assert dm.parse_daemon_query("/daemon version") == ("version", [])

    def test_reload_underscore_normalized(self):
        assert dm.parse_daemon_query("/daemon reload_config") == (
            "reload-config",
            [],
        )

    def test_reload_contains_reload_maps_to_reload_config(self):
        assert dm.parse_daemon_query("/daemon reload") == (
            "reload-config",
            [],
        )

    def test_unknown_subcommand_returns_none(self):
        assert dm.parse_daemon_query("/daemon unknown") is None

    def test_short_alias_restart(self):
        assert dm.parse_daemon_query("/restart") == ("restart", [])

    def test_short_alias_status(self):
        assert dm.parse_daemon_query("/status") == ("status", [])

    def test_short_alias_version(self):
        assert dm.parse_daemon_query("/version") == ("version", [])

    def test_short_alias_with_args(self):
        assert dm.parse_daemon_query("/logs 20") == ("logs", ["20"])

    def test_case_insensitive(self):
        assert dm.parse_daemon_query("/DAEMON STATUS") == ("status", [])

    def test_leading_whitespace_stripped(self):
        assert dm.parse_daemon_query("  /daemon status") == ("status", [])

    def test_unrelated_command_returns_none(self):
        assert dm.parse_daemon_query("/model") is None
        assert dm.parse_daemon_query("/help") is None


# ---------------------------------------------------------------------------
# is_daemon_command
# ---------------------------------------------------------------------------


class TestIsDaemonCommand:
    def test_valid_commands(self):
        handler = dm.DaemonCommandHandlerMixin()
        assert handler.is_daemon_command("/daemon status") is True
        assert handler.is_daemon_command("/restart") is True
        assert handler.is_daemon_command("/daemon") is True

    def test_invalid_commands(self):
        handler = dm.DaemonCommandHandlerMixin()
        assert handler.is_daemon_command("/model") is False
        assert handler.is_daemon_command("hello") is False
        assert handler.is_daemon_command(None) is False
        assert handler.is_daemon_command("") is False


# ---------------------------------------------------------------------------
# _get_last_lines
# ---------------------------------------------------------------------------


class TestGetLastLines:
    def test_missing_file_message(self, tmp_path):
        result = dm._get_last_lines(tmp_path / "gone.log")
        assert "not found" in result

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.log"
        f.write_text("")
        assert dm._get_last_lines(f) == "(empty)"

    def test_returns_last_n_lines(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("\n".join(f"line{i}" for i in range(10)))
        result = dm._get_last_lines(f, lines=3)
        assert result == "line7\nline8\nline9"

    def test_returns_all_when_fewer_than_n(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("a\nb\nc")
        result = dm._get_last_lines(f, lines=10)
        assert result == "a\nb\nc"

    def test_large_file_bounded_read(self, tmp_path):
        f = tmp_path / "big.log"
        # Write 10KB, but limit read to 1KB
        lines = [f"line{i:05d}" for i in range(1000)]
        f.write_text("\n".join(lines))
        result = dm._get_last_lines(f, lines=5, max_bytes=1024)
        result_lines = result.splitlines()
        assert len(result_lines) == 5
        assert result_lines[-1] == "line00999"

    def test_directory_returns_not_found(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        result = dm._get_last_lines(d)
        assert "not found" in result
