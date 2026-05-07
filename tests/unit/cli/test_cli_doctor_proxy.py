# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import sys
from typing import Any

import click
import pytest

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


def test_fetch_running_server_python_bypasses_env_for_loopback(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_get(_url: str, **kwargs):
        captured.update(kwargs)
        return _Response(
            json_data={
                "python_environment": "test-env",
                "python_executable": sys.executable,
            },
        )

    monkeypatch.setattr(doctor_cmd.httpx, "get", _fake_get)

    env, exe, note = doctor_cmd._fetch_running_server_python(
        "http://127.1.2.3:8088",
        2.0,
    )

    assert env == "test-env"
    assert exe == sys.executable
    assert note is None
    assert captured["trust_env"] is False


def test_run_doctor_checks_uses_proxy_aware_helper_for_api_probes(
    monkeypatch,
) -> None:
    requested_urls: list[str] = []

    def _fake_http_get(url: str, **_kwargs):
        requested_urls.append(url)
        if url.endswith("/api/doctor/runtime"):
            return _Response(
                json_data={
                    "python_environment": "test-env",
                    "python_executable": sys.executable,
                },
            )
        if url.endswith("/api/version"):
            return _Response(json_data={"version": "test"})
        if url.endswith("/"):
            return _Response(
                text="<!doctype html><html></html>",
                content_type="text/html",
            )
        return _Response()

    def _unexpected_direct_get(*_args, **_kwargs):
        raise AssertionError("doctor API probes must use _http_get")

    async def _fake_active_llm(_timeout: float, _deep: bool):
        return True, "skip", []

    monkeypatch.setattr(doctor_cmd.httpx, "get", _unexpected_direct_get)
    monkeypatch.setattr(doctor_cmd, "_http_get", _fake_http_get)
    monkeypatch.setattr(
        doctor_cmd,
        "environment_summary_lines",
        lambda **_: [],
    )
    monkeypatch.setattr(
        doctor_cmd,
        "_doctor_server_python_mismatch_note",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        doctor_cmd,
        "strict_validate_config_file",
        lambda: (False, "skip config for proxy test"),
    )
    monkeypatch.setattr(doctor_cmd, "load_raw_config_dict", lambda: None)
    monkeypatch.setattr(
        doctor_cmd,
        "browser_automation_notes",
        lambda _cfg: [],
    )
    monkeypatch.setattr(doctor_cmd, "_check_working_dir", lambda: (True, "ok"))
    monkeypatch.setattr(
        doctor_cmd,
        "check_app_log_writable",
        lambda: (True, "ok"),
    )
    monkeypatch.setattr(
        doctor_cmd,
        "_check_console_static_files",
        lambda: (True, "ok"),
    )
    monkeypatch.setattr(
        doctor_cmd,
        "console_static_diagnostic_notes",
        lambda: [],
    )
    monkeypatch.setattr(
        doctor_cmd,
        "_check_web_auth",
        lambda _base: (True, "ok"),
    )
    monkeypatch.setattr(doctor_cmd, "_check_active_llm", _fake_active_llm)

    ctx = click.Context(
        click.Command("doctor"),
        obj={"host": "127.1.2.3", "port": 8088},
    )

    with pytest.raises(SystemExit):
        doctor_cmd.run_doctor_checks(
            ctx,
            timeout=2.0,
            llm_timeout=2.0,
            deep=False,
        )

    assert requested_urls == [
        "http://127.1.2.3:8088/api/doctor/runtime",
        "http://127.1.2.3:8088/api/agent/health",
        "http://127.1.2.3:8088/api/version",
        "http://127.1.2.3:8088/",
    ]
