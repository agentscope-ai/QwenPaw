# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from qwenpaw.utils import telemetry
from qwenpaw.desktop_env import DESKTOP_APP_ENV


def test_is_desktop_app_reads_environment(monkeypatch):
    monkeypatch.delenv(DESKTOP_APP_ENV, raising=False)
    assert telemetry._is_desktop_app() is False

    monkeypatch.setenv(DESKTOP_APP_ENV, "1")
    assert telemetry._is_desktop_app() is True

    monkeypatch.setenv(DESKTOP_APP_ENV, "true")
    assert telemetry._is_desktop_app() is True

    monkeypatch.setenv(DESKTOP_APP_ENV, "on")
    assert telemetry._is_desktop_app() is True


def test_desktop_telemetry_skips_upload_without_marker(monkeypatch, tmp_path):
    upload_calls = []
    monkeypatch.setenv(DESKTOP_APP_ENV, "1")
    monkeypatch.setattr(
        telemetry,
        "_upload_telemetry_sync",
        lambda data: upload_calls.append(data) or True,
    )

    assert telemetry.is_telemetry_opted_out(tmp_path) is True
    assert telemetry.collect_and_upload_telemetry(tmp_path) is False
    assert upload_calls == []
    assert not (tmp_path / telemetry.TELEMETRY_MARKER_FILE).exists()
