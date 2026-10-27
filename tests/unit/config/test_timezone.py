# -*- coding: utf-8 -*-
"""Tests for the timezone probes in ``qwenpaw.config.timezone``."""

from zoneinfo import available_timezones

from qwenpaw.config.timezone import (
    _WIN_TO_IANA,
    _probe_env,
    detect_system_timezone,
    normalize_tz,
)


def test_probe_env_accepts_a_slashless_tz(monkeypatch):
    """Regression #8046: ``TZ=UTC`` (containers, CI) must not be skipped."""
    monkeypatch.setenv("TZ", "UTC")
    assert _probe_env() == "UTC"


def test_probe_env_accepts_an_iana_tz(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    assert _probe_env() == "Asia/Shanghai"


def test_probe_env_ignores_an_invalid_tz(monkeypatch):
    monkeypatch.setenv("TZ", "Mars/Phobos")
    assert _probe_env() is None


def test_detect_system_timezone_honours_a_slashless_tz(monkeypatch):
    """``$TZ`` describes the process, so it wins over the host zone."""
    monkeypatch.setenv("TZ", "UTC")
    assert detect_system_timezone() == "UTC"


def test_win_to_iana_values_are_resolvable():
    """A typo in the table would make the Windows probe return ``None``."""
    valid = available_timezones()
    assert (
        sorted(
            f"{win_name} -> {iana}"
            for win_name, iana in _WIN_TO_IANA.items()
            if iana not in valid
        )
        == []
    )


def test_win_to_iana_values_normalise_to_a_fixpoint():
    """The probe hands the raw CLDR value to ``normalize_tz``, so a value
    that is itself a deprecated link (``America/Godthab``) would otherwise
    reach ``Config.user_timezone`` uncanonicalised."""
    unresolved = {}
    for value in sorted(set(_WIN_TO_IANA.values())):
        once = normalize_tz(value)
        twice = normalize_tz(once) if once is not None else None
        if once is None or twice != once:
            unresolved[value] = (once, twice)
    assert not unresolved


def test_win_to_iana_covers_the_windows_catalogue():
    """Every name Windows 10/11 lists is mapped — including the
    DST-observing ones that used to fall through to the silent ``"UTC"``
    and come back as a whole-offset shift on naive timestamps."""
    assert len(_WIN_TO_IANA) == 141
    for win_name in (
        "Israel Standard Time",
        "Turkey Standard Time",
        "Egypt Standard Time",
        "Iran Standard Time",
        "Central Europe Standard Time",
        "Central European Standard Time",
        "Azores Standard Time",
        "Cuba Standard Time",
        "Newfoundland Standard Time",
        "Tasmania Standard Time",
        "Lord Howe Standard Time",
        "West Bank Standard Time",
        "Middle East Standard Time",
        "Kamchatka Standard Time",
        "Mid-Atlantic Standard Time",
    ):
        assert win_name in _WIN_TO_IANA, win_name
