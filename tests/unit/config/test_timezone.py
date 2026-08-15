# -*- coding: utf-8 -*-
"""Tests for system timezone detection."""
# pylint: disable=protected-access

from qwenpaw.config import timezone as timezone_config


def test_probe_env_accepts_utc(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "UTC")

    assert timezone_config._probe_env() == "UTC"


def test_probe_env_normalizes_posix_colon_prefix(monkeypatch) -> None:
    monkeypatch.setenv("TZ", ":America/New_York")

    assert timezone_config._probe_env() == "America/New_York"
