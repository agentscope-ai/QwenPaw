# -*- coding: utf-8 -*-
"""Tests for the API health probe used by ``qwenpaw doctor``."""
# pylint: disable=protected-access
from __future__ import annotations

from typing import Any

import httpx

from qwenpaw.cli import doctor_cmd


class _Response:
    def __init__(
        self,
        status_code: int,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self) -> dict[str, Any]:
        return self._json_data


def test_api_health_uses_readiness_endpoint(monkeypatch, capsys) -> None:
    response = _Response(200, {"status": "ok"})
    calls: list[tuple[str, dict[str, object]]] = []

    def _fake_get(url: str, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(doctor_cmd, "_http_get", _fake_get)

    ok, actual = doctor_cmd._check_api_health(
        "http://127.0.0.1:8088",
        timeout=2.0,
    )

    assert ok is True
    assert actual is response
    assert calls == [
        ("http://127.0.0.1:8088/api/healthz", {"timeout": 2.0}),
    ]
    captured = capsys.readouterr()
    assert "OK" in captured.out
    assert "/api/healthz, HTTP 200" in captured.out
    assert captured.err == ""


def test_api_health_reports_background_startup(monkeypatch, capsys) -> None:
    response = _Response(
        503,
        {
            "status": "starting",
            "detail": "Background startup in progress",
        },
    )
    monkeypatch.setattr(
        doctor_cmd,
        "_http_get",
        lambda _url, **_kwargs: response,
    )

    ok, actual = doctor_cmd._check_api_health(
        "http://127.0.0.1:8088",
        timeout=2.0,
    )

    assert ok is False
    assert actual is response
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "FAIL" in captured.err
    assert "health not ready" in captured.err
    assert "Background startup in progress" in captured.err
    assert "rerun `qwenpaw doctor`" in captured.err


def test_api_health_reports_connection_failure(monkeypatch, capsys) -> None:
    def _raise_connection_error(_url: str, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        doctor_cmd,
        "_http_get",
        _raise_connection_error,
    )

    ok, response = doctor_cmd._check_api_health(
        "http://127.0.0.1:8088",
        timeout=2.0,
    )

    assert ok is False
    assert response is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "health not reachable" in captured.err
    assert "connection refused" in captured.err
    assert "start the server with `qwenpaw app`" in captured.err
