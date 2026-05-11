# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from typing import Any

from qwenpaw.cli import doctor_cmd


class _Response:
    def __init__(
        self,
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        text: str = "",
        content_type: str = "application/json",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = {"content-type": content_type}

    def json(self) -> dict[str, Any]:
        return self._json_data


# Doctor uses direct GET probes, so verify they apply the same proxy policy.
def test_doctor_http_get_bypasses_env_for_loopback(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_get(_url: str, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(doctor_cmd.httpx, "get", _fake_get)

    doctor_cmd._http_get("http://127.1.2.3:8088/api/version", timeout=2.0)

    assert captured["trust_env"] is False


def test_doctor_http_get_keeps_env_for_remote_url(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_get(_url: str, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(doctor_cmd.httpx, "get", _fake_get)

    doctor_cmd._http_get("http://192.168.1.10:8088/api/version", timeout=2.0)

    assert captured["trust_env"] is True
