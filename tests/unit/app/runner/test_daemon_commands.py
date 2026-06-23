# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app.runner.daemon_commands import parse_daemon_query


# ---------------------------------------------------------------------------
# parse_daemon_query
# ---------------------------------------------------------------------------


def test_parse_daemon_status():
    result = parse_daemon_query("/daemon status")
    assert result == ("status", [])


def test_parse_daemon_restart():
    result = parse_daemon_query("/daemon restart")
    assert result == ("restart", [])


def test_parse_daemon_bare_defaults_to_status():
    result = parse_daemon_query("/daemon")
    assert result == ("status", [])


def test_parse_daemon_short_alias():
    result = parse_daemon_query("/restart")
    assert result is not None
    assert result[0] == "restart"


def test_parse_daemon_reload_config():
    result = parse_daemon_query("/daemon reload-config")
    assert result is not None
    assert result[0] == "reload-config"


def test_parse_daemon_reload_alias():
    result = parse_daemon_query("/daemon reloadconfig")
    assert result is not None
    assert result[0] == "reload-config"


def test_parse_daemon_unknown_sub_returns_none():
    assert parse_daemon_query("/daemon bogus") is None


def test_parse_daemon_no_slash_returns_none():
    assert parse_daemon_query("daemon status") is None


def test_parse_daemon_empty_returns_none():
    assert parse_daemon_query("") is None
    assert parse_daemon_query(None) is None
