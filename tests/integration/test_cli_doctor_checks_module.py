# -*- coding: utf-8 -*-
"""Integration tests for CLI doctor-check helpers.

Covers src/qwenpaw/cli/doctor_checks.py (766 uncovered lines):
log-path writability, unknown config key scanning, raw config
loading, URL sanity, environment summary helpers.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_check_app_log_writable_returns_tuple() -> None:
    """App log writability check returns (bool, message)."""
    from qwenpaw.cli.doctor_checks import check_app_log_writable

    ok, message = check_app_log_writable()
    assert isinstance(ok, bool)
    assert isinstance(message, str)
    assert message


@pytest.mark.integration
@pytest.mark.p1
def test_scan_unknown_config_keys_clean_dict() -> None:
    """A dict with only known root keys reports nothing."""
    from qwenpaw.cli.doctor_checks import scan_unknown_config_keys

    findings = scan_unknown_config_keys({})
    assert not findings


@pytest.mark.integration
@pytest.mark.p1
def test_scan_unknown_config_flags_unknown_top_level() -> None:
    """Unknown top-level keys are reported."""
    from qwenpaw.cli.doctor_checks import scan_unknown_config_keys

    findings = scan_unknown_config_keys({"totally_unknown_key": 1})
    assert any("totally_unknown_key" in f for f in findings)


@pytest.mark.integration
@pytest.mark.p1
def test_scan_unknown_config_flags_unknown_agents_key() -> None:
    """Unknown keys under agents are reported with prefix."""
    from qwenpaw.cli.doctor_checks import scan_unknown_config_keys

    findings = scan_unknown_config_keys({"agents": {"bogus_key": {}}})
    assert any("agents." in f and "bogus_key" in f for f in findings)


@pytest.mark.integration
@pytest.mark.p1
def test_scan_unknown_config_ignores_non_dict_agents() -> None:
    """Non-dict agents value is skipped without error."""
    from qwenpaw.cli.doctor_checks import scan_unknown_config_keys

    findings = scan_unknown_config_keys({"agents": [1, 2]})
    assert isinstance(findings, list)
    assert not any("agents." in f for f in findings)


@pytest.mark.integration
@pytest.mark.p1
def test_load_raw_config_dict_returns_dict_or_none() -> None:
    """Raw config loader returns a dict or None (missing file)."""
    from qwenpaw.cli.doctor_checks import load_raw_config_dict

    result = load_raw_config_dict()
    assert result is None or isinstance(result, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_url_looks_httpish() -> None:
    """HTTP(S) URLs with netloc pass; others fail."""
    from qwenpaw.cli.doctor_checks import _url_looks_httpish

    assert _url_looks_httpish("http://127.0.0.1:8088") is True
    assert _url_looks_httpish("https://example.com/api") is True
    assert _url_looks_httpish("ftp://example.com") is False
    assert _url_looks_httpish("not a url") is False
    assert _url_looks_httpish("http://") is False


@pytest.mark.integration
@pytest.mark.p1
def test_environment_summary_lines_shape() -> None:
    """Environment summary returns a list of strings."""
    from qwenpaw.cli.doctor_checks import environment_summary_lines

    lines = environment_summary_lines()
    assert isinstance(lines, list)
    assert all(isinstance(x, str) for x in lines)
    assert len(lines) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_windows_long_paths_probe_safe_on_any_os() -> None:
    """Windows long-path probe returns a safe tuple off-Windows."""
    from qwenpaw.cli.doctor_checks import _windows_long_paths_enabled

    enabled, _note = _windows_long_paths_enabled()
    # Off-Windows: (None, None) or (bool, str) — must not raise.
    assert enabled is None or isinstance(enabled, bool)


@pytest.mark.integration
@pytest.mark.p1
def test_startup_extra_volume_disk_notes_shape() -> None:
    """Disk notes helper returns a list for any config."""
    from qwenpaw.cli.doctor_checks import startup_extra_volume_disk_notes

    notes = startup_extra_volume_disk_notes(None)
    assert isinstance(notes, list)


@pytest.mark.integration
@pytest.mark.p1
def test_provider_overview_notes_shape() -> None:
    """Provider overview returns a list of strings."""
    from qwenpaw.cli.doctor_checks import provider_overview_notes

    notes = provider_overview_notes()
    assert isinstance(notes, list)
    assert all(isinstance(x, str) for x in notes)
